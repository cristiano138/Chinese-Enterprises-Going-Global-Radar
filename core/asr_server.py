# -*- coding: utf-8 -*-
"""sherpa-onnx 常驻识别服务（core/asr_server.py）—— 模型只加载一次

为什么需要它：
    `sherpa-onnx-offline` 命令行每调用一次就要重新加载 229MB 模型（本机约 3 秒），
    而真正的计算只要 0.4 秒。输入法能"说完就出字"，靠的就是模型常驻。

做法：
    用 sherpa-onnx 自带的 `sherpa-onnx-offline-websocket-server` 起一个**子进程**，
    模型在进程内只加载一次；Python 侧用**标准库**实现一个最小 WebSocket 客户端
    发音频、收结果。仍然不引入任何第三方库。

协议（见 sherpa-onnx 官方 offline-websocket-client 示例）：
    单条消息 = 采样率(4B 小端 int32) + 数据字节数(4B 小端 int32) + float32 采样点
    超过 10240 字节时分片发送；服务端收满声明的长度即开始解码，回一条 JSON 文本。

红线（与 core/asr.py 一致）：
    ❌ 不产生法规编号 / 条款 / 链接 / 结论
    ❌ 不把音频落盘 —— 采样直接在内存里转 float32
    端口只监听 127.0.0.1；子进程随父进程退出（atexit + 守护线程双重兜底）

环境变量：
    ASR_ENGINE_SERVER        auto（默认，失败退回命令行）| on | off
    ASR_ENGINE_SERVER_PORT   0 = 自动挑空闲端口
    ASR_ENGINE_THREADS       服务端工作线程数（复用 asr_engine 的设置）

自检（离线，不要求已下载模型）：
    python core/asr_server.py
"""

import atexit
import base64
import hashlib
import io
import json
import os
import socket
import struct
import subprocess
import sys
import threading
import time
import wave

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)

try:
    from core import asr_engine
except ImportError:  # python core/asr_server.py
    import asr_engine

MODE = (os.getenv("ASR_ENGINE_SERVER") or "auto").strip().lower()
PORT_ENV = (os.getenv("ASR_ENGINE_SERVER_PORT") or "0").strip()
START_TIMEOUT = 30.0          # 首次启动要加载模型，30 秒足够
FIRST_REQUEST_TIMEOUT = 45.0  # 与 asr.py 的 TRANSCRIBE_TIMEOUT 对齐
FRAME_CHUNK = 10240           # 与官方示例一致

_GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

_lock = threading.RLock()
_process = None
_port = 0
_last_error = ""
_last_start = 0.0
_restart_after = 5.0          # 崩溃后退避，避免每次请求都重拉进程


# ── 最小 WebSocket 客户端（RFC 6455，仅客户端侧，只用标准库）──────────
class WebSocketError(Exception):
    pass


class _WebSocket:
    """够用就好的 WebSocket 客户端：文本/二进制帧、分片、ping/pong、close。"""

    def __init__(self, host, port, timeout):
        self._sock = None
        self._buffer = b""
        try:
            self._sock = socket.create_connection((host, port), timeout=timeout)
            self._sock.settimeout(timeout)
            self._handshake(host, port)
        except WebSocketError:
            self.close()
            raise
        except OSError as exc:
            self.close()
            raise WebSocketError(f"连接常驻服务失败（{type(exc).__name__}）") from None

    # — 握手 —
    def _handshake(self, host, port):
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            "GET / HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self._sock.sendall(request.encode("ascii"))
        head = self._read_until(b"\r\n\r\n")
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise WebSocketError("常驻服务未接受 WebSocket 握手")
        expected = base64.b64encode(
            hashlib.sha1(key.encode("ascii") + _GUID).digest()).decode("ascii")
        if expected.encode("ascii") not in head:
            raise WebSocketError("常驻服务握手校验失败")

    def _read_until(self, marker, limit=64 * 1024):
        while marker not in self._buffer:
            if len(self._buffer) > limit:
                raise WebSocketError("常驻服务响应头过长")
            try:
                chunk = self._sock.recv(4096)
            except OSError as exc:
                raise WebSocketError(f"常驻服务连接异常（{type(exc).__name__}）") from None
            if not chunk:
                raise WebSocketError("常驻服务提前断开连接")
            self._buffer += chunk
        head, self._buffer = self._buffer.split(marker, 1)
        return head

    # — 收发 —
    def _send_frame(self, opcode, payload):
        header = bytearray([0x80 | opcode])
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < 1 << 16:
            header.append(0x80 | 126)
            header += struct.pack(">H", length)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", length)
        mask = os.urandom(4)
        header += mask
        # 客户端发出的帧必须掩码（RFC 6455 §5.3）
        try:
            self._sock.sendall(bytes(header) + _mask(payload, mask))
        except OSError as exc:
            raise WebSocketError(f"常驻服务连接异常（{type(exc).__name__}）") from None

    def send_text(self, text):
        self._send_frame(0x1, text.encode("utf-8"))

    def send_binary(self, payload):
        self._send_frame(0x2, payload)

    def _recv_exact(self, count):
        while len(self._buffer) < count:
            try:
                chunk = self._sock.recv(max(4096, count - len(self._buffer)))
            except OSError as exc:
                raise WebSocketError(f"常驻服务连接异常（{type(exc).__name__}）") from None
            if not chunk:
                raise WebSocketError("常驻服务提前断开连接")
            self._buffer += chunk
        data, self._buffer = self._buffer[:count], self._buffer[count:]
        return data

    def recv_message(self):
        """读一条完整消息（自动拼接分片、自动回 pong）。"""
        chunks = []
        while True:
            first, second = self._recv_exact(2)
            opcode = first & 0x0F
            fin = bool(first & 0x80)
            length = second & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._recv_exact(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._recv_exact(8))[0]
            if length > 64 * 1024 * 1024:
                raise WebSocketError("常驻服务返回数据过大")
            mask = self._recv_exact(4) if second & 0x80 else None
            payload = self._recv_exact(length) if length else b""
            if mask:
                payload = _mask(payload, mask)
            if opcode == 0x8:
                raise WebSocketError("常驻服务关闭了连接")
            if opcode == 0x9:  # ping → pong
                self._send_frame(0xA, payload)
                continue
            if opcode == 0xA:
                continue
            chunks.append(payload)
            if fin:
                return b"".join(chunks)

    def close(self):
        if self._sock is not None:
            try:
                self._send_frame(0x8, b"")
            except Exception:  # noqa: BLE001 —— 关闭阶段不再报错
                pass
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None


