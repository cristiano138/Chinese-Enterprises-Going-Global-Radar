# -*- coding: utf-8 -*-
"""时效性检查的只读数据契约（供前端/调用方使用）。

本模块不发起网络请求、不写文件，只做三件事：
    1. 读 ``data/freshness_latest.json``（链接级）与运行日志；
    2. 读 ``data/metadata_check_latest.json``（官方字段级）；
    3. 计算“多久没查了 / 是否过期 / 是否第一次使用 / 下一次计划时间”。

前端改版分支只需调用 :func:`summarize`，不要把口径散在 UI 里。
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")

LATEST_PATH = os.path.join(DATA_DIR, "freshness_latest.json")
RUNS_PATH = os.path.join(DATA_DIR, "freshness_runs.jsonl")
LOG_PATH = os.path.join(DATA_DIR, "freshness_log.jsonl")
METADATA_LATEST_PATH = os.path.join(DATA_DIR, "metadata_check_latest.json")
SCHEDULE_PATH = os.path.join(DATA_DIR, "freshness_schedule.json")

BJT = timezone(timedelta(hours=8))
DEFAULT_TIMES = ("19:00", "22:00")
DEFAULT_STALE_HOURS = 24


def _read_json(path: str) -> Optional[dict]:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError, TypeError):
        return None


def _read_jsonl(path: str) -> List[dict]:
    rows: List[dict] = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except OSError:
        return []
    return rows


def load_latest(path: Optional[str] = None) -> Optional[dict]:
    """链接级最新态；文件不存在或损坏返回 None。"""
    return _read_json(path or LATEST_PATH)


def load_metadata_latest(path: Optional[str] = None) -> Optional[dict]:
    """官方字段级最新态；文件不存在或损坏返回 None。"""
    return _read_json(path or METADATA_LATEST_PATH)


def load_schedule(path: Optional[str] = None) -> dict:
    """读取定时配置；缺失时回落到北京时间 19:00 / 22:00。"""
    data = _read_json(path or SCHEDULE_PATH) or {}
    times = data.get("times")
    if not isinstance(times, list) or not times:
        times = list(DEFAULT_TIMES)
    clean_times = [str(t) for t in times if isinstance(t, str)]
    return {
        "timezone": data.get("timezone") or "Asia/Shanghai",
        "times": clean_times or list(DEFAULT_TIMES),
        "grace_minutes": int(data.get("grace_minutes") or 120),
    }


PUBLIC_RUN_FIELDS = (
    "checked_at", "total", "content_verified", "ok", "empty_content",
    "rate_limited", "failed", "link_error", "net_error", "changed",
    "legacy_schema",
)


def _public_run(run: dict) -> dict:
    """只暴露页面需要的运行字段；原始日志仍保留完整审计信息。"""
    return {key: run[key] for key in PUBLIC_RUN_FIELDS if key in run}


def read_runs(limit: int = 2, path: Optional[str] = None) -> List[dict]:
    """最近 N 次运行汇总，最新在前。

    优先读 ``freshness_runs.jsonl``（新版每次运行一行）；旧版没有该文件时，
    按 ``run_id`` / ``ts`` 分钟从逐链接日志里聚合，保证页面不会空白。
    """
    limit = max(int(limit), 0)
    if limit == 0:
        return []
    runs = _read_jsonl(path or RUNS_PATH)
    if runs:
        def sort_key(run):
            return (parse_checked_at(run.get("checked_at"))
                    or datetime.min.replace(tzinfo=BJT))
        return [_public_run(run)
                for run in sorted(runs, key=sort_key, reverse=True)[:limit]]

    rows = _read_jsonl(LOG_PATH)
    grouped: Dict[str, List[dict]] = {}
    order: List[str] = []
    for row in rows:
        key = row.get("run_id") or str(row.get("ts", ""))[:16]
        if not key:
            continue
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(row)

    summaries = []
    for key in reversed(order):
        batch = grouped[key]
        summaries.append({
            "run_id": key,
            "checked_at": max((r.get("ts", "") for r in batch), default=""),
            "total": len(batch),
            "ok": sum(1 for r in batch if r.get("ok")),
            "content_verified": sum(1 for r in batch if r.get("content_verified")),
            "empty_content": sum(1 for r in batch
                                 if r.get("kind") == "empty_content"),
            "rate_limited": sum(1 for r in batch
                                if r.get("kind") == "rate_limited"),
            "link_error": sum(1 for r in batch if r.get("kind") == "link_error"),
            "net_error": sum(1 for r in batch if r.get("kind") == "net_error"),
            "changed": sum(1 for r in batch if r.get("changed")),
            "legacy_schema": True,
        })
        if len(summaries) >= limit:
            break

    def sort_key(run):
        return (parse_checked_at(run.get("checked_at"))
                or datetime.min.replace(tzinfo=BJT))
    return [_public_run(run)
            for run in sorted(summaries, key=sort_key, reverse=True)[:limit]]


def parse_checked_at(value: Any) -> Optional[datetime]:
    """解析 ``YYYY-mm-dd HH:MM:SS``（北京时间）或带时区 ISO 字符串。"""
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        try:
            dt = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=BJT)
    return dt


def next_run(now: Optional[datetime] = None, schedule: Optional[dict] = None) -> Optional[datetime]:
    """按北京时间 19:00 / 22:00 计算下一次计划时间。"""
    if now is None:
        now = datetime.now(BJT)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=BJT)
    now = now.astimezone(BJT)
    schedule = schedule or load_schedule()
    slots = []
    for text in schedule.get("times", DEFAULT_TIMES):
        try:
            hour, minute = (int(part) for part in text.split(":", 1))
        except (ValueError, TypeError):
            continue
        slots.append((hour, minute))
    if not slots:
        slots = [(19, 0), (22, 0)]
    slots.sort()
    for hour, minute in slots:
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate > now:
            return candidate
    hour, minute = slots[0]
    return (now + timedelta(days=1)).replace(
        hour=hour, minute=minute, second=0, microsecond=0)


def _counts(latest: Optional[dict]) -> dict:
    if not latest:
        return {
            "total": 0, "http_ok": 0, "content_verified": 0, "ok": 0,
            "empty_content": 0, "rate_limited": 0, "failed": 0,
            "link_error": 0, "net_error": 0, "changed": 0,
            "legacy_schema": False,
        }
    schema = int(latest.get("schema_version") or 1)
    legacy = schema < 2
    total = int(latest.get("total") or 0)
    # 旧口径把 202 空响应算作 ok，不能原样当成“已核验”。
    verified = int(latest.get("content_verified") or 0) if not legacy else 0
    return {
        "total": total,
        "http_ok": int(latest.get("http_ok") or 0),
        "content_verified": verified,
        "ok": verified,
        "empty_content": int(latest.get("empty_content") or 0),
        "rate_limited": int(latest.get("rate_limited") or 0),
        "failed": int(latest.get("failed") or (total - verified)),
        "link_error": int(latest.get("link_error") or 0),
        "net_error": int(latest.get("net_error") or 0),
        "changed": int(latest.get("changed") or 0),
        "legacy_schema": legacy,
    }


def _pending(latest: Optional[dict]) -> List[dict]:
    if not latest:
        return []
    pending = latest.get("pending_links")
    if isinstance(pending, list):
        return [p for p in pending if isinstance(p, dict)]
    out = []
    for url, rec in (latest.get("links") or {}).items():
        if not isinstance(rec, dict) or rec.get("ok"):
            continue
        out.append({
            "url": url,
            "kind": rec.get("kind") or "unknown",
            "status": rec.get("status"),
            "error": rec.get("error", ""),
        })
    return out


_UNSET = object()


def summarize(now: Optional[datetime] = None,
              latest: Any = _UNSET,
              stale_hours: Optional[float] = None) -> Dict[str, Any]:
    """一次返回页面需要的全部时效性状态。

    ``latest`` 不传时读磁盘；显式传 ``None`` 表示“没有检查记录”
    （测试与首次使用态都依赖这个区别）。

    ``stale_hours`` 默认读环境变量 ``FRESHNESS_STALE_HOURS``，再回落 24 小时。
    """
    if now is None:
        now = datetime.now(BJT)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=BJT)

    if stale_hours is None:
        try:
            stale_hours = float(os.getenv("FRESHNESS_STALE_HOURS", "")
                                or DEFAULT_STALE_HOURS)
        except ValueError:
            stale_hours = DEFAULT_STALE_HOURS

    if latest is _UNSET:
        latest = load_latest()
    schedule = load_schedule()
    counts = _counts(latest)
    runs = read_runs(2)
    metadata = load_metadata_latest()

    if not latest:
        return {
            "has_data": False,
            "first_run": not runs,
            "stale": True,
            "legacy_schema": False,
            "checked_at": "",
            "age_hours": None,
            "stale_hours": stale_hours,
            "message": "还没有时效性检查记录",
            "schedule": schedule,
            "next_run": next_run(now, schedule).isoformat(timespec="seconds"),
            **counts,
            "pending_links": [],
            "last_runs": runs,
            "metadata": metadata,
        }

    checked_at = latest.get("checked_at", "")
    checked_dt = parse_checked_at(checked_at)
    if checked_dt is None:
        age_hours = None
        stale = True
        message = "检查时间无法解析，按过期处理"
    else:
        age_hours = max((now - checked_dt).total_seconds() / 3600.0, 0.0)
        stale = age_hours > stale_hours
        if stale:
            message = f"最近检查 {age_hours:.1f} 小时前，数据可能已过期"
        elif counts["legacy_schema"]:
            message = "最近检查记录来自旧版口径，内容核验数不可信，请重新运行"
        else:
            message = (f"最近检查 {age_hours:.1f} 小时前 · "
                       f"实际取得内容 {counts['content_verified']}/{counts['total']}")

    return {
        "has_data": True,
        "first_run": False,
        "stale": stale,
        "legacy_schema": counts["legacy_schema"],
        "checked_at": checked_at,
        "age_hours": None if age_hours is None else round(age_hours, 1),
        "stale_hours": stale_hours,
        "message": message,
        "schedule": schedule,
        "next_run": next_run(now, schedule).isoformat(timespec="seconds"),
        **counts,
        "pending_links": _pending(latest),
        "last_runs": runs,
        "metadata": metadata,
    }


def first_run(now: Optional[datetime] = None) -> bool:
    """没有任何链接级检查记录时返回 True。"""
    return not load_latest() and not read_runs(1)
