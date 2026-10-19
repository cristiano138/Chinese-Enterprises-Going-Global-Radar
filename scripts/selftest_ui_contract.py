# -*- coding: utf-8 -*-
"""输出契约自检：跨模块的统一约定（不属于任何单模块的自测）。

这里守的是「以前踩过的坑」——都是模块各自的自检照不到、但一破就会
让产品说谎或让红线失效的地方：

  A. 免责声明：查询输出都必须带，旧渲染器与新聊天入口分别检查
  B. 顶部元数据：成功/失败分支都要有 header，且四要素齐全（PRD D3）
  C. 模块状态不许谎报：没跑过的模块不能显示成「空」（MODULE_NA 语义）
  D. ELI 永久链接：M1/M2/M3 三个页签都要渲染出来（欧盟 29 条都带 ELI）
  E. 导出安全：范围外/空结果时导出函数返回 None，不抛异常
  F. 空选择不退化：取消全部市场勾选要明确拒绝，不能悄悄返回全选
  G. 键集一致：同一 query() 的成功分支与失败分支键集必须对得上
  H. 日期格式统一：数据截止时间与查询日期同为 ISO 8601

A–H 是 query 级检查；I 及免责声明、ELI 和 UI 配置检查需要使用项目隔离环境中的 Gradio。缺少 Gradio 或应用导入失败时，测试明确失败，不把未执行当作通过。
"""
from __future__ import annotations

import json
import os
import re
import sys
from unittest.mock import patch

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)

from core import snapshot  # noqa: E402
from modules import (m1_map, m2_timeline, m3_todo, m5_compare,  # noqa: E402
                     m6_multi_region, m7_opc_readiness)

FAIL = []


def check(name, condition, detail=""):
    if condition:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAIL.append(name)


HEADER_KEYS = ("查询条件", "查询日期", "快照版本", "数据截止时间", "免责声明")


def _queries():
    """(标签, 结果) —— 覆盖成功与失败两类分支。"""
    return [
        ("M1", m1_map.query("儿童玩具", "欧盟", use_llm=False)),
        ("M2", m2_timeline.query("儿童玩具", "欧盟", use_llm=False)),
        ("M3", m3_todo.query("儿童玩具", "欧盟", use_llm=False)),
        ("M5", m5_compare.query("儿童玩具", ["欧盟", "美国"])),
        ("M6", m6_multi_region.query("儿童玩具", ["欧盟", "美国"])),
        ("M7", m7_opc_readiness.query("儿童玩具", ["欧盟", "美国"])),
    ]


