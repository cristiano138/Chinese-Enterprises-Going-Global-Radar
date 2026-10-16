# -*- coding: utf-8 -*-
# UI v4-2 缓存击穿重发 · 2026-10-17
"""
出海合规雷达 · Web 界面入口（app.py）

页面按使用场景组织（用户视角，无内部模块代号）：
    🔎 智能判定   —— 大白话/整份文件输入 → 自动识别 → 判定卡（旗舰入口）
    🗺 法规地图   —— 手动选品类×市场 → 适用法规清单，每条带官方链接
    ✅ 合规待办   —— 可执行动作 + 来源条款链接，支持导出 CSV
    📅 变化时间线 —— 近期法规变化（含过渡期），每条带官方链接
    ⚖️ 模型对照   —— 固定题干 + 真实历史回放

内部映射（仅供开发，不出现在界面上）：
    智能判定 = modules/m15_router.py；法规地图 = m1_map；
    合规待办 = m3_todo；变化时间线 = m2_timeline；模型对照 = m4_compare。

关键约束：
    每条结论附官方链接；拿不到官方链接的内容一律不输出；
    CSV 严格 10 列，文件名 ComplianceRadar_*.csv；本期不做 PDF；
    待办卡片默认折叠，点开展开证据链；空态文案不硬编。

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
# 性能约定（10-16 UI 增强）：
#   · 收起内容用 content-visibility:auto —— 浏览器跳过不可见区块的布局/绘制；
#   · 动画只用 transform/opacity（合成器路径，不触发重排）；
#   · 不用 backdrop-filter / 大面积阴影（滚动掉帧的主要来源）。
_CSS = """
:root{--cr-brand:#22c3e6;--cr-brand-2:#7df9ff;--cr-brand-soft:rgba(34,195,230,.10);
      --cr-bg:#0b1020;--cr-ink:#e8eef7;--cr-ink2:#b6c1d4;--cr-ink3:#7c889e;
      --cr-line:#1d2742;--cr-radius:4px;--cr-night:#0b1020;
      --cr-beam:#22c3e6;--cr-glow:#7df9ff;
      --cr-hi:#4ade9d;--cr-mid:#e8c06a;--cr-lo:#f0937e;
      --cr-serif:"Songti SC","Noto Serif SC","Source Han Serif SC",STSong,serif}
body, .gradio-container { background: var(--cr-bg) !important; }
/* ── Gradio 组件深色化（清新简约：透明底 + 细线分隔 + 青色点缀）── */
.gradio-container .block, .gradio-container .form, .gradio-container .panel {
    background: transparent !important; border-color: var(--cr-line) !important; }
.gradio-container input[type="text"], .gradio-container input[type="number"],
.gradio-container textarea {
    background: #101731 !important; color: var(--cr-ink) !important;
    border: 1px solid var(--cr-line) !important; }
.gradio-container input::placeholder, .gradio-container textarea::placeholder {
    color: var(--cr-ink3) !important; }
.gradio-container label > span { color: var(--cr-ink2) !important; }
.gradio-container .tab-nav, .gradio-container .tab-container {
    background: transparent !important; border-color: var(--cr-line) !important; }
.gradio-container .tab-nav button {
    color: var(--cr-ink3) !important; background: none !important;
    border: 0 !important; border-bottom: 2px solid transparent !important;
    border-radius: 0 !important; padding: 8px 2px !important;
    font-size: 15px !important; margin-bottom: -1px !important; }
.gradio-container .tab-nav button.selected {
    color: var(--cr-glow) !important; border-bottom-color: var(--cr-glow) !important;
    font-weight: 600 !important; }
.gradio-container .tab-nav button:hover { color: var(--cr-ink) !important; }
.gradio-container button.primary, .gradio-container button.secondary {
    background: var(--cr-night) !important; color: var(--cr-glow) !important;
    border: 1px solid var(--cr-line) !important;
    border-radius: var(--cr-radius) !important; box-shadow: none !important; }
.gradio-container button.primary:hover, .gradio-container button.secondary:hover {
    border-color: var(--cr-brand) !important; opacity: .9; }
.gradio-container details, .gradio-container summary {
    background: transparent !important; color: var(--cr-ink) !important;
    border-color: var(--cr-line) !important; }
.gradio-container .dropdown ul, .gradio-container ul.options {
    background: #101731 !important; color: var(--cr-ink) !important;
    border-color: var(--cr-line) !important; }
