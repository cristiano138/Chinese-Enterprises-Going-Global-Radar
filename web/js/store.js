// 状态：字段逐字取自 prototype.html:1151-1165。
// 包装成 store 是为了让视图改条件时能作废旧结果锚点（见 setConditions）。
const initial = () => ({
  route: "home",
  chatStarted: false,
  messages: [],
  typing: false,
  choices: [],
  filter: "全部",
  freshFilter: "全部",
  tool: null,
  toolGroup: null,
  resultFrom: "assistant",
  searchDone: false,
  query: "",
  hasFreshness: true,
});

export const store = {
  state: initial(),
  _subs: new Set(),

  set(patch) {
    Object.assign(this.state, patch);
    this._subs.forEach((fn) => fn(this.state));
  },

  /** 换查询条件时同时作废旧结果锚点，避免旧结果被当成新条件的结果。 */
  setConditions(patch) {
    this.set({ ...patch, resultFrom: "assistant" });
  },

  reset() {
    this.state = initial();
    this._subs.forEach((fn) => fn(this.state));
  },

  subscribe(fn) {
    this._subs.add(fn);
    return () => this._subs.delete(fn);
  },
};
