# -*- coding: utf-8 -*-
"""sherpa-onnx 引擎适配层（core/asr_engine.py）—— 用外部进程转写，不装任何 Python ASR 库

为什么是外部进程：
    项目约束「不引入 Python ASR 库」。引擎是 GitHub 上的**预编译二进制**
    （k2-fsa/sherpa-onnx，Apache-2.0），Python 侧只做三件事：
    定位/准备文件 → 起子进程 → 读结果。全部走标准库。

两条转写路径（core/asr_server.py 负责后者）：
    ① 常驻服务 —— sherpa-onnx-offline-websocket-server，模型只加载一次，
       本机实测 0.33s/次；默认优先。
    ② 命令行   —— sherpa-onnx-offline，每次重新加载模型（约 3s），
       常驻服务不可用时兜底，保证「能识别」优先于「快」。

为什么选 SenseVoice：
    中文短句 + 领域词的场景下，非自回归的 SenseVoice 比 Whisper 准且快得多
    （官方 184 条真实中文音频实测 CER 7.81% vs Whisper-large-v3 20.02%），
    模型支持中/英/日/韩/粤，中英混说不用切语言。

红线（与 core/asr.py 完全一致）：
    ❌ 不产生法规编号 / 条款号 / 链接 / 结论 —— 这里只出字符串
    ❌ 不把音频写进项目目录 —— 临时文件放系统 temp，用完即删
    引擎与模型默认放 <项目>/models/sherpa-onnx/（已在 .gitignore 中排除）

环境变量（全部可选）：
    ASR_ENGINE_DIR            引擎根目录，默认 <项目>/models/sherpa-onnx
    ASR_ENGINE_VERSION        sherpa-onnx 版本，默认 v1.13.8
    ASR_ENGINE_MODEL          模型包名，默认 sense-voice int8 2024-07-17
    ASR_ENGINE_THREADS        每个进程/服务的线程数，默认 2
    ASR_ENGINE_AUTO_DOWNLOAD  1（默认）= 允许首次自动下载；0 = 只认现成文件
    ASR_ENGINE_BASE_URL       下载源前缀，默认 GitHub Releases（可换内网镜像）
    ASR_ENGINE_SERVER         auto（默认）| on | off —— 是否使用常驻服务

自检（离线，不联网）：
    python core/asr_engine.py
"""

import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.request

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)

VERSION = (os.getenv("ASR_ENGINE_VERSION") or "v1.13.8").strip()
MODEL = (os.getenv("ASR_ENGINE_MODEL")
         or "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17").strip()
ROOT = (os.getenv("ASR_ENGINE_DIR") or os.path.join(PROJECT, "models", "sherpa-onnx")).strip()
THREADS = (os.getenv("ASR_ENGINE_THREADS") or "2").strip()
AUTO_DOWNLOAD = (os.getenv("ASR_ENGINE_AUTO_DOWNLOAD") or "1").strip().lower() in {
    "1", "true", "yes", "on",
}
BASE_URL = (os.getenv("ASR_ENGINE_BASE_URL")
            or "https://github.com/k2-fsa/sherpa-onnx/releases/download").strip().rstrip("/")

# 单次准备动作的硬上限：二进制 ~24MB、模型 ~230MB，慢网也要有边界
DOWNLOAD_TIMEOUT = 30 * 60
# 首次调用要加载模型（1–3 秒），给足冷启动余量
TRANSCRIBE_TIMEOUT = 45.0

_lock = threading.Lock()
_prepared = {"ready": False, "reason": ""}


class EngineError(Exception):
    """引擎不可用 / 调用失败。调用方一律按「降级」处理，不向上抛。"""


# ── 路径 ──────────────────────────────────────────────────────
def asset_name():
    """当前平台对应的 GitHub Release 资产名（静态 CRT / 不带 TTS）。"""
    if sys.platform == "win32":
        return f"sherpa-onnx-{VERSION}-win-x64-shared-MT-Release-no-tts.tar.bz2"
    if sys.platform == "darwin":
        arch = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x64"
        return f"sherpa-onnx-{VERSION}-osx-{arch}-shared-no-tts.tar.bz2"
    return f"sherpa-onnx-{VERSION}-linux-x64-shared-no-tts.tar.bz2"


def asset_url():
    return f"{BASE_URL}/{VERSION}/{asset_name()}"


def model_url():
    return f"{BASE_URL}/asr-models/{MODEL}.tar.bz2"


def bin_dir():
    return os.path.join(ROOT, "bin")


def model_dir():
    return os.path.join(ROOT, "models", MODEL)


def binary_path():
    """在 bin/ 下找可执行文件；找不到返回空串（不抛异常）。"""
    name = "sherpa-onnx-offline.exe" if sys.platform == "win32" else "sherpa-onnx-offline"
    direct = os.path.join(bin_dir(), name)
    if os.path.isfile(direct):
        return direct
    for folder, _, files in os.walk(bin_dir()):
        if name in files:
            return os.path.join(folder, name)
    return ""


