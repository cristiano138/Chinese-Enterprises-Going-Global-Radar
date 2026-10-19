# -*- coding: utf-8 -*-
"""常驻识别服务自检（scripts/selftest_asr_server.py）

全部离线：不启动真实引擎、不联网、不要求模型已下载。
手写的 WebSocket 客户端是本项目唯一「自己实现协议」的地方，必须单独盯住：
帧长度编码、分片拼接、ping/pong、close、掩码可逆。

用法：
    python scripts/selftest_asr_server.py
退出码 0 = 全绿。
"""

import io
import json
import os
import socket
import struct
import sys
import threading
import wave
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

from core import asr_engine, asr_server  # noqa: E402

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"　{detail}" if detail else ""))


def section(title):
    print()
    print(f"  ── {title} " + "─" * max(0, 56 - len(title)))


# ── 构造测试帧 ────────────────────────────────────────────────
def frame(opcode, payload, fin=True, extended=None):
    """构造服务端 → 客户端的帧（服务端不加掩码）。"""
    first = (0x80 if fin else 0) | opcode
    length = len(payload)
    if extended == 126 or (extended is None and 126 <= length < 65536):
        header = bytes([first, 126]) + struct.pack(">H", length)
    elif extended == 127 or (extended is None and length >= 65536):
        header = bytes([first, 127]) + struct.pack(">Q", length)
    else:
        header = bytes([first, length])
    return header + payload


def paired_client():
    """把 _WebSocket 挂到 socketpair 的一端，绕过握手。"""
    mine, theirs = socket.socketpair()
    client = object.__new__(asr_server._WebSocket)
    client._sock = mine
    client._buffer = b""
    return client, theirs, mine


