# 出海合规雷达 · 前端 SPA 改造设计

- 日期：2026-10-20
- 分支：`feat/spa-frontend`（worktree：`compliance-radar-spa`，基底 `c449550` = `origin/main`）
- 原型：`prototype.html`（内联脚本 sha256 `2cc70408cd038820456e7e4bafd1b30a3b66ae65780c6af0ca758994a7f11dca`，79051 字节）
- 拆解证据：`_recon/out/FINDINGS.md`、`_recon/out/routes.json`、`_recon/out/shots/`、`_recon/out/rea/`

## 1. 目标

把现有 Gradio 组件树前端改造为**符合 `prototype.html` 的真实单页应用**：16 条路由、7 个底部抽屉、底部五标签栏、手机比例排布，复用原型的 CSS 令牌与组件样式。

「符合原型」的实质是复用原型的**设计资产**（令牌、组件样式、交互骨架与信息架构），而非照搬原型的行为层——原型的行为层是一次性演示逻辑（`state.choices`、`showToast`、硬编码历史），留着是负债。

## 2. 已确认的决策

| 议题 | 决定 |
|---|---|
| 技术路线 | Gradio 当服务器与 API 层，前端换成真 SPA；`ms_deploy.json` 不动 |
| 桌面端 | 去掉手机壳装饰；保持手机比例与排布。后期主力用户是手机端 |
| 数据接入 | 先做壳与路由，内容先用示例数据 |
| 架构方案 | 甲：原型当设计资产，视图层重写（原生 ES modules，零构建） |
| 工作区 | 独立 worktree，避开原目录的并行工作 |

## 3. 已验证的技术事实

全部在**真实项目代码**上实测，非推断。验证脚本 `_recon/scripts/verify_chain.py`（结果 ALL PASS）。

| 事实 | 证据 |
|---|---|
| `demo.app` 仅在 `launch()` 内创建（源码 `blocks.py:242`），`Blocks.__init__` 里不存在 | 读 Gradio 6.2.0 源码 |
| `launch(prevent_thread_lock=True)` 之后 `demo.app` 可用，**且可继续追加路由** | `/api/ping` → 200 |
| `StaticFiles` 挂 `/static` 会 404（与 Gradio 冲突）；挂 `/web` 正常 | 对照实测 |
| 在 `app.router.routes` 首位插入 `Route("/")` 可接管根路径，**且 Gradio 自身 API 仍存活** | `/` → SPA；`/gradio_api/info` → 200 含真实 `submit_message` |
| `/api/*` 已打通真数据链路 | `/api/bootstrap` → `{"ok":true,"data":{"category":"儿童玩具","market_code":"EU","primary_count":2,"cross_count":5}}` |
| 非阻塞 launch 后进程需显式阻塞，否则退出 | 心跳 10 次验证 |
| `modules.*.query()` 返回结构化 dict，可直接序列化 | `m1_map.query` keys：`ok/reason/品类/市场/market_code/primary/cross/llm` |
| 备选路径 B（`mount_gradio_app` + uvicorn）同样可行 | `/`、`/api/ping`、`/assets/*`、`/gradio` 全 200 |

## 4. 架构与目录

### 4.1 前端（新增，零构建）

```
web/
  index.html                    壳：appbar / view / dock / tabbar / sheet / backdrop / toast
  styles/
    tokens.css                  原型的 :root 令牌（原文照搬）
    base.css                    reset、排版、.mono、.ic
    shell.css                   app-shell / appbar / view / tabbar / dock / sheet / backdrop / toast
    components.css              card / row / chip / btn / stat / tool / rail / filterbar / steps
    views.css                   仅视图特有样式
  js/
    main.js                     启动：建壳、绑事件、启动路由
    router.js                   hash 路由表 + 导航
    store.js                    会话与筛选状态（订阅式）
    api.js                      /api/* 封装 + 错误归一
    icons.js                    原型的 ICONS 表（原文照搬）
    ui/dom.js                   esc / 模板工具
    ui/sheet.js                 底部抽屉
    ui/toast.js                 轻提示
    views/
      home.js  result.js  freshness.js  assistant.js
      regulations.js  search.js  tool.js  profile.js  tutorial.js
```

