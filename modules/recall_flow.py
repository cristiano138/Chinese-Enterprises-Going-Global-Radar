# -*- coding: utf-8 -*-
"""
两层法规召回流程（modules/recall_flow.py）

链路：
    用户业务描述
      -> 路由 LLM：从 recall.law_catalog() 的编号目录里选 law_refs + facets
      -> 检索 LLM：从 recall.candidate_nodes() 的编号候选里选切片 ref
      -> recall.get_nodes()：取回全文 + citation_map
      -> 返回结构化证据（法规、切片、facet、coverage、gaps）

设计原则（与项目既有分工一致）：
    · 模型只做“选择”，不做事实生成；法规/切片内容 100% 来自本地库。
    · 模型只返回 1-based 整数 ref，代码用 recall.resolve_refs() 做范围校验；
      越界/非整数一律丢弃并计入 invalid_refs。
    · 两层都关 thinking（只做选择，延迟敏感），硬超时后走确定性兜底。
    · use_cache=False：提示词含用户原文，禁止落盘缓存；内存缓存只存结构化
      结果（law_id/node_id/facet），key 是 sha256，不含原文。

与参考项目的关系：
    借用了 Loong Lab 的“编号 + 严格范围校验”“证据报告（coverage/gaps）”
    “确定性预执行”思路；没有搬 list_sections/search/get_section 工具循环。
    load_tree / candidate_nodes / get_nodes 已经覆盖了这些工具的语义。

用法：
    from modules import recall_flow
    res = recall_flow.run("带蓝牙的毛绒玩具同时卖欧盟和美国，对比化学安全和标签要求")
    python modules/recall_flow.py "..."       # CLI 演示（会调用模型）
"""

import hashlib
import json
import os
import re
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)

from core import llm, recall  # noqa: E402
from modules import m15_router  # noqa: E402

ROUTER_TIMEOUT = 3.5
RETRIEVAL_TIMEOUT = 3.5
ROUTER_MAX_TOKENS = 400
RETRIEVAL_MAX_TOKENS = 420
MAX_LAWS = 24
CANDIDATES_PER_LAW = 3
MAX_SELECTED = 24
FALLBACK_PER_LAW = 2


def _default_candidates_per_law(n_laws):
    """候选预算：法规少时多给切片，法规多时控制 prompt 体积/延迟。"""
    if n_laws <= 8:
        return 6
    if n_laws <= 14:
        return 4
    return CANDIDATES_PER_LAW
CATALOG_TITLE_CHARS = 90
SNIPPET_CHARS = 200

# 显式点名法规时不要用关键词子集缩小目录，避免漏掉同市场的其他法规。
LAW_HINTS = (
    "reach", "rohs", "ce marking", "cpsia", "fda", "gpsr", "weee",
    "en71", "en 71", "california 65", "ca65", "fcc", "astm", "cpsc",
)

# 源数据的「类目」是单标签：REACH/CLP 被标到纺织服装，但它们是横切化学法规。
# 预筛目录时，除品类命中外，把标题带这些词的法规也带上，避免化学/标签类
# 问题看不到 REACH/CLP/GPSR 等横切法规。
CROSS_CUTTING_TITLE_HINTS = (
    "chemical", "substance", "classification", "labelling", "labeling",
    "restriction", "general product safety", "packaging", "battery",
    "radio equipment", "electromagnetic", "certification", "compliance",
    "testing", "conformity",
)

_CACHE = {}
_CACHE_MAX = 128
_CACHE_LOCK = threading.Lock()

JURISDICTION_CN = {"欧盟": "EU", "美国": "US"}

FACETS_BY_CATEGORY = {
    "儿童玩具": ["toy safety", "chemical safety", "labeling", "testing and certification"],
    "电子电器": ["electrical safety", "EMC", "CE marking", "labeling", "testing and certification"],
    "纺织服装": ["textile safety", "chemical safety", "labeling", "testing and certification"],
    "美妆个护": ["cosmetic safety", "chemical safety", "labeling", "testing and certification"],
    "食品接触材料": ["food contact materials", "chemical safety", "labeling", "testing and certification"],
    "标签标识": ["labeling", "marking", "language requirements"],
    "通用": ["general product safety", "risk assessment", "traceability"],
}

