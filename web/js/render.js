// 搬运自 prototype.html:1425-1441, 1443-1447, 1566-1571, 1627-1632。
// 增量：顶层函数/常量改为 export；显式导入 esc/ic/数据表；
// filteredItems/filteredFresh 改吃 state 参数（Task 4 起由调用方传 store.state）。
import { esc } from "./dom.js";
import { ic } from "./icons.js";
import { ITEMS, RESULT_ITEMS, FRESH_ITEMS } from "./sample.js";

  /** 真实数据行：与原型 rowHtml 同一套类名，id 换成后端稳定标识。 */
  export function dataRow(item) {
    if (!item) return "";
    const rail = item.rail || "ok";
    const typeCls = ["type-chip", item.typeClass].filter(Boolean).join(" ");
    const statusCls = rail === "warn" ? "row__status--warn" : rail === "ok" ? "row__status--ok" : "";
    return `
      <button class="row" data-action="detail" data-id="${esc(item.id)}">
        <span class="row__rail row__rail--${rail}"></span>
        <span class="row__body">
          <span class="row__top"><span class="${typeCls}">${esc(item.type || "法律法规")}</span></span>
          <span class="row__title">${esc(item.title)}</span>
          <span class="row__sub">${esc(item.sub || "")}</span>
          <span class="row__status ${statusCls}"><i></i>${esc(item.status || "")}</span>
        </span>
        <span class="row__end">${ic("chevron")}</span>
      </button>`;
  }

  export function recordRow(record) {
    if (!record) return "";
    return dataRow({
      id: record.id,
      type: record.type || "法律法规",
      title: record.title,
      sub: record.subtitle || record.official_id || record.source || "",
      status: record.status,
      rail: record.rail || "ok",
    });
  }

  export function actionRow(action, index = 0) {
    if (!action) return "";
    const rail = action.urgency === "高" ? "warn" : action.urgency === "低" ? "muted" : "ok";
    return dataRow({
      id: action.id,
      type: (action.type || "操作建议").slice(0, 8),
      typeClass: "type-chip--ops",
      title: action.title,
      sub: [action.law, action.official_id].filter(Boolean).join(" · ") || action.condition,
      status: [action.urgency ? `紧迫度 ${action.urgency}` : "", action.deadline_note || action.deadline]
        .filter(Boolean).join(" · "),
      rail,
    });
  }

  export function rowHtml(id) {
    const it = ITEMS[id];
    if (!it) return "";
    const typeCls = ["type-chip", it.typeClass].filter(Boolean).join(" ");
    const statusCls = it.rail === "warn" ? "row__status--warn" : it.rail === "ok" ? "row__status--ok" : "";
    return `
      <button class="row" data-action="detail" data-id="${id}">
        <span class="row__rail row__rail--${it.rail}"></span>
        <span class="row__body">
          <span class="row__top"><span class="${typeCls}">${esc(it.type)}</span></span>
          <span class="row__title">${esc(it.title)}</span>
          <span class="row__sub">${esc(it.sub)}</span>
          <span class="row__status ${statusCls}"><i></i>${esc(it.status)}</span>
        </span>
        <span class="row__end">${ic("chevron")}</span>
      </button>`;
  }
  export function filteredItems(state) {
    if (state.filter === "全部") return RESULT_ITEMS;
    if (state.filter === "待确认") return RESULT_ITEMS.filter(id => ITEMS[id].rail === "warn");
    return RESULT_ITEMS.filter(id => ITEMS[id].type === state.filter);
  }
  export const toolCard = (group, id, icon, title, sub, badge = "") => `
    <button class="tool" data-action="open-tool" data-group="${group}" data-tool="${id}">
      <span class="tool__icon">${ic(icon)}</span>
      <b>${title}${badge ? `<span class="tool__badge">${badge}</span>` : ""}</b>
      <span>${sub}</span>
    </button>`;
  export function filteredFresh(state) {
    if (state.freshFilter === "需处理") return FRESH_ITEMS.filter(id => ITEMS[id].rail === "warn");
    if (state.freshFilter === "已最新") return FRESH_ITEMS.filter(id => ITEMS[id].rail === "ok");
    if (state.freshFilter === "无法确认") return FRESH_ITEMS.filter(id => ITEMS[id].rail === "muted");
    return FRESH_ITEMS;
  }
