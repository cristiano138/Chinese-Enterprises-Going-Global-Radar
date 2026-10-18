# -*- coding: utf-8 -*-
"""
时效性结构化字段核验（scripts/check_metadata_freshness.py）

用途：
    对 laws 表全部法规（EU + US），每次运行都重新问官方接口要当前的
    时效性字段真值，跟库内旧值逐字段比对，发现不一致就自动回写并写日志。

    这是「数据准确性与时效性监控方案.md」里判定性价比最高的第二层监控
    ——「官方修订记录接口比对」——的落地实现，替代/补充第一层的整页哈希监控。

设计铁律：
    1. 不管库内字段当前是否已有值，每次都重新查官方接口——"库里已经填过"
       不代表"以后不用再查"，字段会过期。
    2. 写入前必须过 sanitize() 校验，已知脏数据模式（占位日期、格式错误的
       编号）一律拒绝写入，只记日志，不污染 laws 表。
    3. 单条法规查询失败/被拒绝都不能让整个任务中断，退出码永远 0。
    4. 复用 fetch_eu.py / fetch_us.py 里已经写好且踩过坑的官方接口查询函数，
       不重新实现 SPARQL / eCFR 调用逻辑。

新增 laws 表列：
    fr_effective_on           US: Federal Register 官方 effective_on
    updated_at                 任一字段被本工具自动改写时，刷新为当次核验时间
    effective_status_detail   派生状态（见 compute_effective_status_detail）

输出：
    sqlite/metadata_check_log.jsonl    追加，只记变化/被拒绝的字段
    sqlite/metadata_check_latest.json  覆盖，当次运行汇总 + 过渡期预警

用法：
    python scripts/check_metadata_freshness.py --dry-run --limit 5   # 冒烟
    python scripts/check_metadata_freshness.py --dry-run              # 全量演练
    python scripts/check_metadata_freshness.py                        # 正式写库

定时（跟 check_freshness.py 一致，每天一次）：
    Windows: schtasks /create /tn "ComplianceRadar-MetadataFreshness" ^
             /tr "python <仓库>\\scripts\\check_metadata_freshness.py" /sc daily /st 09:30
    Linux:   30 9 * * * cd <仓库> && python scripts/check_metadata_freshness.py
"""

import importlib.util
import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# 本脚本所在目录就是 Chinese-Enterprises-Going-Global-Radar/scripts，
# fetch_eu.py / fetch_us.py 跟它是同目录兄弟文件，直接同目录引用。
HERE = os.path.dirname(os.path.abspath(__file__))
GO_RADAR_ROOT = os.path.dirname(HERE)  # .../Chinese-Enterprises-Going-Global-Radar
GO_RADAR_SCRIPTS = HERE

# sqlite/ 跟 Chinese-Enterprises-Going-Global-Radar/ 是兄弟目录，都在「出海合规」下。
PROJECT = os.path.dirname(GO_RADAR_ROOT)
SQLITE_DIR = os.path.join(PROJECT, "sqlite")
DB_PATH = os.path.join(SQLITE_DIR, "regulations.sqlite3")
LOG_PATH = os.path.join(SQLITE_DIR, "metadata_check_log.jsonl")
LATEST_PATH = os.path.join(SQLITE_DIR, "metadata_check_latest.json")

BJT = timezone(timedelta(hours=8))
WARN_WINDOW_DAYS = 90  # 过渡期/生效日预警窗口，可调
REQUEST_INTERVAL = 1.0

FR_API = "https://www.federalregister.gov/api/v1/documents"
_UA = "compliance-radar-metadata-freshness/1.0 (academic research)"


def now_str():
    return datetime.now(BJT).strftime("%Y-%m-%d %H:%M:%S")


# ── 复用 fetch_eu.py / fetch_us.py 里已经写好的官方接口查询函数 ──────────
def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_fetch_eu = _load_module(
    "fetch_eu", os.path.join(GO_RADAR_SCRIPTS, "fetch_eu.py")
)
_fetch_us = _load_module(
    "fetch_us", os.path.join(GO_RADAR_SCRIPTS, "fetch_us.py")
)


