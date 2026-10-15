# -*- coding: utf-8 -*-
"""
出海合规雷达 · Web 界面入口（app.py）

四个模块共用同一组输入（品类 + 市场），输出四样东西：
    M1 合规地图     —— 适用法规清单，每条带官方链接
    M2 变化时间线   —— 近期法规变化（含过渡期），每条带官方链接
    M3 待办清单     —— 可执行动作 + 来源条款链接，**仅导出 CSV（PRD 9）**
    M4 对照演示     —— 固定题干 + 真实历史回放（PRD D4）

PRD 关键约束：
    D3   —— 类目入口仅 5 个；CSV 严格 10 列；文件名 ComplianceRadar_*.csv
    D5-1 —— M3 卡片默认折叠，点开展开完整证据链
    E    —— 所有空态文案走 PRD 附录 E 节；不硬编
    9    —— 本期不做 PDF

运行：
    python app.py
（本机默认 http://127.0.0.1:7860；部署到魔搭创空间时自动使用平台端口）
"""

import html
import os
import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from core import corpus, llm, snapshot  # noqa: E402
from modules import (m1_map, m2_timeline, m3_todo, m4_compare,  # noqa: E402
                     m15_router)

import gradio as gr  # noqa: E402

# M3 待办清单的 CSV 导出目录（PRD D3 格式）。
# 写入方：export_m3_csv()，由 M3 页签的 DownloadButton 触发；命令行等价入口见
#         README「m3_todo.py --export」。
# 全部内容都是**生成物**，随时可删、下次导出会重建，不参与任何查表逻辑。
# ⚠️ 刻意**不进 .gitignore**：导出件要能在仓库里直接看到（演示/评审时按日期取用）。
#    副作用是导过一次后 git status 会多出未跟踪文件 —— 这是预期行为，不是脏数据。
EXPORT_DIR = os.path.join(HERE, "data", "export")


