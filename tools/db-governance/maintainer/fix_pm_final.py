#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""最终精确修正：
1) 恢复被 section 正则误伤的合法容差 22.86±0.64（4 个 eCFR 快照）；
2) 修复 3 处跨行/跨空白的确定伪影；
3) 同步 units.body 与 FTS。
"""
import sqlite3, re

DB = 'sqlite/regulations.sqlite3'
RESTORE = [('22.86-0.64', '22.86±0.64')]
FIXES = [
    (re.compile(r'CH96-\s*1±\s*3'), 'CH96–1–3'),
    (re.compile(r'(27419)±\s*(8300)'), r'\1–\2'),
    (re.compile(r'(Report\s+46)±\s*(27)'), r'\1–\2'),
]

con = sqlite3.connect(DB)
cur = con.cursor()
docs = cur.execute(
    "SELECT id, full_text FROM documents WHERE full_text LIKE '%22.86-0.64%' "
    "OR full_text LIKE '%CH96-%1±%' OR full_text LIKE '%27419±%' OR full_text LIKE '%Report 46±%'"
).fetchall()
print('candidate docs:', [d[0] for d in docs])
changed = []
cur.execute('BEGIN IMMEDIATE')
for did, text in docs:
    new = text
    for a, b in RESTORE:
        new = new.replace(a, b)
    for pat, repl in FIXES:
        new, _ = pat.subn(repl, new)
    if new != text:
        changed.append(did)
        cur.execute('UPDATE documents SET full_text=? WHERE id=?', (new, did))
        for ordinal, body in cur.execute(
                'SELECT ordinal,body FROM units WHERE document_id=?', (did,)).fetchall():
            nb = body
            for a, b in RESTORE:
                nb = nb.replace(a, b)
            for pat, repl in FIXES:
                nb, _ = pat.subn(repl, nb)
            if nb != body:
                cur.execute('UPDATE units SET body=? WHERE document_id=? AND ordinal=?',
                            (nb, did, ordinal))
        trow = cur.execute('SELECT title FROM documents_fts WHERE document_id=?', (did,)).fetchone()
        title = trow[0] if trow else None
        cur.execute('DELETE FROM documents_fts WHERE document_id=?', (did,))
        cur.execute('INSERT INTO documents_fts(document_id,title,body) VALUES(?,?,?)',
                    (did, title, new))
con.commit()
print('changed docs:', changed)
con.close()
