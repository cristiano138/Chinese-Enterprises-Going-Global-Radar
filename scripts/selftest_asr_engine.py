# -*- coding: utf-8 -*-
"""sherpa-onnx 引擎适配层自检（scripts/selftest_asr_engine.py）

全部离线：不联网、不要求本机已下载引擎或模型。
断言的是「不会静默出错」，不是「识别得多准」——
识别质量取决于模型与口音，不能写进 CI 当确定值。

覆盖：
    A · status()/路径解析：缺文件 → 明确不可用，且绝不触发下载
    B · 下载与解包：禁止 shell、拒绝路径逃逸、原子替换
    C · 输出解析：JSON 优先、噪声忽略、纯文本兜底
    D · core/asr.py 的 engine 后端：可用性探测、失败收敛为提示、不污染 meta 契约

用法：
    python scripts/selftest_asr_engine.py
退出码 0 = 全绿。
"""

import io
import json
import os
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from core import asr, asr_engine  # noqa: E402

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"　{detail}" if detail else ""))


def section(title):
    print()
    print(f"  ── {title} " + "─" * max(0, 56 - len(title)))


class EngineCase(unittest.TestCase):
    def setUp(self):
        self._saved = {name: getattr(asr_engine, name)
                       for name in ("ROOT", "AUTO_DOWNLOAD", "MODEL", "VERSION")}
        self.root = Path(tempfile.mkdtemp(prefix="cr-engine-"))
        asr_engine.ROOT = str(self.root)

    def tearDown(self):
        for name, value in self._saved.items():
            setattr(asr_engine, name, value)
        import shutil
        shutil.rmtree(self.root, ignore_errors=True)

    def fake_engine(self):
        binary = self.root / "bin" / ("sherpa-onnx-offline.exe" if sys.platform == "win32"
                                      else "sherpa-onnx-offline")
        binary.parent.mkdir(parents=True, exist_ok=True)
        binary.write_bytes(b"")
        model = self.root / "models" / asr_engine.MODEL
        model.mkdir(parents=True, exist_ok=True)
        (model / "model.int8.onnx").write_bytes(b"0" * 16)
        (model / "tokens.txt").write_text("a 0\n", encoding="utf-8")
        return binary


class PathTests(EngineCase):
    def test_empty_root_is_unavailable_and_does_not_download(self):
        with mock.patch.object(asr_engine, "_download", side_effect=AssertionError("不得下载")):
            state = asr_engine.status()
        self.assertFalse(state["ready"])
        self.assertIn("缺少", state["detail"])
        self.assertEqual(state["binary"], "")

    def test_status_shape_is_stable(self):
        need = {"available", "ready", "root", "binary", "model", "version", "detail"}
        self.assertEqual(set(asr_engine.status()), need)

    def test_complete_layout_becomes_ready(self):
        binary = self.fake_engine()
        state = asr_engine.status()
        self.assertTrue(state["ready"])
        self.assertEqual(Path(state["binary"]), binary)
        self.assertTrue(asr_engine.engine_ready())

    def test_asset_name_matches_platform(self):
        name = asr_engine.asset_name()
        self.assertTrue(name.startswith(f"sherpa-onnx-{asr_engine.VERSION}-"))
        self.assertTrue(name.endswith(".tar.bz2"))
        if sys.platform == "win32":
            self.assertIn("win-x64", name)
        elif sys.platform == "darwin":
            self.assertIn("osx-", name)
        else:
            self.assertIn("linux-x64", name)
        self.assertIn(asr_engine.MODEL, asr_engine.model_url())

    def test_ensure_respects_auto_download_off(self):
        asr_engine.AUTO_DOWNLOAD = False
        with mock.patch.object(asr_engine, "_download", side_effect=AssertionError("不得下载")):
            self.assertFalse(asr_engine.ensure())
        self.assertIn("自动下载", asr_engine.prepare_state()["reason"])


