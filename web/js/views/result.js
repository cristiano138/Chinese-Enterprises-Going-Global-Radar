// 结果页：把 /api/tool/todo 的动作渲染成「现在先做」+ 全量条目。
import { esc } from "../dom.js";
import { ic } from "../icons.js";
import { PRIORITIES } from "../sample.js";
import { actionRow, rowHtml } from "../render.js";
import { cache, conditions, toolData, toolError } from "../data.js";
import { timeLabel as historyTime } from "../history.js";

const URGENCY_RANK = { 高: 0, 中: 1, 低: 2 };

function filteredActions(actions, filter) {
  if (filter === "全部") return actions;
  if (filter === "待确认") return actions.filter((a) => (a.status || "").includes("待确认")
    || (a.type || "").includes("确认"));
  return actions.filter((a) => a.type === filter);
}

export function resultView(state) {
  const data = toolData("todo");
  const error = toolError("todo");
  const boot = cache.boot || {};
  const historical = cache.historical;
  const actions = data ? [...(data.actions || [])] : [];
  actions.sort((a, b) => (URGENCY_RANK[a.urgency] ?? 9) - (URGENCY_RANK[b.urgency] ?? 9));
  const priorities = actions.slice(0, 3).map((a) => [a.title, a.condition || a.law || ""]);
  // 结果页的条目来自 M3 动作类型（标签标识 / 注册备案 …），筛选项随数据生成。
  const filterOptions = ["全部", "待确认",
    ...Array.from(new Set(actions.map((a) => a.type).filter(Boolean))).slice(0, 4)];
  const activeFilter = filterOptions.includes(state.filter) ? state.filter : "全部";
  const shown = actions.length ? filteredActions(actions, activeFilter) : [];
  const cutoff = boot.data_cutoff || "—";
  const lawCount = boot.coverage ? boot.coverage.laws : "";
  const rows = shown.length
    ? shown.map((action) => actionRow(action)).join("")
    : data
      ? `<div class="row"><span class="row__rail"></span><span class="row__body"><span class="row__sub">当前筛选下没有条目。</span></span></div>`
      : ["doc", "label", "amazon", "en71", "lucid"].map(rowHtml).join("");
  const priorityItems = priorities.length ? priorities : PRIORITIES;

  return `
      <div class="page-head" style="padding-top:16px">
        <p>${esc(conditions.category)} · ${esc(conditions.market)} · ${esc(conditions.platform)}。先做优先级最高的几项，其余按证据状态逐条核对。</p>
        <div class="context">
          <span>${esc(conditions.category)}</span><span>${esc(conditions.market)}</span><span>${esc(conditions.platform)}</span><span>${esc(conditions.powered)}</span>
        </div>
        <div class="page-head__meta mono">${historical ? `历史结果 · ${esc(historyTime(historical.ts))} · ` : ""}数据截止 ${esc(cutoff)} · ${lawCount ? `${lawCount} 部法规 · ` : ""}${actions.length} 项待办</div>
      </div>

      <section class="priority" aria-labelledby="priority-title">
        <div class="priority__head">
          <b id="priority-title">现在先做</b><span>按前置依赖排序</span>
        </div>
        ${priorityItems.map((p, i) => `
          <div class="priority__item">
            <span class="priority__no">${i + 1}</span>
            <span class="priority__text">${esc(p[0])}<small>${esc(p[1])}</small></span>
          </div>`).join("")}
      </section>

      <div class="section-head"><b>全部条目</b><span>${shown.length} 条 · 点开看依据</span></div>
      <div class="filter-row" role="tablist" aria-label="筛选条目">
        ${filterOptions.map(f => `
          <button class="filter ${activeFilter === f ? "is-on" : ""}" data-action="filter" data-filter="${f}"
                  role="tab" aria-selected="${activeFilter === f}">${f}</button>`).join("")}
      </div>
      <div class="list">${rows}</div>

      <details class="boundary">
        <summary><span>资料边界与待确认事项</span>${ic("chevron")}</summary>
        <div class="boundary__body">
          <p>目录收录不等于要求等效。平台规则可能随时更新，请以卖家后台和官方原文为准。</p>
          <p>本页不构成法律意见；涉及产品责任或合同条款时，请让专业人员复核。</p>
          ${error ? `<p>后端数据读取失败：${esc(error)}</p>` : ""}
        </div>
      </details>

      <div class="foot-actions">
        <button class="btn btn--ghost" data-action="export">${ic("download")}导出清单</button>
        <button class="btn" data-action="nav" data-to="${esc(state.resultFrom || "assistant")}">返回</button>
      </div>`;
}