ROUTER_PROMPT = """你是“出海合规法规路由器”。根据用户的业务描述，从给定法规目录中选出需要检查的法规。

法规目录（每行：ref | 辖区 | 类目 | 效力 | 标题）：
{catalog}

本地词典初判（仅供参考，可能不完整或错误）：品类={category}，市场={market}

用户业务描述：
{query}

要求：
1. 只返回目录中存在的 ref，不得编造 ref。
2. 产品可能同时属于多个品类（例如带蓝牙的毛绒玩具 = 儿童玩具 + 电子电器），把所有相关法规都选上。
3. 跨市场对比（例如“欧盟和美国”）要选出每个市场对应的法规。
4. facets 用英文短语，检索层会用它们在英文法条里匹配；最多 8 个，例如 ["chemical safety", "labeling", "CE marking"]。
5. 化学安全/成分/标签问题要同时考虑 REACH/CLP/GPSR 等横切法规（如果目录中有）。
6. 蓝牙/无线产品在美国对应 FCC Part 15（目录中的 PART 15—RADIO FREQUENCY DEVICES）。
7. 测试/认证/合规证书问题要选目录中标题含 TESTING / CERTIFICATION / COMPLIANCE 的法规。
8. 美国儿童产品要同时考虑 CPSC 的通用危险物质与玩具识别法规（PART 1500 / PART 1501）。
9. 目录里没有对应监管领域时写进 catalog_gaps，不要硬选。
10. 最多选 {max_laws} 条法规。

只输出 JSON（不要 Markdown、不要解释）：
{{"law_refs":[1,2],"facets":["..."],"catalog_gaps":["..."]}}"""

RETRIEVAL_PROMPT = """你是“法规切片选择器”。根据用户问题和关注面，从候选切片表中选出直接相关的切片。

用户问题：
{query}

路由层选出的法规：
{laws}

关注面（facets）：
{facets}

候选切片（每行：ref | law_id | path | heading | 预览）：
{candidates}

要求：
1. 只选与问题直接相关的切片；只返回表中的 ref，不得编造。
2. 每条选择只打一个 facet 标签（优先使用上面的 facets）。
3. 同一 facet 尽量在每个相关市场都选到；某个市场确实没有时写进 gaps，不要硬选。
4. 最多选 {max_selected} 条。
5. coverage：主要 facet 都覆盖到了写 sufficient，否则 partial。
6. 不要输出 why 或解释文字。

只输出 JSON（不要 Markdown）：
{{"selected":[{{"ref":3,"facet":"chemical safety"}}],"coverage":"sufficient|partial","gaps":["..."]}}"""


# ── 缓存 ────────────────────────────────────────────────────────────
def _cache_key(query, context, version, use_llm):
    raw = ("\x00".join((
        (query or "").strip(),
        (context or "").strip(),
        (version or ""),
        "llm" if use_llm else "deterministic",
    )))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cache_get(key):
    with _CACHE_LOCK:
        return _CACHE.get(key)


def _cache_put(key, value):
    with _CACHE_LOCK:
        if len(_CACHE) >= _CACHE_MAX:
            _CACHE.pop(next(iter(_CACHE)))
        _CACHE[key] = value


def clear_cache():
    with _CACHE_LOCK:
        _CACHE.clear()


# ── 工具 ────────────────────────────────────────────────────────────
def _parse_json(text):
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _str_list(value, limit=32):
    if not isinstance(value, list):
        return []
    out = []
    for x in value:
        s = str(x or "").strip()
        if s and s not in out:
            out.append(s[:200])
        if len(out) >= limit:
            break
    return out


def _truncate(s, n):
    s = str(s or "").strip()
    return s if len(s) <= n else s[:n].rstrip() + "…"


def _catalog_rows(catalog):
    rows = []
    for c in catalog:
        rows.append("%d | %s | %s | %s | %s" % (
            c.get("ref"),
            c.get("jurisdiction") or "",
            c.get("category") or "-",
            c.get("in_force") or "-",
            _truncate(c.get("official_title") or "", CATALOG_TITLE_CHARS),
        ))
    return "\n".join(rows)


