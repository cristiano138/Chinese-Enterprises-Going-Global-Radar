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

# Gradio probes its own loopback URL during startup. Keep local traffic local
# even on developer machines with a global HTTP proxy, preserving other bypasses.
for _proxy_key in ("NO_PROXY", "no_proxy"):
    _bypass = [part for part in os.environ.get(_proxy_key, "").split(",") if part]
    os.environ[_proxy_key] = ",".join(dict.fromkeys(_bypass + ["localhost", "127.0.0.1", "0.0.0.0"]))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# llm 先读取项目 .env，ASR 随后才能取得文件中的配置。
from core import llm  # noqa: E402
from core import asr, corpus, law_store, snapshot, verify  # noqa: E402
from modules import (m1_map, m2_timeline, m3_todo, m4_compare, m5_compare,  # noqa: E402
                     m6_multi_region, m7_opc_readiness, m15_router)

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
:root{--cr-brand:#b98216;--cr-brand-2:#e1b84d;--cr-brand-soft:#fff3c9;
      --cr-bg:#fff9ec;--cr-ink:#3b3427;--cr-ink2:#766b59;--cr-ink3:#a79b86;
      --cr-line:#eee2c7;--cr-radius:14px;--cr-night:#4b3b22;
      --cr-beam:#e1b84d;--cr-glow:#fff0bd;
      --cr-hi:#4c8c62;--cr-mid:#a46f1a;--cr-lo:#ba554c;
      --cr-serif:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif}
html, body, body > div, .gradio-container, .gradio-container > .main, .gradio-container .main, .gradio-container .contain {
  background: var(--cr-bg) !important;
  color: var(--cr-ink) !important;
}
body { min-width: 320px !important; }
/* 内嵌媒体查询保留根选择器，避免 Gradio 6 为顶层媒体规则添加 .contain 前缀。 */
.gradio-container { max-width: 1440px !important; padding: 18px 24px 42px 264px !important;
  @media (max-width:1050px) { padding-left:220px !important; }
  @media (max-width:760px) { padding-left:12px !important; }
  @media (max-width:640px) { padding:12px 10px 28px !important; }
}
.gradio-container .main { background: transparent !important; }
footer { background: var(--cr-bg) !important; }
.gradio-container .contain { width:100%; min-width:0; max-width: 1180px !important; margin: 0 auto !important; }
.cr-wrap { font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
           color:var(--cr-ink); }
