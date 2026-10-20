// 助手：消息、条件与结果全部来自 core/conversation.py（经 /api/conversation/*）。
// 欢迎页仍用原型结构；对话页按会话结果渲染条目、追问、动作与导出。
import { esc } from "../dom.js";
import { ic } from "../icons.js";
import { store } from "../store.js";
import { go } from "../router.js";
import { showToast } from "../ui/toast.js";
import { render as appRender } from "../main.js";
import { cache, conditions } from "../data.js";
import {
  conv, conversationComplete, conversationExport, conversationReset,
  conversationSend, findResult,
} from "../conversation.js";

const state = store.state;
const BUSINESS_KINDS = new Set(["map", "todo", "timeline", "compare", "multi", "readiness", "model", "journey"]);

/** 开场建议由后端支持的品类/市场生成。 */
function startSuggestions() {
  const boot = cache.boot || {};
  const markets = (boot.markets || []).map((item) => item.name);
  const names = markets.length ? markets : ["欧盟", "美国"];
  const category = conditions.category;
  const market = names.includes(conditions.market) ? conditions.market : names[0];
  const other = names.find((name) => name !== market) || "美国";
  return [
    { title: `${category}卖到${market}，要从哪里开始？`, prompt: `我想把${category}卖到${market}，从哪里开始？`, lead: true },
    { title: `${category}卖到${market}，先看相关法规`, prompt: `${category}卖到${market}，先看相关法规`, lead: true },
    { title: `比较${market}和${other}的${category}法规目录`, prompt: `比较${market}和${other}的${category}法规目录` },
    { title: "最近有哪些法规变化和时间节点？", prompt: "查看法规变化时间线，最近有什么新要求" },
  ];
}

function railFor(item) {
  const status = item.status || "";
  if (status === "user_reported_done" || status === "confirmed") return "ok";
  if (status === "excluded" || status === "historical") return "muted";
  return "warn";
}

function itemKindLabel(item) {
  return {
    regulation: "法规", task: "任务", event: "日期节点", region: "市场", replay: "回放",
  }[item.kind] || "条目";
}

function itemRow(item, resultId) {
  const rail = railFor(item);
  const statusCls = rail === "warn" ? "row__status--warn" : rail === "ok" ? "row__status--ok" : "";
  const done = item.status === "user_reported_done";
  return `
    <div class="row" data-action="conv-detail" data-result-id="${esc(resultId)}"
         data-item-id="${esc(item.id)}" role="button" tabindex="0">
      <span class="row__rail row__rail--${rail}"></span>
      <span class="row__body">
        <span class="row__top"><span class="type-chip">${esc(item.group || itemKindLabel(item))}</span></span>
        <span class="row__title">${esc(item.title)}</span>
        <span class="row__sub">${esc(item.summary || "")}</span>
        <span class="row__status ${statusCls}"><i></i>${esc(item.status_label || item.status || "")}</span>
      </span>
      <span class="row__end">
        ${item.can_complete
          ? `<button class="chip" type="button" data-action="conv-complete"
                     data-result-id="${esc(resultId)}" data-item-id="${esc(item.id)}">${done ? "撤回完成" : "标记完成"}</button>`
          : ic("chevron")}
      </span>
    </div>`;
}

function groupedItems(items, resultId) {
  const groups = new Map();
  items.forEach((item) => {
    const key = item.group || itemKindLabel(item);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(item);
  });
  return [...groups.entries()].map(([group, rows]) => `
    <div class="section-head"><b>${esc(group)}</b><span>${rows.length} 条</span></div>
    <div class="list">${rows.map((item) => itemRow(item, resultId)).join("")}</div>`).join("");
}