def _detect_scope(query, context):
    """用 M1.5 的词典表做确定性预筛：返回 (markets, categories)。"""
    blob = ("%s %s" % (query or "", context or "")).lower()
    markets = [m for m, words in m15_router.MARKET_WORDS.items()
               if any(w in blob for w in words)]
    cats = [c for c, words in m15_router.CATEGORY_WORDS.items()
            if any(w in blob for w in words)]
    return markets, cats


def preselect_catalog(query, context, catalog):
    """确定性缩小路由目录，降低提示词长度。

    - 明确提到法规名（REACH/CPSIA/CE…）时不做子集，避免漏法规。
    - 识别到品类/市场时，只给 品类×市场 + 横切 的法规。
    - 识别不到品类时退回全量目录，让模型自己判断。
    """
    markets, cats = _detect_scope(query, context)
    blob = ("%s %s" % (query or "", context or "")).lower()
    explicit_law = any(h in blob for h in LAW_HINTS)
    if explicit_law or not cats:
        return catalog, {"markets": markets, "categories": cats, "narrowed": False}
    jurisdictions = {JURISDICTION_CN[m] for m in markets} if markets else {"EU", "US"}
    wanted = set(cats)
    if not wanted.intersection({"标签标识", "通用"}):
        wanted.update({"标签标识", "通用"})
    base = [c for c in catalog
            if c.get("jurisdiction") in jurisdictions
            and (c.get("category") or "") in wanted]
    # 横切化学/标签法规（如 REACH/CLP 被标到纺织服装）也要让路由器看到。
    extra = [c for c in catalog
             if c.get("jurisdiction") in jurisdictions
             and any(h in (c.get("official_title") or "").lower()
                     for h in CROSS_CUTTING_TITLE_HINTS)]
    seen = set()
    subset = []
    for c in base + extra:
        lid = c.get("law_id")
        if lid and lid not in seen:
            seen.add(lid)
            subset.append(c)
    if not subset:
        return catalog, {"markets": markets, "categories": cats, "narrowed": False}
    return subset, {"markets": markets, "categories": cats, "narrowed": True}


def _fallback_facets(laws):
    out = []
    for law in laws:
        for f in FACETS_BY_CATEGORY.get(law.get("category") or "", []):
            if f not in out:
                out.append(f)
    return out


def _fallback_route(query, context, catalog):
    """确定性兜底：复用 M1.5 的本地词典，按 品类 × 市场 过滤目录。"""
    slots = m15_router.parse_local(query, context)
    cat = slots.get("品类") or ""
    market = slots.get("市场") or ""
    if cat == m15_router.OOS or market == m15_router.OOS:
        return {
            "ok": False, "reason": "输入包含本期不支持的市场或品类",
            "laws": [], "facets": [], "sub_questions": [], "catalog_gaps": [],
            "route_via": "词典兜底", "meta": {}, "invalid_refs": [],
            "slots": slots,
        }
    if not cat:
        return {
            "ok": False, "reason": "未能识别产品品类，请补充产品类型",
            "laws": [], "facets": [], "sub_questions": [], "catalog_gaps": [],
            "route_via": "词典兜底", "meta": {}, "invalid_refs": [],
            "slots": slots,
        }
    jur = JURISDICTION_CN.get(market)
    if not jur:
        return {
            "ok": False, "reason": "缺少目标市场，请补充欧盟或美国",
            "laws": [], "facets": [], "sub_questions": [], "catalog_gaps": [],
            "route_via": "词典兜底", "meta": {}, "invalid_refs": [],
            "slots": slots,
        }
    wanted = {cat}
    if cat not in ("标签标识", "通用"):
        wanted.update({"标签标识", "通用"})
    laws = [c for c in catalog
            if c.get("jurisdiction") == jur and (c.get("category") or "") in wanted]
    return {
        "ok": bool(laws),
        "reason": "" if laws else "目录中没有匹配的法规",
        "laws": laws[:MAX_LAWS],
        "facets": _fallback_facets(laws) or ["compliance requirements"],
        "sub_questions": [],
        "catalog_gaps": [],
        "route_via": "词典兜底",
        "meta": {},
        "invalid_refs": [],
        "slots": slots,
    }


