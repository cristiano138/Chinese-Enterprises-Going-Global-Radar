# -*- coding: utf-8 -*-
"""
M4 · 对照演示（modules/m4_compare.py）

PRD 附录 D4：
    固定题干：「截至{观察日期}，向欧盟销售儿童玩具时，应关注哪些主要法规？
    请区分当前适用要求与已公布的未来变化，附官方依据并说明适用条件及不确定性。」
    通用侧与工具侧使用同一题干和观察日期；
    默认展示真实历史实测回放；允许主动触发实时对照。
    不诱导模型犯错、不预写胜负；未取得确证的「32015R1000 不存在」
    不得作为默认反例。

本期实现：占位 + 历史回放数据结构。
    - 真实回放记录存储在 data/m4_replays.jsonl（每行一条 JSON）
    - 工具侧：本工具查询结果（来自 m1+m2+m3 合并展示）
    - 通用侧：占位（本期未配置真实模型 Token，固定显示「尚未生成对照记录」）

边界（PRD D4）：
    - 不诱导模型犯错
    - 不预写胜负
    - 实时失败显示失败，历史结果单独标识
    - 没有真实记录时显示「尚未生成对照记录」
"""

import json
import os
import sys
from datetime import date
from typing import List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)

from core import snapshot as core_snapshot  # noqa: E402

# ── D4 固定题干（不允许修改） ──────────────────────────────────
M4_FIXED_QUESTION_TEMPLATE = (
    "截至{观察日期}，向欧盟销售儿童玩具时，应关注哪些主要法规？"
    "请区分当前适用要求与已公布的未来变化，"
    "附官方依据并说明适用条件及不确定性。"
)

DEFAULT_OBSERVATION_DATE = "2026-10-15"   # 数据快照后第一个工作日

# 通用模型侧：本期固定占位（PRD D4：未取得确证的「32015R1000 不存在」不得作为默认反例）
# 注意：本字符串**不能**包含任何「玩具安全条例编号 32015R1000」字样
GENERIC_PLACEHOLDER = (
    "尚未生成对照记录。"
    "本期未提供真实历史实测记录（需先调用真实模型生成同题原答并保存），"
    "故不在此处展示示意回答冒充结果。"
)


def build_question(observation_date: str = None) -> str:
    """生成 D4 固定题干（含观察日期占位）。"""
    obs = observation_date or DEFAULT_OBSERVATION_DATE
    return M4_FIXED_QUESTION_TEMPLATE.format(观察日期=obs)


def load_replays():
    """加载历史回放记录。每行一条 JSON；缺字段的容错跳过。

    本期未配置真实回放数据 —— 函数返回空列表时 UI 显示「尚未生成对照记录」。
    """
    path = os.path.join(PROJECT, "data", "m4_replays.jsonl")
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:
                continue
    return out


def query(category="儿童玩具", market="欧盟",
          observation_date=None, use_tool=True):
    """M4 主入口：返回对照演示当前状态。

    返回 dict：
        ok / reason
        观察日期 / 固定题干 / 快照版本 / 数据截止时间
        回放状态 / 回放列表（最新在前）
        通用侧 / 工具侧  本期当前内容
    """
    if category != "儿童玩具" or market != "欧盟":
        return {
            "ok": False,
            "reason": "M4 仅按 PRD D4 对「儿童玩具 × 欧盟」进行对照演示，"
                      "其他组合暂不演示。",
            "观察日期": observation_date or DEFAULT_OBSERVATION_DATE,
            "固定题干": build_question(observation_date),
            "快照版本": core_snapshot.SNAPSHOT_VERSION,
            "数据截止时间": core_snapshot.DATA_CUTOFF,
            "回放状态": "未演示",
            "回放列表": [],
            "通用侧": "（本期仅展示儿童玩具 × 欧盟）",
            "工具侧": "（本期仅展示儿童玩具 × 欧盟）",
        }

    obs = observation_date or DEFAULT_OBSERVATION_DATE
    replays = load_replays()

    return {
        "ok": True,
        "reason": "",
        "观察日期": obs,
        "固定题干": build_question(obs),
        "快照版本": core_snapshot.SNAPSHOT_VERSION,
        "数据截止时间": core_snapshot.DATA_CUTOFF,
        "回放状态": "已录制" if replays else "尚未生成对照记录",
        "回放列表": replays,                       # 供 UI 选择
        "通用侧": replays[0]["generic_answer"] if replays else GENERIC_PLACEHOLDER,
        "工具侧": replays[0]["tool_answer"] if replays
                  else "（点击「查询」按钮后，本工具会按 M1+M2+M3 实时输出）",
        "header": core_snapshot.header(category, market,
                                      m4_status=core_snapshot.MODULE_READY
                                                if replays
                                                else core_snapshot.MODULE_EMPTY),
    }


# ── 渲染成文本（供自检与 CLI） ────────────────────────────────
def render_text(result):
    lines = []
    if not result["ok"]:
        lines.append("❌ " + result["reason"])
        return "\n".join(lines)

    lines.append("=" * 78)
    lines.append("  M4 对照演示 · 儿童玩具 × 欧盟")
    lines.append("=" * 78)
    lines.append(f"  观察日期：{result['观察日期']}")
    lines.append(f"  快照版本：{result['快照版本']}　数据截止时间：{result['数据截止时间']}")
    lines.append("")
    lines.append("【D4 固定题干】")
    lines.append("  " + result["固定题干"])
    lines.append("")
    lines.append("【通用侧（原答）】")
    if result["回放列表"]:
        for r in result["回放列表"]:
            lines.append(f"  · 时间：{r.get('timestamp','-')}")
            lines.append(f"  · 模型：{r.get('generic_model_name','-')}")
            lines.append("    " + r.get("generic_answer", ""))
    else:
        lines.append("  " + result["通用侧"])
    lines.append("")
    lines.append("【工具侧（合规雷达）】")
    if result["回放列表"]:
        for r in result["回放列表"]:
            lines.append(f"  · 时间：{r.get('timestamp','-')}")
            lines.append("    " + r.get("tool_answer", ""))
    else:
        lines.append("  " + result["工具侧"])
    lines.append("")
    lines.append("─" * 78)
    lines.append(f"  ⚖️ {core_snapshot.DISCLAIMER}")
    lines.append(f"  ℹ️  {core_snapshot.WAF_FOOTER_HINT}")
    lines.append("=" * 78)
    return "\n".join(lines)


if __name__ == "__main__":
    res = query()
    print(render_text(res))