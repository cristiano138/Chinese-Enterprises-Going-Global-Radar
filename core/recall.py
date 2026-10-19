# -*- coding: utf-8 -*-
"""
召回目录树只读访问层（core/recall.py）

用途：
    scripts/build_recall_tree.py 生成 recall_nodes / recall_law_docs /
    recall_nodes_fts 之后，路由层和检索层通过本模块读取，不直接写 SQL。

设计约束：
    · 只读：连接用 URI mode=ro + PRAGMA query_only=ON，任何写操作都会失败。
    · 不落盘原文：缓存只在内存里，按 tree_version 失效。
    · 编号化返回：候选节点带 1-based `ref`，上层 LLM 只回 ref，代码再映射
      回 node_id；这是防幻觉的关键（参考 Loong Lab 的 project_match_llm 模式）。

中文检索限制（重要）：
    语料正文是英文，FTS5 用 unicode61 分词。中文 query 不能直接命中英文
    正文（实测“邻苯二甲酸酯”对“phthalate”无结果）。路由层必须输出英文
    facet 关键词，或由调用方接受 LIKE 兜底 / 全树回退。

用法：
    from core import recall
    cat = recall.law_catalog()                 # 带 ref 的紧凑法规目录
    cands = recall.candidate_nodes(["EU:32008R1272"], ["phthalate"], 20)
    nodes = recall.get_nodes([c["node_id"] for c in cands])
"""

import json
import os
import re
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
ROOT = os.path.dirname(PROJECT)


def db_path():
    """与 core/law_store.py 保持同一套解析顺序，避免两处读不同的库。"""
    configured = os.getenv("COMPLIANCE_DB_PATH", "").strip()
    if configured:
        return configured
    for candidate in (os.path.join(PROJECT, "sqlite", "regulations.sqlite3"),
                      os.path.join(ROOT, "sqlite", "regulations.sqlite3")):
        if os.path.exists(candidate):
            return candidate
    return os.path.join(PROJECT, "sqlite", "regulations.sqlite3")


DB_PATH = db_path()

_CON = None
_CATALOG_CACHE = None
_CATALOG_VERSION = None
_ASCII_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*")

# 参考 Loong Lab knowledge_service._build_fts5_query 的停用词思路，英文侧
# 只保留一个轻量集合（不引入 jieba）。
_STOP_WORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
    "by", "as", "at", "is", "are", "was", "were", "be", "been", "being",
    "this", "that", "these", "those", "it", "its", "from", "not", "no",
    "shall", "may", "must", "can", "could", "should", "any", "all", "each",
    "every", "such", "than", "then", "also", "just", "more", "some",
}


def _preview(text, head=400, tail=200):
    """首 400 + 尾 200；复用 Loong Lab _make_chunk_preview 的预览口径。"""
    text = (text or "").strip()
    if len(text) <= head + tail + 20:
        return text[:head]
    return text[:head] + " … " + text[-tail:]


def _connect():
    global _CON
    if _CON is not None:
        return _CON
    target = DB_PATH if os.path.exists(DB_PATH) else db_path()
    uri = "file:%s?mode=ro" % target.replace("\\", "/")
    con = sqlite3.connect(uri, uri=True, timeout=5)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA query_only=ON")
    except sqlite3.DatabaseError:
        pass
    _CON = con
    return con


def close():
    global _CON, _CATALOG_CACHE, _CATALOG_VERSION
    if _CON is not None:
        try:
            _CON.close()
        except Exception:
            pass
    _CON = None
    _CATALOG_CACHE = None
    _CATALOG_VERSION = None


def _reset_cache():
    """测试辅助：清连接和目录缓存。"""
    close()


def _table_exists(con, name):
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name=?",
        (name,),
    ).fetchone() is not None


def tree_version():
    """返回当前树版本；表不存在时返回 None。"""
    con = _connect()
    if not _table_exists(con, "recall_build_meta"):
        return None
    row = con.execute(
        "SELECT value FROM recall_build_meta WHERE key='tree_version'"
    ).fetchone()
    return row[0] if row else None


