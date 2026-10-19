# -*- coding: utf-8 -*-
"""时效性检查回归：口径分类、空哈希、代理降级、汇总契约、定时配置一致性。"""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import freshness, net  # noqa: E402


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fresh = load("check_freshness_under_test", "scripts/check_freshness.py")
meta = load("check_metadata_under_test", "scripts/check_metadata_freshness.py")
runner = load("run_checks_under_test", "scripts/run_freshness_checks.py")

BJT = freshness.BJT


class FakeResponse:
    def __init__(self, status=200, body=b"official-content", headers=None):
        self.status = status
        self._body = body
        self.headers = headers or {}

    def read(self, _n=-1):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


class ProxyTests(unittest.TestCase):
    def test_auto_falls_back_when_proxy_is_down(self):
        env = {"HTTP_PROXY": "http://127.0.0.1:7897",
               "HTTPS_PROXY": "http://127.0.0.1:7897"}
        with patch.dict(os.environ, env, clear=True), \
                patch.object(net, "proxy_reachable", return_value=False):
            decision = net.configure_proxy("auto", logger=lambda _m: None)
            self.assertTrue(decision["fallback"])
            self.assertEqual(decision["mode"], "direct")
            self.assertIsNone(os.environ.get("HTTP_PROXY"))
            self.assertEqual(os.environ.get("NO_PROXY"), "*")

    def test_auto_keeps_reachable_proxy(self):
        env = {"HTTP_PROXY": "http://127.0.0.1:7897"}
        with patch.dict(os.environ, env, clear=True), \
                patch.object(net, "proxy_reachable", return_value=True):
            decision = net.configure_proxy("auto", logger=lambda _m: None)
            self.assertEqual(decision["mode"], "proxy")
            self.assertEqual(decision["proxy"], "http://127.0.0.1:7897")

    def test_explicit_proxy_is_redacted(self):
        with patch.dict(os.environ, {}, clear=True):
            decision = net.configure_proxy(
                "http://user:secret@127.0.0.1:7897", logger=lambda _m: None)
            self.assertEqual(decision["proxy"], "http://127.0.0.1:7897")
            self.assertNotIn("secret", json.dumps(decision, ensure_ascii=False))

    def test_direct_mode_clears_proxy(self):
        with patch.dict(os.environ, {"HTTP_PROXY": "http://127.0.0.1:7897"},
                        clear=True):
            decision = net.configure_proxy("direct", logger=lambda _m: None)
            self.assertEqual(decision["mode"], "direct")
            self.assertIsNone(os.environ.get("HTTP_PROXY"))
            self.assertEqual(os.environ.get("NO_PROXY"), "*")


