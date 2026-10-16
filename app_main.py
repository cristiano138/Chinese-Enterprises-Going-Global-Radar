# -*- coding: utf-8 -*-
# UI v5.1 · 统一 LLM 路由器入口 + M2/M3 独立页签回归（整洁版）
"""
出海合规雷达 · Web 界面入口（app.py）

页面按使用场景组织（用户视角，无内部模块代号）：
    🔎 智能判定   —— 大白话输入（LLM 路由器）→ 品类/市场/风险事实栏
                     → 三列折叠面板：结论摘要 / 待办清单 / 法规原文
    📅 变化时间线 —— 同一个 LLM 路由器输入 → 该品类×市场近期法规变化
    ✅ 合规待办   —— 同一个 LLM 路由器输入 → 待办折叠清单（可导出 CSV）
    ⚖️ 模型对照   —— 通用 AI vs 本工具（固定题干 + 真实历史回放）

内部映射（仅供开发，不出现在界面上）：
    智能判定 = m15_router（识别）+ m1_map（法规原文）+ m3_todo（待办摘要）；
    变化时间线 = m15_router（识别）+ m2_timeline；
    合规待办 = m15_router（识别）+ m3_todo（完整清单，M3 独立入口）；
    模型对照 = m4_compare。

关键约束：
    每条结论附官方链接；拿不到官方链接的内容一律不输出；
    CSV 严格 10 列，文件名 ComplianceRadar_*.csv；本期不做 PDF；
    条目默认折叠，点开展开证据链；空态文案不硬编。

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

from core import snapshot  # noqa: E402
from modules import (m2_timeline, m3_todo, m4_compare,  # noqa: E402
                     m15_router)

import gradio as gr  # noqa: E402

# M3 待办清单的 CSV 导出目录（PRD D3 格式）。
# 写入方：export_m3_csv()，由页首「导出 CSV」按钮触发；命令行等价入口见
#         README「m3_todo.py --export」。
# 全部内容都是**生成物**，随时可删、下次导出会重建，不参与任何查表逻辑。
# ⚠️ 刻意**不进 .gitignore**：导出件要能在仓库里直接看到（演示/评审时按日期取用）。
#    副作用是导过一次后 git status 会多出未跟踪文件 —— 这是预期行为，不是脏数据。
EXPORT_DIR = os.path.join(HERE, "data", "export")


# ── 结果渲染（v4 设计稿：纸白底、衬线标题、细线折叠、描边徽章）──
# 性能约定（10-16 UI 增强）：
#   · 收起内容用 content-visibility:auto —— 浏览器跳过不可见区块的布局/绘制；
#   · 动画只用 transform/opacity（合成器路径，不触发重排）；
#   · 不用 backdrop-filter / 大面积阴影（滚动掉帧的主要来源）。
_CSS = """
:root{--cr-brand:#2f4a8a;--cr-brand-2:#22c3e6;--cr-brand-soft:#eef2f9;
      --cr-bg:#fafaf7;--cr-ink:#1f2430;--cr-ink2:#4b5263;--cr-ink3:#7a8192;
      --cr-line:#e4e4de;--cr-radius:4px;--cr-night:#0b1020;
      --cr-beam:#22c3e6;--cr-glow:#7df9ff;
      --cr-hi:#2e7d5b;--cr-mid:#8f6210;--cr-lo:#a4493f;
      --cr-serif:"Songti SC","Noto Serif SC","Source Han Serif SC",STSong,serif}
body, .gradio-container { background: var(--cr-bg) !important; }
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
.cr-scope { position:absolute; right:18px; top:50%; width:190px; height:190px;
            transform:translateY(-50%); display:none; }
@media (min-width:860px) { .cr-scope { display:block; } }

/* ── 判定结果（v4 设计稿）：echo → 事实栏 → 图例 → 三列折叠 ── */
.cr-echo { margin:14px 0 0; font-size:13px; color:var(--cr-ink3); }
.cr-facts { display:grid; grid-template-columns:repeat(4,1fr); margin:18px 0 0;
            border-top:1px solid var(--cr-line); border-bottom:1px solid var(--cr-line); }
.cr-facts > div { padding:12px 14px 12px 0; }
.cr-facts > div + div { padding-left:14px; border-left:1px solid var(--cr-line); }
.cr-facts dt { font-size:12px; color:var(--cr-ink3); }
.cr-facts dd { margin:0; font-size:15px; font-weight:600; }
.cr-legend { font-size:13px; color:var(--cr-ink3); margin:12px 0 0; }
/* 三列并列（板块级折叠：衬线标题 + 条数 + 箭头） */
.cr-cols { display:grid; grid-template-columns:repeat(3,1fr); margin-top:20px;
           align-items:start; border-top:1px solid var(--cr-line); }