# ── 路由层 ──────────────────────────────────────────────────────────
def route_laws(query, context="", use_llm=True, catalog=None):
    """从编号法规目录里选 law_refs。模型失败时走确定性兜底。"""
    full_catalog = catalog if catalog is not None else recall.law_catalog(as_numbered=True)
    if not full_catalog:
        return {
            "ok": False, "reason": "召回目录树为空，请先运行 scripts/build_recall_tree.py",
            "laws": [], "facets": [], "sub_questions": [], "catalog_gaps": [],
            "route_via": "无", "meta": {}, "invalid_refs": [], "slots": {},
            "catalog_scope": {},
        }

    slots = m15_router.parse_local(query, context)
    scoped_catalog, scope = preselect_catalog(query, context, full_catalog)
    if use_llm and llm.is_ready():
        prompt = ROUTER_PROMPT.format(
            catalog=_catalog_rows(scoped_catalog),
            category=slots.get("品类") or "（未识别）",
            market=slots.get("市场") or "（未识别）",
            query=(query or "")[:1500],
            max_laws=MAX_LAWS,
        )
        out, meta = llm.chat(
            prompt, max_tokens=ROUTER_MAX_TOKENS, temperature=0,
            use_cache=False, timeout=ROUTER_TIMEOUT, thinking=False,
        )
        data = _parse_json(out) if meta.get("ok") else None
        if data is not None:
            refs = data.get("law_refs") if isinstance(data.get("law_refs"), list) else []
            valid, invalid = recall.resolve_refs(refs, scoped_catalog)
            if valid:
                laws = valid[:MAX_LAWS]
                facets = _str_list(data.get("facets"))
                if not facets:
                    facets = _fallback_facets(laws)
                return {
                    "ok": True, "reason": "",
                    "laws": laws,
                    "facets": facets or ["compliance requirements"],
                    "sub_questions": _str_list(data.get("sub_questions")),
                    "catalog_gaps": _str_list(data.get("catalog_gaps")),
                    "route_via": "模型路由",
                    "meta": meta,
                    "invalid_refs": invalid,
                    "slots": slots,
                    "catalog_scope": scope,
                }
            # 模型输出的 ref 全部无效 → 兜底，但保留无效计数
            fallback = _fallback_route(query, context, full_catalog)
            fallback["invalid_refs"] = invalid
            fallback["meta"] = meta
            fallback["reason"] = "模型未返回有效法规 ref，已回退词典"
            fallback["catalog_scope"] = scope
            return fallback
        fallback = _fallback_route(query, context, full_catalog)
        fallback["meta"] = meta
        fallback["reason"] = "模型路由失败，已回退词典：%s" % (meta.get("reason") or "无输出")
        fallback["catalog_scope"] = scope
        return fallback

    fallback = _fallback_route(query, context, full_catalog)
    fallback["catalog_scope"] = scope
    return fallback


# ── 检索层 ──────────────────────────────────────────────────────────
def _candidate_rows(candidates):
    rows = []
    for c in candidates:
        rows.append("%d | %s | %s | %s | %s" % (
            c.get("ref"),
            c.get("law_id") or "",
            _truncate(c.get("path") or "", 140),
            _truncate(c.get("heading") or "", 120),
            _truncate((c.get("snippet") or "").replace("\n", " "), SNIPPET_CHARS),
        ))
    return "\n".join(rows)


def _candidate_laws_text(laws):
    return "\n".join(
        "- %s | %s | %s" % (
            l.get("law_id") or "",
            l.get("jurisdiction") or "",
            _truncate(l.get("official_title") or "", CATALOG_TITLE_CHARS),
        )
        for l in laws
    )


