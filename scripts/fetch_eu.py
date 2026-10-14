# -*- coding: utf-8 -*-
"""
欧盟法规骨架数据抓取器（EUR-Lex / Cellar SPARQL 官方接口）

用途：
    已知 CELEX 号 → 调欧盟官方 SPARQL 接口 → 拿到该法规的全部官方元数据
    （标题、ELI、生效日期、是否现行有效、取代关系……）

数据源：
    https://publications.europa.eu/webapi/rdf/sparql   （免费、免密钥）

⚠️ 重要：
    不要试图爬 eur-lex.europa.eu 网页 —— 它有 AWS WAF 人机验证墙。
    本脚本走的是官方数据接口，不受影响。

输出：
    data/eu_regulations.csv

用法：
    python scripts/fetch_eu.py

变更记录（2026-10-14 修复，对应《代码审查报告》）：
    - [问题10] 「官方编号」改为官方可读写法（Regulation (EU) 2025/2509），
      不再输出 "R2025/2509" 这种既非 CELEX 也非官方引用的形式。
      注：指令/决定的机构后缀（EC/EU/EURATOM）随条约年代而变，接口未直接给出，
      为避免写错，这里只生成 "Directive 2009/48" 并在备注提示补后缀。
    - [新增问题6] 新增「现行效力」列，直接取 resource_legal_in-force，不再只塞备注。
    - [新增问题10] 标题截断时在备注里留痕，读者能区分"原文如此"与"被程序截断"。
"""

import csv
import json
import os
import sys
import time
import urllib.parse
import urllib.request
import urllib.error

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

SPARQL = "https://publications.europa.eu/webapi/rdf/sparql"
HEADERS = {
    "User-Agent": "compliance-radar/1.0 (academic research)",
    "Accept": "application/sparql-results+json",
}
INTERVAL = 1.5

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
OUT_DIR = os.path.join(PROJECT, "data")

CDM = "http://publications.europa.eu/ontology/cdm#"
XSD_STRING = "http://www.w3.org/2001/XMLSchema#string"


def sparql(query, retries=3):
    """执行 SPARQL 查询，返回 bindings 列表。"""
    params = urllib.parse.urlencode({
        "query": query,
        "format": "application/sparql-results+json",
    })
    url = f"{SPARQL}?{params}"

    last_err = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=90) as r:
                data = json.loads(r.read().decode("utf-8"))
            return data.get("results", {}).get("bindings", [])
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code}"
            time.sleep(2 * (i + 1))
        except Exception as e:
            last_err = str(e)
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"SPARQL 失败：{last_err}")


def q_escape(s):
    return s.replace("\\", "\\\\").replace('"', '\\"')


def find_cellar_uri(celex):
    """用 CELEX 号找 Cellar URI。

    ⚠️ 踩坑记录（实测）：
        CELEX 在 Cellar 里是**带类型的字面量**，必须写成
            "32025R2509"^^<http://www.w3.org/2001/XMLSchema#string>
        写成裸字符串 "32025R2509" 会返回 HTTP 200 但 bindings 为 0，
        表现得像「这条法规不存在」，极难排查。
    """
    q = f'''
    PREFIX cdm: <{CDM}>
    SELECT ?work WHERE {{
      ?work cdm:resource_legal_id_celex "{q_escape(celex)}"^^<{XSD_STRING}> .
    }} LIMIT 5
    '''
    rows = sparql(q)
    if not rows:
        return None
    return rows[0]["work"]["value"]


def get_fields(cellar_uri):
    """拿某个 Cellar 资源的所有字段。

    ⚠️ 踩坑记录（实测）：
        1. 标题**不在 work 上**，work_title 返回 0 行。
           它挂在 expression（各语言版本）上，字段名是 expression_title。
        2. 一条法规有 24 种语言的 expression，直接全取会重复。
           必须加 FILTER 只留英文（ENG）。
    """
    q = f'''
    PREFIX cdm: <{CDM}>
    SELECT ?p ?o WHERE {{
      <{cellar_uri}> ?p ?o .
    }} LIMIT 200
    '''
    rows = sparql(q)
    out = {}
    for r in rows:
        p = r["p"]["value"].split("#")[-1].split("/")[-1]
        o = r["o"]["value"]
        out.setdefault(p, []).append(o)

    # 单独补一次英文标题（走 expression 路径）
    qt = f'''
    PREFIX cdm: <{CDM}>
    SELECT ?title WHERE {{
      ?exp cdm:expression_belongs_to_work <{cellar_uri}> .
      ?exp cdm:expression_title ?title .
      ?exp cdm:expression_uses_language ?lang .
      FILTER(CONTAINS(STR(?lang), "ENG"))
    }} LIMIT 3
    '''
    try:
        trows = sparql(qt)
        if trows:
            out["expression_title"] = [t["title"]["value"] for t in trows]
    except Exception:
        pass

    return out