.cr-col { padding:6px 18px 10px 0; min-width:0; }
.cr-col + .cr-col { padding-left:18px; border-left:1px solid var(--cr-line); }
.cr-col > summary { cursor:pointer; list-style:none; padding:12px 0;
                    font-size:17px; font-weight:600; color:var(--cr-ink);
                    font-family:var(--cr-serif);
                    display:flex; align-items:center; gap:10px; user-select:none; }
.cr-col > summary::-webkit-details-marker { display:none; }
.cr-col > summary:hover { color:var(--cr-brand); }
.cr-cnt { font-size:13px; font-weight:400; color:var(--cr-ink3);
          font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif; }
/* 条目折叠单元（板块与条目共用箭头样式） */
.cr-it > summary { cursor:pointer; list-style:none; border-top:1px solid var(--cr-line);
                   padding:11px 0; font-size:15px; color:var(--cr-ink);
                   display:flex; align-items:center; gap:10px; user-select:none; }
.cr-it > summary::-webkit-details-marker { display:none; }
.cr-it > summary:hover .cr-it-t { color:var(--cr-brand); }
.cr-it-t { flex:1; }
.cr-col > summary::after, .cr-it > summary::after {
    content:""; width:8px; height:8px; flex:none; margin-left:auto;
    border-right:1.5px solid var(--cr-ink3); border-bottom:1.5px solid var(--cr-ink3);
    transform:rotate(45deg); transition:transform .2s; }
.cr-col[open] > summary::after, .cr-it[open] > summary::after {
    transform:rotate(225deg); border-color:var(--cr-brand); }
/* 置信度徽章（描边） */
.cr-cf { font-style:normal; font-size:12px; line-height:1; padding:3px 6px;
         border:1px solid currentColor; border-radius:3px; flex:none; }
.cr-cf.hi { color:var(--cr-hi); }
.cr-cf.mid { color:var(--cr-mid); }
.cr-cf.lo { color:var(--cr-lo); }
/* 条目展开区 */
.cr-idt { padding:0 0 12px; color:var(--cr-ink2); font-size:14px; line-height:1.75; }
.cr-idt p { margin:0 0 6px; }
.cr-idt .cr-meta { font-size:12.5px; color:var(--cr-ink3); }
.cr-idt a { color:var(--cr-brand); text-decoration:none; word-break:break-all; }
.cr-idt a:hover { text-decoration:underline; }
/* 变化时间线（v4 设计稿 tlist） */
.cr-tlist { list-style:none; margin:20px 0 0; padding:0; }
.cr-tlist li { padding:12px 0; border-top:1px solid var(--cr-line); }
.cr-tlist li:first-child { border-top:0; }
.cr-tlist .cr-hint { font-size:13px; color:var(--cr-ink3); }
.cr-tlist strong { display:block; font-size:15px; }
.cr-tlist p { margin:2px 0 0; color:var(--cr-ink2); font-size:14px; line-height:1.7; }
.cr-tlist p a { color:var(--cr-brand); text-decoration:none; }
/* 模型对照（v4 设计稿 cmp 两栏） */
.cr-cmp { display:grid; grid-template-columns:1fr 1fr; margin-top:20px; }
.cr-cmp > div { padding:0 22px 0 0; }
.cr-cmp > div + div { padding:0 0 0 22px; border-left:1px solid var(--cr-line); }
.cr-cmp h4 { margin:0 0 4px; font-size:17px; font-family:var(--cr-serif); }
.cr-cmp p { margin:0; color:var(--cr-ink2); }
/* 通用小件（拒绝卡 / 提示 / 空态 / 页脚） */
.cr-note { font-size:12.5px; color:var(--cr-mid); background:#f9f6ee;
           border:1px solid #e7dfc9; border-radius:var(--cr-radius);
           padding:8px 10px; margin:14px 0 0; }
.cr-row  { font-size:13px; color:var(--cr-ink2); margin:3px 0; line-height:1.6;
           word-break: break-word; }
.cr-k { display:inline-block; min-width:88px; color:var(--cr-ink3); }
.cr-dis { font-size:12.5px; color:var(--cr-ink3); margin-top:10px; }
.cr-err { border:1px solid #e5c8c4; background:#faf0ee; border-radius:var(--cr-radius);
          padding:14px; color:var(--cr-lo); font-size:14px; line-height:1.7; }
.cr-empty { font-size:13px; color:var(--cr-ink2); background:transparent;
            border:1px dashed #d8d8d0; border-radius:var(--cr-radius);
            padding:10px 12px; margin:8px 0; }