class ArchiveTests(EngineCase):
    def _build(self, member_name):
        archive = self.root / "bundle.tar.bz2"
        with tarfile.open(archive, "w:bz2") as bundle:
            info = tarfile.TarInfo(member_name)
            payload = b"x"
            info.size = len(payload)
            bundle.addfile(info, io.BytesIO(payload))
        return archive

    def test_traversal_member_is_rejected(self):
        archive = self._build("../escaped.txt")
        with self.assertRaises(asr_engine.EngineError):
            asr_engine._extract(archive, self.root / "out")
        self.assertFalse((self.root.parent / "escaped.txt").exists())

    def test_absolute_member_is_rejected(self):
        archive = self._build("/tmp/escaped.txt")
        with self.assertRaises(asr_engine.EngineError):
            asr_engine._extract(archive, self.root / "out")

    def test_normal_member_is_extracted(self):
        archive = self._build("bundle/bin/sherpa-onnx-offline")
        destination = self.root / "out"
        asr_engine._extract(archive, destination)
        self.assertTrue((destination / "bundle" / "bin" / "sherpa-onnx-offline").is_file())

    def test_flatten_requires_binary(self):
        empty = self.root / "empty"
        empty.mkdir()
        with self.assertRaises(asr_engine.EngineError):
            asr_engine._flatten_binary(empty)


class ParseTests(unittest.TestCase):
    def test_json_line_wins_over_noise(self):
        stdout = json.dumps({"text": "我要把毛绒玩具卖到德国", "tokens": []}, ensure_ascii=False)
        self.assertEqual(asr_engine._parse_output(stdout, "Elapsed 0.3s", "/tmp/a.wav"),
                         "我要把毛绒玩具卖到德国")

    def test_last_valid_json_wins(self):
        stdout = "\n".join([json.dumps({"text": "第一句"}, ensure_ascii=False),
                            "noise",
                            json.dumps({"text": "第二句"}, ensure_ascii=False)])
        self.assertEqual(asr_engine._parse_output(stdout, "", ""), "第二句")

    def test_broken_json_falls_back_to_plain_text(self):
        self.assertEqual(asr_engine._parse_output("", "hello world\n/tmp/a.wav", "/tmp/a.wav"),
                         "hello world")

    def test_garbage_returns_empty(self):
        self.assertEqual(asr_engine._parse_output("{not json", "", ""), "")


class EngineBackendTests(unittest.TestCase):
    """core/asr.py 的 engine 后端：失败必须收敛成提示，不能抛。"""

    def setUp(self):
        self._saved = {name: getattr(asr, name) for name in ("BACKEND_ENV", "API_KEY")}

    def tearDown(self):
        for name, value in self._saved.items():
            setattr(asr, name, value)

    def test_available_prefers_engine_when_ready(self):
        asr.API_KEY = ""
        with mock.patch.object(asr, "_cloud_ready", return_value=False), \
                mock.patch.object(asr, "_engine_ready", return_value=True), \
                mock.patch.object(asr, "_local_importable", return_value=True):
            asr.BACKEND_ENV = "auto"
            self.assertEqual(asr.available()["backend"], "engine")
            asr.BACKEND_ENV = "engine"
            self.assertEqual(asr.available()["backend"], "engine")

    def test_engine_selected_but_missing_reports_actionable_reason(self):
        with mock.patch.object(asr, "_engine_ready", return_value=False), \
                mock.patch.object(asr_engine, "status",
                                  return_value={"ready": False, "detail": "缺少引擎二进制"}):
            asr.BACKEND_ENV = "engine"
            state = asr.available()
        self.assertFalse(state["enabled"])
        self.assertIn("prepare_asr_engine", state["detail"])

    def test_engine_failure_becomes_reason_not_exception(self):
        with mock.patch.object(asr, "_engine_ready", return_value=True), \
                mock.patch.object(asr_engine, "transcribe",
                                  side_effect=asr_engine.EngineError("引擎炸了")), \
                mock.patch.object(asr, "BACKEND_ENV", "engine"):
            try:
                asr._transcribe_engine(b"")
            except asr._ASRFailure as exc:
                self.assertIn("引擎炸了", str(exc))
            else:
                self.fail("引擎失败必须转成 _ASRFailure")

    def test_engine_result_is_normalized(self):
        with mock.patch.object(asr_engine, "transcribe",
                               return_value=("  毛绒玩具卖到德国。 ", {"seconds": 1})):
            self.assertEqual(asr._transcribe_engine(b""), "  毛绒玩具卖到德国。 ")


if __name__ == "__main__":
    print("=" * 66)
    print("  sherpa-onnx 引擎适配层 · 自检")
    print("=" * 66)
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2, stream=sys.stdout).run(suite)
    print()
    print("=" * 66)
    if result.wasSuccessful():
        print("  结果：全部通过")
    else:
        print(f"  结果：失败 {len(result.failures) + len(result.errors)} 项")
    print("=" * 66)
    sys.exit(0 if result.wasSuccessful() else 1)
