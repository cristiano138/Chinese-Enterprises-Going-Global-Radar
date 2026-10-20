# -*- coding: utf-8 -*-
"""离线检查各层 LLM 是否真的被调用，以及失败时是否仍走确定性结果。

这里不联网、不调用真实模型：
  · M2 的键对齐用真实事件 + 假模型输出验证；
  · M1/M2/M3 的润色入口用桩替换，确认 use_llm=True 时确实走到；
  · conversation / ui_chat / web_app 用桩确认开关被透传；
  · SPA 的请求参数做静态检查，防止前端又退回 use_llm=False。
"""
from __future__ import annotations

from datetime import date
import inspect
import os
from pathlib import Path
import sys
from unittest.mock import patch

PROJECT = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from core import conversation, llm
from modules import m1_map, m2_timeline, m3_todo
import ui_chat
import web_app

FIXED_TODAY = date(2026, 10, 15)


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    print(f"PASS: {name}")


def check_m2_key_alignment():
    events = [
        {"event_key": "A|2026-01-01|生效"},
        {"event_key": "A|2027-01-01|适用"},
        {"event_key": "B|2026-02-02|废止"},
    ]
    # 模型最常见的行为：把完整事件键缩写成法规键。
    shortcut = "\n".join([
        "A|||第一次变化|||第一次影响",
        "A|||第二次变化|||第二次影响",
        "B|||第三条变化|||第三条影响",
    ])
    parsed = llm.parse_event_summaries(shortcut, events)
    check("M2 法规键缩写按顺序对齐到不同事件",
          parsed.get("A|2026-01-01|生效") == ("第一次变化", "第一次影响")
          and parsed.get("A|2027-01-01|适用") == ("第二次变化", "第二次影响")
          and parsed.get("B|2026-02-02|废止") == ("第三条变化", "第三条影响"))

    prefixed = "A|2026-01-01|||前缀命中|||前缀影响"
    parsed = llm.parse_event_summaries(prefixed, events)
    check("M2 只写到日期时按前缀对齐",
          parsed.get("A|2026-01-01|生效") == ("前缀命中", "前缀影响"))

    exact = "B|2026-02-02|废止|||精确命中|||精确影响"
    parsed = llm.parse_event_summaries(exact, events)
    check("M2 完整事件键优先精确匹配",
          parsed.get("B|2026-02-02|废止") == ("精确命中", "精确影响"))


def check_m2_integration():
    baseline = m2_timeline.query("儿童玩具", "欧盟", use_llm=False, today=FIXED_TODAY)
    events = baseline["近窗内"] + baseline["即将发生"]
    check("M2 测试样本包含事件", len(events) >= 2)

    lines = []
    for index, event in enumerate(events, start=1):
        law_key = event["event_key"].split("|", 1)[0]
        lines.append(f"{law_key}|||模型摘要{index}|||模型影响{index}")
    fake = ("\n".join(lines), {"ok": True, "reason": "", "cached": False})

    with patch.object(m2_timeline.llm, "chat", return_value=fake):
        result = m2_timeline.query("儿童玩具", "欧盟", use_llm=True, today=FIXED_TODAY)
    got = result["近窗内"] + result["即将发生"]
    check("M2 模型摘要真正进入结果",
          result["ok"] and all(event.get("摘要来源") == "模型润色" for event in got))
    check("M2 模型影响说明同步标注",
          all(event.get("影响来源") == "模型润色" for event in got))
    check("M2 模型摘要按事件逐条写入",
          [event.get("变化摘要") for event in got]
          == [f"模型摘要{index}" for index in range(1, len(got) + 1)])