# ── 结果渲染成 HTML 卡片 ──────────────────────────────────────
_CSS = """
.cr-wrap { font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif; }
.cr-header { background: #f7faff; border: 1px solid #d6e2f5; border-radius: 8px;
             padding: 10px 14px; font-size: 13px; color: #1f4fa8;
             margin-bottom: 14px; line-height: 1.7; }
.cr-header b { color: #111; }
.cr-header .cr-meta-line { margin: 2px 0; }
.cr-header .cr-meta-scope { font-size: 12.5px; color: #4b5563; }
.cr-header .cr-meta-notes { margin-top: 6px; color: #7a5b00;
                              font-size: 12.5px; }
.cr-header .cr-disclaimer { margin-top: 8px; padding-top: 6px;
                            border-top: 1px dashed #c3d5f5;
                            font-size: 12px; color: #4b5563; }
.cr-mod { display: inline-block; font-size: 11.5px; padding: 1px 6px;
          border-radius: 8px; margin: 0 4px; font-weight: 500; }
.cr-mod-ready   { background:#e8f5e9; color:#1b5e20; border:1px solid #b7dfba; }
.cr-mod-empty   { background:#f6f7f9; color:#41536b; border:1px solid #d5dde6; }
.cr-mod-partial { background:#fff8e1; color:#7a5b00; border:1px solid #f0dfa0; }
.cr-mod-error   { background:#fdecea; color:#8e2118; border:1px solid #f3c2bd; }
.cr-head { font-size: 15px; color:#111; margin: 4px 0 12px; }
.cr-head b { font-size: 17px; }
.cr-sec { margin: 18px 0 8px; font-size: 15px; font-weight: 600; color:#111;
          border-left: 4px solid #2f6fed; padding-left: 8px; }
.cr-card { border: 1px solid #e3e6ea; border-radius: 8px; padding: 12px 14px;
           margin-bottom: 10px; background: #fff; }
.cr-title { font-size: 15px; font-weight: 600; color:#111; margin-bottom: 6px; }
.cr-badge { display:inline-block; font-size:12px; padding:2px 7px; border-radius:10px;
            margin-left:6px; vertical-align: middle; }
.b-ok   { background:#e8f5e9; color:#1b5e20; border:1px solid #b7dfba; }
.b-warn { background:#fdecea; color:#8e2118; border:1px solid #f3c2bd; }
.b-q    { background:#fff8e1; color:#7a5b00; border:1px solid #f0dfa0; }
.b-info { background:#eef3fd; color:#1f4fa8; border:1px solid #c3d5f2; }
.b-ref  { background:#f3f4f6; color:#4b5563; border:1px solid #dcdfe4; }
.b-future { background:#f0e9ff; color:#5b2ea6; border:1px solid #d6c7f5; }
.b-u-high { background:#fdecea; color:#8e2118; border:1px solid #f3c2bd; }
.b-u-mid  { background:#fff8e1; color:#7a5b00; border:1px solid #f0dfa0; }
.b-u-low  { background:#eef2f6; color:#41536b; border:1px solid #d5dde6; }
.cr-tip  { font-size:13px; color:#1f4fa8; background:#f2f6fe; border-radius:5px;
           padding:6px 8px; margin:6px 0; }
.cr-row  { font-size:13px; color:#333; margin:3px 0; line-height:1.55;
           word-break: break-word; }
.cr-k { display:inline-block; min-width:88px; color:#6b7280; }
.cr-row code { background:#f6f7f9; padding:1px 5px; border-radius:4px;
               font-family: ui-monospace, Consolas, monospace; font-size:12.5px; }
.cr-a { color:#2f6fed; text-decoration:none; word-break:break-all; }
.cr-a:hover { text-decoration: underline; }
.cr-note { font-size:12.5px; color:#7a5b00; background:#fffdf3; border:1px solid #f0e6c0;
           border-radius:6px; padding:8px 10px; margin:14px 0; }
.cr-dis { font-size:12.5px; color:#6b7280; border-top:1px dashed #dfe3e8;
          margin-top:16px; padding-top:10px; }
.cr-footer { font-size:12px; color:#41536b; background:#fafbfc; border:1px solid #e6e8ec;
             border-radius:6px; padding:8px 12px; margin-top:14px;
             display:flex; align-items:center; gap:8px; }
.cr-footer b { color:#111; }
.cr-err { border:1px solid #f3c2bd; background:#fdecea; border-radius:8px;
          padding:14px; color:#8e2118; font-size:14px; line-height:1.7; }
.cr-tl { border-left: 2px solid #dfe3e8; margin: 6px 0 0 6px; padding-left: 12px; }
.cr-tl .cr-card { position: relative; }
.cr-date { font-family: ui-monospace, Consolas, monospace; font-size: 14px;
           font-weight: 600; color:#111; }
.cr-empty { font-size:13px; color:#4b5563; background:#f6f7f9; border:1px dashed #dfe3e8;
            border-radius:6px; padding:10px 12px; margin:8px 0; }

/* M3 卡片折叠（D5-1）：<details>/<summary> 样式 */
.cr-action { border: 1px solid #e3e6ea; border-radius: 8px; padding: 10px 14px;
             margin-bottom: 8px; background: #fff; }
.cr-action > summary { cursor: pointer; font-size: 14px; font-weight: 600;
                        color:#111; padding: 4px 0; list-style: none; }
.cr-action > summary::-webkit-details-marker { display: none; }
.cr-action > summary::before { content: "▶ "; color:#9ca3af; font-size: 11px; }
.cr-action[open] > summary::before { content: "▼ "; color:#2f6fed; }
.cr-action > summary .cr-summary-meta { color:#6b7280; font-weight: 400;
                                         font-size: 12px; margin-left: 6px; }
.cr-action .cr-evidence { margin-top: 8px; padding-top: 8px;
                          border-top: 1px dashed #e3e6ea; font-size: 13px; }
.cr-action .cr-evidence > div { margin: 4px 0; line-height: 1.55; }
.cr-action .cr-evidence b { color:#1f4fa8; }
"""


def _e(x):
    """HTML 转义。"""
    return html.escape(str(x if x is not None else ""), quote=False)


def _attr(x):
    return html.escape(str(x if x is not None else ""), quote=True)


def _badge(text, cls="b-ok"):
    return f'<span class="cr-badge {cls}">{_e(text)}</span>'


def _validity_badge(validity):
    if validity.startswith("⚠️"):
        return _badge(validity, "b-warn")
    if validity.startswith("❓"):
        return _badge(validity, "b-q")
    return _badge(validity, "b-ok")


def _link_list(r, key_primary="官方原文链接"):
    links, seen = [], set()
    primary = r.get(key_primary) or ""
    eli = r.get("ELI链接") or ""
    if primary and primary not in seen:
        seen.add(primary)
        links.append(f'<a class="cr-a" href="{_attr(primary)}" target="_blank" '
                     f'rel="noopener">官方原文 →</a>')
    if eli.startswith("http") and eli not in seen:
        seen.add(eli)
        links.append(f'<a class="cr-a" href="{_attr(eli)}" target="_blank" '
                     f'rel="noopener">ELI 永久标识 →</a>')
    return '　'.join(links)