.cr-footer { font-size:12.5px; color:var(--cr-ink3); border-top:1px solid var(--cr-line);
             padding:14px 2px 2px; margin-top:28px; line-height:1.8; }

/* ── 页签与按钮（对齐设计稿）── */
.tab-nav button, .tab-container button { background:none !important; border:0 !important;
    box-shadow:none !important; color:var(--cr-ink3) !important; font-size:15px !important;
    padding:8px 2px !important; border-bottom:2px solid transparent !important;
    border-radius:0 !important; margin-bottom:-1px !important; }
.tab-nav button.selected, .tab-container button.selected { color:var(--cr-ink) !important;
    border-bottom-color:var(--cr-ink) !important; font-weight:600 !important; }
#cr-run, #cr-run2, #cr-run3 { background:var(--cr-night) !important; color:var(--cr-glow) !important;
    border:0 !important; border-radius:var(--cr-radius) !important;
    box-shadow:none !important; }
#cr-run:hover, #cr-run2:hover, #cr-run3:hover { opacity:.9; }
#cr-run-row, #cr-run2-row, #cr-run3-row { justify-content:flex-end; }
/* 导出按钮：叠加到横幅右上（小屏自动回落到横幅下方） */
#cr-export-row { justify-content:flex-end; margin:-62px 8px 18px 0; position:relative;
                 z-index:20; }
#cr-export { background:transparent !important; color:var(--cr-glow) !important;
             border:1px solid rgba(125,249,255,.35) !important;
             border-radius:var(--cr-radius) !important; box-shadow:none !important;
             min-width:0 !important; width:fit-content !important; }
#cr-export:hover { border-color:var(--cr-glow) !important; }

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