class LinkClassificationTests(unittest.TestCase):
    def test_200_with_content_is_verified(self):
        body = b"official content"
        with patch.object(fresh, "_open",
                          return_value=FakeResponse(200, body,
                                                    {"ETag": '"abc"'})):
            rec = fresh.check_one("https://example.test/a")
        self.assertTrue(rec["ok"])
        self.assertTrue(rec["content_verified"])
        self.assertTrue(rec["http_ok"])
        self.assertEqual(rec["kind"], "ok")
        self.assertEqual(rec["content_bytes"], len(body))
        self.assertEqual(rec["hash"], hashlib.sha256(body).hexdigest()[:16])
        self.assertEqual(rec["etag"], '"abc"')

    def test_202_with_empty_body_is_not_verified(self):
        with patch.object(fresh, "_open", return_value=FakeResponse(202, b"")):
            rec = fresh.check_one("https://eur-lex.europa.eu/example")
        self.assertFalse(rec["ok"])
        self.assertFalse(rec["content_verified"])
        self.assertTrue(rec["http_ok"])
        self.assertEqual(rec["kind"], "empty_content")
        self.assertEqual(rec["hash"], "")
        self.assertIn("empty", rec["error"])

    def test_404_is_link_error(self):
        err = urllib.error.HTTPError("https://example.test", 404,
                                     "Not Found", {}, None)
        with patch.object(fresh, "_open", side_effect=err):
            rec = fresh.check_one("https://example.test/missing")
        self.assertEqual(rec["kind"], "link_error")
        self.assertEqual(rec["status"], 404)
        self.assertFalse(rec["http_ok"])

    def test_network_exception_is_net_error(self):
        with patch.object(fresh, "_open",
                          side_effect=urllib.error.URLError("refused")):
            rec = fresh.check_one("https://example.test/down")
        self.assertEqual(rec["kind"], "net_error")
        self.assertIn("URLError", rec["error"])

    def test_429_is_retried_then_verified(self):
        err = urllib.error.HTTPError("https://www.ecfr.gov/x", 429,
                                     "Too Many Requests",
                                     {"Retry-After": "1"}, None)
        with patch.object(fresh, "_open",
                          side_effect=[err, FakeResponse(200, b"content")]), \
                patch.object(fresh.time, "sleep", return_value=None):
            rec = fresh.check_one("https://www.ecfr.gov/x")
        self.assertEqual(rec["kind"], "ok")
        self.assertTrue(rec["content_verified"])
        self.assertEqual(rec["attempts"], 2)

    def test_429_exhausted_is_rate_limited(self):
        def boom(*_args, **_kwargs):
            raise urllib.error.HTTPError("https://www.ecfr.gov/x", 429,
                                         "Too Many Requests", {}, None)
        with patch.object(fresh, "_open", side_effect=boom), \
                patch.object(fresh, "_throttle", return_value=None), \
                patch.object(fresh.time, "sleep", return_value=None):
            rec = fresh.check_one("https://www.ecfr.gov/x")
        self.assertEqual(rec["kind"], "rate_limited")
        self.assertEqual(rec["status"], 429)
        self.assertEqual(rec["attempts"], fresh.MAX_HTTP_ATTEMPTS)

    def test_changed_requires_two_usable_hashes(self):
        self.assertTrue(fresh._changed({"hash": "aaaa"}, {"hash": "bbbb"}))
        self.assertFalse(fresh._changed({"hash": fresh.EMPTY_HASH},
                                        {"hash": "bbbb"}))
        self.assertFalse(fresh._changed({"hash": ""}, {"hash": "bbbb"}))
        self.assertFalse(fresh._changed({"hash": "aaaa"},
                                        {"hash": fresh.EMPTY_HASH}))

    def test_changed_ignores_hash_source_switch(self):
        self.assertFalse(fresh._changed(
            {"hash": "aaaa", "verified_via": "html"},
            {"hash": "bbbb", "verified_via": "ecfr_api"}))
        self.assertTrue(fresh._changed(
            {"hash": "aaaa", "verified_via": "ecfr_api"},
            {"hash": "bbbb", "verified_via": "ecfr_api"}))


