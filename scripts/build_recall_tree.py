# -*- coding: utf-8 -*-
"""
法规召回目录树构建（scripts/build_recall_tree.py）

用途：
    把 regulations.sqlite3 里扁平的 units 表整理成可被检索层使用的树：
        法规根 -> 条款/附件（article/annex/section/appendix）-> 超长单元的分块
    结果写入派生表（不改 laws/documents/law_documents/units）：
        recall_law_docs     每法选中的 canonical 文档与选择原因
        recall_nodes        树节点（容器 + 叶子 + 分块）
        recall_nodes_fts    FTS5 索引（heading + body）
        recall_build_meta   版本/配置/校验摘要

口径（2026-10-18 与用户确认）：
    · EU 优先 eu_consolidated（现行合并文本），结构不完整时退回 primary；
      US 用 primary（eCFR）。
    · 只建现行法规树：修正案、勘误、FR 规则发布、bulk fallback、annual
      reference、cited source reference 都不进树。
    · 分块上限默认 6,000 字符；语义锚点优先（CLP index / REACH entry /
      段落 / 空行），最后才硬切。
    · US eCFR 的 subpart body 是整段聚合、与其 section 重复，只当容器，
      不复制 body。
    · THIN（2–4 个叶子单元）仍建结构化节点；只有零结构化单元才用全文兜底。

用法：
    python scripts/build_recall_tree.py --dry-run --limit 5   # 冒烟，不写库
    python scripts/build_recall_tree.py --dry-run             # 全量演练
    python scripts/build_recall_tree.py --backup              # 备份后正式写库
    python scripts/build_recall_tree.py --check               # 校验已有树
    python scripts/build_recall_tree.py --db copy.sqlite3     # 对副本操作（推荐先验证）

退出码：0 成功；1 校验失败；2 用法/DB/schema 错误。
"""

import hashlib
import html
import json
import math
import os
import re
import sqlite3
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
SQLITE_DIR = os.path.join(PROJECT, "sqlite")
DB_PATH = os.path.join(SQLITE_DIR, "regulations.sqlite3")
DEFAULT_REPORT = os.path.join(GO_RADAR_ROOT, "data", "recall_tree_report.json")

CHUNKER_VERSION = "v1"
DEFAULT_MAX_CHARS = 6000
MIN_PIECE = 400
MAX_TITLE_CHARS = 300
MIN_SUBSTANTIVE_CHARS = 40

STRUCTURED_TYPES = ("article", "annex", "section", "subpart", "appendix")
LEAF_TYPES_EU = ("article", "annex")
LEAF_TYPES_US = ("section", "appendix")
NOISE_TYPES = ("pdf_page", "n", "text_block", "auth", "source", "preamble")

