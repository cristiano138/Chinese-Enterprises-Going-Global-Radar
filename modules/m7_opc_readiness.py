# -*- coding: utf-8 -*-
"""M7 · OPC 上线准备度工作台。

把 M3 已核对的动作按商品从选品到上架的经营阶段重新组织，
帮助小团队分工和发现资料缺口。它不判断商品已合规，也不替代人工审核。
"""
from __future__ import annotations

import os
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)

from core import snapshot  # noqa: E402
from modules import m3_todo  # noqa: E402


PHASES = [
    "选品与范围",
    "打样与测试",
    "标签与上架",
    "文件与认证",
    "供应链留档",
    "切换与复核",
]

TYPE_TO_PHASE = {
    "合规确认": "选品与范围",
    "限制禁售": "选品与范围",
    "检测测试": "打样与测试",
    "标签标识": "标签与上架",
    "认证文件": "文件与认证",
    "注册备案": "文件与认证",
    "记录留存": "供应链留档",
    "切换替换": "切换与复核",
}

TYPE_TO_ROLE = {
    "合规确认": "产品负责人",
    "限制禁售": "产品负责人",
    "检测测试": "研发 / 品控",
    "标签标识": "设计 / 运营",
    "认证文件": "合规 / 品控",
    "注册备案": "合规 / 运营",
    "记录留存": "供应链 / 品控",
    "切换替换": "产品负责人 / 合规",
}


def _task_status(action):
    if action.get("待确认") or action.get("条件待确认"):
        return "需确认"
    if action.get("紧迫度") == "高":
        return "优先处理"
    return "待执行"


def _task(action, phase):
    return {
        "动作": action.get("动作", ""),
        "动作类型": action.get("动作类型", "合规确认"),
        "阶段": phase,
        "责任角色": TYPE_TO_ROLE.get(action.get("动作类型"), "产品负责人"),
        "状态": _task_status(action),
        "紧迫度": action.get("紧迫度", "低"),
        "期限": action.get("期限", ""),
        "适用条件": action.get("适用条件", ""),
        "官方编号": action.get("官方编号", ""),
        "依据法规": action.get("依据法规", ""),
        "官方链接": action.get("来源条款链接", ""),
        "证据摘录": action.get("证据摘录", ""),
    }


def _empty(category, markets, reason):
    return {
        "ok": False,
        "reason": reason,
        "品类": category,
        "市场": markets,
        "区域": [],
        "快照版本": snapshot.SNAPSHOT_VERSION,
        "数据截止时间": snapshot.DATA_CUTOFF,
    }


def query(category="儿童玩具", markets=None, today=None):
    """返回一个品类在多个市场的 OPC 上线准备项。"""
    category = (category or "").strip()
    markets = list(dict.fromkeys(markets or list(m3_todo.corpus.SUPPORTED_MARKETS.keys())))
    today = today or date.today()
    if category not in m3_todo.corpus.ENTRY_CATEGORIES:
        return _empty(category, markets, "请选择支持的业务品类。")
    invalid = [m for m in markets if m not in m3_todo.corpus.SUPPORTED_MARKETS]
    if invalid:
        return _empty(category, markets, f"暂不支持市场：{'、'.join(invalid)}。")
    if not markets:
        return _empty(category, markets, "至少选择一个目标市场。")

    regions = []
    for market in markets:
        result = m3_todo.query(category, market, use_llm=False, today=today)
        if not result.get("ok"):
            regions.append({"市场": market, "状态": "error", "阶段": [], "动作": [],
                            "待确认": [], "未产出条数": 0, "动作条数": 0,
                            "错误": result.get("reason", "无法生成待办")})
            continue
        grouped = {phase: [] for phase in PHASES}
        for action in result.get("动作", []):
            phase = TYPE_TO_PHASE.get(action.get("动作类型"), "选品与范围")
            grouped[phase].append(_task(action, phase))
        regions.append({
            "市场": market,
            "状态": "ready" if not result.get("未产出") else "partial",
            "阶段": [{"名称": phase, "动作": grouped[phase], "条数": len(grouped[phase])}
                     for phase in PHASES if grouped[phase]],
            "动作": [item for items in grouped.values() for item in items],
            "待确认": result.get("待确认", []),
            "未产出条数": len(result.get("未产出", [])),
            "动作条数": len(result.get("动作", [])),
            "高优先级": sum(1 for a in result.get("动作", []) if a.get("紧迫度") == "高"),
            "需确认条数": len(result.get("待确认", [])),
        })

    return {
        "ok": True,
        "reason": "",
        "品类": category,
        "市场": markets,
        "区域": regions,
        "总动作数": sum(r.get("动作条数", 0) for r in regions),
        "高优先级数": sum(r.get("高优先级", 0) for r in regions),
        "快照版本": snapshot.SNAPSHOT_VERSION,
        "数据截止时间": snapshot.DATA_CUTOFF,
        "查询日期": today.isoformat(),
        "说明": "这是上线前准备项覆盖情况，不代表商品已经合规；每项仍需按条件和官方依据人工核对。",
    }


def render_text(result):
    if not result.get("ok"):
        return "❌ " + result.get("reason", "无法生成准备度")
    lines = [f"M7 OPC 上线准备度 · {result['品类']}", "=" * 60]
    for region in result["区域"]:
        lines.append(f"{region['市场']}：{region['动作条数']} 项动作，"
                     f"高优先级 {region.get('高优先级', 0)} 项，"
                     f"需确认 {region.get('需确认条数', 0)} 项")
        for phase in region.get("阶段", []):
            lines.append(f"  - {phase['名称']}：{phase['条数']} 项")
    lines.append("说明：" + result["说明"])
    return "\n".join(lines)
