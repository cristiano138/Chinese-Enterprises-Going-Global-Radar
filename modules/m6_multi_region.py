# -*- coding: utf-8 -*-
"""M6 · 多区域法规汇总。

一个品类一次召回多个市场的法规，按市场分组；所有记录均复用 M1 的确定性筛选和链接底线。
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)

from core import corpus, verify, snapshot  # noqa: E402


def query(category="儿童玩具", markets=None):
    category = (category or "").strip()
    markets = list(dict.fromkeys((markets or list(corpus.SUPPORTED_MARKETS.keys()))))
    if category not in corpus.ENTRY_CATEGORIES:
        return {"ok": False, "reason": "请选择支持的业务品类。", "品类": category,
                "市场": markets, "区域": [], "总条数": 0}
    invalid = [m for m in markets if m not in corpus.SUPPORTED_MARKETS]
    if invalid:
        return {"ok": False, "reason": f"暂不支持市场：{'、'.join(invalid)}。", "品类": category,
                "市场": markets, "区域": [], "总条数": 0}
    if not markets:
        return {"ok": False, "reason": "至少选择一个市场。", "品类": category,
                "市场": markets, "区域": [], "总条数": 0}

    regions = []
    for market in markets:
        res = corpus.search(category, market, include_cross_cutting=True)
        kept, dropped = verify.filter_rows(res.get("primary", []) + res.get("cross", []))
        regions.append({"市场": market, "法规": kept, "条数": len(kept),
                        "被拦截": len(dropped), "状态": res.get("ok", False)})
    return {"ok": True, "reason": "", "品类": category, "市场": markets,
            "区域": regions, "总条数": sum(r["条数"] for r in regions),
            "快照版本": snapshot.SNAPSHOT_VERSION, "数据截止时间": snapshot.DATA_CUTOFF}


def render_text(result):
    if not result.get("ok"):
        return "❌ " + result.get("reason", "无法汇总")
    lines = [f"M6 多区域法规汇总 · {result['品类']}", "=" * 60]
    for region in result["区域"]:
        lines.append(f"{region['市场']}：{region['条数']} 条")
    lines.append(f"合计（各区域分别计数）：{result['总条数']} 条")
    return "\n".join(lines)
