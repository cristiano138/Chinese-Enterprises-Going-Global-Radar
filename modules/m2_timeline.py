# -*- coding: utf-8 -*-
"""
M2 · 变化时间线（modules/m2_timeline.py）

一句话：卖家选「品类 + 市场」→ 输出**近期法规变化条目**，
每条含 变化摘要 / 影响说明 / 生效或发布日期 / 官方链接。

输入：商品类目 + 目标市场 + 时间窗（近 12 个月，可缩到近 6 个月）
输出：两节 ——
      · 近窗口内已发生的变化（倒序，最近的在最上面）
      · 即将生效 / 过渡期节点（升序，明确标注「尚未生效」）

链路（与 M1 同构，代码可复用）：
    ① 用户输入 品类 + 市场 + 时间窗
    ② 结构化查表（确定性）—— core/corpus.py 按标签精确筛选
    ③ 日期事件抽取（确定性）—— core/dates.py 把散文日期解析成结构化事件
    ④ 结果集送 LLM（可选）—— 只为每条事件写「变化摘要 + 影响说明」，不得增删事实
    ⑤ 引用对齐（确定性）—— 逐条校验回挂官方链接，无链接一律不输出
    ⑥ 输出时间线

和 M1 的关键差别：
    时间线的事实主体是**日期**，所以确定性代码的比重更高 ——
    日期由 dates.py 解析，模型只负责「这件事该怎么用中文讲给卖家听」。

边界（诚实声明）：
    · 美国条目的「生效日期」列实为 eCFR 收录日，本模块标为「首次收录（参考）」，
      绝不当成生效日；这类条目在界面上有「参考」标记。
    · 时间窗内没有变化时，如实输出「近 N 个月内无变化记录」，并给出放宽后的条数。
"""

import os
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)

from core import actions, corpus, dates, llm, verify, snapshot  # noqa: E402
from core.copy_zh import (  # noqa: E402
    msg_no_input, msg_category_out_of_scope, msg_market_out_of_scope,
    msg_timeline_empty,
)

WINDOW_CHOICES = list(dates.WINDOW_OPTIONS.keys())
DEFAULT_WINDOW = dates.DEFAULT_WINDOW


def _window_months(window):
    """把界面上的中文时间窗 → 月数；无法识别时退回默认 12 个月。"""
    if isinstance(window, (int, float)):
        return int(window)
    return dates.WINDOW_OPTIONS.get((window or "").strip(), 12)


def _fallback_impact(row):
    """确定性影响说明（模型不可用时用）：直接采用语料自带的卖家向说明。"""
    seg0 = (row.get("备注／问题", "") or "").split("｜")[0].strip()
    return seg0 or "官方未说明"


def _to_record(event, row, summary=None, seq=1, total=1, today=None):
    """事件 + 原始语料行 → M2 标准输出记录（README 规定的四要素齐备）。

    seq / total：同一部法规在本节里出现的第几次 / 共几次 ——
    用来告诉卖家「这条法规在这段时间里改了不止一次」。
    """
    key = event["key"]
    urls = verify.official_urls_in(row)

    change = (summary or (None, None))[0] or dates.describe(event)
    impact = (summary or (None, None))[1] or _fallback_impact(row)
    model_used = bool(summary and summary[0])
    reference_today = today or date.today()

    return {
        "event_key": event["event_key"],
        "日期": event["日期"],
        "事件类型": event["事件类型"],
        "官方确认": event["官方确认"],
        "变化摘要": change,
        "影响说明": impact,
        "摘要来源": "模型润色" if model_used else "确定性抽取",
        "距今": dates.humanize_gap(event["date_obj"], reference_today),
        "同类序号": seq,
        "同类计数": total,
        "法规中文名": event["法规中文名"],
        "官方编号": event.get("官方编号", ""),
        "官方链接": row.get("官方链接", ""),
        "全部官方链接": urls,
        "类目": event.get("类目", ""),
        "市场": event.get("市场", ""),
        "现行效力": event.get("现行效力", ""),
        "event_note": event.get("备注", ""),
    }


