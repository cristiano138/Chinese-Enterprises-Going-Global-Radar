# -*- coding: utf-8 -*-
"""
语音识别（core/asr.py）—— 说一句话，变成 M1.5 能吃的字符串

定位（不可越界，与 core/llm.py 同级约束）：
    ASR 只做「音频 → 文字」。它**不理解、不归类、不产生任何合规结论**。
    转写出来的文本交给 modules/m15_router.py，与用户手打字走**完全相同**的链路。
    因此语音不会、也不允许绕过 core/verify.py 的引用对齐。

三级后端（按可用性自动选；任一失败自动降级，任何情况都不抛异常）：
    ① cloud —— OpenAI 兼容的 /audio/transcriptions（配 ASR_API_BASE + ASR_API_KEY + ASR_MODEL）
    ② local —— faster-whisper（本机 CPU int8，**无需密钥、无需联网**；模型首次用时下载）
    ③ off   —— 两者都没有 → available()["enabled"] 为 False，界面显示「语音未启用」，
               文本框照常可用，主链路零影响

为什么默认走 local：
    本机没有 .env、模型链路未配置，云端 ASR 无法实测。演示不能建立在一个
    「配置好了才能用」的假设上 —— 语音是入口，入口不能有前置条件。

红线：
    ❌ 不产生法规编号 / 条款号 / 链接 / 结论（那是 corpus + verify 的事）
    ❌ 不把音频存进项目目录（Gradio 传来的临时文件只读不搬，转写完不留副本）
    ❌ 不缓存音频本身，只缓存「音频 sha256 → 转写文本」（与 llm.py 的缓存同构）

环境变量（全部可选，不配也能跑）：
    ASR_BACKEND       auto | cloud | local | off     默认 auto
    ASR_API_BASE      例 https://xxx/v1
    ASR_API_KEY       云端密钥（与 MODEL_API_TOKEN 分开，互不复用）
    ASR_MODEL         例 whisper-1 / paraformer-v2
    ASR_LANG          默认 zh；填 auto 交给模型判语言
    ASR_LOCAL_MODEL   默认 small（可选 tiny / base / medium）
    ASR_MODEL_DIR     本地模型下载目录（默认用 HuggingFace 缓存）

用法：
    from core import asr
    print(asr.available())
    text, meta = asr.transcribe("path/to/audio.wav")

自检（离线、不联网、不依赖模型是否下好）：
    python core/asr.py
"""

import hashlib
import json
import os
import sys
import time

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

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

_local_model = None
_local_error = ""


# ── 后端探测 ──────────────────────────────────────────────────
def _cloud_ready():
    return bool(API_BASE and API_KEY and API_MODEL)


def _local_importable():
    """faster-whisper 是否装得上。只 import，不加载模型（加载很慢）。"""
    try:
        import faster_whisper  # noqa: F401
        return True
    except Exception:
        return False


def available():
    """当前可用哪个后端。给界面显示状态用，**不加载模型**。"""
    cloud = _cloud_ready()
    local = _local_importable()

    if BACKEND_ENV == "off":
        return {"enabled": False, "backend": "off",
                "detail": "语音已按配置关闭（ASR_BACKEND=off）"}

    if BACKEND_ENV == "cloud":
        return ({"enabled": True, "backend": "cloud", "detail": "云端转写"}
                if cloud else
                {"enabled": False, "backend": "off",
                 "detail": "指定了 cloud 但缺 ASR_API_BASE / ASR_API_KEY / ASR_MODEL"})

    if BACKEND_ENV == "local":
        return ({"enabled": True, "backend": "local", "detail": "本地 Whisper 转写"}
                if local else
                {"enabled": False, "backend": "off",
                 "detail": "指定了 local 但未安装 faster-whisper"})

    # auto：云端优先（快、轻），否则本地，再否则关掉
    if cloud:
        return {"enabled": True, "backend": "cloud", "detail": "云端转写"}
    if local:
        return {"enabled": True, "backend": "local",
                "detail": f"本地 Whisper（{LOCAL_MODEL}）转写"}
    return {"enabled": False, "backend": "off",
            "detail": "未配置云端密钥，且未安装 faster-whisper —— 语音入口暂不可用"}


# ── 缓存：音频 sha256 → 文本（不存音频） ─────────────────────────
def _cache_path(key):
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f"asr_{key[:16]}.json")


