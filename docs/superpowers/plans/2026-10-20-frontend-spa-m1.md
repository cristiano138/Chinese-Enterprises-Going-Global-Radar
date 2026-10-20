# 前端 SPA 改造 M1（壳 + 路由 + 抽屉 + 响应式）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把出海合规雷达的前端从 Gradio 组件树改造为符合 `prototype.html` 的真实单页应用（M1：壳、16 路由、7 抽屉、响应式、示例数据）。

**Architecture:** Gradio 保留为服务器与 API 层（`demo.launch()` 链路不变，`ms_deploy.json` 不动）。前端是零构建的原生 ES modules，由 `web_app.py` 在 `launch()` 后接管根路由并挂载 `/web` 静态资源。原型的 CSS 令牌与组件样式**逐行搬运**，行为层重写为可维护的模块。

**Tech Stack:** Python 3.12 / Gradio 6.2.0 / FastAPI+Starlette（随 Gradio 附带）/ 原生 ES modules（无构建）/ Playwright（仅开发期验收）

**Spec:** `docs/superpowers/specs/2026-10-20-frontend-spa-design.md`

## Global Constraints

- Python 依赖版本不变：`gradio==6.2.0`（`ms_deploy.json` 锁定 `sdk_type: gradio`, `sdk_version: 6.2.0`）——**不得修改 `ms_deploy.json`**
- `modules/` 的对外契约**不得修改**（中文键在 `web_app.py` 边界归一）
- `ui_chat.py` 与 `assets/` **不得删除或修改**（保留为回退界面）
- **零构建**：不得引入 `package.json`、Vite、npm 依赖或任何打包步骤
- 前端只使用浏览器原生能力（ES modules、`fetch`、hash 路由）
- 界面开关：环境变量 `CR_UI`，取值 `spa`（默认）| `gradio`
- 中文文案**逐字照抄原型**，不得改写、意译或"优化"
- 提交时**逐个指定路径**，禁止 `git add -A` / `git add .`（本仓库有并行会话）
- 参考文件 `prototype.html` 在仓库根目录之外；Task 1 会把它入库为只读参考资产
- 【搬运】保留原型的 2 空格缩进，因此**校验用的 grep 一律不要锚定行首**（`^export` 会返回 0）。用 `^[[:space:]]*export` 或干脆不加锚。
- 所有 `python.exe` 调用前都带 `PYTHONIOENCODING=utf-8`。**不要删掉它**：Windows 下子进程的 stdout 默认是 gbk，测试文件里的中文 docstring/用例名会以乱码输出，污染每一次运行结果。

### 关于"从原型搬运"的约定

本计划中标注 **【搬运】** 的步骤指的是：把 `prototype.html` 中指定行号范围的文本**原样复制**到目标文件，不做改写、不重排、不"顺手优化"。每个【搬运】步骤都给出了**精确行号范围**与**搬运后的校验断言**，因此它是一条可执行、可验证的指令，不是占位符。行号以入库的 `docs/ui-preview/prototype-v2.html` 为准（Task 1 入库后行号与原件一致）。

**【搬运】是本计划的主要手段，不只是给 CSS 用的。** 前端的行为层同样逐字搬运——原型那 2452 行里的 JS 本身就是一个干净的小型 SPA 运行时，不需要重新架构它。

**这件事上曾经栽过跟头，所以规则写死在这里**：先前那版计划让作者手写视图标记，结果 77 个静态类名里 20 个（26%）在原型 CSS 里不存在——`fresh-card__top`（原型是 `__head`）、`resume__copy`、`progress__meta`、`composer__mic`、`pill`、`row__copy` 等全是凭空发明的，还自创了 `back` / `send` / `starter` 等原型没有的 `data-action`。**手写就必须手写类名，手写类名就会写错。** 逐字搬运则从根本上没有这个失效模式。

**视图搬运的机械装置**：视图函数**接收 `state` 形参、函数体一字不动**。原型函数体内部本来就写作 `state`、`ITEMS`、`rowHtml`、`ic`、`esc`——模块化后只要用形参与 `import` 把这些名字提供出来，标记与逻辑**一个字符都不用改**。因此每个视图任务的增量只有三类：改 `export`、补 `import`、剔掉演示专用件（逐条列出）。

标注 **【新写】** 的步骤给出完整代码，照抄即可。

## Review Focus

以下五类输入或失效模式是规格与原型都未明说、但最可能在真实使用中咬人的地方。每条都在所属任务里配了测试。

1. **用户输入含 HTML 特殊字符**：产品描述、合同要点、检索编号都可能含 `<`、`&`、`"`。任何直接插进模板字符串而不转义的路径都会造成注入或破版。期望：所有插值经 `esc()`，页面不出现意外的 HTML 解析。
2. **未知或畸形 hash 路由**：用户手动改地址栏、分享被截断的链接、`#/regulations/不存在的工具`。期望：回落到首页，不白屏、不抛未捕获异常。
3. **后端返回 `ok:false` 或空数组**：品类/市场超出语料范围、检索无命中、时效性文件缺失。期望：渲染出原型里已有的"待确认/无法确认"类状态，而不是空卡片或崩溃。
4. **会话中途切换条件**：先查德国、再切美国，抽屉与筛选处于打开状态。期望：不残留上一次的条件，不把旧结果渲染成新条件的结果。
5. **桌面宽屏与移动窄屏之间来回缩放**：跨过 700px 断点时手机壳装饰的开关、标签栏位置、内容栏宽度都不得错乱或留下残影。

---

## File Structure

### 新增

| 文件 | 职责 |
|---|---|
| `web_app.py` | SPA 挂载（根路由 + `/web` 静态）+ `install(demo)` + `CR_UI` 开关 |
| `web/index.html` | 应用外壳：appbar / view / dock / tabbar / sheet / backdrop / toast 七个挂载点 |
| `web/styles/tokens.css` | 原型的 `:root` 设计令牌【搬运】 |
| `web/styles/base.css` | reset、排版、`.ic`、`.mono`【搬运】 |
| `web/styles/shell.css` | 外壳：手机壳、顶栏、滚动区、底部导航、输入区、抽屉、轻提示【搬运】 |
| `web/styles/components.css` | 通用页头与按钮【搬运：原型 434-445、527-551】 |
| `web/styles/views.css` | 其余组件与各视图样式：卡片、行、状态点、工具格、筛选栏、步骤、首页、结果页、法规库、检索、我的【搬运：原型 149-433、446-526、640-780】 |
| `web/js/main.js` | 启动：`render()` 路由分派、事件委托、视图注册 |
| `web/js/router.js` | `routeOf` / `go`【搬运：原型 1181-1182】 |
| `web/js/store.js` | 状态（字段形状取自原型 1151-1165）+ `set` / `setConditions` / `subscribe` |
| `web/js/icons.js` | 图标表 + `ic()`【搬运：原型 901-936】 |
| `web/js/dom.js` | `esc()`【搬运：原型 1176-1178】 |
| `web/js/sample.js` | 示例数据表：`ITEMS` / `TOOL_PAGES` / `PROFILE_SHEETS` / `START` / `CLAUSES` 等【搬运：原型 939-1148、1243-1248、1735-1747、2187-2321】——**M2 只换这一个文件** |
| `web/js/render.js` | 渲染辅助：`rowHtml` / `toolCard` / `filteredItems` / `filteredFresh`【搬运：原型 1425-1441、1443-1447、1566-1571、1627-1632】 |
| `web/js/shell.js` | `renderAppbar` / `renderTabbar` / `TABS`【搬运：原型 1186-1240、1970-2003】 |
| `web/js/ui/sheet.js` | 底部抽屉【搬运：原型 2322-2333】 |
| `web/js/ui/toast.js` | 轻提示【搬运：原型 2147-2152】 |
| `web/js/ui/composer.js` | 输入区 + `bindComposer`【搬运：原型 1946-1967、2335-2348】 |
| `web/js/views/*.js` | 11 个视图模块（home / result / freshness / assistant / regulations / search / tool / action / profile / tutorial / detail）【搬运】 |
| `scripts/selftest_web_api.py` | 离线：静态托管、`install()` 成败契约、未知路由 |
| `scripts/selftest_web_ui.py` | 浏览器：逐路由 DOM/布局/交互断言（Playwright） |
| `scripts/check_web_browser.py` | 浏览器：逐路由截图 + 结构报告（沿用 `check_chat_browser.py` 范式） |
| `scripts/compare_web_screenshots.py` | 像素比对：原型 vs 改造后（调 REA） |

**没有 `components.js`**：先前那版计划造过一层组件抽象（`pageHead` / `card` / `row` / `toolCard` 等返回 HTML 的函数），结果引入了一套自创类名——77 个静态类名里 20 个（26%）在原型 CSS 里不存在。现改为**视图直接逐字搬运原型标记**，不需要中间抽象层。

### 修改

| 文件 | 改动 |
|---|---|
| `app_main.py` | 仅 `__main__` 块：`launch(prevent_thread_lock=True)` → `web_app.install(demo)` → 阻塞 |
| `scripts/selftest_all.py` | 把 `scripts/selftest_web_api.py` 加入离线门禁清单 |

### 入库的参考资产（只读）

| 文件 | 来源 |
|---|---|
| `docs/ui-preview/prototype-v2.html` | `prototype.html` 原样复制（像素比对的基准） |

### M1 刻意不含的文件

规格 §4.1 列出的 `web/js/api.js`（`/api/*` 封装）**属于 M2**：M1 的决定是"先做壳与路由，内容先用示例数据"，因此 M1 的每一层都不发网络请求——所有数据来自 `web/js/sample.js`（原型数据表的逐字搬运）。

**M2 的接缝因此只有一个文件**：把 `sample.js` 的取值处换成 `api.js` 的请求。视图模板、交互、类名一律不动——因为视图代码里不含任何数据来源假设，它们只是消费 `ITEMS` / `TOOL_PAGES` / `PROFILE_SHEETS` 这些名字。`web_app.py` 的 `/api/*` 端点同样在 M2 落地（M1 只做根路由接管与静态托管）。

---

## Task 1: 参考资产入库 + 静态托管骨架

**Files:**
- Create: `docs/ui-preview/prototype-v2.html`（【搬运】自 `C:\Users\ymc\Desktop\agent\prototype.html` 全文）
- Create: `web_app.py`
- Create: `web/index.html`（最小可用外壳）
- Modify: `app_main.py`（仅 `__main__` 块）
- Test: `scripts/selftest_web_api.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `web_app.install(demo) -> bool` —— 把 SPA 挂到 `demo.app` 上；成功返回 `True`，任何失败返回 `False` 且不抛异常
  - `web_app.WEB_DIR: str` —— `web/` 目录绝对路径
  - `web_app.index_html() -> str` —— 返回 `web/index.html` 内容
  - `web_app.ui_mode() -> str` —— 读 `CR_UI`，返回 `"spa"` 或 `"gradio"`

- [ ] **Step 1: 把原型入库为只读参考资产**

```bash
mkdir -p docs/ui-preview
cp "C:/Users/ymc/Desktop/agent/prototype.html" docs/ui-preview/prototype-v2.html
```

校验（拆解基线实测值，作为像素比对基准的完整性锚点）：

```bash
python -c "
import hashlib, pathlib
data = pathlib.Path('docs/ui-preview/prototype-v2.html').read_bytes().replace(b'\r\n', b'\n')
print('bytes:', len(data))
print('sha256:', hashlib.sha256(data).hexdigest())
"
```

Expected（**归一化后**的值——原文件是均匀 CRLF，归一化会去掉 2452 个 
）：
```
bytes: 125082
sha256: 43ef8e474d330c99d5e65bdcfe42648c492299587ab19fde713a1744f05104f5
```

（先归一化 `\r\n` → `\n` 再取哈希：这条断言在 `core.autocrlf` 打开时也必须成立，否则换一台机器检出后测试会假失败。）

- [ ] **Step 2: 写失败的测试**

创建 `scripts/selftest_web_api.py`：

```python
"""SPA 静态托管与 /api/* 契约的离线检查；不需要浏览器。

与 scripts/selftest_chat_ui.py 同风格：unittest、离线、不联网、不调模型。
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time
import unittest
import urllib.request

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

import gradio as gr
from gradio.routes import App  # noqa: F401  （确认 Gradio 版本提供该类型）

import app_main
import web_app


class _Server:
    """在进程内起一次真实 Gradio 服务，供所有用例共用。"""

    _lock = threading.Lock()
    _started = False
    port = int(os.getenv("SELFTEST_WEB_PORT", "7899"))

    @classmethod
    def start(cls):
        with cls._lock:
            if cls._started:
                return
            demo = app_main.build_ui()
            demo.launch(server_name="127.0.0.1", server_port=cls.port,
                        prevent_thread_lock=True, quiet=True, footer_links=[])
            time.sleep(2)
            assert web_app.install(demo), "web_app.install() 必须成功"
            time.sleep(1)
            cls._started = True

    @classmethod
    def get(cls, path):
        url = f"http://127.0.0.1:{cls.port}{path}"
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                return resp.status, resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", "replace")


class StaticHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Server.start()

    def test_root_serves_the_spa_shell(self):
        status, body = _Server.get("/")
        self.assertEqual(status, 200)
        self.assertIn('id="shell"', body)
        self.assertIn("/web/js/main.js", body)

    def test_static_assets_are_served(self):
        status, body = _Server.get("/web/js/main.js")
        self.assertEqual(status, 200)
        self.assertIn("export", body)

    def test_styles_are_served(self):
        status, body = _Server.get("/web/styles/tokens.css")
        self.assertEqual(status, 200)
        self.assertIn("--brand", body)

    def test_gradio_api_survives_the_root_takeover(self):
        status, body = _Server.get("/gradio_api/info")
        self.assertEqual(status, 200)
        self.assertIn("named_endpoints", json.loads(body))


class ReferenceAssetTests(unittest.TestCase):
    def test_prototype_reference_is_the_expected_revision(self):
        path = PROJECT / "docs" / "ui-preview" / "prototype-v2.html"
        self.assertTrue(path.is_file(), "原型参考资产必须入库")
        # 先归一化行尾，使断言在 core.autocrlf 打开时同样成立。
        data = path.read_bytes().replace(b"\r\n", b"\n")
        self.assertEqual(len(data), 125082, "原型归一化后字节数必须与拆解基线一致")
        self.assertEqual(
            hashlib.sha256(data).hexdigest(),
            "43ef8e474d330c99d5e65bdcfe42648c492299587ab19fde713a1744f05104f5",
            "像素比对基准被改动：请确认 docs/ui-preview/prototype-v2.html 未被编辑")


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 3: 运行测试确认失败**

```bash
PYTHONIOENCODING=utf-8 "C:/Users/ymc/Desktop/agent/_recon/probe-venv/Scripts/python.exe" scripts/selftest_web_api.py
```

Expected: FAIL —— `ModuleNotFoundError: No module named 'web_app'`

- [ ] **Step 4: 实现 `web_app.py`**

```python
# -*- coding: utf-8 -*-
"""把前端 SPA 挂到 Gradio 的 FastAPI 实例上。

