#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成成员可用的治理补丁包。

比较“治理前备份库”和“治理后当前库”的 documents.full_text，
把差异记录为 1:1 字符替换位置（不保存整篇正文，补丁很小）。
同时记录每篇文档治理前后的 SHA256，供成员脚本校验。
"""
import sqlite3, hashlib, json, gzip, sys, collections

OLD_DB = 'sqlite/regulations.sqlite3.bak-20261018'
NEW_DB = 'sqlite/regulations.sqlite3'
OUT = 'sqlite/governance_patch.json.gz'

def sha(s):
    return hashlib.sha256(s.encode('utf-8')).hexdigest()

old = sqlite3.connect(OLD_DB)
new = sqlite3.connect(NEW_DB)
oc, nc = old.cursor(), new.cursor()

new_rows = {did: t for did, t in nc.execute('SELECT id, full_text FROM documents WHERE full_text IS NOT NULL')}
docs = []
stats = collections.Counter()
length_mismatch = []

for did, old_text in oc.execute('SELECT id, full_text FROM documents WHERE full_text IS NOT NULL'):
    new_text = new_rows.get(did)
    if new_text is None or new_text == old_text:
        continue
    entry = {
        'id': did,
        'length': len(old_text),
        'old_sha256': sha(old_text),
        'new_sha256': sha(new_text),
    }
    if len(old_text) == len(new_text):
        edits = [[i, new_text[i]] for i in range(len(old_text)) if old_text[i] != new_text[i]]
        entry['edits'] = edits
        stats['edits'] += len(edits)
        stats['docs'] += 1
        # 统计替换类型
        for _, ch in edits:
            stats[f'to:{ch}'] += 1
    else:
        # 理论上不应出现；若出现则整篇替换
        entry['new_text'] = new_text
        entry['edits'] = None
        length_mismatch.append((did, len(old_text), len(new_text)))
        stats['full_replace'] += 1
    docs.append(entry)

payload = {
    'format': 'regulations-governance-patch',
    'version': 1,
    'created_at': '2026-10-18',
    'base_note': '适用于 2026-10-17 交付版数据库（manifest original_sha256 bfb145a5...）',
    'base_manifest_sha256': 'bfb145a5c8ccf6a65809ddc237bdf0e463efc4e03e1b6e52dee64c0f9150012b',
    'summary': {
        'documents': len(docs),
        'char_edits': stats['edits'],
        'length_mismatch_docs': len(length_mismatch),
        'expected_remaining_eth_docs': 1,
        'expected_remaining_eth_chars': 2,
    },
    'docs': docs,
}

raw = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
with gzip.open(OUT, 'wb', compresslevel=9) as f:
    f.write(raw)

print('patch:', OUT)
print('uncompressed bytes:', len(raw))
import os
print('compressed bytes:', os.path.getsize(OUT))
print('documents changed:', len(docs))
print('char edits:', stats['edits'])
print('length mismatch:', length_mismatch[:10], 'count=', len(length_mismatch))
print('replacement chars:', {k: v for k, v in stats.items() if k.startswith('to:')})
print('patch sha256:', hashlib.sha256(open(OUT,'rb').read()).hexdigest())
