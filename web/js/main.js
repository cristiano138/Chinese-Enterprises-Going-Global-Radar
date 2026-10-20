// 启动：挂路由、渲染外壳、绑事件委托。
// render 的分派表与事件委托逐字对应 prototype.html:2006-2078 与 2351-2444。
import { ic } from "./icons.js";
import { store } from "./store.js";
import { routeOf, go } from "./router.js";
import { renderAppbar, renderTabbar } from "./shell.js";
import { closeSheet } from "./ui/sheet.js";

const els = {
  appbar: document.getElementById("appbar"),
  view: document.getElementById("view"),
  dock: document.getElementById("dock"),
  tabbar: document.getElementById("tabbar"),
};

import { homeView } from "./views/home.js";
import { resultView } from "./views/result.js";
import { freshnessView } from "./views/freshness.js";

// Task 6 起逐个接入真实视图；尚无视图的路由渲染空白（回落见下方说明）。
const VIEWS = {
  home: homeView,
  result: resultView,
  freshness: freshnessView,
};

export const render = () => {
  const state = store.state;
  state.route = routeOf();
  const r = state.route;

  // 与原型 2010-2019 一致：工具组与工具名的解析
  if (r.startsWith("regulations/")) {
    state.toolGroup = "regulations";
    state.tool = r.split("/")[1] || null;
  } else if (r.startsWith("action/")) {
    state.toolGroup = "action";
    state.tool = r.split("/")[1] || null;
  } else {
    state.tool = null;
    state.toolGroup = null;
  }

  els.appbar.innerHTML = renderAppbar(state);
  els.tabbar.innerHTML = renderTabbar(state);

  // 原型 2068-2071 的未知路由回落（go("home")）**不在这里**：判据是"当且仅当所有其它路由
  // 都已有视图时，回落才可观测"。Task 6 时 12 条路由仍有 9 条无视图（assistant /
  // regulations(/*) / action(/*) / profile(/*)），回落会对它们一视同仁地触发，
  // 外壳行为的断言会因"每条路由都变成首页"而集体失真。它落在 Task 9。
  const view = VIEWS[r];
  els.view.className = "view";
  els.view.innerHTML = view ? view(state) : "";
  els.view.scrollTop = 0;
  els.dock.innerHTML = "";
};

window.addEventListener("hashchange", () => { store.state.route = routeOf(); render(); });

document.addEventListener("click", (event) => {
  const el = event.target.closest("[data-action]");
  if (!el) return;
  const action = el.dataset.action;
  if (action === "nav") {
    closeSheet();                              // 原型 2357：抽屉里的 nav 也要先关抽屉
    go(el.dataset.to || "assistant");          // 原型 2358：nav 默认去 assistant
  } else if (action === "open-tool") {
    go((el.dataset.group || "regulations") + "/" + el.dataset.tool);
  } else if (action === "fresh-filter") {
    store.set({ freshFilter: el.dataset.filter || "全部" });
    render();
  } else if (action === "close-sheet") {
    closeSheet();
  }
  // 其余 action 由 Task 5 起的任务逐个接入。
});

// 与原型 2443 一致：带 is-on 判断，无关的 Escape 不触发关闭。
document.addEventListener("keydown", (event) => {
  const sheet = document.getElementById("sheet");
  if (event.key === "Escape" && sheet.classList.contains("is-on")) closeSheet();
});

store.state.route = routeOf();
render();