def _model_note(lm, produced_any, kind):
    if lm and lm.get("ok") and produced_any:
        tag = "（缓存命中）" if lm.get("cached") else ""
        what = {"m1": "「卖家提示」", "m2": "「变化摘要 / 影响说明」",
                "m3": "「可执行动作」"}[kind]
        return (f'<div class="cr-note">{what}由大模型生成{tag}，仅作语言润色。'
                f'所有法规编号、日期、链接与结论均来自官方数据，未经模型改动；'
                f'模型返回的任何语料库之外的编号都会被引用对齐拦下。</div>')
    if lm and not lm.get("ok") and lm.get("reason") != "未启用":
        return (f'<div class="cr-note">⚠️ 模型链路不可用'
                f'（{_e(lm.get("reason"))}），已自动降级 —— '
                f'数据完整、链接可核验，演示不中断。</div>')
    return ""


def _dropped_note(dropped):
    if not dropped:
        return ""
    items = "".join(f'<li>{_e(k)}：{_e(why)}</li>' for k, why in dropped)
    return ('<div class="cr-note">⛔ 引用对齐拦下 '
            f'{len(dropped)} 条（无官方链接 / 语料库外的编号，按红线不输出）'
            f'<br><ul style="margin:6px 0 0 18px">{items}</ul></div>')


def _err_html(e):
    return (f'<div class="cr-wrap"><div class="cr-err">'
            f'查询过程出现异常，已捕获（不会白屏）：<br>'
            f'<code>{_e(type(e).__name__)}: {_e(str(e)[:300])}</code><br><br>'
            f'请尝试其它品类 / 市场组合。</div></div>')


def _reject_html(reason, header_meta=None):
    head_html = ""
    if header_meta:
        head_html = _header_block(header_meta)
    return (
        f'<div class="cr-wrap">{head_html}<div class="cr-err">'
        f'<b>此输入不在本工具的支持范围内</b><br>{_e(reason)}<br><br>'
        f'<b>支持的市场：</b>{_e("、".join(corpus.SUPPORTED_MARKETS.keys()))}<br>'
        f'<b>支持的品类入口：</b>{_e("、".join(corpus.SUPPORTED_CATEGORIES))}'
        f'<br><span style="color:#6b7280">本工具按「查到的官方数据」回答，'
        f'范围外的问题不做硬编答案。</span>'
        f'</div></div>'
    )


def _header_block(meta):
    """顶部元数据条（PRD D3：查询条件 / 查询日期 / 快照版本 / 数据截止时间 / 模块状态）。"""
    if not meta:
        return ""
    mod = meta.get("模块状态", {})
    mod_html = "　".join(
        f'<span class="cr-mod cr-mod-{v}">M{k}·{v}</span>'
        for k, v in mod.items()
    )
    notes_html = ""
    if meta.get("附注"):
        notes_html = (
            f'<div class="cr-meta-notes">备注：{_e(meta["附注"])}</div>'
        )
    return (
        '<div class="cr-header">'
        f'<div class="cr-meta-line"><b>查询条件</b>：{_e(meta.get("查询条件", ""))}　'
        f'<b>查询日期</b>：{_e(meta.get("查询日期", ""))}　'
        f'<b>快照版本</b>：{_e(meta.get("快照版本", ""))}　'
        f'<b>数据截止时间</b>：{_e(meta.get("数据截止时间", ""))}</div>'
        f'<div class="cr-meta-line">模块状态：{mod_html}</div>'
        f'<div class="cr-meta-line cr-meta-scope"><b>覆盖范围</b>：'
        f'{_e(meta.get("覆盖范围", ""))}</div>'
        f'<div class="cr-meta-line"><b>数据来源</b>：'
        f'{_e(meta.get("数据来源", ""))}</div>'
        f'{notes_html}'
        f'<div class="cr-disclaimer">{_e(meta.get("免责声明", ""))}</div>'
        '</div>'
    )


def _footer_block():
    """页脚（PRD：固定免责声明 + 用户追加的 WAF 提示）。"""
    return (
        '<div class="cr-footer">'
        f'<b>⚖️</b><span>{_e(snapshot.DISCLAIMER)}</span>'
        '</div>'
        '<div class="cr-footer" style="background:#fff8e1;border-color:#f0dfa0">'
        f'<b>ℹ️</b><span>{_e(snapshot.WAF_FOOTER_HINT)}</span>'
        '</div>'
    )