_SCHEMA_SQL = [
    """CREATE TABLE IF NOT EXISTS recall_law_docs (
        law_id                    TEXT PRIMARY KEY REFERENCES laws(id),
        jurisdiction              TEXT NOT NULL,
        document_id               TEXT NOT NULL REFERENCES documents(id),
        document_kind             TEXT NOT NULL,
        document_version_date     TEXT,
        selection_role            TEXT NOT NULL,
        selection_reason          TEXT NOT NULL,
        primary_document_id       TEXT,
        consolidated_document_id  TEXT,
        primary_leaf_units        INTEGER NOT NULL DEFAULT 0,
        consolidated_leaf_units   INTEGER NOT NULL DEFAULT 0,
        selected_leaf_units       INTEGER NOT NULL DEFAULT 0,
        selected_chars            INTEGER NOT NULL DEFAULT 0,
        has_full_text             INTEGER NOT NULL DEFAULT 0,
        fallback_mode             TEXT NOT NULL DEFAULT '',
        tree_version              TEXT NOT NULL,
        selected_at               TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS recall_nodes (
        node_id         TEXT PRIMARY KEY,
        law_id          TEXT NOT NULL REFERENCES laws(id),
        document_id     TEXT NOT NULL REFERENCES documents(id),
        parent_id       TEXT REFERENCES recall_nodes(node_id) ON DELETE CASCADE,
        node_type       TEXT NOT NULL,
        unit_type       TEXT,
        unit_ordinal    INTEGER,
        chunk_index     INTEGER NOT NULL DEFAULT 0,
        chunk_total     INTEGER NOT NULL DEFAULT 1,
        chunk_label     TEXT,
        depth           INTEGER NOT NULL,
        sibling_ordinal INTEGER NOT NULL DEFAULT 0,
        path            TEXT NOT NULL,
        locator         TEXT,
        source_url      TEXT,
        heading         TEXT NOT NULL,
        heading_label   TEXT,
        heading_title   TEXT,
        body            TEXT,
        char_count      INTEGER NOT NULL DEFAULT 0,
        is_leaf         INTEGER NOT NULL DEFAULT 0,
        is_substantive  INTEGER NOT NULL DEFAULT 1,
        importance      TEXT NOT NULL DEFAULT 'normal',
        flags           TEXT NOT NULL DEFAULT '',
        tree_version    TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_recall_nodes_law ON recall_nodes(law_id, depth, sibling_ordinal)",
    "CREATE INDEX IF NOT EXISTS idx_recall_nodes_parent ON recall_nodes(parent_id, sibling_ordinal)",
    "CREATE INDEX IF NOT EXISTS idx_recall_nodes_leaf ON recall_nodes(law_id, is_leaf)",
    "CREATE INDEX IF NOT EXISTS idx_recall_nodes_unit ON recall_nodes(document_id, unit_ordinal)",
    """CREATE UNIQUE INDEX IF NOT EXISTS idx_recall_nodes_sibling
       ON recall_nodes(parent_id, sibling_ordinal) WHERE parent_id IS NOT NULL""",
    """CREATE VIRTUAL TABLE IF NOT EXISTS recall_nodes_fts USING fts5(
        node_id UNINDEXED,
        law_id  UNINDEXED,
        heading,
        body,
        tokenize = 'unicode61 remove_diacritics 0',
        prefix   = '2 3'
    )""",
    """CREATE TABLE IF NOT EXISTS recall_build_meta (
        key        TEXT PRIMARY KEY,
        value      TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
]

_DROP_SQL = [
    "DROP TABLE IF EXISTS recall_nodes_fts",
    "DROP TABLE IF EXISTS recall_nodes",
    "DROP TABLE IF EXISTS recall_law_docs",
    "DROP TABLE IF EXISTS recall_build_meta",
]

# ── 标题归一 ─────────────────────────────────────────────────────────
_ANNOTATION_RE = re.compile(
    r"^\s*\[[^\]]*(?:背景说明|非法规正文|优先级低于)[^\]]*\]\s*"
)
_AMEND_MARK_RE = re.compile(r"[▼►◄]\s*M?\d*")
_TAG_RE = re.compile(r"<[^>]+>")
_NUMBERED_PARA_RE = re.compile(r"^\d+[.)]\s")

_HEADING_PATTERNS = [
    ("article", re.compile(r"^(Article\s*\d+[a-z]?)\s*(?:[—–-]\s*)?(.*)$", re.I)),
    ("annex", re.compile(r"^(ANNEX\s*(?:[IVXLCDM]+|\d+)?)\s*(?:[—–-]\s*)?(.*)$", re.I)),
    ("section", re.compile(r"^(§§?\s*[\dA-Za-z.\-]+)\s*(.*)$")),
    ("subpart", re.compile(r"^(Subpart\s+[A-Z]+)\s*(?:[—–-]\s*)?(.*)$", re.I)),
    ("appendix", re.compile(
        r"^(Appendix\s+[A-Z0-9]+\s+to\s+Part\s+\d+[A-Za-z]?)\s*(?:[—–-]\s*)?(.*)$",
        re.I)),
    ("appendix_generic", re.compile(
        r"^(Appendix\s+to\s+Part\s+\d+[A-Za-z]?)\s*(?:[—–-]\s*)?(.*)$", re.I)),
    ("part", re.compile(r"^(PART\s+\d+[A-Za-z]?)\s*(?:[—–-]\s*)?(.*)$", re.I)),
]

_FRAGMENT_TITLE_PATTERNS = [
    re.compile(r"<STI\.ART[^>]*>(.*?)</STI\.ART>", re.I | re.S),
    re.compile(r"<STI\.SECTION[^>]*>(.*?)</STI\.SECTION>", re.I | re.S),
    re.compile(r'class="eli-title"[^>]*>(.*?)</', re.I | re.S),
    re.compile(r'class="stitle-article-norm"[^>]*>(.*?)</', re.I | re.S),
    re.compile(r'class="oj-ti-art"[^>]*>(.*?)</', re.I | re.S),
    re.compile(r'class="title-annex-[12]"[^>]*>(.*?)</', re.I | re.S),
    re.compile(r'class="oj-ti-grseq-1"[^>]*>(.*?)</', re.I | re.S),
    re.compile(r'<HEAD>(.*?)</HEAD>', re.I | re.S),
]

# ── 分块锚点 ─────────────────────────────────────────────────────────
STRATEGY_REGEX = {
    "clp_index": re.compile(r"(?m)^[ \t]*(\d{3}-\d{3}-\d{2}-[0-9X])\b"),
    "annex_entry": re.compile(r"(?m)^[ \t]*(\d{1,3})\.\s+"),
    "us_para_top": re.compile(r"(?m)^[ \t]*\(([a-z]{1,2})\)\s+"),
    "us_para_numbered": re.compile(r"(?m)^[ \t]*\((\d{1,3})\)\s+"),
    "eu_para": re.compile(r"(?m)^[ \t]*\(?\d{1,3}[.)]\s+"),
    "eu_heading": re.compile(r"(?m)^[ \t]*(?:PART|Part|SECTION|Section)\s+[A-Z0-9]"),
    "us_heading": re.compile(r"(?m)^[ \t]*(?:Subpart|SUBPART|Table|TABLE)\s+[A-Z0-9]"),
    "heading": re.compile(
        r"(?m)^[ \t]*(?:PART|Part|SECTION|Section|Subpart|SUBPART|Table|TABLE)\s+[A-Z0-9]"),
}


def normalize_ws(text):
    """换行/NBSP/行尾空白/连续空行归一。"""
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text.strip()


def strip_annotations(text):
    return _ANNOTATION_RE.sub("", text or "").strip()


def strip_amendment_markers(text):
    text = _AMEND_MARK_RE.sub(" ", text or "")
    text = re.sub(r"\s*[—–-]\s*$", "", text)
    return re.sub(r"\s+", " ", text).strip()


def split_heading(raw):
    """返回 (label, title)。识别 Article/ANNEX/§/Subpart/Appendix/PART。"""
    text = re.sub(r"\s+", " ", (raw or "")).strip()
    if not text:
        return None, ""
    # "ANNEX — ANNEX II" -> 内层 ANNEX II 才是真正 label
    m = re.match(r"^(ANNEX)\s*[—–-]\s*(ANNEX\s+[IVXLCDM\d]+)\s*(.*)$", text, re.I)
    if m:
        return re.sub(r"\s+", " ", m.group(2)), m.group(3).strip()
    for _kind, pat in _HEADING_PATTERNS:
        m = pat.match(text)
        if not m:
            continue
        label = re.sub(r"\s+", " ", m.group(1)).strip()
        title = (m.group(2) or "").strip()
        # 去掉 label 和 title 之间残留的破折号
        title = re.sub(r"^[—–-]\s*", "", title).strip()
        return label, title
    return None, text


def title_from_body(body, label):
    """从 body 前几行推导标题；跳过 label 行、修订标记行、编号段落。"""
    lines = [l.strip() for l in normalize_ws(body).split("\n") if l.strip()]
    if not lines:
        return ""
    start = 0
    first_word = (label or "").split()[0].lower() if label else ""
    if first_word and lines[0].lower().startswith(first_word):
        start = 1
    while start < len(lines) and len(lines[start]) < 30 and _AMEND_MARK_RE.search(lines[start]):
        start += 1
    for line in lines[start:start + 4]:
        if _NUMBERED_PARA_RE.match(line):
            continue
        if len(line) < 30 and _AMEND_MARK_RE.search(line):
            continue
        if 3 <= len(line) <= MAX_TITLE_CHARS:
            return line
    return ""


def title_from_fragment(fragment):
    """从源 HTML/XML 片段里取原生标题；失败返回空字符串。"""
    if not fragment:
        return ""
    for pat in _FRAGMENT_TITLE_PATTERNS:
        m = pat.search(fragment)
        if not m:
            continue
        text = _TAG_RE.sub(" ", m.group(1))
        text = html.unescape(text)
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            return text
    return ""


def normalize_heading(raw, body, unit_type, locator, fragment=""):
    """返回 dict(label,title,heading,flags)。heading 永不为空。"""
    flags = []
    cleaned = strip_amendment_markers(strip_annotations(normalize_ws(raw)))
    label, title = split_heading(cleaned)
    if not title:
        t = title_from_body(body, label)
        if t:
            title = t
            flags.append("title_from_body")
        elif fragment:
            t = title_from_fragment(fragment)
            if t:
                title = t
                flags.append("title_from_fragment")
    if title and len(title) > MAX_TITLE_CHARS:
        title = title[:MAX_TITLE_CHARS].rsplit(" ", 1)[0].strip()
        flags.append("title_truncated")
    if label and title:
        heading = "%s — %s" % (label, title)
    elif label:
        heading = label
        flags.append("label_only")
    elif title:
        heading = title
    else:
        heading = ("%s %s" % (unit_type or "unit", locator or "")).strip()
        flags.append("heading_fallback")
    return {
        "label": label,
        "title": title or None,
        "heading": heading,
        "flags": flags,
    }


def is_reserved(heading, body):
    """US [Reserved] 占位条款/子部分。"""
    h = (heading or "").lower()
    b = normalize_ws(body).lower()
    return "[reserved]" in h or ("[reserved]" in b and len(b) <= 80)


def truncate(text, n):
    return text if len(text) <= n else text[:n]


# ── DB 读取 ──────────────────────────────────────────────────────────
def connect(path=DB_PATH):
    con = sqlite3.connect(path)
    con.text_factory = str
    return con


def table_exists(con, name):
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name=?",
        (name,),
    ).fetchone() is not None


def load_laws(con):
    rows = con.execute(
        "SELECT id, jurisdiction, official_title, in_force, effective_status_detail "
        "FROM laws ORDER BY id"
    ).fetchall()
    out = []
    for r in rows:
        out.append({
            "law_id": r[0],
            "jurisdiction": r[1],
            "official_title": r[2] or r[0],
            "in_force": r[3],
            "effective_status_detail": r[4],
        })
    return out


def find_role_document(con, law_id, role):
    row = con.execute(
        """SELECT ld.document_id, d.kind, d.version_date, d.source_url,
                  COALESCE(LENGTH(d.full_text), 0)
           FROM law_documents ld JOIN documents d ON d.id = ld.document_id
           WHERE ld.law_id=? AND ld.role=?
           ORDER BY COALESCE(d.version_date, '') DESC
           LIMIT 1""",
        (law_id, role),
    ).fetchone()
    if not row:
        return None
    return {
        "document_id": row[0],
        "kind": row[1],
        "version_date": row[2],
        "source_url": row[3],
        "full_text_len": row[4],
    }


