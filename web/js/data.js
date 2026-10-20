// 后端数据缓存与按路由预取。
// 设计约束：M1 的视图是同步函数，因此这里只负责「拿数据 + 通知重绘」，
// 路由需要而尚未拿到的数据由 main.js 先渲染骨架，数据到达后再渲染真实内容。
import { Api } from "./api.js";
import { recordHistory } from "./history.js";

export const conditions = {
  category: "儿童玩具",
  market: "欧盟",
  platform: "亚马逊",
  powered: "不带电",
  markets: ["欧盟", "美国"],
};

export const cache = {
  boot: null,
  freshness: null,
  tools: {},          // key -> data
  search: null,
  searchError: "",
  query: "",
  historical: null,   // 从历史抽屉打开的快照；重新查询时清空
  lastRoute: null,
  errors: {},         // key -> message
  pending: new Set(), // key
};

// 详情抽屉按后端稳定 id 找记录 / 动作。
export const index = { records: {}, actions: {} };

export function registerRecords(records = []) {
  records.forEach((record) => {
    if (record && record.id) index.records[record.id] = record;
  });
}

export function registerActions(actions = []) {
  actions.forEach((action) => {
    if (action && action.id) index.actions[action.id] = action;
  });
}

function indexToolData(name, data) {
  if (!data) return;
  if (name === "map") registerRecords(data.records);
  if (name === "multi" || name === "compare") {
    (data.regions || []).forEach((region) => registerRecords(region.records));
  }
  if (name === "todo") registerActions(data.actions);
  if (name === "readiness") {
    (data.regions || []).forEach((region) => (region.phases || [])
      .forEach((phase) => registerActions(phase.actions)));
  }
}

let notify = () => {};
export const bindRender = (fn) => { notify = fn; };
const emit = () => notify();

export function toolParams(name) {
  if (name === "compare" || name === "multi" || name === "readiness") {
    return { category: conditions.category, markets: conditions.markets };
  }
  // M1/M2/M3 支持模型润色；后端在未配置模型时会立即降级到确定性结果。
  const params = { category: conditions.category, market: conditions.market };
  if (name === "map" || name === "todo" || name === "timeline") params.use_llm = true;
  return params;
}

export function toolKey(name, params = toolParams(name)) {
  return `${name}:${JSON.stringify(params)}`;
}

export async function loadBootstrap() {
  if (cache.boot || cache.pending.has("boot")) return;
  cache.pending.add("boot");
  try {
    cache.boot = await Api.bootstrap();
    delete cache.errors.boot;
  } catch (error) {
    cache.errors.boot = error.message;
  } finally {
    cache.pending.delete("boot");
    emit();
  }
}

export async function loadFreshness() {
  if (cache.freshness || cache.pending.has("freshness")) return;
  cache.pending.add("freshness");
  try {
    cache.freshness = await Api.freshness();
    delete cache.errors.freshness;
  } catch (error) {
    cache.errors.freshness = error.message;
  } finally {
    cache.pending.delete("freshness");
    emit();
  }
}

export async function ensureTool(name, params = toolParams(name)) {
  const key = toolKey(name, params);
  if (cache.tools[key] || cache.pending.has(key) || cache.errors[key]) {
    return cache.tools[key] || null;
  }
  cache.pending.add(key);
  try {
    cache.tools[key] = await Api.tool(name, params);
    indexToolData(name, cache.tools[key]);
    delete cache.errors[key];
    if (name === "todo") {
      cache.historical = null;
      recordHistory({
        category: params.category,
        market: params.market,
        platform: conditions.platform,
        powered: conditions.powered,
        cutoff: cache.boot && cache.boot.data_cutoff,
        todo: cache.tools[key],
      });
    }
  } catch (error) {
    cache.errors[key] = error.message;
  } finally {
    cache.pending.delete(key);
    emit();
  }
  return cache.tools[key] || null;
}

export function toolData(name, params = toolParams(name)) {
  return cache.tools[toolKey(name, params)] || null;
}

export function toolError(name, params = toolParams(name)) {
  return cache.errors[toolKey(name, params)] || "";
}

// 路由 → 所需数据。返回值：
//   { ready:true, data }  可以渲染
//   { ready:false }       已发起请求，先渲染骨架
//   { ready:true, error } 请求失败，渲染错误态（不再重试）
export function routeData(route) {
  if (route === "home" || route === "freshness") {
    if (route === "home") ensureTool("readiness", toolParams("readiness"));
    if (cache.freshness) return { ready: true, data: cache.freshness };
    if (cache.errors.freshness) return { ready: true, error: cache.errors.freshness };
    loadFreshness();
    return { ready: false };
  }
  if (route === "profile" || route === "profile/tutorial") {
    if (cache.boot) return { ready: true, data: cache.boot };
    if (cache.errors.boot) return { ready: true, error: cache.errors.boot };
    loadBootstrap();
    return { ready: false };
  }
  if (route === "regulations") {
    ensureTool("map", toolParams("map"));
    return { ready: true };
  }
  if (route === "action") {
    ensureTool("todo", toolParams("todo"));
    ensureTool("readiness", toolParams("readiness"));
    return { ready: true };
  }
  const raw = route.startsWith("regulations/")
    ? (route === "regulations/map" ? "map" : route === "regulations/timeline" ? "timeline" : "")
    : route === "result" ? "todo"
      : route.startsWith("action/") ? route.split("/")[1] : "";
  // 行程页复用上线准备数据；其余工具名与后端一致。
  const name = raw === "journey" ? "readiness" : raw;
  if (!name || !["map", "timeline", "todo", "compare", "multi", "readiness"].includes(name)) {
    return { ready: true };
  }
  const toolName = name;
  const params = toolParams(toolName);
  const key = toolKey(toolName, params);
  if (cache.tools[key]) return { ready: true, data: cache.tools[key] };
  if (cache.errors[key]) return { ready: true, error: cache.errors[key] };
  ensureTool(toolName, params);
  return { ready: false };
}

export async function search(identifier, heading = "") {
  cache.search = null;
  cache.searchError = "";
  cache.query = identifier;
  emit();
  try {
    cache.search = await Api.search(identifier, heading);
  } catch (error) {
    cache.searchError = error.message;
  }
  emit();
  return cache.search;
}

export async function route(text, context = "") {
  return Api.route(text, context);
}

export function resetToolCache() {
  cache.tools = {};
  cache.errors = {};
  emit();
}

/** 从历史抽屉打开：恢复查询条件，并把当时的 todo 快照放回缓存（不重新查询）。 */
export function restoreTodoSnapshot(entry) {
  if (!entry || !entry.todo) return false;
  conditions.category = entry.category || conditions.category;
  conditions.market = entry.market || conditions.market;
  conditions.platform = entry.platform || conditions.platform;
  conditions.powered = entry.powered || conditions.powered;
  const params = { category: conditions.category, market: conditions.market };
  cache.tools[toolKey("todo", params)] = entry.todo;
  registerActions(entry.todo.actions || []);
  cache.historical = entry;
  return true;
}
