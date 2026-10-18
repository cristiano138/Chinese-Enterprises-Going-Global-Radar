#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""修复 PDF 抽取导致的 Ð 乱码（破折号/项目符号/连接号），并同步重建 FTS 索引。

规则（仅作用于 documents.full_text 与 units.body）：
  1. 行首 "ÐwordÐ"（同一单词被两个 Ð 包裹） -> —word—（成对破折号）
  2. 数字Ð数字 -> –（连接号，如 5.15Ð5.35）
  3. 其余行首 Ð -> "• "（项目符号）
  4. 其余 Ð -> —（破折号）

排除 EU-DOC:31994L0011：其原始 HTML 本身希腊文已损坏，Ð 属于源文件问题，不擅自改。
原始文件字节保存在 blobs 中，未做任何改动。
"""
import sqlite3, re, sys, json

DB = sys.argv[1] if len(sys.argv) > 1 else 'sqlite/regulations.sqlite3'
SKIP_DOC = 'EU-DOC:31994L0011'

def repair_text(s):
    stats = {'paired': 0, 'en_dash': 0, 'bullet': 0, 'em_dash': 0}
    def _paired(m):
        stats['paired'] += 1
        return f'—{m.group(1)}—'
    s = re.sub(r'(?m)^Ð([A-Za-z]+)Ð', _paired, s)
    def _en(m):
        stats['en_dash'] += 1
        return '–'
    s = re.sub(r'(?<=\d)Ð(?=\d)', _en, s)
    def _bullet(m):
        stats['bullet'] += 1
        return '• '
    s = re.sub(r'(?m)^Ð', _bullet, s)
    stats['em_dash'] = s.count('Ð')
    s = s.replace('Ð', '—')
    return s, stats

con = sqlite3.connect(DB)
cur = con.cursor()

total = {'paired': 0, 'en_dash': 0, 'bullet': 0, 'em_dash': 0}
changed_docs = []
changed_units = 0

cur.execute('BEGIN IMMEDIATE')

# 1) documents.full_text
rows = cur.execute(
    "SELECT id, full_text FROM documents WHERE full_text LIKE '%Ð%' AND id<>?", (SKIP_DOC,)
).fetchall()
for did, text in rows:
    new, st = repair_text(text)
    if new != text:
        cur.execute('UPDATE documents SET full_text=? WHERE id=?', (new, did))
        changed_docs.append(did)
        for k in total: total[k] += st[k]

# 2) units.body
rows = cur.execute(
    "SELECT rowid, body FROM units WHERE body LIKE '%Ð%' AND document_id<>?", (SKIP_DOC,)
).fetchall()
for rid, text in rows:
    new, st = repair_text(text)
    if new != text:
        cur.execute('UPDATE units SET body=? WHERE rowid=?', (new, rid))
        changed_units += 1
        for k in total: total[k] += st[k]

# 3) 同步 FTS（documents_fts 为独立内容的 FTS5 表）
fts_updated = 0
for did in changed_docs:
    r = cur.execute('SELECT rowid FROM documents_fts WHERE document_id=?', (did,)).fetchone()
    if r:
        cur.execute('DELETE FROM documents_fts WHERE rowid=?', (r[0],))
        title, body = cur.execute('SELECT official_title, full_text FROM documents WHERE id=?', (did,)).fetchone()
        cur.execute('INSERT INTO documents_fts(document_id,title,body) VALUES(?,?,?)', (did, title, body))
        fts_updated += 1

con.commit()

remaining = cur.execute(
    "SELECT COUNT(*) FROM documents WHERE id<>? AND full_text LIKE '%Ð%'", (SKIP_DOC,)
).fetchone()[0]
remaining_u = cur.execute(
    "SELECT COUNT(*) FROM units WHERE document_id<>? AND body LIKE '%Ð%'", (SKIP_DOC,)
).fetchone()[0]

print(json.dumps({
    'changed_documents': len(changed_docs),
    'changed_units': changed_units,
    'replacements': total,
    'fts_rows_updated': fts_updated,
    'remaining_eth_docs': remaining,
    'remaining_eth_units': remaining_u,
    'skipped_document': SKIP_DOC,
}, ensure_ascii=False, indent=2))
con.close()
