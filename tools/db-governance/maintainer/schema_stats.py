#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sqlite3
con = sqlite3.connect('sqlite/regulations.sqlite3')
cur = con.cursor()
out = []

def q(title, sql):
    out.append('=== ' + title + ' ===')
    try:
        for r in cur.execute(sql):
            out.append(repr(r))
    except Exception as e:
        out.append('ERR ' + str(e))
    out.append('')

q('laws jurisdiction', "SELECT jurisdiction,COUNT(*) FROM laws GROUP BY 1")
q('laws in_force', "SELECT in_force,COUNT(*) FROM laws GROUP BY 1")
q('laws association_review', "SELECT association_review,COUNT(*) FROM laws GROUP BY 1")
q('laws title_number/part/celex samples', "SELECT id,title_number,part_number,celex,substr(seed_json,1,80) FROM laws LIMIT 3")
q('documents jurisdiction/kind', "SELECT jurisdiction,kind,COUNT(*) FROM documents GROUP BY 1,2 ORDER BY 1,2")
q('documents language', "SELECT language,COUNT(*) FROM documents GROUP BY 1")
q('documents legal_status', "SELECT legal_status,COUNT(*) FROM documents GROUP BY 1")
q('documents metadata_status', "SELECT metadata_status,COUNT(*) FROM documents GROUP BY 1")
q('documents transfer_status', "SELECT transfer_status,COUNT(*) FROM documents GROUP BY 1")
q('documents parse_status', "SELECT parse_status,COUNT(*) FROM documents GROUP BY 1")
q('law_documents role', "SELECT role,COUNT(*) FROM law_documents GROUP BY 1")
q('artifacts purpose', "SELECT purpose,COUNT(*) FROM artifacts GROUP BY 1 ORDER BY 2 DESC")
q('artifacts format', "SELECT format,COUNT(*) FROM artifacts GROUP BY 1 ORDER BY 2 DESC")
q('artifacts format_status', "SELECT format_status,COUNT(*) FROM artifacts GROUP BY 1 ORDER BY 2 DESC")
q('units unit_type', "SELECT unit_type,COUNT(*) FROM units GROUP BY 1 ORDER BY 2 DESC")
q('events event_type', "SELECT event_type,COUNT(*) FROM events GROUP BY 1 ORDER BY 2 DESC")
q('relations predicate', "SELECT predicate,COUNT(*) FROM relations GROUP BY 1 ORDER BY 2 DESC")
q('tasks phase', "SELECT phase,COUNT(*) FROM tasks GROUP BY 1 ORDER BY 2 DESC")
q('tasks state', "SELECT state,COUNT(*) FROM tasks GROUP BY 1 ORDER BY 2 DESC")
q('attempts outcome', "SELECT outcome,COUNT(*) FROM attempts GROUP BY 1 ORDER BY 2 DESC")
q('responses media_type', "SELECT media_type,COUNT(*) FROM responses GROUP BY 1 ORDER BY 2 DESC")
q('blobs encoding', "SELECT encoding,COUNT(*) FROM blobs GROUP BY 1")
q('document_metadata section', "SELECT section,COUNT(*) FROM document_metadata GROUP BY 1 ORDER BY 2 DESC")
q('source_citations match_status', "SELECT match_status,COUNT(*) FROM source_citations GROUP BY 1")
q('law_documents sample', "SELECT * FROM law_documents LIMIT 3")
q('events sample', "SELECT * FROM events LIMIT 3")
q('relations sample', "SELECT * FROM relations LIMIT 8")
q('source_citations sample', "SELECT * FROM source_citations LIMIT 3")
q('document_metadata sample', "SELECT document_id,section,substr(scoped_json,1,200),response_ids_json FROM document_metadata LIMIT 3")
q('tasks sample', "SELECT task_key,phase,law_id,substr(payload_json,1,150),state,substr(error,1,80),updated_at FROM tasks LIMIT 5")
q('attempts sample', "SELECT * FROM attempts ORDER BY id DESC LIMIT 5")
q('settings keys', "SELECT key,substr(value,1,80) FROM settings ORDER BY key")

with open('scripts/schema_stats.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(out))
print('ok', len(out))
