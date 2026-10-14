# -*- coding: utf-8 -*-
"""
ComplianceRadar · 出海合规雷达 —— 可运行版本

产品做什么：
    输入「品类 + 市场」→ 输出适用法规清单与变化时间线，
    每条结论都强制附带官方原文链接，供卖家自行核验。

设计原则（为什么这么写）：
    1. 不依赖大模型也能出结果 —— 主流程是纯查表，演示时绝不会出现空白页。
       大模型只负责「把结果说成人话」，属于增强，不是前提。
    2. 结论必有出处 —— 每条法规都带官方链接与官方编号，不做无源断言。
    3. 只读本地 CSV，不发网络请求 —— 启动快、不依赖外网、不会因限流失败。

魔搭创空间（ModelScope Studio）的三条硬性要求，本文件均已满足：
    - 入口文件名必须是 app.py
    - 必须有模块级全局变量 demo = gr.Blocks(...)
    - 必须调用 demo.launch()

本地运行：
    python app.py
"""

import csv
import re
from pathlib import Path

import gradio as gr

BASE_DIR = Path(__file__).resolve().parent
CORPUS_PATH = BASE_DIR / "data" / "语料核对表_完整版.csv"

MARKET_CHOICES = {"欧盟（EU）": "EU", "美国（US）": "US"}
ALL_MARKETS = "全部市场"
ALL_CATEGORIES = "全部品类"

DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


# --------------------------------------------------------------------------
# 数据加载
# --------------------------------------------------------------------------
def load_corpus():
    """读取语料底表；文件不存在时返回空列表，由界面给出友好提示。"""
    if not CORPUS_PATH.exists():
        return []
    with CORPUS_PATH.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


CORPUS = load_corpus()
CATEGORY_CHOICES = [ALL_CATEGORIES] + sorted({r["类目"] for r in CORPUS})


# --------------------------------------------------------------------------
# 结构化检索（按「类目 + 市场」标签精确筛选，不做向量检索）
# --------------------------------------------------------------------------
def select_rows(category, market_label):
    org = MARKET_CHOICES.get(market_label, "")
    picked = []
    for row in CORPUS:
        if category != ALL_CATEGORIES and row["类目"] != category:
            continue
        if org and row["机构"] != org:
            continue
        picked.append(row)
    return picked


def _meta_line(row):
    """把一条法规的关键元数据拼成一行。"""
    parts = []
    if row.get("官方编号"):
        parts.append("**官方编号**：`" + row["官方编号"] + "`")
    if row.get("CELEX号"):
        parts.append("**CELEX**：`" + row["CELEX号"] + "`")
    if row.get("来源类型"):
        parts.append("**来源**：" + row["来源类型"])
    if row.get("生效日期"):
        parts.append("**生效日期**：" + row["生效日期"])
    if row.get("最新修订日期"):
        parts.append("**最新修订**：" + row["最新修订日期"])
    return " ｜ ".join(parts)


def _clip(text, limit=160):
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit] + "…"


# --------------------------------------------------------------------------
# 三个渲染函数
# --------------------------------------------------------------------------
def render_summary(rows, category, market_label):
    if not CORPUS:
        return (
            "### ⚠️ 语料文件未找到\n\n"
            "请确认 `data/语料核对表_完整版.csv` 与 `app.py` 在同一目录层级。"
        )
    if not rows:
        return (
            "### 🔍 「" + category + " × " + market_label + "」暂无匹配法规\n\n"
            "本期语料覆盖的市场为 **欧盟（EU）** 与 **美国（US）**。"
            "若该组合尚无收录，属**语料覆盖范围限制**，而非「没有要求」。\n\n"
            "> 提示：可先选择「全部品类」查看该市场下已收录的全部法规。"
        )
    return (
        "### ✅ 命中 **" + str(len(rows)) + "** 条法规\n\n"
        "筛选条件：**" + category + " × " + market_label + "** ｜ "
        "全部结论均附官方原文链接，可逐条核验。"
    )


