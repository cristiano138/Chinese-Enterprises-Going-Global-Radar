// 搬运自 prototype.html:1250-1267, 1376-1422。函数体逐字未动。
import { esc } from "../dom.js";
import { ic } from "../icons.js";
import { START } from "../sample.js";
import { store } from "../store.js";
import { go } from "../router.js";
import { showToast } from "../ui/toast.js";
import { render as appRender } from "../main.js";
import { cache, route as routeQuery, conditions } from "../data.js";

const state = store.state;
let requestSeq = 0;

function chatContext() {
  return state.messages
    .filter((message) => message.role === "user")
    .slice(-4)
    .map((message) => message.text)
    .join("；");
}

function choicesFor(result) {
  if (!result) return [];
  if (result.reason === "partial_品类" || result.reason === "bad_category") {
    return ["儿童玩具", "电子电器", "纺织服装", "美妆个护", "食品接触材料"];
  }
  if (result.reason === "partial_市场" || result.reason === "bad_market") {
    return ["欧盟", "美国"];
  }
  return [];
}

async function reply(value) {
  const seq = ++requestSeq;
  const context = chatContext();
  let result = null;
  let error = "";
  try {
    result = await routeQuery(value, context);
  } catch (caught) {
    error = caught.message;
  }
  if (seq !== requestSeq) return;   // 新消息已发出，丢弃过期回复
  state.typing = false;
  if (error) {
    state.messages.push({
      role: "assistant",
      text: `暂时无法完成识别：${error}`,
      meta: "请求未完成 · 请确认服务仍在运行",
    });
  } else {
    state.messages.push({
      role: "assistant",
      text: result.reply,
      meta: result.ok
        ? `依据：法规库 · ${result.category} / ${result.market} · 来源 ${result.route_via || "本地词典解析"}`
        : `未完成识别 · ${result.route_via || ""}`,
      deliverable: Boolean(result.ok),
    });
    state.choices = choicesFor(result);
    if (result.ok) {
      conditions.category = result.category || conditions.category;
      conditions.market = result.market || conditions.market;
    }
  }
  appRender();
}

  export function assistantWelcomeView(state) {
    return `
      <section class="home">
        <div class="radar-hero" aria-hidden="true"><div class="radar-avatar">合</div></div>
        <h1>我是合规雷达</h1>
        <p class="home__lead">告诉我你卖什么、卖到哪里。<br>我帮你查适用法规、看关键日期、列出下一步。</p>

        <div class="reco-label">可以这样开始</div>
        <div class="reco-list">
          ${START.map(x => `
            <button class="reco ${x.lead ? "reco--lead" : ""}" data-action="prompt" data-prompt="${esc(x.prompt)}">
              <span>${esc(x.title)}</span>${ic("chevron")}
            </button>`).join("")}
        </div>

        <p class="home__note">我不知道的会先问你，不会替你猜产品条件。<br>教程在「我的」里。</p>
      </section>`;
  }

  function messageHtml(m, index) {
    if (m.role === "user") {
      return `
        <div class="msg msg--me">
          <div class="msg__avatar">我</div>
          <div class="msg__col">
            <div class="bubble">${esc(m.text)}</div>
            <div class="msg__actions">15:59</div>
          </div>
        </div>`;
    }
    const deliverable = m.deliverable ? `
      <div class="deliverable">
        <div class="deliverable__eyebrow">已生成 · 行动清单</div>
        <div class="deliverable__title">${esc(conditions.category)} · ${esc(conditions.market)} 行动清单</div>
        <div class="deliverable__meta">按紧迫度整理 · 数据截止 ${esc((cache.boot && cache.boot.data_cutoff) || "—")}</div>
        <button class="deliverable__btn" data-action="open-result">
          <span>查看完整结果</span>${ic("arrow")}
        </button>
      </div>` : "";
    return `
      <div class="msg">
        <div class="msg__avatar">合</div>
        <div class="msg__col">
          <div class="bubble">${esc(m.text)}</div>
          ${m.meta ? `<div class="msg__meta">${ic("shield")}${esc(m.meta)}</div>` : ""}
          ${m.deliverable ? "" : `<div class="msg__actions">15:59 · <button data-action="copy">复制</button> · <button data-action="regenerate">重答</button></div>`}
        </div>
      </div>
      ${deliverable}`;
  }

  export function chatView(state) {
    return `
      <div class="chat" id="chatScroll">
        ${state.messages.map(messageHtml).join("")}
        ${state.choices.length ? `
          <div class="choice-row">
            ${state.choices.map(c => `<button class="chip" data-action="choice" data-choice="${esc(c)}">${esc(c)}</button>`).join("")}
          </div>` : ""}
        ${state.typing ? `
          <div class="msg">
            <div class="msg__avatar">合</div>
            <div class="msg__col"><div class="bubble"><span class="typing"><i></i><i></i><i></i></span></div></div>
          </div>` : ""}
      </div>`;
  }

/** 与原型 2029 行一致：有消息则对话页，否则欢迎页。 */
export function render(state) {
  return state.messages.length ? chatView(state) : assistantWelcomeView(state);
}

  export function send(text) {
    const value = String(text || "").trim();
    if (!value && !state.messages.length) {
      showToast("先写一句你的产品、市场和问题");
      const ta = document.querySelector('.composer textarea');
      if (ta) ta.focus();
      return;
    }
    if (!value) return;

    state.chatStarted = true;
    state.messages.push({ role: "user", text: value });
    state.choices = [];
    state.typing = true;
    if (state.route !== "assistant") go("assistant");
    appRender();
    reply(value);
  }

  export function choose(value) {
    send(value);
  }

  export function newChat() {
    requestSeq += 1;                 // 让在途回复失效
    state.chatStarted = false;
    state.messages = [];
    state.typing = false;
    state.choices = [];
    state.filter = "全部";
    go("assistant");
    appRender();
  }
