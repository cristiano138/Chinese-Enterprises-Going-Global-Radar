// 搬运自 prototype.html:1250-1267, 1376-1422。函数体逐字未动。
import { esc } from "../dom.js";
import { ic } from "../icons.js";
import { START } from "../sample.js";
import { store } from "../store.js";
import { go } from "../router.js";
import { showToast } from "../ui/toast.js";
import { render as appRender } from "../main.js";

const state = store.state;
let replyTimer = null;

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
        <div class="deliverable__title">德国市场行动清单</div>
        <div class="deliverable__meta">3 项优先 · 7 项待办 · 数据截止 10-19</div>
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

    // M1：壳与路由阶段，此处用示例回复；M2 换成 POST /api/route 的返回。
    replyTimer = window.setTimeout(() => {
      state.typing = false;
      const asked = state.messages.filter(m => m.role === "assistant").length;
      if (asked === 0) {
        state.messages.push({
          role: "assistant",
          text: "先确认一个条件：这个产品带电吗？这会影响是否还要看 WEEE 和电池法规。",
          meta: "依据：法规库 86 部 · 结论来自核对语料"
        });
        state.choices = ["不带电", "带电", "暂不确定"];
      } else {
        state.messages.push({
          role: "assistant",
          text: "好，条件记下了。先按不带电处理，给你一份可以马上开始的清单。",
          meta: "依据：法规库 86 部 · 数据截止 2026-10-19",
          deliverable: true
        });
      }
      appRender();
    }, 720);
  }

  export function choose(value) {
    state.messages.push({ role: "user", text: value });
    state.choices = [];
    state.typing = true;
    appRender();
    replyTimer = window.setTimeout(() => {
      state.typing = false;
      state.messages.push({
        role: "assistant",
        text: "好，条件记下了。先按" + value + "处理，给你一份可以马上开始的清单。",
        meta: "依据：法规库 86 部 · 数据截止 2026-10-19",
        deliverable: true
      });
      appRender();
    }, 720);
  }

  export function newChat() {
    // 模块化增量：取消待发的演示回复计时器（与 Task 5 的 toast 计时器处理一致）。
    if (replyTimer) { clearTimeout(replyTimer); replyTimer = null; }
    state.chatStarted = false;
    state.messages = [];
    state.typing = false;
    state.choices = [];
    state.filter = "全部";
    go("assistant");
    appRender();
  }
