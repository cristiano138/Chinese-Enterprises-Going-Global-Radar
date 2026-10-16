# -*- coding: utf-8 -*-
"""创空间启动入口（转发器）。
真正的应用在 app_main.py。本文件仅做转发，用于强制平台构建新镜像层，
绕过旧版 app.py 的缓存。launch 逻辑不变，行为与 app_main.py 完全一致。

build: 20261016-1425 响应提速 + 时效性监控（改此行触发平台重建）
"""
import os
import runpy

runpy.run_path(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "app_main.py"),
    run_name="__main__",
)