function itemsBlock(result) {
  const items = result.items || [];
  if (!items.length) return "";
  if (result.kind === "journey") {
    return items.map((stage) => {
      const tasks = stage.details?.tasks || [];
      return `
        <div class="section-head"><b>${esc(stage.title)}</b><span>${tasks.length} 项</span></div>
        ${stage.summary ? `<p class="fine" style="margin:-2px 0 8px">${esc(stage.summary)}</p>` : ""}
        <div class="list">${tasks.length
          ? tasks.map((task) => itemRow(task, result.id)).join("")
          : '<div class="row"><span class="row__rail"></span><span class="row__body"><span class="row__sub">当前阶段没有可展示的任务。</span></span></div>'}</div>`;
    }).join("");
  }
  if (items.some((item) => item.kind === "region")) {
    return items.map((region) => {
      const records = region.details?.items || [];
      return `
        <div class="section-head"><b>${esc(region.title)}</b><span>${records.length} 条</span></div>
        ${region.summary ? `<p class="fine" style="margin:-2px 0 8px">${esc(region.summary)}</p>` : ""}
        <div class="list">${records.length
          ? records.map((item) => itemRow(item, result.id)).join("")
          : '<div class="row"><span class="row__rail"></span><span class="row__body"><span class="row__sub">该市场没有条目。</span></span></div>'}</div>`;
    }).join("");
  }
  return groupedItems(items, result.id);
}

function priorityBlock(result) {
  const actions = result.next_actions || [];
  if (!actions.length) return "";
  return `
    <section class="priority" aria-labelledby="conv-priority-${esc(result.id)}">
      <div class="priority__head"><b id="conv-priority-${esc(result.id)}">现在先做</b><span>按前置依赖排序</span></div>
      ${actions.map((action, index) => `
        <div class="priority__item" data-action="conv-detail" data-result-id="${esc(result.id)}"
             data-item-id="${esc(action.task_id)}" role="button" tabindex="0">
          <span class="priority__no">${index + 1}</span>
          <span class="priority__text">${esc(action.title)}<small>${esc(action.reason || "")}</small></span>
        </div>`).join("")}
    </section>`;
}

function gapsBlock(result) {
  const gaps = result.gaps || [];
  if (!gaps.length) return "";
  return `
    <details class="boundary">
      <summary><span>资料边界与待确认事项</span>${ic("chevron")}</summary>
      <div class="boundary__body">${gaps.map((gap) => `<p>${esc(gap)}</p>`).join("")}</div>
    </details>`;
}

function choiceButtons(result) {
  const buttons = [];
  (result.options || []).forEach((option) => {
    if (!option || !option.label) return;
    if (option.action) {
      buttons.push(`<button class="chip" data-action="conv-action" data-action-name="${esc(option.action)}">${esc(option.label)}</button>`);
    } else {
      buttons.push(`<button class="chip" data-action="conv-option" data-text="${esc(option.text || option.label)}">${esc(option.label)}</button>`);
    }
  });
  (result.follow_up || []).forEach((follow) => {
    (follow.options || []).forEach((option) => {
      buttons.push(`<button class="chip" data-action="conv-option" data-text="${esc(option.text || option.label)}">${esc(option.label)}</button>`);
    });
  });
  (result.actions || []).forEach((action) => {
    if (!action || !action.label) return;
    buttons.push(`<button class="chip" data-action="conv-action" data-action-name="${esc(action.action)}">${esc(action.label)}</button>`);
  });
  return buttons.length ? `<div class="choice-row">${buttons.join("")}</div>` : "";
}

function followUpBlock(result) {
  const follow = (result.follow_up || [])[0];
  if (!follow) return "";
  return `
    <div class="sheet__section">
      <p><b>${esc(follow.question)}</b></p>
      ${follow.note ? `<p class="fine">${esc(follow.note)}</p>` : ""}
    </div>`;
}

function exportBlock(result) {
  if (!BUSINESS_KINDS.has(result.kind)) return "";
  return `<div class="foot-actions" style="margin-top:10px">
    <button class="btn btn--ghost" data-action="conv-export" data-result-id="${esc(result.id)}">
      ${ic("download")}导出当前结果
    </button>
  </div>`;
}

function resultCard(result) {
  if (!result) return "";
  const cutoff = result.data_version?.cutoff || "";
  return `
    <section class="conv-result" data-result-id="${esc(result.id)}" style="margin-top:8px">
      ${priorityBlock(result)}
      ${itemsBlock(result)}
      ${gapsBlock(result)}
      ${followUpBlock(result)}
      ${choiceButtons(result)}
      ${exportBlock(result)}
      ${cutoff ? `<p class="fine" style="margin-top:8px">数据截止 ${esc(cutoff)} · ${esc(result.title || "")}</p>` : ""}
    </section>`;
}

