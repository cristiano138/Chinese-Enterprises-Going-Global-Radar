// 首页工作台：法规时效监控台。数据来自 /api/freshness 与 /api/bootstrap。
// 结构、类名沿用原型（160-...）；拿不到后端数据时保留可读的兜底文案，不白屏。
import { ic } from "../icons.js";
import { cache, conditions, toolData } from "../data.js";
import { latestHistory, timeLabel as historyTime } from "../history.js";
import { doneSet, isDone, phaseProgress } from "../progress.js";

const pad = (n) => String(n).padStart(2, "0");

function timeLabel(value) {
  if (!value) return "--:--";
  const text = String(value);
  const match = text.match(/(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/);
  if (!match) return text;
  const now = new Date();
  const today = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
  const stamp = `${match[1]}${match[2]}${match[3]}`;
  const day = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}`;
  const clock = `${match[4]}:${match[5]}`;
  return stamp === day ? `今天 ${clock}` : `${match[2]}-${match[3]} ${clock}`;
}

function dateLabel(value) {
  const match = String(value || "").match(/(\d{4})-(\d{2})-(\d{2})/);
  return match ? `${Number(match[2])} 月 ${Number(match[3])} 日` : "";
}

export function homeView(state) {
  const fresh = cache.freshness && cache.freshness.available ? cache.freshness : null;
  const boot = cache.boot || {};
  const counts = fresh ? fresh.counts : {
    total: 0, http_ok: 0, changed: 0, pending: 0,
  };
  const total = counts.total || 0;
  const reachable = counts.http_ok || counts.content_verified || 0;
  const pending = counts.pending || 0;
  const changed = counts.changed || 0;
  const checkedAt = fresh ? timeLabel(fresh.checked_at) : "尚未检查";
  const cutoff = boot.data_cutoff || "";
  const error = !fresh && cache.errors.freshness;

  // 上线进度：按 readiness 的 6 个阶段 + 用户自述完成项计算。
  const readiness = toolData("readiness");
  const region = readiness
    ? (readiness.regions.find((item) => item.market === conditions.market) || readiness.regions[0])
    : null;
  const progress = phaseProgress(region);
  const done = doneSet();
  const steps = progress.phases.length
    ? progress.phases.map((phase) => {
        const complete = phase.actions.length > 0
          && phase.actions.every((action) => isDone(action, done));
        return `<span class="${complete ? "" : "is-off"}">${escText(phase.name)}</span>`;
      }).join("")
    : `<span>选品</span><span>测试</span><span class="is-off">标签</span><span class="is-off">文件</span><span class="is-off">供应链</span><span class="is-off">切换</span>`;
  const nextLabel = progress.next ? `下一步：${progress.next.name}` : (progress.loaded ? "所有阶段已完成" : "下一步：标签与说明书");
  const last = latestHistory();

  const pendingRow = pending > 0
    ? `<button class="fresh-item" data-action="nav" data-to="freshness">
         <span class="fresh-item__dot fresh-item__dot--warn"></span>
         <span class="fresh-item__copy">
           <b>${pending} 条官方链接待复核</b>
           <span>${fresh && fresh.proxy && fresh.proxy.fallback
             ? "本次检查走直连；代理不可用不判死链，下次核验会重试"
             : "本机网络或官方站点异常，不判死链；下次核验会重试"}</span>
         </span>
         <span class="fresh-item__end">查看</span>
       </button>`
    : `<button class="fresh-item" data-action="nav" data-to="freshness">
         <span class="fresh-item__dot"></span>
         <span class="fresh-item__copy">
           <b>${total} 条官方链接全部可访问</b>
           <span>HTTP 核验通过；内容哈希用于判断是否更新</span>
         </span>
         <span class="fresh-item__end">查看</span>
       </button>`;

  const changedRow = changed > 0
    ? `<button class="fresh-item" data-action="nav" data-to="freshness">
         <span class="fresh-item__dot fresh-item__dot--warn"></span>
         <span class="fresh-item__copy">
           <b>${changed} 条内容有更新</b>
           <span>页面内容哈希与上次核验不一致，需人工复核</span>
         </span>
         <span class="fresh-item__end">查看</span>
       </button>`
    : `<button class="fresh-item" data-action="nav" data-to="freshness">
         <span class="fresh-item__dot"></span>
         <span class="fresh-item__copy">
           <b>0 条内容有更新</b>
           <span>与上次核验的页面哈希一致</span>
         </span>
         <span class="fresh-item__end">查看</span>
       </button>`;

  return `
      <section class="wb-head">
        <div class="wb-date">${todayLabel()} · ${escText(conditions.category)} / ${escText(conditions.market)} / ${escText(conditions.platform)}</div>
        <h1>最近检查</h1>
        <div class="wb-context">
          <div class="context">
            <span>${escText(conditions.category)}</span><span>${escText(conditions.market)}</span><span>${escText(conditions.platform)}</span><span>${escText(conditions.powered)}</span>
          </div>
          <button class="wb-edit" data-action="sheet" data-sheet="conditions">修改</button>
        </div>
      </section>

      <section class="fresh-card">
        <div class="fresh-card__head">
          <div class="fresh-card__title">法规时效 <span class="monitor-pill"><i></i>监控中</span></div>
          <div class="fresh-card__time">${checkedAt}</div>
        </div>
        <div class="fresh-card__sub">${total} 条官方链接 · 数据截止 ${escText(cutoff || "—")} · 每天 09:00 / 21:00 自动核验</div>

        <div class="fresh-counts">
          <div class="fresh-count"><b>${total}</b><span>核验链接</span></div>
          <div class="fresh-count"><b>${reachable}</b><span>可访问</span></div>
          <div class="fresh-count ${pending > 0 ? "fresh-count--warn" : ""}"><b>${pending}</b><span>待复核</span></div>
          <div class="fresh-count ${changed > 0 ? "fresh-count--warn" : ""}"><b>${changed}</b><span>内容更新</span></div>
        </div>

        <div class="fresh-list">
          ${pendingRow}
          ${changedRow}
        </div>

        <div class="fresh-foot">
          <span>结果只读 · 无需手动操作</span>
          <a href="#/freshness">查看检查记录 →</a>
        </div>
        <p class="fresh-note">检查只核对官方链接状态与内容哈希，不等于法规条文变更；条文级变化仍以人工核对为准。${error ? ` 当前未读到检查结果：${escText(error)}` : ""}</p>
      </section>

      <div class="section-head"><b>继续上次</b><span>${last ? escText(historyTime(last.ts)) : checkedAt}</span></div>
      ${last ? `
      <button class="resume-card" data-action="open-history" data-id="${escText(last.id)}">
        <span class="resume-card__icon">${ic("doc")}</span>
        <span class="resume-card__copy">
          <b>${escText(last.title)}</b>
          <span>${last.action_count} 项待办 · 当时条件 ${escText(last.category)} / ${escText(last.market)} / ${escText(last.platform || "未指定平台")}</span>
        </span>
        <span class="resume-card__end">继续 →</span>
      </button>` : `
      <button class="resume-card" data-action="open-result" data-from="home">
        <span class="resume-card__icon">${ic("doc")}</span>
        <span class="resume-card__copy">
          <b>${escText(conditions.category)} · ${escText(conditions.market)} 行动清单</b>
          <span>按紧迫度整理的合规待办 · 数据截止 ${escText(cutoff || "—")}</span>
        </span>
        <span class="resume-card__end">继续 →</span>
      </button>`}

      <div class="section-head"><b>上线进度</b><span>${progress.done} / ${progress.total} 阶段</span></div>
      <button class="progress-card" data-action="nav" data-to="action/journey" style="width:100%;text-align:left">
        <div class="progress-bar"><i style="width:${progress.percent}%"></i></div>
        <div class="progress-meta"><span>${progress.loaded ? `已完成 ${progress.done} 个含任务的阶段${progress.empty ? ` · ${progress.empty} 个阶段当前无任务` : ""}` : "等待上线准备数据"}</span><span>${escText(nextLabel)}</span></div>
        <div class="progress-steps">${steps}</div>
        <div class="progress-meta" style="margin-top:6px"><span class="fine">按你标记的完成项统计；标记完成不等于合规。</span></div>
      </button>

      <div class="quick-actions">
        <button data-action="nav" data-to="regulations">${ic("book")}查法规</button>
        <button data-action="nav" data-to="action">${ic("flag")}看行动</button>
        <button data-action="nav" data-to="profile/tutorial">${ic("help")}看教程</button>
      </div>

    `;
}

function todayLabel() {
  const now = new Date();
  return `${now.getMonth() + 1} 月 ${now.getDate()} 日`;
}

function escText(value) {
  return String(value == null ? "" : value)
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;").replaceAll("'", "&#39;");
}