Gradio 6.2 的 FastAPI 实例（demo.app）只在 launch() 内部创建，因此本模块的
install() 必须在 launch(prevent_thread_lock=True) 之后调用。
任何挂载失败都不抛异常，只返回 False —— 调用方据此回退到 CR_UI=gradio。
"""
from __future__ import annotations

import os
from pathlib import Path

WEB_DIR = str((Path(__file__).resolve().parent / "web").resolve())


def ui_mode() -> str:
    """读界面开关；非法值一律回落 spa。"""
    mode = os.getenv("CR_UI", "spa").strip().lower()
    return "gradio" if mode == "gradio" else "spa"


def index_html() -> str:
    return (Path(WEB_DIR) / "index.html").read_text(encoding="utf-8")


def install(demo) -> bool:
    """接管根路由并挂载静态资源。成功返回 True，失败返回 False（不抛）。"""
    try:
        from fastapi.responses import HTMLResponse
        from fastapi.staticfiles import StaticFiles
        from starlette.routing import Route
    except Exception:  # noqa: BLE001
        return False
    try:
        app = getattr(demo, "app", None)
        if app is None:
            return False
        # 静态资源挂在 /web：Gradio 自己占用 /static，挂在那里会 404。
        app.mount("/web", StaticFiles(directory=WEB_DIR), name="web")
        # 抢在 Gradio 首页之前接管 "/"。Gradio 的 /gradio_api/* 不受影响。
        app.router.routes.insert(
            0, Route("/", lambda request: HTMLResponse(index_html())))
        return True
    except Exception:  # noqa: BLE001
        return False
```

- [ ] **Step 5: 写最小 `web/index.html`**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
<meta name="theme-color" content="#FAFAF7" />
<title>出海合规雷达</title>
<link rel="stylesheet" href="/web/styles/tokens.css" />
<link rel="stylesheet" href="/web/styles/base.css" />
<link rel="stylesheet" href="/web/styles/shell.css" />
<link rel="stylesheet" href="/web/styles/components.css" />
<link rel="stylesheet" href="/web/styles/views.css" />
</head>
<body>
<div class="app-shell" id="shell">
  <header class="appbar" id="appbar"></header>
  <main class="view" id="view" tabindex="-1"></main>
  <div id="dock"></div>
  <nav class="tabbar" id="tabbar" aria-label="主要导航"></nav>
  <div class="backdrop" id="backdrop" data-action="close-sheet"></div>
  <aside class="sheet" id="sheet" role="dialog" aria-modal="true" aria-label="详情"></aside>
  <div class="toast" id="toast" role="status" aria-live="polite"></div>
</div>
<script type="module" src="/web/js/main.js"></script>
</body>
</html>
```

八个挂载点的 `id` 必须与原型 `prototype.html:885-893` 完全一致（`shell` / `appbar` / `view` / `dock` / `tabbar` / `backdrop` / `sheet` / `toast`），后续所有任务依赖这些 id。

**`#backdrop` / `#sheet` / `#toast` 必须是 `.app-shell` 的子元素，不能是它的兄弟。** 原型就是这样嵌套的（`prototype.html` 的 `</div>` 关闭 `.app-shell` 在第 894 行，位于这三个元素之后）。原因：三者都是 `position: absolute`，而 `.app-shell` 是 `position: relative`，所以绝对定位是相对 `.app-shell` 解析的。一旦把它们放到 `.app-shell` 之外，最近已定位祖先就退化成视口 —— 桌面端（≥700px）抽屉会横跨整个视口宽度而不是收在 480px 窄栏内，Toast 也会居中于整屏而非栏内。

创建占位样式与脚本，使本任务的测试可通过（后续任务会替换为【搬运】的真实内容）：

```bash
mkdir -p web/styles web/js/ui web/js/views
printf ':root{\n  --brand:#0e4d3a;\n}\n' > web/styles/tokens.css
for f in base shell components views; do printf '/* 见 Task 2 起逐节搬运 */\n' > "web/styles/$f.css"; done
printf 'export const started = true;\n' > web/js/main.js
```

- [ ] **Step 6: 改 `app_main.py` 的 `__main__` 块**

把现有 `app_main.py` 末尾的 `if __name__ == "__main__":` 块整体替换为：

```python
if __name__ == "__main__":
    port = int(os.getenv("PORT", os.getenv("SERVER_PORT", "7860")))
    host = "0.0.0.0"
    from ui_chat import CSS
    import web_app
    # 语音引擎预热：只在会用本地引擎时后台准备（不阻塞启动、不抛异常）。
    asr.prewarm()
    launch_kwargs = {"server_name": host, "server_port": port, "css": CSS,
                     "theme": gr.themes.Soft(), "footer_links": [],
                     "show_error": False, "max_file_size": "20mb"}
    demo = build_ui()
    if web_app.ui_mode() == "spa":
        # 非阻塞启动，以便接管根路由；随后显式阻塞主线程。
        demo.launch(prevent_thread_lock=True, quiet=True, **launch_kwargs)
        if not web_app.install(demo):
            print("[UI] SPA mount failed; falling back to the Gradio shell", flush=True)
        demo.block_thread()
    else:
        demo.launch(**launch_kwargs)
```

`build_ui()` 与 `build_legacy_ui` 的定义**不得改动**。

- [ ] **Step 7: 运行测试确认通过**

```bash
PYTHONIOENCODING=utf-8 "C:/Users/ymc/Desktop/agent/_recon/probe-venv/Scripts/python.exe" scripts/selftest_web_api.py
```

Expected: PASS（StaticHostTests 4 + ReferenceAssetTests 1 = 5 个用例）

- [ ] **Step 8: 验证回退开关**

```bash
CR_UI=gradio "C:/Users/ymc/Desktop/agent/_recon/probe-venv/Scripts/python.exe" -c "
import os, web_app
assert web_app.ui_mode() == 'gradio'
os.environ['CR_UI'] = 'spa'
assert web_app.ui_mode() == 'spa'
os.environ['CR_UI'] = '胡写'
assert web_app.ui_mode() == 'spa', '非法值必须回落 spa'
print('CR_UI 开关 OK')"
```

Expected: `CR_UI 开关 OK`

- [ ] **Step 9: 真机冒烟（进程级）**

```bash
PORT=7897 "C:/Users/ymc/Desktop/agent/_recon/probe-venv/Scripts/python.exe" app.py > /tmp/cr-smoke.log 2>&1 &
APP_PID=$!
sleep 12
sleep 12
curl -s -o /dev/null -w "root=%{http_code}\n" http://127.0.0.1:7897/
curl -s -o /dev/null -w "static=%{http_code}\n" http://127.0.0.1:7897/web/js/main.js
curl -s -o /dev/null -w "gradio=%{http_code}\n" http://127.0.0.1:7897/gradio_api/info
# Windows 上 `kill` 不终止 python.exe（Git Bash 作业 ≠ Windows 进程），须 taskkill 按 PID 结束，
# 否则服务会一直占着 7897。
taskkill //F //PID "$APP_PID" 2>/dev/null || kill "$APP_PID" 2>/dev/null
sleep 1
curl -s -o /dev/null -m 2 http://127.0.0.1:7897/ && echo "警告：7897 仍在监听" || echo "7897 已释放"
```

Expected: `root=200`、`static=200`、`gradio=200`

- [ ] **Step 10: 提交**

```bash
git add docs/ui-preview/prototype-v2.html web_app.py web/index.html web/styles web/js app_main.py scripts/selftest_web_api.py
git commit -m "feat(web): serve the SPA shell from Gradio's FastAPI instance"
```

---

## Task 2: 基础样式、图标与转义

**Files:**
- Modify: `web/styles/tokens.css`、`web/styles/base.css`（替换 Task 1 的占位）
- Create: `web/js/icons.js`、`web/js/dom.js`
- Test: `scripts/selftest_web_ui.py`（新建）

**Interfaces:**
- Consumes: `web_app.install()`（Task 1）提供的 `/` 与 `/web/*`；`docs/ui-preview/prototype-v2.html`（Task 1 入库的原型参考资产——本任务所有【搬运】按它的行号取值）
- Produces:
  - `web/js/icons.js` → `export const ICONS`、`export const ic = (name, cls) => string`
  - `web/js/dom.js` → `export const esc = (s) => string`

**本任务不做**：不建 `components.js`。原型的视图直接用模板字符串写标记，不需要组件抽象层——先前那版计划造的 `components.js` 引入了一套自创类名，是 26% 类名错误的来源。视图任务改为逐字搬运原型标记。

- [ ] **Step 1: 写失败的测试**

创建 `scripts/selftest_web_ui.py`。这是后续所有任务共用的浏览器测试骨架。

```python
"""SPA 前端行为与布局检查；需要 Playwright 与一个已启动的服务。

沿用 scripts/check_chat_browser.py 的范式：先起 app.py，再指定 --url。
本文件只做断言，不产生截图（截图与像素比对见 scripts/check_web_browser.py）。
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest

from playwright.sync_api import sync_playwright

PROJECT = Path(__file__).resolve().parent.parent
BASE = os.getenv("SELFTEST_WEB_URL", "http://127.0.0.1:7899")


class _Browser:
    """整个测试文件共用一次浏览器会话。"""

    _pw = None
    _browser = None
    page = None

    @classmethod
    def start(cls):
        if cls.page is not None:
            return
        cls._pw = sync_playwright().start()
        cls._browser = cls._pw.chromium.launch()
        ctx = cls._browser.new_context(viewport={"width": 390, "height": 844},
                                       locale="zh-CN", reduced_motion="reduce")
        cls.page = ctx.new_page()
        cls.page.goto(BASE, wait_until="load")
        cls.page.wait_for_timeout(400)

    @classmethod
    def goto(cls, route):
        cls.page.goto(f"{BASE}#/{route}", wait_until="load")
        cls.page.wait_for_timeout(250)
        return cls.page

    @classmethod
    def stop(cls):
        if cls._browser:
            cls._browser.close()
        if cls._pw:
            cls._pw.stop()


class TokenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Browser.start()

    def test_design_tokens_match_the_prototype(self):
        tokens = _Browser.page.evaluate(
            "() => { const cs = getComputedStyle(document.documentElement);"
            "return ['--paper','--brand','--brand-bright','--amber','--ink','--desk']"
            ".map(n => cs.getPropertyValue(n).trim()); }")
        self.assertEqual(tokens, ["#fafaf7", "#0e4d3a", "#177a57",
                                  "#e8a33d", "#12211b", "#e7ece8"])

    def test_esc_neutralises_html_in_user_input(self):
        got = _Browser.page.evaluate(
            "async () => { const m = await import('/web/js/dom.js');"
            "return m.esc('<img src=x onerror=alert(1)>\"&'); }")
        self.assertNotIn("<", got)
        self.assertIn("&lt;img", got)
        self.assertIn("&amp;", got)

    def test_ic_renders_an_svg_with_the_prototype_geometry(self):
        got = _Browser.page.evaluate(
            "async () => { const m = await import('/web/js/icons.js'); return m.ic('home'); }")
        self.assertIn('class="ic', got)
        self.assertIn('viewBox="0 0 24 24"', got)
        self.assertIn("M3 10.5 12 3l9 7.5", got)

    def test_injected_markup_is_not_parsed(self):
        """Review Focus 1：用户输入含 HTML 时不得被解析成元素。"""
        _Browser.page.evaluate(
            "async () => { const m = await import('/web/js/dom.js');"
            "const v = document.getElementById('view');"
            "v.innerHTML = '<div id=probe>' + m.esc('<b>粗体</b>') + '</div>'; }")
        probe = _Browser.page.locator("#probe")
        self.assertEqual(probe.inner_text(), "<b>粗体</b>")
        self.assertEqual(probe.locator("b").count(), 0)


def _stop_browser():
    _Browser.stop()


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        _Browser.stop()
```

- [ ] **Step 2: 起服务并运行测试确认失败**

```bash
PORT=7899 "C:/Users/ymc/Desktop/agent/_recon/probe-venv/Scripts/python.exe" app.py > /tmp/cr-ui.log 2>&1 &
sleep 12
PYTHONIOENCODING=utf-8 "C:/Users/ymc/Desktop/agent/_recon/probe-venv/Scripts/python.exe" scripts/selftest_web_ui.py
```

Expected: FAIL —— `/web/js/dom.js` 与 `icons.js` 尚不存在

- [ ] **Step 3: 搬运设计令牌与基础样式**

| 目标 | 原型行号（含） |
|---|---|
| `web/styles/tokens.css` | 9–47 |
| `web/styles/base.css` | 49–69 |

```bash
python - <<'PY'
from pathlib import Path
src = Path("docs/ui-preview/prototype-v2.html").read_text(encoding="utf-8").splitlines(keepends=True)
def take(a, b): return "".join(src[a-1:b])          # 1-based 闭区间
Path("web/styles/tokens.css").write_text(take(9, 47), encoding="utf-8")
Path("web/styles/base.css").write_text(take(49, 69), encoding="utf-8")
PY
grep -c -- "--brand:\|--paper:\|--r-xl:" web/styles/tokens.css
grep -c "box-sizing\|\.ic {\|\.mono {" web/styles/base.css
```

Expected: 均 ≥ 3

- [ ] **Step 4: 搬运图标表与转义函数**

```bash
python - <<'PY'
from pathlib import Path
src = Path("docs/ui-preview/prototype-v2.html").read_text(encoding="utf-8").splitlines(keepends=True)
def take(a, b): return "".join(src[a-1:b])

icons = take(901, 936)
icons = icons.replace("const ICONS = {", "export const ICONS = {", 1)
icons = icons.replace("const ic = (name, cls) =>", "export const ic = (name, cls) =>", 1)
Path("web/js/icons.js").write_text(
    "// 搬运自 prototype.html:901-936。仅把两处 const 改为 export const，其余未动。\n" + icons,
    encoding="utf-8")

dom = take(1176, 1178)
dom = dom.replace("const esc = (s) =>", "export const esc = (s) =>", 1)
Path("web/js/dom.js").write_text(
    "// 搬运自 prototype.html:1176-1178。仅把 const 改为 export const。\n" + dom,
    encoding="utf-8")
PY
grep -c "export const ICONS\|export const ic\|export const esc" web/js/icons.js web/js/dom.js
```

Expected: `web/js/icons.js:2`、`web/js/dom.js:1`

- [ ] **Step 5: 运行测试确认通过**

```bash
PYTHONIOENCODING=utf-8 "C:/Users/ymc/Desktop/agent/_recon/probe-venv/Scripts/python.exe" scripts/selftest_web_ui.py
```

Expected: PASS（4 个用例）

- [ ] **Step 6: 提交**

```bash
git add web/styles/tokens.css web/styles/base.css web/js/icons.js web/js/dom.js scripts/selftest_web_ui.py
git commit -m "feat(web): design tokens, icons and escaping ported from the prototype"
```

---

## Task 3: 示例数据层与渲染辅助

**Files:**
- Create: `web/js/sample.js`、`web/js/render.js`
- Test: `scripts/selftest_web_ui.py`（追加）

**Interfaces:**
- Consumes: `ic`、`esc`（Task 2）
- Produces:
  - `web/js/sample.js` → `export const ITEMS`、`RESULT_ITEMS`、`PRIORITIES`、`TOOL_PAGES`、`FRESH_ITEMS`、`START`、`CLAUSES`、`PROFILE_SHEETS`
  - `web/js/render.js` → `export function rowHtml(id)`、`filteredItems()`、`toolCard(group, id, icon, title, sub, badge)`、`filteredFresh()`

**为什么有这一层**：原型的视图函数依赖这批数据表与四个渲染辅助。把它们逐字搬成模块，视图才能在 Task 6–9 里近乎逐字搬运；M2 接真数据时**只换 `sample.js` 的取值处**，视图模板与交互不动——这正是架构想要的接缝。

- [ ] **Step 1: 写失败的测试**

在 `scripts/selftest_web_ui.py` 的 `if __name__ == "__main__":` 块**之前**追加。追加到文件末尾会让新测试类定义晚于 `unittest.main()`，这些用例会被**静默跳过**——输出仍显示 PASS，实际一个都没跑。追加后务必确认运行输出里出现了本任务新增的用例名。

```python
class SampleDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Browser.start()

    def test_sample_tables_carry_the_prototype_shape(self):
        got = _Browser.page.evaluate("""async () => {
          const s = await import('/web/js/sample.js');
          return { items: Object.keys(s.ITEMS).length,
                   result: s.RESULT_ITEMS.length,
                   tools: Object.keys(s.TOOL_PAGES).length,
                   fresh: s.FRESH_ITEMS.length,
                   start: s.START.length,
                   sheets: Object.keys(s.PROFILE_SHEETS).length };
        }""")
        self.assertEqual(got["result"], 7)
        self.assertEqual(got["tools"], 8)
        self.assertEqual(got["fresh"], 4)
        self.assertEqual(got["start"], 4)
        self.assertEqual(got["sheets"], 7)
        self.assertEqual(got["items"], 14, "原型 ITEMS 恰好 14 个顶层键（939-1094 行）")

    def test_profile_sheets_are_actually_callable(self):
        """只数键名是假绿：七个函数体各自调用 ic()，缺导入则全抛 ReferenceError。"""
        got = _Browser.page.evaluate("""async () => {
          const s = await import('/web/js/sample.js');
          const out = {};
          for (const k of Object.keys(s.PROFILE_SHEETS)) {
            try { out[k] = s.PROFILE_SHEETS[k](); }
            catch (e) { out[k] = 'THREW: ' + e.message; }
          }
          return out;
        }""")
        self.assertEqual(len(got), 7)
        for key, html in got.items():
            with self.subTest(key=key):
                self.assertFalse(str(html).startswith("THREW"), f"{key} 抛异常：{html}")
                self.assertIn('class="sheet__body"', str(html))


class RenderHelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Browser.start()

    def test_row_html_uses_the_prototype_classes_and_action(self):
        got = _Browser.page.evaluate(
            "async () => { const r = await import('/web/js/render.js'); return r.rowHtml('toy'); }")
        self.assertIn('class="row"', got)
        self.assertIn('data-action="detail"', got)
        self.assertIn('data-id="toy"', got)
        self.assertIn("row__rail", got)
        self.assertIn("row__body", got)
        self.assertIn("type-chip", got)
        self.assertNotIn("row__copy", got)      # 先前那版计划自创的类名，必须不存在

    def test_row_html_escapes_the_title(self):
        got = _Browser.page.evaluate(
            "async () => { const r = await import('/web/js/render.js');"
            "const s = await import('/web/js/sample.js');"
            "const saved = s.ITEMS.toy.title;"
            "try { s.ITEMS.toy.title = '<img src=x onerror=alert(1)>';"
            "      return r.rowHtml('toy'); }"
            "finally { s.ITEMS.toy.title = saved; } }")
        self.assertNotIn("<img", got)
        self.assertIn("&lt;img", got)

    def test_row_html_returns_empty_for_an_unknown_id(self):
        """Review Focus 2：未知条目 id 不得抛异常。"""
        got = _Browser.page.evaluate(
            "async () => { const r = await import('/web/js/render.js'); return r.rowHtml('不存在'); }")
        self.assertEqual(got, "")

    def test_tool_card_uses_the_prototype_markup(self):
        got = _Browser.page.evaluate(
            "async () => { const r = await import('/web/js/render.js');"
            "return r.toolCard('regulations', 'map', 'map', '法规地图', '按品类和市场看适用法规'); }")
        self.assertIn('data-action="open-tool"', got)
        self.assertIn('data-group="regulations"', got)
        self.assertIn('data-tool="map"', got)
        self.assertIn("tool__icon", got)
        self.assertNotIn("tool__copy", got)     # 自创类名，必须不存在

    def test_freshness_filter_selects_by_rail(self):
        got = _Browser.page.evaluate("""async () => {
          const r = await import('/web/js/render.js');
          const ids = (f) => r.filteredFresh({ freshFilter: f });
          return { all: ids('全部').length, warn: ids('需处理').length,
                   ok: ids('已最新').length, muted: ids('无法确认').length };
        }""")
        self.assertEqual(got["all"], 4)
        self.assertEqual(got["warn"], 2, "原型 freshGpsr / freshToy 为 warn")
        self.assertEqual(got["ok"], 1, "原型 freshEn71 为 ok")
        self.assertEqual(got["muted"], 1, "原型 freshAmazon 为 muted")
```

- [ ] **Step 2: 运行测试确认失败**

```bash
PYTHONIOENCODING=utf-8 "C:/Users/ymc/Desktop/agent/_recon/probe-venv/Scripts/python.exe" scripts/selftest_web_ui.py SampleDataTests RenderHelperTests
```

Expected: FAIL —— `/web/js/sample.js` 尚不存在

- [ ] **Step 3: 搬运数据表**

| 目标 | 原型行号（含） | 内容 |
|---|---|---|
| `web/js/sample.js` | 939–1148 | `ITEMS`、`RESULT_ITEMS`、`PRIORITIES`、`TOOL_PAGES`、`FRESH_ITEMS` |
| `web/js/sample.js` | 1243–1248 | `START` |
| `web/js/sample.js` | 1735–1747 | `CLAUSES` |
| `web/js/sample.js` | 2187–2321 | `PROFILE_SHEETS` |

**本步骤有两处增量，缺一不可**：

1. 八个顶层 `const X = ` 改为 `export const X = `（脚本已做）。
2. **头部补 `import { ic } from "./icons.js";`**。原型里 `ic` 是同一个闭包内的 `const`，模块化后它是 `icons.js` 的**具名导出、不是全局**（`index.html` 只加载 `type="module"` 脚本，ES module 绑定是词法的）。`PROFILE_SHEETS` 的七个函数体里共调用 `ic(...)` **10 次**——不加这行导入，那七个函数**全部会抛 `ReferenceError: ic is not defined`**，而"只数键名"的测试照样全绿。导入行位于被搬运的主体之外，逐字节保真性不受影响。

```bash
python - <<'PY'
import re
from pathlib import Path
src = Path("docs/ui-preview/prototype-v2.html").read_text(encoding="utf-8").splitlines(keepends=True)
def take(a, b): return "".join(src[a-1:b])
body = take(939, 1148) + take(1243, 1248) + take(1735, 1747) + take(2187, 2321)
# 顶层 const 改为 export const，逐个精确替换（不用全局替换，避免误伤对象内部的字面量）
for name in ("ITEMS", "RESULT_ITEMS", "PRIORITIES", "TOOL_PAGES",
             "FRESH_ITEMS", "START", "CLAUSES", "PROFILE_SHEETS"):
    before = body
    body = re.sub(rf"^(\s*)const {name} = ", rf"\1export const {name} = ",
                  body, count=1, flags=re.M)
    assert body != before, f"{name} 未被替换"
header = ("// 搬运自 prototype.html:939-1148, 1243-1248, 1735-1747, 2187-2321。\n"
          "// 增量：顶层 const → export const；并补 ic 导入（见下）。数据内容逐字未动。\n"
          "// M2 接入真数据时只改本文件的取值处，视图模板不动。\n"
          'import { ic } from "./icons.js";\n\n')
Path("web/js/sample.js").write_text(header + body, encoding="utf-8")
PY
grep -cE "^[[:space:]]*export const [A-Z_]+ = " web/js/sample.js
grep -c '^import { ic } from "./icons.js";' web/js/sample.js
```

Expected: `8`；`1`

**第二行为 0 就说明 `PROFILE_SHEETS` 必然全抛异常**——见上面那两处增量的第 2 条。

- [ ] **Step 4: 搬运渲染辅助**

| 目标 | 原型行号（含） | 函数 |
|---|---|---|
| `web/js/render.js` | 1425–1441 | `rowHtml(id)` |
| `web/js/render.js` | 1443–1447 | `filteredItems()` |
| `web/js/render.js` | 1566–1571 | `toolCard(...)` |
| `web/js/render.js` | 1627–1632 | `filteredFresh()` |

三处增量（必须照做，否则后面视图搬不动）：

1. `function rowHtml` / `function filteredItems` / `function filteredFresh` → `export function …`；`const toolCard =` → `export const toolCard =`。
2. 本文件顶部加 `import { esc } from "./dom.js";` 与 `import { ic } from "./icons.js";`——原型里这两个是全局的，模块化后必须显式导入。
3. 四个函数都引用 `ITEMS` / `RESULT_ITEMS` / `FRESH_ITEMS`，加 `import { ITEMS, RESULT_ITEMS, FRESH_ITEMS } from "./sample.js";`。
4. `filteredItems` 与 `filteredFresh` 读 `state.filter` / `state.freshFilter`。**本任务先把 `state` 作为参数传入**：签名改为 `filteredItems(state)` / `filteredFresh(state)`，函数体里的 `state.filter` 保持不变。Task 4 引入 store 后由调用方传入。

```bash
python - <<'PY'
from pathlib import Path
src = Path("docs/ui-preview/prototype-v2.html").read_text(encoding="utf-8").splitlines(keepends=True)
def take(a, b): return "".join(src[a-1:b])
body = take(1425, 1441) + take(1443, 1447) + take(1566, 1571) + take(1627, 1632)
body = body.replace("function rowHtml(id) {", "export function rowHtml(id) {", 1)
body = body.replace("function filteredItems() {", "export function filteredItems(state) {", 1)
body = body.replace("const toolCard = (", "export const toolCard = (", 1)
body = body.replace("function filteredFresh() {", "export function filteredFresh(state) {", 1)
header = ('// 搬运自 prototype.html:1425-1441, 1443-1447, 1566-1571, 1627-1632。\n'
          '// 增量：顶层函数/常量改为 export；显式导入 esc/ic/数据表；\n'
          '// filteredItems/filteredFresh 改吃 state 参数（Task 4 起由调用方传 store.state）。\n'
          'import { esc } from "./dom.js";\n'
          'import { ic } from "./icons.js";\n'
          'import { ITEMS, RESULT_ITEMS, FRESH_ITEMS } from "./sample.js";\n\n')
Path("web/js/render.js").write_text(header + body, encoding="utf-8")
PY
grep -cE "^[[:space:]]*export (function|const)" web/js/render.js
grep -c "^import" web/js/render.js
```

Expected: `4`；`3`

- [ ] **Step 5: 运行测试确认通过**

```bash
PYTHONIOENCODING=utf-8 "C:/Users/ymc/Desktop/agent/_recon/probe-venv/Scripts/python.exe" scripts/selftest_web_ui.py
```

Expected: PASS（TokenTests 4 + SampleDataTests 2 + RenderHelperTests 5 = 11）

- [ ] **Step 6: 提交**

```bash
git add web/js/sample.js web/js/render.js scripts/selftest_web_ui.py
git commit -m "feat(web): port the prototype's sample data tables and render helpers"
```

---

## Task 4: 状态、路由、顶栏与标签栏

**Files:**
- Create: `web/js/store.js`、`web/js/router.js`、`web/js/shell.js`
- Modify: `web/js/main.js`（替换 Task 1 的占位）
- Test: `scripts/selftest_web_ui.py`（追加）

**Interfaces:**
- Consumes: `ic`（Task 2）、`esc`（Task 2）、`TOOL_PAGES`（Task 3）
- Produces:
  - `web/js/store.js` → `export const store`：`store.state`（与原型 `state` 同形）、`store.set(patch)`、`store.subscribe(fn)`
  - `web/js/router.js` → `export const routeOf`、`export const go`
  - `web/js/shell.js` → `export const TABS`、`export function renderAppbar(state)`、`export function renderTabbar(state)`
  - `web/js/main.js` → 导入即启动；导出 `export const render = ()`

- [ ] **Step 1: 搬运状态与路由**

| 目标 | 原型行号（含） |
|---|---|
| `web/js/store.js` | 1151–1165（`state`） |
| `web/js/router.js` | 1181–1182（`routeOf`、`go`；**不含** 1183 的 hashchange，它由 main.js 绑） |

```bash
python - <<'PY'
from pathlib import Path
src = Path("docs/ui-preview/prototype-v2.html").read_text(encoding="utf-8").splitlines(keepends=True)
def take(a, b): return "".join(src[a-1:b])
st = take(1151, 1165).replace("const state = {", "export const store = {", 1)
st = st.replace('  route: "home",', '  state: {\n    route: "home",', 1)
Path("web/js/store.js").write_text(
    "// 搬运自 prototype.html:1151-1165。形状与原型一致，外面套一层 store。\n"
    + st, encoding="utf-8")
PY
```

上面只做了一半——`store` 需要一个把 `state` 作为属性的包装。**本步骤直接写完整文件**，字段逐字取自原型 1152–1164：

```js
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
```

```bash
python - <<'PY'
from pathlib import Path
src = Path("docs/ui-preview/prototype-v2.html").read_text(encoding="utf-8").splitlines(keepends=True)
body = "".join(src[1180:1182])          # 1181-1182
body = body.replace("const routeOf =", "export const routeOf =", 1)
body = body.replace("const go =", "export const go =", 1)
Path("web/js/router.js").write_text(
    "// 搬运自 prototype.html:1181-1182。hashchange 的绑定在 main.js（原型的 1183 行）。\n"
    + body, encoding="utf-8")