export function assistantWelcomeView(state) {
  return `
      <section class="home">
        <div class="radar-hero" aria-hidden="true"><div class="radar-avatar">合</div></div>
        <h1>我是合规雷达</h1>
        <p class="home__lead">告诉我你卖什么、卖到哪里。<br>我帮你查适用法规、看关键日期、列出下一步。</p>

        <div class="reco-label">可以这样开始</div>
        <div class="reco-list">
          ${startSuggestions().map(x => `
            <button class="reco ${x.lead ? "reco--lead" : ""}" data-action="prompt" data-prompt="${esc(x.prompt)}">
              <span>${esc(x.title)}</span>${ic("chevron")}
            </button>`).join("")}
        </div>

        <p class="home__note">我不知道的会先问你，不会替你猜产品条件。<br>教程在「我的」里。</p>
      </section>`;
}

function messageHtml(message) {
  if (message.role === "user") {
    return `
      <div class="msg msg--me">
        <div class="msg__avatar">我</div>
        <div class="msg__col"><div class="bubble">${esc(message.content || "")}</div></div>
      </div>`;
  }
  const result = message.result_id ? findResult(message.result_id) : null;
  return `
    <div class="msg">
      <div class="msg__avatar">合</div>
      <div class="msg__col">
        <div class="bubble">${esc(message.content || "")}</div>
        <div class="msg__actions"><button data-action="copy">复制</button> · <button data-action="regenerate">重新生成</button></div>
        ${resultCard(result)}
      </div>
    </div>`;
}

function pendingHtml() {
  if (conv.pending && conv.pending.text) {
    return `
      <div class="msg msg--me">
        <div class="msg__avatar">我</div>
        <div class="msg__col"><div class="bubble">${esc(conv.pending.text)}</div></div>
      </div>`;
  }
  return "";
}

export function chatView(state) {
  const messages = conv.session?.messages || [];
  return `
      <div class="chat" id="chatScroll">
        ${messages.map(messageHtml).join("")}
        ${pendingHtml()}
        ${conv.error ? `
          <div class="msg">
            <div class="msg__avatar">合</div>
            <div class="msg__col"><div class="bubble">${esc(conv.error)}</div></div>
          </div>` : ""}
        ${conv.loading ? `
          <div class="msg">
            <div class="msg__avatar">合</div>
            <div class="msg__col"><div class="bubble"><span class="typing"><i></i><i></i><i></i></span></div></div>
          </div>` : ""}
      </div>`;
}

export function render(state) {
  const hasMessages = Boolean(conv.session?.messages?.length) || Boolean(conv.pending) || conv.loading;
  return hasMessages ? chatView(state) : assistantWelcomeView(state);
}

export async function send(text, action = null) {
  if (conv.loading) {
    showToast("正在处理上一条，请稍候");
    return;
  }
  const value = String(text || "").trim();
  if (!value && !action) {
    showToast("先写一句你的产品、市场和问题");
    const ta = document.querySelector(".composer textarea");
    if (ta) ta.focus();
    return;
  }
  state.chatStarted = true;
  if (value) state.messages.push({ role: "user", text: value });
  state.typing = true;
  state.choices = [];
  if (state.route !== "assistant") go("assistant");
  appRender();
  await conversationSend(value, action);
  state.typing = false;
  appRender();
}

export function choose(value) {
  send(value);
}

export async function completeTask(resultId, itemId) {
  const result = await conversationComplete(resultId, itemId);
  if (conv.error) {
    showToast(conv.error);
    conv.error = "";
  } else {
    showToast("已记录你的自述进度 · 未核验材料有效性");
  }
  appRender();
  return result;
}

export async function exportResult(resultId) {
  try {
    await conversationExport(resultId);
    showToast("导出已开始");
  } catch (error) {
    showToast(error.message);
  }
}

export function regenerate() {
  const action = conv.session?.last_action;
  if (!action) {
    showToast("还没有可重新生成的结果");
    return;
  }
  send("", action);
}

export function newChat() {
  conversationReset();
  state.chatStarted = false;
  state.messages = [];
  state.typing = false;
  state.choices = [];
  state.filter = "全部";
  go("assistant");
  appRender();
}
