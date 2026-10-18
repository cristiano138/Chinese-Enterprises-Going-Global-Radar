# -*- coding: utf-8 -*-
"""Offline regression for the explicit transcription/confirmation boundary."""
import os
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app_main


class VoiceConfirmationTests(unittest.TestCase):
    def test_dotenv_loaded_before_asr(self):
        code = '''
import os
from unittest.mock import patch
import dotenv

def load_config(*args, **kwargs):
    os.environ.update(ASR_BACKEND="cloud", ASR_API_BASE="https://asr.invalid/v1",
                      ASR_API_KEY="synthetic-test-key", ASR_MODEL="synthetic-model")

with patch.object(dotenv, "load_dotenv", side_effect=load_config):
    import app_main
assert app_main.asr.BACKEND_ENV == "cloud"
assert app_main.asr.API_MODEL == "synthetic-model"
assert app_main.asr.available()["enabled"]
'''
        result = subprocess.run([sys.executable, "-c", code],
                                cwd=os.path.dirname(app_main.__file__),
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_transcription_never_routes(self):
        meta = {"ok": True, "backend": "cloud", "cached": False, "seconds": 0.1}
        with patch.object(app_main.asr, "transcribe", return_value=("毛绒玩具出口德国", meta)), patch.object(app_main, "run_route") as route:
            html, text = app_main.run_voice_transcription("audio.wav", "原文字", "上下文")
        self.assertEqual(text, "毛绒玩具出口德国")
        self.assertIn("开始判定", html)
        self.assertNotIn("判定卡", html)
        route.assert_not_called()

    def test_missing_audio_preserves_text(self):
        with patch.object(app_main, "run_route") as route:
            html, text = app_main.run_voice_transcription(None, "原文字", "")
        self.assertEqual(text, "原文字")
        self.assertIn("请先录音", html)
        route.assert_not_called()

    def test_failure_preserves_text(self):
        with patch.object(app_main.asr, "transcribe", return_value=("", {"ok": False, "reason": "失败"})), patch.object(app_main, "run_route") as route:
            html, text = app_main.run_voice_transcription("audio.wav", "原文字", "")
        self.assertEqual(text, "原文字")
        self.assertNotIn("判定卡", html)
        route.assert_not_called()

    def test_failure_preserves_whitespace(self):
        original = "  原文字\n保留末尾空格  "
        for result in (patch.object(app_main.asr, "transcribe", return_value=("", {"ok": False, "reason": "失败"})),
                       patch.object(app_main.asr, "transcribe", side_effect=RuntimeError("服务异常"))):
            with result, patch.object(app_main, "run_route") as route:
                _, text = app_main.run_voice_transcription("audio.wav", original, "")
            self.assertEqual(text, original)
            route.assert_not_called()

    def test_exception_is_redacted(self):
        with patch.object(app_main.asr, "transcribe", side_effect=RuntimeError("secret-token")):
            html, text = app_main.run_voice_transcription("audio.wav", "原文字", "")
        self.assertEqual(text, "原文字")
        self.assertNotIn("secret-token", html)
        self.assertIn("暂不可用", html)

    def test_transcription_is_html_escaped(self):
        with patch.object(app_main.asr, "transcribe", return_value=("<script>bad</script>", {"ok": True})):
            html, text = app_main.run_voice_transcription("audio.wav", "", "")
        self.assertNotIn("<script>", html)
        self.assertEqual(text, "<script>bad</script>")

    def test_ui_bindings_require_confirmation(self):
        demo = app_main.build_ui()
        functions = list(demo.fns.values())
        transcribe = next(item for item in functions if item.fn == app_main.run_voice_transcription)
        route = next(item for item in functions if item.fn == app_main.run_route)
        self.assertEqual(len(transcribe.inputs), 3)
        self.assertEqual(len(route.inputs), 2)
        self.assertIs(transcribe.outputs[1], route.inputs[0])
        self.assertEqual(route.inputs[0].label, "① 你的生意（一句话，或整份产品/合同文件）")
        self.assertNotIn(transcribe.inputs[0], route.inputs)
        self.assertEqual(transcribe.inputs[0].sources, ["microphone", "upload"])
        self.assertEqual(transcribe.inputs[0].format, "wav")

    def test_unavailable_backend_explains_disabled_upload(self):
        states = [
            {"enabled": False, "detail": "ASR_BACKEND=off"},
            {"enabled": False, "detail": "cloud 缺配置"},
            {"enabled": False, "detail": "未安装 faster-whisper <test>"},
        ]
        for cfg in states:
            with self.subTest(cfg=cfg), patch.object(app_main.asr, "config_summary", return_value=cfg):
                demo = app_main.build_ui()
                transcribe = next(item for item in demo.fns.values() if item.fn == app_main.run_voice_transcription)
                self.assertFalse(transcribe.inputs[0].interactive)
                hints = " ".join(str(getattr(block, "value", "")) for block in demo.blocks.values())
                self.assertIn("录音/上传转写暂不可用", hints)
                self.assertIn("ASR_API_BASE", hints)
                self.assertIn("ASR_API_KEY", hints)
                self.assertIn("ASR_MODEL", hints)
                self.assertNotIn("<test>", hints)

    def test_backend_status_exception_is_safe(self):
        with patch.object(app_main.asr, "config_summary", side_effect=RuntimeError("secret-token")):
            status = app_main._asr_status_line()
        self.assertIn("暂不可用", status)
        self.assertNotIn("secret-token", status)

    def test_confirmation_uses_edited_text(self):
        with patch.object(app_main.m15_router, "route", return_value={"ok": False}) as route, patch.object(app_main.m15_router, "render_parse", return_value="待确认"):
            app_main.run_route("用户修改后的文字", "补充内容")
        route.assert_called_once_with("用户修改后的文字", "补充内容")


if __name__ == "__main__":
    unittest.main()