def model_files():
    """(onnx 路径, tokens 路径)；缺任何一个都算没准备好。"""
    onnx = os.path.join(model_dir(), "model.int8.onnx")
    tokens = os.path.join(model_dir(), "tokens.txt")
    return (onnx if os.path.isfile(onnx) else "",
            tokens if os.path.isfile(tokens) else "")


def status():
    """纯探测，**绝不下载**。给界面显示状态用。"""
    binary = binary_path()
    onnx, tokens = model_files()
    if binary and onnx and tokens:
        return {"available": True, "ready": True, "root": ROOT,
                "binary": binary, "model": MODEL, "version": VERSION,
                "detail": f"本地 SenseVoice 引擎（{MODEL}）"}
    missing = []
    if not binary:
        missing.append("引擎二进制")
    if not onnx or not tokens:
        missing.append("SenseVoice 模型")
    return {"available": False, "ready": False, "root": ROOT,
            "binary": binary, "model": MODEL, "version": VERSION,
            "detail": "缺少" + "、".join(missing) + "，语音入口暂不可用"}


def engine_ready():
    return status()["ready"]


# ── 准备（下载 + 解包；任何失败都只记原因，不抛给主链路）────────
def _download(url, target, timeout=DOWNLOAD_TIMEOUT):
    """流式下载到同目录临时文件，成功后原子替换。不覆盖已有文件。"""
    if os.path.isfile(target) and os.path.getsize(target) > 0:
        return target
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    deadline = time.monotonic() + timeout
    temporary = None
    try:
        request = urllib.request.Request(
            url, headers={"User-Agent": "ComplianceRadar/1.0 (+sherpa-onnx engine)"})
        with urllib.request.urlopen(request, timeout=60) as response:
            total = int(response.headers.get("Content-Length") or 0)
            with tempfile.NamedTemporaryFile(dir=os.path.dirname(target) or ".",
                                             prefix=".dl-", suffix=".part",
                                             delete=False) as handle:
                temporary = handle.name
                while True:
                    if time.monotonic() > deadline:
                        raise EngineError("引擎下载超时")
                    chunk = response.read(1024 * 512)
                    if not chunk:
                        break
                    handle.write(chunk)
        size = os.path.getsize(temporary)
        if size <= 0 or (total and size != total):
            raise EngineError("引擎下载不完整")
        os.replace(temporary, target)
        temporary = None
        return target
    except EngineError:
        raise
    except Exception as exc:  # 网络 / TLS / 磁盘 —— 一律折叠成可读原因
        raise EngineError(f"引擎下载失败（{type(exc).__name__}）") from None
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass


def _extract(archive, destination):
    """解包到 destination。拒绝绝对路径与 .. 逃逸（CVE-2007-4559 类问题）。"""
    os.makedirs(destination, exist_ok=True)
    with tarfile.open(archive, "r:bz2") as bundle:
        base = os.path.abspath(destination)
        for member in bundle.getmembers():
            target = os.path.abspath(os.path.join(destination, member.name))
            if target != base and not target.startswith(base + os.sep):
                raise EngineError("引擎包内含非法路径")
            if member.issym() or member.islnk() or member.isdev():
                raise EngineError("引擎包内含非法链接")
        bundle.extractall(destination)


def _flatten_binary(extracted):
    """把解包出来的 bin/ 目录搬到 ROOT/bin，保持 exe 与 dll 同目录。"""
    wanted = "sherpa-onnx-offline.exe" if sys.platform == "win32" else "sherpa-onnx-offline"
    source = ""
    for folder, _, files in os.walk(extracted):
        if wanted in files:
            source = folder
            break
    if not source:
        raise EngineError("引擎包内没有可执行文件")
    target = bin_dir()
    os.makedirs(target, exist_ok=True)
    for name in os.listdir(source):
        origin = os.path.join(source, name)
        if os.path.isfile(origin):
            shutil.copy2(origin, os.path.join(target, name))
    if sys.platform != "win32":
        os.chmod(os.path.join(target, wanted), 0o755)


