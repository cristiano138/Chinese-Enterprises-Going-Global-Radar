# -*- coding: utf-8 -*-
"""
新法规/变更材料落库（scripts/ingest_law_material.py）

用途：
    时效性脚本或搜索校验 agent 发现新法规/修订后，`core/law_intake.py` 只建
    骨架（laws 行），不抓全文、不切 units。本脚本接收一个**材料 manifest**
    （由 agent/外部解析器生成），把 documents / law_documents / units 写入
    SQLite，随后可重建召回目录树。

    这是“发现 -> 建档 -> 材料落库 -> 召回树”链路的落库环节：
        core/law_intake.py -> ingest_law_material.py -> build_recall_tree.py

manifest 格式（JSON）：
    {
      "law_id": "EU:32026R9999",
      "documents": [
        {
          "id": "EU-DOC:32026R9999",
          "kind": "eu_original",              # 必填
          "source_identifier": "32026R9999",  # 必填
          "official_title": "...",
          "language": "en",
          "version_date": "2026-01-01",
          "publication_date": "2026-01-01",
          "legal_status": "current",          # 必填
          "source_url": "https://...",        # 必填
          "full_text": "...",
          "role": "primary",                  # primary / eu_consolidated / ...
          "replace_units": true,              # true=先删该文档旧 units 再写
          "parse_status": "extracted_unreviewed",
          "metadata_status": "pending",
          "transfer_status": "pending",
          "notes": ""
        }
      ],
      "units": [
        {
          "document_id": "EU-DOC:32026R9999",
          "ordinal": 0,                       # 必填，文档内唯一
          "locator": "https://...#art_1",     # 必填
          "unit_type": "article",             # 必填
          "heading": "Article 1 — Subject matter",
          "body": "Article 1\\nSubject matter\\n...",  # 必填
          "source_fragment": "<html:div ...>"          # 可选
        }
      ]
    }

用法：
    python scripts/ingest_law_material.py --manifest m.json --dry-run
    python scripts/ingest_law_material.py --manifest m.json
    python scripts/ingest_law_material.py --manifest m.json --rebuild
    python scripts/ingest_law_material.py --manifest m.json --db copy.sqlite3

退出码：0 成功；1 校验失败；2 用法/DB/schema 错误。
"""

import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
GO_RADAR_ROOT = os.path.dirname(HERE)
PROJECT = GO_RADAR_ROOT  # 项目根目录就是 GO_RADAR_ROOT；上一级是 workbuddy 工作区
if GO_RADAR_ROOT not in sys.path:
    sys.path.insert(0, GO_RADAR_ROOT)
from core import law_store  # noqa: E402

# 与 core.law_store 保持同一套查找规则：优先 <项目>/sqlite，其次 <工作区>/sqlite。
DB_PATH = str(law_store.db_path())
SQLITE_DIR = os.path.dirname(DB_PATH)
BUILD_SCRIPT = os.path.join(HERE, "build_recall_tree.py")
DEFAULT_REPORT = os.path.join(GO_RADAR_ROOT, "data", "material_ingest_report.json")

ALLOWED_ROLES = {
    "primary", "eu_consolidated", "eu_amendment", "eu_corrigendum",
    "rule_publication", "bulk_fallback", "annual_reference",
    "cited_source_reference",
}
STRUCTURED_TYPES = ("article", "annex", "section", "subpart", "appendix")

DOC_COLUMNS = (
    "id", "jurisdiction", "kind", "source_identifier", "official_title",
    "language", "version_date", "publication_date", "legal_status",
    "source_url", "metadata_status", "transfer_status", "parse_status",
    "full_text", "notes",
)


def connect(path=None):
    con = sqlite3.connect(path or DB_PATH)
    con.text_factory = str
    return con


