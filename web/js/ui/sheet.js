// web/js/ui/sheet.js —— 搬运自 prototype.html:2322-2333。
// 增量：导出；DOM 句柄改为函数内查找（不在导入期取）。
  export function openSheet(html) {
    const sheet = document.getElementById("sheet");
    const backdrop = document.getElementById("backdrop");
    sheet.innerHTML = html;
    backdrop.classList.add("is-on");
    sheet.classList.add("is-on");
    sheet.setAttribute("aria-hidden", "false");
  }
  export function closeSheet() {
    const sheet = document.getElementById("sheet");
    const backdrop = document.getElementById("backdrop");
    backdrop.classList.remove("is-on");
    sheet.classList.remove("is-on");
    sheet.setAttribute("aria-hidden", "true");
    window.setTimeout(() => { if (!sheet.classList.contains("is-on")) sheet.innerHTML = ""; }, 300);
  }
