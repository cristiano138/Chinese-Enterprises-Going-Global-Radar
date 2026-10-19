# -*- coding: utf-8 -*-
"""
法规材料落库链路 · 离线自检（scripts/selftest_material_pipeline.py）

覆盖：
    1. manifest 校验（缺字段/重复 ordinal/法规不存在）
    2. documents / law_documents / units 落库与 replace_units
    3. 编排器状态：ready / material_missing
    4. 材料缺失 -> tasks 表 + data/material_tasks/*.json
    5. 材料齐全 -> 全量召回树重建 + --check（临时 DB，不碰真实库）
    6. 从 freshness summary / intake log 提取 law_id 的格式兼容

用法：
    python scripts/selftest_material_pipeline.py
退出码 0 = 全绿；1 = 有失败项。
"""

import json
import os
import shutil
import sqlite3
import sys
import tempfile

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import ingest_law_material as ing  # noqa: E402
import refresh_recall_pipeline as rp  # noqa: E402

PASS, FAIL = [], []
LAW = "EU:32026R9999"
DOC = "EU-DOC:32026R9999"


def check(name, cond, detail=""):
    if cond:
        PASS.append(name)
        print("  ✅ %s" % name)
    else:
        FAIL.append((name, detail))
        print("  ❌ %s  %s" % (name, detail))


SOURCE_SCHEMA = [
    """CREATE TABLE laws(
        id TEXT PRIMARY KEY, jurisdiction TEXT, official_title TEXT,
        in_force TEXT, effective_status_detail TEXT, seed_json TEXT)""",
    """CREATE TABLE documents(
        id TEXT PRIMARY KEY, jurisdiction TEXT, kind TEXT,
        source_identifier TEXT, official_title TEXT, language TEXT,
        version_date TEXT, publication_date TEXT, legal_status TEXT,
        source_url TEXT, metadata_status TEXT, transfer_status TEXT,
        parse_status TEXT, full_text TEXT, notes TEXT)""",
    """CREATE TABLE law_documents(
        law_id TEXT, document_id TEXT, role TEXT,
        PRIMARY KEY(law_id, document_id, role))""",
    """CREATE TABLE units(
        document_id TEXT, ordinal INTEGER, locator TEXT, unit_type TEXT,
        heading TEXT, body TEXT, source_fragment TEXT,
        PRIMARY KEY(document_id, ordinal))""",
    """CREATE TABLE tasks(
        task_key TEXT PRIMARY KEY, phase TEXT NOT NULL, law_id TEXT,
        payload_json TEXT NOT NULL, state TEXT DEFAULT 'pending',
        error TEXT, updated_at TEXT NOT NULL)""",
]


def manifest(units_count=6):
    units = []
    for i in range(units_count):
        units.append({
            "document_id": DOC,
            "ordinal": i,
            "locator": "https://example/%s#art_%d" % (DOC, i + 1),
            "unit_type": "article",
            "heading": "Article %d — Requirement %d" % (i + 1, i + 1),
            "body": "Article %d\nRequirement %d\n%s" % (i + 1, i + 1, "x" * 120),
        })
    return {
        "law_id": LAW,
        "documents": [{
            "id": DOC,
            "kind": "eu_original",
            "source_identifier": "32026R9999",
            "official_title": "Regulation (EU) 2026/9999 (test)",
            "language": "en",
            "version_date": "2026-01-01",
            "publication_date": "2026-01-01",
            "legal_status": "current",
            "source_url": "https://example/32026R9999",
            "full_text": "full text " * 100,
            "role": "primary",
            "replace_units": True,
        }],
        "units": units,
    }


def make_db():
    tmp = tempfile.mkdtemp(prefix="material_selftest_")
    path = os.path.join(tmp, "test.sqlite3")
    con = sqlite3.connect(path)
    con.text_factory = str
    for sql in SOURCE_SCHEMA:
        con.execute(sql)
    con.execute(
        "INSERT INTO laws VALUES (?,?,?,?,?,?)",
        (LAW, "EU", "Regulation (EU) 2026/9999 (test)", "现行有效",
         "现行有效", json.dumps({"官方链接": "https://example/32026R9999"},
                                ensure_ascii=False)),
    )
    con.commit()
    return tmp, path, con


