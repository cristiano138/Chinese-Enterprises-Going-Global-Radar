// 搬运自 prototype.html:1449-1491。函数体逐字未动，仅补头部导入与 export；
// 唯一增量：filteredItems() -> filteredItems(state)（Task 3 起该函数吃 state 形参）。
import { esc } from "../dom.js";
import { ic } from "../icons.js";
import { ITEMS, TOOL_PAGES, FRESH_ITEMS, PRIORITIES, RESULT_ITEMS } from "../sample.js";
import { rowHtml, filteredFresh, filteredItems } from "../render.js";

  export function resultView(state) {
    const items = filteredItems(state);
    return `
      <div class="page-head" style="padding-top:16px">
        <p>毛绒玩具 · 德国站 · 亚马逊。先做三项，其余按证据状态逐条核对。</p>
        <div class="context">
          <span>儿童玩具</span><span>德国</span><span>亚马逊</span><span>FBA</span>
        </div>
        <div class="page-head__meta mono">CR-1019-03 · 数据截止 2026-10-19 · 86 部法规</div>
      </div>

      <section class="priority" aria-labelledby="priority-title">
        <div class="priority__head">
          <b id="priority-title">现在先做</b><span>按前置依赖排序</span>
        </div>
        ${PRIORITIES.map((p, i) => `
          <div class="priority__item">
            <span class="priority__no">${i + 1}</span>
            <span class="priority__text">${esc(p[0])}<small>${esc(p[1])}</small></span>
          </div>`).join("")}
      </section>

      <div class="section-head"><b>全部条目</b><span>${items.length} 条 · 点开看依据</span></div>
      <div class="filter-row" role="tablist" aria-label="筛选条目">
        ${["全部", "待确认", "法律法规", "平台规则", "操作建议"].map(f => `
          <button class="filter ${state.filter === f ? "is-on" : ""}" data-action="filter" data-filter="${f}"
                  role="tab" aria-selected="${state.filter === f}">${f}</button>`).join("")}
      </div>
      <div class="list">${items.map(rowHtml).join("") || '<div class="row"><span class="row__rail"></span><span class="row__body"><span class="row__sub">当前筛选下没有条目。</span></span></div>'}</div>

      <details class="boundary">
        <summary><span>资料边界与待确认事项</span>${ic("chevron")}</summary>
        <div class="boundary__body">
          <p>目录收录不等于要求等效。平台规则可能随时更新，请以卖家后台和官方原文为准。</p>
          <p>本页不构成法律意见；涉及产品责任或合同条款时，请让专业人员复核。</p>
        </div>
      </details>

      <div class="foot-actions">
        <button class="btn btn--ghost" data-action="export">${ic("download")}导出清单</button>
        <button class="btn" data-action="nav" data-to="${esc(state.resultFrom || "assistant")}">返回</button>
      </div>`;
  }