def load_manifest(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("manifest 顶层必须是 JSON 对象")
    return data


def _law(con, law_id):
    row = con.execute(
        "SELECT id, jurisdiction, official_title, seed_json FROM laws WHERE id=?",
        (law_id,),
    ).fetchone()
    return row


def _linked_docs(con, law_id):
    rows = con.execute(
        "SELECT document_id, role FROM law_documents WHERE law_id=?", (law_id,)
    ).fetchall()
    return {r[0] for r in rows}, {r[0]: r[1] for r in rows}


def validate_manifest(con, manifest):
    """返回 dict(ok, errors, warnings, law, docs, units)。"""
    errors, warnings = [], []
    law_id = str(manifest.get("law_id") or "").strip()
    if not law_id:
        errors.append("缺少 law_id")
        return {"ok": False, "errors": errors, "warnings": warnings,
                "law": None, "docs": [], "units": []}

    law = _law(con, law_id)
    if not law:
        errors.append("laws 表找不到 %s；请先调用 core.law_intake 建档" % law_id)
        return {"ok": False, "errors": errors, "warnings": warnings,
                "law": None, "docs": [], "units": []}
    jurisdiction = law[1]
    linked_ids, linked_roles = _linked_docs(con, law_id)

    raw_docs = manifest.get("documents") or []
    raw_units = manifest.get("units") or []
    if not isinstance(raw_docs, list) or not isinstance(raw_units, list):
        errors.append("documents / units 必须是数组")
        return {"ok": False, "errors": errors, "warnings": warnings,
                "law": law, "docs": [], "units": []}

    docs = []
    doc_ids = set()
    for i, raw in enumerate(raw_docs):
        if not isinstance(raw, dict):
            errors.append("documents[%d] 不是对象" % i)
            continue
        doc = dict(raw)
        doc_id = str(doc.get("id") or "").strip()
        if not doc_id:
            errors.append("documents[%d] 缺少 id" % i)
            continue
        if doc_id in doc_ids:
            errors.append("document id 重复：%s" % doc_id)
            continue
        doc_ids.add(doc_id)
        for key in ("kind", "source_identifier", "legal_status", "source_url"):
            if not str(doc.get(key) or "").strip():
                errors.append("%s 缺少 %s" % (doc_id, key))
        role = str(doc.get("role") or "primary").strip()
        if role not in ALLOWED_ROLES:
            errors.append("%s 的 role=%s 不在允许列表" % (doc_id, role))
        replace_units = doc.get("replace_units", True)
        if not isinstance(replace_units, bool):
            errors.append("%s 的 replace_units 必须是 bool" % doc_id)
            replace_units = True
        doc.update({
            "id": doc_id,
            "jurisdiction": jurisdiction,
            "kind": str(doc.get("kind") or "").strip(),
            "source_identifier": str(doc.get("source_identifier") or "").strip(),
            "official_title": str(doc.get("official_title") or "").strip() or None,
            "language": str(doc.get("language") or "en").strip() or "en",
            "version_date": str(doc.get("version_date") or "").strip() or None,
            "publication_date": str(doc.get("publication_date") or "").strip() or None,
            "legal_status": str(doc.get("legal_status") or "").strip(),
            "source_url": str(doc.get("source_url") or "").strip(),
            "metadata_status": str(doc.get("metadata_status") or "pending").strip(),
            "transfer_status": str(doc.get("transfer_status") or "pending").strip(),
            "parse_status": str(doc.get("parse_status") or "extracted_unreviewed").strip(),
            "full_text": doc.get("full_text"),
            "notes": str(doc.get("notes") or ""),
            "role": role,
            "replace_units": replace_units,
        })
        docs.append(doc)

    units = []
    seen = set()
    units_per_doc = {}
    for i, raw in enumerate(raw_units):
        if not isinstance(raw, dict):
            errors.append("units[%d] 不是对象" % i)
            continue
        unit = dict(raw)
        doc_id = str(unit.get("document_id") or "").strip()
        if doc_id not in doc_ids and doc_id not in linked_ids:
            errors.append("units[%d] document_id=%s 不在 manifest/该法规已关联文档中"
                          % (i, doc_id))
            continue
        try:
            ordinal = int(unit.get("ordinal"))
        except (TypeError, ValueError):
            errors.append("units[%d] ordinal 不是整数" % i)
            continue
        if ordinal < 0:
            errors.append("units[%d] ordinal 不能为负" % i)
            continue
        key = (doc_id, ordinal)
        if key in seen:
            errors.append("units 重复：%s#%d" % key)
            continue
        seen.add(key)
        locator = str(unit.get("locator") or "").strip()
        unit_type = str(unit.get("unit_type") or "").strip()
        body = unit.get("body")
        if not locator:
            errors.append("%s#%d 缺少 locator" % key)
        if not unit_type:
            errors.append("%s#%d 缺少 unit_type" % key)
        if not isinstance(body, str) or not body.strip():
            errors.append("%s#%d body 为空" % key)
        unit.update({
            "document_id": doc_id,
            "ordinal": ordinal,
            "locator": locator,
            "unit_type": unit_type,
            "heading": str(unit.get("heading") or "").strip() or None,
            "body": body,
            "source_fragment": unit.get("source_fragment"),
        })
        units.append(unit)
        units_per_doc[doc_id] = units_per_doc.get(doc_id, 0) + 1

    for doc in docs:
        if doc["replace_units"] and units_per_doc.get(doc["id"], 0) == 0:
            errors.append("%s replace_units=true 但没有提供 units" % doc["id"])
    if not units:
        warnings.append("没有 units；只能更新 documents 元数据，召回树会用全文兜底")
    structured = sum(1 for u in units if u["unit_type"] in STRUCTURED_TYPES)
    if units and structured == 0:
        warnings.append("没有结构化 unit（article/section/annex/subpart/appendix），"
                        "召回树会走全文兜底")
    roles = {d["role"] for d in docs} | set(linked_roles.values())
    if not roles.intersection({"primary", "eu_consolidated"}):
        warnings.append("没有 primary / eu_consolidated 文档，召回树可能没有 canonical 文档")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "law": law,
        "docs": docs,
        "units": units,
    }


