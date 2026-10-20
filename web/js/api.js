// /api/* 封装：统一信封 {ok, reason, data, meta}，失败时抛 ApiError。
// 视图只消费 data，不感知 HTTP 细节。

export class ApiError extends Error {
  constructor(message, { payload = null, status = 0 } = {}) {
    super(message);
    this.name = "ApiError";
    this.payload = payload;
    this.status = status;
  }
}

function withQuery(path, params) {
  if (!params) return path;
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") search.set(key, value);
  });
  const text = search.toString();
  return text ? `${path}?${text}` : path;
}

export async function api(path, { method = "GET", body, params } = {}) {
  const init = { method, headers: {} };
  if (body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(withQuery(path, params), init);
  } catch (error) {
    throw new ApiError("网络不可用，请确认服务仍在运行。", { status: 0 });
  }
  let payload = null;
  try {
    payload = await response.json();
  } catch (error) {
    throw new ApiError(`服务返回了无法解析的内容（HTTP ${response.status}）。`,
      { status: response.status });
  }
  if (!payload || payload.ok !== true) {
    throw new ApiError((payload && payload.reason) || `请求失败（HTTP ${response.status}）`,
      { payload, status: response.status });
  }
  return payload.data;
}

export async function upload(path, formData) {
  let response;
  try {
    response = await fetch(path, { method: "POST", body: formData });
  } catch (error) {
    throw new ApiError("网络不可用，请确认服务仍在运行。", { status: 0 });
  }
  let payload = null;
  try {
    payload = await response.json();
  } catch (error) {
    throw new ApiError(`服务返回了无法解析的内容（HTTP ${response.status}）。`,
      { status: response.status });
  }
  if (!payload || payload.ok !== true) {
    throw new ApiError((payload && payload.reason) || `请求失败（HTTP ${response.status}）`,
      { payload, status: response.status });
  }
  return payload.data;
}

export const Api = {
  bootstrap: () => api("/api/bootstrap"),
  freshness: () => api("/api/freshness"),
  transcribe: (blob, filename = "voice.wav") => {
    const form = new FormData();
    form.append("audio", blob, filename);
    return upload("/api/transcribe", form);
  },
  tool: (name, params = {}) => api(`/api/tool/${name}`, { method: "POST", body: params }),
  route: (text, context = "", useLLM = true) =>
    api("/api/route", { method: "POST", body: { text, context, use_llm: useLLM } }),
  search: (identifier, heading = "") =>
    api("/api/search", { params: { identifier, heading } }),
  todoCsvUrl: ({ category = "", market = "" } = {}) =>
    withQuery("/api/export/todo.csv", { category, market }),
  readinessCsvUrl: ({ category = "", markets = [] } = {}) =>
    withQuery("/api/export/readiness.csv", {
      category,
      markets: Array.isArray(markets) ? markets.join(",") : markets,
    }),
};