def doc_metrics(con, document_id, jurisdiction):
    types = LEAF_TYPES_EU if jurisdiction == "EU" else LEAF_TYPES_US
    ph = ",".join("?" for _ in types)
    n, chars = con.execute(
        "SELECT COUNT(*), COALESCE(SUM(LENGTH(body)), 0) FROM units "
        "WHERE document_id=? AND unit_type IN (%s)" % ph,
        (document_id,) + types,
    ).fetchone()
    return {"leaf_units": n, "chars": chars}


def select_canonical_document(con, law):
    """按用户确认的规则选每法一份 canonical 文档。"""
    law_id = law["law_id"]
    jur = law["jurisdiction"]
    primary = find_role_document(con, law_id, "primary")
    consolidated = find_role_document(con, law_id, "eu_consolidated")

    reason = ""
    selected = None
    role = ""

    if jur == "US":
        selected, role, reason = primary, "primary", "us_primary"
    elif consolidated is None:
        selected, role, reason = primary, "primary", "no_consolidated"
    else:
        pm = doc_metrics(con, primary["document_id"], jur) if primary else {"leaf_units": 0, "chars": 0}
        cm = doc_metrics(con, consolidated["document_id"], jur)
        if consolidated["full_text_len"] < 500:
            selected, role, reason = primary, "primary", "consolidated_no_full_text"
        elif cm["leaf_units"] < 5:
            selected, role, reason = primary, "primary", "consolidated_below_min_units"
        elif cm["leaf_units"] < math.ceil(0.8 * max(1, pm["leaf_units"])):
            selected, role, reason = primary, "primary", "consolidated_low_coverage"
        else:
            selected, role, reason = consolidated, "eu_consolidated", "consolidated"

    if selected is None:
        # primary 缺失：退 consolidated；两者都缺则报错
        if consolidated:
            selected, role, reason = consolidated, "eu_consolidated", "consolidated_fallback_primary_missing"
        else:
            raise ValueError("法规 %s 没有 primary/consolidated 文档" % law_id)

    # 两侧都不可用时的兜底：取 full_text 更大者，再比叶子数，再按 document_id
    if reason in ("consolidated_below_min_units",) and primary is None:
        selected, role = consolidated, "eu_consolidated"
        reason = "consolidated_fallback_primary_missing"

    if role == "primary" and primary is None:
        selected, role = consolidated, "eu_consolidated"
        reason = "consolidated_fallback_primary_missing"

    sel = selected
    sm = doc_metrics(con, sel["document_id"], jur)
    if sm["leaf_units"] == 0:
        fallback_mode = "no_structured"
    elif sm["leaf_units"] < 5:
        fallback_mode = "thin_structured"
    else:
        fallback_mode = ""

    return {
        "document_id": sel["document_id"],
        "role": role,
        "reason": reason,
        "document_kind": sel["kind"],
        "document_version_date": sel["version_date"],
        "source_url": sel["source_url"],
        "has_full_text": 1 if sel["full_text_len"] > 0 else 0,
        "primary_document_id": primary["document_id"] if primary else None,
        "consolidated_document_id": consolidated["document_id"] if consolidated else None,
        "primary_leaf_units": doc_metrics(con, primary["document_id"], jur)["leaf_units"] if primary else 0,
        "consolidated_leaf_units": doc_metrics(con, consolidated["document_id"], jur)["leaf_units"] if consolidated else 0,
        "selected_leaf_units": sm["leaf_units"],
        "selected_chars": sm["chars"],
        "fallback_mode": fallback_mode,
    }


def load_units(con, document_id):
    ph = ",".join("?" for _ in STRUCTURED_TYPES)
    rows = con.execute(
        "SELECT ordinal, unit_type, heading, body, locator FROM units "
        "WHERE document_id=? AND unit_type IN (%s) ORDER BY ordinal" % ph,
        (document_id,) + STRUCTURED_TYPES,
    ).fetchall()
    return [{
        "ordinal": r[0],
        "unit_type": r[1],
        "heading": r[2] or "",
        "body": r[3] or "",
        "locator": r[4],
    } for r in rows]


def get_fragment_head(con, document_id, ordinal, limit=50000):
    row = con.execute(
        "SELECT SUBSTR(source_fragment, 1, ?) FROM units WHERE document_id=? AND ordinal=?",
        (limit, document_id, ordinal),
    ).fetchone()
    return row[0] if row and row[0] else ""


def load_full_text(con, document_id):
    row = con.execute("SELECT full_text FROM documents WHERE id=?", (document_id,)).fetchone()
    return normalize_ws(row[0]) if row and row[0] else ""


def load_largest_text_unit(con, document_id, limit=4):
    rows = con.execute(
        "SELECT body FROM units WHERE document_id=? AND unit_type IN ('rule','text_block') "
        "ORDER BY LENGTH(body) DESC LIMIT ?",
        (document_id, limit),
    ).fetchall()
    return "\n\n".join(r[0] for r in rows if r[0]).strip()


# ── 分块 ────────────────────────────────────────────────────────────
def strategy_order(law_id, unit_type, heading, locator):
    h = (heading or "").upper()
    if law_id == "EU:32008R1272" and h.startswith("ANNEX VI"):
        return ["clp_index", "eu_para", "block", "hard"]
    if law_id == "EU:32006R1907" and h.startswith("ANNEX XVII"):
        return ["annex_entry", "eu_para", "block", "hard"]
    if unit_type == "annex":
        return ["annex_entry", "clp_index", "eu_para", "eu_heading", "block", "hard"]
    if unit_type == "section":
        return ["us_para_top", "us_para_numbered", "us_heading", "block", "hard"]
    if unit_type == "article":
        return ["eu_para", "eu_heading", "block", "hard"]
    if unit_type == "appendix":
        return ["us_para_top", "us_para_numbered", "block", "hard"]
    return ["eu_para", "us_para_top", "us_para_numbered", "heading", "block", "hard"]


def _valid_entry_sequence(nums):
    if len(nums) < 2:
        return False
    ints = []
    for n in nums:
        try:
            ints.append(int(n))
        except (TypeError, ValueError):
            return False
    inc = sum(1 for a, b in zip(ints, ints[1:]) if b > a)
    return inc >= max(1, int(0.6 * (len(ints) - 1)))


def split_at_boundaries(text, strategy):
    """按锚点切块；返回 [{label,text}]，prefix 作为第一块。"""
    if strategy not in STRATEGY_REGEX:
        return []
    pat = STRATEGY_REGEX[strategy]
    matches = list(pat.finditer(text))
    if len(matches) < 2:
        return []
    labels = [m.group(1) if m.lastindex else None for m in matches]
    if strategy == "annex_entry" and not _valid_entry_sequence(labels):
        return []
    pieces = []
    if matches[0].start() > 0:
        prefix = text[:matches[0].start()].strip()
        if prefix:
            pieces.append({"label": "intro", "text": prefix})
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        piece = text[m.start():end].strip()
        if piece:
            pieces.append({"label": labels[i], "text": piece})
    return pieces


