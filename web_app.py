# -*- coding: utf-8 -*-
"""把前端 SPA 挂到 Gradio 的 FastAPI 实例上。

Gradio 6.2 的 FastAPI 实例（demo.app）只在 launch() 内部创建，因此本模块的
install() 必须在 launch(prevent_thread_lock=True) 之后调用。
任何挂载失败都不抛异常，只返回 False —— 调用方据此回退到 CR_UI=gradio。
"""
from __future__ import annotations

import os
from pathlib import Path

WEB_DIR = str((Path(__file__).resolve().parent / "web").resolve())


def ui_mode() -> str:
    """读界面开关；非法值一律回落 spa。"""
    mode = os.getenv("CR_UI", "spa").strip().lower()
    return "gradio" if mode == "gradio" else "spa"


def index_html() -> str:
    return (Path(WEB_DIR) / "index.html").read_text(encoding="utf-8")


def install(demo) -> bool:
    """接管根路由并挂载静态资源。成功返回 True，失败返回 False（不抛）。"""
    try:
        from fastapi.responses import HTMLResponse
        from fastapi.staticfiles import StaticFiles
        from starlette.routing import Route
    except Exception:  # noqa: BLE001
        return False
    try:
        app = getattr(demo, "app", None)
        if app is None:
            return False
        # 安装期就把外壳读进来：若留到请求期再读，读不到时根路由已被遮蔽，
        # 调用方拿不到 False、无从回退，只会在 "/" 上得到一个 500。
        shell = index_html()
        # 静态资源挂在 /web：Gradio 自己占用 /static，挂在那里会 404。
        app.mount("/web", StaticFiles(directory=WEB_DIR), name="web")
        # 抢在 Gradio 首页之前接管 "/"。Gradio 的 /gradio_api/* 不受影响。
        app.router.routes.insert(
            0, Route("/", lambda request: HTMLResponse(shell)))
        return True
    except Exception:  # noqa: BLE001
        return False