def ensure(force=False):
    """确保二进制与模型就位。返回 True/False，原因写进 _prepared。

    幂等：已经就位时直接返回 True，不发任何网络请求。
    """
    with _lock:
        state = status()
        if state["ready"] and not force:
            _prepared.update(ready=True, reason="")
            return True
        if not AUTO_DOWNLOAD and force is False:
            _prepared.update(ready=False, reason=state["detail"] + "（已禁止自动下载）")
            return False
        try:
            if not state["binary"] or force:
                archive = os.path.join(ROOT, "downloads", asset_name())
                _download(asset_url(), archive)
                staging = os.path.join(ROOT, "downloads", "bin-staging")
                shutil.rmtree(staging, ignore_errors=True)
                _extract(archive, staging)
                _flatten_binary(staging)
                shutil.rmtree(staging, ignore_errors=True)
            onnx, tokens = model_files()
            if not onnx or not tokens or force:
                archive = os.path.join(ROOT, "downloads", f"{MODEL}.tar.bz2")
                _download(model_url(), archive)
                _extract(archive, os.path.join(ROOT, "models"))
        except EngineError as exc:
            _prepared.update(ready=False, reason=str(exc))
            return False
        except Exception as exc:  # noqa: BLE001 —— 准备失败不许打断主链路
            _prepared.update(ready=False, reason=f"引擎准备失败（{type(exc).__name__}）")
            return False
        state = status()
        _prepared.update(ready=state["ready"],
                         reason="" if state["ready"] else state["detail"])
        return state["ready"]


def ensure_async():
    """后台准备（启动预热用）。不阻塞、不抛异常。

    注意：这里调 warmup() 而不是 ensure()——除了下载文件，还要把常驻服务
    拉起来，否则第一次点录音仍然要等 3 秒模型加载。
    """
    def work():
        try:
            warmup()
        except Exception:  # noqa: BLE001
            pass

    try:
        threading.Thread(target=work, name="asr-engine-prepare", daemon=True).start()
    except Exception:  # noqa: BLE001
        pass


def warmup():
    """准备文件并拉起常驻服务。返回是否可用，绝不抛异常。"""
    if not ensure():
        return False
    if (os.getenv("ASR_ENGINE_SERVER") or "auto").strip().lower() == "off":
        return True
    try:
        from core import asr_server
    except ImportError:
        try:
            import asr_server
        except ImportError:
            return True
    try:
        ok, _ = asr_server.start()
        return ok
    except Exception:  # noqa: BLE001
        return True  # 常驻失败不影响命令行兜底


def server_state():
    """常驻服务状态（给界面/自检看，不泄漏端口以外的本机信息）。"""
    try:
        from core import asr_server
    except ImportError:
        try:
            import asr_server
        except ImportError:
            return {"mode": "off", "running": False, "detail": "常驻服务模块未加载"}
    try:
        return asr_server.state()
    except Exception:  # noqa: BLE001
        return {"mode": "unknown", "running": False, "detail": "常驻服务状态未知"}


def stop_server():
    """停掉常驻服务（测试与退出时用）。"""
    try:
        from core import asr_server
    except ImportError:
        try:
            import asr_server
        except ImportError:
            return
    try:
        asr_server.stop()
    except Exception:  # noqa: BLE001
        pass


def prepare_state():
    return dict(_prepared)


# ── 转写 ──────────────────────────────────────────────────────
def _parse_output(stdout, stderr, wav_path):
    """从命令行输出里取文本。

    sherpa-onnx-offline 每处理一个文件会先打印文件名，再打印一行 JSON；
    只认最后一段能解析出 text 的 JSON，其余噪声一律丢弃。
    """
    for stream in (stdout, stderr):
        text = stream or ""
        for line in reversed(text.splitlines()):
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                payload = json.loads(line)
            except ValueError:
                continue
            if isinstance(payload, dict) and isinstance(payload.get("text"), str):
                return payload["text"]
    # 旧版本可能只打印纯文本：退回「去掉文件名行与坏 JSON 行后的剩余内容」
    lines = [ln for ln in (stderr or stdout or "").splitlines()
             if ln.strip() and not ln.strip().startswith("{")
             and not ln.strip().endswith((".wav", ".WAV"))
             and ln.strip() != wav_path]
    return " ".join(lines).strip()


def transcribe(audio, timeout=TRANSCRIBE_TIMEOUT, language="auto"):
    """WAV 字节 → 文本。失败一律抛 EngineError（由 core/asr.py 折叠成提示）。

    优先走常驻服务（模型只加载一次，本机实测 0.33s/次）；常驻服务不可用
    或出错时自动退回命令行（冷启动约 3s），保证「能识别」优先于「快」。
    """
    state = status()
    if not state["ready"]:
        raise EngineError(state["detail"])
    language = (language or "auto").strip() or "auto"
    server_note = ""
    if (os.getenv("ASR_ENGINE_SERVER") or "auto").strip().lower() != "off":
        try:
            from core import asr_server  # 局部导入：asr_server 依赖本模块
        except ImportError:
            try:
                import asr_server
            except ImportError:
                asr_server = None
        if asr_server is not None:
            try:
                text, info = asr_server.transcribe(audio, timeout=timeout,
                                                   language=language)
                return text, info
            except Exception as exc:  # noqa: BLE001 —— 常驻失败就退回命令行
                server_note = f"（常驻服务不可用：{type(exc).__name__}）"
    text, info = _transcribe_cli(audio, timeout=timeout, language=language)
    if server_note:
        info = dict(info, fallback=server_note)
    return text, info


