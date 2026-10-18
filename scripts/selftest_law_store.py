# -*- coding: utf-8 -*-
"""隔离库验证：检索、官方响应异常、治理事务、正文确认与真实多进程写入。"""
from contextlib import closing
import concurrent.futures
import importlib.util
import json
import multiprocessing
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core import law_content, law_store


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fresh = load('fresh', 'scripts/check_metadata_freshness.py')
gov = load('gov', 'tools/db-governance/apply_db_governance.py')


def create_db(path):
    con = sqlite3.connect(path)
    con.executescript('''
    CREATE TABLE laws(id TEXT PRIMARY KEY,jurisdiction TEXT,title_number INTEGER,part_number TEXT,celex TEXT,
      seed_json TEXT NOT NULL,seed_sha256 TEXT NOT NULL,official_title TEXT,association_review TEXT,
      fr_effective_on TEXT,updated_at TEXT,effective_status_detail TEXT,part_status TEXT,latest_amendment_date TEXT);
    CREATE TABLE documents(id TEXT PRIMARY KEY,jurisdiction TEXT,kind TEXT,source_identifier TEXT,official_title TEXT,
      language TEXT,version_date TEXT,publication_date TEXT,legal_status TEXT,source_url TEXT,metadata_status TEXT,
      transfer_status TEXT,parse_status TEXT,full_text TEXT,notes TEXT);
    CREATE TABLE law_documents(law_id TEXT REFERENCES laws(id),document_id TEXT REFERENCES documents(id),role TEXT,
      PRIMARY KEY(law_id,document_id,role));
    CREATE TABLE units(document_id TEXT REFERENCES documents(id),ordinal INTEGER,locator TEXT,unit_type TEXT,
      heading TEXT,body TEXT,source_fragment TEXT,PRIMARY KEY(document_id,ordinal));
    CREATE VIRTUAL TABLE documents_fts USING fts5(document_id UNINDEXED,title,body);
    CREATE TABLE events(document_id TEXT,event_type TEXT,date_value TEXT);
    CREATE TABLE blobs(id TEXT); CREATE TABLE artifacts(id TEXT); CREATE TABLE responses(id TEXT);
    ''')
    con.close()


