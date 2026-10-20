# -*- coding: utf-8 -*-
"""把前端 SPA 挂到 Gradio 的 FastAPI 实例上，并提供 /api/* 数据契约。

Gradio 6.2 的 FastAPI 实例（demo.app）只在 launch() 内部创建，因此本模块的
install() 必须在 launch(prevent_thread_lock=True) 之后调用。
任何挂载失败都不抛异常，只返回 False —— 调用方据此回退到 CR_UI=gradio。

数据链路的边界约定（与 docs/superpowers/specs/2026-10-20-frontend-spa-design.md
第 5 节一致）：
  * 模块返回中文键，本模块统一归一成稳定的英文键；
  * 所有响应使用 ``{ok, reason, data, meta}`` 信封；
  * ``modules/`` 与既有 Gradio 界面不受影响。
"""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import threading
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote, urlparse

LOG = logging.getLogger(__name__)

PROJECT = Path(__file__).resolve().parent
WEB_DIR = str((PROJECT / "web").resolve())
FRESHNESS_FILE = PROJECT / "data" / "freshness_latest.json"
FRESHNESS_RUNS_FILE = PROJECT / "data" / "freshness_runs.jsonl"

BUILD = "2026.10.20-m2"
DEFAULT_CATEGORY = "儿童玩具"
DEFAULT_MARKET = "欧盟"

_boot_lock = threading.Lock()
_boot_cache: dict | None = None
_fresh_lock = threading.Lock()
_fresh_cache: dict | None = None
_fresh_mtime: float | None = None


def ui_mode() -> str:
    """读界面开关；非法值一律回落 spa。"""
    mode = os.getenv("CR_UI", "spa").strip().lower()
    return "gradio" if mode == "gradio" else "spa"


def index_html() -> str:
    return (Path(WEB_DIR) / "index.html").read_text(encoding="utf-8")


# ── 公共工具 ──────────────────────────────────────────────────
def _meta() -> dict:
    try:
        from core import snapshot
        return {
            "build": BUILD,
            "snapshot": snapshot.SNAPSHOT_VERSION,
            "data_cutoff": snapshot.DATA_CUTOFF,
        }
    except Exception:  # noqa: BLE001
        return {"build": BUILD, "snapshot": "", "data_cutoff": ""}


def _envelope(data=None, ok: bool = True, reason: str = "", meta: dict | None = None) -> dict:
    return {"ok": ok, "reason": reason, "data": data, "meta": meta or _meta()}


def _json_safe(value):
    """会话状态里含 date / set 等对象，走一次 JSON 归一后再交给响应层。"""
    def default(item):
        if isinstance(item, (date, datetime)):
            return item.isoformat()
        if isinstance(item, set):
            return sorted(item)
        return str(item)
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, default=default))
    except (TypeError, ValueError):
        return None


def _read_json(path: Path, default=None):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:  # noqa: BLE001
        return default


def _link_title(url: str) -> str:
    """给原始链接一个人能读的标题（不访问网络）。"""
    url = url or ""
    if "eur-lex.europa.eu" in url:
        match = re.search(r"CELEX:([0-9A-Za-z()]+)", url)
        if match:
            return f"EUR-Lex · {match.group(1)}"
        return "EUR-Lex"
    if "data.europa.eu" in url:
        match = re.search(r"/(?:eli/)?[^/]+/(\d{4})/(\d+)/", url)
        if match:
            return f"EUR-Lex · {match.group(1)}/{match.group(2)}"
        return "EUR-Lex · ELI"
    if "ecfr.gov" in url:
        match = re.search(r"title-(\d+)/part-([0-9A-Za-z]+)", url)
        if match:
            return f"eCFR · {match.group(1)} CFR Part {match.group(2)}"
        return "eCFR"
    host = urlparse(url).netloc or url
    return host or "官方链接"


def _safe_url(url) -> str:
    """Only allow absolute http(s) URLs without embedded credentials."""
    try:
        parsed = urlparse(str(url))
        if parsed.scheme in ("http", "https") and parsed.hostname and not parsed.username:
            return str(url)
    except (ValueError, TypeError):
        pass
    return ""


def _normalize_record(row: dict) -> dict:
    """M1 记录 → 前端稳定字段。"""
    key = row.get("key") or row.get("官方编号") or ""
    note = row.get("_raw_备注") or ""
    return {
        "id": key,
        "title": row.get("法规中文名") or "官方未标注",
        "subtitle": row.get("官方英文标题") or "",
        "official_id": row.get("官方编号") or "",
        "celex": row.get("CELEX号") or "",
        "type": "法律法规",
        "status": row.get("是否仍有效") or "官方未标注",
        "rail": "warn" if ("已废止" in (row.get("是否仍有效") or "")
                           or "待确认" in (row.get("是否仍有效") or "")) else "ok",
        "source": row.get("OJ出处") or row.get("监管机构") or "官方未标注",
        "url": row.get("官方原文链接") or "",
        "links": row.get("全部官方链接") or [],
        "why": row.get("卖家提示") or (note.split("｜")[0].strip() if note else ""),
        "excerpt": note or row.get("官方英文标题") or "",
        "effective_date": row.get("生效日期") or "",
        "regulator": row.get("监管机构") or "",
        "validity": row.get("是否仍有效") or "",
    }