# ── 校验/防护层（已知脏数据模式：占位日期、格式错误的编号） ──────────────
CELEX_RE = re.compile(r"^\d[0-9]{4}[RLD]\d{4}(?:R\(\d+\))?$")
# FR 文档号格式（实测核实，不是猜测）：
#   用库内全部 791 条真实 us_fr source_identifier + laws.latest_fr_document_number
#   做过全量回归测试，覆盖以下全部历史格式，0 条漏判：
#     2026-00895（现行：4位年份-5位序号）
#     99-32676 / 00-5531（90年代末~2000年代初：2位年份-2~5位序号）
#     E7-5303（2007年前后：1位字母+1位年份数字-序号，字母含义未知但真实存在）
#     C1-2017-18463（更正公告子类型：C+序号-年份-原文档序号）
#   第一版 r"^\d{4}-\d{4,6}$" 只覆盖了"现行格式"，实测对库内 8 条真实老文档号
#   误判为"格式不符"——这些值本身跟库内旧值完全一致，根本不是脏数据，
#   是正则覆盖面不够。教训：正则必须用真实数据全量回归，不能只测几个样本。
FR_DOC_RE = re.compile(r"^(?:[A-Z]\d{1,2}-\d{4}-\d{3,6}|[A-Z]?\d{1,4}-\d{2,6})$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")

REJECTED = object()


def _parse_date_prefix(value):
    """只取日期部分（前 10 位 YYYY-MM-DD），兼容带时间戳的 ISO 字符串。"""
    m = DATE_RE.match(value or "")
    if not m:
        return None
    try:
        return datetime.strptime(m.group(0), "%Y-%m-%d")
    except ValueError:
        return None


def sanitize_date(value):
    """日期字段校验：能解析、排除已知占位值、排除离谱未来日期。"""
    if not value:
        return REJECTED, "空值"
    dt = _parse_date_prefix(value)
    if dt is None:
        return REJECTED, f"无法解析为日期：{value!r}"
    if dt.year in (1001, 9999):
        return REJECTED, f"已知占位日期：{value!r}"
    if dt.year > datetime.now().year + 10:
        return REJECTED, f"未来超过10年的离谱日期：{value!r}"
    return value, None


def sanitize_celex(value):
    if not value:
        return REJECTED, "空值"
    if not CELEX_RE.match(value):
        return REJECTED, f"CELEX 格式不符：{value!r}"
    return value, None


def sanitize_fr_doc_number(value):
    if not value:
        return REJECTED, "空值"
    if not FR_DOC_RE.match(value):
        return REJECTED, f"FR 文档号格式不符：{value!r}"
    return value, None


def sanitize_in_force(value):
    if value not in ("0", "1"):
        return REJECTED, f"in_force 只能是 0/1：{value!r}"
    return value, None


FIELD_SANITIZERS = {
    "last_modification_date": sanitize_date,
    "fr_effective_on": sanitize_date,
    "in_force": sanitize_in_force,
    "latest_amendment_celex": sanitize_celex,
    "latest_corrigendum_celex": sanitize_celex,
    "latest_fr_document_number": sanitize_fr_doc_number,
}


def sanitize(field, value):
    """返回 (clean_value, reject_reason)。clean_value is REJECTED 表示拒绝写入。"""
    fn = FIELD_SANITIZERS.get(field)
    if fn is None:
        return value, None
    return fn(value)


# ── 官方接口查询：EU（复用 fetch_eu.py 的 SPARQL 逻辑） ──────────────────
CELEX_SEQ_RE = re.compile(r"\((\d+)\)\s*$")


def _celex_seq(celex_like):
    m = CELEX_SEQ_RE.search(celex_like or "")
    return int(m.group(1)) if m else -1


def _query_related_celex(uri, predicate):
    """反向查询：谁用 predicate 指向本 URI（主语是修订/勘误文件本身）。

    ⚠️ 实测核实（本次新增，不是猜测）：
        用 CELEX 32009L0048 验证过 —— get_fields() 正向查到的只有
        resource_legal_repeals_resource_legal（取代关系），没有任何
        "最新修订/最新勘误" 字段。真正能拿到修订/勘误 CELEX 的是反向查询：
            ?amender  cdm:resource_legal_amends_resource_legal   <本law的uri>
            ?corrector cdm:resource_legal_corrects_resource_legal <本law的uri>
        之前设想过 work_amended_by_resource_legal /
        resource_legal_amended_by_resource_legal /
        resource_legal_corrected_by_resource_legal 这几个谓词名，
        实测返回 0 行——SPARQL 端点没有这些谓词，已废弃，改用下方反向查询。
    """
    q = f'''
    PREFIX cdm: <{_fetch_eu.CDM}>
    SELECT ?celex WHERE {{
      ?s cdm:{predicate} <{uri}> .
      ?s cdm:resource_legal_id_celex ?celex .
    }} LIMIT 50
    '''
    rows = _fetch_eu.sparql(q)
    idents = [r["celex"]["value"] for r in rows]
    if not idents:
        return None
    idents.sort(key=_celex_seq)
    return idents[-1]


