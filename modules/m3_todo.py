# -*- coding: utf-8 -*-
"""
M3 · 待办清单（modules/m3_todo.py）

一句话：卖家选「品类 + 市场」→ 输出**可执行动作清单**，
每条含 动作 / 适用条件 / 执行时点 / 来源条款 / 原文摘录 / 官方原文。

输入：商品类目 + 目标市场
输出：可执行动作列表 ——
      · 每条动作都回挂**来源条款的官方链接**（点击即回到原文）
      · 按 动作类型 分组、按 紧迫度 排序
      · 卡片默认折叠，点击展开完整证据链（PRD 附录 D5-1）
      · 支持导出 CSV（PRD 附录 D3 严格 10 列 + UTF-8 BOM + 防公式注入）

链路（与 M1/M2 同构）：
    ① 用户输入 品类 + 市场
    ② 结构化查表（确定性）—— core/corpus.py
    ③ 动作候选抽取（确定性）—— core/actions.py 判定「哪些条目能落到动作」
    ④ 送 LLM（可选）—— 把法条语言改写成动词开头的可执行短句
    ⑤ 引用对齐（确定性）—— 逐条校验回挂官方链接，无链接一律不输出
    ⑥ 输出 / 导出

PRD 关键约束：
    - D3：本品仅导出 CSV，不做 PDF（第 9 节明确）
    - D3：CSV 10 列固定顺序 + 文件名 ComplianceRadar_<EU|US>_<类目>_<YYYYMMDD>.csv
    - D3：= + - @ 开头的单元格加文本转义
    - D5-1：待办卡片默认折叠，点开展开完整证据链
    - F1-3：≥3 项不同动作类型 + 适用条件 + 条款依据

诚实标注：
    - 仅导出 CSV。需要 PDF/打印请用 CSV → Excel → 另存为 PDF。
"""

import csv
import hashlib
import io
import os
import re
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)

from core import actions as core_actions  # noqa: E402
from core import corpus, llm, verify, snapshot  # noqa: E402
from core.copy_zh import (  # noqa: E402
    msg_no_input, msg_category_out_of_scope, msg_market_out_of_scope,
    msg_no_audit_todo, msg_conditions_pending, msg_export_no_selection,
    msg_partial_pending,
)

# ── CSV 导出契约（PRD 附录 D3） ──────────────────────────────────
# 固定列顺序，不得更改
CSV_COLUMNS = [
    "商品类目",
    "目标市场",
    "动作",
    "适用条件",
    "执行时点",
    "官方编号",
    "来源条款",
    "官方链接",
    "数据截止时间",
    "免责声明",
]

# 文件名格式（PRD D3）：
# ComplianceRadar_<EU或US>_<类目>_<YYYYMMDD>.csv
def csv_filename(category: str, market: str, today=None) -> str:
    today = today or date.today()
    market_token = "EU" if market == "欧盟" else "US"
    cat_token = (category or "全部").replace("/", "_")
    return f"ComplianceRadar_{market_token}_{cat_token}_{today.strftime('%Y%m%d')}.csv"


# Excel 公式注入转义：= + - @ 开头的单元格前缀加 '
_DANGER_PREFIXES = ("=", "+", "-", "@")


def _csv_safe(value):
    """按 PRD D3：防电子表格把内容解释为公式（= + - @）。"""
    if value is None:
        return ""
    s = str(value)
    if s and s[0] in _DANGER_PREFIXES:
        return "'" + s
    return s


