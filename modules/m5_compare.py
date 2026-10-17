# -*- coding: utf-8 -*-
"""M5 · 同品类跨区域法规对比。

只比较已通过官方链接校验的本地语料，不调用模型、不猜测两地法规等效关系。
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)

from core import corpus, verify, snapshot  # noqa: E402


def _records(category, market):
    res = corpus.search(category, market, include_cross_cutting=True)
    if not res.get("ok"):
        return res, []
    kept, dropped = verify.filter_rows(res["primary"] + res["cross"])
    return res, kept


def _key(row):
    return (row.get("官方编号") or row.get("CELEX号") or "").strip()


def _name(row):
    return (row.get("法规中文名") or row.get("官方标题（英文）") or _key(row)).strip()


def _empty(category, markets, reason):
    """失败分支。

    键集必须与成功分支一致（项目内部约定）：早期版本失败时返回的是
    「欧盟独有」「美国独有」两个键、且缺快照/header，调用方按「独有」取值
    就会 KeyError 或读到空 —— 现在两分支共用同一套键。
    """
    market_label = " / ".join(markets) if markets else "（未选市场）"
    return {
        "ok": False, "reason": reason, "品类": category, "市场": markets,
        "区域": [], "共同": [], "独有": {}, "共同数量": 0,
        "快照版本": snapshot.SNAPSHOT_VERSION,
        "数据截止时间": snapshot.DATA_CUTOFF,
        "说明": "",
        "header": snapshot.header(
            category or "（空）", market_label,
            modules={"M5": snapshot.MODULE_ERROR}),
    }


def query(category="儿童玩具", markets=None):
    """返回同一品类在多个市场的法规集合与差异。

    ``共同`` 只表示同一官方编号出现在两个市场；不会按名称相似推断法规等效。
    """
    category = (category or "").strip()
    if markets is None:
        markets = list(corpus.SUPPORTED_MARKETS.keys())
    markets = list(dict.fromkeys(markets))
    invalid = [m for m in markets if m not in corpus.SUPPORTED_MARKETS]
    if not category or category not in corpus.ENTRY_CATEGORIES:
        return _empty(category, markets, "请选择支持的业务品类。")
    if len(markets) < 2:
        return _empty(category, markets, "跨区域对比至少选择两个市场。")
    if invalid:
        return _empty(category, markets, f"暂不支持市场：{'、'.join(invalid)}。")

    by_market = {}
    for market in markets:
        res, rows = _records(category, market)
        by_market[market] = {"市场": market, "记录": rows, "数量": len(rows),
                             "状态": res.get("ok", False)}

    key_sets = {m: {_key(r) for r in d["记录"] if _key(r)} for m, d in by_market.items()}
    shared_keys = set.intersection(*key_sets.values()) if key_sets else set()
    shared = []
    for key in sorted(shared_keys):
        source = next(r for r in by_market[markets[0]]["记录"] if _key(r) == key)
        shared.append({"key": key, "名称": _name(source), "市场": markets})

    unique = {}
    for market, data in by_market.items():
        other = set().union(*(key_sets[m] for m in markets if m != market))
        unique[market] = [r for r in data["记录"] if _key(r) not in other]

    total = sum(d["数量"] for d in by_market.values())
    if total == 0:
        m5_status = snapshot.MODULE_EMPTY
    elif any(not d["状态"] for d in by_market.values()):
        m5_status = snapshot.MODULE_PARTIAL
    else:
        m5_status = snapshot.MODULE_READY

    return {
        "ok": True, "reason": "", "品类": category, "市场": markets,
        "区域": list(by_market.values()), "共同": shared,
        "独有": unique, "共同数量": len(shared),
        "快照版本": snapshot.SNAPSHOT_VERSION, "数据截止时间": snapshot.DATA_CUTOFF,
        "说明": "共同仅按官方编号精确匹配；名称相似但编号不同的法规仍分别保留。",
        "header": snapshot.header(category, " / ".join(markets),
                                  modules={"M5": m5_status}),
    }


def render_text(result):
    if not result.get("ok"):
        return "❌ " + result.get("reason", "无法完成对比")
    lines = [f"M5 同品类区域对比 · {result['品类']}", "=" * 60]
    for item in result["区域"]:
        lines.append(f"{item['市场']}：{item['数量']} 条法规")
    lines.append(f"共同官方编号：{result['共同数量']} 条")
    for market, rows in result["独有"].items():
        lines.append(f"{market}独有：{len(rows)} 条")
    return "\n".join(lines)