def _normalize_selected(data):
    """把模型返回的 selected 归一成 [(ref, facet, why)]；容忍 int 简写和数字字符串。"""
    out = []
    if not isinstance(data, list):
        return out
    for item in data:
        if isinstance(item, bool):
            continue
        if isinstance(item, int):
            out.append((item, "unspecified", ""))
            continue
        if not isinstance(item, dict):
            continue
        ref = item.get("ref")
        if isinstance(ref, str) and ref.strip().isdigit():
            ref = int(ref.strip())
        if not isinstance(ref, int) or isinstance(ref, bool):
            continue
        facet = str(item.get("facet") or "").strip() or "unspecified"
        why = str(item.get("why") or "").strip()
        out.append((ref, facet, why))
    return out


def _fallback_selected(candidates, laws):
    """模型不可用/无有效选择时：每法取前 N 条候选。"""
    by_law = {}
    for c in candidates:
        by_law.setdefault(c.get("law_id"), []).append(c)
    out = []
    for law in laws:
        entries = by_law.get(law.get("law_id"), [])[:FALLBACK_PER_LAW]
        for c in entries:
            out.append({**c, "facet": "unspecified", "why": "模型不可用，回退候选集"})
        if len(out) >= MAX_SELECTED:
            break
    return out[:MAX_SELECTED]


def retrieve(query, laws, facets, use_llm=True, candidates=None,
             limit_per_law=None):
    """在候选切片里选 ref，返回结构化证据 + citation_map。"""
    if not laws:
        return {
            "ok": False, "reason": "没有选中法规", "selected": [],
            "coverage": "partial", "gaps": [], "invalid_refs": [],
            "meta": {}, "citation_map": {},
        }
    law_ids = [l.get("law_id") for l in laws if l.get("law_id")]
    keywords = list(facets or []) + [query or ""]
    if candidates is None:
        if limit_per_law is None:
            limit_per_law = _default_candidates_per_law(len(law_ids))
        candidates = recall.candidate_nodes(law_ids, keywords, limit_per_law)
    if not candidates:
        return {
            "ok": False, "reason": "候选切片为空（FTS 与回退都没有结果）",
            "selected": [], "coverage": "partial", "gaps": ["没有候选切片"],
            "invalid_refs": [], "meta": {}, "citation_map": {},
        }

    selected = []
    invalid = []
    gaps = []
    coverage = "partial"
    meta = {}

    if use_llm and llm.is_ready():
        prompt = RETRIEVAL_PROMPT.format(
            query=(query or "")[:1500],
            laws=_candidate_laws_text(laws),
            facets=json.dumps(facets or [], ensure_ascii=False),
            candidates=_candidate_rows(candidates),
            max_selected=MAX_SELECTED,
        )
        out, meta = llm.chat(
            prompt, max_tokens=RETRIEVAL_MAX_TOKENS, temperature=0,
            use_cache=False, timeout=RETRIEVAL_TIMEOUT, thinking=False,
        )
        data = _parse_json(out) if meta.get("ok") else None
        if data is not None:
            items = _normalize_selected(data.get("selected"))
            refs = [r for r, _f, _w in items]
            valid, invalid = recall.resolve_refs(refs, candidates)
            by_ref = {c["ref"]: c for c in valid}
            for ref, facet, why in items:
                c = by_ref.get(ref)
                if not c:
                    continue
                selected.append({**c, "facet": facet, "why": why})
                if len(selected) >= MAX_SELECTED:
                    break
            coverage = str(data.get("coverage") or "partial").strip().lower()
            if coverage not in ("sufficient", "partial"):
                coverage = "partial"
            gaps = _str_list(data.get("gaps"))
        else:
            gaps.append("检索模型未返回有效 JSON")

    if not selected:
        selected = _fallback_selected(candidates, laws)
        if not gaps:
            gaps.append("未获得有效切片选择，已回退候选集")
        coverage = "partial"

    # 去重（同一 node_id 只保留第一次）
    dedup = []
    seen = set()
    for s in selected:
        nid = s.get("node_id")
        if nid and nid not in seen:
            seen.add(nid)
            dedup.append(s)
    selected = dedup

    nodes = recall.get_nodes([s["node_id"] for s in selected])
    by_id = {n.get("node_id"): n for n in nodes}
    citation_map = {}
    enriched = []
    for i, s in enumerate(selected, 1):
        cid = "c%d" % i
        n = by_id.get(s.get("node_id"))
        if not n:
            continue
        entry = {
            "citation_id": cid,
            "node_id": n.get("node_id"),
            "law_id": n.get("law_id"),
            "path": n.get("path"),
            "heading": n.get("heading"),
            "locator": n.get("locator"),
            "facet": s.get("facet") or "unspecified",
            "why": s.get("why") or "",
            "char_count": n.get("char_count"),
            "body": n.get("body") or "",
        }
        citation_map[cid] = {
            "node_id": n.get("node_id"),
            "law_id": n.get("law_id"),
            "path": n.get("path"),
            "heading": n.get("heading"),
            "locator": n.get("locator"),
            "facet": entry["facet"],
        }
        enriched.append(entry)

    return {
        "ok": bool(enriched),
        "reason": "" if enriched else "选中的切片在库中不存在",
        "selected": enriched,
        "coverage": coverage,
        "gaps": gaps,
        "invalid_refs": invalid,
        "meta": meta,
        "citation_map": citation_map,
    }


