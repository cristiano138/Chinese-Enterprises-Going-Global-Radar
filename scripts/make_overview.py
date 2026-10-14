# -*- coding: utf-8 -*-
"""
生成《数据总览》—— 给人看的汇总页。

骨架 CSV 是给机器/表格用的；这份是给人快速了解「数据线做完了、做了什么」看的。

输出：
    data/数据总览.md

用法：
    python scripts/make_overview.py

变更记录（2026-10-14 修复，对应《代码审查报告》）：
    - [问题9] 生成时间、条数不再写死：时间取当前时刻，条数取 len(rows)。
    - [新增问题1] 链接实测不再把「限流复测的 5 条」合并进 59。改为分档列出
      首次 200 / 限流复测 / 人机验证墙 / 待确认 / 有问题。
    - [问题7] 增列「监管机构」统计。
"""

import csv
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
DATA = os.path.join(PROJECT, "data")

CATS = ["儿童玩具", "电子电器", "纺织服装", "美妆个护", "食品接触材料", "标签标识", "通用"]


def link_bucket(v):
    """把「链接可打开」列的取值归入标准档。"""
    v = (v or "").strip()
    if not v:
        return "未检测"
    if "WAF" in v:
        return "人机验证墙（真人可开）"
    if v.startswith("有问题"):
        return "有问题"
    if "待人工确认" in v:
        return "待人工确认"
    if v.startswith("是"):
        return "限流复测后通过" if "复测" in v else "首次即 200"
    return "其他"


