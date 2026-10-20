// 上线进度：用户自述完成项，保存在浏览器本地。
// 只用 readiness（M7）的阶段/动作结构算「完成了几个阶段」；标记完成不等于合规。
const KEY = "cr_done_v1";
const LIMIT = 500;

function read() {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(KEY) || "{}");
    return {
      ids: Array.isArray(parsed.ids) ? parsed.ids : [],
      titles: Array.isArray(parsed.titles) ? parsed.titles : [],
    };
  } catch (error) {
    return { ids: [], titles: [] };
  }
}

function write(state) {
  try {
    window.localStorage.setItem(KEY, JSON.stringify({
      ids: state.ids.slice(-LIMIT),
      titles: state.titles.slice(-LIMIT),
    }));
  } catch (error) {
    // 隐私模式或配额不足时静默降级，不影响当前页面。
  }
}

export function doneSet() {
  const state = read();
  return {
    ids: new Set(state.ids),
    titles: new Set(state.titles),
  };
}

export function markDone(id, title) {
  const state = read();
  const ids = new Set(state.ids);
  const titles = new Set(state.titles);
  if (id) ids.add(id);
  if (title) titles.add(title);
  write({ ids: [...ids], titles: [...titles] });
}

export function isDone(action, done = doneSet()) {
  if (!action) return false;
  return (action.id && done.ids.has(action.id))
    || (action.title && done.titles.has(action.title));
}

/**
 * 返回 { total, done, phases, next, percent, empty, loaded }。
 * 分母只算「当前有适用任务」的阶段；空阶段仍返回给前端画完整六阶段路线。
 */
export function phaseProgress(region) {
  const phases = (region && region.phases) || [];
  if (!phases.length) {
    return { total: 6, done: 0, phases: [], next: null, percent: 0, empty: 0, loaded: false };
  }
  const done = doneSet();
  const applicable = phases.filter((phase) => (phase.actions || []).length > 0);
  const completed = applicable.filter((phase) => phase.actions.every((action) => isDone(action, done)));
  const next = applicable.find((phase) => !completed.includes(phase)) || null;
  return {
    total: applicable.length,
    done: completed.length,
    phases,
    next,
    percent: applicable.length ? Math.round((completed.length / applicable.length) * 100) : 0,
    empty: phases.length - applicable.length,
    loaded: true,
  };
}
