// 启动：挂路由、渲染外壳、绑事件委托。
// render 的分派表与事件委托逐字对应 prototype.html:2006-2078 与 2351-2444。
import { ic } from "./icons.js";
import { store } from "./store.js";
import { routeOf, go } from "./router.js";
import { renderAppbar, renderTabbar } from "./shell.js";
import { closeSheet, openSheet } from "./ui/sheet.js";

const els = {
  appbar: document.getElementById("appbar"),
  view: document.getElementById("view"),
  dock: document.getElementById("dock"),
  tabbar: document.getElementById("tabbar"),
};

import { homeView } from "./views/home.js";
import { resultView } from "./views/result.js";
import { freshnessView } from "./views/freshness.js";
import { render as assistantRender, send, choose, newChat } from "./views/assistant.js";
import { regulationsView } from "./views/regulations.js";
import { actionView } from "./views/action.js";
import { toolView } from "./views/tool.js";
import { searchView } from "./views/search.js";
import { composerDock, bindComposer } from "./ui/composer.js";
import { showToast } from "./ui/toast.js";
import { PROFILE_SHEETS } from "./sample.js";

// Task 6 起逐个接入真实视图；尚无视图的路由渲染空白（回落见下方说明）。
const VIEWS = {
  home: homeView,
  result: resultView,
  freshness: freshnessView,
  assistant: assistantRender,
  regulations: regulationsView,
  "regulations/search": searchView,
  action: actionView,
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
  const view = Object.hasOwn(VIEWS, r) ? VIEWS[r] : ((r.startsWith("regulations/") || r.startsWith("action/")) ? toolView : null);
  els.view.className = r === "assistant" ? "view view--chat" : "view";
  els.view.innerHTML = view ? view(state) : "";
  els.view.scrollTop = 0;
  els.dock.innerHTML = r === "assistant" ? composerDock(state) : "";
  if (r === "assistant") {
    bindComposer((text) => {
      send(text);
      render();
    });
  }
};

window.addEventListener("hashchange", () => { store.state.route = routeOf(); render(); });

document.addEventListener("click", (event) => {
  const el = event.target.closest("[data-action]");
  if (!el) return;
  const action = el.dataset.action;
  if (action === "nav") {
    closeSheet();                              // 原型 2357：抽屉里的 nav 也要先关抽屉
    go(el.dataset.to || "assistant");          // 原型 2358：nav 默认去 assistant
  } else if (action === "prompt") {
    send(el.dataset.prompt || "");
    render();
  } else if (action === "choice") {
    choose(el.dataset.choice || "");
    render();
  } else if (action === "new-chat") {
    newChat();
    render();
  } else if (action === "history") {
    openSheet(PROFILE_SHEETS.history());
  } else if (action === "quick") {
    const label = el.dataset.label;
    const prompts = {
      "多市场": "多个市场汇总，一次看清主要差异",
      "时间线": "查看法规变化时间线，最近有什么新要求",
      "对比": "比较欧盟和美国的儿童玩具法规目录",
      "导出": "导出当前结果",
    };
    if (label === "导出") showToast("原型中不生成文件；正式版会导出当前结果");
    else { send(prompts[label] || label); render(); }
  } else if (action === "open-tool") {
    go((el.dataset.group || "regulations") + "/" + el.dataset.tool);
  } else if (action === "fresh-filter") {
    store.set({ freshFilter: el.dataset.filter || "全部" });
    render();
  } else if (action === "filter") {
    store.set({ filter: el.dataset.filter || "全部" });
    render();
  } else if (action === "rerun") {
    showToast("已按当前条件重新生成");
  } else if (action === "example-query") {
    store.set({ query: el.dataset.query || "", searchDone: true });
    render();
  } else if (action === "close-sheet") {
    closeSheet();
  }
  // 其余 action 由 Task 5 起的任务逐个接入。
});

// Task 7 的 compose 提交处理器绑定在 form 元素上（见 ui/composer.js），因此这里只处理 search。
document.addEventListener("submit", (event) => {
  const form = event.target;
  if (form.dataset.form === "search") {
    event.preventDefault();
    const input = form.querySelector("input");
    store.set({ query: input ? input.value : "", searchDone: true });
    render();
  }
});

// 与原型 2443 一致：带 is-on 判断，无关的 Escape 不触发关闭。
document.addEventListener("keydown", (event) => {
  const sheet = document.getElementById("sheet");
  if (event.key === "Escape" && sheet.classList.contains("is-on")) closeSheet();
});

store.state.route = routeOf();
render();