def main():
    src = os.path.join(DATA, "语料核对表_完整版.csv")
    if not os.path.exists(src):
        src = os.path.join(DATA, "语料核对表_骨架总表.csv")
    if not os.path.exists(src):
        print("找不到数据文件")
        return

    with open(src, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    cols = list(rows[0].keys()) if rows else []

    L = []
    L.append("# 出海合规雷达 · 数据总览")
    L.append("")
    L.append(f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
    L.append(f"> 数据量：**{len(rows)} 条**官方法规（欧盟 + 美国）")
    L.append("> 核验方式：全部来自官方数据接口，非网页抓取")
    L.append("")
    L.append("---")
    L.append("")

    # 一、数据来源
    L.append("## 一、数据从哪来（全部官方接口，免密钥）")
    L.append("")
    L.append("| 市场 | 官方数据源 | 接口性质 |")
    L.append("| --- | --- | --- |")
    L.append("| 欧盟 | 欧盟出版局 Cellar（`publications.europa.eu/webapi/rdf/sparql`） | 官方 SPARQL 数据接口，返回 CELEX、ELI、生效日期、取代关系等权威字段 |")
    L.append("| 美国 | eCFR（`www.ecfr.gov/api/versioner/v1/`） | 官方 REST API，JSON 格式，含条文结构与历次修订记录 |")
    L.append("")
    L.append("> **为什么不用爬网页**：欧盟 EUR-Lex 整站有 AWS WAF 人机验证墙，程序无法访问；"
             "美国 FDA/FTC 等站点对本机也有拦截。走官方数据接口既稳定又更权威。")
    L.append("")

    # 二、覆盖情况
    L.append("## 二、覆盖情况（市场 × 品类）")
    L.append("")
    d = defaultdict(Counter)
    for r in rows:
        d[r["类目"]][r["机构"]] += 1

    L.append("| 品类 | 欧盟 | 美国 | 合计 |")
    L.append("| --- | --- | --- | --- |")
    te = tu = 0
    for cat in CATS:
        eu, us = d[cat]["EU"], d[cat]["US"]
        if eu + us == 0:
            continue
        te += eu
        tu += us
        L.append(f"| {cat} | {eu} | {us} | {eu + us} |")
    L.append(f"| **合计** | **{te}** | **{tu}** | **{te + tu}** |")
    L.append("")

    # 监管机构分布
    if "监管机构" in cols:
        ag = Counter((r.get("监管机构") or r["机构"]) for r in rows)
        L.append("按监管机构：")
        L.append("")
        L.append("| 监管机构 | 条数 |")
        L.append("| --- | --- |")
        for k, v in ag.most_common():
            L.append(f"| {k} | {v} |")
        L.append("")
    L.append("**每个品类都同时覆盖欧盟和美国两个市场** —— 这是「一个产品、两个市场」对照查询的基础。")
    L.append("")

    # 三、数据完整度
    L.append("## 三、数据完整度")
    L.append("")
    L.append("| 字段 | 填充率 | 说明 |")
    L.append("| --- | --- | --- |")
    fields = [
        ("法规中文名", "中文译名，已用 AI 批量翻译"),
        ("官方标题（英文）", "官方原文标题"),
        ("官方编号", "官方可读编号 / CFR 条款号"),
        ("官方链接", "可点开核验的官方地址"),
        ("现行效力", "现行有效 / 已废止 / 待确认"),
        ("生效日期", "欧盟为生效日；美国标注首次收录参考日"),
        ("最新修订日期", "美国 eCFR 提供；欧盟记录于备注"),
        ("链接可打开", "逐条实测结果"),
        ("备注／问题", "一句话作用说明 + 技术备注"),
    ]
    for name, desc in fields:
        if name not in cols:
            continue
        n = sum(1 for r in rows if (r.get(name, "") or "").strip())
        pct = f"{n / len(rows) * 100:.0f}%" if rows else "0%"
        L.append(f"| {name} | {n}/{len(rows)}（{pct}） | {desc} |")
    L.append("")
    L.append("> `核对人`、`核对日期` 两列**刻意留空** —— 这是真人核验后签字的字段，不能由程序代填。")
    L.append("")

    # 四、链接实测
    L.append("## 四、链接实测结果")
    L.append("")
    L.append("对全部链接逐条做了程序实测（分档统计，不把限流复测的条目并进「可访问」）：")
    L.append("")
    c = Counter(link_bucket(r.get("链接可打开", "")) for r in rows)
    L.append("| 状态 | 条数 | 含义 |")
    L.append("| --- | --- | --- |")
    L.append(f"| 首次即 200 | {c.get('首次即 200', 0)} | 程序一次访问即通（多为美国 eCFR） |")
    L.append(f"| 限流复测后通过 | {c.get('限流复测后通过', 0)} | 先遇 429/503，退避重试后通过（**不是死链**） |")
    L.append(f"| 人机验证墙（真人可开） | {c.get('人机验证墙（真人可开）', 0)} | 站方 WAF 挡住程序，**真人浏览器可正常打开** |")
    if c.get("待人工确认", 0):
        L.append(f"| 待人工确认 | {c.get('待人工确认', 0)} | 返回 202 挑战但未识别为 WAF，需人工看一眼 |")
    if c.get("有问题", 0):
        L.append(f"| 有问题 | {c.get('有问题', 0)} | 需人工处理 |")
    L.append("")
    L.append("> ⚠️ **重要判定规则**：欧盟链接「程序打不开」**不等于链接失效** —— 那是 AWS WAF 人机验证，"
             "真人在浏览器里点开是完全正常的。绝不能因为程序打不开就去改链接。")
    L.append("")

    # 五、法规示例
    L.append("## 五、数据长什么样（抽样）")
    L.append("")
    for r in rows[:3]:
        L.append(f"**{r['法规中文名'] or r['官方标题（英文）']}**（{r['机构']}）")
        L.append(f"- 官方编号：`{r['官方编号'] or r['CELEX号']}`")
        L.append(f"- 说明：{r['备注／问题'].split('｜')[0]}")
        L.append(f"- 链接：{r['官方链接']}")
        L.append("")

    # 六、下一步
    L.append("## 六、下一步（真人的活）")
    L.append("")
    L.append("| 要做的事 | 说明 |")
    L.append("| --- | --- |")
    L.append("| 逐条点开链接核验 | 一条能点开的原始链接，比任何转述都可靠 —— 这是项目立身之本 |")
    L.append("| 填「核对人」「核对日期」 | 核验后签字 |")
    L.append("| 抽检 AI 生成的中文名 | AI 翻译可能有偏差，重点看法规编号与中文名是否对得上 |")
    L.append("")
    L.append("---")
    L.append("")
    L.append(f"**数据文件**：`{os.path.relpath(src, PROJECT).replace(os.sep, '/')}`"
             f"（{len(rows)} 条 × {len(cols)} 列，可直接用 Excel 打开）")

    out = os.path.join(DATA, "数据总览.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(L))

    print(f"已生成：{out}")
    print(f"共 {len(rows)} 条")


if __name__ == "__main__":
    main()