def query(category, market, use_llm=True, today=None):
    """M3 主入口。

    返回 dict：
        ok        —— 是否成功（False 表示范围外输入）
        品类 / 市场
        动作       —— 动作记录列表（已排序、已分组信息齐全）
        分组       —— [(动作类型, [动作, ...]), ...]
        未产出     —— 落不到动作、因此不上清单的条目（如实上报）
        待确认     —— PRD D5-2：本次查询先落盘的待确认事项（暂用规格条目）
        dropped   —— 被引用对齐拦下的条目
        llm       —— 模型元信息
        stats     —— 条数、涉及法规数、紧迫度分布
        header    —— 顶部元数据（PRD D3）
    """
    today = today or date.today()

    res = corpus.search(category, market)
    if not res["ok"]:
        cat = (category or "").strip()
        mkt = (market or "").strip()
        if not cat and not mkt:
            reason = msg_no_input()
        elif mkt and mkt not in corpus.SUPPORTED_MARKETS:
            reason = msg_market_out_of_scope(mkt)
        else:
            reason = msg_category_out_of_scope(cat) if cat else msg_no_input()
        return {"ok": False, "reason": reason, "品类": category,
                "市场": market, "动作": [], "分组": [], "未产出": [],
                "待确认": [], "dropped": [], "llm": None, "stats": {},
                "header": snapshot.header(cat or "（空）", mkt or "（空）",
                                          m3_status=snapshot.MODULE_ERROR)}

    # ── ⑤ 引用对齐先过（红线优先于润色）────────────────────
    # M3 是可执行清单：只允许已经人工核对的语料进入动作层；待核对记录
    # 仍可在 M1/M5/M6 作为候选展示，但不能被导出成上线依据。
    kept, drop = verify.filter_rows(
        res["primary"] + res["cross"], require_audited=True
    )
    dropped = [(core_actions.row_key(r), why) for r, why in drop]
    pending_audit_count = sum(
        1 for r in (res["primary"] + res["cross"])
        if (r.get("核对状态") or "").strip() != "已核对"
    )

    # ── ③ 动作候选抽取（确定性）───────────────────────────
    cands, skipped = core_actions.collect(kept, today=today)

    # ── ④ 送 LLM 改写成可执行动作（可选，失败自动降级）──────
    rewritten, meta = ({}, {"ok": True, "reason": "未启用", "cached": False})
    if use_llm and cands:
        rewritten, meta = llm.m3_actions(cands)
        if rewritten:
            corpus_keys = {c["key"] for c in cands}
            aligned, rejected = verify.align_output(
                [{"key": k} for k in rewritten], corpus_keys)
            valid = {a["key"] for a in aligned}
            rewritten = {k: v for k, v in rewritten.items() if k in valid}
            for it, why in rejected:
                dropped.append((it.get("key"), why))

    for c in cands:
        new_text = (rewritten.get(c["key"]) or "").strip()
        if new_text:
            c["动作"] = new_text
            c["动作来源"] = "模型改写"
        else:
            c["动作来源"] = "规则抽取"
        c["动作"] = c["动作"].strip()
        # 标识依据业务字段生成，不随候选排序或展示序号变化。
        identity = "|".join((c.get("市场", ""), c.get("类目", ""),
                             c.get("key", ""), c.get("动作类型", "")))
        c["action_id"] = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]

    grouped = core_actions.group_by_type(cands)

    urgency_count = {}
    for c in cands:
        urgency_count[c["紧迫度"]] = urgency_count.get(c["紧迫度"], 0) + 1

    # PRD D5-2：待确认事项占位 —— 本期暂按"涉及横切规则 + 类别性质"启发式列出
    # 注：本次实现仅在产品层做透明提示；正式待确认事项由张审核后入库（PRD F2）
    pending_items = []
    if any(c.get("动作类型") in ("切换替换", "合规确认") for c in cands):
        pending_items.append({
            "需确认": "商品所属品类与经营者身份（制造商 / 进口商 / 销售者）",
            "影响": "不同身份的义务不同 —— 部分动作（如注册备案、授权代表）仅对特定身份适用",
            "如何核对": "对照经营者所在地与商品流通链路，确认身份后再勾选对应待办",
        })

    # M3 模块状态
    if len(cands) == 0:
        m3_status = snapshot.MODULE_EMPTY
    elif len(skipped) > 0:
        m3_status = snapshot.MODULE_PARTIAL
    else:
        m3_status = snapshot.MODULE_READY

    return {
        "ok": True,
        "reason": "",
        "品类": res["category"],
        "市场": res["market"],
        "today": today,
        "动作": cands,
        "分组": grouped,
        "未产出": skipped,
        "待确认": pending_items,
        "dropped": dropped,
        "llm": meta,
        "stats": {
            "动作条数": len(cands),
            "涉及法规数": len({c["官方编号"] for c in cands}),
            "未产出条数": len(skipped),
            "候选法规条数": len(kept),
            "待核对法规条数": pending_audit_count,
            "紧迫度分布": urgency_count,
        },
        "header": snapshot.header(res["category"], res["market"],
                                  m3_status=m3_status),
    }


