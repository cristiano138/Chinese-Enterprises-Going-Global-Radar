// 搬运自 prototype.html:1186-1240, 1970-2003。
// 增量：函数改为 export 并接收 state 形参（函数体逐字未动，因为原型内部就写作 state）；
// 显式导入 esc/ic/TOOL_PAGES。
import { esc } from "./dom.js";
import { ic } from "./icons.js";
import { TOOL_PAGES } from "./sample.js";

  export function renderAppbar(state) {
    const r = state.route;
    const brand = (title, sub) => `
      <div class="brand">
        <span class="brand__mark">${ic("radar")}</span>
        <div>
          <div class="brand__name">${esc(title)}</div>
          <div class="brand__sub"><span class="live-dot"></span>${esc(sub)}</div>
        </div>
      </div>`;
    const back = (to, label, sub) => `
      <button class="iconbtn" data-action="nav" data-to="${to}" aria-label="返回">${ic("back")}</button>
      <div class="bar-title">
        <div class="bar-title__name">${esc(label)}</div>
        <div class="bar-title__sub">${esc(sub || "")}</div>
      </div>`;

    const history = `<button class="iconbtn" data-action="history" aria-label="历史结果">${ic("history")}</button>`;
    const plus = `<button class="iconbtn" data-action="new-chat" aria-label="新对话">${ic("plus")}</button>`;

    if (r === "home") return brand("合规雷达", "每天 09:00 / 21:00 自动核验") + history + plus;
    if (r === "freshness") return back("home", "检查记录", "每天 09:00 / 21:00 自动核验") + history;
    if (r === "assistant") {
      return `
        <button class="iconbtn" data-action="nav" data-to="home" aria-label="返回首页">${ic("back")}</button>
        <div class="bar-title">
          <button class="bar-title__btn" data-action="history" aria-label="打开对话历史">
            <span class="bar-title__name">合规雷达 · 新对话</span>
            <span class="bar-title__caret">▾</span>
          </button>
          <div class="bar-title__sub"><span class="live-dot"></span>deepseek-chat · 德国 / 亚马逊</div>
        </div>
        <button class="iconbtn" data-action="new-chat" aria-label="新对话">${ic("plus")}</button>`;
    }
    if (r === "result") {
      return back(state.resultFrom || "assistant", "德国市场行动清单", "结果 CR-1019-03 · 数据截止 10-19") +
        `<button class="iconbtn" data-action="export" aria-label="导出">${ic("download")}</button>`;
    }
    if (r === "regulations") return brand("合规雷达", "法规中心 · 搜索与时间线") + history;
    if (r === "regulations/search") return back("regulations", "条款检索", "按法规编号定位正文") + history;
    if (r.startsWith("regulations/")) {
      const tool = state.tool && TOOL_PAGES[state.tool];
      return back("regulations", tool ? tool.title : "法规中心", "当前筛选会随结果保留") + history;
    }
    if (r === "action") return brand("合规雷达", "行动 · 任务、计划与市场") + history;
    if (r.startsWith("action/")) {
      const tool = state.tool && TOOL_PAGES[state.tool];
      return back("action", tool ? tool.title : "行动", "当前筛选会随结果保留") + history;
    }
    if (r === "profile/tutorial") return back("profile", "教程", "企业用户使用指引 · 约 3 分钟") + history;
    if (r === "profile") return brand("我的", "教程、历史与设置") +
      `<button class="iconbtn" data-action="nav" data-to="profile/tutorial" aria-label="教程">${ic("help")}</button>`;

    return brand("合规雷达", "在线 · 法规库 86 部") + history + plus;
  }

  export const TABS = [
    ["home", "home", "首页"],
    ["regulations", "book", "法规"],
    ["assistant", "chat", "助手"],
    ["action", "flag", "行动"],
    ["profile", "user", "我的"]
  ];

  export function renderTabbar(state) {
    const active = state.route.startsWith("regulations")
      ? "regulations"
      : state.route.startsWith("action")
        ? "action"
        : state.route.startsWith("profile")
          ? "profile"
          : state.route === "freshness"
            ? "home"
            : state.route;
    return TABS.map(([route, icon, label]) => {
      if (route === "assistant") {
        return `
          <button class="tab tab--main ${active === route ? "is-on" : ""}" data-action="nav" data-to="${route}"
                  aria-current="${active === route ? "page" : "false"}" aria-label="${label}">
            <span class="tab__main">${ic(icon)}<span>${label}</span></span>
          </button>`;
      }
      return `
        <button class="tab ${active === route ? "is-on" : ""}" data-action="nav" data-to="${route}"
                aria-current="${active === route ? "page" : "false"}">
          <span class="tab__wrap">${ic(icon)}</span>
          <span>${label}</span>
        </button>`;
    }).join("");
  }
