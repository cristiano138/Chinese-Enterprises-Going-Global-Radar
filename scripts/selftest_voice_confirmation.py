# -*- coding: utf-8 -*-
"""Offline regression for the explicit transcription/confirmation boundary."""
import os
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app_main
import ui_chat
from core import conversation


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
        transcribers = [item for item in functions if item.fn == ui_chat.transcribe]
        senders = [item for item in functions if item.fn == ui_chat.submit_message]
        self.assertTrue(transcribers, "New UI must register transcription callbacks.")
        self.assertGreaterEqual(len(senders), 2, "Both send button and typed submit must use the same service.")
        for transcribe in transcribers:
            # 语音只写输入框 + 预编辑快照，绝不绕过「发送」这一步。
            self.assertEqual(len(transcribe.inputs), 3)   # 音频 / 输入框 / 预编辑快照
            self.assertEqual(len(transcribe.outputs), 3)  # 输入框 / 状态说明 / 预编辑快照
            self.assertIs(transcribe.inputs[1], transcribe.outputs[0])
            self.assertIs(transcribe.inputs[2], transcribe.outputs[2])
            self.assertEqual(transcribe.outputs[1].get_block_name(), "markdown")
            self.assertEqual(transcribe.inputs[0].sources, ["microphone", "upload"])
            self.assertEqual(transcribe.inputs[0].format, "wav")
            for send in senders:
                self.assertEqual(len(send.inputs), 2)
                self.assertIs(transcribe.outputs[0], send.inputs[0])
                self.assertNotIn(transcribe.inputs[0], send.inputs)
                self.assertEqual(send.inputs[1].get_block_name(), "state")

        undo = [item for item in functions if item.fn == ui_chat.undo_voice]
        self.assertTrue(undo, "Pre-edit state must be reversible.")
        for item in undo:
            self.assertEqual(len(item.inputs), 2)
            self.assertEqual(len(item.outputs), 3)
            # 撤销读预编辑快照、写回同一个输入框，同样不触发查询。
            self.assertEqual(item.inputs[0].get_block_name(), "state")
            self.assertIs(item.outputs[0], item.inputs[1])
            for send in senders:
                self.assertIs(item.outputs[0], send.inputs[0])

    def test_unavailable_backend_explains_disabled_upload(self):
        states = [
            {"enabled": False, "detail": "ASR_BACKEND=off"},
            {"enabled": False, "detail": "cloud 缺配置"},
            {"enabled": False, "detail": "未安装 faster-whisper <test>"},
        ]
        for cfg in states:
            with self.subTest(cfg=cfg), patch.object(app_main.asr, "config_summary", return_value=cfg):
                demo = app_main.build_ui()
                transcribe = next(item for item in demo.fns.values() if item.fn == ui_chat.transcribe)
                self.assertFalse(transcribe.inputs[0].interactive)
                hints = " ".join(str(getattr(block, "value", "")) for block in demo.blocks.values())
                self.assertIn("语音服务未启用", hints)
                self.assertIn("继续使用文字", hints)
                self.assertIn("管理员配置", hints)
                buttons = [block for block in demo.blocks.values()
                           if getattr(block, "value", None) == "转写到输入框"]
                self.assertTrue(buttons)
                self.assertTrue(all(not button.interactive for button in buttons))
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

    def test_chat_transcription_never_calls_the_conversation_service(self):
        meta = {"ok": True, "backend": "cloud", "cached": False}
        with patch.object(ui_chat.asr, "transcribe", return_value=("毛绒玩具出口德国", meta)), \
                patch.object(conversation, "respond") as respond:
            text, status, snapshot = ui_chat.transcribe("audio.wav", "原文字")
        self.assertEqual(text, "毛绒玩具出口德国")
        self.assertEqual(snapshot["before"], "原文字")
        self.assertIn("核对", status)
        self.assertIn("尚未", status)
        respond.assert_not_called()

    def test_chat_confirmation_uses_current_edited_text(self):
        state = conversation.new_session()
        with patch.object(conversation, "respond", return_value=(state, None)) as respond:
            ui_chat.submit_message("用户核对并修改后的输入", state)
        respond.assert_called_once_with("用户核对并修改后的输入", state, action=None)

    def test_chat_transcription_failure_preserves_text_and_redacts_errors(self):
        original = "  原文字\n保留末尾空格  "
        with patch.object(ui_chat.asr, "transcribe", side_effect=RuntimeError("secret-token")), \
                patch.object(conversation, "respond") as respond:
            text, status, snapshot = ui_chat.transcribe("audio.wav", original)
        self.assertEqual(text, original)
        self.assertEqual(snapshot, {}, "失败时不应留下预编辑快照")
        self.assertNotIn("secret-token", status)
        self.assertIn("原文字已保留", status)
        respond.assert_not_called()


if __name__ == "__main__":
    unittest.main()
