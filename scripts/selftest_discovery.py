# -*- coding: utf-8 -*-
"""新法规发现回归：编号映射、去重、FR 映射、LLM 解析、演练不写库。

全部离线：网络函数用桩替换，不访问官方接口、不调用真实模型。
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


disc = load("discover_new_laws_under_test", "scripts/discover_new_laws.py")


class MappingTests(unittest.TestCase):
    def test_celex_to_eli(self):
        self.assertEqual(disc.eli_from_celex("32014L0053"),
                         "http://data.europa.eu/eli/dir/2014/53/oj")
        self.assertEqual(disc.eli_from_celex("32023R0988"),
                         "http://data.europa.eu/eli/reg/2023/988/oj")
        self.assertEqual(disc.eli_from_celex("32026D2284"),
                         "http://data.europa.eu/eli/dec/2026/2284/oj")
        self.assertEqual(disc.eli_from_celex("not-a-celex"), "")

    def test_official_urls(self):
        self.assertEqual(
            disc.eu_official_url("32023R0988"),
            "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32023R0988")
        self.assertEqual(disc.us_official_url(16, "1461"),
                         "https://www.ecfr.gov/current/title-16/part-1461")

    def test_parse_llm_lines(self):
        text = "\n".join([
            "1|||是|||儿童玩具|||新玩具安全要求",
            "2|||否|||其他|||关税措施",
            "3|||不确定|||其他|||信息不足",
            "bad line",
            "4|||是|||",
        ])
        parsed = disc.parse_llm_lines(text)
        self.assertTrue(parsed[1]["relevant"])
        self.assertFalse(parsed[2]["relevant"])
        self.assertIsNone(parsed[3]["relevant"])
        self.assertNotIn(4, parsed)
        self.assertEqual(parsed[1]["category"], "儿童玩具")


class DatabaseDedupeTests(unittest.TestCase):
    def make_db(self):
        tmp = tempfile.TemporaryDirectory()
        path = Path(tmp.name) / "laws.sqlite3"
        con = sqlite3.connect(path)
        con.execute(
            "CREATE TABLE laws(id TEXT PRIMARY KEY, jurisdiction TEXT, "
            "title_number INTEGER, part_number TEXT, celex TEXT)")
        con.execute("INSERT INTO laws VALUES('EU:32014L0053','EU',NULL,NULL,"
                    "'32014L0053')")
        con.execute("INSERT INTO laws VALUES('US:16:1250','US',16,'1250',NULL)")
        con.commit()
        con.close()
        self.addCleanup(tmp.cleanup)
        return path

    def test_load_existing(self):
        path = self.make_db()
        existing = disc.load_existing(str(path))
        self.assertEqual(existing["eu"], {"32014L0053"})
        self.assertEqual(existing["us"], {(16, "1250")})
        self.assertEqual(existing["us_titles"], [16])
        self.assertEqual(existing["total"], 2)

    def test_query_eu_works_dedupes_celex(self):
        rows = [
            {"celex": {"value": "32026R9999"}, "date": {"value": "2026-10-02"}},
            {"celex": {"value": "32026R9999"}, "date": {"value": "2026-10-01"}},
            {"celex": {"value": "bad"}, "date": {"value": "2026-10-01"}},
        ]
        with patch.object(disc._fetch_eu, "sparql", return_value=rows):
            works = disc.query_eu_works("2026-10-01", "2026-10-19", 10)
        self.assertEqual(works, [{"celex": "32026R9999",
                                  "published_on": "2026-10-02"}])

    def test_discover_eu_skips_existing(self):
        path = self.make_db()
        existing = disc.load_existing(str(path))
        works = [
            {"celex": "32014L0053", "published_on": "2026-10-01"},
            {"celex": "32026R9999", "published_on": "2026-10-02"},
        ]
        meta = {"32026R9999": {"title": "Test Regulation", "eli": ""}}
        with patch.object(disc, "query_eu_works", return_value=works), \
                patch.object(disc, "query_eu_titles", return_value=meta):
            candidates, stat = disc.discover_eu(
                "2026-10-01", "2026-10-19", existing, 10)
        self.assertEqual([c["celex"] for c in candidates], ["32026R9999"])
        self.assertEqual(stat["skipped_exists"], 1)
        self.assertEqual(candidates[0]["official_title"], "Test Regulation")
        # SPARQL 没给 ELI 时用 CELEX 兜底
        self.assertEqual(candidates[0]["eli"],
                         "http://data.europa.eu/eli/reg/2026/9999/oj")


class FederalRegisterTests(unittest.TestCase):
    def doc(self, number, date, refs, title="Rule title"):
        return {
            "document_number": number,
            "title": title,
            "publication_date": date,
            "effective_on": "2026-11-01",
            "cfr_references": refs,
            "agencies": [{"name": "Consumer Product Safety Commission"}],
            "html_url": f"https://www.federalregister.gov/documents/{number}",
            "abstract": "abstract",
            "type": "Rule",
        }

    def test_maps_cfr_refs_dedupes_and_keeps_latest_evidence(self):
        existing = {"us": {(16, "1250")}, "eu": set(), "us_titles": [16],
                    "total": 1}
        docs = [
            self.doc("A", "2026-10-19",
                     [{"title": 16, "part": "1250"},
                      {"title": 16, "part": "1461"}]),
            # 同一条规则在不同查询里重复出现 / 后一份证据更旧 → 保留 A
            self.doc("B", "2026-10-18", [{"title": 16, "part": "1461"}]),
            # 只引用已存在的 Part → 属于既有法规修订，不算新法规
            self.doc("D", "2026-10-16", [{"title": 16, "part": "1250"}]),
            # 没有 CFR 映射 → 无法建档，单列计数
            self.doc("C", "2026-10-17", []),
        ]
        with patch.object(disc, "query_fr_documents", return_value=docs):
            candidates, stat = disc.discover_us(
                "2026-10-01", "2026-10-19", existing, 100, [16])
        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate["law_id"], "US:16:1461")
        self.assertEqual(candidate["new_parts"],
                         [{"title": 16, "part": "1461"}])
        self.assertEqual(candidate["cfr_references"],
                         [{"title": 16, "part": "1250"},
                          {"title": 16, "part": "1461"}])
        self.assertEqual(candidate["evidence_url"],
                         "https://www.federalregister.gov/documents/A")
        self.assertEqual(stat["skipped_exists"], 1)
        self.assertEqual(stat["unmapped"], 1)

    def test_title_filter_ignores_other_titles(self):
        existing = {"us": set(), "eu": set(), "us_titles": [16], "total": 0}
        docs = [self.doc("A", "2026-10-19",
                         [{"title": 21, "part": "101"}]),
                self.doc("B", "2026-10-19",
                         [{"title": 16, "part": "../evil"}])]
        with patch.object(disc, "query_fr_documents", return_value=docs):
            candidates, stat = disc.discover_us(
                "2026-10-01", "2026-10-19", existing, 100, [16])
        self.assertEqual(candidates, [])
        self.assertEqual(stat["unmapped"], 2)


class WebToolTests(unittest.TestCase):
    def test_web_search_clamps_count_and_returns_results(self):
        from core import llm
        results = [{"url": "https://example.test/a"}]
        with patch.object(llm, "_web_post",
                          return_value=({"results": results}, {"ok": True})) as post:
            got, meta = llm.web_search("q", count=999)
        self.assertEqual(got, results)
        self.assertTrue(meta["ok"])
        self.assertEqual(post.call_args[0][1]["count"], 50)

    def test_web_fetch_returns_title_and_content(self):
        from core import llm
        with patch.object(llm, "_web_post",
                          return_value=({"title": "T", "content": "C"},
                                       {"ok": True})):
            page, meta = llm.web_fetch("https://example.test/a")
        self.assertEqual(page, {"title": "T", "content": "C"})
        self.assertTrue(meta["ok"])

    def test_web_post_without_config_does_not_raise(self):
        from core import llm
        with patch.object(llm, "READY", False):
            data, meta = llm._web_post("/v1/tools/search", {})
        self.assertIsNone(data)
        self.assertFalse(meta["ok"])
        self.assertIn("未配置", meta["reason"])


class WebConflictTests(unittest.TestCase):
    def hit(self, url, title="测试法规"):
        return {"url": url, "title": title, "summary": "summary",
                "snippet": "snippet", "date": None, "authority": 4}

    def existing(self):
        return {"eu": set(), "us": set(), "us_titles": [16], "total": 0}

    def test_api_missing_is_conflict_not_candidate(self):
        from core import llm
        hit = self.hit("https://eur-lex.europa.eu/legal-content/EN/TXT/"
                       "?uri=CELEX:32026R9999")
        with patch.object(llm, "is_ready", return_value=True), \
                patch.object(llm, "web_search", return_value=([hit], {"ok": True})), \
                patch.object(disc, "verify_eu_celex",
                             return_value=(False, "http_404")):
            candidates, conflicts, stat = disc.discover_web(
                "2026-09-20", "2026-10-20", self.existing(), [16], {"EU"},
                custom_queries=[("儿童玩具", "EU", "q")])
        self.assertEqual(candidates, [])
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["identifier"], "EU:32026R9999")
        self.assertEqual(conflicts[0]["visibility"], "admin_only")
        self.assertEqual(conflicts[0]["status"], "pending_review")
        self.assertEqual(stat["unverified"], 1)

    def test_network_error_is_not_a_conflict(self):
        from core import llm
        hit = self.hit("https://eur-lex.europa.eu/legal-content/EN/TXT/"
                       "?uri=CELEX:32026R9999")
        with patch.object(llm, "is_ready", return_value=True), \
                patch.object(llm, "web_search", return_value=([hit], {"ok": True})), \
                patch.object(disc, "verify_eu_celex",
                             return_value=(False, "network:URLError")):
            candidates, conflicts, stat = disc.discover_web(
                "2026-09-20", "2026-10-20", self.existing(), [16], {"EU"},
                custom_queries=[("儿童玩具", "EU", "q")])
        self.assertEqual(candidates, [])
        self.assertEqual(conflicts, [])
        self.assertEqual(stat["unverified"], 1)

    def test_fr_404_is_conflict(self):
        from core import llm
        hit = self.hit("https://www.federalregister.gov/documents/"
                       "2026/10/19/2026-99999/test")
        with patch.object(llm, "is_ready", return_value=True), \
                patch.object(llm, "web_search", return_value=([hit], {"ok": True})), \
                patch.object(disc, "verify_fr_document",
                             return_value=(None, "http_404")):
            candidates, conflicts, _stat = disc.discover_web(
                "2026-09-20", "2026-10-20", self.existing(), [16], {"US"},
                custom_queries=[("儿童玩具", "US", "q")])
        self.assertEqual(candidates, [])
        self.assertEqual(conflicts[0]["identifier"], "US-FR:2026-99999")
        self.assertIn("fr_document_number", conflicts[0])

    def test_write_conflicts_appends_and_writes_latest(self):
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "conflicts.jsonl"
            latest = Path(td) / "conflicts.json"
            record = {"identifier": "EU:32026R9999",
                      "detected_at": "2026-10-20 00:00:00",
                      "visibility": "admin_only",
                      "verification": {"reason": "http_404"}}
            with patch.object(disc, "CONFLICT_LOG_PATH", str(log)), \
                    patch.object(disc, "CONFLICT_LATEST_PATH", str(latest)):
                disc.write_conflicts([dict(record)])
                disc.write_conflicts([dict(record, detected_at="2026-10-21 00:00:00")])
            self.assertEqual(len(log.read_text(encoding="utf-8").splitlines()), 2)
            snapshot = json.loads(latest.read_text(encoding="utf-8"))
            self.assertEqual(snapshot["visibility"], "admin_only")
            self.assertEqual(snapshot["count"], 1)
            item = snapshot["items"][0]
            self.assertEqual(item["identifier"], "EU:32026R9999")
            self.assertEqual(item["seen_count"], 2)
            self.assertEqual(item["first_seen"], "2026-10-20 00:00:00")
            self.assertEqual(item["last_seen"], "2026-10-21 00:00:00")


class SeenStateTests(unittest.TestCase):
    def test_first_seen_and_new_flag(self):
        from datetime import datetime
        now = datetime(2026, 10, 20, 0, 0, tzinfo=disc.BJT)
        previous = {"EU:32014L0053": "2026-10-01 00:00:00",
                    "EU:32000R0001": "2020-01-01 00:00:00"}
        candidates = [{"law_id": "EU:32014L0053"},
                      {"law_id": "EU:32026R9999"}]
        kept, new_count = disc.mark_seen(candidates, previous, now)
        self.assertFalse(candidates[0]["is_new"])
        self.assertEqual(candidates[0]["first_seen"], "2026-10-01 00:00:00")
        self.assertTrue(candidates[1]["is_new"])
        self.assertEqual(candidates[1]["first_seen"], "2026-10-20 00:00:00")
        self.assertEqual(new_count, 1)
        # 超过 180 天的旧状态被清理，防止文件无限增长
        self.assertNotIn("EU:32000R0001", kept)


class IntakeWriteTests(unittest.TestCase):
    """确认 --intake 真的只建骨架、且不重复备份整个库。"""

    SCHEMA = """
    CREATE TABLE laws(
      id TEXT PRIMARY KEY, jurisdiction TEXT NOT NULL, title_number INTEGER,
      part_number TEXT, celex TEXT, seed_json TEXT NOT NULL,
      seed_sha256 TEXT NOT NULL, official_title TEXT,
      association_review TEXT, last_modification_date TEXT, in_force TEXT,
      latest_amendment_celex TEXT, latest_corrigendum_celex TEXT,
      latest_fr_document_number TEXT, fr_effective_on TEXT, updated_at TEXT,
      effective_status_detail TEXT)
    """

    def test_eu_intake_writes_skeleton(self):
        from core import law_intake

        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "laws.sqlite3"
            con = sqlite3.connect(db)
            con.execute(self.SCHEMA)
            con.commit()
            con.close()

            old = (law_intake.DB_PATH, law_intake.SQLITE_DIR,
                   law_intake.INTAKE_LOG_PATH, law_intake._freshness.REQUEST_INTERVAL)
            law_intake.DB_PATH = str(db)
            law_intake.SQLITE_DIR = td
            law_intake.INTAKE_LOG_PATH = str(Path(td) / "law_intake_log.jsonl")
            law_intake._freshness.REQUEST_INTERVAL = 0
            fields = {
                "expression_title": ["Test Regulation"],
                "resource_legal_eli": ["http://data.europa.eu/eli/reg/2026/9999/oj"],
                "resource_legal_type": ["R"],
                "resource_legal_year": ["2026"],
                "resource_legal_number_natural": ["9999"],
            }
            try:
                with patch.object(law_intake._freshness, "query_eu_official",
                                  return_value={"last_modification_date": "2026-10-16",
                                                "in_force": "1"}), \
                        patch.object(law_intake._freshness._fetch_eu,
                                     "find_cellar_uri",
                                     return_value="http://cellar/x"), \
                        patch.object(law_intake._freshness._fetch_eu,
                                     "get_fields", return_value=fields), \
                        patch.object(disc, "_backup_once", return_value=None):
                    results = disc.intake_candidates(
                        [{"law_id": "EU:32026R9999", "jurisdiction": "EU",
                          "celex": "32026R9999", "published_on": "2026-10-16",
                          "llm": {"relevant": True, "category": "儿童玩具"}}],
                        SimpleNamespace(category="", intake_limit=5), str(db))
            finally:
                (law_intake.DB_PATH, law_intake.SQLITE_DIR,
                 law_intake.INTAKE_LOG_PATH,
                 law_intake._freshness.REQUEST_INTERVAL) = old

            self.assertEqual(results[0]["action"], "inserted")
            con = sqlite3.connect(db)
            row = con.execute("SELECT id, celex, official_title FROM laws").fetchone()
            con.close()
            self.assertEqual(row, ("EU:32026R9999", "32026R9999",
                                   "Test Regulation"))
            log = Path(td) / "law_intake_log.jsonl"
            self.assertTrue(log.exists())
            self.assertEqual(json.loads(log.read_text(encoding="utf-8").splitlines()[0])
                             ["action"], "inserted")


class IntakeGuardTests(unittest.TestCase):
    def candidate(self):
        return {
            "law_id": "EU:32026R9999", "jurisdiction": "EU",
            "celex": "32026R9999", "published_on": "2026-10-16",
            "llm": {"relevant": True, "category": "儿童玩具"},
        }

    def test_dry_run_never_backs_up_or_writes(self):
        args = SimpleNamespace(category="", intake_limit=5)
        with patch.object(disc, "_backup_once",
                          side_effect=AssertionError("dry-run 不应备份")):
            results = disc.intake_candidates(
                [self.candidate()], args, "unused.sqlite3", dry_run=True)
        self.assertEqual(results[0]["action"], "dry_run")
        self.assertTrue(results[0]["ok"])

    def test_us_multi_part_intake_limit_counts_laws(self):
        candidate = {
            "jurisdiction": "US", "law_id": "US:16:1",
            "title_number": 16, "part_number": "1",
            "new_parts": [{"title": 16, "part": "1"},
                          {"title": 16, "part": "2"},
                          {"title": 16, "part": "3"}],
            "llm": {"relevant": True, "category": "电子电器"},
        }
        args = SimpleNamespace(category="", intake_limit=2)
        results = disc.intake_candidates(
            [candidate], args, "unused.sqlite3", dry_run=True)
        self.assertEqual([r["law_id"] for r in results],
                         ["US:16:1", "US:16:2"])

    def test_build_report_counts(self):
        args = SimpleNamespace(db="x.sqlite3")
        candidates = [
            {"jurisdiction": "EU", "law_id": "EU:1", "published_on": "2026-10-16",
             "llm": {"relevant": True}},
            {"jurisdiction": "US", "law_id": "US:16:1",
             "published_on": "2026-10-15", "llm": {"relevant": False}},
        ]
        stats = [{"source": "EU", "ok": True, "scanned": 3,
                  "skipped_exists": 1, "candidates": 2}]
        report = disc.build_report(
            args, "2026-10-01", "2026-10-19",
            {"total": 86, "eu": {"x"}, "us": {"y"}}, candidates, stats,
            [{"ok": True}])
        self.assertEqual(report["counts"]["candidates"], 2)
        self.assertEqual(report["counts"]["llm_relevant"], 1)
        self.assertEqual(report["counts"]["intaked"], 1)
        json.dumps(report, ensure_ascii=False)  # 必须可序列化


if __name__ == "__main__":
    unittest.main(verbosity=2)
