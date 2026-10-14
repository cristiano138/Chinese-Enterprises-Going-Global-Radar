# -*- coding: utf-8 -*-
"""
合并欧盟 + 美国两份骨架数据 → 一张「语料核对表」形状的总表。

用途：
    抓取脚本（fetch_eu.py / fetch_us.py）各自产出中间文件，
    本脚本把它们统一成**能直接粘进语料核对表**的格式，并做完整性体检。

输入：
    data/eu_regulations.csv
    data/us_regulations.csv

输出：
    data/语料核对表_骨架总表.csv   （18 列，与语料核对表列名对齐）
    data/骨架体检报告.txt          （缺项统计 + 待人工核对的清单）

用法：
    python scripts/merge_corpus.py
"""

import csv
import os
import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
DATA = os.path.join(PROJECT, "data")

# 语料核对表的标准列（18 列）
COLS = ["类目", "机构", "法规中文名", "官方标题（英文）", "官方编号", "CELEX号",
        "ELI标识", "官方链接", "来源类型", "生效日期", "最新修订日期",
        "链接可打开", "编号核对", "是否官方来源", "核对状态", "核对人", "核对日期", "备注／问题"]

# ── 相关性筛选：把与「跨境消费品出海合规」关系太弱的条目剔除 ──────────
# 理由：eCFR 是按 Part 组织的，同一 Title 里混着大量与五个品类无关的法规
#      （割草机、火柴、车库门……），这些对出海卖家没有参考价值。
# 做法：命中即剔除（宁可少几条，也不要凑数）。
IRRELEVANT_KEYWORDS = [
    "lawn mower", "matchbook", "cigarette lighter", "swimming pool",
    "cellulose insulation", "citizens band", "garage door", "bicycle helmet",
    "architectural glazing", "multi-purpose lighter", "candle",
    "refrigerator", "drywall", "extension cord", "hair dryer",
]

# 保留白名单：即使命中了上面的词，若明确与品类相关也留（当前为空，留扩展位）
KEEP_WHITELIST = []


def is_relevant(row):
    """判断一条法规是否与项目品类相关。返回 (是否保留, 原因)。"""
    title = (row.get("官方标题（英文）", "") or "").lower()
    cite = (row.get("官方编号", "") or "")

    for w in KEEP_WHITELIST:
        if w in cite:
            return True, "白名单保留"

    for k in IRRELEVANT_KEYWORDS:
        if k in title:
            return False, f"与品类无关（命中'{k}'）"

    return True, ""


def load(path, org):
    if not os.path.exists(path):
        print(f"  ⚠️ 找不到 {path}，跳过")
        return []
    with open(path, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    out = []
    for r in rows:
        rr = {c: (r.get(c, "") or "").strip() for c in COLS}
        rr["机构"] = org
        out.append(rr)
    return out


def main():
    print("=" * 66)
    print("  骨架数据合并 + 体检")
    print("=" * 66)
    print()

    eu = load(os.path.join(DATA, "eu_regulations.csv"), "EU")
    us = load(os.path.join(DATA, "us_regulations.csv"), "US")

    # ── 相关性筛选 ──────────────────────────────────────
    kept = []
    dropped = []
    for r in eu + us:
        ok, why = is_relevant(r)
        (kept if ok else dropped).append(r if ok else (r, why))

    allrows = kept
    print(f"  欧盟：{len(eu)} 条")
    print(f"  美国：{len(us)} 条")
    print(f"  相关性筛选：剔除 {len(dropped)} 条，保留 {len(allrows)} 条")
    if dropped:
        print("    已剔除的：")
        for r, why in dropped:
            print(f"      - {r['机构']} {r['官方编号']:<22} {why}")
    print()

    out_csv = os.path.join(DATA, "语料核对表_骨架总表.csv")
    with open(out_csv, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(allrows)
    print(f"  已保存：{out_csv}")
    print()

    # ── 体检 ────────────────────────────────────────────
    lines = []
    lines.append("=" * 66)
    lines.append("  骨架数据体检报告")
    lines.append("=" * 66)
    lines.append("")
    lines.append(f"总数：{len(allrows)} 条（欧盟 {len(eu)} + 美国 {len(us)}）")
    lines.append("")

    def stat(field, label):
        missing = [r for r in allrows if not r[field]]
        lines.append(f"【{label}】有值 {len(allrows) - len(missing)} / {len(allrows)}")
        if missing:
            for r in missing:
                key = r["CELEX号"] or r["官方编号"]
                lines.append(f"    缺 → {r['机构']} {key}  ({r['类目']})")
        lines.append("")
        return missing

    stat("官方标题（英文）", "官方标题（英文）")
    stat("官方编号", "官方编号")
    stat("官方链接", "官方链接")

    # ELI 是欧盟专属标识，美国法规没有是正常的，不算缺项
    eu_rows = [r for r in allrows if r["机构"] == "EU"]
    eu_no_eli = [r for r in eu_rows if not r["ELI标识"]]
    lines.append(f"【ELI 标识】欧盟 {len(eu_rows) - len(eu_no_eli)} / {len(eu_rows)}"
                 "（注：ELI 是欧盟专属标识，美国法规没有是正常的）")
    if eu_no_eli:
        for r in eu_no_eli:
            lines.append(f"    缺 → EU {r['CELEX号']}  ({r['类目']})")
    lines.append("")

    # 链接可打开 / 核对状态 的默认值提示
    lines.append("【下一步人工核对】")
    lines.append(f"    需逐一打开验证的链接：{len(allrows)} 个")
    lines.append("    核对重点：链接能否打开、编号是否与页面一致、是否仍现行有效")
    lines.append("")
    lines.append("=" * 66)

    out_txt = os.path.join(DATA, "骨架体检报告.txt")
    with open(out_txt, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n".join(lines))
    print(f"\n  体检报告已保存：{out_txt}")
    print("=" * 66)


if __name__ == "__main__":
    main()
