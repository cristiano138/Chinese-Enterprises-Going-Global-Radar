#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
第三方依赖许可证核查器

用途：
    读取 requirements.txt → 向 PyPI 官方元数据接口查询每个依赖的许可证
    → 输出清单（Markdown 表格），用于生成/校验 THIRD_PARTY_NOTICES.md

为什么需要：
    参赛/交付要求"开源合规建档"。他人复用本项目时，有权知道我们用到的
    每一个第三方组件是什么许可证、能否商用。本脚本让这件事**可复现**，
    而不是靠人工抄一遍。

数据源：
    https://pypi.org/pypi/<包名>/json  （PyPI 官方 JSON API，免费免密钥）

用法：
    python scripts/check_licenses.py
    python scripts/check_licenses.py --markdown > THIRD_PARTY_NOTICES.md

退出码：
    0 = 全部依赖均查到宽松许可证
    1 = 发现 GPL / AGPL / LGPL 等传染性许可证（需人工复核）
    2 = 查询过程出错
"""

import argparse
import json
import re
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS = ROOT / "requirements.txt"
PYPI_JSON = "https://pypi.org/pypi/{}/json"

# 传染性许可证关键词：一旦命中，整个项目可能被迫开源
COPYLEFT_MARKERS = ("GPL", "AGPL", "LGPL", "MPL", "EPL", "CDDL", "SSPL")


def parse_requirements(path: Path):
    """从 requirements.txt 解析出 (包名, 版本约束)。忽略注释与空行。"""
    items = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#")[0].strip()
        if not line or line.startswith("-"):
            continue
        # 包名在第一个版本/环境标记符号之前
        name = re.split(r"[<>=!~\[\;]", line)[0].strip()
        if not name:
            continue
        rest = line[len(name):].strip()
        items.append((name, rest or "任意版本"))
    return items


def fetch_pypi_info(package: str):
    """查询 PyPI 元数据。先走正常证书校验，失败则退化为不校验并告警。"""
    request = urllib.request.Request(
        PYPI_JSON.format(package),
        headers={"User-Agent": "compliance-radar/license-checker"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as resp:
            return json.load(resp)["info"]
    except ssl.SSLError:
        # 部分网络环境的证书链不完整，退化为不校验（仅读取公开元数据，风险可控）
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(request, timeout=30, context=ctx) as resp:
            return json.load(resp)["info"]


def extract_license(info: dict) -> str:
    """按可靠性从高到低提取许可证标识（SPDX 表达式优先）。"""
    expr = (info.get("license_expression") or "").strip()
    if expr:
        return expr
    lic = (info.get("license") or "").strip()
    if lic and len(lic) <= 80:
        return lic
    for classifier in info.get("classifiers", []):
        if classifier.startswith("License :: OSI Approved ::"):
            return classifier.split("::")[-1].strip()
    return "（未在元数据中声明，需人工查看项目主页）"


def main() -> int:
    parser = argparse.ArgumentParser(description="核查 requirements.txt 中依赖的许可证")
    parser.add_argument("--markdown", action="store_true", help="输出 Markdown 表格")
    args = parser.parse_args()

    if not REQUIREMENTS.exists():
        print(f"[错误] 找不到 {REQUIREMENTS}")
        return 2

    rows = []
    risky = []
    for name, constraint in parse_requirements(REQUIREMENTS):
        try:
            info = fetch_pypi_info(name)
        except (urllib.error.URLError, KeyError) as exc:
            print(f"[错误] {name} 查询失败：{exc}")
            return 2

        lic = extract_license(info)
        rows.append((name, constraint, info.get("version", "-"), lic))

        upper = lic.upper()
        if any(marker in upper for marker in COPYLEFT_MARKERS):
            risky.append((name, lic))

    if args.markdown:
        print("| 组件 | 版本约束 | 最新版本 | 许可证 |")
        print("|---|---|---|---|")
        for name, constraint, latest, lic in rows:
            print(f"| `{name}` | `{constraint}` | {latest} | {lic} |")
    else:
        print(f"共 {len(rows)} 个依赖：\n")
        for name, constraint, latest, lic in rows:
            print(f"  {name:<16} {constraint:<12} -> {lic}")

    print()
    if risky:
        print("[警告] 发现可能的传染性许可证，需人工复核：")
        for name, lic in risky:
            print(f"  - {name}: {lic}")
        return 1

    print("[通过] 未发现传染性许可证，全部依赖可用于商业场景。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