def query(category, market, window=DEFAULT_WINDOW, use_llm=True, today=None):
    """M2 主入口。

    返回 dict：
        ok        —— 是否成功（False 表示范围外输入）
        品类 / 市场 / 时间窗
        近窗内     —— 时间窗内已发生的变化（倒序）
        即将发生   —— 未来节点（升序）
        window_months / today
        dropped   —— 被引用对齐拦下的条目
        llm       —— 模型元信息
        stats     —— 条目数、涉及法规数、放宽时间窗后的条数
    """
    today = today or date.today()
    months = _window_months(window)

    res = corpus.search(category, market)
    if not res["ok"]:
        cat = (category or "").strip()
        mkt = (market or "").strip()
        if not cat and not mkt:
            reason = msg_no_input()
        elif mkt and mkt not in corpus.SUPPORTED_MARKETS:
            reason = msg_market_out_of_scope(mkt)
        else:
            reason = msg_category_out_of_scope(cat) if cat else msg_no_input()
        return {"ok": False, "reason": reason, "品类": category,
                "市场": market, "时间窗": window, "近窗内": [], "即将发生": [],
                "dropped": [], "llm": None, "stats": {},
                "header": snapshot.header(cat or "（空）", mkt or "（空）",
                                          m2_status=snapshot.MODULE_ERROR)}

    # ── ⑤ 引用对齐先过（红线优先于润色）────────────────────
    kept, drop = verify.filter_rows(res["primary"] + res["cross"])
    dropped = [(actions.row_key(r), why) for r, why in drop]
    row_by_key = {actions.row_key(r): r for r in kept}

    # ── ③ 日期事件抽取（确定性）───────────────────────────
    packed = dates.collect_events(kept, months=months, today=today)
    recent, upcoming, all_events = packed["近窗内"], packed["即将发生"], packed["全部"]

    # ── ④ 送 LLM 写摘要 + 影响（可选，失败自动降级）─────────
    targets = recent + upcoming
    summaries, meta = ({}, {"ok": True, "reason": "未启用", "cached": False})
    if use_llm and targets:
        summaries, meta = llm.m2_summaries(targets)
        if summaries:
            # 防幻觉第二道关：事件键的法规部分必须落在语料库真实键集合内
            corpus_keys = set(row_by_key.keys())
            aligned, rejected = verify.align_output(
                [{"key": k.split("|")[0], "_orig": k} for k in summaries],
                corpus_keys)
            valid = {a["_orig"] for a in aligned}
            summaries = {k: v for k, v in summaries.items() if k in valid}
            for it, why in rejected:
                dropped.append((it.get("key"), why))
        elif not meta["ok"]:
            summaries = {}

    def _recs(evs):
        # 同一部法规在窗口内可能改了不止一次，标出「第 N / 共 M 次」
        totals = {}
        for e in evs:
            totals[e["key"]] = totals.get(e["key"], 0) + 1
        seen = {}
        out = []
        for e in evs:
            row = row_by_key.get(e["key"])
            if row is None:
                continue
            seen[e["key"]] = seen.get(e["key"], 0) + 1
            out.append(_to_record(e, row, summaries.get(e["event_key"]),
                                  seq=seen[e["key"]], total=totals[e["key"]],
                                  today=today))
        return out

    recent_recs = _recs(recent)
    upcoming_recs = _recs(upcoming)

    n_reg = len({r["官方编号"] or r["法规中文名"] for r in recent_recs})

    # M2 模块状态：empty / partial / ready
    total = len(recent_recs) + len(upcoming_recs)
    if total == 0:
        m2_status = snapshot.MODULE_EMPTY
    elif len(recent_recs) == 0:
        # 只有未来节点（PASS
        m2_status = snapshot.MODULE_READY
    else:
        # 「官方确认=False」（=首次收录）算 partial
        pending = sum(1 for r in recent_recs + upcoming_recs
                      if not r["官方确认"])
        m2_status = snapshot.MODULE_PARTIAL if pending else snapshot.MODULE_READY

    return {
        "ok": True,
        "reason": "",
        "品类": res["category"],
        "市场": res["market"],
        "时间窗": window,
        "window_months": months,
        "today": today,
        "近窗内": recent_recs,
        "即将发生": upcoming_recs,
        "dropped": dropped,
        "llm": meta,
        "stats": {
            "近窗内条数": len(recent_recs),
            "即将发生条数": len(upcoming_recs),
            "涉及法规数": n_reg,
            "全部历史条数": len(all_events),
            "候选法规条数": len(kept),
        },
        "header": snapshot.header(res["category"], res["market"],
                                  m2_status=m2_status),
    }