def query_eu_official(celex):
    """问 Cellar SPARQL 要当前真值：lastModificationDate / in_force /
    最新 amendment、corrigendum（按 CELEX (NN) 序号取最大）。

    返回 dict，查询失败则对应字段省略（不写 None，交由上层区分"没查到"
    和"查到了但是空"）。
    """
    out = {}
    uri = _fetch_eu.find_cellar_uri(celex)
    if not uri:
        raise RuntimeError(f"Cellar 找不到 CELEX {celex}")
    time.sleep(REQUEST_INTERVAL)
    fields = _fetch_eu.get_fields(uri)

    last_mod = _fetch_eu.pick(fields, "lastModificationDate")
    if last_mod:
        out["last_modification_date"] = last_mod

    in_force = _fetch_eu.pick(fields, "resource_legal_in-force")
    if in_force:
        out["in_force"] = in_force

    time.sleep(REQUEST_INTERVAL)
    latest_amend = _query_related_celex(uri, "resource_legal_amends_resource_legal")
    if latest_amend:
        out["latest_amendment_celex"] = latest_amend

    time.sleep(REQUEST_INTERVAL)
    latest_corr = _query_related_celex(uri, "resource_legal_corrects_resource_legal")
    if latest_corr:
        out["latest_corrigendum_celex"] = latest_corr

    return out


# ── 官方接口查询：US（eCFR 复用 fetch_us.py；FR 新写） ───────────────────
def query_fr_effective_date(document_number, retries=3):
    """问 Federal Register 官方 API 要 effective_on。"""
    url = f"{FR_API}/{document_number}.json"
    last_err = None
    for i in range(retries):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": _UA, "Accept": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read().decode("utf-8"))
            return data.get("effective_on") or ""
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code}"
            if e.code == 404:
                return ""  # 文档号查不到，不是脏数据，是没有该记录
            time.sleep(2 * (i + 1))
        except Exception as e:
            last_err = str(e)
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"FR API 查询失败：{document_number} —— {last_err}")


def query_latest_fr_rule(title_number, part_number, retries=3):
    """用 FR 官方搜索接口，按 CFR title+part 直接查最新一条 Rule（已定稿生效的
    最终规则，排除 Proposed Rule 提案稿），拿到当前真正最新的文档号。

    ⚠️ 实测核实（本次新增）：
        eCFR 的 versions API（fetch_us.py 的 get_versions()）的
        content_versions 里完全没有 FR 文档号字段，无法从 eCFR 侧推导。
        FR 自己的 documents.json 搜索接口支持 conditions[cfr][title] /
        conditions[cfr][part] / conditions[type][] 过滤，按 newest 排序
        第一条就是当前最新的 Rule —— 这是比"沿用库内旧文档号"更可靠的
        "先定文档号"实现，不依赖库内已有值。
    """
    import urllib.parse

    params = {
        "conditions[cfr][title]": title_number,
        "conditions[cfr][part]": part_number,
        "conditions[type][]": "RULE",
        "order": "newest",
        "per_page": "1",
    }
    url = f"{FR_API}.json?{urllib.parse.urlencode(params)}"
    last_err = None
    for i in range(retries):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": _UA, "Accept": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read().decode("utf-8"))
            results = data.get("results") or []
            return results[0]["document_number"] if results else None
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code}"
            time.sleep(2 * (i + 1))
        except Exception as e:
            last_err = str(e)
            time.sleep(2 * (i + 1))
    raise RuntimeError(
        f"FR 搜索失败：title={title_number} part={part_number} —— {last_err}"
    )


