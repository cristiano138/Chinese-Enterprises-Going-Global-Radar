# -*- coding: utf-8 -*-
"""
批量生成「法规中文名 + 一句话说明」—— 数据线的最后一块。

思路：
    法规骨架（英文标题、编号、链接）已有，缺中文名和作用说明。
    把法规标题**打包成批**发给大模型翻译/概括，比逐条调用省 token。

⚠️ 重要原则：
    AI 只做「翻译 + 概括」这类不需要事实准确性的活。
    法规编号、日期这些**事实**一律用官方数据，绝不让 AI 生成。

输入：
    data/语料核对表_骨架总表.csv
输出：
    data/语料核对表_完整版.csv   （在骨架基础上补齐中文名和说明）

用法：
    python scripts/enrich_cn.py

变更记录（2026-10-14 修复，对应《代码审查报告》问题13）：
    - 原来手写 urllib + 手写重试，与 test_connection.py 用 openai SDK 的风格不一致，
      且 requirements.txt 引入的 tenacity 一直没用上。现统一改用 openai SDK，
      重试交给 tenacity。
    - 修正提示词自相矛盾：原提示词写「每条三行」，但示例格式是一行。
"""

import csv
import os
import sys
import time

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
DATA = os.path.join(PROJECT, "data")

load_dotenv(os.path.join(PROJECT, ".env"), override=True)

TOKEN = os.getenv("MODEL_API_TOKEN", "").strip()
BASE = os.getenv("MODEL_API_BASE", "").strip().rstrip("/")
MODEL = os.getenv("MODEL_NAME", "").strip()

BATCH = 8          # 每批几条（省 token 的平衡点）
INTERVAL = 4       # 批次间隔，避免触发限流

# ── LLM 客户端（统一用 openai SDK + tenacity 重试）──────────────
try:
    from openai import OpenAI
except ImportError:
    print("缺少 openai 库：pip install openai python-dotenv tenacity")
    sys.exit(1)

try:
    from tenacity import retry, stop_after_attempt, wait_exponential
except ImportError:
    # 没有 tenacity 时退化为「只试一次」，不阻塞主流程
    def retry(*a, **k):
        def deco(fn):
            return fn
        return deco

    def stop_after_attempt(*a, **k):
        return None

    def wait_exponential(*a, **k):
        return None

_client = None


def client():
    global _client
    if _client is None:
        _client = OpenAI(api_key=TOKEN, base_url=BASE, timeout=180)
    return _client


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=True)
def call_model(prompt, max_tokens=8000):
    """调模型。

    ⚠️ max_tokens 必须给足 8000：
        推理模型（如 DeepSeek 系列）的思考过程可达 10000+ 字符，
        给少了会返回空字符串。
    """
    resp = client().chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        temperature=0.2,
    )
    return resp.choices[0].message.content or ""


PROMPT_TMPL = """你是跨境电商合规专家。下面是一批官方法规的英文标题。

请为每一条输出：
1. 法规中文名：标准的中文译名（如 "Regulation (EU) 2025/2509" → 《玩具安全条例》）
2. 作用说明：一句话（30 字以内）说明这条法规管什么、卖家要注意什么

严格按下面的格式输出，**每条一行**，不要用 markdown 表格，不要加解释：
编号|||中文名|||作用说明

法规清单（每行：编号|||英文标题）：
{items}
"""


def build_items(batch):
    lines = []
    for r in batch:
        key = r["CELEX号"] or r["官方编号"]
        lines.append(f"{key}|||{r['官方标题（英文）']}")
    return "\n".join(lines)


def parse(out):
    """解析模型输出 → {编号: (中文名, 说明)}。"""
    res = {}
    for line in out.splitlines():
        line = line.strip()
        if "|||" not in line:
            continue
        parts = [p.strip() for p in line.split("|||")]
        if len(parts) < 3:
            continue
        key = parts[0].strip().strip("`* ")
        name = parts[1].strip()
        desc = parts[2].strip()
        if key:
            res[key] = (name, desc)
    return res


def main():
    if not TOKEN or not BASE or not MODEL:
        print("❌ .env 里缺 TOKEN / BASE / MODEL，无法调用模型")
        return

    src = os.path.join(DATA, "语料核对表_骨架总表.csv")
    if not os.path.exists(src):
        print(f"找不到 {src}")
        return

    with open(src, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    print("=" * 70)
    print(f"  批量生成法规中文名 —— 共 {len(rows)} 条，每批 {BATCH} 条")
    print("=" * 70)
    print()

    result = {}
    batches = [rows[i:i + BATCH] for i in range(0, len(rows), BATCH)]

    for bi, batch in enumerate(batches, 1):
        print(f"  批次 {bi}/{len(batches)} ...", end=" ", flush=True)
        prompt = PROMPT_TMPL.format(items=build_items(batch))
        try:
            out = call_model(prompt)
        except Exception as e:
            print(f"失败：{type(e).__name__}: {str(e)[:80]}")
            out = ""
        got = parse(out)
        result.update(got)
        print(f"解析出 {len(got)} 条")
        time.sleep(INTERVAL)

    print()
    print(f"  共拿到 {len(result)} 条翻译（目标 {len(rows)} 条）")
    print()

    # 回填（只补「法规中文名」空值；说明追加到备注最前）
    hit = 0
    for r in rows:
        key = r["CELEX号"] or r["官方编号"]
        if key in result:
            name, desc = result[key]
            if not r["法规中文名"].strip():
                r["法规中文名"] = name
            old = r["备注／问题"].strip()
            r["备注／问题"] = f"{desc}｜{old}" if desc else old
            hit += 1

    print(f"  成功回填 {hit} 条")

    out_csv = os.path.join(DATA, "语料核对表_完整版.csv")
    cols = list(rows[0].keys())
    with open(out_csv, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)

    print(f"  已保存：{out_csv}")
    print("=" * 70)


if __name__ == "__main__":
    main()