# ── M1 渲染 ───────────────────────────────────────────────────
def _m1_card(r, idx):
    rows = [
        f'<div class="cr-row"><span class="cr-k">官方编号</span>'
        f'<code>{_e(r["官方编号"])}</code></div>',
        f'<div class="cr-row"><span class="cr-k">CELEX 号</span>'
        f'<code>{_e(r["CELEX号"])}</code></div>',
        f'<div class="cr-row"><span class="cr-k">生效日期</span>{_e(r["生效日期"])}</div>',
        f'<div class="cr-row"><span class="cr-k">监管机构</span>{_e(r["监管机构"])}</div>',
        f'<div class="cr-row"><span class="cr-k">OJ 出处</span>{_e(r["OJ出处"])}</div>',
    ]
    links = _link_list(r)
    if links:
        rows.append('<div class="cr-row"><span class="cr-k">可核验链接</span>'
                    + links + '</div>')
    rows.append(f'<div class="cr-row"><span class="cr-k">链接状态</span>'
                f'{_e(r["链接状态"])}</div>')
    rows.append(f'<div class="cr-row"><span class="cr-k">官方标题</span>'
                f'{_e(r["官方英文标题"])}</div>')

    tip = (f'<div class="cr-tip">{_e(r["卖家提示"])}</div>'
           if r.get("卖家提示") else "")

    return (f'<div class="cr-card">'
            f'<div class="cr-title">{idx}. {_e(r["法规中文名"])}'
            f'{_validity_badge(r["是否仍有效"])}</div>'
            f'{tip}{"".join(rows)}</div>')


def render_m1(result):
    if not result["ok"]:
        return _reject_html(result["reason"], result.get("header"))

    p, c = result["primary"], result["cross"]
    lm = result.get("llm") or {}
    head = (f'<div class="cr-head"><b>M1 合规地图</b>　'
            f'<span style="color:#6b7280;font-size:13px">'
            f'主体 {len(p)} 条 · 横切 {len(c)} 条</span></div>')
    note = _model_note(lm, bool(p and p[0].get("卖家提示")), "m1")

    parts = [f'<div class="cr-wrap">{_header_block(result.get("header"))}{head}{note}']
    if p:
        parts.append(f'<div class="cr-sec">{_e(result["品类"])} · '
                     f'直接适用法规（{len(p)} 条）</div>')
        parts.extend(_m1_card(r, i) for i, r in enumerate(p, 1))
    else:
        parts.append('<div class="cr-empty">该品类在当前市场暂无语料条目。</div>')

    if c:
        parts.append('<div class="cr-sec">横切法规 · 标签标识 / 通用'
                     f'（任何品类都适用，{len(c)} 条）</div>')
        parts.extend(_m1_card(r, i) for i, r in enumerate(c, 1))

    parts.append(_dropped_note(result["dropped"]))
    parts.append(_footer_block())
    parts.append('</div>')
    return "".join(parts)


# 兼容旧调用
render = render_m1


# ── M2 渲染 ───────────────────────────────────────────────────
_TYPE_CLS = {"废止": "b-warn", "生效": "b-ok", "修订": "b-info",
             "适用": "b-future", "首次收录": "b-ref"}


def _m2_card(r, idx):
    ref = "" if r["官方确认"] else _badge("参考日期", "b-ref")
    rep = (f'<span style="color:#8e2118;font-size:12px">'
           f'　该法规本窗口内第 {r["同类序号"]}/{r["同类计数"]} 次变化</span>'
           if r["同类计数"] > 1 else "")
    links = _link_list(r, key_primary="官方链接")
    return (
        f'<div class="cr-card">'
        f'<div class="cr-title"><span class="cr-date">{_e(r["日期"])}</span>'
        f'{_badge(r["事件类型"], _TYPE_CLS.get(r["事件类型"], "b-info"))}{ref}'
        f'<span style="color:#6b7280;font-size:12.5px">　{_e(r["距今"])}</span>'
        f'{rep}</div>'
        f'<div class="cr-row"><span class="cr-k">变化摘要</span>{_e(r["变化摘要"])}</div>'
        f'<div class="cr-row"><span class="cr-k">影响说明</span>{_e(r["影响说明"])}</div>'
        f'<div class="cr-row"><span class="cr-k">法规</span>'
        f'{_e(r["法规中文名"])}　<code>{_e(r["官方编号"])}</code></div>'
        f'<div class="cr-row"><span class="cr-k">官方链接</span>{links}</div>'
        f'<div class="cr-row"><span class="cr-k">摘要来源</span>'
        f'{_e(r["摘要来源"])}</div>'
        f'</div>'
    )