def query_us_official(title_number, part_number):
    """两步（按讨论结论"先定文档号，再查生效日"）：
    1) 用 FR 官方搜索接口按 CFR title+part 直接查最新 Rule 文档号
       （query_latest_fr_rule，不依赖库内旧文档号）
    2) 用这个文档号查 FR 详情接口拿 effective_on
       （query_fr_effective_date，列表接口的 effective_on 始终为空，
       实测确认必须查详情接口）
    同时查 eCFR 的 latest_amendment_date 作为辅助参考（eCFR 字段本身的
    局限——这是"编入汇编时间"不是"法律生效时间"——已在团队备忘里点破，
    这里仍然采集，但不作为权威生效日，只做辅助展示）。
    """
    out = {}

    latest_amend, _ver_count, _recent, _earliest = _fetch_us.get_versions(
        title_number, part_number
    )
    if latest_amend:
        out["latest_amendment_date"] = latest_amend  # 辅助字段，非权威生效日

    time.sleep(REQUEST_INTERVAL)
    fr_doc_number = query_latest_fr_rule(title_number, part_number)
    if fr_doc_number:
        out["latest_fr_document_number"] = fr_doc_number
        time.sleep(REQUEST_INTERVAL)
        effective_on = query_fr_effective_date(fr_doc_number)
        if effective_on:
            out["fr_effective_on"] = effective_on

    return out


# ── 数据库结构变更（沿用 backfill_law_metadata.py 的 ensure_columns 模式） ──
NEW_LAW_COLUMNS = [
    ("fr_effective_on", "TEXT"),
    ("updated_at", "TEXT"),
    ("effective_status_detail", "TEXT"),
]


def ensure_columns(con, dry_run):
    cur = con.cursor()
    cur.execute("PRAGMA table_info(laws)")
    existing = {row[1] for row in cur.fetchall()}
    for name, coltype in NEW_LAW_COLUMNS:
        if name not in existing:
            print(f"  ALTER TABLE laws ADD COLUMN {name} {coltype}")
            if not dry_run:
                cur.execute(f"ALTER TABLE laws ADD COLUMN {name} {coltype}")
    if not dry_run:
        con.commit()


# ── 比对主流程 ─────────────────────────────────────────────────────────
# 会被比对的字段（EU / US 各自只查自己有的字段，其余字段对另一方跳过）
EU_FIELDS = (
    "last_modification_date",
    "in_force",
    "latest_amendment_celex",
    "latest_corrigendum_celex",
)
US_FIELDS = (
    "latest_fr_document_number",
    "fr_effective_on",
)
# latest_amendment_date 是 eCFR 侧的辅助参考字段（非权威生效日，见
# query_us_official 的说明），laws 表没有这一列，不参与比对/写库，
# 只在日志的 official_raw 里留痕供人工参考。
US_AUX_FIELDS = ("latest_amendment_date",)


def load_laws(con):
    cur = con.cursor()
    cur.execute("PRAGMA table_info(laws)")
    existing_cols = {row[1] for row in cur.fetchall()}

    base_cols = [
        "id", "jurisdiction", "celex", "title_number", "part_number",
        "last_modification_date", "in_force", "latest_amendment_celex",
        "latest_corrigendum_celex", "latest_fr_document_number",
    ]
    # fr_effective_on 可能是刚才 --dry-run 模式下"打算加但还没真加"的新列，
    # 这里按实际存在情况取，不存在就不选它（下游用 law.get() 拿默认 None）。
    select_cols = [c for c in base_cols if c in existing_cols]
    if "fr_effective_on" in existing_cols:
        select_cols.append("fr_effective_on")

    cur.execute(f"SELECT {', '.join(select_cols)} FROM laws")
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def check_one_law(law):
    """查官方接口，跟库内旧值比对。返回 (official_dict, error_or_None)。

    任何异常都捕获返回，不抛出——单条失败不能中断整体任务。
    """
    try:
        if law["jurisdiction"] == "EU":
            official = query_eu_official(law["celex"])
        elif law["jurisdiction"] == "US":
            official = query_us_official(law["title_number"], law["part_number"])
        else:
            return {}, f"未知 jurisdiction={law['jurisdiction']}"
        return official, None
    except Exception as e:
        return {}, str(e)


