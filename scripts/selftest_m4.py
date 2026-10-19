"""Malformed replay data must not crash queries or mix observation dates."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from modules import m4_compare as m4


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        (self.project / "data").mkdir()
        replacement = patch.object(m4, "PROJECT", str(self.project))
        replacement.start()
        self.addCleanup(replacement.stop)

    def record(self, day):
        return {"timestamp": day + "T12:00:00Z", "observation_date": day,
                "question": m4.build_question(day), "snapshot_version": "test-fixture",
                "generic_answer": "Test fixture only", "tool_answer": "Test fixture only",
                "generic_model_name": "fixture", "tool_conditions": {"category": "儿童玩具"},
                "source_coverage": "unreviewed fixture", "evidence_support": "unreviewed fixture",
                "verdict": "Test data; not a real model recording"}

    def test_invalid_json_shapes_are_skipped(self):
        values = [[], 5, {}, {"generic_answer": "missing metadata"}, self.record("2026-10-19")]
        path = self.project / "data/m4_replays.jsonl"
        path.write_text("broken json\n" + "\n".join(json.dumps(v) for v in values), encoding="utf-8")
        self.assertEqual(len(m4.load_replays()), 1)
        self.assertEqual(m4.query()["观察日期"], "2026-10-19")

    def test_latest_first_and_explicit_date_never_mix(self):
        for day in ("2026-10-18", "2026-10-19", "2026-10-17"):
            m4.append_replay(self.record(day))
        self.assertEqual(m4.query()["观察日期"], "2026-10-19")
        result = m4.query(observation_date="2026-10-18")
        self.assertEqual([r["observation_date"] for r in result["回放列表"]], ["2026-10-18"])
        self.assertEqual(m4.query(observation_date="2026-10-20")["回放列表"], [])

    def test_append_rejects_missing_or_mismatched_provenance(self):
        for change in ({"timestamp": "2026-10-19T12:00:00"}, {"question": "different question"},
                       {"source_coverage": ""}, {"generic_answer": []}, {"tool_conditions": {}}):
            with self.subTest(change=change):
                record = dict(self.record("2026-10-19"), **change)
                with self.assertRaises(ValueError):
                    m4.append_replay(record)
        self.assertFalse((self.project / "data/m4_replays.jsonl").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
