# -*- coding: utf-8 -*-
"""Offline regression for the explicit transcription/confirmation boundary."""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app_main


class VoiceConfirmationTests(unittest.TestCase):
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

    def test_confirmation_uses_edited_text(self):
        with patch.object(app_main.m15_router, "route", return_value={"ok": False}) as route, patch.object(app_main.m15_router, "render_parse", return_value="待确认"):
            app_main.run_route("用户修改后的文字", "补充内容")
        route.assert_called_once_with("用户修改后的文字", "补充内容")


if __name__ == "__main__":
    unittest.main()