class EcfrFallbackTests(unittest.TestCase):
    def test_api_url_mapping(self):
        self.assertEqual(
            fresh._ecfr_api_url("https://www.ecfr.gov/current/title-16/part-1250"),
            "https://www.ecfr.gov/api/versioner/v1/versions/title-16.json?part=1250")
        self.assertEqual(
            fresh._ecfr_api_url("https://www.ecfr.gov/current/title-21/part-170/"),
            "https://www.ecfr.gov/api/versioner/v1/versions/title-21.json?part=170")
        self.assertEqual(fresh._ecfr_api_url("https://eur-lex.europa.eu/x"), "")

    def test_fingerprint_is_stable_and_content_sensitive(self):
        payload = {
            "meta": {"latest_amendment_date": "2026-01-01",
                     "latest_issue_date": "2025-12-01", "result_count": "2"},
            "content_versions": [
                {"identifier": "1250.1", "date": "2020-01-01",
                 "amendment_date": "2020-01-01", "issue_date": "2020-01-02",
                 "substantive": True, "removed": False},
            ],
        }
        reordered = {
            "content_versions": payload["content_versions"],
            "meta": dict(reversed(list(payload["meta"].items()))),
        }
        self.assertEqual(fresh._ecfr_fingerprint(payload),
                         fresh._ecfr_fingerprint(reordered))
        changed = json.loads(json.dumps(payload))
        changed["content_versions"][0]["amendment_date"] = "2026-02-02"
        self.assertNotEqual(fresh._ecfr_fingerprint(payload),
                            fresh._ecfr_fingerprint(changed))

    def api_body(self):
        return json.dumps({
            "meta": {"latest_amendment_date": "2026-06-15",
                     "latest_issue_date": "2026-06-15", "result_count": "1"},
            "content_versions": [
                {"identifier": "1250.1", "date": "2020-01-01",
                 "amendment_date": "2020-01-01", "issue_date": "2020-01-02",
                 "substantive": True, "removed": False},
            ],
        }).encode("utf-8")

    def test_ecfr_uses_api_first(self):
        with patch.object(fresh, "_open",
                          return_value=FakeResponse(200, self.api_body())), \
                patch.object(fresh, "_throttle", return_value=None):
            rec = fresh.check_one("https://www.ecfr.gov/current/title-16/part-1250")
        self.assertEqual(rec["kind"], "ok")
        self.assertTrue(rec["content_verified"])
        self.assertEqual(rec["verified_via"], "ecfr_api")
        self.assertEqual(rec["api_status"], 200)
        self.assertTrue(rec["hash"])

    def test_api_failure_falls_back_to_html(self):
        err = urllib.error.HTTPError(
            "https://www.ecfr.gov/api/versioner/v1/versions/title-16.json?part=1250",
            429, "Too Many Requests", {"Retry-After": "1"}, None)
        with patch.object(fresh, "_open",
                          side_effect=[err, err, err, err,
                                       FakeResponse(200, b"html content")]), \
                patch.object(fresh, "_throttle", return_value=None), \
                patch.object(fresh.time, "sleep", return_value=None):
            rec = fresh.check_one("https://www.ecfr.gov/current/title-16/part-1250")
        self.assertEqual(rec["kind"], "ok")
        self.assertEqual(rec["verified_via"], "html")
        self.assertEqual(rec["api_status"], 429)


