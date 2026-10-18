#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把乱码治理补丁应用到本地 regulations.sqlite3。

只使用 Python 标准库，不需要安装任何第三方包。
用法：
    python apply_db_governance.py --db "D:/path/regulations.sqlite3" --patch governance_patch.json.gz
    python apply_db_governance.py --db ... --patch ... --dry-run
    python apply_db_governance.py --db ... --patch ... --verify-only

脚本会：
  1. 校验当前库结构与补丁格式；
  2. 自动创建一份完整备份（可用 --no-backup 关闭）；
  3. 按文档校验治理前 SHA256，仅对匹配的文档应用逐字符修正；
  4. 同步重写受影响文档的 units.body 和 documents_fts；
  5. 提交后做一次校验，打印结果。

安全原则：任何一篇文档的旧文本哈希不匹配，就跳过该文档并报告，不强行修改。
"""
import argparse
import gzip
import hashlib
import json
import os
import sqlite3
import sys
import time

# Windows 控制台可能是 GBK；避免打印中文/特殊字符时崩溃
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

REQUIRED_TABLES = {'laws', 'documents', 'units', 'documents_fts', 'blobs', 'artifacts', 'responses'}

def sha256_text(s):
    return hashlib.sha256(s.encode('utf-8')).hexdigest()

def load_patch(path):
    with open(path, 'rb') as f:
        magic = f.read(2)
    if magic == b'\x1f\x8b':
        with gzip.open(path, 'rb') as f:
            data = f.read()
    else:
        with open(path, 'rb') as f:
            data = f.read()
    payload = json.loads(data.decode('utf-8'))
    if payload.get('format') != 'regulations-governance-patch':
        raise ValueError('不是预期的治理补丁文件')
    return payload

def check_db(con):
    cur = con.cursor()
    names = {r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    missing = REQUIRED_TABLES - names
    if missing:
        raise ValueError('数据库缺少表：' + ', '.join(sorted(missing)))
    if cur.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
        raise ValueError('数据库 quick_check 未通过，请先排查')

def make_backup(con, db_path):
    stamp = time.strftime('%Y%m%d-%H%M%S')
    backup = f'{db_path}.bak-governance-{stamp}'
    if os.path.exists(backup):
        raise FileExistsError(backup)
    print(f'[备份] 正在创建 {backup} ...', flush=True)
    dst = sqlite3.connect(backup)
    try:
        con.backup(dst)
    finally:
        dst.close()
    print(f'[备份] 完成，{os.path.getsize(backup):,} 字节', flush=True)
    return backup

def apply_patch(con, patch, dry_run=False):
    cur = con.cursor()
    docs = patch['docs']
    stats = {
        'applied': 0, 'already': 0, 'mismatch': 0, 'error': 0,
        'units_updated': 0, 'units_missing': 0, 'fts_updated': 0,
    }
    mismatches = []
    errors = []
    cur.execute('BEGIN IMMEDIATE')
    for i, entry in enumerate(docs, 1):
        did = entry['id']
        row = cur.execute('SELECT full_text FROM documents WHERE id=?', (did,)).fetchone()
        if not row or row[0] is None:
            stats['error'] += 1
            errors.append((did, '文档不存在或 full_text 为空'))
            continue
        old_text = row[0]
        h_old = sha256_text(old_text)
        if h_old == entry['new_sha256']:
            stats['already'] += 1
            continue
        if h_old != entry['old_sha256']:
            stats['mismatch'] += 1
            mismatches.append((did, h_old, entry['old_sha256']))
            continue
        edits = entry.get('edits')
        if edits is None:
            stats['error'] += 1
            errors.append((did, '补丁包含整篇替换，当前脚本版本不支持'))
            continue
        chars = list(old_text)
        bad = False
        for pos, ch in edits:
            if pos < 0 or pos >= len(chars):
                bad = True
                break
            chars[pos] = ch
        if bad:
            stats['error'] += 1
            errors.append((did, '补丁位置越界'))
            continue
        new_text = ''.join(chars)
        if sha256_text(new_text) != entry['new_sha256']:
            stats['error'] += 1
            errors.append((did, '应用后哈希与补丁不一致'))
            continue

        if not dry_run:
            cur.execute('UPDATE documents SET full_text=? WHERE id=?', (new_text, did))

            # units：原库中受影响的 unit body 是 old_text 的精确子串
            search_start = 0
            units = cur.execute(
                'SELECT ordinal, body FROM units WHERE document_id=? ORDER BY ordinal', (did,)
            ).fetchall()
            for ordinal, old_body in units:
                off = old_text.find(old_body, search_start)
                if off < 0:
                    stats['units_missing'] += 1
                    continue
                search_start = off + len(old_body)
                new_body = new_text[off:off + len(old_body)]
                if new_body != old_body:
                    cur.execute(
                        'UPDATE units SET body=? WHERE document_id=? AND ordinal=?',
                        (new_body, did, ordinal)
                    )
                    stats['units_updated'] += 1

            # FTS：保留本地已有 title
            trow = cur.execute(
                'SELECT title FROM documents_fts WHERE document_id=?', (did,)
            ).fetchone()
            if trow is None:
                trow = cur.execute(
                    'SELECT official_title FROM documents WHERE id=?', (did,)
                ).fetchone()
            title = trow[0] if trow else None
            cur.execute('DELETE FROM documents_fts WHERE document_id=?', (did,))
            cur.execute(
                'INSERT INTO documents_fts(document_id,title,body) VALUES(?,?,?)',
                (did, title, new_text)
            )
            stats['fts_updated'] += 1

        stats['applied'] += 1
        if i % 50 == 0:
            if not dry_run:
                con.commit()
                cur.execute('BEGIN IMMEDIATE')
            print(f'[进度] {i}/{len(docs)} 篇；已修正 {stats["applied"]} 篇', flush=True)

    if dry_run:
        con.rollback()
    else:
        con.commit()
    return stats, mismatches, errors

def verify(con, patch):
    cur = con.cursor()
    result = {}
    result['quick_check'] = cur.execute('PRAGMA quick_check').fetchone()[0]
    result['foreign_key_check'] = len(cur.execute('PRAGMA foreign_key_check').fetchall())
    result['fts_rows'] = cur.execute('SELECT COUNT(*) FROM documents_fts').fetchone()[0]
    result['fts_body_mismatch'] = cur.execute(
        'SELECT COUNT(*) FROM documents_fts f JOIN documents d ON d.id=f.document_id '
        'WHERE f.body IS NOT d.full_text'
    ).fetchone()[0]
    result['eth_docs'] = cur.execute(
        "SELECT id, length(full_text)-length(replace(full_text,'Ð','')) "
        "FROM documents WHERE full_text LIKE '%Ð%'"
    ).fetchall()
    result['eth_units'] = cur.execute(
        "SELECT COUNT(*) FROM units WHERE body LIKE '%Ð%'"
    ).fetchone()[0]
    # 补丁文档逐篇核对
    ok = bad = 0
    for entry in patch['docs']:
        row = cur.execute('SELECT full_text FROM documents WHERE id=?', (entry['id'],)).fetchone()
        if row and row[0] is not None and sha256_text(row[0]) == entry['new_sha256']:
            ok += 1
        else:
            bad += 1
    result['patch_docs_ok'] = ok
    result['patch_docs_bad'] = bad
    return result

def main():
    ap = argparse.ArgumentParser(description='应用法规数据库乱码治理补丁')
    ap.add_argument('--db', required=True, help='本地 regulations.sqlite3 路径')
    ap.add_argument('--patch', default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                    'governance_patch.json.gz'),
                    help='补丁文件路径（默认与脚本同目录的 governance_patch.json.gz）')
    ap.add_argument('--dry-run', action='store_true', help='只检查和统计，不写入')
    ap.add_argument('--verify-only', action='store_true', help='只做校验，不写入')
    ap.add_argument('--no-backup', action='store_true', help='跳过自动备份（不推荐）')
    args = ap.parse_args()

    if not os.path.isfile(args.db):
        print(f'错误：找不到数据库 {args.db}', file=sys.stderr)
        return 2
    if not os.path.isfile(args.patch):
        print(f'错误：找不到补丁 {args.patch}', file=sys.stderr)
        return 2

    print(f'数据库：{os.path.abspath(args.db)}')
    print(f'补丁：  {os.path.abspath(args.patch)}')
    patch = load_patch(args.patch)
    s = patch.get('summary', {})
    print(f'补丁信息：创建于 {patch.get("created_at")}；文档 {s.get("documents")} 篇；'
          f'字符修正 {s.get("char_edits")} 处')

    con = sqlite3.connect(args.db)
    try:
        check_db(con)
        if args.verify_only:
            r = verify(con, patch)
            print('\n=== 校验结果 ===')
            for k, v in r.items():
                print(f'{k}: {v}')
            return 0 if r['patch_docs_bad'] == 0 and r['quick_check'] == 'ok' else 1

        if not args.no_backup and not args.dry_run:
            make_backup(con, args.db)

        t0 = time.time()
        stats, mismatches, errors = apply_patch(con, patch, dry_run=args.dry_run)
        print('\n=== 应用结果 ===')
        for k, v in stats.items():
            print(f'{k}: {v}')
        print(f'耗时：{time.time()-t0:.1f}s')

        if mismatches:
            print('\n以下文档的旧文本哈希与补丁不匹配，已跳过（你的库可能不是同一版本）：')
            for did, got, want in mismatches[:30]:
                print(f'  {did}  当前={got[:16]}  期望={want[:16]}')
            if len(mismatches) > 30:
                print(f'  ...另外 {len(mismatches)-30} 篇')
        if errors:
            print('\n以下文档处理出错：')
            for did, msg in errors[:30]:
                print(f'  {did}: {msg}')
        if args.dry_run:
            print('\n[dry-run] 未写入任何数据')
            return 0

        r = verify(con, patch)
        print('\n=== 应用后校验 ===')
        for k, v in r.items():
            print(f'{k}: {v}')
        ok = (not mismatches and not errors and stats['units_missing'] == 0
              and r['patch_docs_bad'] == 0 and r['fts_body_mismatch'] == 0
              and r['quick_check'] == 'ok')
        print('\n结果：' + ('成功' if ok else '有未完成项，请查看上面的报告'))
        return 0 if ok else 1
    finally:
        con.close()

if __name__ == '__main__':
    sys.exit(main())
