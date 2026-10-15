# -*- coding: utf-8 -*-
"""核心层：PRD 附录 E 节空态文案。

PRD 附录 E 列出了 14 种异常/降级场景的用户文案。本模块把每一场景封装为
可调用函数，上层永远不直写硬编文案 —— 一切空态走这里。

口径：原文用 14 种场景；本模块用 12 个函数（含合并"未选输入"与"非法参数"）。
新增场景时按 PRD 原文补充，**禁止自由发挥**。
"""
from __future__ import annotations

# ---- 1. 未选择输入或非法参数 ----
def msg_no_input() -> str:
    return "请选择支持的商品类目和目标市场。"


# ---- 2. 无关类目（PRD：本期仅支持 5 类）----
ALLOWED_CATEGORIES = ("儿童玩具", "电子电器", "纺织服装", "美妆个护", "食品接触材料")


def msg_category_out_of_scope(category: str) -> str:
    return (
        f"本期仅支持儿童玩具、电子电器、纺织服装、美妆个护、食品接触材料。"
        f"「{category}」不在本期支持范围内。"
    )


# ---- 3. 不支持的市场 ----
def msg_market_out_of_scope(market: str) -> str:
    if market == "美国":
        return "本期仅支持欧盟和美国；当前版本仅开放欧盟。"
    return "本期仅支持欧盟和美国。"


# ---- 4. 类目尚无审核通过记录 ----
def msg_empty_no_audit(category: str, market: str) -> str:
    return (
        f"{category} / {market}：该组合暂缺已核对法规，"
        f"不能据此判断无需合规。"
    )


# ---- 5. 一部分记录未通过 ----
def msg_partial_pending(category: str, market: str) -> str:
    return (
        f"{category} / {market}：当前仅展示已核对内容，"
        f"部分资料仍在核验中。"
    )


# ---- 6. 生效日期未知 ----
def msg_date_unknown() -> str:
    return "生效日期待核实。"


# ---- 7. 没有近期事件（时间线空态）----
def msg_timeline_empty(category: str, market: str) -> str:
    return (
        f"{category} / {market}：当前语料未收录可展示的相关日期事件，"
        f"不代表没有法规变化。"
    )


# ---- 8. 没有条款待办证据（M3 空态，禁用导出）----
def msg_no_audit_todo(category: str, market: str) -> str:
    return (
        f"{category} / {market}：尚无足够的已核对条款依据生成待办，"
        f"请先查看法规原文。"
    )


# ---- 9. 法律依据明确但商品属性或经营者身份未知 ----
def msg_conditions_pending() -> str:
    return (
        "这项行动取决于以下条件，请先核对；"
        "尚不能判断是否适用于你的商品或经营角色。"
    )


# ---- 10. 待办差异案例未审核或已过期（不展示独立报错；保留 M2 节点与 M3 待办）----
def msg_diff_case_unavailable() -> str:
    # 按 PRD：不增加独立报错
    return ""


# ---- 11. 官方链接确认失效 ----
def msg_source_revoked() -> str:
    return "部分来源暂不可用，相关条目已暂停展示。"


# ---- 12. WAF / 403 / 限流 / 临时超时 ----
def msg_waf_or_blocked() -> str:
    return (
        "官方站点当前自动访问受限；此处展示已核对快照，"
        "请结合数据截止时间查阅。"
    )


# ---- 13. 模型超时 / 空返回 / 格式错误 ----
def msg_llm_unavailable() -> str:
    return "AI服务暂不可用，已展示审核数据中的结果。"


# ---- 14. 模型配额不足 ----
def msg_llm_quota_exceeded() -> str:
    return (
        "AI服务额度暂不可用，法规清单与已核对待办仍可查看。"
    )


# ---- 15. M4 实时失败 ----
def msg_m4_realtime_failed() -> str:
    return "本次实时对照未完成，可查看标注时间的历史实测记录。"


# ---- 16. 快照缺失或校验失败 ----
def msg_snapshot_invalid() -> str:
    return "数据暂不可用，请稍后再试。"


# ---- 17. 数据版本更新后导出 ----
def msg_snapshot_version_changed() -> str:
    return "数据版本已更新，请重新查询后导出。"


# ---- 18. 未选择导出条目 ----
def msg_export_no_selection() -> str:
    return "请至少选择一项待办。"


# ---- 顶部署名常量 ----
ALL_MESSAGES = {
    "no_input": msg_no_input,
    "category_out_of_scope": msg_category_out_of_scope,
    "market_out_of_scope": msg_market_out_of_scope,
    "empty_no_audit": msg_empty_no_audit,
    "partial_pending": msg_partial_pending,
    "date_unknown": msg_date_unknown,
    "timeline_empty": msg_timeline_empty,
    "no_audit_todo": msg_no_audit_todo,
    "conditions_pending": msg_conditions_pending,
    "diff_case_unavailable": msg_diff_case_unavailable,
    "source_revoked": msg_source_revoked,
    "waf_or_blocked": msg_waf_or_blocked,
    "llm_unavailable": msg_llm_unavailable,
    "llm_quota_exceeded": msg_llm_quota_exceeded,
    "m4_realtime_failed": msg_m4_realtime_failed,
    "snapshot_invalid": msg_snapshot_invalid,
    "snapshot_version_changed": msg_snapshot_version_changed,
    "export_no_selection": msg_export_no_selection,
}