// 七个工具页：内容来自 /api/tool/*，类名沿用原型。
import { esc } from "../dom.js";
import { ic } from "../icons.js";
import { TOOL_PAGES } from "../sample.js";
import { actionRow, recordRow } from "../render.js";
import { cache, conditions, toolData, toolError } from "../data.js";
import { regulationsView } from "./regulations.js";
import { actionView } from "./action.js";

const CATEGORY_FALLBACK = ["儿童玩具", "电子电器", "纺织服装", "美妆个护", "食品接触材料"];
const MARKET_FALLBACK = ["欧盟", "美国"];

function options(list, selected) {
  return list.map((value) => `<option ${value === selected ? "selected" : ""}>${esc(value)}</option>`).join("");
}

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
  const status = conditions.recordStatus;
  const records = data.records.filter((record) => {
    if (status === "现行有效") return (record.status || "").includes("现行有效");
    if (status === "已废止或待确认") return /已废止|待确认/.test(record.status || "");
    return true;
  });
  return `
    <div class="section-head"><b>${esc(data.category)} · ${esc(data.market)} 适用法规</b><span>${records.length} 条 · 点开看依据</span></div>
    <div class="list">${recordList(records)}</div>
    <p class="fine" style="margin-top:9px">主体法规 ${data.primary.length} 条，横切法规 ${data.cross.length} 条；当前筛选 ${esc(status)}。目录收录不等于要求等效。</p>
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
  const all = data.actions || [];
  const actions = conditions.urgency === "按紧迫度"
    ? all : all.filter((action) => action.urgency === conditions.urgency);
  const urgent = all.filter((a) => a.urgency === "高").length;
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
  const boot = cache.boot || {};
  const categories = boot.categories || CATEGORY_FALLBACK;
  const markets = (boot.markets || []).map((item) => item.name);
  const marketNames = markets.length ? markets : MARKET_FALLBACK;
  const multiMarket = ["compare", "multi", "readiness", "journey"].includes(id);
  const third = id === "map"
    ? `<label class="select"><select aria-label="法规状态" data-filter-role="recordStatus">${options(["全部状态", "现行有效", "已废止或待确认"], conditions.recordStatus)}</select></label>`
    : id === "timeline"
      ? `<label class="select"><select aria-label="时间窗" data-filter-role="window">${options(boot.timeline_windows || ["近 12 个月", "近 6 个月"], conditions.window)}</select></label>`
      : id === "todo"
        ? `<label class="select"><select aria-label="紧迫度" data-filter-role="urgency">${options(["按紧迫度", "高", "中", "低"], conditions.urgency)}</select></label>`
        : "";
  const filters = `<div class="filterbar">
      <label class="select"><span class="select__label">品类</span><select aria-label="品类" data-filter-role="category">${options(categories, conditions.category)}</select></label>
      ${multiMarket
        ? `<span class="chip">${esc(marketNames.join(" + "))}</span>`
        : `<label class="select"><span class="select__label">市场</span><select aria-label="市场" data-filter-role="market">${options(marketNames, conditions.market)}</select></label>`}
      ${third}
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
  else body = `<div class="list">${recordList([])}</div>${errorNote(error)}`;

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
