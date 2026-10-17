# -*- coding: utf-8 -*-
"""
新法规骨架级建档入口（core/law_intake.py）

用途：
    封装给未来的"搜索校验 LLM"调用的建档 skill——它联网发现库外新法规后，
    自主调用这个入口把骨架级元数据写进 laws 表，不需要等人工审批流程，
    事后由人工审查 metadata_check_log.jsonl / 本模块产生的日志即可。

范围边界（明确、不含糊）：
    只做骨架级建档——标题、CELEX/Title+Part号、生效日期、现行效力、
    seed_json——跟 fetch_eu.py / fetch_us.py 现在产出 CSV 的深度一致。

    不做全文抓取、不做 units 表条款级切片。原因：当前库内 86 条法规的
    units 片段是怎么来的，这个仓库里没有对应的自动化脚本——那部分显然
    经过人工/半自动流程（seed_json 里能看到"核对人"这类人工签字字段），
    本模块不假装有能力替代这个流程。新建档的法规在 units 表没有任何
    记录，是预期行为，不是 bug——后续原文落库仍需要走现有的人工流程。

复用：
    EU 查询：scripts/check_metadata_freshness.py 的 query_eu_official()
    US 查询：scripts/check_metadata_freshness.py 的 query_us_official()
    （两者本身又复用 fetch_eu.py / fetch_us.py 已验证过的官方接口调用）

用法：
    from core import law_intake
    result = law_intake.intake_eu_law("32026L9999", category="儿童玩具",
                                       note="示例")
    result = law_intake.intake_us_law(16, "9999", category="电子电器",
                                       agency="CPSC")

    两者都返回 dict：
        {"ok": True/False, "law_id": ..., "action": "inserted"/"skipped_exists"/
         "rejected", "reason": "..."}
    任何失败都通过返回值表达，不抛异常——调用方（搜索校验 LLM 的工具
    调用层）预期的是"结构化结果"，不是异常处理。
"""

import importlib.util
import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
GO_RADAR_ROOT = os.path.dirname(HERE)
PROJECT = os.path.dirname(GO_RADAR_ROOT)
SQLITE_DIR = os.path.join(PROJECT, "sqlite")
DB_PATH = os.path.join(SQLITE_DIR, "regulations.sqlite3")
INTAKE_LOG_PATH = os.path.join(SQLITE_DIR, "law_intake_log.jsonl")

BJT = timezone(timedelta(hours=8))


def _now_str():
    return datetime.now(BJT).strftime("%Y-%m-%d %H:%M:%S")


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_freshness = _load_module(
    "check_metadata_freshness",
    os.path.join(GO_RADAR_ROOT, "scripts", "check_metadata_freshness.py"),
)


def _connect():
    import sqlite3

    con = sqlite3.connect(DB_PATH)
    con.text_factory = str
    return con


def _law_exists(con, law_id):
    cur = con.cursor()
    cur.execute("SELECT 1 FROM laws WHERE id=?", (law_id,))
    return cur.fetchone() is not None


