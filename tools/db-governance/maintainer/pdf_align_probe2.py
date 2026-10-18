#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""原型2：去空白字符序列上的上下文匹配。只读。"""
import sqlite3, zlib, re, sys, collections, fitz

OLD_DB = 'sqlite/regulations.sqlite3.bak-20261018'
NEW_DB = 'sqlite/regulations.sqlite3'
DOCS = sys.argv[1:] or ['US-FR:96-14138', 'US-FR:97-2007', 'US-CFR:2025:21:3:178',
                        'US-FR:96-1143', 'US-FR:95-5382']

def get_pdf_text(cur, did):
    r = cur.execute('''SELECT b.encoding,b.payload FROM artifacts ar
        JOIN responses r ON r.id=ar.response_id JOIN blobs b ON b.sha256=r.blob_sha256
        WHERE ar.document_id=? AND ar.format='pdf' LIMIT 1''', (did,)).fetchone()
    if not r:
        return None
    enc, payload = r
    data = zlib.decompress(payload) if enc == 'zlib' else payload
    return '\n'.join(p.get_text() for p in fitz.open(stream=data, filetype='pdf'))

WS = re.compile(r'\s+')

def strip_ws(s):
    return WS.sub('', s)

def build_index_map(old):
    """old 中每个下标 -> 去掉空白后的下标（空白字符映射到前一个非空白计数）。"""
    idx = [0]*len(old)
    n = 0
    for i, ch in enumerate(old):
        idx[i] = n
        if not ch.isspace():
            n += 1
    return idx, n

def resolve(old_ns, new_ns, ns_pos, char):
    for radius in (50, 35, 25, 15, 8):
        left = old_ns[max(0, ns_pos-radius):ns_pos]
        right = old_ns[ns_pos+1:ns_pos+1+radius]
        if not left and not right:
            continue
        def esc_ctx(x):
            return ''.join('.' if ch in 'Ð±' else re.escape(ch) for ch in x)
        pat = re.compile(esc_ctx(left) + '(.)' + esc_ctx(right))
        ms = list(pat.finditer(new_ns))
        if len(ms) == 1:
            return ms[0].group(1), radius
        if len(ms) > 1:
            for m in ms:
                if m.group(1) != char:
                    return m.group(1), radius
            return ms[0].group(1), radius
    return None, None

old = sqlite3.connect(OLD_DB)
newcon = sqlite3.connect(NEW_DB)
for did in DOCS:
    row = old.execute('SELECT full_text FROM documents WHERE id=?', (did,)).fetchone()
    if not row:
        print(did, 'NO OLD'); continue
    old_text = row[0]
    new_text = get_pdf_text(newcon.cursor(), did)
    if new_text is None:
        print(did, 'NO PDF'); continue
    old_ns = strip_ws(old_text)
    new_ns = strip_ws(new_text)
    omap, _ = build_index_map(old_text)
    positions = [(m.start(), c) for c in ('Ð', '±') for m in re.finditer(c, old_text)]
    positions.sort()
    cap = collections.Counter(); unresolved = []
    for pos, c in positions:
        got, radius = resolve(old_ns, new_ns, omap[pos], c)
        if got is None:
            unresolved.append((c, repr(old_text[max(0,pos-50):pos+51])))
        else:
            cap[(c, got)] += 1
    print('='*20, did, 'chars=', len(positions), 'resolved=', sum(cap.values()),
          'unresolved=', len(unresolved))
    print('captured:', dict(cap))
    for u in unresolved[:8]:
        print('   ', u)
