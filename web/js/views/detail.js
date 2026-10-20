// 详情抽屉：优先展示后端记录 / 动作，找不到时回落到原型示例（保证未知 id 不白屏）。
import { esc } from "../dom.js";
import { ic } from "../icons.js";
import { cache, index } from "../data.js";
import { findItem, findResult } from "../conversation.js";

function recordToItem(record) {
  const cutoff = (cache.boot && cache.boot.data_cutoff) || "";
  return {
    type: "法律法规",
    typeClass: "",
    rail: record.rail || "ok",
    title: record.title,
    sub: record.subtitle || record.official_id || record.source || "",
    status: record.status || "官方未标注",
    why: record.why || "本条结论来自已核对目录，请结合产品实际情况核对适用性。",
    source: [record.official_id, record.source].filter(Boolean).join(" · ") || "官方来源",
    url: record.url || (record.links && record.links[0]) || "",
    excerpt: record.excerpt || "官方原文请点击来源链接查看。",
    version: [record.effective_date ? `生效日期 ${record.effective_date}` : "",
      cutoff ? `数据截止 ${cutoff}` : ""].filter(Boolean).join(" · "),
  };
}

function actionToItem(action) {
  const cutoff = (cache.boot && cache.boot.data_cutoff) || "";
  return {
    type: "操作建议",
    typeClass: "type-chip--ops",
    rail: action.urgency === "高" ? "warn" : "ok",
    title: action.title,
    sub: [action.type, action.deadline].filter(Boolean).join(" · "),
    status: action.urgency ? `紧迫度 ${action.urgency}` : "待人工确认",
    why: action.condition || "适用条件以官方原文为准。",
    source: [action.law, action.official_id].filter(Boolean).join(" · ") || "官方来源",
    url: action.url || "",
    excerpt: action.excerpt || "该条目未附原文摘录，请点击来源链接核对。",
    version: [action.deadline_note, cutoff ? `数据截止 ${cutoff}` : ""]
      .filter(Boolean).join(" · "),
  };
}

const NOT_FOUND = {
  type: "提示",
  typeClass: "",
  rail: "warn",
  title: "没有找到这一条",
  sub: "记录可能已更新，或不在当前查询结果里。",
  status: "请返回列表后重试",
  why: "详情只展示本次查询返回的记录或动作，不补造内容。",
  source: "—",
  url: "",
  excerpt: "",
  version: "",
};

const DETAIL_KEYS = [
  "官方编号", "CELEX号", "法规中文名", "依据法规", "动作", "动作类型",
  "阶段", "责任角色", "执行时点", "期限", "期限说明", "紧迫度",
  "适用条件", "现行效力", "是否仍有效", "监管机构", "类目", "市场",
  "变化摘要", "影响说明", "日期", "事件类型", "摘要来源", "已核对",
];

function detailRows(details) {
  const rows = [];
  DETAIL_KEYS.forEach((key) => {
    const value = details ? details[key] : "";
    if (value === undefined || value === null || value === "") return;
    if (typeof value === "object") return;
    const text = String(value);
    if (text.length > 320) return;
    rows.push(`<p class="fine"><b>${esc(key)}：</b>${esc(text)}</p>`);
  });
  return rows.join("");
}

