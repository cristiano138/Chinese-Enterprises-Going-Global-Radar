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
import { profileView } from "./views/profile.js";
import { tutorialView } from "./views/tutorial.js";
import { detailSheet } from "./views/detail.js";
import { composerDock, bindComposer } from "./ui/composer.js";
import { showToast } from "./ui/toast.js";
import { PROFILE_SHEETS } from "./sample.js";
import { openVoiceSheet } from "./voice.js";
import {
  bindRender, conditions, loadBootstrap, loadFreshness,
  restoreTodoSnapshot, routeData, search as runSearch,
} from "./data.js";
import { getHistory } from "./history.js";
import { markDone } from "./progress.js";
import { Api } from "./api.js";

// 路由到视图的分派表；工具组与工具名在下方按前缀解析。
const VIEWS = {
  home: homeView,
  result: resultView,
  freshness: freshnessView,
  assistant: assistantRender,
  regulations: regulationsView,
  "regulations/search": searchView,
  action: actionView,
  profile: profileView,
  "profile/tutorial": tutorialView,
};

// 事件委托里实际处理的所有 action 名（toggle-freshness 在 M1 刻意不接入）。
export const HANDLED_ACTIONS = [
  "nav", "prompt", "choice", "open-result", "new-chat", "history",
  "detail", "filter", "fresh-filter", "open-tool", "rerun",
  "example-query", "sheet", "open-history", "close-sheet", "export",
  "mark-done", "copy", "regenerate", "voice", "quick", "help"
];

const loadingView = (route) => `
  <div class="page-head" style="padding-top:16px">
    <p>正在读取后端数据…</p>
    <div class="page-head__meta mono">${stateLabel(route)}</div>
  </div>
  <div class="list">
    <div class="row">
      <span class="row__rail"></span>
      <span class="row__body"><span class="row__sub">加载中，请稍候</span></span>
    </div>
  </div>`;

const stateLabel = (route) => route === "freshness"
  ? "时效性检查记录"
  : route.startsWith("regulations") ? "法规库查询"
    : route.startsWith("action") || route === "result" ? "行动清单查询"
      : "启动信息";

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

  // 数据未到达时先渲染骨架；data.js 完成后会通过 bindRender 回调重绘。
  const loaded = routeData(r);
  if (!loaded.ready) {
    els.view.className = "view";
    els.view.innerHTML = loadingView(r);
    els.dock.innerHTML = "";
    return;
  }

  // 原型 2068-2071 的未知路由回落：所有路由就位后，未知路由回首页。
  const view = Object.hasOwn(VIEWS, r)
    ? VIEWS[r]
    : ((r.startsWith("regulations/") || r.startsWith("action/")) ? toolView : null);
  if (!view) {
    go("home");
    return;
  }
  els.view.className = r === "assistant" ? "view view--chat" : "view";
  els.view.innerHTML = view(state);
  els.view.scrollTop = 0;
  // 原型 2074-2076：对话页有新消息时滚到最新一条，而不是停在顶部。
  if (r === "assistant" && state.messages.length) {
    requestAnimationFrame(() => { els.view.scrollTop = els.view.scrollHeight; });
  }
  els.dock.innerHTML = r === "assistant" ? composerDock(state) : "";
  if (r === "assistant") {
    bindComposer((text) => {
      send(text);
      render();
    });
  }
};

// 除原型的 render 外，路由切换时先收起仍打开的抽屉：原型的所有导航入口（nav/open-tool/
// open-result/open-history）都会自行关闭抽屉，这里覆盖直接改 hash 的路径（含浏览器前进后退）。
window.addEventListener("hashchange", () => { store.state.route = routeOf(); closeSheet(); render(); });

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
    const query = el.dataset.query || "";
    store.set({ query, searchDone: true });
    if (query) runSearch(query);
    render();
  } else if (action === "close-sheet") {
    closeSheet();
  } else if (action === "detail") {
    openSheet(detailSheet(el.dataset.id));
  } else if (action === "sheet") {
    if (el.dataset.sheet === "voice") openVoiceSheet();
    else {
      const builder = PROFILE_SHEETS[el.dataset.sheet];
      if (builder) openSheet(builder());
    }
  } else if (action === "open-result") {
    store.state.resultFrom = el.dataset.from
      || (store.state.route === "home" ? "home" : "assistant");
    go("result");
  } else if (action === "open-history") {
    closeSheet();
    store.state.resultFrom = ["home", "assistant", "regulations", "action"]
      .includes(store.state.route) ? store.state.route : "profile";
    const entry = getHistory(el.dataset.id || "");
    if (entry) restoreTodoSnapshot(entry);
    go("result");
  } else if (action === "export") {
    const route = store.state.route;
    const readiness = route === "action/readiness" || route === "action/journey";
    const url = readiness
      ? Api.readinessCsvUrl({ category: conditions.category, markets: conditions.markets })
      : Api.todoCsvUrl({ category: conditions.category, market: conditions.market });
    window.location.href = url;
    showToast("正在导出 CSV");
  } else if (action === "mark-done") {
    markDone(el.dataset.id || "", el.dataset.title || "");
    showToast("已标记为已完成 · 不会自动视为合规");
    closeSheet();
    render();
  } else if (action === "copy") {
    showToast("已复制这条回答");
  } else if (action === "regenerate") {
    showToast("原型中不重复调用模型；正式版会基于同一条件重答");
  } else if (action === "voice") {
    openVoiceSheet();
  } else if (action === "help") {
    openSheet(PROFILE_SHEETS.help());
  }
});

// Task 7 的 compose 提交处理器绑定在 form 元素上（见 ui/composer.js），因此这里只处理 search。
document.addEventListener("submit", (event) => {
  const form = event.target;
  if (form.dataset.form === "search") {
    event.preventDefault();
    const input = form.querySelector("input");
    const query = input ? input.value.trim() : "";
    store.set({ query, searchDone: true });
    if (query) runSearch(query);
    render();
  }
});

// 与原型 2443 一致：带 is-on 判断，无关的 Escape 不触发关闭。
document.addEventListener("keydown", (event) => {
  const sheet = document.getElementById("sheet");
  if (event.key === "Escape" && sheet.classList.contains("is-on")) closeSheet();
});

bindRender(render);
store.state.route = routeOf();
render();
// 首屏先拿启动信息与时效性结果；失败时视图继续用原型数据兜底，不白屏。
loadBootstrap();
loadFreshness();