def _seed_meta(seed_json):
    try:
        data = json.loads(seed_json or "{}")
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def law_catalog(as_numbered=True):
    """法规目录：laws LEFT JOIN recall_law_docs。

    返回 list[dict]，按 jurisdiction, law_id 排序；as_numbered=True 时附
    1-based `ref`，供路由 LLM 返回 `law_refs`。
    """
    global _CATALOG_CACHE, _CATALOG_VERSION
    version = tree_version()
    if _CATALOG_CACHE is not None and _CATALOG_VERSION == version:
        return list(_CATALOG_CACHE)
    con = _connect()
    if _table_exists(con, "recall_law_docs"):
        rows = con.execute(
            """SELECT l.id, l.jurisdiction, l.official_title, l.in_force,
                      l.effective_status_detail, l.seed_json,
                      ld.document_id, ld.selection_role, ld.selection_reason,
                      ld.selected_leaf_units, ld.fallback_mode
               FROM laws l LEFT JOIN recall_law_docs ld ON ld.law_id = l.id
               ORDER BY l.jurisdiction, l.id"""
        ).fetchall()
    else:
        rows = con.execute(
            """SELECT id, jurisdiction, official_title, in_force,
                      effective_status_detail, seed_json,
                      NULL, NULL, NULL, NULL, NULL
               FROM laws ORDER BY jurisdiction, id"""
        ).fetchall()
    out = []
    for i, r in enumerate(rows, 1):
        meta = _seed_meta(r["seed_json"])
        item = {
            "law_id": r["id"],
            "jurisdiction": r["jurisdiction"],
            "official_title": r["official_title"] or r["id"],
            "in_force": r["in_force"],
            "effective_status_detail": r["effective_status_detail"],
            "category": meta.get("类目"),
            "name_zh": meta.get("法规中文名"),
            "official_number": meta.get("官方编号"),
            "selected_document_id": r[6],
            "selection_role": r[7],
            "selection_reason": r[8],
            "selected_leaf_units": r[9],
            "fallback_mode": r[10],
        }
        if as_numbered:
            item["ref"] = i
        out.append(item)
    _CATALOG_CACHE = out
    _CATALOG_VERSION = version
    return list(out)


def _node_dict(row, include_body=True):
    d = {
        "node_id": row["node_id"],
        "law_id": row["law_id"],
        "document_id": row["document_id"],
        "parent_id": row["parent_id"],
        "node_type": row["node_type"],
        "unit_type": row["unit_type"],
        "unit_ordinal": row["unit_ordinal"],
        "chunk_index": row["chunk_index"],
        "chunk_total": row["chunk_total"],
        "chunk_label": row["chunk_label"],
        "depth": row["depth"],
        "sibling_ordinal": row["sibling_ordinal"],
        "path": row["path"],
        "locator": row["locator"],
        "source_url": row["source_url"],
        "heading": row["heading"],
        "heading_label": row["heading_label"],
        "heading_title": row["heading_title"],
        "char_count": row["char_count"],
        "is_leaf": row["is_leaf"],
        "is_substantive": row["is_substantive"],
        "importance": row["importance"],
        "flags": row["flags"],
        "tree_version": row["tree_version"],
    }
    if include_body:
        d["body"] = row["body"]
    return d


def load_tree(law_ids=None, include_body=False):
    """返回 dict[law_id] -> list[node]，按树顺序排列。"""
    con = _connect()
    if not _table_exists(con, "recall_nodes"):
        return {}
    sql = ("SELECT * FROM recall_nodes")
    params = []
    if law_ids:
        ph = ",".join("?" for _ in law_ids)
        sql += " WHERE law_id IN (%s)" % ph
        params = list(law_ids)
    sql += " ORDER BY law_id, depth, sibling_ordinal, chunk_index"
    rows = con.execute(sql, params).fetchall()
    out = {}
    for r in rows:
        out.setdefault(r["law_id"], []).append(_node_dict(r, include_body))
    return out


def _fallback_candidates(con, law_ids, limit_per_law):
    """无可用关键词时的确定性回退：每法按 importance/深度取叶子。"""
    params = []
    where = "n.is_leaf=1 AND n.is_substantive=1"
    if law_ids:
        ph = ",".join("?" for _ in law_ids)
        where += " AND n.law_id IN (%s)" % ph
        params = list(law_ids)
    rows = con.execute(
        """SELECT n.* FROM recall_nodes n
           WHERE %s
           ORDER BY n.law_id,
                    CASE n.importance WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END,
                    n.depth, n.sibling_ordinal, n.chunk_index""" % where,
        params,
    ).fetchall()
    out, counts = [], {}
    for r in rows:
        law = r["law_id"]
        if counts.get(law, 0) >= limit_per_law:
            continue
        counts[law] = counts.get(law, 0) + 1
        d = _node_dict(r, False)
        d["snippet"] = _preview(r["body"] or r["heading"] or "")
        d["score"] = 0.0
        out.append(d)
    return out


