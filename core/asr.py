# -*- coding: utf-8 -*-
"""
语音识别（core/asr.py）—— 说一句话，变成 M1.5 能吃的字符串

定位（不可越界，与 core/llm.py 同级约束）：
    ASR 只做「音频 → 文字」。它**不理解、不归类、不产生任何合规结论**。
    转写出来的文本交给 modules/m15_router.py，与用户手打字走**完全相同**的链路。
    因此语音不会、也不允许绕过 core/verify.py 的引用对齐。

四级后端（按可用性自动选；任何情况都不抛异常）：
    ① cloud  —— OpenAI 兼容的 /audio/transcriptions（配 ASR_API_BASE + ASR_API_KEY + ASR_MODEL）
    ② engine —— ★推荐：sherpa-onnx 预编译二进制 + SenseVoice 模型，走子进程，
                 **不装任何 Python ASR 库**（core/asr_engine.py 只用标准库）
    ③ local  —— faster-whisper（历史后端，保留作兜底；需要 pip 依赖，不再推荐）
    ④ off    —— 全都没有 → available()["enabled"] 为 False，界面显示「语音未启用」，
                文本框照常可用，主链路零影响

为什么把 engine 放在 local 之前：
    中文短句 + 领域词是典型场景。SenseVoice 是非自回归模型，官方 184 条真实中文
    音频实测 CER 7.81%，Whisper-large-v3 为 20.02%；CPU 上 SenseVoice 还快一个量级。
    更准 + 更省 + 零 Python 依赖，没有理由继续用 whisper small。

为什么默认不走 cloud：
    本机没有 .env、模型链路未配置，云端 ASR 无法实测。演示不能建立在一个
    「配置好了才能用」的假设上 —— 语音是入口，入口不能有前置条件。

降级顺序（auto）：cloud（显式配了才用）→ engine → local → off。

红线：
    ❌ 不产生法规编号 / 条款号 / 链接 / 结论（那是 corpus + verify 的事）
    ❌ 不把音频存进项目目录（Gradio 传来的临时文件只读不搬，转写完不留副本）
    转写文本默认不落盘；显式开启缓存后按后端、模型、语言及音频摘要隔离。

环境变量（全部可选，不配也能跑）：
    ASR_BACKEND       auto | cloud | engine | local | off     默认 auto
    ASR_API_BASE      例 https://xxx/v1
    ASR_API_KEY       云端密钥（与 MODEL_API_TOKEN 分开，互不复用）
    ASR_MODEL         例 whisper-1 / paraformer-v2
    ASR_LANG          默认 zh；填 auto 交给模型判语言
    ASR_LOCAL_MODEL   本地 Whisper 型号（默认 small，仅 local 后端使用）
    ASR_MODEL_DIR     本地 Whisper 模型下载目录
    ASR_CACHE_ENABLED 默认关闭；1/true/yes/on 显式允许缓存转写文本
    （engine 后端另有 ASR_ENGINE_* 变量，见 core/asr_engine.py）

用法：
    from core import asr
    print(asr.available())
    text, meta = asr.transcribe("path/to/audio.wav")

自检（离线、不联网、不依赖模型是否下好）：
    python core/asr.py
"""

import hashlib
import importlib.util
import io
import json
import math
import os
import stat
import struct
import sys
import tempfile
import threading
import time
import wave

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

try:  # 包内导入（from core import asr）
    from core import asr_engine
except ImportError:  # 直接运行 python core/asr.py
    import asr_engine

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
CACHE_DIR = os.path.join(PROJECT, "data", "cache")

BACKEND_ENV = (os.getenv("ASR_BACKEND") or "auto").strip().lower()
API_BASE = (os.getenv("ASR_API_BASE") or "").strip().rstrip("/")
API_KEY = (os.getenv("ASR_API_KEY") or "").strip()
API_MODEL = (os.getenv("ASR_MODEL") or "").strip()
LANG = (os.getenv("ASR_LANG") or "zh").strip()
LOCAL_MODEL = (os.getenv("ASR_LOCAL_MODEL") or "small").strip()
MODEL_DIR = (os.getenv("ASR_MODEL_DIR") or "").strip()

# 短的转写结果没有意义（"嗯""啊"），当失败处理 —— 不许把噪声送进路由层
MIN_CHARS = 2