def wav_bytes(rate=16000, seconds=1, channels=1, width=2):
    stream = io.BytesIO()
    with wave.open(stream, "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(width)
        handle.setframerate(rate)
        handle.writeframes(b"\x00" * int(rate * seconds) * width * channels)
    return stream.getvalue()


# ── A · 协议层 ────────────────────────────────────────────────
def test_protocol():
    section("A · 手写 WebSocket 客户端")

    payload = b"abcdefg"
    key = b"\x01\x02\x03\x04"
    check("掩码可逆", asr_server._mask(asr_server._mask(payload, key), key) == payload)
    check("空载荷安全", asr_server._mask(b"", key) == b"")

    client, theirs, mine = paired_client()
    try:
        theirs.sendall(frame(0x1, b'{"text": "\xe6\xaf\x9b\xe7\xbb\x92"}'))
        got = client.recv_message()
        check("文本帧解析", json.loads(got.decode("utf-8"))["text"] == "毛绒", got[:20])
    finally:
        client.close()
        theirs.close()

    client, theirs, mine = paired_client()
    try:
        body = b"x" * 200  # 走 126 扩展长度
        theirs.sendall(frame(0x2, body))
        check("126 扩展长度", client.recv_message() == body)
    finally:
        client.close()
        theirs.close()

    client, theirs, mine = paired_client()
    try:
        body = b"y" * 70000  # 走 127 扩展长度
        writer = threading.Thread(target=theirs.sendall, args=(frame(0x2, body),),
                                  daemon=True)
        writer.start()
        got = client.recv_message()
        writer.join(5)
        check("127 扩展长度（70KB）", got == body and len(got) == 70000)
    finally:
        client.close()
        theirs.close()

    client, theirs, mine = paired_client()
    try:
        theirs.sendall(frame(0x1, b'{"text": "half', fin=False))
        theirs.sendall(frame(0x0, b'-done"}', fin=True))
        check("分片拼接", client.recv_message() == b'{"text": "half-done"}')
    finally:
        client.close()
        theirs.close()

    client, theirs, mine = paired_client()
    try:
        # ping 后必须继续读下一条帧，否则 recv_message 会一直等下一条消息
        theirs.sendall(frame(0x9, b"hb") + frame(0x1, b"ok"))
        message = client.recv_message()
        theirs.settimeout(2)
        pong = theirs.recv(16)
        check("ping → pong 且继续读下一条", message == b"ok" and (pong[0] & 0x0F) == 0x0A,
              f"msg={message!r} opcode={pong[0] & 0x0F if pong else None}")
    finally:
        client.close()
        theirs.close()

    client, theirs, mine = paired_client()
    try:
        theirs.sendall(frame(0x8, b""))
        try:
            client.recv_message()
        except asr_server.WebSocketError:
            check("close 帧 → 明确异常", True)
        else:
            check("close 帧 → 明确异常", False)
    finally:
        client.close()
        theirs.close()

    client, theirs, mine = paired_client()
    try:
        client._sock.close()  # 对端已断
        try:
            client.recv_message()
        except asr_server.WebSocketError:
            check("对端断开 → 明确异常", True)
        else:
            check("对端断开 → 明确异常", False)
    finally:
        theirs.close()


# ── B · 音频转换 ──────────────────────────────────────────────
def test_audio():
    section("B · WAV → float32")

    samples, rate = asr_server.wav_to_samples(wav_bytes())
    check("16bit 单声道", rate == 16000 and len(samples) == 16000 * 4, f"{len(samples)}B")

    samples, rate = asr_server.wav_to_samples(wav_bytes(channels=2))
    check("立体声下混单声道", rate == 16000 and len(samples) == 16000 * 4, f"{len(samples)}B")

    samples, rate = asr_server.wav_to_samples(wav_bytes(width=1))
    check("8bit 也能转", rate == 16000 and len(samples) == 16000 * 4, f"{len(samples)}B")

    try:
        asr_server.wav_to_samples(b"not-a-wav")
    except Exception:
        check("坏 WAV → 抛异常（由上层折叠）", True)
    else:
        check("坏 WAV → 抛异常（由上层折叠）", False)


# ── C · 响应与状态 ────────────────────────────────────────────
def test_state_and_response():
    section("C · 状态与响应解析")

    check("解析 JSON 文本", asr_server._extract_text('{"text": "毛绒玩具"}') == "毛绒玩具")
    check("兼容纯文本", asr_server._extract_text("纯文本") == "纯文本")
    check("空响应 → 空串", asr_server._extract_text("") == "")
    check("缺 text 字段 → 空串", asr_server._extract_text('{"lang": "zh"}') == "")

    check("state() 字段完整",
          set(asr_server.state()) == {"mode", "running", "detail"})

    saved = {name: getattr(asr_server, name) for name in
             ("MODE", "_process", "_port", "_last_error", "_last_start")}
    try:
        asr_server.MODE = "off"
        ok, reason = asr_server.start()
        check("MODE=off 不启动", not ok and "关闭" in reason, reason)

        asr_server.MODE = "auto"
        with mock.patch.object(asr_engine, "status",
                               return_value={"ready": False, "detail": "缺少 SenseVoice 模型"}):
            asr_server._process, asr_server._last_error, asr_server._last_start = None, "", 0.0
            ok, reason = asr_server.start()
            check("引擎缺失 → 不启动且说明原因", not ok and "缺少" in reason, reason)

        asr_server._last_error = ""
        # 同时把「引擎已就绪」摆好：否则在没下载模型的机器上，start() 会先卡在
        # 「引擎缺失」那一关，这条用例就永远测不到「有引擎但缺常驻可执行文件」。
        with mock.patch.object(asr_engine, "status",
                               return_value={"ready": True, "detail": ""}), \
                mock.patch.object(asr_server, "_server_binary", return_value=""):
            asr_server._process, asr_server._last_start = None, 0.0
            ok, reason = asr_server.start()
            check("缺常驻可执行文件 → 不启动", not ok and "常驻服务" in reason, reason)

        asr_server._last_error = ""
        asr_server._process, asr_server._last_start = None, 0.0
        # 这里必须把可执行文件也挡掉：否则会真的拉起一个服务，
        # 测试就变成了「依赖本机模型」的网络/进程测试。
        with mock.patch.object(asr_server, "_server_binary", return_value=""):
            try:
                asr_server.transcribe(wav_bytes())
            except asr_server.WebSocketError:
                check("不可用时 transcribe 抛 WebSocketError", True)
            else:
                check("不可用时 transcribe 抛 WebSocketError", False)
        asr_server._last_error = ""
    finally:
        for name, value in saved.items():
            setattr(asr_server, name, value)
        asr_server.stop()


if __name__ == "__main__":
    print("=" * 66)
    print("  sherpa-onnx 常驻识别服务 · 自检")
    print("=" * 66)
    test_protocol()
    test_audio()
    test_state_and_response()
    print()
    print("=" * 66)
    if FAIL:
        print(f"  结果：失败 {len(FAIL)} 项")
        for item in FAIL:
            print(f"    ❌ {item}")
    else:
        print(f"  结果：全部通过（{len(PASS)} 项）")
    print("=" * 66)
    sys.exit(1 if FAIL else 0)
