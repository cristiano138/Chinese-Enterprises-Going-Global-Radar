// 启动：挂路由、渲染外壳、绑事件委托。
// render 的分派表与事件委托逐字对应 prototype.html:2006-2078 与 2351-2444。
import { ic } from "./icons.js";
import { store } from "./store.js";
import { routeOf, go } from "./router.js";
import { renderAppbar, renderTabbar } from "./shell.js";

const els = {
  appbar: document.getElementById("appbar"),
  view: document.getElementById("view"),
  dock: document.getElementById("dock"),
  tabbar: document.getElementById("tabbar"),
};

// Task 5 起逐个接入真实视图；在此之前视图为空，路由与外壳行为已可完整验证。
const VIEWS = {};

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

  // 本任务还没有任何视图，未知或无视图的路由渲染空白即可。
  // 原型 2068-2071 的未知路由回落（go("home")）**不在这里**：它要等首页视图存在
  // 才有可观测性，且若在此处生效，每条路由都会回落，外壳行为全部失真。见 Task 6。
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
    go(el.dataset.to || "assistant");          // 原型 2358：nav 默认去 assistant
  } else if (action === "open-tool") {
    go((el.dataset.group || "regulations") + "/" + el.dataset.tool);
  }
  // 其余 action 由 Task 5 起的任务逐个接入。
});

store.state.route = routeOf();
render();
