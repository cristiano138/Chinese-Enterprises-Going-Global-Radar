#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""收尾：修复残留的、模式高度确定的 ± 伪影（CAS 号、ASTM 标准号、ZIP+4、
法条号、年份区间等），并同步 units.body 与 FTS。"""
import sqlite3, re, collections

DB = 'sqlite/regulations.sqlite3'
PATTERNS = [
    ('cas',        re.compile(r'\b(\d{2,7})±(\d{2})±(\d)\b'),        r'\1–\2–\3'),
    ('astm',       re.compile(r'\b([DF]\s?\d{1,4})±(\d{2,4})\b'),    r'\1-\2'),
    ('section',    re.compile(r'\b(\d{2,4}\.\d{2,4})±(\d{1,3})\b'),  r'\1-\2'),
    ('zip4',       re.compile(r'\b(\d{5})±(\d{4})\b'),               r'\1-\2'),
    ('year',       re.compile(r'\b((?:19|20)\d{2})±(\d{2})\b'),      r'\1–\2'),
    ('id_partial', re.compile(r'\b([A-Z]{1,4}\d{1,4}-\d{1,3})±(\d{1,3})\b'), r'\1-\2'),
    ('report',     re.compile(r'\bReport (\d{1,4})±(\d{1,4})\b'),    r'Report \1-\2'),
    ('td',         re.compile(r'\b(T\. D\. \d{1,4})±(\d{1,4})\b'),   r'\1-\2'),
]

def fix(text):
    counts = collections.Counter()
    for name, pat, repl in PATTERNS:
        text, n = pat.subn(repl, text)
        if n:
            counts[name] += n
    return text, counts

con = sqlite3.connect(DB)
cur = con.cursor()
docs = cur.execute("SELECT id, full_text FROM documents WHERE full_text LIKE '%±%'").fetchall()
total = collections.Counter()
changed_docs = []
changed_units = 0
cur.execute('BEGIN IMMEDIATE')
for did, text in docs:
    new, cnt = fix(text)
    if new == text:
        continue
    changed_docs.append(did)
    total.update(cnt)
    cur.execute('UPDATE documents SET full_text=? WHERE id=?', (new, did))
    # units：对每条 body 应用同一组确定性规则
    for ordinal, body in cur.execute(
            'SELECT ordinal,body FROM units WHERE document_id=?', (did,)).fetchall():
        nb, c2 = fix(body)
        if nb != body:
            cur.execute('UPDATE units SET body=? WHERE document_id=? AND ordinal=?',
                        (nb, did, ordinal))
            changed_units += 1
            total.update(c2)
    # FTS
    trow = cur.execute('SELECT title FROM documents_fts WHERE document_id=?', (did,)).fetchone()
    title = trow[0] if trow else None
    cur.execute('DELETE FROM documents_fts WHERE document_id=?', (did,))
    cur.execute('INSERT INTO documents_fts(document_id,title,body) VALUES(?,?,?)',
                (did, title, new))
con.commit()
print('changed docs:', len(changed_docs), changed_docs)
print('changed units:', changed_units)
print('replacements:', dict(total), 'sum=', sum(total.values()))
con.close()