def pack_pieces(pieces, max_chars):
    """贪心打包；尾块过小并入前块。"""
    chunks = []
    cur = []
    cur_len = 0
    for piece in pieces:
        text = piece["text"]
        joiner = 2 if cur else 0
        if cur and cur_len + joiner + len(text) > max_chars:
            chunks.append({"text": "\n\n".join(p["text"] for p in cur),
                           "label": _range_label(cur)})
            cur, cur_len = [], 0
        cur.append(piece)
        cur_len += (2 if len(cur) > 1 else 0) + len(text)
    if cur:
        chunks.append({"text": "\n\n".join(p["text"] for p in cur),
                       "label": _range_label(cur)})
    # 尾块过小，尝试并入前块
    if len(chunks) >= 2 and len(chunks[-1]["text"]) < MIN_PIECE:
        merged = chunks[-2]["text"] + "\n\n" + chunks[-1]["text"]
        if len(merged) <= max_chars:
            chunks[-2]["text"] = merged
            chunks.pop()
    return chunks


def _range_label(pieces):
    labels = [p.get("label") for p in pieces if p.get("label") and p.get("label") != "intro"]
    if not labels:
        return None
    if labels[0] == labels[-1]:
        return labels[0]
    return "%s-%s" % (labels[0], labels[-1])


def _loong_chunk_text(text, max_chars, overlap):
    """段落/句子/逗号切分 + 尾部重叠。

    复用 Loong Lab `backend/services/chunk_service.py:2042` 的 chunk_text() 算法：
    先按空行分段落，单段超限按句末标点切，句子仍超限按逗号切，块间保留
    overlap 字符的尾部段落。原函数模块级 import 了 jieba，不能跨仓库直接
    import；这里只保留纯文本切分部分，并补了最终 max_chars 硬上限保护。
    """
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks = []
    current = []
    current_len = 0

    def _flush():
        nonlocal current, current_len
        if not current:
            return
        chunks.append("\n\n".join(current))
        keep = []
        keep_len = 0
        for p in reversed(current):
            plen = len(p) + 2
            if keep_len + plen > overlap and keep:
                break
            keep.insert(0, p)
            keep_len += plen
        current = keep
        current_len = sum(len(p) + 2 for p in current)

    for para in paragraphs:
        plen = len(para) + 2
        if plen > max_chars:
            _flush()
            for sent in re.split(r"(?<=[。！？.!?])", para):
                sent = sent.strip()
                if not sent:
                    continue
                if len(sent) + 2 > max_chars:
                    for part in re.split(r"(?<=[，,])", sent):
                        part = part.strip()
                        if not part:
                            continue
                        if current_len + len(part) + 2 > max_chars and current:
                            _flush()
                        current.append(part)
                        current_len += len(part) + 2
                else:
                    if current_len + len(sent) + 2 > max_chars and current:
                        _flush()
                    current.append(sent)
                    current_len += len(sent) + 2
            continue

        if current_len + plen > max_chars and current:
            _flush()
        current.append(para)
        current_len += plen

    _flush()
    out = chunks or [text]
    # 最终硬上限：正常路径不会触发，防御超长无标点文本
    capped = []
    for c in out:
        if len(c) <= max_chars:
            capped.append(c)
        else:
            for i in range(0, len(c), max_chars):
                piece = c[i:i + max_chars].strip()
                if piece:
                    capped.append(piece)
    return capped


def _pack_blocks(text, max_chars):
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    if not blocks:
        return []
    pieces = [{"label": None, "text": b} for b in blocks]
    return pack_pieces(pieces, max_chars)


