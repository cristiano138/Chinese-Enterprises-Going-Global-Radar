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

from datetime import date, datetime, timezone, timedelta
from typing import Dict, List

# 北京时区偏移（+8 小时）；不带夏令时
_BEIJING = timezone(timedelta(hours=8))

# ----- 快照元数据（按 PRD 附录 D3 / C1 声明）-----

# 快照版本号（人类可读；本期为单版本，全局固定）
SNAPSHOT_VERSION = "v1.0-pre-review"

# 数据截止时间（采集管线最后一次成功刷新的日期；本期采用 corpus.py 内部固定值）
# 若需调整，运行 `scripts/merge_corpus.py` 刷新后同步更新此值即可
DATA_CUTOFF = "2026-10-14"

# 官方来源（PRD 附录 C3 允许集合）
DATA_SOURCES = (
    "EUR-Lex SPARQL（publications.europa.eu/webapi/rdf/sparql）",
    "eCFR API（api.ecfr.gov / www.ecfr.gov）",
)

# 语料规模（来自 data/语料核对表_完整版.csv；本期未自动扩展）
# 注：与 PRD 附录 A 中 "88行 / 86 个唯一键" 一致；按 PRD A 节，本字段不承诺"已核对"
CORPUS_ROWS_TOTAL = 86
CORPUS_ROWS_BY_MARKET = {"欧盟": 29, "美国": 57}

# 模块状态枚举（PRD 附录 D3）
MODULE_READY = "ready"      # 有合格数据
MODULE_EMPTY = "empty"      # 无合格数据
MODULE_PARTIAL = "partial"  # 一部分合格，一部分仍在核验
MODULE_ERROR = "error"      # 异常

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
           m1_status: str = MODULE_EMPTY,
           m2_status: str = MODULE_EMPTY,
           m3_status: str = MODULE_EMPTY,
           m4_status: str = MODULE_EMPTY,
           extra_notes: str = "") -> Dict[str, object]:
    """返回所有查询结果顶部的统一元数据字典。

    各模块分别报告状态 —— 一个模块为空不阻塞其他模块（PRD D3）。
    """
    return {
        "查询条件": f"{category} / {market}",
        "类目": category,
        "市场": market,
        "查询日期": now_bjt(),
        "快照版本": SNAPSHOT_VERSION,
        "数据截止时间": DATA_CUTOFF,
        "数据来源": "、".join(DATA_SOURCES),
        "覆盖范围": COVERAGE_SCOPE,
        "模块状态": {
            "M1": m1_status,
            "M2": m2_status,
            "M3": m3_status,
            "M4": m4_status,
        },
        "附注": extra_notes.strip(),
        "免责声明": DISCLAIMER,
        "页脚提示": WAF_FOOTER_HINT,
    }


def render_header_block(meta: Dict[str, object]) -> str:
    """把元数据渲染成 HTML 顶部条（被 M1/M2/M3 复用）。"""
    mod = meta.get("模块状态", {})
    mod_html = "　".join(
        f"<span class='cr-mod cr-mod-{v}'>M{k}·{v}</span>"
        for k, v in mod.items()
    )

    notes_html = ""
    if meta.get("附注"):
        notes_html = (
            f"<div class='cr-meta-notes'>备注：{meta['附注']}</div>"
        )

    return (
        "<div class='cr-header'>"
        f"<div class='cr-meta-line'><b>查询条件</b>：{meta.get('查询条件', '')}　"
        f"<b>查询日期</b>：{meta.get('查询日期', '')}　"
        f"<b>快照版本</b>：{meta.get('快照版本', '')}　"
        f"<b>数据截止时间</b>：{meta.get('数据截止时间', '')}</div>"
        f"<div class='cr-meta-line'>模块状态：{mod_html}</div>"
        f"<div class='cr-meta-line cr-meta-scope'><b>覆盖范围</b>：{meta.get('覆盖范围', '')}</div>"
        f"<div class='cr-meta-line'><b>数据来源</b>：{meta.get('数据来源', '')}</div>"
        f"{notes_html}"
        f"<div class='cr-disclaimer'>{meta.get('免责声明', '')}</div>"
        "</div>"
    )


def module_status_for(count_ok: int, count_pending: int = 0,
                      out_of_scope: bool = False) -> str:
    """根据条目数判定模块状态。"""
    if out_of_scope:
        return MODULE_EMPTY
    if count_ok == 0:
        return MODULE_EMPTY
    if count_pending > 0:
        return MODULE_PARTIAL
    return MODULE_READY