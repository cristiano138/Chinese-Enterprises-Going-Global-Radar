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


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        _Browser.stop()