/* ── 小屏适配（设计稿断点）── */
@media (max-width:760px){
  .cr-cols { grid-template-columns:1fr; }
  .cr-col { padding-right:0; }
  .cr-col + .cr-col { padding-left:0; border-left:0; border-top:1px solid var(--cr-line); }
  .cr-facts { grid-template-columns:1fr 1fr; }
  .cr-facts > div:nth-child(3) { padding-left:0; border-left:0; }
  .cr-facts > div:nth-child(n+3) { border-top:1px solid var(--cr-line); }
  .cr-cmp { grid-template-columns:1fr; }
  .cr-cmp > div + div { padding:16px 0 0; border-left:0; border-top:1px solid var(--cr-line); }
  #cr-export-row { margin:8px 0 0; }
}
@media (max-width:640px){ .cr-band h1 { font-size:24px; margin-top:28px; } }
"""


def _e(x):
    """HTML 转义。"""
    return html.escape(str(x if x is not None else ""), quote=False)


def _attr(x):
    return html.escape(str(x if x is not None else ""), quote=True)


def _err_html(e):
    return (f'<div class="cr-wrap"><div class="cr-err">'
            f'查询过程出现异常，已捕获（不会白屏）：<br>'
            f'<code>{_e(type(e).__name__)}: {_e(str(e)[:300])}</code><br><br>'
            f'请换一句话再试。</div></div>')


# ── 页脚（红线：免责声明 + 数据截止 + 隐私提示 + 时效核验）────────────
def _footer_block(privacy=False):
    line = (f'{_e(snapshot.DISCLAIMER)}　·　数据截止：{_e(snapshot.DATA_CUTOFF)}')
    if privacy:
        line += ('<br>🔒 输入只在内存处理，不落盘、不缓存；'
                 '请勿输入个人隐私或客户敏感信息。')
    return f'<div class="cr-footer">{line}</div>' + _freshness_footer()


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
    return (f'<div class="cr-footer" style="{style}">'
            f'{parts}</div>')


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


# ── 顶部深色雷达横幅（v4 设计稿 band 区）────────────────────────────
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


def _hero_html():
    """顶部横幅（v4 设计稿）：品牌 + 衬线大标题 + 一句引导，其余一律不放。"""
    guide = ("不知道从哪开始？直接在下方用大白话提问；"
             "「合规待办」查要办什么事、右上角可导出 CSV；"
             "「变化时间线」查法规什么时候变；"
             "「模型对照」看我们和通用 AI 的区别。")
    return (
        '<div class="cr-wrap"><div class="cr-band">'
        '<div class="cr-bar"><span class="cr-brand">出海合规雷达</span></div>'
        '<h1>输入你的生意，雷达告诉你要做什么</h1>'
        '<p class="cr-lead">大白话直接问即可。每条结论都标注置信度，'
        '并附官方原文链接。</p>'
        f'<p class="cr-band-guide">{_e(guide)}</p>'
        f'{_HERO_SVG}'
        '</div></div>'
    )


# ── v5 统一视图组件（LLM 路由器入口 · 按 v4 设计稿）──────────────────
_CONF_NOTE = ("置信度：高——有官方原文且与你的产品直接相关；"
              "中——官方原文成立，但需结合产品设计或销售渠道判断；"
              "低——信息不足，需补充后再确认。")


def _cf(conf):
    cls = {"高": "hi", "中": "mid", "低": "lo"}.get(conf, "mid")
    return f'<em class="cr-cf {cls}">{_e(conf)}</em>'


def _it(title, conf, desc_html, link=None):
    """一个折叠条目（v4 .fold.it）：标题常显，点开展开说明 + 官方链接。"""
    badge = _cf(conf) if conf else ""
    a = (f'<a href="{_attr(link)}" target="_blank" rel="noopener">查看官方原文</a>'
         if link else "")
    return (f'<details class="cr-it"><summary>'
            f'<span class="cr-it-t">{title}</span>{badge}</summary>'
            f'<div class="cr-idt">{desc_html}{a}</div></details>')


def _col(title, body):
    """一个折叠板块（v4 .fold.col）：衬线标题 + 条数，默认收起。"""
    return (f'<details class="cr-col"><summary>{_e(title)}'
            f'<span class="cr-cnt">{len(body)} 项</span></summary>'
            f'<div class="cr-col-body">{"".join(body)}</div></details>')


def _facts(cat, mkt, risk):
    """事实栏（v4 .facts 四格）：品类 / 目标市场 / 风险等级 / 数据截止。"""
    return ('<dl class="cr-facts">'
            f'<div><dt>品类</dt><dd>{_e(cat or "—")}</dd></div>'
            f'<div><dt>目标市场</dt><dd>{_e(mkt or "—")}</dd></div>'
            f'<div><dt>风险等级</dt><dd>{_e(risk)}</dd></div>'
            f'<div><dt>数据截止</dt><dd>{_e(snapshot.DATA_CUTOFF)}</dd></div>'
            '</dl>')


def _law_conf(r, cross):
    """法规条目置信度：⚠️ 待核实 → 低；❓ 待确认 → 中；现行有效 → 高；
    横切法规（需结合品类判断）最多给到「中」。"""
    v = str(r.get("是否仍有效") or "")
    if v.startswith("⚠️"):
        base = "低"
    elif v.startswith("❓"):
        base = "中"
    else:
        base = "高"
    if cross and base == "高":
        base = "中"
    return base


def _law_it(r, cross):
    desc = _e(r.get("卖家提示") or "")
    meta = (f'<p><span class="cr-meta">官方编号 {_e(r.get("官方编号"))}'
            f'　·　生效 {_e(r.get("生效日期"))}'
            f'　·　{_e(r.get("监管机构"))}</span></p>')
    body = (f'<p>{desc}</p>' if desc else "") + meta
    return _it(_e(r.get("法规中文名") or r.get("官方编号") or "（未命名法规）"),
               _law_conf(r, cross), body, r.get("官方原文链接"))


def _todo_it(a):
    cond = _e(a.get("类型含义") or "")
    dl = f'⏰ 期限：{_e(a["期限"])}' if a.get("期限") else "持续义务"
    src = f'{_e(a.get("官方编号"))}　《{_e(a.get("依据法规"))}》'
    body = (f'<p>{cond}（动作类型：{_e(a.get("动作类型"))}）</p>'
            f'<p><span class="cr-meta">来源条款：{src}　·　{dl}</span></p>')
    return _it(_e(a.get("动作") or ""), a.get("紧迫度") or "中",
               body, a.get("来源条款链接"))


def _risk_from_m3(m3res):
    """风险等级（语料无风险字段，按 M3 紧迫度分布推导）。"""
    dist = ((m3res or {}).get("stats") or {}).get("紧迫度分布") or {}
    return "高" if dist.get("高", 0) else ("中" if dist.get("中", 0) else "低")


def _summary_items(res, m3res):
    """结论摘要列（v4 CONC）：计数结论 + 首要动作 + 风险等级 + 待确认 + 缺资料。
    全部由已核对语料推导，不硬编。"""
    m1 = res["m1"]
    p = m1.get("primary") or []
    c = m1.get("cross") or []
    laws = p + c
    items = []
    if laws:
        ok_n = sum(1 for r in laws
                   if not str(r.get("是否仍有效") or "").startswith(("⚠️", "❓")))
        items.append(_it(
            f'适用法规 {len(laws)} 部（主体 {len(p)} · 横切 {len(c)}）', "高",
            f'<p>其中 {ok_n} 部现行有效；每条附官方原文链接，'
            f'展开「法规原文」逐条核对。</p>',
            (p[0] or {}).get("官方原文链接")))

    dist = ((m3res or {}).get("stats") or {}).get("紧迫度分布") or {}
    k_hi = dist.get("高", 0)
    risk = _risk_from_m3(m3res)

    if m3res is None:
        items.append(_it("待办清单暂不可用", "低",
                         "<p>生成待办时出现异常，请重试。</p>"))
    else:
        a3 = m3res.get("动作") or []
        if a3:
            first = a3[0]
            items.append(_it(
                f'待办 {len(a3)} 条，高紧迫 {k_hi} 项', "高",
                f'<p>首要动作：{_e(first.get("动作"))}。</p>',
                first.get("来源条款链接")))
        else:
            items.append(_it("待办清单为空", "低",
                             "<p>该组合暂无足够已核对条款生成的待办。</p>"))

    items.append(_it(f'整体风险等级：{risk}', risk,
                     "<p>按待办紧迫度与适用法规数量综合评估，供参考。</p>"))

    for it_ in ((m3res or {}).get("待确认") or []):
        items.append(_it(_e(it_.get("需确认") or ""), "中",
                         f'<p>影响：{_e(it_.get("影响"))}　'
                         f'如何核对：{_e(it_.get("如何核对"))}</p>'))
    for m in (res.get("missing") or [])[:3]:
        items.append(_it(_e(m), "低",
                         "<p>补充该信息后，这一单的判定会更准。</p>"))
    return items, risk


def render_judge(text, res, m3res):
    """智能判定结果（v4 设计稿 judge 面板）：echo → 事实栏 → 图例 → 三列。"""
    summary_items, risk = _summary_items(res, m3res)
    m1 = res["m1"]
    law_items = ([_law_it(r, False) for r in (m1.get("primary") or [])]
                 + [_law_it(r, True) for r in (m1.get("cross") or [])])
    if law_items:
        law_col = _col("法规原文", law_items)
    else:
        law_col = _col("法规原文", ['<div class="cr-empty">该品类在当前市场暂无语料条目。</div>'])

    if m3res is None:
        todo_col = _col("待办清单", ['<div class="cr-empty">待办清单生成失败，请重试。</div>'])
    else:
        todo_items = [_todo_it(a) for a in (m3res.get("动作") or [])]
        if todo_items:
            todo_col = _col("待办清单", todo_items)
        else:
            todo_col = _col("待办清单", ['<div class="cr-empty">该组合暂无可执行待办。</div>'])

    cols = ('<div class="cr-cols">'
            + _col("结论摘要", summary_items) + todo_col + law_col
            + '</div>')

    echo = f'<p class="cr-echo">判定依据：「{_e(text)}」</p>'
    note = res.get("note") or ""
    note_html = f'<div class="cr-note">ℹ️ {_e(note)}</div>' if note else ""
    # 如实披露（红线：不硬编）—— 未产出动作与被引用对齐拦下的条目，压成一行
    extra = ""
    un = (m3res or {}).get("未产出") or []
    if un:
        extra += (f'<div class="cr-note">另有 {len(un)} 条语料暂无明确动作，'
                  f'按规格未上清单（如实不硬编）。</div>')
    dropped = (m3res or {}).get("dropped") or (m1.get("dropped") or [])
    if dropped:
        extra += (f'<div class="cr-note">引用对齐拦下 {len(dropped)} 条'
                  f'（无官方链接 / 语料库外的编号，按红线不输出）。</div>')

    return (f'<div class="cr-wrap">{echo}{note_html}'
            f'{_facts(res["品类"], res["市场"], risk)}'
            f'<p class="cr-legend">{_e(_CONF_NOTE)}</p>'
            f'{cols}{extra}{_footer_block(privacy=True)}</div>')


def _tl_li(r, upcoming):
    ref = "" if r.get("官方确认") else " · 参考日期"
    if upcoming:
        hint = f'即将生效 · {_e(r.get("日期", ""))} · {_e(r.get("距今", ""))}{ref}'
    else:
        hint = (f'{_e(r.get("日期", ""))} · {_e(r.get("距今", ""))} · '
                f'{_e(r.get("事件类型", ""))}{ref}')
    p = _e(r.get("变化摘要") or "")
    imp = _e(r.get("影响说明") or "")
    if imp and imp != p:
        p += f'　影响：{imp}'
    link = r.get("官方链接") or ""
    a = (f'　<a href="{_attr(link)}" target="_blank" rel="noopener">官方原文</a>'
         if str(link).startswith("http") else "")
    return (f'<li><span class="cr-hint">{hint}</span>'
            f'<strong>{_e(r.get("法规中文名", ""))}</strong>'
            f'<p>{p}{a}</p></li>')


def render_timeline(m2res):
    """变化时间线结果（v4 设计稿 tlist）：即将生效在前，历史在后。"""
    if not m2res.get("ok"):
        return (f'<div class="cr-wrap"><div class="cr-err">'
                f'{_e(m2res.get("reason") or "该输入暂无可核验的时间线数据。")}'
                f'</div></div>')
    s = m2res.get("stats") or {}
    lis = [_tl_li(r, True) for r in (m2res.get("即将发生") or [])]
    lis += [_tl_li(r, False) for r in (m2res.get("近窗内") or [])]
    if lis:
        body = '<ol class="cr-tlist">' + "".join(lis) + '</ol>'
    else:
        body = ('<div class="cr-empty">当前语料未收录可展示的相关日期事件，'
                '不代表没有法规变化。</div>')
    echo = (f'<p class="cr-echo">时间窗：{_e(m2res.get("时间窗", ""))} · '
            f'近窗 {s.get("近窗内条数", 0)} 条 · 即将发生 {s.get("即将发生条数", 0)} 条'
            f' · 数据截止 {_e(snapshot.DATA_CUTOFF)}</p>')
    return f'<div class="cr-wrap">{echo}{body}{_footer_block(privacy=True)}</div>'


def render_todo(text, res, m3res):
    """合规待办页（M3 独立入口）：echo → 事实栏 → 待办折叠列表 → 如实披露 → 页脚。"""
    if m3res is None:
        return ('<div class="cr-wrap"><div class="cr-err">'
                '待办清单生成失败，请重试。</div></div>')
    if not m3res.get("ok"):
        return (f'<div class="cr-wrap"><div class="cr-err">'
                f'{_e(m3res.get("reason") or "该输入暂无可核验的待办数据。")}'
                f'</div></div>')
    a3 = m3res.get("动作") or []
    body = "".join(_todo_it(a) for a in a3) if a3 else \
        '<div class="cr-empty">该组合暂无可执行待办。</div>'
    k_hi = ((m3res.get("stats") or {}).get("紧迫度分布") or {}).get("高", 0)
    echo = (f'<p class="cr-echo">判定依据：「{_e(text)}」 · '
            f'待办 {len(a3)} 条 · 高紧迫 {k_hi} 项</p>')
    note = res.get("note") or ""
    note_html = f'<div class="cr-note">ℹ️ {_e(note)}</div>' if note else ""
    extra = ""
    un = m3res.get("未产出") or []
    if un:
        extra += (f'<div class="cr-note">另有 {len(un)} 条语料暂无明确动作，'
                  f'按规格未上清单（如实不硬编）。</div>')
    dropped = m3res.get("dropped") or []
    if dropped:
        extra += (f'<div class="cr-note">引用对齐拦下 {len(dropped)} 条'
                  f'（无官方链接 / 语料库外的编号，按红线不输出）。</div>')
    return (f'<div class="cr-wrap">{echo}{note_html}'
            f'{_facts(res["品类"], res["市场"], _risk_from_m3(m3res))}'
            f'<p class="cr-legend">{_e(_CONF_NOTE)}</p>'
            f'{body}{extra}{_footer_block(privacy=True)}</div>')


def render_cmp():
    """模型对照（v4 设计稿 cmp 两栏 + 折叠的固定题干 / 历史回放）。"""
    res = m4_compare.query()
    replays = res.get("回放列表") or []
    parts = ['<div class="cr-wrap">'
             '<div class="cr-cmp">'
             '<div><h4>通用 AI</h4><p>凭训练数据作答，法规可能已过时，'
             '通常没有可核对的官方原文。</p></div>'
             '<div><h4>合规雷达</h4><p>结论来自核对语料，每条附官方链接，'
             '并标注置信度与数据截止日期。</p></div>'
             '</div>']
    if res.get("固定题干"):
        parts.append(_it("固定题干", None, f'<p>{_e(res["固定题干"])}</p>'))
    for k, r in enumerate(replays, 1):
        inner = (f'<p><b>通用侧原答</b>：{_e(r.get("generic_answer", ""))}</p>'
                 f'<p><b>本工具侧</b>：{_e(r.get("tool_answer", ""))}</p>'
                 f'<p><span class="cr-meta">核验状态：{_e(r.get("verdict", "未核验"))}'
                 f'　·　录制于 {_e(r.get("timestamp", "-"))}</span></p>')
        parts.append(_it(f'历史回放 {k} · {_e(r.get("generic_model_name", "-"))}',
                         None, inner))
    if not replays:
        parts.append('<p class="cr-echo" style="margin-top:14px">'
                     '历史回放待录制后上线。</p>')
    parts.append(_footer_block())
    parts.append('</div>')
    return "".join(parts)


# ── 回调 ──────────────────────────────────────────────────────
def _safe(fn):
    """任何异常都不白屏：失败返回 None，由渲染层给诚实提示。"""
    try:
        return fn()
    except Exception:  # noqa: BLE001
        return None


def run_route(text, context):
    """智能判定回调：LLM 路由 → 结论摘要 / 待办清单 / 法规原文 三列。
    返回 (HTML, 品类, 市场)——后两个进 State 供导出 CSV 用。"""
    try:
        res = m15_router.route(text, context)
        if not res.get("ok"):
            return m15_router.render_parse(res), "", ""
        m3res = _safe(lambda: m3_todo.query(res["品类"], res["市场"],
                                            use_llm=False))
        return (render_judge((text or "").strip(), res, m3res),
                res["品类"], res["市场"])
    except Exception as e:  # noqa: BLE001
        return _err_html(e), "", ""


def run_timeline(text, context):
    """变化时间线回调：同一个 LLM 路由器识别品类×市场 → 时间线列表。"""
    try:
        res = m15_router.route(text, context)
        if not res.get("ok"):
            return m15_router.render_parse(res)
        m2res = _safe(lambda: m2_timeline.query(
            res["品类"], res["市场"], window=m2_timeline.DEFAULT_WINDOW,
            use_llm=False))
        if m2res is None:
            return _err_html(Exception("时间线查询异常"))
        return render_timeline(m2res)
    except Exception as e:  # noqa: BLE001
        return _err_html(e)


def run_todo(text, context):
    """合规待办回调：LLM 路由识别品类×市场 → M3 完整待办清单。
    返回 (HTML, 品类, 市场)——后两个回填 State，导出按钮跟随最近查询。"""
    try:
        res = m15_router.route(text, context)
        if not res.get("ok"):
            return m15_router.render_parse(res), "", ""
        m3res = _safe(lambda: m3_todo.query(res["品类"], res["市场"],
                                            use_llm=False))
        if m3res is None:
            return _err_html(Exception("待办查询异常")), "", ""
        return (render_todo((text or "").strip(), res, m3res),
                res["品类"], res["市场"])
    except Exception as e:  # noqa: BLE001
        return _err_html(e), "", ""


_DEFAULT_Q = "我要把洋娃娃卖到美国去，要做哪些合规工作？"


def _route_initial():
    """智能判定页签的初始展示（词典路径，不联网、零成本）。
    返回 (HTML, 品类, 市场)。"""
    try:
        res = m15_router.route(_DEFAULT_Q, "", use_llm=False)
        if res.get("ok"):
            m3res = _safe(lambda: m3_todo.query(res["品类"], res["市场"],
                                                use_llm=False))
            return (render_judge(_DEFAULT_Q, res, m3res),
                    res["品类"], res["市场"])
        return m15_router.render_parse(res), "", ""
    except Exception as e:  # noqa: BLE001
        return _err_html(e), "", ""


def _timeline_initial():
    """变化时间线页签的初始展示（词典路径，不联网、零成本）。"""
    try:
        res = m15_router.route(_DEFAULT_Q, "", use_llm=False)
        if res.get("ok"):
            m2res = _safe(lambda: m2_timeline.query(
                res["品类"], res["市场"], window=m2_timeline.DEFAULT_WINDOW,
                use_llm=False))
            if m2res:
                return render_timeline(m2res)
        return ('<div class="cr-wrap"><p class="cr-echo">'
                '输入你的生意，查询对应市场的法规变化。</p></div>')
    except Exception as e:  # noqa: BLE001
        return _err_html(e)


def _todo_initial():
    """合规待办页签的初始展示（词典路径，不联网、零成本）。
    返回 (HTML, 品类, 市场)。"""
    try:
        res = m15_router.route(_DEFAULT_Q, "", use_llm=False)
        if res.get("ok"):
            m3res = _safe(lambda: m3_todo.query(res["品类"], res["市场"],
                                                use_llm=False))
            if m3res:
                return (render_todo(_DEFAULT_Q, res, m3res),
                        res["品类"], res["市场"])
        return ('<div class="cr-wrap"><p class="cr-echo">'
                '输入你的生意，查询要办的合规事项；右上角可导出 CSV。</p></div>',
                "", "")
    except Exception as e:  # noqa: BLE001
        return _err_html(e), "", ""


def export_m3_csv(category, market):
    """导出 M3 清单为 CSV，返回文件路径（失败返回 None）。"""
    res = m3_todo.query(category or "", market or "", use_llm=False)
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
    _major = int(gr.__version__.split(".")[0])
    _blocks_kwargs = {"title": "出海合规雷达 ComplianceRadar"}
    if _major < 6:
        _blocks_kwargs.update(css=_CSS, theme=gr.themes.Soft())

    # 初始展示（词典路径，不联网、零成本）：各页签直接铺好默认示例的结果
    init_html, init_cat, init_mkt = _route_initial()
    init_tl = _timeline_initial()
    init_todo, _td_cat, _td_mkt = _todo_initial()

    with gr.Blocks(**_blocks_kwargs) as demo:
        # 开场雷达 CG（~2s 自动淡出，纯 CSS，不阻塞交互）
        # + 顶部深色雷达横幅（v4 设计稿 band 区）
        gr.HTML(_INTRO_HTML)
        gr.HTML(_hero_html())

        # 判定槽位（品类×市场）：run_route 回填，供导出 CSV 使用
        cat_s, mkt_s = gr.State(init_cat), gr.State(init_mkt)

        # 导出按钮：视觉上叠加在横幅右上（v4 设计稿 band 的 link 位）
        with gr.Row(elem_id="cr-export-row"):
            csv_btn = gr.DownloadButton(
                "导出 CSV", elem_id="cr-export", scale=0,
                value=lambda c, m: export_m3_csv(c, m),
                inputs=[cat_s, mkt_s])

        with gr.Tabs():
            # ── ① 智能判定（统一 LLM 路由器入口）──────────────
            with gr.Tab("智能判定"):
                q_text = gr.Textbox(
                    lines=3, value=_DEFAULT_Q,
                    label="你的生意（一句话，或整份产品/合同文件）",
                )
                with gr.Accordion("补充上下文（选填，仅辅助识别，不存储）",
                                  open=False):
                    q_ctx = gr.Textbox(
                        lines=2, value="", show_label=False,
                        placeholder="例：产品材质 / 结构、适用年龄、客户要求…")
                with gr.Row(elem_id="cr-run-row"):
                    q_btn = gr.Button("开始判定", variant="primary",
                                      elem_id="cr-run", scale=0)
                q_out = gr.HTML(init_html)

            # ── ② 变化时间线（同一个 LLM 路由器）──────────────
            with gr.Tab("变化时间线"):
                t_text = gr.Textbox(
                    lines=3, value=_DEFAULT_Q,
                    label="你的生意（一句话，或整份产品/合同文件）",
                )
                with gr.Accordion("补充上下文（选填，仅辅助识别，不存储）",
                                  open=False):
                    t_ctx = gr.Textbox(
                        lines=2, value="", show_label=False,
                        placeholder="例：产品材质 / 结构、适用年龄、客户要求…")
                with gr.Row(elem_id="cr-run2-row"):
                    t_btn = gr.Button("查询时间线", variant="primary",
                                      elem_id="cr-run2", scale=0)
                t_out = gr.HTML(init_tl)

            # ── ③ 合规待办（M3 独立入口，同一个 LLM 路由器）────
            with gr.Tab("合规待办"):
                d_text = gr.Textbox(
                    lines=3, value=_DEFAULT_Q,
                    label="你的生意（一句话，或整份产品/合同文件）",
                )
                with gr.Accordion("补充上下文（选填，仅辅助识别，不存储）",
                                  open=False):
                    d_ctx = gr.Textbox(
                        lines=2, value="", show_label=False,
                        placeholder="例：产品材质 / 结构、适用年龄、客户要求…")
                with gr.Row(elem_id="cr-run3-row"):
                    d_btn = gr.Button("查询待办", variant="primary",
                                      elem_id="cr-run3", scale=0)
                d_out = gr.HTML(init_todo)

            # ── ④ 模型对照（固定，无输入）─────────────────────
            with gr.Tab("模型对照"):
                m4_out = gr.HTML(render_cmp())

        # 事件绑定（Ctrl+Enter / 回车可直接提交）
        q_btn.click(run_route, inputs=[q_text, q_ctx],
                    outputs=[q_out, cat_s, mkt_s])
        q_text.submit(run_route, inputs=[q_text, q_ctx],
                      outputs=[q_out, cat_s, mkt_s])
        t_btn.click(run_timeline, inputs=[t_text, t_ctx], outputs=t_out)
        t_text.submit(run_timeline, inputs=[t_text, t_ctx], outputs=t_out)
        d_btn.click(run_todo, inputs=[d_text, d_ctx],
                    outputs=[d_out, cat_s, mkt_s])
        d_text.submit(run_todo, inputs=[d_text, d_ctx],
                      outputs=[d_out, cat_s, mkt_s])

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