def apply_manifest(con, validation, dry_run=False):
    """把校验过的 manifest 写入 documents/law_documents/units。"""
    if not validation.get("ok"):
        return False
    law = validation["law"]
    law_id = law[0]
    docs = validation["docs"]
    units = validation["units"]

    if dry_run:
        return True

    con.execute("BEGIN IMMEDIATE")
    try:
        for doc in docs:
            con.execute(
                """INSERT INTO documents
                   (id, jurisdiction, kind, source_identifier, official_title,
                    language, version_date, publication_date, legal_status,
                    source_url, metadata_status, transfer_status, parse_status,
                    full_text, notes)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET
                     jurisdiction=excluded.jurisdiction,
                     kind=excluded.kind,
                     source_identifier=excluded.source_identifier,
                     official_title=excluded.official_title,
                     language=excluded.language,
                     version_date=excluded.version_date,
                     publication_date=excluded.publication_date,
                     legal_status=excluded.legal_status,
                     source_url=excluded.source_url,
                     metadata_status=excluded.metadata_status,
                     transfer_status=excluded.transfer_status,
                     parse_status=excluded.parse_status,
                     full_text=excluded.full_text,
                     notes=excluded.notes""",
                tuple(doc[k] for k in DOC_COLUMNS),
            )
            con.execute(
                """INSERT INTO law_documents (law_id, document_id, role)
                   VALUES (?,?,?)
                   ON CONFLICT(law_id, document_id, role) DO NOTHING""",
                (law_id, doc["id"], doc["role"]),
            )
            if doc["replace_units"]:
                con.execute("DELETE FROM units WHERE document_id=?", (doc["id"],))

        for unit in units:
            con.execute(
                """INSERT INTO units
                   (document_id, ordinal, locator, unit_type, heading, body, source_fragment)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(document_id, ordinal) DO UPDATE SET
                     locator=excluded.locator,
                     unit_type=excluded.unit_type,
                     heading=excluded.heading,
                     body=excluded.body,
                     source_fragment=excluded.source_fragment""",
                (unit["document_id"], unit["ordinal"], unit["locator"],
                 unit["unit_type"], unit["heading"], unit["body"],
                 unit["source_fragment"]),
            )
        con.commit()
        return True
    except Exception:
        con.rollback()
        raise