def pick(fields, key, idx=0):
    v = fields.get(key)
    if not v:
        return ""
    try:
        return v[idx]
    except IndexError:
        return ""


# 法规类型 → 官方可读前缀
TYPE_WORD = {"R": "Regulation", "L": "Directive", "D": "Decision"}


def official_number(etype, year, num, celex):
    """把 CELEX 拆出的类型/年/序号，拼成官方可读编号。

    例：R/2025/2509 → "Regulation (EU) 2025/2509"
        L/2009/48   → "Directive 2009/48"（机构后缀 EC/EU 需按 OJ 确认后再补）
    """
    w = TYPE_WORD.get((etype or "").upper())
    if not (w and year and num):
        return celex
    if w == "Regulation":
        return f"Regulation (EU) {year}/{num}"
    return f"{w} {year}/{num}"


# ── 目标清单（按品类组织，只列 CELEX 号） ────────────────────
# 说明：CELEX 号格式 = 部门号(3) + 年份(4位) + 类型字母 + 序号
#   R=Regulation(条例)  L=Directive(指令)  D=Decision(决定)
TARGETS = [
    # ── 儿童玩具 ──
    {"celex": "32025R2509", "category": "儿童玩具", "note": "玩具安全条例（取代 2009/48/EC）"},
    {"celex": "32009L0048", "category": "儿童玩具", "note": "玩具安全指令（旧法，2030-08-01 废止）"},

    # ── 通用产品安全（覆盖全品类） ──
    {"celex": "32023R0988", "category": "通用", "note": "通用产品安全法规 GPSR"},

    # ── 电子电器 ──
    {"celex": "32014L0053", "category": "电子电器", "note": "无线电设备指令 RED"},
    {"celex": "32011L0065", "category": "电子电器", "note": "限制有害物质指令 RoHS"},
    {"celex": "32012L0019", "category": "电子电器", "note": "废弃电子电气设备指令 WEEE"},
    {"celex": "32014L0030", "category": "电子电器", "note": "电磁兼容指令 EMC"},
    {"celex": "32009L0125", "category": "电子电器", "note": "生态设计框架指令"},
    {"celex": "32014L0035", "category": "电子电器", "note": "低电压指令 LVD"},
    {"celex": "32023R1542", "category": "电子电器", "note": "电池与废电池法规（取代电池指令 2006/66/EC）"},
    {"celex": "32009R0640", "category": "电子电器", "note": "电动机生态设计要求实施条例"},
    {"celex": "32017R1369", "category": "电子电器", "note": "能源相关产品能效标识框架法规"},

    # ── 纺织服装 ──
    {"celex": "32011R1007", "category": "纺织服装", "note": "纺织品纤维名称法规"},
    {"celex": "32008R1272", "category": "纺织服装", "note": "化学品分类标签包装法规 CLP"},
    {"celex": "32006R1907", "category": "纺织服装", "note": "化学品注册评估授权限制法规 REACH"},
    {"celex": "32023R1671", "category": "纺织服装", "note": "相关产品实施条例"},

    # ── 美妆个护 ──
    {"celex": "32009R1223", "category": "美妆个护", "note": "化妆品法规"},

    # ── 食品接触材料 ──
    {"celex": "32004R1935", "category": "食品接触材料", "note": "食品接触材料框架法规"},
    {"celex": "32011R0010", "category": "食品接触材料", "note": "食品接触塑料材料法规"},
    {"celex": "32005R0396", "category": "食品接触材料", "note": "食品接触材料良好生产规范"},
    {"celex": "32011L0008", "category": "食品接触材料", "note": "食品接触塑料材料指令修订（双酚 A 限制）"},
    {"celex": "32009R0450", "category": "食品接触材料", "note": "食品接触活性与智能材料法规"},
    {"celex": "32022R1616", "category": "食品接触材料", "note": "食品接触再生塑料法规"},
    {"celex": "32007R0901", "category": "食品接触材料", "note": "食品接触陶瓷制品法规"},

    # ── 标签标识 ──
    {"celex": "32011R1169", "category": "标签标识", "note": "食品信息消费者法规"},
    {"celex": "31994L0011", "category": "标签标识", "note": "包装及包装废弃物指令"},
    {"celex": "32025R0040", "category": "标签标识", "note": "包装与包装废弃物法规 PPWR（取代 94/62/EC）"},
    {"celex": "32001L0095", "category": "标签标识", "note": "通用产品安全指令（GPSR 前身）"},

    # ── 儿童玩具：儿童用品生态设计 ──
    {"celex": "32023R1670", "category": "儿童玩具", "note": "儿童用品生态设计要求条例"},
]

