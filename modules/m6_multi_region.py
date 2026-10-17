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


def _empty(category, markets, reason):
    """失败分支：键集与成功分支一致，并带上 header（PRD D3 每次输出都要有）。"""
    market_label = " / ".join(markets) if markets else "（未选市场）"
    return {"ok": False, "reason": reason, "品类": category,
            "市场": markets, "区域": [], "总条数": 0,
            "快照版本": snapshot.SNAPSHOT_VERSION,
            "数据截止时间": snapshot.DATA_CUTOFF,
            "header": snapshot.header(category or "（空）", market_label,
                                      modules={"M6": snapshot.MODULE_ERROR})}


def query(category="儿童玩具", markets=None):
    category = (category or "").strip()
    # 关键区分：None = 未指定（默认全选）；[] = 用户把勾选全取消（应明确拒绝）。
    # 早期写法 `markets or list(...)` 把两者混为一谈 —— 取消全部勾选反而返回
    # 全部市场，「至少选择一个市场」这条分支永远不可达。
    if markets is None:
        markets = list(corpus.SUPPORTED_MARKETS.keys())
    markets = list(dict.fromkeys(markets))
    if category not in corpus.ENTRY_CATEGORIES:
        return _empty(category, markets, "请选择支持的业务品类。")
    invalid = [m for m in markets if m not in corpus.SUPPORTED_MARKETS]
    if invalid:
        return _empty(category, markets, f"暂不支持市场：{'、'.join(invalid)}。")
    if not markets:
        return _empty(category, markets, "至少选择一个市场。")

    regions = []
    for market in markets:
        res = corpus.search(category, market, include_cross_cutting=True)
        kept, dropped = verify.filter_rows(res.get("primary", []) + res.get("cross", []))
        regions.append({"市场": market, "法规": kept, "条数": len(kept),
                        "被拦截": len(dropped), "状态": res.get("ok", False)})
    total = sum(r["条数"] for r in regions)
    if total == 0:
        m6_status = snapshot.MODULE_EMPTY
    elif any(not r["状态"] for r in regions):
        m6_status = snapshot.MODULE_PARTIAL
    else:
        m6_status = snapshot.MODULE_READY
    return {"ok": True, "reason": "", "品类": category, "市场": markets,
            "区域": regions, "总条数": total,
            "快照版本": snapshot.SNAPSHOT_VERSION, "数据截止时间": snapshot.DATA_CUTOFF,
            "header": snapshot.header(category, " / ".join(markets),
                                      modules={"M6": m6_status})}


def render_text(result):
    if not result.get("ok"):
        return "❌ " + result.get("reason", "无法汇总")
    lines = [f"M6 多区域法规汇总 · {result['品类']}", "=" * 60]
    for region in result["区域"]:
        lines.append(f"{region['市场']}：{region['条数']} 条")
    lines.append(f"合计（各区域分别计数）：{result['总条数']} 条")
    return "\n".join(lines)
