# -*- coding: utf-8 -*-
"""
时效性监控 · 最小可行版（scripts/check_freshness.py）

团队新思路（2026-10-16）的可行性收敛：
    原思路：法规**全文落库** + 每天定时查时效 + 查询动作写日志。
    本期收敛（4 天工期，红线不破）：
      · 监控对象 = 语料表全部官方链接（元数据级：HTTP 状态 /
        Last-Modified / 内容哈希），**不做全文解析入库**
        —— 全文落库与每日定时已写入 docs/时效性监控.md 作为后续路线；
      · 日志 = data/freshness_log.jsonl：每次核验每链接追加一行，
        可审计、可回放（对应「查询动作写日志」）；
      · 最新态 = data/freshness_latest.json：供 Web 页脚展示
        「最近核验时间 · 可访问 / 异常数」（用户可见的时效性证据）；
      · 「变化」判定 = 与上一次核验的内容哈希比对（hash 变了 → changed）。

用法：
    python scripts/check_freshness.py            # 核验全部链接（约 1~2 分钟）
    python scripts/check_freshness.py --limit 5  # 只验前 5 条（冒烟）

定时（二选一，本期不强绑）：
    Windows：schtasks /create /tn "ComplianceRadar-Freshness" ^
             /tr "python <仓库>\\scripts\\check_freshness.py" /sc daily /st 09:00
    Linux：  0 9 * * * cd <仓库> && python scripts/check_freshness.py

退出码：永远 0 —— 监控脚本不许把自己跑挂（单个链接失败只记录，不中断）。
"""

import hashlib
import json
import os
import sys
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)

from core import corpus  # noqa: E402

LOG_PATH = os.path.join(PROJECT, "data", "freshness_log.jsonl")
LATEST_PATH = os.path.join(PROJECT, "data", "freshness_latest.json")

TIMEOUT = 15          # 单链接超时（秒）
WORKERS = 8           # 并发数
MAX_READ = 128 * 1024  # 只读前 128KB 算哈希（元数据级，不抓全文）
BJT = timezone(timedelta(hours=8))

_UA = ("Mozilla/5.0 (compatible; ComplianceRadar-Freshness/1.0; "
       "+https://github.com/cristiano138/Chinese-Enterprises-Going-Global-Radar)")


def collect_urls():
    """从语料表收集去重后的官方链接清单（官方链接 + ELI 链接）。"""
    rows = corpus.load_corpus()
    urls = []
    seen = set()
    for r in rows:
        for key in ("官方链接", "ELI链接"):
            u = (r.get(key) or "").strip()
            if u.startswith("http") and u not in seen:
                seen.add(u)
                urls.append(u)
    return urls


def check_one(url):
    """核验单个链接。返回记录 dict；任何异常都落进记录，不抛出。

    kind 三分（诚实口径，演示不说谎）：
      ok         —— 连上了且 HTTP 2xx/3xx
      link_error —— 连上了但 HTTP 4xx/5xx（链接本身可能失效，该人工复核）
      net_error  —— 本机网络层面没连上（SSL 握手超时等）——
                   只说明「本机 → 目标站」不通，**不判死链**
                   （实测：国内直连 ecfr.gov 全部 SSL 握手超时，浏览器走代理则正常）
    """
    ts = datetime.now(BJT).strftime("%Y-%m-%d %H:%M:%S")
    rec = {"ts": ts, "url": url, "ok": False, "kind": "net_error",
           "status": None, "last_modified": "", "hash": "",
           "elapsed_ms": 0, "error": ""}
    t0 = time.time()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            rec["status"] = resp.status
            rec["last_modified"] = resp.headers.get("Last-Modified", "")
            body = resp.read(MAX_READ)
            rec["hash"] = hashlib.sha256(body).hexdigest()[:16]
            rec["ok"] = 200 <= resp.status < 400
            rec["kind"] = "ok" if rec["ok"] else "link_error"
    except urllib.error.HTTPError as e:
        rec["status"] = e.code
        rec["kind"] = "link_error"
        rec["error"] = f"HTTP {e.code}"
    except Exception as e:
        rec["error"] = f"{type(e).__name__}: {str(e)[:120]}"
    rec["elapsed_ms"] = int((time.time() - t0) * 1000)
    return rec


def load_previous():
    """读上一次的最新态（用于 changed 比对）。文件不存在/损坏都当首次。"""
    try:
        with open(LATEST_PATH, encoding="utf-8") as f:
            return json.load(f).get("links", {})
    except Exception:
        return {}


def main():
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    urls = collect_urls()
    if limit:
        urls = urls[:limit]
    prev = load_previous()

    print("=" * 66)
    print(f"  时效性核验 · {len(urls)} 个官方链接（并发 {WORKERS}，单链超时 {TIMEOUT}s）")
    print("=" * 66)

    records = []
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futs = {pool.submit(check_one, u): u for u in urls}
        done = 0
        for fut in as_completed(futs):
            rec = fut.result()
            done += 1
            # 与上次哈希比对 → 内容是否变化
            old = prev.get(rec["url"]) or {}
            rec["changed"] = bool(old.get("hash") and rec["hash"]
                                  and old["hash"] != rec["hash"])
            records.append(rec)
            mark = "✓" if rec["ok"] else "✗"
            flag = " 🔶内容有更新" if rec["changed"] else ""
            print(f"  [{done:>2}/{len(urls)}] {mark} "
                  f"{rec['status'] or '-'} {rec['elapsed_ms']:>5}ms "
                  f"{rec['url'][:72]}{flag}")

    # 追加日志（每链接一行，可审计回放）
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # 写最新态（UI 读这份）
    ok_n = sum(1 for r in records if r["ok"])
    link_bad = sum(1 for r in records if r.get("kind") == "link_error")
    net_bad = sum(1 for r in records if r.get("kind") == "net_error")
    changed_n = sum(1 for r in records if r.get("changed"))
    latest = {
        "checked_at": datetime.now(BJT).strftime("%Y-%m-%d %H:%M:%S"),
        "total": len(records),
        "ok": ok_n,
        "failed": len(records) - ok_n,
        "link_error": link_bad,
        "net_error": net_bad,
        "changed": changed_n,
        "links": {r["url"]: r for r in records},
    }
    with open(LATEST_PATH, "w", encoding="utf-8") as f:
        json.dump(latest, f, ensure_ascii=False, indent=1)

    print()
    print(f"  结果：{ok_n}/{len(records)} 可访问；"
          f"链接异常 {link_bad} 条；本机网络未连通 {net_bad} 条（不判死链）；"
          f"内容较上次有更新 {changed_n} 条")
    print(f"  日志追加 → {os.path.relpath(LOG_PATH, PROJECT)}")
    print(f"  最新态   → {os.path.relpath(LATEST_PATH, PROJECT)}")
    print("=" * 66)
    return 0


if __name__ == "__main__":
    sys.exit(main())