def apply_changes(con, law, official, dry_run, log_records):
    """逐字段比对、校验、写回、记日志。返回本条变化数。

    official 里 US_AUX_FIELDS（如 latest_amendment_date）只是辅助参考，
    laws 表没有对应列，跳过比对/写库，不记变化日志（避免噪音——它只是
    "这次查到的值"，没有旧值可比，天然每次都"不同"）。
    """
    cur = con.cursor()
    changed_n = 0
    for field, new_raw in official.items():
        if field in US_AUX_FIELDS:
            continue
        old_value = law.get(field)
        clean, reject_reason = sanitize(field, new_raw)
        ts = now_str()
        if clean is REJECTED:
            log_records.append(
                {
                    "ts": ts,
                    "law_id": law["id"],
                    "jurisdiction": law["jurisdiction"],
                    "field": field,
                    "old_value": old_value,
                    "new_value": new_raw,
                    "action": "rejected_invalid_value",
                    "reason": reject_reason,
                }
            )
            continue
        if clean == old_value:
            continue  # 没变化，不占日志
        log_records.append(
            {
                "ts": ts,
                "law_id": law["id"],
                "jurisdiction": law["jurisdiction"],
                "field": field,
                "old_value": old_value,
                "new_value": clean,
                "action": "auto_updated",
                "reason": "",
            }
        )
        if not dry_run:
            cur.execute(
                f"UPDATE laws SET {field}=?, updated_at=? WHERE id=?",
                (clean, ts, law["id"]),
            )
        changed_n += 1
    return changed_n


# ── 过渡期 / 即将生效预警（只读 events 表，不改 laws 任何字段） ──────────
# events 跟 law 的关联路径：events.document_id -> law_documents.document_id
#   -> law_documents.law_id。 EU 用 resource_legal_date_deadline /
#   resource_legal_date_entry-into-force；US 用 effective。
DEADLINE_EVENT_TYPES = (
    "resource_legal_date_deadline",
    "resource_legal_date_entry-into-force",
    "effective",
)


def load_future_events(con):
    cur = con.cursor()
    placeholders = ",".join("?" for _ in DEADLINE_EVENT_TYPES)
    cur.execute(
        f"""SELECT DISTINCT ld.law_id, e.event_type, e.date_value
            FROM events e
            JOIN law_documents ld ON e.document_id = ld.document_id
            WHERE e.event_type IN ({placeholders})
            ORDER BY ld.law_id, e.date_value""",
        DEADLINE_EVENT_TYPES,
    )
    return cur.fetchall()


def compute_upcoming_deadlines(con, today=None):
    """扫 events 表里未来的 deadline/entry-into-force/effective 日期，
    落在 WARN_WINDOW_DAYS 内的收进预警列表。不碰 laws 表任何字段。
    """
    today = today or datetime.now(BJT).date()
    upcoming = []
    for law_id, event_type, date_value in load_future_events(con):
        dt = _parse_date_prefix(date_value)
        if dt is None:
            continue
        d = dt.date()
        if d <= today:
            continue
        days_remaining = (d - today).days
        if days_remaining <= WARN_WINDOW_DAYS:
            upcoming.append(
                {
                    "law_id": law_id,
                    "event_type": event_type,
                    "deadline_date": date_value,
                    "days_remaining": days_remaining,
                }
            )
    upcoming.sort(key=lambda x: x["days_remaining"])
    return upcoming


# ── 派生状态字段（六）：比 in_force 二元标记更细的现行效力描述 ───────────
def compute_effective_status_detail(con, law):
    """结合 in_force + events 里的 entry-into-force / deadline 日期 +
    今天日期，推导更细的状态。不改变 in_force 字段本身的含义。

    US 没有 in_force 字段（持续修订的汇编，没有单一生效/废止概念），
    只能用"有无未来 effective 日期"做近似推断。
    """
    today = datetime.now(BJT).date()
    cur = con.cursor()
    cur.execute(
        """SELECT e.event_type, e.date_value FROM events e
           JOIN law_documents ld ON e.document_id = ld.document_id
           WHERE ld.law_id=?""",
        (law["id"],),
    )
    rows = cur.fetchall()

    def dates_for(event_type):
        out = []
        for et, dv in rows:
            if et == event_type:
                dt = _parse_date_prefix(dv)
                if dt:
                    out.append(dt.date())
        return out

    if law["jurisdiction"] == "EU":
        in_force = law.get("in_force")
        if in_force == "0":
            return "已废止"
        entry_dates = dates_for("resource_legal_date_entry-into-force")
        deadline_dates = dates_for("resource_legal_date_deadline")
        if entry_dates and today < min(entry_dates):
            return "即将生效(未到entry-into-force)"
        if any(d > today for d in deadline_dates):
            return "现行有效(过渡期内)"
        return "现行有效(完全生效)" if in_force == "1" else "待确认"
    else:
        effective_dates = dates_for("effective")
        if any(d > today for d in effective_dates):
            return "现行有效(过渡期内)"
        return "现行有效(持续修订)"


