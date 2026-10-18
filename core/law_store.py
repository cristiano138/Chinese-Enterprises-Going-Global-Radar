# -*- coding: utf-8 -*-
"""可选 SQLite 条款库；缺库时保留 CSV 主链路，不静默创建数据库。"""
import os
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIRED = {'laws', 'documents', 'law_documents', 'units'}


def db_path():
    configured = os.getenv('COMPLIANCE_DB_PATH', '').strip()
    if configured:
        return Path(configured).expanduser().resolve()
    candidates = [ROOT / 'sqlite/regulations.sqlite3', ROOT.parent / 'sqlite/regulations.sqlite3']
    return next((p for p in candidates if p.is_file()), candidates[0])


def connect(path=None, writable=False):
    path = Path(path or db_path()).resolve()
    if not path.is_file():
        raise FileNotFoundError('条款库未配置；CSV 法规清单仍可使用')
    con = sqlite3.connect(path.as_uri() + ('?mode=rw' if writable else '?mode=ro'), uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA busy_timeout=30000')
    con.execute('PRAGMA foreign_keys=ON')
    return con


def status(path=None):
    try:
        with closing(connect(path)) as con:
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            missing = REQUIRED - tables
            if missing:
                return {'ok': False, 'reason': '条款库结构不完整：' + ', '.join(sorted(missing))}
            return {'ok': True, 'reason': 'SQLite 条款库已接入',
                    'laws': con.execute('SELECT COUNT(*) FROM laws').fetchone()[0]}
    except (OSError, sqlite3.Error) as exc:
        return {'ok': False, 'reason': str(exc)}


def backup(con, path=None):
    path = Path(path or db_path())
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    target = path.with_name(path.name + '.bak-' + stamp)
    with closing(sqlite3.connect(target)) as dst:
        con.backup(dst)
    return str(target)


def law_id(identifier):
    value = str(identifier or '').strip()
    match = re.fullmatch(r'(?:EU:)?([036]\d{4}[A-Z]\d{4}(?:R\(\d+\))?(?:-\d{8})?)', value, re.I)
    if match:
        return 'EU:' + match[1].upper()
    match = re.fullmatch(r'US:(\d{1,2}):(\d+[a-z]?)', value, re.I)
    if not match:
        match = re.fullmatch(r'(\d{1,2})\s*CFR\s*(?:Part\s*)?(\d+[a-z]?)', value, re.I)
    return f'US:{int(match[1])}:{match[2]}' if match else ''


def retrieve(identifier, heading='', limit=12, max_chars=24000, path=None):
    ident = law_id(identifier)
    if not ident:
        return {'ok': False, 'reason': '请输入完整 CELEX、EU:CELEX、US:编:Part 或 16 CFR Part 1250', 'units': []}
    ready = status(path)
    if not ready['ok']:
        return {**ready, 'units': [], 'fallback': 'csv'}
    tokens = list(dict.fromkeys(re.findall(r'[\w]+', str(heading).casefold())))[:12]
    try:
        with closing(connect(path)) as con:
            law = con.execute('SELECT * FROM laws WHERE id=?', (ident,)).fetchone()
            if law is None:
                return {'ok': False, 'reason': '条款库未收录该法规；未进行模糊替代', 'units': []}
            clauses = ['ld.law_id=?']
            args = [ident]
            # 第二阶段只筛 heading，LIKE 通配符按字面处理。
            for token in tokens:
                clauses.append("LOWER(COALESCE(u.heading,'')) LIKE ? ESCAPE '\\'")
                args.append('%' + token.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%')
            rows = con.execute('''SELECT DISTINCT u.document_id,u.ordinal,u.locator,u.unit_type,
                u.heading,u.body,d.source_url,d.kind,d.parse_status,d.version_date
                FROM law_documents ld JOIN documents d ON d.id=ld.document_id
                JOIN units u ON u.document_id=d.id WHERE ''' + ' AND '.join(clauses) + '''
                ORDER BY CASE ld.role WHEN 'primary' THEN 0 WHEN 'eu_consolidated' THEN 1 ELSE 2 END,
                d.version_date DESC,u.ordinal LIMIT ?''', args + [min(max(int(limit), 1), 30)]).fetchall()
            result, remaining = [], min(max(int(max_chars), 1000), 60000)
            for row in rows:
                item = dict(row)
                body = item.pop('body') or ''
                if remaining <= 0:
                    break
                item['body'] = body[:remaining]
                item['truncated'] = len(body) > remaining
                item['release_eligible'] = False
                remaining -= len(item['body'])
                result.append(item)
            return {'ok': True, 'law_id': ident, 'units': result,
                    'reason': '抽取文本仅供条款溯源；不会自动生成执行动作' if result else '该法规没有匹配的条款标题；可清空标题关键词重试',
                    'release_eligible': False}
    except sqlite3.Error as exc:
        return {'ok': False, 'reason': '条款库查询失败：' + str(exc), 'units': []}
