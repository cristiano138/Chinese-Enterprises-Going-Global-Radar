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
"""

import csv
import json
import os
import sys
import time
import urllib.request
import urllib.error

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


def call_model(prompt, max_tokens=8000, retries=3):
    """调魔搭模型。

    ⚠️ max_tokens 必须给足 8000：
        DeepSeek-V4.1-Flash 是推理模型，实测思考过程可达 10000+ 字符，
        给少了会返回空字符串。
    """
    url = f"{BASE}/chat/completions"
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.2,
    }
    for i in range(retries):
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {TOKEN}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=180) as r:
                d = json.loads(r.read().decode("utf-8"))
            return d["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            body = e.read()[:200].decode("utf-8", "ignore")
            print(f"    [!] HTTP {e.code}: {body}")
            time.sleep(3 * (i + 1))
        except Exception as e:
            print(f"    [!] {type(e).__name__}: {str(e)[:80]}")
            time.sleep(3 * (i + 1))
    return ""


PROMPT_TMPL = """你是跨境电商合规专家。下面是一批官方法规的英文标题。

请为每一条输出：
1. 法规中文名：标准的中文译名（如 "Regulation (EU) 2025/2509" → 《玩具安全条例》）
2. 作用说明：一句话（30 字以内）说明这条法规管什么、卖家要注意什么

严格按下面的格式输出，每条三行，不要用 markdown 表格，不要加解释：
编号|||中文名|||作用说明

法规清单：
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
        # 去掉可能的编号前缀，如 "16 CFR Part 1250"
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
        out = call_model(prompt)
        got = parse(out)
        result.update(got)
        print(f"解析出 {len(got)} 条")
        time.sleep(INTERVAL)

    print()
    print(f"  共拿到 {len(result)} 条翻译（目标 {len(rows)} 条）")
    print()

    # 回填
    hit = 0
    for r in rows:
        key = r["CELEX号"] or r["官方编号"]
        if key in result:
            name, desc = result[key]
            if not r["法规中文名"].strip():
                r["法规中文名"] = name
            # 备注：保留原始技术信息，前面加一句作用说明
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
