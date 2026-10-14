# -*- coding: utf-8 -*-
"""
语料库（core/corpus.py）—— 把 86 条官方法规读进来，按「类目 + 市场」精确检索。

设计原则（对应 README「技术架构」）：
    语料是「小规模（86 条）+ 强结构化（类目/机构/编号都有标签）」，
    因此**不用向量检索**，直接按标签精确筛选 —— 更准、更快、零成本，
    且结果 100% 可解释（能追到具体是哪一行数据）。

    本模块是**纯确定性代码**：只读 CSV、只做字符串匹配，
    不联网、不调模型 —— 这是产品可信度的地基。

输入：
    data/语料核对表_完整版.csv   （86 条 × 20 列，主底表）
    回退：data/语料核对表_骨架总表.csv

用法：
    from core import corpus
    cat = corpus.load_corpus()          # 载入（带缓存）
    hits = corpus.search("儿童玩具", "欧盟")   # 精确筛选
"""

import csv
import os
import sys
from collections import OrderedDict

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
DATA = os.path.join(PROJECT, "data")

# 优先用「完整版」（含 AI 补齐的中文名），找不到再退回骨架表
CORPUS_FILES = ["语料核对表_完整版.csv", "语料核对表_骨架总表.csv"]

# ── 支持范围（与 README「数据来源与引用规范 · 本期覆盖范围」严格一致）──────
SUPPORTED_MARKETS = OrderedDict([
    ("欧盟", "EU"),
    ("美国", "US"),
])

# 品类 = 5 个行业类目（卖家视角的「我卖什么」）
SUPPORTED_CATEGORIES = [
    "儿童玩具",
    "电子电器",
    "纺织服装",
    "美妆个护",
    "食品接触材料",
]

# 横切维度 —— 不是并列品类，而是「任何品类都要遵守」的维度。
# 这正是设计优点：两个维度覆盖所有品类。
#   标签标识：任何品类都要打标签
#   通用    ：任何消费品都可能被通用法规（如欧盟 GPSR）覆盖
CROSS_CUTTING = ["标签标识", "通用"]

ALL_QUERYABLE = SUPPORTED_CATEGORIES + CROSS_CUTTING

# 每家市场的「通用/横切」法规覆盖面（用于在清单里单列一节，而不是混进品类）
_FLAG_KEY = {"欧盟": "EU", "美国": "US"}


def _read_rows(path):
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def resolve_corpus_path():
    """返回实际可用的语料文件路径。"""
    for name in CORPUS_FILES:
        p = os.path.join(DATA, name)
        if os.path.exists(p):
            return p
    raise FileNotFoundError(
        f"找不到语料文件，已尝试：{CORPUS_FILES}（目录：{DATA}）"
    )


_CACHE = None


def load_corpus(force=False):
    """载入语料（进程内缓存）。返回 list[dict]。"""
    global _CACHE
    if _CACHE is not None and not force:
        return _CACHE

    path = resolve_corpus_path()
    raw = _read_rows(path)

    rows = []
    for r in raw:
        row = {k: (v or "").strip() for k, v in r.items()}
        # 只保留有官方链接的条目 —— 红线：拿不到链接的内容一律不许输出
        if not row.get("官方链接"):
            continue
        row["_source_file"] = os.path.basename(path)
        rows.append(row)

    _CACHE = rows
    return rows


def stats():
    """语料概览：总数、市场分布、品类分布、效力分布。"""
    rows = load_corpus()
    market, category, validity = {}, {}, {}
    for r in rows:
        market[r.get("机构", "")] = market.get(r.get("机构", ""), 0) + 1
        category[r.get("类目", "")] = category.get(r.get("类目", ""), 0) + 1
        validity[r.get("现行效力", "")] = validity.get(r.get("现行效力", ""), 0) + 1
    return {
        "total": len(rows),
        "file": os.path.basename(resolve_corpus_path()),
        "market": market,
        "category": category,
        "validity": validity,
    }


def market_code(market):
    """中文市场名 → 语料里的机构代码（EU / US）。"""
    return SUPPORTED_MARKETS.get((market or "").strip(), "")