class BackfillTests(unittest.TestCase):
    def test_parse_slot(self):
        self.assertEqual(fresh._parse_slot("2026-10-17 19:00"),
                         datetime(2026, 10, 17, 19, 0, tzinfo=BJT))
        self.assertEqual(fresh._parse_slot("2026-10-18 22:00:00"),
                         datetime(2026, 10, 18, 22, 0, tzinfo=BJT))
        with self.assertRaises(SystemExit):
            fresh._parse_slot("2026/10/17 19:00")

    def test_backfill_writes_slot_and_keeps_actual_time(self):
        rec = {
            "url": "https://example.test/a", "ok": True,
            "content_verified": True, "http_ok": True, "kind": "ok",
            "status": 200, "last_modified": "", "etag": "", "hash": "abc123",
            "content_bytes": 3, "elapsed_ms": 1, "error": "",
            "changed": False, "verified_via": "html", "api_status": None,
            "api_error": "", "attempts": 1,
        }
        with tempfile.TemporaryDirectory() as td:
            latest = Path(td) / "latest.json"
            log = Path(td) / "log.jsonl"
            runs = Path(td) / "runs.jsonl"
            with patch.object(fresh, "LATEST_PATH", str(latest)), \
                    patch.object(fresh, "LOG_PATH", str(log)), \
                    patch.object(fresh, "RUNS_PATH", str(runs)), \
                    patch.object(fresh, "collect_urls",
                                 return_value=["https://example.test/a"]), \
                    patch.object(fresh, "check_one", return_value=dict(rec)), \
                    patch.object(fresh.net, "configure_proxy",
                                 return_value={"mode": "direct"}):
                self.assertEqual(
                    fresh.main(["--slot", "2026-10-17 19:00",
                                "--proxy", "direct"]), 0)
            summary = json.loads(latest.read_text(encoding="utf-8"))
            self.assertEqual(summary["checked_at"], "2026-10-17 19:00:00")
            self.assertTrue(summary["backfilled"])
            self.assertEqual(summary["slot_at"], "2026-10-17 19:00:00")
            self.assertNotEqual(summary["actual_checked_at"],
                                "2026-10-17 19:00:00")
            row = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(row["ts"], "2026-10-17 19:00:00")
            self.assertTrue(row["backfilled"])
            self.assertTrue(row["run_id"].endswith("-backfill"))
            self.assertIn("-p" + str(os.getpid()), row["run_id"])

    def test_read_runs_sorts_by_checked_at(self):
        rows = [
            {"run_id": "a", "checked_at": "2026-10-17 19:00:00"},
            {"run_id": "b", "checked_at": "2026-10-18 22:00:00"},
        ]
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "runs.jsonl"
            path.write_text("\n".join(json.dumps(r) for r in rows) + "\n",
                            encoding="utf-8")
            with patch.object(freshness, "RUNS_PATH", str(path)):
                out = freshness.read_runs(2)
        self.assertEqual([r["checked_at"] for r in out],
                         ["2026-10-18 22:00:00", "2026-10-17 19:00:00"])
        self.assertNotIn("run_id", out[0])

    def test_summarize_uses_checked_at_for_age(self):
        now = datetime(2026, 10, 19, 23, 0, tzinfo=BJT)
        latest = {
            "schema_version": 2, "checked_at": "2026-10-18 22:00:00",
            "total": 1, "content_verified": 1,
        }
        with patch.object(freshness, "read_runs", return_value=[]), \
                patch.object(freshness, "load_metadata_latest", return_value=None), \
                patch.object(freshness, "load_schedule", return_value={
                    "timezone": "Asia/Shanghai",
                    "times": ["19:00", "22:00"], "grace_minutes": 120}):
            out = freshness.summarize(now=now, latest=latest, stale_hours=24)
        self.assertEqual(out["checked_at"], "2026-10-18 22:00:00")
        self.assertTrue(out["stale"])
        self.assertAlmostEqual(out["age_hours"], 25.0, places=1)
        self.assertNotIn("backfilled", out)