def worker(args):
    path, candidate, sha = args
    return law_content.apply(candidate, sha, path)['action']


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'sample.sqlite3'
        create_db(self.path)
        self.directory = Path(self.tmp.name) / 'staged'

    def candidate(self):
        raw = b'<DIV1 TYPE="TITLE" N="16"><DIV5 TYPE="PART" N="1250"><HEAD>PART 1250 TOY SAFETY</HEAD><DIV8 TYPE="SECTION" N="1250.1"><HEAD>Section 1250.1 Scope</HEAD><P>Official sample text for transaction testing only. This fixture does not represent a real legal requirement.</P></DIV8></DIV5></DIV1>'
        text = 'PART 1250 TOY SAFETY\nSection 1250.1 ScopeOfficial sample text for transaction testing only. This fixture does not represent a real legal requirement.'
        data = {'titles': [{'number': 16, 'latest_issue_date': '2026-10-14'}]}
        with patch.object(law_content, 'fetch', side_effect=[(json.dumps(data).encode(), 'https://www.ecfr.gov/api/versioner/v1/titles.json'), (raw, 'https://www.ecfr.gov/api/versioner/v1/full/2026-10-14/title-16.xml?part=1250')]):
            result = law_content.stage('US:16:1250', self.directory, self.path)
        self.assertTrue(result['ok'], result)
        return result

    def test_missing_and_identifier(self):
        missing = Path(self.tmp.name) / 'missing.sqlite3'
        self.assertFalse(law_store.retrieve('US:16:1250', path=missing)['ok'])
        self.assertFalse(missing.exists())
        self.assertEqual(law_store.law_id('16 CFR Part 1250'), 'US:16:1250')
        self.assertEqual(law_store.law_id("US:16:1250' OR 1=1"), '')

    def test_intake_retrieve_idempotent_backup(self):
        result = self.candidate()
        self.assertFalse(law_store.retrieve('US:16:1250', path=self.path)['ok'])
        applied = law_content.apply(result['candidate'], result['sha256'], self.path)
        self.assertTrue(applied['ok'])
        self.assertTrue(Path(applied['backup']).is_file())
        self.assertEqual(law_content.apply(result['candidate'], result['sha256'], self.path)['action'], 'unchanged')
        rows = law_store.retrieve('16 CFR Part 1250', 'TOY SAFETY', path=self.path)
        self.assertTrue(rows['ok'])
        self.assertEqual(len(rows['units']), 1)
        self.assertFalse(rows['release_eligible'])
        self.assertEqual(law_store.retrieve('US:16:1250', 'UNRELATED', path=self.path)['units'], [])
        with closing(sqlite3.connect(self.path)) as con:
            seed = json.loads(con.execute('SELECT seed_json FROM laws').fetchone()[0])
            self.assertEqual(seed['核对状态'], '待核对')
            self.assertEqual(con.execute('PRAGMA quick_check').fetchone()[0], 'ok')

    def test_process_contention(self):
        result = self.candidate()
        args = (str(self.path), result['candidate'], result['sha256'])
        with concurrent.futures.ProcessPoolExecutor(max_workers=4, mp_context=multiprocessing.get_context('spawn')) as pool:
            actions = list(pool.map(worker, [args] * 12))
        self.assertEqual(actions.count('applied'), 1)
        self.assertEqual(actions.count('unchanged'), 11)
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM laws').fetchone()[0], 1)
            self.assertEqual(con.execute('SELECT COUNT(*) FROM documents_fts').fetchone()[0], 1)

    def test_candidate_changed(self):
        result = self.candidate()
        with self.assertRaises(ValueError):
            law_content.apply(result['candidate'], '0' * 64, self.path)
        path = Path(result['candidate'])
        data = json.loads(path.read_text(encoding='utf-8'))
        data['body'] += 'changed'
        data['sha256'] = law_content.digest(data['body'])
        path.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaises(ValueError):
            law_content.apply(path, data['sha256'], self.path)

    def test_official_type_errors(self):
        for value in [[], {}, None, 12, True]:
            self.assertIs(fresh.sanitize('fr_effective_on', value)[0], fresh.REJECTED)
            self.assertIs(fresh.sanitize('latest_amendment_celex', value)[0], fresh.REJECTED)
        for value in ['32009L0048', '32024R1234', '32024C1234', '32024E1234', '32009L0048R(01)']:
            self.assertEqual(fresh.sanitize('latest_amendment_celex', value)[0], value)
        self.assertIs(fresh.sanitize('id=1', 'value')[0], fresh.REJECTED)
        with patch.object(fresh._fetch_us, 'api_get', return_value={'titles': 'bad'}):
            with self.assertRaises(ValueError):
                fresh.query_us_official(16, '1250')

    def test_us_part_status(self):
        title = {'titles': [{'number': 16, 'latest_issue_date': '2026-10-14'}]}
        tree = {'type': 'title', 'identifier': '16', 'children': [{'type': 'part', 'identifier': '1250', 'label': 'Part 1250 [Removed]'}]}
        with patch.object(fresh._fetch_us, 'api_get', side_effect=[title, tree]), patch.object(fresh._fetch_us, 'get_versions', return_value=('', 0, [], '')), patch.object(fresh, 'query_latest_fr_rule', return_value=None), patch.object(fresh.time, 'sleep'):
            result = fresh.query_us_official(16, '1250')
        self.assertEqual(result['part_status'], 'removed')
        with closing(sqlite3.connect(self.path)) as con:
            self.assertIn('移除', fresh.compute_effective_status_detail(con, {'id': 'US:16:1250', 'jurisdiction': 'US', **result}))
            self.assertIn('待确认', fresh.compute_effective_status_detail(con, {'id': 'US:16:1250', 'jurisdiction': 'US'}))

    def test_split_preserves_full_text(self):
        body = 'Preamble\nPART 1 TITLE\n§ 1.1 Scope\n' + 'x' * 50000
        units = law_content.split_text(body, 'https://www.ecfr.gov')
        self.assertEqual(''.join(u['body'] for u in units), body)
        self.assertLessEqual(max(len(u['body']) for u in units), 12000)

    def test_governance_overlap_and_rollback(self):
        old, new = 'PART 1ÐTitle\nArticle 1\nBody', 'PART 1—Title\nArticle 1\nBody'
        entry = {'id': 'D1', 'old_sha256': gov.sha256_text(old), 'new_sha256': gov.sha256_text(new), 'edits': [[6, '—']]}
        patch_data = {'docs': [entry]}
        with closing(sqlite3.connect(self.path)) as con:
            con.execute('INSERT INTO documents(id,full_text) VALUES(?,?)', ('D1', old))
            con.executemany('INSERT INTO units(document_id,ordinal,body) VALUES(?,?,?)', [('D1', 0, old), ('D1', 1, old[:12])])
            con.commit()
            stats, _, errors = gov.apply_patch(con, patch_data)
            self.assertEqual(errors, [])
            self.assertEqual(stats['applied'], 1)
            self.assertEqual(con.execute('SELECT full_text FROM documents').fetchone()[0], new)
            self.assertEqual(gov.apply_patch(con, patch_data)[0]['already'], 1)
            con.execute('UPDATE documents SET full_text=?', (old,))
            con.execute('UPDATE units SET body=? WHERE ordinal=1', ('unmatched',))
            con.commit()
            stats, _, errors = gov.apply_patch(con, patch_data)
            self.assertTrue(errors)
            self.assertEqual(con.execute('SELECT full_text FROM documents').fetchone()[0], old)


if __name__ == '__main__':
    multiprocessing.freeze_support()
    unittest.main(verbosity=2)