def _normalize_action(action: dict) -> dict:
    links = action.get("全部官方链接") or []
    return {
        "id": action.get("action_id") or action.get("key") or "",
        "title": action.get("动作") or "",
        "type": action.get("动作类型") or "",
        "type_meaning": action.get("类型含义") or "",
        "urgency": action.get("紧迫度") or "",
        "deadline": action.get("期限") or "",
        "deadline_note": action.get("期限说明") or "",
        "condition": action.get("适用条件") or "",
        "law": action.get("依据法规") or "",
        "official_id": action.get("官方编号") or "",
        "url": action.get("来源条款链接") or (links[0] if links else ""),
        "excerpt": action.get("证据摘录") or "",
        "status": action.get("状态") or action.get("现行效力") or "",
        "source": action.get("动作来源") or "",
    }


def _normalize_event(event: dict) -> dict:
    return {
        "id": event.get("event_key") or "",
        "date": event.get("日期") or "",
        "type": event.get("事件类型") or "",
        "official": bool(event.get("官方确认")),
        "summary": event.get("变化摘要") or "",
        "impact": event.get("影响说明") or "",
        "law": event.get("法规中文名") or "",
        "official_id": event.get("官方编号") or "",
        "url": event.get("官方链接") or "",
        "gap": event.get("距今") or "",
        "seq": event.get("同类序号") or 1,
        "total": event.get("同类计数") or 1,
        "validity": event.get("现行效力") or "",
        "summary_source": event.get("摘要来源") or "",
        "impact_source": event.get("影响来源") or "",
    }


def _records_from_map(result: dict) -> dict:
    primary = [_normalize_record(r) for r in result.get("primary", [])]
    cross = [_normalize_record(r) for r in result.get("cross", [])]
    for record in primary + cross:
        if not record["why"]:
            record["why"] = "本条结论来自已核对目录，请结合产品实际情况核对适用性。"
        if not record["excerpt"]:
            record["excerpt"] = "官方原文请点击来源链接查看。"
    return {
        "category": result.get("品类") or "",
        "market": result.get("市场") or "",
        "market_code": result.get("market_code") or "",
        "records": primary + cross,
        "primary": primary,
        "cross": cross,
        "stats": result.get("stats") or {},
        "header": result.get("header") or {},
        "llm": result.get("llm") or {},
    }


# ── /api/bootstrap ────────────────────────────────────────────
def _bootstrap_payload() -> dict:
    global _boot_cache
    if _boot_cache is not None:
        return _boot_cache
    with _boot_lock:
        if _boot_cache is not None:
            return _boot_cache
        from core import asr, corpus, dates, law_store, llm, snapshot

        store = law_store.status()
        quality = _read_json(PROJECT / "data" / "data_quality_report.json", {}) or {}
        audit = quality.get("audit_status_distribution") or {}
        try:
            llm_summary = llm.config_summary()
        except Exception:  # noqa: BLE001
            llm_summary = {}
        try:
            asr_summary = asr.config_summary()
        except Exception:  # noqa: BLE001
            asr_summary = {"enabled": False, "detail": "语音入口未配置"}
        payload = {
            "brand": "合规雷达",
            "build": BUILD,
            "snapshot_version": snapshot.SNAPSHOT_VERSION,
            "data_cutoff": snapshot.DATA_CUTOFF,
            "categories": list(corpus.ENTRY_CATEGORIES),
            "markets": [{"name": name, "code": code}
                        for name, code in corpus.SUPPORTED_MARKETS.items()],
            "timeline_windows": list(dates.WINDOW_OPTIONS.keys()),
            "coverage": {
                "laws": store.get("laws") or 0,
                "law_store_ok": bool(store.get("ok")),
                "law_store_reason": store.get("reason") or "",
                "categories": len(corpus.ENTRY_CATEGORIES),
                "markets": len(corpus.SUPPORTED_MARKETS),
                "audited": audit.get("已核对") or 0,
                "pending_audit": audit.get("待核对") or 0,
                "total_rows": quality.get("total_rows") or 0,
                "status_distribution": quality.get("status_distribution") or {},
            },
            "llm": {
                "ready": bool(llm_summary.get("ready")),
                "model": llm_summary.get("model") or "",
                "reason": llm_summary.get("reason") or "",
            },
            "asr": {
                "enabled": bool(asr_summary.get("enabled")),
                "backend": asr_summary.get("backend") or "off",
                "detail": asr_summary.get("detail") or "",
            },
        }
        _boot_cache = payload
        return payload