def render_m2(result):
    if not result["ok"]:
        return _reject_html(result["reason"], result.get("header"))

    s = result["stats"]
    lm = result.get("llm") or {}
    head = (f'<div class="cr-head"><b>M2 变化时间线</b>　'
            f'<span style="color:#6b7280;font-size:13px">{_e(result["时间窗"])}'
            f'　近窗内 {s["近窗内条数"]} 条 · 涉及法规 {s["涉及法规数"]} 部'
            f' · 即将发生 {s["即将发生条数"]} 条</span></div>')
    note = _model_note(lm, bool(result["近窗内"]
                                and result["近窗内"][0]["摘要来源"] == "模型润色"), "m2")

    parts = [f'<div class="cr-wrap">{_header_block(result.get("header"))}{head}{note}']

    if result["近窗内"]:
        parts.append(f'<div class="cr-sec">近 {result["window_months"]} 个月'
                     f'已发生的变化（{len(result["近窗内"])} 条）</div>')
        parts.append('<div class="cr-tl">')
        parts.extend(_m2_card(r, i) for i, r in enumerate(result["近窗内"], 1))
        parts.append('</div>')
    else:
        # PRD E 节 7：保留已知未来节点；两者都无则空态
        empty_msg = (
            f'近 {result["window_months"]} 个月内，'
            f'该组合没有可核验的法规变化记录。'
        )
        if not result["即将发生"]:
            empty_msg = ("当前语料未收录可展示的相关日期事件，"
                         f"不代表没有法规变化。（放宽到全部历史，"
                         f"共有 {s['全部历史条数']} 个事件）")
        parts.append(f'<div class="cr-empty">{_e(empty_msg)}</div>')

    if result["即将发生"]:
        parts.append('<div class="cr-sec">即将发生 / 过渡期节点'
                     f'（尚未生效，{len(result["即将发生"])} 条）</div>')
        parts.append('<div class="cr-tl">')
        parts.extend(_m2_card(r, i) for i, r in enumerate(result["即将发生"], 1))
        parts.append('</div>')

    parts.append(_dropped_note(result["dropped"]))
    parts.append(_footer_block())
    parts.append('</div>')
    return "".join(parts)


# ── M3 渲染（含 D5-1 默认折叠） ───────────────────────────────────────
_U_CLS = {"高": "b-u-high", "中": "b-u-mid", "低": "b-u-low"}


def _m3_card(r, idx):
    """PRD D5-1：默认折叠（仅 动作 + 时点 + 条件状态）；
    点开展开  执行动作 → 适用条件 → 来源条款 → 原文摘录 → 官方原文。
    """
    link = _link_list(r, key_primary="来源条款链接")
    deadline_summary = (f"⏰ {r['期限']}" if r.get("期限") else "持续义务")
    summary_text = f"{_e(r['动作'])}"
    summary_meta = (
        f'<span class="cr-summary-meta">'
        f'{_badge(r["紧迫度"], _U_CLS.get(r["紧迫度"], "b-u-low"))}'
        f'{_badge(r["动作类型"], "b-info")}'
        f'　{_e(deadline_summary)}'
        f'　·　{_e(r.get("动作来源", ""))}'
        f'</span>'
    )

    # 证据链展开区（D5-1 五步）
    evidence = (
        '<div class="cr-evidence">'
        f'<div><b>① 执行动作</b>：{_e(r["动作"])}</div>'
        f'<div><b>② 适用条件</b>：{_e(r.get("类型含义", ""))}'
        f'（动作类型：{_e(r["动作类型"])}）</div>'
        f'<div><b>③ 来源条款</b>：{_e(r["官方编号"])}　'
        f'《{_e(r["依据法规"])}》</div>'
        f'<div><b>④ 原文摘录</b>：（以官方原文为准 —— 见下方链接）</div>'
        f'<div><b>⑤ 官方原文</b>：{link}</div>'
        '</div>'
    )

    return (
        f'<details class="cr-action">'
        f'<summary>{idx}. {summary_text}{summary_meta}</summary>'
        f'{evidence}'
        f'</details>'
    )


