"""Prepare an optional, verified public-clause asset without replacing a user's DB."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile

ROOT = Path(__file__).resolve().parent.parent


def _digest(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_bundled_database(root=ROOT):
    root = Path(root).resolve()
    target = root / "sqlite/regulations.sqlite3"
    if os.getenv("COMPLIANCE_DB_PATH", "").strip() or target.exists():
        return False
    metadata = root / "data/law_store_manifest.json"
    bundle = root / "runtime-assets/law-store.bundle"
    if not metadata.is_file() or not bundle.is_file():
        return False
    manifest = json.loads(metadata.read_text(encoding="utf-8"))
    expected = manifest.get("database_bytes")
    if (manifest.get("format") != 1 or manifest.get("compression") != "gzip"
            or type(expected) is not int or not 0 < expected <= 512 * 1024 * 1024):
        raise ValueError("Invalid public database manifest")
    if bundle.stat().st_size != manifest.get("bundle_bytes") or _digest(bundle) != manifest.get("bundle_sha256"):
        raise ValueError("Public database bundle failed verification")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        count, digest = 0, hashlib.sha256()
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".clauses-", delete=False) as output:
            temporary = Path(output.name)
            with gzip.open(bundle, "rb") as compressed:
                while chunk := compressed.read(1024 * 1024):
                    count += len(chunk)
                    if count > expected:
                        raise ValueError("Public database exceeds expected size")
                    output.write(chunk)
                    digest.update(chunk)
        if count != expected or digest.hexdigest() != manifest.get("database_sha256"):
            raise ValueError("Public database content failed verification")
        con = sqlite3.connect(temporary.as_uri() + "?mode=ro", uri=True)
        try:
            tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {"laws", "documents", "law_documents", "units"}.issubset(tables):
                raise ValueError("Public database schema is incomplete")
            if con.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("Public database integrity check failed")
        finally:
            con.close()
        # Atomic creation that fails if another process or user supplied a DB.
        try:
            os.link(temporary, target)
        except FileExistsError:
            return False
        return True
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
