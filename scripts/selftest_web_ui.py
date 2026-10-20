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


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        _Browser.stop()