def _cache_key(backend, digest):
    """缓存键必须带后端名。

    本地 Whisper 与云端是两套模型，同一段音频的转写结果可能不同。
    只按音频内容做键的话，用户切换后端会拿到另一个后端的结果，
    而且界面会把旧结果标成新后端 —— 违反「如实标注」。
    """
    raw = f"{backend}:{digest}".encode()
    return hashlib.sha256(raw).hexdigest()


def _digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _cache_get(key):
    """返回 (text, backend) 或 None。backend 可能为空（旧格式缓存文件）。"""
    p = _cache_path(key)
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("text"), str):
            return data["text"], (data.get("backend") or "")
    except Exception:
        return None
    return None


def _cache_put(key, text, backend=""):
    try:
        with open(_cache_path(key), "w", encoding="utf-8") as f:
            json.dump({"text": text, "backend": backend}, f, ensure_ascii=False)
    except Exception:
        pass


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
def _transcribe_cloud(path):
    """OpenAI 兼容 /audio/transcriptions。用 requests（已是现有依赖），不新增 SDK。"""
    import requests

    url = f"{API_BASE}/audio/transcriptions"
    data = {"model": API_MODEL}
    if LANG and LANG != "auto":
        data["language"] = LANG
    with open(path, "rb") as fh:
        files = {"file": (os.path.basename(path), fh, "application/octet-stream")}
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {API_KEY}"},
            data=data, files=files, timeout=90,
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:160]}")
    # 兼容两种返回：{"text": "..."} 与 {"output": {"text": "..."}}
    try:
        j = resp.json()
    except Exception:
        return resp.text or ""
    if isinstance(j, dict):
        if isinstance(j.get("text"), str):
            return j["text"]
        out = j.get("output")
        if isinstance(out, dict) and isinstance(out.get("text"), str):
            return out["text"]
    return ""


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
    global _local_model, _local_error
    if _local_model is not None:
        return _local_model
    from faster_whisper import WhisperModel
    kwargs = {"device": "cpu", "compute_type": "int8"}
    if MODEL_DIR:
        kwargs["download_root"] = MODEL_DIR
    _local_model = WhisperModel(_resolve_local_model(), **kwargs)
    return _local_model


def _transcribe_local(path):
    model = _get_local_model()
    lang = None if LANG == "auto" else (LANG or None)
    segments, info = model.transcribe(
        path, language=lang, beam_size=1, vad_filter=True,
        condition_on_previous_text=False,
    )
    return "".join(seg.text for seg in segments).strip()


# ── 主入口 ────────────────────────────────────────────────────
def transcribe(path):
    """音频 → (文本, meta)。**任何异常都不抛出**，上层靠 meta 降级。

    meta 字段固定：ok / reason / backend / cached / seconds / lang
    """
    t0 = time.time()
    meta = {"ok": False, "reason": "", "backend": "", "cached": False,
            "seconds": 0.0, "lang": LANG}

    avail = available()
    if not avail["enabled"]:
        meta["reason"] = avail["detail"]
        return "", meta
    meta["backend"] = avail["backend"]

    if not path or not os.path.exists(path):
        meta["reason"] = "音频文件不存在"
        return "", meta

    try:
        digest = _digest(path)
    except Exception as e:  # noqa: BLE001
        meta["reason"] = f"音频读取失败：{type(e).__name__}"
        return "", meta

    key = _cache_key(avail["backend"], digest)
    hit = _cache_get(key)
    if hit is not None:
        text, hit_backend = hit
        meta.update(ok=True, cached=True,
                    backend=hit_backend or avail["backend"],
                    seconds=round(time.time() - t0, 2))
        return text, meta

    try:
        if avail["backend"] == "cloud":
            raw = _transcribe_cloud(path)
        else:
            raw = _transcribe_local(path)
    except Exception as e:  # noqa: BLE001
        # 不抛错：语音坏了不能拖垮整个页面
        meta["reason"] = f"{type(e).__name__}: {str(e)[:160]}"
        meta["seconds"] = round(time.time() - t0, 2)
        return "", meta

    text = normalize(raw)
    if len(text) < MIN_CHARS:
        meta["reason"] = "没听清（转写结果为空或过短）"
        meta["seconds"] = round(time.time() - t0, 2)
        return "", meta

    _cache_put(key, text, avail["backend"])
    meta.update(ok=True, seconds=round(time.time() - t0, 2))
    return text, meta


def config_summary():
    """给界面显示的非敏感摘要（**不泄露密钥**）。"""
    a = available()
    return {
        "enabled": a["enabled"],
        "backend": a["backend"],
        "detail": a["detail"],
        "lang": LANG,
        "key": "已配置" if API_KEY else "未配置",
    }


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
        if meta["ok"]:
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
