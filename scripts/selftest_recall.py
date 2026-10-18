# -*- coding: utf-8 -*-
"""
召回目录树 · 离线自检（scripts/selftest_recall.py）

用临时 SQLite 构造最小语料，验证：
    1. canonical 文档选择规则与选择原因
    2. heading 归一/补标题/纯编号标记
    3. US subpart 父子推导、[Reserved] 处理
    4. 分块上限与语义锚点（CLP index / REACH entry / US 段落 / hard window）
    5. node_id / tree_version 的确定性
    6. FTS 候选与 core.recall 只读访问层
    7. 校验能捕获 orphan / 空 heading / 容器带 body / 超限 / FTS 不一致
    8. dry-run 不写派生表

用法：
    python scripts/selftest_recall.py
退出码 0 = 全绿；1 = 有失败项。
"""

import os
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

import build_recall_tree as brt  # noqa: E402
from core import recall  # noqa: E402

PASS, FAIL = [], []


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
        id TEXT PRIMARY KEY, kind TEXT, version_date TEXT, source_url TEXT,
        full_text TEXT)""",
    """CREATE TABLE law_documents(
        law_id TEXT, document_id TEXT, role TEXT,
        PRIMARY KEY(law_id, document_id, role))""",
    """CREATE TABLE units(
        document_id TEXT, ordinal INTEGER, locator TEXT, unit_type TEXT,
        heading TEXT, body TEXT, source_fragment TEXT,
        PRIMARY KEY(document_id, ordinal))""",
]


def make_db():
    path = os.path.join(tempfile.mkdtemp(prefix="recall_selftest_"), "src.db")
    con = brt.connect(path)
    for sql in SOURCE_SCHEMA:
        con.execute(sql)
    con.commit()
    return path, con


def add_law(con, law_id, jur, title=None, seed_json="{}"):
    con.execute(
        "INSERT INTO laws VALUES (?,?,?,?,?,?)",
        (law_id, jur, title or law_id, "现行有效", "现行有效", seed_json),
    )


def add_doc(con, doc_id, kind, full_text="", version_date="2026-01-01"):
    con.execute(
        "INSERT INTO documents VALUES (?,?,?,?,?)",
        (doc_id, kind, version_date, "http://example/%s" % doc_id, full_text),
    )


def add_link(con, law_id, doc_id, role):
    con.execute("INSERT INTO law_documents VALUES (?,?,?)", (law_id, doc_id, role))


def add_unit(con, doc_id, ordinal, unit_type, heading, body, fragment=None):
    con.execute(
        "INSERT INTO units VALUES (?,?,?,?,?,?,?)",
        (doc_id, ordinal, "#u%d" % ordinal, unit_type, heading, body, fragment),
    )


def seed_selection_db(con):
    # US: primary
    add_law(con, "US:16:1500", "US", "PART 1500—HAZARDOUS SUBSTANCES")
    add_doc(con, "US-eCFR:16:1500", "us_ecfr", "full us text")
    add_link(con, "US:16:1500", "US-eCFR:16:1500", "primary")
    add_unit(con, "US-eCFR:16:1500", 0, "section", "§ 1500.1 Scope.",
             "§ 1500.1 Scope. " + "x" * 100)

    # EU: no consolidated
    add_law(con, "EU:32005R0396", "EU", "REGULATION 396/2005")
    add_doc(con, "EU-DOC:32005R0396", "eu_original", "full eu text")
    add_link(con, "EU:32005R0396", "EU-DOC:32005R0396", "primary")
    add_unit(con, "EU-DOC:32005R0396", 0, "article", "Article 1",
             "Article 1 Subject matter " + "x" * 100)

    # EU: consolidated full_text too short
    add_law(con, "EU:31994L0011", "EU", "DIRECTIVE 94/11")
    add_doc(con, "EU-DOC:31994L0011", "eu_original", "primary text " * 100)
    add_doc(con, "EU-DOC:01994L0011-2013", "eu_consolidated", "short")
    add_link(con, "EU:31994L0011", "EU-DOC:31994L0011", "primary")
    add_link(con, "EU:31994L0011", "EU-DOC:01994L0011-2013", "eu_consolidated")
    for i in range(8):
        add_unit(con, "EU-DOC:31994L0011", i, "article", "Article %d" % (i + 1),
                 "Article %d body %s" % (i + 1, "x" * 100))
    for i in range(3):
        add_unit(con, "EU-DOC:01994L0011-2013", i, "article", "Article %d" % (i + 1),
                 "Article %d body %s" % (i + 1, "x" * 100))

    # EU: consolidated below min units
    add_law(con, "EU:32001L0095", "EU", "DIRECTIVE 2001/95")
    add_doc(con, "EU-DOC:32001L0095", "eu_original", "primary text " * 100)
    add_doc(con, "EU-DOC:02001L0095-2026", "eu_consolidated", "consolidated text " * 100)
    add_link(con, "EU:32001L0095", "EU-DOC:32001L0095", "primary")
    add_link(con, "EU:32001L0095", "EU-DOC:02001L0095-2026", "eu_consolidated")
    for i in range(20):
        add_unit(con, "EU-DOC:32001L0095", i, "article", "Article %d" % (i + 1),
                 "Article %d body %s" % (i + 1, "x" * 100))
    for i in range(3):
        add_unit(con, "EU-DOC:02001L0095-2026", i, "article", "Article %d" % (i + 1),
                 "Article %d body %s" % (i + 1, "x" * 100))

    # EU: consolidated healthy (28 vs primary 29)
    add_law(con, "EU:32004R1935", "EU", "REGULATION 1935/2004")
    add_doc(con, "EU-DOC:32004R1935", "eu_original", "primary text " * 100)
    add_doc(con, "EU-DOC:02004R1935-2026", "eu_consolidated", "consolidated text " * 100)
    add_link(con, "EU:32004R1935", "EU-DOC:32004R1935", "primary")
    add_link(con, "EU:32004R1935", "EU-DOC:02004R1935-2026", "eu_consolidated")
    for i in range(29):
        add_unit(con, "EU-DOC:32004R1935", i, "article", "Article %d" % (i + 1),
                 "Article %d body %s" % (i + 1, "x" * 100))
    for i in range(28):
        add_unit(con, "EU-DOC:02004R1935-2026", i, "article", "Article %d" % (i + 1),
                 "Article %d body %s" % (i + 1, "x" * 100))
    con.commit()


def seed_tree_db(con):
    """一棵 US 树 + 一棵 EU 树，用于建树/FTS/访问层测试。"""
    add_law(con, "US:16:1500", "US", "PART 1500—HAZARDOUS SUBSTANCES",
            '{"类目":"儿童玩具","法规中文名":"危险物质法","官方编号":"16 CFR Part 1500"}')
    add_doc(con, "US-eCFR:16:1500", "us_ecfr", "full us text")
    add_link(con, "US:16:1500", "US-eCFR:16:1500", "primary")
    add_unit(con, "US-eCFR:16:1500", 0, "subpart", "Subpart A—General",
             "Subpart A—General\n§ 1500.1 Scope.")
    add_unit(con, "US-eCFR:16:1500", 1, "section", "§ 1500.1 Scope of subchapter.",
             "§ 1500.1 Scope of subchapter. This part applies to toys. " + "x" * 80)
    add_unit(con, "US-eCFR:16:1500", 2, "section", "§ 1500.2 Authority.",
             "§ 1500.2 Authority. The Commission. " + "x" * 80)
    add_unit(con, "US-eCFR:16:1500", 3, "subpart", "Subpart B—Requirements",
             "Subpart B—Requirements\n§ 1500.3 Requirements.")
    add_unit(con, "US-eCFR:16:1500", 4, "section", "§ 1500.3 Requirements.",
             "§ 1500.3 Requirements. Phthalate limits. " + "x" * 80)
    add_unit(con, "US-eCFR:16:1500", 5, "subpart", "Subpart C [Reserved]",
             "Subpart C [Reserved]")
    add_unit(con, "US-eCFR:16:1500", 6, "section", "§ 1500.4 [Reserved]",
             "§ 1500.4 [Reserved]")
    add_unit(con, "US-eCFR:16:1500", 7, "appendix",
             "Appendix A to Part 1500—Glossary",
             "Appendix A to Part 1500—Glossary. " + "x" * 80)

    add_law(con, "EU:32009L0048", "EU", "Directive 2009/48/EC on toy safety")
    add_doc(con, "EU-DOC:02009L0048-2026", "eu_consolidated",
            "consolidated text " * 100)
    add_link(con, "EU:32009L0048", "EU-DOC:02009L0048-2026", "eu_consolidated")
    add_unit(con, "EU-DOC:02009L0048-2026", 0, "article", "Article 1",
             "Article 1 Subject-matter\nThis Directive lays down rules.")
    add_unit(con, "EU-DOC:02009L0048-2026", 1, "article", "Article 2 — Scope",
             "Article 2\nScope\nThis Directive applies to toys.")
    add_unit(con, "EU-DOC:02009L0048-2026", 2, "annex", "ANNEX I",
             "ANNEX I\nList of toy categories\n" + ("A" * 7000))
    con.commit()


def find_law(con, law_id):
    for law in brt.load_laws(con):
        if law["law_id"] == law_id:
            return law
    raise KeyError(law_id)


# ── 测试 ────────────────────────────────────────────────────────────
def test_canonical_selection():
    path, con = make_db()
    try:
        seed_selection_db(con)
        cases = [
            ("US:16:1500", "primary", "us_primary"),
            ("EU:32005R0396", "primary", "no_consolidated"),
            ("EU:31994L0011", "primary", "consolidated_no_full_text"),
            ("EU:32001L0095", "primary", "consolidated_below_min_units"),
            ("EU:32004R1935", "eu_consolidated", "consolidated"),
        ]
        for law_id, role, reason in cases:
            sel = brt.select_canonical_document(con, find_law(con, law_id))
            check("%s -> %s / %s" % (law_id, role, reason),
                  sel["role"] == role and sel["reason"] == reason,
                  "got %s / %s" % (sel["role"], sel["reason"]))
    finally:
        con.close()


def test_heading():
    cases = [
        (("Article 5 — Prohibitions", "", "article", "#a5", ""),
         ("Article 5", "Prohibitions")),
        (("Article 9", "Article 9\nExemption from registration", "article", "#a9", ""),
         ("Article 9", "Exemption from registration")),
        (("ANNEX VI — Harmonised classification", "", "annex", "#a6", ""),
         ("ANNEX VI", "Harmonised classification")),
        (("ANNEX — ANNEX II", "", "annex", "#a2", ""),
         ("ANNEX II", None)),
        (("ANNEX XVII — ▼M5", "ANNEX XVII\n▼M5\nRESTRICTIONS ON USE", "annex", "#a17", ""),
         ("ANNEX XVII", "RESTRICTIONS ON USE")),
        (("§ 176.170 Components of paper", "", "section", "176.170", ""),
         ("§ 176.170", "Components of paper")),
        (("Subpart B—Substances", "", "subpart", "B", ""),
         ("Subpart B", "Substances")),
        (("Appendix A to Part 423—Glossary of Terms", "", "appendix", "A", ""),
         ("Appendix A to Part 423", "Glossary of Terms")),
        (("Article 1", "Article 1 Subject matter", "article", "#a1",
          "<STI.ART>Subject matter</STI.ART>"),
         ("Article 1", "Subject matter")),
    ]
    for args, expected in cases:
        norm = brt.normalize_heading(*args)
        check("heading %r -> %r" % (args[0], norm["heading"]),
              (norm["label"], norm["title"]) == expected,
              "got (%r, %r)" % (norm["label"], norm["title"]))

    norm = brt.normalize_heading("Article 3", "Article 3 Without prejudice", "article", "#a3", "")
    check("无标题条款保留 label_only",
          norm["heading"] == "Article 3" and "label_only" in norm["flags"],
          str(norm))


def test_us_parents():
    path, con = make_db()
    try:
        seed_tree_db(con)
        plan = brt.build_plan(con, 6000)
        nodes = {n["node_id"]: n for n in plan["nodes"]}
        root = "rc|US:16:1500|root"
        sub_a = "rc|US:16:1500|u0"
        sub_b = "rc|US:16:1500|u3"
        check("section §1500.1 挂在 Subpart A",
              nodes["rc|US:16:1500|u1"]["parent_id"] == sub_a,
              str(nodes["rc|US:16:1500|u1"]["parent_id"]))
        check("section §1500.3 挂在 Subpart B",
              nodes["rc|US:16:1500|u4"]["parent_id"] == sub_b,
              str(nodes["rc|US:16:1500|u4"]["parent_id"]))
        check("section path 含 Subpart A",
              "Subpart A" in nodes["rc|US:16:1500|u1"]["path"],
              nodes["rc|US:16:1500|u1"]["path"])
        check("reserved subpart 是非实质叶子",
              nodes["rc|US:16:1500|u5"]["is_leaf"] == 1
              and nodes["rc|US:16:1500|u5"]["is_substantive"] == 0
              and "reserved_subpart" in nodes["rc|US:16:1500|u5"]["flags"],
              str(nodes["rc|US:16:1500|u5"]))
        check("reserved section 是非实质叶子",
              nodes["rc|US:16:1500|u6"]["is_substantive"] == 0
              and "reserved_section" in nodes["rc|US:16:1500|u6"]["flags"],
              str(nodes["rc|US:16:1500|u6"]))
        check("appendix 挂根",
              nodes["rc|US:16:1500|u7"]["parent_id"] == root,
              str(nodes["rc|US:16:1500|u7"]["parent_id"]))
        check("EU annex 超长被切分",
              nodes["rc|EU:32009L0048|u2"]["is_leaf"] == 0
              and any(n["parent_id"] == "rc|EU:32009L0048|u2" and n["node_type"] == "chunk"
                      for n in plan["nodes"]),
              "annex u2")
    finally:
        con.close()


def test_chunking():
    chunks = brt.chunk_text("a" * 15000, "US:16:1500", "section", "§ x", "1", 6000)
    check("15000 字符无锚点 -> 全部 <=6000", all(len(c["text"]) <= 6000 for c in chunks))
    check("15000 字符无锚点 -> 至少 3 块", len(chunks) >= 3, str(len(chunks)))

    chunks = brt.chunk_text("b" * 6000, "US:16:1500", "section", "§ x", "1", 6000)
    check("恰好 6000 -> 1 块", len(chunks) == 1, str(len(chunks)))

    clp = "\n".join(
        "%03d-%03d-%02d-%s entry %d\n" % (607, i, i % 100, "X" if i % 7 == 0 else i % 10, i)
        + ("z" * 700)
        for i in range(10)
    )
    chunks = brt.chunk_text(clp, "EU:32008R1272", "annex", "ANNEX VI", "#anx_VI", 6000)
    check("CLP index 切分全部 <=6000", all(len(c["text"]) <= 6000 for c in chunks))
    check("CLP index 使用了语义锚点", any(c.get("strategy") == "clp_index" for c in chunks),
          str([c.get("strategy") for c in chunks]))

    reach = "\n".join("%d.  substance %d\n" % (i, i) + ("y" * 900) for i in range(1, 11))
    chunks = brt.chunk_text(reach, "EU:32006R1907", "annex", "ANNEX XVII", "#anx_XVII", 6000)
    check("REACH entry 切分全部 <=6000", all(len(c["text"]) <= 6000 for c in chunks))
    check("REACH entry 使用了语义锚点", any(c.get("strategy") == "annex_entry" for c in chunks),
          str([c.get("strategy") for c in chunks]))

    us = "\n".join("(%s) paragraph %s\n" % (chr(97 + i), "w" * 900) for i in range(10))
    chunks = brt.chunk_text(us, "US:16:1500", "section", "§ x", "1", 6000)
    check("US 段落切分全部 <=6000", all(len(c["text"]) <= 6000 for c in chunks))
    check("US 段落使用了语义锚点", any(c.get("strategy") == "us_para_top" for c in chunks),
          str([c.get("strategy") for c in chunks]))


def test_tree_and_access():
    path, con = make_db()
    try:
        seed_tree_db(con)
        plan = brt.build_plan(con, 6000)
        check("dry-run 不建 recall_nodes", not brt.table_exists(con, "recall_nodes"))
        check("plan 校验通过", not plan["validation"]["errors"], str(plan["validation"]["errors"]))
        ids1 = {n["node_id"] for n in plan["nodes"]}
        ver1 = plan["tree_version"]
        plan2 = brt.build_plan(con, 6000)
        ids2 = {n["node_id"] for n in plan2["nodes"]}
        check("同数据两次构建 node_id 一致", ids1 == ids2)
        check("同数据两次构建 tree_version 一致", ver1 == plan2["tree_version"],
              "%s vs %s" % (ver1, plan2["tree_version"]))
        plan3 = brt.build_plan(con, 3000)
        check("max_chars 变化 -> tree_version 变化",
              plan3["tree_version"] != ver1)

        result = brt.write_plan(con, plan)
        check("写库后校验通过", not result["errors"], str(result["errors"]))
        check("recall_nodes 行数 = plan 节点数",
              con.execute("SELECT COUNT(*) FROM recall_nodes").fetchone()[0] == len(plan["nodes"]))
        check("FTS 行数 = 节点数",
              con.execute("SELECT COUNT(*) FROM recall_nodes_fts").fetchone()[0] == len(plan["nodes"]))

        recall.DB_PATH = path
        recall._reset_cache()
        check("recall.tree_version 可读", recall.tree_version() == ver1,
              str(recall.tree_version()))
        catalog = recall.law_catalog()
        check("law_catalog 带 ref 且覆盖两法",
              len(catalog) == 2 and catalog[0].get("ref") == 1,
              str([(c["law_id"], c.get("ref")) for c in catalog]))
        cands = recall.candidate_nodes(["US:16:1500"], ["phthalate"], 10)
        check("candidate_nodes 命中 phthalate",
              any("phthalate" in (c.get("snippet") or "").lower() for c in cands),
              str([(c.get("heading"), c.get("snippet", "")[:40]) for c in cands]))
        check("candidate_nodes 带 ref/node_id",
              bool(cands) and cands[0].get("ref") == 1 and cands[0].get("node_id"))
        valid, invalid = recall.resolve_refs([1, 99, "x", True, 1], cands)
        check("resolve_refs 严格过滤非整数/越界，重复 ref 去重",
              len(valid) == 1 and len(invalid) == 3,
              "valid=%d invalid=%s" % (len(valid), invalid))
        got = recall.get_nodes([cands[0]["node_id"]])
        check("get_nodes 返回正文", bool(got) and bool(got[0].get("body")))
        tree = recall.load_tree(["US:16:1500"], include_body=False)
        check("load_tree 不含 body", bool(tree) and "body" not in tree["US:16:1500"][0])
        cn = recall.candidate_nodes(["US:16:1500"], ["邻苯二甲酸酯"], 5)
        check("中文关键词不抛错/有回退", isinstance(cn, list) and len(cn) > 0)
        recall.close()
    finally:
        con.close()


def test_validation():
    path, con = make_db()
    try:
        seed_tree_db(con)
        plan = brt.build_plan(con, 6000)
        # 复制一份节点列表做篡改
        import copy
        bad = copy.deepcopy(plan)
        by_id = {n["node_id"]: n for n in bad["nodes"]}
        # orphan：把某个 section 的 parent 改掉
        by_id["rc|US:16:1500|u1"]["parent_id"] = "missing"
        res = brt.validate_plan(bad)
        check("校验捕获 orphan", any("父节点不存在" in e for e in res["errors"]),
              str(res["errors"][:3]))

        bad2 = copy.deepcopy(plan)
        by_id2 = {n["node_id"]: n for n in bad2["nodes"]}
        by_id2["rc|US:16:1500|u1"]["heading"] = ""
        res2 = brt.validate_plan(bad2)
        check("校验捕获空 heading", any("heading 为空" in e for e in res2["errors"]))

        bad3 = copy.deepcopy(plan)
        by_id3 = {n["node_id"]: n for n in bad3["nodes"]}
        by_id3["rc|US:16:1500|u0"]["body"] = "not null"
        res3 = brt.validate_plan(bad3)
        check("校验捕获容器带 body", any("容器 body 非空" in e for e in res3["errors"]))

        brt.write_plan(con, plan)
        con.execute("DELETE FROM recall_nodes_fts WHERE node_id='rc|US:16:1500|u1'")
        con.commit()
        res4 = brt.validate_db(con, 6000, 2)
        check("validate_db 捕获 FTS 行数不一致",
              any("FTS 行数" in e for e in res4["errors"]), str(res4["errors"]))
    finally:
        con.close()


def main():
    print("=" * 70)
    print("  召回目录树 · 自检")
    print("=" * 70)
    print("\n【1】canonical 文档选择")
    test_canonical_selection()
    print("\n【2】heading 归一")
    test_heading()
    print("\n【3】US 父子与 reserved")
    test_us_parents()
    print("\n【4】分块")
    test_chunking()
    print("\n【5】建树 / FTS / 访问层")
    test_tree_and_access()
    print("\n【6】校验")
    test_validation()
    print("\n" + "=" * 70)
    print("  通过 %d 项，失败 %d 项" % (len(PASS), len(FAIL)))
    if FAIL:
        for name, detail in FAIL:
            print("  FAIL: %s  %s" % (name, detail))
        print("=" * 70)
        return 1
    print("  ALL PASS")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