CACHE_ENABLED = (os.getenv("ASR_CACHE_ENABLED") or "").strip().lower() in {
    "1", "true", "yes", "on",
}
CACHE_TTL = 7 * 24 * 60 * 60
CACHE_MAX_ENTRIES = 256
CACHE_MAX_ENTRY_BYTES = 64 * 1024
CACHE_MAX_BYTES = 4 * 1024 * 1024
MAX_AUDIO_BYTES = 10 * 1024 * 1024
MAX_AUDIO_SECONDS = 60
TRANSCRIBE_TIMEOUT = 45.0
MAX_CONCURRENT = 2

_local_model = None
_local_model_lock = threading.Lock()
_cache_lock = threading.Lock()
_work_slots = threading.BoundedSemaphore(MAX_CONCURRENT)


# ── 后端探测 ──────────────────────────────────────────────────
def _cloud_ready():
    return bool(API_BASE and API_KEY and API_MODEL)


def _local_importable():
    """只探测依赖位置，不导入模型或其重型依赖。"""
    try:
        return importlib.util.find_spec("faster_whisper") is not None
    except (ImportError, ValueError, AttributeError):
        return False


def _engine_ready():
    """引擎是否已就位（只查文件，**不触发下载、不起进程**）。"""
    try:
        return bool(asr_engine.status().get("ready"))
    except Exception:  # noqa: BLE001 —— 探测失败等同于不可用
        return False


def available():
    """当前可用哪个后端。给界面显示状态用，**不加载模型**。"""
    if BACKEND_ENV == "off":
        return {"enabled": False, "backend": "off",
                "detail": "语音已按配置关闭（ASR_BACKEND=off）"}

    if BACKEND_ENV == "cloud":
        return ({"enabled": True, "backend": "cloud", "detail": "云端转写"}
                if _cloud_ready() else
                {"enabled": False, "backend": "off",
                 "detail": "指定了 cloud 但缺 ASR_API_BASE / ASR_API_KEY / ASR_MODEL"})

    if BACKEND_ENV == "engine":
        return ({"enabled": True, "backend": "engine",
                 "detail": asr_engine.status()["detail"]}
                if _engine_ready() else
                {"enabled": False, "backend": "off",
                 "detail": _engine_missing_detail("指定了 engine 但")})

    if BACKEND_ENV == "local":
        return ({"enabled": True, "backend": "local", "detail": "本地 Whisper 转写"}
                if _local_importable() else
                {"enabled": False, "backend": "off",
                 "detail": "指定了 local 但未安装 faster-whisper"})

    # auto：云端（显式配置才生效）→ sherpa-onnx 引擎 → 本地 Whisper → 关掉
    if _cloud_ready():
        return {"enabled": True, "backend": "cloud", "detail": "云端转写"}
    if _engine_ready():
        return {"enabled": True, "backend": "engine",
                "detail": asr_engine.status()["detail"]}
    if _local_importable():
        return {"enabled": True, "backend": "local",
                "detail": f"本地 Whisper（{LOCAL_MODEL}）转写"}
    return {"enabled": False, "backend": "off",
            "detail": _engine_missing_detail("")}


def _engine_missing_detail(prefix):
    """把「引擎没准备好」翻译成一句管理员能照做的话。"""
    try:
        detail = asr_engine.status()["detail"]
    except Exception:  # noqa: BLE001
        detail = "本地语音引擎不可用"
    return (prefix + detail +
            "；运行 scripts/prepare_asr_engine.py 准备引擎，或继续打字。")


# ── 可选磁盘缓存（不存音频，任何缓存故障均按未命中处理） ──────────
def _cache_path(key):
    return os.path.join(CACHE_DIR, f"asr_{key}.json")