# ── /api/freshness ────────────────────────────────────────────
def _freshness_payload() -> dict:
    global _fresh_cache, _fresh_mtime
    try:
        mtime = FRESHNESS_FILE.stat().st_mtime
    except OSError:
        return {"available": False, "reason": "时效性检查结果尚未生成", "runs": [],
                "counts": {}, "pending": [], "changed": [], "checked_at": ""}
    if _fresh_cache is not None and mtime == _fresh_mtime:
        return _fresh_cache
    with _fresh_lock:
        if _fresh_cache is not None and mtime == _fresh_mtime:
            return _fresh_cache
        data = _read_json(FRESHNESS_FILE, None)
        if not isinstance(data, dict):
            return {"available": False, "reason": "时效性检查结果无法读取", "runs": [],
                    "counts": {}, "pending": [], "changed": [], "checked_at": ""}

        links = data.get("links") or {}
        pending, changed = [], []
        for url, info in links.items():
            item = {
                "url": url,
                "title": _link_title(url),
                "kind": info.get("kind") or "",
                "error": info.get("error") or "",
                "http_status": info.get("http_status"),
                "content_verified": bool(info.get("content_verified")),
                "changed": bool(info.get("changed")),
            }
            if not info.get("ok") or info.get("content_verified") is False:
                pending.append(item)
            if info.get("changed"):
                changed.append(item)

        runs = []
        try:
            lines = FRESHNESS_RUNS_FILE.read_text(encoding="utf-8").splitlines()
            for line in lines[-2:][::-1]:
                row = json.loads(line)
                runs.append({
                    "run_id": row.get("run_id") or "",
                    "checked_at": row.get("checked_at") or "",
                    "duration_seconds": row.get("duration_seconds") or 0,
                    "total": row.get("total") or 0,
                    "http_ok": row.get("http_ok") or 0,
                    "content_verified": row.get("content_verified") or 0,
                    "changed": row.get("changed") or 0,
                    "failed": row.get("failed") or 0,
                    "net_error": row.get("net_error") or 0,
                    "link_error": row.get("link_error") or 0,
                })
        except Exception:  # noqa: BLE001
            pass

        counts = {
            "total": data.get("total") or len(links),
            "http_ok": data.get("http_ok") or 0,
            "content_verified": data.get("content_verified") or 0,
            "failed": data.get("failed") or 0,
            "link_error": data.get("link_error") or 0,
            "net_error": data.get("net_error") or 0,
            "empty_content": data.get("empty_content") or 0,
            "rate_limited": data.get("rate_limited") or 0,
            "changed": data.get("changed") or len(changed),
            "pending": len(pending),
        }
        payload = {
            "available": True,
            "run_id": data.get("run_id") or "",
            "checked_at": data.get("checked_at") or "",
            "checked_at_utc": data.get("checked_at_utc") or "",
            "duration_seconds": data.get("duration_seconds") or 0,
            "proxy": data.get("proxy") or {},
            "counts": counts,
            "runs": runs,
            "pending": pending,
            "changed": changed,
        }
        _fresh_cache = payload
        _fresh_mtime = mtime
        return payload


# ── 工具查询 ──────────────────────────────────────────────────
def _param(body: dict, key: str, default: str = "") -> str:
    value = body.get(key)
    return str(value).strip() if value is not None else default


def _tool_map(body: dict) -> dict:
    from modules import m1_map
    result = m1_map.query(_param(body, "category", DEFAULT_CATEGORY),
                          _param(body, "market", DEFAULT_MARKET),
                          use_llm=bool(body.get("use_llm")))
    if not result.get("ok"):
        return result
    return _records_from_map(result)


def _tool_todo(body: dict) -> dict:
    from modules import m3_todo
    result = m3_todo.query(_param(body, "category", DEFAULT_CATEGORY),
                           _param(body, "market", DEFAULT_MARKET),
                           use_llm=bool(body.get("use_llm")))
    if not result.get("ok"):
        return result
    actions = [_normalize_action(a) for a in result.get("动作", [])]
    return {
        "category": result.get("品类") or "",
        "market": result.get("市场") or "",
        "actions": actions,
        "groups": [{"type": t, "actions": [_normalize_action(a) for a in items]}
                   for t, items in (result.get("分组") or [])],
        "pending": result.get("待确认") or [],
        "unproduced": result.get("未产出") or [],
        "history": result.get("历史关联") or [],
        "stats": result.get("stats") or {},
        "header": result.get("header") or {},
        "llm": result.get("llm") or {},
    }


