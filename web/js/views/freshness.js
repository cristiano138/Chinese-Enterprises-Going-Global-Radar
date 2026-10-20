// 搬运自 prototype.html:1494-1563。函数体逐字未动，仅补头部导入与 export。
import { esc } from "../dom.js";
import { ic } from "../icons.js";
import { ITEMS, TOOL_PAGES, FRESH_ITEMS, PRIORITIES, RESULT_ITEMS } from "../sample.js";
import { rowHtml, filteredFresh, filteredItems } from "../render.js";

  export function freshnessView(state) {
    return `
      <div class="page-head" style="padding-top:16px">
        <p>系统每天 09:00 / 21:00 自动核验 86 条官方链接。这里显示最近一次检查和最近两次记录，结果只读，不需要手动操作。</p>
        <div class="page-head__meta mono">最近检查 2026-10-19 09:00 · 数据截止 2026-10-19</div>
      </div>

      <section class="fresh-card">
        <div class="fresh-card__head">
          <div class="fresh-card__title">法规时效 <span class="monitor-pill"><i></i>监控中</span></div>
          <div class="fresh-card__time">今天 09:00</div>
        </div>
        <div class="fresh-card__sub">86 条官方链接 · 下一次 21:00</div>
        <div class="fresh-counts">
          <div class="fresh-count"><b>86</b><span>核验链接</span></div>
          <div class="fresh-count"><b>84</b><span>可访问</span></div>
          <div class="fresh-count fresh-count--warn"><b>2</b><span>待复核</span></div>
          <div class="fresh-count"><b>0</b><span>内容更新</span></div>
        </div>
      </section>

      <div class="section-head"><b>最近两次检查</b><span>自动核验</span></div>
      <div class="list">
        <div class="row">
          <span class="row__rail row__rail--warn"></span>
          <span class="row__body">
            <span class="row__top"><span class="type-chip type-chip--pol">今天 09:00</span></span>
            <span class="row__title">86 条 · 84 可访问 · 2 待复核</span>
            <span class="row__sub">0 条内容更新 · 数据截止 2026-10-19</span>
          </span>
        </div>
        <div class="row">
          <span class="row__rail row__rail--ok"></span>
          <span class="row__body">
            <span class="row__top"><span class="type-chip">昨天 21:00</span></span>
            <span class="row__title">86 条 · 86 可访问 · 0 待复核</span>
            <span class="row__sub">0 条内容更新 · 数据截止 2026-10-19</span>
          </span>
        </div>
      </div>

      <div class="section-head"><b>待复核链接</b><span>2 条 · 本次检查</span></div>
      <div class="list">
        <a class="row" href="https://www.ecfr.gov/current/title-16/part-1250" target="_blank" rel="noreferrer">
          <span class="row__rail row__rail--warn"></span>
          <span class="row__body">
            <span class="row__top"><span class="type-chip type-chip--pol">网络未连通</span></span>
            <span class="row__title">eCFR · 16 CFR Part 1250</span>
            <span class="row__sub">本机网络未连通，不判死链；下一次核验会重试</span>
          </span>
          <span class="row__end">${ic("external")}</span>
        </a>
        <a class="row" href="https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32023R0988" target="_blank" rel="noreferrer">
          <span class="row__rail row__rail--warn"></span>
          <span class="row__body">
            <span class="row__top"><span class="type-chip type-chip--pol">网络未连通</span></span>
            <span class="row__title">EUR-Lex · 32023R0988</span>
            <span class="row__sub">本机网络未连通，不判死链；下一次核验会重试</span>
          </span>
          <span class="row__end">${ic("external")}</span>
        </a>
      </div>

      <div class="section-head"><b>检查口径</b><span>只读</span></div>
      <p class="fresh-note" style="font-size:11px">
        检查项：HTTP 状态 / Last-Modified / 内容哈希。内容哈希变化只代表页面字节变了，不等于法规条文变更；
        条文级变化仍归时间线人工核对。本机网络未连通不判死链，下一次核验会重试。
        原始日志保留在 <span class="mono">data/freshness_log.jsonl</span>。
      </p>`;
  }
