# -*- coding: utf-8 -*-
"""
出海合规雷达 · Web 界面入口（app.py）

M1 合规地图：卖家选「品类 + 市场」→ 输出法规清单，每条带官方链接。

运行：
    python app.py
（本机默认 http://127.0.0.1:7860；部署到魔搭创空间时自动使用平台端口）

设计要点：
    · 输入区：类目下拉（与语料实际类目一致）+ 市场下拉
    · 结果区：逐条法规卡片，链接可点、可核验
    · 免责声明固定输出（不可关闭）
    · 范围外输入 → 明示拒绝，不硬编答案
    · 模型不可用 → 自动降级为原始清单，演示不中断
"""

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

from core import corpus, llm  # noqa: E402
from modules import m1_map  # noqa: E402

import gradio as gr  # noqa: E402


# ── 结果渲染成 HTML 卡片 ──────────────────────────────────────
_CSS = """
.cr-wrap { font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif; }
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
.cr-err { border:1px solid #f3c2bd; background:#fdecea; border-radius:8px;
          padding:14px; color:#8e2118; font-size:14px; line-height:1.7; }
"""


def _badge(validity):
    if validity.startswith("⚠️"):
        return f'<span class="cr-badge b-warn">{validity}</span>'
    if validity.startswith("❓"):
        return f'<span class="cr-badge b-q">{validity}</span>'
    return f'<span class="cr-badge b-ok">{validity}</span>'


def _card(r, idx):
    rows = []
    rows.append(
        f'<div class="cr-row"><span class="cr-k">官方编号</span>'
        f'<code>{r["官方编号"]}</code></div>')
    rows.append(
        f'<div class="cr-row"><span class="cr-k">CELEX 号</span>'
        f'<code>{r["CELEX号"]}</code></div>')
    rows.append(
        f'<div class="cr-row"><span class="cr-k">生效日期</span>{r["生效日期"]}</div>')
    rows.append(
        f'<div class="cr-row"><span class="cr-k">监管机构</span>{r["监管机构"]}</div>')
    rows.append(
        f'<div class="cr-row"><span class="cr-k">OJ 出处</span>{r["OJ出处"]}</div>')

    # 链接：ELI（欧盟）与官方原文，逐个可点
    links = []
    if r["官方原文链接"]:
        links.append(f'<a class="cr-a" href="{r["官方原文链接"]}" target="_blank" '
                     f'rel="noopener">官方原文 →</a>')
    if r["ELI链接"].startswith("http"):
        links.append(f'<a class="cr-a" href="{r["ELI链接"]}" target="_blank" '
                     f'rel="noopener">ELI 永久标识 →</a>')
    if links:
        rows.append('<div class="cr-row"><span class="cr-k">可核验链接</span>'
                    + '　'.join(links) + '</div>')

    rows.append(
        f'<div class="cr-row"><span class="cr-k">链接状态</span>{r["链接状态"]}</div>')
    rows.append(
        f'<div class="cr-row"><span class="cr-k">官方标题</span>'
        f'{r["官方英文标题"]}</div>')

    tip = (f'<div class="cr-tip">{r["卖家提示"]}</div>'
           if r.get("卖家提示") else "")

    return (
        f'<div class="cr-card">'
        f'<div class="cr-title">{idx}. {r["法规中文名"]}{_badge(r["是否仍有效"])}</div>'
        f'{tip}{"".join(rows)}'
        f'</div>'
    )


def render(result):
    """把 M1 结果渲染成 HTML。"""
    if not result["ok"]:
        return (
            f'<div class="cr-wrap"><div class="cr-err">'
            f'<b>此输入不在本工具的支持范围内</b><br>{result["reason"]}<br><br>'
            f'<b>支持的市场：</b>{"、".join(corpus.SUPPORTED_MARKETS.keys())}<br>'
            f'<b>支持的品类：</b>{"、".join(corpus.SUPPORTED_CATEGORIES)}<br>'
            f'<b>横切维度：</b>{"、".join(corpus.CROSS_CUTTING)}'
            f'（任何品类都适用，可单独查询）<br><br>'
            f'<span style="color:#6b7280">本工具按「查到的官方数据」回答，'
            f'范围外的问题不做硬编答案。</span>'
            f'</div></div>'
        )

    p, c = result["primary"], result["cross"]
    lm = result.get("llm") or {}

    head = (f'<div class="cr-head"><b>M1 合规地图</b>　'
            f'{result["品类"]} × {result["市场"]}　'
            f'<span style="color:#6b7280;font-size:13px">'
            f'主体 {len(p)} 条 · 横切 {len(c)} 条</span></div>')

    # 模型状态如实标注
    if lm.get("ok") and p and p[0].get("卖家提示"):
        tag = "（缓存命中）" if lm.get("cached") else ""
        note = (f'<div class="cr-note">「卖家提示」由大模型生成{tag}，'
                f'仅作语言润色。所有法规编号、日期、链接均来自官方数据，'
                f'未经模型改动。</div>')
    elif lm and not lm.get("ok") and lm.get("reason") != "未启用":
        note = (f'<div class="cr-note">⚠️ 模型链路不可用'
                f'（{lm.get("reason")}），已自动降级为原始清单 —— '
                f'法规数据完整、链接可核验，演示不中断。</div>')
    else:
        note = ""

    parts = [f'<div class="cr-wrap">{head}{note}']

    if p:
        parts.append(f'<div class="cr-sec">{result["品类"]} · 直接适用法规（{len(p)} 条）</div>')
        parts.extend(_card(r, i) for i, r in enumerate(p, 1))
    else:
        parts.append('<div class="cr-note">该品类在当前市场暂无语料条目。</div>')

    if c:
        parts.append('<div class="cr-sec">横切法规 · 标签标识 / 通用（任何品类都适用，'
                     f'{len(c)} 条）</div>')
        parts.extend(_card(r, i) for i, r in enumerate(c, 1))

    if result["dropped"]:
        items = "".join(f'<li>{k}：{why}</li>' for k, why in result["dropped"])
        parts.append('<div class="cr-note">⛔ 引用对齐拦下 '
                     f'{len(result["dropped"])} 条（无官方链接，按红线不输出）'
                     f'<br><ul style="margin:6px 0 0 18px">{items}</ul></div>')

    parts.append(f'<div class="cr-dis">⚖️ {m1_map.DISCLAIMER}'
                 f'<br>数据来源：欧盟 EUR-Lex / 美国 eCFR 官方接口；'
                 f'语料快照 {corpus.stats()["total"]} 条。</div>')
    parts.append('</div>')
    return "".join(parts)