`styles/tokens.css` 与 `js/icons.js` **原文复用**原型资产。`views/tool.js` 承载 7 个工具视图（map / timeline / todo / readiness / journey / compare / multi），由 `TOOL_PAGES` 的配置驱动。时效性检查独立成 `views/freshness.js`（对应原型顶层路由 `#/freshness`，不归入工具组）。

### 4.2 后端（改动最小）

```
web_app.py        新增：SPA 挂载（根路由 + /web 静态）+ /api/* 契约层 + 键名归一
app_main.py       改：__main__ 里 launch(prevent_thread_lock=True) → web_app.install(demo) → 阻塞
ui_chat.py        不动（回退界面）
assets/           不动（旧界面资源）
modules/          不动（契约由 web_app.py 在边界归一）
ms_deploy.json    不动
```

`app_main.py` 顶部保留 `build_legacy_ui = build_ui` 的既有别名语义；`build_ui()` 仍然返回未挂 SPA 的 Gradio Blocks，SPA 挂载由 `web_app.install(demo)` 独立完成，便于单独测试。

界面开关：环境变量 `CR_UI=spa|gradio`，默认 `spa`。`gradio` 时跳过 `install()`，回退到现有 Gradio 界面。

## 5. API 契约

统一信封，沿用模块既有的 `ok/reason` 约定：

```json
{ "ok": true, "reason": "", "data": {}, "meta": { "build": "...", "snapshot": "..." } }
```

`ok:false` 时 `reason` 为面向用户的说明文案，`data` 为 `null`。

| 端点 | 方法 | 入参 | 数据来源 |
|---|---|---|---|
| `/api/bootstrap` | GET | — | 品牌、构建版本、数据快照统计、模型与语音可用性 |
| `/api/freshness` | GET | — | `data/freshness_latest.json` |
| `/api/route` | POST | `{text, context}` | `m15_router.route` |
| `/api/tool/map` | POST | `{category, market}` | `m1_map.query` |
| `/api/tool/todo` | POST | `{category, market}` | `m3_todo.query` |
| `/api/tool/timeline` | POST | `{category, market, window}` | `m2_timeline.query` |
| `/api/tool/compare` | POST | `{category}` | `m5_compare.query` |
| `/api/tool/multi` | POST | `{category, markets}` | `m6_multi_region.query` |
| `/api/tool/readiness` | POST | `{category, markets}` | `m7_opc_readiness.query` |
| `/api/search` | GET | `?identifier=&heading=` | `core.law_store.retrieve` → `{reason, units[{heading,locator,document_id,parse_status,body,truncated}]}` |
| `/api/transcribe` | POST | multipart 音频 | `core.asr.transcribe` → `(text, meta)` |
| `/api/export/todo.csv` | GET | `?category=&market=` | `app_main.export_m3_csv` |
| `/api/export/readiness.csv` | GET | `?category=&markets=` | `app_main.export_readiness_csv` |

**键名归一**：模块返回中文键（`品类`/`市场`/`primary`/`cross`），在 `web_app.py` 边界统一转成稳定英文键（`category`/`market`/`primary`/`cross`）。`modules/` 与既有 Gradio 界面不受影响。

## 6. 前端路由与状态

hash 路由，语义照原型。

| 分组 | 路由 |
|---|---|
| 首页 | `#/home`、`#/result`、`#/freshness` |
| 助手 | `#/assistant` |
| 法规 | `#/regulations`、`#/regulations/search`、`#/regulations/map`、`#/regulations/timeline` |
| 行动 | `#/action`、`#/action/todo`、`#/action/readiness`、`#/action/journey`、`#/action/compare`、`#/action/multi` |
| 我的 | `#/profile`、`#/profile/tutorial` |

