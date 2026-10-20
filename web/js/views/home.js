// 搬运自 prototype.html:1295-1372。函数体逐字未动，仅补头部导入与 export；
// 唯一剔除：1372 行末尾的原型演示开关 button（data-action="toggle-freshness" 那个）。
import { esc } from "../dom.js";
import { ic } from "../icons.js";
import { ITEMS, TOOL_PAGES, FRESH_ITEMS, PRIORITIES, RESULT_ITEMS } from "../sample.js";
import { rowHtml, filteredFresh, filteredItems } from "../render.js";

export function homeView(state) {
    return `
      <section class="wb-head">
        <div class="wb-date">10 月 19 日 · 儿童玩具 / 德国 / 亚马逊</div>
        <h1>最近检查</h1>
        <div class="wb-context">
          <div class="context">
            <span>儿童玩具</span><span>德国</span><span>亚马逊</span><span>不带电</span>
          </div>
          <button class="wb-edit" data-action="sheet" data-sheet="conditions">修改</button>
        </div>
      </section>

      <section class="fresh-card">
        <div class="fresh-card__head">
          <div class="fresh-card__title">法规时效 <span class="monitor-pill"><i></i>监控中</span></div>
          <div class="fresh-card__time">今天 09:00</div>
        </div>
        <div class="fresh-card__sub">86 条官方链接 · 数据截止 10-19 · 每天 09:00 / 21:00 自动核验</div>

        <div class="fresh-counts">
          <div class="fresh-count"><b>86</b><span>核验链接</span></div>
          <div class="fresh-count"><b>84</b><span>可访问</span></div>
          <div class="fresh-count fresh-count--warn"><b>2</b><span>待复核</span></div>
          <div class="fresh-count"><b>0</b><span>内容更新</span></div>
        </div>

        <div class="fresh-list">
          <button class="fresh-item" data-action="nav" data-to="freshness">
            <span class="fresh-item__dot fresh-item__dot--warn"></span>
            <span class="fresh-item__copy">
              <b>2 条官方链接待复核</b>
              <span>本机网络未连通，不判死链；下次核验会重试</span>
            </span>
            <span class="fresh-item__end">查看</span>
          </button>
          <button class="fresh-item" data-action="nav" data-to="freshness">
            <span class="fresh-item__dot"></span>
            <span class="fresh-item__copy">
              <b>0 条内容有更新</b>
              <span>与上次核验的页面哈希一致</span>
            </span>
            <span class="fresh-item__end">查看</span>
          </button>
        </div>

        <div class="fresh-foot">
          <span>结果只读 · 无需手动操作</span>
          <a href="#/freshness">查看检查记录 →</a>
        </div>
        <p class="fresh-note">检查只核对官方链接状态与内容哈希，不等于法规条文变更；条文级变化仍以人工核对为准。</p>
      </section>

      <div class="section-head"><b>继续上次</b><span>今天 14:32</span></div>
      <button class="resume-card" data-action="open-result" data-from="home">
        <span class="resume-card__icon">${ic("doc")}</span>
        <span class="resume-card__copy">
          <b>德国市场行动清单</b>
          <span>3 项优先 · 7 项待办 · 数据截止 10-19</span>
        </span>
        <span class="resume-card__end">继续 →</span>
      </button>

      <div class="section-head"><b>上线进度</b><span>2 / 6 阶段</span></div>
      <button class="progress-card" data-action="nav" data-to="action/journey" style="width:100%;text-align:left">
        <div class="progress-bar"><i style="width:33%"></i></div>
        <div class="progress-meta"><span>选品、测试已完成</span><span>下一步：标签与说明书</span></div>
        <div class="progress-steps">
          <span>选品</span><span>测试</span><span class="is-off">标签</span><span class="is-off">文件</span><span class="is-off">供应链</span><span class="is-off">切换</span>
        </div>
      </button>

      <div class="quick-actions">
        <button data-action="nav" data-to="regulations">${ic("book")}查法规</button>
        <button data-action="nav" data-to="action">${ic("flag")}看行动</button>
        <button data-action="nav" data-to="profile/tutorial">${ic("help")}看教程</button>
      </div>

    `;
}