def main():
    print("=" * 74)
    print("  输出契约自检（跨模块统一约定）")
    print("=" * 74)

    # ── B. header 四要素（成功 + 失败分支）──────────────────
    print("\n【B】顶部元数据：成功与失败分支都要有 header，四要素齐全")
    results = _queries()
    for label, res in results:
        head = res.get("header") or {}
        missing = [k for k in HEADER_KEYS if not head.get(k)]
        check(f"{label} 成功分支 header 完整", not missing, f"缺 {missing}")
    failure_cases = [
        ("M1", m1_map.query("汽车配件", "欧盟", use_llm=False)),
        ("M2", m2_timeline.query("儿童玩具", "日本", use_llm=False)),
        ("M3", m3_todo.query("汽车配件", "欧盟", use_llm=False)),
        ("M5", m5_compare.query("汽车配件", ["欧盟", "美国"])),
        ("M6", m6_multi_region.query("汽车配件", ["欧盟", "美国"])),
        ("M7", m7_opc_readiness.query("汽车配件", ["欧盟", "美国"])),
    ]
    for label, res in failure_cases:
        check(f"{label} 失败分支明确拒绝", res.get("ok") is False)
        head = res.get("header") or {}
        check(f"{label} 失败分支仍有 header", bool(head.get("快照版本")),
              f"header={head}")

    # ── C. 模块状态不许谎报 ─────────────────────────────────
    print("\n【C】模块状态：只列本次真正跑过的模块（未跑不等于「空」）")
    m1_head = m1_map.query("儿童玩具", "欧盟", use_llm=False)["header"]
    mods = m1_head.get("模块状态", {})
    check("M1 查询只报 M1 状态",
          set(mods) == {"M1"}, f"实际 {set(mods)}")
    check("M1 查询不把 M2/M3 标成空",
          snapshot.MODULE_EMPTY not in [mods.get("M2"), mods.get("M3")],
          f"实际 {mods}")
    m6_head = m6_multi_region.query("儿童玩具", ["欧盟"])["header"]
    check("M6 查询报 M6 状态", "M6" in m6_head.get("模块状态", {}),
          f"实际 {m6_head.get('模块状态')}")

    # ── H. 日期格式统一 ────────────────────────────────────
    print("\n【H】日期格式：数据截止时间与查询日期同为 ISO 8601")
    check("数据截止时间是 ISO 格式（YYYY-MM-DD）",
          len(snapshot.DATA_CUTOFF) == 10 and snapshot.DATA_CUTOFF[4] == "-"
          and snapshot.DATA_CUTOFF[7] == "-", repr(snapshot.DATA_CUTOFF))
    check("查询日期是 ISO 格式",
          len(snapshot.now_bjt()) == 10 and snapshot.now_bjt()[4] == "-",
          repr(snapshot.now_bjt()))

    # ── G. 键集一致 ───────────────────────────────────────
    print("\n【G】键集一致：成功分支与失败分支键集对齐")
    for label, q in (("M5", m5_compare.query), ("M6", m6_multi_region.query),
                     ("M7", m7_opc_readiness.query)):
        ok_r = q("儿童玩具", ["欧盟"])
        bad_r = q("汽车配件", ["欧盟"])
        only_bad = sorted(set(bad_r) - set(ok_r))
        check(f"{label} 失败分支不多出键", not only_bad, f"多出 {only_bad}")
        check(f"{label} 失败分支不缺成功分支的键",
              not sorted(set(ok_r) - set(bad_r)),
              f"缺 {sorted(set(ok_r) - set(bad_r))}")

    # ── F. 空选择不退化为全选 ───────────────────────────────
    print("\n【F】空选择：取消全部勾选要明确拒绝")
    for label, q in (("M6", m6_multi_region.query), ("M7", m7_opc_readiness.query)):
        empty = q("儿童玩具", [])
        check(f"{label} 空市场列表被拒绝", empty.get("ok") is False,
              f"实际 ok={empty.get('ok')} 品类={empty.get('市场')}")

    # ── E. 导出安全 ───────────────────────────────────────
    print("\n【E】导出安全：范围外输入不抛异常")
    try:
        m3_todo.export_csv(m3_todo.query("汽车配件", "欧盟", use_llm=False))
        check("M3 导出对范围外输入抛 RuntimeError", False, "没抛异常")
    except RuntimeError:
        check("M3 导出对范围外输入抛 RuntimeError", True)

    # ── D. M7 不许有假的「需确认」统计 ─────────────────────
    print("\n【D】M7 状态：单项状态只用规则算得出的值")
    r7 = m7_opc_readiness.query("儿童玩具", ["欧盟", "美国"])
    statuses = {it["状态"] for reg in r7["区域"] for it in reg["动作"]}
    check("M7 单项状态在允许集合内",
          statuses <= {"优先处理", "待执行"}, f"实际 {statuses}")

    # ── 渲染级检查（需要 gradio）──────────────────────────
    print("\n【A】免责声明 + 【D】ELI 链接：渲染级检查")
    try:
        import app_main
    except Exception as exc:                     # noqa: BLE001
        check("应用可导入并执行 A/D/I 渲染检查", False,
              f"{type(exc).__name__}: {exc}；请使用项目 Gradio 环境")
    else:
        disc = snapshot.DISCLAIMER

        # ── 首页统计与 M5/M6 命名回归 ─────────────────────────
        print("\n【I】旧版统计兼容与新版七项能力入口契约")

        def overview_fixture(total, audit_distribution):
            with patch.object(snapshot, "CORPUS_ROWS_TOTAL", total), \
                    patch.object(snapshot, "CORPUS_ROWS_BY_AUDIT_STATUS",
                                 audit_distribution):
                return app_main._overview_html("模型：未配置")

        def stat_values(html):
            return dict(re.findall(
                r'<div class="cr-stat"><div class="cr-stat-k">([^<]+)</div>'
                r'<div class="cr-stat-v">([^<]+)</div>', html))

        with open(os.path.join(PROJECT, "data", "snapshot.json"), encoding="utf-8") as f:
            release = json.load(f)
        check("审核统计直接读取当前快照",
              snapshot.CORPUS_ROWS_BY_AUDIT_STATUS == release.get("audit_status_distribution", {}))
        actual_stats = stat_values(app_main._overview_html("模型：未配置"))
        check("首页候选总数匹配当前快照",
              actual_stats.get("候选总数") == str(release["total_rows"]), str(actual_stats))
        for status in ("已核对", "待核对"):
            value = release.get("audit_status_distribution", {}).get(status)
            expected = "未提供" if value is None else str(value)
            check(f"首页{status}匹配当前快照", actual_stats.get(status) == expected, str(actual_stats))

        fixture_a = overview_fixture(12, {"已核对": 4, "待核对": 8})
        stats_a = stat_values(fixture_a)
        check("首页显示候选总数", stats_a.get("候选总数") == "12", str(stats_a))
        check("首页显示已核对数", stats_a.get("已核对") == "4", str(stats_a))
        check("首页显示待核对数", stats_a.get("待核对") == "8", str(stats_a))

        fixture_b = overview_fixture(3, {"已核对": 0, "待核对": 3})
        stats_b = stat_values(fixture_b)
        check("首页统计支持零已核对 fixture", stats_b.get("已核对") == "0", str(stats_b))
        check("首页统计支持另一组候选总数", stats_b.get("候选总数") == "3", str(stats_b))

        fixture_missing = overview_fixture(7, {"已核对": 7})
        stats_missing = stat_values(fixture_missing)
        check("审核分布缺失时不伪造待核对数",
              stats_missing.get("待核对") == "未提供", str(stats_missing))
        for distribution in ({}, None, {"已核对": None, "待核对": None}):
            missing_stats = stat_values(overview_fixture(7, distribution))
            check(f"缺失或空审核分布不伪造数量 {distribution!r}",
                  missing_stats.get("已核对") == "未提供"
                  and missing_stats.get("待核对") == "未提供", str(missing_stats))

        check("core.snapshot M5 模块名统一",
              snapshot.MODULE_NAMES.get("M5") == "区域对比")
        check("core.snapshot M6 模块名统一",
              snapshot.MODULE_NAMES.get("M6") == "多区域汇总")

        import ui_chat
        from core import conversation

        ui = app_main.build_ui()
        components = ui.get_config_file()["components"]
        button_values = [c["props"].get("value", "") for c in components if c["type"] == "button"]
        expected_actions = {"map", "todo", "timeline", "compare", "multi", "readiness", "model"}
        check("新版目录保留完整七项能力",
              {action for action, _, _ in ui_chat.CAPABILITIES} == expected_actions)
        check("UI能力目录与会话服务目录一致",
              {item["action"] for item in conversation.CAPABILITIES} == expected_actions)
        for action, title, _ in ui_chat.CAPABILITIES:
            check(f"{action} 有真实可见按钮", any(value.startswith(title) for value in button_values), title)
        compare_title = next(title for action, title, _ in ui_chat.CAPABILITIES if action == "compare")
        multi_title = next(title for action, title, _ in ui_chat.CAPABILITIES if action == "multi")
        compare_positions = [i for i, value in enumerate(button_values) if value.startswith(compare_title)]
        multi_positions = [i for i, value in enumerate(button_values) if value.startswith(multi_title)]
        check("区域对比入口位于多市场汇总之前",
              bool(compare_positions and multi_positions and compare_positions[0] < multi_positions[0]))

        # Verify actual registered click callbacks, rather than only a constant
        # containing seven labels. These callbacks must use the shared service.
        bound_actions = set()
        for callback in ui.fns.values():
            if not callback.fn:
                continue
            defaults = getattr(callback.fn, "__defaults__", ()) or ()
            action = next((value for value in defaults if isinstance(value, str) and value in expected_actions), None)
            if not action:
                continue
            state = conversation.new_session()
            with patch.object(ui_chat, "submit_message", return_value=()) as submit:
                callback.fn(state)
            actual = submit.call_args.args if submit.call_args else ()
            check(f"{action} 点击回调复用同一会话入口",
                  len(actual) == 3 and actual[0] == "" and actual[1] is state and actual[2] == action)
            bound_actions.add(action)
        check("七项能力均有已注册的点击回调", bound_actions == expected_actions, str(bound_actions))
        check("旧M5/M6调用助手保留兼容",
              callable(app_main.run_compare) and callable(app_main.run_multi_region))
        check("新聊天入口包含明确免责声明",
              any(disc in str(component["props"].get("value", ""))
                  for component in components))

        renderers = [
            ("M1", app_main.render_m1(m1_map.query("儿童玩具", "欧盟", use_llm=False))),
            ("M2", app_main.render_m2(m2_timeline.query("儿童玩具", "欧盟", use_llm=False))),
            ("M3", app_main.render_m3(m3_todo.query("儿童玩具", "欧盟", use_llm=False))),
            ("M5", app_main.render_m5(m5_compare.query("儿童玩具", ["欧盟", "美国"]))),
            ("M6", app_main.render_m6(m6_multi_region.query("儿童玩具", ["欧盟", "美国"]))),
            ("M7", app_main.render_m7(m7_opc_readiness.query("儿童玩具", ["欧盟", "美国"]))),
        ]
        for label, html in renderers:
            check(f"{label} 输出含免责声明", disc in html or "不构成法律意见" in html)
        m2_html = dict(renderers)["M2"]
        m3_html = dict(renderers)["M3"]
        check("M2 渲染出 ELI 永久标识链接（data.europa.eu）",
              "data.europa.eu" in m2_html)
        check("M3 渲染出 ELI 永久标识链接（data.europa.eu）",
              "data.europa.eu" in m3_html)

    print("\n" + "=" * 74)
    if FAIL:
        print(f"  结果：失败 {len(FAIL)} 项")
        for name in FAIL:
            print(f"    ❌ {name}")
        print("=" * 74)
        return 1
    print("  结果：全部通过")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