PY
grep -cE "^[[:space:]]*export const (routeOf|go)" web/js/router.js
```

Expected: `2`

- [ ] **Step 2: 搬运顶栏与标签栏**

| 目标 | 原型行号（含） | 内容 |
|---|---|---|
| `web/js/shell.js` | 1186–1240 | `renderAppbar()` |
| `web/js/shell.js` | 1970–2003 | `TABS` + `renderTabbar()` |

增量：
1. `function renderAppbar()` → `export function renderAppbar(state)`，函数体把 `state.route` 等改为 `state.route`（形参同名，**函数体内一行不用改**——原型内部就写作 `state`）。
2. `function renderTabbar()` → `export function renderTabbar(state)`，同样函数体不动。
3. `const TABS = [` → `export const TABS = [`。
4. 顶部加 `import { esc } from "./dom.js";`、`import { ic } from "./icons.js";`、`import { TOOL_PAGES } from "./sample.js";`。

**注意**：把 `state` 作为形参、函数体一字不改，是为了让搬运真正做到逐字——原型函数体里所有 `state.x` 引用都保持不变。

```bash
python - <<'PY'
from pathlib import Path
src = Path("docs/ui-preview/prototype-v2.html").read_text(encoding="utf-8").splitlines(keepends=True)
def take(a, b): return "".join(src[a-1:b])
body = take(1186, 1240) + "\n" + take(1970, 2003)
body = body.replace("function renderAppbar() {", "export function renderAppbar(state) {", 1)
body = body.replace("function renderTabbar() {", "export function renderTabbar(state) {", 1)
body = body.replace("const TABS = [", "export const TABS = [", 1)
header = ('// 搬运自 prototype.html:1186-1240, 1970-2003。\n'
          '// 增量：函数改为 export 并接收 state 形参（函数体逐字未动，因为原型内部就写作 state）；\n'
          '// 显式导入 esc/ic/TOOL_PAGES。\n'
          'import { esc } from "./dom.js";\n'
          'import { ic } from "./icons.js";\n'
          'import { TOOL_PAGES } from "./sample.js";\n\n')
Path("web/js/shell.js").write_text(header + body, encoding="utf-8")
PY
grep -cE "^[[:space:]]*export (function (renderAppbar|renderTabbar)|const TABS)" web/js/shell.js
```

Expected: `3`

- [ ] **Step 3: 写失败的测试**

在 `scripts/selftest_web_ui.py` 的 `if __name__ == "__main__":` 块**之前**追加：

```python
class ShellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Browser.start()

    def test_tabbar_has_the_five_prototype_tabs(self):
        labels = _Browser.page.locator("#tabbar .tab").all_inner_texts()
        self.assertEqual([t.strip() for t in labels],
                         ["首页", "法规", "助手", "行动", "我的"])

    def test_assistant_tab_uses_the_raised_pill(self):
        self.assertEqual(_Browser.page.locator("#tabbar .tab--main").count(), 1)
        self.assertIn("助手", _Browser.page.locator("#tabbar .tab--main").inner_text())

    def test_active_tab_matches_the_prototype_mapping(self):
        """原型的映射：regulations/action/profile 前缀归各自标签，freshness 归首页。"""
        cases = [("home", "首页"), ("freshness", "首页"),
                 ("regulations", "法规"), ("regulations/map", "法规"),
                 ("action", "行动"), ("action/journey", "行动"),
                 ("profile", "我的"), ("profile/tutorial", "我的"),
                 ("assistant", "助手")]
        for route, expected in cases:
            with self.subTest(route=route):
                _Browser.goto(route)
                current = _Browser.page.locator('#tabbar [aria-current="page"]')
                self.assertEqual(current.count(), 1)
                self.assertIn(expected, current.inner_text())

    def test_result_route_highlights_no_tab(self):
        """原型对 result 不做归并，因此没有任何标签被标为当前页。"""
        _Browser.goto("result")
        self.assertEqual(_Browser.page.locator('#tabbar [aria-current="page"]').count(), 0)

    def test_appbar_gives_back_buttons_a_nav_action(self):
        """原型没有 back 这个 action；返回一律走 data-action="nav" data-to=父路由。"""
        _Browser.goto("regulations/map")
        back = _Browser.page.locator("#appbar button[aria-label='返回']")
        self.assertEqual(back.count(), 1)
        self.assertEqual(back.get_attribute("data-action"), "nav")
        self.assertEqual(back.get_attribute("data-to"), "regulations")

    def test_shell_mount_points_match_the_prototype(self):
        for node_id in ["shell", "appbar", "view", "dock", "tabbar",
                        "backdrop", "sheet", "toast"]:
            with self.subTest(node_id=node_id):
                self.assertEqual(_Browser.page.locator(f"#{node_id}").count(), 1)


class StoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Browser.start()

    def test_state_shape_matches_the_prototype(self):
        got = _Browser.page.evaluate("""async () => {
          const { store } = await import('/web/js/store.js');
          return Object.keys(store.state).sort();
        }""")
        self.assertEqual(got, sorted(["route", "chatStarted", "messages", "typing",
                                      "choices", "filter", "freshFilter", "tool",
                                      "toolGroup", "resultFrom", "searchDone",
                                      "query", "hasFreshness"]))

    def test_set_conditions_resets_the_result_origin(self):
        """Review Focus 4：换条件后不得沿用上一次的结果来源。"""
        got = _Browser.page.evaluate("""async () => {
          const { store } = await import('/web/js/store.js');
          store.reset();
          store.set({ resultFrom: 'home' });
          const before = store.state.resultFrom;
          store.setConditions({ freshFilter: '需处理' });
          return { before, after: store.state.resultFrom };
        }""")
        self.assertEqual(got["before"], "home")
        self.assertEqual(got["after"], "assistant")

    def test_subscribers_are_notified_and_can_unsubscribe(self):
        got = _Browser.page.evaluate("""async () => {
          const { store } = await import('/web/js/store.js');
          let hits = 0;
          const off = store.subscribe(() => { hits += 1; });
          store.set({ filter: '全部' });
          off();
          store.set({ filter: '需处理' });
          return hits;
        }""")
        self.assertEqual(got, 1)
```

- [ ] **Step 4: 写 `web/js/main.js`**

```js
// 启动：挂路由、渲染外壳、绑事件委托。
// render 的分派表与事件委托逐字对应 prototype.html:2006-2078 与 2351-2444。
import { ic } from "./icons.js";
import { store } from "./store.js";
import { routeOf, go } from "./router.js";
import { renderAppbar, renderTabbar } from "./shell.js";

const els = {
  appbar: document.getElementById("appbar"),
  view: document.getElementById("view"),
  dock: document.getElementById("dock"),
  tabbar: document.getElementById("tabbar"),
};

// Task 5 起逐个接入真实视图；在此之前视图为空，路由与外壳行为已可完整验证。
const VIEWS = {};

export const render = () => {
  const state = store.state;
  state.route = routeOf();
  const r = state.route;

  // 与原型 2010-2019 一致：工具组与工具名的解析
  if (r.startsWith("regulations/")) {
    state.toolGroup = "regulations";
    state.tool = r.split("/")[1] || null;
  } else if (r.startsWith("action/")) {
    state.toolGroup = "action";
    state.tool = r.split("/")[1] || null;
  } else {
    state.tool = null;
    state.toolGroup = null;
  }

  els.appbar.innerHTML = renderAppbar(state);
  els.tabbar.innerHTML = renderTabbar(state);

  // 本任务还没有任何视图，未知或无视图的路由渲染空白即可。
  // 原型 2068-2071 的未知路由回落（go("home")）**不在这里**：它要等首页视图存在
  // 才有可观测性，且若在此处生效，每条路由都会回落，外壳行为全部失真。见 Task 6。
  const view = VIEWS[r];
  els.view.className = "view";
  els.view.innerHTML = view ? view(state) : "";
  els.view.scrollTop = 0;
  els.dock.innerHTML = "";
};

window.addEventListener("hashchange", () => { store.state.route = routeOf(); render(); });

document.addEventListener("click", (event) => {
  const el = event.target.closest("[data-action]");
  if (!el) return;
  const action = el.dataset.action;
  if (action === "nav") {
    go(el.dataset.to || "assistant");          // 原型 2358：nav 默认去 assistant
  } else if (action === "open-tool") {
    go((el.dataset.group || "regulations") + "/" + el.dataset.tool);
  }
  // 其余 action 由 Task 5 起的任务逐个接入。
});

store.state.route = routeOf();
render();
```

**注意**：`nav` 默认目标是 `assistant`（原型 2358 行 `go(el.dataset.to || "assistant")`），不是 `home`——先前那版计划写成了 home 并把返回按钮做成自创的 `back` action。

- [ ] **Step 5: 运行测试确认通过**

```bash
PYTHONIOENCODING=utf-8 "C:/Users/ymc/Desktop/agent/_recon/probe-venv/Scripts/python.exe" scripts/selftest_web_ui.py
```

Expected: PASS（ShellTests 6 + StoreTests 3 全通过，既有类无回归）

- [ ] **Step 6: 提交**

```bash
git add web/js/store.js web/js/router.js web/js/shell.js web/js/main.js scripts/selftest_web_ui.py
git commit -m "feat(web): state, routing, appbar and tabbar ported from the prototype"
```

---

## Task 5: 底部抽屉与轻提示

**Files:**
- Create: `web/js/ui/sheet.js`、`web/js/ui/toast.js`
- Modify: `web/js/main.js`（接入 `close-sheet` 与 Escape）
- Test: `scripts/selftest_web_ui.py`（追加）

**Interfaces:**
- Consumes: `#sheet` / `#backdrop` / `#toast` 挂载点（Task 1）；`.is-on` 类（Task 3 搬运的 `shell.css`）
- Produces:
  - `web/js/ui/sheet.js` → `export function openSheet(html)`、`export function closeSheet()`
  - `web/js/ui/toast.js` → `export function showToast(text)`

**原型对照**：抽屉 `prototype.html:2322-2333`；轻提示 `2147-2152`。动画全在 CSS（`.sheet` 默认 `translateY(103%)`、`.is-on` 归零），JS 只管类名与 aria——与原型一致，本任务不写动画。

- [ ] **Step 1: 搬运样式层（shell / components / views）**

**这一步是上一版计划的重大遗漏**：File Structure 表里写着这三个文件是【搬运】，但**没有任何任务步真的去搬**，于是它们一直停在 Task 1 的 33 字节占位，整个视觉层缺失——Tasks 6–9 会渲染出没样式的页面，Task 10 的覆盖没有可覆盖的对象，Task 11 的像素比对会大面积失败。

| 目标 | 原型行号（含） | 内容 |
|---|---|---|
| `web/styles/shell.css` | 71–148 | 手机壳（含 `@media (min-width: 700px)`）、顶栏、主滚动区 |
| `web/styles/shell.css` | 552–639 | 输入区、底部导航 |
| `web/styles/shell.css` | 781–881 | 抽屉、轻提示、可访问性（**881 为终点**，882 是 `</style>`） |
| `web/styles/components.css` | 434–445 | 通用页头 |
| `web/styles/components.css` | 527–551 | 按钮 |
| `web/styles/views.css` | 149–433 | 首页、工作台首页、首次使用态、教程、法规中心/行动入口、时效性检查、对话 |
| `web/styles/views.css` | 446–526 | 结果页 |
| `web/styles/views.css` | 640–780 | 法规库、检索、我的 |

```bash
python - <<'PY'
from pathlib import Path
src = Path("docs/ui-preview/prototype-v2.html").read_text(encoding="utf-8").splitlines(keepends=True)
def take(a, b): return "".join(src[a-1:b])
Path("web/styles/shell.css").write_text(
    "/* 搬运自 prototype.html:71-148, 552-639, 781-881。未做改动。 */\n"
    + take(71, 148) + take(552, 639) + take(781, 881), encoding="utf-8")
Path("web/styles/components.css").write_text(
    "/* 搬运自 prototype.html:434-445, 527-551。未做改动。 */\n"
    + take(434, 445) + take(527, 551), encoding="utf-8")
Path("web/styles/views.css").write_text(
    "/* 搬运自 prototype.html:149-433, 446-526, 640-780。未做改动。 */\n"
    + take(149, 433) + take(446, 526) + take(640, 780), encoding="utf-8")
PY
```

【搬运】校验（每节都要留下可辨识的规则；**不要锚定行首**，原型 CSS 带两空格缩进）：

```bash
grep -c "\.app-shell\|\.appbar\|\.tabbar\|\.tab--main" web/styles/shell.css
grep -c "\.composer\|\.dock\|\.sheet\|\.backdrop\|\.toast" web/styles/shell.css
grep -c "\.page-head\|\.btn" web/styles/components.css
grep -c "\.wb-head\|\.fresh-card\|\.reco\|\.row\|\.tool" web/styles/views.css
```

Expected: 四行均 ≥ 3。

**这一步做完后，本任务那条 `test_backdrop_click_closes_the_sheet` 才会通过**——`#backdrop` 需要原型 782-799 的 `position:absolute; inset:0`。

- [ ] **Step 2: 写失败的测试**

在 `scripts/selftest_web_ui.py` 的 `if __name__ == "__main__":` 块**之前**追加。追加到末尾会让新测试类定义晚于 `unittest.main()`，用例被**静默跳过**（输出仍显 PASS）。追加后确认运行输出里出现了本任务新增的用例名。

```python
class SheetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Browser.start()

    def setUp(self):
        _Browser.goto("home")
        _Browser.page.evaluate(
            "async () => { const s = await import('/web/js/ui/sheet.js'); s.closeSheet(); }")

    def _open(self, html='<div class="sheet__body"><h2>详情</h2></div>'):
        _Browser.page.evaluate(
            "async (h) => { const s = await import('/web/js/ui/sheet.js'); s.openSheet(h); }", html)

    def test_open_and_close_toggle_the_prototype_classes(self):
        self._open()
        self.assertIn("is-on", _Browser.page.locator("#sheet").get_attribute("class"))
        self.assertIn("is-on", _Browser.page.locator("#backdrop").get_attribute("class"))
        self.assertEqual(_Browser.page.locator("#sheet").get_attribute("aria-hidden"), "false")
        _Browser.page.evaluate(
            "async () => { const s = await import('/web/js/ui/sheet.js'); s.closeSheet(); }")
        self.assertNotIn("is-on", _Browser.page.locator("#sheet").get_attribute("class"))
        self.assertNotIn("is-on", _Browser.page.locator("#backdrop").get_attribute("class"))
        self.assertEqual(_Browser.page.locator("#sheet").get_attribute("aria-hidden"), "true")

    def test_sheet_is_marked_dialog_and_modal_from_the_markup(self):
        self.assertEqual(_Browser.page.locator("#sheet").get_attribute("role"), "dialog")
        self.assertEqual(_Browser.page.locator("#sheet").get_attribute("aria-modal"), "true")

    def test_escape_closes_the_sheet(self):
        self._open()
        _Browser.page.keyboard.press("Escape")
        _Browser.page.wait_for_timeout(200)
        self.assertNotIn("is-on", _Browser.page.locator("#sheet").get_attribute("class"))

    def test_backdrop_click_closes_the_sheet(self):
        """backdrop 自带 data-action="close-sheet"（原型 891 行），走事件委托关闭。"""
        self._open()
        _Browser.page.locator("#backdrop").click(force=True)
        _Browser.page.wait_for_timeout(250)
        self.assertNotIn("is-on", _Browser.page.locator("#sheet").get_attribute("class"))

    def test_sheet_content_is_escaped_by_the_caller(self):
        """Review Focus 1：esc 之后再注入的内容不得被解析成元素。"""
        _Browser.page.evaluate(
            "async () => { const d = await import('/web/js/dom.js');"
            "const s = await import('/web/js/ui/sheet.js');"
            "s.openSheet('<div class=\"sheet__body\"><p id=probe>' + d.esc('<b>x</b>') + '</p></div>'); }")
        self.assertEqual(_Browser.page.locator("#probe").locator("b").count(), 0)


class ToastTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Browser.start()

    def test_toast_shows_then_hides_after_2400ms(self):
        _Browser.page.evaluate(
            "async () => { const t = await import('/web/js/ui/toast.js'); t.showToast('先写一句你的产品'); }")
        self.assertIn("is-on", _Browser.page.locator("#toast").get_attribute("class"))
        self.assertEqual(_Browser.page.locator("#toast").inner_text(), "先写一句你的产品")
        _Browser.page.wait_for_timeout(2600)
        self.assertNotIn("is-on", _Browser.page.locator("#toast").get_attribute("class"))

    def test_second_toast_restarts_the_timer(self):
        got = _Browser.page.evaluate("""async () => {
          const t = await import('/web/js/ui/toast.js');
          t.showToast('第一条');
          await new Promise(r => setTimeout(r, 1800));
          t.showToast('第二条');
          await new Promise(r => setTimeout(r, 1200));
          return document.getElementById('toast').classList.contains('is-on');
        }""")
        self.assertTrue(got, "第二次提示必须重新计时，而不是沿用第一次留下的定时器")
```

- [ ] **Step 3: 运行测试确认失败**

```bash
PYTHONIOENCODING=utf-8 "C:/Users/ymc/Desktop/agent/_recon/probe-venv/Scripts/python.exe" scripts/selftest_web_ui.py SheetTests ToastTests
```

Expected: FAIL —— `/web/js/ui/sheet.js` 尚不存在

- [ ] **Step 4: 搬运抽屉与轻提示**

| 目标 | 原型行号（含） |
|---|---|
| `web/js/ui/sheet.js` | 2322–2333 |
| `web/js/ui/toast.js` | 2147–2152 |

增量（三条）：

1. `function openSheet` / `function closeSheet` / `function showToast` → `export function …`。
2. 原型用模块顶层常量 `sheet` / `backdrop` / `toast` 持有 DOM 句柄（原型 1172–1174）。模块化后**不要在导入期取 DOM**（导入可能早于解析到这些节点）；改为在函数内 `document.getElementById(...)`。
3. `showToast` 里的**函数属性** `showToast._t`（原型 2150-2151 把计时器挂在函数对象上，不是挂在 DOM 节点上）改为模块内的 `let timer`。`window.clearTimeout(showToast._t)` → `if (timer) clearTimeout(timer)`，`showToast._t = window.setTimeout(...)` → `timer = setTimeout(...)`。

先把原文看清楚：

```bash
python - <<'PY'
from pathlib import Path
src = Path("docs/ui-preview/prototype-v2.html").read_text(encoding="utf-8").splitlines(keepends=True)
def take(a, b): return "".join(src[a-1:b])
Path(".superpowers/sdd/2026-10-20-frontend-spa-m1/_sheet_raw.js").write_text(take(2322, 2333), encoding="utf-8")
Path(".superpowers/sdd/2026-10-20-frontend-spa-m1/_toast_raw.js").write_text(take(2147, 2152), encoding="utf-8")
PY
cat .superpowers/sdd/2026-10-20-frontend-spa-m1/_sheet_raw.js
echo '--- toast ---'
cat .superpowers/sdd/2026-10-20-frontend-spa-m1/_toast_raw.js
```

**下面两段代码是"搬运后应有的结果"，用来对照——但优先做法是逐字搬运 2322-2333 / 2147-2152，再只应用上述三条增量。** 手写替换会丢行：上一版计划手写 `closeSheet` 时就漏了原型 2332 的 300ms 清理语句。若你选择逐字搬运（推荐），务必用 diff 确认除枚举增量外与原型逐字节一致。

```js
// web/js/ui/sheet.js —— 搬运自 prototype.html:2322-2333。
// 增量：导出；DOM 句柄改为函数内查找（不在导入期取）。
const sheetEl = () => document.getElementById("sheet");
const backdropEl = () => document.getElementById("backdrop");

export function openSheet(html) {
  const sheet = sheetEl();
  sheet.innerHTML = html;
  backdropEl().classList.add("is-on");
  sheet.classList.add("is-on");
  sheet.setAttribute("aria-hidden", "false");
}

export function closeSheet() {
  const sheet = sheetEl();
  backdropEl().classList.remove("is-on");
  sheet.classList.remove("is-on");
  sheet.setAttribute("aria-hidden", "true");
  // 原型 2332：关闭动画（.28s）走完后清空抽屉内容。
  // 这一句容易在"手写替换"时丢掉——上一版计划就丢了。
  window.setTimeout(() => {
    if (!sheet.classList.contains("is-on")) sheet.innerHTML = "";
  }, 300);
}
```

```js
// web/js/ui/toast.js —— 搬运自 prototype.html:2147-2152。
// 增量：导出；计时器从挂在 DOM 节点上的 toast._t 改为模块内变量。
const DURATION = 2400;
let timer = null;

export function showToast(text) {
  const toast = document.getElementById("toast");
  toast.textContent = text;
  toast.classList.add("is-on");
  if (timer) clearTimeout(timer);
  timer = setTimeout(() => toast.classList.remove("is-on"), DURATION);
}
```

**关键**：改写时必须保持原型那三行**赋值顺序**（先 `backdrop` 后 `sheet`）与 `aria-hidden` 的取值，测试会核对。

- [ ] **Step 5: 在 `main.js` 接入 `close-sheet` 与 Escape**

导入区加：

```js
import { closeSheet } from "./ui/sheet.js";
```

事件委托里，在 `open-tool` 分支之后补：

```js
  } else if (action === "close-sheet") {
    closeSheet();
```

**同时给已有的 `nav` 分支补上 `closeSheet();`**——原型 2356-2358 是：

```js
    if (action === "nav") {
      closeSheet();
      go(el.dataset.to || "assistant");
    }
```

Task 4 只写了 `go(...)`，漏了 `closeSheet()`。**这一句是有实际作用的**：`PROFILE_SHEETS.conditions()` 的抽屉里渲染了一个 `data-action="nav" data-to="assistant"` 按钮（原型 2226），而抽屉（z-index 70）盖在背景层（60）之上，所以那次点击进的是 `nav` 分支而不是背景层的 `close-sheet`。少了这句，点「回对话修改」会导航到助手页，**而抽屉仍盖在新页面上面**。把 `nav` 分支改成：

```js
  } else if (action === "nav") {
    closeSheet();
    go(el.dataset.to || "assistant");

文件底部 `render();` 之前加：

```js
document.addEventListener("keydown", (event) => {
  const sheet = document.getElementById("sheet");
  if (event.key === "Escape" && sheet.classList.contains("is-on")) closeSheet();
});
```

**注意**：Escape 必须带 `classList.contains("is-on")` 判断——与原型 2443 行一致，否则无关的 Escape 也会触发关闭。

- [ ] **Step 6: 运行测试确认通过**

```bash
PYTHONIOENCODING=utf-8 "C:/Users/ymc/Desktop/agent/_recon/probe-venv/Scripts/python.exe" scripts/selftest_web_ui.py
```

Expected: PASS（SheetTests 5 + ToastTests 2 全通过，既有类无回归）

- [ ] **Step 7: 提交**

```bash
git add web/js/ui/sheet.js web/js/ui/toast.js web/js/main.js scripts/selftest_web_ui.py
git commit -m "feat(web): bottom sheet and toast ported from the prototype"
```

---

## Task 6: 首页、结果页、时效性检查

**Files:**
- Create: `web/js/views/home.js`、`web/js/views/result.js`、`web/js/views/freshness.js`
- Modify: `web/js/main.js`（注册三个视图 + 接入 `fresh-filter`）
- Test: `scripts/selftest_web_ui.py`（追加）

**Interfaces:**
- Consumes: `esc`、`ic`（Task 2）；`ITEMS`、`TOOL_PAGES`、`FRESH_ITEMS`、`PRIORITIES`、`RESULT_ITEMS`（Task 3）；`rowHtml`、`filteredFresh`、`filteredItems`（Task 3）；`store`（Task 4）
- Produces: 三个视图模块，各 `export function render(state) -> string`（本任务实际导出名为 `homeView` / `resultView` / `freshnessView`，注册进 `main.js` 的 `VIEWS`）

**本任务起所有视图任务的通用约定**：视图函数**接收 `state` 形参、函数体逐字不动**。原型函数体内部就写作 `state`、`ITEMS`、`rowHtml`、`ic`、`esc`——模块化后只要用导入与形参把这些名字提供出来，**标记与逻辑一个字符都不用改**。这正是本计划不再出现自创类名的原因。

- [ ] **Step 1: 搬运三个视图**

| 目标 | 原型行号（含） | 内容 |
|---|---|---|
| `web/js/views/home.js` | 1295–1372 | `homeView()` 的 `return` 主体；**须剔掉第 1372 行末尾那个 `<button class="proto-toggle" data-action="toggle-freshness">`**，并在第 1370 行的 `</div>` 处闭合模板（**不要取到 1373 行**——那是原函数的闭合 `}`，叠加 wrapper 的 `}` 会使花括号不配平） |
| `web/js/views/result.js` | 1449–1491 | `resultView()` 全文 |
| `web/js/views/freshness.js` | 1494–1563 | `freshnessView()` 全文 |

**唯一要从 home 剔掉的东西**：原型 1269–1293 是 `homeView()` 开头，含 `if (!state.hasFreshness)` 的"首次使用"分支，其末尾 1291 行是一个 `<button class="proto-toggle" …>原型：查看有记录状态</button>`。**这是原型用来演示两种状态的开关，不进产品**。所以 `home.js` 只搬 1295–1373；store 里保留 `hasFreshness` 字段（Task 4 按原型形状保留），但 M1 不渲染首次使用分支。

```bash
python - <<'PY'
from pathlib import Path
src = Path("docs/ui-preview/prototype-v2.html").read_text(encoding="utf-8").splitlines(keepends=True)
def take(a, b): return "".join(src[a-1:b])

