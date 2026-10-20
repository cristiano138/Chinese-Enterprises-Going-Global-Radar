"""SPA 前端行为与布局检查；需要 Playwright 与一个已启动的服务。

沿用 scripts/check_chat_browser.py 的范式：先起 app.py，再指定 --url。
本文件只做断言，不产生截图（截图与像素比对见 scripts/check_web_browser.py）。
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest

from playwright.sync_api import sync_playwright

PROJECT = Path(__file__).resolve().parent.parent
BASE = os.getenv("SELFTEST_WEB_URL", "http://127.0.0.1:7899")


class _Browser:
    """整个测试文件共用一次浏览器会话。"""

    _pw = None
    _browser = None
    page = None

    @classmethod
    def start(cls):
        if cls.page is not None:
            return
        cls._pw = sync_playwright().start()
        cls._browser = cls._pw.chromium.launch()
        ctx = cls._browser.new_context(viewport={"width": 390, "height": 844},
                                       locale="zh-CN", reduced_motion="reduce")
        cls.page = ctx.new_page()
        cls.page.goto(BASE, wait_until="load")
        cls.page.wait_for_timeout(400)

    @classmethod
    def goto(cls, route):
        cls.page.goto(f"{BASE}#/{route}", wait_until="load")
        cls.page.wait_for_timeout(250)
        return cls.page

    @classmethod
    def stop(cls):
        if cls._browser:
            cls._browser.close()
        if cls._pw:
            cls._pw.stop()


class TokenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Browser.start()

    def test_design_tokens_match_the_prototype(self):
        tokens = _Browser.page.evaluate(
            "() => { const cs = getComputedStyle(document.documentElement);"
            "return ['--paper','--brand','--brand-bright','--amber','--ink','--desk']"
            ".map(n => cs.getPropertyValue(n).trim()); }")
        self.assertEqual(tokens, ["#fafaf7", "#0e4d3a", "#177a57",
                                  "#e8a33d", "#12211b", "#e7ece8"])

    def test_esc_neutralises_html_in_user_input(self):
        got = _Browser.page.evaluate(
            "async () => { const m = await import('/web/js/dom.js');"
            "return m.esc('<img src=x onerror=alert(1)>\"&'); }")
        self.assertNotIn("<", got)
        self.assertIn("&lt;img", got)
        self.assertIn("&amp;", got)

    def test_ic_renders_an_svg_with_the_prototype_geometry(self):
        got = _Browser.page.evaluate(
            "async () => { const m = await import('/web/js/icons.js'); return m.ic('home'); }")
        self.assertIn('class="ic', got)
        self.assertIn('viewBox="0 0 24 24"', got)
        self.assertIn("M3 10.5 12 3l9 7.5", got)

    def test_injected_markup_is_not_parsed(self):
        """Review Focus 1：用户输入含 HTML 时不得被解析成元素。"""
        _Browser.page.evaluate(
            "async () => { const m = await import('/web/js/dom.js');"
            "const v = document.getElementById('view');"
            "v.innerHTML = '<div id=probe>' + m.esc('<b>粗体</b>') + '</div>'; }")
        probe = _Browser.page.locator("#probe")
        self.assertEqual(probe.inner_text(), "<b>粗体</b>")
        self.assertEqual(probe.locator("b").count(), 0)


class SampleDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Browser.start()

    def test_sample_tables_carry_the_prototype_shape(self):
        got = _Browser.page.evaluate("""async () => {
          const s = await import('/web/js/sample.js');
          return { items: Object.keys(s.ITEMS).length,
                   result: s.RESULT_ITEMS.length,
                   tools: Object.keys(s.TOOL_PAGES).length,
                   fresh: s.FRESH_ITEMS.length,
                   start: s.START.length,
                   sheets: Object.keys(s.PROFILE_SHEETS).length };
        }""")
        self.assertEqual(got["result"], 7)
        self.assertEqual(got["tools"], 8)
        self.assertEqual(got["fresh"], 4)
        self.assertEqual(got["start"], 4)
        self.assertEqual(got["sheets"], 7)
        self.assertEqual(got["items"], 14, "原型 ITEMS 恰好 14 个顶层键（939-1094 行）")

    def test_profile_sheets_are_actually_callable(self):
        """只数键名是假绿：七个函数体各自调用 ic()，缺导入则全抛 ReferenceError。"""
        got = _Browser.page.evaluate("""async () => {
          const s = await import('/web/js/sample.js');
          const out = {};
          for (const k of Object.keys(s.PROFILE_SHEETS)) {
            try { out[k] = s.PROFILE_SHEETS[k](); }
            catch (e) { out[k] = 'THREW: ' + e.message; }
          }
          return out;
        }""")
        self.assertEqual(len(got), 7)
        for key, html in got.items():
            with self.subTest(key=key):
                self.assertFalse(str(html).startswith("THREW"), f"{key} 抛异常：{html}")
                self.assertIn('class="sheet__body"', str(html))


class RenderHelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Browser.start()

    def test_row_html_uses_the_prototype_classes_and_action(self):
        got = _Browser.page.evaluate(
            "async () => { const r = await import('/web/js/render.js'); return r.rowHtml('toy'); }")
        self.assertIn('class="row"', got)
        self.assertIn('data-action="detail"', got)
        self.assertIn('data-id="toy"', got)
        self.assertIn("row__rail", got)
        self.assertIn("row__body", got)
        self.assertIn("type-chip", got)
        self.assertNotIn("row__copy", got)      # 先前那版计划自创的类名，必须不存在

    def test_row_html_escapes_the_title(self):
        got = _Browser.page.evaluate(
            "async () => { const r = await import('/web/js/render.js');"
            "const s = await import('/web/js/sample.js');"
            "const saved = s.ITEMS.toy.title;"
            "try { s.ITEMS.toy.title = '<img src=x onerror=alert(1)>';"
            "      return r.rowHtml('toy'); }"
            "finally { s.ITEMS.toy.title = saved; } }")
        self.assertNotIn("<img", got)
        self.assertIn("&lt;img", got)

    def test_row_html_returns_empty_for_an_unknown_id(self):
        """Review Focus 2：未知条目 id 不得抛异常。"""
        got = _Browser.page.evaluate(
            "async () => { const r = await import('/web/js/render.js'); return r.rowHtml('不存在'); }")
        self.assertEqual(got, "")

    def test_tool_card_uses_the_prototype_markup(self):
        got = _Browser.page.evaluate(
            "async () => { const r = await import('/web/js/render.js');"
            "return r.toolCard('regulations', 'map', 'map', '法规地图', '按品类和市场看适用法规'); }")
        self.assertIn('data-action="open-tool"', got)
        self.assertIn('data-group="regulations"', got)
        self.assertIn('data-tool="map"', got)
        self.assertIn("tool__icon", got)
        self.assertNotIn("tool__copy", got)     # 自创类名，必须不存在

    def test_freshness_filter_selects_by_rail(self):
        got = _Browser.page.evaluate("""async () => {
          const r = await import('/web/js/render.js');
          const ids = (f) => r.filteredFresh({ freshFilter: f });
          return { all: ids('全部').length, warn: ids('需处理').length,
                   ok: ids('已最新').length, muted: ids('无法确认').length };
        }""")
        self.assertEqual(got["all"], 4)
        self.assertEqual(got["warn"], 2, "原型 freshGpsr / freshToy 为 warn")
        self.assertEqual(got["ok"], 1, "原型 freshEn71 为 ok")
        self.assertEqual(got["muted"], 1, "原型 freshAmazon 为 muted")


def _stop_browser():
    _Browser.stop()


class ShellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Browser.start()

    def test_tabbar_has_the_five_prototype_tabs(self):
        labels = _Browser.page.locator("#tabbar .tab").all_inner_texts()
        self.assertEqual([t.strip() for t in labels],
                         ["首页", "法规", "助手", "行动", "我的"])

    def test_assistant_tab_uses_the_raised_pill(self):
        self.assertEqual(_Browser.page.locator("#tabbar .tab--main").count(), 1)
        self.assertIn("助手", _Browser.page.locator("#tabbar .tab--main").inner_text())

    def test_active_tab_matches_the_prototype_mapping(self):
        """原型的映射：regulations/action/profile 前缀归各自标签，freshness 归首页。"""
        cases = [("home", "首页"), ("freshness", "首页"),
                 ("regulations", "法规"), ("regulations/map", "法规"),
                 ("action", "行动"), ("action/journey", "行动"),
                 ("profile", "我的"), ("profile/tutorial", "我的"),
                 ("assistant", "助手")]
        for route, expected in cases:
            with self.subTest(route=route):
                _Browser.goto(route)
                current = _Browser.page.locator('#tabbar [aria-current="page"]')
                self.assertEqual(current.count(), 1)
                self.assertIn(expected, current.inner_text())

    def test_result_route_highlights_no_tab(self):
        """原型对 result 不做归并，因此没有任何标签被标为当前页。"""
        _Browser.goto("result")
        self.assertEqual(_Browser.page.locator('#tabbar [aria-current="page"]').count(), 0)

    def test_appbar_gives_back_buttons_a_nav_action(self):
        """原型没有 back 这个 action；返回一律走 data-action="nav" data-to=父路由。"""
        _Browser.goto("regulations/map")
        back = _Browser.page.locator("#appbar button[aria-label='返回']")
        self.assertEqual(back.count(), 1)
        self.assertEqual(back.get_attribute("data-action"), "nav")
        self.assertEqual(back.get_attribute("data-to"), "regulations")

    def test_shell_mount_points_match_the_prototype(self):
        for node_id in ["shell", "appbar", "view", "dock", "tabbar",
                        "backdrop", "sheet", "toast"]:
            with self.subTest(node_id=node_id):
                self.assertEqual(_Browser.page.locator(f"#{node_id}").count(), 1)


class StoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Browser.start()

    def test_state_shape_matches_the_prototype(self):
        got = _Browser.page.evaluate("""async () => {
          const { store } = await import('/web/js/store.js');
          return Object.keys(store.state).sort();
        }""")
        self.assertEqual(got, sorted(["route", "chatStarted", "messages", "typing",
                                      "choices", "filter", "freshFilter", "tool",
                                      "toolGroup", "resultFrom", "searchDone",
                                      "query", "hasFreshness"]))

    def test_set_conditions_resets_the_result_origin(self):
        """Review Focus 4：换条件后不得沿用上一次的结果来源。"""
        got = _Browser.page.evaluate("""async () => {
          const { store } = await import('/web/js/store.js');
          store.reset();
          store.set({ resultFrom: 'home' });
          const before = store.state.resultFrom;
          store.setConditions({ freshFilter: '需处理' });
          return { before, after: store.state.resultFrom };
        }""")
        self.assertEqual(got["before"], "home")
        self.assertEqual(got["after"], "assistant")

    def test_subscribers_are_notified_and_can_unsubscribe(self):
        got = _Browser.page.evaluate("""async () => {
          const { store } = await import('/web/js/store.js');
          let hits = 0;
          const off = store.subscribe(() => { hits += 1; });
          store.set({ filter: '全部' });
          off();
          store.set({ filter: '需处理' });
          return hits;
        }""")
        self.assertEqual(got, 1)


class SheetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Browser.start()

    def setUp(self):
        _Browser.goto("home")
        _Browser.page.evaluate(
            "async () => { const s = await import('/web/js/ui/sheet.js'); s.closeSheet(); }")

    def _open(self, html='<div class="sheet__body"><h2>详情</h2></div>'):
        _Browser.page.evaluate(
            "async (h) => { const s = await import('/web/js/ui/sheet.js'); s.openSheet(h); }", html)

    def test_open_and_close_toggle_the_prototype_classes(self):
        self._open()
        self.assertIn("is-on", _Browser.page.locator("#sheet").get_attribute("class"))
        self.assertIn("is-on", _Browser.page.locator("#backdrop").get_attribute("class"))
        self.assertEqual(_Browser.page.locator("#sheet").get_attribute("aria-hidden"), "false")
        _Browser.page.evaluate(
            "async () => { const s = await import('/web/js/ui/sheet.js'); s.closeSheet(); }")
        self.assertNotIn("is-on", _Browser.page.locator("#sheet").get_attribute("class"))
        self.assertNotIn("is-on", _Browser.page.locator("#backdrop").get_attribute("class"))
        self.assertEqual(_Browser.page.locator("#sheet").get_attribute("aria-hidden"), "true")

    def test_sheet_is_marked_dialog_and_modal_from_the_markup(self):
        self.assertEqual(_Browser.page.locator("#sheet").get_attribute("role"), "dialog")
        self.assertEqual(_Browser.page.locator("#sheet").get_attribute("aria-modal"), "true")

    def test_escape_closes_the_sheet(self):
        self._open()
        _Browser.page.keyboard.press("Escape")
        _Browser.page.wait_for_timeout(200)
        self.assertNotIn("is-on", _Browser.page.locator("#sheet").get_attribute("class"))

    def test_backdrop_click_closes_the_sheet(self):
        """backdrop 自带 data-action="close-sheet"（原型 891 行），走事件委托关闭。"""
        self._open()
        _Browser.page.locator("#backdrop").click(force=True)
        _Browser.page.wait_for_timeout(250)
        self.assertNotIn("is-on", _Browser.page.locator("#sheet").get_attribute("class"))

    def test_sheet_content_is_escaped_by_the_caller(self):
        """Review Focus 1：esc 之后再注入的内容不得被解析成元素。"""
        _Browser.page.evaluate(
            "async () => { const d = await import('/web/js/dom.js');"
            "const s = await import('/web/js/ui/sheet.js');"
            "s.openSheet('<div class=\"sheet__body\"><p id=probe>' + d.esc('<b>x</b>') + '</p></div>'); }")
        self.assertEqual(_Browser.page.locator("#probe").locator("b").count(), 0)


class ToastTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Browser.start()

    def test_toast_shows_then_hides_after_2400ms(self):
        _Browser.page.evaluate(
            "async () => { const t = await import('/web/js/ui/toast.js'); t.showToast('先写一句你的产品'); }")
        self.assertIn("is-on", _Browser.page.locator("#toast").get_attribute("class"))
        self.assertEqual(_Browser.page.locator("#toast").inner_text(), "先写一句你的产品")
        _Browser.page.wait_for_timeout(2600)
        self.assertNotIn("is-on", _Browser.page.locator("#toast").get_attribute("class"))

    def test_second_toast_restarts_the_timer(self):
        got = _Browser.page.evaluate("""async () => {
          const t = await import('/web/js/ui/toast.js');
          t.showToast('第一条');
          await new Promise(r => setTimeout(r, 1800));
          t.showToast('第二条');
          await new Promise(r => setTimeout(r, 1200));
          return document.getElementById('toast').classList.contains('is-on');
        }""")
        self.assertTrue(got, "第二次提示必须重新计时，而不是沿用第一次留下的定时器")


class HomeViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Browser.start()

    def test_headline_and_context_match_the_prototype(self):
        _Browser.goto("home")
        view = _Browser.page.locator("#view")
        self.assertIn("最近检查", view.inner_text())
        # 后端只支持「欧盟 / 美国」两个市场；首页条件条必须显示真实查询市场。
        for label in ["儿童玩具", "欧盟", "亚马逊"]:
            with self.subTest(label=label):
                self.assertIn(label, view.inner_text())

    def test_freshness_card_uses_the_prototype_classes(self):
        _Browser.goto("home")
        for sel in [".fresh-card", ".fresh-card__head", ".fresh-card__title",
                    ".monitor-pill", ".fresh-card__time"]:
            with self.subTest(sel=sel):
                self.assertEqual(_Browser.page.locator(f"#view {sel}").count(), 1,
                                 f"{sel} 必须存在（原型类名）")
        for wrong in [".fresh-card__top", ".fresh-card__at", ".pill"]:
            with self.subTest(wrong=wrong):
                self.assertEqual(_Browser.page.locator(f"#view {wrong}").count(), 0,
                                 f"{wrong} 是自创类名，必须不存在")

    def test_readonly_card_states_its_own_scope(self):
        _Browser.goto("home")
        text = _Browser.page.locator("#view").inner_text()
        self.assertIn("无需手动操作", text)
        self.assertIn("不等于法规条文变更", text)

    def test_first_run_toggle_is_not_shipped(self):
        _Browser.goto("home")
        self.assertEqual(_Browser.page.locator("#view .proto-toggle").count(), 0)

class ResultViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Browser.start()

    def test_priority_block_and_rows_are_present(self):
        _Browser.goto("result")
        self.assertIn("现在先做", _Browser.page.locator("#view").inner_text())
        self.assertGreaterEqual(_Browser.page.locator("#view .row").count(), 1)

    def test_rows_carry_the_prototype_inner_markup(self):
        _Browser.goto("result")
        for sel in [".row__rail", ".row__body", ".row__top", ".row__title",
                    ".row__sub", ".row__status", ".row__end"]:
            with self.subTest(sel=sel):
                self.assertGreaterEqual(_Browser.page.locator(f"#view {sel}").count(), 1)
        self.assertEqual(_Browser.page.locator("#view .row__copy").count(), 0,
                         "row__copy 是自创类名，必须不存在")


class FreshnessViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Browser.start()

    def test_page_head_and_meta_match_the_prototype(self):
        _Browser.goto("freshness")
        view = _Browser.page.locator("#view")
        self.assertIn("09:00 / 21:00", view.inner_text())
        self.assertEqual(_Browser.page.locator("#view .page-head__meta.mono").count(), 1)

    def test_fresh_card_uses_the_prototype_classes(self):
        _Browser.goto("freshness")
        for sel in [".fresh-card", ".fresh-card__head", ".fresh-card__title",
                    ".monitor-pill", ".fresh-card__time", ".fresh-card__sub"]:
            with self.subTest(sel=sel):
                self.assertEqual(_Browser.page.locator(f"#view {sel}").count(), 1)
        self.assertEqual(_Browser.page.locator("#view .fresh-count").count(), 4)
        self.assertEqual(_Browser.page.locator("#view .fresh-count--warn").count(), 1)

    def test_check_history_rows_are_plain_not_buttons(self):
        """这两行是只读的检查记录，原型用 div.row，不是可点的 button.row。"""
        _Browser.goto("freshness")
        self.assertGreaterEqual(_Browser.page.locator("#view div.row").count(), 2)

    def test_pending_links_are_real_anchors_with_external_icons(self):
        _Browser.goto("freshness")
        links = _Browser.page.locator("#view a.row")
        self.assertGreaterEqual(links.count(), 1)
        for i in range(links.count()):
            with self.subTest(i=i):
                self.assertTrue(links.nth(i).get_attribute("href"))
                self.assertEqual(links.nth(i).get_attribute("target"), "_blank")

    def test_scope_note_is_present(self):
        _Browser.goto("freshness")
        self.assertEqual(_Browser.page.locator("#view .fresh-note").count(), 1)

    def test_this_route_has_no_filter_buttons(self):
        """筛选属于 toolView 的 freshness 定制页（原型里无可达入口），不在本路由。"""
        _Browser.goto("freshness")
        self.assertEqual(
            _Browser.page.locator("#view button[data-action='fresh-filter']").count(), 0,
            "freshnessView 是静态页，不应有筛选按钮")

    def test_invented_classes_are_absent(self):
        _Browser.goto("freshness")
        for wrong in [".fresh-card__top", ".fresh-card__at", ".pill", ".row__copy"]:
            with self.subTest(wrong=wrong):
                self.assertEqual(_Browser.page.locator(f"#view {wrong}").count(), 0)


class AssistantViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Browser.start()

    def setUp(self):
        _Browser.goto("assistant")
        _Browser.page.evaluate("""async () => {
          const a = await import('/web/js/views/assistant.js');
          if (a.newChat) a.newChat();
        }""")

    def test_welcome_page_matches_the_prototype(self):
        _Browser.goto("assistant")
        text = _Browser.page.locator("#view").inner_text()
        self.assertIn("我是合规雷达", text)
        self.assertIn("告诉我你卖什么、卖到哪里。", text)
        self.assertIn("可以这样开始", text)
        self.assertIn("教程在「我的」里。", text)

    def test_welcome_offers_four_prompts_with_the_lead_ones_tinted(self):
        _Browser.goto("assistant")
        self.assertEqual(_Browser.page.locator("#view .reco").count(), 4)
        self.assertEqual(_Browser.page.locator("#view .reco--lead").count(), 2)
        first = _Browser.page.locator("#view .reco").first
        self.assertEqual(first.get_attribute("data-action"), "prompt")
        self.assertTrue(first.get_attribute("data-prompt"))

    def test_composer_is_a_form_with_tool_and_submit(self):
        _Browser.goto("assistant")
        self.assertEqual(_Browser.page.locator("#dock form.composer").count(), 1)
        self.assertEqual(_Browser.page.locator("#dock form.composer").get_attribute("data-form"),
                         "compose")
        self.assertEqual(_Browser.page.locator("#dock .composer__tool").count(), 1)
        self.assertEqual(_Browser.page.locator("#dock button[type='submit']").count(), 1)
        self.assertEqual(_Browser.page.locator("#dock .composer__mic").count(), 0,
                         "composer__mic 是自创类名，必须不存在")

    def test_submitting_the_form_sends_and_switches_to_the_thread(self):
        _Browser.goto("assistant")
        _Browser.page.locator("#dock textarea").fill("毛绒玩具卖到德国亚马逊")
        _Browser.page.locator("#dock button[type='submit']").click()
        _Browser.page.wait_for_timeout(400)
        self.assertIn("毛绒玩具卖到德国亚马逊", _Browser.page.locator("#view").inner_text())

    def test_conversation_renders_backend_result_cards(self):
        """助手走 /api/conversation/*，结果卡与追问都必须来自后端会话。"""
        _Browser.goto("assistant")
        _Browser.page.locator("#dock textarea").fill("毛绒玩具卖到欧盟，需要做什么")
        _Browser.page.locator("#dock button[type='submit']").click()
        _Browser.page.locator("#view .conv-result").first.wait_for(timeout=20000)
        self.assertGreaterEqual(_Browser.page.locator("#view .conv-result .row").count(), 1)
        self.assertGreaterEqual(_Browser.page.locator("#view .conv-result .choice-row .chip").count(), 1)
        self.assertEqual(
            _Browser.page.locator("#view [data-action='conv-export']").count(), 1,
            "业务结果必须提供真实导出入口")

    def test_quickbar_appears_only_once_a_conversation_started(self):
        _Browser.goto("assistant")
        self.assertEqual(_Browser.page.locator("#dock .quickbar").count(), 0)
        _Browser.page.locator("#dock textarea").fill("测试")
        _Browser.page.locator("#dock button[type='submit']").click()
        _Browser.page.wait_for_timeout(400)
        self.assertEqual(_Browser.page.locator("#dock .quickbar").count(), 1)
        self.assertEqual(_Browser.page.locator("#dock .quickbar .chip").count(), 4)

    def test_message_text_with_html_is_shown_literally(self):
        """Review Focus 1：消息含 HTML 时必须原样显示为文本。"""
        _Browser.goto("assistant")
        _Browser.page.locator("#dock textarea").fill("<b>粗体</b> 卖到德国")
        _Browser.page.locator("#dock button[type='submit']").click()
        _Browser.page.wait_for_timeout(400)
        view = _Browser.page.locator("#view")
        self.assertIn("<b>粗体</b> 卖到德国", view.inner_text())


class RegulationsHubTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Browser.start()

    def test_hub_has_a_search_entry_and_two_tools(self):
        _Browser.goto("regulations")
        self.assertIn("法规中心", _Browser.page.locator("#view").inner_text())
        self.assertEqual(_Browser.page.locator("#view .search-entry").count(), 1)
        self.assertEqual(_Browser.page.locator("#view .tool").count(), 2)

    def test_search_entry_navigates_to_the_search_route(self):
        _Browser.goto("regulations")
        _Browser.page.locator("#view .search-entry").click()
        _Browser.page.wait_for_timeout(300)
        self.assertIn("regulations/search", _Browser.page.url)


class ActionHubTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Browser.start()

    def test_hub_groups_tasks_and_markets(self):
        _Browser.goto("action")
        self.assertIn("要做的事", _Browser.page.locator("#view").inner_text())
        self.assertIn("看市场", _Browser.page.locator("#view").inner_text())
        self.assertEqual(_Browser.page.locator("#view [data-action='open-tool']").count(), 5)


class ToolViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Browser.start()

    TOOLS = [("regulations", "map", "法规地图"), ("regulations", "timeline", "变化时间线"),
             ("action", "todo", "合规待办"), ("action", "readiness", "上线准备"),
             ("action", "journey", "六阶段路线"), ("action", "compare", "区域对比"),
             ("action", "multi", "多市场汇总")]

    def test_each_tool_renders_its_own_content(self):
        for group, tool, title in self.TOOLS:
            with self.subTest(tool=tool):
                _Browser.goto(f"{group}/{tool}")
                # 原型的工具标题在顶栏（1226-1233）；视图内是副标题与工具内容。
                self.assertIn(title, _Browser.page.locator("#appbar").inner_text())
                self.assertTrue(_Browser.page.locator("#view").inner_text().strip())

    def test_tool_pages_keep_the_bottom_tabbar_active(self):
        for group, tool, _ in self.TOOLS:
            with self.subTest(tool=tool):
                _Browser.goto(f"{group}/{tool}")
                current = _Browser.page.locator('#tabbar [aria-current="page"]')
                self.assertEqual(current.count(), 1)

    def test_unknown_tool_name_falls_back_without_blanking(self):
        """Review Focus 2：未知/畸形工具名必须回落到该组的中心页。"""
        for bad in ["不存在", "__proto__", "constructor"]:
            with self.subTest(bad=bad):
                _Browser.goto(f"regulations/{bad}")
                text = _Browser.page.locator("#view").inner_text()
                self.assertTrue(text.strip())
                self.assertIn("法规中心", text)


class SearchViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Browser.start()

    def test_search_route_renders_the_prototype_clauses(self):
        _Browser.goto("regulations/search")
        # 标题在顶栏（原型 1225）；视图内是检索表单与正文指引。
        self.assertIn("条款检索", _Browser.page.locator("#appbar").inner_text())
        self.assertIn("按法规编号精确定位", _Browser.page.locator("#view").inner_text())


class ProfileViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Browser.start()

    def test_profile_menu_uses_the_sheet_action(self):
        _Browser.goto("profile")
        rows = _Browser.page.locator("#view [data-action='sheet']")
        self.assertGreaterEqual(rows.count(), 6)
        keys = [rows.nth(i).get_attribute("data-sheet") for i in range(rows.count())]
        for key in ["history", "conditions", "voice", "coverage", "privacy", "about"]:
            with self.subTest(key=key):
                self.assertIn(key, keys)

    def test_tutorial_is_the_prototype_article_and_lives_under_profile(self):
        """tutorialView 是一篇长文档（article.tutorial + tut-lead/tut-source/tut-callout + 表格），
        不是卡片列表——`.step` 属于 PROFILE_SHEETS.help() 的抽屉，不在此路由。"""
        _Browser.goto("profile/tutorial")
        view = _Browser.page.locator("#view")
        self.assertEqual(_Browser.page.locator("#view article.tutorial").count(), 1)
        self.assertIn("企业用户使用指引", view.inner_text())
        self.assertGreaterEqual(_Browser.page.locator("#view .tut-lead").count(), 2)
        self.assertEqual(_Browser.page.locator("#view .tut-source").count(), 1)
        self.assertGreaterEqual(_Browser.page.locator("#view .tut-callout").count(), 1)
        self.assertGreaterEqual(_Browser.page.locator("#view table tr").count(), 1)
        self.assertEqual(_Browser.page.locator("#view .step").count(), 0,
                         "教程路由不应有 .step（那属于帮助抽屉）")
        current = _Browser.page.locator('#tabbar [aria-current="page"]')
        self.assertIn("我的", current.inner_text())

    def test_profile_shows_the_radar_mark_once(self):
        """我的页顶栏应与其他页面一致保留小标记；hero 不再重复大标记。"""
        _Browser.goto("profile")
        self.assertEqual(_Browser.page.locator("#appbar .brand__mark").count(), 1)
        self.assertEqual(_Browser.page.locator("#view .profile__mark").count(), 0)


class DetailSheetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Browser.start()

    # help 在原型里没有 UI 入口（PROFILE_SHEETS.help 仍保留、handler 仍接线），
    # 故不放进"从 profile 可打开"的键列表——否则点击定位器没有目标。
    PROFILE_KEYS = ["conditions", "history", "voice", "coverage", "privacy", "about"]

    def _open_key(self, key):
        _Browser.goto("profile")
        _Browser.page.evaluate(
            "async () => { const s = await import('/web/js/ui/sheet.js'); s.closeSheet(); }")
        _Browser.page.locator(f"#view [data-action='sheet'][data-sheet='{key}']").first.click()
        _Browser.page.wait_for_timeout(300)

    def test_every_profile_sheet_opens_with_content(self):
        for key in self.PROFILE_KEYS:
            with self.subTest(key=key):
                self._open_key(key)
                sheet = _Browser.page.locator("#sheet")
                self.assertIn("is-on", sheet.get_attribute("class"))
                self.assertTrue(sheet.inner_text().strip(), f"{key} 抽屉不得为空")

    def test_every_sheet_has_a_grab_handle_and_a_close_button(self):
        for key in self.PROFILE_KEYS:
            with self.subTest(key=key):
                self._open_key(key)
                sheet = _Browser.page.locator("#sheet")
                self.assertEqual(sheet.locator(".sheet__grab").count(), 1)
                self.assertEqual(sheet.locator("[data-action='close-sheet']").count(), 1)

    def test_item_detail_opens_from_a_row(self):
        _Browser.goto("result")
        _Browser.page.locator("#view [data-action='detail']").first.click()
        _Browser.page.wait_for_timeout(300)
        sheet = _Browser.page.locator("#sheet")
        self.assertIn("is-on", sheet.get_attribute("class"))
        self.assertEqual(sheet.locator(".sheet__grab").count(), 1)

    def test_unknown_detail_id_does_not_blank_the_sheet(self):
        """Review Focus 2：未知条目 id 不得白屏或抛异常。"""
        got = _Browser.page.evaluate("""async () => {
          const d = await import('/web/js/views/detail.js');
          try { return d.detailSheet('完全不存在的条目'); }
          catch (e) { return 'THREW: ' + e.message; }
        }""")
        self.assertFalse(str(got).startswith("THREW"), "未知 id 不得抛异常")


class UnknownRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Browser.start()

    def test_unknown_route_redirects_home(self):
        """原型 2068-2071：未知路由 go("home")。所有视图就位后此行为才可观测。"""
        for bad in ["完全瞎写", "zzz", "foo/bar", "__proto__"]:
            with self.subTest(bad=bad):
                _Browser.goto(bad)
                self.assertTrue(_Browser.page.url.endswith("#/home"),
                                f"未知路由必须回落到 #/home，实际 {_Browser.page.url}")

    def test_unknown_route_renders_the_home_view(self):
        for bad in ["完全瞎写", "foo/bar", "__proto__"]:
            with self.subTest(bad=bad):
                _Browser.goto(bad)
                self.assertTrue(_Browser.page.locator("#view").inner_text().strip(),
                                "回落首页后必须渲染出内容，而不是白屏")


class DelegationCompletenessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Browser.start()

    def test_every_action_in_the_prototype_is_handled(self):
        """把原型事件委托里出现过的 action 逐个点一遍，任何未接的 action 会表现为无反应。

        本测试只断言页面不崩、不白屏；具体行为由各自视图的测试覆盖。
        """
        actions = ["nav", "prompt", "choice", "open-result", "new-chat", "history",
                   "detail", "filter", "fresh-filter", "open-tool", "rerun",
                   "example-query", "sheet", "open-history",
                   "close-sheet", "export", "mark-done", "copy", "regenerate",
                   "voice", "quick", "help"]
        got = _Browser.page.evaluate("""async () => {
          const m = await import('/web/js/main.js');
          return m.HANDLED_ACTIONS;
        }""")
        for action in actions:
            with self.subTest(action=action):
                self.assertIn(action, got, f"action「{action}」尚未接入")


class ResponsiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Browser.start()

    @classmethod
    def tearDownClass(cls):
        # 共享 page 的视口必须恢复，否则字母序在其后的浏览器测试会在桌面宽度下运行。
        _Browser.page.set_viewport_size({"width": 390, "height": 844})

    def _at(self, width, prop):
        _Browser.page.set_viewport_size({"width": width, "height": 900})
        _Browser.page.goto(f"{BASE}#/home", wait_until="load")
        _Browser.page.wait_for_timeout(350)
        return _Browser.page.evaluate(
            "() => { const el = document.querySelector('.app-shell'); const cs = getComputedStyle(el);"
            "return { prop: cs.getPropertyValue(%r), rect: el.getBoundingClientRect().toJSON() }; }"
            % prop)

    def test_wide_viewport_has_no_phone_shell_decoration(self):
        for prop in ["border-top-width", "box-shadow"]:
            with self.subTest(prop=prop):
                got = self._at(1440, prop)
                self.assertIn(got["prop"], ["0px", "none"],
                              f"桌面端不应保留手机壳装饰：{prop}={got['prop']}")

    def test_wide_viewport_keeps_the_phone_proportions_and_centering(self):
        rect = self._at(1440, "width")["rect"]
        self.assertLessEqual(rect["width"], 481, "桌面端内容栏不得超过 480px")
        self.assertAlmostEqual(rect["x"] + rect["width"] / 2, 720, delta=2, msg="内容栏必须居中")

    def test_narrow_viewport_keeps_the_full_width_shell(self):
        _Browser.page.set_viewport_size({"width": 390, "height": 844})
        _Browser.page.goto(f"{BASE}#/home", wait_until="load")
        _Browser.page.wait_for_timeout(350)
        rect = _Browser.page.evaluate(
            "() => document.querySelector('.app-shell').getBoundingClientRect().toJSON()")
        self.assertEqual(rect["width"], 390)
        self.assertEqual(rect["x"], 0)

    def test_tabbar_stays_at_the_bottom_across_the_breakpoint(self):
        """Review Focus 5：跨断点来回缩放不得错乱。"""
        for width in [390, 1440, 390, 1440]:
            with self.subTest(width=width):
                _Browser.page.set_viewport_size({"width": width, "height": 900})
                _Browser.page.goto(f"{BASE}#/home", wait_until="load")
                _Browser.page.wait_for_timeout(300)
                box = _Browser.page.evaluate(
                    "() => { const r = document.querySelector('.tabbar').getBoundingClientRect();"
                    "return { bottom: r.bottom, vh: window.innerHeight, w: r.width }; }")
                self.assertLessEqual(abs(box["bottom"] - box["vh"]), 2, "标签栏必须贴在视口底部")
                self.assertGreater(box["w"], 300, "标签栏不得塌陷")


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        _Browser.stop()