def render_m3(result):
    if not result["ok"]:
        return _reject_html(result["reason"], result.get("header"))

    s = result["stats"]
    lm = result.get("llm") or {}
    dist = "　".join(f"{k} {v} 条" for k, v in
                    sorted(s["紧迫度分布"].items(),
                           key=lambda x: "高中低".index(x[0])))
    head = (f'<div class="cr-head"><b>M3 待办清单</b>　'
            f'<span style="color:#6b7280;font-size:13px">'
            f'动作 {s["动作条数"]} 条 · 涉及法规 {s["涉及法规数"]} 部'
            f'　|　<span style="color:#7a5b00">卡片默认折叠，点开展开证据链</span>'
            f'</span></div>')
    note = _model_note(lm, bool(result["动作"]
                                and result["动作"][0]["动作来源"] == "模型改写"), "m3")

    parts = [f'<div class="cr-wrap">{_header_block(result.get("header"))}{head}{note}']

    # 待确认事项（PRD D5-2）
    if result.get("待确认"):
        items = "".join(
            f'<li><b>{_e(it["需确认"])}</b><br>'
            f'<span style="color:#6b7280">影响：{_e(it["影响"])}</span><br>'
            f'<span style="color:#1f4fa8">如何核对：{_e(it["如何核对"])}</span>'
            f'</li>'
            for it in result["待确认"])
        parts.append(f'<div class="cr-note">待确认事项（{len(result["待确认"])} 项）'
                     f'<ul style="margin:6px 0 0 18px">{items}</ul></div>')

    if dist:
        parts.append(f'<div class="cr-empty">紧迫度分布：{_e(dist)}'
                     f'　·　清单可导出 CSV（右侧按钮）</div>')

    idx = 0
    for tname, bunch in result["分组"]:
        parts.append(f'<div class="cr-sec">【{_e(tname)}】{len(bunch)} 条　'
                     f'<span style="font-weight:400;color:#6b7280;font-size:13px">'
                     f'（{_e(bunch[0].get("类型含义", ""))}）</span></div>')
        for a in bunch:
            idx += 1
            parts.append(_m3_card(a, idx))

    if not result["动作"]:
        parts.append('<div class="cr-empty">该组合尚无足够的已核对条款依据生成待办，'
                     '请先查看法规原文。</div>')

    if result["未产出"]:
        items = "".join(
            f'<li>{_e(r.get("官方编号", ""))}　'
            f'{_e((r.get("备注／问题", "") or "").split("｜")[0][:70])}</li>'
            for r in result["未产出"])
        parts.append('<div class="cr-note">'
                     f'⚠️ 另有 {len(result["未产出"])} 条语料落不到明确动作，'
                     f'按规格「只做能落到动作的条目」故未上清单 —— '
                     f'如实列出，不硬编动作：'
                     f'<br><ul style="margin:6px 0 0 18px">{items}</ul></div>')

    parts.append(_dropped_note(result["dropped"]))
    parts.append(_footer_block())
    parts.append('</div>')
    return "".join(parts)


# ── M4 渲染（D4 占位） ───────────────────────────────────────────────────
def render_m4(result):
    if not result["ok"]:
        return _reject_html(result["reason"], result.get("header"))

    head = ('<div class="cr-head"><b>M4 对照演示</b>　'
            '<span style="color:#6b7280;font-size:13px">'
            '通用大模型 vs 本工具 · 同一固定题干</span></div>')

    parts = [f'<div class="cr-wrap">{_header_block(result.get("header"))}{head}']
    parts.append('<div class="cr-sec">固定题干（PRD D4）</div>')
    parts.append(f'<div class="cr-empty" style="font-family:ui-monospace,Consolas,monospace;'
                 f'line-height:1.7">{_e(result["固定题干"])}</div>')

    if result.get("回放列表"):
        parts.append('<div class="cr-sec">已录制历史回放'
                     f'（{len(result["回放列表"])} 条，最新在前）</div>')
        for r in result["回放列表"]:
            parts.append(
                f'<div class="cr-card">'
                f'<div class="cr-row"><span class="cr-k">录制时间</span>'
                f'{_e(r.get("timestamp", "-"))}</div>'
                f'<div class="cr-row"><span class="cr-k">通用模型</span>'
                f'{_e(r.get("generic_model_name", "-"))}</div>'
                f'<div class="cr-row"><span class="cr-k">通用侧原答</span></div>'
                f'<div style="white-space:pre-wrap;font-size:12.5px;'
                f'margin:4px 0 8px;padding:6px 8px;background:#f6f7f9;'
                f'border-radius:4px">{_e(r.get("generic_answer", ""))}</div>'
                f'<div class="cr-row"><span class="cr-k">工具侧</span></div>'
                f'<div style="white-space:pre-wrap;font-size:12.5px;'
                f'margin:4px 0 8px;padding:6px 8px;background:#eef3fd;'
                f'border-radius:4px">{_e(r.get("tool_answer", ""))}</div>'
                f'<div class="cr-row"><span class="cr-k">核验状态</span>'
                f'{_e(r.get("verdict", "未核验"))}</div>'
                f'</div>'
            )
    else:
        # 占位 —— 不诱导模型、不预写胜负、不拿"32015R1000"当反例
        parts.append('<div class="cr-empty" style="color:#7a5b00">'
                     '⚠️ <b>尚未生成对照记录</b>。<br>'
                     '本期未提供真实历史实测记录（需先调用真实模型生成同题原答并保存），'
                     '故不在此处展示示意回答冒充结果。<br>'
                     '<span style="font-size:12px;color:#6b7280">'
                     '按 PRD D4：未取得确证的案例不得作为默认反例，'
                     '回放记录待人工录制后展示。</span>'
                     '</div>')

    parts.append(_footer_block())
    parts.append('</div>')
    return "".join(parts)


