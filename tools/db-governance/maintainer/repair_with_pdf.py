#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""以库内原始 PDF 的重新抽取结果为准，校正 documents.full_text 与 units.body
中的 Ð / ± 字体映射乱码。

- 旧文本取自修复前备份库；PDF 取自当前库 blobs（原始字节未改动）。
- 仅处理“含 Ð”或“含 >=3 个典型 ± 标识符模式”的文档，避免误改合法 ± 容差。
- 校正采用“去空白后的字符序列上下文匹配”：用 PDF 文本中对应位置的字符替换。
- 无法匹配时使用保守回退规则；仍无法判断的 ± 保留原样并写入报告。
- 同步更新 documents_fts。
"""
import sqlite3, zlib, re, sys, collections, time, fitz

OLD_DB = 'sqlite/regulations.sqlite3.bak-20261018'
NEW_DB = 'sqlite/regulations.sqlite3'
REPORT = 'scripts/pdf_repair_report.txt'
DRY = '--dry-run' in sys.argv
SKIP_DOC = 'EU-DOC:31994L0011'
LIMIT = None
for a in sys.argv[1:]:
    if a.startswith('--limit='):
        LIMIT = int(a.split('=', 1)[1])

STRONG = [
    re.compile(r'\bFR Doc\.? \d+±\d+'),
    re.compile(r'Filed \d+±\d+±\d+'),
    re.compile(r'BILLING CODE \d+±\d+±[A-Z]'),
    re.compile(r'\bNo\. \d+±\d+'),
    re.compile(r'Docket No\. \d+±\d+'),
    re.compile(r'\bFCC \d+±\d+'),
    re.compile(r'\(\d{3}\) \d+±\d+'),
    re.compile(r'\d+(?:\.\d+)?±\d+(?:\.\d+)? (?:GHz|MHz|kHz|Hz)\b'),
    re.compile(r'U\.S\.C\. \d+±\d+'),
    re.compile(r'\b(?:Part|Subpart) \d+±\d+'),
    re.compile(r'U±NII'),
    re.compile(r'\b\d+±\d+±\d+\b'),
    re.compile(r'\b(?:19|20)\d{2}±(?:19|20)\d{2}\b'),
]

WS = re.compile(r'\s+')
def strip_ws(s):
    return WS.sub('', s)

def index_map(s):
    m = [0] * len(s)
    n = 0
    for i, ch in enumerate(s):
        m[i] = n
        if not ch.isspace():
            n += 1
    return m

def esc_ctx(x):
    return ''.join('.' if ch in 'Ð±' else re.escape(ch) for ch in x)

def resolve(old_ns, new_ns, ns_pos):
    """返回 (替换字符, 置信度, 半径)。"""
    for radius in (100, 70, 50, 35, 25, 15, 8):
        left = old_ns[max(0, ns_pos - radius):ns_pos]
        right = old_ns[ns_pos + 1:ns_pos + 1 + radius]
        if not left and not right:
            continue
        try:
            pat = re.compile(esc_ctx(left) + '(.)' + esc_ctx(right))
        except re.error:
            continue
        ms = list(pat.finditer(new_ns))
        if len(ms) == 1:
            return ms[0].group(1), 'unique', radius
        if ms:
            chars = {m.group(1) for m in ms}
            if len(chars) == 1:
                return chars.pop(), 'multi_same', radius
    return None, 'none', None

ALLOWED = {
    'Ð': set('—–-•·.'),          # PDF 中对应为破折号/连接号/项目符号等
    '±': set('–—-±.'),           # 对应为连接号/连字符/合法 ±/小数点等
}

def valid_replacement(old_char, got, old_text, pos):
    if not got:
        return False
    if got == old_char:
        return True
    if got not in ALLOWED[old_char]:
        return False
    # 若 PDF 中该字符被删除，上下文偏移可能抓到后一个字符
    nxt = old_text[pos + 1] if pos + 1 < len(old_text) else ''
    if got == nxt and got not in ALLOWED[old_char]:
        return False
    return True

def fallback(old_char, old_text, pos):
    if old_char == 'Ð':
        line_start = pos == 0 or old_text[pos - 1] == '\n'
        nxt = old_text[pos + 1] if pos + 1 < len(old_text) else ''
        if line_start and nxt.isupper():
            return '•', 'fallback_bullet'
        return '—', 'fallback_emdash'
    # ±
    l = pos
    while l > 0 and not old_text[l - 1].isspace():
        l -= 1
    r = pos + 1
    while r < len(old_text) and not old_text[r].isspace():
        r += 1
    token = old_text[l:r]
    ctx = old_text[max(0, pos - 45):pos + 46]
    if re.search(r'[A-Za-z]', token):
        return '-', 'fallback_letter_token'
    if re.search(r'FR Doc|Docket|BILLING CODE|Filed|No\.|FCC|U\.S\.C\.|Part|Subpart|Case|Amendment|Amdt|Reg\. No\.|RIN', ctx):
        return '-', 'fallback_identifier'
    m = re.search(r'([\d,]+(?:\.\d+)?)\s*±\s*([\d,]+(?:\.\d+)?)', old_text[max(0, pos - 30):pos + 31])
    if m:
        try:
            left = float(m.group(1).replace(',', ''))
            right = float(m.group(2).replace(',', ''))
            if right > left:
                return '-', 'fallback_numeric_range'
        except ValueError:
            pass
    return '±', 'left_unchanged'

def repair_text(old_text, new_ns, stats):
    """返回修复后的文本；stats 为 collections.Counter。"""
    positions = [(m.start(), m.group(0)) for ch in ('Ð', '±') for m in re.finditer(ch, old_text)]
    positions.sort()
    if not positions:
        return old_text
    omap = index_map(old_text)
    old_ns = strip_ws(old_text)
    chars = list(old_text)
    for pos, ch in positions:
        got, conf, radius = resolve(old_ns, new_ns, omap[pos])
        if got is not None and valid_replacement(ch, got, old_text, pos):
            chars[pos] = got
            stats[f'{ch}->{got}'] += 1
            stats['resolved'] += 1
        else:
            rep, how = fallback(ch, old_text, pos)
            chars[pos] = rep
            stats[f'{ch}->{rep}'] += 1
            stats[how] += 1
            stats['unresolved'] += 1
            if len(stats.setdefault('unresolved_samples', [])) < 200:
                stats['unresolved_samples'].append((ch, how, old_text[max(0, pos - 60):pos + 61]))
    return ''.join(chars)

def pdf_text_for(cur, did):
    r = cur.execute('''SELECT b.encoding,b.payload FROM artifacts ar
        JOIN responses r ON r.id=ar.response_id JOIN blobs b ON b.sha256=r.blob_sha256
        WHERE ar.document_id=? AND ar.format='pdf' LIMIT 1''', (did,)).fetchone()
    if not r:
        return None
    enc, payload = r
    data = zlib.decompress(payload) if enc == 'zlib' else payload
    with fitz.open(stream=data, filetype='pdf') as doc:
        return '\n'.join(page.get_text() for page in doc)

def main():
    old = sqlite3.connect(OLD_DB)
    cur_old = old.cursor()
    new = sqlite3.connect(NEW_DB)
    cur_new = new.cursor()

    rows = cur_old.execute(
        "SELECT id,full_text FROM documents WHERE (full_text LIKE '%Ð%' OR full_text LIKE '%±%')"
    ).fetchall()

    affected = []
    for did, text in rows:
        if did == SKIP_DOC:
            continue
        has_eth = 'Ð' in text
        is_pm = sum(len(p.findall(text)) for p in STRONG) >= 3
        if has_eth or is_pm:
            have_pdf = cur_new.execute(
                "SELECT COUNT(*) FROM artifacts WHERE document_id=? AND format='pdf'", (did,)
            ).fetchone()[0]
            if have_pdf:
                affected.append((did, text))
    affected.sort()
    if LIMIT:
        affected = affected[:LIMIT]

    print(f'affected docs with PDF: {len(affected)}; dry_run={DRY}', flush=True)
    out = [f'affected docs with PDF: {len(affected)}', f'dry_run: {DRY}', '']
    total = collections.Counter()
    all_unresolved = []
    per_doc = []
    changed_docs = 0

    if not DRY:
        cur_new.execute('BEGIN IMMEDIATE')

    t0 = time.time()
    for idx, (did, old_text) in enumerate(affected, 1):
        try:
            new_text = pdf_text_for(cur_new, did)
        except Exception as e:
            per_doc.append((did, 0, 0, 0, f'PDF_ERROR: {e}'))
            continue
        if not new_text:
            per_doc.append((did, 0, 0, 0, 'NO_PDF_TEXT'))
            continue
        new_ns = strip_ws(new_text)
        stats = collections.Counter()
        new_full = repair_text(old_text, new_ns, stats)
        all_unresolved.extend(stats.pop('unresolved_samples', []))

        # units.body：已确认是 full_text 的精确子串，直接复用修复后的切片
        unit_changed = 0
        search_start = 0
        for ordinal, old_body in cur_old.execute(
                'SELECT ordinal,body FROM units WHERE document_id=? ORDER BY ordinal', (did,)):
            off = old_text.find(old_body, search_start)
            if off >= 0:
                new_body = new_full[off:off + len(old_body)]
                search_start = off + len(old_body)
            else:
                new_body = old_body  # 理论上不会发生；保守不动
            if new_body != old_body:
                if not DRY:
                    cur_new.execute('UPDATE units SET body=? WHERE document_id=? AND ordinal=?',
                                    (new_body, did, ordinal))
                unit_changed += 1
        if new_full != old_text:
            changed_docs += 1
            if not DRY:
                cur_new.execute('UPDATE documents SET full_text=? WHERE id=?', (new_full, did))
                # 同步 FTS，保留原有 title
                trow = cur_old.execute('SELECT title FROM documents_fts WHERE document_id=?', (did,)).fetchone()
                title = trow[0] if trow else None
                cur_new.execute('DELETE FROM documents_fts WHERE document_id=?', (did,))
                cur_new.execute('INSERT INTO documents_fts(document_id,title,body) VALUES(?,?,?)',
                                (did, title, new_full))
        for k, v in stats.items():
            if isinstance(v, int):
                total[k] += v
        per_doc.append((did, stats.get('resolved', 0), stats.get('unresolved', 0),
                        unit_changed, ''))
        if idx % 10 == 0 or idx == len(affected):
            if not DRY:
                new.commit()
                cur_new.execute('BEGIN IMMEDIATE')
            print(f'[{idx}/{len(affected)}] {did} resolved={stats.get("resolved",0)} '
                  f'unresolved={stats.get("unresolved",0)} units={unit_changed} '
                  f'({time.time()-t0:.1f}s)', flush=True)
    if not DRY:
        new.commit()

    out.append(f'changed docs: {changed_docs}')
    out.append(f'replacements (incl. units): {dict(total)}')
    out.append('')
    out.append('per-doc: doc\ttotal_resolved\ttotal_unresolved\tunits_changed\tnote')
    for r in per_doc:
        out.append('\t'.join(str(x) for x in r))
    out.append('')
    out.append(f'unresolved samples (first 100 of {len(all_unresolved)}):')
    for s in all_unresolved[:100]:
        out.append(repr(s))
    with open(REPORT, 'w', encoding='utf-8') as f:
        f.write('\n'.join(out))
    print('report:', REPORT)

if __name__ == '__main__':
    main()
