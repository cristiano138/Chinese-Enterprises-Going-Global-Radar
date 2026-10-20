// 搬运自 prototype.html:1573-1596。函数体逐字未动，仅补头部导入与 export。
import { ic } from "../icons.js";
import { rowHtml, toolCard } from "../render.js";

  export function regulationsView(state) {
    return `
      <div class="page-head">
        <h1>法规中心</h1>
        <p>查法规、看时间线、找原文。浏览和检索都在这一个页面里。</p>
      </div>

      <button class="search-entry" data-action="nav" data-to="regulations/search">
        ${ic("search")}
        <span class="search-entry__text">搜法规编号、条款标题或产品要求</span>
        <span class="search-entry__id">2009/48/EC</span>
      </button>

      <div class="section-head"><b>查询工具</b><span>2 项</span></div>
      <div class="tool-grid">
        ${toolCard("regulations", "map", "map", "法规地图", "按品类和市场看适用法规")}
        ${toolCard("regulations", "timeline", "calendar", "变化时间线", "发布、生效与过渡节点")}
      </div>

      <div class="section-head"><b>当前市场</b><span>儿童玩具 · 德国</span></div>
      <div class="list">${["toy", "en71", "freshGpsr"].map(rowHtml).join("")}</div>
      <p class="fine" style="margin-top:9px">当前市场条目来自已核对目录；点开可核对适用条件和官方原文。</p>
      <p class="fine" style="margin-top:12px">法规时效检查结果在首页，每天 09:00 / 21:00 自动更新。</p>`;
  }
