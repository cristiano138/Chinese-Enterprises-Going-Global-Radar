# -*- coding: utf-8 -*-
"""
生成「欧盟待补清单」——给人工直接照着填的作业单（条数按实际数据动态生成）。

用途：
    骨架总表是给机器读的（18 列很宽），人填的时候不好用。
    本脚本把它转成一张**人看着就懂的动作清单**：
    每条列出 已知信息 + 待填空白 + 一个「中文提示」（这条法规大概管什么）。

输出：
    data/欧盟待补清单.md

用法：
    python scripts/make_todo_eu.py
"""

import csv
import os
import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
DATA = os.path.join(PROJECT, "data")

# 中文提示：给每条法规一句话说明它管什么（供填表人参考，不当结论用）
HINTS = {
    "32025R2509": ("儿童玩具", "玩具的机械物理性能、化学性能、燃烧性能等安全要求。**2026-01-01 起生效，2030-08-01 完全取代旧指令 2009/48/EC。**"),
    "32009L0048": ("儿童玩具", "旧版玩具安全指令。已被 2025/2509 取代，2030-08-01 起废止 —— **引用时要提醒卖家这条快过期了**。"),
    "32023R0988": ("通用", "通用产品安全法规 GPSR。**覆盖所有消费品**，跨境电商卖家最常踩的一条。"),
    "32014L0053": ("电子电器", "无线电设备指令 RED。带无线功能的产品（蓝牙/WiFi/遥控）必备。"),
    "32011L0065": ("电子电器", "限制有害物质指令 RoHS。限制铅、汞、镉等 10 种有害物质。"),
    "32012L0019": ("电子电器", "废弃电子电气设备指令 WEEE。管回收和处理，卖家要注册。"),
    "32014L0030": ("电子电器", "电磁兼容指令 EMC。产品不能产生干扰、也不能被干扰。"),
    "32009L0125": ("电子电器", "生态设计框架指令。能效、待机功耗等要求。"),
    "32011R1007": ("纺织服装", "纺织品纤维名称法规。**衣服的洗标内容必须合规**。"),
    "32008R1272": ("纺织服装", "化学品分类标签包装法规 CLP。涉及化学品的标签要求。"),
    "32006R1907": ("纺织服装", "化学品注册评估授权限制法规 REACH。**纺织品染料、偶氮等限用物质的重灾区**。"),
    "32009R1223": ("美妆个护", "化妆品法规。**化妆品卖欧盟的准入门槛**，要求极多。"),
    "32004R1935": ("食品接触材料", "食品接触材料框架法规。所有会接触食品的材料都受管。"),
    "32011R0010": ("食品接触材料", "食品接触塑料材料法规。塑料饭盒、保鲜膜等具体规定。"),
    "32005R0396": ("食品接触材料", "食品接触材料良好生产规范 GMP。生产环节的要求。"),
    "32011R1169": ("标签标识", "食品信息消费者法规。**食品标签怎么标注**的规定。"),
    "31994L0011": ("标签标识", "包装及包装废弃物指令。**欧盟新包装法规 PPWR 正在取代它**，要留意。"),
}


def main():
    src = os.path.join(DATA, "语料核对表_骨架总表.csv")
    if not os.path.exists(src):
        print(f"找不到 {src}，请先运行 merge_corpus.py")
        return

    with open(src, encoding="utf-8-sig") as f:
        rows = [r for r in csv.DictReader(f) if r["机构"] == "EU"]

    # 按类目分组
    groups = {}
    for r in rows:
        groups.setdefault(r["类目"], []).append(r)

    lines = []
    lines.append(f"# 欧盟 {len(rows)} 条待补清单（作业单）")
    lines.append("")
    lines.append("> 数据已经抓好，你只要**打开链接 → 读 → 填 3 个空**。")
    lines.append(f"> 每条约 5 分钟，{len(rows)} 条约 {len(rows) * 5 / 60:.1f} 小时。")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 怎么填（先看这个）")
    lines.append("")
    lines.append("每条要补 3 处：")
    lines.append("")
    lines.append("| 列名 | 填什么 | 举例 |")
    lines.append("| --- | --- | --- |")
    lines.append("| **法规中文名** | 官方标题翻译成中文 | （对 2009/48/EC）《玩具安全指令》 |")
    lines.append("| **备注／问题** | 一句话：这条管什么 | 管玩具的机械物理性能安全要求 |")
    lines.append("| **核对状态** | 看完链接后填 `已核对` | 已核对 |")
    lines.append("")
    lines.append("⚠️ **两个重要提醒**：")
    lines.append("")
    lines.append("1. **欧盟链接程序打不开是正常的**（有人机验证墙），用**浏览器**点开就行。")
    lines.append("2. 「中文提示」是助手给的参考，**不是结论** —— 你要以打开链接看到的内容为准。")
    lines.append("")
    lines.append("---")
    lines.append("")

    n = 0
    for cat, items in groups.items():
        lines.append(f"## 类目：{cat}（{len(items)} 条）")
        lines.append("")
        for r in items:
            n += 1
            celex = r["CELEX号"]
            hint_cat, hint = HINTS.get(celex, ("", "（无提示，看链接内容）"))
            lines.append(f"### {n}. `{celex}`　官方编号：{r['官方编号']}")
            lines.append("")
            lines.append(f"- **官方标题（英文）**：{r['官方标题（英文）']}")
            lines.append(f"- **官方链接**：{r['官方链接']}")
            lines.append(f"- **生效日期**：{r['生效日期']}")
            lines.append(f"- **ELI 标识**：{r['ELI标识']}")
            lines.append(f"- **链接状态**：{r['链接可打开']}")
            lines.append("")
            lines.append(f"💡 **中文提示**：{hint}")
            lines.append("")
            lines.append("✏️ 待填：")
            lines.append("```")
            lines.append("法规中文名：")
            lines.append("备注／问题（这条管什么）：")
            lines.append("核对状态：")
            lines.append("核对人：")
            lines.append("核对日期：")
            lines.append("```")
            lines.append("")
        lines.append("---")
        lines.append("")

    lines.append("## 全部填完后的检查")
    lines.append("")
    lines.append(f"- [ ] {len(rows)} 条都填了「法规中文名」")
    lines.append(f"- [ ] {len(rows)} 条都填了「备注／问题」")
    lines.append(f"- [ ] {len(rows)} 条都点开过链接")
    lines.append(f"- [ ] {len(rows)} 条都填了「核对人」「核对日期」")
    lines.append("- [ ] 特别留意：`32009L0048`（旧玩具指令，即将废止）和 `31994L0011`（包装指令，正被取代）")
    lines.append("")

    out = os.path.join(DATA, "欧盟待补清单.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"已生成：{out}")
    print(f"共 {len(rows)} 条，分 {len(groups)} 个类目")
    for cat, items in groups.items():
        print(f"  {cat}: {len(items)} 条")


if __name__ == "__main__":
    main()
