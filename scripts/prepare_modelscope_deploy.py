# -*- coding: utf-8 -*-
"""Build a clean ModelScope Studio deployment folder (and optional ZIP).

This is deliberately separate from ``prepare_release.py``:
  * the current SPA needs ``web/`` and ``web_app.py``;
  * the runtime clause bundle is a separate, optional asset;
  * secrets, the 2.23 GB maintenance DB, Windows ASR binaries and the
    demo-capture output must never be uploaded.

Usage:
  .venv\\Scripts\\python.exe scripts\\prepare_modelscope_deploy.py
  .venv\\Scripts\\python.exe scripts\\prepare_modelscope_deploy.py --force --zip
  .venv\\Scripts\\python.exe scripts\\prepare_modelscope_deploy.py \\
      --law-store dist\\law-store-20261020\\law-store.bundle
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = PROJECT / "dist" / "modelscope-deploy"

ROOT_FILES = (
    "app.py", "app_main.py", "ui_chat.py", "web_app.py",
    "requirements.txt", "requirements-asr.txt", "ms_deploy.json",
    "README.md", "LICENSE", "THIRD_PARTY_NOTICES.md",
    ".env.example", ".gitignore", "run_pipeline.bat",
)
SOURCE_DIRS = ("core", "modules", "assets", "web", "scripts")
DATA_FILES = (
    "data/语料核对表_完整版.csv",
    "data/语料核对表_完整版.xlsx",
    "data/语料核对表_骨架总表.csv",
    "data/eu_regulations.csv",
    "data/us_regulations.csv",
    "data/snapshot.json",
    "data/journey_sources.json",
    "data/freshness_latest.json",
    "data/freshness_log.jsonl",
    "data/freshness_runs.jsonl",
    "data/freshness_schedule.json",
    "data/data_quality_report.json",
    "data/audit_attestation.json",
    "data/platform_policy_status.json",
    "data/recall_eval_report.json",
    "data/recall_tree_report.json",
    "data/数据总览.md",
    "data/指南核对报告.md",
    "data/欧盟待补清单.md",
    "data/链接检查报告.txt",
    "data/骨架体检报告.txt",
    "data/m4_replays.jsonl",
)
REQUIRED_FILES = (
    "app.py", "app_main.py", "web_app.py",
    "requirements.txt", "ms_deploy.json",
    "web/index.html", "web/js/main.js", "web/styles/tokens.css",
    "core/llm.py", "core/asr.py", "core/law_store.py",
    "modules/m15_router.py", "modules/m1_map.py",
    "data/语料核对表_完整版.csv", "data/snapshot.json",
    "data/journey_sources.json",
)
BINARY_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".ico", ".woff", ".woff2",
    ".xlsx", ".zip", ".bundle", ".sqlite", ".sqlite3", ".db",
}
TEXT_SUFFIXES = {
    ".py", ".js", ".css", ".html", ".md", ".txt", ".json", ".yml", ".yaml",
    ".toml", ".bat", ".cmd", ".ps1", ".sh", ".csv", ".gitignore", ".example",
}
SKIP_DIR_NAMES = {
    ".git", ".venv", "venv", "env", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", "node_modules", "dist", "build",
    "htmlcov", "logs", "tmp", "temp", "secrets", "credentials",
    "ui-preview", "online-acceptance",
}
SKIP_SUFFIXES = {".pyc", ".pyo", ".log", ".sqlite", ".sqlite3", ".db"}
SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
    re.compile(r"oauth2:[A-Za-z0-9._-]{16,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._-]{24,}"),
)
PLACEHOLDERS = {"your_token_here", "sk-xxx", "", "REPLACE_ME"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_state() -> dict:
    try:
        head = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              cwd=PROJECT, capture_output=True, text=True)
        status = subprocess.run(["git", "status", "--porcelain"],
                                cwd=PROJECT, capture_output=True, text=True)
        return {"git_head": head.stdout.strip(), "dirty": bool(status.stdout.strip())}
    except Exception:  # noqa: BLE001
        return {}


def copy_one(src: Path, dst: Path, files: list[str], prefix: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    files.append(dst.relative_to(prefix).as_posix())


def copy_tree(src: Path, dst: Path, files: list[str], prefix: Path,
              *, allow_suffixes: set[str] | None = None) -> None:
    for folder, dirs, names in os.walk(src):
        current = Path(folder)
        dirs[:] = sorted(
            name for name in dirs
            if name not in SKIP_DIR_NAMES and not name.startswith(".")
        )
        for name in sorted(names):
            source = current / name
            if source.is_symlink() or not source.is_file():
                continue
            if source.suffix.casefold() in SKIP_SUFFIXES:
                continue
            if allow_suffixes is not None and source.suffix.casefold() not in allow_suffixes:
                continue
            target = dst / source.relative_to(src)
            copy_one(source, target, files, prefix)


def scan_secrets(root: Path) -> list[dict]:
    findings: list[dict] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if path.name in {"prepare_modelscope_deploy.py",
                         "verify_modelscope_package.py"}:
            continue  # the scanners themselves contain the search literals
        if path.name == ".env" or (path.name.startswith(".env.") and path.name != ".env.example"):
            findings.append({"path": rel, "line": 0, "kind": "env-file"})
            continue
        if path.suffix.casefold() not in TEXT_SUFFIXES and path.name not in {
                ".gitignore", ".env.example"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            for pattern in SECRET_PATTERNS:
                match = pattern.search(line)
                if match:
                    findings.append({
                        "path": rel, "line": line_no,
                        "kind": "token-like",
                        "match": match.group(0)[:6] + "***",
                    })
            if "MODEL_API_TOKEN=" in line:
                value = line.split("MODEL_API_TOKEN=", 1)[1].strip()
                placeholder = (
                    value in PLACEHOLDERS
                    or value.startswith(("${", "<", "你的"))
                    or "令牌" in value or "token" in value.casefold()
                )
                if not placeholder:
                    findings.append({
                        "path": rel, "line": line_no,
                        "kind": "model-token-assignment",
                    })
    return findings


def validate_law_store(bundle: Path, manifest_path: Path) -> dict:
    if not bundle.is_file():
        raise ValueError(f"条款库 bundle 不存在：{bundle}")
    if not manifest_path.is_file():
        raise ValueError(f"条款库 manifest 不存在：{manifest_path}")
    meta = json.loads(manifest_path.read_text(encoding="utf-8"))
    if meta.get("format") != 1 or meta.get("compression") != "gzip":
        raise ValueError("条款库 manifest 的 format/compression 不受支持")
    if meta.get("asset_path") != "runtime-assets/law-store.bundle":
        raise ValueError("条款库 manifest 的 asset_path 必须是 runtime-assets/law-store.bundle")
    size = bundle.stat().st_size
    digest = sha256(bundle)
    if size != meta.get("bundle_bytes") or digest != meta.get("bundle_sha256"):
        raise ValueError("条款库 bundle 与 manifest 的大小/SHA256 不一致；请重新生成")
    return {
        "bundle_bytes": size,
        "bundle_sha256": digest,
        "database_bytes": meta.get("database_bytes"),
        "database_sha256": meta.get("database_sha256"),
        "tables": meta.get("tables"),
    }


def find_law_store(explicit: str) -> tuple[Path | None, Path | None]:
    if explicit:
        bundle = Path(explicit).expanduser().resolve()
        siblings = [bundle.parent / "law_store_manifest.json",
                    bundle.parent / "law-store-manifest.json"]
        for candidate in siblings:
            if candidate.is_file():
                return bundle, candidate
        repo_manifest = PROJECT / "data" / "law_store_manifest.json"
        if repo_manifest.is_file():
            return bundle, repo_manifest
        return bundle, None
    candidates = [
        (PROJECT / "runtime-assets" / "law-store.bundle",
         PROJECT / "data" / "law_store_manifest.json"),
        (PROJECT / "dist" / "law-store-20261020" / "law-store.bundle",
         PROJECT / "dist" / "law-store-20261020" / "law_store_manifest.json"),
    ]
    for bundle, manifest in candidates:
        if bundle.is_file() and manifest.is_file():
            return bundle, manifest
    return None, None


def build(output: Path, *, force: bool, make_zip: bool, with_docs: bool,
          law_store_arg: str) -> dict:
    output = output.resolve()
    # Allow outputs outside the project, but never let a typo wipe the repo.
    if output == PROJECT or output in PROJECT.parents:
        raise ValueError("拒绝把项目根目录或上级目录作为输出目录")
    if output.exists():
        if not force:
            raise ValueError(f"输出目录已存在：{output}\n确认要重建请加 --force")
        if output.is_dir():
            shutil.rmtree(output)
        else:
            output.unlink()
    output.mkdir(parents=True)

    files: list[str] = []
    for name in ROOT_FILES:
        source = PROJECT / name
        if source.is_file():
            copy_one(source, output / name, files, output)
        elif name in ("app.py", "app_main.py", "web_app.py", "requirements.txt",
                      "ms_deploy.json"):
            raise ValueError(f"缺少必需文件：{name}")

    for name in SOURCE_DIRS:
        source = PROJECT / name
        if not source.is_dir():
            raise ValueError(f"缺少目录：{name}")
        copy_tree(source, output / name, files, output)

    for rel in DATA_FILES:
        source = PROJECT / rel
        if source.is_file():
            copy_one(source, output / rel, files, output)

    if with_docs:
        docs = PROJECT / "docs"
        if docs.is_dir():
            copy_tree(docs, output / "docs", files, output)

    law_bundle, law_manifest = find_law_store(law_store_arg)
    law_info = None
    if law_bundle and law_manifest:
        law_info = validate_law_store(law_bundle, law_manifest)
        copy_one(law_bundle, output / "runtime-assets" / "law-store.bundle",
                 files, output)
        copy_one(law_manifest, output / "data" / "law_store_manifest.json",
                 files, output)
    else:
        print("[warn] 未找到条款库 bundle：条款检索页会显示缺库；"
              "用 --law-store 指定 bundle 后重建。")

    missing = [rel for rel in REQUIRED_FILES if not (output / rel).is_file()]
    if missing:
        raise ValueError("部署包缺少必需文件：\n  " + "\n  ".join(missing))

    deploy_cfg = json.loads((output / "ms_deploy.json").read_text(encoding="utf-8"))
    if deploy_cfg.get("sdk_type") != "gradio":
        raise ValueError("ms_deploy.json 的 sdk_type 必须是 gradio")
    if deploy_cfg.get("sdk_version") != "6.2.0":
        raise ValueError("ms_deploy.json 的 sdk_version 必须是本项目验证过的 6.2.0")

    manifest_entries = []
    for rel in sorted(files):
        path = output / rel
        manifest_entries.append({
            "path": rel,
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        })

    deploy_manifest = {
        "format": 1,
        "entry": "app.py",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": git_state(),
        "law_store": law_info,
        "docs_included": with_docs,
        "files": manifest_entries,
        "total_bytes": sum(item["bytes"] for item in manifest_entries),
        "note": "ModelScope Studio deployment folder. No secrets; .env is never copied.",
    }
    (output / "DEPLOY_MANIFEST.json").write_text(
        json.dumps(deploy_manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    findings = scan_secrets(output)
    zip_path = None
    if make_zip:
        stamp = datetime.now().strftime("%Y%m%d-%H%M")
        zip_path = PROJECT / "dist" / f"ComplianceRadar-modelscope-{stamp}.zip"
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(output.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(output).as_posix())
        with zipfile.ZipFile(zip_path) as archive:
            if archive.testzip() is not None:
                raise ValueError("ZIP 校验失败")
        zip_digest = sha256(zip_path)
        zip_path.with_suffix(".zip.sha256").write_text(
            f"{zip_digest}  {zip_path.name}\n", encoding="utf-8")

    return {
        "output": str(output),
        "files": len(files) + 1,
        "folders": len(list(output.rglob("*"))),
        "total_bytes": deploy_manifest["total_bytes"],
        "zip": str(zip_path) if zip_path else None,
        "zip_bytes": zip_path.stat().st_size if zip_path else None,
        "zip_sha256": sha256(zip_path) if zip_path else None,
        "law_store": law_info,
        "secret_findings": findings,
        "source": deploy_manifest["source"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--force", action="store_true",
                        help="输出目录已存在时先清空")
    parser.add_argument("--zip", action="store_true",
                        help="同时生成可直接网页上传的 ZIP")
    parser.add_argument("--no-docs", action="store_true",
                        help="不包含 docs/（默认包含，排除大图目录）")
    parser.add_argument("--law-store", default="",
                        help="条款库 bundle 路径；缺省自动查找 runtime-assets/ 或 dist/law-store-20261020/")
    args = parser.parse_args()
    try:
        result = build(args.output_dir, force=args.force, make_zip=args.zip,
                       with_docs=not args.no_docs, law_store_arg=args.law_store)
    except (OSError, ValueError) as exc:
        print("打包失败：" + str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["secret_findings"]:
        print("\n[!] 发现疑似密钥，请先处理再上传：", file=sys.stderr)
        for item in result["secret_findings"]:
            print(f"  {item['path']}:{item['line']} {item['kind']}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
