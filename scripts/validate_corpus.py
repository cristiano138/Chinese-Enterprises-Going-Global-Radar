# -*- coding: utf-8 -*-
"""Validate the release corpus and emit a machine-readable quality report."""
from __future__ import annotations

import csv
import json
import os
from collections import Counter
from datetime import datetime, timezone, timedelta

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(PROJECT, "data")
SOURCE = os.path.join(DATA, "语料核对表_完整版.csv")
REPORT = os.path.join(DATA, "data_quality_report.json")
REQUIRED = {"类目", "机构", "法规中文名", "官方编号", "官方链接", "现行效力"}
VALID_STATUS = {"现行有效", "现行有效（持续修订）", "未来生效", "已废止", "待确认", ""}
AUDIT_STATUS = {"已核对", "待核对", "需复核", ""}


def main() -> int:
    errors = []
    warnings = []
    with open(SOURCE, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fields = set(reader.fieldnames or [])
        missing_fields = sorted(REQUIRED - fields)
        if missing_fields:
            errors.append(f"缺少必填字段: {', '.join(missing_fields)}")
        rows = [{k: (v or "").strip() for k, v in row.items()} for row in reader]

    keys = [(row.get("机构", ""), row.get("官方编号", "")) for row in rows]
    duplicate_keys = [list(key) for key, count in Counter(keys).items() if key != ("", "") and count > 1]
    if duplicate_keys:
        errors.append(f"发现重复唯一键 {len(duplicate_keys)} 个")

    invalid_rows = []
    missing_urls = []
    invalid_status = []
    invalid_audit_status = []
    for index, row in enumerate(rows, 2):
        problems = []
        if not row.get("官方编号"):
            problems.append("缺少官方编号")
        if not row.get("官方链接"):
            problems.append("缺少官方链接")
            missing_urls.append(index)
        elif not row["官方链接"].startswith(("http://", "https://")):
            problems.append("官方链接不是 HTTP(S)")
        if row.get("现行效力") not in VALID_STATUS:
            invalid_status.append({"row": index, "value": row.get("现行效力", "")})
            problems.append("效力状态不在允许集合")
        audit_status = row.get("核对状态", "")
        if audit_status not in AUDIT_STATUS:
            invalid_audit_status.append({"row": index, "value": audit_status})
            problems.append("核对状态不在允许集合")
        if problems:
            invalid_rows.append({"row": index, "problems": problems})

    if invalid_rows:
        errors.append(f"发现字段错误 {len(invalid_rows)} 行")
    if invalid_status:
        errors.append(f"发现非法效力状态 {len(invalid_status)} 个")
    if invalid_audit_status:
        errors.append(f"发现非法核对状态 {len(invalid_audit_status)} 个")
    pending_audit = [index for index, row in enumerate(rows, 2)
                     if row.get("核对状态") != "已核对"]
    if pending_audit:
        warnings.append(
            f"有 {len(pending_audit)} 行尚未人工核对；这些记录不得作为已发布合规依据")
    # 团队人工核对声明：允许负责人一次性声明剩余记录已核对，但不伪造逐条元数据。
    attestation = None
    attested_rows = set()
    attestation_path = os.path.join(PROJECT, "data", "audit_attestation.json")
    if os.path.exists(attestation_path):
        try:
            with open(attestation_path, encoding="utf-8") as fh:
                loaded = json.load(fh)
            if loaded.get("attested") is True:
                attestation = loaded
                attested_rows = set(loaded.get("covers_rows") or [])
        except (OSError, ValueError):
            attestation = None
    uncovered_audit = [index for index in pending_audit if index not in attested_rows]
    if attestation and not uncovered_audit and pending_audit:
        warnings.append(
            f"其余 {len(pending_audit)} 行由{attestation.get('attested_by', '负责人')}"
            f"于 {attestation.get('attested_at', '')} 声明确认已核对；逐条元数据未随库提交")
    if any(not row.get("链接可打开") for row in rows):
        warnings.append("部分链接没有自动核验结果；这不等同于链接失效")

    market_counts = Counter(row.get("机构", "") for row in rows)
    status_counts = Counter(row.get("现行效力", "") or "未填写" for row in rows)
    report = {
        "generated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
        "source_file": os.path.relpath(SOURCE, PROJECT),
        "total_rows": len(rows),
        "unique_keys": len(set(keys)),
        "duplicate_keys": duplicate_keys,
        "markets": dict(sorted(market_counts.items())),
        "status_distribution": dict(sorted(status_counts.items())),
        "invalid_rows": invalid_rows,
        "missing_urls": missing_urls,
        "audit_status_distribution": dict(sorted(
            Counter(row.get("核对状态", "") or "未填写" for row in rows).items()
        )),
        "pending_audit_rows": pending_audit,
        "uncovered_audit_rows": uncovered_audit,
        "audit_attestation": ({k: attestation.get(k) for k in
                               ("attested_by", "attested_at", "scope", "basis", "statement", "covers_count")}
                              if attestation else None),
        "invalid_audit_status": invalid_audit_status,
        "warnings": warnings,
        "release_eligible": not errors and not uncovered_audit,
        "valid": not errors,
        "errors": errors,
    }
    with open(REPORT, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