# ── 回调 ──────────────────────────────────────────────────────
def run_all(category, market, window, use_llm):
    cat = _real(category)
    try:
        r1 = m1_map.query(cat, market, use_llm=bool(use_llm))
        r2 = m2_timeline.query(cat, market, window=window, use_llm=bool(use_llm))
        r3 = m3_todo.query(cat, market, use_llm=bool(use_llm))
        r4 = m4_compare.query()
        return render_m1(r1), render_m2(r2), render_m3(r3), render_m4(r4)
    except Exception as e:  # noqa: BLE001
        err = _err_html(e)
        return err, err, err, err


def run_route(text, context):
    """M1.5 智能路由回调（输入驱动）。任何异常都不白屏。"""
    try:
        res = m15_router.route(text, context)
        if res.get("ok"):
            # 判定卡头部（识别结果 + 缺失资料）+ 复用 M1 渲染（含免责声明）
            return m15_router.render_parse(res) + render_m1(res["m1"])
        return m15_router.render_parse(res)
    except Exception as e:  # noqa: BLE001
        return _err_html(e)


def _route_initial():
    """M1.5 页签的初始展示（词典路径，不联网、零成本）。"""
    try:
        res = m15_router.route("我要把洋娃娃卖到美国去，要做哪些合规工作？",
                               "", use_llm=False)
        if res.get("ok"):
            return m15_router.render_parse(res) + render_m1(res["m1"])
        return m15_router.render_parse(res)
    except Exception as e:  # noqa: BLE001
        return _err_html(e)


def _real(category):
    return (category or "").replace("（横切维度）", "").strip()


def export_m3_csv(category, market):
    """导出 M3 清单为 CSV，返回文件路径（失败返回 None）。"""
    cat = _real(category)
    res = m3_todo.query(cat, market, use_llm=False)
    if not res["ok"]:
        return None
    os.makedirs(EXPORT_DIR, exist_ok=True)
    try:
        name, data = m3_todo.export_csv(res)
    except RuntimeError:
        return None
    path = os.path.join(EXPORT_DIR, name)
    with open(path, "wb") as f:
        f.write(data)
    return path


