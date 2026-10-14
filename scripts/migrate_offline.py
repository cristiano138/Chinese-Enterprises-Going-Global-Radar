# -*- coding: utf-8 -*-
"""
离线数据迁移 + 重生成脚本（配套 2026-10-14 代码审查修复）

背景：
    本次修复调整了数据管线（新增「现行效力」列、欧盟官方编号归一、美国去重、
    链接检测改非破坏写入并支持限流复测）。重新抓取需要联网；本脚本把仓库已有
    数据迁移到新格式，并按**正确顺序**重跑确定性环节，使 data/ 下全部文件自洽。

执行顺序（与 run_pipeline.bat 一致）：
    0. 从旧完整版取回「法规中文名 / 备注（作用说明）」
    1. eu_regulations.csv：官方编号归一 + 补「现行效力」
    2. us_regulations.csv：按官方编号去重 + 补「现行效力」
    3. merge_corpus.py   → 20 列骨架总表 + 体检报告（去重生效）
    4. check_links.py    → 链接实测 + 报告（非破坏写入，可 --skip-links 跳过）
    5. 回填中文名/备注 → 生成 完整版（「链接可打开」一律以第 4 步实测为准）
    6. make_overview.py / make_todo_eu.py

用法（仓库根目录）：
    python scripts/migrate_offline.py                # 联网，含真实链接实测
    python scripts/migrate_offline.py --skip-links   # 无网时跳过链接实测

⚠️ 一次性迁移脚本；之后直接跑 run_pipeline.bat 即可。
"""

import csv
import importlib.util
import os
import subprocess
import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
DATA = os.path.join(PROJECT, "data")
sys.path.insert(0, HERE)

SRC_COLS = ["类目", "机构", "法规中文名", "官方标题（英文）", "官方编号", "CELEX号",
            "ELI标识", "官方链接", "来源类型", "现行效力", "生效日期", "最新修订日期",
            "链接可打开", "编号核对", "是否官方来源", "核对状态", "核对人", "核对日期", "备注／问题"]

TYPE_WORD = {"R": "Regulation", "L": "Directive", "D": "Decision"}


def official_number(celex):
    """CELEX → 官方可读编号（与 fetch_eu.official_number 规则一致）。"""
    if len(celex) < 7 or not celex.startswith("3"):
        return celex
    year, etype, num = celex[1:5], celex[5], celex[6:].lstrip("0") or "0"
    w = TYPE_WORD.get(etype)
    if not w:
        return celex
    return f"Regulation (EU) {year}/{num}" if w == "Regulation" else f"{w} {year}/{num}"


def eu_inforce(row):
    txt = row.get("备注／问题", "") or ""
    if "现行有效：否" in txt:
        return "已废止"
    if "现行有效：是" in txt:
        return "现行有效"
    if (row.get("来源类型", "") or "").startswith("官方（待确认"):
        return "待确认"
    return ""


def read_csv(path):
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows, cols):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    skip_links = "--skip-links" in sys.argv
    print("=" * 70)
    print("  离线数据迁移 + 重生成（对齐 2026-10-14 修复后的格式）")
    print("=" * 70)

    # ── 0. 从旧完整版取回「中文名 / 备注」 ──────────────────────
    old_complete = os.path.join(DATA, "语料核对表_完整版.csv")
    enrich = {}
    if os.path.exists(old_complete):
        for r in read_csv(old_complete):
            k = (r.get("机构", ""), (r.get("CELEX号") or r.get("官方编号") or "").strip())
            enrich.setdefault(k, {
                "法规中文名": r.get("法规中文名", ""),
                "备注／问题": r.get("备注／问题", ""),
            })
        print(f"  读入旧完整版 {len(enrich)} 个唯一键（回填中文名/备注）")

    # ── 1. 规范欧盟文件 ─────────────────────────────────────────
    eu_path = os.path.join(DATA, "eu_regulations.csv")
    eu_rows = read_csv(eu_path)
    for r in eu_rows:
        r["官方编号"] = official_number((r.get("CELEX号") or "").strip()) or r.get("官方编号", "")
        r["现行效力"] = eu_inforce(r)
    write_csv(eu_path, eu_rows, SRC_COLS)
    print(f"  [1] eu_regulations.csv：{len(eu_rows)} 条，官方编号已归一、补现行效力")

    # ── 2. 美国文件去重 + 补列 ──────────────────────────────────
    us_path = os.path.join(DATA, "us_regulations.csv")
    us_rows = read_csv(us_path)
    seen, us_dedup = set(), []
    for r in us_rows:
        k = (r.get("官方编号") or "").strip()
        if k in seen:
            continue
        seen.add(k)
        r["现行效力"] = "现行有效（持续修订）"
        us_dedup.append(r)
    write_csv(us_path, us_dedup, SRC_COLS)
    print(f"  [2] us_regulations.csv：{len(us_rows)} → {len(us_dedup)} 条（去重 {len(us_rows) - len(us_dedup)}）")

    # ── 3. 合并 ────────────────────────────────────────────────
    print()
    load_module("merge_corpus", "merge_corpus.py").main()

    # ── 4. 链接实测（可选）─────────────────────────────────────
    if skip_links:
        print("\n  [4] 跳过链接实测（--skip-links）\n")
    else:
        print("\n  [4] 链接实测（非破坏写入 + 限流复测）...\n")
        subprocess.run([sys.executable, os.path.join(HERE, "check_links.py"), "--force"],
                       cwd=PROJECT, check=False)

    # ── 5. 生成完整版（链接结论一律取骨架表现值）────────────────
    skeleton = os.path.join(DATA, "语料核对表_骨架总表.csv")
    rows = read_csv(skeleton)
    cols = list(rows[0].keys()) if rows else SRC_COLS + ["监管机构"]
    filled = 0
    for r in rows:
        k = (r.get("机构", ""), (r.get("CELEX号") or r.get("官方编号") or "").strip())
        if k in enrich:
            e = enrich[k]
            if e["法规中文名"]:
                r["法规中文名"] = e["法规中文名"]
            if e["备注／问题"]:
                r["备注／问题"] = e["备注／问题"]
            filled += 1
    complete = os.path.join(DATA, "语料核对表_完整版.csv")
    write_csv(complete, rows, cols)
    print()
    print(f"  [5] 完整版：{len(rows)} 条 × {len(cols)} 列，回填 {filled} 条")

    # ── 6. 总览 / 待补清单 ─────────────────────────────────────
    load_module("make_overview", "make_overview.py").main()
    load_module("make_todo_eu", "make_todo_eu.py").main()

    print()
    print("  迁移完成。data/ 下 全部文件已按 修复后 的口径对齐。")
    print("=" * 70)


if __name__ == "__main__":
    main()