def _mask(payload, mask):
    """RFC 6455 §5.3 掩码。用 int 异或比逐字节循环快一个量级。"""
    if not payload:
        return b""
    length = len(payload)
    key = int.from_bytes((mask * (length // 4 + 1))[:length], "big")
    return (int.from_bytes(payload, "big") ^ key).to_bytes(length, "big")


# ── WAV → float32 采样 ────────────────────────────────────────
def wav_to_samples(audio):
    """把已校验的 WAV 字节转成 (float32 采样点 bytes, 采样率, 声道数)。"""
    with wave.open(io.BytesIO(audio), "rb") as handle:
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        rate = handle.getframerate()
        frames = handle.getnframes()
        raw = handle.readframes(frames)
    if width == 2:
        count = len(raw) // 2
        values = struct.unpack(f"<{count}h", raw)
        scale = 32768.0
    elif width == 1:
        values = tuple((byte - 128) for byte in raw)
        scale = 128.0
    elif width == 4:
        count = len(raw) // 4
        values = struct.unpack(f"<{count}i", raw)
        scale = 2147483648.0
    else:
        raise WebSocketError("不支持的采样位宽")
    samples = [value / scale for value in values]
    if channels > 1:  # 下混成单声道
        samples = [sum(samples[i:i + channels]) / channels
                   for i in range(0, len(samples) - channels + 1, channels)]
    return struct.pack(f"<{len(samples)}f", *samples), rate


# ── 进程管理 ──────────────────────────────────────────────────
def _free_port():
    if PORT_ENV.isdigit() and int(PORT_ENV) > 0:
        return int(PORT_ENV)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _server_binary():
    name = ("sherpa-onnx-offline-websocket-server.exe" if sys.platform == "win32"
            else "sherpa-onnx-offline-websocket-server")
    candidate = os.path.join(asr_engine.bin_dir(), name)
    return candidate if os.path.isfile(candidate) else ""


def _command(port):
    onnx, tokens = asr_engine.model_files()
    language = (os.getenv("ASR_LANG") or "auto").strip() or "auto"
    return [_server_binary(),
            f"--port={port}",
            f"--num-work-threads={asr_engine.THREADS}",
            f"--max-batch-size=1",
            f"--tokens={asr_engine._cli_path(tokens)}",
            f"--sense-voice-model={asr_engine._cli_path(onnx)}",
            f"--sense-voice-language={language}",
            "--sense-voice-use-itn=1",
            # 服务默认把 log.txt 写到当前目录；指到被 .gitignore 的 models/ 下，
            # 避免在仓库根目录留下运行日志。
            f"--log-file={asr_engine._cli_path(os.path.join(asr_engine.ROOT, 'asr-server.log'))}"]


def _wait_ready(port, process, deadline):
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def start():
    """确保常驻服务在跑。返回 (ok, 原因)。不抛异常。"""
    global _process, _port, _last_error, _last_start
    if MODE == "off":
        return False, "常驻服务已按配置关闭（ASR_ENGINE_SERVER=off）"
    with _lock:
        if _process is not None and _process.poll() is None:
            return True, ""
        if time.monotonic() - _last_start < _restart_after and _last_error:
            return False, _last_error  # 退避期内不反复拉起
        state = asr_engine.status()
        if not state["ready"]:
            return False, state["detail"]
        binary = _server_binary()
        if not binary:
            _last_error = "引擎包里没有常驻服务可执行文件"
            return False, _last_error
        port = _free_port()
        options = {}
        if sys.platform == "win32":
            options["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        _last_start = time.monotonic()
        try:
            _process = subprocess.Popen(
                _command(port), cwd=asr_engine.PROJECT,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, **options)
        except (OSError, ValueError):
            _process, _last_error = None, "常驻服务启动失败"
            return False, _last_error
        if not _wait_ready(port, _process, time.monotonic() + START_TIMEOUT):
            _last_error = "常驻服务启动超时"
            stop()
            return False, _last_error
        _port, _last_error = port, ""
        return True, ""


def stop():
    """停掉子进程。可重复调用。"""
    global _process, _port
    with _lock:
        process, _process, _port = _process, None, 0
    if process is None:
        return
    try:
        process.terminate()
        process.wait(timeout=5)
    except Exception:  # noqa: BLE001
        try:
            process.kill()
        except Exception:  # noqa: BLE001
            pass


def running():
    with _lock:
        return _process is not None and _process.poll() is None


def state():
    """给界面显示的状态（不含端口以外的本机路径）。"""
    with _lock:
        alive = _process is not None and _process.poll() is None
        return {"mode": MODE, "running": alive,
                "detail": "常驻识别服务（模型已加载）" if alive else (_last_error or "未启动")}


# ── 转写 ──────────────────────────────────────────────────────
def transcribe(audio, timeout=FIRST_REQUEST_TIMEOUT, language="auto"):
    """WAV 字节 → 文本。失败抛 WebSocketError，由上层决定是否退回命令行。"""
    ok, reason = start()
    if not ok:
        raise WebSocketError(reason)
    payload, rate = wav_to_samples(audio)
    with _lock:
        port = _port
    if not port:
        raise WebSocketError("常驻服务未就绪")
    started = time.monotonic()
    client = None
    try:
        client = _WebSocket("127.0.0.1", port, timeout)
        message = struct.pack("<ii", rate, len(payload)) + payload
        offset = 0
        while offset < len(message):
            client.send_binary(message[offset:offset + FRAME_CHUNK])
            offset += FRAME_CHUNK
        raw = client.recv_message().decode("utf-8", "replace").strip()
    except WebSocketError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise WebSocketError(f"常驻服务调用失败（{type(exc).__name__}）") from None
    finally:
        if client is not None:
            client.close()
    text = _extract_text(raw)
    return text, {"engine": "sherpa-onnx-server", "seconds": round(time.monotonic() - started, 3)}


def _extract_text(raw):
    """服务端回的是 JSON 文本；兼容极少数版本回纯文本。"""
    if not raw:
        return ""
    try:
        payload = json.loads(raw)
    except ValueError:
        return raw
    if isinstance(payload, dict) and isinstance(payload.get("text"), str):
        return payload["text"]
    return ""


atexit.register(stop)


# ── 自检 ──────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 66)
    print("  sherpa-onnx 常驻识别服务 · 自检")
    print("=" * 66)
    fails = []
    info = state()
    print(f"  模式：{info['mode']}　状态：{info['detail']}")
    print(f"  引擎：{asr_engine.status()['detail']}")
    print()

    ok = _extract_text('{"text": "毛绒玩具"}') == "毛绒玩具"
    print(f"  [{'PASS' if ok else 'FAIL'}] 解析服务端 JSON")
    if not ok:
        fails.append("解析 JSON")

    ok = _extract_text("纯文本兜底") == "纯文本兜底"
    print(f"  [{'PASS' if ok else 'FAIL'}] 兼容纯文本响应")
    if not ok:
        fails.append("纯文本")

    stream = io.BytesIO()
    with wave.open(stream, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * 16000)
    samples, rate = wav_to_samples(stream.getvalue())
    ok = rate == 16000 and len(samples) == 16000 * 4
    print(f"  [{'PASS' if ok else 'FAIL'}] WAV → float32（{rate}Hz，{len(samples)}B）")
    if not ok:
        fails.append("WAV 转换")

    # 掩码必须可逆：同一份数据掩两次应还原
    payload = b"abcdefg"
    ok = _mask(_mask(payload, b"\x01\x02\x03\x04"), b"\x01\x02\x03\x04") == payload
    print(f"  [{'PASS' if ok else 'FAIL'}] WebSocket 掩码可逆")
    if not ok:
        fails.append("掩码")

    ok, reason = start()
    if ok:
        print("  [PASS] 常驻服务可启动")
        print(f"  [INFO] 端口 {_port}")
        stop()
    else:
        print(f"  [SKIP] 常驻服务未启动（{reason[:50]}）")

    print()
    print("=" * 66)
    print("  结果：全部通过" if not fails else f"  结果：失败 {len(fails)} 项")
    for item in fails:
        print(f"    ❌ {item}")
    print("=" * 66)
    sys.exit(0 if not fails else 1)