# ── 导出 CSV（PRD 附录 D3 严格按 10 列）──────────────────────────
def export_csv(result, selected_action_ids=None):
    """导出 CSV 字节流。

    返回 (filename, bytes) 或抛 RuntimeError。
    文件名格式：ComplianceRadar_<EU|US>_<类目>_<YYYYMMDD>.csv
    编码：UTF-8 BOM（Excel 双击不乱码）
    列：PRD D3 规定的 10 列固定顺序
    防公式注入：= + - @ 开头单元格加文本转义

    无动作/未选择时按 PRD E 节返回错误。
    """
    if not result.get("ok"):
        raise RuntimeError(result.get("reason") or "查询未成功")
    actions_list = result.get("动作", [])
    if not actions_list:
        raise RuntimeError(
            msg_no_audit_todo(result.get("品类", ""), result.get("市场", "")))

    # PRD E：未选择导出条目 → 报错；no 提示不生成空文件
    if selected_action_ids is not None and len(selected_action_ids) == 0:
        raise RuntimeError(msg_export_no_selection())

    # 默认全选（PRD D3：M3 默认选中全部合格待办）
    if selected_action_ids is None:
        selected = list(range(len(actions_list)))
    else:
        # 选择口径（向后兼容四种写法）：
        #   action_id 字符串 → 按稳定标识精确匹配（推荐）
        #   整数            → 按下标
        #   动作文本        → 旧调用方仍可用（文本重复时可能多选，仅作兼容）
        chosen = {str(x).strip() for x in selected_action_ids}
        selected = [
            i for i, a in enumerate(actions_list)
            if (a.get("action_id") in chosen) or str(i) in chosen
            or (a.get("动作") in chosen)
        ]
        if not selected:
            raise RuntimeError("所选待办ID无匹配项，未生成文件。")

    buf = io.StringIO(newline="")
    w = csv.writer(buf, quoting=csv.QUOTE_ALL)
    today = result.get("today") or date.today()
    cutoff = snapshot.DATA_CUTOFF
    cat = result.get("品类", "")
    mkt = result.get("市场", "")
    mkt_code = "EU" if mkt == "欧盟" else "US"

    # 表头（PRD D3 固定 10 列）
    w.writerow(CSV_COLUMNS)

    for idx, action in enumerate(actions_list):
        if idx not in selected:
            continue
        action_text = action["动作"]
        conditions = (action.get("适用条件") or "").strip()
        if not conditions:
            conditions = msg_conditions_pending()
        conditions += "；人工确认：商品属性、经营者身份及条款适用范围"
        source_clause = action["官方编号"] or "（未标注）"
        # 「来源条款」列填中文要点时必须带来源标注：底表没收录条文正文，
        # 这个摘要是 AI 预生成的一句话中文说明，不能让它看起来像条文原文。
        # 没有摘要则回落到原文缺省提示（不编造）。
        excerpt_text = (action.get("证据摘录") or "").strip()
        excerpt = (f"中文要点（AI 预生成，非条文原文）：{excerpt_text}"
                   if excerpt_text else "（以官方原文为准 —— 见官方链接）")

        w.writerow([
            _csv_safe(cat),
            _csv_safe(mkt_code),                # 用 EU/US 编码而非中文
            _csv_safe(action_text),
            _csv_safe(conditions or "（按法规全文判断）"),
            _csv_safe(action.get("期限") or "持续义务（在相关市场提供行为发生前）"),
            _csv_safe(source_clause),
            _csv_safe(excerpt),
            _csv_safe(action.get("来源条款链接", "")),
            _csv_safe(cutoff),
            _csv_safe(snapshot.DISCLAIMER),
        ])

    raw = buf.getvalue().encode("utf-8-sig")  # UTF-8 BOM
    return csv_filename(cat, mkt, today), raw