def main():
    print("=" * 74)
    print("  法规材料落库链路 · 自检")
    print("=" * 74)
    tmp, path, con = make_db()
    try:
        # ── 1. manifest 校验与落库 ─────────────────────────────
        print("\n【1】manifest 校验 / 落库")
        val = ing.validate_manifest(con, manifest())
        check("合法 manifest 通过校验", val["ok"], str(val["errors"]))
        check("识别 1 份文档 + 6 个 units",
              len(val["docs"]) == 1 and len(val["units"]) == 6)
        ing.apply_manifest(con, val)
        n_doc = con.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        n_link = con.execute("SELECT COUNT(*) FROM law_documents").fetchone()[0]
        n_unit = con.execute("SELECT COUNT(*) FROM units").fetchone()[0]
        check("documents/law_documents/units 落库",
              (n_doc, n_link, n_unit) == (1, 1, 6),
              "(%d,%d,%d)" % (n_doc, n_link, n_unit))

        # ── 2. replace_units ───────────────────────────────────
        print("\n【2】replace_units")
        val2 = ing.validate_manifest(con, manifest(units_count=4))
        ing.apply_manifest(con, val2)
        n_unit2 = con.execute("SELECT COUNT(*) FROM units").fetchone()[0]
        check("replace_units=true 后只剩 4 条", n_unit2 == 4, str(n_unit2))

        # ── 3. 非法 manifest ───────────────────────────────────
        print("\n【3】非法 manifest 被拒绝")
        bad_law = manifest()
        bad_law["law_id"] = "EU:does-not-exist"
        check("法规不存在 -> 报错",
              not ing.validate_manifest(con, bad_law)["ok"])
        bad_dup = manifest()
        bad_dup["units"].append(dict(bad_dup["units"][0]))
        check("重复 ordinal -> 报错",
              any("重复" in e for e in ing.validate_manifest(con, bad_dup)["errors"]))
        bad_empty = manifest()
        bad_empty["units"][0]["body"] = ""
        check("空 body -> 报错",
              any("body" in e for e in ing.validate_manifest(con, bad_empty)["errors"]))

        # ── 4. 编排器状态 / task ───────────────────────────────
        print("\n【4】编排器状态与 material task")
        # 第 2 步故意只剩 4 条；先把 6 条恢复，再验证 ready。
        ing.apply_manifest(con, ing.validate_manifest(con, manifest()))
        st = rp.law_material_status(con, LAW)
        check("材料齐全 -> ready", st["status"] == "ready", st["status"])
        con.execute("DELETE FROM units")
        con.commit()
        st = rp.law_material_status(con, LAW)
        check("无 units -> material_missing", st["status"] == "material_missing",
              st["status"])
        payload = rp.task_payload(st)
        check("task payload 带 manifest 模板",
              payload["law_id"] == LAW and "manifest_template" in payload
              and payload["manifest_template"]["law_id"] == LAW)
        rp.upsert_task(con, LAW, payload, "pending")
        row = con.execute(
            "SELECT phase, state FROM tasks WHERE task_key=?",
            ("material:" + LAW,)).fetchone()
        check("tasks 表写入 pending", row == ("material_intake", "pending"), str(row))
        task_file = rp.write_task_file(st, payload, os.path.join(tmp, "tasks"))
        check("task 文件生成", bool(task_file) and os.path.exists(task_file))

        # 再落库，task 标 done
        ing.apply_manifest(con, ing.validate_manifest(con, manifest()))
        rp.mark_task_done(con, LAW)
        state = con.execute(
            "SELECT state FROM tasks WHERE task_key=?",
            ("material:" + LAW,)).fetchone()[0]
        check("材料到位后 task=done", state == "done", state)

        # ── 5. 全量召回树重建 ─────────────────────────────────
        print("\n【5】材料齐全 -> 召回树重建 + check")
        tree_report = os.path.join(tmp, "tree_report.json")
        result = rp.run_rebuild(path, check=True, dry_run=False,
                                tree_report=tree_report)
        check("build_recall_tree returncode=0",
              result.get("returncode") == 0,
              str(result.get("stderr_tail")))
        check("build_recall_tree --check returncode=0",
              result.get("check_returncode") == 0,
              str(result.get("check_tail") or result.get("check_stderr_tail")))
        n_nodes = con.execute("SELECT COUNT(*) FROM recall_nodes").fetchone()[0]
        check("临时库生成 recall_nodes", n_nodes > 0, str(n_nodes))

        # ── 6. law_id 提取格式 ─────────────────────────────────
        print("\n【6】changed-file / intake log 格式兼容")
        ids = rp.extract_law_ids_from_data(
            {"changes": [{"law_id": "EU:A", "field": "x"}, {"law_id": "EU:B"}]})
        check("freshness summary changes[]", ids == ["EU:A", "EU:B"], str(ids))
        ids = rp.extract_law_ids_from_data({"law_ids": ["EU:C"]})
        check("law_ids 列表", ids == ["EU:C"], str(ids))
        ids = rp.extract_law_ids_from_data([{"law_id": "US:1:2"}])
        check("list[dict]", ids == ["US:1:2"], str(ids))

        print("\n" + "=" * 74)
        print("  通过 %d 项，失败 %d 项" % (len(PASS), len(FAIL)))
        if FAIL:
            for name, detail in FAIL:
                print("  FAIL: %s  %s" % (name, detail))
            print("=" * 74)
            return 1
        print("  ALL PASS")
        print("=" * 74)
        return 0
    finally:
        con.close()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
