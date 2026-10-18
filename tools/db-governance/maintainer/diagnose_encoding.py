#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""扫描数据库所有文本列的编码异常，输出 UTF-8 报告。只读，不修改数据库。"""
import sqlite3, json, sys, re

DB = sys.argv[1] if len(sys.argv) > 1 else 'sqlite/regulations.sqlite3'
OUT = sys.argv[2] if len(sys.argv) > 2 else 'scripts/encoding_report.txt'

con = sqlite3.connect(DB)
cur = con.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'documents_fts%' AND name NOT LIKE 'sqlite_%' ORDER BY name")
tables = [r[0] for r in cur.fetchall()]

REPL = '�'          # replacement character
# 典型 UTF-8 被按 cp1252/latin-1 解码后的乱码特征
MOJI_RE = re.compile(r'[À-ÿ][\u0080-¿‘-›]|â€|Ã[\u0080-¿]|锟斤拷|烫烫烫|屯屯屯')
CTRL_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f]')
QM_RE = re.compile(r'\?{3,}')

lines = []
def w(s=''):
    lines.append(s)

w(f'DB: {DB}')
w(f'tables: {len(tables)}')
w()

summary = []
examples = []
for t in tables:
    cols = cur.execute(f'PRAGMA table_info("{t}")').fetchall()
    textcols = [c[1] for c in cols if (c[2] or '').upper() in ('TEXT','','CLOB') or c[2] is None]
    n = cur.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
    for c in textcols:
        try:
            rows = cur.execute(f'SELECT rowid, "{c}" FROM "{t}" WHERE "{c}" IS NOT NULL').fetchall()
        except sqlite3.Error:
            # WITHOUT ROWID 等
            rows = cur.execute(f'SELECT "{c}" FROM "{t}" WHERE "{c}" IS NOT NULL').fetchall()
        stats = {'repl': 0, 'moji': 0, 'ctrl': 0, 'qm': 0}
        ex = {'repl': [], 'moji': [], 'ctrl': [], 'qm': []}
        for row in rows:
            v = row[-1]
            if not isinstance(v, str):
                continue
            if REPL in v:
                stats['repl'] += 1
                if len(ex['repl']) < 3: ex['repl'].append(v[:200])
            if MOJI_RE.search(v):
                stats['moji'] += 1
                if len(ex['moji']) < 3: ex['moji'].append(v[:200])
            if CTRL_RE.search(v):
                stats['ctrl'] += 1
                if len(ex['ctrl']) < 3: ex['ctrl'].append(repr(v[:200]))
            if QM_RE.search(v):
                stats['qm'] += 1
                if len(ex['qm']) < 3: ex['qm'].append(v[:200])
        bad = sum(1 for k in stats if stats[k])
        if bad:
            summary.append((t, c, len(rows), stats))
            for k in ('repl','moji','ctrl','qm'):
                if stats[k]:
                    examples.append((t, c, k, stats[k], ex[k][:2]))

w('=== 汇总（仅列出有异常的表/列）===')
for t, c, total, st in summary:
    w(f'{t}.{c}: 非空={total} repl={st["repl"]} moji={st["moji"]} ctrl={st["ctrl"]} qmark={st["qm"]}')

w()
w('=== 示例（最多2条/类）===')
for t, c, k, n, exs in examples:
    w(f'--- {t}.{c} [{k}] n={n}')
    for e in exs:
        w('    ' + repr(e))

with open(OUT, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))
print(f'written {OUT}: {len(lines)} lines')
