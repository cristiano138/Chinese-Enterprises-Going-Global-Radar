# -*- coding: utf-8 -*-
"""Deterministic integration checks for M2 timeline and M3 todo/export."""
from __future__ import annotations

import csv
import hashlib
import io
import os
import sys
from datetime import date
from unittest.mock import patch

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

    # 缓存键必须区分同日期但不同法规的所有事件输出字段。
    dates._EVENT_CACHE.clear()
    same_date_a = {
        "CELEX号": "32025R1001", "官方编号": "Regulation (EU) 2025/1001",
        "法规中文名": "《法规甲》", "类目": "儿童玩具", "机构": "EU",
        "生效日期": "2026-01-01", "最新修订日期": "", "现行效力": "现行有效",
        "备注／问题": "",
    }
    same_date_b = dict(same_date_a, CELEX号="32025R1002",
                       官方编号="Regulation (EU) 2025/1002", 法规中文名="《法规乙》")
    events_a = dates.extract_events(same_date_a)
    events_b = dates.extract_events(same_date_b)
    check("缓存区分同日期不同法规", events_a[0]["官方编号"] != events_b[0]["官方编号"])
    check("缓存事件中文名不串", events_a[0]["法规中文名"] != events_b[0]["法规中文名"])
    for field, value in (
        ("CELEX号", "32025R1003"), ("官方编号", "其他编号"),
        ("法规中文名", "《其他中文名》"), ("类目", "电子电器"),
        ("机构", "US"), ("生效日期", "2026-02-01"),
        ("最新修订日期", "2026-03-01"), ("现行效力", "已废止"),
        ("备注／问题", "生效/适用日期：2026-01-01、2035-01-01"),
    ):
        changed = dict(same_date_a, **{field: value})
        check(f"缓存指纹独立覆盖{field}",
              dates._row_fingerprint(changed) != dates._row_fingerprint(same_date_a)
              and dates.extract_events(changed) == dates._extract_events_uncached(changed))
    events_a[0]["法规中文名"] = "调用方修改"
    check("缓存命中返回副本且不被调用方污染",
          dates.extract_events(same_date_a)[0]["法规中文名"] == "《法规甲》")

    far_future = dict(same_date_a, 生效日期="2035-01-01")
    packed = dates.collect_events([far_future], months=12, today=fixed_today)
    check("远期未来事件不静默截断", [e["日期"] for e in packed["即将发生"]] == ["2035-01-01"])
    first_record = dict(same_date_a, 机构="US", CELEX号="", 官方编号="16 CFR Part 1",
                        生效日期="首次收录 2026-01-01（参考）")
    first_packed = dates.collect_events([first_record], months=12, today=fixed_today)
    check("非官方首次收录不进入法律时间线",
          not first_packed["近窗内"] and not first_packed["即将发生"]
          and len(first_packed["参考事件"]) == 1)

    future_only_row = dict(same_date_a,
                           生效日期="2035-01-01",
                           官方链接="https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32025R1001",
                           核对状态="已核对")
    future_only_search = {
        "ok": True, "reason": "", "category": "儿童玩具", "market": "欧盟",
        "code": "EU", "primary": [future_only_row], "cross": [],
    }
    with patch.object(m2_timeline.corpus, "search", return_value=future_only_search):
        future_only = m2_timeline.query("儿童玩具", "欧盟", use_llm=False,
                                        today=fixed_today)
    check("M2 只有未来事件时查询成功", future_only["ok"])
    check("M2 只有未来事件时涉及法规数包含未来",
          not future_only["近窗内"] and len(future_only["即将发生"]) == 1
          and future_only["stats"]["涉及法规数"] == 1)

    m2 = m2_timeline.query("儿童玩具", "欧盟", use_llm=False, today=fixed_today)
    check("M2 查询成功", m2["ok"])
    events = m2["近窗内"] + m2["即将发生"]
    check("M2 事件全部带官方链接", all(e.get("官方链接", "").startswith("http") for e in events))
    check("M2 距今使用固定 today", all(e["距今"] == dates.humanize_gap(date.fromisoformat(e["日期"]), fixed_today) for e in events))
    check("M2 未来事件日期不早于基准日", all(date.fromisoformat(e["日期"]) > fixed_today for e in m2["即将发生"]))
    check("M2 涉及法规数包含未来事件",
          m2["stats"]["涉及法规数"] == len({e["官方编号"] or e["法规中文名"]
                                          for e in events}))

    m3 = m3_todo.query("儿童玩具", "欧盟", use_llm=False, today=fixed_today)
    check("M3 查询成功", m3["ok"])
    check("M3 数量守恒", m3["stats"]["动作条数"] + m3["stats"]["未产出条数"] == m3["stats"]["候选法规条数"])
    check("M3 动作链接通过官方校验", all(verify.is_official_url(a["来源条款链接"]) for a in m3["动作"]))
    check("M3 action_id 按业务字段稳定哈希",
          all(a["action_id"] == hashlib.sha256(
              "|".join((a["市场"], a["类目"], a["key"], a["动作类型"])).encode("utf-8")
          ).hexdigest()[:20] for a in m3["动作"]))

    filename, payload = m3_todo.export_csv(m3)
    check("CSV 文件名符合契约", filename.startswith("ComplianceRadar_EU_"))
    check("CSV 含 UTF-8 BOM", payload.startswith(b"\xef\xbb\xbf"))
    rows = list(csv.reader(io.StringIO(payload.decode("utf-8-sig"))))
    check("CSV 列数为 10", len(rows[0]) == 10)
    check("CSV 可重新解析且有数据", len(rows) > 1)
    check("CSV 适用条件明确人工确认",
          all("人工确认：" in row[3] and "动作类型：" not in row[3]
              for row in rows[1:]))
    try:
        m3_todo.export_csv(m3, ["unknown-export-id"])
    except RuntimeError:
        rejected_unknown_id = True
    else:
        rejected_unknown_id = False
    check("未知导出ID拒绝生成文件", rejected_unknown_id)

    original_collect = m3_todo.core_actions.collect

    def reversed_collect(source_rows, today=None):
        candidates, skipped = original_collect(source_rows, today=today)
        return list(reversed(candidates)), skipped

    with patch.object(m3_todo.core_actions, "collect", side_effect=reversed_collect):
        reordered = m3_todo.query("儿童玩具", "欧盟", use_llm=False, today=fixed_today)
    reordered_ids = {a["key"]: a["action_id"] for a in reordered["动作"]}
    original_ids = {a["key"]: a["action_id"] for a in m3["动作"]}
    check("action_id 不依赖候选排序",
          len(m3["动作"]) > 1 and reordered_ids == original_ids
          and reordered["动作"][0]["key"] == m3["动作"][-1]["key"])
    chosen_action = m3["动作"][0]
    _, chosen_payload = m3_todo.export_csv(reordered, [chosen_action["action_id"]])
    chosen_rows = list(csv.reader(io.StringIO(chosen_payload.decode("utf-8-sig")) ))
    check("重排后按稳定ID只导出所选动作",
          len(chosen_rows) == 2 and chosen_rows[1][5] == chosen_action["官方编号"])

    us = m3_todo.query("儿童玩具", "美国", use_llm=False, today=fixed_today)
    check("美国未核对法规统计保留且动作数为零",
          us["ok"] and us["stats"]["待核对法规条数"] > 0
          and us["stats"]["动作条数"] == 0)
    try:
        m3_todo.export_csv(us)
    except RuntimeError:
        rejected_us_export = True
    else:
        rejected_us_export = False
    check("美国待核对零动作拒绝导出", rejected_us_export)

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
