# -*- coding: utf-8 -*-
"""Offline integration checks for real module routing and session boundaries.

Run from the project root: python scripts/selftest_conversation.py
Only model availability and malformed-model scenarios are stubbed. Actual local
data, all seven modules, filters, task identities and exports are exercised.
"""
from __future__ import annotations

import copy
import csv
import io
import json
import os
import sys
import unittest
from unittest.mock import patch

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)

from core import conversation as service  # noqa: E402


class ConversationTests(unittest.TestCase):
    def test_positive_guidance_answers_keep_route_and_parse_chinese_fba(self):
        state, result = service.respond("儿童玩具卖到德国亚马逊，从哪里开始")
        for text in ("适用年龄3岁以上", "这款产品不带电", "采用FBA发货"):
            state, result = service.respond(text, state)
            self.assertEqual(result["kind"], "journey")
        self.assertEqual(state["context"]["age"], "3岁以上")
        self.assertFalse(state["context"]["electric"])
        self.assertEqual(state["context"]["fulfillment"], "FBA")
        self.assertEqual(result["follow_up"], [])

    def test_guidance_asks_one_unknown_and_keeps_real_route(self):
        state, result = service.respond("儿童玩具卖到德国亚马逊，从哪里开始")
        self.assertEqual(result["kind"], "journey")
        self.assertEqual(len(result["stages"]), 6)
        self.assertEqual([q["field"] for q in result["follow_up"]], ["age"])
        state, result = service.respond("年龄暂不确定", state)
        self.assertEqual(state["context"]["age"], "")
        self.assertEqual(result["follow_up"][0]["field"], "electric")
        state, result = service.respond("是否带电暂不确定", state)
        self.assertIsNone(state["context"]["electric"])
        self.assertEqual(result["follow_up"][0]["field"], "fulfillment")
        state, result = service.respond("采用自行发货", state)
        self.assertEqual(state["context"]["fulfillment"], "自发货")
        self.assertEqual(result["follow_up"], [])
        state, result = service.respond("另一款产品是木制玩具", state)
        self.assertEqual(result["follow_up"][0]["field"], "age")

    def test_guidance_does_not_replace_law_queries_or_leak_market(self):
        state, result = service.respond("儿童玩具卖到德国亚马逊，只看法规")
        self.assertEqual(result["kind"], "map")
        self.assertEqual(result["follow_up"], [])
        state, result = service.respond("改卖美国，先看待办", state)
        self.assertEqual(result["follow_up"], [])
        self.assertEqual(result["next_actions"], [])

    def test_next_action_preview_uses_real_tasks_and_refreshes_after_completion(self):
        state, result = service.respond("3岁以上不带电玩具卖到德国亚马逊，从哪里开始")
        actions = result["next_actions"]
        self.assertGreater(len(actions), 0)
        self.assertLessEqual(len(actions), 3)
        tasks = {task["id"]: task for task in service._all_tasks(result)}
        for action in actions:
            self.assertEqual(action["sources"], tasks[action["task_id"]]["sources"])
            self.assertFalse(tasks[action["task_id"]]["details"]["blocked_by"])
        completed = actions[0]["task_id"]
        state, result = service.complete_task(state, result["id"], completed)
        self.assertNotIn(completed, [a["task_id"] for a in result["next_actions"]])
        self.assertFalse(state["context"]["completed"][completed]["evidence_verified"])

    def start(self, text="3岁以上不带电毛绒玩具卖到德国亚马逊德国站，先看待办"):
        return service.respond(text, service.new_session())

    def test_independent_sessions_and_immutable_caller(self):
        first, second = service.new_session(), service.new_session()
        before = copy.deepcopy(first)
        changed, result = service.respond("玩具卖到美国，查看法规", first)
        self.assertEqual(first, before)
        self.assertEqual(second["messages"], [])
        self.assertFalse(second["context"]["category"])
        self.assertNotEqual(changed["id"], second["id"])
        self.assertEqual(result["kind"], "map")

    def test_directory_has_seven_entries_without_query(self):
        with patch.object(service.m1_map, "query", side_effect=AssertionError("must not query")):
            state, result = self.start("你能做什么")
        self.assertEqual(result["kind"], "capabilities")
        self.assertEqual(len(result["actions"]), 7)
        self.assertEqual(state["context"]["category"], "")

    def test_long_input_is_rejected_without_silent_context_truncation(self):
        original = service.new_session()
        state, result = service.respond("玩具" * 3001 + "卖到德国", original)
        self.assertEqual(result["kind"], "error")
        self.assertIn("6000", result["summary"])
        self.assertEqual(state["context"], original["context"])

    def test_required_followup_remembers_intent(self):
        state, result = self.start("我想查玩具法规")
        self.assertEqual(result["kind"], "question")
        self.assertEqual(state["pending_action"], "map")
        state, result = service.respond("美国", state)
        self.assertEqual(result["kind"], "map")
        self.assertEqual(result["context"]["category"], "儿童玩具")

    def test_regulations_do_not_require_platform(self):
        state, result = self.start("儿童玩具卖到欧盟，只看法规，我还没选平台")
        self.assertEqual(result["kind"], "map")
        self.assertEqual(state["context"]["platform"], "")
        self.assertEqual(state["context"]["country"], "")

    def test_each_original_module_has_real_path(self):
        for action in ("map", "todo", "timeline", "compare", "multi", "readiness", "model"):
            with self.subTest(action=action):
                state, _ = self.start()
                state, result = service.respond("", state, action=action)
                self.assertEqual(result["kind"], action)
                self.assertIsInstance(result["raw"], dict)
                self.assertNotEqual(result["raw"].get("ok"), False)
                self.assertTrue(result["data_version"]["snapshot"])
                self.assertTrue(result["context_fingerprint"])

    def test_text_and_button_share_same_business_data(self):
        state, _ = self.start()
        _, text_result = service.respond("先看待办", state)
        _, button_result = service.respond("", state, action="todo")
        self.assertEqual(text_result["raw"], button_result["raw"])
        self.assertEqual([item["id"] for item in text_result["items"]],
                         [item["id"] for item in button_result["items"]])

    def test_known_mismatches_are_quarantined_in_every_view(self):
        for action in ("map", "todo", "timeline", "compare", "multi", "readiness"):
            with self.subTest(action=action):
                state, _ = self.start()
                _, result = service.respond("", state, action=action)
                raw = copy.deepcopy(result["raw"])
                source_raw = raw.pop("source_raw", None)
                rendered = json.dumps(raw, ensure_ascii=False, default=str)
                self.assertNotIn("2023/1670", rendered)
                self.assertNotIn("2011/1169", rendered)
                self.assertNotIn("1994/11", rendered)
                if action in ("map", "todo", "compare", "multi", "readiness"):
                    self.assertTrue(result["excluded"])
                    self.assertIsNotNone(source_raw)
                    self.assertTrue(all(not item["can_complete"] for item in result["excluded"]))
                if action in ("todo", "readiness"):
                    self.assertNotIn("Directive 2001/95", rendered)

    def test_new_toy_law_is_not_general_immediate_application(self):
        _, result = self.start("儿童玩具卖到欧盟，查看法规")
        records = result["items"]
        new = next(item for item in records if "2025/2509" in str(item["details"]))
        self.assertEqual(new["status"], "condition_pending")
        self.assertTrue(any("2030-08-01" in gap for gap in new["gaps"]))
        old = next(item for item in records if "2009/48" in str(item["details"]))
        self.assertNotEqual(old["status"], "historical")

    def test_complete_is_self_report_and_does_not_touch_source_raw(self):
        state, result = self.start()
        raw = copy.deepcopy(result["raw"])
        task = result["items"][0]
        changed, updated = service.complete_task(state, result["id"], task["id"])
        self.assertEqual(updated["items"][0]["status"], "user_reported_done")
        self.assertEqual(updated["raw"].get("source_raw", updated["raw"]), raw.get("source_raw", raw))
        self.assertFalse(changed["context"]["completed"][task["id"]]["evidence_verified"])
        self.assertEqual(result["items"][0]["status"], "condition_pending")

    def test_complete_survives_same_product_view_change(self):
        state, result = self.start()
        original = next(item for item in result["items"] if item.get("aliases"))
        item_id = original["id"]
        state, _ = service.complete_task(state, result["id"], item_id)
        state, ready = service.respond("", state, action="readiness")
        task = next(item for item in ready["items"] if item["id"] in original["aliases"])
        self.assertEqual(task["status"], "user_reported_done")

    def test_pilot_todo_keeps_six_stages_and_platform_tasks(self):
        state, result = self.start()
        self.assertEqual(result["kind"], "todo")
        self.assertEqual(len(result["stages"]), 6)
        self.assertTrue(all(stage["tasks"] for stage in result["stages"]))
        tasks = result["items"]
        self.assertTrue(any(task["id"] == "amazon-account-docs" for task in tasks))
        self.assertTrue(any("平台规则" in task["information_type"] for task in tasks))
        self.assertTrue(any("操作建议" in task["information_type"] for task in tasks))
        self.assertTrue(any("法律要求" in task["information_type"] for task in tasks))
        self.assertNotIn("journey", result["raw"]["source_raw"])
        self.assertIn("动作", result["raw"]["source_raw"])
        self.assertEqual(result["data_version"]["journey"], result["raw"]["journey"]["version"])
        self.assertEqual(result["data_version"]["sources_retrieved_on"], result["raw"]["journey"]["retrieved_on"])

    def test_pilot_completion_is_shared_between_todo_and_journey(self):
        state, todo = self.start()
        task_id = "amazon-account-docs"
        state, _ = service.complete_task(state, todo["id"], task_id)
        state, route = service.respond("", state, action="journey")
        task = next(task for stage in route["stages"] for task in stage["tasks"] if task["id"] == task_id)
        self.assertEqual(task["status"], "user_reported_done")
        state, route = service.complete_task(state, route["id"], task_id)
        state, todo = service.respond("", state, action="todo")
        task = next(task for task in todo["items"] if task["id"] == task_id)
        self.assertNotEqual(task["status"], "user_reported_done")
        state, route = service.respond("", state, action="journey")
        state, _ = service.complete_task(state, route["id"], "toy-scope")
        state, todo = service.respond("", state, action="todo")
        task = next(task for task in todo["items"] if task["id"] == "toy-scope")
        self.assertEqual(task["group"], "用户自述已完成")

    def test_pilot_csv_exports_every_visible_task_without_requery(self):
        state, todo = self.start()
        with patch.object(service.m3_todo, "query", side_effect=AssertionError("must not query")), \
                patch("core.journey.query", side_effect=AssertionError("must not query")):
            filename, payload = service.export_result(state, todo["id"])
        rows = list(csv.DictReader(io.StringIO(payload.decode("utf-8-sig"))))
        self.assertEqual(len(rows), len(todo["items"]))
        for task in todo["items"]:
            self.assertTrue(any(row["动作"].startswith(task["title"]) for row in rows))
        self.assertTrue(any("平台规则" in row["适用条件"] for row in rows))
        self.assertTrue(all(len(row) == 10 for row in rows))

    def test_explicit_preparation_stage_changes_next_group(self):
        state, selection = self.start()
        next_selection = {task["id"] for task in selection["items"] if task["group"] == "下一步"}
        state["context"]["stage"] = "主体与税务准备"
        state, business = service.respond("", state, action="todo")
        next_business = {task["id"] for task in business["items"] if task["group"] == "下一步"}
        self.assertNotEqual(next_selection, next_business)
        self.assertIn("amazon-account-docs", next_business)
        state["context"]["stage"] = "商品刊登与提交"
        state, listing = service.respond("", state, action="todo")
        submission = next(task for task in listing["items"] if task["id"] == "amazon-compliance-submission")
        self.assertNotEqual(submission["group"], "下一步")
        self.assertTrue(submission["details"]["blocked_by"])

    def test_non_pilot_todo_retains_original_module_path(self):
        state, result = self.start("毛绒玩具卖到美国，先看待办")
        self.assertEqual(result["kind"], "todo")
        self.assertNotIn("journey", result["raw"])
        self.assertFalse(any(task["id"].startswith("amazon-") for task in result["items"]))

    def test_completion_can_be_withdrawn_without_approving_evidence(self):
        state, result = self.start()
        item_id = result["items"][0]["id"]
        state, _ = service.complete_task(state, result["id"], item_id)
        state, result = service.complete_task(state, result["id"], item_id)
        self.assertFalse(state["context"]["completed"])
        self.assertEqual(result["items"][0]["status"], "condition_pending")
        self.assertTrue(result["items"][0]["gaps"])

    def test_market_switch_clears_german_site_and_completion(self):
        state, original = self.start()
        state, _ = service.complete_task(state, original["id"], original["items"][0]["id"])
        state, changed = service.respond("改卖美国呢", state)
        self.assertEqual(changed["kind"], "todo")
        self.assertEqual(state["context"]["market"], "美国")
        self.assertEqual(state["context"]["country"], "")
        self.assertEqual(state["context"]["site"], "")
        self.assertFalse(state["context"]["completed"])
        self.assertEqual(state["context"]["age"], "3岁以上")
        self.assertIs(state["context"]["electric"], False)
        with self.assertRaises(ValueError):
            service.complete_task(state, original["id"], original["items"][0]["id"])

    def test_negated_country_is_not_retained_as_current_route(self):
        for text, country in (("不是德国，是法国", "法国"), ("不卖德国，卖意大利", "意大利"),
                              ("德国不要了，改西班牙", "西班牙")):
            with self.subTest(text=text):
                state, _ = self.start("毛绒玩具卖到德国亚马逊德国站，查看全流程")
                state, result = service.respond(text, state)
                self.assertEqual(state["context"]["country"], country)
                self.assertEqual(state["context"]["site"], "")
                self.assertFalse(result["raw"]["route_supported"])
                self.assertFalse(any(task["id"] == "german-packaging"
                                     for stage in result["stages"] for task in stage["tasks"]))

    def test_negated_market_corrections_work_both_directions(self):
        state, _ = self.start()
        state, result = service.respond("不是欧盟，是美国", state)
        self.assertEqual(state["context"]["market"], "美国")
        self.assertEqual(state["context"]["country"], "")
        state, result = service.respond("不卖美国，卖德国", state)
        self.assertEqual(state["context"]["market"], "欧盟")
        self.assertEqual(state["context"]["country"], "德国")
        state, result = service.respond("不是日本，是德国", state)
        self.assertNotEqual(result["kind"], "unsupported")
        self.assertEqual(state["context"]["country"], "德国")

    def test_negated_platform_cannot_keep_german_amazon_tasks(self):
        state, _ = self.start("毛绒玩具卖到德国亚马逊德国站，查看全流程")
        state, result = service.respond("不是亚马逊，是独立站", state)
        self.assertEqual(state["context"]["platform"], "独立站")
        self.assertEqual(state["context"]["site"], "")
        self.assertFalse(result["raw"]["route_supported"])
        self.assertFalse(any(task["id"].startswith("amazon-")
                             for stage in result["stages"] for task in stage["tasks"]))

    def test_context_panel_market_change_cannot_leak_completion(self):
        state, result = self.start()
        state, _ = service.complete_task(state, result["id"], result["items"][0]["id"])
        state["context"].update(market="美国", country="", site="", markets=["美国"])
        state, changed = service.respond("", state, action="todo")
        self.assertFalse(state["context"]["completed"])
        self.assertTrue(all(item["status"] != "user_reported_done" for item in changed["items"]))

    def test_new_product_does_not_inherit_report_or_age(self):
        state, result = self.start()
        state, _ = service.respond("我已经有检测报告", state)
        self.assertTrue(state["context"]["reports"])
        state, changed = service.respond("另一个产品是木制玩具", state)
        self.assertEqual(state["context"]["category"], "儿童玩具")
        self.assertEqual(state["context"]["age"], "")
        self.assertIsNone(state["context"]["electric"])
        self.assertFalse(state["context"]["reports"])
        self.assertFalse(state["context"]["completed"])
        self.assertEqual(state["context"]["materials"], "木制")

    def test_product_features_do_not_switch_product_category(self):
        state, _ = self.start()
        state, result = service.respond("带电池和蓝牙遥控，6岁以上", state)
        self.assertEqual(state["context"]["category"], "儿童玩具")
        self.assertTrue(state["context"]["electric"])
        self.assertEqual(state["context"]["age"], "6岁以上")
        self.assertEqual(state["context"]["product_revision"], 0)

    def test_report_name_does_not_confirm_or_switch_market(self):
        state, result = self.start("玩具，有EN71报告，查看法规")
        self.assertEqual(result["kind"], "question")
        self.assertEqual(state["context"]["market"], "")
        state, _ = self.start("玩具卖到美国，查看法规")
        state, _ = service.respond("还有CE认证", state)
        self.assertEqual(state["context"]["market"], "美国")

    def test_self_report_does_not_auto_complete_a_task(self):
        state, result = self.start()
        state, changed = service.respond("已有检测报告", state)
        self.assertTrue(state["context"]["reports"])
        self.assertFalse(state["context"]["completed"])
        self.assertTrue(any("未验证" in gap for gap in changed["gaps"]))
        state, _ = service.respond("我还没有检测报告", service.new_session())
        self.assertFalse(state["context"]["reports"])

    def test_unsupported_market_is_not_silently_mapped(self):
        state, _ = self.start()
        state, result = service.respond("改卖日本呢", state)
        self.assertEqual(result["kind"], "unsupported")
        self.assertEqual(state["context"]["market"], service.m15_router.OOS)
        _, mixed = self.start("玩具卖到美国和日本，比较市场")
        self.assertEqual(mixed["kind"], "unsupported")

    def test_unsupported_category_is_not_toy(self):
        _, result = self.start("汽车零部件卖到德国，法规")
        self.assertEqual(result["kind"], "unsupported")

    def test_timeline_window_is_reused(self):
        state, _ = self.start()
        state, result = service.respond("最近半年有哪些变化", state)
        self.assertEqual(result["raw"]["window_months"], 6)
        state, result = service.respond("", state, action="timeline")
        self.assertEqual(result["raw"]["window_months"], 6)

    def test_compare_does_not_switch_current_market(self):
        state, _ = self.start()
        state, result = service.respond("比较欧盟和美国的市场差异", state)
        self.assertEqual(result["kind"], "compare")
        self.assertEqual(state["context"]["market"], "欧盟")
        self.assertEqual(state["context"]["country"], "德国")
        self.assertEqual(len(result["raw"]["区域"]), 2)

    def test_export_uses_existing_raw_and_preserves_original_csv(self):
        state, result = self.start()
        with patch.object(service.m3_todo, "query", side_effect=AssertionError("must not requery")):
            filename, payload = service.export_result(state, result["id"])
        self.assertTrue(filename.endswith(".csv"))
        rows = list(csv.reader(io.StringIO(payload.decode("utf-8-sig"))))
        self.assertEqual(len(rows[0]), 10)
        self.assertEqual(len(rows) - 1, len(result["items"]))
        self.assertNotIn("2023/1670", payload.decode("utf-8-sig"))
        self.assertNotIn("2001/95", payload.decode("utf-8-sig"))
        self.assertIn("条件待确认", payload.decode("utf-8-sig"))

    def test_export_rejects_stale_and_changed_context(self):
        state, result = self.start()
        state["context"]["market"] = "美国"
        with self.assertRaises(ValueError):
            service.export_result(state, result["id"])
        state, changed = service.respond("", state, action="map")
        with self.assertRaises(ValueError):
            service.export_result(state, result["id"])
        filename, payload = service.export_result(state, changed["id"])
        exported = json.loads(payload)
        self.assertEqual(exported["id"], changed["id"])
        self.assertEqual(exported["raw"], changed["raw"])

    def test_export_text_keeps_active_business_result(self):
        state, result = self.start()
        state, result = service.respond("导出", state)
        self.assertTrue(result["export_requested"])
        filename, payload = service.export_result(state, result["id"])
        self.assertTrue(filename.endswith(".csv"))
        self.assertGreater(len(payload), 0)

    def test_natural_export_with_task_noun_keeps_existing_result(self):
        state, original = self.start()
        with patch.object(service.m3_todo, "query", side_effect=AssertionError("must not requery")), \
                patch("core.journey.query", side_effect=AssertionError("must not requery")):
            state, result = service.respond("请帮我导出当前待办", state)
        self.assertEqual(result["id"], original["id"])
        self.assertTrue(result["export_requested"])
        self.assertEqual(state["active_result_id"], original["id"])

    def test_export_with_changed_market_does_not_export_old_route(self):
        state, original = self.start()
        state, result = service.respond("导出美国待办", state)
        self.assertEqual(result["kind"], "todo")
        self.assertEqual(result["context"]["market"], "美国")
        self.assertNotEqual(result["id"], original["id"])
        self.assertTrue(result["export_requested"])
        self.assertNotIn("journey", result["raw"])

    def test_export_explicit_view_does_not_use_different_active_kind(self):
        state, _ = self.start()
        state, original = service.respond("", state, action="map")
        state, result = service.respond("导出待办", state)
        self.assertEqual(result["kind"], "todo")
        self.assertTrue(result["export_requested"])
        self.assertNotEqual(result["id"], original["id"])

    def test_journey_completion_refreshes_groups_and_dependencies_immediately(self):
        state, _ = self.start()
        state["context"]["stage"] = "检测、标识与资料"
        state, result = service.respond("", state, action="journey")
        state, result = service.complete_task(state, result["id"], "toy-scope")
        tasks = {task["id"]: task for stage in result["stages"] for task in stage["tasks"]}
        self.assertEqual(tasks["toy-scope"]["group"], "用户自述已完成")
        self.assertEqual(tasks["toy-safety-docs"]["details"]["blocked_by"], [])
        self.assertEqual(tasks["toy-safety-docs"]["group"], "下一步")

    def test_conditional_task_stays_pending_after_requery_and_withdrawal(self):
        state, result = self.start()
        state, result = service.complete_task(state, result["id"], "amazon-category-access")
        state, result = service.respond("", state, action="todo")
        state, result = service.complete_task(state, result["id"], "amazon-category-access")
        task = next(task for task in result["items"] if task["id"] == "amazon-category-access")
        self.assertEqual(task["status"], "condition_pending")
        self.assertEqual(task["group"], "待确认")
        self.assertFalse(state["context"]["completed"])

    def test_report_correction_removes_previous_self_report(self):
        state, _ = self.start()
        state, _ = service.respond("已有检测报告", state)
        self.assertTrue(state["context"]["reports"])
        state, result = service.respond("刚才说错了，我还没有检测报告", state)
        self.assertFalse(state["context"]["reports"])
        self.assertFalse(any("你提到已有资料" in gap for gap in result.get("gaps", [])))

    def test_metadata_nodes_are_not_task_deadlines(self):
        state, result = self.start()
        for item in result["items"]:
            self.assertEqual(item["details"]["期限"], "待核验")
            self.assertEqual(item["details"]["紧迫度"], "待核验")
            self.assertNotIn("最晚不迟于", item["details"]["期限说明"])
        self.assertIn("source_raw", result["raw"])
        filename, payload = service.export_result(state, result["id"])
        self.assertIn("待核验", payload.decode("utf-8-sig"))

    def test_model_entry_does_not_require_business_setup(self):
        state, result = service.respond("", service.new_session(), action="model")
        self.assertEqual(result["kind"], "model")
        self.assertEqual(state["context"]["category"], "")
        self.assertEqual(state["context"]["market"], "")

    def test_default_and_buttons_do_not_call_model(self):
        with patch.object(service.m15_router, "parse_model", side_effect=AssertionError("must not call")):
            state, _ = self.start()
            state["context"]["use_llm"] = True
            _, result = service.respond("", state, action="todo")
            self.assertEqual(result["kind"], "todo")

    def test_model_failure_falls_back_without_stack_or_secret(self):
        state = service.new_session()
        state["context"]["use_llm"] = True
        with patch.object(service.llm, "is_ready", return_value=True), \
                patch.object(service.m15_router, "parse_model", side_effect=TimeoutError("SECRET")):
            state, result = service.respond("玩具", state)
        self.assertEqual(result["kind"], "question")
        self.assertEqual(state["context"]["category"], "儿童玩具")
        self.assertNotIn("SECRET", str(result))

    def test_model_extraction_cannot_invent_legal_items(self):
        state = service.new_session()
        state["context"]["use_llm"] = True
        slots = {"品类": "儿童玩具", "市场": "欧盟", "法规": "MADE-UP RULE"}
        with patch.object(service.llm, "is_ready", return_value=True), \
                patch.object(service.m15_router, "parse_model", return_value=(slots, {"ok": True})):
            state, result = service.respond("一款布偶的欧陆法规", state)
        self.assertEqual(result["kind"], "map")
        self.assertNotIn("MADE-UP RULE", str(result))
        self.assertTrue(result["understanding"]["model_used"])

    def test_replay_missing_is_honest(self):
        state, _ = self.start()
        _, result = service.respond("", state, action="model")
        if not result["raw"]["回放列表"]:
            self.assertIn("尚未生成", result["summary"])
            self.assertEqual(result["items"], [])

    def test_journey_has_six_stages_with_sources_and_gaps(self):
        state, result = self.start("3岁以上不带电毛绒玩具卖到德国亚马逊德国站，查看全流程")
        self.assertEqual(result["kind"], "journey")
        self.assertEqual(len(result["stages"]), 6)
        self.assertEqual(len(result["items"]), 6)
        self.assertEqual(result["data_version"]["journey"], result["raw"]["version"])
        self.assertEqual(result["data_version"]["sources_retrieved_on"], result["raw"]["retrieved_on"])
        for stage in result["stages"]:
            self.assertIn("tasks", stage)
            self.assertIn("gaps", stage)

    def test_beginner_start_question_switches_from_map_to_journey(self):
        state, previous = self.start("儿童玩具卖到欧盟，先看相关法规")
        self.assertEqual(previous["kind"], "map")
        for phrase in ("从哪开始", "从哪里开始", "如何开始"):
            with self.subTest(phrase=phrase):
                _, result = service.respond("我想把毛绒玩具卖到德国亚马逊，" + phrase + "？", state)
                self.assertEqual(result["kind"], "journey")
                self.assertEqual(len(result["stages"]), 6)
                self.assertEqual(result["context"]["country"], "德国")

    def test_non_german_journey_does_not_inherit_german_platform(self):
        state, _ = self.start()
        state, result = service.respond("改卖美国，查看全流程", state)
        self.assertEqual(result["kind"], "journey")
        self.assertFalse(result["raw"]["route_supported"])
        self.assertEqual(state["context"]["site"], "")
        self.assertTrue(result["gaps"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
