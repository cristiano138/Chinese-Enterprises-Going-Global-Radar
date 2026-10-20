// 条款检索：GET /api/search（SQLite 条款库）。正文原样展示，不生成执行动作。
import { esc } from "../dom.js";
import { ic } from "../icons.js";
import { cache } from "../data.js";

const EXAMPLES = ["32009L0048", "16 CFR Part 1250", "32023R0988"];

function unitBody(text) {
  const value = String(text || "").trim();
  return esc(value.length > 900 ? `${value.slice(0, 900)}…` : value);
}

export function searchView(state) {
  const result = cache.search;
  const error = cache.searchError;
  const loading = state.searchDone && !result && !error;

  let body = "";
  if (!state.searchDone) {
    body = `
      <div class="clause" style="margin-top:18px;color:var(--muted);font-size:11.5px;line-height:1.8">
        输入法规编号后显示正文。目录标记和机器解析不等于商品已合规，请回看官方原文确认适用性。
      </div>`;
  } else if (loading) {
    body = `<div class="section-head"><b>检索结果</b><span>查询中</span></div>
      <div class="list"><div class="row"><span class="row__rail"></span><span class="row__body"><span class="row__sub">正在查询条款库…</span></span></div></div>`;
  } else if (error) {
    body = `<div class="section-head"><b>检索结果</b><span>未完成</span></div>
      <div class="list"><div class="row"><span class="row__rail row__rail--warn"></span><span class="row__body"><span class="row__sub">${esc(error)}</span></span></div></div>`;
  } else if (result && result.units.length) {
    body = `
      <div class="section-head"><b>检索结果</b><span>${result.units.length} 条 · ${esc(result.identifier)}</span></div>
      ${result.units.map((unit) => `
        <article class="clause">
          <div class="clause__head">
            <span class="clause__id">${esc(unit.document_id || result.identifier)}</span>
            <span class="type-chip">${esc(unit.parse_status || "已解析")}</span>
          </div>
          <h3>${esc(unit.heading)}</h3>
          <p>${unitBody(unit.body)}${unit.truncated ? " …（已截断，请查看原文）" : ""}</p>
          <div class="clause__foot">
            ${unit.locator ? `<a href="${esc(unit.locator)}" target="_blank" rel="noreferrer">查看官方原文 ${ic("external")}</a>` : ""}
            <span>${esc(unit.version_date || "")}${unit.locator ? "" : " 条款库定位"}</span>
          </div>
        </article>`).join("")}`;
  } else {
    body = `<div class="section-head"><b>检索结果</b><span>无命中</span></div>
      <div class="list"><div class="row"><span class="row__rail row__rail--warn"></span><span class="row__body"><span class="row__sub">${esc(result ? result.reason : "没有检索到条款")}</span></span></div></div>`;
  }

  return `
      <div class="page-head" style="padding-top:14px">
        <p>按法规编号精确定位，再按条款标题筛选。正文保留来源、版本和解析状态。</p>
      </div>
      <form class="searchbox" data-form="search">
        <input name="q" value="${esc(state.query)}" placeholder="例如 32009L0048 或 16 CFR Part 1250"
               aria-label="法规编号" autocomplete="off" />
        <button class="btn btn--primary" type="submit">${ic("search")}检索</button>
      </form>
      <div class="example-row">
        ${EXAMPLES.map(x => `
          <button class="chip" data-action="example-query" data-query="${x}">${x}</button>`).join("")}
      </div>
      ${body}`;
}
