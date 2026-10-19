"""Offline checks for incomplete deployment asset recovery and atomic replacement."""
import hashlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import model_assets as assets


class AssetTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.path = self.root / assets.MODEL_PATH
        self.path.parent.mkdir(parents=True)
        self.payload = b"public synthetic model bytes"
        self.sha = hashlib.sha256(self.payload).hexdigest()
        self.pointer = (f"version https://git-lfs.github.com/spec/v1\noid sha256:{self.sha}\nsize {len(self.payload)}\n").encode()

    def test_absent_or_real_model_does_not_use_network(self):
        with patch.object(assets, "urlopen") as request:
            self.assertFalse(assets.ensure_bundled_whisper(self.root))
            self.path.write_bytes(self.payload)
            self.assertFalse(assets.ensure_bundled_whisper(self.root))
            request.assert_not_called()

    def test_valid_download_replaces_pointer(self):
        self.path.write_bytes(self.pointer.replace(b"\n", b"\r\n"))
        with patch.object(assets, "SIZE", len(self.payload)), patch.object(assets, "SHA256", self.sha), patch.object(assets, "urlopen", return_value=io.BytesIO(self.payload)):
            self.assertTrue(assets.ensure_bundled_whisper(self.root))
        self.assertEqual(self.path.read_bytes(), self.payload)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_short_corrupt_oversized_or_failed_download_keeps_pointer(self):
        for payload in (b"short", b"x" * len(self.payload), self.payload + b"extra", None):
            with self.subTest(payload=payload):
                self.path.write_bytes(self.pointer)
                kwargs = {"side_effect": OSError("network unavailable")} if payload is None else {"return_value": io.BytesIO(payload)}
                with patch.object(assets, "SIZE", len(self.payload)), patch.object(assets, "SHA256", self.sha), patch.object(assets, "urlopen", **kwargs):
                    with self.assertRaises((ValueError, OSError)):
                        assets.ensure_bundled_whisper(self.root)
                self.assertEqual(self.path.read_bytes(), self.pointer)
                self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_unknown_pointer_does_not_use_network(self):
        self.path.write_bytes(self.pointer)
        with patch.object(assets, "urlopen") as request:
            with self.assertRaises(ValueError):
                assets.ensure_bundled_whisper(self.root)
            request.assert_not_called()

    def test_timeout_cleans_temporary_file_and_keeps_pointer(self):
        self.path.write_bytes(self.pointer)
        with patch.object(assets, "SIZE", len(self.payload)), patch.object(assets, "SHA256", self.sha), patch.object(assets, "urlopen", return_value=io.BytesIO(self.payload)), patch.object(assets.time, "monotonic", side_effect=[0, 91]):
            with self.assertRaises(TimeoutError):
                assets.ensure_bundled_whisper(self.root)
        self.assertEqual(self.path.read_bytes(), self.pointer)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])


if __name__ == "__main__":
    unittest.main()