def run_query(category, market, use_llm):
    """界面回调。任何异常都不白屏。"""
    try:
        result = m1_map.query(category, market, use_llm=bool(use_llm))
        return render(result)
    except Exception as e:
        return (f'<div class="cr-wrap"><div class="cr-err">'
                f'查询过程出现异常，已捕获（不会白屏）：<br>'
                f'<code>{type(e).__name__}: {str(e)[:300]}</code><br><br>'
                f'请尝试其它品类 / 市场组合。</div></div>')


def build_ui():
    cfg = llm.config_summary()
    status = ("模型链路：已配置（可选润色）" if cfg["ready"]
              else "模型链路：未配置 —— 将输出原始清单（数据完整，链接可核验）")

    # 样式与主题在 Gradio 6 移到了 launch()；这里用兼容写法，
    # 保证 Gradio 4.x / 5.x / 6.x 都能跑（部署平台的版本不可控）。
    _major = int(gr.__version__.split(".")[0])
    _blocks_kwargs = {"title": "出海合规雷达 · M1 合规地图"}
    if _major < 6:
        _blocks_kwargs.update(css=_CSS, theme=gr.themes.Soft())

    with gr.Blocks(**_blocks_kwargs) as demo:
        gr.Markdown(
            "# 出海合规雷达 ComplianceRadar\n"
            "### M1 · 合规地图\n"
            "**输入「我卖什么 + 我卖到哪」→ 输出适用法规清单，每条附官方原文链接，可点开核验。**"
        )

        with gr.Row():
            with gr.Column(scale=1):
                cat = gr.Dropdown(
                    choices=corpus.SUPPORTED_CATEGORIES + [
                        f"{c}（横切维度）" for c in corpus.CROSS_CUTTING],
                    value="儿童玩具",
                    label="① 商品类目",
                )
                mkt = gr.Dropdown(
                    choices=list(corpus.SUPPORTED_MARKETS.keys()),
                    value="欧盟",
                    label="② 目标市场",
                )
                use_llm = gr.Checkbox(
                    value=cfg["ready"],
                    label="启用中文卖家提示（可选；关闭则输出原始清单）",
                    interactive=cfg["ready"],
                )
                btn = gr.Button("生成合规清单", variant="primary")
                gr.Markdown(
                    f"<small style='color:#6b7280'>{status}<br>"
                    f"模型：{cfg['model']}</small>"
                )
                gr.Markdown(
                    "<small style='color:#6b7280'>"
                    "语料范围：欧盟 + 美国 × 5 个品类 + 2 个横切维度。"
                    "范围外输入会被明确拒绝。</small>"
                )
            with gr.Column(scale=3):
                out = gr.HTML(render(m1_map.query("儿童玩具", "欧盟",
                                                  use_llm=False)))

        def _on_click(c, m, u):
            # 下拉里「（横切维度）」是展示后缀，回退成真实值
            real = c.replace("（横切维度）", "").strip()
            return run_query(real, m, u)

        btn.click(_on_click, inputs=[cat, mkt, use_llm], outputs=out)
        cat.change(_on_click, inputs=[cat, mkt, use_llm], outputs=out)
        mkt.change(_on_click, inputs=[cat, mkt, use_llm], outputs=out)

    return demo


if __name__ == "__main__":
    # 魔搭创空间会注入 SERVER_PORT；本机默认 7860
    port = int(os.getenv("SERVER_PORT", os.getenv("PORT", "7860")))
    host = "0.0.0.0" if os.getenv("SERVER_PORT") else "127.0.0.1"
    _major = int(gr.__version__.split(".")[0])
    launch_kwargs = {"server_name": host, "server_port": port}
    if _major < 6:
        # Gradio 6 移除了 show_api，并改从 launch() 接收 css/theme
        launch_kwargs.update(show_api=False, css=_CSS, theme=gr.themes.Soft())
    else:
        launch_kwargs.update(css=_CSS, theme=gr.themes.Soft())
    build_ui().launch(**launch_kwargs)
