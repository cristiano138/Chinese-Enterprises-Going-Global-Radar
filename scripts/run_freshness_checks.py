# -*- coding: utf-8 -*-
"""时效性检查总入口：链接级 + 官方字段级，一次跑完并留运行汇总。

计划时间：**北京时间每天 19:00、22:00**（见 data/freshness_schedule.json）。

用法：
    python scripts/run_freshness_checks.py                 # 两层都跑
    python scripts/run_freshness_checks.py --limit 5       # 冒烟
    python scripts/run_freshness_checks.py --links-only    # 只跑链接级
    python scripts/run_freshness_checks.py --metadata-only --dry-run
    python scripts/run_freshness_checks.py --proxy direct

调度：
    Windows：scripts/install_freshness_schedule.ps1（推荐）
    GitHub Actions：.github/workflows/freshness-check.yml

输出：
    data/freshness_run_latest.json   最近一次总运行汇总
    data/freshness_run_log.jsonl     每次运行追加一行

退出码：两步都成功 → 0；任一步进程失败 → 1。单条链接/单条法规失败由
各自脚本记录，不会让总入口崩溃（与监控脚本“不把自己跑挂”的原则一致）。
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core import freshness  # noqa: E402
from core import law_store  # noqa: E402

DATA_DIR = os.path.join(ROOT, "data")
RUN_LATEST_PATH = os.path.join(DATA_DIR, "freshness_run_latest.json")
RUN_LOG_PATH = os.path.join(DATA_DIR, "freshness_run_log.jsonl")
LINK_SCRIPT = os.path.join(HERE, "check_freshness.py")
META_SCRIPT = os.path.join(HERE, "check_metadata_freshness.py")
BJT = timezone(timedelta(hours=8))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def now_bjt():
    return datetime.now(BJT)


def _run_id(started):
    return started.strftime("%Y%m%dT%H%M%S%z") + "-p" + str(os.getpid())


def _atomic_json(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp-" + str(os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _append_jsonl(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _reader(pipe, out_queue):
    try:
        for line in iter(pipe.readline, ""):
            out_queue.put(line)
    finally:
        out_queue.put(None)


def _run_step(name, command, timeout_seconds):
    """运行子脚本，实时转发输出；超时则终止，返回结构化结果。"""
    started = now_bjt()
    tail = []
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    print(f"\n[{name}] 开始：{' '.join(command)}", flush=True)

    try:
        proc = subprocess.Popen(
            command, cwd=ROOT, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8",
            errors="replace", bufsize=1, env=env,
        )
    except OSError as exc:
        finished = now_bjt()
        return {
            "name": name, "status": "failed", "command": command,
            "started_at": started.strftime("%Y-%m-%d %H:%M:%S"),
            "finished_at": finished.strftime("%Y-%m-%d %H:%M:%S"),
            "duration_seconds": 0.0, "returncode": None,
            "error": f"{type(exc).__name__}: {exc}", "tail": [],
        }

    lines = queue.Queue()
    threading.Thread(target=_reader, args=(proc.stdout, lines), daemon=True).start()
    deadline = time.monotonic() + max(float(timeout_seconds), 1.0)
    timed_out = False

    while True:
        try:
            line = lines.get(timeout=1.0)
        except queue.Empty:
            line = ""
        if line is None:
            break
        if line:
            text = line.rstrip("\r\n")
            tail.append(text)
            if len(tail) > 120:
                tail = tail[-120:]
            print(f"[{name}] {text}", flush=True)
        if proc.poll() is not None and lines.empty():
            break
        if time.monotonic() > deadline:
            timed_out = True
            proc.kill()
            break

    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()

    finished = now_bjt()
    returncode = proc.returncode
    status = "ok" if returncode == 0 and not timed_out else "failed"
    if timed_out:
        status = "timeout"
    print(f"[{name}] 结束：status={status}, returncode={returncode}", flush=True)
    return {
        "name": name,
        "status": status,
        "command": command,
        "started_at": started.strftime("%Y-%m-%d %H:%M:%S"),
        "finished_at": finished.strftime("%Y-%m-%d %H:%M:%S"),
        "duration_seconds": round((finished - started).total_seconds(), 1),
        "returncode": returncode,
        "error": "timeout" if timed_out else "",
        "tail": tail[-40:],
    }


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="时效性检查总入口")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--links-only", action="store_true", help="只跑链接级检查")
    group.add_argument("--metadata-only", action="store_true", help="只跑官方字段级检查")
    parser.add_argument("--dry-run", action="store_true",
                        help="演练：两层都不写检查日志/最新态/数据库（仍写运行汇总）")
    parser.add_argument("--limit", type=int, default=None,
                        help="两层各只处理前 N 条（冒烟）")
    parser.add_argument("--proxy", default="auto",
                        help="auto（默认）/ direct / 指定代理 URL")
    parser.add_argument("--timeout-minutes", type=float, default=180.0,
                        help="单步超时（分钟），默认 180；86 条字段级检查实测约 60 分钟")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    started = now_bjt()
    run_id = _run_id(started)
    schedule = freshness.load_schedule()
    timeout_seconds = max(float(args.timeout_minutes), 1.0) * 60

    print("=" * 66)
    print("  时效性检查总入口")
    print(f"  run_id={run_id}")
    print(f"  计划时间：北京时间 {' / '.join(schedule['times'])}")
    print("=" * 66)

    steps = []

    if not args.metadata_only:
        cmd = [sys.executable, LINK_SCRIPT, "--proxy", args.proxy]
        if args.dry_run:
            cmd.append("--dry-run")
        if args.limit:
            cmd += ["--limit", str(args.limit)]
        steps.append(_run_step("links", cmd, timeout_seconds))

    if not args.links_only:
        db_path = str(law_store.db_path())
        if not os.path.isfile(db_path):
            print(f"\n[metadata] 跳过：正式库不存在 {db_path}", flush=True)
            steps.append({
                "name": "metadata", "status": "skipped",
                "command": [], "started_at": "", "finished_at": "",
                "duration_seconds": 0.0, "returncode": None,
                "error": f"database not found: {db_path}", "tail": [],
            })
        else:
            cmd = [sys.executable, META_SCRIPT, "--proxy", args.proxy,
                   "--backup", "daily"]
            if args.dry_run:
                cmd.append("--dry-run")
            if args.limit:
                cmd += ["--limit", str(args.limit)]
            steps.append(_run_step("metadata", cmd, timeout_seconds))

    executed = [s for s in steps if s["status"] != "skipped"]
    failed = [s for s in executed if s["status"] != "ok"]
    if not executed:
        status = "skipped"
    elif failed:
        status = "partial" if len(failed) < len(executed) else "failed"
    else:
        status = "ok"

    finished = now_bjt()
    summary = {
        "schema_version": 1,
        "run_id": run_id,
        "checked_at": finished.strftime("%Y-%m-%d %H:%M:%S"),
        "checked_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "timezone": "Asia/Shanghai",
        "duration_seconds": round((finished - started).total_seconds(), 1),
        "status": status,
        "proxy_requested": args.proxy,
        "dry_run": args.dry_run,
        "limit": args.limit,
        "schedule": schedule,
        "next_run": freshness.next_run(finished, schedule).isoformat(timespec="seconds"),
        "steps": steps,
    }
    _append_jsonl(RUN_LOG_PATH, summary)
    _atomic_json(RUN_LATEST_PATH, summary)

    print()
    print("=" * 66)
    for step in steps:
        print(f"  {step['name']:<10} {step['status']:<8} "
              f"{step['duration_seconds']:>7.1f}s"
              + (f"  {step['error']}" if step.get("error") else ""))
    print(f"  总体：{status}")
    print(f"  汇总 → {os.path.relpath(RUN_LATEST_PATH, ROOT)}")
    print("=" * 66)
    return 0 if status in ("ok", "skipped") else 1


if __name__ == "__main__":
    sys.exit(main())
