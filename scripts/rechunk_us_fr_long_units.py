# -*- coding: utf-8 -*-
"""
US 长文档补切片（scripts/rechunk_us_fr_long_units.py）

背景：
    us_fr（Federal Register 最终规则）文档中位数长度 6972 字符，大多数
    能直接喂给下游 LLM，但有长尾——约 60 条超过 10 万字符（最长 180 万），
    现有 units 表把它们整篇塞成一个 unit_type='rule' 的粗粒度块，路由层
    拿到这种块无法喂给 LLM。

实测结论（按讨论结论，只切 PART 级，不再往 § 细切）：
    1. FR 最终规则文档结构固定两段：
       - 陈述性前言（preamble）：背景说明、评论回复摘要，占绝大部分篇幅，
         不含可执行的法规条文本身，但对理解"为什么这么改"仍有参考价值
       - 修订指令正文：固定以大写全词 "PART N—标题" 开头（N=CFR Part号），
         逐个列出这次修订涉及的每个 Part，这才是真正的法规条文修改内容
    2. "PART N—标题" 这个大写全词格式实测跨机构通用（FDA/FCC/CPSC 三个
       机构样本验证一致），且不会在目录区重复出现（目录区列的是具体
       § 条款号，不会把 "PART N" 大写格式本身列进目录）——不需要像
       EU 罗马数字标题那样做"去重取第二次出现"的处理。
    3. 60 条长文档中 59 条能用这个标记切开；1 条（US-FR:2018-18692）
       完全没有 PART 标记——实测确认它是行政性拍卖程序公告，不是
       修订规则文件，本来就不该拆分，保留整篇是正确处理。
    4. 切完后仍有 4 条的某个单独 PART 块超过 10 万字符（该 Part 本身
       修订内容confirmed特别长，如 US-FR:2015-21920 的 PART 117 达到
       15.9 万字符）——这是已知、按范围说明接受的局限，不在本次任务
       范围内处理（范围边界：只切 PART 级）。

输出的新 units 行：
    unit_type='part_amendment'，heading="PART N — 标题"
    locator 沿用原 document 的 locator 并加 "#part-N" 后缀（可追溯）
    preamble 整体保留一行，unit_type='preamble'，
    heading="[背景说明，非法规正文] 原文档标题的 SUMMARY/SUPPLEMENTARY INFORMATION"
    （标注"背景说明，非法规正文"是给路由LLM看的重要程度提示，不是新字段，
     跟 EU 侧 heading 的标注风格一致）

原有的整篇 unit_type='rule' 粗粒度行保留不删——双层存在，粗粒度兜底。

用法：
    python scripts/rechunk_us_fr_long_units.py --dry-run --limit 3   # 冒烟
    python scripts/rechunk_us_fr_long_units.py --dry-run              # 全量演练
    python scripts/rechunk_us_fr_long_units.py                         # 正式写库
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
DB_PATH = os.path.join(PROJECT, "sqlite", "regulations.sqlite3")

LONG_THRESHOLD = 100000  # 只处理超过这个长度的 us_fr 整篇块

PART_RE = re.compile(r"(?m)^[ \t]*PART[ \t]+(\d+[A-Za-z]?)[ \t]*[^\n\d]*")


def extract_part_title(line_start_text):
    """从 'PART N—TITLE \n' 这一行提取 '标题' 部分。em-dash 在不同抽取
    环境下可能已损坏成乱码字节，不依赖具体 dash 字符，只取冒号/破折号/
    换行之前能提取的第一行非空文本。
    """
    first_line = line_start_text.split("\n", 1)[0]
    # 去掉开头的 "PART N" 标签本身，剩下的按非字母数字符号切一刀
    m = re.match(r"^[ \t]*PART[ \t]+\d+[A-Za-z]?[ \t]*(.*)$", first_line)
    tail = m.group(1).strip() if m else ""
    # 去掉开头残留的分隔符字符（破折号/乱码字节）
    tail = re.sub(r"^[^A-Za-z0-9]+", "", tail).strip()
    return tail


def split_document(body):
    """返回 (preamble_text_or_None, [(part_number, heading, text), ...])。

    没有 PART 标记的文档返回 (None, [])，由上层判断整篇保留不动。
    """
    matches = list(PART_RE.finditer(body))
    if not matches:
        return None, []

    preamble = body[: matches[0].start()].strip()
    parts = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        part_number = m.group(1)
        chunk_text = body[start:end]
        title = extract_part_title(chunk_text)
        heading = f"PART {part_number} — {title}" if title else f"PART {part_number}"
        parts.append((part_number, heading, chunk_text.strip()))

    return preamble, parts


def preamble_heading(original_heading):
    base = (original_heading or "SUPPLEMENTARY INFORMATION").strip()
    return f"[背景说明，非法规正文，优先级低于PART正文] {base}"


def load_long_units(con, limit=None):
    cur = con.cursor()
    cur.execute(
        """SELECT u.document_id, u.heading, u.locator, u.body
           FROM units u JOIN documents d ON u.document_id = d.id
           WHERE d.kind = 'us_fr' AND u.unit_type = 'rule'
             AND LENGTH(u.body) > ?""",
        (LONG_THRESHOLD,),
    )
    rows = cur.fetchall()
    if limit:
        rows = rows[:limit]
    return rows


def rechunk_one(con, document_id, original_heading, original_locator, body, dry_run):
    """返回 (new_rows_count, skipped_reason_or_None)。"""
    preamble, parts = split_document(body)
    if not parts:
        return 0, "无 PART 标记（可能是非修订类文件，整篇保留）"

    cur = con.cursor()
    # 新增行的 ordinal 从比当前文档最大 ordinal 更大的位置开始，避免跟
    # 已有整篇 rule 行（ordinal=0）冲突
    cur.execute(
        "SELECT COALESCE(MAX(ordinal), -1) FROM units WHERE document_id=?",
        (document_id,),
    )
    next_ordinal = cur.fetchone()[0] + 1

    new_rows = []
    if preamble:
        new_rows.append(
            (
                document_id,
                next_ordinal,
                f"{original_locator}#preamble",
                "preamble",
                preamble_heading(original_heading),
                preamble,
                None,
            )
        )
        next_ordinal += 1

    for part_number, heading, text in parts:
        new_rows.append(
            (
                document_id,
                next_ordinal,
                f"{original_locator}#part-{part_number}",
                "part_amendment",
                heading,
                text,
                None,
            )
        )
        next_ordinal += 1

    if not dry_run:
        cur.executemany(
            """INSERT INTO units
               (document_id, ordinal, locator, unit_type, heading, body, source_fragment)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            new_rows,
        )

    return len(new_rows), None


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

    con = sqlite3.connect(DB_PATH)
    con.text_factory = str

    rows = load_long_units(con, limit)

    print("=" * 62)
    print(f"  US 长文档补切片（PART级）{'（演练模式）' if dry_run else ''}")
    print("=" * 62)
    print(f"  待处理：{len(rows)} 条（us_fr 整篇块 > {LONG_THRESHOLD} 字符）")
    print()

    total_new_rows = 0
    skipped = []
    for document_id, heading, locator, body in rows:
        n, reason = rechunk_one(con, document_id, heading, locator, body, dry_run)
        if reason:
            skipped.append((document_id, reason))
            print(f"  [{document_id}] 跳过：{reason}")
        else:
            total_new_rows += n
            print(f"  [{document_id}] 切出 {n} 个新块")

    if not dry_run:
        con.commit()

    print()
    print(f"  处理完成：{len(rows)} 条文档，共新增 {total_new_rows} 个切片块；跳过 {len(skipped)} 条")
    if dry_run:
        print("  （演练模式，未写库）")
    print("=" * 62)

    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