def _tool_timeline(body: dict) -> dict:
    from modules import m2_timeline
    result = m2_timeline.query(_param(body, "category", DEFAULT_CATEGORY),
                               _param(body, "market", DEFAULT_MARKET),
                               window=body.get("window") or m2_timeline.DEFAULT_WINDOW,
                               use_llm=bool(body.get("use_llm")))
    if not result.get("ok"):
        return result
    return {
        "category": result.get("品类") or "",
        "market": result.get("市场") or "",
        "window": result.get("时间窗") or "",
        "window_months": result.get("window_months") or 0,
        "recent": [_normalize_event(e) for e in result.get("近窗内", [])],
        "upcoming": [_normalize_event(e) for e in result.get("即将发生", [])],
        "stats": result.get("stats") or {},
        "header": result.get("header") or {},
        "llm": result.get("llm") or {},
    }


def _tool_compare(body: dict) -> dict:
    from modules import m5_compare
    markets = body.get("markets") or None
    result = m5_compare.query(_param(body, "category", DEFAULT_CATEGORY), markets)
    if not result.get("ok"):
        return result
    return {
        "category": result.get("品类") or "",
        "markets": result.get("市场") or [],
        "regions": [{
            "market": region.get("市场") or "",
            "count": region.get("数量") or 0,
            "pending_audit": region.get("待核对") or 0,
            "ok": bool(region.get("状态")),
            "records": [_normalize_record(r) for r in region.get("记录", [])],
        } for region in result.get("区域", [])],
        "shared": result.get("共同") or [],
        "unique": result.get("独有") or {},
        "shared_count": result.get("共同数量") or 0,
        "note": result.get("说明") or "",
        "header": result.get("header") or {},
    }


def _tool_multi(body: dict) -> dict:
    from modules import m6_multi_region
    markets = body.get("markets") or None
    result = m6_multi_region.query(_param(body, "category", DEFAULT_CATEGORY), markets)
    if not result.get("ok"):
        return result
    return {
        "category": result.get("品类") or "",
        "markets": result.get("市场") or [],
        "total": result.get("总条数") or 0,
        "regions": [{
            "market": region.get("市场") or "",
            "count": region.get("条数") or 0,
            "pending_audit": region.get("待核对") or 0,
            "blocked": region.get("被拦截") or 0,
            "ok": bool(region.get("状态")),
            "records": [_normalize_record(r) for r in region.get("法规", [])],
        } for region in result.get("区域", [])],
        "header": result.get("header") or {},
    }


def _readiness_phases(region: dict, phase_names: list[str]) -> list[dict]:
    """按 M7 的六阶段顺序输出，空阶段也保留（前端用来画完整路线）。"""
    existing = {phase.get("名称"): phase for phase in (region.get("阶段") or [])}
    ordered = list(phase_names) + [name for name in existing if name not in phase_names]
    phases = []
    for name in ordered:
        phase = existing.get(name) or {}
        actions = [{
            "id": (task.get("官方编号") or "") + "|" + (task.get("动作") or ""),
            "title": task.get("动作") or "",
            "phase": task.get("阶段") or name,
            "role": task.get("责任角色") or "",
            "status": task.get("状态") or "",
            "urgency": task.get("紧迫度") or "",
            "condition": task.get("适用条件") or "",
            "official_id": task.get("官方编号") or "",
            "law": task.get("依据法规") or "",
            "url": task.get("官方链接") or "",
        } for task in (phase.get("动作") or [])]
        phases.append({"name": name, "count": len(actions), "actions": actions})
    return phases


def _tool_readiness(body: dict) -> dict:
    from modules import m7_opc_readiness
    markets = body.get("markets") or None
    result = m7_opc_readiness.query(_param(body, "category", DEFAULT_CATEGORY), markets)
    if not result.get("ok"):
        return result
    return {
        "category": result.get("品类") or "",
        "markets": result.get("市场") or [],
        "total_actions": result.get("总动作数") or 0,
        "high_priority": result.get("高优先级数") or 0,
        "note": result.get("说明") or "",
        "phase_names": list(m7_opc_readiness.PHASES),
        "regions": [{
            "market": region.get("市场") or "",
            "status": region.get("状态") or "",
            "action_count": region.get("动作条数") or 0,
            "pending_audit": region.get("待核对") or 0,
            "pending_confirm": region.get("需确认条数") or 0,
            "phases": _readiness_phases(region, list(m7_opc_readiness.PHASES)),
        } for region in result.get("区域", [])],
        "header": result.get("header") or {},
    }


