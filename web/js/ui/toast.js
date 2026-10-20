// web/js/ui/toast.js —— 搬运自 prototype.html:2147-2152。
// 增量：导出；DOM 句柄改为函数内查找；计时器由函数属性 showToast._t 改为模块内 let。
let timer = null;
  export function showToast(text) {
    const toast = document.getElementById("toast");
    toast.textContent = text;
    toast.classList.add("is-on");
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => toast.classList.remove("is-on"), 2400);
  }
