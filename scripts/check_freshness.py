# -*- coding: utf-8 -*-
"""时效性监控 · 链接级核验（scripts/check_freshness.py）

监控对象 = 语料表全部官方链接（官方链接 + ELI 标识），元数据级：
HTTP 状态 / Last-Modified / ETag / 前 128KB 内容哈希。不做全文解析入库。

口径（2026-10-19 修正，必须诚实）：
    ok / content_verified —— HTTP 2xx/3xx 且响应体非空；才算“已核验”。
    http_ok              —— HTTP 2xx/3xx，但可能拿不到内容；单列，不冒充已核验。
    empty_content        —— HTTP 成功但响应体为空（EUR-Lex 实测返回
                            202 + 空体，反爬），不判死链，也不算已核验。
    link_error           —— 连上了但 HTTP 4xx/5xx，链接本身可能失效，待人工复核。
    net_error            —— 本机网络层面没连上（代理未开 / SSL 握手超时 /
                            DNS 失败），只说明“本机 → 目标站”不通，不判死链。

“内容有更新”判定：
    只有上次和本次都取得非空哈希、且哈希不同，才记 changed=True。
    空响应体的哈希（空串 SHA-256）不参与比对——否则所有 202 空响应会互相
    抵消，changed 永远为假，页面却显示“可访问”。

用法：
    python scripts/check_freshness.py                  # 核验全部链接
    python scripts/check_freshness.py --limit 5        # 冒烟
    python scripts/check_freshness.py --proxy direct   # 强制直连
    python scripts/check_freshness.py --proxy auto     # 默认：探测环境代理，不可达自动直连

定时（主方案见 scripts/run_freshness_checks.py）：
    北京时间每天 19:00、22:00。

退出码：永远 0 —— 监控脚本不许把自己跑挂（单个链接失败只记录，不中断）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)

from core import corpus  # noqa: E402
from core import net  # noqa: E402

DATA_DIR = os.path.join(PROJECT, "data")
LOG_PATH = os.path.join(DATA_DIR, "freshness_log.jsonl")
RUNS_PATH = os.path.join(DATA_DIR, "freshness_runs.jsonl")
LATEST_PATH = os.path.join(DATA_DIR, "freshness_latest.json")

SCHEMA_VERSION = 2
TIMEOUT = 30          # 单链接超时（秒）；eCFR 实测有 20s+ 的慢响应
WORKERS = 8           # 并发数
MAX_READ = 128 * 1024  # 只读前 128KB 算哈希（元数据级，不抓全文）
BJT = timezone(timedelta(hours=8))
EMPTY_HASH = hashlib.sha256(b"").hexdigest()[:16]

# eCFR 实测在突发请求下返回 429/503；按主机限速并重试，避免把限流误判成死链。
RETRY_STATUS = {429, 500, 502, 503, 504}
MAX_HTTP_ATTEMPTS = 4
HOST_MIN_INTERVAL = {"www.ecfr.gov": 0.6}
_HOST_LOCKS = {}
_HOST_LOCKS_GUARD = threading.Lock()
_HOST_LAST = {}

_UA = ("Mozilla/5.0 (compatible; ComplianceRadar-Freshness/1.0; "
       "+https://github.com/cristiano138/Chinese-Enterprises-Going-Global-Radar)")

# 语料表里所有可能承载官方链接的列名（**必须与 CSV 实际列名完全一致**）。
# 踩过的坑（10-16 发现，10-17 复审再次确认未合入）：这里曾写成 "ELI链接"，
# 而底表的真实列名是 "ELI标识" —— 于是 29 条欧盟 ELI 永久标识从未被核验，
# 页脚却照常显示「86/86 可访问」，等于把 25% 的链接漏检当成了全覆盖。
# 新增链接列时只改这里，并保持下方 audit_url_fields() 的自检为绿。
URL_FIELDS = ("官方链接", "ELI标识")


def now_bjt():
    return datetime.now(BJT)


def audit_url_fields(rows):
    """口径自检：扫描语料中「出现过 http 取值」但没被 URL_FIELDS 覆盖的列。

    只告警、不抛异常 —— 监控脚本不许把自己跑挂（见文件头「退出码永远 0」）。
    """
    if not rows:
        return []
    uncovered = []
    for name in rows[0].keys():
        if name in URL_FIELDS:
            continue
        hits = sum(1 for r in rows if (r.get(name) or "").strip().startswith("http"))
        if hits:
            uncovered.append((name, hits))
    if uncovered:
        print("⚠️ 口径告警：以下列含 http 取值但不在 URL_FIELDS 中，其链接不会被核验：")
        for name, hits in uncovered:
            print(f"   - {name}（{hits} 条）")
    return uncovered


def collect_urls():
    """从语料表收集去重后的官方链接清单（官方链接 + ELI 标识）。"""
    rows = corpus.load_corpus()
    audit_url_fields(rows)
    urls = []
    seen = set()
    for r in rows:
        for key in URL_FIELDS:
            u = (r.get(key) or "").strip()
            if u.startswith("http") and u not in seen:
                seen.add(u)
                urls.append(u)
    return urls


def _open(req, timeout):
    """独立成函数，便于回归测试注入假响应。"""
    return urllib.request.urlopen(req, timeout=timeout)


def _hash_usable(value):
    """空串哈希不能作为“内容指纹”参与变更比对。"""
    return bool(value) and value != EMPTY_HASH


def _changed(old, new):
    """只有同一来源的两次非空哈希不同，才算内容有更新。

    页面 HTML 哈希与 eCFR API 指纹不可比；来源切换（例如本次走 API、
    上次走 HTML）不应报“内容更新”。
    """
    old = old or {}
    new = new or {}
    old_hash = old.get("hash")
    new_hash = new.get("hash")
    old_via = old.get("verified_via") or ("html" if old_hash else "")
    new_via = new.get("verified_via") or ("html" if new_hash else "")
    return bool(_hash_usable(old_hash) and _hash_usable(new_hash)
                and old_via == new_via and old_hash != new_hash)


def _throttle(host):
    """同一主机串行限速；不同主机互不阻塞。"""
    interval = HOST_MIN_INTERVAL.get(host, 0)
    if interval <= 0:
        return
    with _HOST_LOCKS_GUARD:
        lock = _HOST_LOCKS.setdefault(host, threading.Lock())
    with lock:
        last = _HOST_LAST.get(host)
        if last is not None:
            wait = interval - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
        _HOST_LAST[host] = time.monotonic()


def _retry_delay(attempt, headers=None):
    """优先遵守 Retry-After，否则指数退避；上限 30 秒。"""
    value = (headers or {}).get("Retry-After", "")
    if value:
        try:
            return min(max(int(str(value).strip()), 1), 30)
        except (TypeError, ValueError):
            pass
    return min(2 ** attempt, 30)


_ECFR_PATH_RE = re.compile(r"^/current/title-(\d+)/part-([0-9A-Za-z.]+)/?$")


def _ecfr_api_url(url):
    """把 eCFR 人类页面链接映射到官方 versions API。

    例：/current/title-16/part-1250 →
        https://www.ecfr.gov/api/versioner/v1/versions/title-16.json?part=1250
    """
    parsed = urllib.parse.urlsplit(url)
    if parsed.netloc.lower() != "www.ecfr.gov":
        return ""
    match = _ECFR_PATH_RE.match(parsed.path or "")
    if not match:
        return ""
    title, part = match.group(1), match.group(2)
    return (f"https://www.ecfr.gov/api/versioner/v1/versions/"
            f"title-{title}.json?part={urllib.parse.quote(part)}")


def _ecfr_fingerprint(payload):
    """从 eCFR versions JSON 生成稳定指纹，不直接哈希整段响应。

    只取“会随法规修订变化”的字段，避免无关包装字段造成误报。
    """
    if not isinstance(payload, dict):
        return ""
    meta = payload.get("meta") or {}
    versions = payload.get("content_versions") or []
    rows = []
    for item in versions[:5000]:
        if not isinstance(item, dict):
            continue
        rows.append([
            item.get("identifier"),
            item.get("date"),
            item.get("amendment_date"),
            item.get("issue_date"),
            bool(item.get("substantive")),
            bool(item.get("removed")),
        ])
    canonical = {
        "latest_amendment_date": meta.get("latest_amendment_date"),
        "latest_issue_date": meta.get("latest_issue_date"),
        "result_count": meta.get("result_count"),
        "versions": rows,
    }
    text = json.dumps(canonical, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _probe_ecfr_api(url, timeout=TIMEOUT):
    """eCFR 页面被限流/服务异常时，用官方 API 取结构化内容指纹。"""
    api_url = _ecfr_api_url(url)
    if not api_url:
        return {"ok": False, "error": "not an eCFR part URL", "status": None,
                "hash": "", "content_bytes": 0}
    last = {"ok": False, "error": "", "status": None,
            "hash": "", "content_bytes": 0}
    for attempt in range(1, MAX_HTTP_ATTEMPTS + 1):
        _throttle("www.ecfr.gov")
        try:
            req = urllib.request.Request(
                api_url, headers={"User-Agent": _UA,
                                  "Accept": "application/json"})
            with _open(req, timeout) as resp:
                status = resp.status
                raw = resp.read(4 * 1024 * 1024)
                last["status"] = status
                if status in RETRY_STATUS and attempt < MAX_HTTP_ATTEMPTS:
                    time.sleep(_retry_delay(attempt, resp.headers))
                    continue
                if not (200 <= status < 400):
                    last["error"] = f"API HTTP {status}"
                    return last
                data = json.loads(raw.decode("utf-8"))
                fingerprint = _ecfr_fingerprint(data)
                if not fingerprint:
                    last["error"] = "API returned no usable version data"
                    return last
                return {"ok": True, "error": "", "status": status,
                        "hash": fingerprint, "content_bytes": len(raw)}
        except urllib.error.HTTPError as e:
            last["status"] = e.code
            last["error"] = f"API HTTP {e.code}"
            if e.code in RETRY_STATUS and attempt < MAX_HTTP_ATTEMPTS:
                time.sleep(_retry_delay(attempt, e.headers))
                continue
            return last
        except Exception as e:
            last["error"] = f"API {type(e).__name__}: {str(e)[:100]}"
            return last
    return last


def check_one(url, timeout=TIMEOUT):
    """核验单个链接。返回记录 dict；任何异常都落进记录，不抛出。

    429/5xx 视为“对方限流或暂时故障”，重试后再决定；重试耗尽仍失败
    才记为 link_error，避免把 eCFR 的临时 503 当成法规链接失效。
    """
    ts = now_bjt().strftime("%Y-%m-%d %H:%M:%S")
    host = urllib.parse.urlsplit(url).netloc
    rec = {
        "ts": ts,
        "url": url,
        "ok": False,               # 向后兼容：等价于 content_verified
        "content_verified": False,
        "http_ok": False,
        "kind": "net_error",
        "status": None,
        "last_modified": "",
        "etag": "",
        "hash": "",
        "content_bytes": 0,
        "elapsed_ms": 0,
        "error": "",
        "changed": False,
        "attempts": 0,
        "verified_via": "",
        "api_status": None,
        "api_error": "",
    }
    t0 = time.time()

    # eCFR 人类页面在自动化访问下会被 429/503 限流；官方 versioner API
    # 是同一机构的权威结构化接口，优先用它保证每次都有稳定指纹。
    if _ecfr_api_url(url):
        probe = _probe_ecfr_api(url, timeout)
        rec["api_status"] = probe.get("status")
        rec["api_error"] = probe.get("error", "")
        if probe.get("ok"):
            rec.update({
                "status": probe["status"],
                "http_ok": True,
                "kind": "ok",
                "ok": True,
                "content_verified": True,
                "verified_via": "ecfr_api",
                "hash": probe["hash"],
                "content_bytes": probe["content_bytes"],
                "error": "verified via eCFR API",
            })
            rec["elapsed_ms"] = int((time.time() - t0) * 1000)
            return rec

    for attempt in range(1, MAX_HTTP_ATTEMPTS + 1):
        rec["attempts"] = attempt
        _throttle(host)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _UA})
            with _open(req, timeout) as resp:
                status = resp.status
                body = resp.read(MAX_READ)
                headers = resp.headers
                rec["status"] = status
                rec["last_modified"] = headers.get("Last-Modified", "") or ""
                rec["etag"] = headers.get("ETag", "") or ""
                rec["content_bytes"] = len(body)
                rec["http_ok"] = 200 <= status < 400
                if status in RETRY_STATUS and attempt < MAX_HTTP_ATTEMPTS:
                    rec["error"] = f"HTTP {status} (retry {attempt})"
                    time.sleep(_retry_delay(attempt, headers))
                    continue
                if not rec["http_ok"]:
                    rec["kind"] = "link_error"
                    rec["error"] = f"HTTP {status}"
                elif not body:
                    # 202 + 空体是 EUR-Lex 的典型反爬响应：连上了，但没有内容。
                    rec["kind"] = "empty_content"
                    rec["error"] = f"HTTP {status} with empty body"
                else:
                    rec["kind"] = "ok"
                    rec["ok"] = True
                    rec["content_verified"] = True
                    rec["verified_via"] = "html"
                    rec["hash"] = hashlib.sha256(body).hexdigest()[:16]
                break
        except urllib.error.HTTPError as e:
            rec["status"] = e.code
            if e.code in RETRY_STATUS and attempt < MAX_HTTP_ATTEMPTS:
                rec["error"] = f"HTTP {e.code} (retry {attempt})"
                time.sleep(_retry_delay(attempt, e.headers))
                continue
            rec["kind"] = "link_error"
            rec["error"] = f"HTTP {e.code}"
            break
        except Exception as e:
            rec["kind"] = "net_error"
            rec["error"] = f"{type(e).__name__}: {str(e)[:120]}"
            break

    # API 也失败时退到 HTML；HTML 仍是 429 则单列“官方限流”，不判死链。
    if rec["kind"] == "link_error" and rec["status"] == 429:
        rec["kind"] = "rate_limited"

    rec["elapsed_ms"] = int((time.time() - t0) * 1000)
    return rec


def load_previous():
    """读上一次的最新态（用于 changed 比对）。文件不存在/损坏都当首次。"""
    try:
        with open(LATEST_PATH, encoding="utf-8") as f:
            return json.load(f).get("links", {})
    except Exception:
        return {}


def _rel(path):
    """跨盘符时 relpath 会抛 ValueError，退回绝对路径。"""
    try:
        return os.path.relpath(path, PROJECT)
    except ValueError:
        return path


def _atomic_json(path, payload):
    """先写临时文件再替换，避免 UI 读到写一半的 JSON。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp-" + str(os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _append_jsonl(path, records):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _run_id(started):
    return started.strftime("%Y%m%dT%H%M%S%z") + "-p" + str(os.getpid())


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="法规官方链接时效性核验")
    parser.add_argument("--limit", type=int, default=None, help="只核验前 N 条（冒烟）")
    parser.add_argument("--timeout", type=float, default=TIMEOUT, help="单链接超时秒数")
    parser.add_argument("--workers", type=int, default=WORKERS, help="并发数")
    parser.add_argument("--proxy", default="auto",
                        help="auto（默认）/ direct / 指定代理 URL")
    parser.add_argument("--dry-run", action="store_true",
                        help="只核验并打印，不写日志/最新态")
    parser.add_argument("--slot", default=None,
                        help="指定核验时点（北京时间 YYYY-MM-DD HH:MM[:SS]）")
    return parser.parse_args(argv)


