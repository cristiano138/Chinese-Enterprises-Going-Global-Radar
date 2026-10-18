# -*- coding: utf-8 -*-
"""官方正文候选、差异审阅及带哈希确认的事务入库。"""
import difflib
import hashlib
import json
import re
import sqlite3
import urllib.request
import xml.etree.ElementTree as ET
from contextlib import closing
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

from core import law_store


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def fetch(url):
    accept = 'application/json' if '.json' in url else ('application/xml' if '.xml' in url else 'text/html')
    req = urllib.request.Request(url, headers={'User-Agent': 'compliance-radar/1.0', 'Accept': accept})
    with urllib.request.urlopen(req, timeout=45) as response:
        final = response.url
        host = __import__('urllib.parse', fromlist=['urlsplit']).urlsplit(final).hostname
        if host not in {'www.ecfr.gov', 'eur-lex.europa.eu'}:
            raise ValueError('官方接口重定向至非预期来源')
        raw = response.read(20_000_001)
        if len(raw) > 20_000_000:
            raise ValueError('官方正文超过单次抓取上限')
        return raw, final


class DocumentHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.depth = 0
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style'}:
            self.skip += 1
        if dict(attrs).get('id') == 'document1':
            self.depth = 1
        elif self.depth and tag not in {'br', 'hr', 'img', 'meta', 'link', 'input', 'wbr'}:
            self.depth += 1
        if self.depth and tag in {'p', 'div', 'br', 'tr', 'h1', 'h2', 'h3'}:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in {'script', 'style'}:
            self.skip = max(0, self.skip - 1)
        if self.depth and tag not in {'br', 'hr', 'img', 'meta', 'link', 'input', 'wbr'}:
            self.depth -= 1

    def handle_data(self, data):
        if self.depth and not self.skip:
            self.parts.append(data)


def split_text(text, url, max_size=12000):
    """逐字符保留正文；结构标记细切后仍对超长段落做有界续片。"""
    marks = list(re.finditer(r'(?m)^\s*(?:Article\s+\d+[a-z]?|ANNEX\b[^\n]*|§\s*\d+[\w.\-]*|PART\s+\d+[^\n]*)', text, re.I))
    starts = sorted(set([0] + [m.start() for m in marks] + [len(text)]))
    units = []
    for start, end in zip(starts, starts[1:]):
        chunk = text[start:end]
        lines = [s.strip() for s in chunk.splitlines() if s.strip()]
        label = lines[0][:200] if lines else '正文'
        for offset in range(0, len(chunk), max_size):
            body = chunk[offset:offset + max_size]
            units.append({'heading': label + (f'（续片 {offset // max_size + 1}）' if offset else ''),
                          'locator': url + '#offset-' + str(start + offset), 'body': body,
                          'unit_type': 'text_block', 'source_fragment': None})
    return units


