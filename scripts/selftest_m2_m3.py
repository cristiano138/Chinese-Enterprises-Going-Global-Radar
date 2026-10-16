# -*- coding: utf-8 -*-
"""Deterministic integration checks for M2 timeline and M3 todo/export."""
from __future__ import annotations

import csv
import io
import os
import sys
from datetime import date

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)

from modules import m2_timeline, m3_todo
from core import corpus, dates, verify


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    print(f"PASS: {name}")


def main():
    fixed_today = date(2026, 10, 15)
    m2 = m2_timeline.query("儿童玩具", "欧盟", use_llm=False, today=fixed_today)
    check("M2 查询成功", m2["ok"])
    events = m2["近窗内"] + m2["即将发生"]
    check("M2 事件全部带官方链接", all(e.get("官方链接", "").startswith("http") for e in events))
    check("M2 距今使用固定 today", all(e["距今"] == dates.humanize_gap(date.fromisoformat(e["日期"]), fixed_today) for e in events))
    check("M2 未来事件日期不早于基准日", all(date.fromisoformat(e["日期"]) > fixed_today for e in m2["即将发生"]))

    m3 = m3_todo.query("儿童玩具", "欧盟", use_llm=False, today=fixed_today)
    check("M3 查询成功", m3["ok"])
    check("M3 数量守恒", m3["stats"]["动作条数"] + m3["stats"]["未产出条数"] == m3["stats"]["候选法规条数"])
    check("M3 动作链接通过官方校验", all(verify.is_official_url(a["来源条款链接"]) for a in m3["动作"]))

    filename, payload = m3_todo.export_csv(m3)
    check("CSV 文件名符合契约", filename.startswith("ComplianceRadar_EU_"))
    check("CSV 含 UTF-8 BOM", payload.startswith(b"\xef\xbb\xbf"))
    rows = list(csv.reader(io.StringIO(payload.decode("utf-8-sig"))))
    check("CSV 列数为 10", len(rows[0]) == 10)
    check("CSV 可重新解析且有数据", len(rows) > 1)

    bad = m2_timeline.query("儿童玩具", "日本", use_llm=False, today=fixed_today)
    check("M2 范围外市场明确拒绝", not bad["ok"])
    bad = m3_todo.query("汽车配件", "欧盟", use_llm=False, today=fixed_today)
    check("M3 范围外类目明确拒绝", not bad["ok"])
    check("语料支持范围完整", set(corpus.SUPPORTED_CATEGORIES) == {"儿童玩具", "电子电器", "纺织服装", "美妆个护", "食品接触材料"})
    print("M2/M3: PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}")
        raise
