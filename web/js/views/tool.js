// 七个工具页：内容来自 /api/tool/*，类名沿用原型。
import { esc } from "../dom.js";
import { ic } from "../icons.js";
import { TOOL_PAGES } from "../sample.js";
import { actionRow, recordRow, rowHtml, filteredFresh } from "../render.js";
import { conditions, toolData, toolError } from "../data.js";
import { regulationsView } from "./regulations.js";
import { actionView } from "./action.js";

function errorNote(error) {
  return error
    ? `<p class="fine" style="margin-top:9px">后端数据读取失败：${esc(error)}</p>`
    : "";
}

function recordList(records) {
  return records.length
    ? records.map(recordRow).join("")
    : `<div class="row"><span class="row__rail"></span><span class="row__body"><span class="row__sub">当前条件下没有条目。</span></span></div>`;
}

function mapBody(data, error) {
  if (!data) return `<div class="list">${recordList([])}</div>${errorNote(error)}`;
  return `
    <div class="section-head"><b>${esc(data.category)} · ${esc(data.market)} 适用法规</b><span>${data.records.length} 条 · 点开看依据</span></div>
    <div class="list">${recordList(data.records)}</div>
    <p class="fine" style="margin-top:9px">主体法规 ${data.primary.length} 条，横切法规 ${data.cross.length} 条；目录收录不等于要求等效。</p>
    ${errorNote(error)}`;
}

function timelineBody(data, error) {
  if (!data) return `<div class="timeline">${recordList([])}</div>${errorNote(error)}`;
  const events = [...data.recent, ...data.upcoming];
  if (!events.length) {
    return `<div class="list"><div class="row"><span class="row__rail"></span><span class="row__body"><span class="row__sub">最近 ${data.window_months} 个月没有已确认的日期节点。</span></span></div></div>`;
  }
  return `
    <div class="section-head"><b>近窗内</b><span>${data.recent.length} 条</span></div>
    <div class="timeline">${data.recent.length ? data.recent.map((event) => eventBlock(event)).join("") : '<p class="fine">近窗内没有变化。</p>'}</div>
    <div class="section-head"><b>即将发生</b><span>${data.upcoming.length} 条</span></div>
    <div class="timeline">${data.upcoming.length ? data.upcoming.map((event) => eventBlock(event)).join("") : '<p class="fine">没有已确认的未来节点。</p>'}</div>
    ${errorNote(error)}`;
}

function eventBlock(event) {
  return `
    <div class="tl">
      <div class="tl__date">${esc(event.date)}</div>
      <h3>${esc(event.law || event.summary)}</h3>
      <p>${esc(event.summary)}${event.impact ? ` ${esc(event.impact)}` : ""}</p>
      <span class="tl__tag">${esc(event.type || "节点")}${event.official ? "" : " · 待官方确认"}</span>
      ${event.url ? `<p class="fine"><a href="${esc(event.url)}" target="_blank" rel="noreferrer">查看官方原文 ${ic("external")}</a></p>` : ""}
    </div>`;
}

function todoBody(data, error) {
  if (!data) return `<div class="list">${recordList([])}</div>${errorNote(error)}`;
  const actions = data.actions || [];
  const urgent = actions.filter((a) => a.urgency === "高").length;
  return `
    <div class="section-head"><b>可执行动作</b><span>${actions.length} 条 · 高优先级 ${urgent} 条</span></div>
    <div class="list">${actions.length ? actions.map((a) => actionRow(a)).join("") : recordList([])}</div>
    ${data.pending.length ? `
      <div class="section-head"><b>待确认事项</b><span>${data.pending.length} 条</span></div>
      <div class="list">${data.pending.map((item) => `
        <div class="row">
          <span class="row__rail row__rail--warn"></span>
          <span class="row__body">
            <span class="row__title">${esc(item["需确认"] || "")}</span>
            <span class="row__sub">${esc(item["影响"] || "")}</span>
          </span>
        </div>`).join("")}</div>` : ""}
    ${errorNote(error)}`;
}

function compareBody(data, error) {
  if (!data) return `<div class="compare">${recordList([])}</div>${errorNote(error)}`;
  const regions = data.regions || [];
  const head = `<div class="compare__head">${regions.map((r) => `<span>${esc(r.market)}</span>`).join("")}</div>`;
  const rows = [];
  const max = Math.max(0, ...regions.map((r) => r.records.length));
  for (let i = 0; i < Math.min(max, 8); i += 1) {
    rows.push(`<div class="compare__row">${regions.map((r) => {
      const record = r.records[i];
      return `<span><b>${record ? esc(record.title) : "—"}</b>${record && record.official_id ? `<br><small>${esc(record.official_id)}</small>` : ""}</span>`;
    }).join("")}</div>`);
  }
  return `
    <div class="compare">${head}${rows.join("")}</div>
    <p class="fine" style="margin-top:9px">按官方编号精确匹配：共同 ${data.shared_count} 条。${esc(data.note || "")}</p>
    ${errorNote(error)}`;
}