# ── 渲染成文本（供 CLI 与自检使用）─────────────────────────────
def render_text(result):
    lines = []
    if not result["ok"]:
        lines.append("❌ " + result["reason"])
        lines.append("")
        lines.append("支持的品类：" + "、".join(corpus.ALL_QUERYABLE))
        lines.append("支持的市场：" + "、".join(corpus.SUPPORTED_MARKETS.keys()))
        return "\n".join(lines)

    s = result["stats"]
    lines.append("=" * 78)
    lines.append(f"  M2 变化时间线 · {result['品类']} × {result['市场']}"
                 f"　（{result['时间窗']}）")
    lines.append("=" * 78)
    lines.append(f"  近窗内 {s['近窗内条数']} 条 · 涉及法规 {s['涉及法规数']} 部"
                 f" · 即将发生 {s['即将发生条数']} 条")
    lines.append(f"  （该组合语料共 {s['候选法规条数']} 条，"
                 f"全部历史事件 {s['全部历史条数']} 个）")

    lm = result.get("llm") or {}
    if lm.get("ok") and result["近窗内"] and result["近窗内"][0]["摘要来源"] == "模型润色":
        tag = "（缓存命中）" if lm.get("cached") else ""
        lines.append(f"  摘要与影响说明：由模型改写{tag} —— 日期与法规事实未经模型改动")
    elif lm and not lm.get("ok") and lm.get("reason") != "未启用":
        lines.append(f"  ⚠️ 模型不可用（{lm.get('reason')}），已降级为确定性摘要"
                     f" —— 时间线与链接依然完整可核验")
    lines.append("")

    def block(title, recs):
        if not recs:
            return
        lines.append("─" * 78)
        lines.append(f"  【{title}】{len(recs)} 条")
        lines.append("─" * 78)
        for i, r in enumerate(recs, 1):
            ref = "" if r["官方确认"] else "（参考）"
            rep = (f"　⚠ 该法规本窗口内第 {r['同类序号']}/{r['同类计数']} 次"
                   if r["同类计数"] > 1 else "")
            lines.append(f"  {i:>2}. {r['日期']}　{r['事件类型']}{ref}"
                         f"　{r['距今']}{rep}")
            lines.append(f"      变化摘要 : {r['变化摘要']}")
            lines.append(f"      影响说明 : {r['影响说明']}")
            lines.append(f"      法规     : {r['法规中文名']}　{r['官方编号']}")
            lines.append(f"      官方链接 : {r['官方链接']}")
            lines.append("")

    if result["近窗内"]:
        block(f"近 {result['window_months']} 个月已发生的变化", result["近窗内"])
    else:
        lines.append("─" * 78)
        # PRD E 节 7：保留已知未来节点；两者都无则空态
        if result["即将发生"]:
            lines.append(f"  近 {result['window_months']} 个月内，"
                         f"该组合没有可核验的法规变化记录，"
                         f"但保留已知未来节点。")
        else:
            lines.append("  " + msg_timeline_empty(result["品类"], result["市场"]))
        lines.append(f"  放宽到全部历史，共有 {result['stats']['全部历史条数']} 个事件。")
        lines.append("")

    if result["即将发生"]:
        block("即将发生 / 过渡期节点（尚未生效）", result["即将发生"])

    if result["dropped"]:
        lines.append("─" * 78)
        lines.append(f"  ⛔ 被引用对齐拦下 {len(result['dropped'])} 条（无官方链接，不输出）")
        for k, why in result["dropped"]:
            lines.append(f"      - {k}：{why}")
        lines.append("")

    lines.append("─" * 78)
    lines.append(f"  ⚖️ {snapshot.DISCLAIMER}")
    lines.append(f"  ℹ️  {snapshot.WAF_FOOTER_HINT}")
    lines.append("=" * 78)
    return "\n".join(lines)


if __name__ == "__main__":
    cat = sys.argv[1] if len(sys.argv) > 1 else "儿童玩具"
    mkt = sys.argv[2] if len(sys.argv) > 2 else "欧盟"
    win = DEFAULT_WINDOW
    for c in WINDOW_CHOICES:
        if c in sys.argv:
            win = c
    no_llm = "--no-llm" in sys.argv
    print(render_text(query(cat, mkt, window=win, use_llm=not no_llm)))
