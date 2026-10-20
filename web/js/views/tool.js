// 搬运自 prototype.html:1634-1732。函数体逐字未动，仅补头部导入与 export。
// 两处机械增量：签名改吃 state 并按路由取 id；filteredFresh 改吃 state 参数。
import { esc } from "../dom.js";
import { ic } from "../icons.js";
import { TOOL_PAGES } from "../sample.js";
import { rowHtml, filteredFresh } from "../render.js";
import { regulationsView } from "./regulations.js";
import { actionView } from "./action.js";

  export function toolView(state) {
    const id = state.tool;
    const t = TOOL_PAGES[id];
    if (!t) return state.toolGroup === "regulations" ? regulationsView() : actionView();
    const filters = `<div class="filterbar">${t.filters.map((f, i) => `
      <label class="select"><select aria-label="${esc(f)}"><option>${esc(f)}</option></select></label>`).join("")}
      <button class="chip" data-action="rerun">${ic("search")}重新生成</button></div>`;

    let body = "";
    if (t.custom === "freshness") {
      const fresh = filteredFresh(state);
      body = `
        <div class="fresh-summary">
          <div class="fresh-summary__head"><b>检查 4 条，2 条需要处理</b><span>检查于今天 15:20</span></div>
          <div class="fresh-summary__counts">
            <div><b>1</b><span>需处理</span></div>
            <div><b>1</b><span>有更新</span></div>
            <div><b>1</b><span>已最新</span></div>
            <div><b>1</b><span>无法确认</span></div>
          </div>
        </div>
        <div class="section-head"><b>核对结果</b><span>${fresh.length} 条 · 点开看依据</span></div>
        <div class="filter-row">
          ${["全部", "需处理", "已最新", "无法确认"].map(f => `
            <button class="filter ${state.freshFilter === f ? "is-on" : ""}"
                    data-action="fresh-filter" data-filter="${f}">${f}</button>`).join("")}
        </div>
        <div class="list">${fresh.map(rowHtml).join("")}</div>
        <p class="fine" style="margin-top:9px">时效性检查只核对目录中的版本与日期；平台规则和成员国执行差异仍需人工确认。</p>
        <div style="margin-top:14px">
          <button class="btn btn--block" data-action="rerun">${ic("search")}重新检查</button>
        </div>`;
    } else if (t.custom === "timeline") {
      body = `
        <div class="timeline">
          ${[
            ["2026-12-13", "欧盟通用产品安全法规（GPSR）适用", "在线销售的产品需要指定欧盟责任人，并更新安全信息。", "生效"],
            ["2027-01-01", "玩具指令修订过渡期节点", "关注新旧条款衔接；库存与在途货物需单独核对。", "过渡"],
            ["2027-06-30", "包装登记信息年度更新", "德国包装登记与回收系统信息需要按年度维护。", "更新"]
          ].map(([date, title, text, tag]) => `
            <div class="tl">
              <div class="tl__date">${date}</div>
              <h3>${title}</h3><p>${text}</p>
              <span class="tl__tag">${tag}</span>
            </div>`).join("")}
        </div>`;
    } else if (t.custom === "compare") {
      body = `
        <div class="compare">
          <div class="compare__head"><span>欧盟</span><span>美国</span></div>
          ${[
            ["玩具安全指令 2009/48/EC", "CPSIA + 16 CFR 1250"],
            ["CE 标识 + EU 符合性声明", "儿童产品证书（CPC）"],
            ["EN 71 系列协调标准", "ASTM F963 + 第三方测试"],
            ["欧盟责任人信息", "美国本土责任方信息"]
          ].map(([a, b]) => `<div class="compare__row"><span><b>${a}</b></span><span><b>${b}</b></span></div>`).join("")}
        </div>
        <p class="fine" style="margin-top:9px">按官方编号匹配；名称相似不代表要求等效。</p>`;
    } else if (t.custom === "multi") {
      body = `
        <div class="region">
          <div class="region__head"><b>欧盟</b><span>4 条 · 已核对</span></div>
          <div class="list">${["toy", "en71", "ce", "label"].map(rowHtml).join("")}</div>
        </div>
        <div class="region">
          <div class="region__head"><b>美国</b><span>2 条 · 已核对</span></div>
          <div class="list">${["cpsia", "amazon"].map(rowHtml).join("")}</div>
        </div>`;
    } else if (t.custom === "phases") {
      body = `
        <div class="list">
          ${[
            ["1", "选品与年龄分级", "确认目标年龄、材料和是否带电", "3 项"],
            ["2", "检测与报告", "EN 71 / CPSIA 测试范围", "2 项"],
            ["3", "标签与说明书", "德语标签、警告语、CE 标识", "4 项"],
            ["4", "文件与责任主体", "DoC、技术文件、欧盟责任人", "3 项"],
            ["5", "供应链与平台审核", "工厂资料、亚马逊类目审核", "5 项"],
            ["6", "切换与复核", "旧库存、过渡期、年度更新", "2 项"]
          ].map(([no, title, sub, count]) => `
            <button class="phase" data-action="detail" data-id="doc">
              <span class="phase__no">${no}</span>
              <span class="phase__copy"><b>${title}</b><span>${sub}</span></span>
              <span class="menu-row__end">${count}${ic("chevron")}</span>
            </button>`).join("")}
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