function multiBody(data, error) {
  if (!data) return `<div class="list">${recordList([])}</div>${errorNote(error)}`;
  return (data.regions || []).map((region) => `
    <div class="region">
      <div class="region__head"><b>${esc(region.market)}</b><span>${region.count} 条 · ${region.ok ? "已核对" : "待核对"}</span></div>
      <div class="list">${recordList(region.records.slice(0, 10))}</div>
    </div>`).join("") + errorNote(error);
}

function phasesBody(data, error) {
  if (!data) return `<div class="list">${recordList([])}</div>${errorNote(error)}`;
  const regions = data.regions || [];
  return regions.map((region) => `
    <div class="section-head"><b>${esc(region.market)}</b><span>${region.action_count} 项 · 待确认 ${region.pending_confirm || 0}</span></div>
    <div class="list">
      ${(region.phases || []).map((phase, phaseIndex) => `
        <div class="section-head"><b>${esc(phase.name)}</b><span>${phase.count} 项</span></div>
        ${phase.actions.length ? phase.actions.map((task) => `
          <button class="phase" data-action="detail" data-id="${esc(task.id)}">
            <span class="phase__no">${phaseIndex + 1}</span>
            <span class="phase__copy"><b>${esc(task.title)}</b><span>${esc(task.role || "")} · ${esc(task.urgency || "")}</span></span>
            <span class="menu-row__end">${ic("chevron")}</span>
          </button>`).join("") : `<p class="fine" style="margin:6px 0 10px">当前无适用任务。</p>`}
      `).join("") || `<div class="row"><span class="row__rail"></span><span class="row__body"><span class="row__sub">当前市场没有可执行的上线准备项。</span></span></div>`}
    </div>`).join("") + errorNote(error);
}

export function toolView(state) {
  const id = state.tool;
  const t = TOOL_PAGES[id];
  if (!Object.hasOwn(TOOL_PAGES, id)) return state.toolGroup === "regulations" ? regulationsView(state) : actionView(state);
  const filters = `<div class="filterbar">
      <label class="select"><span class="select__label">品类</span><select aria-label="品类"><option>${esc(conditions.category)}</option></select></label>
      <label class="select"><span class="select__label">市场</span><select aria-label="市场"><option>${esc(conditions.market)}</option></select></label>
      ${t.filters.slice(2).map((f) => `<label class="select"><select aria-label="${esc(f)}"><option>${esc(f)}</option></select></label>`).join("")}
      <button class="chip" data-action="rerun">${ic("search")}重新生成</button></div>`;

  const error = toolError(id === "journey" ? "readiness" : id);
  const data = toolData(id === "journey" ? "readiness" : id);
  let body = "";
  if (id === "map") body = mapBody(data, error);
  else if (id === "timeline") body = timelineBody(data, error);
  else if (id === "todo") body = todoBody(data, error);
  else if (id === "compare") body = compareBody(data, error);
  else if (id === "multi") body = multiBody(data, error);
  else if (id === "readiness" || id === "journey") body = phasesBody(data, error);
  else if (t.custom === "freshness") {
    const fresh = filteredFresh(state);
    body = `
      <div class="fresh-summary">
        <div class="fresh-summary__head"><b>检查 ${fresh.length} 条</b><span>检查于今天</span></div>
        <div class="fresh-summary__counts">
          <div><b>${fresh.length}</b><span>条目</span></div>
          <div><b>0</b><span>需处理</span></div>
          <div><b>0</b><span>有更新</span></div>
          <div><b>${fresh.length}</b><span>已最新</span></div>
        </div>
      </div>
      <div class="section-head"><b>核对结果</b><span>${fresh.length} 条 · 点开看依据</span></div>
      <div class="filter-row">
        ${["全部", "需处理", "已最新", "无法确认"].map(f => `
          <button class="filter ${state.freshFilter === f ? "is-on" : ""}"
                  data-action="fresh-filter" data-filter="${f}">${f}</button>`).join("")}
      </div>
      <div class="list">${fresh.map(recordRow).join("")}</div>
      <p class="fine" style="margin-top:9px">时效性检查只核对目录中的版本与日期；平台规则和成员国执行差异仍需人工确认。</p>
      <div style="margin-top:14px">
        <button class="btn btn--block" data-action="rerun">${ic("search")}重新检查</button>
      </div>`;
  } else {
    body = `<div class="section-head"><b>${t.head}</b><span>点开看依据</span></div>
            <div class="list">${t.rows.map(rowHtml).join("")}</div>`;
  }

  return `
      <div class="page-head" style="padding:14px 0 0">
        <p>${t.sub}</p>
      </div>
      ${filters}
      ${body}
      <div style="margin-top:18px">
        <button class="btn btn--block" data-action="nav" data-to="assistant">不确定？回助手直接问</button>
      </div>`;
}