def _cache_key(audio, backend):
    if backend == "cloud":
        model = API_MODEL
    elif backend == "engine":
        model = [asr_engine.MODEL, asr_engine.VERSION]
    else:
        model = [LOCAL_MODEL, MODEL_DIR]
    # 不使用 API_KEY 或可能含凭据的 API_BASE，避免凭据进入缓存标识。
    identity = json.dumps([backend, model, LANG], ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(identity + b"\0" + audio).hexdigest()


def _cache_get(key):
    if not CACHE_ENABLED:
        return None
    try:
        with _cache_lock, open(_cache_path(key), "rb") as fh:
            payload = fh.read(CACHE_MAX_ENTRY_BYTES + 1)
        if len(payload) > CACHE_MAX_ENTRY_BYTES:
            return None
        entry = json.loads(payload)
        created = entry.get("created")
        text = entry.get("text")
        if (not isinstance(created, (int, float)) or isinstance(created, bool)
                or not math.isfinite(created) or not 0 <= time.time() - created < CACHE_TTL
                or not isinstance(text, str) or len(normalize(text)) < MIN_CHARS):
            return None
        return normalize(text)
    except Exception:
        return None


def _prune_cache(reserve=0, replacing=None):
    entries = []
    now = time.time()
    with os.scandir(CACHE_DIR) as files:
        for entry in files:
            if not (entry.name.startswith("asr_") and entry.name.endswith(".json")
                    and entry.is_file(follow_symlinks=False)):
                continue
            info = entry.stat(follow_symlinks=False)
            age = now - info.st_mtime
            if age < 0:
                # Filesystem timestamp conversion can put a just-written file
                # one floating-point tick ahead of time.time() on Windows.
                # Confirm the payload's creation time instead of deleting a
                # valid fresh entry merely because its metadata rounded up.
                try:
                    with open(entry.path, "rb") as fh:
                        payload = fh.read(CACHE_MAX_ENTRY_BYTES + 1)
                    created = json.loads(payload).get("created")
                    if (len(payload) > CACHE_MAX_ENTRY_BYTES or isinstance(created, bool)
                            or not isinstance(created, (int, float)) or not math.isfinite(created)):
                        raise ValueError
                    age = now - created
                except (OSError, ValueError, TypeError, AttributeError):
                    age = -1
            if (not 0 <= age < CACHE_TTL
                    or info.st_size > CACHE_MAX_ENTRY_BYTES):
                os.unlink(entry.path)
            elif entry.path == replacing:
                # The reserved payload replaces this entry; it consumes no
                # additional entry and its old bytes must not be counted twice.
                continue
            else:
                entries.append((info.st_mtime, entry.path, info.st_size))
    total = sum(item[2] for item in entries)
    entries.sort()
    while entries and (len(entries) + bool(reserve) > CACHE_MAX_ENTRIES
                       or total + reserve > CACHE_MAX_BYTES):
        _, path, size = entries.pop(0)
        os.unlink(path)
        total -= size


def _cache_put(key, text):
    if not CACHE_ENABLED:
        return
    temporary = None
    try:
        created = time.time()
        payload = json.dumps({"created": created, "text": text},
                             ensure_ascii=False).encode("utf-8")
        if len(payload) > min(CACHE_MAX_ENTRY_BYTES, CACHE_MAX_BYTES):
            return
        with _cache_lock:
            os.makedirs(CACHE_DIR, exist_ok=True)
            _prune_cache(reserve=len(payload), replacing=_cache_path(key))
            with tempfile.NamedTemporaryFile(mode="wb", dir=CACHE_DIR,
                                             prefix=".asr_", suffix=".tmp",
                                             delete=False) as fh:
                temporary = fh.name
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            # Use the payload's clock for TTL cleanup too. Filesystem commit
            # time is a different sample and can briefly round into the future.
            os.utime(temporary, (created, created))
            os.replace(temporary, _cache_path(key))
            temporary = None
    except Exception:
        pass
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass


class _ASRFailure(Exception):
    pass


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise _ASRFailure("语音转写超时，请稍后重试")
    return remaining


def _read_wav(path):
    """校验实际 RIFF/WAVE 和完整帧，返回同一份只读快照供后端使用。"""
    if not isinstance(path, (str, bytes, os.PathLike)) or not path:
        raise _ASRFailure("音频文件不存在")
    try:
        with open(path, "rb") as fh:
            info = os.fstat(fh.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise _ASRFailure("音频必须是普通 WAV 文件")
            if info.st_size > MAX_AUDIO_BYTES:
                raise _ASRFailure("音频大小超过 10MB")
            audio = fh.read(MAX_AUDIO_BYTES + 1)
    except (OSError, ValueError, TypeError):
        raise _ASRFailure("音频文件不存在或不可读") from None
    if len(audio) > MAX_AUDIO_BYTES:
        raise _ASRFailure("音频大小超过 10MB")
    try:
        if (len(audio) < 12 or audio[:4] != b"RIFF" or audio[8:12] != b"WAVE"
                or struct.unpack_from("<I", audio, 4)[0] + 8 != len(audio)):
            raise ValueError
        offset, data_bytes, fmt = 12, None, None
        while offset < len(audio):
            if offset + 8 > len(audio):
                raise ValueError
            kind, size = struct.unpack_from("<4sI", audio, offset)
            start = offset + 8
            end = start + size
            if end > len(audio):
                raise ValueError
            if kind == b"fmt ":
                if fmt is not None or data_bytes is not None or size < 16:
                    raise ValueError
                fmt = struct.unpack_from("<HHIIHH", audio, start)
            elif kind == b"data":
                if data_bytes is not None or fmt is None:
                    raise ValueError
                data_bytes = size
            offset = end + (size % 2)
        if offset != len(audio) or fmt is None or data_bytes is None:
            raise ValueError
        _, channels, rate, byte_rate, alignment, bits = fmt
        with wave.open(io.BytesIO(audio), "rb") as wav:
            frames = wav.getnframes()
            width = wav.getsampwidth()
            if (channels <= 0 or rate <= 0 or bits != width * 8
                    or alignment != channels * width or byte_rate != rate * alignment
                    or data_bytes % alignment or frames <= 0):
                raise ValueError
            if frames > rate * MAX_AUDIO_SECONDS:
                raise _ASRFailure("音频时长超过 60秒")
            if len(wav.readframes(frames)) != data_bytes:
                raise ValueError
    except (ValueError, EOFError, wave.Error, struct.error, ZeroDivisionError):
        raise _ASRFailure("音频不是有效的 WAV 文件") from None
    return audio


# ── 文本归一 ──────────────────────────────────────────────────
def normalize(text):
    """把口语转写整理成一句干净的话。

    只做「去噪」，不做「补全」——**绝不替用户补上他没说过的类目或市场**，
    否则等于由 ASR 侧制造事实，路由层就失去了「识别依据可追溯」。
    """
    t = (text or "").strip()
    for ch in ("\r", "\n", "\t"):
        t = t.replace(ch, " ")
    while "  " in t:
        t = t.replace("  ", " ")
    return t.strip(" ，,。.、；;：:")


# ── 后端实现 ──────────────────────────────────────────────────
def _transcribe_cloud(audio, timeout=TRANSCRIBE_TIMEOUT):
    """仅接受结构化转写字段，错误与非 JSON 响应均不回显正文。"""
    import requests

    data = {"model": API_MODEL}
    if LANG and LANG != "auto":
        data["language"] = LANG
    resp = None
    try:
        resp = requests.post(
            f"{API_BASE}/audio/transcriptions",
            headers={"Authorization": f"Bearer {API_KEY}"},
            data=data, files={"file": ("audio.wav", audio, "audio/wav")},
            timeout=timeout, allow_redirects=False,
        )
        if not 200 <= resp.status_code < 300:
            raise _ASRFailure("云端语音服务请求失败")
        j = resp.json()
        if isinstance(j, dict):
            if isinstance(j.get("text"), str):
                return j["text"]
            out = j.get("output")
            if isinstance(out, dict) and isinstance(out.get("text"), str):
                return out["text"]
        raise _ASRFailure("云端语音服务返回格式无效")
    except _ASRFailure:
        raise
    except Exception:
        raise _ASRFailure("云端语音服务请求失败") from None
    finally:
        if resp is not None:
            try:
                resp.close()
            except Exception:
                pass


def _resolve_local_model():
    """决定本地模型从哪加载。

    顺序：
      ① ASR_LOCAL_MODEL 本身是目录 → 直接用它（离线部署 / 手工拷模型）
      ② 约定缓存目录 ~/.cache/compliance-radar/asr/faster-whisper-<模型名> 存在 → 用它
         （scripts/prepare_asr.py 会把模型下到这里；避免 Windows 下 HF 软链接失败）
      ③ 否则交给 HuggingFace 按模型名下载（需要网络，国内建议配 HF_ENDPOINT）
    """
    if LOCAL_MODEL and os.path.isdir(LOCAL_MODEL):
        return LOCAL_MODEL
    cand = os.path.join(os.path.expanduser("~"), ".cache", "compliance-radar",
                        "asr", f"faster-whisper-{LOCAL_MODEL}")
    if os.path.isdir(cand) and os.path.exists(os.path.join(cand, "model.bin")):
        return cand
    return LOCAL_MODEL


def _get_local_model():
    """懒加载本地模型。首次加载 2–8 秒（模型文件只下不重复下）。"""
    global _local_model
    with _local_model_lock:
        if _local_model is None:
            from faster_whisper import WhisperModel
            kwargs = {"device": "cpu", "compute_type": "int8"}
            if MODEL_DIR:
                kwargs["download_root"] = MODEL_DIR
            _local_model = WhisperModel(_resolve_local_model(), **kwargs)
        return _local_model


def _transcribe_local(audio):
    model = _get_local_model()
    lang = None if LANG == "auto" else (LANG or None)
    segments, info = model.transcribe(
        io.BytesIO(audio), language=lang, beam_size=5, vad_filter=True,
        vad_parameters={"threshold": 0.35, "min_silence_duration_ms": 500,
                        "speech_pad_ms": 500},
        condition_on_previous_text=False,
    )
    return "".join(seg.text for seg in segments).strip()


def _transcribe_engine(audio, timeout=TRANSCRIBE_TIMEOUT):
    """sherpa-onnx 子进程转写。失败统一折成 _ASRFailure，不向上抛原始异常。"""
    language = "auto" if LANG == "auto" else (LANG or "auto")
    try:
        text, _ = asr_engine.transcribe(audio, timeout=timeout, language=language)
        return text
    except asr_engine.EngineError as exc:
        raise _ASRFailure(str(exc)) from None
    except Exception:  # noqa: BLE001 —— 任何引擎侧异常都只降级
        raise _ASRFailure("本地语音引擎调用失败") from None


# ── 主入口 ────────────────────────────────────────────────────
def _transcribe_work(path, deadline, state):
    avail = available()
    if not avail["enabled"]:
        raise _ASRFailure(avail["detail"])
    backend = avail["backend"]
    state["backend"] = backend
    audio = _read_wav(path)
    _remaining(deadline)
    key = _cache_key(audio, backend)
    hit = _cache_get(key)
    _remaining(deadline)
    if hit is not None:
        return hit, True
    if backend == "cloud":
        raw = _transcribe_cloud(audio, timeout=_remaining(deadline))
    elif backend == "engine":
        raw = _transcribe_engine(audio, timeout=_remaining(deadline))
    else:
        raw = _transcribe_local(audio)
    # Event.wait() may return at a scheduler boundary slightly before the clock
    # deadline. Once the caller has abandoned this request, a late backend result
    # must never reach the optional disk cache, even with clock granularity.
    cancelled = state.get("cancelled")
    if cancelled is not None and cancelled.is_set():
        raise _ASRFailure("语音转写超时，请稍后重试")
    _remaining(deadline)
    if not isinstance(raw, str):
        raise _ASRFailure("语音服务返回格式无效")
    text = normalize(raw)
    if len(text) < MIN_CHARS:
        raise _ASRFailure("没听清（转写结果为空或过短）")
    _cache_put(key, text)
    _remaining(deadline)
    return text, False


def transcribe(path):
    """音频 → (文本, meta)，所有失败均保持固定六字段，满载时不排队。"""
    started = time.monotonic()
    deadline = started + TRANSCRIBE_TIMEOUT
    meta = {"ok": False, "reason": "", "backend": "", "cached": False,
            "seconds": 0.0, "lang": LANG}
    slots = _work_slots
    if not slots.acquire(blocking=False):
        meta["reason"] = "语音服务繁忙，请稍后重试"
        return "", meta

    done = threading.Event()
    state = {"backend": "", "text": "", "cached": False, "reason": "",
             "cancelled": threading.Event()}

    def work():
        try:
            state["text"], state["cached"] = _transcribe_work(path, deadline, state)
        except _ASRFailure as exc:
            state["reason"] = str(exc)
        except Exception:
            state["reason"] = "语音转写失败，请稍后重试"
        finally:
            # 只有实际工作线程能释放槽位；调用方超时并不代表模型或请求已结束。
            slots.release()
            done.set()

    try:
        threading.Thread(target=work, name="asr-worker", daemon=True).start()
    except Exception:
        slots.release()
        meta["reason"] = "语音服务启动失败"
        return "", meta

    if not done.wait(max(0.0, deadline - time.monotonic())):
        state["cancelled"].set()
        meta.update(reason="语音转写超时，请稍后重试", backend=state["backend"],
                    seconds=round(time.monotonic() - started, 2))
        return "", meta
    meta.update(backend=state["backend"], reason=state["reason"],
                seconds=round(time.monotonic() - started, 2))
    if state["reason"]:
        return "", meta
    meta.update(ok=True, cached=state["cached"])
    return state["text"], meta


def config_summary():
    """给界面显示的非敏感摘要（**不泄露密钥**）。"""
    a = available()
    return {
        "enabled": a["enabled"],
        "backend": a["backend"],
        "detail": a["detail"],
        "lang": LANG,
        "key": "已配置" if API_KEY else "未配置",
        "engine": _engine_summary(),
    }


def _engine_summary():
    """引擎一句话状态（不带路径，避免把本机目录暴露到界面）。"""
    try:
        state = asr_engine.status()
        return {"ready": state["ready"], "model": state["model"],
                "detail": state["detail"], "server": asr_engine.server_state()}
    except Exception:  # noqa: BLE001
        return {"ready": False, "model": "", "detail": "本地语音引擎状态未知",
                "server": {"mode": "unknown", "running": False, "detail": "未知"}}


def prewarm():
    """启动时后台准备引擎（下载二进制与模型）。

    只在「auto 且未配云端」或「显式指定 engine」时触发 —— 已经用云端的人
    不该被顺带下载 230MB。不阻塞启动、不抛异常。
    """
    if BACKEND_ENV in ("off", "cloud", "local"):
        return
    if BACKEND_ENV == "auto" and _cloud_ready():
        return
    try:
        asr_engine.ensure_async()
    except Exception:  # noqa: BLE001
        pass


# ── 自检 ──────────────────────────────────────────────────────
def _write_silent_wav(path, seconds=1.0, rate=16000):
    """生成一段静音 wav —— 只为验证「不炸」，不验证识别准确率。"""
    import wave

    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))


