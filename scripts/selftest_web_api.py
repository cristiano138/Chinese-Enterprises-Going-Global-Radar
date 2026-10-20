"""SPA 静态托管与 /api/* 契约的离线检查；不需要浏览器。

与 scripts/selftest_chat_ui.py 同风格：unittest、离线、不联网、不调模型。
"""
from __future__ import annotations

import hashlib
from html.parser import HTMLParser
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
import urllib.request
import wave

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

    @classmethod
    def get_bytes(cls, path):
        url = f"http://127.0.0.1:{cls.port}{path}"
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                return resp.status, resp.read(), dict(resp.headers)
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read(), dict(exc.headers)

    @classmethod
    def post(cls, path, payload):
        url = f"http://127.0.0.1:{cls.port}{path}"
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as resp:
                return resp.status, resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", "replace")

    @classmethod
    def post_multipart(cls, path, field, filename, content, content_type):
        boundary = "----CRTest" + str(time.time_ns())
        head = (f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n").encode("utf-8")
        body = head + content + f"\r\n--{boundary}--\r\n".encode("utf-8")
        request = urllib.request.Request(
            f"http://127.0.0.1:{cls.port}{path}", data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=90) as resp:
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

    # ---- install() 的失败契约：任何失败都必须返回 False 且不抛异常，
    # ---- 因为调用方正是靠这个布尔值决定回退到 CR_UI=gradio。

    def test_install_returns_false_without_a_demo(self):
        self.assertIs(web_app.install(None), False)

    def test_install_returns_false_when_the_demo_has_no_app_attribute(self):
        self.assertIs(web_app.install(object()), False)

    def test_install_returns_false_when_reading_the_app_attribute_raises(self):
        class _HostileDemo:
            @property
            def app(self):
                raise RuntimeError("app unavailable")

        self.assertIs(web_app.install(_HostileDemo()), False)

    def test_install_returns_false_when_mounting_static_files_fails(self):
        class _RefusingApp:
            def mount(self, *args, **kwargs):
                raise RuntimeError("mount refused")

        class _Demo:
            app = _RefusingApp()

        self.assertIs(web_app.install(_Demo()), False)

    def test_install_returns_false_and_mounts_nothing_when_the_shell_is_unreadable(self):
        # 外壳读不到时必须在安装期就回退：此时 Gradio 的根路由还没被遮蔽，
        # 调用方还能退回 Gradio 界面；若晚到请求期，"/" 只会 500。
        class _StubRouter:
            def __init__(self):
                self.routes = []

        class _StubApp:
            def __init__(self):
                self.router = _StubRouter()
                self.mounted = []

            def mount(self, path, *args, **kwargs):
                self.mounted.append(path)

        class _Demo:
            def __init__(self, app):
                self.app = app

        app = _StubApp()
        with tempfile.TemporaryDirectory() as empty_dir:
            # 目录存在但没有 index.html
            with mock.patch.object(web_app, "WEB_DIR", empty_dir):
                self.assertIs(web_app.install(_Demo(app)), False)
        self.assertEqual(app.mounted, [], "读不到外壳时必须什么都没挂")

    def test_styles_are_served(self):
        status, body = _Server.get("/web/styles/tokens.css")
        self.assertEqual(status, 200)
        self.assertIn("--brand", body)

    def test_gradio_api_survives_the_root_takeover(self):
        status, body = _Server.get("/gradio_api/info")
        self.assertEqual(status, 200)
        self.assertIn("named_endpoints", json.loads(body))


class ApiContractTests(unittest.TestCase):
    """M2 契约：/api/* 必须返回统一信封与稳定的英文键。"""

    @classmethod
    def setUpClass(cls):
        _Server.start()

    def _data(self, status, body):
        self.assertEqual(status, 200, body[:400])
        payload = json.loads(body)
        self.assertIs(payload["ok"], True, payload)
        self.assertEqual(set(payload), {"ok", "reason", "data", "meta"})
        return payload["data"]

    def test_bootstrap_reports_real_coverage(self):
        data = self._data(*_Server.get("/api/bootstrap"))
        self.assertIn("儿童玩具", data["categories"])
        self.assertEqual([m["name"] for m in data["markets"]], ["欧盟", "美国"])
        self.assertGreater(data["coverage"]["laws"], 0)
        self.assertTrue(data["data_cutoff"])

    def test_freshness_reports_counts_and_recent_runs(self):
        data = self._data(*_Server.get("/api/freshness"))
        self.assertTrue(data["available"])
        counts = data["counts"]
        self.assertGreater(counts["total"], 0)
        self.assertLessEqual(counts["total"], counts["http_ok"] + counts["pending"])
        self.assertLessEqual(len(data["runs"]), 2)

    def test_tool_endpoints_return_normalized_english_keys(self):
        cases = {
            "map": ("records", "primary", "cross"),
            "todo": ("actions", "groups", "pending"),
            "timeline": ("recent", "upcoming", "window"),
            "compare": ("regions", "shared", "shared_count"),
            "multi": ("regions", "total"),
            "readiness": ("regions", "total_actions"),
        }
        body = {"category": "儿童玩具", "market": "欧盟"}
        for name, keys in cases.items():
            with self.subTest(tool=name):
                data = self._data(*_Server.post(f"/api/tool/{name}", body))
                for key in keys:
                    self.assertIn(key, data, f"{name} 缺少 {key}")

    def test_map_records_carry_source_links(self):
        data = self._data(*_Server.post("/api/tool/map",
                                        {"category": "儿童玩具", "market": "欧盟"}))
        self.assertGreater(len(data["records"]), 0)
        record = data["records"][0]
        self.assertTrue(record["title"])
        self.assertTrue(record["url"].startswith("http"))

    def test_route_returns_a_user_facing_reply(self):
        data = self._data(*_Server.post("/api/route",
                                        {"text": "毛绒玩具卖到欧盟"}))
        self.assertIs(data["ok"], True, data)
        self.assertEqual(data["category"], "儿童玩具")
        self.assertEqual(data["market"], "欧盟")
        self.assertIn("已识别", data["reply"])
        self.assertIsNotNone(data["m1"])
        self.assertGreater(len(data["m1"]["records"]), 0)

    def test_route_partial_request_is_explained_not_crashed(self):
        data = self._data(*_Server.post("/api/route", {"text": "毛绒玩具"}))
        self.assertIs(data["ok"], False)
        self.assertIn("市场", data["reply"])

    def test_search_returns_clause_units(self):
        data = self._data(*_Server.get("/api/search?identifier=32009L0048"))
        self.assertTrue(data["units"])
        unit = data["units"][0]
        for key in ("heading", "locator", "document_id", "parse_status", "body"):
            self.assertIn(key, unit)

    def test_readiness_keeps_all_six_phases(self):
        data = self._data(*_Server.post("/api/tool/readiness",
                                        {"category": "儿童玩具", "markets": ["欧盟", "美国"]}))
        self.assertEqual(len(data["phase_names"]), 6)
        region = data["regions"][0]
        self.assertEqual([phase["name"] for phase in region["phases"]], data["phase_names"])
        self.assertTrue(any(phase["count"] > 0 for phase in region["phases"]))

    def test_transcribe_rejects_missing_audio(self):
        status, body = _Server.post("/api/transcribe", {"text": "no audio"})
        self.assertEqual(status, 400)
        payload = json.loads(body)
        self.assertIs(payload["ok"], False)
        self.assertTrue(payload["reason"])

    def test_transcribe_returns_a_stable_envelope(self):
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(16000)
            handle.writeframes(b"\x00\x00" * 8000)
        status, body = _Server.post_multipart(
            "/api/transcribe", "audio", "probe.wav", buffer.getvalue(), "audio/wav")
        self.assertEqual(status, 200, body[:300])
        payload = json.loads(body)
        self.assertEqual(set(payload), {"ok", "reason", "data", "meta"})
        if payload["ok"]:
            self.assertTrue(payload["data"]["text"])
            self.assertIn("backend", payload["data"]["meta"])
        else:
            # 本机未配置语音引擎时必须给出可读的原因，而不是 500。
            self.assertTrue(payload["reason"])

    def test_todo_export_is_csv_with_bom(self):
        status, payload, headers = _Server.get_bytes(
            "/api/export/todo.csv?category=%E5%84%BF%E7%AB%A5%E7%8E%A9%E5%85%B7"
            "&market=%E6%AC%A7%E7%9B%9F")
        self.assertEqual(status, 200, payload[:200])
        self.assertIn("text/csv", headers.get("content-type", ""))
        self.assertTrue(payload.startswith(b"\xef\xbb\xbf"), "CSV 必须带 UTF-8 BOM")
        self.assertIn("商品类目".encode("utf-8"), payload)


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