def candidate_nodes(law_ids=None, keywords=None, limit_per_law=20):
    """按英文关键词做 FTS/BM25 候选召回，返回带 1-based `ref` 的列表。

    keywords: str 或 list[str]。只保留 ASCII token；中文输入会走回退。
    """
    con = _connect()
    if not _table_exists(con, "recall_nodes"):
        return []
    if isinstance(keywords, str):
        raw = [keywords]
    else:
        raw = list(keywords or [])
    tokens = []
    for item in raw:
        for m in _ASCII_TOKEN_RE.finditer(str(item)):
            tok = m.group(0).lower()
            if len(tok) >= 2 and tok not in _STOP_WORDS and tok not in tokens:
                tokens.append(tok)
    tokens = tokens[:32]

    if not tokens:
        out = _fallback_candidates(con, law_ids, limit_per_law)
    else:
        # 复用参考项目“短语优先 + OR 召回”的查询构造：多词输入先整句短语，
        # 再逐词 OR；这样 "CE marking" / "toy safety" 不会只命中 "ce"。
        phrases = []
        for item in raw:
            s = re.sub(r"\s+", " ", str(item)).strip()
            if " " in s and len(s) <= 80 and re.search(r"[A-Za-z]", s):
                phrase = s.replace('"', "").lower()
                if phrase not in phrases:
                    phrases.append('"%s"' % phrase)
        terms = ['"%s"' % t.replace('"', "") for t in tokens]
        match = " OR ".join(dict.fromkeys(phrases + terms))
        where = "n.is_leaf=1 AND n.is_substantive=1"
        params = [match]
        if law_ids:
            ph = ",".join("?" for _ in law_ids)
            where += " AND n.law_id IN (%s)" % ph
            params.extend(law_ids)
        # bm25() 不能直接出现在窗口函数里（SQLite 限制），先算出 score 再排名。
        sql = """
            SELECT * FROM (
                SELECT q.*, ROW_NUMBER() OVER (
                    PARTITION BY q.law_id ORDER BY q.score
                ) AS rn
                FROM (
                    SELECT n.*,
                           snippet(recall_nodes_fts, 3, '[', ']', '…', 24) AS snip,
                           bm25(recall_nodes_fts, 0, 0, 5.0, 1.0) AS score
                    FROM recall_nodes_fts
                    JOIN recall_nodes n ON n.node_id = recall_nodes_fts.node_id
                    WHERE recall_nodes_fts MATCH ? AND %s
                ) q
            ) WHERE rn <= ?
            ORDER BY law_id, score
        """ % where
        params.append(limit_per_law)
        try:
            rows = con.execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            rows = []
        out = []
        for r in rows:
            d = _node_dict(r, False)
            d["snippet"] = r["snip"] or _preview(r["body"] or r["heading"] or "")
            d["score"] = float(r["score"]) if r["score"] is not None else 0.0
            out.append(d)
        if not out:
            out = _fallback_candidates(con, law_ids, limit_per_law)

    for i, d in enumerate(out, 1):
        d["ref"] = i
    return out


def resolve_refs(refs, candidates):
    """严格校验 LLM 返回的 ref。

    复用 Loong Lab `backend/services/project_match_llm.py:116` 的口径：
    只接受整数（bool 不算）、必须在 1..n 内；非整数/越界一律丢弃并返回，
    供调用方记录 invalid_ref_rate。重复 ref 只保留第一次。
    """
    by_ref = {c.get("ref"): c for c in (candidates or [])}
    valid, invalid, seen = [], [], set()
    if not isinstance(refs, (list, tuple)):
        return [], refs
    for r in refs:
        if isinstance(r, bool) or not isinstance(r, int):
            invalid.append(r)
            continue
        c = by_ref.get(r)
        if not c:
            invalid.append(r)
            continue
        key = c.get("node_id") or c.get("law_id") or r
        if key in seen:
            continue
        seen.add(key)
        valid.append(c)
    return valid, invalid


def get_nodes(node_ids, include_body=True):
    """按 node_id 批量取节点，保持输入顺序。"""
    con = _connect()
    if not _table_exists(con, "recall_nodes"):
        return []
    ids = [x for x in dict.fromkeys(node_ids or [])]
    out = []
    for i in range(0, len(ids), 500):
        batch = ids[i:i + 500]
        ph = ",".join("?" for _ in batch)
        rows = con.execute(
            "SELECT * FROM recall_nodes WHERE node_id IN (%s)" % ph, batch
        ).fetchall()
        found = {r["node_id"]: _node_dict(r, include_body) for r in rows}
        out.extend(found[x] for x in batch if x in found)
    return out
