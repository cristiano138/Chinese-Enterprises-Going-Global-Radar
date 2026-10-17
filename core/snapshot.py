# -*- coding: utf-8 -*-
"""核心层：数据快照元数据。

本工具所有查询结果顶部统一显示以下四项（PRD 附录 D3 `query()` 契约）：
- 查询条件（类目 + 市场）
- 查询日期（北京时间）
- 快照版本
- 数据截止时间

本期不实现完整发布管线（PRD 附录 C 描述的快照/校验/版本切换机制），
原因：用户明确「创空间更新一次覆盖上传就行，不用整包重来」。
本模块只承担「在所有输出顶部声明当前快照的版本与截止时间」这一职责。
"""
from __future__ import annotations

import html
import json
import os
from datetime import date, datetime, timezone, timedelta
from typing import Dict, List

# 北京时区偏移（+8 小时）；不带夏令时
_BEIJING = timezone(timedelta(hours=8))

# ----- 快照元数据（按 PRD 附录 D3 / C1 声明）-----

# 快照版本号（人类可读；本期为单版本，全局固定）
_PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SNAPSHOT_FILE = os.path.join(_PROJECT, "data", "snapshot.json")


def _load_release_snapshot():
    try:
        with open(_SNAPSHOT_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("total_rows") and not data.get("duplicate_keys"):
            return data
    except (OSError, ValueError, TypeError):
        pass
    return {}


_RELEASE = _load_release_snapshot()
SNAPSHOT_VERSION = _RELEASE.get("snapshot_version", "v1.0-pre-review")


def _normalize_date(text, fallback="2026-10-14"):
    """把 2026.10.14 / 2026年10月14日 之类写法统一成 ISO 8601（2026-10-14）。

    底表「核对日期」列历史写法是点分（2026.10.14），曾被 build_snapshot 原样
    写进 snapshot.json，结果页面上「数据截止 2026.10.14」和「查询日期
    2026-10-17」两种格式并排 —— 同一行元数据出现两套日期写法，容易被误读成
    版本号。这里做一次归一，展示层与导出层只认 ISO。
    """
    raw = (text or "").strip()
    if not raw:
        return fallback
    digits = "".join(ch if ch.isdigit() else " " for ch in raw).split()
    if len(digits) >= 3 and len(digits[0]) == 4:
        y, m, d = digits[0], digits[1], digits[2]
        if len(m) <= 2 and len(d) <= 2:
            return f"{y}-{int(m):02d}-{int(d):02d}"
    if len(raw) == 10 and raw[4] == "-" and raw[7] == "-":
        return raw
    return raw


DATA_CUTOFF = _normalize_date(_RELEASE.get("data_cutoff"))

# 发布脚本生成的总量；快照不存在时保留兼容兜底。
CORPUS_ROWS_TOTAL = int(_RELEASE.get("total_rows", 86))
CORPUS_ROWS_BY_MARKET = _RELEASE.get("markets", {"欧盟": 29, "美国": 57})

# 核对状态分布（由 validate_corpus → build_snapshot 写进快照）。
# 概览卡片原先直接拿 CORPUS_ROWS_TOTAL 当「已核对法规」展示，等于把 57 条
# 待核对语料也算成已核对 —— 这里把口径拆开，避免页面自报假数字。
CORPUS_AUDIT_STATUS = _RELEASE.get("audit_status_distribution", {}) or {}
CORPUS_ROWS_AUDITED = int(CORPUS_AUDIT_STATUS.get("已核对", 0) or 0)

# 官方来源（PRD 附录 C3 允许集合）
DATA_SOURCES = (
    "EUR-Lex SPARQL（publications.europa.eu/webapi/rdf/sparql）",
    "eCFR API（api.ecfr.gov / www.ecfr.gov）",
)

# 模块状态枚举（PRD 附录 D3）
MODULE_READY = "ready"      # 有合格数据
MODULE_EMPTY = "empty"      # 无合格数据
MODULE_PARTIAL = "partial"  # 一部分合格，一部分仍在核验
MODULE_ERROR = "error"      # 异常

# 「本次未查询」（**不是「空」**）。
# 踩过的坑：header() 曾把未传的模块状态默认成 MODULE_EMPTY，于是 M1 页签顶栏
# 把明明有数据的 M2/M3/M4 标成「空」—— 状态语义被默认值污染。
# 现在的做法：没传状态的模块**根本不出现在顶栏**（不列 = 未查询）；
# MODULE_NA 保留给「显式想说明该模块本应参与但未跑」的场景。
MODULE_NA = "n/a"

# 状态中文名唯一出口（app_main 与 CLI 共用，禁止各处再写一份）
MODULE_CN = {
    MODULE_READY: "就绪",
    MODULE_PARTIAL: "部分",
    MODULE_EMPTY: "空",
    MODULE_ERROR: "异常",
    MODULE_NA: "未查询",
}

# 模块代号 → 页面上对用户可见的名字（不暴露内部代号）
MODULE_NAMES = {
    "M1": "法规地图",
    "M2": "变化时间线",
    "M3": "合规待办",
    "M4": "模型对照",
    "M5": "区域对比",
    "M6": "多区域汇总",
    "M7": "OPC 上线准备",
}

# 合法状态集合：渲染时用它做白名单，避免异常值被拼进 class 属性
_MODULE_ALL = frozenset(MODULE_CN)


def _esc(value) -> str:
    """HTML 转义（None 视为空串）。"""
    return html.escape("" if value is None else str(value), quote=True)

# 覆盖范围说明（顶部展示）
COVERAGE_SCOPE = (
    "本期支持欧盟、美国；"
    "类目固定为儿童玩具、电子电器、纺织服装、美妆个护、食品接触材料；"
    "「标签标识」「通用」按审核条件关联，不作为独立入口。"
)

# 免责声明（PRD 附录 D3：每条导出记录固定附；M1/M2/M3 顶部固定附）
DISCLAIMER = (
    "本清单仅供参考，不构成法律意见。请以官方原文为准，并由专业人员复核。"
)

# 页脚 WAF 提示（用户在指令中追加）
WAF_FOOTER_HINT = "部分官方站点会拦截自动访问，真人浏览器一般可正常打开。"


def now_bjt() -> str:
    """查询日期（北京时间），ISO 8601 YYYY-MM-DD。"""
    return datetime.now(_BEIJING).strftime("%Y-%m-%d")


def header(category: str, market: str,
           m1_status: str = None,
           m2_status: str = None,
           m3_status: str = None,
           m4_status: str = None,
           extra_notes: str = "",
           modules: Dict[str, str] = None) -> Dict[str, object]:
    """返回所有查询结果顶部的统一元数据字典。

    各模块分别报告状态 —— 一个模块为空不阻塞其他模块（PRD D3）。

    只列出**本次查询真正跑过**的模块：没传状态的模块不出现（用 MODULE_NA 的
    语义表达「未查询」，而不是默认成 MODULE_EMPTY 谎报「空」）。
    ``modules`` 供 M5/M6/M7 等新模块自报状态（如 {"M5": MODULE_READY}）。
    """
    statuses: Dict[str, str] = {}
    for code, val in (("M1", m1_status), ("M2", m2_status),
                      ("M3", m3_status), ("M4", m4_status)):
        if val is not None:
            statuses[code] = val
    if modules:
        statuses.update(modules)
    return {
        "查询条件": f"{category} / {market}",
        "类目": category,
        "市场": market,
        "查询日期": now_bjt(),
        "快照版本": SNAPSHOT_VERSION,
        "数据截止时间": DATA_CUTOFF,
        "数据来源": "、".join(DATA_SOURCES),
        "覆盖范围": COVERAGE_SCOPE,
        "模块状态": statuses,
        "附注": extra_notes.strip(),
        "免责声明": DISCLAIMER,
        "页脚提示": WAF_FOOTER_HINT,
    }


def render_header_block(meta: Dict[str, object]) -> str:
    """把元数据渲染成 HTML 顶部条（全站唯一实现）。

    10-16 瘦身：覆盖范围 / 数据来源已移除 —— 它们是静态信息，与单次查询无关，
    属冗余内容；免责声明保留（红线）。原先 app_main 里另有一份同功能实现，
    两套并存必然漂移，现在统一到这里，UI 层只负责调用。

    所有动态值统一走 html.escape：语料里含 ``&`` ``<`` 等字符，未转义会破坏结构。
    """
    if not meta:
        return ""
    mod = meta.get("模块状态", {}) or {}
    parts = []
    for key, value in mod.items():
        # 状态值只可能是枚举之一；异常值降级为「未查询」，不把原始串拼进 class。
        status = value if value in _MODULE_ALL else MODULE_NA
        parts.append(
            f'<span class="cr-mod cr-mod-{status}">'
            f'{_esc(MODULE_NAMES.get(key, key))}·{_esc(MODULE_CN.get(status, status))}'
            f'</span>'
        )
    mod_html = "　".join(parts)

    notes_html = ""
    if meta.get("附注"):
        notes_html = f'<div class="cr-meta-notes">备注：{_esc(meta["附注"])}</div>'

    return (
        '<div class="cr-header">'
        f'<div class="cr-meta-line"><b>{_esc(meta.get("查询条件", ""))}</b>'
        f'　·　快照 {_esc(meta.get("快照版本", ""))}'
        f'　·　数据截止 {_esc(meta.get("数据截止时间", ""))}'
        f'　{mod_html}</div>'
        f'{notes_html}'
        f'<div class="cr-disclaimer">{_esc(meta.get("免责声明", ""))}</div>'
        '</div>'
    )