IMPORTS = ('import { esc } from "../dom.js";\n'
           'import { ic } from "../icons.js";\n'
           'import { ITEMS, TOOL_PAGES, FRESH_ITEMS, PRIORITIES, RESULT_ITEMS } from "../sample.js";\n'
           'import { rowHtml, filteredFresh, filteredItems } from "../render.js";\n\n')

specs = [
    ("home.js",      1295, 1372, "export function homeView(state) {\n"
        + take(1295, 1372).replace(
            '      <button class="proto-toggle" data-action="toggle-freshness">原型：查看首次使用态</button>`;',
            "    `;") + "}\n"),
    ("result.js",    1449, 1491, None),
    ("freshness.js", 1494, 1563, None),
]
for name, a, b, custom in specs:
    if custom is not None:
        body = custom
    else:
        body = take(a, b)
        if name == "result.js":
            body = body.replace("function resultView() {", "export function resultView(state) {", 1)
        else:
            body = body.replace("function freshnessView() {", "export function freshnessView(state) {", 1)
    Path(f"web/js/views/{name}").write_text(
        f"// 搬运自 prototype.html:{a}-{b}。函数体逐字未动，仅补头部导入与 export。\n"
        + IMPORTS + body, encoding="utf-8")
PY
grep -c "export function" web/js/views/home.js web/js/views/result.js web/js/views/freshness.js
grep -c "proto-toggle\|hasFreshness" web/js/views/home.js
```

Expected: 第一个 grep 三个文件各 `1`；第二个 grep 为 `0`（演示开关必须已被剔除）

注意 `home.js` 用的是 `custom` 分支：因为 1295 行是 `return \`` 而不是函数声明行，需手工补上 `export function homeView(state) {` 与外层 `}`。搬运后**自查花括号是否配平**（`return` 的模板字符串以 `` `; `` 结束，其后补 `}`）。

- [ ] **Step 2: 写失败的测试**

在 `scripts/selftest_web_ui.py` 的 `if __name__ == "__main__":` 块**之前**追加：

```python
class HomeViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Browser.start()

    def test_headline_and_context_match_the_prototype(self):
        _Browser.goto("home")
        view = _Browser.page.locator("#view")
        self.assertIn("最近检查", view.inner_text())
        for label in ["儿童玩具", "德国", "亚马逊"]:
            with self.subTest(label=label):
                self.assertIn(label, view.inner_text())

    def test_freshness_card_uses_the_prototype_classes(self):
        _Browser.goto("home")
        for sel in [".fresh-card", ".fresh-card__head", ".fresh-card__title",
                    ".monitor-pill", ".fresh-card__time"]:
            with self.subTest(sel=sel):
                self.assertEqual(_Browser.page.locator(f"#view {sel}").count(), 1,
                                 f"{sel} 必须存在（原型类名）")
        for wrong in [".fresh-card__top", ".fresh-card__at", ".pill"]:
            with self.subTest(wrong=wrong):
                self.assertEqual(_Browser.page.locator(f"#view {wrong}").count(), 0,
                                 f"{wrong} 是自创类名，必须不存在")

    def test_readonly_card_states_its_own_scope(self):
        _Browser.goto("home")
        text = _Browser.page.locator("#view").inner_text()
        self.assertIn("无需手动操作", text)
        self.assertIn("不等于法规条文变更", text)

    def test_first_run_toggle_is_not_shipped(self):
        _Browser.goto("home")
        self.assertEqual(_Browser.page.locator("#view .proto-toggle").count(), 0)

class ResultViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Browser.start()

    def test_priority_block_and_rows_are_present(self):
        _Browser.goto("result")
        self.assertIn("现在先做", _Browser.page.locator("#view").inner_text())
        self.assertGreaterEqual(_Browser.page.locator("#view .row").count(), 1)

    def test_rows_carry_the_prototype_inner_markup(self):
        _Browser.goto("result")
        for sel in [".row__rail", ".row__body", ".row__top", ".row__title",
                    ".row__sub", ".row__status", ".row__end"]:
            with self.subTest(sel=sel):
                self.assertGreaterEqual(_Browser.page.locator(f"#view {sel}").count(), 1)
        self.assertEqual(_Browser.page.locator("#view .row__copy").count(), 0,
                         "row__copy 是自创类名，必须不存在")


class FreshnessViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Browser.start()

    def test_page_head_and_meta_match_the_prototype(self):
        _Browser.goto("freshness")
        view = _Browser.page.locator("#view")
        self.assertIn("09:00 / 21:00", view.inner_text())
        self.assertEqual(_Browser.page.locator("#view .page-head__meta.mono").count(), 1)

    def test_fresh_card_uses_the_prototype_classes(self):
        _Browser.goto("freshness")
        for sel in [".fresh-card", ".fresh-card__head", ".fresh-card__title",
                    ".monitor-pill", ".fresh-card__time", ".fresh-card__sub"]:
            with self.subTest(sel=sel):
                self.assertEqual(_Browser.page.locator(f"#view {sel}").count(), 1)
        self.assertEqual(_Browser.page.locator("#view .fresh-count").count(), 4)
        self.assertEqual(_Browser.page.locator("#view .fresh-count--warn").count(), 1)

    def test_check_history_rows_are_plain_not_buttons(self):
        """这两行是只读的检查记录，原型用 div.row，不是可点的 button.row。"""
        _Browser.goto("freshness")
        self.assertGreaterEqual(_Browser.page.locator("#view div.row").count(), 2)

    def test_pending_links_are_real_anchors_with_external_icons(self):
        _Browser.goto("freshness")
        links = _Browser.page.locator("#view a.row")
        self.assertGreaterEqual(links.count(), 1)
        for i in range(links.count()):
            with self.subTest(i=i):
                self.assertTrue(links.nth(i).get_attribute("href"))
                self.assertEqual(links.nth(i).get_attribute("target"), "_blank")

    def test_scope_note_is_present(self):
        _Browser.goto("freshness")
        self.assertEqual(_Browser.page.locator("#view .fresh-note").count(), 1)

    def test_this_route_has_no_filter_buttons(self):
        """筛选属于 toolView 的 freshness 定制页（原型里无可达入口），不在本路由。"""
        _Browser.goto("freshness")
        self.assertEqual(
            _Browser.page.locator("#view button[data-action='fresh-filter']").count(), 0,
            "freshnessView 是静态页，不应有筛选按钮")

    def test_invented_classes_are_absent(self):
        _Browser.goto("freshness")
        for wrong in [".fresh-card__top", ".fresh-card__at", ".pill", ".row__copy"]:
            with self.subTest(wrong=wrong):
                self.assertEqual(_Browser.page.locator(f"#view {wrong}").count(), 0)
```

- [ ] **Step 3: 运行测试确认失败**

```bash
PYTHONIOENCODING=utf-8 "C:/Users/ymc/Desktop/agent/_recon/probe-venv/Scripts/python.exe" scripts/selftest_web_ui.py HomeViewTests ResultViewTests FreshnessViewTests
```

Expected: FAIL —— 三个视图尚未注册

- [ ] **Step 4: 在 `main.js` 注册视图并接入 `fresh-filter`**

把 `const VIEWS = {};` 替换为：

```js
import { homeView } from "./views/home.js";
import { resultView } from "./views/result.js";
import { freshnessView } from "./views/freshness.js";

