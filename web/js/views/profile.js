// 搬运自 prototype.html:1880-1943。函数体逐字未动，仅补 export 与头部导入。
import { ic } from "../icons.js";

  /* ================= 我的 ================= */
  export function profileView(state) {
    return `
      <div class="profile">
        <div class="profile__hero">
          <div class="profile__mark">${ic("radar")}</div>
          <div>
            <h1>合规雷达</h1>
            <p>出海合规助手 · 构建 2026.10.19-chat1.6</p>
          </div>
        </div>

        <div class="menu-group">
          <button class="menu-row" data-action="nav" data-to="profile/tutorial">
            <span class="menu-row__icon">${ic("help")}</span>
            <span class="menu-row__copy"><b>教程 · 企业用户使用指引</b><span>3 分钟读完，照着走一遍</span></span>
            <span class="menu-row__end">打开${ic("chevron")}</span>
          </button>
        </div>

        <div class="menu-group">
          <button class="menu-row" data-action="sheet" data-sheet="history">
            <span class="menu-row__icon">${ic("history")}</span>
            <span class="menu-row__copy"><b>历史结果</b><span>保留当时查询条件</span></span>
            <span class="menu-row__end">3 份${ic("chevron")}</span>
          </button>
          <button class="menu-row" data-action="sheet" data-sheet="conditions">
            <span class="menu-row__icon">${ic("settings")}</span>
            <span class="menu-row__copy"><b>当前查询条件</b><span>儿童玩具 · 德国 · 亚马逊</span></span>
            <span class="menu-row__end">${ic("chevron")}</span>
          </button>
        </div>

        <div class="menu-group">
          <button class="menu-row" data-action="sheet" data-sheet="voice">
            <span class="menu-row__icon">${ic("mic")}</span>
            <span class="menu-row__copy"><b>语音输入</b><span>转写后先确认，再发送</span></span>
            <span class="menu-row__end">已启用${ic("chevron")}</span>
          </button>
          <button class="menu-row" data-action="sheet" data-sheet="coverage">
            <span class="menu-row__icon">${ic("layers")}</span>
            <span class="menu-row__copy"><b>数据覆盖与版本</b><span>86 部法规 · 5 类商品</span></span>
            <span class="menu-row__end">${ic("chevron")}</span>
          </button>
        </div>

        <div class="menu-group">
          <button class="menu-row" data-action="sheet" data-sheet="privacy">
            <span class="menu-row__icon">${ic("lock")}</span>
            <span class="menu-row__copy"><b>隐私与使用边界</b><span>数据保存、模型调用与录音说明</span></span>
            <span class="menu-row__end">${ic("chevron")}</span>
          </button>
          <button class="menu-row" data-action="sheet" data-sheet="about">
            <span class="menu-row__icon">${ic("help")}</span>
            <span class="menu-row__copy"><b>关于这个助手</b><span>版本、来源与免责声明</span></span>
            <span class="menu-row__end">${ic("chevron")}</span>
          </button>
        </div>

        <p class="fine" style="text-align:center;margin-top:18px">
          有来源，有边界。帮助你准备下一步，不构成法律意见。
        </p>
      </div>`;
  }
