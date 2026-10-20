"""SPA 静态托管与 /api/* 契约的离线检查；不需要浏览器。

与 scripts/selftest_chat_ui.py 同风格：unittest、离线、不联网、不调模型。
"""
from __future__ import annotations

import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import sys
import threading
import time
import unittest
import urllib.request

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

import gradio as gr
from gradio.routes import App  # noqa: F401  （确认 Gradio 版本提供该类型）

import app_main
import web_app


class _Server:
    """在进程内起一次真实 Gradio 服务，供所有用例共用。"""

    _lock = threading.Lock()
    _started = False
    port = int(os.getenv("SELFTEST_WEB_PORT", "7899"))

    @classmethod
    def start(cls):
        with cls._lock:
            if cls._started:
                return
            demo = app_main.build_ui()
            demo.launch(server_name="127.0.0.1", server_port=cls.port,
                        prevent_thread_lock=True, quiet=True, footer_links=[])
            time.sleep(2)
            assert web_app.install(demo), "web_app.install() 必须成功"
            time.sleep(1)
            cls._started = True

    @classmethod
    def get(cls, path):
        url = f"http://127.0.0.1:{cls.port}{path}"
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                return resp.status, resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", "replace")


class _ElementParents(HTMLParser):
    """记录每个带 id 的元素的直接父元素 id。"""

    _VOID = {"area", "base", "br", "col", "hr", "img", "input", "link", "meta", "source"}

    def __init__(self):
        super().__init__()
        self._stack = []
        self.parents = {}

    def handle_starttag(self, tag, attrs):
        element_id = dict(attrs).get("id")
        if element_id:
            self.parents[element_id] = self._stack[-1] if self._stack else None
        if tag not in self._VOID:
            self._stack.append(element_id)

    def handle_endtag(self, tag):
        if tag not in self._VOID and self._stack:
            self._stack.pop()


class StaticHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Server.start()

    def test_root_serves_the_spa_shell(self):
        status, body = _Server.get("/")
        self.assertEqual(status, 200)
        self.assertIn('id="shell"', body)
        self.assertIn("/web/js/main.js", body)

    def test_floating_layers_are_nested_inside_the_app_shell(self):
        # 三者都是 position:absolute，需相对 .app-shell（position:relative）解析。
        # 若退化成 .app-shell 的兄弟，最近已定位祖先变为视口，桌面端（≥700px）
        # 抽屉会横跨整个视口、Toast 居中于整屏。钉住嵌套以免静默回归。
        status, body = _Server.get("/")
        self.assertEqual(status, 200)
        parser = _ElementParents()
        parser.feed(body)
        parser.close()
        for element in ("backdrop", "sheet", "toast"):
            self.assertEqual(
                parser.parents.get(element), "shell",
                f"#{element} 必须是 #shell 的直接子元素")

    def test_static_assets_are_served(self):
        status, body = _Server.get("/web/js/main.js")
        self.assertEqual(status, 200)
        self.assertIn("export", body)

    def test_styles_are_served(self):
        status, body = _Server.get("/web/styles/tokens.css")
        self.assertEqual(status, 200)
        self.assertIn("--brand", body)

    def test_gradio_api_survives_the_root_takeover(self):
        status, body = _Server.get("/gradio_api/info")
        self.assertEqual(status, 200)
        self.assertIn("named_endpoints", json.loads(body))


class ReferenceAssetTests(unittest.TestCase):
    def test_prototype_reference_is_the_expected_revision(self):
        path = PROJECT / "docs" / "ui-preview" / "prototype-v2.html"
        self.assertTrue(path.is_file(), "原型参考资产必须入库")
        # 先归一化行尾，使断言在 core.autocrlf 打开时同样成立。
        data = path.read_bytes().replace(b"\r\n", b"\n")
        self.assertEqual(len(data), 125082, "原型归一化后字节数必须与拆解基线一致")
        self.assertEqual(
            hashlib.sha256(data).hexdigest(),
            "43ef8e474d330c99d5e65bdcfe42648c492299587ab19fde713a1744f05104f5",
            "像素比对基准被改动：请确认 docs/ui-preview/prototype-v2.html 未被编辑")


if __name__ == "__main__":
    unittest.main(verbosity=2)