if __name__ == "__main__":
    import tempfile

    print("=" * 66)
    print("  语音识别 core/asr.py · 自检")
    print("=" * 66)
    fails = []

    cfg = config_summary()
    print(f"  后端状态：{cfg['detail']}")
    print(f"  语言：{cfg['lang']}　密钥：{cfg['key']}")
    print()

    # 1) 不存在的文件必须降级，不许抛
    text, meta = transcribe("C:/definitely/not/here.wav")
    ok = (text == "" and not meta["ok"] and bool(meta["reason"]))
    print(f"  [{'PASS' if ok else 'FAIL'}] 文件不存在 → 降级（{meta['reason'][:40]}）")
    if not ok:
        fails.append("文件不存在降级")

    # 2) meta 字段必须固定
    need = {"ok", "reason", "backend", "cached", "seconds", "lang"}
    ok = set(meta.keys()) == need
    print(f"  [{'PASS' if ok else 'FAIL'}] 返回字段固定 {len(need)} 个")
    if not ok:
        fails.append("meta 字段")

    # 3) 归一化：不替用户补内容，只去噪
    cases = [
        ("  我要把毛绒玩具卖到德国。 ", "我要把毛绒玩具卖到德国"),
        ("嗯，蓝牙耳机出口欧盟，", "嗯，蓝牙耳机出口欧盟"),
        ("", ""),
    ]
    for raw, want in cases:
        got = normalize(raw)
        if got != want:
            fails.append(f"normalize({raw!r}) → {got!r} != {want!r}")
    print(f"  [{'PASS' if not any('normalize' in f for f in fails) else 'FAIL'}] "
          f"{len(cases)} 条归一化用例")

    # 4) 静音音频：后端可用时不许抛异常；不可用时必须给出明确原因
    tmp = os.path.join(tempfile.gettempdir(), "cr_asr_selftest.wav")
    _write_silent_wav(tmp)
    text, meta = transcribe(tmp)
    if meta["backend"]:
        ok = isinstance(text, str)  # 静音 → 空文本 + ok=False，属正常
        print(f"  [{'PASS' if ok else 'FAIL'}] 静音音频不抛异常"
              f"（{meta['reason'] or '转写成功'}，{meta['seconds']}s）")
        if not ok:
            fails.append("静音音频")
        # 5) 缓存：同一文件第二次必须命中（仅当首次成功才成立）
        if meta["ok"] and CACHE_ENABLED:
            _, meta2 = transcribe(tmp)
            ok = meta2.get("cached") is True
            print(f"  [{'PASS' if ok else 'FAIL'}] 同音频二次调用命中缓存")
            if not ok:
                fails.append("缓存命中")
    else:
        print(f"  [SKIP] 静音音频（后端未启用：{meta['reason'][:40]}）")
    try:
        os.remove(tmp)
    except Exception:
        pass

    print()
    print("=" * 66)
    if fails:
        print(f"  结果：失败 {len(fails)} 项")
        for f in fails:
            print(f"    ❌ {f}")
    else:
        print("  结果：全部通过")
    print("=" * 66)
    sys.exit(0 if not fails else 1)