const VIEWS = {
  home: homeView,
  result: resultView,
  freshness: freshnessView,
};
```

**本任务不装未知路由回落**——判据是"**当且仅当所有其它路由都已有视图时**，回落才可观测"。
Task 6 时 12 条路由仍有 9 条无视图（assistant / regulations(/*) / action(/*) / profile(/*)），
回落会对它们一视同仁地触发，外壳行为的断言会因"每条路由都变成首页"而集体失真——
这正是当初把它从 Task 4 挪走的原因，而它在此处**依然成立**。它落在 Task 9（最后一个视图任务）。

事件委托里，在 `open-tool` 分支之后加：

```js
  } else if (action === "fresh-filter") {
    store.set({ freshFilter: el.dataset.filter || "全部" });
    render();
```

**注意**：原型读 `el.dataset.filter`（2376 行），**不是** `data-value`——先前那版计划写成了 `data-value`。

- [ ] **Step 5: 运行测试确认通过**

```bash
PYTHONIOENCODING=utf-8 "C:/Users/ymc/Desktop/agent/_recon/probe-venv/Scripts/python.exe" scripts/selftest_web_ui.py
```

Expected: PASS（HomeViewTests 4 + ResultViewTests 2 + FreshnessViewTests 7 全通过，既有类无回归）

- [ ] **Step 6: 提交**

```bash
git add web/js/views/home.js web/js/views/result.js web/js/views/freshness.js web/js/main.js scripts/selftest_web_ui.py
git commit -m "feat(web): home, result and freshness views ported from the prototype"
```

---

## Task 7: 助手（欢迎页、对话页、输入区）

**Files:**
- Create: `web/js/views/assistant.js`、`web/js/ui/composer.js`
- Modify: `web/js/main.js`（注册 assistant 视图 + 接入 `prompt`/`choice`/`new-chat`/`history`/`quick` + `compose` 表单提交）
- Test: `scripts/selftest_web_ui.py`（追加）

**Interfaces:**
- Consumes: `esc`、`ic`（Task 2）；`START`（Task 3）；`store`（Task 4）；`openSheet`（Task 5）；`showToast`（Task 5）
- Produces:
  - `web/js/views/assistant.js` → `export function assistantWelcomeView(state)`、`export function chatView(state)`、`export function render(state)`（`render` 按 `state.messages.length` 二选一，与原型 2029 行一致）
  - `web/js/ui/composer.js` → `export function composerDock(state)`、`export function bindComposer(onSend)`、`export function send(text)`、`export function choose(value)`、`export function newChat()`

**原型对照**：欢迎页 `1250-1267`；对话页 `1376-1422`；输入区 `1946-1967`；`bindComposer` `2335-2348`；`send`/`choose`/`newChat` 在 `2080-2349` 交互段内。

- [ ] **Step 1: 搬运欢迎页与对话页**

| 目标 | 原型行号（含） | 内容 |
|---|---|---|
| `web/js/views/assistant.js` | 1250–1267 | `assistantWelcomeView()` |
| `web/js/views/assistant.js` | 1376–1422 | `messageHtml(m, index)` + `chatView()` |

增量只有三条：

1. `function assistantWelcomeView()` → `export function assistantWelcomeView(state)`；`function chatView()` → `export function chatView(state)`；`function messageHtml(m, index)` → `function messageHtml(m, index)`（内部函数，不导出）。
2. 顶部补导入：`import { esc } from "../dom.js";`、`import { ic } from "../icons.js";`、`import { START } from "../sample.js";`。
3. 文件末尾加 `render` 分发：

```js
/** 与原型 2029 行一致：有消息就渲染对话页，否则渲染欢迎页。 */
export function render(state) {
  return state.messages.length ? chatView(state) : assistantWelcomeView(state);
}
```

**验证要点**：欢迎页用的是 `data-action="prompt" data-prompt="…"`，**不是** `data-action="starter"`——先前那版计划自创了 `starter`/`data-text`。

```bash
python - <<'PY'
from pathlib import Path
src = Path("docs/ui-preview/prototype-v2.html").read_text(encoding="utf-8").splitlines(keepends=True)
def take(a, b): return "".join(src[a-1:b])
body = take(1250, 1267) + "\n" + take(1376, 1422)
body = body.replace("function assistantWelcomeView() {",
                    "export function assistantWelcomeView(state) {", 1)
body = body.replace("function chatView() {", "export function chatView(state) {", 1)
body += ('\n/** 与原型 2029 行一致：有消息则对话页，否则欢迎页。 */\n'
         'export function render(state) {\n'
         '  return state.messages.length ? chatView(state) : assistantWelcomeView(state);\n'
         '}\n')
header = ('// 搬运自 prototype.html:1250-1267, 1376-1422。函数体逐字未动。\n'
          'import { esc } from "../dom.js";\n'
          'import { ic } from "../icons.js";\n'
          'import { START } from "../sample.js";\n\n')
Path("web/js/views/assistant.js").write_text(header + body, encoding="utf-8")
PY
grep -c "data-action=\"prompt\"" web/js/views/assistant.js
grep -c "starter" web/js/views/assistant.js
```

Expected: 第一个 `1`（`START.map` 那一行）；第二个 `0`（自创 action 必须不存在）

- [ ] **Step 2: 搬运输入区**

| 目标 | 原型行号（含） |
|---|---|
| `web/js/ui/composer.js` | 1946–1967（`composerDock`） |
| `web/js/ui/composer.js` | 2335–2348（`bindComposer`） |

增量：
1. `function composerDock()` → `export function composerDock(state)`；`function bindComposer()` → `export function bindComposer()`。
2. 顶部导入：`import { esc } from "../dom.js";`、`import { ic } from "../icons.js";`。
3. `bindComposer` 原型内直接调 `send()` 与 `render()`（全局）。模块化后改为**接收回调**：签名 `export function bindComposer(onSend)`，函数体里把 `send(ta.value)` 改为 `onSend(ta.value)`。原型那一处提交处理器（`data-form="compose"`）也一并接过来。

**注意**：`composerDock` 用的是 `<form class="composer" data-form="compose">` + `<button type="submit">`，**不是** `data-action="send"` 按钮；麦克风类是 `.composer__tool`，**不是** `composer__mic`。这两处先前那版计划都写错了。

- [ ] **Step 3: 搬运 `send` / `choose` / `newChat`**

这三个函数在原型交互段（2080–2349）内。用 Read 工具打开 `prototype.html` 的 2080–2349，定位 `function send(`、`function choose(`、`function newChat(`，把三个函数**逐字**搬进 `web/js/views/assistant.js`，仅加 `export`。

`send` 里对 `state.messages` 的推送与 `state.choices` 的更新保持原样；`newChat()` 里重置的字段与本项目 store 的字段名一致（Task 4 已按原型形状保留）。

**M1 的数据边界**：原型的 `send()` 末尾会往 `state.messages` 里推一段**演示用的助手回复**。M1 明确不接后端（规格第 11 节：先壳与路由 + 示例数据），因此**保留那段演示回复不动**，并在其上一行加注释：

```js
    // M1：壳与路由阶段，此处用示例回复；M2 换成 POST /api/route 的返回。
```

- [ ] **Step 4: 写失败的测试**

在 `scripts/selftest_web_ui.py` 的 `if __name__ == "__main__":` 块**之前**追加：

```python
class AssistantViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Browser.start()

    def setUp(self):
        _Browser.goto("assistant")
        _Browser.page.evaluate("""async () => {
          const a = await import('/web/js/views/assistant.js');
          if (a.newChat) a.newChat();
        }""")

    def test_welcome_page_matches_the_prototype(self):
        _Browser.goto("assistant")
        text = _Browser.page.locator("#view").inner_text()
        self.assertIn("我是合规雷达", text)
        self.assertIn("告诉我你卖什么、卖到哪里。", text)
        self.assertIn("可以这样开始", text)
        self.assertIn("教程在「我的」里。", text)

    def test_welcome_offers_four_prompts_with_the_lead_ones_tinted(self):
        _Browser.goto("assistant")
        self.assertEqual(_Browser.page.locator("#view .reco").count(), 4)
        self.assertEqual(_Browser.page.locator("#view .reco--lead").count(), 2)
        first = _Browser.page.locator("#view .reco").first
        self.assertEqual(first.get_attribute("data-action"), "prompt")
        self.assertTrue(first.get_attribute("data-prompt"))

    def test_composer_is_a_form_with_tool_and_submit(self):
        _Browser.goto("assistant")
        self.assertEqual(_Browser.page.locator("#dock form.composer").count(), 1)
        self.assertEqual(_Browser.page.locator("#dock form.composer").get_attribute("data-form"),
                         "compose")
        self.assertEqual(_Browser.page.locator("#dock .composer__tool").count(), 1)
        self.assertEqual(_Browser.page.locator("#dock button[type='submit']").count(), 1)
        self.assertEqual(_Browser.page.locator("#dock .composer__mic").count(), 0,
                         "composer__mic 是自创类名，必须不存在")

    def test_submitting_the_form_sends_and_switches_to_the_thread(self):
        _Browser.goto("assistant")
        _Browser.page.locator("#dock textarea").fill("毛绒玩具卖到德国亚马逊")
        _Browser.page.locator("#dock button[type='submit']").click()
        _Browser.page.wait_for_timeout(400)
        self.assertIn("毛绒玩具卖到德国亚马逊", _Browser.page.locator("#view").inner_text())

    def test_quickbar_appears_only_once_a_conversation_started(self):
        _Browser.goto("assistant")
        self.assertEqual(_Browser.page.locator("#dock .quickbar").count(), 0)
        _Browser.page.locator("#dock textarea").fill("测试")
        _Browser.page.locator("#dock button[type='submit']").click()
        _Browser.page.wait_for_timeout(400)
        self.assertEqual(_Browser.page.locator("#dock .quickbar").count(), 1)
        self.assertEqual(_Browser.page.locator("#dock .quickbar .chip").count(), 4)

    def test_message_text_with_html_is_shown_literally(self):
        """Review Focus 1：消息含 HTML 时必须原样显示为文本。"""
        _Browser.goto("assistant")
        _Browser.page.locator("#dock textarea").fill("<b>粗体</b> 卖到德国")
        _Browser.page.locator("#dock button[type='submit']").click()
        _Browser.page.wait_for_timeout(400)
        view = _Browser.page.locator("#view")
        self.assertIn("<b>粗体</b> 卖到德国", view.inner_text())
```

- [ ] **Step 5: 运行测试确认失败**

```bash
PYTHONIOENCODING=utf-8 "C:/Users/ymc/Desktop/agent/_recon/probe-venv/Scripts/python.exe" scripts/selftest_web_ui.py AssistantViewTests
```

Expected: FAIL —— assistant 视图尚未注册

- [ ] **Step 6: 在 `main.js` 注册并接入 action**

导入区加：

```js
import { render as assistantRender, send, choose, newChat } from "./views/assistant.js";
import { composerDock, bindComposer } from "./ui/composer.js";
import { openSheet } from "./ui/sheet.js";
import { showToast } from "./ui/toast.js";
import { PROFILE_SHEETS } from "./sample.js";
```

`VIEWS` 里加 `assistant: assistantRender`。

`render()` 里，先把视图的 className 按路由设置（原型 2030 行只给对话页加 `view--chat`，其余都是 `view`）：：

```js
  els.view.className = r === "assistant" ? "view view--chat" : "view";
```

再按路由挂输入区（与原型 2031 行一致，只有 assistant 有 dock）：

```js
  els.dock.innerHTML = r === "assistant" ? composerDock(state) : "";
  if (r === "assistant") {
    bindComposer((text) => {
      send(text);
      render();
    });
  }
```

事件委托里补五个分支：

```js
  } else if (action === "prompt") {
    send(el.dataset.prompt || "");
    render();
  } else if (action === "choice") {
    choose(el.dataset.choice || "");
    render();
  } else if (action === "new-chat") {
    newChat();
    render();
  } else if (action === "history") {
    openSheet(PROFILE_SHEETS.history());
  } else if (action === "quick") {
    const label = el.dataset.label;
    const prompts = {
      "多市场": "多个市场汇总，一次看清主要差异",
      "时间线": "查看法规变化时间线，最近有什么新要求",
      "对比": "比较欧盟和美国的儿童玩具法规目录",
      "导出": "导出当前结果",
    };
    if (label === "导出") showToast("原型中不生成文件；正式版会导出当前结果");
    else { send(prompts[label] || label); render(); }
  }
```

**注意**：`quick` 与 `history` 的行为逐字取自原型 2368–2370 与 2411–2420。原型的 `quick` 在 label 为「导出」时只提示不发送——照搬。

- [ ] **Step 7: 运行测试确认通过**

```bash
PYTHONIOENCODING=utf-8 "C:/Users/ymc/Desktop/agent/_recon/probe-venv/Scripts/python.exe" scripts/selftest_web_ui.py
```

Expected: PASS（AssistantViewTests 6 全通过，既有类无回归）

- [ ] **Step 8: 提交**

```bash
git add web/js/views/assistant.js web/js/ui/composer.js web/js/main.js scripts/selftest_web_ui.py
git commit -m "feat(web): assistant view, composer and quickbar ported from the prototype"
```

---

## Task 8: 法规中心、检索、工具页、行动

**Files:**
- Create: `web/js/views/regulations.js`、`web/js/views/search.js`、`web/js/views/tool.js`、`web/js/views/action.js`
- Modify: `web/js/main.js`（注册四个视图 + 接入 `rerun`/`example-query`/`filter` + `search` 表单提交）
- Test: `scripts/selftest_web_ui.py`（追加）

**Interfaces:**
- Consumes: `esc`、`ic`（Task 2）；`ITEMS`、`TOOL_PAGES`、`CLAUSES`（Task 3）；`rowHtml`、`toolCard`、`filteredItems`（Task 3）；`store`（Task 4）；`showToast`（Task 5）
- Produces: 四个视图模块，各 `export function render(state) -> string`

**原型对照**：法规中心 `1573-1596`；行动 `1598-1625`；工具页 `1634-1732`；检索 `1748-1781`。

- [ ] **Step 1: 搬运四个视图**

| 目标 | 原型行号（含） |
|---|---|
| `web/js/views/regulations.js` | 1573–1596（`regulationsView`） |
| `web/js/views/action.js` | 1598–1625（`actionView`） |
| `web/js/views/tool.js` | 1634–1732（`toolView`） |
| `web/js/views/search.js` | 1748–1781（`searchView`） |

增量：
1. 四个 `function xView()` → `export function xView(state) {`，函数体逐字不动。
2. 顶部导入：`esc`、`ic`、`ITEMS`、`TOOL_PAGES`、`CLAUSES`、`rowHtml`、`toolCard`、`filteredItems`（**每个文件只导入自己用到的**——`tool.js` 用不到 `rowHtml` 就别导）。
3. `toolView(id)` 原型签名的形参是 `id`，但它内部也引用全局 `state.toolGroup`。模块化后改为 `export function toolView(state)`，函数体首行加 `const id = state.tool;`——**这是唯一需要动函数体的一处**，因为原型把 id 当参数传（`toolView(state.tool)`，见原型 2049/2057 行），而分派表是按路由取函数的。

**注意**：`tool.js` 里对未知 tool 名的回落（原型 `if (!t) return state.toolGroup === "regulations" ? regulationsView() : actionView();`）必须保留——这是 Review Focus 2 在工具页上的落点。

- [ ] **Step 2: 写失败的测试**

在 `scripts/selftest_web_ui.py` 的 `if __name__ == "__main__":` 块**之前**追加：

```python
class RegulationsHubTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Browser.start()

    def test_hub_has_a_search_entry_and_two_tools(self):
        _Browser.goto("regulations")
        self.assertIn("法规中心", _Browser.page.locator("#view").inner_text())
        self.assertEqual(_Browser.page.locator("#view .search-entry").count(), 1)
        self.assertEqual(_Browser.page.locator("#view .tool").count(), 2)

    def test_search_entry_navigates_to_the_search_route(self):
        _Browser.goto("regulations")
        _Browser.page.locator("#view .search-entry").click()
        _Browser.page.wait_for_timeout(300)
        self.assertIn("regulations/search", _Browser.page.url)


class ActionHubTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Browser.start()

    def test_hub_groups_tasks_and_markets(self):
        _Browser.goto("action")
        self.assertIn("要做的事", _Browser.page.locator("#view").inner_text())
        self.assertIn("看市场", _Browser.page.locator("#view").inner_text())
        self.assertEqual(_Browser.page.locator("#view [data-action='open-tool']").count(), 5)


class ToolViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Browser.start()

    TOOLS = [("regulations", "map", "法规地图"), ("regulations", "timeline", "变化时间线"),
             ("action", "todo", "合规待办"), ("action", "readiness", "上线准备"),
             ("action", "journey", "六阶段路线"), ("action", "compare", "区域对比"),
             ("action", "multi", "多市场汇总")]

    def test_each_tool_renders_its_own_content(self):
        for group, tool, title in self.TOOLS:
            with self.subTest(tool=tool):
                _Browser.goto(f"{group}/{tool}")
                # 原型的工具标题在顶栏（1226-1233）；视图内是副标题与工具内容。
                self.assertIn(title, _Browser.page.locator("#appbar").inner_text())
                self.assertTrue(_Browser.page.locator("#view").inner_text().strip())

    def test_tool_pages_keep_the_bottom_tabbar_active(self):
        for group, tool, _ in self.TOOLS:
            with self.subTest(tool=tool):
                _Browser.goto(f"{group}/{tool}")
                current = _Browser.page.locator('#tabbar [aria-current="page"]')
                self.assertEqual(current.count(), 1)

    def test_unknown_tool_name_falls_back_without_blanking(self):
        """Review Focus 2：未知工具名必须回落到该组的中心页。"""
        _Browser.goto("regulations/不存在")
        text = _Browser.page.locator("#view").inner_text()
        self.assertTrue(text.strip())
        self.assertIn("法规中心", text)


class SearchViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Browser.start()

    def test_search_route_renders_the_prototype_clauses(self):
        _Browser.goto("regulations/search")
        # 标题在顶栏（原型 1225）；视图内是检索表单与正文指引。
        self.assertIn("条款检索", _Browser.page.locator("#appbar").inner_text())
        self.assertIn("按法规编号精确定位", _Browser.page.locator("#view").inner_text())
```

- [ ] **Step 3: 运行测试确认失败**

```bash
PYTHONIOENCODING=utf-8 "C:/Users/ymc/Desktop/agent/_recon/probe-venv/Scripts/python.exe" scripts/selftest_web_ui.py RegulationsHubTests ActionHubTests ToolViewTests SearchViewTests
```

Expected: FAIL —— 四个视图尚未注册

- [ ] **Step 4: 在 `main.js` 注册并接入 action**

`VIEWS` 补齐：

```js
import { regulationsView } from "./views/regulations.js";
import { actionView } from "./views/action.js";
import { toolView } from "./views/tool.js";
import { searchView } from "./views/search.js";

// 加进 VIEWS：
//   regulations: regulationsView,
//   "regulations/search": searchView,
//   action: actionView,
```

工具路由（`regulations/<tool>` 与 `action/<tool>`）在 `render()` 里按下述方式分派——与原型 2048–2059 一致，两个前缀都走 `toolView`：

```js
  const view = VIEWS[r]
    || ((r.startsWith("regulations/") || r.startsWith("action/")) ? toolView : null);
```

**未知路由的 `go("home")` 回落不在这里**：本任务时 `profile` / `profile/tutorial` 仍无视图，
回落会把它们也送去首页并打回归 `ShellTests`。回落落在 Task 9（届时全部路由都有视图）。

事件委托补三个分支（逐字对应原型 2372–2374、2380–2381、2385–2388）：

```js
  } else if (action === "filter") {
    store.set({ filter: el.dataset.filter || "全部" });
    render();
  } else if (action === "rerun") {
    showToast("已按当前条件重新生成");
  } else if (action === "example-query") {
    store.set({ query: el.dataset.query || "", searchDone: true });
    render();
  }
```

`search` 表单提交（原型 2433–2439）：

```js
document.addEventListener("submit", (event) => {
  const form = event.target;
  if (form.dataset.form === "search") {
    event.preventDefault();
    const input = form.querySelector("input");
    store.set({ query: input ? input.value : "", searchDone: true });
    render();
  }
});
```

**注意**：`search` 表单的提交处理器与 Task 7 的 `compose` 处理器**必须共存**——若 Task 7 已经把 submit 监听器写成只处理 `compose`，本任务要扩展成 `if/else if` 两个分支，而不是新加一个监听器（两个监听器都会收到事件，`preventDefault` 顺序会出问题）。

- [ ] **Step 5: 运行测试确认通过**

```bash
PYTHONIOENCODING=utf-8 "C:/Users/ymc/Desktop/agent/_recon/probe-venv/Scripts/python.exe" scripts/selftest_web_ui.py
```

Expected: PASS（RegulationsHubTests 2 + ActionHubTests 1 + ToolViewTests 3 + SearchViewTests 1 全通过，既有类无回归）

- [ ] **Step 6: 提交**

```bash
git add web/js/views/regulations.js web/js/views/action.js web/js/views/tool.js web/js/views/search.js web/js/main.js scripts/selftest_web_ui.py
git commit -m "feat(web): regulations hub, clause search, tool pages and action hub ported from the prototype"
```

---

## Task 9: 我的、教程与七个底部抽屉

**Files:**
- Create: `web/js/views/profile.js`、`web/js/views/tutorial.js`、`web/js/views/detail.js`
- Modify: `web/js/main.js`（注册三个视图 + 补全剩余 action）
- Test: `scripts/selftest_web_ui.py`（追加）

**Interfaces:**
- Consumes: `esc`、`ic`（Task 2）；`PROFILE_SHEETS`（Task 3）；`store`（Task 4）；`openSheet`/`closeSheet`（Task 5）；`go`（Task 4）
- Produces: 三个视图模块，各 `export function render(state) -> string`

**原型对照**：我的 `1880-1943`；教程 `1783-1878`；条目详情 `2154-2185`（`detailSheet(id)`）。七个 `PROFILE_SHEETS` 已在 Task 3 搬进 `sample.js`。

- [ ] **Step 1: 搬运三个视图**

| 目标 | 原型行号（含） |
|---|---|
| `web/js/views/profile.js` | 1880–1943（`profileView`） |
| `web/js/views/tutorial.js` | 1783–1878（`tutorialView`） |
| `web/js/views/detail.js` | 2154–2185（`detailSheet`） |

增量：
1. 三个 `function x()` → `export function`（`detailSheet` 也导出——`main.js` 要用）。
2. 顶部导入：`esc`、`ic`、`ITEMS`（`detailSheet` 里会按 id 取条目）、`PROFILE_SHEETS`（若用到）。
3. `detailSheet(id)` **保持吃 `id` 形参**（与 `toolView` 不同）——因为它由 `data-action="detail" data-id="…"` 的委托调用，id 来自 DOM，不经 `state`。

**注意**：`profile.js` 的菜单行用的是 `data-action="sheet" data-sheet="<id>"`（原型 `PROFILE_SHEETS` 的键名），而**不是** `data-action="detail" data-id`。这两套是不同的机制：`detail` 打开条目详情（按 ITEMS id），`sheet` 打开七个固定抽屉（按 PROFILE_SHEETS 键）。先前那版计划把两者混为一谈。

- [ ] **Step 2: 写失败的测试**

在 `scripts/selftest_web_ui.py` 的 `if __name__ == "__main__":` 块**之前**追加：

```python
class ProfileViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Browser.start()

    def test_profile_menu_uses_the_sheet_action(self):
        _Browser.goto("profile")
        rows = _Browser.page.locator("#view [data-action='sheet']")
        self.assertGreaterEqual(rows.count(), 6)
        keys = [rows.nth(i).get_attribute("data-sheet") for i in range(rows.count())]
        for key in ["history", "conditions", "voice", "coverage", "privacy", "about"]:
            with self.subTest(key=key):
                self.assertIn(key, keys)

    def test_tutorial_is_the_prototype_article_and_lives_under_profile(self):
        """tutorialView 是一篇长文档（article.tutorial + tut-lead/tut-source/tut-callout + 表格），
        不是卡片列表——`.step` 属于 PROFILE_SHEETS.help() 的抽屉，不在此路由。"""
        _Browser.goto("profile/tutorial")
        view = _Browser.page.locator("#view")
        self.assertEqual(_Browser.page.locator("#view article.tutorial").count(), 1)
        self.assertIn("企业用户使用指引", view.inner_text())
        self.assertGreaterEqual(_Browser.page.locator("#view .tut-lead").count(), 2)
        self.assertEqual(_Browser.page.locator("#view .tut-source").count(), 1)
        self.assertGreaterEqual(_Browser.page.locator("#view .tut-callout").count(), 1)
        self.assertGreaterEqual(_Browser.page.locator("#view table tr").count(), 1)
        self.assertEqual(_Browser.page.locator("#view .step").count(), 0,
                         "教程路由不应有 .step（那属于帮助抽屉）")
        current = _Browser.page.locator('#tabbar [aria-current="page"]')
        self.assertIn("我的", current.inner_text())

    def test_profile_shows_the_radar_mark_once(self):
        """我的页同时有顶栏 brand 与 hero 两处雷达标记，视觉上重复。
        产品决定：保留 hero 的品牌标记，顶栏在 profile 路由不画标记。"""
        _Browser.goto("profile")
        self.assertEqual(_Browser.page.locator("#appbar .brand__mark").count(), 0)
        self.assertEqual(_Browser.page.locator("#view .profile__mark").count(), 1)


class DetailSheetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Browser.start()

    # help 在原型里没有 UI 入口（PROFILE_SHEETS.help 仍保留、handler 仍接线），
    # 故不放进"从 profile 可打开"的键列表——否则点击定位器没有目标。
    PROFILE_KEYS = ["conditions", "history", "voice", "coverage", "privacy", "about"]

    def _open_key(self, key):
        _Browser.goto("profile")
        _Browser.page.evaluate(
            "async () => { const s = await import('/web/js/ui/sheet.js'); s.closeSheet(); }")
        _Browser.page.locator(f"#view [data-action='sheet'][data-sheet='{key}']").first.click()
        _Browser.page.wait_for_timeout(300)

    def test_every_profile_sheet_opens_with_content(self):
        for key in self.PROFILE_KEYS:
            with self.subTest(key=key):
                self._open_key(key)
                sheet = _Browser.page.locator("#sheet")
                self.assertIn("is-on", sheet.get_attribute("class"))
                self.assertTrue(sheet.inner_text().strip(), f"{key} 抽屉不得为空")

    def test_every_sheet_has_a_grab_handle_and_a_close_button(self):
        for key in self.PROFILE_KEYS:
            with self.subTest(key=key):
                self._open_key(key)
                sheet = _Browser.page.locator("#sheet")
                self.assertEqual(sheet.locator(".sheet__grab").count(), 1)
                self.assertEqual(sheet.locator("[data-action='close-sheet']").count(), 1)

    def test_item_detail_opens_from_a_row(self):
        _Browser.goto("result")
        _Browser.page.locator("#view [data-action='detail']").first.click()
        _Browser.page.wait_for_timeout(300)
        sheet = _Browser.page.locator("#sheet")
        self.assertIn("is-on", sheet.get_attribute("class"))
        self.assertEqual(sheet.locator(".sheet__grab").count(), 1)

    def test_unknown_detail_id_does_not_blank_the_sheet(self):
        """Review Focus 2：未知条目 id 不得白屏或抛异常。"""
        got = _Browser.page.evaluate("""async () => {
          const d = await import('/web/js/views/detail.js');
          try { return d.detailSheet('完全不存在的条目'); }
          catch (e) { return 'THREW: ' + e.message; }
        }""")
        self.assertFalse(str(got).startswith("THREW"), "未知 id 不得抛异常")


class UnknownRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Browser.start()

    def test_unknown_route_redirects_home(self):
        """原型 2068-2071：未知路由 go("home")。所有视图就位后此行为才可观测。"""
        for bad in ["完全瞎写", "zzz", "foo/bar", "__proto__"]:
            with self.subTest(bad=bad):
                _Browser.goto(bad)
                self.assertTrue(_Browser.page.url.endswith("#/home"),
                                f"未知路由必须回落到 #/home，实际 {_Browser.page.url}")

    def test_unknown_route_renders_the_home_view(self):
        for bad in ["完全瞎写", "foo/bar", "__proto__"]:
            with self.subTest(bad=bad):
                _Browser.goto(bad)
                self.assertTrue(_Browser.page.locator("#view").inner_text().strip(),
                                "回落首页后必须渲染出内容，而不是白屏")


class DelegationCompletenessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Browser.start()

    def test_every_action_in_the_prototype_is_handled(self):
        """把原型事件委托里出现过的 action 逐个点一遍，任何未接的 action 会表现为无反应。

        本测试只断言页面不崩、不白屏；具体行为由各自视图的测试覆盖。
        """
        actions = ["nav", "prompt", "choice", "open-result", "new-chat", "history",
                   "detail", "filter", "fresh-filter", "open-tool", "rerun",
                   "toggle-freshness", "example-query", "sheet", "open-history",
                   "close-sheet", "export", "mark-done", "copy", "regenerate",
                   "voice", "quick", "help"]
        got = _Browser.page.evaluate("""async () => {
          const m = await import('/web/js/main.js');
          return m.HANDLED_ACTIONS;
        }""")
        for action in actions:
            with self.subTest(action=action):
                self.assertIn(action, got, f"action「{action}」尚未接入")
```

`main.js` 需导出它已接入的 action 清单，供此测试核对：

```js
export const HANDLED_ACTIONS = [ /* 事件委托里实际处理的所有 action 名 */ ];
```

- [ ] **Step 3: 运行测试确认失败**

```bash
PYTHONIOENCODING=utf-8 "C:/Users/ymc/Desktop/agent/_recon/probe-venv/Scripts/python.exe" scripts/selftest_web_ui.py ProfileViewTests DetailSheetTests DelegationCompletenessTests
```

Expected: FAIL —— 三个视图尚未注册，`HANDLED_ACTIONS` 不存在

- [ ] **Step 4: 在 `main.js` 注册并补全剩余 action**

`VIEWS` 加 `profile: profileView`、`"profile/tutorial": tutorialView`。

**本任务装上未知路由回落**（原型 2068-2071）——到这一步所有路由都已有视图，回落才首次可观测：

```js
  const view = Object.hasOwn(VIEWS, r)
    ? VIEWS[r]
    : ((r.startsWith("regulations/") || r.startsWith("action/")) ? toolView : null);
  if (!view) {
    go("home");
    return;
  }
  els.view.className = r === "assistant" ? "view view--chat" : "view";
  els.view.innerHTML = view(state);
```

工具路由的分派必须保留（Task 8 加的 `|| … toolView`）；`view--chat` 的条件也必须保留（Task 7 加的）。

并在导入区确认有 `import { go } from "./router.js";`。

导入：`import { detailSheet } from "./views/detail.js";`。**不要**导入 `toggleFreshness`——`toggle-freshness` 在 M1 不接入（见下），未使用的导入是死代码。

补齐剩下六个分支，逐字对应原型 2363–2371、2392–2423：

```js
  } else if (action === "detail") {
    openSheet(detailSheet(el.dataset.id));
  } else if (action === "sheet") {
    const builder = PROFILE_SHEETS[el.dataset.sheet];
    if (builder) openSheet(builder());
  } else if (action === "open-result") {
    store.state.resultFrom = el.dataset.from
      || (store.state.route === "home" ? "home" : "assistant");
    go("result");
  } else if (action === "open-history") {
    closeSheet();
    store.state.resultFrom = ["home", "assistant", "regulations", "action"]
      .includes(store.state.route) ? store.state.route : "profile";
    go("result");
  } else if (action === "export") {
    showToast("原型中不生成文件；正式版会导出带查询条件的 CSV");
  } else if (action === "mark-done") {
    showToast("已标记为已完成 · 不会自动视为合规");
    closeSheet();
  } else if (action === "copy") {
    showToast("已复制这条回答");
  } else if (action === "regenerate") {
    showToast("原型中不重复调用模型；正式版会基于同一条件重答");
  } else if (action === "voice") {
    showToast("语音入口：转写后先预编辑，再发送");
  } else if (action === "help") {
    openSheet(PROFILE_SHEETS.help());
  }
```

`toggle-freshness`（原型 2382–2384）**M1 不接入**：它只服务于原型的"首次使用/有记录"双态演示开关，而该开关已按 Task 6 从产品中剔除。因此在 `HANDLED_ACTIONS` 里**不列**它，并把上面测试的 `actions` 列表里的 `"toggle-freshness"` 一并删掉——两者必须一致，否则测试会要求一个我们刻意不做的 action。

最后导出 `HANDLED_ACTIONS`，内容是事件委托里出现的全部 action 名（不含 `toggle-freshness`）。

- [ ] **Step 5: 运行测试确认通过**

```bash
PYTHONIOENCODING=utf-8 "C:/Users/ymc/Desktop/agent/_recon/probe-venv/Scripts/python.exe" scripts/selftest_web_ui.py
```

Expected: PASS（ProfileViewTests 3 + DetailSheetTests 4 + UnknownRouteTests 2 + DelegationCompletenessTests 1 全通过，既有类无回归）

- [ ] **Step 6: 提交**

```bash
git add web/js/views/profile.js web/js/views/tutorial.js web/js/views/detail.js web/js/main.js scripts/selftest_web_ui.py
git commit -m "feat(web): profile, tutorial and the seven sheets ported from the prototype"
```

---

## Task 10: 响应式——桌面端去掉手机壳

**Files:**
- Modify: `web/styles/shell.css`（追加覆盖）
- Test: `scripts/selftest_web_ui.py`（追加）

**Interfaces:**
- Consumes: Task 5 搬运进 `shell.css` 的原型 `71-148`（含 `@media (min-width: 700px)` 的手机壳规则）
- Produces: 无导出；行为约束——≥700px 时无手机壳装饰，窄栏仍居中且为手机比例

**规格第 7 节**：桌面端去掉边框、圆角、阴影、桌面底纹；内容窄栏居中 `max-width: 480px`；标签栏保持底部。

- [ ] **Step 1: 写失败的测试**

在 `scripts/selftest_web_ui.py` 的 `if __name__ == "__main__":` 块**之前**追加：

```python
class ResponsiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Browser.start()

    @classmethod
    def tearDownClass(cls):
        # 共享 page 的视口必须恢复，否则字母序在其后的浏览器测试会在桌面宽度下运行。
        _Browser.page.set_viewport_size({"width": 390, "height": 844})

    def _at(self, width, prop):
        _Browser.page.set_viewport_size({"width": width, "height": 900})
        _Browser.page.goto(f"{BASE}#/home", wait_until="load")
        _Browser.page.wait_for_timeout(350)
        return _Browser.page.evaluate(
            "() => { const el = document.querySelector('.app-shell'); const cs = getComputedStyle(el);"
            "return { prop: cs.getPropertyValue(%r), rect: el.getBoundingClientRect().toJSON() }; }"
            % prop)

    def test_wide_viewport_has_no_phone_shell_decoration(self):
        for prop in ["border-top-width", "box-shadow"]:
            with self.subTest(prop=prop):
                got = self._at(1440, prop)
                self.assertIn(got["prop"], ["0px", "none"],
                              f"桌面端不应保留手机壳装饰：{prop}={got['prop']}")

    def test_wide_viewport_keeps_the_phone_proportions_and_centering(self):
        rect = self._at(1440, "width")["rect"]
        self.assertLessEqual(rect["width"], 481, "桌面端内容栏不得超过 480px")
        self.assertAlmostEqual(rect["x"] + rect["width"] / 2, 720, delta=2, msg="内容栏必须居中")

    def test_narrow_viewport_keeps_the_full_width_shell(self):
        _Browser.page.set_viewport_size({"width": 390, "height": 844})
        _Browser.page.goto(f"{BASE}#/home", wait_until="load")
        _Browser.page.wait_for_timeout(350)
        rect = _Browser.page.evaluate(
            "() => document.querySelector('.app-shell').getBoundingClientRect().toJSON()")
        self.assertEqual(rect["width"], 390)
        self.assertEqual(rect["x"], 0)

    def test_tabbar_stays_at_the_bottom_across_the_breakpoint(self):
        """Review Focus 5：跨断点来回缩放不得错乱。"""
        for width in [390, 1440, 390, 1440]:
            with self.subTest(width=width):
                _Browser.page.set_viewport_size({"width": width, "height": 900})
                _Browser.page.goto(f"{BASE}#/home", wait_until="load")
                _Browser.page.wait_for_timeout(300)
                box = _Browser.page.evaluate(
                    "() => { const r = document.querySelector('.tabbar').getBoundingClientRect();"
                    "return { bottom: r.bottom, vh: window.innerHeight, w: r.width }; }")
                self.assertLessEqual(abs(box["bottom"] - box["vh"]), 2, "标签栏必须贴在视口底部")
                self.assertGreater(box["w"], 300, "标签栏不得塌陷")
```

- [ ] **Step 2: 运行测试确认失败**

```bash
PYTHONIOENCODING=utf-8 "C:/Users/ymc/Desktop/agent/_recon/probe-venv/Scripts/python.exe" scripts/selftest_web_ui.py ResponsiveTests
```

Expected: FAIL —— 搬来的原型规则仍带边框、圆角、阴影

- [ ] **Step 3: 追加去壳覆盖**

追加到 `web/styles/shell.css` **末尾**（原型原文保留在文件中不动，便于对照）：

```css
/* ============================================================
   桌面端去壳（规格第 7 节）
   原型在 ≥700px 渲染居中手机壳；本项目保留手机比例与排布，
   但去掉边框、圆角、阴影与桌面底纹。
   与原型规则同为 @media (min-width: 700px)，特异性相同，
   靠"后声明胜出"生效——因此本块必须在文件末尾。
   ============================================================ */
@media (min-width: 700px) {
  body {
    display: block;
    padding: 0;
    background: var(--paper);
  }
  .app-shell {
    height: 100dvh;
    border: 0;
    border-radius: 0;
    box-shadow: none;
  }
}
```

- [ ] **Step 4: 运行测试确认通过**

```bash
PYTHONIOENCODING=utf-8 "C:/Users/ymc/Desktop/agent/_recon/probe-venv/Scripts/python.exe" scripts/selftest_web_ui.py
```

Expected: PASS（ResponsiveTests 4 全通过，既有类无回归）

- [ ] **Step 5: 提交**

```bash
git add web/styles/shell.css scripts/selftest_web_ui.py
git commit -m "style(web): drop the phone shell on wide viewports, keep phone proportions"
```

---

## Task 11: 像素验收与门禁接入

**Files:**
- Create: `scripts/check_web_browser.py`、`scripts/compare_web_screenshots.py`
- Modify: `scripts/selftest_all.py`
- Test: 本任务即验收工具

**Interfaces:**
- Consumes: 全部前序产物；`docs/ui-preview/prototype-v2.html`（Task 1）
- Produces:
  - `scripts/check_web_browser.py --url URL [--out DIR]` → 逐路由截图 + `web-report.json`
  - `scripts/compare_web_screenshots.py --prototype DIR --rebuilt DIR [--out FILE]` → 调 REA 做像素比对

**为什么分两个脚本**：截图必须由 Playwright 在**固定视口**下采集（REA 抓的是真实窗口可视区，尺寸受窗口边框影响——实测为 496×751 而非 390×844）；比对则交给 REA 独立完成。这是"确定性采集 + 独立比对"的分工。

- [ ] **Step 1: 写 `scripts/check_web_browser.py`**

沿用 `scripts/check_chat_browser.py` 的 `--url` 范式：

```python
"""逐路由截图与结构检查；需要 Playwright。

用法：
  PORT=7899 python app.py &
  python scripts/check_web_browser.py --url http://127.0.0.1:7899 --out docs/ui-preview/rebuilt
"""
import argparse
import json
from pathlib import Path
import sys

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent

ROUTES = ["home", "result", "freshness", "assistant",
          "regulations", "regulations/search", "regulations/map", "regulations/timeline",
          "action", "action/todo", "action/readiness", "action/journey",
          "action/compare", "action/multi",
          "profile", "profile/tutorial"]

VIEWPORTS = {"mobile": {"width": 390, "height": 844},
             "desktop": {"width": 1440, "height": 900}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--out", default=str(ROOT / "docs" / "ui-preview" / "rebuilt"))
    args = parser.parse_args()

    out = Path(args.out)
    shots = out / "shots"
    shots.mkdir(parents=True, exist_ok=True)
    report = {"url": args.url, "routes": {}, "failures": []}

    with sync_playwright() as p:
        browser = p.chromium.launch()
        for vp_name, vp in VIEWPORTS.items():
            ctx = browser.new_context(viewport=vp, device_scale_factor=2,
                                      locale="zh-CN", color_scheme="light",
                                      reduced_motion="reduce")
            page = ctx.new_page()
            for route in ROUTES:
                page.goto(f"{args.url}#/{route}", wait_until="load")
                page.wait_for_timeout(400)
                key = f"{route}@{vp_name}"
                page.screenshot(path=str(shots / f"{key.replace('/', '_')}.png"))
                info = page.evaluate("""() => ({
                  viewText: (document.getElementById('view')?.innerText || '').trim().slice(0, 400),
                  tabbarCount: document.querySelectorAll('#tabbar .tab').length,
                })""")
                report["routes"][key] = info
                if not info["viewText"]:
                    report["failures"].append(f"{key}: #view 为空（疑似白屏）")
                if info["tabbarCount"] != 5:
                    report["failures"].append(f"{key}: 标签项 {info['tabbarCount']} 个，期望 5")
            ctx.close()
        browser.close()

    (out / "web-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"routes={len(report['routes'])} failures={len(report['failures'])}")
    for line in report["failures"]:
        print("  FAIL:", line)
    return 1 if report["failures"] else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 采集原型的基准截图**

用同一脚本采原型，保证视口与参数完全一致：

```bash
python -m http.server 8899 --bind 127.0.0.1 --directory docs/ui-preview &
sleep 2
PYTHONIOENCODING=utf-8 "C:/Users/ymc/Desktop/agent/_recon/probe-venv/Scripts/python.exe" scripts/check_web_browser.py \
  --url http://127.0.0.1:8899/prototype-v2.html \
  --out docs/ui-preview/prototype-baseline
kill %1
```

然后**采改造后的**（服务已由 Step 4 起的那个，或另起）：

```bash
PYTHONIOENCODING=utf-8 "C:/Users/ymc/Desktop/agent/_recon/probe-venv/Scripts/python.exe" scripts/check_web_browser.py \
  --url http://127.0.0.1:7899 --out docs/ui-preview/rebuilt
```

Expected: 两份各 32 张截图。原型的报告里会有若干 `failures`（原型部分路由本就没有 5 个标签项或有空态），**这是基准图，不作为门禁**——它的用途只是像素比对的对照。

- [ ] **Step 3: 写 `scripts/compare_web_screenshots.py`**

契约已实测，**不要自己实现像素算法**：

- 位置参数：`<beforeJson> <afterJson>`，两者都是截图产物 JSON **文件路径**
- 截图产物 JSON 形状：`{"sha256", "bytes", "media_type": "image/png", "data_base64"}`
- 输出（`normalized_result`）：`status`（`"identical"` / `"different"`）、`changed_ratio`（0.0~1.0）、`changed_pixels`、`compared_pixels`、`maximum_channel_delta`、`mean_absolute_channel_delta`
- 只接受**非交错 8-bit RGB/RGBA PNG**；比对不含 OCR、不做语义布局分析、不做感知色彩校正

```python
"""原型 vs 改造后的像素比对；比对由 REA 完成。

用法：
  python scripts/compare_web_screenshots.py \
    --prototype docs/ui-preview/prototype-baseline/shots \
    --rebuilt   docs/ui-preview/rebuilt/shots \
    --out       docs/ui-preview/web-pixel-diff.json
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def snapshot(path):
    data = path.read_bytes()
    return {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
            "media_type": "image/png", "data_base64": base64.b64encode(data).decode()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prototype", required=True)
    parser.add_argument("--rebuilt", required=True)
    parser.add_argument("--out", default=None)
    parser.add_argument("--threshold", type=float, default=0.02, help="允许的差异像素占比")
    args = parser.parse_args()

    if shutil.which("rea") is None:
        print("REA 未安装：npm install --global rea-agents", file=sys.stderr)
        return 2

    proto_dir, rebuilt_dir = Path(args.prototype), Path(args.rebuilt)
    names = sorted(p.name for p in proto_dir.glob("*.png"))
    if not names:
        print(f"基准目录没有截图：{proto_dir}", file=sys.stderr)
        return 2

    report = {"pairs": [], "over_threshold": []}
    with tempfile.TemporaryDirectory() as tmp:
        for name in names:
            rebuilt = rebuilt_dir / name
            if not rebuilt.is_file():
                report["over_threshold"].append({"name": name, "reason": "缺少改造后截图"})
                continue
            before = Path(tmp) / f"{name}.before.json"
            after = Path(tmp) / f"{name}.after.json"
            before.write_text(json.dumps(snapshot(proto_dir / name)), encoding="utf-8")
            after.write_text(json.dumps(snapshot(rebuilt)), encoding="utf-8")
            proc = subprocess.run(
                ["rea", "compare-web-screenshots", str(before), str(after), "--json"],
                capture_output=True, text=True, encoding="utf-8", shell=False)
            if proc.returncode != 0:
                report["over_threshold"].append(
                    {"name": name, "reason": f"REA 退出码 {proc.returncode}: {proc.stderr[:200]}"})
                continue
            norm = json.loads(proc.stdout).get("normalized_result", {})
            entry = {"name": name, "status": norm.get("status"),
                     "changed_ratio": norm.get("changed_ratio"),
                     "changed_pixels": norm.get("changed_pixels"),
                     "compared_pixels": norm.get("compared_pixels"),
                     "maximum_channel_delta": norm.get("maximum_channel_delta")}
            report["pairs"].append(entry)
            ratio = entry["changed_ratio"]
            if isinstance(ratio, (int, float)) and ratio > args.threshold:
                report["over_threshold"].append(entry)

    text = json.dumps(report, ensure_ascii=False, indent=1)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)
    return 1 if report["over_threshold"] else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 运行像素比对**

```bash
PYTHONIOENCODING=utf-8 "C:/Users/ymc/Desktop/agent/_recon/probe-venv/Scripts/python.exe" scripts/compare_web_screenshots.py \
  --prototype docs/ui-preview/prototype-baseline/shots \
  --rebuilt docs/ui-preview/rebuilt/shots \
  --out docs/ui-preview/web-pixel-diff.json
```

Expected: 每题给出差异占比。M1 的目标是 **移动端（`@mobile`）同路由差异显著低于桌面端**——桌面端按规格第 7 节刻意去壳，与原型必然不同，属**预期差异**。

在 `web-pixel-diff.json` 旁写一份 `docs/ui-preview/web-pixel-diff.md`，逐条说明哪些差异是规格允许的（桌面去壳）、哪些是待修的。

- [ ] **Step 5: 把 API 门禁加入离线总闸**

在 `scripts/selftest_all.py` 的 `SCRIPTS` 列表末尾追加（保持与既有条目同样的注释风格）：

```python
    # SPA 静态托管与 /api/* 契约：Gradio 的根路由被接管后必须仍然可用。
    "scripts/selftest_web_api.py",
```

- [ ] **Step 6: 跑完整门禁**

```bash
PYTHONIOENCODING=utf-8 "C:/Users/ymc/Desktop/agent/_recon/probe-venv/Scripts/python.exe" scripts/selftest_all.py 2>&1 | tail -8
```

Expected: 除既有那条 `selftest_recall_flow.py`（`runtime-assets/law-store.bundle` 缺失，原仓库同样缺失）外**不得新增失败**。新条目 `selftest_web_api.py` 必须通过。

- [ ] **Step 7: 提交**

```bash
git add scripts/check_web_browser.py scripts/compare_web_screenshots.py scripts/selftest_all.py docs/ui-preview/web-pixel-diff.json docs/ui-preview/web-pixel-diff.md
git commit -m "test(web): per-route screenshots, REA pixel diff and the offline SPA gate"
```

---

## M1 完成判据

全部满足才算 M1 交付：

1. `scripts/selftest_web_api.py` 与 `scripts/selftest_web_ui.py` 全绿
2. `scripts/selftest_all.py` 除既有那条 `selftest_recall_flow.py` 外无新增失败
3. `PORT=xxxx python app.py` 后 `/` 是 SPA、`/gradio_api/info` 仍 200
4. `CR_UI=gradio` 能退回原 Gradio 界面
5. 16 条路由在 390×844 与 1440×900 下都非白屏，标签栏恒为底部
6. 像素比对报告生成，且差异已逐条分类说明
7. **`web/js/` 下不出现任何原型 CSS 里不存在的类名**——由各视图测试里的反向断言（`.row__copy`、`.tool__copy`、`.fresh-card__top`、`.composer__mic`、`.proto-toggle` 等必须不存在）守住

## M2 预告（不在本计划范围）

把 `web/js/sample.js` 的取值处换成 `/api/*`（规格第 5 节），并补 `/api/search` 空命中、`/api/route` 的 `ok:false` 分支契约测试。因为视图模板与交互不含任何数据来源假设，M2 只动 `sample.js` 一个文件加 `api.js`。
