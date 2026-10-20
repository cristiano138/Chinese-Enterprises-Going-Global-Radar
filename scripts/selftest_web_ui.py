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


def _stop_browser():
    _Browser.stop()


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        _Browser.stop()