# ── 日志输出 ──────────────────────────────────────────────────────────
def write_log(records, dry_run):
    if not records:
        return
    if dry_run:
        return
    os.makedirs(SQLITE_DIR, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def write_latest(summary, dry_run):
    if dry_run:
        return
    os.makedirs(SQLITE_DIR, exist_ok=True)
    with open(LATEST_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)


# ── 主流程 ────────────────────────────────────────────────────────────
def _require_db():
    """依赖的离线 sqlite 库是否就位。

    sqlite/regulations.sqlite3 是大体积离线数据，被 .gitignore 的 *.sqlite
    排除、不随仓库分发。缺库时 sqlite3.connect() 会静默新建空库，
    后续 ALTER/SELECT 才报 no such table，排查成本高 —— 入口先显式拦一道。
    """
    if os.path.isfile(DB_PATH):
        return True
    print("× 未找到离线语料库：" + DB_PATH)
    print("  本脚本需要 laws / units 表所在的 sqlite 库；该库不随 Git 分发。")
    print("  请从项目离线数据包放入 sqlite/regulations.sqlite3 后重跑。")
    return False


def main():
    if not _require_db():
        return 1
    dry_run = "--dry-run" in sys.argv
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    con = sqlite3.connect(DB_PATH)
    con.text_factory = str

    print("=" * 66)
    print("  法规时效性结构化字段核验" + ("（演练模式，不写库）" if dry_run else ""))
    print("=" * 66)

    ensure_columns(con, dry_run)

    laws = load_laws(con)
    if limit:
        laws = laws[:limit]

    log_records = []
    changed_count = 0
    rejected_count = 0
    failed = []

    for i, law in enumerate(laws, 1):
        print(f"  [{i:>2}/{len(laws)}] {law['id']} ...", end=" ")
        official, err = check_one_law(law)
        if err:
            print(f"失败：{err}")
            failed.append({"law_id": law["id"], "error": err})
            time.sleep(REQUEST_INTERVAL)
            continue

        before_rejected = sum(
            1 for r in log_records if r.get("action") == "rejected_invalid_value"
        )
        n_changed = apply_changes(con, law, official, dry_run, log_records)
        after_rejected = sum(
            1 for r in log_records if r.get("action") == "rejected_invalid_value"
        )
        rejected_count += after_rejected - before_rejected
        changed_count += n_changed

        detail = compute_effective_status_detail(con, law)
        if not dry_run:
            con.execute(
                "UPDATE laws SET effective_status_detail=? WHERE id=?",
                (detail, law["id"]),
            )

        flag = f" 变化{n_changed}处" if n_changed else ""
        print(f"OK{flag}  状态={detail}")
        time.sleep(REQUEST_INTERVAL)

    if not dry_run:
        con.commit()

    upcoming = compute_upcoming_deadlines(con)

    write_log(log_records, dry_run)
    summary = {
        "checked_at": now_str(),
        "total_laws": len(laws),
        "changed_count": changed_count,
        "rejected_count": rejected_count,
        "failed_count": len(failed),
        "failed": failed,
        "changes": [r for r in log_records if r.get("action") == "auto_updated"],
        "rejected": [
            r for r in log_records if r.get("action") == "rejected_invalid_value"
        ],
        "upcoming_deadlines": upcoming,
    }
    write_latest(summary, dry_run)

    print()
    print(
        f"  核验完成：{len(laws)} 条；自动更新 {changed_count} 处；"
        f"拒绝脏数据 {rejected_count} 处；查询失败 {len(failed)} 条；"
        f"未来 {WARN_WINDOW_DAYS} 天内到期/生效预警 {len(upcoming)} 条"
    )
    if dry_run:
        print("  （演练模式，未写库、未写日志文件）")
    else:
        print(f"  日志追加 → {os.path.relpath(LOG_PATH, GO_RADAR_ROOT)}")
        print(f"  最新态   → {os.path.relpath(LATEST_PATH, GO_RADAR_ROOT)}")
    print("=" * 66)

    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