_TOOL_HANDLERS = {
    "map": _tool_map,
    "todo": _tool_todo,
    "timeline": _tool_timeline,
    "compare": _tool_compare,
    "multi": _tool_multi,
    "readiness": _tool_readiness,
}


# ── 路由结果 ──────────────────────────────────────────────────
_REASON_REPLY = {
    "empty": "先写一句你的产品、市场和问题。",
    "no_slots": "还没听出品类或市场。可以说「毛绒玩具卖到欧盟」这样的一句话。",
    "partial_品类": "请补充商品品类，例如儿童玩具、电子电器。",
    "partial_市场": "请补充目标市场。目前支持欧盟和美国。",
    "m1_unavailable": "识别成功，但法规库暂时没有返回结果，请稍后再试。",
}


def _route_reply(result: dict) -> str:
    if result.get("ok"):
        m1 = result.get("m1") or {}
        count = len(m1.get("primary", [])) + len(m1.get("cross", []))
        parts = [f"已识别：{result.get('品类', '')} / {result.get('市场', '')}。"
                 f"查到 {count} 条相关法规。"]
        missing = result.get("missing") or []
        if missing:
            parts.append("还需要确认：" + "、".join(missing) + "。")
        return "".join(parts)
    reason = result.get("reason") or ""
    ident = result.get("识别") or {}
    if reason == "bad_category":
        user = ident.get("用户品类") or "这个品类"
        return (f"暂不支持「{user}」。目前支持：儿童玩具、电子电器、纺织服装、"
                "美妆个护、食品接触材料。")
    if reason == "bad_market":
        user = ident.get("用户市场") or "这个市场"
        return f"暂不支持「{user}」。目前支持欧盟和美国。"
    note = result.get("note") or ""
    base = _REASON_REPLY.get(reason) or (reason or "暂时无法识别，请补充品类和市场。")
    return base + (f"（{note}）" if note else "")


def _route_payload(text: str, context: str, use_llm: bool = False) -> dict:
    from modules import m15_router
    result = m15_router.route(text, context, use_llm=use_llm)
    ident = result.get("识别") or {}
    m1 = result.get("m1") or None
    payload = {
        "ok": bool(result.get("ok")),
        "reason": result.get("reason") or "",
        "route_via": result.get("route_via") or "",
        "note": result.get("note") or "",
        "reply": _route_reply(result),
        "category": result.get("品类") or "",
        "market": result.get("市场") or "",
        "user_category": ident.get("用户品类") or "",
        "user_market": ident.get("用户市场") or "",
        "sources": {
            "category": ident.get("品类来源") or "",
            "market": ident.get("市场来源") or "",
        },
        "hits": result.get("命中词") or [],
        "missing": result.get("missing") or [],
        "m1": None,
    }
    if m1 and m1.get("ok"):
        payload["m1"] = _records_from_map(m1)
    return payload


# ── 搜索 ──────────────────────────────────────────────────────
def _search_payload(identifier: str, heading: str) -> dict:
    from core import law_store
    result = law_store.retrieve(identifier, heading)
    units = []
    for unit in result.get("units", []):
        units.append({
            "heading": unit.get("heading") or "（无标题）",
            "locator": unit.get("locator") or "",
            "document_id": unit.get("document_id") or "",
            "parse_status": unit.get("parse_status") or "",
            "body": unit.get("body") or "",
            "truncated": bool(unit.get("truncated")),
            "version_date": unit.get("version_date") or "",
            "kind": unit.get("kind") or "",
            "source_url": unit.get("source_url") or "",
        })
    if result.get("ok") and units:
        return {
            "ok": True,
            "reason": "",
            "mode": "identifier",
            "identifier": result.get("law_id") or identifier,
            "units": units,
        }

    # 编号定位失败时，把输入当作自然语言问题走两层召回
    # （路由 LLM 选法规 → 检索 LLM 选片段），与 Gradio 会话的「检索条文依据」同一条链路。
    identifier = (identifier or "").strip()
    if len(identifier) >= 4:
        try:
            from modules import recall_flow
            recalled = recall_flow.run(identifier, use_llm=True)
        except Exception:  # noqa: BLE001
            LOG.exception("recall fallback failed")
            recalled = {"ok": False, "reason": "智能检索暂不可用，请稍后重试"}
        retrieval = (recalled.get("retrieval") or {})
        selected = retrieval.get("selected") or []
        if recalled.get("ok") and selected:
            route = recalled.get("route") or {}
            return {
                "ok": True,
                "reason": "",
                "mode": "recall",
                "identifier": identifier,
                "route_via": route.get("route_via") or "",
                "coverage": retrieval.get("coverage") or "",
                "units": [{
                    "heading": snippet.get("heading") or snippet.get("path") or "条文片段",
                    "locator": _safe_url(snippet.get("locator") or ""),
                    "document_id": snippet.get("law_id") or "",
                    "parse_status": "智能检索",
                    "body": snippet.get("body") or "",
                    "truncated": False,
                    "version_date": "",
                    "kind": "recall",
                    "source_url": _safe_url(snippet.get("locator") or ""),
                } for snippet in selected],
            }
        recall_reason = recalled.get("reason") or retrieval.get("reason") or ""
        if recall_reason:
            return {
                "ok": False,
                "reason": (result.get("reason") or "没有检索到条款") + "；智能检索：" + recall_reason,
                "mode": "recall",
                "identifier": identifier,
                "units": [],
            }

    return {
        "ok": bool(result.get("ok")),
        "reason": result.get("reason") or "",
        "mode": "identifier",
        "identifier": result.get("law_id") or identifier,
        "units": units,
    }


