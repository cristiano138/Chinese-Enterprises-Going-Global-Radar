# -*- coding: utf-8 -*-
"""
新法规/变更 -> 召回树 编排器（scripts/refresh_recall_pipeline.py）

用途：
    时效性脚本（check_metadata_freshness.py）或搜索校验 agent 发现新法规/变更后，
    按同一链路收口：
        laws 行（core.law_intake）
          -> 材料落库（scripts/ingest_law_material.py）
          -> 重建召回树（scripts/build_recall_tree.py）
          -> core.recall / modules.recall_flow 可检索

    本脚本不抓全文、不解析材料；它负责：
      1. 检查目标法规的材料是否齐全（documents/law_documents/units）；
      2. 材料缺失时，写一个 pending task（DB tasks 表 + data/material_tasks/*.json），
         里面带 manifest 模板和来源链接，交给材料抓取/解析 agent；
      3. 材料齐全时，可选地触发**全量**召回树重建并校验。

用法：
    # 单个/多个法规
    python scripts/refresh_recall_pipeline.py --law-id EU:32026R9999 --dry-run
    python scripts/refresh_recall_pipeline.py --law-id EU:32026R9999 --rebuild

    # 从时效性报告/日志提取变化的 law_id
    python scripts/refresh_recall_pipeline.py --changed-file data/metadata_check_latest.json --rebuild
    （链接级 data/freshness_latest.json 不含 law_id，不能作为变更信号来源）

    # 从新法规建档日志提取
    python scripts/refresh_recall_pipeline.py --from-intake-log --rebuild

退出码：
    0 所有目标法规材料齐全（或已成功重建）
    1 存在材料缺失/法规不存在（已生成 task）
    2 用法/DB 错误
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
INTAKE_LOG = os.path.join(SQLITE_DIR, "law_intake_log.jsonl")
TASK_DIR = os.path.join(GO_RADAR_ROOT, "data", "material_tasks")
DEFAULT_REPORT = os.path.join(GO_RADAR_ROOT, "data", "recall_refresh_report.json")
TREE_REPORT = os.path.join(GO_RADAR_ROOT, "data", "recall_tree_report.json")

STRUCTURED_TYPES = ("article", "annex", "section", "subpart", "appendix")


def connect(path=None):
    con = sqlite3.connect(path or DB_PATH)
    con.text_factory = str
    return con


def _arg_values(name):
    out = []
    for i, arg in enumerate(sys.argv):
        if arg == name and i + 1 < len(sys.argv):
            out.append(sys.argv[i + 1])
    return out


def _arg_value(name, default=None):
    vals = _arg_values(name)
    return vals[-1] if vals else default


def extract_law_ids_from_data(data):
    """支持：list[str|dict]、{"law_ids":[...]}、freshness summary {"changes":[...]}。"""
    out = []
    if isinstance(data, dict):
        if isinstance(data.get("law_ids"), list):
            for x in data["law_ids"]:
                if isinstance(x, str):
                    out.append(x)
                elif isinstance(x, dict) and x.get("law_id"):
                    out.append(x["law_id"])
        for key in ("changes", "laws", "records"):
            if isinstance(data.get(key), list):
                for x in data[key]:
                    if isinstance(x, str):
                        out.append(x)
                    elif isinstance(x, dict) and x.get("law_id"):
                        out.append(x["law_id"])
        if not out and data.get("law_id"):
            out.append(data["law_id"])
    elif isinstance(data, list):
        for x in data:
            if isinstance(x, str):
                out.append(x)
            elif isinstance(x, dict) and x.get("law_id"):
                out.append(x["law_id"])
    return out


def load_changed_ids(path):
    if not path or not os.path.exists(path):
        return []
    if path.endswith(".jsonl"):
        ids = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if isinstance(rec, dict) and rec.get("law_id"):
                    action = rec.get("action")
                    if action in (None, "auto_updated", "inserted", "new_law"):
                        ids.append(rec["law_id"])
        return ids
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return extract_law_ids_from_data(data)


def load_intake_ids(path=INTAKE_LOG):
    if not os.path.exists(path):
        return []
    ids = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if isinstance(rec, dict) and rec.get("action") == "inserted" and rec.get("law_id"):
                ids.append(rec["law_id"])
    return ids


def dedupe(ids):
    out = []
    seen = set()
    for x in ids:
        x = str(x or "").strip()
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def resolve_target_ids():
    ids = list(_arg_values("--law-id"))
    ids += load_changed_ids(_arg_value("--changed-file"))
    if "--from-intake-log" in sys.argv:
        ids += load_intake_ids(_arg_value("--intake-log", INTAKE_LOG))
    return dedupe(ids)


def law_material_status(con, law_id):
    """返回 per-law 材料状态；不写库。"""
    row = con.execute(
        "SELECT id, jurisdiction, official_title, seed_json FROM laws WHERE id=?",
        (law_id,),
    ).fetchone()
    if not row:
        return {"law_id": law_id, "status": "missing_law", "jurisdiction": None,
                "official_title": None, "source_url": None, "docs": [],
                "canonical": None, "seed_json": {}}
    seed = {}
    try:
        seed = json.loads(row[3] or "{}")
    except (TypeError, ValueError):
        seed = {}
    docs = con.execute(
        """SELECT ld.document_id, ld.role, d.kind, d.version_date, d.source_url,
                  (SELECT COUNT(*) FROM units u WHERE u.document_id=d.id),
                  (SELECT COUNT(*) FROM units u WHERE u.document_id=d.id
                     AND u.unit_type IN ('article','annex','section','subpart','appendix'))
           FROM law_documents ld JOIN documents d ON d.id=ld.document_id
           WHERE ld.law_id=?
           ORDER BY ld.role, COALESCE(d.version_date,'') DESC""",
        (law_id,),
    ).fetchall()
    doc_rows = [{
        "document_id": r[0], "role": r[1], "kind": r[2],
        "version_date": r[3], "source_url": r[4],
        "units": r[5], "structured_units": r[6],
    } for r in docs]
    canonical = None
    for d in doc_rows:
        if d["role"] in ("primary", "eu_consolidated") and d["structured_units"] > 0:
            if canonical is None or d["structured_units"] > canonical["structured_units"]:
                canonical = d
    if not doc_rows or sum(d["units"] for d in doc_rows) == 0:
        status = "material_missing"
    elif canonical is None:
        status = "no_structured"
    elif canonical["structured_units"] < 5:
        status = "thin"
    else:
        status = "ready"
    source_url = (seed.get("官方链接") or (canonical or {}).get("source_url")
                  or (doc_rows[0]["source_url"] if doc_rows else None))
    return {
        "law_id": law_id,
        "status": status,
        "jurisdiction": row[1],
        "official_title": row[2],
        "source_url": source_url,
        "seed_json": seed,
        "docs": doc_rows,
        "canonical": canonical,
        "structured_units": (canonical or {}).get("structured_units", 0),
    }


def task_payload(status):
    law_id = status["law_id"]
    return {
        "law_id": law_id,
        "phase": "material_intake",
        "status": status["status"],
        "jurisdiction": status.get("jurisdiction"),
        "official_title": status.get("official_title"),
        "source_url": status.get("source_url"),
        "seed_json": status.get("seed_json") or {},
        "required": {
            "documents": "至少一份 role=primary（EU 可用 eu_consolidated）的 documents 行",
            "law_documents": "law_id -> document_id 的角色关联",
            "units": "ordinal/locator/unit_type/body；优先 article/annex/section/subpart/appendix",
            "manifest": "用 scripts/ingest_law_material.py 的 manifest 格式提交",
        },
        "manifest_template": {
            "law_id": law_id,
            "documents": [{
                "id": "DOC-ID",
                "kind": "eu_original 或 us_ecfr / us_fr",
                "source_identifier": "CELEX / CFR Part / FR doc number",
                "official_title": status.get("official_title") or "",
                "language": "en",
                "version_date": None,
                "publication_date": None,
                "legal_status": "current",
                "source_url": status.get("source_url") or "",
                "full_text": "",
                "role": "primary",
                "replace_units": True,
            }],
            "units": [{
                "document_id": "DOC-ID",
                "ordinal": 0,
                "locator": "https://...#art_1",
                "unit_type": "article",
                "heading": "Article 1 — ...",
                "body": "Article 1\\n...",
                "source_fragment": None,
            }],
        },
        "next_command": (
            "python scripts/ingest_law_material.py --manifest <manifest.json> "
            "--rebuild"
        ),
    }


def ensure_tasks_table(con):
    con.execute(
        """CREATE TABLE IF NOT EXISTS tasks (
             task_key TEXT PRIMARY KEY,
             phase TEXT NOT NULL,
             law_id TEXT,
             payload_json TEXT NOT NULL,
             state TEXT DEFAULT 'pending',
             error TEXT,
             updated_at TEXT NOT NULL
           )"""
    )


def upsert_task(con, law_id, payload, state="pending", dry_run=False):
    if dry_run:
        return
    ensure_tasks_table(con)
    key = "material:" + law_id
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    con.execute(
        """INSERT INTO tasks (task_key, phase, law_id, payload_json, state, error, updated_at)
           VALUES (?, 'material_intake', ?, ?, ?, NULL, ?)
           ON CONFLICT(task_key) DO UPDATE SET
             payload_json=excluded.payload_json,
             state=excluded.state,
             error=NULL,
             updated_at=excluded.updated_at""",
        (key, law_id, json.dumps(payload, ensure_ascii=False), state, now),
    )
    con.commit()


def mark_task_done(con, law_id, dry_run=False):
    if dry_run:
        return
    ensure_tasks_table(con)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    con.execute(
        "UPDATE tasks SET state='done', updated_at=? WHERE task_key=?",
        (now, "material:" + law_id),
    )
    con.commit()


def write_task_file(status, payload, task_dir=TASK_DIR, dry_run=False):
    if dry_run:
        return None
    os.makedirs(task_dir, exist_ok=True)
    safe = status["law_id"].replace(":", "_").replace("|", "_").replace("/", "_")
    path = os.path.join(task_dir, safe + ".json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


def run_rebuild(db_path, check=False, dry_run=False, tree_report=TREE_REPORT):
    cmd = [sys.executable, BUILD_SCRIPT, "--db", db_path]
    if tree_report:
        cmd.extend(["--report", tree_report])
    if dry_run:
        return {"skipped": True, "cmd": cmd}
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


def main():
    dry_run = "--dry-run" in sys.argv
    rebuild = "--rebuild" in sys.argv
    check = "--check" in sys.argv
    db_path = _arg_value("--db", DB_PATH)
    report_path = _arg_value("--report", DEFAULT_REPORT)
    task_dir = _arg_value("--task-dir", TASK_DIR)
    tree_report = _arg_value("--tree-report", TREE_REPORT)

    if not os.path.exists(db_path):
        print("错误：数据库不存在：%s" % db_path, file=sys.stderr)
        return 2
    ids = resolve_target_ids()
    if not ids:
        print("错误：没有目标法规。传 --law-id / --changed-file / --from-intake-log",
              file=sys.stderr)
        return 2

    con = connect(db_path)
    try:
        targets = []
        for law_id in ids:
            st = law_material_status(con, law_id)
            targets.append(st)
            if st["status"] in ("material_missing", "missing_law"):
                payload = task_payload(st)
                upsert_task(con, law_id, payload, "pending", dry_run)
                path = write_task_file(st, payload, task_dir, dry_run)
                st["task_file"] = path
            elif st["status"] in ("ready", "thin", "no_structured"):
                mark_task_done(con, law_id, dry_run)

        blocked = [t for t in targets if t["status"] in ("material_missing", "missing_law")]
        buildable = [t for t in targets if t not in blocked]
        summary = {
            "total": len(targets),
            "ready": sum(1 for t in targets if t["status"] == "ready"),
            "thin": sum(1 for t in targets if t["status"] == "thin"),
            "no_structured": sum(1 for t in targets if t["status"] == "no_structured"),
            "material_missing": sum(1 for t in targets if t["status"] == "material_missing"),
            "missing_law": sum(1 for t in targets if t["status"] == "missing_law"),
        }

        result = {
            "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "db": db_path,
            "dry_run": dry_run,
            "summary": summary,
            "targets": [{k: v for k, v in t.items() if k != "seed_json"} for t in targets],
            "blocked": [t["law_id"] for t in blocked],
            "rebuild": None,
        }

        print("=" * 78)
        print("  法规材料 -> 召回树 编排%s" % ("（演练模式，不写库）" if dry_run else ""))
        print("=" * 78)
        print("  %-22s %-18s %8s %10s %s" % ("law_id", "status", "units", "structured", "task"))
        for t in targets:
            print("  %-22s %-18s %8d %10d %s" % (
                t["law_id"], t["status"],
                sum(d["units"] for d in t.get("docs", [])),
                t.get("structured_units", 0),
                t.get("task_file") or "-"))

        if rebuild:
            if blocked:
                result["rebuild"] = {
                    "skipped": True,
                    "reason": "存在材料缺失/法规不存在，先落库再重建",
                }
                print("  重建：跳过（%d 条材料缺失）" % len(blocked))
            else:
                result["rebuild"] = run_rebuild(db_path, check, dry_run, tree_report)
                if dry_run:
                    print("  重建：演练（%s）" % " ".join(result["rebuild"]["cmd"]))
                else:
                    print("  重建：returncode=%s%s" % (
                        result["rebuild"].get("returncode"),
                        "" if not check else " / check=%s" %
                        result["rebuild"].get("check_returncode")))
        else:
            print("  重建：未触发（加 --rebuild）")

        if blocked:
            print("  待材料落库：%d 条；task %s %s" % (
                len(blocked),
                "待写入（演练）" if dry_run else "已写入",
                task_dir))
        print("=" * 78)

        if dry_run:
            print("  报告：演练模式未写（%s）" % report_path)
        else:
            os.makedirs(os.path.dirname(report_path), exist_ok=True)
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            print("  报告：%s" % report_path)
        return 1 if blocked else 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
