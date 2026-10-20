// 搬运自 prototype.html:2154-2185。函数体逐字未动，仅补 export 与头部导入。
import { esc } from "../dom.js";
import { ic } from "../icons.js";
import { ITEMS } from "../sample.js";

  export function detailSheet(id) {
    const it = ITEMS[id] || ITEMS.toy;
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
          <a class="source-link" href="${it.url}" target="_blank" rel="noreferrer">
            ${ic("doc")}<span style="flex:1">${esc(it.source)}</span>${ic("external")}
          </a>
          <p class="excerpt">${esc(it.excerpt)}</p>
          <p class="fine">${esc(it.version)}</p>
        </div>
        <div class="sheet__actions">
          <button class="btn btn--primary btn--block" data-action="mark-done">${ic("check")}标记为已完成</button>
          <button class="btn btn--block" data-action="export">导出这一条</button>
        </div>
      </div>`;
  }