浮层（底部抽屉，**不写 URL**，照原型）：`detail`、`history`、`conditions`、`voice`、`coverage`、`privacy`、`about`、`help`。

标签栏高亮规则照原型：`regulations/*` 归 法规，`action/*` 归 行动，`profile/*` 归 我的，`freshness` 归 首页。

`store` 管会话（品类 / 市场 / 平台 / 站点 / 履约 / 结果 id / 筛选）。结果带 `result_id` 锚定，沿用现有「只在换结果时滚动、展开证据不跳位」的约定（现由 `assets/chat.js` 的 `followResult` 实现，改造后由 store 订阅实现）。

**语音预编辑归前端**：`ui_chat.transcribe` 目前顺带维护预编辑快照（识别前原文 + 识别结果）以支持撤销。改造后该状态移入前端 store，`/api/transcribe` 只返回 `{text, meta}`，撤销语义（「未编辑前可撤销」）由前端保证。

## 7. 响应式

- **移动 (<700px)**：严格照原型。appbar + view + tabbar 满宽满高。
- **桌面 (≥700px)**：去掉手机壳装饰（无边框、无圆角、无阴影、无桌面底纹），内容窄栏居中 `max-width: 480px`，标签栏保持底部。

实测参照：原型移动端 `.appbar` 高 62、`.tabbar` 高 63、`.view` 720、内容左右内边距 17、卡片圆角 13。

## 8. 验收

1. **像素**：Playwright 在固定 390×844 与 1440×900 逐路由截图「原型 vs 改造后」→ REA `compare-web-screenshots` 做独立像素比对（内容寻址 PNG，可比、可存档）。
2. **结构**：REA `inspect-web-page` 取可访问性树，比对关键 role 与名称。
3. **契约**：`/api/*` 逐端点断言，含 `ok:false` 分支与空选择态。
4. **回归**：`scripts/selftest_all.py` 离线门禁保持既有通过项不退化。

## 9. 风险与回退

| 风险 | 级别 | 缓解 |
|---|---|---|
| 创空间 gradio SDK 健康检查是否容忍根路由被接管 | **未验证** | 本机无魔搭 CLI / 凭据，无法部署验证。方案 C 已在本地全链路通过；残余风险靠一次真机探针部署关闭。若不容忍 → 回退已验证的路径 B（`mount_gradio_app` + uvicorn） |
| 与并行会话在同一仓库互相干扰 | 中 | 已隔离到独立 worktree；提交时逐个指定路径，不用 `git add -A` |
| Gradio 升级改变 `demo.app` 或路由插入行为 | 低 | `ms_deploy.json` 锁 6.2.0；`web_app.install()` 失败时回退 `CR_UI=gradio` |
| 原目录工作区并行改动 | 中 | 不触碰；本分支基底为 `origin/main` |

## 10. 非目标（YAGNI）

- 不做桌面专属多栏布局（后期主力是手机端）
- 不引入 Node 构建链（Vite / 框架）
- 不修改 `modules/` 的对外契约
- 不删除 `ui_chat.py` 与 `assets/`（保留为回退界面）
- 不在本阶段接入真数据（先壳与路由 + 示例数据）

## 11. 分阶段

- **M1**：壳（appbar / view / dock / tabbar / sheet / toast）、16 路由、7 抽屉、响应式、令牌与组件样式复用、示例数据。验收=像素比对原型。
- **M2**：`/api/*` 契约层 + 逐路由替换示例数据为真数据。验收=契约断言 + 回归门禁。

## 12. 环境备注

- 隔离环境：`_recon/probe-venv`（Python 3.12 + `gradio==6.2.0` + 项目全部依赖 + playwright）
- 基线：`scripts/selftest_all.py` 14/15 组通过；`scripts/selftest_recall_flow.py` 失败，原因是 `runtime-assets/law-store.bundle` 缺失（该文件不被 git 跟踪，按 `scripts/build_runtime_law_store.py` docstring 属单独分发资产）。**原仓库同样缺失**，属既有环境缺口，与本改造无关。