"""Build a reviewable source ZIP from this project; never commit, upload, or deploy.

Run from the final project root:
    .venv\\Scripts\\python.exe scripts\\prepare_release.py --output dist\\ComplianceRadar-ui.zip

Runtime data is selected explicitly rather than inferred from Git tracking/ignore
rules. SQLite archives, user exports, caches, credentials, and environments stay
local. The ZIP opens directly onto app.py (no enclosing project directory).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import zipfile


PROJECT = Path(__file__).resolve().parent.parent
ROOT_FILES = {
    "app.py", "app_main.py", "ui_chat.py", "requirements.txt",
    "requirements-asr.txt", "ms_deploy.json", "README.md", "LICENSE",
    "THIRD_PARTY_NOTICES.md", ".env.example", ".gitignore", "run_pipeline.bat",
}
SOURCE_DIRS = {"core", "modules", "scripts", "assets", "docs", "tools"}
DATA_FILES = {
    "语料核对表_完整版.csv", "语料核对表_骨架总表.csv",
    "eu_regulations.csv", "us_regulations.csv", "snapshot.json",
    "journey_sources.json", "freshness_latest.json", "data_quality_report.json", "law_store_manifest.json",
    "数据总览.md", "指南核对报告.md", "欧盟待补清单.md",
    "链接检查报告.txt", "骨架体检报告.txt",
}
REQUIRED_FILES = {
    "app.py", "app_main.py", "ui_chat.py", "requirements.txt", "ms_deploy.json",
    "assets/chat.css", "assets/chat.js", "core/conversation.py", "core/journey.py",
    "data/语料核对表_完整版.csv", "data/snapshot.json", "data/journey_sources.json",
}
# Missing a transitive import must fail packaging, not first fail on the host.
REQUIRED_FILES.update("core/" + name for name in (
    "__init__.py", "actions.py", "asr.py", "copy_zh.py", "corpus.py", "dates.py",
    "law_content.py", "law_intake.py", "law_store.py", "llm.py", "snapshot.py", "verify.py",
    "model_assets.py", "database_assets.py",
))
REQUIRED_FILES.update("modules/" + name for name in (
    "__init__.py", "m1_map.py", "m15_router.py", "m2_timeline.py", "m3_todo.py",
    "m4_compare.py", "m5_compare.py", "m6_multi_region.py", "m7_opc_readiness.py",
))
PREVIEW_FILES = {
    "01-desktop.png", "02-capabilities.png", "03-stages-expanded.png",
    "04-task-evidence.png", "05-comparison.png", "06-timeline.png", "07-mobile.png",
    "08-mobile-expanded.png",
    "browser-report.json",
}
SKIP_DIRS = {
    ".git", ".agents", ".codex", ".aws", ".ssh", ".venv", "venv", "env",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".cache",
    "node_modules", "dist", "build", "htmlcov", "cache", "logs", "tmp", "temp",
    "secrets", "credentials", "content_staging", "export", "raw", "sqlite",
    "legal_archive",
}
ALLOWED_SUFFIXES = {
    ".py", ".md", ".txt", ".json", ".css", ".js", ".html", ".svg",
    ".png", ".webp", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2",
    ".bat", ".cmd", ".toml", ".yml", ".yaml", ".xlsx", ".patch",
}
SECRET_NAMES = {"credentials.json", "secrets.json", "token", "token.txt", "id_rsa", "id_ed25519"}
SECRET_STEMS = {"credentials", "secrets", "secret", "token", "access_token", "api_key", "api_keys"}
SECRET_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".sqlite", ".sqlite3", ".db"}


def is_link(path: Path) -> bool:
    """Also reject Windows junctions/reparse points on Python 3.11."""
    info = path.lstat()
    return path.is_symlink() or bool(
        getattr(info, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def permitted_file(relative: Path) -> bool:
    lower_parts = tuple(part.casefold() for part in relative.parts)
    name = lower_parts[-1]
    if any(part in SKIP_DIRS or part.startswith(".env") for part in lower_parts[:-1]):
        return False
    if name.startswith(".env") and relative.as_posix() != ".env.example":
        return False
    if (name in SECRET_NAMES or relative.stem.casefold() in SECRET_STEMS
            or relative.suffix.casefold() in SECRET_SUFFIXES
            or (name.startswith(("_cache_", "."))
                and relative.as_posix() not in (".env.example", ".gitignore"))):
        return False
    if len(relative.parts) == 1:
        return relative.name in ROOT_FILES
    if relative.parts[0] == "data":
        return len(relative.parts) == 2 and relative.name in DATA_FILES
    if relative.as_posix() in ("docs/ui-first-pass.png", "scripts/debug_chat_browser.py"):
        return False
    if relative.parts[:2] == ("docs", "ui-preview"):
        return len(relative.parts) == 3 and relative.name in PREVIEW_FILES
    return relative.parts[0] in SOURCE_DIRS and relative.suffix.casefold() in ALLOWED_SUFFIXES


def collect_files(root: Path, include_replays: bool = False) -> list[tuple[Path, str]]:
    selected = []
    for folder, directories, names in os.walk(root, followlinks=False):
        current = Path(folder)
        directories[:] = sorted(
            name for name in directories
            if name.casefold() not in SKIP_DIRS and not name.startswith(".")
            and not is_link(current / name)
            and (current != root or name in SOURCE_DIRS or name == "data")
        )
        for name in sorted(names):
            source = current / name
            relative = source.relative_to(root)
            approved_replay = include_replays and relative.as_posix() == "data/m4_replays.jsonl"
            if not is_link(source) and source.is_file() and (permitted_file(relative) or approved_replay):
                selected.append((source, relative.as_posix()))
    missing = REQUIRED_FILES - {name for _, name in selected}
    if missing:
        raise ValueError("Required release files are missing: " + ", ".join(sorted(missing)))
    return selected


def build_archive(root: Path, output: Path, include_replays: bool = False) -> dict:
    root, output = root.resolve(), output.resolve()
    selected = collect_files(root, include_replays=include_replays)
    if output.suffix.casefold() != ".zip":
        raise ValueError("--output must end in .zip")
    if output.exists():
        raise ValueError("Output already exists; select a new --output path.")
    if output.is_relative_to(root) and output.relative_to(root).parts[0] != "dist":
        raise ValueError("An output inside the project must be under dist/.")
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "format": 1,
        "entry": "app.py",
        "database_included": False,
        "model_replays_included": any(name == "data/m4_replays.jsonl" for _, name in selected),
        "note": "Source package only; no deployment has been performed.",
        "files": [],
    }
    created = False
    try:
        with output.open("xb") as handle:
            created = True
            with zipfile.ZipFile(handle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for source, name in selected:
                    payload = source.read_bytes()
                    archive.writestr(name, payload)
                    manifest["files"].append({
                        "path": name, "bytes": len(payload),
                        "sha256": hashlib.sha256(payload).hexdigest(),
                    })
                archive.writestr(
                    "RELEASE_MANIFEST.json",
                    json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
                )
        with zipfile.ZipFile(output) as archive:
            if archive.testzip() is not None or not REQUIRED_FILES.issubset(archive.namelist()):
                raise ValueError("Archive verification failed.")
    except Exception:
        if created:
            output.unlink(missing_ok=True)
        raise
    return {"output": str(output), "files": len(selected) + 1,
            "bytes": output.stat().st_size, "database_included": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=PROJECT / "dist" / "ComplianceRadar-ui.zip")
    parser.add_argument("--include-replays", action="store_true",
                        help="Include data/m4_replays.jsonl only after reviewing its answers for publication.")
    args = parser.parse_args()
    output = args.output.expanduser()
    if not output.is_absolute():
        output = PROJECT / output
    try:
        result = build_archive(PROJECT, output.resolve(), include_replays=args.include_replays)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print("Package failed: " + str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
