# -*- coding: utf-8 -*-
"""
一键准备本地语音模型（scripts/prepare_asr.py）

为什么需要这个脚本：
    faster-whisper 默认走 HuggingFace 官方源，国内直连通常不通（ProxyError / 502）；
    且 Windows 下默认的软链接式缓存经常留空目录（blobs 下好了、snapshots 是空的）。
    本脚本做三件事，把「配不通」变成一条命令：
      ① 默认走国内镜像（HF_ENDPOINT=https://hf-mirror.com）
      ② 关掉 Xet 存储协议（老镜像不代理它，会 401）
      ③ 用 local_dir 落成**实体文件**，绕开 Windows 软链接失败

用法：
    $PY scripts/prepare_asr.py                  # 默认 small（推荐，中文够用）
    $PY scripts/prepare_asr.py base            # 更快、更小、更不准
    $PY scripts/prepare_asr.py medium          # 更准、更慢（约 1.5 GB）

产物：
    ~/.cache/compliance-radar/asr/faster-whisper-<型号>/
    core/asr.py 会自动发现该目录，**无需再配任何环境变量**。
"""

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
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)

# 这两个必须在 import huggingface_hub 之前设好
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

ALLOWED = ("tiny", "base", "small", "medium")


def target_dir(model):
    return os.path.join(os.path.expanduser("~"), ".cache", "compliance-radar",
                        "asr", f"faster-whisper-{model}")


def main():
    model = (sys.argv[1] if len(sys.argv) > 1 else "small").strip()
    if model not in ALLOWED:
        print(f"型号只能是 {' / '.join(ALLOWED)}，收到：{model}")
        return 2

    dst = target_dir(model)
    print("=" * 66)
    print("  准备本地语音模型")
    print("=" * 66)
    print(f"  型号：{model}")
    print(f"  目录：{dst}")
    print(f"  镜像：{os.environ['HF_ENDPOINT']}")
    print()

    if os.path.exists(os.path.join(dst, "model.bin")):
        print("  已存在，跳过下载。")
    else:
        try:
            from huggingface_hub import snapshot_download
        except Exception as e:  # noqa: BLE001
            print(f"  缺少 huggingface_hub：{e}")
            print("  先跑：pip install faster-whisper")
            return 2

        os.makedirs(dst, exist_ok=True)
        t0 = time.time()
        try:
            snapshot_download(f"Systran/faster-whisper-{model}", local_dir=dst)
        except Exception as e:  # noqa: BLE001
            print(f"  下载失败：{type(e).__name__}: {str(e)[:200]}")
            print("  可改用云端转写：配 ASR_API_BASE / ASR_API_KEY / ASR_MODEL，"
                  "无需本地模型。")
            return 1
        print(f"  下载完成，用时 {time.time() - t0:.1f}s")

    # 真实加载一次，确认不是半截文件 —— 这一步比「下载成功」更有说服力
    print()
    print("  正在验证模型可加载…")
    t0 = time.time()
    try:
        from faster_whisper import WhisperModel
        WhisperModel(dst, device="cpu", compute_type="int8")
    except Exception as e:  # noqa: BLE001
        print(f"  ❌ 加载失败：{type(e).__name__}: {str(e)[:200]}")
        return 1
    print(f"  ✅ 加载成功，用时 {time.time() - t0:.1f}s")

    size = sum(os.path.getsize(os.path.join(dst, f))
               for f in os.listdir(dst)
               if os.path.isfile(os.path.join(dst, f)))
    print(f"  磁盘占用：{size / 1024 / 1024:.0f} MB")
    print()
    print("  下一步：直接跑 $PY app.py —— core/asr.py 会自动发现这个目录。")
    print("=" * 66)
    return 0


if __name__ == "__main__":
    sys.exit(main())
