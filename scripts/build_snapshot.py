# -*- coding: utf-8 -*-
"""Build the release snapshot consumed by the application."""
from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(PROJECT, "data")
SOURCE = os.path.join(DATA, "语料核对表_完整版.csv")
SNAPSHOT = os.path.join(DATA, "snapshot.json")
REPORT = os.path.join(DATA, "data_quality_report.json")


def git_commit():
    try:
        return subprocess.check_output(["git", "-C", PROJECT, "rev-parse", "--short", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return "unknown"


def main() -> int:
    validator = os.path.join(os.path.dirname(__file__), "validate_corpus.py")
    if subprocess.run([sys.executable, validator], cwd=PROJECT).returncode:
        return 1
    with open(SOURCE, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    with open(REPORT, encoding="utf-8") as f:
        quality = json.load(f)
    now = datetime.now(timezone(timedelta(hours=8)))
    labels = {"EU": "欧盟", "US": "美国"}
    snapshot = {
        "snapshot_version": "v1.1",
        "generated_at": now.isoformat(timespec="seconds"),
        "data_cutoff": max((r.get("核对日期", "") for r in rows), default=""),
        "git_commit": git_commit(),
        "total_rows": quality["total_rows"],
        "unique_keys": quality["unique_keys"],
        "duplicate_keys": quality["duplicate_keys"],
        "markets": {labels.get(k, k): v for k, v in quality["markets"].items()},
        "status_distribution": quality["status_distribution"],
        "source_file": os.path.relpath(SOURCE, PROJECT),
    }
    with open(SNAPSHOT, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    print(json.dumps(snapshot, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
