// 服务端会话（core/conversation.py）的浏览器侧状态。
// 会话对象由后端生成并随请求往返；这里只负责保存、持久化、同步查询条件与导出。
import { Api } from "./api.js";
import { applyContext, conditions } from "./data.js";

const KEY = "cr_conversation_v1";
const HISTORY_KEY = "cr_conversations_v1";
const HISTORY_LIMIT = 10;

export const conv = {
  session: null,
  result: null,
  loading: false,
  pending: null,
  error: "",
  title: "新对话",
};

let notify = () => {};
let generation = 0;
export const bindConversationRender = (fn) => { notify = fn; };

function persist() {
  try {
    if (conv.session) window.sessionStorage.setItem(KEY, JSON.stringify(conv.session));
    else window.sessionStorage.removeItem(KEY);
  } catch (error) {
    // 会话过大或隐私模式：内存态仍可用，只是刷新后不恢复。
  }
}

export function restoreConversation() {
  try {
    const raw = window.sessionStorage.getItem(KEY);
    if (!raw) return;
    const session = JSON.parse(raw);
    if (session && Array.isArray(session.messages)) {
      conv.session = session;
      conv.result = activeResult(session);
      const saved = readHistory().find((entry) => entry.id === session.id);
      const firstUser = session.messages.find((message) => message.role === "user");
      conv.title = saved?.title || String(firstUser?.content || "新对话").trim().slice(0, 50) || "新对话";
    }
  } catch (error) {
    conv.session = null;
  }
}

function readHistory() {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(HISTORY_KEY) || "[]");
    return Array.isArray(parsed) ? parsed : [];
  } catch (error) {
    return [];
  }
}

/** 保存当前会话到本地对话历史（同一 session id 覆盖，按更新时间排序）。 */
function saveConversation() {
  if (!conv.session || !(conv.session.messages || []).length) return;
  const existing = readHistory().find((entry) => entry.id === conv.session.id);
  const firstUser = conv.session.messages.find((message) => message.role === "user");
  const derived = String(firstUser?.content || "新对话").trim().slice(0, 50) || "新对话";
  const title = existing?.renamed ? existing.title : derived;
  conv.title = title;
  const entries = readHistory().filter((entry) => entry.id !== conv.session.id);
  entries.unshift({
    id: conv.session.id,
    title,
    renamed: Boolean(existing?.renamed),
    updated_at: Date.now(),
    message_count: conv.session.messages.length,
    session: conv.session,
  });
  let keep = entries.slice(0, HISTORY_LIMIT);
  while (keep.length) {
    try {
      window.localStorage.setItem(HISTORY_KEY, JSON.stringify(keep));
      return;
    } catch (error) {
      keep = keep.slice(0, -1);   // 配额不足时丢掉最旧的会话
    }
  }
}

export function listConversations() {
  return readHistory().sort((a, b) => (b.updated_at || 0) - (a.updated_at || 0));
}

export function loadConversation(id) {
  const entry = readHistory().find((item) => item.id === id);
  if (!entry || !entry.session) return false;
  generation += 1;
  conv.session = entry.session;
  conv.result = activeResult(entry.session);
  conv.loading = false;
  conv.pending = null;
  conv.error = "";
  conv.title = entry.title || "新对话";
  persist();
  notify();
  return true;
}

export function renameConversation(id, title) {
  const value = String(title || "").trim().slice(0, 50);
  if (!value) return false;
  const entries = readHistory().map((entry) => entry.id === id
    ? { ...entry, title: value, renamed: true }
    : entry);
  try {
    window.localStorage.setItem(HISTORY_KEY, JSON.stringify(entries));
  } catch (error) {
    return false;
  }
  if (conv.session && conv.session.id === id) {
    conv.title = value;
    notify();
  }
  return true;
}

export function deleteConversation(id) {
  const entries = readHistory().filter((entry) => entry.id !== id);
  try {
    window.localStorage.setItem(HISTORY_KEY, JSON.stringify(entries));
  } catch (error) {
    // 配额问题不影响删除当前内存状态
  }
  if (conv.session && conv.session.id === id) {
    conversationReset();
    return true;
  }
  notify();
  return false;
}

function activeResult(session) {
  if (!session) return null;
  return (session.results || []).find((result) => result.id === session.active_result_id)
    || (session.results || [])[(session.results || []).length - 1]
    || null;
}

export function findResult(resultId) {
  return (conv.session?.results || []).find((result) => result.id === resultId) || null;
}

export function findItem(resultId, itemId) {
  const result = findResult(resultId);
  if (!result) return null;
  const scan = (items) => {
    for (const item of items || []) {
      if (item.id === itemId) return item;
      for (const nested of item.details?.items || []) {
        if (nested.id === itemId) return nested;
        for (const task of nested.details?.tasks || []) if (task.id === itemId) return task;
      }
      for (const task of item.details?.tasks || []) if (task.id === itemId) return task;
    }
    return null;
  };
  const found = scan(result.items);
  if (found) return found;
  for (const stage of result.stages || []) {
    const task = (stage.tasks || []).find((entry) => entry.id === itemId);
    if (task) return task;
  }
  return null;
}

function syncConditions(result) {
  const context = (result && result.context) || {};
  const patch = {};
  if (context.category) patch.category = context.category;
  if (["欧盟", "美国"].includes(context.market)) patch.market = context.market;
  if (context.platform) patch.platform = context.platform;
  if (context.electric === true) patch.powered = "带电";
  if (context.electric === false) patch.powered = "不带电";
  if (Object.keys(patch).length) applyContext(patch);
}

export async function conversationSend(text, action = null) {
  const current = generation;
  conv.loading = true;
  conv.pending = { text: String(text || ""), action };
  conv.error = "";
  notify();
  try {
    const data = await Api.conversationMessage(conv.session, text, action);
    if (current !== generation) return null;   // 新对话已开始，丢弃过期回复
    conv.session = data.session;
    conv.result = data.result;
    syncConditions(data.result);
    persist();
    saveConversation();
  } catch (error) {
    if (current === generation) conv.error = error.message;
  } finally {
    if (current === generation) {
      conv.loading = false;
      conv.pending = null;
      notify();
    }
  }
  return conv.result;
}

export async function conversationComplete(resultId, itemId) {
  const current = generation;
  try {
    const data = await Api.conversationComplete(conv.session, resultId, itemId);
    if (current !== generation) return null;
    conv.session = data.session;
    conv.result = data.result;
    persist();
    saveConversation();
  } catch (error) {
    if (current === generation) conv.error = error.message;
  }
  if (current === generation) notify();
  return conv.result;
}

export async function conversationExport(resultId) {
  const { blob, name } = await Api.conversationExport(conv.session, resultId);
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function conversationReset() {
  generation += 1;
  conv.session = null;
  conv.result = null;
  conv.loading = false;
  conv.pending = null;
  conv.error = "";
  conv.title = "新对话";
  persist();
  notify();
}

export { conditions };
