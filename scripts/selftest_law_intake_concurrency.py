"""隔离官方网络响应，验证欧美建档入口的真实多进程插入和日志竞争。"""
from contextlib import closing
import concurrent.futures
import json
import multiprocessing
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from selftest_law_store import create_db


def worker(path, jurisdiction, barrier):
    os.environ['COMPLIANCE_DB_PATH'] = path
    from core import law_intake
    law_intake.DB_PATH = path
    law_intake.SQLITE_DIR = str(Path(path).parent)
    law_intake.INTAKE_LOG_PATH = str(Path(path).with_suffix('.jsonl'))

    def official(*args):
        if jurisdiction == 'US':
            barrier.wait(timeout=90)
        return {'part_status': 'present', 'official_title': 'Concurrent fixture', 'in_force': '1'}

    def cellar(*args):
        barrier.wait(timeout=90)
        return 'fixture:cellar'

    with patch.object(law_intake._freshness, 'query_us_official', side_effect=official), patch.object(law_intake._freshness, 'query_eu_official', side_effect=official), patch.object(law_intake._freshness._fetch_eu, 'find_cellar_uri', side_effect=cellar), patch.object(law_intake._freshness._fetch_eu, 'get_fields', return_value={}), patch.object(law_intake._freshness._fetch_eu, 'pick', return_value=''), patch.object(law_intake._freshness._fetch_eu, 'official_number', return_value='Fixture'), patch.object(law_intake._freshness, 'REQUEST_INTERVAL', 0):
        if jurisdiction == 'US':
            return law_intake.intake_us_law(16, '1250')
        return law_intake.intake_eu_law('32009L0048')


def main():
    ctx = multiprocessing.get_context('spawn')
    results = []
    with tempfile.TemporaryDirectory(prefix='law-intake-') as directory, ctx.Manager() as manager:
        for jurisdiction in ('US', 'EU'):
            path = Path(directory) / (jurisdiction + '.sqlite3')
            create_db(path)
            with closing(sqlite3.connect(path)) as con:
                for name in ('latest_fr_document_number', 'last_modification_date', 'in_force', 'latest_amendment_celex', 'latest_corrigendum_celex'):
                    con.execute('ALTER TABLE laws ADD COLUMN ' + name + ' TEXT')
                con.commit()
            barrier = manager.Barrier(12)
            with concurrent.futures.ProcessPoolExecutor(max_workers=12, mp_context=ctx) as pool:
                futures = [pool.submit(worker, str(path), jurisdiction, barrier) for _ in range(12)]
                outcomes = [future.result(timeout=120) for future in futures]
            actions = [row['action'] for row in outcomes]
            assert actions.count('inserted') == 1, outcomes
            assert actions.count('skipped_exists') == 11, outcomes
            with closing(sqlite3.connect(path)) as con:
                assert con.execute('SELECT COUNT(*) FROM laws').fetchone()[0] == 1
                assert con.execute('SELECT COUNT(*) FROM documents').fetchone()[0] == 0
                assert con.execute('SELECT COUNT(*) FROM units').fetchone()[0] == 0
                assert con.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
                assert con.execute('PRAGMA foreign_key_check').fetchall() == []
                seed = json.loads(con.execute('SELECT seed_json FROM laws').fetchone()[0])
                assert seed['核对状态'] == '待核对'
            records = [json.loads(line) for line in path.with_suffix('.jsonl').read_text(encoding='utf-8').splitlines()]
            assert len(records) == 12, records
            assert sum(row['action'] == 'inserted' for row in records) == 1, records
            assert sum(row['action'] == 'skipped_exists' for row in records) == 11, records
            results.append({'jurisdiction': jurisdiction, 'processes': 12, 'inserted': 1, 'skipped_exists': 11, 'log_records': len(records), 'quick_check': 'ok', 'foreign_key_errors': 0})
    print(json.dumps({'ok': True, 'network': '官方响应以固定夹具隔离，真实多进程调用建档入口', 'results': results}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    multiprocessing.freeze_support()
    main()