def build_ui():
    cfg = llm.config_summary()
    status = ("模型链路：已配置（可选润色）" if cfg["ready"]
              else "模型链路：未配置 —— 将输出原始清单（数据完整，链接可核验）")
    export_hint = "导出：仅 CSV（PRD 第 9 节规定本期不做 PDF）"

    # 类目下拉 —— PRD 第 3 节：仅 5 个业务类目入口；横切维度不算
    cat_choices = list(corpus.SUPPORTED_CATEGORIES)

    _major = int(gr.__version__.split(".")[0])
    _blocks_kwargs = {"title": "出海合规雷达 · 合规地图 / 时间线 / 待办清单 / 对照演示"}
    if _major < 6:
        _blocks_kwargs.update(css=_CSS, theme=gr.themes.Soft())

    with gr.Blocks(**_blocks_kwargs) as demo:
        gr.Markdown(
            "# 出海合规雷达 ComplianceRadar\n"
            "**输入「我卖什么 + 我卖到哪」→ 一次得到四样东西："
            "适用法规清单（M1）· 法规变化时间线（M2）· 可执行待办清单（M3）"
            "· 通用模型 vs 本工具对比（M4）。**\n\n"
            "每条结论都附官方原文链接，可点开逐条核验；"
            "拿不到官方链接的内容一律不输出。"
        )

        with gr.Row():
            with gr.Column(scale=1):
                cat = gr.Dropdown(
                    choices=cat_choices,
                    value="儿童玩具",
                    label="① 商品类目（PRD：仅 5 个业务类目）",
                )
                mkt = gr.Dropdown(
                    choices=list(corpus.SUPPORTED_MARKETS.keys()),
                    value="欧盟",
                    label="② 目标市场",
                )
                window = gr.Radio(
                    choices=m2_timeline.WINDOW_CHOICES,
                    value=m2_timeline.DEFAULT_WINDOW,
                    label="③ 时间窗（M2 用）",
                )
                use_llm = gr.Checkbox(
                    value=cfg["ready"],
                    label="启用中文润色（可选；关闭则输出确定性结果）",
                    interactive=cfg["ready"],
                )
                btn = gr.Button("生成", variant="primary")

                gr.Markdown(
                    f"<small style='color:#6b7280'>{status}<br>"
                    f"模型：{cfg['model']}<br>"
                    f"快照：{snapshot.SNAPSHOT_VERSION}　"
                    f"数据截止时间：{snapshot.DATA_CUTOFF}<br>"
                    f"{export_hint}</small>"
                )

            with gr.Column(scale=3):
                with gr.Tabs():
                    with gr.Tab("M1 · 合规地图"):
                        m1_out = gr.HTML(render_m1(
                            m1_map.query("儿童玩具", "欧盟", use_llm=False)))
                    with gr.Tab("M2 · 变化时间线"):
                        m2_out = gr.HTML(render_m2(
                            m2_timeline.query("儿童玩具", "欧盟", use_llm=False)))
                    with gr.Tab("M3 · 待办清单"):
                        m3_out = gr.HTML(render_m3(
                            m3_todo.query("儿童玩具", "欧盟", use_llm=False)))
                        with gr.Row():
                            csv_btn = gr.DownloadButton(
                                "⬇ 导出 CSV（PRD D3 格式）", variant="secondary",
                                value=lambda c, m: export_m3_csv(c, m),
                                inputs=[cat, mkt])
                    with gr.Tab("M4 · 对照演示"):
                        m4_out = gr.HTML(render_m4(m4_compare.query()))
                    with gr.Tab("M1.5 · 智能路由（一句话判定）"):
                        gr.Markdown(
                            "**用大白话描述你的生意 → 自动识别「品类 × 市场」→ "
                            "查核对过的官方合规表 → 给出针对这一单的判定卡。**\n\n"
                            "模型只负责**理解输入**；法规结论 100% 来自核对语料 + 官方链接，"
                            "模型无权新增或编造。"
                        )
                        q_text = gr.Textbox(
                            lines=3,
                            value="我要把洋娃娃卖到美国去，要做哪些合规工作？",
                            label="① 用一句话描述你的业务（产品 + 目标市场）",
                        )
                        q_ctx = gr.Textbox(
                            lines=2, value="",
                            placeholder=("选填：产品材质 / 结构、客户要求、合同关键信息…"
                                         "（仅辅助识别，不存储）"),
                            label="② 企业上下文（选填）",
                        )
                        q_btn = gr.Button("开始判定", variant="primary")
                        q_out = gr.HTML(_route_initial())
                        q_btn.click(run_route, inputs=[q_text, q_ctx],
                                    outputs=q_out)
                        gr.Markdown(
                            "<small style='color:#8e2118'>"
                            "🔒 隐私边界：输入原文只在内存中处理，不落盘、不缓存，"
                            "判定只依赖「品类 / 市场」两个槽位。"
                            "请勿输入个人隐私或客户敏感信息。</small>"
                        )

        btn.click(run_all, inputs=[cat, mkt, window, use_llm],
                  outputs=[m1_out, m2_out, m3_out, m4_out])
        cat.change(run_all, inputs=[cat, mkt, window, use_llm],
                   outputs=[m1_out, m2_out, m3_out, m4_out])
        mkt.change(run_all, inputs=[cat, mkt, window, use_llm],
                   outputs=[m1_out, m2_out, m3_out, m4_out])
        window.change(run_all, inputs=[cat, mkt, window, use_llm],
                      outputs=[m1_out, m2_out, m3_out, m4_out])

    return demo


if __name__ == "__main__":
    port = int(os.getenv("SERVER_PORT", os.getenv("PORT", "7860")))
    host = "0.0.0.0" if os.getenv("SERVER_PORT") else "127.0.0.1"
    _major = int(gr.__version__.split(".")[0])
    launch_kwargs = {"server_name": host, "server_port": port}
    if _major < 6:
        launch_kwargs.update(show_api=False, css=_CSS, theme=gr.themes.Soft())
    else:
        launch_kwargs.update(css=_CSS, theme=gr.themes.Soft())
    build_ui().launch(**launch_kwargs)