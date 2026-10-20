// 历史结果：浏览器本地保存最近若干次「品类 + 市场」查询的清单快照。
// 会话本来就不写服务端；这里只存查询条件和归一化后的 todo 载荷，打开时原样回放。
import { esc } from "./dom.js";
import { ic } from "./icons.js";

const KEY = "cr_history_v1";
const LIMIT = 8;

function newId() {
  if (window.crypto && typeof window.crypto.randomUUID === "function") {
    return window.crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export function listHistory() {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(KEY) || "[]");
    return Array.isArray(parsed) ? parsed : [];
  } catch (error) {
    return [];
  }
}

function save(entries) {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(entries.slice(0, LIMIT)));
  } catch (error) {
    // 隐私模式或配额不足时静默降级：历史不可用，但当前查询不受影响。
  }
}

export function timeLabel(ts) {
  const date = new Date(Number(ts) || Date.now());
  if (Number.isNaN(date.getTime())) return "";
  const now = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  const sameDay = date.getFullYear() === now.getFullYear()
    && date.getMonth() === now.getMonth() && date.getDate() === now.getDate();
  const clock = `${pad(date.getHours())}:${pad(date.getMinutes())}`;
  return sameDay ? `今天 ${clock}` : `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${clock}`;
}

export function latestHistory() {
  return listHistory()[0] || null;
}

export function getHistory(id) {
  return listHistory().find((entry) => entry.id === id) || null;
}

export function recordHistory({ category, market, platform, powered, cutoff, todo }) {
  if (!todo || !Array.isArray(todo.actions)) return;
  const key = [category, market, platform, powered].join("|");
  const entries = listHistory().filter((entry) => entry.key !== key);
  entries.unshift({
    id: newId(),
    key,
    ts: Date.now(),
    category,
    market,
    platform: platform || "",
    powered: powered || "",
    cutoff: cutoff || "",
    title: `${category} · ${market} 行动清单`,
    action_count: todo.actions.length,
    high_priority: todo.actions.filter((action) => action.urgency === "高").length,
    todo,
  });
  save(entries);
}

export function historySheet() {
  const entries = listHistory();
  const rows = entries.length
    ? entries.map((entry) => `
        <button class="history-item" data-action="open-history" data-id="${esc(entry.id)}">
          <span class="menu-row__icon">${ic("doc")}</span>
          <span class="history-item__copy">
            <b>${esc(entry.title)}</b>
            <span>${esc(timeLabel(entry.ts))} · ${esc(entry.category)} / ${esc(entry.market)} / ${esc(entry.platform || "未指定平台")} · ${entry.action_count} 项</span>
          </span>
          ${ic("chevron")}
        </button>`).join("")
    : `<div class="row">
         <span class="row__rail"></span>
         <span class="row__body"><span class="row__sub">还没有历史结果。完成一次查询后，这里会保留当时的条件和清单快照。</span></span>
       </div>`;
  return `
    <div class="sheet__grab"></div>
    <div class="sheet__body">
      <div class="sheet__top">
        <span class="sheet__lead" style="margin:0">历史结果</span>
        <button class="sheet__close" data-action="close-sheet" aria-label="关闭">${ic("close")}</button>
      </div>
      <h2>保留当时条件的 ${entries.length} 份结果</h2>
      <div style="margin-top:12px">${rows}</div>
      <p class="fine" style="margin-top:14px">打开历史结果会回放当时的清单快照，不自动重新查询；需要最新数据请重新生成。</p>
    </div>`;
}
