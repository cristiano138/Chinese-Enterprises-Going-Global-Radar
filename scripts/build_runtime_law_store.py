"""Export the four public query tables from the team's full SQLite archive.

The source is opened read-only. Blobs, request/response logs, seed payloads,
reviewer details and duplicate document full_text are never exported.
Run from the project root; outputs are separate assets, not GitHub source files.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
TABLES = {
    "laws": ("id TEXT PRIMARY KEY, jurisdiction TEXT, official_title TEXT",
             ("id", "jurisdiction", "official_title")),
    "documents": ("id TEXT PRIMARY KEY, kind TEXT, source_url TEXT, parse_status TEXT, "
                  "version_date TEXT, language TEXT, official_title TEXT",
                  ("id", "kind", "source_url", "parse_status", "version_date", "language", "official_title")),
    "law_documents": ("law_id TEXT REFERENCES laws(id), document_id TEXT REFERENCES documents(id), role TEXT",
                      ("law_id", "document_id", "role")),
    "units": ("document_id TEXT REFERENCES documents(id), ordinal INTEGER, locator TEXT, "
              "unit_type TEXT, heading TEXT, body TEXT, PRIMARY KEY(document_id,ordinal)",
              ("document_id", "ordinal", "locator", "unit_type", "heading", "body")),
}


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def build(source, bundle, manifest):
    source, bundle, manifest = map(lambda p: Path(p).resolve(), (source, bundle, manifest))
    if not source.is_file():
        raise FileNotFoundError("Full database is missing")
    if bundle.exists() or manifest.exists():
        raise FileExistsError("Choose new asset output paths; existing files are preserved")
    bundle.parent.mkdir(parents=True, exist_ok=True)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    counts = {}
    with tempfile.TemporaryDirectory(prefix="cr-law-export-", dir=bundle.parent) as temp:
        database = Path(temp) / "clauses.sqlite3"
        src = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)
        dst = sqlite3.connect(database)
        try:
            src.execute("BEGIN")
            dst.execute("PRAGMA foreign_keys=ON")
            for table, (schema, columns) in TABLES.items():
                dst.execute("CREATE TABLE " + table + " (" + schema + ")")
                cursor = src.execute("SELECT " + ",".join(columns) + " FROM " + table)
                counts[table] = 0
                while rows := cursor.fetchmany(500):
                    if table == "documents":
                        for row in rows:
                            url = urlsplit(row[columns.index("source_url")] or "")
                            if url.username or url.password or url.scheme not in ("http", "https"):
                                raise ValueError("Document source must be a public HTTP(S) URL")
                    dst.executemany("INSERT INTO " + table + " VALUES(" + ",".join("?" for _ in columns) + ")", rows)
                    counts[table] += len(rows)
            dst.execute("CREATE INDEX law_documents_law ON law_documents(law_id)")
            dst.commit()
            if dst.execute("PRAGMA quick_check").fetchone()[0] != "ok" or dst.execute("PRAGMA foreign_key_check").fetchone():
                raise ValueError("Export integrity check failed")
        finally:
            dst.close()
            src.close()
        payload = {"format": 1, "asset_path": "runtime-assets/law-store.bundle", "compression": "gzip",
                   "database_bytes": database.stat().st_size, "database_sha256": digest(database),
                   "source_database_sha256": digest(source), "source_manifest_sha256": digest(ROOT / "docs/法规资料传输包/数据库分卷manifest.json"),
                   "tables": counts, "release_eligible": False,
                   "scope": "Extracted clauses and provenance from the supplied full database; no automatic legal sign-off"}
        created = False
        try:
            with bundle.open("xb") as output:
                created = True
                with gzip.GzipFile(fileobj=output, mode="wb", filename="", mtime=0) as compressed, database.open("rb") as input_file:
                    shutil.copyfileobj(input_file, compressed, 1024 * 1024)
            payload.update(bundle_bytes=bundle.stat().st_size, bundle_sha256=digest(bundle))
            with manifest.open("x", encoding="utf-8") as output:
                json.dump(payload, output, ensure_ascii=False, indent=2)
        except BaseException:
            # Only the new output owned by this invocation is removed.
            if created:
                bundle.unlink(missing_ok=True)
            raise
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.db, args.bundle, args.manifest), ensure_ascii=False, indent=2))
