# -*- coding: utf-8 -*-
"""创空间启动入口。
先核对打包语音模型是否仍为 LFS 指针，再转发至 app_main.py 启动应用。
模型补齐失败时保留文字查询服务，并在运行日志中记录不含敏感信息的错误类别。

build: 2026.10.19-chat1.3 修复部署后语音模型仅有 LFS 指针的情况
"""
import os
import runpy

from core.model_assets import ensure_bundled_whisper

try:
    if ensure_bundled_whisper():
        print("[ASR] Bundled model recovered and SHA-256 verified", flush=True)
except Exception as error:
    # Keep text queries available; do not echo response bodies or signed URLs.
    print("[ASR] Bundled model preparation failed: " + type(error).__name__, flush=True)

runpy.run_path(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "app_main.py"),
    run_name="__main__",
)
