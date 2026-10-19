# -*- coding: utf-8 -*-
"""官方接口网络策略：代理探测、自动降级、脱敏显示。

背景（2026-10-19 实测）：
    · 本机环境设置了 ``HTTP_PROXY/HTTPS_PROXY=127.0.0.1:7897``；
    · Clash 未启动时，urllib 会直接报 ``WinError 10061 目标计算机积极拒绝``；
    · 关闭代理后，eCFR / Federal Register 可直连，EUR-Lex 仍会返回
      202 + 空响应体（反爬），需要由调用方如实记录，不能当成“可访问”。

这里只做网络策略，不写业务结论：
    mode="auto"   → 有代理先探测端口；不可达则清空代理并直连（记录 fallback）
    mode="direct" → 强制直连
    mode="<url>"  → 强制使用指定代理（如 http://127.0.0.1:7897）

所有日志只显示脱敏后的 scheme://host:port，不打印可能带凭据的完整代理 URL。
"""
from __future__ import annotations

import os
import socket
import urllib.parse

PROXY_KEYS = ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy")
NO_PROXY_KEYS = ("NO_PROXY", "no_proxy")


def _normalize_proxy(url: str) -> str:
    """允许用户写 127.0.0.1:7897，自动补 http://。"""
    text = str(url or "").strip()
    if text and "://" not in text:
        text = "http://" + text
    return text


def redact_proxy(url: str) -> str:
    """把代理 URL 脱敏成 scheme://host:port，不暴露用户名/密码/路径。"""
    try:
        parsed = urllib.parse.urlsplit(_normalize_proxy(url))
        host = parsed.hostname or ""
        port = f":{parsed.port}" if parsed.port else ""
        scheme = parsed.scheme or "http"
        return f"{scheme}://{host}{port}" if host else "<invalid-proxy>"
    except ValueError:
        return "<invalid-proxy>"


def env_proxy() -> str:
    """读取环境变量里的代理；空值、none、null 都视为未设置。"""
    for key in PROXY_KEYS:
        value = (os.environ.get(key) or "").strip()
        if value and value.lower() not in ("none", "null"):
            return value
    return ""


def proxy_reachable(proxy_url: str, timeout: float = 1.5) -> bool:
    """只探测代理进程端口是否在监听。

    不区分 socks/http：对“代理没开”这个最常见故障，TCP 连通性已经足够；
    真正发请求时仍由 urllib 按 URL scheme 处理。
    """
    try:
        parsed = urllib.parse.urlsplit(_normalize_proxy(proxy_url))
        host = parsed.hostname
        port = parsed.port
        if not host:
            return False
        if port is None:
            port = 443 if parsed.scheme == "https" else 80
        with socket.create_connection((host, port), timeout=max(float(timeout), 0.1)):
            return True
    except (OSError, ValueError):
        return False


def _clear_proxy_env() -> None:
    for key in PROXY_KEYS:
        os.environ.pop(key, None)
    for key in NO_PROXY_KEYS:
        os.environ[key] = "*"


def _set_proxy_env(proxy_url: str) -> None:
    proxy_url = _normalize_proxy(proxy_url)
    for key in PROXY_KEYS:
        os.environ[key] = proxy_url
    # 显式指定代理时，清掉 * 形式的全局绕过；保留用户自定义的精确白名单。
    for key in NO_PROXY_KEYS:
        if (os.environ.get(key) or "").strip() in ("", "*"):
            os.environ.pop(key, None)


def configure_proxy(mode: str = "auto", logger=print) -> dict:
    """按模式配置 urllib 使用的环境代理，返回本次决策（可写入运行日志）。

    返回示例::

        {"requested": "auto", "mode": "direct", "proxy": "",
         "fallback": True, "reason": "proxy 127.0.0.1:7897 unreachable"}
    """
    requested = (mode or "auto").strip()
    decision = {
        "requested": (redact_proxy(requested)
                      if requested not in ("", "auto", "direct") else requested),
        "mode": "direct",
        "proxy": "",
        "fallback": False,
        "reason": "",
    }

    if requested == "direct":
        _clear_proxy_env()
        decision["reason"] = "forced direct"
        logger("[NET] 代理策略：强制直连")
        return decision

    if requested not in ("", "auto"):
        _set_proxy_env(requested)
        decision.update(mode="proxy", proxy=redact_proxy(requested),
                        reason="explicit proxy")
        logger(f"[NET] 代理策略：使用指定代理 {decision['proxy']}")
        return decision

    current = env_proxy()
    if not current:
        _clear_proxy_env()
        decision["reason"] = "no proxy configured"
        logger("[NET] 代理策略：未配置代理，直连")
        return decision

    if proxy_reachable(current):
        decision.update(mode="proxy", proxy=redact_proxy(current),
                        reason="environment proxy reachable")
        logger(f"[NET] 代理策略：使用环境代理 {decision['proxy']}")
        return decision

    _clear_proxy_env()
    decision.update(fallback=True,
                    reason=f"proxy {redact_proxy(current)} unreachable")
    logger(f"[NET] 代理 {redact_proxy(current)} 不可达，已自动切换直连")
    return decision
