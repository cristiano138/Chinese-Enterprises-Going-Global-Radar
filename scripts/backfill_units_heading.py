# -*- coding: utf-8 -*-
"""
补齐 units 表 EU 侧 heading 字段（scripts/backfill_units_heading.py）

背景：
    路由LLM 要靠"目录树"（units 表的 ordinal/heading/locator 列表）决定
    拿哪些切片给下游，但实测发现 EU 侧（eu_original/eu_amendment/
    eu_consolidated/eu_corrigendum）的 article/annex 类型 heading 列
    100% 为空——不是遗漏抓取，是当时的抽取脚本没填这个字段，
    标题信息其实已经在 body 开头，可以程序化推导，不需要重新抓取。

规律（实测统计 5437 条 EU article/annex，覆盖 100%）：
    body 开头固定是："Article N \n [可选：标题行] \n 正文..."
    或 "ANNEX N \n [可选：标题行] \n 正文..."
    78.6% 的条款有独立标题行（如 "Article 3 \n Definitions \n ..."），
    剩余 21.4% 没有标题行，Article/Annex 后直接接正文——这部分条款
    本身就没有标题，heading 退回成纯编号标签（如 "Article 3"），
    不凑造不存在的标题。

用法：
    python scripts/backfill_units_heading.py --dry-run --limit 20   # 冒烟
    python scripts/backfill_units_heading.py --dry-run               # 全量演练
    python scripts/backfill_units_heading.py                          # 正式写库
"""

import os
import re
import sqlite3
import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
GO_RADAR_ROOT = os.path.dirname(HERE)
PROJECT = os.path.dirname(GO_RADAR_ROOT)
sys.path.insert(0, GO_RADAR_ROOT)
from core import law_store
DB_PATH = str(law_store.db_path())

TARGET_KINDS = ("eu_original", "eu_amendment", "eu_consolidated", "eu_corrigendum")
TARGET_UNIT_TYPES = ("article", "annex")

LABEL_RE = re.compile(r"^(Article\s*\d+[a-z]?|ANNEX\s*[IVXLCM\d]*)", re.IGNORECASE)
NUMBERED_PARA_RE = re.compile(r"^\d+\.")


def extract_heading(body):
    """从 body 开头推导 heading。返回 None 表示连标签都提取不出来（异常数据）。"""
    body2 = (body or "").replace("\xa0", " ")
    lines = [l.strip() for l in body2.split("\n") if l.strip()]
    if not lines:
        return None

    m = LABEL_RE.match(lines[0])
    label = m.group(1).strip() if m else None
    if label is None:
        return None  # 第一行不符合已知标签格式，不猜，交人工看

    if len(lines) >= 2:
        candidate = lines[1]
        # 标题行特征：短（<100字符），不是编号段落（"1. ..."）
        if len(candidate) < 100 and not NUMBERED_PARA_RE.match(candidate):
            return f"{label} — {candidate}"
    return label


def _require_db():
    if os.path.isfile(DB_PATH):
        return True
    print("× 未找到离线语料库：" + DB_PATH)
    print("  本脚本需要 units 表所在的 sqlite 库；该库不随 Git 分发。")
    print("  请从项目离线数据包放入 sqlite/regulations.sqlite3 后重跑。")
    return False


def main():
    if not _require_db():
        return 1
    dry_run = "--dry-run" in sys.argv
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    con = law_store.connect(DB_PATH, writable=not dry_run)
    if not dry_run:
        print('写前备份：' + law_store.backup(con, DB_PATH))
    cur = con.cursor()

    placeholders_kind = ",".join("?" for _ in TARGET_KINDS)
    placeholders_type = ",".join("?" for _ in TARGET_UNIT_TYPES)
    cur.execute(
        f"""SELECT u.document_id, u.ordinal, u.body FROM units u
            JOIN documents d ON u.document_id = d.id
            WHERE d.kind IN ({placeholders_kind})
              AND u.unit_type IN ({placeholders_type})
              AND (u.heading IS NULL OR TRIM(u.heading) = '')""",
        TARGET_KINDS + TARGET_UNIT_TYPES,
    )
    rows = cur.fetchall()
    if limit:
        rows = rows[:limit]

    print("=" * 62)
    print(f"  units.heading 补齐（EU侧 article/annex）{'（演练模式）' if dry_run else ''}")
    print("=" * 62)
    print(f"  待处理：{len(rows)} 条")
    print()

    filled = 0
    unresolved = []
    for document_id, ordinal, body in rows:
        heading = extract_heading(body)
        if heading is None:
            unresolved.append((document_id, ordinal))
            continue
        if dry_run:
            print(f"  [{document_id}#{ordinal}] -> {heading[:80]}")
        else:
            cur.execute(
                "UPDATE units SET heading=? WHERE document_id=? AND ordinal=?",
                (heading, document_id, ordinal),
            )
        filled += 1

    if not dry_run:
        con.commit()

    print()
    print(f"  成功补齐：{filled} / {len(rows)}")
    if unresolved:
        print(f"  无法提取标签（交人工看）：{len(unresolved)} 条")
        for doc_id, ordinal in unresolved[:10]:
            print(f"    {doc_id}#{ordinal}")
    if dry_run:
        print("  （演练模式，未写库）")
    print("=" * 62)

    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
