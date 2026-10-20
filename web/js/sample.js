// 搬运自 prototype.html:939-1148, 1243-1248, 1735-1747, 2187-2321。
// 增量：顶层 const → export const；并补 ic 导入（见下）。数据内容逐字未动。
// M2 接入真数据时只改本文件的取值处，视图模板不动。
import { ic } from "./icons.js";
// M2：抽屉里少数会随真实数据变化的值在这里读取后端缓存；其余仍是原型文案。
import { cache, conditions } from "./data.js";
import { historySheet } from "./history.js";

  export const ITEMS = {
    toy: {
      type: "法律法规", typeClass: "", rail: "ok",
      title: "玩具安全指令 2009/48/EC",
      sub: "CE 标识、年龄分级与警告语",
      status: "有来源 · 请核对适用性",
      why: "毛绒玩具属于玩具指令覆盖范围。投放欧盟市场前，需要满足基本安全要求、加贴 CE 标识，并保留技术文件与 EU 符合性声明。",
      source: "EUR-Lex · Directive 2009/48/EC",
      url: "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32009L0048",
      excerpt: "玩具在投放市场前应满足指令规定的基本安全要求；制造商应执行符合性评估程序并起草 EU 符合性声明。",
      version: "版本日期 2024-12-01 · 文本状态 已解析 · 定位 Article 4"
    },
    doc: {
      type: "操作建议", typeClass: "type-chip--ops", rail: "warn",
      title: "准备 EU 符合性声明（DoC）",
      sub: "技术文件里的声明与责任主体",
      status: "适用条件待确认",
      why: "DoC 需要写明制造商信息、产品识别信息、适用指令与协调标准，并由责任主体签署。若你只是贸易商，需要先确认谁承担制造商责任。",
      source: "欧盟官方指南 · Blue Guide 2022",
      url: "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:52022XC0629(03)",
      excerpt: "制造商应起草 EU 符合性声明，声明产品符合适用联盟协调立法的要求，并对声明内容负责。",
      version: "指南版本 2022 · 需结合产品具体协调标准核对"
    },
    en71: {
      type: "法律法规", typeClass: "", rail: "ok",
      title: "EN 71 玩具安全检测",
      sub: "机械物理、阻燃与迁移元素",
      status: "有来源 · 请核对报告有效期",
      why: "EN 71 系列是玩具指令的协调标准。毛绒玩具通常涉及 EN 71-1（机械物理）、EN 71-2（阻燃）和 EN 71-3（迁移元素）。检测报告需覆盖实际材料与工艺。",
      source: "CEN · EN 71 系列标准",
      url: "https://standards.cencenelec.eu/",
      excerpt: "EN 71-1 规定玩具机械与物理性能的安全要求；EN 71-3 规定特定元素的迁移限值。",
      version: "标准版本需按报告核对 · 建议确认实验室资质"
    },
    amazon: {
      type: "平台规则", typeClass: "type-chip--plat", rail: "warn",
      title: "Amazon 玩具类目审核",
      sub: "上架前提交检测报告与产品图片",
      status: "平台材料待补",
      why: "玩具类目通常需要提交检测报告、符合性声明和产品标签照片。平台审核要求可能随站点变化，需以卖家后台当时的要求为准。",
      source: "Amazon Seller Central · 玩具类目要求",
      url: "https://sellercentral.amazon.com/",
      excerpt: "部分玩具类商品在发布前需通过类目审核，并提交安全文件与标签图片。",
      version: "平台规则随时更新 · 以卖家后台为准"
    },
    label: {
      type: "操作建议", typeClass: "type-chip--ops", rail: "ok",
      title: "德国市场德语标签与警告语",
      sub: "品名、年龄、进口商信息",
      status: "有来源 · 请核对最终版面",
      why: "德国销售通常需要德语标签，包含产品名称、适用年龄、警告语、制造商或进口商名称及地址。警告语应清晰、易读、不可擦除。",
      source: "欧盟玩具安全指令 · 标签条款",
      url: "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32009L0048",
      excerpt: "玩具应附有清晰可辨的警告语；警告语应使用消费者所在成员国的官方语言。",
      version: "需在设计定稿后逐项核对"
    },
    lucid: {
      type: "法律法规", typeClass: "", rail: "warn",
      title: "德国包装登记（LUCID）",
      sub: "包装责任与回收系统登记",
      status: "待确认是否适用",
      why: "如果以自有品牌向德国终端消费者销售带包装商品，通常需要在 LUCID 包装登记册注册，并与回收系统签约。是否适用取决于你的销售与履约模式。",
      source: "德国中央包装登记处 · LUCID",
      url: "https://lucid.verpackungsregister.org/",
      excerpt: "生产者有义务在中央包装登记处登记其投放市场的包装，并参与系统回收。",
      version: "规则版本 2025 · 建议按实际履约模式确认"
    },
    weee: {
      type: "法律法规", typeClass: "", rail: "warn",
      title: "WEEE 电子电气回收责任",
      sub: "含电子部件的玩具可能适用",
      status: "待确认是否带电",
      why: "若玩具含电池、发声或发光电子模块，可能同时落入 WEEE 与电池法规范围。需要确认产品是否含电子部件，再判断注册与回收义务。",
      source: "EUR-Lex · WEEE Directive 2012/19/EU",
      url: "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32012L0019",
      excerpt: "成员国应确保生产者对电子电气设备的回收负责，并建立生产者登记制度。",
      version: "版本日期 2024 · 需确认产品是否含电子部件"
    },
    ce: {
      type: "法律法规", typeClass: "", rail: "ok",
      title: "CE 标识与符合性评估",
      sub: "标识位置、尺寸与责任主体",
      status: "有来源 · 请核对标识位置",
      why: "CE 标识应清晰、可见、不可擦除地附着在产品或其包装上。标识尺寸和位置需要符合适用指令，不能只放在说明书里。",
      source: "欧盟 Blue Guide · CE 标识",
      url: "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:52022XC0629(03)",
      excerpt: "CE 标识应附着在产品或其铭牌上；当产品性质不允许时，可附着在包装或随附文件上。",
      version: "指南版本 2022"
    },
    cpsia: {
      type: "法律法规", typeClass: "", rail: "ok",
      title: "美国 CPSIA 儿童产品安全",
      sub: "儿童产品证书与第三方测试",
      status: "有来源 · 请核对适用规则",
      why: "面向 12 岁以下儿童的美国产品通常需要儿童产品证书（CPC），并基于第三方实验室测试。测试范围取决于产品材料、年龄分级和适用标准。",
      source: "CPSC · CPSIA 指南",
      url: "https://www.cpsc.gov/Business--Manufacturing/Testing-Certification",
      excerpt: "儿童产品制造商或进口商应基于第三方测试出具儿童产品证书，证明产品符合适用安全规则。",
      version: "规则持续更新 · 以 CPSC 当前要求为准"
    },
    timeline1: {
      type: "日期节点", typeClass: "", rail: "ok",
      title: "欧盟玩具指令过渡条款",
      sub: "旧库存与新版要求的衔接",
      status: "已记录 · 请核对具体条款",
      why: "时间线只展示已核对目录中的日期节点，不代表所有成员国执行节奏完全一致。涉及库存和过渡期时，需要逐条查看条款原文。",
      source: "EUR-Lex · 2009/48/EC",
      url: "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32009L0048",
      excerpt: "成员国应按规定日期实施相关条款；过渡安排以指令及后续修订为准。",
      version: "日期节点来自当前法规库快照"
    },
    freshGpsr: {
      type: "关键日期", typeClass: "type-chip--pol", rail: "warn",
      title: "GPSR 通用产品安全法规",
      sub: "2026-12-13 起适用 · 在线销售需指定欧盟责任人",
      status: "即将生效 · 请核对",
      why: "你当前的德国站销售路径会受到影响。在线销售的产品需要指定欧盟责任人，并在产品页面提供安全信息。请确认责任人信息和页面信息是否已经补齐。",
      source: "EUR-Lex · Regulation (EU) 2023/988",
      url: "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32023R0988",
      excerpt: "在线销售的产品应在产品页面清晰提供制造商及欧盟责任人的名称、地址和联系方式。",
      version: "检查日期 2026-10-19 · 目录版本 2026-10-19 · 生效日期 2026-12-13"
    },
    freshToy: {
      type: "版本更新", typeClass: "type-chip--pol", rail: "warn",
      title: "玩具安全指令 2009/48/EC",
      sub: "目录内版本 2024-12-01 · 检测报告可能引用旧版",
      status: "有更新 · 需要核对",
      why: "法规本身没有替代，但目录记录的版本和协调标准有更新。你手上的 EN 71 报告如果引用旧版标准，需要在下次补货或审核前确认是否需要更新。",
      source: "EUR-Lex · Directive 2009/48/EC",
      url: "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32009L0048",
      excerpt: "玩具应满足指令的基本安全要求；协调标准版本以欧盟官方公报最新引用为准。",
      version: "检查日期 2026-10-19 · 目录版本 2024-12-01"
    },
    freshEn71: {
      type: "已核对", typeClass: "", rail: "ok",
      title: "EN 71-1 机械物理性能",
      sub: "目录引用版本 2014+A1:2018 · 与当前报告一致",
      status: "已是最新",
      why: "当前目录引用的标准版本与检测报告一致。仍然需要确认报告覆盖实际材料、颜色和工艺；换供应商或换材料时需要重新评估。",
      source: "CEN · EN 71-1",
      url: "https://standards.cencenelec.eu/",
      excerpt: "EN 71-1 规定玩具机械与物理性能的安全要求及测试方法。",
      version: "检查日期 2026-10-19 · 报告版本 2014+A1:2018"
    },
    freshAmazon: {
      type: "平台规则", typeClass: "type-chip--plat", rail: "muted",
      title: "Amazon 玩具类目审核",
      sub: "平台规则无法自动核对 · 需人工查看卖家后台",
      status: "无法确认",
      why: "平台规则不在公开法规库内，且更新频率高。建议在每次上架或补货前，直接查看卖家后台的类目审核要求，并保留当时的截图或文件。",
      source: "Amazon Seller Central",
      url: "https://sellercentral.amazon.com/",
      excerpt: "部分玩具类商品在发布前需通过类目审核，并提交安全文件与标签图片。",
      version: "无法自动核对 · 以卖家后台当前页面为准"
    }
  };

  export const RESULT_ITEMS = ["toy", "doc", "en71", "amazon", "label", "lucid", "weee"];
  export const PRIORITIES = [
    ["确认年龄分级与德语警告语", "标签和说明书先定稿，再送检"],
    ["准备 EU 符合性声明 DoC", "确认谁承担制造商责任"],
    ["核对 EN 71 检测报告覆盖范围", "报告需匹配实际材料与工艺"]
  ];

  export const TOOL_PAGES = {
    map: {
      icon: "map", title: "法规地图", sub: "选择一个品类和市场，查看适用法规、状态与官方来源。",
      filters: ["儿童玩具", "欧盟", "全部状态"],
      rows: ["toy", "en71", "ce", "label"],
      head: "已核对目录 · 4 条"
    },
    todo: {
      icon: "list", title: "合规待办", sub: "把法规变成今天能执行的动作，按紧迫度排序。",
      filters: ["儿童玩具", "欧盟", "按紧迫度"],
      rows: ["doc", "label", "amazon", "en71", "lucid"],
      head: "3 项优先 · 其余 5 项"
    },
    timeline: {
      icon: "calendar", title: "变化时间线", sub: "区分发布、生效、适用与过渡日期，避免按旧规则准备。",
      filters: ["儿童玩具", "欧盟", "最近 12 个月"],
      custom: "timeline"
    },
    freshness: {
      icon: "shield", title: "时效性检查", sub: "核对你正在依赖的法规和标准是否仍是最新，哪些需要处理。",
      filters: ["儿童玩具", "德国", "全部状态"],
      custom: "freshness"
    },
    compare: {
      icon: "compare", title: "区域对比", sub: "按官方编号精确匹配，不把名称相似误判为同一法规。",
      filters: ["儿童玩具", "欧盟 ↔ 美国"],
      custom: "compare"
    },
    multi: {
      icon: "globe", title: "多市场汇总", sub: "同一品类在不同市场的法规与数据状态，按区域分组。",
      filters: ["儿童玩具", "欧盟 + 美国"],
      custom: "multi"
    },
    readiness: {
      icon: "flag", title: "上线准备", sub: "把待办排成小团队能执行的计划，按阶段和责任组织。",
      filters: ["儿童玩具", "欧盟 + 美国"],
      custom: "phases"
    },
    journey: {
      icon: "layers", title: "六阶段路线", sub: "从选品到切换复核，看每个阶段的任务、资料和缺口。",
      filters: ["德国亚马逊", "儿童玩具"],
      custom: "phases"
    }
  };

  export const FRESH_ITEMS = ["freshGpsr", "freshToy", "freshEn71", "freshAmazon"];
  export const START = [
    { title: "毛绒玩具卖到德国亚马逊，要从哪里开始？", prompt: "我想把毛绒玩具卖到德国亚马逊，从哪里开始？", lead: true },
    { title: "儿童玩具卖到欧盟，先看相关法规", prompt: "儿童玩具卖到欧盟，先看相关法规", lead: true },
    { title: "比较欧盟和美国的儿童玩具法规目录", prompt: "比较欧盟和美国的儿童玩具法规目录" },
    { title: "最近有哪些法规变化和时间节点？", prompt: "查看法规变化时间线，最近有什么新要求" }
  ];
  export const CLAUSES = [
    {
      id: "EU:32009L0048", heading: "Article 4 · 一般安全要求", status: "已解析",
      body: "成员国应确保投放市场的玩具符合本指令规定的基本安全要求。制造商应执行符合性评估，并确保生产过程持续符合要求。",
      link: "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32009L0048", meta: "12 段 · 版本 2024-12-01"
    },
    {
      id: "EU:32009L0048", heading: "Article 9 · 警告语", status: "已解析",
      body: "玩具应附有清晰可辨的警告语，以减少使用时的固有风险。警告语应使用消费者所在成员国的官方语言。",
      link: "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32009L0048", meta: "8 段 · 版本 2024-12-01"
    }
  ];

  export const PROFILE_SHEETS = {
    history: (conversations) => historySheet(conversations),
    conditions: () => `
      <div class="sheet__grab"></div>
      <div class="sheet__body">
        <div class="sheet__top">
          <span class="sheet__lead" style="margin:0">当前查询条件</span>
          <button class="sheet__close" data-action="close-sheet" aria-label="关闭">${ic("close")}</button>
        </div>
        <h2>助手目前的理解</h2>
        <div class="context" style="margin-top:12px">
          <span>${conditions.category}</span><span>${conditions.market}</span><span>${conditions.platform}</span><span>${conditions.powered}</span>
        </div>
        <div class="sheet__section">
          <h3>只改需要改变的条件</h3>
          <p>可以直接在对话里说「市场改成美国」或「不是 FBA」，助手会保留其他条件并更新结果。</p>
        </div>
        <div class="sheet__actions">
          <button class="btn btn--primary btn--block" data-action="nav" data-to="assistant">回对话修改</button>
        </div>
      </div>`,
    voice: () => `
      <div class="sheet__grab"></div>
      <div class="sheet__body">
        <div class="sheet__top">
          <span class="sheet__lead" style="margin:0">语音输入</span>
          <button class="sheet__close" data-action="close-sheet" aria-label="关闭">${ic("close")}</button>
        </div>
        <h2>说完先确认，再发送</h2>
        <p class="sheet__lead">识别结果会先进输入框做预编辑。确认产品名称、国家和数字无误后，再点发送。</p>
        <div class="sheet__status" style="margin-top:14px">${ic("check")}本地语音引擎已启用 · 最长 60 秒</div>
        <div class="sheet__section">
          <h3>使用边界</h3>
          <p>录音由界面临时存储，应用不另存音频。云端转写会把录音发送到语音服务；请勿输入客户敏感资料。</p>
        </div>
      </div>`,
    coverage: () => `
      <div class="sheet__grab"></div>
      <div class="sheet__body">
        <div class="sheet__top">
          <span class="sheet__lead" style="margin:0">数据覆盖与版本</span>
          <button class="sheet__close" data-action="close-sheet" aria-label="关闭">${ic("close")}</button>
        </div>
        <h2>目录、核对与截止日期</h2>
        <div class="stat-row">
          <div class="stat"><b>${(cache.boot && cache.boot.coverage && cache.boot.coverage.laws) || 86}</b><span>部法规</span></div>
          <div class="stat"><b>${(cache.boot && cache.boot.coverage && cache.boot.coverage.categories) || 5}</b><span>类商品</span></div>
          <div class="stat"><b>${(cache.boot && cache.boot.coverage && cache.boot.coverage.audited) || 0}</b><span>条逐条核对</span></div>
          <div class="stat"><b>${(cache.boot && cache.boot.coverage && cache.boot.coverage.pending_audit) || 0}</b><span>条负责人声明确认</span></div>
        </div>
        <div class="sheet__section">
          <h3>数据快照</h3>
          <p>截止 ${(cache.boot && cache.boot.data_cutoff) || "2026-10-14"}。目录标记、机器读取与用户自述均不等于商品已合规；请逐条查看适用条件与证据状态。</p>
        </div>
      </div>`,
    privacy: () => `
      <div class="sheet__grab"></div>
      <div class="sheet__body">
        <div class="sheet__top">
          <span class="sheet__lead" style="margin:0">隐私与使用边界</span>
          <button class="sheet__close" data-action="close-sheet" aria-label="关闭">${ic("close")}</button>
        </div>
        <h2>数据怎么处理</h2>
        <div class="sheet__section">
          <h3>会话</h3>
          <p>业务状态默认保存在服务内存，不写入原始对话日志。导出使用临时文件。</p>
        </div>
        <div class="sheet__section">
          <h3>模型</h3>
          <p>模型只用于理解输入。结论来自已核对语料和确定性规则；输入文字可能发送给模型服务。</p>
        </div>
        <div class="sheet__section">
          <h3>语音</h3>
          <p>录音由界面临时存储；云端转写会发送录音。请勿输入客户敏感资料。</p>
        </div>
      </div>`,
    about: () => `
      <div class="sheet__grab"></div>
      <div class="sheet__body">
        <div class="sheet__top">
          <span class="sheet__lead" style="margin:0">关于</span>
          <button class="sheet__close" data-action="close-sheet" aria-label="关闭">${ic("close")}</button>
        </div>
        <h2>出海合规雷达</h2>
        <p class="sheet__lead">从问题到下一步。先理解你的生意，再从已核对语料里给出法规、日期和行动。</p>
        <div class="sheet__section">
          <h3>版本</h3>
          <p class="mono">2026.10.19-chat1.6 · 原型 v2</p>
        </div>
        <div class="sheet__section">
          <h3>边界</h3>
          <p>有帮助，有来源，有边界。不构成法律意见；涉及产品责任、合同或争议时，请让专业人员复核。</p>
        </div>
      </div>`,
    help: () => `
      <div class="sheet__grab"></div>
      <div class="sheet__body">
        <div class="sheet__top">
          <span class="sheet__lead" style="margin:0">怎么用</span>
          <button class="sheet__close" data-action="close-sheet" aria-label="关闭">${ic("close")}</button>
        </div>
        <h2>四步用好这个助手</h2>
        <div class="steps">
          ${[
            ["说清生意", "一句自然语言就够：毛绒玩具卖到德国亚马逊。不用先选菜单。"],
            ["回答追问", "助手一次只问一个条件，比如是否带电、FBA 还是自发货。"],
            ["看行动与依据", "先看现在先做的三项；点条目核对适用条件和官方原文。"],
            ["查正文、导出、存档", "在法规中心里按编号查条款；结果可以导出，也可以回看历史。"]
          ].map(([t, s], i) => `
            <div class="step"><span class="step__no">${i + 1}</span><span><b>${t}</b><span>${s}</span></span></div>`).join("")}
        </div>
      </div>`
  };

