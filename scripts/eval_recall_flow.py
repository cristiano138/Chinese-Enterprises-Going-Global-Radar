# -*- coding: utf-8 -*-
"""
两层召回评测（scripts/eval_recall_flow.py）

用 data/recall_golden.json 的 query -> expected_laws 跑 recall_flow.run()，
输出法规召回、切片覆盖、ref 越界、coverage/gaps 和延迟。

指标口径：
    route_recall —— 路由层选中的法规里，命中了多少期望法规（首要指标）
    slice_recall —— 最终选中的切片涉及多少期望法规（次级指标）
    extra_laws   —— 路由多选的法规数（不一定是错，法规可能确实相关）
    invalid_refs —— 模型返回的越界/非整数 ref 数

用法：
    python scripts/eval_recall_flow.py                 # 模型路径（5s/条左右）
    python scripts/eval_recall_flow.py --no-llm        # 确定性兜底基线
    python scripts/eval_recall_flow.py --limit 2       # 冒烟
    python scripts/eval_recall_flow.py --json data/recall_eval_report.json

说明：
    · 这是评测工具，不是发布门禁；退出码 0 表示跑完，不代表召回达标。
    · 期望法规是人工 golden set，会随产品口径调整；先看趋势，不要把它当绝对真值。
"""

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
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)

from core import llm  # noqa: E402
from modules import recall_flow as rf  # noqa: E402

GOLDEN_PATH = os.path.join(PROJECT, "data", "recall_golden.json")
DEFAULT_REPORT = os.path.join(PROJECT, "data", "recall_eval_report.json")


def _arg_value(name, default=None):
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


def _pct(x):
    return "%.0f%%" % (100.0 * x)


def _percentile(values, p):
    if not values:
        return 0
    values = sorted(values)
    idx = min(len(values) - 1, int(p * len(values)))
    return values[idx]


def main():
    no_llm = "--no-llm" in sys.argv
    limit = None
    if "--limit" in sys.argv:
        try:
            limit = int(_arg_value("--limit"))
        except (TypeError, ValueError):
            print("错误：--limit 需要整数", file=sys.stderr)
            return 2
    report_path = _arg_value("--json", DEFAULT_REPORT)

    if not os.path.exists(GOLDEN_PATH):
        print("错误：找不到 golden set：%s" % GOLDEN_PATH, file=sys.stderr)
        return 2
    with open(GOLDEN_PATH, encoding="utf-8") as f:
        golden = json.load(f)
    if limit:
        golden = golden[:limit]

    if not no_llm and not llm.is_ready():
        print("提示：模型链路未配置，自动切到 --no-llm 基线。")
        no_llm = True

    print("=" * 92)
    print("  两层法规召回评测（%s）" % ("确定性兜底" if no_llm else "模型路径"))
    print("=" * 92)
    print("  %-16s %7s %7s %6s %7s %10s %7s" % (
        "id", "route", "slice", "extra", "invalid", "coverage", "ms"))

    rows = []
    for item in golden:
        qid = item.get("id") or item.get("query", "")[:16]
        query = item.get("query") or ""
        expected = set(item.get("expected_laws") or [])
        res = rf.run(query, use_llm=not no_llm)
        route = res.get("route") or {}
        ret = res.get("retrieval") or {}
        route_laws = {l.get("law_id") for l in (route.get("laws") or []) if l.get("law_id")}
        slice_laws = {s.get("law_id") for s in (ret.get("selected") or []) if s.get("law_id")}
        hit_route = expected & route_laws
        hit_slice = expected & slice_laws
        route_recall = len(hit_route) / len(expected) if expected else 0.0
        slice_recall = len(hit_slice) / len(expected) if expected else 0.0
        invalid = len(route.get("invalid_refs") or []) + len(ret.get("invalid_refs") or [])
        row = {
            "id": qid,
            "query": query,
            "ok": res.get("ok"),
            "reason": res.get("reason"),
            "route_via": route.get("route_via"),
            "route_recall": round(route_recall, 4),
            "slice_recall": round(slice_recall, 4),
            "route_hits": sorted(hit_route),
            "slice_hits": sorted(hit_slice),
            "missing": sorted(expected - route_laws),
            "extra_laws": sorted(route_laws - expected),
            "invalid_refs": invalid,
            "coverage": ret.get("coverage"),
            "gaps": ret.get("gaps") or [],
            "latency_ms": res.get("latency_ms"),
            "selected_slices": len(ret.get("selected") or []),
        }
        rows.append(row)
        print("  %-16s %7s %7s %6d %7d %10s %7d" % (
            qid, _pct(route_recall), _pct(slice_recall),
            len(row["extra_laws"]), invalid, ret.get("coverage") or "-",
            res.get("latency_ms") or 0))
        if row["missing"]:
            print("      缺：%s" % ", ".join(row["missing"]))
        if not res.get("ok"):
            print("      失败：%s" % (res.get("reason") or "-"))

    n = len(rows) or 1
    latencies = [r["latency_ms"] for r in rows if r.get("latency_ms") is not None]
    summary = {
        "mode": "no_llm" if no_llm else "llm",
        "queries": len(rows),
        "mean_route_recall": round(sum(r["route_recall"] for r in rows) / n, 4),
        "mean_slice_recall": round(sum(r["slice_recall"] for r in rows) / n, 4),
        "total_invalid_refs": sum(r["invalid_refs"] for r in rows),
        "failures": sum(1 for r in rows if not r["ok"]),
        "latency_p50_ms": _percentile(latencies, 0.5),
        "latency_p95_ms": _percentile(latencies, 0.95),
        "latency_max_ms": max(latencies) if latencies else 0,
    }
    print("-" * 92)
    print("  平均 route recall：%s" % _pct(summary["mean_route_recall"]))
    print("  平均 slice recall：%s" % _pct(summary["mean_slice_recall"]))
    print("  无效 ref：%d　失败：%d" % (
        summary["total_invalid_refs"], summary["failures"]))
    print("  延迟：p50=%dms　p95=%dms　max=%dms" % (
        summary["latency_p50_ms"], summary["latency_p95_ms"],
        summary["latency_max_ms"]))
    print("=" * 92)

    report = {"summary": summary, "rows": rows}
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print("  报告：%s" % report_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