def render_list(rows):
    if not rows:
        return "_该组合下暂无收录法规。_"
    blocks = []
    for i, row in enumerate(rows, 1):
        title = row["法规中文名"] or "（未命名）"
        lines = ["#### " + str(i) + ". " + title]

        meta = _meta_line(row)
        if meta:
            lines.append(meta)

        if row.get("官方链接"):
            short = _clip(row["官方标题（英文）"].split(" of ")[0], 70)
            lines.append("🔗 **官方原文**：[" + short + "](" + row["官方链接"] + ")")

        if row.get("官方标题（英文）"):
            lines.append("<sub>" + _clip(row["官方标题（英文）"]) + "</sub>")

        if row.get("备注／问题"):
            lines.append("<sub>📌 " + _clip(row["备注／问题"], 220) + "</sub>")

        blocks.append("\n\n".join(lines))
    return "\n\n---\n\n".join(blocks)


def render_timeline(rows):
    """按日期倒序排出一张变化时间线。日期取自「生效日期」与「最新修订日期」两列。"""
    if not rows:
        return "_该组合下暂无收录法规。_"

    events = []
    for row in rows:
        name = row["法规中文名"] or "（未命名）"
        org = row["机构"]
        if row.get("生效日期"):
            hit = DATE_RE.search(row["生效日期"])
            if hit:
                events.append((hit.group(1), "生效", name, org, row.get("官方链接", "")))
        if row.get("最新修订日期"):
            hit = DATE_RE.search(row["最新修订日期"])
            if hit:
                events.append((hit.group(1), "最新修订", name, org, row.get("官方链接", "")))

    if not events:
        return "_这两列暂无可用日期。_"

    events.sort(key=lambda item: item[0], reverse=True)
    shown = events[:40]

    lines = ["| 日期 | 变化类型 | 市场 | 法规 |", "|---|---|---|---|"]
    for date, kind, name, org, link in shown:
        label = "[" + name + "](" + link + ")" if link else name
        lines.append("| `" + date + "` | " + kind + " | " + org + " | " + label + " |")

    if len(events) > len(shown):
        lines.append("")
        lines.append("<sub>共 " + str(len(events)) + " 个日期节点，此处展示最近 " + str(len(shown)) + " 条。</sub>")

    return "\n".join(lines)


# --------------------------------------------------------------------------
# 主处理函数
# --------------------------------------------------------------------------
def handle(category, market_label):
    rows = select_rows(category, market_label)
    return (
        render_summary(rows, category, market_label),
        render_list(rows),
        render_timeline(rows),
    )


# --------------------------------------------------------------------------
# 界面（必须存在模块级变量 demo）
# --------------------------------------------------------------------------
INTRO = """# 🛰️ 出海合规雷达 ComplianceRadar

**输入「品类 + 市场」，输出适用法规清单 —— 每条结论强制附官方原文链接。**

卖家出海最怕的不是「法规多」，而是「不知道哪条法规管我、什么时候生效、原文在哪」。本工具把这三件事一次说清。

> **数据来源**：欧盟 EUR-Lex、美国 eCFR 等官方公开渠道。
> **免责声明**：本工具输出为信息检索与整理结果，**不构成法律意见**；做出合规决策前请咨询持牌专业人士或向主管机关核实。
"""

with gr.Blocks(title="出海合规雷达 ComplianceRadar") as demo:
    gr.Markdown(INTRO)

    with gr.Row():
        category_box = gr.Dropdown(
            choices=CATEGORY_CHOICES,
            value="儿童玩具",
            label="① 选择品类",
        )
        market_box = gr.Dropdown(
            choices=[ALL_MARKETS] + list(MARKET_CHOICES.keys()),
            value="欧盟（EU）",
            label="② 选择市场",
        )
        search_btn = gr.Button("🔍 查询适用法规", variant="primary", scale=0)

    summary_md = gr.Markdown()

    with gr.Tabs():
        with gr.Tab("📋 适用法规清单"):
            list_md = gr.Markdown()
        with gr.Tab("🕒 变化时间线"):
            timeline_md = gr.Markdown()

    search_btn.click(
        fn=handle,
        inputs=[category_box, market_box],
        outputs=[summary_md, list_md, timeline_md],
    )

    # 页面加载时先跑一次默认查询（儿童玩具 × 欧盟），保证打开即有内容
    demo.load(
        fn=handle,
        inputs=[category_box, market_box],
        outputs=[summary_md, list_md, timeline_md],
    )

    gr.Markdown(
        "---\n"
        "<sub>ComplianceRadar · 浙客松「AI+X 破界黑客松」· 天猫校园 OPC 产业孵化赛道</sub>"
    )


if __name__ == "__main__":
    demo.launch()