def run_rebuild(db_path, check=False, report_path=None):
    cmd = [sys.executable, BUILD_SCRIPT, "--db", db_path]
    if report_path:
        cmd.extend(["--report", report_path])
    proc = subprocess.run(cmd, cwd=PROJECT, capture_output=True,
                          encoding="utf-8", errors="replace")
    out = {"cmd": cmd, "returncode": proc.returncode,
           "stdout_tail": (proc.stdout or "")[-2000:],
           "stderr_tail": (proc.stderr or "")[-2000:]}
    if proc.returncode == 0 and check:
        chk = subprocess.run(
            [sys.executable, BUILD_SCRIPT, "--db", db_path, "--check"],
            cwd=PROJECT, capture_output=True, encoding="utf-8", errors="replace",
        )
        out["check_returncode"] = chk.returncode
        out["check_stdout_tail"] = (chk.stdout or "")[-2000:]
        out["check_stderr_tail"] = (chk.stderr or "")[-2000:]
    return out


def _arg_value(name, default=None):
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


def main():
    dry_run = "--dry-run" in sys.argv
    rebuild = "--rebuild" in sys.argv
    manifest_path = _arg_value("--manifest")
    db_path = _arg_value("--db", DB_PATH)
    report_path = _arg_value("--report", DEFAULT_REPORT)
    tree_report = _arg_value("--tree-report")
    if not manifest_path:
        print("错误：缺少 --manifest", file=sys.stderr)
        return 2
    if not os.path.exists(manifest_path):
        print("错误：manifest 不存在：%s" % manifest_path, file=sys.stderr)
        return 2
    if not os.path.exists(db_path):
        print("错误：数据库不存在：%s" % db_path, file=sys.stderr)
        return 2
    try:
        manifest = load_manifest(manifest_path)
    except Exception as e:  # noqa: BLE001
        print("错误：manifest 解析失败：%s" % e, file=sys.stderr)
        return 2

    con = connect(db_path)
    try:
        validation = validate_manifest(con, manifest)
        print("=" * 66)
        print("  法规材料落库%s" % ("（演练模式，不写库）" if dry_run else ""))
        print("=" * 66)
        print("  law_id：%s" % manifest.get("law_id"))
        print("  documents：%d　units：%d" % (
            len(validation["docs"]), len(validation["units"])))
        if validation["warnings"]:
            for w in validation["warnings"]:
                print("  ⚠ %s" % w)
        if validation["errors"]:
            for e in validation["errors"]:
                print("  ✗ %s" % e)
            print("  校验：FAIL")
            return 1
        print("  校验：OK")
        apply_manifest(con, validation, dry_run)
        print("  写入：%s" % ("跳过（演练）" if dry_run else "完成"))

        result = {"ok": True, "dry_run": dry_run,
                  "law_id": manifest.get("law_id"),
                  "documents": len(validation["docs"]),
                  "units": len(validation["units"]),
                  "warnings": validation["warnings"]}
        if rebuild and not dry_run:
            result["rebuild"] = run_rebuild(db_path, check=True,
                                            report_path=tree_report)
            if result["rebuild"]["returncode"] != 0:
                result["ok"] = False

        if dry_run:
            print("  报告：演练模式未写（%s）" % report_path)
        else:
            os.makedirs(os.path.dirname(report_path), exist_ok=True)
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            print("  报告：%s" % report_path)
        print("=" * 66)
        return 0 if result["ok"] else 1
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
