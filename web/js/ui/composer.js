// 搬运自 prototype.html:1946-1967, 2335-2348。函数体逐字未动。
import { esc } from "../dom.js";
import { ic } from "../icons.js";
import { conv } from "../conversation.js";

  export function composerDock(state) {
    const inChat = state.messages.length > 0 || Boolean(conv.session?.messages?.length);
    const strip = inChat
      ? `<div class="quickbar">
          ${[["⚖️", "欧美对比", "比较欧盟和美国的儿童玩具法规目录"],
             ["🗓️", "时间线", "查看法规变化时间线，最近有什么新要求"],
             ["🌍", "多市场", "多个市场汇总，一次看清主要差异"],
             ["📄", "导出", "导出当前结果"]].map(([e, label, prompt]) => `
            <button class="chip" data-action="quick" data-label="${label}" data-prompt="${esc(prompt)}">${e} ${label}</button>`).join("")}
        </div>`
      : "";
    return `
      <div class="dock">
        ${strip}
        <form class="composer" data-form="compose">
          <button class="composer__tool" type="button" data-action="voice" aria-label="语音输入">${ic("mic")}</button>
          <textarea name="draft" rows="1" aria-label="你的问题"
            placeholder="${inChat ? "问点什么…（Enter 发送）" : "发消息或按住说话…"}"></textarea>
          <button class="composer__send" type="submit" aria-label="发送">${ic("send")}</button>
        </form>
      </div>`;
  }

  export function bindComposer(onSend) {
    const ta = document.querySelector(".composer textarea");
    if (!ta) return;
    ta.addEventListener("input", () => {
      ta.style.height = "auto";
      ta.style.height = Math.min(ta.scrollHeight, 116) + "px";
    });
    ta.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        onSend(ta.value);
      }
    });
    const form = document.querySelector('form[data-form="compose"]');
    if (!form) return;
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const ta = form.querySelector("textarea");
      onSend(ta ? ta.value : "");
      if (ta) ta.value = "";
    });
  }
