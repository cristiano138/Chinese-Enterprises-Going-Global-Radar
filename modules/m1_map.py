# -*- coding: utf-8 -*-
"""
M1 · 合规地图（modules/m1_map.py）

一句话：卖家选「品类 + 市场」→ 输出**适用法规清单**，每条带官方链接。

输入：商品类目（5 个行业品类 / 2 个横切维度）+ 目标市场（欧盟 / 美国）
输出：适用法规清单，每条含 README 规定的 8 个字段 ——
      法规中文名 / 官方英文标题 / 官方编号 / CELEX 号 / ELI 链接 /
      OJ 出处 / 生效日期 / 是否仍有效

链路（README「一次查询的完整链路」）：
    ① 用户输入 品类 + 市场
    ② 结构化查表（确定性）—— 按「类目」「机构」两列精确筛选，不联网、零成本
    ③ 结果集送 LLM（可选）—— 只为每条写一句中文卖家提示，不得增删法规
    ④ 引用对齐（确定性）—— 逐条校验回挂官方链接，无链接一律不输出
    ⑤ 输出清单

边界：
    · 范围外的类目/市场 → 明示不支持，不做硬编答案
    · 全部结论附统一免责声明
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)

from core import corpus, llm, verify  # noqa: E402

DISCLAIMER = ("本清单仅供参考，不构成法律意见。请以官方原文为准，"
              "并由专业人员复核后再作合规决策。")

# M1 输出字段的中文表头（与 README 功能模块表的 8 项严格对应）
FIELD_LABELS = [
    "法规中文名",
    "官方英文标题",
    "官方编号",
    "CELEX号",
    "ELI链接",
    "官方原文链接",
    "OJ出处",
    "生效日期",
    "是否仍有效",
]


def _extract_oj(row):
    """取 OJ 出处。语料里 OJ 信息在「来源类型」与备注中，做保守提取。"""
    src = row.get("来源类型", "")
    if "OJ" in src:
        return "欧盟官方公报（OJ）"
    if "eCFR" in src:
        return "美国联邦法规电子版（eCFR，电子版非官方法律版）"
    return src or "官方未标注"


def _validity_text(row):
    """把「现行效力」翻译成卖家看得懂的一句话。"""
    v = row.get("现行效力", "") or "官方未标注"
    if v == "已废止":
        return "⚠️ 已废止（不要再作为合规依据）"
    if v == "待确认":
        return "❓ 效力待确认（需人工复核）"
    if v.startswith("现行有效（持续修订）"):
        return "✅ 现行有效（持续修订）"
    if v.startswith("现行有效"):
        return "✅ 现行有效"
    return v


def to_record(row, tips=None):
    """把一条语料记录 → M1 的标准输出记录（8 字段 + 来源链接）。"""
    key = row.get("CELEX号") or row.get("官方编号")
    urls = verify.official_urls_in(row)

    rec = {
        "key": key,
        "法规中文名": row.get("法规中文名", "") or "官方未标注",
        "官方英文标题": row.get("官方标题（英文）", "") or "官方未标注",
        "官方编号": row.get("官方编号", "") or "官方未标注",
        "CELEX号": row.get("CELEX号", "") or "（美国法规无 CELEX 号，属正常）",
        "ELI链接": row.get("ELI标识", "") or "（ELI 为欧盟专属标识）",
        "官方原文链接": row.get("官方链接", ""),
        "OJ出处": _extract_oj(row),
        "生效日期": row.get("生效日期", "") or "官方未标注",
        "是否仍有效": _validity_text(row),
        # 附加（非 README 八项，但对卖家有用，且全部来自官方数据）
        "监管机构": row.get("监管机构", "") or row.get("机构", ""),
        "类目": row.get("类目", ""),
        "链接状态": row.get("链接可打开", "") or "官方未标注",
        "卖家提示": (tips or {}).get(key, ""),
        "全部官方链接": urls,
    }
    # 内部用：保留原始备注里的技术说明，供「详情」展开
    rec["_raw_备注"] = row.get("备注／问题", "")
    return rec


def query(category, market, use_llm=True):
    """M1 主入口。

    返回 dict：
        ok            —— 是否成功（False 表示范围外输入）
        reason        —— 失败原因
        品类 / 市场     —— 回显
        primary       —— 主体法规记录（该品类）
        cross         —— 横切法规记录（标签标识 / 通用，所有品类都适用）
        llm           —— 模型调用元信息（成功/失败/缓存）
        dropped       —— 被引用对齐拦下的条目（正常情况下为 0）
        stats         —— 本市场语料统计
    """
    res = corpus.search(category, market)

    if not res["ok"]:
        return {"ok": False, "reason": res["reason"],
                "品类": category, "市场": market,
                "primary": [], "cross": [], "llm": None,
                "dropped": [], "stats": {}}

    # ── ④ 引用对齐（先过底线，再谈润色）─────────────────────
    prim_kept, prim_drop = verify.filter_rows(res["primary"])
    cross_kept, cross_drop = verify.filter_rows(res["cross"])
    dropped = [(r.get("CELEX号") or r.get("官方编号"), why)
               for r, why in (prim_drop + cross_drop)]

    # ── ③ 送 LLM 写卖家提示（可选，失败自动降级）────────────
    all_rows = prim_kept + cross_kept
    tips, meta = ({}, {"ok": True, "reason": "未启用", "cached": False})
    if use_llm:
        tips, meta = llm.m1_tips(all_rows)
        # 防幻觉第二道关：LLM 返回的键必须落在语料库真实键集合内
        corpus_keys = {(r.get("CELEX号") or r.get("官方编号")) for r in all_rows}
        aligned, rejected = verify.align_output(
            [{"key": k} for k in tips.keys()], corpus_keys)
        valid_keys = {a["key"] for a in aligned}
        tips = {k: v for k, v in tips.items() if k in valid_keys}
        for it, why in rejected:
            dropped.append((it.get("key"), why))

    return {
        "ok": True,
        "reason": "",
        "品类": res["category"],
        "市场": res["market"],
        "market_code": res["code"],
        "primary": [to_record(r, tips) for r in prim_kept],
        "cross": [to_record(r, tips) for r in cross_kept],
        "llm": meta,
        "dropped": dropped,
        "stats": {
            "主体条数": len(prim_kept),
            "横切条数": len(cross_kept),
            "本市场语料总数": len(res["primary"]) + len(res["cross"]),
        },
    }


# ── 渲染成文本（供 CLI 与自检使用）─────────────────────────────
def render_text(result):
    """把 M1 结果渲染成人类可读文本。"""
    lines = []
    if not result["ok"]:
        lines.append("❌ " + result["reason"])
        lines.append("")
        lines.append("支持的品类：" + "、".join(corpus.ALL_QUERYABLE))
        lines.append("支持的市场：" + "、".join(corpus.SUPPORTED_MARKETS.keys()))
        return "\n".join(lines)

    lines.append("=" * 78)
    lines.append(f"  M1 合规地图 · {result['品类']} × {result['市场']}")
    lines.append("=" * 78)
    lines.append(f"  主体法规 {result['stats']['主体条数']} 条"
                 f" · 横切法规 {result['stats']['横切条数']} 条")
    lm = result.get("llm") or {}
    if lm.get("ok") and result["primary"] and result["primary"][0].get("卖家提示"):
        tag = "（缓存命中）" if lm.get("cached") else ""
        lines.append(f"  中文提示：由模型生成{tag} —— 仅作润色，不参与事实判断")
    elif lm and not lm.get("ok") and lm.get("reason") != "未启用":
        lines.append(f"  ⚠️ 模型不可用（{lm.get('reason')}），"
                     f"已降级为原始清单 —— 数据依然完整可核验")
    lines.append("")

    def block(title, records):
        if not records:
            return
        lines.append("─" * 78)
        lines.append(f"  【{title}】{len(records)} 条")
        lines.append("─" * 78)
        for i, r in enumerate(records, 1):
            lines.append(f"  {i:>2}. {r['法规中文名']}    {r['是否仍有效']}")
            if r.get("卖家提示"):
                lines.append(f"      · {r['卖家提示']}")
            lines.append(f"      官方英文标题 : {r['官方英文标题'][:110]}")
            lines.append(f"      官方编号     : {r['官方编号']}")
            lines.append(f"      CELEX 号     : {r['CELEX号']}")
            lines.append(f"      ELI 链接     : {r['ELI链接']}")
            lines.append(f"      OJ 出处      : {r['OJ出处']}")
            lines.append(f"      生效日期     : {r['生效日期']}")
            lines.append(f"      监管机构     : {r['监管机构']}")
            lines.append(f"      官方链接     : {r['官方原文链接']}")
            lines.append("")

    block(f"{result['品类']} · 直接适用法规", result["primary"])
    if result["cross"]:
        block("横切法规（标签标识 / 通用，任何品类都适用）", result["cross"])

    if result["dropped"]:
        lines.append("─" * 78)
        lines.append(f"  ⛔ 被引用对齐拦下 {len(result['dropped'])} 条（无官方链接，不输出）")
        for k, why in result["dropped"]:
            lines.append(f"      - {k}：{why}")
        lines.append("")

    lines.append("─" * 78)
    lines.append(f"  ⚖️ {DISCLAIMER}")
    lines.append("=" * 78)
    return "\n".join(lines)


if __name__ == "__main__":
    cat = sys.argv[1] if len(sys.argv) > 1 else "儿童玩具"
    mkt = sys.argv[2] if len(sys.argv) > 2 else "欧盟"
    no_llm = "--no-llm" in sys.argv
    print(render_text(query(cat, mkt, use_llm=not no_llm)))
