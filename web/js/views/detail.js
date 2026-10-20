// 详情抽屉：优先展示后端记录 / 动作，找不到时回落到原型示例（保证未知 id 不白屏）。
import { esc } from "../dom.js";
import { ic } from "../icons.js";
import { ITEMS } from "../sample.js";
import { cache, index } from "../data.js";

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

export function detailSheet(id) {
  const it = index.records[id] ? recordToItem(index.records[id])
    : index.actions[id] ? actionToItem(index.actions[id])
      : (ITEMS[id] || ITEMS.toy);
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
