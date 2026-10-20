// 搬运自 prototype.html:1598-1625。函数体逐字未动，仅补头部导入与 export。
import { ic } from "../icons.js";
import { toolCard } from "../render.js";
import { toolData } from "../data.js";

  /* ================= 行动 ================= */
  export function actionView(state) {
    const todo = toolData("todo");
    const readiness = toolData("readiness");
    const todoCount = todo ? todo.actions.length : 3;
    const readinessCount = readiness ? readiness.total_actions : 0;
    return `
      <div class="page-head">
        <h1>行动</h1>
        <p>把法规变成任务、上线计划和市场对比。要做的事和要看清的市场差异都在这里。</p>
      </div>

      <div class="section-head"><b>要做的事</b><span>${todoCount + readinessCount} 项</span></div>
      <div class="tool-grid">
        ${toolCard("action", "todo", "list", "合规待办", `按紧迫度整理下一步${todo ? ` · ${todoCount} 项` : ""}`)}
        ${toolCard("action", "readiness", "flag", "上线准备", `按阶段和责任排任务${readiness ? ` · ${readinessCount} 项` : ""}`)}
        <button class="tool tool--wide" data-action="open-tool" data-group="action" data-tool="journey">
          <span class="tool__icon">${ic("layers")}</span>
          <span style="flex:1">
            <b>德国亚马逊六阶段路线</b><br>
            <span>选品 → 测试 → 标签 → 文件 → 供应链 → 切换复核</span>
          </span>
          ${ic("chevron")}
        </button>
      </div>

      <div class="section-head"><b>看市场</b><span>2 项</span></div>
      <div class="tool-grid">
        ${toolCard("action", "compare", "compare", "区域对比", "欧盟和美国逐条对照")}
        ${toolCard("action", "multi", "globe", "多市场汇总", "分区域查看法规")}
      </div>`;
  }
