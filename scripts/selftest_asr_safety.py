# -*- coding: utf-8 -*-
"""ASR 安全边界回归；仅使用临时文件、合成 WAV 和离线 mocks。"""
import importlib.util
import io
import json
import os
from pathlib import Path
import runpy
import struct
import sys
import tempfile
import threading
import time
import types
import unittest
from contextlib import ExitStack
from unittest import mock
import wave

sys.dont_write_bytecode = True
PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from core import asr


class ASRSafetyTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.cache = self.root / "cache"
        self.path = self.root / "audio.wav"
        self.path.write_bytes(self.wav())
        self.patch("CACHE_DIR", str(self.cache))
        self.patch("CACHE_ENABLED", False)
        self.patch("BACKEND_ENV", "cloud")
        self.patch("API_BASE", "https://asr.invalid/v1")
        self.patch("API_KEY", "secret-test-key")
        self.patch("API_MODEL", "test-model")
        self.patch("LANG", "zh")
        self.patch("_work_slots", threading.BoundedSemaphore(2))
        self.patch("_local_model", None)
        self.cloud = self.patch("_transcribe_cloud", mock.Mock(return_value="测试文本"))
        self.local = self.patch("_transcribe_local", mock.Mock(return_value="本地文本"))
        self.patch("_local_importable", mock.Mock(return_value=True))
        self.threads = []
        self.events = []
        original_thread = threading.Thread

        def tracked_thread(*args, **kwargs):
            thread = original_thread(*args, **kwargs)
            self.threads.append(thread)
            return thread

        self.stack.enter_context(mock.patch.object(asr.threading, "Thread", tracked_thread))

    def tearDown(self):
        for event in self.events:
            event.set()
        for thread in self.threads:
            if thread.ident is not None:
                thread.join(3)
                self.assertFalse(thread.is_alive(), "离线测试线程必须结束")

    def patch(self, name, value):
        return self.stack.enter_context(mock.patch.object(asr, name, value))

    @staticmethod
    def wav(seconds=1, rate=16000, width=2, channels=1):
        stream = io.BytesIO()
        with wave.open(stream, "wb") as out:
            out.setnchannels(channels)
            out.setsampwidth(width)
            out.setframerate(rate)
            out.writeframes(b"\0" * int(rate * seconds) * width * channels)
        return stream.getvalue()

    def transcribe(self, path=None):
        result = asr.transcribe(str(self.path) if path is None else path)
        text, meta = result
        self.assertEqual(set(meta), {"ok", "reason", "backend", "cached", "seconds", "lang"})
        self.assertIsInstance(text, str)
        self.assertIsInstance(meta["seconds"], (float, int))
        if not meta["ok"]:
            self.assertEqual(text, "")
            self.assertTrue(meta["reason"])
            self.assertFalse(meta["cached"])
        return result

    def event(self):
        event = threading.Event()
        self.events.append(event)
        return event

    def join_workers(self):
        for thread in list(self.threads):
            if thread.ident is not None:
                thread.join(3)
                self.assertFalse(thread.is_alive())

    def test_defaults_and_cache_opt_in(self):
        for setting, expected in [(None, False), ("0", False), ("true", True), ("1", True)]:
            with self.subTest(setting=setting), mock.patch.dict(os.environ, {}, clear=True):
                if setting is not None:
                    os.environ["ASR_CACHE_ENABLED"] = setting
                namespace = runpy.run_path(str(PROJECT / "core" / "asr.py"), run_name="asr_config_test")
                self.assertIs(namespace["CACHE_ENABLED"], expected)
                self.assertEqual(namespace["TRANSCRIBE_TIMEOUT"], 45)
                self.assertEqual(namespace["MAX_CONCURRENT"], 2)
                self.assertEqual(namespace["CACHE_TTL"], 7 * 86400)
                self.assertEqual(namespace["CACHE_MAX_ENTRIES"], 256)
        self.assertTrue(self.transcribe()[1]["ok"])
        self.assertTrue(self.transcribe()[1]["ok"])
        self.assertEqual(self.cloud.call_count, 2)
        self.assertFalse(self.cache.exists())
        with mock.patch("builtins.open", side_effect=AssertionError("禁读缓存")):
            self.assertIsNone(asr._cache_get("unused"))
            asr._cache_put("unused", "测试文本")

    def test_cache_hit_and_key_isolation_without_credentials(self):
        self.patch("CACHE_ENABLED", True)
        audio = self.path.read_bytes()
        key = asr._cache_key(audio, "cloud")
        self.assertTrue(self.transcribe()[1]["ok"])
        self.assertTrue(self.transcribe()[1]["cached"])
        self.assertEqual(self.cloud.call_count, 1)
        self.assertEqual(len(key), 64)
        with mock.patch.object(asr, "API_KEY", "another-secret"), mock.patch.object(asr, "API_BASE", "https://user:password@other.invalid"):
            self.assertEqual(key, asr._cache_key(audio, "cloud"))
        for name, value in [("API_MODEL", "other"), ("LANG", "en")]:
            with self.subTest(name=name), mock.patch.object(asr, name, value):
                self.assertNotEqual(key, asr._cache_key(audio, "cloud"))
                self.assertFalse(self.transcribe()[1]["cached"])
        self.assertNotEqual(key, asr._cache_key(audio, "local"))
        with mock.patch.object(asr, "BACKEND_ENV", "local"):
            self.assertEqual(self.transcribe()[0], "本地文本")
        local_key = asr._cache_key(audio, "local")
        with mock.patch.object(asr, "LOCAL_MODEL", "tiny"):
            self.assertNotEqual(local_key, asr._cache_key(audio, "local"))
        self.assertNotEqual(key, asr._cache_key(audio + b"different", "cloud"))
        for file in self.cache.iterdir():
            self.assertNotIn("secret", file.name + file.read_text(encoding="utf-8"))

    def test_unwritable_cache_directory_degrades(self):
        self.patch("CACHE_ENABLED", True)
        self.cache.write_text("这是文件而非目录", encoding="utf-8")
        self.assertTrue(self.transcribe()[1]["ok"])
        with mock.patch.object(asr.os, "makedirs", side_effect=PermissionError("sensitive")):
            self.assertTrue(self.transcribe()[1]["ok"])
        with mock.patch("builtins.open", side_effect=PermissionError("sensitive")):
            self.assertIsNone(asr._cache_get("a" * 64))

    def test_atomic_cache_write_and_failure_cleanup(self):
        self.patch("CACHE_ENABLED", True)
        key = "a" * 64
        asr._cache_put(key, "原始文本")
        original_replace = os.replace

        def inspect_replace(source, target):
            self.assertEqual(Path(source).parent, self.cache)
            self.assertEqual(json.loads(Path(source).read_bytes())["text"], "更新文本")
            self.assertEqual(json.loads(Path(target).read_bytes())["text"], "原始文本")
            original_replace(source, target)

        with mock.patch.object(asr.os, "replace", side_effect=inspect_replace) as replace:
            asr._cache_put(key, "更新文本")
            replace.assert_called_once()
        self.assertEqual(asr._cache_get(key), "更新文本")
        with mock.patch.object(asr.os, "replace", side_effect=PermissionError("secret")):
            asr._cache_put(key, "失败文本")
        self.assertEqual(asr._cache_get(key), "更新文本")
        self.assertEqual(len(list(self.cache.iterdir())), 1)

    def test_cache_ttl_corruption_and_entry_limit(self):
        self.patch("CACHE_ENABLED", True)
        self.cache.mkdir()
        key = "b" * 64
        file = Path(asr._cache_path(key))
        now = time.time()
        cases = [b"not-json", b"[]", b'{"text":42}', b"x" * (asr.CACHE_MAX_ENTRY_BYTES + 1)]
        for created in [now - asr.CACHE_TTL, now + 60, float("nan"), float("inf"), True]:
            cases.append(json.dumps({"created": created, "text": "旧文本"}).encode())
        for payload in cases:
            with self.subTest(payload=payload[:70]):
                file.write_bytes(payload)
                self.assertIsNone(asr._cache_get(key))
        with mock.patch.object(asr.time, "time", return_value=now):
            file.write_text(json.dumps({"created": now - asr.CACHE_TTL + 1, "text": "有效文本"}), encoding="utf-8")
            self.assertEqual(asr._cache_get(key), "有效文本")
        file.unlink()
        asr._cache_put(key, "长" * asr.CACHE_MAX_ENTRY_BYTES)
        self.assertFalse(file.exists())

    def test_cache_capacity_total_size_and_expired_cleanup(self):
        self.patch("CACHE_ENABLED", True)
        self.cache.mkdir()
        unrelated = self.cache / "llm_keep.json"
        unrelated.write_text("保留", encoding="utf-8")
        expired = self.cache / "asr_old.json"
        expired.write_text("过期", encoding="utf-8")
        old = time.time() - asr.CACHE_TTL - 1
        os.utime(expired, (old, old))
        for index in range(257):
            asr._cache_put(f"{index:064x}", "容量测试")
        files = list(self.cache.glob("asr_*.json"))
        self.assertEqual(len(files), 256)
        self.assertFalse(expired.exists())
        self.assertTrue(unrelated.exists())
        self.patch("CACHE_MAX_BYTES", 160)
        asr._cache_put("f" * 64, "大小测试")
        self.assertLessEqual(sum(file.stat().st_size for file in self.cache.glob("asr_*.json")), 160)

    def test_concurrent_cache_writes_remain_valid_and_bounded(self):
        self.patch("CACHE_ENABLED", True)
        self.patch("CACHE_MAX_ENTRIES", 4)
        threads = [threading.Thread(target=asr._cache_put, args=(f"{index:064x}", "并发文本")) for index in range(12)]
        for thread in threads:
            thread.start()
        self.join_workers()
        self.assertEqual(len(list(self.cache.iterdir())), 4)
        for file in self.cache.iterdir():
            self.assertEqual(json.loads(file.read_bytes())["text"], "并发文本")

    def test_valid_wav_snapshot_and_exact_duration_limit(self):
        for seconds in [1, 60]:
            with self.subTest(seconds=seconds):
                audio = self.wav(seconds=seconds)
                self.path.write_bytes(audio)
                self.assertTrue(self.transcribe()[1]["ok"])
                self.assertEqual(self.cloud.call_args.args[0], audio)
                self.assertGreater(self.cloud.call_args.kwargs["timeout"], 0)
                self.assertLessEqual(self.cloud.call_args.kwargs["timeout"], 45)
        renamed = self.root / "valid.bin"
        renamed.write_bytes(self.wav())
        self.assertTrue(self.transcribe(str(renamed))[1]["ok"])

    def test_invalid_wav_headers_truncation_and_duration(self):
        audio = self.wav()
        forged = bytearray(audio)
        struct.pack_into("<I", forged, 28, 1)
        damaged_data = bytearray(audio)
        struct.pack_into("<I", damaged_data, 40, len(audio) * 2)
        cases = [b"", b"ID3" + b"x" * 50, b"RIFF" + b"x" * 100,
                 audio[:-2], audio + b"junk", bytes(forged), bytes(damaged_data),
                 self.wav(seconds=0), self.wav(seconds=60 + 1 / 16000)]
        for payload in cases:
            with self.subTest(size=len(payload)):
                self.path.write_bytes(payload)
                self.assertFalse(self.transcribe()[1]["ok"])
        self.cloud.assert_not_called()

    def test_audio_size_limit_and_input_errors(self):
        self.path.write_bytes(b"x" * (asr.MAX_AUDIO_BYTES + 1))
        self.assertIn("10MB", self.transcribe()[1]["reason"])
        for path in ["", str(self.root / "missing.wav"), str(self.root), 123, object()]:
            with self.subTest(path=path):
                self.assertFalse(self.transcribe(path)[1]["ok"])
        self.cloud.assert_not_called()
        audio = self.wav()
        with mock.patch.object(asr, "MAX_AUDIO_BYTES", len(audio)):
            self.path.write_bytes(audio)
            self.assertTrue(self.transcribe()[1]["ok"])

    def test_exact_10mib_wav_and_one_byte_over(self):
        audio = self.wav()
        padding = asr.MAX_AUDIO_BYTES - len(audio) - 8
        exact = bytearray(audio + struct.pack("<4sI", b"JUNK", padding) + b"\0" * padding)
        struct.pack_into("<I", exact, 4, len(exact) - 8)
        self.assertEqual(len(exact), 10 * 1024 * 1024)
        self.path.write_bytes(exact)
        self.assertTrue(self.transcribe()[1]["ok"])
        self.path.write_bytes(exact + b"\0")
        self.assertIn("10MB", self.transcribe()[1]["reason"])
        self.assertEqual(self.cloud.call_count, 1)

    def test_input_validation_precedes_cache_hit(self):
        self.patch("CACHE_ENABLED", True)
        with mock.patch.object(asr, "_cache_get", return_value="缓存文本") as get:
            self.path.write_bytes(b"not-wav")
            self.assertFalse(self.transcribe()[1]["ok"])
            get.assert_not_called()

    def test_cloud_errors_never_echo_body_or_exception(self):
        secret = "secret-test-key response-private /private/location"
        # 恢复真实适配器，但 requests 整个模块均为离线替身。
        real_cloud = _REAL_CLOUD
        self.patch("_transcribe_cloud", real_cloud)
        for status, payload, error in [(401, None, None), (302, None, None),
                                      (200, None, ValueError(secret)), (200, [secret], None),
                                      (200, {"error": secret}, None)]:
            with self.subTest(status=status, payload=payload):
                response = mock.Mock(status_code=status)
                response.json = mock.Mock(return_value=payload, side_effect=error)
                type(response).text = mock.PropertyMock(side_effect=AssertionError("禁止访问响应正文"))
                requests = types.SimpleNamespace(post=mock.Mock(return_value=response))
                with mock.patch.dict(sys.modules, {"requests": requests}):
                    text, meta = self.transcribe()
                self.assertFalse(meta["ok"])
                self.assertNotIn(secret, text + str(meta))
                self.assertNotIn("secret-test-key", str(meta))
                response.close.assert_called_once()
        requests = types.SimpleNamespace(post=mock.Mock(side_effect=RuntimeError(secret)))
        with mock.patch.dict(sys.modules, {"requests": requests}):
            self.assertNotIn(secret, str(self.transcribe()))

    def test_cloud_valid_json_fields_and_no_redirect(self):
        self.patch("_transcribe_cloud", _REAL_CLOUD)
        for payload in [{"text": "云端文本"}, {"output": {"text": "云端文本"}}]:
            response = mock.Mock(status_code=200)
            response.json.return_value = payload
            requests = types.SimpleNamespace(post=mock.Mock(return_value=response))
            with mock.patch.dict(sys.modules, {"requests": requests}):
                self.assertEqual(self.transcribe()[0], "云端文本")
            kwargs = requests.post.call_args.kwargs
            self.assertFalse(kwargs["allow_redirects"])
            self.assertEqual(kwargs["files"]["file"], ("audio.wav", self.path.read_bytes(), "audio/wav"))

    def test_backend_failure_and_invalid_result_keep_contract(self):
        for result in ["", "嗯", None, {}, 42]:
            with self.subTest(result=result):
                self.cloud.return_value = result
                self.assertFalse(self.transcribe()[1]["ok"])
        self.cloud.side_effect = RuntimeError("secret-test-key private server response")
        self.assertNotIn("secret-test-key", str(self.transcribe()))
        self.patch("BACKEND_ENV", "local")
        self.local.side_effect = RuntimeError("private model path")
        self.assertNotIn("private model path", str(self.transcribe()))

    def test_available_skips_local_probe_in_off_cloud_and_ready_auto(self):
        probe = asr._local_importable
        for backend in ["off", "cloud", "auto"]:
            with mock.patch.object(asr, "BACKEND_ENV", backend):
                asr.available()
        probe.assert_not_called()
        with mock.patch.object(asr, "API_KEY", ""), mock.patch.object(asr, "BACKEND_ENV", "cloud"):
            self.assertFalse(asr.available()["enabled"])
        probe.assert_not_called()
        with mock.patch.object(asr, "BACKEND_ENV", "off"):
            self.assertFalse(self.transcribe()[1]["ok"])

    def test_available_uses_find_spec_without_heavy_import(self):
        self.patch("_local_importable", _REAL_IMPORTABLE)
        self.patch("BACKEND_ENV", "local")
        original_import = __import__

        def guarded_import(name, *args, **kwargs):
            if name.split(".")[0] in {"faster_whisper", "torch", "ctranslate2"}:
                raise AssertionError("available 不得导入重库")
            return original_import(name, *args, **kwargs)

        with mock.patch("builtins.__import__", side_effect=guarded_import):
            for spec, expected in [(object(), True), (None, False)]:
                with mock.patch.object(importlib.util, "find_spec", return_value=spec) as find:
                    self.assertEqual(asr.available()["enabled"], expected)
                    find.assert_called_once_with("faster_whisper")
            with mock.patch.object(importlib.util, "find_spec", side_effect=ValueError("invalid spec")):
                self.assertFalse(asr.available()["enabled"])
        self.patch("BACKEND_ENV", "auto")
        self.patch("API_KEY", "")
        with mock.patch.object(importlib.util, "find_spec", return_value=None):
            self.assertFalse(asr.available()["enabled"])

    def test_local_model_initialization_is_locked_and_retryable(self):
        entered, release = self.event(), self.event()
        instance = object()

        def construct(*args, **kwargs):
            entered.set()
            self.assertTrue(release.wait(2))
            return instance

        constructor = mock.Mock(side_effect=construct)
        results = []
        with mock.patch.dict(sys.modules, {"faster_whisper": types.SimpleNamespace(WhisperModel=constructor)}):
            with mock.patch.object(asr, "_resolve_local_model", return_value="offline-model"):
                first = threading.Thread(target=lambda: results.append(asr._get_local_model()))
                second = threading.Thread(target=lambda: results.append(asr._get_local_model()))
                first.start()
                self.assertTrue(entered.wait(1))
                second.start()
                release.set()
                self.join_workers()
                self.assertEqual(results, [instance, instance])
                constructor.assert_called_once_with("offline-model", device="cpu", compute_type="int8")
                asr._local_model = None
                constructor.side_effect = [RuntimeError("init failure"), instance]
                with self.assertRaises(RuntimeError):
                    asr._get_local_model()
                self.assertIs(asr._get_local_model(), instance)

    def test_local_adapter_consumes_validated_memory_snapshot(self):
        model = mock.Mock()
        model.transcribe.return_value = ([types.SimpleNamespace(text="本地"), types.SimpleNamespace(text="文本")], object())
        with mock.patch.object(asr, "_get_local_model", return_value=model):
            self.assertEqual(_REAL_LOCAL(self.path.read_bytes()), "本地文本")
        self.assertEqual(model.transcribe.call_args.args[0].getvalue(), self.path.read_bytes())

    def test_timeout_retains_two_slots_until_actual_work_finishes(self):
        self.patch("TRANSCRIBE_TIMEOUT", 0.05)
        self.patch("CACHE_ENABLED", True)
        release = self.event()
        entered = [self.event(), self.event()]
        counter_lock = threading.Lock()
        count = 0

        def blocked(*args, **kwargs):
            nonlocal count
            with counter_lock:
                index = count
                count += 1
            entered[index].set()
            release.wait(3)
            return "迟到文本"

        self.cloud.side_effect = blocked
        for event in entered:
            started = time.monotonic()
            _, meta = self.transcribe()
            self.assertTrue(event.is_set())
            self.assertIn("超时", meta["reason"])
            self.assertLess(time.monotonic() - started, 0.5)
        for _ in range(10):
            self.assertIn("繁忙", self.transcribe()[1]["reason"])
        self.assertEqual(self.cloud.call_count, 2)
        release.set()
        self.join_workers()
        self.assertFalse(self.cache.exists(), "超时的迟到文本不得写入缓存")
        self.cloud.side_effect = None
        self.assertTrue(self.transcribe()[1]["ok"])
        self.assertEqual(self.cloud.call_count, 3)

    def test_overall_timeout_also_covers_input_validation(self):
        self.patch("TRANSCRIBE_TIMEOUT", 0.03)
        release, entered = self.event(), self.event()
        original = asr._read_wav

        def slow_read(path):
            entered.set()
            release.wait(3)
            return original(path)

        with mock.patch.object(asr, "_read_wav", side_effect=slow_read):
            self.assertIn("超时", self.transcribe()[1]["reason"])
            self.assertTrue(entered.is_set())
            self.assertTrue(asr._work_slots.acquire(blocking=False))
            self.assertFalse(asr._work_slots.acquire(blocking=False))
            asr._work_slots.release()
            release.set()
            self.join_workers()
        self.cloud.assert_not_called()
        self.assertTrue(self.transcribe()[1]["ok"])

    def test_thread_start_failure_restores_slot(self):
        with mock.patch.object(asr.threading, "Thread", side_effect=RuntimeError("secret")):
            self.assertFalse(self.transcribe()[1]["ok"])
        self.assertTrue(asr._work_slots.acquire(blocking=False))
        self.assertTrue(asr._work_slots.acquire(blocking=False))
        self.assertFalse(asr._work_slots.acquire(blocking=False))
        asr._work_slots.release()
        asr._work_slots.release()


_REAL_CLOUD = asr._transcribe_cloud
_REAL_LOCAL = asr._transcribe_local
_REAL_IMPORTABLE = asr._local_importable

if __name__ == "__main__":
    unittest.main(verbosity=2)