class MetadataWriteTests(unittest.TestCase):
    COLUMNS = (
        "id", "jurisdiction", "last_modification_date", "in_force",
        "latest_amendment_celex", "latest_corrigendum_celex",
        "latest_fr_document_number", "fr_effective_on", "official_title",
        "part_status", "latest_amendment_date", "updated_at",
        "effective_status_detail",
    )

    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.con.execute(
            "CREATE TABLE laws(" + ",".join(f"{c} TEXT" for c in self.COLUMNS) + ")")
        self.con.execute(
            "INSERT INTO laws(id,jurisdiction,last_modification_date,in_force) "
            "VALUES(?,?,?,?)",
            ("EU:32009L0125", "EU", "2020-01-01", "1"))

    def tearDown(self):
        self.con.close()

    def law(self):
        return {"id": "EU:32009L0125", "jurisdiction": "EU",
                "last_modification_date": "2020-01-01", "in_force": "1",
                "latest_amendment_celex": None,
                "latest_corrigendum_celex": None}

    def test_updates_valid_fields_and_rejects_dirty_value(self):
        logs = []
        changed = meta.apply_changes(
            self.con, self.law(),
            {"last_modification_date": "2026-01-01", "in_force": "0",
             "latest_amendment_celex": "32025R0001",
             "latest_corrigendum_celex": "9999"},
            False, logs)
        self.assertEqual(changed, 3)
        row = self.con.execute(
            "SELECT last_modification_date,in_force,latest_amendment_celex,"
            "latest_corrigendum_celex,updated_at FROM laws").fetchone()
        self.assertEqual(row[0:3], ("2026-01-01", "0", "32025R0001"))
        self.assertIsNone(row[3])
        self.assertTrue(row[4])
        self.assertEqual(
            sum(1 for r in logs if r["action"] == "auto_updated"), 3)
        self.assertEqual(
            sum(1 for r in logs if r["action"] == "rejected_invalid_value"), 1)

    def test_dry_run_does_not_write(self):
        logs = []
        changed = meta.apply_changes(
            self.con, self.law(),
            {"last_modification_date": "2026-01-01"}, True, logs)
        self.assertEqual(changed, 1)
        row = self.con.execute(
            "SELECT last_modification_date,updated_at FROM laws").fetchone()
        self.assertEqual(row, ("2020-01-01", None))

    def test_combined_related_celex_picks_latest_per_predicate(self):
        rows = [
            {"celex": {"value": "32020R0001"},
             "p": {"value": "http://publications.europa.eu/ontology/cdm#resource_legal_amends_resource_legal"}},
            {"celex": {"value": "32025R0009"},
             "p": {"value": "http://publications.europa.eu/ontology/cdm#resource_legal_amends_resource_legal"}},
            {"celex": {"value": "32021R0002"},
             "p": {"value": "http://publications.europa.eu/ontology/cdm#resource_legal_corrects_resource_legal"}},
        ]
        with patch.object(meta._fetch_eu, "sparql", return_value=rows):
            amend, corr = meta._query_related_celex_both("http://cellar/x")
        self.assertEqual(amend, "32025R0009")
        self.assertEqual(corr, "32021R0002")


class CorpusTests(unittest.TestCase):
    def test_url_field_audit_flags_uncovered_column(self):
        rows = [{"官方链接": "https://a", "ELI标识": "https://b",
                 "其他列": "https://c"}]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            uncovered = fresh.audit_url_fields(rows)
        self.assertEqual(uncovered, [("其他列", 1)])
        self.assertIn("其他列", out.getvalue())

    def test_collect_urls_dedupes_and_keeps_order(self):
        rows = [
            {"官方链接": "https://a", "ELI标识": "https://b"},
            {"官方链接": "https://a", "ELI标识": "not-a-url"},
        ]
        with patch.object(fresh.corpus, "load_corpus", return_value=rows):
            self.assertEqual(fresh.collect_urls(), ["https://a", "https://b"])


