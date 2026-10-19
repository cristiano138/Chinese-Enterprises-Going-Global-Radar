# -*- coding: utf-8 -*-
"""新法规发现（scripts/discover_new_laws.py）

用途：
    定时/按需去**官方数据源**找「laws 表里还没有」的法规，可选地调用
    ``core/law_intake.py`` 建档，把「发现 → 建档 → 材料落库 → 召回树」
    链路的第一环补上。

数据源（免费、免密钥、官方）：
    · 欧盟：Publications Office Cellar SPARQL
      ``?work cdm:work_date_document ?date`` 按日期窗口查 sector 3 新作品；
      再批量补英文标题 / ELI。
    · 美国：Federal Register API
      ``documents.json`` 按 ``publication_date`` + ``type=RULE`` +
      ``conditions[cfr][title]`` 查新最终规则，从 ``cfr_references`` 取
      Title + Part，与 laws 表比对。

分工铁律（沿用项目原则）：
    · **发现、去重、编号映射全部由确定性代码完成**；
    · LLM 只做「这条法规是否属于出海合规范围 / 归到哪个品类 / 一句话摘要」，
      并且只允许使用官方接口给出的标题、摘要、编号——不得补充或推断事实。
    · LLM 不可用时自动降级：仍然输出候选清单，只是没有相关性判断。

安全默认值：
    · 默认**只出报告，不写库**；``--intake`` 才建档。
    · ``--intake`` 默认只建档 LLM 判定为相关的候选；LLM 不可用时需显式
      ``--intake-all`` 才建档。
    · 建档一律带「待人工复核」标记，且新法规在 units 表没有切片是预期状态
      （材料落库走 ``scripts/ingest_law_material.py``）。

用法：
    # 最近 30 天，只出报告
    python scripts/discover_new_laws.py

    # 指定窗口 / 单市场 / 跳过 LLM
    python scripts/discover_new_laws.py --since 2026-09-01 --until 2026-10-19 --only EU
    python scripts/discover_new_laws.py --no-llm

    # 对 LLM 判定相关的候选建档（先 dry-run 看清单更稳）
    python scripts/discover_new_laws.py --intake --intake-limit 5 --dry-run

    # 建档后让下游生成材料待办并重建召回树
    python scripts/discover_new_laws.py --intake --refresh

退出码：
    0 至少一个官方源成功（单源失败只记录，不中断）
    1 所有官方源都失败
    2 用法 / 数据库错误
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core import law_store  # noqa: E402
from core import net  # noqa: E402

DATA_DIR = os.path.join(ROOT, "data")
REPORT_PATH = os.path.join(DATA_DIR, "new_law_candidates.json")
LOG_PATH = os.path.join(DATA_DIR, "new_law_discovery_log.jsonl")
SEEN_PATH = os.path.join(DATA_DIR, "new_law_seen.json")
SEEN_MAX_AGE_DAYS = 180
# 冲突留存：LLM/搜索说“有新法规”，官方接口说“没有”。
# 只给管理端后续复核，不进入普通用户可见的候选报告/页面。
CONFLICT_LOG_PATH = os.path.join(DATA_DIR, "new_law_conflicts.jsonl")
CONFLICT_LATEST_PATH = os.path.join(DATA_DIR, "new_law_conflicts.json")
ADMIN_ONLY = {"visibility": "admin_only", "status": "pending_review",
              "priority": "admin_review"}
BJT = timezone(timedelta(hours=8))

SCHEMA_VERSION = 1
FR_API = "https://www.federalregister.gov/api/v1/documents.json"
_UA = ("Mozilla/5.0 (compatible; ComplianceRadar-Discovery/1.0; "
       "+https://github.com/cristiano138/Chinese-Enterprises-Going-Global-Radar)")
CELEX_RE = re.compile(r"^3([0-9]{4})([RLD])([0-9]{4})$", re.I)
EU_TYPE_WORD = {"R": "Regulation", "L": "Directive", "D": "Decision"}
ELI_TYPE_WORD = {"R": "reg", "L": "dir", "D": "dec"}


def now_bjt():
    return datetime.now(BJT)


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_fetch_eu = _load_module("fetch_eu", os.path.join(HERE, "fetch_eu.py"))


# ── CELEX / ELI 映射（确定性，不调模型）──────────────────────────────
def eli_from_celex(celex):
    """CELEX → ELI 兜底链接；无法识别返回空串。

    只作为 SPARQL 没返回 ELI 时的展示兜底；正式的 ELI 以 Cellar 字段为准。
    """
    match = CELEX_RE.match(str(celex or "").strip())
    if not match:
        return ""
    year, letter, number = match.group(1), match.group(2).upper(), match.group(3)
    kind = ELI_TYPE_WORD.get(letter)
    return (f"http://data.europa.eu/eli/{kind}/{year}/{int(number)}/oj"
            if kind else "")


def eu_official_url(celex):
    return f"https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{celex}"


def us_official_url(title_number, part_number):
    return f"https://www.ecfr.gov/current/title-{title_number}/part-{part_number}"


def _eu_candidate(celex, published_on="", title="", eli="", source="eurlex"):
    """组装一个 EU 候选（确定性发现和联网发现共用）。"""
    letter = CELEX_RE.match(celex).group(2).upper()
    return {
        "source": source,
        "jurisdiction": "EU",
        "law_id": f"EU:{celex}",
        "celex": celex,
        "title_number": None,
        "part_number": None,
        "new_parts": [],
        "cfr_references": [],
        "official_title": title or "",
        "published_on": published_on or "",
        "effective_on": "",
        "eli": eli or eli_from_celex(celex),
        "official_url": eu_official_url(celex),
        "evidence_url": eu_official_url(celex),
        "agency": "EU",
        "abstract": "",
        "doc_type": EU_TYPE_WORD.get(letter, letter),
    }


def _us_candidate(doc, titles, existing):
    """把一条 FR 文档转成候选；返回 (candidate, reason)。

    reason: "" 表示成功；"unmapped" 表示没有可用 CFR 映射；
    "exists" 表示只涉及库里已有的 Part（属于既有法规修订）。
    """
    refs = []
    for ref in doc.get("cfr_references") or []:
        try:
            ref_title = int(ref.get("title"))
            part = str(ref.get("part") or "").strip()
        except (TypeError, ValueError):
            continue
        # 与 law_intake 的编号校验保持一致，拒绝异常 Part 字符串
        if (ref_title in titles and re.fullmatch(r"\d+[a-z]?", part)
                and (ref_title, part) not in refs):
            refs.append((ref_title, part))
    if not refs:
        return None, "unmapped"
    new_parts = [pair for pair in refs if pair not in existing["us"]]
    if not new_parts:
        return None, "exists"
    agencies = [a.get("name") for a in (doc.get("agencies") or [])
                if isinstance(a, dict) and a.get("name")]
    primary_title, primary_part = new_parts[0]
    return {
        "source": "federal_register",
        "jurisdiction": "US",
        "law_id": f"US:{primary_title}:{primary_part}",
        "law_ids": [f"US:{t}:{p}" for t, p in new_parts],
        "celex": "",
        "title_number": primary_title,
        "part_number": primary_part,
        "new_parts": [{"title": t, "part": p} for t, p in new_parts],
        "cfr_references": [{"title": t, "part": p} for t, p in refs],
        "official_title": (doc.get("title") or "").strip(),
        "published_on": (doc.get("publication_date") or "").strip(),
        "effective_on": (doc.get("effective_on") or "").strip(),
        "eli": "",
        "official_url": us_official_url(primary_title, primary_part),
        "evidence_url": (doc.get("html_url") or "").strip(),
        "agency": "; ".join(agencies),
        "abstract": (doc.get("abstract") or "").strip()[:600],
        "doc_type": (doc.get("type") or "Rule").strip(),
        "fr_document_number": (doc.get("document_number") or "").strip(),
    }, ""


# ── 数据库已有法规（去重基准）──────────────────────────────────────
def load_existing(db_path):
    """读 laws 表：已有 CELEX / 已有 US Title+Part / US 标题集合。"""
    con = law_store.connect(db_path)
    try:
        eu = {str(r[0]).strip().upper() for r in con.execute(
            "SELECT celex FROM laws WHERE jurisdiction='EU' AND celex IS NOT NULL")
            if r[0]}
        us = {(int(r[0]), str(r[1]).strip()) for r in con.execute(
            "SELECT title_number, part_number FROM laws "
            "WHERE jurisdiction='US' AND title_number IS NOT NULL "
            "AND part_number IS NOT NULL")}
        titles = sorted({int(r[0]) for r in con.execute(
            "SELECT DISTINCT title_number FROM laws "
            "WHERE jurisdiction='US' AND title_number IS NOT NULL")})
        total = con.execute("SELECT COUNT(*) FROM laws").fetchone()[0]
    finally:
        con.close()
    return {"eu": eu, "us": us, "us_titles": titles, "total": total}


# ── 欧盟：Cellar SPARQL 增量发现 ─────────────────────────────────────
def query_eu_works(since, until, limit):
    """按官方发布日期窗口查 sector 3 的 R/L/D 作品。"""
    query = f'''
    PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
    PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
    SELECT DISTINCT ?celex ?date WHERE {{
      ?work cdm:resource_legal_id_celex ?celex .
      ?work cdm:work_date_document ?date .
      FILTER(?date >= "{since}"^^xsd:date && ?date <= "{until}"^^xsd:date)
      FILTER(REGEX(STR(?celex), "^3[0-9]{{4}}[RLD][0-9]{{4}}$"))
    }} ORDER BY DESC(?date) LIMIT {max(int(limit), 1)}
    '''
    rows = _fetch_eu.sparql(query)
    out, seen = [], set()
    for row in rows:
        celex = (row.get("celex", {}).get("value") or "").strip().upper()
        date = (row.get("date", {}).get("value") or "")[:10]
        if not CELEX_RE.match(celex) or celex in seen:
            continue
        seen.add(celex)
        out.append({"celex": celex, "published_on": date})
    return out


def query_eu_titles(celexes, batch_size=50):
    """批量补英文标题与 ELI；查询失败返回空映射（不阻断发现）。"""
    out = {}
    for start in range(0, len(celexes), batch_size):
        batch = celexes[start:start + batch_size]
        values = " ".join(f'"{c}"^^xsd:string' for c in batch)
        query = f'''
        PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        SELECT ?celex ?title ?eli WHERE {{
          VALUES ?celex {{ {values} }}
          ?work cdm:resource_legal_id_celex ?celex .
          OPTIONAL {{ ?work cdm:resource_legal_eli ?eli }}
          OPTIONAL {{
            ?exp cdm:expression_belongs_to_work ?work .
            ?exp cdm:expression_title ?title .
            ?exp cdm:expression_uses_language ?lang .
            FILTER(CONTAINS(STR(?lang), "ENG"))
          }}
        }} LIMIT {len(batch) * 4}
        '''
        try:
            rows = _fetch_eu.sparql(query)
        except Exception as exc:  # 标题补全失败不阻断候选清单
            print(f"  ⚠️ 欧盟标题补全失败（{len(batch)} 条）："
                  f"{type(exc).__name__}: {str(exc)[:120]}", flush=True)
            continue
        for row in rows:
            celex = (row.get("celex", {}).get("value") or "").strip().upper()
            if not celex:
                continue
            item = out.setdefault(celex, {"title": "", "eli": ""})
            title = (row.get("title", {}).get("value") or "").replace("\xa0", " ").strip()
            eli = (row.get("eli", {}).get("value") or "").strip()
            if title and not item["title"]:
                item["title"] = title
            if eli and not item["eli"]:
                item["eli"] = eli
        time.sleep(0.4)
    return out


def discover_eu(since, until, existing, limit):
    """返回 (candidates, stat)。已有 CELEX 不进入候选。"""
    started = time.time()
    stat = {"source": "EU", "ok": False, "scanned": 0, "skipped_exists": 0,
            "candidates": 0, "unmapped": 0, "error": ""}
    try:
        works = query_eu_works(since, until, limit)
    except Exception as exc:
        stat["error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
        return [], stat
    stat["scanned"] = len(works)
    todo = []
    for work in works:
        if work["celex"] in existing["eu"]:
            stat["skipped_exists"] += 1
            continue
        todo.append(work)
    meta = query_eu_titles([w["celex"] for w in todo]) if todo else {}
    candidates = []
    for work in todo:
        info = meta.get(work["celex"]) or {}
        candidates.append(_eu_candidate(
            work["celex"], published_on=work["published_on"],
            title=info.get("title") or "", eli=info.get("eli") or ""))
    stat["ok"] = True
    stat["candidates"] = len(candidates)
    stat["elapsed_seconds"] = round(time.time() - started, 1)
    return candidates, stat


# ── 美国：Federal Register 增量发现 ─────────────────────────────────
FR_FIELDS = ("document_number", "title", "publication_date", "effective_on",
             "cfr_references", "agencies", "html_url", "abstract", "type")
FR_DOC_RE = re.compile(
    r"^(?:[A-Z]\d{1,2}-\d{4}-\d{3,6}|[A-Z]?\d{1,4}-\d{2,6})$", re.I)
_FR_DOC_PATH_RE = re.compile(
    r"/(?:documents(?:/full_text/(?:xml|html))?|api/v1/documents)"
    r"/(?:[0-9]{4}/[0-9]{2}/[0-9]{2}/)?"
    r"([A-Z]?\d{1,4}-\d{2,6})(?:[./?#]|$)", re.I)

# 联网发现只允许官方域名；搜索结果只是线索，必须再经官方 API 核验。
DISCOVERY_HOSTS = {
    "eur-lex.europa.eu", "data.europa.eu", "publications.europa.eu",
    "federalregister.gov", "ecfr.gov", "govinfo.gov",
    "cpsc.gov", "fda.gov", "ftc.gov", "fcc.gov",
}
CELLAR_API = "https://publications.europa.eu/resource/celex/{}"
# 5 类主要商品；英文关键词用于搜索官方站点。
WEB_CATEGORY_TERMS = {
    "儿童玩具": "children's toy safety",
    "电子电器": "electrical electronic equipment safety",
    "美妆个护": "cosmetics safety",
    "纺织服装": "textile apparel labelling",
    "食品接触材料": "food contact materials",
}
_CELEX_TEXT_RE = re.compile(
    r"CELEX(?:%3A|:|\\s*[:=]\\s*)(3[0-9]{4}[RLD][0-9]{4})", re.I)
_CELEX_RESOURCE_RE = re.compile(
    r"/resource/celex/(3[0-9]{4}[RLD][0-9]{4})", re.I)
_ELI_PATH_RE = re.compile(r"/eli/([a-z_]+)/([0-9]{4})/([0-9]+)", re.I)
_ELI_TYPE = {"reg": "R", "dir": "L", "dec": "D"}
# 官方编号写法（现代 year/number 与旧式 No number/year 两种都要认）。
# 欧盟搜索结果经常是法语/西语/德语页面，类型词必须多语言覆盖。
_TYPE_WORDS = {
    "regulation": "R", "reglamento": "R", "règlement": "R", "verordnung": "R",
    "regolamento": "R", "regulamento": "R", "verordening": "R",
    "directive": "L", "directiva": "L", "richtlinie": "L", "direttiva": "L",
    "diretiva": "L",
    "decision": "D", "decisión": "D", "décision": "D", "entscheidung": "D",
    "decisione": "D", "decisão": "D", "beschikking": "D",
}
_TYPE_WORD_RE = "|".join(
    re.escape(word) for word in sorted(_TYPE_WORDS, key=len, reverse=True))
_EU_SUFFIX = r"(?:EU|EC|EEC|Euratom|UE|CE|CEE|EG|EWG|EEG|EØF)"
_OFFICIAL_NUMBER_RES = (
    re.compile(
        rf"\b({_TYPE_WORD_RE})\s*\({_EU_SUFFIX}\)\s*"
        rf"(No\.?\s*|N[oº°]\.?\s*)?"
        rf"([0-9]{{1,4}})/([0-9]{{1,4}})", re.I),
    re.compile(
        rf"\b({_TYPE_WORD_RE})\s+([0-9]{{4}})/([0-9]{{1,4}})\s*/\s*{_EU_SUFFIX}\b",
        re.I),
)


def _fr_json(url, retries=3, timeout=45):
    """GET 一个 FR JSON 地址，带重试。"""
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": _UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last_err = f"HTTP {exc.code}"
            if exc.code in (429, 500, 502, 503, 504):
                time.sleep(min(2 ** attempt, 20))
                continue
            raise
        except Exception as exc:
            last_err = f"{type(exc).__name__}: {str(exc)[:120]}"
            time.sleep(min(2 ** attempt, 20))
    raise RuntimeError(last_err or "FR API 请求失败")


def _fr_get(params, retries=3, timeout=45):
    query = urllib.parse.urlencode(params, doseq=True)
    return _fr_json(FR_API + "?" + query, retries, timeout)


def query_fr_documents(title_number, since, until, limit):
    """按 CFR Title 拉取窗口内的最终规则（分页，最多 limit 条）。"""
    results = []
    page = 1
    while len(results) < limit:
        params = [
            ("conditions[publication_date][gte]", since),
            ("conditions[publication_date][lte]", until),
            ("conditions[type][]", "RULE"),
            ("conditions[cfr][title]", str(title_number)),
            ("order", "newest"),
            ("per_page", "100"),
            ("page", str(page)),
        ] + [("fields[]", field) for field in FR_FIELDS]
        data = _fr_get(params)
        batch = data.get("results") or []
        results.extend(batch)
        if len(batch) < 100:
            break
        page += 1
        time.sleep(0.4)
    return results[:limit]


def discover_us(since, until, existing, limit, titles):
    """返回 (candidates, stat)。

    候选粒度 = **FR 文档（规则）**，不是单个 CFR Part：一条规则经常同时
    引用十几个 Part（例如某食品标准修订），按 Part 展开会把同一条规则
    重复报十几次。文档里只保留「库里没有」的 Part 作为 new_parts；
    如果引用的 Part 都已在库里，说明是既有法规修订，不计入新法规候选。
    """
    started = time.time()
    stat = {"source": "US", "ok": False, "scanned": 0, "skipped_exists": 0,
            "candidates": 0, "unmapped": 0, "error": ""}
    candidates = {}
    errors = []
    for title in titles:
        try:
            docs = query_fr_documents(title, since, until, limit)
        except Exception as exc:
            errors.append(f"title {title}: {type(exc).__name__}: {str(exc)[:120]}")
            continue
        stat["scanned"] += len(docs)
        for doc in docs:
            candidate, reason = _us_candidate(doc, titles, existing)
            if reason == "unmapped":
                stat["unmapped"] += 1
                continue
            if reason == "exists":
                stat["skipped_exists"] += 1
                continue
            # 同一条规则可能在不同 Title 的查询里重复出现；同一组新 Part
            # 只保留发布日期最新的一份文档作为证据。
            key = tuple(sorted((p["title"], p["part"])
                               for p in candidate["new_parts"]))
            current = candidates.get(key)
            if current and current["published_on"] >= candidate["published_on"]:
                continue
            candidates[key] = candidate
    stat["ok"] = not errors or bool(candidates)
    hint = ""
    if errors and all("403" in error for error in errors):
        hint = ("（Federal Register 对直连返回 403：请确认 Clash/代理已开启，"
                "或用 --proxy 指定代理）")
    stat["error"] = "；".join(errors) + hint
    stat["candidates"] = len(candidates)
    stat["elapsed_seconds"] = round(time.time() - started, 1)
    return list(candidates.values()), stat


# ── 联网发现：DeepSeek Search / Fetch ───────────────────────────────
def default_web_queries(markets):
    """按 5 类商品 × 市场生成官方站点限定查询（英文关键词）。"""
    queries = []
    for category, terms in WEB_CATEGORY_TERMS.items():
        if "EU" in markets:
            queries.append((category, "EU",
                            f"{terms} new regulation 2026 site:eur-lex.europa.eu"))
        if "US" in markets:
            queries.append((category, "US",
                            f"{terms} final rule 2026 site:federalregister.gov"))
    return queries


def _is_discovery_host(url):
    try:
        host = (urllib.parse.urlsplit(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    return any(host == item or host.endswith("." + item)
               for item in DISCOVERY_HOSTS)


def extract_eu_celex(text):
    """从搜索 URL / 网页正文里提取 CELEX；支持 CELEX:、资源路径、ELI 路径。"""
    raw = urllib.parse.unquote(str(text or ""))
    for regex in (_CELEX_TEXT_RE, _CELEX_RESOURCE_RE):
        match = regex.search(raw)
        if match:
            celex = match.group(1).upper()
            if CELEX_RE.match(celex):
                return celex
    match = _ELI_PATH_RE.search(raw)
    if match:
        letter = _ELI_TYPE.get(match.group(1).lower().split("_", 1)[0])
        if letter:
            number = int(match.group(3))
            if number <= 9999:
                return f"3{match.group(2)}{letter}{number:04d}"
    return ""


def extract_official_number_celex(text):
    """从“Regulation (EU) 2025/2509”“Directive 2009/48/EC”这类编号生成 CELEX。"""
    raw = urllib.parse.unquote(str(text or ""))
    for regex in _OFFICIAL_NUMBER_RES:
        for match in regex.finditer(raw):
            letter = _TYPE_WORDS.get(match.group(1).lower())
            if not letter:
                continue
            if len(match.groups()) == 4:
                has_no, first, second = match.group(2), match.group(3), match.group(4)
                number, year = (first, second) if has_no else (second, first)
            else:
                year, number = match.group(2), match.group(3)
            try:
                number, year = int(number), int(year)
            except ValueError:
                continue
            if 0 < number <= 9999 and 1900 <= year <= 2100:
                return f"3{year:04d}{letter}{number:04d}"
    return ""


def extract_eu_celex_any(text):
    """先认 CELEX/ELI，再退到官方编号写法。"""
    return extract_eu_celex(text) or extract_official_number_celex(text)


def extract_fr_doc_number(text):
    """从 FR URL / 正文提取文档号；不会把 2026-10-19 这类日期误判成文档号。"""
    raw = urllib.parse.unquote(str(text or ""))
    match = _FR_DOC_PATH_RE.search(raw)
    if match and FR_DOC_RE.match(match.group(1)):
        return match.group(1)
    for token in re.findall(
            r"(?<![\d-])([A-Z]?\d{1,4}-\d{2,6})(?![\d-])", raw):
        if FR_DOC_RE.match(token):
            return token
    return ""


def verify_eu_celex(celex, timeout=30):
    """用 Cellar 官方资源接口核验 CELEX，返回 (ok, reason)。

    reason 用于区分“官方明确没有”（http_404 / empty，属于冲突，需管理端留存）
    和“本次没连上/服务异常”（network / http_5xx，只是未核验，不算冲突）。
    """
    try:
        req = urllib.request.Request(
            CELLAR_API.format(celex),
            headers={"User-Agent": _UA, "Accept": "application/rdf+xml"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            body = resp.read(4096)
            if not (200 <= status < 400):
                return False, f"http_{status}"
            if not body:
                return False, "empty"
            return True, "ok"
    except urllib.error.HTTPError as exc:
        return False, f"http_{exc.code}"
    except Exception as exc:
        return False, f"network:{type(exc).__name__}"


def verify_fr_document(document_number, timeout=45):
    """用 FR 详情接口核验文档号，返回 (data, reason)。

    reason: ok / not_rule / http_404 / network:...
    """
    try:
        data = _fr_json(
            "https://www.federalregister.gov/api/v1/documents/"
            f"{document_number}.json", timeout=timeout)
    except Exception as exc:
        text = str(exc)
        if "HTTP 404" in text or "HTTP 410" in text:
            return None, "http_404"
        return None, f"network:{type(exc).__name__}"
    if not isinstance(data, dict):
        return None, "empty"
    if (data.get("type") or "").lower() != "rule":
        return None, "not_rule"
    return data, "ok"


def _conflict_record(jurisdiction, identifier, reason, query, category,
                     result, extra=None):
    """构造一条“搜索说有、官方接口说没有”的管理端留存记录。

    这类记录**不进入候选报告**，也不得在普通用户页面展示；接口结果优先。
    """
    record = {
        "detected_at": now_bjt().strftime("%Y-%m-%d %H:%M:%S"),
        "kind": "llm_found_api_missing",
        "jurisdiction": jurisdiction,
        "identifier": identifier,
        "discovered_by": query,
        "discovered_category": category,
        "search_url": result.get("url") or "",
        "search_title": result.get("title") or "",
        "search_summary": (result.get("summary") or "")[:1000],
        "verification": {"ok": False, "reason": reason},
        **ADMIN_ONLY,
        "note": ("LLM/搜索发现，但官方接口未确认；仅管理端留存，"
                 "普通用户页面不展示"),
    }
    if extra:
        record.update(extra)
    return record


def discover_web(since, until, existing, us_titles, markets,
                 count=8, max_candidates=60, fetch_pages=False,
                 custom_queries=None):
    """联网发现：搜索只是线索，所有候选必须再经官方 API 核验。

    返回 (candidates, conflicts, stat)。
    ``conflicts`` 是“搜索说有、官方接口明确说没有”的管理端留存记录，
    不进入候选报告，也不得在普通用户页面展示（接口优先）。
    任何搜索/抓取失败都只记录，不中断其他源。
    """
    from core import llm

    started = time.time()
    stat = {"source": "WEB", "ok": False, "queries": 0, "scanned": 0,
            "skipped_host": 0, "skipped_date": 0, "skipped_exists": 0,
            "unmapped": 0, "unverified": 0, "candidates": 0, "error": ""}
    if not llm.is_ready():
        stat["error"] = "模型链路未配置"
        return [], [], stat

    queries = custom_queries or default_web_queries(markets)
    hits, errors, conflicts = [], [], {}
    for category, market, query in queries:
        results, meta = llm.web_search(query, count=count)
        stat["queries"] += 1
        if not meta.get("ok"):
            errors.append(f"{query[:36]}: {meta.get('reason')}")
            continue
        for result in results:
            if isinstance(result, dict):
                hits.append((category, market, query, result))
    stat["scanned"] = len(hits)

    eu_seen, fr_seen = {}, {}
    since_year = int(since[:4])
    for category, market, query, result in hits:
        url = (result.get("url") or "").strip()
        if not _is_discovery_host(url):
            stat["skipped_host"] += 1
            continue
        date = (result.get("date") or "")[:10]
        if date and not (since <= date <= until):
            stat["skipped_date"] += 1
            continue
        # 搜索结果的标题/摘要里常带官方编号（OJ PDF 尤其如此）
        blob = "\n".join(str(result.get(key) or "")
                         for key in ("title", "summary", "snippet"))
        celex = extract_eu_celex_any(url) or extract_eu_celex_any(blob)
        if celex:
            # 没有发布日期时，用编号年份挡住明显过时的搜索命中
            if not date and int(celex[1:5]) < since_year - 1:
                stat["skipped_date"] += 1
                continue
            if market in ("EU", "ANY"):
                eu_seen.setdefault(celex, (category, query, result))
            continue
        document_number = (extract_fr_doc_number(url)
                           or extract_fr_doc_number(blob))
        if document_number:
            if market in ("US", "ANY"):
                fr_seen.setdefault(document_number, (category, query, result))
            continue
        # 官方站点但 URL/摘要里没有编号：可选抓正文再提取
        if not fetch_pages:
            stat["unmapped"] += 1
            continue
        page, meta = llm.web_fetch(url)
        if not meta.get("ok"):
            stat["unmapped"] += 1
            continue
        text = f"{page.get('title', '')}\n{page.get('content', '')}"
        celex = extract_eu_celex_any(text)
        document_number = extract_fr_doc_number(text)
        if celex and market in ("EU", "ANY"):
            eu_seen.setdefault(celex, (category, query, result))
        elif document_number and market in ("US", "ANY"):
            fr_seen.setdefault(document_number, (category, query, result))
        else:
            stat["unmapped"] += 1

    candidates = []
    # 欧盟：先核验存在，再补官方标题/ELI
    eu_todo = [celex for celex in eu_seen if celex not in existing["eu"]]
    stat["skipped_exists"] += len(eu_seen) - len(eu_todo)
    eu_todo = eu_todo[:max_candidates]
    verified = []
    for celex in eu_todo:
        ok, reason = verify_eu_celex(celex)
        if ok:
            verified.append(celex)
            continue
        stat["unverified"] += 1
        # 官方明确说“没有”才留存冲突；网络/5xx 只是本次未核验
        if reason in ("http_404", "http_410", "empty"):
            category, query, result = eu_seen[celex]
            conflicts[("EU", celex, reason)] = _conflict_record(
                "EU", f"EU:{celex}", reason, query, category, result,
                {"celex": celex})
    titles = query_eu_titles(verified) if verified else {}
    for celex in verified:
        category, query, result = eu_seen[celex]
        info = titles.get(celex) or {}
        candidate = _eu_candidate(
            celex, published_on=(result.get("date") or "")[:10],
            title=info.get("title") or result.get("title") or "",
            eli=info.get("eli") or "", source="web_search")
        candidate.update({
            "verified_via": "cellar_api",
            "discovered_by": query,
            "discovered_category": category,
            "search_url": result.get("url") or "",
            "search_authority": result.get("authority"),
        })
        candidates.append(candidate)

    # 美国：FR 详情接口核验编号、规则类型与 CFR 映射
    for document_number, (category, query, result) in fr_seen.items():
        if len(candidates) >= max_candidates:
            break
        data, verify_reason = verify_fr_document(document_number)
        if not data:
            stat["unverified"] += 1
            if verify_reason in ("http_404", "http_410", "not_rule", "empty"):
                conflicts[("US", document_number, verify_reason)] = _conflict_record(
                    "US", f"US-FR:{document_number}", verify_reason, query,
                    category, result,
                    {"fr_document_number": document_number})
            continue
        published = (data.get("publication_date") or "")[:10]
        if published and not (since <= published <= until):
            stat["skipped_date"] += 1
            continue
        candidate, reason = _us_candidate(data, us_titles, existing)
        if reason == "exists":
            stat["skipped_exists"] += 1
            continue
        if reason == "unmapped":
            stat["unmapped"] += 1
            continue
        candidate.update({
            "source": "web_search",
            "verified_via": "fr_api",
            "discovered_by": query,
            "discovered_category": category,
            "search_url": result.get("url") or "",
            "search_authority": result.get("authority"),
        })
        candidates.append(candidate)

    # 同一 law_id 只保留一条（多份 FR 文档可能指向同一 Part）
    unique = {}
    for candidate in candidates:
        unique.setdefault(candidate["law_id"], candidate)
    candidates = list(unique.values())[:max_candidates]

    stat["ok"] = bool(candidates) or (stat["queries"] > 0 and not errors)
    stat["error"] = "；".join(errors)
    stat["candidates"] = len(candidates)
    stat["elapsed_seconds"] = round(time.time() - started, 1)
    return candidates, list(conflicts.values()), stat


def merge_candidates(candidates):
    """按 law_id 合并确定性发现与联网发现，保留双方来源标记。"""
    merged = {}
    for candidate in candidates:
        law_id = candidate.get("law_id") or ""
        if law_id not in merged:
            candidate["discovered_via"] = [candidate.get("source") or ""]
            merged[law_id] = candidate
            continue
        base = merged[law_id]
        via = set(base.get("discovered_via") or [base.get("source") or ""])
        via.add(candidate.get("source") or "")
        base["discovered_via"] = sorted(item for item in via if item)
        for key in ("search_url", "discovered_by", "search_authority",
                    "discovered_category", "verified_via"):
            if candidate.get(key) and not base.get(key):
                base[key] = candidate[key]
    return list(merged.values())


# ── LLM：只做相关性 / 品类 / 摘要 ────────────────────────────────────
LLM_PROMPT = """你是跨境电商产品合规助理。下面是官方数据源最近发布、且项目库里还没有的法规候选。

