// 检查记录页：只读展示 /api/freshness 的真实核验结果。
import { esc } from "../dom.js";
import { ic } from "../icons.js";
import { cache } from "../data.js";

function timeLabel(value) {
  if (!value) return "尚未检查";
  const text = String(value);
  const match = text.match(/(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/);
  if (!match) return text;
  const now = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  const day = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}`;
  const stamp = `${match[1]}${match[2]}${match[3]}`;
  const clock = `${match[4]}:${match[5]}`;
  return stamp === day ? `今天 ${clock}` : `${match[2]}-${match[3]} ${clock}`;
}

function linkRow(item, rail) {
  return `
    <a class="row" href="${esc(item.url)}" target="_blank" rel="noreferrer">
      <span class="row__rail row__rail--${rail}"></span>
      <span class="row__body">
        <span class="row__top"><span class="type-chip type-chip--pol">${esc(item.kind || "待复核")}</span></span>
        <span class="row__title">${esc(item.title)}</span>
        <span class="row__sub">${esc(item.error || (item.http_status ? `HTTP ${item.http_status}` : "需要人工复核"))}</span>
      </span>
      <span class="row__end">${ic("external")}</span>
    </a>`;
}

export function freshnessView(state) {
  const fresh = cache.freshness && cache.freshness.available ? cache.freshness : null;
  const boot = cache.boot || {};
  const counts = fresh ? fresh.counts : { total: 0, http_ok: 0, changed: 0, pending: 0 };
  const total = counts.total || 0;
  const reachable = counts.http_ok || counts.content_verified || 0;
  const pending = counts.pending || 0;
  const changed = counts.changed || 0;
  const checkedAt = fresh ? timeLabel(fresh.checked_at) : "尚未检查";
  const cutoff = boot.data_cutoff || "—";
  const runs = fresh ? fresh.runs || [] : [];
  const pendingLinks = fresh ? fresh.pending || [] : [];
  const changedLinks = fresh ? fresh.changed || [] : [];
  const error = !fresh && cache.errors.freshness;

  const runRows = runs.length ? runs.map((run, index) => {
    const warnings = (run.link_error || 0) + (run.failed || 0);
    const rail = warnings > 0 ? "warn" : "ok";
    return `
      <div class="row">
        <span class="row__rail row__rail--${rail}"></span>
        <span class="row__body">
          <span class="row__top"><span class="type-chip ${index === 0 ? "type-chip--pol" : ""}">${timeLabel(run.checked_at)}</span></span>
          <span class="row__title">${run.total} 条 · ${run.http_ok} 可访问 · ${warnings} 待复核</span>
          <span class="row__sub">${run.changed} 条内容更新 · 耗时 ${run.duration_seconds}s · 数据截止 ${esc(cutoff)}</span>
        </span>
      </div>`;
  }).join("") : `
      <div class="row">
        <span class="row__rail"></span>
        <span class="row__body"><span class="row__sub">还没有可用的检查记录。</span></span>
      </div>`;

  const pendingBody = pendingLinks.length
    ? pendingLinks.map((item) => linkRow(item, "warn")).join("")
    : `<div class="row">
         <span class="row__rail row__rail--ok"></span>
         <span class="row__body"><span class="row__sub">本次没有待复核链接。</span></span>
       </div>`;

  const changedBody = changedLinks.length
    ? changedLinks.map((item) => linkRow(item, "warn")).join("")
    : `<div class="row">
         <span class="row__rail row__rail--ok"></span>
         <span class="row__body"><span class="row__sub">本次没有内容更新。</span></span>
       </div>`;

  return `
      <div class="page-head" style="padding-top:16px">
        <p>系统每天 09:00 / 21:00 自动核验 ${total} 条官方链接。这里显示最近一次检查和最近两次记录，结果只读，不需要手动操作。</p>
        <div class="page-head__meta mono">最近检查 ${checkedAt} · 数据截止 ${esc(cutoff)}</div>
      </div>

      <section class="fresh-card">
        <div class="fresh-card__head">
          <div class="fresh-card__title">法规时效 <span class="monitor-pill"><i></i>监控中</span></div>
          <div class="fresh-card__time">${checkedAt}</div>
        </div>
        <div class="fresh-card__sub">${total} 条官方链接 · 下一次 21:00</div>
        <div class="fresh-counts">
          <div class="fresh-count"><b>${total}</b><span>核验链接</span></div>
          <div class="fresh-count"><b>${reachable}</b><span>可访问</span></div>
          <div class="fresh-count ${pending > 0 ? "fresh-count--warn" : ""}"><b>${pending}</b><span>待复核</span></div>
          <div class="fresh-count ${changed > 0 ? "fresh-count--warn" : ""}"><b>${changed}</b><span>内容更新</span></div>
        </div>
      </section>

      <div class="section-head"><b>最近两次检查</b><span>自动核验</span></div>
      <div class="list">${runRows}</div>

      <div class="section-head"><b>待复核链接</b><span>${pending} 条 · 本次检查</span></div>
      <div class="list">${pendingBody}</div>

      <div class="section-head"><b>内容更新</b><span>${changed} 条 · 本次检查</span></div>
      <div class="list">${changedBody}</div>

      <div class="section-head"><b>检查口径</b><span>只读</span></div>
      <p class="fresh-note" style="font-size:11px">
        检查项：HTTP 状态 / Last-Modified / 内容哈希。内容哈希变化只代表页面字节变了，不等于法规条文变更；
        条文级变化仍归时间线人工核对。本机网络未连通不判死链，下一次核验会重试。
        原始日志保留在 <span class="mono">data/freshness_log.jsonl</span>。${error ? ` 当前未读到检查结果：${esc(error)}` : ""}
      </p>`;
}