def fetch_official(identifier):
    ident = law_store.law_id(identifier)
    if not ident:
        raise ValueError('法规标识无效')
    if ident.startswith('US:'):
        _, title, part = ident.split(':')
        raw_titles, _ = fetch('https://www.ecfr.gov/api/versioner/v1/titles.json')
        titles = json.loads(raw_titles)
        if not isinstance(titles, dict) or not isinstance(titles.get('titles'), list):
            raise ValueError('eCFR titles 响应结构异常')
        title_meta = next((t for t in titles['titles'] if str(t.get('number')) == title), None)
        if not title_meta:
            raise ValueError('eCFR 未找到该 Title')
        date = title_meta.get('latest_issue_date') or titles.get('meta', {}).get('date')
        if not isinstance(date, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', date):
            raise ValueError('eCFR 缺少可信快照日期')
        url = f'https://www.ecfr.gov/api/versioner/v1/full/{date}/title-{title}.xml?part={part}'
        raw, final = fetch(url)
        tree = ET.fromstring(raw)
        node = next((n for n in tree.iter() if n.attrib.get('TYPE') == 'PART' and n.attrib.get('N') == part), None)
        if node is None:
            raise ValueError('eCFR 正文未包含目标 Part；保留旧数据')
        head = node.find('HEAD')
        label = ''.join(head.itertext()).strip() if head is not None else ''
        if not label or '[Reserved]' in label or '[Removed]' in label:
            raise ValueError('eCFR Part 无正文或标为保留/移除')
        text = '\n'.join(''.join(child.itertext()).strip() for child in node if ''.join(child.itertext()).strip())
        document_id = f'US-eCFR:{title}:{part}:{date}'
        kind, legal = 'us_ecfr', 'authoritative_unofficial_compilation'
    else:
        celex = ident.split(':', 1)[1]
        url = f'https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:{celex}'
        raw, final = fetch(url)
        parser = DocumentHTML()
        parser.feed(raw.decode('utf-8-sig'))
        text = '\n'.join(s.strip() for s in ''.join(parser.parts).replace('\xa0', ' ').splitlines() if s.strip())
        if not re.search(r'\b(?:Article\s+\d|ANNEX)\b', text, re.I):
            raise ValueError('官方英文页面缺少可识别正文；未覆盖现有数据')
        label = text.splitlines()[0][:500]
        date, document_id = None, 'EU-DOC:' + celex
        kind, legal = 'eu_original', 'official_publication_source'
    if len(text.strip()) < 100:
        raise ValueError('官方正文为空或过短，保留旧数据')
    return {'law_id': ident, 'document_id': document_id, 'official_title': label,
            'source_url': final, 'version_date': date, 'kind': kind, 'legal_status': legal,
            'body': text, 'raw_sha256': hashlib.sha256(raw).hexdigest(), 'raw_hex': raw.hex(),
            'sha256': digest(text), 'units': split_text(text, final),
            'retrieved_at': datetime.now(timezone.utc).isoformat()}


def stage(identifier, directory, path=None):
    """抓取阶段只写候选，不更改正式库。异常分类留存，可重试。"""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    ident = law_store.law_id(identifier)
    try:
        candidate = fetch_official(identifier)
        base = None
        if law_store.status(path)['ok']:
            with closing(law_store.connect(path)) as con:
                row = con.execute('SELECT full_text FROM documents WHERE id=?', (candidate['document_id'],)).fetchone()
                base = row[0] if row else None
        candidate['base_sha256'] = digest(base) if base is not None else None
        candidate['diff'] = ''.join(difflib.unified_diff((base or '').splitlines(True), candidate['body'].splitlines(True), fromfile='现有正文', tofile='官方候选'))
        candidate['state'] = 'pending_review'
        target = directory / (candidate['law_id'].replace(':', '-') + '-' + candidate['sha256'][:16] + '.json')
        target.write_text(json.dumps(candidate, ensure_ascii=False, indent=2), encoding='utf-8')
        return {'ok': True, 'candidate': str(target), 'sha256': candidate['sha256'], 'state': candidate['state']}
    except Exception as exc:
        error = {'ok': False, 'law_id': ident, 'state': 'unavailable_or_fetch_failed', 'error_type': type(exc).__name__, 'reason': str(exc)}
        target = directory / ((ident or 'invalid').replace(':', '-') + '-failure.json')
        target.write_text(json.dumps(error, ensure_ascii=False, indent=2), encoding='utf-8')
        return error


def _insert(con, table, values):
    columns = {r[1] for r in con.execute('PRAGMA table_info(' + table + ')')}
    values = {k: v for k, v in values.items() if k in columns}
    con.execute('INSERT INTO ' + table + ' (' + ','.join(values) + ') VALUES (' + ','.join('?' for _ in values) + ')', list(values.values()))


def apply(candidate_path, expected_sha256, path=None):
    candidate = json.loads(Path(candidate_path).read_text(encoding='utf-8'))
    body = candidate.get('body', '')
    if candidate.get('state') != 'pending_review' or digest(body) != expected_sha256 or candidate.get('sha256') != expected_sha256:
        raise ValueError('候选状态或确认哈希不匹配')
    raw = bytes.fromhex(candidate['raw_hex'])
    if hashlib.sha256(raw).hexdigest() != candidate['raw_sha256']:
        raise ValueError('候选原始响应哈希不匹配')
    ident = law_store.law_id(candidate['law_id'])
    if not ident or not body.strip():
        raise ValueError('候选缺少法规标识或正文')
    from urllib.parse import urlsplit, parse_qs
    source = urlsplit(candidate['source_url'])
    if ident.startswith('US:'):
        _, title, part = ident.split(':')
        date = candidate['version_date']
        if candidate['document_id'] != f'US-eCFR:{title}:{part}:{date}' or source.hostname != 'www.ecfr.gov' or source.path != f'/api/versioner/v1/full/{date}/title-{title}.xml' or parse_qs(source.query).get('part') != [part]:
            raise ValueError('候选来源与法规标识不一致')
        tree = ET.fromstring(raw)
        node = next((n for n in tree.iter() if n.attrib.get('TYPE') == 'PART' and n.attrib.get('N') == part), None)
        if node is None:
            raise ValueError('官方原件缺少目标 Part')
        parsed = '\n'.join(''.join(child.itertext()).strip() for child in node if ''.join(child.itertext()).strip())
    else:
        celex = ident.split(':', 1)[1]
        if source.hostname != 'eur-lex.europa.eu' or parse_qs(source.query).get('uri') != ['CELEX:' + celex] or candidate['document_id'] != 'EU-DOC:' + celex:
            raise ValueError('候选来源与法规标识不一致')
        parser = DocumentHTML()
        parser.feed(raw.decode('utf-8-sig'))
        parsed = '\n'.join(s.strip() for s in ''.join(parser.parts).replace('\xa0', ' ').splitlines() if s.strip())
    if parsed != body:
        raise ValueError('正文与留存的官方响应解析不一致')
    with closing(law_store.connect(path, writable=True)) as con:
        backup_path = law_store.backup(con, path)
        try:
            con.execute('BEGIN IMMEDIATE')
            current = con.execute('SELECT full_text FROM documents WHERE id=?', (candidate['document_id'],)).fetchone()
            current_hash = digest(current[0]) if current and current[0] is not None else None
            if current_hash == expected_sha256:
                con.rollback()
                return {'ok': True, 'action': 'unchanged', 'backup': backup_path}
            if current_hash != candidate.get('base_sha256'):
                raise ValueError('正文已被其他写入者更新，请重新抓取审阅')
            law = con.execute('SELECT id FROM laws WHERE id=?', (ident,)).fetchone()
            if not law:
                bits = ident.split(':')
                seed = json.dumps({'核对状态': '待核对', '官方链接': candidate['source_url'], '官方标题（英文）': candidate['official_title']}, ensure_ascii=False, sort_keys=True)
                _insert(con, 'laws', {'id': ident, 'jurisdiction': bits[0], 'title_number': int(bits[1]) if bits[0] == 'US' else None,
                                     'part_number': bits[2] if bits[0] == 'US' else None, 'celex': bits[1] if bits[0] == 'EU' else None,
                                     'seed_json': seed, 'seed_sha256': digest(seed), 'official_title': candidate['official_title'],
                                     'association_review': '未作适用性判断'})
            values = {k: candidate.get(k) for k in ['kind', 'official_title', 'source_url', 'version_date', 'legal_status']}
            values.update(id=candidate['document_id'], jurisdiction=ident.split(':')[0], language='en',
                          source_identifier=ident.split(':', 1)[1], metadata_status='downloaded', transfer_status='downloaded',
                          parse_status='extracted_unreviewed', full_text=body, notes='官方抓取候选经哈希确认入库；未经法律适用性审核')
            if current:
                con.execute('UPDATE documents SET full_text=?,parse_status=? WHERE id=?', (body, 'extracted_unreviewed', values['id']))
                con.execute('DELETE FROM units WHERE document_id=?', (values['id'],))
            else:
                _insert(con, 'documents', values)
            con.execute('INSERT OR IGNORE INTO law_documents(law_id,document_id,role) VALUES(?,?,?)', (ident, values['id'], 'primary' if not law else ('bulk_fallback' if ident.startswith('US:') else 'eu_original')))
            for ordinal, unit in enumerate(split_text(body, candidate['source_url'])):
                _insert(con, 'units', {**unit, 'document_id': values['id'], 'ordinal': ordinal})
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'documents_fts' in tables:
                con.execute('DELETE FROM documents_fts WHERE document_id=?', (values['id'],))
                con.execute('INSERT INTO documents_fts(document_id,title,body) VALUES(?,?,?)', (values['id'], values['official_title'], body))
            if con.execute('PRAGMA quick_check').fetchone()[0] != 'ok' or con.execute('PRAGMA foreign_key_check').fetchone():
                raise ValueError('数据库一致性校验失败')
            con.commit()
            actual = con.execute('SELECT full_text FROM documents WHERE id=?', (values['id'],)).fetchone()[0]
            return {'ok': digest(actual) == expected_sha256, 'action': 'applied', 'backup': backup_path,
                    'law_id': ident, 'document_id': values['id'], 'sha256': digest(actual), 'release_eligible': False}
        except Exception:
            con.rollback()
            raise