/** 会话条目详情：来源、字段与资料缺口都来自 conversation.py 的结果快照。 */
export function conversationSheet(resultId, itemId) {
  const result = findResult(resultId);
  const item = findItem(resultId, itemId) || NOT_FOUND;
  const details = item.details || {};
  const rail = item.status === "user_reported_done" || item.status === "confirmed"
    ? "ok" : item.status === "excluded" || item.status === "historical" ? "muted" : "warn";
  const statusCls = rail === "warn" ? "sheet__status sheet__status--warn" : "sheet__status";
  const sources = (item.sources || []).filter((source) => source && source.url);
  const gaps = item.gaps || [];
  const done = item.status === "user_reported_done";
  return `
      <div class="sheet__grab"></div>
      <div class="sheet__body">
        <div class="sheet__top">
          <span class="type-chip ${item.kind === "task" ? "type-chip--ops" : ""}">${
            esc(item.group || (item.kind === "task" ? "操作建议" : "法规来源"))}</span>
          <button class="sheet__close" data-action="close-sheet" aria-label="关闭">${ic("close")}</button>
        </div>
        <h2>${esc(item.title)}</h2>
        <p class="sheet__lead">${esc(item.summary || "")}</p>
        <div class="${statusCls}">${ic("shield")}${esc(item.status_label || item.status || "待核对")}</div>

        <div class="sheet__section">
          <h3>为什么和你有关</h3>
          <p>${esc(item.summary || "该条目来自当前会话结果，请结合原始来源核对适用条件。")}</p>
          ${detailRows(details)}
        </div>

        <div class="sheet__section">
          <h3>依据与官方原文</h3>
          ${sources.length ? sources.map((source) => `
            <a class="source-link" href="${esc(source.url)}" target="_blank" rel="noreferrer">
              ${ic("doc")}<span style="flex:1">${esc(source.title || source.locator || source.url)}</span>${ic("external")}
            </a>
            ${source.excerpt ? `<p class="excerpt">${esc(source.excerpt)}</p>` : ""}
            <p class="fine">${esc(source.status || source.locator || "")}</p>`).join("")
            : `<p class="fine">这个条目没有可打开的官方链接；请按原始资料核对，不将其作为执行依据。</p>`}
        </div>

        ${gaps.length ? `
        <div class="sheet__section">
          <h3>资料边界与缺口</h3>
          ${gaps.map((gap) => `<p class="fine">${esc(gap)}</p>`).join("")}
        </div>` : ""}

        <div class="sheet__actions">
          ${item.can_complete ? `
            <button class="btn btn--primary btn--block" data-action="conv-complete"
                    data-result-id="${esc(resultId)}" data-item-id="${esc(item.id)}">
              ${ic("check")}${done ? "撤回完成记录" : "记录自述完成"}
            </button>` : ""}
          ${result && BUSINESS_KINDS.has(result.kind) ? `
            <button class="btn btn--block" data-action="conv-export" data-result-id="${esc(resultId)}">导出这份结果</button>` : ""}
        </div>
      </div>`;
}

const BUSINESS_KINDS = new Set(["map", "todo", "timeline", "compare", "multi", "readiness", "model", "journey"]);

export function detailSheet(id) {
  const it = index.records[id] ? recordToItem(index.records[id])
    : index.actions[id] ? actionToItem(index.actions[id])
      : NOT_FOUND;
  const statusCls = it.rail === "warn" ? "sheet__status sheet__status--warn" : "sheet__status";
  return `
      <div class="sheet__grab"></div>
      <div class="sheet__body">
        <div class="sheet__top">
          <span class="type-chip ${it.typeClass || ""}">${esc(it.type)}</span>
          <button class="sheet__close" data-action="close-sheet" aria-label="关闭">${ic("close")}</button>
        </div>
        <h2>${esc(it.title)}</h2>
        <p class="sheet__lead">${esc(it.sub)}</p>
        <div class="${statusCls}">${ic("shield")}${esc(it.status)}</div>

        <div class="sheet__section">
          <h3>为什么和你有关</h3>
          <p>${esc(it.why)}</p>
        </div>
        <div class="sheet__section">
          <h3>依据与官方原文</h3>
          ${it.url ? `
          <a class="source-link" href="${esc(it.url)}" target="_blank" rel="noreferrer">
            ${ic("doc")}<span style="flex:1">${esc(it.source)}</span>${ic("external")}
          </a>` : `<p class="fine">${esc(it.source)}</p>`}
          <p class="excerpt">${esc(it.excerpt)}</p>
          <p class="fine">${esc(it.version)}</p>
        </div>
        <div class="sheet__actions">
          <button class="btn btn--primary btn--block" data-action="mark-done"
                  data-id="${esc(id)}" data-title="${esc(it.title)}">${ic("check")}标记为已完成</button>
          <button class="btn btn--block" data-action="export">导出这一条</button>
        </div>
      </div>`;
}