.gradio-container ul.options li { color: var(--cr-ink) !important; }
.gradio-container ul.options li:hover, .gradio-container ul.options li.selected {
    background: #1a2445 !important; }
.gradio-container footer, .gradio-container .show-api {
    background: transparent !important; color: var(--cr-ink3) !important; }
.cr-wrap { font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
           color:var(--cr-ink); }
/* ── 深色雷达横幅（与开场动画同色系）── */
.cr-band { position:relative; overflow:hidden; border-radius:8px;
           background:radial-gradient(560px 260px at 88% 45%, rgba(34,195,230,.13), transparent 62%), var(--cr-night);
           color:#e6f7ff; border:1px solid rgba(34,195,230,.22);
           padding:20px 22px 16px; }
.cr-band .cr-bar { display:flex; align-items:center; gap:12px; }
.cr-brand { font-size:17px; font-weight:600; color:#e6f7ff;
            font-family:var(--cr-serif); }
.cr-band h1 { font-size:26px; font-weight:600; line-height:1.35; margin:24px 0 8px;
              max-width:620px; font-family:var(--cr-serif); color:#fff; }
.cr-lead { margin:0; color:#9fb3c8; max-width:620px; font-size:14px; }
.cr-band-guide { margin:10px 0 0; color:#7e93a8; font-size:12.5px; max-width:620px; }
.cr-band-meta { margin:14px 0 0; padding-top:10px;
                border-top:1px dashed rgba(125,249,255,.18);
                color:#7e93a8; font-size:12px; }
.cr-scope { position:absolute; right:18px; top:50%; width:190px; height:190px;
            transform:translateY(-50%); display:none; }
@media (min-width:860px) { .cr-scope { display:block; } }
/* ── 结果区元数据条 ── */
.cr-header { background:transparent; border-top:1px solid var(--cr-line);
             border-bottom:1px solid var(--cr-line); border-radius:0;
             padding: 8px 2px; font-size: 12.5px; color: var(--cr-ink2);
             margin-bottom: 14px; line-height: 1.7; }
.cr-header b { color: var(--cr-ink); }
.cr-header .cr-meta-line { margin: 1px 0; }
.cr-header .cr-meta-notes { margin-top: 4px; color: var(--cr-mid); font-size: 12px; }
.cr-header .cr-disclaimer { margin-top: 6px; padding-top: 6px;
                            border-top: 1px dashed var(--cr-line);
                            font-size: 12px; color: var(--cr-ink3); }
.cr-mod { display: inline-block; font-size: 11.5px; padding: 1px 6px;
          border:1px solid currentColor; border-radius:3px; margin: 0 4px;
          font-weight: 500; background:transparent; }
.cr-mod-ready   { color:var(--cr-hi); }
.cr-mod-empty   { color:var(--cr-ink3); }
.cr-mod-partial { color:var(--cr-mid); }
.cr-mod-error   { color:var(--cr-lo); }
.cr-head { font-size: 15px; color:var(--cr-ink); margin: 6px 0 12px; }
.cr-head b { font-size:20px; font-family:var(--cr-serif); font-weight:600; }
.cr-sec { margin: 18px 0 8px; font-size: 16px; font-weight: 600; color:var(--cr-ink);
          border-left: 3px solid var(--cr-brand); padding-left: 8px;
          font-family:var(--cr-serif); }
.cr-card { border:0; border-top:1px solid var(--cr-line); border-radius:0;
           padding: 12px 2px; margin-bottom: 2px; background: transparent;
           content-visibility: auto; contain-intrinsic-size: auto 220px; }
.cr-title { font-size: 15px; font-weight: 600; color:var(--cr-ink); margin-bottom: 6px; }
.cr-badge { display:inline-block; font-size:12px; padding:1px 6px; border-radius:3px;
            margin-left:6px; vertical-align: middle;
            border:1px solid currentColor; background:transparent; }
.b-ok   { color:var(--cr-hi); }
.b-warn { color:var(--cr-lo); }
.b-q    { color:var(--cr-mid); }
.b-info { color:var(--cr-brand); }
.b-ref  { color:var(--cr-ink3); }
.b-future { color:var(--cr-brand); }
.b-u-high { color:var(--cr-lo); }
.b-u-mid  { color:var(--cr-mid); }
.b-u-low  { color:var(--cr-ink3); }
.cr-tip  { font-size:13px; color:var(--cr-brand); background:var(--cr-brand-soft);
           border-radius:var(--cr-radius); padding:6px 8px; margin:6px 0; }
.cr-row  { font-size:13px; color:var(--cr-ink2); margin:3px 0; line-height:1.6;
           word-break: break-word; }
.cr-k { display:inline-block; min-width:88px; color:var(--cr-ink3); }
.cr-row code { background:#101731; color:var(--cr-ink2); padding:1px 5px;
               border-radius:3px;
               font-family: ui-monospace, Consolas, monospace; font-size:12.5px; }
.cr-a { color:var(--cr-brand); text-decoration:none; word-break:break-all; }
.cr-a:hover { text-decoration: underline; }
.cr-note { font-size:12.5px; color:var(--cr-mid); background:rgba(232,192,106,.07);
           border:1px solid rgba(232,192,106,.28); border-radius:var(--cr-radius);
           padding:8px 10px; margin:14px 0; }
.cr-dis { font-size:12.5px; color:var(--cr-ink3); border-top:1px dashed var(--cr-line);
          margin-top:16px; padding-top:10px; }
.cr-footer { font-size:12px; color:var(--cr-ink3); background:transparent;
             border-top:1px solid var(--cr-line); border-radius:0;
             padding:10px 2px 2px; margin-top:16px;
             display:flex; align-items:flex-start; gap:8px; }
.cr-footer b { color:var(--cr-ink2); }
.cr-err { border:1px solid rgba(240,147,126,.35); background:rgba(240,147,126,.08);
          border-radius:var(--cr-radius);
          padding:14px; color:var(--cr-lo); font-size:14px; line-height:1.7; }
.cr-tl { border-left: 2px solid var(--cr-line); margin: 6px 0 0 6px; padding-left: 12px; }
.cr-tl .cr-card { position: relative; }
.cr-date { font-family: ui-monospace, Consolas, monospace; font-size: 14px;
           font-weight: 600; color:var(--cr-ink); }
.cr-empty { font-size:13px; color:var(--cr-ink2); background:transparent;
            border:1px dashed #26314f; border-radius:var(--cr-radius);
            padding:10px 12px; margin:8px 0; }

/* ── 可折叠板块（v2）：细线 + 衬线标题 + 右侧箭头（v4 折叠样式）──
   summary 常显（标题 + 条数 + 提示），收起内容不参与渲染（content-visibility）*/
.cr-group { border:0; border-top:1px solid var(--cr-line); border-radius:0;
            margin: 14px 0 4px; background: transparent; overflow: visible; }
.cr-group > summary { cursor: pointer; list-style: none; padding: 12px 2px;
                      font-size: 16px; font-weight: 600; color: var(--cr-ink);
                      font-family: var(--cr-serif);
                      display: flex; align-items: center; gap: 10px;
                      user-select: none; }
.cr-group > summary::-webkit-details-marker { display: none; }
.cr-group > summary::after { content: ""; width: 8px; height: 8px; flex: none;
                             margin-left: auto;
                             border-right: 1.5px solid var(--cr-ink3);
                             border-bottom: 1.5px solid var(--cr-ink3);
                             transform: rotate(45deg); transition: transform .2s; }
.cr-group[open] > summary::after { transform: rotate(225deg);
                                   border-color: var(--cr-brand); }
.cr-group > summary:hover { color: var(--cr-brand); }
.cr-g-count { font-size: 12.5px; font-weight: 400; color: var(--cr-ink3);
              font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif; }
.cr-g-hint { font-size: 12px; font-weight: 400; color: var(--cr-ink3); }
.cr-group-body { padding: 2px 2px 10px;
                 content-visibility: auto; contain-intrinsic-size: auto 600px; }

/* M3 待办卡片折叠（D5-1）：细线行 + 右箭头，点开展开证据链 */
.cr-action { border:0; border-top:1px solid var(--cr-line); border-radius:0;
             padding: 4px 2px 10px; margin-bottom: 0; background: transparent; }
.cr-action > summary { cursor: pointer; font-size: 14.5px; font-weight: 600;
                        color:var(--cr-ink); padding: 6px 0; list-style: none; }
.cr-action > summary::-webkit-details-marker { display: none; }
.cr-action > summary::before { content: ""; display:inline-block; width: 7px; height: 7px;
                               margin-right: 8px; vertical-align: 1px;
                               border-right: 1.5px solid var(--cr-ink3);
                               border-bottom: 1.5px solid var(--cr-ink3);
                               transform: rotate(-45deg); transition: transform .2s; }
.cr-action[open] > summary::before { transform: rotate(45deg);
                                     border-color: var(--cr-brand); }
.cr-action > summary:hover { color: var(--cr-brand); }
.cr-action > summary .cr-summary-meta { color:var(--cr-ink3); font-weight: 400;
                                         font-size: 12px; margin-left: 6px; }
.cr-action .cr-evidence { margin-top: 8px; padding-top: 8px;
                          border-top: 1px dashed var(--cr-line); font-size: 13px; }
.cr-action .cr-evidence > div { margin: 4px 0; line-height: 1.6; }
.cr-action .cr-evidence b { color: var(--cr-brand); }

/* ── 开场雷达 CG（应用启动时 ~2s，自动淡出，不阻塞交互）────────────
   纯 CSS 动画（v4 设计）：深色底 + 三重同心圆 + 锥形扫描叶 + 目标点闪烁，
   2s 后整层 opacity→0 且 visibility:hidden。pointer-events:none 全程放行点击。
   prefers-reduced-motion 用户直接隐藏（无障碍）。 */
.cr-intro { position: fixed; inset: 0; z-index: 9999;
            display: flex; flex-direction: column; align-items: center;
            justify-content: center; gap: 22px; pointer-events: none;
            background: var(--cr-night);
            animation: crIntroOut 2s ease forwards; }
.cr-intro .cr-radar { position: relative; width: 180px; height: 180px; }
.cr-intro .cr-radar i { position: absolute; inset: 0;
                        border: 1px solid rgba(34,195,230,.35); border-radius: 50%; }
.cr-intro .cr-radar i:nth-child(2) { inset: 30px; }
.cr-intro .cr-radar i:nth-child(3) { inset: 60px; }
.cr-intro .cr-sweep { position: absolute; inset: 0; border-radius: 50%;
                      background: conic-gradient(from 0deg, rgba(34,195,230,.5), transparent 70deg);
                      animation: crSweep 1.6s linear infinite; }
.cr-intro .cr-blip { position: absolute; width: 7px; height: 7px; border-radius: 50%;
                     background: var(--cr-glow);
                     animation: crBlink .8s ease-in-out infinite; }
.cr-intro-name { color: #e6f7ff; font-size: 18px; letter-spacing: .2em; opacity: 0;
                 animation: crFadeIn .4s .2s forwards; }
.cr-intro-sub { color: #9fb3c8; font-size: 12px; letter-spacing: 1px; opacity: 0;
                animation: crFadeIn .4s .5s forwards; }
@keyframes crSweep { to { transform: rotate(360deg); } }
@keyframes crBlink { 0%,100% { opacity: 1; } 50% { opacity: .15; } }
@keyframes crFadeIn { to { opacity: 1; } }
@keyframes crIntroOut { 0%,80% { opacity: 1; visibility: visible; }
                        100% { opacity: 0; visibility: hidden; } }
@media (prefers-reduced-motion: reduce) {
  .cr-intro { display: none; }
}
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
        f'<br><span style="color:#7a8192">本工具按「查到的官方数据」回答，'
        f'范围外的问题不做硬编答案。</span>'
        f'</div></div>'
    )


def _header_block(meta):
    """顶部元数据条（10-16 瘦身：压成一行，覆盖范围/数据来源移除 ——
    它们是静态信息，与单次查询无关，属冗余内容；免责声明保留——红线）。"""
    if not meta:
        return ""
    _MOD_NAMES = {"M1": "法规地图", "M2": "变化时间线",
                  "M3": "合规待办", "M4": "模型对照"}
    _MOD_CN = {"ready": "就绪", "partial": "部分", "empty": "空",
               "error": "异常"}
    mod = meta.get("模块状态", {})
    mod_html = "　".join(
        f'<span class="cr-mod cr-mod-{v}">'
        f'{_MOD_NAMES.get(k, k)}·{_MOD_CN.get(v, v)}</span>'
        for k, v in mod.items()
    )
    notes_html = ""
    if meta.get("附注"):
        notes_html = (
            f'<div class="cr-meta-notes">备注：{_e(meta["附注"])}</div>'
        )
    return (
        '<div class="cr-header">'
        f'<div class="cr-meta-line"><b>{_e(meta.get("查询条件", ""))}</b>'
        f'　·　快照 {_e(meta.get("快照版本", ""))}'
        f'　·　数据截止 {_e(meta.get("数据截止时间", ""))}'
        f'　{mod_html}</div>'
        f'{notes_html}'
        f'<div class="cr-disclaimer">{_e(meta.get("免责声明", ""))}</div>'
        '</div>'
    )


def _footer_block():
    """页脚（PRD：固定免责声明 + 时效性核验徽章；WAF 平台提示已删——与应用无关）。"""
    return (
        '<div class="cr-footer">'
        f'<b>⚖️</b><span>{_e(snapshot.DISCLAIMER)}</span>'
        '</div>'
        + _freshness_footer()
    )


# ── 可折叠板块组件（v2）：结果按板块分组，点标题展开详情 ─────────────
def _group(title, count, body, open_=False, hint=""):
    """一个 <details> 板块：标题常显（+ 条数徽标 + 灰字提示），正文可展开。
    open_=True 时默认展开（只给每个页签最重要的板块，其余收起保持干净）。"""
    o = " open" if open_ else ""
    c = f'<span class="cr-g-count">{count} 项</span>' if count != "" else ""
    h = f'<span class="cr-g-hint">{_e(hint)}</span>' if hint else ""
    return (f'<details class="cr-group"{o}><summary>{_e(title)}{c}{h}</summary>'
            f'<div class="cr-group-body">{body}</div></details>')


# ── 开场雷达 CG（应用启动 ~2s，纯 CSS，自动淡出，不阻塞交互）────────
# 结构（v4 设计）：三重同心圆 + 锥形扫描叶 + 三个闪烁目标点 + 品牌名。
# 动画全在 _CSS 里（transform/opacity 合成器路径）；这里只放标记。
_INTRO_HTML = (
    '<div class="cr-intro" aria-hidden="true">'
    '<div class="cr-radar">'
    '<i></i><i></i><i></i>'
    '<div class="cr-sweep"></div>'
    '<span class="cr-blip" style="top:40px;left:118px"></span>'
    '<span class="cr-blip" style="top:112px;left:50px;animation-delay:.3s"></span>'
    '<span class="cr-blip" style="top:72px;left:58px;animation-delay:.55s"></span>'
    '</div>'
    '<div class="cr-intro-name">出海合规雷达</div>'
    '<div class="cr-intro-sub">COMPLIANCE RADAR · 每条结论附官方原文链接</div>'
    '</div>'
)


# ── 顶部深色雷达横幅（v4 设计：品牌行 + 衬线大标题 + 雷达刻度盘）──────
_HERO_SVG = (
    '<svg class="cr-scope" viewBox="0 0 240 240" aria-hidden="true">'
    '<defs><linearGradient id="crSwG" x1="0" y1="0" x2="1" y2="1">'
    '<stop offset="0" stop-color="#22C3E6" stop-opacity=".45"/>'
    '<stop offset="1" stop-color="#22C3E6" stop-opacity="0"/></linearGradient></defs>'
    '<g fill="none" stroke="#22C3E6" stroke-opacity=".3">'
    '<circle cx="120" cy="120" r="40"/><circle cx="120" cy="120" r="80"/>'
    '<circle cx="120" cy="120" r="118"/>'
    '<path d="M120 2V238M2 120H238"/></g>'
    '<path d="M120 120L120 2A118 118 0 0 1 203.4 36.6Z" fill="url(#crSwG)"/>'
    '<g fill="#7DF9FF"><circle cx="150" cy="72" r="3"/>'
    '<circle cx="66" cy="150" r="2.5" opacity=".7"/>'
    '<circle cx="96" cy="92" r="2" opacity=".5"/></g>'
    '</svg>'
)


def _hero_html(model_status):
    """顶部横幅（v4 设计稿 band 区）：品牌 + 衬线大标题 + 引导 + 元数据。
    替代原 gr.Markdown 标题区；信息一一对应（含模型状态/快照/数据截止），
    仅呈现方式改为与开场动画同色系的深色带。"""
    guide = ("不知道从哪开始？在下方「智能判定」用大白话提问；"
             "明确品类和市场，用「法规地图 / 合规待办 / 变化时间线」精确查询；"
             "「模型对照」看我们和通用 AI 的区别。")
    return (
        '<div class="cr-wrap"><div class="cr-band">'
        '<div class="cr-bar"><span class="cr-brand">出海合规雷达</span></div>'
        '<h1>输入你的生意，雷达告诉你要做什么</h1>'
        '<p class="cr-lead">大白话直接问即可。每条结论都附官方原文链接，'
        '并标注数据截止日期。</p>'
        f'<p class="cr-band-guide">{_e(guide)}</p>'
        f'<div class="cr-band-meta">{_e(model_status)}　·　'
        f'快照：{_e(snapshot.SNAPSHOT_VERSION)}　·　'
        f'数据截止：{_e(snapshot.DATA_CUTOFF)}　·　结果可导出 CSV</div>'
        f'{_HERO_SVG}'
        '</div></div>'
    )


# ── 时效性核验徽章（团队「持续监控」思路的最小可行落地）──────────────
# 数据来自 scripts/check_freshness.py 生成的 data/freshness_latest.json；
# 文件不存在（没跑过核验）就静默不显示 —— 不硬编、不假装验过。
_FRESHNESS_FILE = os.path.join(HERE, "data", "freshness_latest.json")
_freshness_memo = {"mtime": 0, "data": None}


def _freshness_latest():
    """按文件 mtime 记忆化读取最新核验结果（每次渲染都读盘太浪费）。"""
    try:
        mtime = os.path.getmtime(_FRESHNESS_FILE)
        if mtime != _freshness_memo["mtime"]:
            import json as _json
            with open(_FRESHNESS_FILE, encoding="utf-8") as f:
                _freshness_memo.update(mtime=mtime, data=_json.load(f))
        return _freshness_memo["data"]
    except Exception:
        return None


def _freshness_footer():
    d = _freshness_latest()
    if not d:
        return ""
    ok, total = d.get("ok", 0), d.get("total", 0)
    # 三分口径（与 check_freshness.py 一致）：
    #   link_error = 连上了但 4xx/5xx，链接可能失效；net_error = 本机网络没连通，不判死链
    link_bad = d.get("link_error", 0)
    net_bad = d.get("net_error", 0)
    changed = d.get("changed", 0)
    style = ("background:#eaf4ee;border-color:#cfe4d6" if link_bad == 0
             else "background:#f7f1e2;border-color:#e5d9bd")
    parts = (f"官方链接最近核验：{_e(d.get('checked_at', ''))}（北京时间）· "
             f"{ok}/{total} 可访问")
    if link_bad:
        parts += f" · ⚠️ {link_bad} 条链接异常（待人工复核）"
    if net_bad:
        parts += f" · {net_bad} 条本机网络未连通（不判死链）"
    if changed:
        parts += f" · 🔶 {changed} 条内容较上次核验有更新"
    parts += "　—　时效性监控脚本定期核验，日志留档可回放"
    return (f'<div class="cr-footer" style="{style}">'
            f'<b>🛰️</b><span>{parts}</span></div>')


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
    head = (f'<div class="cr-head"><b>法规地图</b>　'
            f'<span style="color:#7a8192;font-size:13px">'
            f'这一单适用的法规 · 主体 {len(p)} 条 · 横切 {len(c)} 条'
            f'（每条附官方原文链接）</span></div>')
    note = _model_note(lm, bool(p and p[0].get("卖家提示")), "m1")

    parts = [f'<div class="cr-wrap">{_header_block(result.get("header"))}{head}{note}']
    if p:
        body = "".join(_m1_card(r, i) for i, r in enumerate(p, 1))
        parts.append(_group(
            f'{_e(result["品类"])} · 直接适用法规', len(p), body,
            open_=len(p) <= 6, hint="点开逐条看依据与官方链接"))
    else:
        parts.append('<div class="cr-empty">该品类在当前市场暂无语料条目。</div>')

    if c:
        body = "".join(_m1_card(r, i) for i, r in enumerate(c, 1))
        parts.append(_group(
            '横切法规 · 标签标识 / 通用', len(c), body,
            hint="任何品类都适用 · 点开查看"))

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
    rep = (f'<span style="color:#a4493f;font-size:12px">'
           f'　该法规本窗口内第 {r["同类序号"]}/{r["同类计数"]} 次变化</span>'
           if r["同类计数"] > 1 else "")
    links = _link_list(r, key_primary="官方链接")
    return (
        f'<div class="cr-card">'
        f'<div class="cr-title"><span class="cr-date">{_e(r["日期"])}</span>'
        f'{_badge(r["事件类型"], _TYPE_CLS.get(r["事件类型"], "b-info"))}{ref}'
        f'<span style="color:#7a8192;font-size:12.5px">　{_e(r["距今"])}</span>'
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
    head = (f'<div class="cr-head"><b>变化时间线</b>　'
            f'<span style="color:#7a8192;font-size:13px">{_e(result["时间窗"])}'
            f'　近窗内 {s["近窗内条数"]} 条 · 涉及法规 {s["涉及法规数"]} 部'
            f' · 即将发生 {s["即将发生条数"]} 条</span></div>')
    note = _model_note(lm, bool(result["近窗内"]
                                and result["近窗内"][0]["摘要来源"] == "模型润色"), "m2")

    parts = [f'<div class="cr-wrap">{_header_block(result.get("header"))}{head}{note}']

    if result["近窗内"]:
        body = ('<div class="cr-tl">'
                + "".join(_m2_card(r, i) for i, r in enumerate(result["近窗内"], 1))
                + '</div>')
        parts.append(_group(f'近 {result["window_months"]} 个月已发生的变化',
                            len(result["近窗内"]), body,
                            hint="历史记录 · 点开回看"))
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
        body = ('<div class="cr-tl">'
                + "".join(_m2_card(r, i) for i, r in enumerate(result["即将发生"], 1))
                + '</div>')
        parts.append(_group('即将发生 / 过渡期节点', len(result["即将发生"]), body,
                            open_=True, hint="尚未生效 · 提前准备窗口"))

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
        f'<div><b>② 适用条件</b>：{_e(r.get("适用条件") or r.get("类型含义", ""))}'
        f'（动作类型：{_e(r["动作类型"])}）</div>'
        f'<div><b>③ 来源条款</b>：{_e(r["官方编号"])}　'
        f'《{_e(r["依据法规"])}》</div>'
        f'<div><b>④ 原文摘录</b>：{_e(r.get("证据摘录") or "以官方原文为准")}</div>'
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
    head = (f'<div class="cr-head"><b>合规待办</b>　'
            f'<span style="color:#7a8192;font-size:13px">'
            f'动作 {s["动作条数"]} 条 · 涉及法规 {s["涉及法规数"]} 部'
            f'　|　<span style="color:#8f6210">卡片默认折叠，点开展开证据链</span>'
            f'</span></div>')
    note = _model_note(lm, bool(result["动作"]
                                and result["动作"][0]["动作来源"] == "模型改写"), "m3")

    parts = [f'<div class="cr-wrap">{_header_block(result.get("header"))}{head}{note}']

    # 待确认事项（PRD D5-2）
    if result.get("待确认"):
        items = "".join(
            f'<li><b>{_e(it["需确认"])}</b><br>'
            f'<span style="color:#7a8192">影响：{_e(it["影响"])}</span><br>'
            f'<span style="color:#2f4a8a">如何核对：{_e(it["如何核对"])}</span>'
            f'</li>'
            for it in result["待确认"])
        parts.append(f'<div class="cr-note">待确认事项（{len(result["待确认"])} 项）'
                     f'<ul style="margin:6px 0 0 18px">{items}</ul></div>')

    if dist:
        parts.append(f'<div class="cr-empty">紧迫度分布：{_e(dist)}'
                     f'　·　清单可导出 CSV（页面下方按钮）</div>')

    idx = 0
    for tname, bunch in result["分组"]:
        cards = []
        for a in bunch:
            idx += 1
            cards.append(_m3_card(a, idx))
        body = (f'<div style="font-size:12.5px;color:#7a8192;margin:2px 0 8px">'
                f'{_e(bunch[0].get("类型含义", ""))}</div>' + "".join(cards))
        parts.append(_group(f'【{_e(tname)}】', len(bunch), body,
                            open_=(tname == "高"),
                            hint="点开逐条看证据链"))

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

    head = ('<div class="cr-head"><b>模型对照参考</b>　'
            '<span style="color:#7a8192;font-size:13px">'
            '通用大模型 vs 本工具 · 同一固定题干</span></div>')

    parts = [f'<div class="cr-wrap">{_header_block(result.get("header"))}{head}']
    parts.append('<div class="cr-sec">固定题干</div>')
    parts.append(f'<div class="cr-empty" style="font-family:ui-monospace,Consolas,monospace;'
                 f'line-height:1.7">{_e(result["固定题干"])}</div>')

    if result.get("回放列表"):
        parts.append('<div class="cr-sec">已录制历史回放'
                     f'（{len(result["回放列表"])} 条，最新在前 · 点开看全文）</div>')
        for k, r in enumerate(result["回放列表"]):
            inner = (
                f'<div class="cr-row"><span class="cr-k">录制时间</span>'
                f'{_e(r.get("timestamp", "-"))}</div>'
                f'<div class="cr-row"><span class="cr-k">通用模型</span>'
                f'{_e(r.get("generic_model_name", "-"))}</div>'
                f'<div class="cr-row"><span class="cr-k">通用侧原答</span></div>'
                f'<div style="white-space:pre-wrap;font-size:12.5px;'
                f'margin:4px 0 8px;padding:6px 8px;background:#f1f1ec;'
                f'border-radius:6px">{_e(r.get("generic_answer", ""))}</div>'
                f'<div class="cr-row"><span class="cr-k">工具侧</span></div>'
                f'<div style="white-space:pre-wrap;font-size:12.5px;'
                f'margin:4px 0 8px;padding:6px 8px;background:#eef2f9;'
                f'border-radius:6px">{_e(r.get("tool_answer", ""))}</div>'
                f'<div class="cr-row"><span class="cr-k">核验状态</span>'
                f'{_e(r.get("verdict", "未核验"))}</div>'
            )
            parts.append(_group(
                f'回放 {k + 1} · {_e(r.get("generic_model_name", "-"))}',
                "", inner, hint=f'录制于 {_e(r.get("timestamp", "-"))}'))
    else:
        # 占位 —— 不诱导模型、不预写胜负、不拿"32015R1000"当反例
        parts.append('<div class="cr-empty" style="color:#8f6210">'
                     '⚠️ <b>尚未生成对照记录</b>。<br>'
                     '本期未提供真实历史实测记录（需先调用真实模型生成同题原答并保存），'
                     '故不在此处展示示意回答冒充结果。<br>'
                     '<span style="font-size:12px;color:#7a8192">'
                     '按对照规范：未取得真实实测记录的案例不作为默认展示，'
                     '回放记录待人工录制后上线。</span>'
                     '</div>')

    parts.append(_footer_block())
    parts.append('</div>')
    return "".join(parts)


# ── 回调 ──────────────────────────────────────────────────────
def run_map(category, market, use_llm):
    """法规地图回调。任何异常都不白屏。"""
    cat = _real(category)
    try:
        return render_m1(m1_map.query(cat, market, use_llm=bool(use_llm)))
    except Exception as e:  # noqa: BLE001
        return _err_html(e)


def run_todo(category, market, use_llm):
    """合规待办回调。任何异常都不白屏。"""
    cat = _real(category)
    try:
        return render_m3(m3_todo.query(cat, market, use_llm=bool(use_llm)))
    except Exception as e:  # noqa: BLE001
        return _err_html(e)


def run_timeline(category, market, window, use_llm):
    """变化时间线回调。任何异常都不白屏。"""
    cat = _real(category)
    try:
        return render_m2(m2_timeline.query(cat, market, window=window,
                                           use_llm=bool(use_llm)))
    except Exception as e:  # noqa: BLE001
        return _err_html(e)


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
    model_status = ("模型：已接入（理解输入用，结论仍 100% 来自核对语料）"
                    if cfg["ready"] else
                    "模型：未配置 —— 输出原始清单（数据完整，链接可核验）")

    # 类目下拉 —— 仅 5 个业务类目入口；横切维度随品类附带，不单独查
    cat_choices = list(corpus.SUPPORTED_CATEGORIES)
    mkt_choices = list(corpus.SUPPORTED_MARKETS.keys())

    _major = int(gr.__version__.split(".")[0])
    _blocks_kwargs = {"title": "出海合规雷达 ComplianceRadar"}
    if _major < 6:
        _blocks_kwargs.update(css=_CSS, theme=gr.themes.Soft())

    with gr.Blocks(**_blocks_kwargs) as demo:
        # 开场雷达 CG（~2s 自动淡出，纯 CSS，不阻塞交互）
        # + 顶部深色雷达横幅（v4 设计：替代原 Markdown 标题区，信息不变）
        gr.HTML(_INTRO_HTML)
        gr.HTML(_hero_html(model_status))

        with gr.Tabs():
            # ── ① 智能判定 ────────────────────────────────────
            with gr.Tab("🔎 智能判定"):
                gr.Markdown(
                    "**大白话直接问 → 自动识别「品类 × 市场」→ 出判定卡。**"
                    "支持整段粘贴产品描述、BOM、合同要点。"
                    "模型只负责理解输入；结论 100% 来自核对语料 + 官方链接。"
                )
                q_text = gr.Textbox(
                    lines=4,
                    value="我要把洋娃娃卖到美国去，要做哪些合规工作？",
                    label="① 你的生意（一句话，或整份产品/合同文件）",
                )
                q_ctx = gr.Textbox(
                    lines=2, value="",
                    placeholder=("选填：产品材质 / 结构、客户要求、合同关键信息…"
                                 "（仅辅助识别，不存储）"),
                    label="② 补充上下文（选填）",
                )
                q_btn = gr.Button("开始判定", variant="primary")
                q_out = gr.HTML(_route_initial())
                gr.Markdown(
                    "<small style='color:#a4493f'>"
                    "🔒 隐私边界：输入原文只在内存中处理，不落盘、不缓存，"
                    "判定只依赖「品类 / 市场」两个槽位。"
                    "请勿输入个人隐私或客户敏感信息。</small>"
                )

            # ── ② 法规地图 ────────────────────────────────────
            with gr.Tab("🗺 法规地图"):
                gr.Markdown("**已知品类和市场？选好直接生成 —— 板块标题可点开看详情。**")
                with gr.Row():
                    cat1 = gr.Dropdown(choices=cat_choices, value="儿童玩具",
                                       label="① 商品类目")
                    mkt1 = gr.Dropdown(choices=mkt_choices, value="欧盟",
                                       label="② 目标市场")
                    use1 = gr.Checkbox(value=cfg["ready"],
                                       label="中文润色（可选）",
                                       interactive=cfg["ready"])
                    btn1 = gr.Button("生成清单", variant="primary")
                m1_out = gr.HTML(render_m1(
                    m1_map.query("儿童玩具", "欧盟", use_llm=False)))

            # ── ③ 合规待办 ────────────────────────────────────
            with gr.Tab("✅ 合规待办"):
                gr.Markdown("**这一单要办的事按紧迫度分板块排好 —— 点开板块和每条卡片看证据链。**")
                with gr.Row():
                    cat3 = gr.Dropdown(choices=cat_choices, value="儿童玩具",
                                       label="① 商品类目")
                    mkt3 = gr.Dropdown(choices=mkt_choices, value="欧盟",
                                       label="② 目标市场")
                    use3 = gr.Checkbox(value=cfg["ready"],
                                       label="中文润色（可选）",
                                       interactive=cfg["ready"])
                    btn3 = gr.Button("生成待办", variant="primary")
                m3_out = gr.HTML(render_m3(
                    m3_todo.query("儿童玩具", "欧盟", use_llm=False)))
                with gr.Row():
                    csv_btn = gr.DownloadButton(
                        "⬇ 导出待办清单（CSV）", variant="secondary",
                        value=lambda c, m: export_m3_csv(c, m),
                        inputs=[cat3, mkt3])

            # ── ④ 变化时间线 ──────────────────────────────────
            with gr.Tab("📅 变化时间线"):
                gr.Markdown("**法规什么时候生效、什么时候变 —— 重点看「即将发生」的过渡期节点。**")
                with gr.Row():
                    cat2 = gr.Dropdown(choices=cat_choices, value="儿童玩具",
                                       label="① 商品类目")
                    mkt2 = gr.Dropdown(choices=mkt_choices, value="欧盟",
                                       label="② 目标市场")
                    window2 = gr.Radio(
                        choices=m2_timeline.WINDOW_CHOICES,
                        value=m2_timeline.DEFAULT_WINDOW,
                        label="③ 时间窗（只影响时间线）",
                    )
                    use2 = gr.Checkbox(value=cfg["ready"],
                                       label="中文润色（可选）",
                                       interactive=cfg["ready"])
                    btn2 = gr.Button("生成时间线", variant="primary")
                m2_out = gr.HTML(render_m2(
                    m2_timeline.query("儿童玩具", "欧盟", use_llm=False)))

            # ── ⑤ 模型对照 ────────────────────────────────────
            with gr.Tab("⚖️ 模型对照"):
                gr.Markdown("**同一道固定题，两边各答一遍 —— 有没有官方来源，你自己看。**")
                m4_out = gr.HTML(render_m4(m4_compare.query()))

        # 事件绑定（每页签自足，互不干扰）
        q_btn.click(run_route, inputs=[q_text, q_ctx], outputs=q_out)
        for w in (cat1, mkt1, use1):
            w.change(run_map, inputs=[cat1, mkt1, use1], outputs=m1_out)
        btn1.click(run_map, inputs=[cat1, mkt1, use1], outputs=m1_out)
        for w in (cat3, mkt3, use3):
            w.change(run_todo, inputs=[cat3, mkt3, use3], outputs=m3_out)
        btn3.click(run_todo, inputs=[cat3, mkt3, use3], outputs=m3_out)
        for w in (cat2, mkt2, window2, use2):
            w.change(run_timeline, inputs=[cat2, mkt2, window2, use2],
                     outputs=m2_out)
        btn2.click(run_timeline, inputs=[cat2, mkt2, window2, use2],
                   outputs=m2_out)

    return demo


if __name__ == "__main__":
    # 后台预热智能判定（M1.5）：把演示常用输入的模型解析提前算进内存缓存，
    # 演示首点即毫秒级命中；不阻塞启动，失败静默（词典兜底照常）。
    m15_router.start_prewarm()
    port = int(os.getenv("SERVER_PORT", os.getenv("PORT", "7860")))
    host = "0.0.0.0" if os.getenv("SERVER_PORT") else "127.0.0.1"
    _major = int(gr.__version__.split(".")[0])
    launch_kwargs = {"server_name": host, "server_port": port}
    if _major < 6:
        launch_kwargs.update(show_api=False, css=_CSS, theme=gr.themes.Soft())
    else:
        launch_kwargs.update(css=_CSS, theme=gr.themes.Soft())
    build_ui().launch(**launch_kwargs)