# ── 编排 ────────────────────────────────────────────────────────────
def run(query, context="", use_llm=True):
    """路由 + 检索。返回结构化结果；任何失败都不抛异常。"""
    t0 = time.time()
    version = recall.tree_version()
    key = _cache_key(query, context, version, use_llm)
    hit = _cache_get(key)
    if hit is not None:
        result = dict(hit)
        result["cached"] = True
        return result

    routed = route_laws(query, context, use_llm=use_llm)
    if not routed.get("ok"):
        result = {
            "ok": False,
            "reason": routed.get("reason") or "路由失败",
            "route": routed,
            "retrieval": None,
            "tree_version": version,
            "latency_ms": int((time.time() - t0) * 1000),
            "cached": False,
        }
        # 失败/超时不缓存：网络抖动不该让同一输入永远降级（与 M1.5 一致）。
        return result

    retrieved = retrieve(query, routed["laws"], routed["facets"], use_llm=use_llm)
    result = {
        "ok": bool(retrieved.get("ok")),
        "reason": "" if retrieved.get("ok") else (retrieved.get("reason") or "检索失败"),
        "route": routed,
        "retrieval": retrieved,
        "tree_version": version,
        "latency_ms": int((time.time() - t0) * 1000),
        "cached": False,
    }
    if result["ok"]:
        _cache_put(key, result)
    return result


def render_text(result):
    """CLI/自检用的人类可读摘要。"""
    lines = []
    route = result.get("route") or {}
    ret = result.get("retrieval") or {}
    lines.append("路由：%s（%s）" % (route.get("route_via") or "-",
                                   "OK" if route.get("ok") else "FAIL"))
    if route.get("reason"):
        lines.append("  原因：%s" % route["reason"])
    for law in route.get("laws") or []:
        lines.append("  - %s | %s | %s" % (
            law.get("law_id"), law.get("jurisdiction"),
            _truncate(law.get("official_title") or "", 80)))
    lines.append("facets：%s" % ", ".join(route.get("facets") or []))
    if route.get("catalog_gaps"):
        lines.append("目录缺口：%s" % "；".join(route["catalog_gaps"]))
    lines.append("检索：coverage=%s，切片=%d" % (
        ret.get("coverage") or "-", len(ret.get("selected") or [])))
    for s in ret.get("selected") or []:
        lines.append("  [%s] %s | %s | %s" % (
            s.get("citation_id"), s.get("facet"), s.get("law_id"),
            _truncate(s.get("path") or "", 100)))
    if ret.get("gaps"):
        lines.append("检索缺口：%s" % "；".join(ret["gaps"]))
    if result.get("latency_ms") is not None:
        lines.append("耗时：%d ms%s" % (result["latency_ms"],
                                        "（缓存）" if result.get("cached") else ""))
    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print("用法：python modules/recall_flow.py \"你的业务描述\"")
        return 2
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    res = run(sys.argv[1], " ".join(sys.argv[2:]))
    print(render_text(res))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