def chunk_text(text, law_id, unit_type, heading, locator, max_chars):
    """返回 [{text,label,strategy}]。"""
    text = normalize_ws(text)
    if len(text) <= max_chars:
        return [{"text": text, "label": None, "strategy": "none"}]
    strategies = strategy_order(law_id, unit_type, heading, locator)
    for i, strategy in enumerate(strategies):
        if strategy in ("block", "hard"):
            continue
        pieces = split_at_boundaries(text, strategy)
        if len(pieces) < 2:
            continue
        ok = True
        expanded = []
        for piece in pieces:
            if len(piece["text"]) <= max_chars:
                expanded.append(piece)
                continue
            sub = chunk_text(
                piece["text"], law_id, unit_type, heading, locator, max_chars
            )
            if not sub or any(len(c["text"]) > max_chars for c in sub):
                ok = False
                break
            for sc in sub:
                expanded.append({"label": sc.get("label"), "text": sc["text"]})
        if not ok:
            continue
        packed = pack_pieces(expanded, max_chars)
        if packed and all(len(c["text"]) <= max_chars for c in packed):
            for c in packed:
                c["strategy"] = strategy
            return packed
    packed = _pack_blocks(text, max_chars)
    if packed and all(len(c["text"]) <= max_chars for c in packed):
        for c in packed:
            c["strategy"] = "block"
        return packed
    raw = _loong_chunk_text(text, max_chars, min(200, max_chars // 20))
    return [{"text": t, "label": None, "strategy": "hard"} for t in raw if t]


# ── 节点构造 ─────────────────────────────────────────────────────────
def make_root_id(law_id):
    return "rc|%s|root" % law_id


def make_node_id(law_id, ordinal, chunk_index=0):
    if chunk_index:
        return "rc|%s|u%s|c%s" % (law_id, ordinal, chunk_index)
    return "rc|%s|u%s" % (law_id, ordinal)


def make_full_id(law_id, chunk_index=0):
    if chunk_index:
        return "rc|%s|full|c%s" % (law_id, chunk_index)
    return "rc|%s|full" % law_id


def _node(law_id, document_id, parent_id, node_type, unit_type, unit_ordinal,
          chunk_index, chunk_total, chunk_label, depth, sibling_ordinal,
          path, locator, source_url, heading, label, title, body,
          char_count, is_leaf, is_substantive, importance, flags):
    return {
        "node_id": None,  # caller 填
        "law_id": law_id,
        "document_id": document_id,
        "parent_id": parent_id,
        "node_type": node_type,
        "unit_type": unit_type,
        "unit_ordinal": unit_ordinal,
        "chunk_index": chunk_index,
        "chunk_total": chunk_total,
        "chunk_label": chunk_label,
        "depth": depth,
        "sibling_ordinal": sibling_ordinal,
        "path": path,
        "locator": locator,
        "source_url": source_url,
        "heading": heading,
        "heading_label": label,
        "heading_title": title,
        "body": body,
        "char_count": char_count,
        "is_leaf": is_leaf,
        "is_substantive": is_substantive,
        "importance": importance,
        "flags": flags,
        "tree_version": "",
    }


def build_root_node(law, selection):
    heading = law["official_title"] or law["law_id"]
    n = _node(
        law_id=law["law_id"],
        document_id=selection["document_id"],
        parent_id=None,
        node_type="law",
        unit_type=None,
        unit_ordinal=None,
        chunk_index=0,
        chunk_total=1,
        chunk_label=None,
        depth=0,
        sibling_ordinal=0,
        path=law["law_id"],
        locator=selection["source_url"],
        source_url=selection["source_url"],
        heading=heading,
        label=None,
        title=heading,
        body=None,
        char_count=0,
        is_leaf=0,
        is_substantive=0,
        importance="navigation",
        flags="root",
    )
    n["node_id"] = make_root_id(law["law_id"])
    return n


def _importance_for(unit_type):
    if unit_type in ("article", "section"):
        return "high"
    return "normal"


def build_unit_node(con, law, selection, unit, parent_id, parent_path,
                    depth, sibling, max_chars, extra_flags):
    """条款/附件/附录：返回 [节点...]（可能含分块）。"""
    law_id = law["law_id"]
    doc_id = selection["document_id"]
    raw_heading = unit["heading"]
    body = normalize_ws(unit["body"])
    norm = normalize_heading(raw_heading, body, unit["unit_type"], unit["locator"])
    if not norm["title"]:
        frag = get_fragment_head(con, doc_id, unit["ordinal"])
        if frag:
            norm = normalize_heading(
                raw_heading, body, unit["unit_type"], unit["locator"], frag
            )
    flags = list(norm["flags"]) + list(extra_flags or [])
    reserved = is_reserved(norm["heading"], body)
    if reserved:
        flags.append("reserved_%s" % unit["unit_type"])
    heading = norm["heading"]
    label = norm["label"]
    title = norm["title"]
    locator = unit["locator"]
    if len(body) <= max_chars or reserved:
        n = _node(
            law_id, doc_id, parent_id, unit["unit_type"], unit["unit_type"],
            unit["ordinal"], 0, 1, None, depth, sibling,
            "%s > %s" % (parent_path, heading), locator, selection["source_url"],
            heading, label, title, body, len(body), 1,
            0 if reserved else 1,
            "context" if reserved else _importance_for(unit["unit_type"]),
            ",".join(flags),
        )
        n["node_id"] = make_node_id(law_id, unit["ordinal"], 0)
        return [n]

    # 超长：容器 + 分块
    container_id = make_node_id(law_id, unit["ordinal"], 0)
    container = _node(
        law_id, doc_id, parent_id, unit["unit_type"], unit["unit_type"],
        unit["ordinal"], 0, 1, None, depth, sibling,
        "%s > %s" % (parent_path, heading), locator, selection["source_url"],
        heading, label, title, None, len(body), 0, 0, "navigation",
        ",".join(flags + ["chunked"]),
    )
    container["node_id"] = container_id
    chunks = chunk_text(body, law_id, unit["unit_type"], heading, locator, max_chars)
    if len(chunks) <= 1:
        # 兜底：不建单子容器；若 chunk_text 做了空白归一，用归一后的文本
        leaf_text = chunks[0]["text"] if chunks else body
        n = _node(
            law_id, doc_id, parent_id, unit["unit_type"], unit["unit_type"],
            unit["ordinal"], 0, 1, None, depth, sibling,
            "%s > %s" % (parent_path, heading), locator, selection["source_url"],
            heading, label, title, leaf_text, len(leaf_text), 1, 1,
            _importance_for(unit["unit_type"]), ",".join(flags),
        )
        n["node_id"] = container_id
        return [n]
    container["chunk_total"] = len(chunks)
    out = [container]
    total = len(chunks)
    for i, ch in enumerate(chunks, 1):
        c_label = ch.get("label") or ("part %d/%d" % (i, total))
        c_flags = list(flags)
        strat = ch.get("strategy") or "block"
        c_flags.append("hard_window" if strat == "hard" else strat)
        n = _node(
            law_id, doc_id, container_id, "chunk", unit["unit_type"],
            unit["ordinal"], i, total, c_label, depth + 1, i,
            "%s > [%s]" % (container["path"], c_label),
            "%s#chunk-%d" % (locator or "", i), selection["source_url"],
            heading, label, title, ch["text"], len(ch["text"]), 1, 1,
            _importance_for(unit["unit_type"]), ",".join(c_flags + ["chunk"]),
        )
        n["node_id"] = make_node_id(law_id, unit["ordinal"], i)
        out.append(n)
    return out


def build_subpart_node(con, law, selection, unit, parent_id, max_chars):
    """US eCFR subpart：普通 subpart 只当容器；[Reserved] 建短叶子。"""
    law_id = law["law_id"]
    doc_id = selection["document_id"]
    body = normalize_ws(unit["body"])
    norm = normalize_heading(unit["heading"], body, "subpart", unit["locator"])
    flags = list(norm["flags"])
    reserved = is_reserved(norm["heading"], body)
    node_id = make_node_id(law_id, unit["ordinal"], 0)
    if reserved:
        flags.append("reserved_subpart")
        n = _node(
            law_id, doc_id, parent_id, "subpart", "subpart", unit["ordinal"],
            0, 1, None, 1, unit["ordinal"],
            "%s > %s" % (law_id, norm["heading"]), unit["locator"],
            selection["source_url"], norm["heading"], norm["label"],
            norm["title"], body, len(body), 1, 0, "context", ",".join(flags),
        )
        n["node_id"] = node_id
        return [n], None
    n = _node(
        law_id, doc_id, parent_id, "subpart", "subpart", unit["ordinal"],
        0, 1, None, 1, unit["ordinal"],
        "%s > %s" % (law_id, norm["heading"]), unit["locator"],
        selection["source_url"], norm["heading"], norm["label"],
        norm["title"], None, 0, 0, 0, "navigation",
        ",".join(flags + ["subpart_container"]),
    )
    n["node_id"] = node_id
    return [n], node_id


def build_us_nodes(con, law, selection, max_chars):
    nodes = []
    current_subpart = None
    current_subpart_path = None
    law_id = law["law_id"]
    for unit in load_units(con, selection["document_id"]):
        ut = unit["unit_type"]
        if ut == "subpart":
            sub_nodes, sid = build_subpart_node(
                con, law, selection, unit, make_root_id(law_id), max_chars
            )
            nodes.extend(sub_nodes)
            current_subpart = sid
            current_subpart_path = sub_nodes[0]["path"] if sid else None
        elif ut == "section":
            parent = current_subpart or make_root_id(law_id)
            parent_path = current_subpart_path or law_id
            depth = 2 if current_subpart else 1
            nodes.extend(build_unit_node(
                con, law, selection, unit, parent, parent_path, depth,
                unit["ordinal"], max_chars, [],
            ))
        elif ut == "appendix":
            low = (unit["heading"] or "").lower()
            if "to subpart" in low and current_subpart:
                parent, parent_path, depth = current_subpart, current_subpart_path, 2
            else:
                parent, parent_path, depth = make_root_id(law_id), law_id, 1
            nodes.extend(build_unit_node(
                con, law, selection, unit, parent, parent_path, depth,
                unit["ordinal"], max_chars, [],
            ))
    return nodes


def build_eu_nodes(con, law, selection, max_chars):
    nodes = []
    for unit in load_units(con, selection["document_id"]):
        if unit["unit_type"] not in ("article", "annex", "appendix"):
            continue
        nodes.extend(build_unit_node(
            con, law, selection, unit, make_root_id(law["law_id"]),
            law["law_id"], 1, unit["ordinal"], max_chars, [],
        ))
    return nodes


def build_fulltext_nodes(con, law, selection, max_chars):
    text = load_full_text(con, selection["document_id"])
    if not text:
        text = load_largest_text_unit(con, selection["document_id"])
    if not text:
        text = law["official_title"] or law["law_id"]
        extra = ["no_text_available"]
    else:
        extra = []
    norm = normalize_heading(law["official_title"], text, "rule", selection["source_url"])
    root_id = make_root_id(law["law_id"])
    heading = norm["heading"] + " [full text]"
    chunks = chunk_text(text, law["law_id"], "rule", heading,
                        selection["source_url"], max_chars)
    flags = list(norm["flags"]) + ["full_text_fallback"] + extra
    if len(chunks) <= 1:
        leaf_text = chunks[0]["text"] if chunks else text
        n = _node(
            law["law_id"], selection["document_id"], root_id, "rule", None, None,
            0, 1, None, 1, 0, "%s > %s" % (law["law_id"], heading),
            selection["source_url"] + "#full-text", selection["source_url"],
            heading, norm["label"], norm["title"], leaf_text, len(leaf_text), 1, 1,
            "normal", ",".join(flags),
        )
        n["node_id"] = make_full_id(law["law_id"], 0)
        return [n]
    container_id = make_full_id(law["law_id"], 0)
    out = [_node(
        law["law_id"], selection["document_id"], root_id, "rule", None, None,
        0, 1, None, 1, 0, "%s > %s" % (law["law_id"], heading),
        selection["source_url"] + "#full-text", selection["source_url"],
        heading, norm["label"], norm["title"], None, len(text), 0, 0,
        "navigation", ",".join(flags + ["chunked"]),
    )]
    out[0]["node_id"] = container_id
    total = len(chunks)
    out[0]["chunk_total"] = total
    for i, ch in enumerate(chunks, 1):
        c_label = ch.get("label") or ("part %d/%d" % (i, total))
        n = _node(
            law["law_id"], selection["document_id"], container_id, "chunk", None,
            None, i, total, c_label, 2, i,
            "%s > [%s]" % (out[0]["path"], c_label),
            selection["source_url"] + "#full-text-chunk-%d" % i,
            selection["source_url"], heading, norm["label"], norm["title"],
            ch["text"], len(ch["text"]), 1, 1, "normal",
            ",".join(flags + ["chunk",
                              "hard_window" if ch.get("strategy") == "hard"
                              else ch.get("strategy", "block")]),
        )
        n["node_id"] = make_full_id(law["law_id"], i)
        out.append(n)
    return out


def build_law_plan(con, law, max_chars):
    selection = select_canonical_document(con, law)
    root = build_root_node(law, selection)
    if selection["selected_leaf_units"] == 0:
        children = build_fulltext_nodes(con, law, selection, max_chars)
    elif law["jurisdiction"] == "US":
        children = build_us_nodes(con, law, selection, max_chars)
    else:
        children = build_eu_nodes(con, law, selection, max_chars)

    if 0 < selection["selected_leaf_units"] < 5:
        for n in children:
            n["flags"] = (n["flags"] + ",thin").strip(",")

    law_doc = {
        "law_id": law["law_id"],
        "jurisdiction": law["jurisdiction"],
        "document_id": selection["document_id"],
        "document_kind": selection["document_kind"],
        "document_version_date": selection["document_version_date"],
        "selection_role": selection["role"],
        "selection_reason": selection["reason"],
        "primary_document_id": selection["primary_document_id"],
        "consolidated_document_id": selection["consolidated_document_id"],
        "primary_leaf_units": selection["primary_leaf_units"],
        "consolidated_leaf_units": selection["consolidated_leaf_units"],
        "selected_leaf_units": selection["selected_leaf_units"],
        "selected_chars": selection["selected_chars"],
        "has_full_text": selection["has_full_text"],
        "fallback_mode": selection["fallback_mode"],
        "tree_version": "",
        "selected_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    return law_doc, [root] + children


def compute_tree_version(nodes, max_chars):
    payload = {
        "chunker_version": CHUNKER_VERSION,
        "max_chars": max_chars,
        "nodes": sorted(
            (n["node_id"], n["heading"], len(n["body"] or ""), n["is_leaf"],
             n["is_substantive"], n["importance"], n["flags"])
            for n in nodes
        ),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return "rt1-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def build_plan(con, max_chars, limit=None):
    laws = load_laws(con)
    if limit:
        laws = laws[:limit]
    law_docs, nodes = [], []
    for law in laws:
        law_doc, law_nodes = build_law_plan(con, law, max_chars)
        law_docs.append(law_doc)
        nodes.extend(law_nodes)
    version = compute_tree_version(nodes, max_chars)
    for n in nodes:
        n["tree_version"] = version
    for ld in law_docs:
        ld["tree_version"] = version
    plan = {
        "laws": laws,
        "law_docs": law_docs,
        "nodes": nodes,
        "tree_version": version,
        "max_chars": max_chars,
        "partial": bool(limit and limit < len(load_laws(con))),
    }
    plan["stats"] = plan_stats(plan)
    plan["validation"] = validate_plan(plan)
    return plan


# ── 统计/校验 ────────────────────────────────────────────────────────
def _flag_count(nodes, flag):
    return sum(1 for n in nodes if flag in (n["flags"] or "").split(","))


def plan_stats(plan):
    nodes = plan["nodes"]
    law_docs = plan["law_docs"]
    reasons = {}
    for ld in law_docs:
        reasons[ld["selection_reason"]] = reasons.get(ld["selection_reason"], 0) + 1
    strategies = {}
    for n in nodes:
        for f in (n["flags"] or "").split(","):
            if f in ("clp_index", "annex_entry", "us_para_top",
                     "us_para_numbered", "eu_para", "eu_heading",
                     "us_heading", "block", "hard_window", "none"):
                strategies[f] = strategies.get(f, 0) + 1
    return {
        "laws": len(law_docs),
        "roots": sum(1 for n in nodes if n["node_type"] == "law"),
        "nodes": len(nodes),
        "containers": sum(1 for n in nodes if not n["is_leaf"]),
        "leaves": sum(1 for n in nodes if n["is_leaf"]),
        "chunk_nodes": sum(1 for n in nodes if n["node_type"] == "chunk"),
        "source_leaf_units": sum(ld["selected_leaf_units"] for ld in law_docs),
        "source_leaf_chars": sum(ld["selected_chars"] for ld in law_docs),
        "selection_reasons": reasons,
        "thin_laws": sum(1 for ld in law_docs if ld["fallback_mode"] == "thin_structured"),
        "no_structured_laws": sum(1 for ld in law_docs if ld["fallback_mode"] == "no_structured"),
        "label_only": _flag_count(nodes, "label_only"),
        "title_enriched": _flag_count(nodes, "title_from_body") + _flag_count(nodes, "title_from_fragment"),
        "reserved": sum(
            1 for n in nodes
            if any(f.startswith("reserved_") for f in (n["flags"] or "").split(","))
        ),
        "chunk_strategies": strategies,
        "max_leaf_chars": max([n["char_count"] for n in nodes if n["is_leaf"]] or [0]),
    }


def validate_plan(plan):
    errors, warnings = [], []
    nodes = plan["nodes"]
    by_id = {}
    roots = {}
    for n in nodes:
        if n["node_id"] in by_id:
            errors.append("重复 node_id: %s" % n["node_id"])
        by_id[n["node_id"]] = n
        if n["node_type"] == "law":
            roots.setdefault(n["law_id"], []).append(n)
    for law_id, rs in roots.items():
        if len(rs) != 1:
            errors.append("%s 根节点数=%d" % (law_id, len(rs)))
    for ld in plan["law_docs"]:
        if ld["law_id"] not in roots:
            errors.append("%s 缺少 law 根节点" % ld["law_id"])

    for n in nodes:
        if not (n["heading"] or "").strip():
            errors.append("%s heading 为空" % n["node_id"])
        if n["is_leaf"] and not (n["body"] or "").strip():
            errors.append("%s 叶子 body 为空" % n["node_id"])
        if not n["is_leaf"] and n["body"] is not None:
            errors.append("%s 容器 body 非空" % n["node_id"])
        if n["is_leaf"] and n["char_count"] != len(n["body"] or ""):
            errors.append("%s char_count 不一致" % n["node_id"])
        if n["is_leaf"] and n["char_count"] > plan["max_chars"] \
                and "oversized_exception" not in (n["flags"] or ""):
            errors.append("%s 超过 max_chars=%d" % (n["node_id"], plan["max_chars"]))
        if n["parent_id"]:
            p = by_id.get(n["parent_id"])
            if not p:
                errors.append("%s 父节点不存在" % n["node_id"])
            elif p["law_id"] != n["law_id"]:
                errors.append("%s 跨 law 父节点" % n["node_id"])
            elif n["depth"] != p["depth"] + 1:
                errors.append("%s depth 不一致" % n["node_id"])
    # 每法至少一个 substantive 叶子
    for ld in plan["law_docs"]:
        leaves = [n for n in nodes if n["law_id"] == ld["law_id"]
                  and n["is_leaf"] and n["is_substantive"]]
        if not any(n["char_count"] >= MIN_SUBSTANTIVE_CHARS for n in leaves):
            errors.append("%s 没有 substantive 叶子" % ld["law_id"])
    # 分块父子一致性
    children = {}
    for n in nodes:
        if n["parent_id"]:
            children.setdefault(n["parent_id"], []).append(n)
    for n in nodes:
        if not n["is_leaf"] and n["node_type"] == "chunk":
            errors.append("%s chunk 节点不应是容器" % n["node_id"])
        kids = children.get(n["node_id"], [])
        if not n["is_leaf"] and not kids:
            errors.append("%s 空容器" % n["node_id"])
        if n["chunk_index"] > 0:
            if n["chunk_total"] < 1 or n["chunk_index"] > n["chunk_total"]:
                errors.append("%s chunk_index 越界" % n["node_id"])
        if n["chunk_index"] == 0 and kids:
            if any(k["node_type"] == "chunk" for k in kids):
                if len([k for k in kids if k["node_type"] == "chunk"]) != n["chunk_total"]:
                    errors.append("%s chunk_total 不一致" % n["node_id"])
    versions = {n["tree_version"] for n in nodes}
    if len(versions) > 1:
        errors.append("tree_version 不唯一: %s" % versions)
    # warnings
    if plan["stats"]["label_only"]:
        warnings.append("label_only 节点 %d 个" % plan["stats"]["label_only"])
    if plan["stats"]["thin_laws"]:
        warnings.append("THIN 法规 %d 条（已保留结构化节点）" % plan["stats"]["thin_laws"])
    return {"errors": errors, "warnings": warnings}


def validate_db(con, max_chars, expected_laws=None):
    errors, warnings = [], []
    if not table_exists(con, "recall_nodes"):
        return {"errors": ["recall_nodes 不存在"], "warnings": []}
    node_count = con.execute("SELECT COUNT(*) FROM recall_nodes").fetchone()[0]
    if node_count == 0:
        errors.append("recall_nodes 为空")
    fts_count = con.execute("SELECT COUNT(*) FROM recall_nodes_fts").fetchone()[0]
    if fts_count != node_count:
        errors.append("FTS 行数 %d != 节点数 %d" % (fts_count, node_count))
    checks = [
        ("空 heading", "SELECT COUNT(*) FROM recall_nodes WHERE heading IS NULL OR TRIM(heading)=''"),
        ("容器 body 非空", "SELECT COUNT(*) FROM recall_nodes WHERE is_leaf=0 AND body IS NOT NULL"),
        ("叶子 body 为空", "SELECT COUNT(*) FROM recall_nodes WHERE is_leaf=1 AND (body IS NULL OR TRIM(body)='')"),
        ("char_count 不一致", "SELECT COUNT(*) FROM recall_nodes WHERE is_leaf=1 AND char_count != LENGTH(body)"),
        ("超 max_chars", "SELECT COUNT(*) FROM recall_nodes WHERE is_leaf=1 AND char_count > %d AND flags NOT LIKE '%%oversized_exception%%'" % max_chars),
        ("孤儿父节点", """SELECT COUNT(*) FROM recall_nodes n LEFT JOIN recall_nodes p
                           ON n.parent_id=p.node_id WHERE n.parent_id IS NOT NULL AND p.node_id IS NULL"""),
        ("跨 law 父节点", """SELECT COUNT(*) FROM recall_nodes n JOIN recall_nodes p
                           ON n.parent_id=p.node_id WHERE n.law_id != p.law_id"""),
        ("depth 不一致", """SELECT COUNT(*) FROM recall_nodes n JOIN recall_nodes p
                           ON n.parent_id=p.node_id WHERE n.depth != p.depth+1"""),
        ("空容器", """SELECT COUNT(*) FROM recall_nodes n WHERE n.is_leaf=0
                     AND NOT EXISTS (SELECT 1 FROM recall_nodes c WHERE c.parent_id=n.node_id)"""),
        ("源 unit 缺失", """SELECT COUNT(*) FROM recall_nodes n WHERE n.unit_ordinal IS NOT NULL
                           AND NOT EXISTS (SELECT 1 FROM units u WHERE u.document_id=n.document_id
                                           AND u.ordinal=n.unit_ordinal)"""),
    ]
    for label, sql in checks:
        cnt = con.execute(sql).fetchone()[0]
        if cnt:
            errors.append("%s: %d" % (label, cnt))
    distinct_versions = con.execute("SELECT COUNT(DISTINCT tree_version) FROM recall_nodes").fetchone()[0]
    if distinct_versions != 1:
        errors.append("tree_version 种类=%d" % distinct_versions)
    law_docs = con.execute("SELECT COUNT(*) FROM recall_law_docs").fetchone()[0]
    if expected_laws is not None and law_docs != expected_laws:
        errors.append("recall_law_docs=%d != 法规数=%d" % (law_docs, expected_laws))
    missing_roots = con.execute(
        """SELECT COUNT(*) FROM recall_law_docs ld WHERE NOT EXISTS
           (SELECT 1 FROM recall_nodes n WHERE n.law_id=ld.law_id AND n.node_type='law')"""
    ).fetchone()[0]
    if missing_roots:
        errors.append("缺少 law 根: %d" % missing_roots)
    # 每法至少一个 substantive 叶子
    thin = con.execute(
        """SELECT COUNT(*) FROM recall_law_docs ld WHERE NOT EXISTS
           (SELECT 1 FROM recall_nodes n WHERE n.law_id=ld.law_id AND n.is_leaf=1
            AND n.is_substantive=1 AND n.char_count>=%d)""" % MIN_SUBSTANTIVE_CHARS
    ).fetchone()[0]
    if thin:
        errors.append("没有 substantive 叶子的法规: %d" % thin)
    try:
        fk = con.execute("PRAGMA foreign_key_check(recall_nodes)").fetchall()
        if fk:
            errors.append("foreign_key_check 非空: %d 行" % len(fk))
    except Exception:
        pass
    return {"errors": errors, "warnings": warnings}


# ── 写库 / 报告 ──────────────────────────────────────────────────────
def make_backup(con, db_path):
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dst_path = "%s.bak-recall-%s" % (db_path, stamp)
    dst = sqlite3.connect(dst_path)
    try:
        con.backup(dst)
    finally:
        dst.close()
    return dst_path


def write_plan(con, plan, source_db=None):
    con.execute("BEGIN IMMEDIATE")
    try:
        for sql in _DROP_SQL:
            con.execute(sql)
        for sql in _SCHEMA_SQL:
            con.execute(sql)
        con.executemany(
            """INSERT INTO recall_law_docs
               (law_id, jurisdiction, document_id, document_kind, document_version_date,
                selection_role, selection_reason, primary_document_id,
                consolidated_document_id, primary_leaf_units, consolidated_leaf_units,
                selected_leaf_units, selected_chars, has_full_text, fallback_mode,
                tree_version, selected_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [(
                ld["law_id"], ld["jurisdiction"], ld["document_id"], ld["document_kind"],
                ld["document_version_date"], ld["selection_role"], ld["selection_reason"],
                ld["primary_document_id"], ld["consolidated_document_id"],
                ld["primary_leaf_units"], ld["consolidated_leaf_units"],
                ld["selected_leaf_units"], ld["selected_chars"], ld["has_full_text"],
                ld["fallback_mode"], ld["tree_version"], ld["selected_at"],
            ) for ld in plan["law_docs"]],
        )
        cols = ("node_id, law_id, document_id, parent_id, node_type, unit_type, "
                "unit_ordinal, chunk_index, chunk_total, chunk_label, depth, "
                "sibling_ordinal, path, locator, source_url, heading, "
                "heading_label, heading_title, body, char_count, is_leaf, "
                "is_substantive, importance, flags, tree_version")
        rows = [(
            n["node_id"], n["law_id"], n["document_id"], n["parent_id"], n["node_type"],
            n["unit_type"], n["unit_ordinal"], n["chunk_index"], n["chunk_total"],
            n["chunk_label"], n["depth"], n["sibling_ordinal"], n["path"], n["locator"],
            n["source_url"], n["heading"], n["heading_label"], n["heading_title"],
            n["body"], n["char_count"], n["is_leaf"], n["is_substantive"],
            n["importance"], n["flags"], n["tree_version"],
        ) for n in sorted(plan["nodes"], key=lambda x: (x["depth"], x["law_id"],
                                                        x["sibling_ordinal"], x["chunk_index"]))]
        con.executemany(
            "INSERT INTO recall_nodes (%s) VALUES (%s)" % (cols, ",".join("?" * 25)),
            rows,
        )
        con.execute(
            """INSERT INTO recall_nodes_fts (node_id, law_id, heading, body)
               SELECT node_id, law_id, heading, COALESCE(body,'') FROM recall_nodes"""
        )
        meta = {
            "tree_version": plan["tree_version"],
            "chunker_version": CHUNKER_VERSION,
            "max_chars": str(plan["max_chars"]),
            "built_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source_db": source_db or DB_PATH,
            "partial": "1" if plan.get("partial") else "0",
            "node_count": str(plan["stats"]["nodes"]),
            "leaf_count": str(plan["stats"]["leaves"]),
            "fts_count": str(plan["stats"]["nodes"]),
            "validation_ok": "0" if plan["validation"]["errors"] else "1",
        }
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        con.executemany(
            "INSERT INTO recall_build_meta (key, value, updated_at) VALUES (?,?,?)",
            [(k, v, now) for k, v in meta.items()],
        )
        result = validate_db(con, plan["max_chars"], len(plan["law_docs"]))
        if result["errors"]:
            con.rollback()
            return result
        con.commit()
        return result
    except Exception:
        con.rollback()
        raise


def write_report(plan, path):
    report = {
        "tree_version": plan["tree_version"],
        "max_chars": plan["max_chars"],
        "partial": plan.get("partial", False),
        "stats": plan["stats"],
        "validation": plan["validation"],
        "laws": [{
            "law_id": ld["law_id"],
            "jurisdiction": ld["jurisdiction"],
            "document_id": ld["document_id"],
            "document_kind": ld["document_kind"],
            "selection_role": ld["selection_role"],
            "selection_reason": ld["selection_reason"],
            "selected_leaf_units": ld["selected_leaf_units"],
            "selected_chars": ld["selected_chars"],
            "fallback_mode": ld["fallback_mode"],
        } for ld in plan["law_docs"]],
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)


def print_summary(plan, title):
    st = plan["stats"]
    print("=" * 66)
    print("  %s" % title)
    print("=" * 66)
    print("  法规数：%d　canonical：%s" % (
        st["laws"], ", ".join("%s=%d" % (k, v) for k, v in sorted(st["selection_reasons"].items()))))
    print("  源叶子单元：%d（%s 字符）" % (st["source_leaf_units"], format(st["source_leaf_chars"], ",")))
    print("  节点：%d（容器 %d / 叶子 %d / 分块 %d）" % (
        st["nodes"], st["containers"], st["leaves"], st["chunk_nodes"]))
    print("  heading：label_only=%d　补标题=%d　reserved=%d" % (
        st["label_only"], st["title_enriched"], st["reserved"]))
    print("  THIN 法规：%d　无结构化：%d　最大叶子：%d 字符" % (
        st["thin_laws"], st["no_structured_laws"], st["max_leaf_chars"]))
    print("  tree_version：%s" % plan["tree_version"])
    if plan["validation"]["errors"]:
        print("  校验：FAIL（%d 项）" % len(plan["validation"]["errors"]))
        for e in plan["validation"]["errors"][:20]:
            print("    ✗ %s" % e)
    else:
        print("  校验：OK")
    if plan["validation"]["warnings"]:
        for w in plan["validation"]["warnings"][:10]:
            print("    ⚠ %s" % w)
    print("=" * 66)


# ── CLI ─────────────────────────────────────────────────────────────
def _arg_value(name, default=None):
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


def main():
    dry_run = "--dry-run" in sys.argv
    check = "--check" in sys.argv
    backup = "--backup" in sys.argv
    no_quick_check = "--no-quick-check" in sys.argv
    limit = None
    if "--limit" in sys.argv:
        try:
            limit = int(_arg_value("--limit"))
        except (TypeError, ValueError):
            print("错误：--limit 需要整数", file=sys.stderr)
            return 2
        if limit <= 0:
            print("错误：--limit 必须 > 0", file=sys.stderr)
            return 2
        if not dry_run:
            print("错误：--limit 只允许与 --dry-run 同用；正式写库必须全量", file=sys.stderr)
            return 2
    try:
        max_chars = int(_arg_value("--max-chars", str(DEFAULT_MAX_CHARS)))
    except (TypeError, ValueError):
        print("错误：--max-chars 需要整数", file=sys.stderr)
        return 2
    if max_chars < 500:
        print("错误：--max-chars 不能小于 500", file=sys.stderr)
        return 2
    report_path = _arg_value("--report", DEFAULT_REPORT)
    db_path = _arg_value("--db", DB_PATH)

    if not os.path.exists(db_path):
        print("错误：数据库不存在：%s" % db_path, file=sys.stderr)
        return 2

    con = connect(db_path)
    try:
        if check:
            result = validate_db(con, max_chars)
            print("=" * 66)
            print("  法规召回目录树 · 校验")
            print("=" * 66)
            if result["errors"]:
                for e in result["errors"]:
                    print("  ✗ %s" % e)
                print("  校验：FAIL")
                return 1
            print("  校验：OK")
            return 0

        plan = build_plan(con, max_chars, limit=limit)
        if dry_run:
            print_summary(plan, "法规召回目录树 · 演练模式（不写库）")
            return 1 if plan["validation"]["errors"] else 0

        print_summary(plan, "法规召回目录树 · 构建")
        if plan["validation"]["errors"]:
            write_report(plan, report_path)
            print("  已中止：校验失败，未写库。报告：%s" % report_path)
            return 1
        if not no_quick_check:
            ok = con.execute("PRAGMA quick_check").fetchone()[0]
            if ok != "ok":
                print("错误：quick_check 未通过：%s" % ok, file=sys.stderr)
                return 2
        if backup:
            path = make_backup(con, db_path)
            print("  备份：%s" % path)
        result = write_plan(con, plan, source_db=db_path)
        if result["errors"]:
            print("  写库后校验失败（已回滚）：")
            for e in result["errors"]:
                print("    ✗ %s" % e)
            return 1
        try:
            con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception:
            pass
        write_report(plan, report_path)
        print("  报告：%s" % report_path)
        print("  完成。")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