class SummaryTests(unittest.TestCase):
    def summarize(self, latest, now, runs=None):
        with patch.object(freshness, "read_runs", return_value=runs or []), \
                patch.object(freshness, "load_metadata_latest", return_value=None), \
                patch.object(freshness, "load_schedule",
                             return_value={"timezone": "Asia/Shanghai",
                                           "times": ["19:00", "22:00"],
                                           "grace_minutes": 120}):
            return freshness.summarize(now=now, latest=latest, stale_hours=24)

    def test_v2_counts_and_freshness(self):
        now = datetime(2026, 10, 19, 20, 0, tzinfo=BJT)
        latest = {
            "schema_version": 2,
            "checked_at": "2026-10-19 19:00:00",
            "total": 3, "http_ok": 2, "content_verified": 2,
            "ok": 2, "empty_content": 1, "link_error": 0, "net_error": 0,
            "changed": 0,
            "pending_links": [{"url": "https://x", "kind": "empty_content"}],
        }
        out = self.summarize(latest, now)
        self.assertFalse(out["stale"])
        self.assertFalse(out["legacy_schema"])
        self.assertEqual(out["content_verified"], 2)
        self.assertEqual(out["empty_content"], 1)
        self.assertEqual(out["age_hours"], 1.0)
        self.assertIn("2/3", out["message"])

    def test_legacy_schema_does_not_claim_verified(self):
        now = datetime(2026, 10, 19, 20, 0, tzinfo=BJT)
        out = self.summarize({"checked_at": "2026-10-19 19:00:00",
                              "total": 86, "ok": 28}, now)
        self.assertTrue(out["legacy_schema"])
        self.assertEqual(out["content_verified"], 0)
        self.assertIn("旧版", out["message"])

    def test_old_check_is_stale(self):
        now = datetime(2026, 10, 19, 20, 0, tzinfo=BJT)
        out = self.summarize({"schema_version": 2,
                              "checked_at": "2026-10-18 10:00:00",
                              "total": 1, "content_verified": 1}, now)
        self.assertTrue(out["stale"])
        self.assertIn("已过期", out["message"])

    def test_no_data_is_first_run(self):
        now = datetime(2026, 10, 19, 20, 0, tzinfo=BJT)
        out = self.summarize(None, now)
        self.assertTrue(out["first_run"])
        self.assertFalse(out["has_data"])

    def test_next_run_slots(self):
        schedule = {"times": ["19:00", "22:00"]}
        cases = [
            (datetime(2026, 10, 19, 18, 0, tzinfo=BJT), datetime(2026, 10, 19, 19, 0, tzinfo=BJT)),
            (datetime(2026, 10, 19, 19, 30, tzinfo=BJT), datetime(2026, 10, 19, 22, 0, tzinfo=BJT)),
            (datetime(2026, 10, 19, 22, 30, tzinfo=BJT), datetime(2026, 10, 20, 19, 0, tzinfo=BJT)),
        ]
        for now, expected in cases:
            self.assertEqual(freshness.next_run(now, schedule), expected)

    def test_parse_checked_at(self):
        self.assertEqual(freshness.parse_checked_at("2026-10-19 19:00:00"),
                         datetime(2026, 10, 19, 19, 0, tzinfo=BJT))
        self.assertEqual(
            freshness.parse_checked_at("2026-10-19T11:00:00+00:00"),
            datetime(2026, 10, 19, 19, 0, tzinfo=BJT))
        self.assertIsNone(freshness.parse_checked_at("not-a-date"))


class ScheduleContractTests(unittest.TestCase):
    def test_schedule_file_is_beijing_19_22(self):
        data = json.loads((ROOT / "data/freshness_schedule.json")
                          .read_text(encoding="utf-8"))
        self.assertEqual(data["timezone"], "Asia/Shanghai")
        self.assertEqual(data["times"], ["19:00", "22:00"])

    def test_windows_installer_matches_schedule(self):
        text = (ROOT / "scripts/install_freshness_schedule.ps1").read_text(
            encoding="utf-8")
        self.assertIn('@("19:00", "22:00")', text)
        self.assertIn("China Standard Time", text)

    def test_github_actions_cron_is_utc_equivalent(self):
        text = (ROOT / ".github/workflows/freshness-check.yml").read_text(
            encoding="utf-8")
        self.assertIn('cron: "0 11,14 * * *"', text)

    def test_metadata_output_lives_in_data(self):
        self.assertTrue(meta.LATEST_PATH.endswith(
            os.path.join("data", "metadata_check_latest.json")))
        self.assertNotIn(os.path.join("sqlite", "metadata_check"), meta.LATEST_PATH)


class CliContractTests(unittest.TestCase):
    def test_metadata_cli_options(self):
        args = meta.parse_args(
            ["--dry-run", "--limit", "5", "--only", "EU",
             "--proxy", "direct", "--backup", "daily"])
        self.assertTrue(args.dry_run)
        self.assertEqual(args.limit, 5)
        self.assertEqual(args.only, "EU")
        self.assertEqual(args.backup, "daily")

    def test_runner_cli_options(self):
        args = runner.parse_args(["--links-only", "--limit", "3",
                                  "--proxy", "auto"])
        self.assertTrue(args.links_only)
        self.assertFalse(args.metadata_only)
        self.assertEqual(args.limit, 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