# ⚠️ 下面每个 CELEX 都必须已用官方 SPARQL 接口逐个验证存在。
#    教训：AI 猜的法规编号必须核实 —— 初版写过的 32015R1000 就不存在，已删。


COLS = ["类目", "机构", "法规中文名", "官方标题（英文）", "官方编号", "CELEX号",
        "ELI标识", "官方链接", "来源类型", "现行效力", "生效日期", "最新修订日期",
        "链接可打开", "编号核对", "是否官方来源", "核对状态", "核对人", "核对日期", "备注／问题"]


def main():
    print("=" * 62)
    print("  欧盟法规骨架抓取 —— EUR-Lex / Cellar 官方 SPARQL 接口")
    print("=" * 62)
    print()

    rows = []
    ok = 0
    fail = 0

    for t in TARGETS:
        celex = t["celex"]
        print(f"  查询 {celex} ({t['note']}) ...", end=" ")

        try:
            uri = find_cellar_uri(celex)
            if not uri:
                print("未找到")
                fail += 1
                rows.append(empty_row(t, "未在官方数据库找到该 CELEX 号"))
                time.sleep(INTERVAL)
                continue

            time.sleep(INTERVAL)
            f = get_fields(uri)

            title = pick(f, "expression_title") or pick(f, "work_title") or pick(f, "resource_legal_title")
            # 清理不可见字符（Cellar 标题里有 \xa0 = 不换行空格）
            title = title.replace("\xa0", " ").replace("&#11;", " ").strip()
            # 标题过长时截断，避免 Excel 里撑爆单元格；但要在备注里留痕（修复）
            truncated = len(title) > 300
            if truncated:
                title = title[:297] + "..."

            eli = pick(f, "resource_legal_eli")
            entry = f.get("resource_legal_date_entry-into-force", [])
            # ⚠️ 清洗脏日期：官方接口有时返回 1001-01-01 这类占位值，必须剔除
            entry = [d for d in entry if not d.startswith("1001") and not d.startswith("9999")]
            sig = pick(f, "resource_legal_date_signature")
            inforce = pick(f, "resource_legal_in-force")
            etype = pick(f, "resource_legal_type")
            year = pick(f, "resource_legal_year")
            num = pick(f, "resource_legal_number_natural")
            repeals = f.get("resource_legal_repeals_resource_legal", [])

            official_url = f"https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{celex}"
            number = official_number(etype, year, num, celex)

            note_parts = [t["note"]]
            if entry:
                note_parts.append(f"生效/适用日期：{'、'.join(entry)}")
            if inforce:
                note_parts.append(f"现行有效：{'是' if inforce == '1' else '否'}")
            if repeals:
                note_parts.append(f"取代了 {len(repeals)} 条法规")
            if len(f.get("resource_legal_date_entry-into-force", [])) > 1:
                note_parts.append("⚠️有多个日期，注意区分生效日与适用日")
            if truncated:
                note_parts.append("⚠️标题超 300 字符已截断，完整标题见官方链接")

            rows.append({
                "类目": t["category"],
                "机构": "EU",
                "法规中文名": "",
                "官方标题（英文）": title,
                "官方编号": number,
                "CELEX号": celex,
                "ELI标识": eli,
                "官方链接": official_url,
                "来源类型": "官方原文（OJ）" if inforce == "1" else "官方（待确认效力）",
                "现行效力": "现行有效" if inforce == "1" else ("已废止" if inforce == "0" else "待确认"),
                "生效日期": entry[0] if entry else "",
                "最新修订日期": "",
                "链接可打开": "待查",
                "编号核对": "一致" if eli or inforce else "待查",
                "是否官方来源": "官方",
                "核对状态": "待核对",
                "核对人": "",
                "核对日期": "",
                "备注／问题": "；".join(note_parts),
            })
            ok += 1
            print(f"OK  现行有效={inforce or '?'}  生效={entry[0] if entry else '?'}")

        except Exception as e:
            print(f"失败：{e}")
            fail += 1
            rows.append(empty_row(t, f"查询失败：{str(e)[:80]}"))

        time.sleep(INTERVAL)

    print()
    print(f"  成功 {ok} 条，失败 {fail} 条")

    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, "eu_regulations.csv")
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    print(f"  已保存：{out}")
    print("=" * 62)


def empty_row(t, reason):
    return {
        "类目": t["category"], "机构": "EU", "法规中文名": "",
        "官方标题（英文）": "", "官方编号": "", "CELEX号": t["celex"],
        "ELI标识": "", "官方链接": "", "来源类型": "", "现行效力": "",
        "生效日期": "", "最新修订日期": "",
        "链接可打开": "待查", "编号核对": "待查", "是否官方来源": "待确认",
        "核对状态": "有问题", "核对人": "", "核对日期": "",
        "备注／问题": reason,
    }


if __name__ == "__main__":
    main()
