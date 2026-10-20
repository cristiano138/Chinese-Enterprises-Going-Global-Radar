// 搬运自 prototype.html:1748-1781。函数体逐字未动，仅补头部导入与 export。
import { esc } from "../dom.js";
import { ic } from "../icons.js";
import { CLAUSES } from "../sample.js";

  export function searchView(state) {
    return `
      <div class="page-head" style="padding-top:14px">
        <p>按法规编号精确定位，再按条款标题筛选。正文保留来源、版本和解析状态。</p>
      </div>
      <form class="searchbox" data-form="search">
        <input name="q" value="${esc(state.query)}" placeholder="例如 2009/48/EC 或 16 CFR Part 1250"
               aria-label="法规编号" autocomplete="off" />
        <button class="btn btn--primary" type="submit">${ic("search")}检索</button>
      </form>
      <div class="example-row">
        ${["2009/48/EC", "16 CFR Part 1250", "32023R0988"].map(x => `
          <button class="chip" data-action="example-query" data-query="${x}">${x}</button>`).join("")}
      </div>
      ${state.searchDone ? `
        <div class="section-head"><b>检索结果</b><span>2 条 · 已解析</span></div>
        ${CLAUSES.map(c => `
          <article class="clause">
            <div class="clause__head">
              <span class="clause__id">${c.id}</span>
              <span class="type-chip">${c.status}</span>
            </div>
            <h3>${c.heading}</h3>
            <p>${c.body}</p>
            <div class="clause__foot">
              <a href="${c.link}" target="_blank" rel="noreferrer">查看官方原文 ${ic("external")}</a>
              <span>${c.meta}</span>
            </div>
          </article>`).join("")}
      ` : `
        <div class="clause" style="margin-top:18px;color:var(--muted);font-size:11.5px;line-height:1.8">
          输入法规编号后显示正文。目录标记和机器解析不等于商品已合规，请回看官方原文确认适用性。
        </div>`}`;
  }
