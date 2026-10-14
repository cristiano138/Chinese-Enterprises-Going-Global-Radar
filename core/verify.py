# -*- coding: utf-8 -*-
"""
引用对齐（core/verify.py）—— 产品的命根子 ⭐

职责（单一且不可砍）：
    逐条校验 LLM 输出是否**回挂官方链接**。
    - 拿不到链接的条目，一律**丢弃**，不输出给用户。
    - 链接必须来自语料库本身，**不接受 LLM 自己生成的任何 URL**。

红线（README + AI 执行手册）：
    ❌ 没有 CELEX 号或 ELI 链接的条目不许输出
    ❌ 链接点不开的条目不许输出
    ✅ 拿不到官方链接的内容一律不输出

本模块是**纯确定性代码**，不联网、不调模型。
"""

import re

# 允许的官方域（README「什么算官方来源」）：
#   · 欧盟：eur-lex.europa.eu（原文）、data.europa.eu（ELI 永久标识）
#   · 美国：ecfr.gov / govinfo.gov / fda.gov / fcc.gov / cpsc.gov / ftc.gov
OFFICIAL_HOSTS = (
    "eur-lex.europa.eu",
    "data.europa.eu",
    "ecfr.gov",
    "govinfo.gov",
    "fda.gov",
    "fcc.gov",
    "cpsc.gov",
    "ftc.gov",
)

_URL_RE = re.compile(r"https?://[^\s<>\)\]\"']+")


def is_official_url(url):
    """判断 URL 是否落在官方域名白名单内。"""
    if not url:
        return False
    u = url.strip().lower()
    if not u.startswith("http://") and not u.startswith("https://"):
        return False
    # 去掉协议部分，取主机名
    host = u.split("//", 1)[1].split("/", 1)[0].split(":", 1)[0]
    return any(host == h or host.endswith("." + h) for h in OFFICIAL_HOSTS)


def official_urls_in(row):
    """取出一条语料记录里所有**合法的官方链接**。

    返回去重后的列表（欧盟条目通常同时有 ELI 标识 + EUR-Lex 原文链接）。
    """
    urls = []
    for field in ("官方链接", "ELI标识"):
        u = (row.get(field) or "").strip()
        if u and is_official_url(u) and u not in urls:
            urls.append(u)
    return urls


def accept(row):
    """判定一条语料记录能否输出给用户。返回 (bool, 原因)。

    这是「无链接不输出」底线的唯一实现点 —— 所有模块都必须过这一关。
    """
    if not row.get("官方链接"):
        return False, "缺官方链接"
    if not is_official_url(row.get("官方链接", "")):
        return False, "链接域名不在官方白名单内"
    if not (row.get("官方编号") or row.get("CELEX号")):
        return False, "缺官方编号与 CELEX 号"
    return True, ""


def filter_rows(rows):
    """批量过滤：返回 (通过的条目, 被丢弃的条目+原因)。"""
    kept, dropped = [], []
    for r in rows:
        ok, why = accept(r)
        if ok:
            kept.append(r)
        else:
            dropped.append((r, why))
    return kept, dropped


def align_output(items, corpus_keys):
    """对齐 LLM 输出与语料库。

    参数：
        items       —— LLM 输出的条目，每条形如 {"key": "...", ...}
                       key 为 CELEX 号或官方编号（语料库里的唯一键）
        corpus_keys —— 允许出现的键集合（必须来自语料库）

    返回：
        aligned   —— 通过校验的条目
        rejected  —— 被拒的条目 + 原因

    这是防幻觉的关键一步：LLM 只要编了一个语料库里不存在的编号，
    在这里就会被拦下 —— 因为 corpus_keys 是**语料库的真实键**。
    """
    aligned, rejected = [], []
    for it in items:
        key = (it.get("key") or "").strip()
        if not key:
            rejected.append((it, "条目缺编号键"))
            continue
        if key not in corpus_keys:
            # ⭐ 这一条就是「32015R1000 在官方数据库中不存在」的拦截点
            rejected.append((it, f"编号 {key} 不在语料库中（疑似幻觉，已拦截）"))
            continue
        aligned.append(it)
    return aligned, rejected


def rate(aligned, total):
    """回挂率：通过校验的条目 / LLM 产出的条目。"""
    if total <= 0:
        return 1.0
    return len(aligned) / total


def find_invented_urls(text, allowed_urls):
    """扫描自由文本里出现的 URL，标出**未被语料库授权**的那些。

    用于自检与演示：直观看到「LLM 有没有自己编链接」。
    """
    found = _URL_RE.findall(text or "")
    invented = [u for u in found if u not in allowed_urls]
    return found, invented