# ── 安装 ──────────────────────────────────────────────────────
def _install_routes(app, shell: str):
    """把 /、/web、/api/* 挂到 FastAPI 实例上。调用方保证 shell 已读入。"""
    from fastapi.responses import HTMLResponse, JSONResponse, Response
    from fastapi.staticfiles import StaticFiles
    from starlette.concurrency import run_in_threadpool
    from starlette.requests import Request
    from starlette.routing import Route

    async def _body(request: Request) -> dict:
        try:
            raw = await request.body()
            if not raw:
                return {}
            payload = json.loads(raw.decode("utf-8"))
            return payload if isinstance(payload, dict) else {}
        except Exception:  # noqa: BLE001
            LOG.warning("request body was not valid UTF-8 JSON", exc_info=True)
            return {}

    def _json(data, status_code: int = 200):
        return JSONResponse(data, status_code=status_code)

    async def api_bootstrap(request: Request):
        try:
            data = await run_in_threadpool(_bootstrap_payload)
            return _json(_envelope(data))
        except Exception:  # noqa: BLE001
            LOG.exception("bootstrap payload failed")
            return _json(_envelope(None, False, "启动信息暂时不可用，请稍后再试。", _meta()), 500)

    async def api_freshness(request: Request):
        try:
            data = await run_in_threadpool(_freshness_payload)
            return _json(_envelope(data))
        except Exception:  # noqa: BLE001
            LOG.exception("freshness payload failed")
            return _json(_envelope(None, False, "时效性检查结果暂时不可用，请稍后再试。", _meta()), 500)

    async def api_tool(request: Request):
        name = request.path_params.get("name") or ""
        handler = _TOOL_HANDLERS.get(name)
        if handler is None:
            return _json(_envelope(None, False, f"未知工具：{name}", _meta()), 404)
        body = await _body(request)
        try:
            data = await run_in_threadpool(handler, body)
        except Exception:  # noqa: BLE001
            LOG.exception("tool query failed: %s", name)
            return _json(_envelope(None, False, "查询暂时未完成，请稍后再试。", _meta()), 500)
        if not isinstance(data, dict):
            return _json(_envelope(None, False, "查询返回了无法解析的结果", _meta()), 500)
        # 归一化后的成功载荷不含 ok 字段；模块原始失败载荷带 ok:false。
        if "ok" not in data:
            data["ok"] = True
        if not data.get("ok"):
            return _json(_envelope(None, False, data.get("reason") or "查询未成功", _meta()))
        return _json(_envelope(data))

    async def api_route(request: Request):
        body = await _body(request)
        text = str(body.get("text") or "").strip()
        context = str(body.get("context") or "").strip()
        use_llm = bool(body.get("use_llm"))
        try:
            data = await run_in_threadpool(_route_payload, text, context, use_llm)
        except Exception:  # noqa: BLE001
            LOG.exception("route payload failed")
            return _json(_envelope(None, False, "暂时无法完成识别，请补充品类和市场后重试。", _meta()), 500)
        return _json(_envelope(data))

    async def api_search(request: Request):
        identifier = (request.query_params.get("identifier")
                      or request.query_params.get("q") or "").strip()
        heading = (request.query_params.get("heading") or "").strip()
        if not identifier:
            return _json(_envelope(None, False, "请输入法规编号，例如 32009L0048。", _meta()), 400)
        try:
            data = await run_in_threadpool(_search_payload, identifier, heading)
        except Exception:  # noqa: BLE001
            LOG.exception("search payload failed")
            return _json(_envelope(None, False, "条款库暂时不可用，请稍后再试。", _meta()), 500)
        if not data.get("ok"):
            return _json(_envelope(None, False, data.get("reason") or "没有检索到结果", _meta()))
        return _json(_envelope(data))

    async def api_transcribe(request: Request):
        """浏览器录音/上传 → WAV → core.asr.transcribe(path)。

        音频只落在进程临时目录，转写结束立即删除；响应不带路径或密钥。
        """
        max_bytes = 10 * 1024 * 1024
        try:
            declared = int(request.headers.get("content-length") or 0)
        except ValueError:
            declared = 0
        if declared > max_bytes + 64 * 1024:
            return _json(_envelope(None, False, "音频超过 10MB，请缩短录音。", _meta()), 413)
        try:
            form = await request.form()
        except Exception:  # noqa: BLE001
            LOG.warning("voice form parse failed", exc_info=True)
            return _json(_envelope(None, False, "无法读取上传的音频。", _meta()), 400)
        upload = form.get("audio") or form.get("file")
        if upload is None or not hasattr(upload, "read"):
            return _json(_envelope(None, False, "请先录音或上传音频。", _meta()), 400)
        try:
            payload = await upload.read()
        except Exception:  # noqa: BLE001
            LOG.warning("voice upload read failed", exc_info=True)
            return _json(_envelope(None, False, "读取音频失败，请重试。", _meta()), 400)
        finally:
            try:
                await upload.close()
            except Exception:  # noqa: BLE001
                pass
        if not payload:
            return _json(_envelope(None, False, "音频是空的，请重新录制。", _meta()), 400)
        if len(payload) > max_bytes:
            return _json(_envelope(None, False, "音频超过 10MB，请缩短录音。", _meta()), 413)

        suffix = Path(getattr(upload, "filename", "") or "audio.wav").suffix.lower()
        if suffix not in (".wav", ".webm", ".ogg", ".mp3", ".m4a", ".mp4"):
            suffix = ".wav"
        path = None
        try:
            handle, path = tempfile.mkstemp(prefix="cr-voice-", suffix=suffix)
            os.close(handle)
            with open(path, "wb") as target:
                target.write(payload)
            from core import asr
            text, meta = await run_in_threadpool(asr.transcribe, path)
        except Exception:  # noqa: BLE001
            LOG.exception("voice transcription failed")
            return _json(_envelope(None, False, "语音转写暂时不可用，请稍后再试。", _meta()), 500)
        finally:
            if path:
                try:
                    os.unlink(path)
                except OSError:
                    pass
        if not meta.get("ok"):
            return _json(_envelope(None, False, meta.get("reason") or "没有识别到语音。", _meta()))
        return _json(_envelope({
            "text": text,
            "meta": {
                "backend": meta.get("backend") or "",
                "cached": bool(meta.get("cached")),
                "seconds": meta.get("seconds") or 0,
                "lang": meta.get("lang") or "",
            },
        }))

    def _file_response(name: str, payload: bytes):
        is_json = name.lower().endswith(".json")
        disposition = (f"attachment; filename=\"export{'.json' if is_json else '.csv'}\"; "
                       f"filename*=UTF-8''{quote(name)}")
        return Response(
            content=payload,
            media_type="application/json; charset=utf-8" if is_json else "text/csv; charset=utf-8",
            headers={"Content-Disposition": disposition},
        )

    def _too_large(request: Request, limit: int) -> bool:
        try:
            return int(request.headers.get("content-length") or 0) > limit
        except ValueError:
            return False

    async def api_conversation_message(request: Request):
        """完整会话：保留多轮条件、结果、追问与动作状态。"""
        if _too_large(request, 6 * 1024 * 1024):
            return _json(_envelope(None, False, "会话状态过大，请新建对话后重试。", _meta()), 413)
        body = await _body(request)
        text = str(body.get("text") or "").strip()[:6000]
        action = body.get("action")
        action = str(action).strip() if action else None
        session = body.get("session")
        use_llm = body.get("use_llm")
        if use_llm is not None:
            from core import llm as llm_core
            if not isinstance(session, dict):
                from core import conversation as conv_core
                session = conv_core.new_session()
            session.setdefault("context", {})["use_llm"] = bool(use_llm) and llm_core.is_ready()
        try:
            from core import conversation
            state, result = await run_in_threadpool(
                conversation.respond, text, session, action)
        except Exception:  # noqa: BLE001
            LOG.exception("conversation respond failed")
            return _json(_envelope(None, False, "本次对话暂时没有完成，请稍后再试。", _meta()), 500)
        payload = _json_safe({"session": state, "result": result})
        if payload is None:
            return _json(_envelope(None, False, "会话状态无法序列化，请新建对话后重试。", _meta()), 500)
        return _json(_envelope(payload))

    async def api_conversation_complete(request: Request):
        if _too_large(request, 8 * 1024 * 1024):
            return _json(_envelope(None, False, "会话状态过大，请新建对话后重试。", _meta()), 413)
        body = await _body(request)
        result_id = str(body.get("result_id") or "").strip()
        item_id = str(body.get("item_id") or "").strip()
        if not result_id or not item_id:
            return _json(_envelope(None, False, "缺少结果或条目标识。", _meta()), 400)
        try:
            from core import conversation
            state, result = await run_in_threadpool(
                conversation.complete_task, body.get("session"), result_id, item_id)
        except ValueError as exc:
            return _json(_envelope(None, False, str(exc), _meta()), 400)
        except Exception:  # noqa: BLE001
            LOG.exception("conversation complete failed")
            return _json(_envelope(None, False, "记录进度暂时没有完成，请稍后再试。", _meta()), 500)
        payload = _json_safe({"session": state, "result": result})
        if payload is None:
            return _json(_envelope(None, False, "会话状态无法序列化，请新建对话后重试。", _meta()), 500)
        return _json(_envelope(payload))

    async def api_conversation_export(request: Request):
        if _too_large(request, 8 * 1024 * 1024):
            return _json(_envelope(None, False, "会话状态过大，请新建对话后重试。", _meta()), 413)
        body = await _body(request)
        result_id = str(body.get("result_id") or "").strip()
        if not result_id:
            return _json(_envelope(None, False, "缺少结果标识。", _meta()), 400)
        try:
            from core import conversation
            name, payload = await run_in_threadpool(
                conversation.export_result, body.get("session"), result_id)
        except ValueError as exc:
            return _json(_envelope(None, False, str(exc), _meta()), 400)
        except Exception:  # noqa: BLE001
            LOG.exception("conversation export failed")
            return _json(_envelope(None, False, "导出暂时不可用，请稍后再试。", _meta()), 500)
        return _file_response(name, payload)

    async def api_export_todo(request: Request):
        from modules import m3_todo
        category = (request.query_params.get("category") or DEFAULT_CATEGORY).strip()
        market = (request.query_params.get("market") or DEFAULT_MARKET).strip()
        try:
            result = await run_in_threadpool(
                m3_todo.query, category, market, False)
            name, payload = m3_todo.export_csv(result)
            return _file_response(name, payload)
        except Exception:  # noqa: BLE001
            LOG.exception("todo csv export failed")
            return _json(_envelope(None, False, "导出暂时不可用，请稍后再试。", _meta()), 400)

    async def api_export_readiness(request: Request):
        from modules import m7_opc_readiness
        category = (request.query_params.get("category") or DEFAULT_CATEGORY).strip()
        markets_raw = (request.query_params.get("markets") or "").strip()
        markets = [m.strip() for m in markets_raw.split(",") if m.strip()] or None
        try:
            result = await run_in_threadpool(
                m7_opc_readiness.query, category, markets)
            name, payload = m7_opc_readiness.export_csv(result)
            return _file_response(name, payload)
        except Exception:  # noqa: BLE001
            LOG.exception("readiness csv export failed")
            return _json(_envelope(None, False, "导出暂时不可用，请稍后再试。", _meta()), 400)

    app.mount("/web", StaticFiles(directory=WEB_DIR), name="web")
    routes = [
        Route("/api/bootstrap", api_bootstrap, methods=["GET"]),
        Route("/api/freshness", api_freshness, methods=["GET"]),
        Route("/api/route", api_route, methods=["POST"]),
        Route("/api/tool/{name}", api_tool, methods=["POST"]),
        Route("/api/search", api_search, methods=["GET"]),
        Route("/api/transcribe", api_transcribe, methods=["POST"]),
        Route("/api/conversation/message", api_conversation_message, methods=["POST"]),
        Route("/api/conversation/complete", api_conversation_complete, methods=["POST"]),
        Route("/api/conversation/export", api_conversation_export, methods=["POST"]),
        Route("/api/export/todo.csv", api_export_todo, methods=["GET"]),
        Route("/api/export/readiness.csv", api_export_readiness, methods=["GET"]),
        Route("/", lambda request: HTMLResponse(shell)),
    ]
    # 抢在 Gradio 首页与内置 API 之前接管这些精确路径；/gradio_api/* 不受影响。
    for route in reversed(routes):
        app.router.routes.insert(0, route)


def install(demo) -> bool:
    """接管根路由并挂载静态资源 + /api/*。成功返回 True，失败返回 False（不抛）。"""
    try:
        app = getattr(demo, "app", None)
        if app is None:
            return False
        # 安装期就把外壳读进来：若留到请求期再读，读不到时根路由已被遮蔽，
        # 调用方拿不到 False、无从回退，只会在 "/" 上得到一个 500。
        shell = index_html()
        _install_routes(app, shell)
        return True
    except Exception:  # noqa: BLE001
        return False