.gradio-container button { border-radius:10px !important; font-weight:600 !important; }
.gradio-container button.primary { background:var(--cr-brand) !important; border-color:var(--cr-brand) !important; box-shadow:0 5px 14px rgba(185,130,22,.18); color:#fff !important; }
.gradio-container button.primary:hover { background:#976b12 !important; }
.gradio-container button.secondary { border-color:#e4d3a9 !important; color:#70551e !important; background:#fffdf7 !important; }
.gradio-container input, .gradio-container textarea, .gradio-container select { border-radius:10px !important; border-color:#e6d8b9 !important; background:#fffefa !important; }
.gradio-container label span { color:var(--cr-ink2) !important; font-weight:600 !important; }
/* ── 参考工作台：左侧导航 + 轻量顶部状态 + 明亮概览 ── */
.cr-shell { display:grid; grid-template-columns:220px minmax(0,1fr); gap:22px; align-items:start; }
.cr-sidebar { position:fixed; z-index:20; left:18px; top:18px; width:220px; box-sizing:border-box; background:#fffdf7; border:1px solid var(--cr-line); border-radius:16px; padding:16px 12px; box-shadow:0 8px 24px rgba(137,105,35,.07); }
.cr-side-brand { display:flex; align-items:center; gap:10px; padding:8px 10px 18px; border-bottom:1px solid var(--cr-line); color:var(--cr-ink); font-weight:800; font-size:16px; }
.cr-side-logo { width:30px; height:30px; display:grid; place-items:center; border-radius:9px; background:#f7e4a9; color:#8c6414; font-size:16px; }
.cr-side-label { padding:18px 10px 7px; color:var(--cr-ink3); font-size:11px; letter-spacing:.08em; }
.cr-side-item { display:flex; align-items:center; gap:9px; padding:10px; margin:3px 0; border-radius:10px; color:var(--cr-ink2); font-size:13px; }
.cr-side-item.active { color:#765514; background:#fff1bf; font-weight:700; }
.cr-side-item span:first-child { width:20px; text-align:center; }
.cr-side-foot { margin:18px 4px 2px; padding:12px 10px; border-radius:11px; background:#fff7dc; color:var(--cr-ink2); font-size:11px; line-height:1.65; }
.cr-main { min-width:0; }
.cr-band { position:relative; overflow:hidden; border-radius:16px; background:#fffdf7;
           color:var(--cr-ink); border:1px solid var(--cr-line); padding:22px 26px 20px; box-shadow:0 8px 24px rgba(137,105,35,.06); }
.cr-band::after { content:""; position:absolute; width:260px; height:260px; right:-70px; top:-150px;
                  border:1px solid #ead9a6; border-radius:50%; box-shadow:0 0 0 30px rgba(231,201,115,.12),0 0 0 60px rgba(231,201,115,.08); }
.cr-band .cr-bar { display:flex; align-items:center; gap:12px; position:relative; z-index:1; }
.cr-brand { font-size:17px; font-weight:800; color:#795714; letter-spacing:.02em; font-family:var(--cr-serif); }
.cr-band h1 { font-size:28px; font-weight:750; line-height:1.3; margin:22px 0 8px;
              max-width:760px; font-family:var(--cr-serif); color:var(--cr-ink); position:relative; z-index:1; }
.cr-lead { margin:0; color:var(--cr-ink2); max-width:760px; font-size:14px; position:relative; z-index:1; }
.cr-band-guide { margin:10px 0 0; color:var(--cr-ink3); font-size:12.5px; max-width:820px; position:relative; z-index:1; }
.cr-band-meta { margin:16px 0 0; padding-top:11px; border-top:1px solid var(--cr-line);
                color:var(--cr-ink3); font-size:12px; position:relative; z-index:1; }
.cr-scope { position:absolute; right:36px; top:50%; width:190px; height:190px;
            transform:translateY(-50%); opacity:.28; }
.cr-overview { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; margin:16px 0 18px; }
.cr-stat { background:#fffdf7; border:1px solid var(--cr-line); border-radius:13px; padding:14px 15px; box-shadow:0 5px 16px rgba(137,105,35,.045); }
.cr-stat-k { color:var(--cr-ink3); font-size:11px; margin-bottom:7px; }
.cr-stat-v { color:var(--cr-ink); font-size:22px; font-weight:800; line-height:1; }
.cr-stat-s { margin-top:7px; color:var(--cr-ink2); font-size:11px; }
.cr-panel { background:#fffdf7; border:1px solid var(--cr-line); border-radius:15px; padding:18px; box-shadow:0 6px 20px rgba(137,105,35,.05); }
@media (max-width:1050px) { .cr-sidebar { left:12px; width:190px; } .cr-scope { right:-18px; opacity:.18; } }
@media (max-width:760px) { .cr-shell { display:block; } .cr-sidebar { position:static; display:flex; align-items:center; gap:7px; overflow:auto; width:auto; padding:8px; margin-bottom:14px; } .cr-side-brand { border:0; padding:5px 9px; white-space:nowrap; } .cr-side-label,.cr-side-foot { display:none; } .cr-side-item { margin:0; white-space:nowrap; padding:8px 9px; } .cr-overview { grid-template-columns:repeat(2,minmax(0,1fr)); } }
@media (max-width:640px) { .cr-band { padding:18px 17px 16px; border-radius:13px; } .cr-band h1 { font-size:23px; margin-top:18px; } .cr-band-guide { line-height:1.7; } .cr-band-meta { line-height:1.8; } .cr-overview { gap:8px; margin-top:12px; } .cr-stat { padding:12px; } .cr-stat-v { font-size:19px; } }
/* ── 结果区元数据条 ── */
.cr-header { background:#f9fbff; border:1px solid var(--cr-line); border-radius:12px;
             padding: 12px 14px; font-size: 12.5px; color: var(--cr-ink2);
             margin: 16px 0; line-height: 1.7; box-shadow:0 3px 12px rgba(35,54,90,.04); }
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
.cr-mod-n_a     { color:var(--cr-ink3); }
.cr-head { font-size: 15px; color:var(--cr-ink); margin: 6px 0 12px; }
.cr-head b { font-size:20px; font-family:var(--cr-serif); font-weight:600; }
.cr-sec { margin: 18px 0 8px; font-size: 16px; font-weight: 600; color:var(--cr-ink);
          border-left: 3px solid var(--cr-brand); padding-left: 8px;
          font-family:var(--cr-serif); }
.cr-card { border:1px solid var(--cr-line); border-radius:12px;
           padding: 16px; margin:10px 0; background:#f9fbff;
           box-shadow:0 4px 16px rgba(35,54,90,.045); content-visibility:auto; contain-intrinsic-size:auto 220px; }
.cr-title { font-size: 15px; font-weight: 600; color:var(--cr-ink); margin-bottom: 6px; }
.cr-badge { display:inline-block; font-size:12px; padding:1px 6px; border-radius:3px;
            margin-left:6px; vertical-align: middle;
            border:1px solid currentColor; background:transparent; }
/* ── 语音回显：先把「听到什么」摆在结论之前 ── */
.cr-echo { margin:0 0 12px; padding:12px 14px; border-radius:12px;
           background:#fff7dc; border:1px solid #efdfae; border-left:4px solid var(--cr-brand);
           color:var(--cr-ink); font-size:13.5px; line-height:1.7; }
.cr-echo b { color:#795714; }
.cr-echo .cr-echo-meta { margin-top:6px; color:var(--cr-ink2); font-size:12px; line-height:1.65; }
/* 窄屏：语音块整块落到输入框上方，避免被压成竖排小字与输入框抢宽 */
@media (max-width:760px) {
  .cr-voice-row { flex-direction:column !important; align-items:stretch !important; gap:10px !important; }
  .cr-voice-row > * { width:100% !important; min-width:0 !important; }
}
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
.cr-row code { background:#f1f1ec; padding:1px 5px; border-radius:3px;
               font-family: ui-monospace, Consolas, monospace; font-size:12.5px; }
.cr-a { color:var(--cr-brand); text-decoration:none; word-break:break-all; }
.cr-a:hover { text-decoration: underline; }
.cr-note { font-size:12.5px; color:var(--cr-mid); background:#f9f6ee;
           border:1px solid #e7dfc9; border-radius:var(--cr-radius);
           padding:8px 10px; margin:14px 0; }
.cr-dis { font-size:12.5px; color:var(--cr-ink3); border-top:1px dashed var(--cr-line);
          margin-top:16px; padding-top:10px; }
.cr-footer { font-size:12px; color:var(--cr-ink3); background:transparent;
             border-top:1px solid var(--cr-line); border-radius:0;
             padding:10px 2px 2px; margin-top:16px;
             display:flex; align-items:flex-start; gap:8px; }
.cr-footer b { color:var(--cr-ink2); }
.cr-err { border:1px solid #e5c8c4; background:#faf0ee; border-radius:var(--cr-radius);
          padding:14px; color:var(--cr-lo); font-size:14px; line-height:1.7; }
.cr-tl { border-left: 2px solid var(--cr-line); margin: 6px 0 0 6px; padding-left: 12px; }
.cr-tl .cr-card { position: relative; }
.cr-date { font-family: ui-monospace, Consolas, monospace; font-size: 14px;
           font-weight: 600; color:var(--cr-ink); }
.cr-empty { font-size:13px; color:var(--cr-ink2); background:transparent;
            border:1px dashed #d8d8d0; border-radius:var(--cr-radius);
            padding:10px 12px; margin:8px 0; }

/* ── 可折叠板块（v2）：细线 + 衬线标题 + 右侧箭头（v4 折叠样式）──
   summary 常显（标题 + 条数 + 提示），收起内容不参与渲染（content-visibility）*/
.cr-group { border:1px solid var(--cr-line); border-radius:12px;
            margin: 14px 0 10px; background:#f9fbff; overflow:hidden; box-shadow:0 3px 12px rgba(35,54,90,.035); }
.cr-group > summary { cursor: pointer; list-style: none; padding: 14px 16px;
                      font-size: 16px; font-weight: 700; color: var(--cr-ink);
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
.cr-group-body { padding: 2px 16px 14px;
                 content-visibility: auto; contain-intrinsic-size: auto 600px; }
.gradio-container .tabs { margin-top:18px; }
.gradio-container .tab-nav { gap:6px; border-bottom:1px solid var(--cr-line); padding:0 4px; }
.gradio-container .tab-nav button { border:0 !important; background:transparent !important; color:var(--cr-ink2) !important; padding:12px 14px !important; border-radius:10px 10px 0 0 !important; }
.gradio-container .tab-nav button.selected { color:var(--cr-brand) !important; background:var(--cr-brand-soft) !important; box-shadow:inset 0 -2px 0 var(--cr-brand); }
.gradio-container .block { border-color:var(--cr-line) !important; }
.cr-section-intro { color:var(--cr-ink2); font-size:14px; margin:10px 0 16px; line-height:1.7; }
.cr-quick { display:flex; gap:10px; flex-wrap:wrap; margin:12px 0 18px; }
.cr-quick span { padding:8px 12px; background:#f9fbff; border:1px solid var(--cr-line); border-radius:999px; color:var(--cr-ink2); font-size:12px; }

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

/* ── 进入 CG：品牌启动动画（约 2.6s，pointer-events:none 不阻塞交互）──
   视觉节奏：网格亮起 → 雷达扫描 → 数据点汇聚 → 品牌标题出现 → 平滑淡出。 */
.cr-intro { position:fixed; inset:0; z-index:9999; display:flex; flex-direction:column;
            align-items:center; justify-content:center; gap:18px; pointer-events:none;
            overflow:hidden; background:linear-gradient(135deg,#0d1b38 0%,#172f68 55%,#0f4aa8 100%);
            animation:crIntroOut 2.6s cubic-bezier(.4,0,.2,1) forwards; }
.cr-intro::before { content:""; position:absolute; inset:0; opacity:.22;
  background-image:linear-gradient(rgba(142,180,255,.22) 1px,transparent 1px),linear-gradient(90deg,rgba(142,180,255,.22) 1px,transparent 1px);
  background-size:42px 42px; transform:scale(1.08); animation:crGridIn 1.4s ease-out forwards; }
.cr-intro::after { content:""; position:absolute; width:520px; height:520px; border:1px solid rgba(145,181,255,.16); border-radius:50%; box-shadow:0 0 0 34px rgba(145,181,255,.07),0 0 0 68px rgba(145,181,255,.04); animation:crOrbitIn 1.2s ease-out forwards; }
.cr-intro .cr-radar { position:relative; z-index:1; width:190px; height:190px; }
.cr-intro .cr-radar i { position:absolute; inset:0; border:1px solid rgba(182,211,255,.5); border-radius:50%; opacity:0; animation:crRingIn .65s ease-out forwards; }
.cr-intro .cr-radar i:nth-child(2) { inset:30px; animation-delay:.12s; }
.cr-intro .cr-radar i:nth-child(3) { inset:60px; animation-delay:.24s; }
.cr-intro .cr-radar::before,.cr-intro .cr-radar::after { content:""; position:absolute; background:rgba(182,211,255,.35); }
.cr-intro .cr-radar::before { width:100%; height:1px; left:0; top:50%; }
.cr-intro .cr-radar::after { height:100%; width:1px; left:50%; top:0; }
.cr-intro .cr-sweep { position:absolute; inset:0; border-radius:50%;
  background:conic-gradient(from 0deg,rgba(97,160,255,.76),rgba(97,160,255,0) 72deg);
  transform-origin:50% 50%; animation:crSweep 1.25s linear infinite; }
.cr-intro .cr-blip { position:absolute; z-index:2; width:8px; height:8px; border-radius:50%; background:#dbe9ff; box-shadow:0 0 0 5px rgba(121,177,255,.2),0 0 18px #8dbbff; opacity:0; animation:crBlipIn .45s ease-out forwards,crBlink .9s ease-in-out .45s infinite; }
.cr-intro-name { position:relative; z-index:1; color:#fff; font-size:22px; font-weight:700; letter-spacing:.15em; opacity:0; transform:translateY(8px); animation:crFadeIn .55s .55s forwards; }
.cr-intro-sub { position:relative; z-index:1; color:rgba(220,233,255,.76); font-size:12px; letter-spacing:1.5px; opacity:0; animation:crFadeIn .5s .9s forwards; }
.cr-intro-progress { position:relative; z-index:1; width:180px; height:2px; margin-top:4px; background:rgba(255,255,255,.18); overflow:hidden; opacity:0; animation:crFadeIn .35s .75s forwards; }
.cr-intro-progress::after { content:""; display:block; width:45%; height:100%; background:#9bc4ff; box-shadow:0 0 12px #9bc4ff; animation:crProgress 1.5s ease-in-out infinite; }
@keyframes crSweep { to { transform:rotate(360deg); } }
@keyframes crGridIn { from { opacity:0; transform:scale(1.2); } to { opacity:.22; transform:scale(1); } }
@keyframes crOrbitIn { from { opacity:0; transform:scale(.7) rotate(-20deg); } to { opacity:1; transform:scale(1) rotate(0); } }
@keyframes crRingIn { from { opacity:0; transform:scale(.65); } to { opacity:1; transform:scale(1); } }
@keyframes crBlipIn { from { opacity:0; transform:scale(.2); } to { opacity:1; transform:scale(1); } }
@keyframes crBlink { 0%,100% { opacity:1; } 50% { opacity:.3; } }
@keyframes crFadeIn { to { opacity:1; transform:translateY(0); } }
@keyframes crProgress { 0% { transform:translateX(-120%); } 100% { transform:translateX(340%); } }
@keyframes crIntroOut { 0%,78% { opacity:1; visibility:visible; } 100% { opacity:0; visibility:hidden; } }
@media (prefers-reduced-motion:reduce) { .cr-intro { display:none; } }
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
    """渲染可核验链接（主链接 + ELI 永久标识）。

    ⚠️ ELI 取值的三个来源，缺一不可：
      · M1 记录：m1_map 已把底表「ELI标识」映射成「ELI链接」；
      · M2 事件 / M3 动作：**没有**「ELI链接」这个键，ELI 在「全部官方链接」列表里。
    早期只读 r["ELI链接"]，于是 M2/M3 的欧盟 ELI 永久标识被静默丢掉 ——
    链接还在（主链接正常），但少了那条「编号永不变」的兜底入口。
    """
    links, seen = [], set()
    primary = r.get(key_primary) or ""
    eli = r.get("ELI链接") or ""
    if not eli:
        for url in (r.get("全部官方链接") or []):
            if isinstance(url, str) and "data.europa.eu/eli" in url:
                eli = url
                break
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
    它们是静态信息，与单次查询无关，属冗余内容；免责声明保留——红线）。

    模块名与状态中文名统一取自 core.snapshot（MODULE_NAMES / MODULE_CN），
    不在 UI 层再维护一份映射 —— 否则新增模块时两处必然走偏。
    """
    if not meta:
        return ""
    mod = meta.get("模块状态", {})
    mod_html = "　".join(
        f'<span class="cr-mod cr-mod-{_attr(v)}">'
        f'{_e(snapshot.MODULE_NAMES.get(k, k))}·{_e(snapshot.MODULE_CN.get(v, v))}</span>'
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
    '<div class="cr-intro-progress" aria-hidden="true"></div>'
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
    total = d.get("total", 0)
    # 新版口径：content_verified 才叫“取得内容”；HTTP 可达不等于拿到内容。
    verified = d.get("content_verified", d.get("ok", 0))
    empty = d.get("empty_content", 0)
    limited = d.get("rate_limited", 0)
    link_bad = d.get("link_error", 0)
    net_bad = d.get("net_error", 0)
    changed = d.get("changed", 0)
    style = ("background:#eaf4ee;border-color:#cfe4d6" if link_bad == 0
             else "background:#f7f1e2;border-color:#e5d9bd")
    parts = (f"官方链接最近核验：{_e(d.get('checked_at', ''))}（北京时间）· "
             f"{total} 个链接，{verified} 条取得内容")
    if empty:
        parts += f" · {empty} 条官方空响应（未取得内容）"
    if limited:
        parts += f" · {limited} 条被官方限流（待下次重试）"
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

    ④ 的措辞说明：语料底表**没有收录条文正文**，「证据摘录」实际是一句话中文
    要点（AI 预生成、已固化进 CSV）。PRD 要求「原文摘录可附审核后的中文解释，
    英文原文保持可见」，所以这一格拆成两行：先给官方英文标题（可核验的原文，
    来自底表），再明确标注中文要点的来源与性质 —— 不能把 AI 摘要直接标成
    「原文摘录」，那是把不可核验的内容伪装成条文原文。
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

    raw = r.get("_raw") or {}
    en_title = (raw.get("官方标题（英文）") or "").strip()
    zh_digest = (r.get("证据摘录") or "").strip()
    excerpt_rows = (
        f'<div><b>原文标题（英文）</b>：'
        f'{_e(en_title) if en_title else "（底表未收录英文标题）"}</div>'
        + (f'<div style="color:#8a91a3">中文要点（AI 预生成，非条文原文）：'
           f'{_e(zh_digest)}</div>' if zh_digest else "")
    )

    # 证据链展开区（D5-1 五步）
    evidence = (
        '<div class="cr-evidence">'
        f'<div><b>① 执行动作</b>：{_e(r["动作"])}</div>'
        f'<div><b>② 适用条件</b>：{_e(r.get("类型含义", ""))}'
        f'（动作类型：{_e(r["动作类型"])}）</div>'
        f'<div><b>③ 来源条款</b>：{_e(r["官方编号"])}　'
        f'《{_e(r["依据法规"])}》</div>'
        f'<div><b>④ 原文摘录</b>：{excerpt_rows}</div>'
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


# ── M5/M6：多区域能力 ────────────────────────────────────────
def _region_record_card(row, index):
    title = _e(row.get("法规中文名") or row.get("官方标题（英文）") or "官方未标注")
    key = _e(row.get("官方编号") or row.get("CELEX号") or "-")
    validity = _e(row.get("现行效力") or "官方未标注")
    url = row.get("官方链接") or ""
    link = (f'<a class="cr-a" href="{_attr(url)}" target="_blank" rel="noopener">官方原文 →</a>'
            if verify.is_official_url(url) else "")
    note = _e((row.get("备注／问题") or "").split("｜")[0])
    return (f'<div class="cr-card"><div class="cr-title">{index}. {title}'
            f'{_badge(validity, "b-ok" if validity.startswith("现行") else "b-q")}</div>'
            f'<div class="cr-row"><span class="cr-k">官方编号</span><code>{key}</code></div>'
            f'<div class="cr-row"><span class="cr-k">业务提示</span>{note or "官方未标注"}</div>'
            f'<div class="cr-row"><span class="cr-k">官方链接</span>{link}</div></div>')


def render_m6(result):
    """M6 多区域汇总。

    与 M1–M4 保持同一套外壳：顶部元数据条（PRD D3）+ 页脚免责声明（红线）。
    早期版本这三个新页签只渲染内容，既不声明快照/截止时间、也不输出免责声明 ——
    等于把「每条结论附官方链接 + 固定免责」的承诺只做在了老页签上。
    """
    if not result.get("ok"):
        return _reject_html(result.get("reason", "无法汇总"), result.get("header"))
    parts = [f'<div class="cr-wrap">{_header_block(result.get("header"))}'
             f'<div class="cr-head"><b>多区域法规汇总</b>　'
             f'<span style="color:#8b7d68;font-size:13px">{_e(result["品类"])} · '
             f'{result["总条数"]} 条区域法规</span></div>']
    for region in result["区域"]:
        body = "".join(_region_record_card(r, i + 1) for i, r in enumerate(region["法规"]))
        parts.append(_group(
            f'{region["市场"]}法规清单', region["条数"], body, open_=True,
            hint=(f'官方链接通过 {region["条数"]} 条；'
                  f'待核对 {region.get("待核对", 0)} 条；'
                  f'被拦截 {region["被拦截"]} 条')))
    parts.append('<div class="cr-note">区域分别计数；同一横切法规在不同区域会分别展示。'
                 '“待核对”表示尚未完成人工核验，不等同于已发布依据。</div>')
    parts.append(_footer_block())
    parts.append('</div>')
    return "".join(parts)


def render_m5(result):
    if not result.get("ok"):
        return _reject_html(result.get("reason", "无法完成对比"), result.get("header"))
    parts = [f'<div class="cr-wrap">{_header_block(result.get("header"))}'
             f'<div class="cr-head"><b>区域差异对比</b>　'
             f'<span style="color:#8b7d68;font-size:13px">{_e(result["品类"])} · '
             f'共同编号 {result["共同数量"]} 条</span></div>',
             f'<div class="cr-note">{_e(result["说明"])} 快照 {_e(result["快照版本"])}，数据截止 {_e(result["数据截止时间"])}。</div>']
    summary = "".join(f'<div class="cr-stat"><div class="cr-stat-k">{_e(x["市场"])}法规</div>'
                       f'<div class="cr-stat-v">{x["数量"]}</div><div class="cr-stat-s">已通过链接校验</div></div>'
                       for x in result["区域"])
    parts.append(f'<div class="cr-overview">{summary}</div>')
    shared_body = "".join(f'<div class="cr-row"><span class="cr-k">共同编号</span>'
                           f'<code>{_e(x["key"])}</code> {_e(x["名称"])}</div>'
                           for x in result["共同"])
    parts.append(_group("两地共同出现的官方编号", len(result["共同"]),
                        shared_body or '<div class="cr-empty">没有按官方编号精确匹配的共同条目。</div>', open_=True))
    for market, rows in result["独有"].items():
        body = "".join(_region_record_card(r, i + 1) for i, r in enumerate(rows))
        parts.append(_group(f'{market}独有法规', len(rows), body, open_=False,
                            hint='官方编号未在其他所选区域出现'))
    parts.append(_footer_block())
    parts.append('</div>')
    return "".join(parts)


# ── M7：OPC 上线准备度 ────────────────────────────────────────
def render_m7(result):
    if not result.get("ok"):
        return _reject_html(result.get("reason", "无法生成上线准备度"),
                            result.get("header"))
    parts = [f'<div class="cr-wrap">{_header_block(result.get("header"))}'
             f'<div class="cr-head"><b>OPC 上线准备度</b>　'
             f'<span style="color:#8b7d68;font-size:13px">{_e(result["品类"])} · '
             f'{result["总动作数"]} 项准备动作</span></div>',
             f'<div class="cr-note">{_e(result["说明"])} 查询日期 {_e(result["查询日期"])}，'
             f'快照 {_e(result["快照版本"])}。</div>']
    for region in result["区域"]:
        summary = (f'<div class="cr-overview"><div class="cr-stat"><div class="cr-stat-k">目标区域</div>'
                   f'<div class="cr-stat-v">{_e(region["市场"])}</div><div class="cr-stat-s">{region["动作条数"]} 项动作</div></div>'
                   f'<div class="cr-stat"><div class="cr-stat-k">优先处理</div><div class="cr-stat-v">{region.get("高优先级", 0)}</div><div class="cr-stat-s">按规则计算</div></div>'
                   f'<div class="cr-stat"><div class="cr-stat-k">需确认</div><div class="cr-stat-v">{region.get("需确认条数", 0)}</div><div class="cr-stat-s">身份或条件待核</div></div>'
                   f'<div class="cr-stat"><div class="cr-stat-k">未产出</div><div class="cr-stat-v">{region.get("未产出条数", 0)}</div><div class="cr-stat-s">证据不足不硬编</div></div></div>')
        parts.append(f'<div class="cr-sec">{_e(region["市场"])}上线准备</div>' + summary)
        for phase in region.get("阶段", []):
            cards = []
            for item in phase["动作"]:
                cards.append(
                    f'<div class="cr-card"><div class="cr-title">{_e(item["动作"])}'
                    f'{_badge(item["状态"], "b-warn" if item["状态"] == "需确认" else "b-info")}</div>'
                    f'<div class="cr-row"><span class="cr-k">责任角色</span>{_e(item["责任角色"])}</div>'
                    f'<div class="cr-row"><span class="cr-k">适用条件</span>{_e(item["适用条件"] or "请结合商品属性核对")}</div>'
                    f'<div class="cr-row"><span class="cr-k">依据法规</span>{_e(item["依据法规"])} · <code>{_e(item["官方编号"])}</code></div>'
                    f'<div class="cr-row"><span class="cr-k">官方链接</span><a class="cr-a" href="{_attr(item["官方链接"])}" target="_blank" rel="noopener">打开原文 →</a></div></div>')
            parts.append(_group(f'{_e(phase["名称"])} · {region["市场"]}', phase["条数"], "".join(cards), open_=phase["名称"] in ("选品与范围", "打样与测试"), hint="按责任角色推进并留存证据"))
        if region.get("待确认"):
            pending = "".join(f'<div class="cr-note"><b>需确认：</b>{_e(x.get("需确认", ""))}<br>{_e(x.get("影响", ""))}<br><span class="cr-k">核对方向</span>{_e(x.get("如何核对", ""))}</div>' for x in region["待确认"])
            parts.append(_group(f'{region["市场"]}待确认事项', len(region["待确认"]), pending, open_=True))
    parts.append(_footer_block())
    parts.append('</div>')
    return "".join(parts)


def run_readiness(category, markets):
    try:
        return render_m7(m7_opc_readiness.query(category, markets))
    except Exception as e:  # noqa: BLE001
        return _err_html(e)


def export_readiness_csv(category, markets):
    """导出 OPC 执行清单。失败返回 None（与 export_m3_csv 口径一致）。

    DownloadButton 的回调里抛异常会在页面上变成红色报错堆栈；
    M3 那边早就是「失败返回 None」，这里对齐，避免同一个 UI 里两种失败行为。
    """
    try:
        result = m7_opc_readiness.query(category, markets)
        name, data = m7_opc_readiness.export_csv(result)
    except RuntimeError:
        return None
    os.makedirs(EXPORT_DIR, exist_ok=True)
    path = os.path.join(EXPORT_DIR, name)
    with open(path, "wb") as handle:
        handle.write(data)
    return path


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


def run_multi_region(category, markets):
    try:
        return render_m6(m6_multi_region.query(category, markets))
    except Exception as e:  # noqa: BLE001
        return _err_html(e)


def run_compare(category):
    try:
        return render_m5(m5_compare.query(category, ["欧盟", "美国"]))
    except Exception as e:  # noqa: BLE001
        return _err_html(e)


def run_route(text, context):
    """M1.5 智能路由回调（输入驱动）。任何异常都不白屏。

    判定按钮只读取当前文本框。录音结束或手动上传转写后，用户核对才调用本函数，
    不会重新转写旧录音或覆盖用户修改。
    """
    try:
        res = m15_router.route(text, context)
        if res.get("ok"):
            # 判定卡头部（识别结果 + 缺失资料）+ 复用 M1 渲染（含免责声明）
            return m15_router.render_parse(res) + render_m1(res["m1"])
        return m15_router.render_parse(res)
    except Exception as e:  # noqa: BLE001
        return _err_html(e)


# ── 语音输入：只做「声音 → 文字」，判定仍走 M1.5 原链路 ─────────────
_ASR_BACKEND_ZH = {"local": "本地 Whisper", "cloud": "云端转写"}


def _asr_status_line():
    """语音入口可用性（不加载模型，只报配置）。"""
    try:
        cfg = asr.config_summary()
    except Exception:  # noqa: BLE001
        return "录音/上传转写暂不可用：语音服务状态检查失败，请联系管理员；可继续打字。"
    if cfg.get("enabled"):
        return (f"语音入口：{_e(cfg.get('detail'))}　语言 {_e(cfg.get('lang'))}。"
                "配置已识别，实际可用性以转写结果为准；请核对文字后再开始判定。")
    return (f"录音/上传转写暂不可用：{_e(cfg.get('detail'))}。"
            "本地引擎运行 scripts/prepare_asr_engine.py 准备（sherpa-onnx + SenseVoice，"
            "无需安装 Python 库）；或配置 ASR_API_BASE、ASR_API_KEY、ASR_MODEL 走云端。"
            "录音和上传共用语音服务，可继续打字。")


def _voice_hint(msg="", kind="error"):
    """语音区提示。这里只解释「发生了什么」，不给任何合规结论。"""
    if not msg:
        return (
            '<div class="cr-wrap"><div class="cr-empty">'
            '🎤 可以直接说一句（例：「我要把毛绒玩具卖到德国」），'
            '也可以在输入框里打字或粘贴整份资料。'
            '转写结果会<b>回填到输入框</b>，确认或改错后再点「开始判定」。<br>'
            '<span style="font-size:12px;color:var(--cr-ink2)">'
            '语音与打字走同一条链路：识别「品类 × 市场」→ 本地核对语料查表 → '
            '每条结论回挂官方链接。语音不参与任何合规判断。</span>'
            '</div></div>'
        )
    cls = "cr-err" if kind == "error" else "cr-empty"
    return f'<div class="cr-wrap"><div class="{cls}">{msg}</div></div>'


def _voice_echo_html(text, meta):
    """把「听到了什么」摆在结论之前 —— 用户必须先看见转写原文。"""
    if not meta:
        badge = '<span class="cr-badge b-info">文字输入</span>'
        detail = ""
    else:
        ok = meta.get("ok")
        badge = ('<span class="cr-badge b-ok">语音转写</span>' if ok
                 else '<span class="cr-badge b-warn">转写失败</span>')
        backend_name = _ASR_BACKEND_ZH.get(meta.get("backend"), meta.get("backend") or "—")
        detail = (f'后端 {_e(backend_name)}'
                  f' · 耗时 {_e(meta.get("seconds"))}s'
                  f'{" · 缓存命中" if meta.get("cached") else ""}')
    return (
        '<div class="cr-echo">'
        f'🎤 <b>听到</b>：{_e(text)}　{badge}'
        f'<div class="cr-echo-meta">已回填到输入框，可改错后重新判定。'
        f'{("　" + detail) if detail else ""}'
        f'<br>语音只做「声音 → 文字」，转写错误可能改变品类或市场，'
        f'请先核对文字。法规结果仍受原有人工核对门禁约束。</div>'
        '</div>'
    )


def run_route_with_voice(audio_path, text, context):
    """① 标签页统一入口：有录音先转写，否则直接用文本框内容。

    返回 (判定 HTML, 回填文本)。转写失败只解释原因，不产出任何合规结论。
    """
    original_text = text or ""
    said = original_text.strip()
    meta = None
    if audio_path:
        try:
            heard, meta = asr.transcribe(audio_path)
        except Exception as e:  # noqa: BLE001 —— 语音永不打断主链路
            heard, meta = "", {"ok": False, "reason": "语音服务暂不可用，请重试或直接输入文字", "backend": None}
        if not heard:
            reason = (meta or {}).get("reason") or "未知原因"
            return (_voice_hint(
                f"<b>这句话没听清</b><br>{_e(reason)}<br><br>"
                '<span style="color:var(--cr-ink2)">'
                '可以直接在输入框打字，或重新录音、上传音频。</span>'), original_text)
        said = heard
        return (_voice_echo_html(said, meta) + _voice_hint(
            "转写完成，请核对输入框中的文字，确认后点击「开始判定」。", kind="info"), said)

    if not said:
        return _voice_hint("请先说一句话，或在输入框里描述你的商品与目标市场。"), said

    # 复用纯文字链路 —— 语音与打字必须出同一份结论，不能有第二套渲染
    return _voice_echo_html(said, meta) + run_route(said, context), said


def run_voice_transcription(audio_path, text, context):
    """转写按钮只填文字，永不自动查询法规。"""
    if not audio_path:
        return _voice_hint("请先录音或上传音频，再点击「转写到输入框」。"), text or ""
    return run_route_with_voice(audio_path, text, context)


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


def _sidebar_html():
    """参考工作台的左侧导航；实际功能仍由下方标签页承载。

    语料条数取快照自报的 CORPUS_ROWS_TOTAL —— 原先写死「86 条已核对语料」，
    一旦补录语料就变成假数字，而这类「看起来精确的静态数字」最难被发现。
    """
    return (
        '<div class="cr-side-brand"><span class="cr-side-logo">⌁</span>'
        '<span>合规雷达</span></div>'
        '<div class="cr-side-label">工作台</div>'
        '<div class="cr-side-item active"><span>⌂</span><span>智能判定</span></div>'
        '<div class="cr-side-item"><span>▦</span><span>法规地图</span></div>'
        '<div class="cr-side-item"><span>✓</span><span>合规待办</span></div>'
        '<div class="cr-side-item"><span>◷</span><span>变化时间线</span></div>'
        '<div class="cr-side-item"><span>⇄</span><span>模型对照</span></div>'
        '<div class="cr-side-item"><span>🚀</span><span>OPC 上线准备</span></div>'
        '<div class="cr-side-label">当前数据</div>'
        f'<div class="cr-side-foot">覆盖 {"、".join(corpus.SUPPORTED_MARKETS.keys())}'
        f'<br>{snapshot.CORPUS_ROWS_TOTAL} 条候选语料（按核对状态分层）<br>每条结论附官方链接</div>'
    )


def _overview_html(model_status):
    """参考图的数据概览卡片，数据只来自当前发布快照。"""
    audit = snapshot.CORPUS_ROWS_BY_AUDIT_STATUS or {}
    audited = audit.get("已核对")
    pending = audit.get("待核对")
    audited = "未提供" if audited is None else audited
    pending = "未提供" if pending is None else pending
    eu = snapshot.CORPUS_ROWS_BY_MARKET.get("欧盟", 0)
    us = snapshot.CORPUS_ROWS_BY_MARKET.get("美国", 0)
    model = "已接入" if llm.is_ready() else "规则降级"
    return (
        '<div class="cr-overview">'
        f'<div class="cr-stat"><div class="cr-stat-k">候选总数</div>'
        f'<div class="cr-stat-v">{_e(snapshot.CORPUS_ROWS_TOTAL)}</div>'
        f'<div class="cr-stat-s">快照 { _e(snapshot.SNAPSHOT_VERSION) }</div></div>'
        f'<div class="cr-stat"><div class="cr-stat-k">已核对</div>'
        f'<div class="cr-stat-v">{_e(audited)}</div>'
        '<div class="cr-stat-s">按当前快照审核分布</div></div>'
        f'<div class="cr-stat"><div class="cr-stat-k">待核对</div>'
        f'<div class="cr-stat-v">{_e(pending)}</div>'
        '<div class="cr-stat-s">按当前快照审核分布</div></div>'
        f'<div class="cr-stat"><div class="cr-stat-k">覆盖区域</div>'
        f'<div class="cr-stat-v">2</div><div class="cr-stat-s">欧盟 {eu} · 美国 {us}</div></div>'
        f'<div class="cr-stat"><div class="cr-stat-k">入口品类</div>'
        f'<div class="cr-stat-v">{len(corpus.SUPPORTED_CATEGORIES)}</div>'
        '<div class="cr-stat-s">玩具 · 电器 · 服装等</div></div>'
        f'<div class="cr-stat"><div class="cr-stat-k">智能解析</div>'
        f'<div class="cr-stat-v">{_e(model)}</div>'
        f'<div class="cr-stat-s">{_e(model_status.split("（")[0])}</div></div>'
        '</div>'
    )


BUILD_VERSION = "2026.10.18-db1"


def run_clause_search(identifier, heading):
    result = law_store.retrieve(identifier, heading)
    blocks = [f'<div class="cr-note">{_e(result.get("reason", ""))}</div>']
    for unit in result.get('units', []):
        blocks.append('<details class="cr-card"><summary>' + _e(unit['heading'] or unit['locator']) + '</summary>'
                      + '<p>' + _e(unit['document_id']) + ' · ' + _e(unit.get('parse_status', '')) + '</p>'
                      + '<pre style="white-space:pre-wrap;overflow-wrap:anywhere">' + _e(unit['body']) + '</pre>'
                      + ('<p>显示预算已截断，请回看官方原文。</p>' if unit['truncated'] else '')
                      + '<p>' + _e(unit['locator']) + '</p></details>')
    return ''.join(blocks)


def build_ui():
    cfg = llm.config_summary()
    model_status = ("模型：已接入（理解输入用，结论仍 100% 来自核对语料）"
                    if cfg["ready"] else
                    "模型：未配置 —— 输出原始清单（数据完整，链接可核验）")
    # 语音入口可用性（缺依赖/缺配置时自动关闭，打字链路不受影响）
    try:
        _asr_on = bool(asr.config_summary().get("enabled"))
    except Exception:  # noqa: BLE001
        _asr_on = False

    # 类目下拉 —— 仅 5 个业务类目入口；横切维度随品类附带，不单独查
    cat_choices = list(corpus.SUPPORTED_CATEGORIES)
    mkt_choices = list(corpus.SUPPORTED_MARKETS.keys())

    _major = int(gr.__version__.split(".")[0])
    _blocks_kwargs = {"title": "出海合规雷达 ComplianceRadar"}
    if _major < 6:
        _blocks_kwargs.update(css=_CSS, theme=gr.themes.Soft())

    with gr.Blocks(**_blocks_kwargs) as demo:
        # 开场雷达 CG（~2s 自动淡出，纯 CSS，不阻塞交互）
        gr.HTML(_INTRO_HTML)
        gr.HTML('<aside class="cr-sidebar" aria-label="功能导航">' + _sidebar_html() + '</aside>')
        gr.HTML(_hero_html(model_status))
        gr.HTML(_overview_html(model_status))
        gr.Markdown(f"<small>构建版本 {BUILD_VERSION} · {_e(law_store.status()['reason'])}</small>")

        with gr.Tabs():
            # ── ① 智能判定 ────────────────────────────────────
            with gr.Tab("🔎 智能判定"):
                gr.HTML(
                    '<div class="cr-section-intro"><b>先说清楚你要卖什么、卖到哪里。</b> '
                    '系统会自动识别品类和市场，再从已核对语料中生成法规与待办。模型只理解输入，结论仍来自确定性规则和官方链接。</div>'
                    '<div class="cr-quick"><span>适合：产品描述</span><span>适合：BOM / 合同要点</span><span>结果：法规 + 待办 + 证据</span></div>'
                )
                gr.Markdown("**点击开始录音即可说话，再点击结束录音，自动转写到输入框。** 最长60秒；首次使用请允许浏览器访问麦克风，未开始录音请检查地址栏权限。核对文字后再点「开始判定」。")
                with gr.Row():
                    q_record_start = gr.Button("点击开始录音", variant="primary", interactive=_asr_on)
                    q_record_stop = gr.Button("结束录音并转写", interactive=_asr_on)
                with gr.Row(elem_classes=["cr-voice-row"]):
                    audio_in = gr.Audio(
                        sources=["microphone", "upload"], type="filepath", format="wav",
                        label="录音或上传音频（可选，最长60秒）", scale=1,
                        interactive=_asr_on,
                    )
                    q_text = gr.Textbox(
                        lines=4, scale=3,
                        value="我要把洋娃娃卖到美国去，要做哪些合规工作？",
                        label="① 你的生意（一句话，或整份产品/合同文件）",
                    )
                q_ctx = gr.Textbox(
                    lines=2, value="",
                    placeholder=("选填：产品材质 / 结构、客户要求、合同关键信息…"
                                 "（仅辅助识别，不存储）"),
                    label="② 补充上下文（选填）",
                )
                with gr.Row():
                    q_transcribe = gr.Button("转写到输入框", interactive=_asr_on, scale=2)
                    q_btn = gr.Button("开始判定", variant="primary", scale=3)
                    q_clear = gr.ClearButton([audio_in, q_text], value="清空录音/文字",
                                             scale=1)
                gr.HTML('<div class="cr-note" role="status">' + _asr_status_line() + '</div>')
                q_out = gr.HTML(_route_initial())
                gr.Markdown(
                    "<small style='color:#a4493f'>"
                    "隐私边界：文字输入不由本应用持久保存；录音由界面临时存储，"
                    "本应用不另存音频。转写文本默认不缓存，管理员可显式开启。"
                    "云端转写会发送录音，模型理解可能发送文字，请勿输入客户敏感信息。</small>"
                )

            # ── ② 法规地图 ────────────────────────────────────
            with gr.Tab("🗺 法规地图"):
                gr.HTML('<div class="cr-section-intro"><b>已知品类和市场？</b> 选择两个条件，快速查看适用法规、状态和官方来源。</div>')
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
                gr.HTML('<div class="cr-section-intro"><b>把法规变成今天能执行的动作。</b> 按紧迫度查看待办，点开每条卡片核对适用条件、原文摘录和官方链接。</div>')
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
                gr.HTML('<div class="cr-section-intro"><b>先看时间，再安排动作。</b> 关注法规发布日期、生效日期和过渡期节点，避免按旧规则准备。</div>')
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

            # ── ⑤ 区域差异对比 ─────────────────────────────────
            with gr.Tab("🧭 M5 区域对比"):
                gr.HTML('<div class="cr-section-intro"><b>同一品类，欧盟和美国要求有什么不同？</b> 按官方编号精确匹配共同条目，区域独有条目单独列出，不把名称相似误判为同一法规。</div>')
                with gr.Row():
                    cat5 = gr.Dropdown(choices=cat_choices, value="儿童玩具", label="商品类目")
                    btn5 = gr.Button("开始对比", variant="primary")
                m5_out = gr.HTML(render_m5(m5_compare.query("儿童玩具", mkt_choices)))

            # ── ⑥ 多区域汇总 ──────────────────────────────────
            with gr.Tab("🌍 M6 多区域汇总"):
                gr.HTML('<div class="cr-section-intro"><b>一次查看同一品类在多个区域的法规。</b> 当前先支持欧盟与美国，结果按区域分组，所有条目附官方来源。</div>')
                with gr.Row():
                    cat6 = gr.Dropdown(choices=cat_choices, value="儿童玩具", label="商品类目")
                    markets6 = gr.CheckboxGroup(choices=mkt_choices, value=mkt_choices, label="目标区域（可多选）")
                    btn6 = gr.Button("汇总法规", variant="primary")
                m6_out = gr.HTML(render_m6(m6_multi_region.query("儿童玩具", mkt_choices)))

            # ── ⑦ OPC 上线准备 ────────────────────────────────
            with gr.Tab("🚀 OPC 上线准备"):
                gr.HTML('<div class="cr-section-intro"><b>把合规待办排成小团队能执行的上线计划。</b> 按选品、测试、标签、文件、供应链和切换复核分阶段展示，并给出责任角色与官方依据。</div>')
                with gr.Row():
                    cat7 = gr.Dropdown(choices=cat_choices, value="儿童玩具", label="商品类目")
                    markets7 = gr.CheckboxGroup(choices=mkt_choices, value=mkt_choices, label="目标区域（可多选）")
                    btn7 = gr.Button("生成上线准备", variant="primary")
                m7_out = gr.HTML(render_m7(m7_opc_readiness.query("儿童玩具", mkt_choices)))
                with gr.Row():
                    readiness_csv = gr.DownloadButton("⬇ 导出 OPC 执行清单（CSV）", variant="secondary",
                                                      value=lambda c, ms: export_readiness_csv(c, ms),
                                                      inputs=[cat7, markets7])

            # ── ⑧ 模型对照 ────────────────────────────────────
            with gr.Tab("⚖️ 模型对照"):
                gr.HTML('<div class="cr-section-intro"><b>同一道题，两套方法放在一起看。</b> 重点观察来源、编号和证据是否能被复核；当前页面只展示已录制的真实回放。</div>')
                m4_out = gr.HTML(render_m4(m4_compare.query()))

            with gr.Tab("条款检索"):
                gr.Markdown("按法规编号精确定位，再按条款标题筛选。抽取文本保留来源、版本及解析状态，不会自动提升审核状态或生成执行动作。")
                clause_id = gr.Textbox(label="法规编号", value="16 CFR Part 1250")
                clause_heading = gr.Textbox(label="条款标题关键词（可选，多个词需同时匹配）")
                clause_button = gr.Button("检索条款")
                clause_out = gr.HTML()
                clause_button.click(run_clause_search, inputs=[clause_id, clause_heading], outputs=clause_out)

        # 事件绑定（每页签自足，互不干扰）
        q_record_start.click(lambda: gr.Audio(value=None, recording=True),
                             outputs=audio_in, queue=False, api_visibility="private")
        q_record_stop.click(lambda: gr.Audio(recording=False),
                            outputs=audio_in, queue=False, api_visibility="private")
        audio_in.stop_recording(run_voice_transcription, inputs=[audio_in, q_text, q_ctx],
                                outputs=[q_out, q_text], concurrency_limit=2,
                                concurrency_id="asr", api_name="transcribe_recording")
        q_transcribe.click(run_voice_transcription, inputs=[audio_in, q_text, q_ctx],
                           outputs=[q_out, q_text], concurrency_limit=2,
                           concurrency_id="asr")
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
        for w in (cat6, markets6):
            w.change(run_multi_region, inputs=[cat6, markets6], outputs=m6_out)
        btn6.click(run_multi_region, inputs=[cat6, markets6], outputs=m6_out)
        cat5.change(run_compare, inputs=[cat5], outputs=m5_out)
        btn5.click(run_compare, inputs=[cat5], outputs=m5_out)
        for w in (cat7, markets7):
            w.change(run_readiness, inputs=[cat7, markets7], outputs=m7_out)
        btn7.click(run_readiness, inputs=[cat7, markets7], outputs=m7_out)

    return demo


# Preserve old render helpers and callbacks for CLI integrations and regression
# tests. The default web entry now builds only the conversation shell; there are
# no startup queries, preset legal conclusions or automatic model calls.
build_legacy_ui = build_ui


def build_ui():
    from ui_chat import build_ui as build_chat_ui
    return build_chat_ui()


if __name__ == "__main__":
    port = int(os.getenv("PORT", os.getenv("SERVER_PORT", "7860")))
    # 魔搭创空间通过 PORT 注入服务端口；本地运行也绑定全网卡，便于容器探活。
    host = "0.0.0.0"
    from ui_chat import CSS
    # 语音引擎预热：只在会用本地引擎时后台准备（不阻塞启动、不抛异常）。
    # 界面在 build_ui() 时读一次可用性，所以先起线程，让下载与建界面并行。
    asr.prewarm()
    launch_kwargs = {"server_name": host, "server_port": port, "css": CSS,
                     "theme": gr.themes.Soft(), "footer_links": [],
                     "show_error": False, "max_file_size": "20mb"}
    build_ui().launch(**launch_kwargs)