请判断每条是否与「跨境电商实物商品合规」相关，并归类、写一句话中文摘要。

【相关范围】
产品安全、玩具、电子电器、美妆个护、纺织服装、食品接触材料、化学品限制、
标签/认证、包装与环保责任、进口准入。

【不相关】
纯程序性/内部管理规则、关税/贸易救济、农业补贴、移民、政府采购、金融监管、
与实物商品无关的执法公告或人事任命。

【不可违反的硬约束】
1. 只能依据下面给出的编号、标题、摘要判断；不得补充、推断或编造任何编号、日期、链接。
2. 不确定就写「不确定」，不要猜。
3. 输出严格每行一条，用 ||| 分隔，不要 markdown，不要额外解释：
序号|||相关(是/否/不确定)|||品类(儿童玩具/电子电器/美妆个护/纺织服装/食品接触/化学品/其他)|||一句话中文摘要(40字以内)

候选：
{items}
"""

_RELEVANT = {"是", "相关", "yes", "true", "y"}
_IRRELEVANT = {"否", "不相关", "no", "false", "n"}


def _candidate_line(index, candidate):
    if candidate.get("jurisdiction") == "EU":
        ident = candidate.get("celex", "")
        extra = candidate.get("doc_type", "")
    else:
        parts = candidate.get("new_parts") or [{
            "title": candidate.get("title_number"),
            "part": candidate.get("part_number"),
        }]
        shown = ", ".join(f"{p['title']} CFR {p['part']}" for p in parts[:6])
        if len(parts) > 6:
            shown += f" 等 {len(parts)} 个 Part"
        ident = shown
        extra = candidate.get("doc_type", "")
    title = (candidate.get("official_title") or "")[:300]
    abstract = (candidate.get("abstract") or "")[:300]
    return (f"{index}. [{candidate.get('jurisdiction')}] {ident} | { title } | "
            f"{candidate.get('published_on','')} | {extra} | {abstract}")


def parse_llm_lines(text):
    """解析 ``序号|||相关|||品类|||摘要``；坏行直接忽略。"""
    out = {}
    for line in (text or "").splitlines():
        parts = [part.strip() for part in line.split("|||")]
        if len(parts) < 4:
            continue
        match = re.match(r"^(\d+)", parts[0])
        if not match:
            continue
        index = int(match.group(1))
        verdict = parts[1].strip().lower()
        relevant = (True if verdict in _RELEVANT
                    else False if verdict in _IRRELEVANT else None)
        out[index] = {
            "relevant": relevant,
            "category": parts[2][:20],
            "summary": parts[3][:80],
        }
    return out


def classify_candidates(candidates, enabled=True, chunk_size=25):
    """给每个候选补 llm 字段；失败/未启用时如实标记，不阻断报告。"""
    for candidate in candidates:
        candidate["llm"] = {"ok": False, "relevant": None, "category": "",
                            "summary": "", "error": ""}
    if not enabled:
        for candidate in candidates:
            candidate["llm"]["error"] = "未启用"
        return candidates

    try:
        from core import llm
    except Exception as exc:
        for candidate in candidates:
            candidate["llm"]["error"] = f"LLM 模块不可用：{type(exc).__name__}"
        return candidates

    if not llm.is_ready():
        for candidate in candidates:
            candidate["llm"]["error"] = "模型链路未配置"
        return candidates

    for start in range(0, len(candidates), chunk_size):
        batch = candidates[start:start + chunk_size]
        lines = "\n".join(
            _candidate_line(start + index + 1, candidate)
            for index, candidate in enumerate(batch))
        prompt = LLM_PROMPT.format(items=lines)
        text, meta = llm.chat(prompt, max_tokens=2500, temperature=0,
                              use_cache=True, timeout=90, thinking=False)
        parsed = parse_llm_lines(text) if meta.get("ok") else {}
        for index, candidate in enumerate(batch, start=start + 1):
            item = parsed.get(index)
            if item:
                candidate["llm"] = {"ok": True, "relevant": item["relevant"],
                                    "category": item["category"],
                                    "summary": item["summary"], "error": ""}
            else:
                reason = meta.get("reason") or "模型未返回该条结果"
                candidate["llm"] = {"ok": False, "relevant": None,
                                    "category": "", "summary": "",
                                    "error": str(reason)[:120]}
    return candidates


# ── 建档（显式 --intake 才写库）─────────────────────────────────────
def _backup_once(db_path):
    """整批建档前只备份一次，避免每条法规复制一份 2.2GB 库。"""
    con = law_store.connect(db_path, writable=True)
    try:
        law_store.backup(con, db_path)
    finally:
        con.close()


def intake_candidates(candidates, args, db_path, dry_run=False):
    """调用 core.law_intake 建档；返回逐条 law 的 intake 结果。

    美国候选是「一条规则 + 多个新 Part」，这里按 Part 拆成多个建档任务；
    ``--intake-limit`` 限制的是**实际建案件数**，不是候选文档数。
    """
    if not candidates:
        return []
    jobs = []
    for candidate in candidates:
        if candidate["jurisdiction"] == "EU":
            jobs.append((candidate, candidate.get("celex"), None, None))
        else:
            parts = candidate.get("new_parts") or [{
                "title": candidate.get("title_number"),
                "part": candidate.get("part_number"),
            }]
            for part in parts:
                jobs.append((candidate, None, part.get("title"),
                             part.get("part")))
    jobs = jobs[:max(int(args.intake_limit), 0)]
    if not jobs:
        return []

    law_intake = None
    if not dry_run:
        from core import law_intake
        _backup_once(db_path)
    results = []
    for candidate, celex, title_number, part_number in jobs:
        category = ((candidate.get("llm") or {}).get("category")
                    or args.category or "")
        law_id = (f"EU:{celex}" if celex
                  else f"US:{title_number}:{part_number}")
        if dry_run:
            result = {"ok": True, "law_id": law_id,
                      "action": "dry_run", "reason": ""}
        else:
            try:
                if celex:
                    result = law_intake.intake_eu_law(
                        celex, category=category,
                        note=f"官方源发现于 {candidate.get('published_on', '')}",
                        source="discover_new_laws", backup=False)
                else:
                    result = law_intake.intake_us_law(
                        title_number, part_number, category=category,
                        agency=candidate.get("agency", ""),
                        source="discover_new_laws", backup=False)
            except Exception as exc:
                result = {"ok": False, "law_id": law_id, "action": "error",
                          "reason": f"{type(exc).__name__}: {str(exc)[:160]}"}
        candidate.setdefault("intakes", []).append(result)
        results.append(result)
        flag = "✓" if result.get("ok") else "✗"
        print(f"  {flag} {result.get('action', ''):<14} "
              f"{law_id}  {result.get('reason', '')}", flush=True)
    return results


def run_refresh():
    """建档后让下游生成材料待办并重建召回树（材料缺失时只建 pending task）。"""
    import subprocess
    command = [sys.executable, os.path.join(HERE, "refresh_recall_pipeline.py"),
               "--from-intake-log"]
    print(f"\n[refresh] {' '.join(command)}", flush=True)
    completed = subprocess.run(command, cwd=ROOT)
    return completed.returncode


# ── 报告 ────────────────────────────────────────────────────────────
def load_seen(path=SEEN_PATH):
    """读取历史候选 first_seen；文件缺失/损坏都当第一次运行。"""
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        laws = data.get("laws") if isinstance(data, dict) else None
        return laws if isinstance(laws, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def mark_seen(candidates, previous, now=None):
    """标记 first_seen / is_new；返回 (要持久化的映射, 本轮新增数)。"""
    now = now or now_bjt()
    stamp = now.strftime("%Y-%m-%d %H:%M:%S")
    cutoff = (now - timedelta(days=SEEN_MAX_AGE_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    kept = {law_id: first for law_id, first in (previous or {}).items()
            if isinstance(first, str) and first >= cutoff}
    new_count = 0
    for candidate in candidates:
        law_id = candidate.get("law_id") or ""
        first_seen = kept.get(law_id) or stamp
        candidate["first_seen"] = first_seen
        candidate["is_new"] = law_id not in (previous or {})
        if candidate["is_new"]:
            new_count += 1
        kept[law_id] = first_seen
    return kept, new_count


def _atomic_json(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp-" + str(os.getpid())
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _append_log(payload):
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _conflict_key(item):
    return (item.get("identifier"),
            (item.get("verification") or {}).get("reason"))


def write_conflicts(conflicts, dry_run=False):
    """把“搜索说有、官方接口说没有”的冲突留存到管理端。

    追加 `new_law_conflicts.jsonl` 供审计；`new_law_conflicts.json` 是
    **按 identifier + 原因去重后的管理端队列**（带 first_seen / last_seen /
    seen_count），供后续管理员系统直接消费。普通用户可见的
    `new_law_candidates.json` 不包含这些记录。
    """
    if dry_run or not conflicts:
        return
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CONFLICT_LOG_PATH, "a", encoding="utf-8") as handle:
        for item in conflicts:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")

    existing = {}
    try:
        with open(CONFLICT_LATEST_PATH, encoding="utf-8") as handle:
            for item in json.load(handle).get("items") or []:
                if isinstance(item, dict):
                    existing[_conflict_key(item)] = item
    except (OSError, ValueError, TypeError):
        pass

    for item in conflicts:
        key = _conflict_key(item)
        old = existing.get(key)
        if old:
            old["last_seen"] = item["detected_at"]
            old["seen_count"] = int(old.get("seen_count") or 1) + 1
            for field in ("search_url", "search_title", "search_summary",
                          "discovered_by", "discovered_category"):
                if item.get(field):
                    old[field] = item[field]
            existing[key] = old
        else:
            item["first_seen"] = item["detected_at"]
            item["last_seen"] = item["detected_at"]
            item["seen_count"] = 1
            existing[key] = item

    _atomic_json(CONFLICT_LATEST_PATH, {
        "schema_version": 1,
        "generated_at": now_bjt().strftime("%Y-%m-%d %H:%M:%S"),
        "count": len(existing),
        "visibility": "admin_only",
        "items": list(existing.values()),
    })


def build_report(args, since, until, existing, candidates, stats, intake_results):
    relevant = [c for c in candidates
                if (c.get("llm") or {}).get("relevant") is True]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_bjt().strftime("%Y-%m-%d %H:%M:%S"),
        "window": {"since": since, "until": until},
        "database": {"path": os.path.abspath(args.db),
                     "laws": existing["total"],
                     "eu": len(existing["eu"]), "us": len(existing["us"])},
        "sources": stats,
        "counts": {
            "scanned": sum(s.get("scanned", 0) for s in stats),
            "skipped_exists": sum(s.get("skipped_exists", 0) for s in stats),
            "candidates": len(candidates),
            "new": sum(1 for c in candidates if c.get("is_new")),
            "llm_relevant": len(relevant),
            "intaked": sum(1 for r in intake_results if r.get("ok")),
            "web_queries": sum(s.get("queries", 0) for s in stats
                               if s.get("source") == "WEB"),
            "web_unverified": sum(s.get("unverified", 0) for s in stats
                                  if s.get("source") == "WEB"),
        },
        "candidates": sorted(
            candidates,
            key=lambda c: (c.get("published_on") or "", c.get("law_id") or ""),
            reverse=True),
    }


def print_summary(report):
    counts = report["counts"]
    print()
    print("=" * 72)
    for stat in report["sources"]:
        note = f"  {stat.get('error')}" if stat.get("error") else ""
        if stat.get("source") == "WEB":
            print(f"  WEB    {'ok' if stat.get('ok') else 'failed':<7} "
                  f"查询 {stat.get('queries', 0):>3} 次 · "
                  f"命中 {stat.get('scanned', 0):>4} · "
                  f"已存在 {stat.get('skipped_exists', 0):>3} · "
                  f"过时 {stat.get('skipped_date', 0):>3} · "
                  f"核验失败 {stat.get('unverified', 0):>3} · "
                  f"未映射 {stat.get('unmapped', 0):>3} · "
                  f"新候选 {stat.get('candidates', 0):>3}{note}")
            continue
        print(f"  {stat['source']:<6} {'ok' if stat.get('ok') else 'failed':<7} "
              f"扫描 {stat.get('scanned', 0):>4} · 已存在 {stat.get('skipped_exists', 0):>4} · "
              f"新候选 {stat.get('candidates', 0):>3}"
              f"{' · 无CFR映射 ' + str(stat.get('unmapped')) if stat.get('unmapped') else ''}"
              f"{note}")
    print(f"  合计：候选 {counts['candidates']} 条"
          f"（本轮新增 {counts.get('new', 0)} 条），"
          f"LLM 判定相关 {counts['llm_relevant']} 条，"
          f"已建档 {counts['intaked']} 条")
    print("=" * 72)
    if not report["candidates"]:
        return
    print(f"  {'日期':<10} {'市场':<3} {'编号':<22} {'相关':<5} 标题")
    for candidate in report["candidates"][:60]:
        llm = candidate.get("llm") or {}
        flag = ("是" if llm.get("relevant") is True
                else "否" if llm.get("relevant") is False
                else "?")
        ident = (candidate.get("celex") or
                 f"{candidate.get('title_number')} CFR {candidate.get('part_number')}")
        title = (candidate.get("official_title") or "")[:48]
        print(f"  {candidate.get('published_on', ''):<10} "
              f"{candidate.get('jurisdiction', ''):<3} {ident:<22} {flag:<5} {title}")
    if len(report["candidates"]) > 60:
        print(f"  … 其余 {len(report['candidates']) - 60} 条见报告文件")


# ── CLI ─────────────────────────────────────────────────────────────
def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="新法规发现（官方源增量 + 可选建档）")
    today = now_bjt().date()
    parser.add_argument("--since", default=str(today - timedelta(days=30)),
                        help="起始日期 YYYY-MM-DD（含），默认 30 天前")
    parser.add_argument("--until", default=str(today),
                        help="结束日期 YYYY-MM-DD（含），默认今天（北京时间）")
    parser.add_argument("--only", default="EU,US",
                        help="只查指定市场，逗号分隔：EU,US（默认两者）")
    parser.add_argument("--us-titles", default="",
                        help="美国 CFR Title 列表（逗号分隔）；默认取 laws 表已有 Title")
    parser.add_argument("--limit", type=int, default=300,
                        help="每个官方源最多扫描的条目数（默认 300）")
    parser.add_argument("--no-llm", action="store_true", help="跳过 LLM 相关性判断")
    parser.add_argument("--web", action="store_true",
                        help="启用 DeepSeek 联网搜索发现（官方站点限定，结果必须再经官方 API 核验）")
    parser.add_argument("--web-only", action="store_true",
                        help="只跑联网搜索，跳过 EUR-Lex SPARQL / Federal Register API 增量扫描")
    parser.add_argument("--web-count", type=int, default=8,
                        help="每个搜索词返回条数（1-50，默认 8）")
    parser.add_argument("--web-max", type=int, default=60,
                        help="联网发现最多保留候选数（默认 60）")
    parser.add_argument("--web-fetch", action="store_true",
                        help="对 URL 中无编号的官方结果调用 Fetch 读正文再提取编号")
    parser.add_argument("--web-queries", default="",
                        help="自定义搜索词，分号分隔；提供后不再使用默认 5 类商品模板")
    parser.add_argument("--intake", action="store_true",
                        help="对候选调用 core.law_intake 建档（默认只出报告）")
    parser.add_argument("--intake-all", action="store_true",
                        help="建档所有候选（默认只建档 LLM 判定为相关的）")
    parser.add_argument("--intake-limit", type=int, default=5,
                        help="单次最多建案件数（美国一条规则多个 Part 时按 Part 计，默认 5）")
    parser.add_argument("--category", default="",
                        help="LLM 未给出品类时的兜底品类")
    parser.add_argument("--refresh", action="store_true",
                        help="建档后运行 refresh_recall_pipeline --from-intake-log")
    parser.add_argument("--dry-run", action="store_true",
                        help="不写报告/日志，且 --intake 只演练不写库")
    parser.add_argument("--proxy", default="auto",
                        help="auto（默认）/ direct / 指定代理 URL")
    parser.add_argument("--db", default=str(law_store.db_path()),
                        help="laws 所在 SQLite 路径（默认 sqlite/regulations.sqlite3）")
    parser.add_argument("--report", default=REPORT_PATH, help="报告输出路径")
    return parser.parse_args(argv)


def _valid_date(text, name):
    try:
        return datetime.strptime(text.strip(), "%Y-%m-%d").date().isoformat()
    except (AttributeError, ValueError):
        raise SystemExit(f"{name} 日期格式应为 YYYY-MM-DD，收到：{text!r}")


def main(argv=None):
    args = parse_args(argv)
    since = _valid_date(args.since, "--since")
    until = _valid_date(args.until, "--until")
    if since > until:
        raise SystemExit("--since 不能晚于 --until")
    if not os.path.isfile(args.db):
        print(f"错误：laws 数据库不存在：{args.db}", file=sys.stderr)
        print("新法规发现需要 laws 表做去重；请先在离线包中放入数据库。",
              file=sys.stderr)
        return 2

    net.configure_proxy(args.proxy)

    markets = {m.strip().upper() for m in (args.only or "").split(",") if m.strip()}
    if not markets <= {"EU", "US"}:
        raise SystemExit("--only 只接受 EU / US（逗号分隔）")
    if not markets:
        raise SystemExit("--only 不能为空")

    existing = load_existing(args.db)
    if args.us_titles:
        try:
            us_titles = sorted({int(x) for x in args.us_titles.split(",")
                                if x.strip()})
        except ValueError:
            raise SystemExit("--us-titles 需为逗号分隔的数字，例如 16,21,47")
    else:
        us_titles = existing["us_titles"]
    if "US" in markets and not us_titles:
        print("⚠️ laws 表没有 US Title，跳过美国源（可用 --us-titles 指定）",
              flush=True)

    print("=" * 72)
    print("  新法规发现")
    print(f"  窗口：{since} ~ {until}（北京时间）")
    print(f"  已有：{existing['total']} 条"
          f"（EU {len(existing['eu'])} / US {len(existing['us'])}）")
    print(f"  市场：{' / '.join(sorted(markets))}；"
          f"LLM：{'关闭' if args.no_llm else '启用'}")
    print("=" * 72)

    if args.web_only:
        args.web = True

    candidates, stats = [], []
    if not args.web_only:
        if "EU" in markets:
            found, stat = discover_eu(since, until, existing, args.limit)
            candidates.extend(found)
            stats.append(stat)
            print(f"[EU] 扫描 {stat['scanned']} 条，已存在 {stat['skipped_exists']} 条，"
                  f"新候选 {len(found)} 条"
                  + (f"；错误：{stat['error']}" if stat["error"] else ""), flush=True)
        if "US" in markets and us_titles:
            found, stat = discover_us(since, until, existing, args.limit, us_titles)
            candidates.extend(found)
            stats.append(stat)
            print(f"[US] 扫描 {stat['scanned']} 条，已存在 {stat['skipped_exists']} 条，"
                  f"新候选 {len(found)} 条，无 CFR 映射 {stat.get('unmapped', 0)} 条"
                  + (f"；错误：{stat['error']}" if stat["error"] else ""), flush=True)

    web_conflicts = []
    if args.web:
        custom = [q.strip() for q in (args.web_queries or "").split(";")
                  if q.strip()]
        custom_queries = ([("自定义", "ANY", q) for q in custom]
                          if custom else None)
        found, web_conflicts, stat = discover_web(
            since, until, existing, us_titles, markets,
            count=args.web_count, max_candidates=args.web_max,
            fetch_pages=args.web_fetch, custom_queries=custom_queries)
        candidates.extend(found)
        stats.append(stat)
        print(f"[WEB] 查询 {stat.get('queries', 0)} 次"
              f"（约 ¥{stat.get('queries', 0) * 0.005:.2f}），"
              f"官方核验失败 {stat.get('unverified', 0)} 条，"
              f"新候选 {len(found)} 条"
              + (f"；错误：{stat['error']}" if stat["error"] else ""), flush=True)
        if web_conflicts:
            where = ("已留存管理端日志" if not args.dry_run
                     else "演练模式未写")
            print(f"[冲突] {len(web_conflicts)} 条「搜索说有、官方接口说没有」，"
                  f"{where}；普通用户页面不展示", flush=True)

    # 确定性源与联网源可能发现同一条法规：按 law_id 合并来源标记
    candidates = merge_candidates(candidates)
    candidates = classify_candidates(candidates, enabled=not args.no_llm)
    if candidates and not args.no_llm:
        ok = sum(1 for c in candidates if (c.get("llm") or {}).get("ok"))
        print(f"[LLM] 已判断 {ok}/{len(candidates)} 条"
              + ("（其余未返回，保留为不确定）" if ok < len(candidates) else ""),
              flush=True)

    seen, new_count = mark_seen(candidates, load_seen())
    if candidates:
        print(f"[去重] 本轮新增 {new_count} 条（对比 {SEEN_PATH} 的历史候选）",
              flush=True)

    intake_results = []
    if args.intake:
        relevant = [c for c in candidates
                    if args.intake_all
                    or (c.get("llm") or {}).get("relevant") is True]
        # 最新发布的优先建档；--intake-limit 限制的是实际建案件数
        relevant.sort(key=lambda c: c.get("published_on") or "", reverse=True)
        relevant = relevant[:max(args.intake_limit, 0)]
        if not relevant:
            print("[intake] 没有可建档的候选"
                  "（LLM 判定相关为 0；如需全部建档请加 --intake-all）", flush=True)
        else:
            print(f"\n[intake] 准备建档 {len(relevant)} 条"
                  + ("（演练）" if args.dry_run else ""), flush=True)
            intake_results = intake_candidates(
                relevant, args, args.db, dry_run=args.dry_run)
        if (args.refresh and not args.dry_run
                and any(r.get("ok") for r in intake_results)):
            run_refresh()

    report = build_report(args, since, until, existing, candidates, stats,
                          intake_results)
    if args.dry_run:
        print("\n（演练模式：未写报告/日志）")
    else:
        write_conflicts(web_conflicts, dry_run=False)
        _atomic_json(SEEN_PATH, {
            "schema_version": 1,
            "updated_at": now_bjt().strftime("%Y-%m-%d %H:%M:%S"),
            "laws": seen,
        })
        _atomic_json(args.report, report)
        _append_log({key: report[key] for key in
                     ("schema_version", "generated_at", "window", "counts")}
                    | {"sources": [{k: s.get(k) for k in
                                    ("source", "ok", "scanned", "skipped_exists",
                                     "candidates", "error")} for s in stats]})
        print(f"\n报告：{os.path.relpath(args.report, ROOT)}")
    print_summary(report)

    if stats and not any(stat.get("ok") for stat in stats):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