def _write_log(record):
    os.makedirs(SQLITE_DIR, exist_ok=True)
    with open(INTAKE_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _seed_json_and_hash(payload):
    """跟库内现有 seed_json 一致的 JSON 序列化方式（排序键，中文不转义），
    并算出 seed_sha256（laws.seed_sha256 列是 NOT NULL，必须提供）。
    """
    s = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    sha = hashlib.sha256(s.encode("utf-8")).hexdigest()
    return s, sha


# ── EU ────────────────────────────────────────────────────────────────
def intake_eu_law(celex, category="", note="", source="search_verify_llm"):
    """用 CELEX 号建档一条新 EU 法规骨架记录。

    流程：
      1) 先查 laws 表是否已存在这个 law_id（EU:{celex}），存在就跳过，
         不覆盖已有记录——建新档不是这个函数的职责范围，已有记录的
         更新走 check_metadata_freshness.py。
      2) 调 query_eu_official() 拿官方字段（已验证过的 SPARQL 查询）。
      3) 查不到这个 CELEX（Cellar 没有）直接判定失败——不编造数据，
         对应 fetch_eu.py 注释里"AI 猜的法规编号必须核实"的教训。
      4) 组装 seed_json（跟库内现有记录格式一致，含"核对状态"字段，
         标记为"待核对"而非"已核对"——如实区分 LLM 自主建档 vs
         人工核对过的记录，不假装已经核实）。
      5) INSERT 进 laws 表，写意图日志。
    """
    law_id = f"EU:{celex}"
    ts = _now_str()
    con = _connect()
    try:
        if _law_exists(con, law_id):
            _write_log(
                {
                    "ts": ts,
                    "law_id": law_id,
                    "action": "skipped_exists",
                    "source": source,
                }
            )
            return {
                "ok": False,
                "law_id": law_id,
                "action": "skipped_exists",
                "reason": "该 law_id 已存在于 laws 表，不覆盖",
            }

        uri = _freshness._fetch_eu.find_cellar_uri(celex)
        if not uri:
            _write_log(
                {
                    "ts": ts,
                    "law_id": law_id,
                    "action": "rejected",
                    "source": source,
                    "reason": "Cellar 找不到该 CELEX，可能是编造或错误的编号",
                }
            )
            return {
                "ok": False,
                "law_id": law_id,
                "action": "rejected",
                "reason": "Cellar 官方数据库找不到该 CELEX 号，不建档",
            }

        import time

        time.sleep(_freshness.REQUEST_INTERVAL)
        fields = _freshness._fetch_eu.get_fields(uri)
        official = _freshness.query_eu_official(celex)

        title = (
            _freshness._fetch_eu.pick(fields, "expression_title")
            or _freshness._fetch_eu.pick(fields, "resource_legal_title")
            or ""
        )
        title = title.replace("\xa0", " ").strip()
        eli = _freshness._fetch_eu.pick(fields, "resource_legal_eli")
        etype = _freshness._fetch_eu.pick(fields, "resource_legal_type")
        year = _freshness._fetch_eu.pick(fields, "resource_legal_year")
        num = _freshness._fetch_eu.pick(fields, "resource_legal_number_natural")
        number = _freshness._fetch_eu.official_number(etype, year, num, celex)
        official_url = f"https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{celex}"

        in_force = official.get("in_force", "")
        entry = official.get("last_modification_date", "")

        seed_payload = {
            "CELEX号": celex,
            "ELI标识": eli,
            "官方标题（英文）": title,
            "官方编号": number,
            "官方链接": official_url,
            "是否官方来源": "官方",
            "机构": "EU",
            "来源类型": "官方原文（OJ）" if in_force == "1" else "官方（待确认效力）",
            "核对人": "",
            "核对日期": "",
            "核对状态": "待核对",  # 如实区分：LLM自主建档，非人工核对
            "法规中文名": "",
            "现行效力": "现行有效" if in_force == "1" else ("已废止" if in_force == "0" else "待确认"),
            "监管机构": "EU",
            "类目": category,
            "编号核对": "一致" if eli else "待查",
            "链接可打开": "待查",
            "备注／问题": f"{note}｜由搜索校验LLM自主建档（{source}），待人工复核" if note
            else f"由搜索校验LLM自主建档（{source}），待人工复核",
        }
        seed_json, seed_sha256 = _seed_json_and_hash(seed_payload)

        cur = con.cursor()
        cur.execute(
            """INSERT INTO laws
               (id, jurisdiction, title_number, part_number, celex,
                seed_json, seed_sha256, official_title, association_review,
                last_modification_date, in_force, latest_amendment_celex,
                latest_corrigendum_celex, updated_at)
               VALUES (?, 'EU', NULL, NULL, ?, ?, ?, ?, '未作适用性判断',
                       ?, ?, ?, ?, ?)""",
            (
                law_id,
                celex,
                seed_json,
                seed_sha256,
                title,
                official.get("last_modification_date"),
                official.get("in_force"),
                official.get("latest_amendment_celex"),
                official.get("latest_corrigendum_celex"),
                ts,
            ),
        )
        con.commit()

        _write_log(
            {
                "ts": ts,
                "law_id": law_id,
                "action": "inserted",
                "source": source,
                "official_title": title,
            }
        )
        return {"ok": True, "law_id": law_id, "action": "inserted", "reason": ""}
    finally:
        con.close()


# ── US ────────────────────────────────────────────────────────────────
def intake_us_law(title_number, part_number, category="", agency="", source="search_verify_llm"):
    """用 Title+Part 号建档一条新 US 法规骨架记录。

    流程跟 intake_eu_law 对称：已存在跳过；查不到对应 eCFR Part 判定
    失败不建档；否则组装 seed_json、INSERT、写日志。

    "查不到"的判定：eCFR structure API 没有现成的"单个 part 是否存在"
    查询，这里用 query_us_official() 的返回是否为空 dict 作为代理判断——
    如果 eCFR 和 FR 都查不到任何字段，大概率是 title/part 号错误。
    """
    law_id = f"US:{title_number}:{part_number}"
    ts = _now_str()
    con = _connect()
    try:
        if _law_exists(con, law_id):
            _write_log(
                {
                    "ts": ts,
                    "law_id": law_id,
                    "action": "skipped_exists",
                    "source": source,
                }
            )
            return {
                "ok": False,
                "law_id": law_id,
                "action": "skipped_exists",
                "reason": "该 law_id 已存在于 laws 表，不覆盖",
            }

        official = _freshness.query_us_official(title_number, part_number)
        if not official:
            _write_log(
                {
                    "ts": ts,
                    "law_id": law_id,
                    "action": "rejected",
                    "source": source,
                    "reason": "eCFR/FR 均查不到该 Title+Part，可能是编造或错误的编号",
                }
            )
            return {
                "ok": False,
                "law_id": law_id,
                "action": "rejected",
                "reason": "eCFR/FR 官方接口都查不到该 Title+Part 号，不建档",
            }

        citation = f"{title_number} CFR Part {part_number}"
        fr_doc = official.get("latest_fr_document_number", "")
        url = f"https://www.ecfr.gov/current/title-{title_number}/part-{part_number}"

        seed_payload = {
            "CELEX号": "",
            "ELI标识": "",
            "官方标题（英文）": "",  # eCFR structure API 需要额外一次 title-level 查询才能取
            # part 的标签文本；骨架级建档不强求，留空交人工/后续补齐
            "官方编号": citation,
            "官方链接": url,
            "是否官方来源": "官方",
            "机构": agency or "US",
            "来源类型": "官方（eCFR）",
            "核对人": "",
            "核对日期": "",
            "核对状态": "待核对",
            "法规中文名": "",
            "现行效力": "现行有效（持续修订）",
            "监管机构": agency or "US",
            "类目": category,
            "编号核对": "待查",
            "链接可打开": "待查",
            "备注／问题": f"由搜索校验LLM自主建档（{source}），待人工复核；"
            f"最新FR文档号：{fr_doc or '未查到'}",
        }
        seed_json, seed_sha256 = _seed_json_and_hash(seed_payload)

        cur = con.cursor()
        cur.execute(
            """INSERT INTO laws
               (id, jurisdiction, title_number, part_number, celex,
                seed_json, seed_sha256, official_title, association_review,
                latest_fr_document_number, fr_effective_on, updated_at)
               VALUES (?, 'US', ?, ?, NULL, ?, ?, ?, '未作适用性判断',
                       ?, ?, ?)""",
            (
                law_id,
                title_number,
                part_number,
                seed_json,
                seed_sha256,
                None,  # official_title 留空：citation（如"16 CFR Part 1215"）只是
                # 引用编号，不是法规标题文本，填进这一列会让人误以为标题已抓到——
                # 真实标题需要额外查 eCFR title-level 结构才能拿到人类可读的
                # Part label，骨架级建档不做这一步。citation 本身没有丢失，
                # 完整保留在 seed_json 的"官方编号"字段里。
                official.get("latest_fr_document_number"),
                official.get("fr_effective_on"),
                ts,
            ),
        )
        con.commit()

        _write_log(
            {
                "ts": ts,
                "law_id": law_id,
                "action": "inserted",
                "source": source,
                "citation": citation,
            }
        )
        return {"ok": True, "law_id": law_id, "action": "inserted", "reason": ""}
    finally:
        con.close()