def is_supported(category, market):
    """判断「类目 + 市场」是否在支持范围内。返回 (bool, 拒绝原因)。"""
    cat = (category or "").strip()
    mkt = (market or "").strip()

    if mkt not in SUPPORTED_MARKETS:
        return False, (
            f"暂不支持市场「{mkt or '（空）'}」。本期仅覆盖："
            + "、".join(SUPPORTED_MARKETS.keys())
        )
    if cat not in ALL_QUERYABLE:
        return False, (
            f"暂不支持品类「{cat or '（空）'}」。本期仅覆盖："
            + "、".join(ALL_QUERYABLE)
        )
    return True, ""


def search(category, market, include_cross_cutting=True):
    """按「类目 + 市场」精确筛选。

    返回 dict：
        primary   —— 命中该品类的法规（严格按「类目」列匹配）
        cross     —— 横切法规（标签标识 / 通用），所有品类都适用
        market    —— 市场中文名
        category  —— 品类中文名
        code      —— 机构代码 EU / US

    注：横切法规只在查询**行业品类**时附带；若用户直接查「标签标识」
        或「通用」，则它们本身就是 primary，不再重复计入 cross。
    """
    ok, reason = is_supported(category, market)
    if not ok:
        return {"ok": False, "reason": reason,
                "primary": [], "cross": [], "category": category, "market": market}

    code = market_code(market)
    rows = [r for r in load_corpus() if r.get("机构") == code]

    cat = category.strip()

    if cat in CROSS_CUTTING:
        # 直接查横切维度：它自己就是主体
        primary = [r for r in rows if r.get("类目") == cat]
        cross = []
    else:
        primary = [r for r in rows if r.get("类目") == cat]
        cross = []
        if include_cross_cutting:
            cross = [r for r in rows if r.get("类目") in CROSS_CUTTING]

    return {
        "ok": True,
        "reason": "",
        "category": cat,
        "market": market.strip(),
        "code": code,
        "primary": _sort_rows(primary),
        "cross": _sort_rows(cross),
    }


def _validity_rank(row):
    """排序权重：现行有效在前，已废止沉底（但**不隐藏** —— 用户需要知道它已失效）。"""
    v = row.get("现行效力", "")
    if v.startswith("现行有效"):
        return 0
    if v == "待确认":
        return 1
    if v == "已废止":
        return 2
    return 3


def _date_rank(row):
    d = row.get("生效日期", "") or ""
    # 空日期沉底；否则按字符串倒序（ISO 格式可直接比大小）
    return (0, _neg_str(d)) if d else (1, "")


def _neg_str(s):
    # 让 ISO 日期在「升序排序」里表现为最新在前
    return "".join(chr(0x10FFFF - ord(c)) if c.isdigit() else c for c in s)


def _sort_rows(rows):
    return sorted(rows, key=lambda r: (_validity_rank(r), _date_rank(r)))


def row_label(row):
    """给一条法规生成人类可读标签，用于日志/自检。"""
    key = row.get("CELEX号") or row.get("官方编号") or "（无编号）"
    return f"{row.get('机构','')} {key} {row.get('法规中文名','')}"


if __name__ == "__main__":
    s = stats()
    print("=" * 66)
    print("  语料库自检")
    print("=" * 66)
    print(f"  文件：{s['file']}")
    print(f"  总条数：{s['total']}")
    print(f"  市场分布：{s['market']}")
    print(f"  品类分布：{s['category']}")
    print(f"  效力分布：{s['validity']}")
    print()
    for cat in ALL_QUERYABLE:
        for mkt in SUPPORTED_MARKETS:
            res = search(cat, mkt)
            print(f"  {cat:<8} × {mkt}  →  主体 {len(res['primary']):>2} 条"
                  f" + 横切 {len(res['cross']):>2} 条")
    print()
    bad, why = is_supported("汽车配件", "欧盟")
    print(f"  范围外输入测试：汽车配件 × 欧盟 → ok={bad}，{why}")
    print("=" * 66)