def check_module_defaults_and_calls():
    check("M1 默认启用可选润色",
          inspect.signature(m1_map.query).parameters["use_llm"].default is True)
    check("M2 默认启用可选润色",
          inspect.signature(m2_timeline.query).parameters["use_llm"].default is True)
    check("M3 默认启用可选润色",
          inspect.signature(m3_todo.query).parameters["use_llm"].default is True)

    with patch.object(m1_map.llm, "m1_tips",
                      return_value=({}, {"ok": True})) as tips:
        m1_map.query("儿童玩具", "欧盟", use_llm=True)
    check("M1 use_llm=True 调用 m1_tips", tips.called)

    with patch.object(m3_todo.llm, "m3_actions",
                      return_value=({}, {"ok": True})) as rewrite:
        m3_todo.query("儿童玩具", "欧盟", use_llm=True, today=FIXED_TODAY)
    check("M3 use_llm=True 调用 m3_actions", rewrite.called)


def check_conversation_forwarding():
    context = {"category": "儿童玩具", "market": "欧盟", "markets": ["欧盟"],
               "window": "近 12 个月", "use_llm": True}
    with patch.object(conversation.llm, "is_ready", return_value=True), \
            patch.object(conversation.m1_map, "query", return_value={"ok": True}) as query:
        conversation._call("map", dict(context))
    check("conversation 把 use_llm=True 传给 M1",
          query.call_args.kwargs.get("use_llm") is True)

    with patch.object(conversation.llm, "is_ready", return_value=True), \
            patch.object(conversation.m3_todo, "query", return_value={"ok": True}) as query:
        conversation._call("todo", dict(context))
    check("conversation 把 use_llm=True 传给 M3",
          query.call_args.kwargs.get("use_llm") is True)

    with patch.object(conversation.llm, "is_ready", return_value=True), \
            patch.object(conversation.m2_timeline, "query", return_value={"ok": True}) as query:
        conversation._call("timeline", dict(context))
    check("conversation 把 use_llm=True 传给 M2",
          query.call_args.kwargs.get("use_llm") is True)

    context["use_llm"] = False
    with patch.object(conversation.llm, "is_ready", return_value=True), \
            patch.object(conversation.m1_map, "query", return_value={"ok": True}) as query:
        conversation._call("map", dict(context))
    check("conversation 关闭时不调用模型润色",
          query.call_args.kwargs.get("use_llm") is False)

    context["use_llm"] = True
    with patch.object(conversation.llm, "is_ready", return_value=False), \
            patch.object(conversation.m1_map, "query", return_value={"ok": True}) as query:
        conversation._call("map", dict(context))
    check("模型未配置时 conversation 不传 use_llm=True",
          query.call_args.kwargs.get("use_llm") is False)


def check_ui_and_api_forwarding():
    with patch.object(ui_chat.llm, "is_ready", return_value=True):
        state = ui_chat._new_session()
    check("Gradio 新会话在模型就绪时默认开启润色",
          state["context"]["use_llm"] is True)
    with patch.object(ui_chat.llm, "is_ready", return_value=False):
        state = ui_chat._new_session()
    check("Gradio 新会话在模型未配置时保持关闭",
          state["context"]["use_llm"] is False)

    with patch("modules.m1_map.query", return_value={
            "ok": True, "品类": "儿童玩具", "市场": "欧盟",
            "primary": [], "cross": [], "llm": {"ok": True}}) as query:
        web_app._tool_map({"category": "儿童玩具", "market": "欧盟", "use_llm": True})
    check("SPA /api/tool/map 透传 use_llm", query.call_args.kwargs.get("use_llm") is True)

    with patch("modules.m3_todo.query", return_value={
            "ok": True, "品类": "儿童玩具", "市场": "欧盟",
            "动作": [], "分组": [], "llm": {"ok": True}}) as query:
        web_app._tool_todo({"category": "儿童玩具", "market": "欧盟", "use_llm": True})
    check("SPA /api/tool/todo 透传 use_llm", query.call_args.kwargs.get("use_llm") is True)

    with patch("modules.m2_timeline.query", return_value={
            "ok": True, "品类": "儿童玩具", "市场": "欧盟",
            "近窗内": [], "即将发生": [], "llm": {"ok": True}}) as query:
        web_app._tool_timeline({"category": "儿童玩具", "market": "欧盟", "use_llm": True})
    check("SPA /api/tool/timeline 透传 use_llm", query.call_args.kwargs.get("use_llm") is True)

    with patch("modules.m15_router.route", return_value={
            "ok": False, "reason": "no_slots", "识别": {}}) as route:
        web_app._route_payload("毛绒玩具卖到欧盟", "", True)
    check("SPA /api/route 透传 use_llm", route.call_args.kwargs.get("use_llm") is True)


