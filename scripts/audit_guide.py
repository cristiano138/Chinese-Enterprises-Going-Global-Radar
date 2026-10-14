# -*- coding: utf-8 -*-
"""
核对《官方法规网站查找指南》里的所有链接和数据。

两部分：
  1. 链接可达性：逐个实测 HTTP 状态（区分正常/人机验证墙/失效）
  2. 数据准确性：把文档里的法规编号、CFR 条款号，拿到官方数据源交叉核对

输出：
    data/指南核对报告.md

用法：
    python scripts/audit_guide.py
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
DATA = os.path.join(PROJECT, "data")
GUIDE = r"E:\浙客松天猫OPC赛道\官方法规网站查找指南.md"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def probe(url, timeout=30):
    """返回 (状态码, 判定, 说明)。判定分 OK / WAF / BAD。"""
    for method in ("HEAD", "GET"):
        try:
            req = urllib.request.Request(url, method=method, headers={
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml,*/*",
                "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
            })
            with urllib.request.urlopen(req, timeout=timeout) as r:
                status = r.status
                body = b""
                if method == "GET":
                    body = r.read(8192)
            if status == 202:
                if method == "HEAD":
                    continue
                txt = body.decode("utf-8", "ignore").lower()
                if "awswaf" in txt or "challenge" in txt:
                    return "202", "WAF", "人机验证墙（真人浏览器可打开）"
                return "202", "WAF?", "返回 202，需人工确认"
            if 200 <= status < 300:
                return str(status), "OK", "可访问"
            return str(status), "BAD", f"HTTP {status}"
        except urllib.error.HTTPError as e:
            if e.code in (403, 405, 501, 406) and method == "HEAD":
                continue
            if e.code == 403:
                return "403", "WAF", "拒绝程序访问（可能有人机验证）"
            if e.code == 404:
                return "404", "BAD", "页面不存在"
            return str(e.code), "BAD", f"HTTP {e.code}"
        except Exception as e:
            if method == "HEAD":
                continue
            return type(e).__name__, "BAD", str(e)[:70]
    return "?", "BAD", "所有方法均失败"


# ── 官方数据源交叉核对 ─────────────────────────────────────
SPARQL = "https://publications.europa.eu/webapi/rdf/sparql"
CDM = "http://publications.europa.eu/ontology/cdm#"
XSD = "http://www.w3.org/2001/XMLSchema#string"


def sparql(query, retries=2):
    params = urllib.parse.urlencode({"query": query, "format": "application/sparql-results+json"})
    url = f"{SPARQL}?{params}"
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA, "Accept": "application/sparql-results+json"})
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.loads(r.read().decode("utf-8")).get("results", {}).get("bindings", [])
        except Exception:
            time.sleep(2)
    return []


def eu_check(celex):
    """查一个 CELEX 在官方库里是否存在，返回 (存在?, 标题, 生效日期, 是否有效)。"""
    q = f'''
    PREFIX cdm: <{CDM}>
    SELECT ?title ?entry ?inforce WHERE {{
      ?work cdm:resource_legal_id_celex "{celex}"^^<{XSD}> .
      OPTIONAL {{
        ?exp cdm:expression_belongs_to_work ?work .
        ?exp cdm:expression_title ?title .
        ?exp cdm:expression_uses_language ?lang .
        FILTER(CONTAINS(STR(?lang), "ENG"))
      }}
      OPTIONAL {{ ?work cdm:resource_legal_date_entry-into-force ?entry }}
      OPTIONAL {{ ?work cdm:resource_legal_in-force ?inforce }}
    }} LIMIT 5
    '''
    rows = sparql(q)
    if not rows:
        return False, "", "", ""
    r = rows[0]
    return (True,
            r.get("title", {}).get("value", "").replace("\xa0", " ")[:120],
            r.get("entry", {}).get("value", ""),
            r.get("inforce", {}).get("value", ""))


def ecfr_part_exists(title, part):
    """查 eCFR 里 title-N 有没有 part-P。返回 (存在?, 名称)。"""
    url = f"https://www.ecfr.gov/api/versioner/v1/titles.json"
    # 用 structure 接口查该 title 下是否存在该 part
    try:
        req = urllib.request.Request(
            f"https://www.ecfr.gov/api/versioner/v1/structure/2026-10-08/title-{title}.json",
            headers={"User-Agent": UA, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return None, f"查询失败：{e}"

    found = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "part" and str(node.get("identifier")) == str(part):
                found.append(node.get("label") or node.get("name") or "")
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(data)
    return (len(found) > 0), (found[0] if found else "")


def main():
    if not os.path.exists(GUIDE):
        print(f"找不到指南：{GUIDE}")
        return

    text = open(GUIDE, encoding="utf-8").read()
    links = []
    seen = set()
    for label, u in re.findall(r"\[([^\]]+)\]\((https?://[^\)]+)\)", text):
        if u not in seen:
            seen.add(u)
            links.append((label, u))

    print("=" * 74)
    print(f"  核对《官方法规网站查找指南》—— {len(links)} 个唯一链接")
    print("=" * 74)

    results = []
    for i, (label, u) in enumerate(links, 1):
        print(f"  [{i:>2}/{len(links)}] {u[:66]} ...", end=" ", flush=True)
        code, verdict, note = probe(u)
        icon = {"OK": "✔", "WAF": "△", "WAF?": "△", "BAD": "✘"}.get(verdict, "?")
        print(f"{icon} {code} {note}")
        results.append((label, u, code, verdict, note))
        time.sleep(0.7)

    # ── 数据核对 ──────────────────────────────────────────
    print()
    print("=" * 74)
    print("  数据核对：文档里的法规编号，拿到官方源交叉验证")
    print("=" * 74)

    # 文档中出现的欧盟法规（CELEX）
    eu_claims = [
        ("32025R2509", "Regulation (EU) 2025/2509 玩具安全条例", "2026-01-01"),
        ("32009L0048", "Directive 2009/48/EC 玩具安全指令", "2009-07-20"),
        ("32014L0035", "Directive 2014/35/EU 低电压指令 LVD", "2016-04-20"),
        ("32011R1007", "Regulation (EU) No 1007/2011 纺织纤维", "2011-11-07"),
        ("32009R1223", "Regulation (EC) No 1223/2009 化妆品条例", "2010-01-11"),
        ("32004R1935", "Regulation (EC) No 1935/2004 食品接触材料", "2004-12-03"),
    ]

    eu_results = []
    for celex, desc, claimed in eu_claims:
        print(f"  查 {celex} ({desc[:34]}) ...", end=" ", flush=True)
        exists, title, entry, inforce = eu_check(celex)
        if exists:
            print(f"✔ 存在 | 生效={entry or '?'} | 有效={inforce or '?'}")
        else:
            print("✘ 官方库未找到")
        eu_results.append((celex, desc, claimed, exists, title, entry, inforce))
        time.sleep(1.2)

    # 美国 CFR 条款
    print()
    us_claims = [
        (16, 1250, "CPSC 玩具安全标准（指南第 2.2、3 节引用）"),
        (16, 423, "FTC 洗护标签规则（指南第 2.2、3 节引用）"),
        (47, 15, "FCC 射频设备（指南第 2.2、3 节引用）"),
        (21, 701, "FDA 化妆品标签（指南第 2.2 节引用）"),
        (21, 740, "FDA 化妆品（指南第 2.2 节引用）"),
        (21, 175, "FDA 食品接触材料（指南第 2.2、3 节引用）"),
        (21, 176, "FDA 食品接触材料（指南第 2.2 节引用）"),
        (21, 177, "FDA 食品接触材料（指南第 2.2 节引用）"),
        (21, 178, "FDA 食品接触材料（指南第 2.2 节引用）"),
        (21, 120, "eCFR 版本性质说明页面对应条款（指南第 2.1 节）"),
    ]

    us_results = []
    for title, part, desc in us_claims:
        print(f"  查 {title} CFR Part {part} ...", end=" ", flush=True)
        ok, name = ecfr_part_exists(title, part)
        if ok is None:
            print(f"✘ {name}")
        elif ok:
            print(f"✔ 存在（{str(name)[:40]}）")
        else:
            print("✘ 未找到")
        us_results.append((title, part, desc, ok, name))
        time.sleep(0.5)

    # ── 写报告 ────────────────────────────────────────────
    lines = []
    lines.append("# 《官方法规网站查找指南》核对报告")
    lines.append("")
    lines.append("> 核对时间：2026-10-14 18:10")
    lines.append(f"> 范围：文档中 {len(links)} 个链接 + 16 项法规编号/条款号")
    lines.append("")
    lines.append("---")
    lines.append("")

    ok_n = sum(1 for r in results if r[3] == "OK")
    waf_n = sum(1 for r in results if r[3].startswith("WAF"))
    bad_n = sum(1 for r in results if r[3] == "BAD")
    lines.append("## 一、链接可达性总览")
    lines.append("")
    lines.append(f"| 判定 | 数量 |")
    lines.append("| --- | --- |")
    lines.append(f"| ✔ 可访问 | {ok_n} |")
    lines.append(f"| △ 人机验证墙（真人可开） | {waf_n} |")
    lines.append(f"| ✘ 有问题 | {bad_n} |")
    lines.append("")
    lines.append("### 逐条明细")
    lines.append("")
    lines.append("| # | 链接 | 状态 | 判定 |")
    lines.append("| --- | --- | --- | --- |")
    for i, (label, u, code, verdict, note) in enumerate(results, 1):
        lines.append(f"| {i} | {label[:34]} | {code} | {note} |")
    lines.append("")

    if bad_n:
        lines.append("### ✘ 需要处理的链接")
        lines.append("")
        for label, u, code, verdict, note in results:
            if verdict == "BAD":
                lines.append(f"- **{label}**（{code} {note}）")
                lines.append(f"  - {u}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 二、欧盟法规编号核对（对照官方 SPARQL 接口）")
    lines.append("")
    lines.append("| CELEX | 文档说法 | 官方库 | 生效日期 | 现行有效 |")
    lines.append("| --- | --- | --- | --- | --- |")
    for celex, desc, claimed, exists, title, entry, inforce in eu_results:
        mark = "✔ 存在" if exists else "✘ 未找到"
        inforce_txt = "是" if inforce == "1" else ("否" if inforce else "?")
        lines.append(f"| {celex} | {desc[:30]} | {mark} | {entry or '?'} | {inforce_txt} |")
    lines.append("")

    lines.append("## 三、美国 CFR 条款核对（对照 eCFR 官方接口）")
    lines.append("")
    lines.append("| 条款 | 文档用途 | 官方库 |")
    lines.append("| --- | --- | --- |")
    for title, part, desc, ok, name in us_results:
        mark = "✔ 存在" if ok else ("✘ 未找到" if ok is False else "? 查询失败")
        lines.append(f"| {title} CFR Part {part} | {desc[:32]} | {mark} |")
    lines.append("")

    out = os.path.join(DATA, "指南核对报告.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print()
    print("=" * 74)
    print(f"  链接：可访问 {ok_n} / 人机墙 {waf_n} / 有问题 {bad_n}")
    print(f"  报告已保存：{out}")
    print("=" * 74)


if __name__ == "__main__":
    main()
