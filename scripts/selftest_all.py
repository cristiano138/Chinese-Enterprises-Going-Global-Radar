# -*- coding: utf-8 -*-
"""Single offline release gate for all deterministic checks."""
from __future__ import annotations

import os
import subprocess
import sys

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = [
    "scripts/validate_corpus.py",
    "scripts/selftest_m1.py",
    "scripts/selftest_m15.py",
    "scripts/selftest_m2_m3.py",
    "scripts/selftest_m5_m6.py",
    "scripts/selftest_m7.py",
]


def main() -> int:
    failed = []
    for script in SCRIPTS:
        print(f"\n=== {script} ===")
        result = subprocess.run([sys.executable, script], cwd=PROJECT)
        if result.returncode:
            failed.append(script)
    print("\n=== RELEASE GATE ===")
    if failed:
        print("失败数：" + str(len(failed)))
        for item in failed:
            print("FAIL: " + item)
        return 1
    print("M1: PASS")
    print("M1.5: PASS")
    print("M2: PASS")
    print("M3: PASS")
    print("M5/M6: PASS")
    print("M7: PASS")
    print("失败数：0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
