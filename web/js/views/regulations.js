// 法规中心：检索入口 + 两个工具 + 当前市场的适用法规（来自 /api/tool/map）。
import { ic } from "../icons.js";
import { recordRow, toolCard } from "../render.js";
import { conditions, toolData, toolError } from "../data.js";

export function regulationsView(state) {
  const map = toolData("map");
  const error = toolError("map");
  const records = map ? map.records : [];
  const rows = records.length
    ? records.slice(0, 8).map(recordRow).join("")
    : `<div class="row">
         <span class="row__rail ${error ? "row__rail--warn" : ""}"></span>
         <span class="row__body"><span class="row__sub">${error
           ? `法规库暂时不可用：${escapeText(error)}`
           : "当前条件下没有条目。"}</span></span>
       </div>`;
  const count = records.length;
  const searchId = (map && map.records.find((record) => record.celex) || {}).celex || "32009L0048";
  const head = map
    ? `${conditions.category} · ${conditions.market}`
    : `${conditions.category} · ${conditions.market}`;

  return `
      <div class="page-head">
        <h1>法规中心</h1>
        <p>查法规、看时间线、找原文。浏览和检索都在这一个页面里。</p>
      </div>

      <button class="search-entry" data-action="nav" data-to="regulations/search">
        ${ic("search")}
        <span class="search-entry__text">搜法规编号、条款标题或产品要求</span>
        <span class="search-entry__id">${escapeText(searchId)}</span>
      </button>

      <div class="section-head"><b>查询工具</b><span>2 项</span></div>
      <div class="tool-grid">
        ${toolCard("regulations", "map", "map", "法规地图", "按品类和市场看适用法规")}
        ${toolCard("regulations", "timeline", "calendar", "变化时间线", "发布、生效与过渡节点")}
      </div>

      <div class="section-head"><b>当前市场</b><span>${head}</span></div>
      <div class="list">${rows}</div>
      <p class="fine" style="margin-top:9px">当前市场条目来自已核对目录，共 ${count} 条；点开可核对适用条件和官方原文。${error ? ` 数据读取失败：${escapeText(error)}` : ""}</p>
      <p class="fine" style="margin-top:12px">法规时效检查结果在首页，每天 09:00 / 21:00 自动更新。</p>`;
}

function escapeText(value) {
  return String(value == null ? "" : value)
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
}
