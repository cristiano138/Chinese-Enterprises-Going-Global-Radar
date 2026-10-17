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
CELEX_RE = re.compile(r"^\d{8}[RLD]\d{4}(?:R\(\d+\))?$")
FR_DOC_RE = re.compile(r"^\d{4}-\d{4,6}$")
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
