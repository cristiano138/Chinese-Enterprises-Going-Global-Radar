"""Corrupt assets fail closed and existing databases are never replaced."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.database_assets import ensure_bundled_database


class AssetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "data").mkdir()
        (self.root / "runtime-assets").mkdir()
        self.manifest_path = self.root / "data/law_store_manifest.json"
        self.bundle = self.root / "runtime-assets/law-store.bundle"
        self.target = self.root / "sqlite/regulations.sqlite3"
        source = self.root / "fixture.sqlite3"
        con = sqlite3.connect(source)
        for table in ("laws", "documents", "law_documents", "units"):
            con.execute("CREATE TABLE " + table + " (id TEXT)")
        con.close()
        self.content = source.read_bytes()
        self.bundle.write_bytes(gzip.compress(self.content, mtime=0))
        self.manifest = {"format": 1, "compression": "gzip", "database_bytes": len(self.content),
                         "database_sha256": hashlib.sha256(self.content).hexdigest(),
                         "bundle_bytes": self.bundle.stat().st_size,
                         "bundle_sha256": hashlib.sha256(self.bundle.read_bytes()).hexdigest()}
        self.save()
        env = patch.dict(os.environ, {"COMPLIANCE_DB_PATH": ""})
        env.start()
        self.addCleanup(env.stop)

    def save(self):
        self.manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")

    def test_verified_asset_and_repeat_noop(self):
        self.assertTrue(ensure_bundled_database(self.root))
        self.assertEqual(self.target.read_bytes(), self.content)
        self.assertFalse(ensure_bundled_database(self.root))
        self.assertEqual(list(self.target.parent.glob(".clauses-*")), [])

    def test_existing_or_configured_database_is_preserved(self):
        with patch.dict(os.environ, {"COMPLIANCE_DB_PATH": "custom.sqlite3"}):
            self.assertFalse(ensure_bundled_database(self.root))
        self.assertFalse(self.target.exists())
        self.target.parent.mkdir()
        self.target.write_bytes(b"User-owned database")
        self.assertFalse(ensure_bundled_database(self.root))
        self.assertEqual(self.target.read_bytes(), b"User-owned database")

    def test_corrupt_bundle_never_creates_database(self):
        self.bundle.write_bytes(self.bundle.read_bytes()[:-10])
        with self.assertRaises(ValueError):
            ensure_bundled_database(self.root)
        self.assertFalse(self.target.exists())

    def test_size_or_hash_failure_cleans_temporary_output(self):
        for field, value in (("database_bytes", len(self.content) - 1), ("database_sha256", "0" * 64)):
            with self.subTest(field=field):
                old = self.manifest[field]
                self.manifest[field] = value
                self.save()
                with self.assertRaises(ValueError):
                    ensure_bundled_database(self.root)
                self.assertFalse(self.target.exists())
                self.assertEqual(list(self.target.parent.glob(".clauses-*")), [])
                self.manifest[field] = old


if __name__ == "__main__":
    unittest.main(verbosity=2)