def _fake_recall():
    return {
        "ok": True,
        "reason": "",
        "route": {
            "ok": True, "laws": ["EU:32025R2509"], "facets": ["CE marking"],
            "route_via": "模型路由", "catalog_gaps": [], "invalid_refs": [],
        },
        "retrieval": {
            "ok": True, "coverage": "partial", "gaps": [], "invalid_refs": [],
            "selected": [{
                "citation_id": "c1", "node_id": "rc|EU:32025R2509|u16",
                "law_id": "EU:32025R2509", "heading": "Article 17 — CE marking",
                "path": "EU:32025R2509 > Article 17",
                "locator": "https://eur-lex.europa.eu/eli/reg/2025/2509/oj",
                "body": "The CE marking shall be affixed visibly, legibly and indelibly.",
                "facet": "CE marking", "why": "",
            }],
        },
        "tree_version": "test-tree",
        "latency_ms": 1,
        "cached": False,
    }


def check_recall_in_conversation():
    check("条文问题被识别为 recall 意图",
          conversation._intent("这条法规原文第 17 条怎么规定？") == "recall")
    check("普通法规目录问题仍走 map",
          conversation._intent("儿童玩具卖到欧盟有哪些法规要求？") == "map")

    context = {"category": "", "market": "", "product": "毛绒玩具",
               "markets": [], "window": "近 12 个月", "use_llm": True}
    with patch.object(conversation.llm, "is_ready", return_value=True), \
            patch("modules.recall_flow.run", return_value=_fake_recall()) as run:
        conversation._call("recall", dict(context), query="毛绒玩具欧盟安全测试原文")
    check("conversation recall 调用两层召回并透传 use_llm",
          run.called and run.call_args.kwargs.get("use_llm") is True)

    result = conversation._normalize("recall", dict(context), _fake_recall())
    check("recall 结果生成条文条目",
          result["kind"] == "recall" and len(result["items"]) == 1)
    check("recall 片段保留官方定位",
          result["items"][0]["sources"][0]["url"].startswith("https://eur-lex.europa.eu"))
    check("recall 不把片段说成适用性审核",
          any("适用性" in gap for gap in result["gaps"]))


def check_spa_search_recall():
    with patch("core.law_store.retrieve", return_value={
            "ok": False, "reason": "请输入完整 CELEX", "units": []}), \
            patch("modules.recall_flow.run", return_value=_fake_recall()):
        data = web_app._search_payload("毛绒玩具出口欧盟要做哪些安全测试", "")
    check("SPA 编号查询失败后自动走两层召回",
          data["ok"] and data["mode"] == "recall" and len(data["units"]) == 1)
    check("SPA 召回片段带官方原文定位",
          data["units"][0]["source_url"].startswith("https://eur-lex.europa.eu"))


def check_spa_requests():
    api_js = (PROJECT / "web" / "js" / "api.js").read_text(encoding="utf-8")
    data_js = (PROJECT / "web" / "js" / "data.js").read_text(encoding="utf-8")
    check("SPA 路由请求默认 use_llm=true", "useLLM = true" in api_js)
    check("SPA 工具请求为 M1/M2/M3 带 use_llm",
          "params.use_llm = true" in data_js)


def main():
    check_m2_key_alignment()
    check_m2_integration()
    check_module_defaults_and_calls()
    check_conversation_forwarding()
    check_ui_and_api_forwarding()
    check_recall_in_conversation()
    check_spa_search_recall()
    check_spa_requests()
    print("LLM layers: PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}")
        raise