def _transcribe_cli(audio, timeout=TRANSCRIBE_TIMEOUT, language="auto"):
    """命令行兜底：每次一个进程、每次重新加载模型。"""
    state = status()
    binary = state["binary"]
    onnx, tokens = model_files()
    language = (language or "auto").strip() or "auto"

    command = [binary,
               f"--tokens={tokens}",
               f"--sense-voice-model={onnx}",
               f"--sense-voice-language={language}",
               "--sense-voice-use-itn=1",
               f"--num-threads={THREADS}",
               "--debug=0"]
    workdir = tempfile.mkdtemp(prefix="cr-asr-")
    started = time.monotonic()
    try:
        wav_path = os.path.join(workdir, "audio.wav")
        with open(wav_path, "wb") as handle:
            handle.write(audio)
        command.append(wav_path)
        env = dict(os.environ)
        env.setdefault("OMP_NUM_THREADS", THREADS)
        env.setdefault("ORT_NUM_THREADS", THREADS)
        try:
            done = subprocess.run(command, capture_output=True, timeout=timeout,
                                  cwd=os.path.dirname(binary), env=env,
                                  check=False)
        except subprocess.TimeoutExpired:
            raise EngineError("语音转写超时，请稍后重试") from None
        except (OSError, ValueError):
            raise EngineError("本地语音引擎启动失败") from None
        if done.returncode != 0:
            raise EngineError("本地语音引擎返回错误")
        text = _parse_output(done.stdout.decode("utf-8", "replace"),
                             done.stderr.decode("utf-8", "replace"), wav_path)
        return text, {"engine": "sherpa-onnx-cli", "model": MODEL,
                      "seconds": round(time.monotonic() - started, 2)}
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


# ── 自检 ──────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 66)
    print("  sherpa-onnx 引擎适配层 · 自检")
    print("=" * 66)
    fails = []

    state = status()
    print(f"  资产：{asset_name()}")
    print(f"  目录：{state['root']}")
    print(f"  状态：{state['detail']}")
    print()

    ok = asset_name().startswith("sherpa-onnx-") and asset_name().endswith(".tar.bz2")
    print(f"  [{'PASS' if ok else 'FAIL'}] 平台资产名可解析")
    if not ok:
        fails.append("资产名")

    ok = asset_url().startswith("http") and MODEL in model_url()
    print(f"  [{'PASS' if ok else 'FAIL'}] 下载地址可解析")
    if not ok:
        fails.append("下载地址")

    ok = set(state) >= {"available", "ready", "root", "binary", "model", "version", "detail"}
    print(f"  [{'PASS' if ok else 'FAIL'}] status() 字段完整")
    if not ok:
        fails.append("status 字段")

    # 输出解析：JSON 优先，噪声行忽略
    sample = ('/tmp/a.wav\n{ "text": "我要把毛绒玩具卖到德国", "tokens": [] }\n')
    ok = _parse_output(sample, "", "/tmp/a.wav") == "我要把毛绒玩具卖到德国"
    print(f"  [{'PASS' if ok else 'FAIL'}] 解析 JSON 输出")
    if not ok:
        fails.append("解析 JSON")

    # 非法包必须被拒绝，而不是解到项目外
    ok = False
    try:
        with tempfile.TemporaryDirectory() as tmp:
            archive = os.path.join(tmp, "bad.tar.bz2")
            with tarfile.open(archive, "w:bz2") as bundle:
                info = tarfile.TarInfo("../escape.txt")
                info.size = 1
                bundle.addfile(info, __import__("io").BytesIO(b"x"))
            try:
                _extract(archive, os.path.join(tmp, "out"))
            except EngineError:
                ok = True
    except Exception:  # noqa: BLE001
        ok = False
    print(f"  [{'PASS' if ok else 'FAIL'}] 拒绝含 .. 的压缩包")
    if not ok:
        fails.append("路径逃逸")

    if state["ready"]:
        try:
            text, meta = transcribe(b"\x00" * 3200)  # 非法 WAV，只验证不抛未捕获异常
            print(f"  [SKIP] 引擎调用（{meta}）")
        except EngineError as exc:
            print(f"  [PASS] 引擎调用失败可收敛（{exc}）")
    else:
        print("  [SKIP] 引擎调用（尚未准备，先跑 scripts/prepare_asr_engine.py）")

    print()
    print("=" * 66)
    print("  结果：全部通过" if not fails else f"  结果：失败 {len(fails)} 项")
    for item in fails:
        print(f"    ❌ {item}")
    print("=" * 66)
    sys.exit(0 if not fails else 1)
