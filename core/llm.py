# -*- coding: utf-8 -*-
"""
大模型接入（core/llm.py）

分工铁律（README「AI 与确定性代码的分工」）：
    LLM 只做「理解、归类、摘要、翻译」四件事。
    抓取、URL 校验、引用对齐、缓存去重 —— 全部由确定性代码完成，
    绝不交给概率模型。

因此本模块的定位很窄：
    把**已经确定的**法规数据组织成中文表达，不负责判断「有哪些法规」。
    硬约束：只能使用给定内容，不得补充自行「知道」的法规。

降级设计（README「这套设计的额外好处」）：
    即使模型调用失败或配额耗尽，程序依然能输出原始法规清单
    （只是没有中文润色）—— 演示不会因 API 问题而中断。
"""

import hashlib
import json
import os
import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
CACHE_DIR = os.path.join(PROJECT, "data", "cache")


def _load_env():
    """读取 .env（若存在）。没有 python-dotenv 也不阻塞。"""
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(PROJECT, ".env"), override=True)
    except Exception:
        # 退化为手写解析，保证「没有第三方库也能跑」
        env_path = os.path.join(PROJECT, ".env")
        if os.path.exists(env_path):
            with open(env_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())


_load_env()

TOKEN = os.getenv("MODEL_API_TOKEN", "").strip()
BASE = os.getenv("MODEL_API_BASE", "").strip().rstrip("/")
MODEL = os.getenv("MODEL_NAME", "").strip()

# 明确的「未就绪」标记，供上层做降级判断
READY = bool(TOKEN and BASE and MODEL) and TOKEN != "your_token_here"

_client = None


def is_ready():
    """模型链路是否可用（Token / Base / Model 三项齐全）。"""
    return READY


def config_summary():
    """给界面展示的非敏感配置摘要（**不泄露 Token**）。"""
    return {
        "ready": READY,
        "base": BASE or "（未配置）",
        "model": MODEL or "（未配置）",
        "token": "已配置" if (TOKEN and TOKEN != "your_token_here") else "未配置",
    }


def _client_get():
    global _client
    if _client is None:
        from openai import OpenAI
        _client = OpenAI(api_key=TOKEN, base_url=BASE, timeout=120)
    return _client


# ── 缓存：高频调用结果缓存，省额度、免重复计费（README 2.1.6）──────────
def _cache_path(prompt):
    h = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f"llm_{h}.json")


def _cache_get(prompt):
    p = _cache_path(prompt)
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f).get("text")
        except Exception:
            return None
    return None


def _cache_put(prompt, text):
    try:
        with open(_cache_path(prompt), "w", encoding="utf-8") as f:
            json.dump({"text": text}, f, ensure_ascii=False)
    except Exception:
        pass


def chat(prompt, max_tokens=4000, temperature=0.2, use_cache=True):
    """调用模型。返回 (text, meta)。

    meta 说明调用是否成功、是否命中缓存，供上层如实标注。
    任何异常都不抛出 —— 上层靠 meta 判断并降级。
    """
    if not READY:
        return "", {"ok": False, "reason": "模型链路未配置（缺 Token/Base/Model）",
                    "cached": False}

    if use_cache:
        hit = _cache_get(prompt)
        if hit is not None:
            return hit, {"ok": True, "reason": "", "cached": True}

    try:
        resp = _client_get().chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        text = resp.choices[0].message.content or ""
        if not text.strip():
            # 推理模型 token 给少了的典型症状：返回空
            return "", {"ok": False, "reason": "模型返回空内容（可能 max_tokens 不足）",
                        "cached": False}
        if use_cache:
            _cache_put(prompt, text)
        return text, {"ok": True, "reason": "", "cached": False}
    except Exception as e:
        return "", {"ok": False,
                    "reason": f"{type(e).__name__}: {str(e)[:160]}",
                    "cached": False}


# ── M1 专用提示词 ────────────────────────────────────────────────
M1_PROMPT = """你是跨境电商合规助理。下面给出的是**已经从官方数据库检索到的**
法规条目（编号、官方英文标题、中文名、作用说明、链接、生效日期、现行效力）。

请为每条法规写一段**给卖家看的中文说明**，帮助他快速理解这条法规管什么。

【不可违反的硬约束】
1. 只允许使用下面给出的内容。**不得补充任何你认为「应该还有」的法规**。
2. **不得修改、推断或新增**任何法规编号、日期、链接 —— 这些是事实，一律照抄。
3. 如果某条信息下面没有给出（例如缺日期），就写「官方未标注」，**不要猜**。
4. 语气务实，不用营销腔，不承诺「保证合规」。

【输出格式】
严格每条一行，用 ||| 分隔，不要 markdown 表格，不要加解释：
编号|||一句话卖家提示（40 字以内）

法规条目：
{items}
"""


def build_m1_items(rows):
    """把语料记录拍平成提示词里的条目文本。"""
    lines = []
    for r in rows:
        key = r.get("CELEX号") or r.get("官方编号")
        lines.append(
            f"{key}|||{r.get('法规中文名','')}|||{r.get('官方标题（英文）','')}"
            f"|||{r.get('现行效力','')}|||{r.get('生效日期','') or '官方未标注'}"
        )
    return "\n".join(lines)


def parse_keyed_lines(text):
    """解析「编号|||内容」格式 → {编号: 内容}。"""
    out = {}
    for line in (text or "").splitlines():
        line = line.strip().lstrip("-•* ").strip()
        if "|||" not in line:
            continue
        parts = [p.strip() for p in line.split("|||")]
        if len(parts) < 2:
            continue
        key = parts[0].strip().strip("`* ")
        val = "|||".join(parts[1:]).strip()
        if key and val:
            out[key] = val
    return out


def m1_tips(rows):
    """M1 的可选润色步骤：给每条法规生成一句话卖家提示。

    返回 (tips_dict, meta)。模型不可用时 tips_dict 为空 ——
    上层照常输出原始清单，只是没有这句提示。
    """
    if not rows:
        return {}, {"ok": True, "reason": "无条目", "cached": False}
    prompt = M1_PROMPT.format(items=build_m1_items(rows))
    text, meta = chat(prompt, max_tokens=4000)
    if not meta["ok"]:
        return {}, meta
    return parse_keyed_lines(text), meta