def _parse_slot(value):
    """解析指定核验时点；不带时区按北京时间处理。"""
    text = (value or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=BJT)
        except ValueError:
            continue
    raise SystemExit(
        "--slot 格式应为 'YYYY-MM-DD HH:MM' 或 'YYYY-MM-DD HH:MM:SS'，"
        f"收到：{value!r}")


def main(argv=None):
    args = parse_args(argv)
    timeout = max(float(args.timeout), 1.0)
    workers = max(int(args.workers), 1)

    proxy_decision = net.configure_proxy(args.proxy)

    urls = collect_urls()
    if args.limit:
        urls = urls[:args.limit]
    prev = load_previous()

    actual_started = now_bjt()
    slot_dt = _parse_slot(args.slot) if args.slot else None
    checked_dt = slot_dt or actual_started
    backfilled = slot_dt is not None
    checked_at = checked_dt.strftime("%Y-%m-%d %H:%M:%S")
    run_id = _run_id(checked_dt) + ("-backfill" if backfilled else "")
    print("=" * 66)
    print(f"  时效性核验 · {len(urls)} 个官方链接"
          f"（并发 {workers}，单链超时 {timeout:g}s）")
    print(f"  run_id={run_id}")
    if backfilled:
        print(f"  核验时点：{checked_at}（北京时间）  "
              f"实际运行：{actual_started.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 66)

    records = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(check_one, u, timeout): u for u in urls}
        done = 0
        for fut in as_completed(futs):
            rec = fut.result()
            done += 1
            old = prev.get(rec["url"]) or {}
            rec["changed"] = _changed(old, rec)
            rec["run_id"] = run_id
            rec["ts"] = checked_at
            rec["actual_ts"] = actual_started.strftime("%Y-%m-%d %H:%M:%S")
            rec["backfilled"] = backfilled
            records.append(rec)
            mark = {"ok": "✓", "empty_content": "○", "rate_limited": "⏳",
                    "link_error": "✗", "net_error": "✗"}.get(rec["kind"], "?")
            flag = " 🔶内容有更新" if rec["changed"] else ""
            note = "" if rec["kind"] == "ok" else f" {rec['kind']}"
            print(f"  [{done:>2}/{len(urls)}] {mark} "
                  f"{rec['status'] or '-'} {rec['elapsed_ms']:>5}ms "
                  f"{rec['url'][:64]}{note}{flag}")

    ok_n = sum(1 for r in records if r["content_verified"])
    http_ok_n = sum(1 for r in records if r["http_ok"])
    empty_n = sum(1 for r in records if r["kind"] == "empty_content")
    limited_n = sum(1 for r in records if r["kind"] == "rate_limited")
    link_bad = sum(1 for r in records if r["kind"] == "link_error")
    net_bad = sum(1 for r in records if r["kind"] == "net_error")
    changed_n = sum(1 for r in records if r["changed"])
    finished = now_bjt()

    summary = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "checked_at": checked_at,
        "checked_at_utc": checked_dt.astimezone(timezone.utc).isoformat(timespec="seconds"),
        "actual_checked_at": actual_started.strftime("%Y-%m-%d %H:%M:%S"),
        "actual_checked_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "backfilled": backfilled,
        "slot_at": checked_at if backfilled else "",
        "timezone": "Asia/Shanghai",
        "duration_seconds": round((finished - actual_started).total_seconds(), 1),
        "proxy": proxy_decision,
        "total": len(records),
        "http_ok": http_ok_n,
        "content_verified": ok_n,
        "ok": ok_n,
        "empty_content": empty_n,
        "rate_limited": limited_n,
        "failed": len(records) - ok_n,
        "link_error": link_bad,
        "net_error": net_bad,
        "changed": changed_n,
        "pending_links": [
            {"url": r["url"], "kind": r["kind"], "status": r["status"],
             "error": r["error"]}
            for r in records if r["kind"] != "ok"
        ],
        "links": {r["url"]: r for r in records},
    }

    if not args.dry_run:
        _append_jsonl(LOG_PATH, records)
        _append_jsonl(RUNS_PATH, [{
            k: v for k, v in summary.items() if k != "links"
        }])
        _atomic_json(LATEST_PATH, summary)

    print()
    print(f"  结果：HTTP 可达 {http_ok_n}/{len(records)}；"
          f"实际取得内容 {ok_n}/{len(records)}；空响应 {empty_n} 条；"
          f"官方限流 {limited_n} 条；链接异常 {link_bad} 条；"
          f"本机网络未连通 {net_bad} 条（不判死链）；"
          f"内容较上次有更新 {changed_n} 条")
    if args.dry_run:
        print("  （演练模式，未写日志/最新态）")
    else:
        print(f"  日志追加 → {_rel(LOG_PATH)}")
        print(f"  运行汇总 → {_rel(RUNS_PATH)}")
        print(f"  最新态   → {_rel(LATEST_PATH)}")
    print("=" * 66)
    return 0


if __name__ == "__main__":
    sys.exit(main())
