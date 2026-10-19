"""Offline checks for the real Gradio/conversation boundary; no browser required.

These exercise startup, the submission/voice/export boundary, and whether nested
service results reach actionable UI cards. They do not certify browser layout.
"""
from __future__ import annotations

from contextlib import ExitStack
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

import gradio as gr
from core import conversation
import ui_chat


class ChatUITests(unittest.TestCase):
    def test_clause_render_retains_source_version_and_truncation(self):
        text = ui_chat.clause_markdown({"ok": True, "law_id": "EU:32009L0048", "reason": "抽取文本",
            "units": [{"heading": "Article 1", "body": "<script>test</script>",
                       "source_url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32009L0048",
                       "locator": "https://example.invalid/#art1", "version_date": None,
                       "parse_status": "extracted_unreviewed", "truncated": True}]})
        self.assertIn("eur-lex.europa.eu", text)
        self.assertIn("extracted_unreviewed", text)
        self.assertIn("未记录", text)
        self.assertIn("部分正文", text)
        self.assertNotIn("<script>", text)

    def test_build_does_not_execute_queries_or_call_a_model(self):
        with ExitStack() as stack:
            probes = [stack.enter_context(patch.object(module, "query", side_effect=AssertionError("eager query")))
                      for module in (conversation.m1_map, conversation.m2_timeline,
                                     conversation.m3_todo, conversation.m4_compare,
                                     conversation.m5_compare, conversation.m6_multi_region,
                                     conversation.m7_opc_readiness)]
            model = stack.enter_context(patch.object(conversation.llm, "chat", side_effect=AssertionError("eager model")))
            stack.enter_context(patch.object(ui_chat.asr, "config_summary", return_value={"enabled": False}))
            stack.enter_context(patch.object(ui_chat.law_store, "status", return_value={"ok": False, "reason": "测试缺库"}))
            demo = ui_chat.build_ui()
        self.assertTrue(demo.config["components"])
        self.assertTrue(demo.fns)
        self.assertTrue(all(probe.call_count == 0 for probe in probes))
        self.assertEqual(model.call_count, 0)
        self.assertEqual({action for action, _, _ in ui_chat.CAPABILITIES},
                         {"map", "todo", "timeline", "compare", "multi", "readiness", "model"})
        textboxes = [component for component in demo.config["components"] if component["type"] == "textbox"]
        self.assertTrue(any(item["props"].get("value", "") == "" for item in textboxes))

    def test_submit_uses_one_service_call_and_preserves_the_input_session(self):
        state = conversation.new_session()
        before = copy.deepcopy(state)
        with patch.object(conversation, "_call", wraps=conversation._call) as service:
            output = ui_chat.submit_message("儿童玩具卖到欧盟，先看法规", state)
        self.assertEqual(service.call_count, 1)
        self.assertEqual(state, before)
        self.assertEqual(output[1]["kind"], "map")
        self.assertEqual(output[0]["active_result_id"], output[1]["id"])
        self.assertEqual(output[6], "")
        self.assertEqual(len(output), 11)
        # The blank-input path receives a list of result snapshots as in production.
        empty = ui_chat.submit_message("", output[0])
        self.assertEqual(empty[1]["id"], output[1]["id"])
        self.assertEqual(empty[0]["results"], output[0]["results"])

    def test_service_failure_preserves_input_for_retry(self):
        state = conversation.new_session()
        with patch.object(conversation, "respond", side_effect=RuntimeError("private endpoint data")):
            output = ui_chat.submit_message("我的原问题", state)
        self.assertIs(output[0], state)
        self.assertEqual(output[6], "我的原问题")
        self.assertNotIn("private endpoint", str(output))
        self.assertIsNone(output[1])

    def test_voice_only_fills_the_textbox_and_failure_keeps_old_text(self):
        with patch.object(conversation, "respond", side_effect=AssertionError("automatic voice query")):
            with patch.object(ui_chat.asr, "transcribe", return_value=("儿童玩具卖到欧盟", {"ok": True})):
                text, note = ui_chat.transcribe("test.wav", "原输入")
                self.assertEqual(text, "儿童玩具卖到欧盟")
                self.assertIn("尚未", note)
            with patch.object(ui_chat.asr, "transcribe", return_value=("", {"ok": False})):
                text, note = ui_chat.transcribe("test.wav", "保留原输入")
                self.assertEqual(text, "保留原输入")

    def test_export_uses_saved_result_and_rejects_changed_conditions(self):
        state, result = conversation.respond("儿童玩具卖到欧盟", action="map")
        created = []
        try:
            with patch.object(conversation, "_call", side_effect=AssertionError("export reran service")):
                download, notice = ui_chat.prepare_export(state, result)
                path = Path(download["value"])
                created.append(path)
                payload = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(payload["id"], result["id"])
                self.assertEqual(payload["context"], result["context"])
                self.assertIn("已生成", notice)
                changed = copy.deepcopy(state)
                changed["context"]["market"] = "美国"
                refused, notice = ui_chat.prepare_export(changed, result)
                self.assertFalse(refused["visible"])
                self.assertIsNone(refused["value"])
                self.assertIn("变化", notice)
        finally:
            # Remove only files and empty directories created by this test call.
            for path in created:
                path.unlink(missing_ok=True)
                path.parent.rmdir()

    def test_comparison_renders_each_nested_law_with_its_sources(self):
        state, result = conversation.respond("比较儿童玩具在欧盟和美国的法规", action="compare")
        leaves = [item for region in result["items"] for item in region["details"]["items"]]
        self.assertGreater(len(leaves), 2)
        self.assertTrue(all(item["sources"] for item in leaves))
        rendered = []
        with gr.Blocks():
            components = [gr.State(state), gr.State(result), gr.Markdown()]
            with patch.object(ui_chat, "_item_card", side_effect=lambda item, *args, **kwargs: rendered.append(item)):
                ui_chat._comparison(result["raw"], result["items"], result["id"], *components)
        self.assertTrue({item["id"] for item in leaves}.issubset({item["id"] for item in rendered}),
                        "Regional summaries must expand into each law card and source.")

    def test_natural_export_returns_download_without_requerying(self):
        state, result = conversation.respond("儿童玩具卖到欧盟", action="todo")
        created = None
        try:
            with patch.object(conversation, "_call", side_effect=AssertionError("export reran service")):
                output = ui_chat.submit_message("导出当前待办", state)
            self.assertEqual(output[1]["id"], result["id"])
            self.assertTrue(output[8]["visible"])
            created = Path(output[8]["value"])
            self.assertGreater(created.stat().st_size, 30)
        finally:
            if created:
                created.unlink(missing_ok=True)
                created.parent.rmdir()

    def test_journey_tasks_allow_self_report_with_the_real_result_id(self):
        state, result = conversation.respond("毛绒玩具卖到德国亚马逊", action="journey")
        expected = {task["id"] for stage in result["stages"] for task in stage["tasks"]
                    if task.get("can_complete", True) and task.get("status") not in ("excluded", "historical")}
        self.assertTrue(expected)
        rendered = []

        def record(item, rid, index, *components, **kwargs):
            rendered.append((item["id"], rid, kwargs.get("allow_complete", False)))

        with gr.Blocks():
            components = [gr.State(state), gr.State(result), gr.Markdown()]
            with patch.object(ui_chat, "_item_card", side_effect=record):
                ui_chat._stages(result, *components)
        available = {iid for iid, rid, allowed in rendered if rid == result["id"] and allowed}
        self.assertTrue(expected.issubset(available),
                        "Journey progress buttons must target the stored result, not a stage component key.")

    def test_multi_region_expands_the_normalized_source_cards(self):
        state, result = conversation.respond("儿童玩具在欧盟和美国一起看", action="multi")
        expected = {leaf["id"] for region in result["items"] for leaf in region["details"]["items"]}
        self.assertTrue(expected)
        rendered = []
        with gr.Blocks():
            components = [gr.State(state), gr.State(result), gr.Markdown()]
            with patch.object(ui_chat, "_item_card", side_effect=lambda item, *args, **kwargs: rendered.append(item)):
                for region in result["items"]:
                    ui_chat._region_cards(region, result["id"], *components)
        self.assertTrue(expected.issubset({item["id"] for item in rendered}))
        self.assertTrue(all(item["sources"] for item in rendered))

    def test_readiness_exposes_tasks_and_explains_a_pending_market(self):
        initial = conversation.new_session()
        initial["context"].update(category="儿童玩具", product="儿童玩具", market="欧盟", markets=["欧盟", "美国"])
        state, result = conversation.respond("", initial, action="readiness")
        expected = {item["id"] for item in result["items"]}
        self.assertTrue(expected)
        rendered, text = [], []

        def record(item, rid, index, *components, **kwargs):
            rendered.append((item["id"], rid, kwargs.get("allow_complete", False)))

        markdown, html = gr.Markdown, gr.HTML
        with gr.Blocks():
            components = [gr.State(state), gr.State(result), gr.Markdown()]
            with patch.object(ui_chat, "_item_card", side_effect=record), \
                    patch.object(gr, "Markdown", side_effect=lambda value="", **kw: (text.append(str(value)), markdown(value, **kw))[1]), \
                    patch.object(gr, "HTML", side_effect=lambda value="", **kw: (text.append(str(value)), html(value, **kw))[1]):
                ui_chat._stages(result, *components)
        self.assertTrue(expected.issubset({iid for iid, rid, allowed in rendered if rid == result["id"] and allowed}))
        self.assertIn("美国", " ".join(text))
        self.assertRegex(" ".join(text), "待核对|未核对|暂无可生成")

    def test_journey_platform_filter_filters_tasks_inside_stages(self):
        state, result = conversation.respond("毛绒玩具卖到德国亚马逊", action="journey")
        expected = {task["id"] for stage in result["items"] for task in stage["details"].get("tasks", [])
                    if "平台" in str(task.get("details", {}).get("kind", task.get("kind", "")))}
        self.assertTrue(expected)
        rendered = []
        with gr.Blocks():
            components = [gr.State(state), gr.State(result), gr.Markdown()]
            with patch.object(ui_chat, "_item_card", side_effect=lambda item, *args, **kwargs: rendered.append(item)):
                ui_chat._stages(result, *components, selection="平台规则")
        self.assertEqual({item["id"] for item in rendered}, expected)

    def test_edit_country_clears_german_scope_and_preserves_the_journey_view(self):
        state, result = conversation.respond("毛绒玩具卖到德国亚马逊", action="journey")
        demo = ui_chat.build_ui()
        edit = next(item.fn for item in demo.fns.values()
                    if item.fn and item.fn.__name__ == "update_conditions")
        with patch.object(ui_chat, "submit_message", side_effect=lambda text, session, action: (session, action)):
            updated, action = edit(state, None, None, "法国", None, None, None,
                                   "近 12 个月", ["欧盟"], False)
        self.assertEqual(updated["context"]["country"], "法国")
        self.assertNotEqual(updated["context"]["site"], "德国站")
        self.assertEqual(action, "journey")
        self.assertEqual(state["context"]["country"], "德国")

    def test_scope_labels_escape_user_html(self):
        rendered = ui_chat.context_html({"product": '<img src=x onerror="alert(1)">', "market": "欧盟"})
        self.assertNotIn("<img", rendered)
        self.assertIn("&lt;img", rendered)


if __name__ == "__main__":
    unittest.main(verbosity=2)