def csv_filename_for(result, today=None):
    """只生成文件名（便于前端展示）。"""
    return csv_filename(result.get("品类", ""), result.get("市场", ""),
                        today or result.get("today") or date.today())


# ── 渲染成文本（供 CLI 与自检使用）─────────────────────────────
def render_text(result):
    lines = []
    if not result["ok"]:
        lines.append("❌ " + result["reason"])
        return "\n".join(lines)

    s = result["stats"]
    lines.append("=" * 78)
    lines.append(f"  M3 待办清单 · {result['品类']} × {result['市场']}")
    lines.append("=" * 78)
    dist = "　".join(f"{k} {v} 条" for k, v in sorted(s["紧迫度分布"].items(),
                                                    key=lambda x: "高中低".index(x[0])))
    lines.append(f"  动作 {s['动作条数']} 条 · 涉及法规 {s['涉及法规数']} 部"
                 f" · 未产出动作 {s['未产出条数']} 条")
    if dist:
        lines.append(f"  紧迫度：{dist}")
    lines.append(f"  快照 {snapshot.SNAPSHOT_VERSION}　数据截止时间 {snapshot.DATA_CUTOFF}")
    lines.append("")

    idx = 0
    for tname, bunch in result["分组"]:
        lines.append("─" * 78)
        lines.append(f"  【{tname}】{len(bunch)} 条　"
                     f"（{core_actions.TYPE_MEANING.get(tname, '')}）")
        lines.append("─" * 78)
        for a in bunch:
            idx += 1
            dl = f"　⏰ 时限 {a['期限']}" if a.get("期限") else ""
            lines.append(f"  {idx:>2}. [{a['紧迫度']}] {a['动作']}{dl}")
            lines.append(f"      依据《{a['依据法规']}》　{a['官方编号']}")
            lines.append(f"      来源条款链接：{a['来源条款链接']}")
        lines.append("")

    if result["未产出"]:
        lines.append("─" * 78)
        lines.append(f"  ⚠️ 未产出动作 {len(result['未产出'])} 条"
                     f"（落不到明确动作，按规格不上清单 —— 如实列出）")
        for r in result["未产出"]:
            seg0 = (r.get("备注／问题", "") or "").split("｜")[0]
            lines.append(f"      - {r.get('官方编号','')}　{seg0[:56]}")
        lines.append("")

    if result["dropped"]:
        lines.append("─" * 78)
        lines.append(f"  ⛔ 被引用对齐拦下 {len(result['dropped'])} 条（无官方链接，不输出）")
        for k, why in result["dropped"]:
            lines.append(f"      - {k}：{why}")
        lines.append("")

    lines.append("─" * 78)
    lines.append(f"  ⚖️ {snapshot.DISCLAIMER}")
    lines.append(f"  ℹ️  {snapshot.WAF_FOOTER_HINT}")
    lines.append("=" * 78)
    return "\n".join(lines)


if __name__ == "__main__":
    cat = sys.argv[1] if len(sys.argv) > 1 else "儿童玩具"
    mkt = sys.argv[2] if len(sys.argv) > 2 else "欧盟"
    no_llm = "--no-llm" in sys.argv
    res = query(cat, mkt, use_llm=not no_llm)
    print(render_text(res))
    if res["ok"] and "--export" in sys.argv:
        outdir = os.path.join(PROJECT, "data", "export")
        os.makedirs(outdir, exist_ok=True)
        try:
            name, csv_bytes = export_csv(res)
            csv_path = os.path.join(outdir, name)
            with open(csv_path, "wb") as f:
                f.write(csv_bytes)
            print(f"  已导出 CSV：{csv_path}")
        except RuntimeError as e:
            print(f"  ⚠️ CSV 导出跳过：{e}")