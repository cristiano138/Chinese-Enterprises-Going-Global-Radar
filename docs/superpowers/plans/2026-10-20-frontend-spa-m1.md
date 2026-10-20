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

### 关于"从原型搬运"的约定

本计划中标注 **【搬运】** 的步骤指的是：把 `prototype.html` 中指定行号范围的文本**原样复制**到目标文件，不做改写、不重排、不"顺手优化"。每个【搬运】步骤都给出了**精确行号范围**与**搬运后的校验断言**，因此它是一条可执行、可验证的指令，不是占位符。行号以入库的 `docs/ui-preview/prototype-v2.html` 为准（Task 1 入库后行号与原件一致）。

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
| `web/js/main.js` | 启动：建壳、绑全局事件、启动路由 |
| `web/js/router.js` | 路由表、hash 解析、导航、未知路由回落 |
| `web/js/store.js` | 会话与筛选状态（订阅式） |
| `web/js/icons.js` | 原型图标表【搬运】+ `ic()` 辅助 |
| `web/js/dom.js` | `esc()`、模板工具 |
| `web/js/ui/sheet.js` | 底部抽屉：`openSheet` / `closeSheet` |
| `web/js/ui/toast.js` | 轻提示：`showToast` |
| `web/js/views/*.js` | 16 条路由的视图模块（10 个文件） |
| `scripts/selftest_web_api.py` | 离线：静态托管、`/api/*` 契约、`ok:false`、未知路由 |
| `scripts/check_web_browser.py` | 浏览器：逐路由 DOM/布局断言 + 截图（沿用 `check_chat_browser.py` 范式） |
| `scripts/compare_web_screenshots.py` | 像素比对：原型 vs 改造后（调 REA） |

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

规格 §4.1 列出的 `web/js/api.js`（`/api/*` 封装）**属于 M2**：M1 的决定是"先做壳与路由，内容先用示例数据"，因此 M1 的每一层都不发网络请求，各视图的数据以模块内的 `SAMPLE` 常量提供。M2 引入 `api.js` 时，只替换各视图的 `SAMPLE` 取值处，视图的模板与交互不动。`web_app.py` 的 `/api/*` 端点同样在 M2 落地（M1 只做根路由接管与静态托管）。

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

Expected:
```
bytes: 127534
sha256: c7dc84ce5fd1f365764bfa3e39aa46fcb01a151fcef76acf9e8f818b2440af16
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
        self.assertEqual(len(data), 127534, "原型字节数必须与拆解基线一致")
        self.assertEqual(
            hashlib.sha256(data).hexdigest(),
            "c7dc84ce5fd1f365764bfa3e39aa46fcb01a151fcef76acf9e8f818b2440af16",
            "像素比对基准被改动：请确认 docs/ui-preview/prototype-v2.html 未被编辑")


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 3: 运行测试确认失败**

```bash
"C:/Users/ymc/Desktop/agent/_recon/probe-venv/Scripts/python.exe" scripts/selftest_web_api.py
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
</div>
<div class="backdrop" id="backdrop" data-action="close-sheet"></div>
<aside class="sheet" id="sheet" role="dialog" aria-modal="true" aria-label="详情"></aside>
<div class="toast" id="toast" role="status" aria-live="polite"></div>
<script type="module" src="/web/js/main.js"></script>
</body>
</html>
```

六个挂载点必须与原型 `prototype.html:885-893` 的 `id` 完全一致（`shell` / `appbar` / `view` / `dock` / `tabbar` / `backdrop` / `sheet` / `toast`），后续所有任务依赖这些 id。

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
"C:/Users/ymc/Desktop/agent/_recon/probe-venv/Scripts/python.exe" scripts/selftest_web_api.py
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
kill "$APP_PID"
```

Expected: `root=200`、`static=200`、`gradio=200`

- [ ] **Step 10: 提交**

```bash
git add docs/ui-preview/prototype-v2.html web_app.py web/index.html web/styles web/js app_main.py scripts/selftest_web_api.py
git commit -m "feat(web): serve the SPA shell from Gradio's FastAPI instance"
```

---

## Task 2: 设计令牌、基础样式、图标与共享组件

**Files:**
- Modify: `web/styles/tokens.css`（替换 Task 1 的占位）
- Modify: `web/styles/base.css`（替换占位）
- Create: `web/js/icons.js`
- Create: `web/js/dom.js`
- Create: `web/js/components.js`
- Test: `scripts/selftest_web_ui.py`（新建，Playwright）

**Interfaces:**
- Consumes: `web_app.install()`（Task 1）提供的 `/` 与 `/web/*`；`docs/ui-preview/prototype-v2.html`（Task 1 入库的原型参考资产——本任务的【搬运】步骤按它的行号取值，未入库就跑不了）
- Produces:
  - `web/js/icons.js` → `export const ICONS: Record<string, string>`（原型图标表全文）；`export const ic = (name, cls) => string`
  - `web/js/dom.js` → `export const esc = (v) => string`；`export const h = (strings, ...values) => string`（自动 `esc` 所有插值）
  - `web/js/components.js` → `pageHead({title, lead})`、`sectionHead({title, count, action})`、`card(inner, cls)`、`row({id, title, sub, status, rail})`、`chip(text)`、`stat({value, label, tone})`、`toolCard({group, id, icon, title, sub})`、`rail({tone})`、`iconTile({icon, tone})` —— 全部返回 HTML 字符串

- [ ] **Step 1: 搬运设计令牌**

把 `prototype.html:15-47`（`:root { … }` 整块，含文件头注释）复制进 `web/styles/tokens.css`，并保留其上方 `prototype.html:9-14` 的三行设计方向注释。

```bash
python - <<'PY'
from pathlib import Path
src = Path("docs/ui-preview/prototype-v2.html").read_text(encoding="utf-8").splitlines(keepends=True)
# 行号 1-based → 切片 0-based
Path("web/styles/tokens.css").write_text("".join(src[8:47]), encoding="utf-8")   # 9-47
PY
```

【搬运】校验：

```bash
grep -c -- "--brand:\|--paper:\|--r-xl:" web/styles/tokens.css
grep -q "min(480px" web/styles/tokens.css || echo "注意：手机壳规则属 shell.css，见 Task 3"
```

Expected: 至少 3 行命中（`--brand`、`--paper`、`--r-xl`）

- [ ] **Step 2: 搬运基础样式**

把 `prototype.html:49-69`（`* { box-sizing }` 到 `.mono`，含 `html`/`body`/`button`/`a`/`h1,h2,h3,p`/`.ic`）复制进 `web/styles/base.css`。

```bash
python - <<'PY'
from pathlib import Path
src = Path("docs/ui-preview/prototype-v2.html").read_text(encoding="utf-8").splitlines(keepends=True)
Path("web/styles/base.css").write_text("".join(src[48:69]), encoding="utf-8")   # 49-69
PY
grep -c "box-sizing\|\.ic {\|\.mono {" web/styles/base.css
```

Expected: ≥ 3

- [ ] **Step 3: 写失败的浏览器测试**

创建 `scripts/selftest_web_ui.py`。这是后续所有视图任务共用的浏览器测试骨架，先起服务、再断言令牌与转义。

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

    def test_injected_markup_is_not_parsed(self):
        """Review Focus 1：用户输入含 HTML 时不得被解析成元素。"""
        _Browser.page.evaluate(
            "async () => { const m = await import('/web/js/dom.js');"
            "const v = document.getElementById('view');"
            "v.innerHTML = '<div id=probe>' + m.esc('<b>粗体</b>') + '</div>'; }")
        probe = _Browser.page.locator("#probe")
        self.assertEqual(probe.inner_text(), "<b>粗体</b>")
        self.assertEqual(probe.locator("b").count(), 0)


class SharedComponentsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Browser.start()

    def test_page_head_escapes_its_title(self):
        got = _Browser.page.evaluate(
            "async () => { const c = await import('/web/js/components.js');"
            "return c.pageHead({title:'<script>x</script>', lead:'a & b'}); }")
        self.assertNotIn("<script>", got)
        self.assertIn("&lt;script&gt;", got)
        self.assertIn("a &amp; b", got)

    def test_ic_renders_an_svg_with_the_prototype_geometry(self):
        got = _Browser.page.evaluate(
            "async () => { const m = await import('/web/js/icons.js'); return m.ic('home'); }")
        self.assertIn('class="ic', got)
        self.assertIn('viewBox="0 0 24 24"', got)
        self.assertIn("M3 10.5 12 3l9 7.5", got)   # 原型 home 图标路径


def _teardown_module():
    _Browser.stop()


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        _Browser.stop()
```

- [ ] **Step 4: 起服务并运行测试确认失败**

```bash
PORT=7899 "C:/Users/ymc/Desktop/agent/_recon/probe-venv/Scripts/python.exe" app.py &
sleep 12
"C:/Users/ymc/Desktop/agent/_recon/probe-venv/Scripts/python.exe" scripts/selftest_web_ui.py
```

Expected: FAIL —— `/web/js/dom.js` 与 `/web/js/components.js` 不存在，`main.js` 尚未导入它们

- [ ] **Step 5: 搬运图标表并写 `web/js/icons.js`**

把 `prototype.html:902-936`（`const ICONS = { … }` 与 `const ic = (name, cls) => …`）复制为新文件主体，并把两处 `const` 改成 `export const`。

```bash
python - <<'PY'
from pathlib import Path
src = Path("docs/ui-preview/prototype-v2.html").read_text(encoding="utf-8").splitlines(keepends=True)
body = "".join(src[901:936])                      # 902-936
body = body.replace("  const ICONS = {", "export const ICONS = {", 1)
body = body.replace("  const ic = (name, cls) =>", "export const ic = (name, cls) =>", 1)
header = ("// 图标表搬运自 prototype.html:902-936，未做任何改动。\n"
          "// 新增图标前请先确认原型里确实没有。\n")
Path("web/js/icons.js").write_text(header + body, encoding="utf-8")
PY
grep -c "export const ICONS\|export const ic" web/js/icons.js
grep -c "radar:\|shield:\|compare:" web/js/icons.js
```

Expected: `2`；第二个 grep ≥ 3（确认图标表是完整的，不是被截断的）

- [ ] **Step 6: 写 `web/js/dom.js`**

```js
// 模板与转义工具。所有插值都必须经过 esc() 或 h`` —— 见 Review Focus 1。

export const esc = (value) => String(value ?? "").replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/** 带标签模板：除 HTML 片段外，所有插值自动转义。 */
export const h = (strings, ...values) => strings.reduce((out, part, i) => {
  if (i === 0) return part;
  const v = values[i - 1];
  const rendered = Array.isArray(v) ? v.join("") : esc(v);
  return out + rendered + part;
}, "");
```

注意 `h` 的语义：数组插值按"已渲染片段"直接拼接（调用方负责用 `esc` 处理元素），标量插值自动转义。这是刻意设计——视图里大量 `items.map(row)` 需要拼片段，而零散字段需要转义。

**`raw` 不需要出现在最终代码里**：M1 的每个视图都能只用 `esc` 与 `h` 写完（`components.js` 已经把拼片段的场景收敛成了组件函数）。既然没有调用方，就不要导出它——绕过转义的逃生舱口一旦存在就会被用。若实现时确实需要拼接未转义片段，那说明该片段应该先变成一个组件函数，而不是打开这个口子。

- [ ] **Step 7: 写 `web/js/components.js`**

```js
// 通用组件：与 prototype.html 里反复出现的片段一一对应。
// 样式全部来自 components.css（Task 3 搬运），这里只产出结构。
import { esc, h } from "./dom.js";
import { ic } from "./icons.js";

export const pageHead = ({ title, lead }) => h`
  <div class="page-head">
    <h1>${title}</h1>
    ${lead ? h`<p>${lead}</p>` : ""}
  </div>`;

export const sectionHead = ({ title, count = "", action = "" }) => h`
  <div class="section-head">
    <b>${title}</b><span>${count}</span>${action}
  </div>`;

export const card = (inner, cls = "") =>
  `<section class="card ${esc(cls)}">${inner}</section>`;

/** 状态点：ok=绿 / warn=琥珀 / muted=灰，对应原型 .rail 的三种色调。 */
export const rail = (tone = "ok") =>
  `<span class="rail rail--${esc(tone)}" aria-hidden="true"></span>`;

export const row = ({ id, title, sub, status, tone = "ok" }) => h`
  <button class="row" data-action="detail" data-id="${id}">
    ${rail(tone)}
    <span class="row__copy">
      <b>${title}</b>
      ${sub ? h`<span>${sub}</span>` : ""}
    </span>
    ${status ? h`<span class="row__status">${status}</span>` : ""}
    ${ic("chevron")}
  </button>`;

export const chip = (text) => `<span class="chip">${esc(text)}</span>`;

export const stat = ({ value, label, tone = "" }) => h`
  <div class="stat ${tone ? "stat--" + tone : ""}">
    <b>${value}</b><span>${label}</span>
  </div>`;

export const iconTile = ({ icon, tone = "" }) => h`
  <span class="tool__icon ${tone ? "tool__icon--" + tone : ""}">${ic(icon)}</span>`;

export const toolCard = ({ group, id, icon, title, sub }) => h`
  <button class="tool" data-action="open-tool" data-group="${group}" data-tool="${id}">
    ${iconTile({ icon })}
    <span class="tool__copy"><b>${title}</b><span>${sub}</span></span>
    ${ic("chevron")}
  </button>`;

export const emptyState = (text) => h`<p class="fine fine--empty">${text}</p>`;
```

- [ ] **Step 8: 运行测试确认通过**

```bash
"C:/Users/ymc/Desktop/agent/_recon/probe-venv/Scripts/python.exe" scripts/selftest_web_ui.py
```

Expected: PASS（5 个用例）

- [ ] **Step 9: 提交**

```bash
git add web/styles/tokens.css web/styles/base.css web/js/icons.js web/js/dom.js web/js/components.js scripts/selftest_web_ui.py
git commit -m "feat(web): prototype design tokens, icons and shared components"
```

---

## Task 3: 应用外壳、底部标签栏与路由

**Files:**
- Modify: `web/styles/shell.css`（替换占位；【搬运】原型的外壳与导航分节）
- Create: `web/js/store.js`
- Create: `web/js/router.js`
- Modify: `web/js/main.js`（替换 Task 1 的占位）
- Test: `scripts/selftest_web_ui.py`（追加测试类）

**Interfaces:**
- Consumes: `ic()`（Task 2）、`esc`/`h`（Task 2）、`components.js`（Task 2）
- Produces:
  - `web/js/store.js` → `export const store`，含 `store.state`、`store.set(patch) -> void`、`store.subscribe(fn) -> () => void`、`store.reset() -> void`
    - `store.state` 形状：`{ category: string, market: string, markets: string[], platform: string, resultId: string|null, filter: string }`
  - `web/js/router.js` → `export const ROUTES`（`Record<string, () => object>`）、`export const parse = (hash) => {path, group, tool}`、`export const navigate = (route) => void`、`export const start = (onRoute) => void`、`export const activeTab = (route) => "home"|"regulations"|"assistant"|"action"|"profile"`
  - `web/js/main.js` → 无导出；导入即启动

- [ ] **Step 1: 写失败的测试**

在 `scripts/selftest_web_ui.py` 的 `_teardown_module` 之前追加：

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
        """原型的中央助手是凸起药丸，不是普通标签。"""
        self.assertEqual(_Browser.page.locator("#tabbar .tab--main").count(), 1)
        self.assertIn("助手", _Browser.page.locator("#tabbar .tab--main").inner_text())

    def test_active_tab_follows_the_route_group(self):
        cases = [("home", "首页"), ("freshness", "首页"), ("result", "首页"),
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

    def test_unknown_route_falls_back_to_home(self):
        """Review Focus 2：畸形/未知 hash 不得白屏。"""
        for bad in ["regulations/不存在", "action/zzz", "完全瞎写", "", "//"]:
            with self.subTest(bad=bad):
                _Browser.goto(bad)
                self.assertTrue(_Browser.page.locator("#view").inner_text().strip(),
                                "未知路由必须回落到首页而不是白屏")

    def test_shell_mount_points_match_the_prototype(self):
        for node_id in ["shell", "appbar", "view", "dock", "tabbar",
                        "backdrop", "sheet", "toast"]:
            with self.subTest(node_id=node_id):
                self.assertEqual(_Browser.page.locator(f"#{node_id}").count(), 1)


class StoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Browser.start()

    def test_changing_conditions_drops_the_previous_result_anchor(self):
        """Review Focus 4：先查德国再切美国时，不得把旧结果当成新条件的结果。"""
        got = _Browser.page.evaluate("""async () => {
          const { store } = await import('/web/js/store.js');
          store.reset();
          store.set({ resultId: '德国-清单' });
          const before = store.state.resultId;
          store.setConditions({ market: '美国' });
          return { before, after: store.state.resultId, market: store.state.market };
        }""")
        self.assertEqual(got["before"], "德国-清单")
        self.assertIsNone(got["after"], "换条件必须作废旧结果锚点")
        self.assertEqual(got["market"], "美国")

    def test_plain_set_keeps_the_result_anchor(self):
        """只改筛选（不换条件）时结果锚点必须保留，否则展开/筛选会跳位。"""
        got = _Browser.page.evaluate("""async () => {
          const { store } = await import('/web/js/store.js');
          store.reset();
          store.set({ resultId: 'R1' });
          store.set({ filter: '需处理' });
          return store.state.resultId;
        }""")
        self.assertEqual(got, "R1")

    def test_subscribers_are_notified_and_can_unsubscribe(self):
        got = _Browser.page.evaluate("""async () => {
          const { store } = await import('/web/js/store.js');
          store.reset();
          let hits = 0;
          const off = store.subscribe(() => { hits += 1; });
          store.set({ filter: '全部' });
          off();
          store.set({ filter: '需处理' });
          return hits;
        }""")
        self.assertEqual(got, 1)
```

- [ ] **Step 2: 运行测试确认失败**

```bash
"C:/Users/ymc/Desktop/agent/_recon/probe-venv/Scripts/python.exe" scripts/selftest_web_ui.py ShellTests
```

Expected: FAIL —— `#tabbar` 为空（`main.js` 还是 Task 1 的占位）

- [ ] **Step 3: 搬运外壳与导航样式**

按分节搬运进 `web/styles/shell.css`（追加，保持原型顺序）：

| 目标文件 | 原型行号 | 内容 |
|---|---|---|
| `web/styles/shell.css` | `71-91` | 手机壳 `.app-shell`（含 `@media (min-width: 700px)`） |
| `web/styles/shell.css` | `92-135` | 顶栏 `.appbar` / `.brand` / `.live-dot` / `.bar-title` / `.iconbtn` |
| `web/styles/shell.css` | `136-148` | 主滚动区 `.view` |
| `web/styles/shell.css` | `598-639` | 底部导航 `.tabbar` / `.tab` / `.tab--main` |
| `web/styles/shell.css` | `552-597` | 输入区 `.composer`（Task 6 用，先搬） |
| `web/styles/shell.css` | `781-855` | 抽屉 `.sheet` / `.backdrop`（Task 4 用，先搬） |
| `web/styles/shell.css` | `856-876` | 轻提示 `.toast`（Task 4 用，先搬） |
| `web/styles/shell.css` | `877-881` | 可访问性规则（**不含** 882 行的 `</style>`） |
| `web/styles/components.css` | `434-445` | 通用页头 `.page-head` |
| `web/styles/components.css` | `527-551` | 按钮 `.btn` |
| `web/styles/views.css` | `204-306` | 工作台首页与法规时效只读卡 |
| `web/styles/views.css` | `149-203` | 首页 hero 与推荐项 `.reco` |
| `web/styles/views.css` | `307-326` | 首次使用态 |
| `web/styles/views.css` | `327-343` | 教程页 |
| `web/styles/views.css` | `344-368` | 法规中心 / 行动入口 / 时效性检查 |
| `web/styles/views.css` | `369-433` | 对话 |
| `web/styles/views.css` | `446-526` | 结果页 |
| `web/styles/views.css` | `640-732` | 法规库 |
| `web/styles/views.css` | `733-755` | 检索 |
| `web/styles/views.css` | `756-780` | 我的 |

一次性完成所有搬运（后续任务不再重复搬运样式）：

```bash
python - <<'PY'
from pathlib import Path
src = Path("docs/ui-preview/prototype-v2.html").read_text(encoding="utf-8").splitlines(keepends=True)

def take(a, b):            # 1-based 闭区间
    return "".join(src[a - 1:b])

shell = (take(71, 148) + take(552, 639) + take(781, 881))   # 881 为终点：882 是 </style>
components = take(434, 445) + take(527, 551)
views = (take(149, 433) + take(446, 526) + take(640, 780))

Path("web/styles/shell.css").write_text(
    "/* 搬运自 prototype.html：71-148, 552-639, 781-882。未做改动。 */\n" + shell, encoding="utf-8")
Path("web/styles/components.css").write_text(
    "/* 搬运自 prototype.html：434-445, 527-551。未做改动。 */\n" + components, encoding="utf-8")
Path("web/styles/views.css").write_text(
    "/* 搬运自 prototype.html：149-433, 446-526, 640-780。未做改动。 */\n" + views, encoding="utf-8")
PY
```

【搬运】校验（每节都必须留下可辨识的规则）：

```bash
grep -c "\.app-shell\|\.appbar\|\.tabbar\|\.tab--main" web/styles/shell.css
grep -c "\.page-head\|\.btn" web/styles/components.css
grep -c "\.wb-head\|\.fresh-card\|\.reco\|\.tool\b" web/styles/views.css
```

Expected: 均 ≥ 3

- [ ] **Step 4: 写 `web/js/store.js`**

```js
// 会话状态。抽屉与筛选不写 URL（照原型），因此它们住在 store 里而不是路由里。

const initial = () => ({
  category: "儿童玩具",
  market: "德国",
  markets: ["欧盟", "美国"],
  platform: "亚马逊",
  resultId: null,
  filter: "全部",
});

export const store = {
  state: initial(),
  _subs: new Set(),

  set(patch) {
    this.state = { ...this.state, ...patch };
    this._subs.forEach((fn) => fn(this.state));
  },

  /** 条件变化时清掉上一次的结果锚点，避免旧结果被当成新条件的结果。 */
  setConditions(patch) {
    this.set({ ...patch, resultId: null });
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

`setConditions` 是 Review Focus 4（会话中途切换条件）的落点：换条件必须同时作废旧结果锚点。

- [ ] **Step 5: 写 `web/js/router.js`**

```js
// hash 路由。语义照原型：go("regulations/map") → "#/regulations/map"。

import home from "./views/home.js";
import result from "./views/result.js";
import freshness from "./views/freshness.js";
import assistant from "./views/assistant.js";
import regulations from "./views/regulations.js";
import search from "./views/search.js";
import tool from "./views/tool.js";
import action from "./views/action.js";
import profile from "./views/profile.js";
import tutorial from "./views/tutorial.js";

/** 静态路由表。工具页由 tool.js 按 tool 名分发，避免 7 个近乎相同的模块。 */
export const ROUTES = {
  home,
  result,
  freshness,
  assistant,
  regulations,
  "regulations/search": search,
  regulations_tool: tool,     // 见 parse()：regulations/<tool> 走这里
  action,
  action_tool: tool,          // action/<tool>
  profile,
  "profile/tutorial": tutorial,
};

const TOOL_NAMES = ["map", "timeline", "todo", "readiness", "journey", "compare", "multi"];

export const parse = (hash) => {
  const path = String(hash || "").replace(/^#\/?/, "").replace(/\/+$/, "");
  if (!path) return { path: "home", group: null, tool: null };

  if (path === "regulations") return { path, group: null, tool: null };
  if (path === "action") return { path, group: null, tool: null };

  const [head, tail] = path.split("/");
  if ((head === "regulations" || head === "action") && tail) {
    // Review Focus 2：未知工具名必须回落，不得白屏。
    const toolName = TOOL_NAMES.includes(tail) ? tail : TOOL_NAMES[0];
    return { path: `${head}_tool`, group: head, tool: toolName };
  }
  if (ROUTES[path]) return { path, group: null, tool: null };
  return { path: "home", group: null, tool: null };
};

export const activeTab = (route) => {
  if (route.startsWith("regulations")) return "regulations";
  if (route.startsWith("action")) return "action";
  if (route.startsWith("profile")) return "profile";
  if (route === "assistant") return "assistant";
  return "home";   // home / result / freshness 都归首页
};

export const navigate = (route) => { location.hash = "#/" + String(route).replace(/^#?\/?/, ""); };

export const start = (onRoute) => {
  const run = () => onRoute(parse(location.hash));
  window.addEventListener("hashchange", run);
  run();
};
```

- [ ] **Step 6: 建视图桩模块**

`main.js` 在导入时会拉起全部 10 个视图模块，所以它们**必须在本任务就存在**，否则本任务的测试无法通过。先建桩，后续视图任务逐个替换为真实实现。

```bash
mkdir -p web/js/views
for v in home result freshness assistant regulations search tool action profile tutorial; do
  cat > "web/js/views/$v.js" <<EOF
// 桩：由后续视图任务替换为真实实现。
export default {
  title: "出海合规雷达",
  sub: "桩视图",
  render() { return '<p class="fine">$v 视图待实现</p>'; },
};
EOF
done
ls web/js/views/ | wc -l
```

Expected: `10`

- [ ] **Step 7: 写 `web/js/ui/detail.js`**

详情抽屉的内容用注册表解耦：`main.js` 只依赖接口，各视图任务按需注册自己的详情渲染器。这样 `main.js` 不必反过来依赖所有视图。

```bash
cat > web/js/ui/detail.js <<'EOF'
// 详情抽屉的内容注册表。默认渲染器保证任何 id 都有可读兜底，不会白屏。
import { esc } from "../dom.js";

let impl = (id) => `
  <div class="sheet__grab"></div>
  <div class="sheet__body"><h2>${esc(id)}</h2></div>`;

export const registerDetail = (fn) => { impl = fn; };
export const detailSheet = (id) => impl(id);
EOF
```

- [ ] **Step 8: 写 `web/js/main.js`**

```js
// 启动：渲染外壳、绑定全局事件、启动路由。导入即执行。

import { ic } from "./icons.js";
import { h } from "./dom.js";
import { store } from "./store.js";
import { ROUTES, parse, navigate, start, activeTab } from "./router.js";
import { openSheet, closeSheet } from "./ui/sheet.js";
import { showToast } from "./ui/toast.js";
import { detailSheet } from "./ui/detail.js";

const TABS = [
  ["home", "home", "首页"],
  ["regulations", "book", "法规"],
  ["assistant", "chat", "助手"],
  ["action", "flag", "行动"],
  ["profile", "user", "我的"],
];

const els = {
  appbar: document.getElementById("appbar"),
  view: document.getElementById("view"),
  dock: document.getElementById("dock"),
  tabbar: document.getElementById("tabbar"),
};

export const renderTabbar = (route) => {
  const active = activeTab(route);
  els.tabbar.innerHTML = TABS.map(([to, icon, label]) => {
    const on = active === to;
    if (to === "assistant") {
      return h`
        <button class="tab tab--main ${on ? "is-on" : ""}" data-action="nav" data-to="${to}"
                aria-current="${on ? "page" : "false"}" aria-label="${label}">
          <span class="tab__main">${ic(icon)}<span>${label}</span></span>
        </button>`;
    }
    return h`
      <button class="tab ${on ? "is-on" : ""}" data-action="nav" data-to="${to}"
              aria-current="${on ? "page" : "false"}">
        <span class="tab__wrap">${ic(icon)}</span>
        <span>${label}</span>
      </button>`;
  }).join("");
};

export const renderAppbar = (view, route) => {
  const title = view.title ?? "合规雷达";
  const sub = view.sub ?? "";
  els.appbar.innerHTML = view.back
    ? h`
      <button class="iconbtn iconbtn--ghost" data-action="back" aria-label="返回">${ic("back")}</button>
      <span class="bar-title">
        <span class="bar-title__name">${title}</span>
        ${sub ? h`<span class="bar-title__sub">${sub}</span>` : ""}
      </span>
      <button class="iconbtn iconbtn--ghost" data-action="history" aria-label="历史结果">${ic("history")}</button>`
    : h`
      <span class="brand">
        <span class="brand__mark">${ic("radar")}</span>
        <span>
          <span class="brand__name">${title}</span>
          <span class="brand__sub"><span class="live-dot"></span>${sub}</span>
        </span>
      </span>
      <button class="iconbtn iconbtn--ghost" data-action="history" aria-label="历史结果">${ic("history")}</button>
      <button class="iconbtn iconbtn--ghost" data-action="new" aria-label="新建">${ic("plus")}</button>`;
};

const render = (r) => {
  const view = ROUTES[r.path] ?? ROUTES.home;
  const ctx = { route: r, store, navigate, openSheet, closeSheet, showToast };
  renderAppbar(view, r.path);
  renderTabbar(r.path);
  els.view.className = view.viewClass ? `view ${view.viewClass}` : "view";
  els.view.innerHTML = view.render(ctx);
  els.view.scrollTop = 0;
  els.dock.innerHTML = view.dock ? view.dock(ctx) : "";
  view.mount?.(els.view, ctx);
};

document.addEventListener("click", (event) => {
  const nav = event.target.closest("[data-action='nav']");
  if (nav) { navigate(nav.dataset.to); return; }
  const tool = event.target.closest("[data-action='open-tool']");
  if (tool) { navigate(`${tool.dataset.group}/${tool.dataset.tool}`); return; }
  const back = event.target.closest("[data-action='back']");
  if (back) { history.length > 1 ? history.back() : navigate("home"); return; }
  if (event.target.closest("[data-action='close-sheet'], #backdrop")) { closeSheet(); return; }
  const detail = event.target.closest("[data-action='detail']");
  if (detail) { openSheet(detailSheet(detail.dataset.id)); return; }
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeSheet();
});

start(render);
```

- [ ] **Step 9: 建 `ui/sheet.js` 与 `ui/toast.js` 桩**

`main.js` 导入了这两个模块，本任务先把它们建出来；完整实现见 Task 4。

```bash
cat > web/js/ui/sheet.js <<'EOF'
// 桩：Task 4 替换为完整实现。
export const openSheet = () => {};
export const closeSheet = () => {};
EOF
cat > web/js/ui/toast.js <<'EOF'
// 桩：Task 4 替换为完整实现。
export const showToast = () => {};
EOF
```

- [ ] **Step 10: 运行测试确认通过**

```bash
"C:/Users/ymc/Desktop/agent/_recon/probe-venv/Scripts/python.exe" scripts/selftest_web_ui.py ShellTests
```

Expected: PASS（ShellTests 5 + StoreTests 3 = 8；`test_unknown_route_falls_back_to_home` 的 5 个子用例全过）

- [ ] **Step 11: 全量回归确认 Task 2 未被破坏**

```bash
"C:/Users/ymc/Desktop/agent/_recon/probe-venv/Scripts/python.exe" scripts/selftest_web_ui.py
```

Expected: PASS。此后的每个任务都以此为准：**新测试类全通过，且既有测试类一个不少、全部仍通过**。（累计数量会随任务增长，故不再逐个写死；若有既有用例转红，即为回归。）

- [ ] **Step 12: 提交**

```bash
git add web/js/store.js web/js/router.js web/js/main.js web/js/views web/js/ui scripts/selftest_web_ui.py
git commit -m "feat(web): app shell, bottom tabbar and hash router"
```

---

## Task 4: 底部抽屉与轻提示

**Files:**
- Modify: `web/js/ui/sheet.js`（替换桩）
- Modify: `web/js/ui/toast.js`（替换桩）
- Test: `scripts/selftest_web_ui.py`（追加测试类）

**Interfaces:**
- Consumes: `#sheet` / `#backdrop` / `#toast` 三个挂载点（Task 1）；`.is-on` 类（Task 3 搬运的 `shell.css:781-882`）
- Produces:
  - `ui/sheet.js` → `openSheet(html: string) -> void`、`closeSheet() -> void`、`isSheetOpen() -> boolean`
  - `ui/toast.js` → `showToast(text: string) -> void`

原型的抽屉靠给 `#backdrop` 与 `#sheet` 加 `.is-on` 打开（`prototype.html:2322-2333`），CSS 里 `.sheet` 默认 `translateY(100%)`、`.sheet.is-on` 归零（`prototype.html:789-808`）。所以本任务只需管类名与 aria，不需要手写动画。

- [ ] **Step 1: 写失败的测试**

追加到 `scripts/selftest_web_ui.py`（`_teardown_module` 之前）：

```python
class SheetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Browser.start()

    def setUp(self):
        _Browser.goto("home")
        _Browser.page.evaluate(
            "async () => { const s = await import('/web/js/ui/sheet.js'); s.closeSheet(); }")

    def test_open_and_close_toggle_the_prototype_classes(self):
        _Browser.page.evaluate(
            "async () => { const s = await import('/web/js/ui/sheet.js');"
            "s.openSheet('<div class=\"sheet__body\"><h2>详情</h2></div>'); }")
        self.assertIn("is-on", _Browser.page.locator("#sheet").get_attribute("class"))
        self.assertIn("is-on", _Browser.page.locator("#backdrop").get_attribute("class"))
        self.assertEqual(_Browser.page.locator("#sheet").get_attribute("aria-hidden"), "false")

        _Browser.page.evaluate(
            "async () => { const s = await import('/web/js/ui/sheet.js'); s.closeSheet(); }")
        self.assertNotIn("is-on", _Browser.page.locator("#sheet").get_attribute("class"))
        self.assertNotIn("is-on", _Browser.page.locator("#backdrop").get_attribute("class"))

    def test_sheet_is_marked_dialog_and_modal(self):
        role = _Browser.page.locator("#sheet").get_attribute("role")
        self.assertEqual(role, "dialog")
        self.assertEqual(_Browser.page.locator("#sheet").get_attribute("aria-modal"), "true")

    def test_escape_and_backdrop_click_close_the_sheet(self):
        open_js = ("async () => { const s = await import('/web/js/ui/sheet.js');"
                   "s.openSheet('<div class=\"sheet__body\"><h2>详情</h2></div>'); }")
        _Browser.page.evaluate(open_js)
        _Browser.page.keyboard.press("Escape")
        _Browser.page.wait_for_timeout(200)
        self.assertNotIn("is-on", _Browser.page.locator("#sheet").get_attribute("class"))

        _Browser.page.evaluate(open_js)
        _Browser.page.locator("#backdrop").click(force=True)
        _Browser.page.wait_for_timeout(200)
        self.assertNotIn("is-on", _Browser.page.locator("#sheet").get_attribute("class"))

    def test_sheet_content_is_escaped_by_the_caller_contract(self):
        """Review Focus 1：抽屉内容里的用户输入必须已被转义。"""
        _Browser.page.evaluate(
            "async () => { const d = await import('/web/js/dom.js');"
            "const s = await import('/web/js/ui/sheet.js');"
            "s.openSheet('<div class=\"sheet__body\"><p id=probe>' + d.esc('<b>x</b>') + '</p></div>'); }")
        self.assertEqual(_Browser.page.locator("#probe").locator("b").count(), 0)


class ToastTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Browser.start()

    def test_toast_shows_then_hides(self):
        _Browser.page.evaluate(
            "async () => { const t = await import('/web/js/ui/toast.js'); t.showToast('先写一句你的产品'); }")
        self.assertIn("is-on", _Browser.page.locator("#toast").get_attribute("class"))
        self.assertEqual(_Browser.page.locator("#toast").inner_text(), "先写一句你的产品")
        _Browser.page.wait_for_timeout(2600)
        self.assertNotIn("is-on", _Browser.page.locator("#toast").get_attribute("class"))

    def test_toast_announces_politely(self):
        self.assertEqual(_Browser.page.locator("#toast").get_attribute("aria-live"), "polite")
```

- [ ] **Step 2: 运行测试确认失败**

```bash
"C:/Users/ymc/Desktop/agent/_recon/probe-venv/Scripts/python.exe" scripts/selftest_web_ui.py SheetTests ToastTests
```

Expected: FAIL —— 桩实现不切换类名

- [ ] **Step 3: 实现 `web/js/ui/sheet.js`**

```js
// 底部抽屉。样式全部来自 shell.css（搬运自 prototype.html:781-855），
// 这里只负责类名与 aria —— 动画由 CSS 过渡完成，与原型一致。
const backdrop = () => document.getElementById("backdrop");
const sheet = () => document.getElementById("sheet");

export const isSheetOpen = () => sheet()?.classList.contains("is-on") ?? false;

export const openSheet = (html) => {
  const node = sheet();
  if (!node) return;
  node.innerHTML = String(html ?? "");
  node.classList.add("is-on");
  node.setAttribute("aria-hidden", "false");
  backdrop()?.classList.add("is-on");
};

export const closeSheet = () => {
  const node = sheet();
  if (!node) return;
  node.classList.remove("is-on");
  node.setAttribute("aria-hidden", "true");
  backdrop()?.classList.remove("is-on");
};
```

`#sheet` 的 `role="dialog"` / `aria-modal="true"` 已在 `index.html` 里静态声明（Task 1 Step 5），因此抽屉本身不需要再设置。

- [ ] **Step 4: 实现 `web/js/ui/toast.js`**

```js
// 轻提示。原型用 2400ms 自动隐藏（prototype.html:2147-2152），照搬。
const DURATION = 2400;
let timer = null;

export const showToast = (text) => {
  const node = document.getElementById("toast");
  if (!node) return;
  node.textContent = String(text ?? "");
  node.classList.add("is-on");
  if (timer) clearTimeout(timer);
  timer = setTimeout(() => node.classList.remove("is-on"), DURATION);
};
```

- [ ] **Step 5: 运行测试确认通过**

```bash
"C:/Users/ymc/Desktop/agent/_recon/probe-venv/Scripts/python.exe" scripts/selftest_web_ui.py
```

Expected: PASS（SheetTests 4 + ToastTests 2 全通过，既有类无回归）

- [ ] **Step 6: 提交**

```bash
git add web/js/ui/sheet.js web/js/ui/toast.js scripts/selftest_web_ui.py
git commit -m "feat(web): bottom sheet and toast"
```

---

## Task 5: 首页视图

**Files:**
- Modify: `web/js/views/home.js`（替换桩）
- Test: `scripts/selftest_web_ui.py`（追加测试类）

**Interfaces:**
- Consumes: `pageHead` / `sectionHead` / `card` / `stat` / `chip` / `row` / `rail`（Task 2）；`store`（Task 3）；`showToast`（Task 4）
- Produces: `web/js/views/home.js` 默认导出 `{ title, sub, render(ctx) }`
  - `render(ctx)` 返回首页 HTML；`ctx.showDetail(id)` 打开条目详情

**原型对照**：结构与文案照 `prototype.html:1269-1374`（`homeView()`）；样式来自 Task 3 已搬运的 `views.css`（原型 `204-306`：工作台首页、法规时效只读卡）。

**示例数据**：M1 用固定示例数据渲染，来源照抄原型 `prototype.html:939-1148` 的 `ITEMS` / `FRESH_ITEMS` / `PRIORITIES`。在 `views/home.js` 顶部以 `SAMPLE` 常量声明，M2 换成 `/api/*`。

- [ ] **Step 1: 写失败的测试**

在 `scripts/selftest_web_ui.py` 的 `if __name__ == "__main__":` 块**之前**追加。
追加到文件末尾会让新测试类定义晚于 `unittest.main()`，这些用例会被**静默跳过**——
输出仍显示 PASS，实际一个都没跑。追加后务必确认运行输出里出现了本任务新增的用例名。

```python
class HomeViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Browser.start()

    def test_headline_and_context_chips_match_the_prototype(self):
        _Browser.goto("home")
        view = _Browser.page.locator("#view")
        self.assertIn("最近检查", view.inner_text())
        for label in ["儿童玩具", "德国", "亚马逊"]:
            with self.subTest(label=label):
                self.assertIn(label, view.inner_text())

    def test_freshness_card_renders_the_four_readonly_stats(self):
        _Browser.goto("home")
        stats = _Browser.page.locator("#view .fresh-card .stat").all_inner_texts()
        self.assertEqual(len(stats), 4)
        joined = " ".join(stats)
        for label in ["核验链接", "可访问", "待复核", "内容更新"]:
            with self.subTest(label=label):
                self.assertIn(label, joined)

    def test_readonly_card_explains_its_own_scope(self):
        """规格要求只读卡片必须自述边界，不能被当成合规结论。"""
        _Browser.goto("home")
        text = _Browser.page.locator("#view").inner_text()
        self.assertIn("无需手动操作", text)
        self.assertIn("不等于法规条文变更", text)

    def test_continue_card_and_progress_are_present(self):
        _Browser.goto("home")
        text = _Browser.page.locator("#view").inner_text()
        self.assertIn("继续上次", text)
        self.assertIn("上线进度", text)

    def test_tapping_a_row_opens_the_detail_sheet(self):
        _Browser.goto("home")
        _Browser.page.locator("#view [data-action='detail']").first.click()
        _Browser.page.wait_for_timeout(300)
        self.assertIn("is-on", _Browser.page.locator("#sheet").get_attribute("class"))
        self.assertTrue(_Browser.page.locator("#sheet").inner_text().strip())
```

- [ ] **Step 2: 运行测试确认失败**

```bash
"C:/Users/ymc/Desktop/agent/_recon/probe-venv/Scripts/python.exe" scripts/selftest_web_ui.py HomeViewTests
```

Expected: FAIL —— 桩视图无「最近检查」

- [ ] **Step 3: 写 `web/js/views/home.js`**

```js
// 首页（工作台）。结构与文案照 prototype.html:1269-1374 的 homeView()。
// M1 数据为示例常量；M2 换成 /api/bootstrap 与 /api/freshness。
import { h } from "../dom.js";
import { ic } from "../icons.js";
import { card, chip, rail, row, sectionHead, stat } from "../components.js";

const SAMPLE = {
  date: "10月19日",
  context: ["儿童玩具", "德国", "亚马逊", "不带电"],
  freshness: {
    checkedAt: "今天 09:00",
    meta: "86 条官方链接 · 数据截止 10-19 · 每天 09:00 / 21:00 自动核验",
    stats: [
      { value: "86", label: "核验链接", tone: "" },
      { value: "84", label: "可访问", tone: "" },
      { value: "2", label: "待复核", tone: "warn" },
      { value: "0", label: "内容更新", tone: "" },
    ],
    rows: [
      { text: "2 条官方链接待复核", sub: "本机网络未连通，不判死链；下次核验会重试", tone: "warn" },
      { text: "0 条内容有更新", sub: "与上次核验的页面哈希一致", tone: "ok" },
    ],
  },
  resume: { title: "德国市场行动清单", meta: "3 项优先 · 7 项待办 · 数据截止 10-19", at: "今天 14:32" },
  progress: {
    done: "选品、测试已完成", next: "下一步：标签与说明书", stage: "2 / 6 阶段",
    steps: [["选品", true], ["测试", true], ["标签", false], ["文件", false],
            ["供应链", false], ["切换", false]],
  },
};

export default {
  title: "合规雷达",
  sub: "每天 09:00 / 21:00 自动核验",

  render() {
    const d = SAMPLE;
    return h`
      <section class="wb-head">
        <p class="wb-date">${d.date} · ${d.context.join(" / ")}</p>
        <h1>最近检查</h1>
        <div class="wb-context">
          <span class="context">${d.context.map(chip)}</span>
          <button class="wb-edit" data-action="detail" data-id="conditions">修改</button>
        </div>
      </section>

      <section class="fresh-card">
        <div class="fresh-card__top">
          <b>法规时效</b>
          <span class="pill"><span class="live-dot"></span>监控中</span>
          <span class="fresh-card__at">${d.freshness.checkedAt}</span>
        </div>
        <p class="fine">${d.freshness.meta}</p>
        <div class="stat-row">
          ${d.freshness.stats.map((s) => stat(s))}
        </div>
        <div class="alert-list">
          ${d.freshness.rows.map((r) => h`
            <button class="alert" data-action="detail" data-id="freshness">
              ${rail(r.tone)}
              <span class="alert__copy"><b>${r.text}</b><span>${r.sub}</span></span>
              <span class="alert__go">查看</span>
            </button>`)}
        </div>
        <div class="fresh-card__foot">
          <span class="fine">结果只读 · 无需手动操作</span>
          <button class="link" data-action="nav" data-to="freshness">查看检查记录 →</button>
        </div>
        <p class="fine">检查只核对官方链接状态与内容哈希，不等于法规条文变更；条文级变化仍以人工核对为准。</p>
      </section>

      ${sectionHead({ title: "继续上次", count: d.resume.at })}
      <button class="resume" data-action="nav" data-to="result">
        <span class="resume__icon">${ic("doc")}</span>
        <span class="resume__copy"><b>${d.resume.title}</b><span>${d.resume.meta}</span></span>
        <span class="resume__go">继续 →</span>
      </button>

      ${sectionHead({ title: "上线进度", count: d.progress.stage })}
      ${card(h`
        <div class="progress"><span style="width:${(2 / 6 * 100).toFixed(1)}%"></span></div>
        <div class="progress__meta">
          <span>${d.progress.done}</span><span>${d.progress.next}</span>
        </div>
        <div class="progress__steps">
          ${d.progress.steps.map(([label, done]) =>
            `<span class="chip ${done ? "chip--done" : ""}">${label}</span>`)}
        </div>`)}
    `;
  },
};
```

- [ ] **Step 4: 运行测试确认通过**

```bash
"C:/Users/ymc/Desktop/agent/_recon/probe-venv/Scripts/python.exe" scripts/selftest_web_ui.py HomeViewTests
```

Expected: PASS（5 个用例）

- [ ] **Step 5: 全量回归**

```bash
"C:/Users/ymc/Desktop/agent/_recon/probe-venv/Scripts/python.exe" scripts/selftest_web_ui.py
```

Expected: PASS（HomeViewTests 5 全通过，既有类无回归）

- [ ] **Step 6: 提交**

```bash
git add web/js/views/home.js scripts/selftest_web_ui.py
git commit -m "feat(web): home view"
```

---

## Task 6: 助手视图与输入区

**Files:**
- Modify: `web/js/views/assistant.js`（替换桩）
- Create: `web/js/ui/composer.js`
- Test: `scripts/selftest_web_ui.py`（追加测试类）

**Interfaces:**
- Consumes: `h` / `esc`（Task 2）、`ic`（Task 2）、`store`（Task 3）、`showToast`（Task 4）
- Produces:
  - `views/assistant.js` 默认导出 `{ title, sub, back: true, viewClass, render(ctx), dock(ctx), mount(root, ctx) }`
    - `render(ctx)`：欢迎页（未开始对话）或对话页（已有消息）
    - `dock(ctx)`：输入区 HTML
    - `mount(root, ctx)`：绑输入区事件
  - `ui/composer.js` → `composerDock() -> string`、`bindComposer(root, { onSend, onVoice }) -> void`、`voiceState() -> { text, before, backend } | null`、`applyVoice(text, meta) -> void`、`undoVoice() -> string | null`

**原型对照**：欢迎页（雷达同心圆、`我是合规雷达`、4 条推荐）照 `prototype.html:1243-1275`；对话页照 `1376-1423`；输入区照 `1946-1968` 的 `composerDock()` 与 `prototype.html:2335-2349` 的 `bindComposer()`。样式已在 Task 3 搬运（`views.css` 的 `369-433` 对话、`shell.css` 的 `552-597` 输入区）。

**语音预编辑归前端**（规格第 6 节）：`voiceState` 保存 `{text, before, backend}`，`undoVoice()` 仅在用户尚未编辑时允许撤销。M1 不接真实转写，`onVoice` 先 `showToast("语音待接入")`；M2 接 `/api/transcribe`。

- [ ] **Step 1: 写失败的测试**

在 `scripts/selftest_web_ui.py` 的 `if __name__ == "__main__":` 块**之前**追加。
追加到文件末尾会让新测试类定义晚于 `unittest.main()`，这些用例会被**静默跳过**——
输出仍显示 PASS，实际一个都没跑。追加后务必确认运行输出里出现了本任务新增的用例名。

```python
class AssistantViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Browser.start()

    def test_welcome_page_matches_the_prototype(self):
        _Browser.goto("assistant")
        text = _Browser.page.locator("#view").inner_text()
        self.assertIn("我是合规雷达", text)
        self.assertIn("告诉我你卖什么、卖到哪里。", text)
        self.assertIn("可以这样开始", text)
        self.assertIn("教程在「我的」里。", text)

    def test_welcome_offers_four_starters_with_one_lead(self):
        _Browser.goto("assistant")
        recos = _Browser.page.locator("#view .reco")
        self.assertEqual(recos.count(), 4)
        self.assertEqual(_Browser.page.locator("#view .reco--lead").count(), 1)

    def test_composer_dock_is_present_with_mic_and_send(self):
        _Browser.goto("assistant")
        self.assertEqual(_Browser.page.locator("#dock .composer").count(), 1)
        self.assertEqual(_Browser.page.locator("#dock .composer textarea").count(), 1)
        self.assertEqual(_Browser.page.locator("#dock [data-action='voice']").count(), 1)
        self.assertEqual(_Browser.page.locator("#dock [data-action='send']").count(), 1)

    def test_empty_send_warns_instead_of_submitting(self):
        """原型行为：空输入时提示而不是发送（prototype.html:2081-2092）。"""
        _Browser.goto("assistant")
        _Browser.page.locator("#dock textarea").fill("")
        _Browser.page.locator("#dock [data-action='send']").click()
        _Browser.page.wait_for_timeout(300)
        self.assertIn("is-on", _Browser.page.locator("#toast").get_attribute("class"))

    def test_sending_a_message_switches_to_the_thread_and_echoes_it_safely(self):
        """Review Focus 1：消息含 HTML 时必须原样显示为文本。"""
        _Browser.goto("assistant")
        _Browser.page.evaluate(
            "async () => { const a = await import('/web/js/views/assistant.js');"
            "const c = await import('/web/js/ui/composer.js');"
            "a.__test_send('<b>粗体</b> 卖到德国'); }")
        _Browser.page.wait_for_timeout(300)
        thread = _Browser.page.locator("#view")
        self.assertIn("<b>粗体</b> 卖到德国", thread.inner_text())
        self.assertEqual(thread.locator(".chat b").count(), 0)

    def test_voice_undo_only_before_the_user_edits(self):
        _Browser.goto("assistant")
        got = _Browser.page.evaluate("""async () => {
          const c = await import('/web/js/ui/composer.js');
          const ta = document.querySelector('#dock textarea');
          ta.value = '原文字'; c.applyVoice('识别结果', { backend: 'local' });
          ta.value = '识别结果'; ta.dispatchEvent(new Event('input'));
          const first = c.undoVoice();
          ta.value = '识别结果改了'; ta.dispatchEvent(new Event('input'));
          const second = c.undoVoice();
          return [first, second];
        }""")
        self.assertEqual(got[0], "原文字", "未编辑时应可撤销回识别前原文")
        self.assertIsNone(got[1], "用户已编辑后不得再撤销")
```

需要在 `views/assistant.js` 暴露 `__test_send` 供测试直接驱动发送（不引入仅测试用的全局函数到产品路径：`export const __test_send = send;`）。

- [ ] **Step 2: 运行测试确认失败**

```bash
"C:/Users/ymc/Desktop/agent/_recon/probe-venv/Scripts/python.exe" scripts/selftest_web_ui.py AssistantViewTests
```

Expected: FAIL —— 桩视图无「我是合规雷达」

- [ ] **Step 3: 写 `web/js/ui/composer.js`**

```js
// 输入区。结构照 prototype.html:1946-1968，事件照 2335-2349。
// 语音预编辑状态住在这里，不进后端（规格第 6 节）。
import { esc, h } from "../dom.js";
import { ic } from "../icons.js";

let voice = null;   // { text, before, backend } | null

export const voiceState = () => voice;

export const composerDock = () => h`
  <div class="composer" id="composer">
    <button class="composer__mic" data-action="voice" aria-label="按住说话">${ic("mic")}</button>
    <textarea id="composer-input" rows="1" placeholder="发消息或按住说话…"
              aria-label="输入你的问题"></textarea>
    <button class="composer__send" data-action="send" aria-label="发送">${ic("send")}</button>
  </div>`;

export const applyVoice = (text, meta = {}) => {
  const ta = document.getElementById("composer-input");
  const before = ta ? ta.value : "";
  voice = { text: String(text ?? ""), before, backend: meta.backend ?? "" };
  if (ta) ta.value = voice.text;
  return voice;
};

/** 仅在用户尚未编辑识别结果时允许撤销；返回撤销后的文本，不可撤销时返回 null。 */
export const undoVoice = () => {
  const ta = document.getElementById("composer-input");
  if (!voice || !ta) return null;
  if (ta.value !== voice.text) { voice = null; return null; }
  ta.value = voice.before;
  const restored = voice.before;
  voice = null;
  return restored;
};

export const bindComposer = (root, { onSend, onVoice } = {}) => {
  const ta = root.querySelector("#composer-input");
  const sendNow = () => {
    const value = (ta?.value ?? "").trim();
    if (!value) return onSend?.("", { empty: true });
    onSend?.(value, { empty: false });
  };
  root.querySelector("[data-action='send']")?.addEventListener("click", sendNow);
  ta?.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); sendNow(); }
  });
  root.querySelector("[data-action='voice']")?.addEventListener("click", () => onVoice?.());
  // 用户手动编辑即作废预编辑快照，撤销随之失效。
  ta?.addEventListener("input", () => {
    if (voice && ta.value !== voice.text) voice = null;
  });
};
```

- [ ] **Step 4: 写 `web/js/views/assistant.js`**

```js
// 助手。欢迎页照 prototype.html:1243-1275，对话页照 1376-1423。
import { esc, h } from "../dom.js";
import { ic } from "../icons.js";
import { bindComposer, composerDock } from "../ui/composer.js";

const STARTERS = [
  "毛绒玩具卖到德国亚马逊，要从哪里开始？",
  "儿童玩具卖到欧盟，先看相关法规",
  "比较欧盟和美国的儿童玩具法规目录",
  "最近有哪些法规变化和时间节点？",
];

const state = { messages: [] };

const welcome = () => h`
  <section class="home">
    <div class="radar-hero">
      <span class="radar-avatar">合</span>
    </div>
    <h1>我是合规雷达</h1>
    <p class="home__lead">告诉我你卖什么、卖到哪里。<br>我帮你查适用法规、看关键日期、列出下一步。</p>
    <p class="reco-label">可以这样开始</p>
    <div class="reco-list">
      ${STARTERS.map((text, i) => h`
        <button class="reco ${i === 0 ? "reco--lead" : ""}" data-action="starter" data-text="${text}">
          <span>${text}</span>${ic("chevron")}
        </button>`)}
    </div>
    <p class="home__note">我不知道的会先问你，不会替你猜产品条件。<br>教程在「我的」里。</p>
  </section>`;

const thread = () => h`
  <div class="chat" id="chatScroll">
    ${state.messages.map((m) => h`
      <div class="msg msg--${m.role}">
        <div class="msg__bubble">${m.text}</div>
      </div>`)}
  </div>`;

export const send = (text) => {
  const value = String(text ?? "").trim();
  if (!value) return false;
  state.messages.push({ role: "user", text: value });
  state.messages.push({ role: "assistant",
    text: "M1 为壳与路由阶段：这里接入 /api/route 后返回真实判定。" });
  return true;
};

export const __test_send = send;

export default {
  title: "合规雷达 · 新对话",
  sub: "deepseek-chat · 德国 / 亚马逊",
  back: true,
  viewClass: "view--chat",

  render(ctx) {
    return state.messages.length ? thread() : welcome();
  },

  dock() { return composerDock(); },

  mount(root, ctx) {
    bindComposer(document.getElementById("dock"), {
      onSend: (value, { empty }) => {
        if (empty) { ctx.showToast("先写一句你的产品、市场和问题"); return; }
        if (send(value)) {
          const ta = document.getElementById("composer-input");
          if (ta) ta.value = "";
          root.innerHTML = thread();
        }
      },
      onVoice: () => ctx.showToast("语音待接入（M2 接 /api/transcribe）"),
    });
    root.querySelectorAll("[data-action='starter']").forEach((button) => {
      button.addEventListener("click", () => {
        if (send(button.dataset.text)) root.innerHTML = thread();
      });
    });
  },
};
```

- [ ] **Step 5: 运行测试确认通过**

```bash
"C:/Users/ymc/Desktop/agent/_recon/probe-venv/Scripts/python.exe" scripts/selftest_web_ui.py AssistantViewTests
```

Expected: PASS（6 个用例）

- [ ] **Step 6: 全量回归并提交**

```bash
"C:/Users/ymc/Desktop/agent/_recon/probe-venv/Scripts/python.exe" scripts/selftest_web_ui.py
git add web/js/views/assistant.js web/js/ui/composer.js scripts/selftest_web_ui.py
git commit -m "feat(web): assistant view, composer dock and voice pre-edit"
```

---

## Task 7: 法规中心、检索与七个工具页

**Files:**
- Modify: `web/js/views/regulations.js`、`web/js/views/search.js`、`web/js/views/tool.js`（替换桩）
- Test: `scripts/selftest_web_ui.py`（追加测试类）

**Interfaces:**
- Consumes: `pageHead` / `sectionHead` / `card` / `chip` / `row` / `toolCard` / `emptyState`（Task 2）；`store`（Task 3）；`showDetail`（Task 3 via ctx）
- Produces:
  - `views/regulations.js` 默认导出 `{ title, sub, render(ctx) }`
  - `views/search.js` 默认导出 `{ title, sub, back: true, render(ctx) }`
  - `views/tool.js` 默认导出 `{ title, sub, back: true, render(ctx) }`，按 `ctx.route.tool` 分发；并导出 `TOOL_PAGES` 配置表

**原型对照**：
- 法规中心照 `prototype.html:1573-1597`（`regulationsView()`）
- 检索照 `1748-1782`（`searchView()`），条款常量照 `1735-1747`（`CLAUSES`）
- 工具页配置照 `1103-1148`（`TOOL_PAGES`），工具视图分发照 `1634-1734`（`toolView()`）
- 样式已在 Task 3 搬运（`views.css` 的 `344-368`、`640-732`、`733-755`）

- [ ] **Step 1: 写失败的测试**

在 `scripts/selftest_web_ui.py` 的 `if __name__ == "__main__":` 块**之前**追加。
追加到文件末尾会让新测试类定义晚于 `unittest.main()`，这些用例会被**静默跳过**——
输出仍显示 PASS，实际一个都没跑。追加后务必确认运行输出里出现了本任务新增的用例名。

```python
class RegulationsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Browser.start()

    def test_regulations_hub_lists_two_tools_and_a_search_entry(self):
        _Browser.goto("regulations")
        view = _Browser.page.locator("#view")
        self.assertIn("法规中心", view.inner_text())
        self.assertEqual(_Browser.page.locator("#view .tool").count(), 2)
        self.assertEqual(_Browser.page.locator("#view .search-entry").count(), 1)

    def test_search_entry_navigates_and_back_returns(self):
        _Browser.goto("regulations")
        _Browser.page.locator("#view .search-entry").click()
        _Browser.page.wait_for_timeout(300)
        self.assertIn("regulations/search", _Browser.page.url)
        self.assertEqual(_Browser.page.locator("#appbar [data-action='back']").count(), 1)

    def test_search_view_shows_the_prototype_identifier(self):
        _Browser.goto("regulations/search")
        self.assertIn("2009/48/EC", _Browser.page.locator("#view .search-entry__id").inner_text())


class ToolViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Browser.start()

    TOOLS = [("regulations", "map", "法规地图"), ("regulations", "timeline", "变化时间线"),
             ("action", "todo", "合规待办"), ("action", "readiness", "上线准备"),
             ("action", "journey", "六阶段路线"), ("action", "compare", "区域对比"),
             ("action", "multi", "多市场汇总")]

    def test_each_tool_renders_its_own_title_and_filterbar(self):
        for group, tool, title in self.TOOLS:
            with self.subTest(tool=tool):
                _Browser.goto(f"{group}/{tool}")
                view = _Browser.page.locator("#view")
                self.assertIn(title, view.inner_text())
                self.assertEqual(_Browser.page.locator("#view .filterbar").count(), 1)

    def test_tool_routes_keep_the_bottom_tabbar(self):
        for group, tool, _ in self.TOOLS:
            with self.subTest(tool=tool):
                _Browser.goto(f"{group}/{tool}")
                current = _Browser.page.locator('#tabbar [aria-current="page"]')
                self.assertEqual(current.count(), 1)

    def test_action_hub_links_to_every_action_tool(self):
        _Browser.goto("action")
        view = _Browser.page.locator("#view")
        self.assertIn("要做的事", view.inner_text())
        self.assertIn("看市场", view.inner_text())
        self.assertEqual(_Browser.page.locator("#view [data-action='open-tool']").count(), 5)

    def test_unknown_tool_name_does_not_blank_the_page(self):
        """Review Focus 2：/regulations/不存在 必须回落到地图且不白屏。"""
        _Browser.goto("regulations/不存在")
        self.assertIn("法规地图", _Browser.page.locator("#view").inner_text())
```

- [ ] **Step 2: 运行测试确认失败**

```bash
"C:/Users/ymc/Desktop/agent/_recon/probe-venv/Scripts/python.exe" scripts/selftest_web_ui.py RegulationsTests ToolViewTests
```

Expected: FAIL —— 桩视图

- [ ] **Step 3: 写 `web/js/views/regulations.js`**

```js
// 法规中心。照 prototype.html:1573-1597。
import { h } from "../dom.js";
import { ic } from "../icons.js";
import { pageHead, sectionHead, toolCard, row } from "../components.js";

const CURRENT = [
  { id: "toy", title: "玩具安全指令 2009/48/EC", sub: "CE 标识、年龄分级与警告语", status: "有来源 · 请核对适用性", tone: "ok" },
  { id: "en71", title: "EN 71 玩具安全检测", sub: "机械物理、阻燃与迁移元素", status: "有来源 · 请核对报告有效期", tone: "ok" },
  { id: "freshGpsr", title: "GPSR 通用产品安全法规", sub: "2026-12-13 起适用 · 在线销售需指定欧盟责任人", status: "即将生效 · 请核对", tone: "warn" },
];

export default {
  title: "法规中心",
  sub: "查法规、看时间线、找原文",

  render() {
    return h`
      ${pageHead({ title: "法规中心", lead: "查法规、看时间线、找原文。浏览和检索都在这一个页面里。" })}
      <button class="search-entry" data-action="nav" data-to="regulations/search">
        ${ic("search")}
        <span class="search-entry__text">搜法规编号、条款标题或产品要求</span>
        <span class="search-entry__id">2009/48/EC</span>
      </button>
      ${sectionHead({ title: "查询工具", count: "2 项" })}
      <div class="tool-grid">
        ${toolCard({ group: "regulations", id: "map", icon: "map", title: "法规地图", sub: "按品类和市场看适用法规" })}
        ${toolCard({ group: "regulations", id: "timeline", icon: "calendar", title: "变化时间线", sub: "发布、生效与过渡节点" })}
      </div>
      ${sectionHead({ title: "当前市场", count: "儿童玩具 · 德国" })}
      <div class="list">${CURRENT.map(row)}</div>
      <p class="fine">当前市场条目来自已核对目录；点开可核对适用条件和官方原文。</p>
      <p class="fine">法规时效检查结果在首页，每天 09:00 / 21:00 自动更新。</p>`;
  },
};
```

- [ ] **Step 4: 写 `web/js/views/search.js`**

```js
// 条款检索。照 prototype.html:1748-1782，条款常量照 1735-1747。
import { h } from "../dom.js";
import { pageHead, card } from "../components.js";

const CLAUSES = [
  { id: "16 CFR Part 1250", heading: "儿童产品的安全标准", locator: "§ 1250.2", body: "儿童产品应符合适用安全标准。" },
  { id: "2009/48/EC", heading: "Article 4", locator: "Article 4", body: "玩具在投放市场前应满足基本安全要求。" },
];

export default {
  title: "条款检索",
  sub: "按编号精确定位",
  back: true,

  render() {
    return h`
      ${pageHead({ title: "条款检索", lead: "按法规编号精确定位，再按条款标题筛选。" })}
      <div class="field"><label for="q-id">法规编号</label>
        <input id="q-id" value="16 CFR Part 1250" /></div>
      <div class="field"><label for="q-heading">条款标题关键词（可选）</label>
        <input id="q-heading" value="" /></div>
      <button class="btn btn--primary btn--block" data-action="run-search">检索条款</button>
      <div id="search-result">
        ${CLAUSES.map((c) => card(h`
          <b>${c.heading}</b>
          <p class="mono">${c.locator}</p>
          <p>${c.body}</p>`, "card--clause"))}
      </div>`;
  },
};
```

M1 的检索结果用固定示例；M2 接 `/api/search`（`core.law_store.retrieve`）。空命中态用 `emptyState("没有匹配的条款，请核对编号。")`——M2 的契约测试覆盖（见 `test_search_empty_result_uses_the_prototype_empty_state`，Task 11 加入）。

- [ ] **Step 5: 写 `web/js/views/tool.js`**

```js
// 七个工具页。配置照 prototype.html:1103-1148 的 TOOL_PAGES，分发照 1634-1734。
import { h } from "../dom.js";
import { ic } from "../icons.js";
import { emptyState, pageHead, row } from "../components.js";

export const TOOL_PAGES = {
  map:      { icon: "map",      title: "法规地图", sub: "选择一个品类和市场，查看适用法规、状态与官方来源。", filters: ["儿童玩具", "欧盟", "全部状态"] },
  timeline: { icon: "calendar", title: "变化时间线", sub: "区分发布、生效、适用与过渡日期，避免按旧规则准备。", filters: ["儿童玩具", "欧盟", "最近 12 个月"] },
  todo:     { icon: "list",     title: "合规待办", sub: "把法规变成今天能执行的动作，按紧迫度排序。", filters: ["儿童玩具", "欧盟", "按紧迫度"] },
  readiness:{ icon: "flag",     title: "上线准备", sub: "把待办排成小团队能执行的计划，按阶段和责任组织。", filters: ["儿童玩具", "欧盟 + 美国"] },
  journey:  { icon: "layers",   title: "六阶段路线", sub: "从选品到切换复核，看每个阶段的任务、资料和缺口。", filters: ["德国亚马逊", "儿童玩具"] },
  compare:  { icon: "compare",  title: "区域对比", sub: "按官方编号精确匹配，不把名称相似误判为同一法规。", filters: ["儿童玩具", "欧盟 ↔ 美国"] },
  multi:    { icon: "globe",    title: "多市场汇总", sub: "同一品类在不同市场的法规与数据状态，按区域分组。", filters: ["儿童玩具", "欧盟 + 美国"] },
};

const SAMPLE_ROWS = {
  map: [["toy", "玩具安全指令 2009/48/EC", "CE 标识、年龄分级与警告语", "有来源 · 请核对适用性", "ok"]],
  todo: [["doc", "准备 EU 符合性声明（DoC）", "技术文件里的声明与责任主体", "适用条件待确认", "warn"]],
};

const filterbar = (filters) => h`
  <div class="filterbar">
    ${filters.map((label) => h`
      <label class="select"><select aria-label="${label}"><option>${label}</option></select></label>`)}
    <button class="chip" data-action="rerun">${ic("search")}重新生成</button>
  </div>`;

const phaseList = (phases) => card(phases.map(([no, title, sub, count]) => h`
  <button class="phase" data-action="detail" data-id="stage-${no}">
    <span class="phase__no">${no}</span>
    <span class="phase__copy"><b>${title}</b><span>${sub}</span></span>
    <span class="phase__count">${count}</span>${ic("chevron")}
  </button>`).join(""), "card--phases");

const PHASES = {
  journey: [[1, "选品与年龄分级", "确认目标年龄、材料和是否带电", "3 项"],
            [2, "检测与报告", "EN 71 / CPSIA 测试范围", "2 项"],
            [3, "标签与说明书", "德语标签、警告语、CE 标识", "4 项"],
            [4, "文件与责任主体", "DoC、技术文件、欧盟责任人", "3 项"],
            [5, "供应链与平台审核", "工厂资料、亚马逊类目审核", "5 项"],
            [6, "切换与复核", "旧库存、过渡期、年度更新", "2 项"]],
  readiness: [[1, "选品定稿", "年龄分级与材料确认", "2 项"],
              [2, "送检与报告", "确认实验室资质与覆盖范围", "3 项"],
              [3, "文件与标签", "DoC、德语标签、CE 标识", "4 项"]],
};

export default {
  title: "工具",
  sub: "当前筛选会随结果保留",
  back: true,

  render(ctx) {
    const id = ctx.route.tool;
    const page = TOOL_PAGES[id];
    if (!page) return emptyState("这个工具不存在。");
    const rows = SAMPLE_ROWS[id] ?? [];
    return h`
      ${pageHead({ title: page.title, lead: page.sub })}
      ${filterbar(page.filters)}
      ${PHASES[id]
        ? phaseList(PHASES[id])
        : (rows.length ? `<div class="list">${rows.map(row)}</div>`
                       : emptyState("当前条件下没有条目。换个品类或市场再试。"))}
      ${id !== "journey" ? h`
        <button class="btn btn--block" data-action="nav" data-to="assistant">不确定？回助手直接问</button>` : ""}`;
  },
};
```

- [ ] **Step 6: 写 `web/js/views/action.js` 与 `web/js/views/regulations.js` 的标题一致性**

`action.js` 已在 Task 9 实现；本任务先把它从桩替换为只含中心页的最小实现，使 `ToolViewTests.test_action_hub_links_to_every_action_tool` 可通过：

```js
// 行动中心。照 prototype.html:1598-1626。
import { h } from "../dom.js";
import { ic } from "../icons.js";
import { pageHead, sectionHead, toolCard } from "../components.js";

export default {
  title: "行动",
  sub: "任务、计划与市场",

  render() {
    return h`
      ${pageHead({ title: "行动", lead: "把法规变成任务、上线计划和市场对比。要做的事和要看清的市场差异都在这里。" })}
      ${sectionHead({ title: "要做的事", count: "3 项" })}
      <div class="tool-grid">
        ${toolCard({ group: "action", id: "todo", icon: "list", title: "合规待办", sub: "按紧迫度整理下一步" })}
        ${toolCard({ group: "action", id: "readiness", icon: "flag", title: "上线准备", sub: "按阶段和责任排任务" })}
        <button class="tool tool--wide" data-action="open-tool" data-group="action" data-tool="journey">
          <span class="tool__icon">${ic("layers")}</span>
          <span style="flex:1"><b>德国亚马逊六阶段路线</b><br>
            <span>选品 → 测试 → 标签 → 文件 → 供应链 → 切换复核</span></span>
          ${ic("chevron")}
        </button>
      </div>
      ${sectionHead({ title: "看市场", count: "2 项" })}
      <div class="tool-grid">
        ${toolCard({ group: "action", id: "compare", icon: "compare", title: "区域对比", sub: "欧盟和美国逐条对照" })}
        ${toolCard({ group: "action", id: "multi", icon: "globe", title: "多市场汇总", sub: "分区域查看法规" })}
      </div>`;
  },
};
```

- [ ] **Step 7: 运行测试确认通过**

```bash
"C:/Users/ymc/Desktop/agent/_recon/probe-venv/Scripts/python.exe" scripts/selftest_web_ui.py
```

Expected: PASS（RegulationsTests 3 + ToolViewTests 4 全通过，既有类无回归）

- [ ] **Step 8: 提交**

```bash
git add web/js/views/regulations.js web/js/views/search.js web/js/views/tool.js web/js/views/action.js scripts/selftest_web_ui.py
git commit -m "feat(web): regulations hub, clause search and the seven tool pages"
```

---

## Task 8: 结果页、时效性检查页、我的与教程

**Files:**
- Modify: `web/js/views/result.js`、`web/js/views/freshness.js`、`web/js/views/profile.js`、`web/js/views/tutorial.js`（替换桩）
- Test: `scripts/selftest_web_ui.py`（追加测试类）

**Interfaces:**
- Consumes: `pageHead` / `sectionHead` / `card` / `row` / `chip` / `stat` / `rail` / `emptyState`（Task 2）；`creative` 无；`ic`（Task 2）
- Produces: 四个视图模块，各默认导出 `{ title, sub, back?, viewClass?, render(ctx) }`
  - `views/result.js` 额外导出 `resultRows()`，供 M2 接 `/api/route` 时替换数据源

**原型对照**：
- 结果页照 `prototype.html:1449-1492`（`resultView()`）；样式已在 Task 3 搬运（`views.css` 的 `446-526`）
- 时效性检查照 `1494-1564`（`freshnessView()`）与 `1627-1633`（`filteredFresh()`）
- 我的照 `1881-1944`（`profileView()`）；教程照 `1784-1879`（`tutorialView()`）

- [ ] **Step 1: 写失败的测试**

在 `scripts/selftest_web_ui.py` 的 `if __name__ == "__main__":` 块**之前**追加。
追加到文件末尾会让新测试类定义晚于 `unittest.main()`，这些用例会被**静默跳过**——
输出仍显示 PASS，实际一个都没跑。追加后务必确认运行输出里出现了本任务新增的用例名。

```python
class ResultAndFreshnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Browser.start()

    def test_result_page_shows_a_priority_block_and_items(self):
        _Browser.goto("result")
        view = _Browser.page.locator("#view")
        self.assertIn("现在先做", view.inner_text())
        self.assertGreaterEqual(_Browser.page.locator("#view .list .row").count(), 1)

    def test_result_rows_carry_their_evidence_status(self):
        """规格要求每条都带来源状态，不能被读成合规结论。"""
        _Browser.goto("result")
        text = _Browser.page.locator("#view").inner_text()
        self.assertTrue("请核对" in text or "待确认" in text)

    def test_freshness_page_offers_three_filters(self):
        _Browser.goto("freshness")
        self.assertEqual(_Browser.page.locator("#view .filterbar").count(), 1)
        text = _Browser.page.locator("#view").inner_text()
        for label in ["全部", "需处理", "已最新"]:
            with self.subTest(label=label):
                self.assertIn(label, text)

    def test_freshness_marks_unverifiable_platform_rules_as_unconfirmed(self):
        """Review Focus 3：无法确认的条目必须显式说明，而不是留空。"""
        _Browser.goto("freshness")
        self.assertIn("无法确认", _Browser.page.locator("#view").inner_text())


class ProfileAndTutorialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Browser.start()

    def test_profile_lists_the_prototype_menu_rows(self):
        _Browser.goto("profile")
        view = _Browser.page.locator("#view")
        self.assertIn("我的", view.inner_text())
        for label in ["历史结果", "隐私与使用边界", "关于"]:
            with self.subTest(label=label):
                self.assertIn(label, view.inner_text())

    def test_tutorial_has_four_steps(self):
        _Browser.goto("profile/tutorial")
        steps = _Browser.page.locator("#view .step")
        self.assertEqual(steps.count(), 4)
        self.assertIn("说清生意", _Browser.page.locator("#view").inner_text())

    def test_tutorial_range_stays_on_the_profile_tab(self):
        _Browser.goto("profile/tutorial")
        current = _Browser.page.locator('#tabbar [aria-current="page"]')
        self.assertIn("我的", current.inner_text())
```

- [ ] **Step 2: 运行测试确认失败**

```bash
"C:/Users/ymc/Desktop/agent/_recon/probe-venv/Scripts/python.exe" scripts/selftest_web_ui.py ResultAndFreshnessTests ProfileAndTutorialTests
```

Expected: FAIL —— 四个桩视图

- [ ] **Step 3: 写 `web/js/views/result.js`**

```js
// 结果页。照 prototype.html:1449-1492。
import { h } from "../dom.js";
import { pageHead, sectionHead, card, row } from "../components.js";

export const PRIORITIES = [
  ["确认年龄分级与德语警告语", "标签和说明书先定稿，再送检"],
  ["准备 EU 符合性声明 DoC", "确认谁承担制造商责任"],
  ["核对 EN 71 检测报告覆盖范围", "报告需匹配实际材料与工艺"],
];

const ITEMS = [
  { id: "toy", title: "玩具安全指令 2009/48/EC", sub: "CE 标识、年龄分级与警告语", status: "有来源 · 请核对适用性", tone: "ok" },
  { id: "doc", title: "准备 EU 符合性声明（DoC）", sub: "技术文件里的声明与责任主体", status: "适用条件待确认", tone: "warn" },
  { id: "en71", title: "EN 71 玩具安全检测", sub: "机械物理、阻燃与迁移元素", status: "有来源 · 请核对报告有效期", tone: "ok" },
];

export const resultRows = () => ITEMS;

export default {
  title: "查询结果",
  sub: "儿童玩具 · 德国 · 亚马逊",
  back: true,

  render() {
    return h`
      ${pageHead({ title: "德国市场行动清单", lead: "儿童玩具 / 德国 / 亚马逊 · 先看现在先做的三项。" })}
      <section class="priority" aria-labelledby="priority-title">
        ${sectionHead({ title: "现在先做", count: "按前置依赖排序" })}
        <div class="list">
          ${PRIORITIES.map(([title, sub], i) => row({
            id: `priority-${i}`, title, sub, status: "", tone: i === 0 ? "warn" : "ok" }))}
        </div>
      </section>
      ${sectionHead({ title: "法规与依据", count: `${ITEMS.length} 条` })}
      <div class="list">${ITEMS.map(row)}</div>
      <p class="fine">有帮助，有来源，有边界。不构成法律意见；涉及产品责任、合同或争议时，请让专业人员复核。</p>`;
  },
};
```

- [ ] **Step 4: 写 `web/js/views/freshness.js`**

```js
// 时效性检查。照 prototype.html:1494-1564，筛选照 1627-1633。
import { h } from "../dom.js";
import { card, pageHead, rail, sectionHead, stat } from "../components.js";

const ITEMS = [
  { id: "freshGpsr", title: "GPSR 通用产品安全法规", sub: "2026-12-13 起适用 · 在线销售需指定欧盟责任人", status: "即将生效 · 请核对", tone: "warn", type: "关键日期" },
  { id: "freshToy", title: "玩具安全指令 2009/48/EC", sub: "目录内版本 2024-12-01 · 检测报告可能引用旧版", status: "有更新 · 需要核对", tone: "warn", type: "版本更新" },
  { id: "freshEn71", title: "EN 71-1 机械物理性能", sub: "目录引用版本 2014+A1:2018 · 与当前报告一致", status: "已是最新", tone: "ok", type: "已核对" },
  { id: "freshAmazon", title: "Amazon 玩具类目审核", sub: "平台规则无法自动核对 · 需人工查看卖家后台", status: "无法确认", tone: "muted", type: "平台规则" },
];

const FILTERS = ["全部", "需处理", "已最新", "无法确认"];

const matches = (filter, item) => {
  if (filter === "需处理") return item.tone === "warn";
  if (filter === "已最新") return item.tone === "ok";
  if (filter === "无法确认") return item.tone === "muted";
  return true;
};

export default {
  title: "时效性检查",
  sub: "最近检查 2026-10-19 09:00",
  back: true,

  filter: "全部",

  render(ctx) {
    const items = ITEMS.filter((item) => matches(this.filter, item));
    return h`
      ${pageHead({ title: "时效性检查", lead: "核对你正在依赖的法规和标准是否仍是最新，哪些需要处理。" })}
      <div class="filterbar">
        ${FILTERS.map((label) => h`
          <button class="chip ${this.filter === label ? "chip--on" : ""}"
                  data-action="fresh-filter" data-value="${label}">${label}</button>`)}
      </div>
      ${card(h`
        <div class="stat-row">
          ${stat({ value: "86", label: "核验链接" })}
          ${stat({ value: "84", label: "可访问" })}
          ${stat({ value: "2", label: "待复核", tone: "warn" })}
          ${stat({ value: "0", label: "内容更新" })}
        </div>`, "fresh-card")}
      ${sectionHead({ title: "检查结果", count: `${items.length} 条` })}
      <div class="list">
        ${items.length
          ? items.map((item) => h`
              <button class="row" data-action="detail" data-id="${item.id}">
                ${rail(item.tone)}
                <span class="row__copy"><b>${item.title}</b><span>${item.sub}</span></span>
                <span class="row__status">${item.status}</span>
              </button>`)
          : `<p class="fine fine--empty">这个筛选下没有条目。</p>`}
      </div>
      <p class="fine">检查只核对官方链接状态与内容哈希，不等于法规条文变更；条文级变化仍以人工核对为准。</p>`;
  },

  mount(root) {
    root.querySelectorAll("[data-action='fresh-filter']").forEach((button) => {
      button.addEventListener("click", () => {
        this.filter = button.dataset.value;
        root.innerHTML = this.render({});
      });
    });
  },
};
```

`freshness` 的筛选是 **Review Focus 3 的落点**：`无法确认` 这个筛选必须真能筛出 `tone: "muted"` 的条目，且筛选后为空时渲染 `fine--empty` 而不是空 div。

- [ ] **Step 5: 写 `web/js/views/profile.js`**

```js
// 我的。照 prototype.html:1881-1944。
import { h } from "../dom.js";
import { ic } from "../icons.js";
import { pageHead } from "../components.js";

const MENU = [
  { id: "history", icon: "history", title: "历史结果", sub: "保留当时条件的查询记录" },
  { id: "conditions", icon: "list", title: "当前查询条件", sub: "查看并纠正助手的理解" },
  { id: "voice", icon: "mic", title: "语音输入", sub: "说完先确认，再发送" },
  { id: "coverage", icon: "layers", title: "数据覆盖与版本", sub: "目录、核对与截止日期" },
  { id: "privacy", icon: "lock", title: "隐私与使用边界", sub: "数据怎么处理" },
  { id: "about", icon: "help", title: "关于", sub: "版本与边界" },
];

export default {
  title: "我的",
  sub: "教程、隐私与数据状态",

  render() {
    return h`
      ${pageHead({ title: "我的", lead: "教程在下面；这里也放数据边界和版本信息。" })}
      <div class="list">
        ${MENU.map((m) => h`
          <button class="menu-row" data-action="detail" data-id="${m.id}">
            <span class="menu-row__icon">${ic(m.icon)}</span>
            <span class="menu-row__copy"><b>${m.title}</b><span>${m.sub}</span></span>
            ${ic("chevron")}
          </button>`)}
        <button class="menu-row" data-action="nav" data-to="profile/tutorial">
          <span class="menu-row__icon">${ic("help")}</span>
          <span class="menu-row__copy"><b>新手教程</b><span>四步用好这个助手</span></span>
          ${ic("chevron")}
        </button>
      </div>`;
  },
};
```

- [ ] **Step 6: 写 `web/js/views/tutorial.js`**

```js
// 教程。照 prototype.html:1784-1879 的四步结构。
import { h } from "../dom.js";
import { pageHead } from "../components.js";

const STEPS = [
  ["说清生意", "一句自然语言就够：毛绒玩具卖到德国亚马逊。不用先选菜单。"],
  ["回答追问", "助手一次只问一个条件，比如是否带电、FBA 还是自发货。"],
  ["看行动与依据", "先看现在先做的三项；点条目核对适用条件和官方原文。"],
  ["查正文、导出、存档", "在法规中心里按编号查条款；结果可以导出，也可以回看历史。"],
];

export default {
  title: "新手教程",
  sub: "四步用好这个助手",
  back: true,

  render() {
    return h`
      ${pageHead({ title: "四步用好这个助手", lead: "从说清生意到查条文，每一步都能核对来源。" })}
      <div class="steps">
        ${STEPS.map(([title, sub], i) => h`
          <div class="step">
            <span class="step__no">${i + 1}</span>
            <span><b>${title}</b><span>${sub}</span></span>
          </div>`)}
      </div>`;
  },
};
```

- [ ] **Step 7: 运行测试确认通过**

```bash
"C:/Users/ymc/Desktop/agent/_recon/probe-venv/Scripts/python.exe" scripts/selftest_web_ui.py
```

Expected: PASS（ResultAndFreshnessTests 4 + ProfileAndTutorialTests 3 全通过，既有类无回归）

- [ ] **Step 8: 提交**

```bash
git add web/js/views/result.js web/js/views/freshness.js web/js/views/profile.js web/js/views/tutorial.js scripts/selftest_web_ui.py
git commit -m "feat(web): result, freshness, profile and tutorial views"
```

---

## Task 9: 七个底部抽屉

**Files:**
- Create: `web/js/views/detail.js`
- Modify: `web/js/main.js`（导入并注册详情渲染器）
- Test: `scripts/selftest_web_ui.py`（追加测试类）

**Interfaces:**
- Consumes: `registerDetail`（Task 3 的 `ui/detail.js`）、`openSheet`（Task 4）、`esc`/`h`（Task 2）
- Produces: `web/js/views/detail.js` → `export const detailHtml = (id) => string`，覆盖 `conditions` / `history` / `voice` / `coverage` / `privacy` / `about` / `help` 七个 id，以及任意条目 id 的兜底

**原型对照**：条目详情照 `prototype.html:2154-2186`（`detailSheet()`）；其余六个照 `2187-2321`（`PROFILE_SHEETS`）。文案逐字照抄。

- [ ] **Step 1: 写失败的测试**

在 `scripts/selftest_web_ui.py` 的 `if __name__ == "__main__":` 块**之前**追加。
追加到文件末尾会让新测试类定义晚于 `unittest.main()`，这些用例会被**静默跳过**——
输出仍显示 PASS，实际一个都没跑。追加后务必确认运行输出里出现了本任务新增的用例名。

```python
class DetailSheetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Browser.start()

    SHEETS = [("conditions", "助手目前的理解"), ("history", "历史结果"),
              ("voice", "说完先确认，再发送"), ("coverage", "目录、核对与截止日期"),
              ("privacy", "数据怎么处理"), ("about", "出海合规雷达"),
              ("help", "四步用好这个助手")]

    def _open(self, node_id):
        _Browser.goto("profile")
        _Browser.page.evaluate(
            "async () => { const s = await import('/web/js/ui/sheet.js'); s.closeSheet(); }")
        _Browser.page.evaluate(
            "async () => { const d = await import('/web/js/views/detail.js');"
            "const s = await import('/web/js/ui/sheet.js'); s.openSheet(d.detailHtml(%r)); }" % node_id)
        _Browser.page.wait_for_timeout(250)

    def test_every_profile_sheet_has_its_own_content(self):
        for node_id, expected in self.SHEETS:
            with self.subTest(node_id=node_id):
                self._open(node_id)
                self.assertIn(expected, _Browser.page.locator("#sheet").inner_text())

    def test_every_sheet_has_a_grab_handle_and_a_close_button(self):
        for node_id, _ in self.SHEETS:
            with self.subTest(node_id=node_id):
                self._open(node_id)
                sheet = _Browser.page.locator("#sheet")
                self.assertEqual(sheet.locator(".sheet__grab").count(), 1)
                self.assertEqual(sheet.locator("[data-action='close-sheet']").count(), 1)

    def test_unknown_id_gets_a_readable_fallback(self):
        """Review Focus 2：未知条目 id 不得白屏或抛异常。"""
        self._open("完全不存在的条目")
        self.assertTrue(_Browser.page.locator("#sheet").inner_text().strip())

    def test_sheet_content_escapes_user_derived_values(self):
        self._open("<img src=x onerror=alert(1)>")
        self.assertEqual(_Browser.page.locator("#sheet").locator("img").count(), 0)
```

- [ ] **Step 2: 运行测试确认失败**

```bash
"C:/Users/ymc/Desktop/agent/_recon/probe-venv/Scripts/python.exe" scripts/selftest_web_ui.py DetailSheetTests
```

Expected: FAIL —— `views/detail.js` 不存在

- [ ] **Step 3: 写 `web/js/views/detail.js`**

```js
// 七个底部抽屉。文案逐字照 prototype.html:2187-2321 的 PROFILE_SHEETS。
import { esc, h } from "../dom.js";
import { ic } from "../icons.js";

const head = (label) => h`
  <div class="sheet__grab"></div>
  <div class="sheet__body">
    <div class="sheet__top">
      <span class="sheet__lead">${label}</span>
      <button class="sheet__close" data-action="close-sheet" aria-label="关闭">${ic("close")}</button>
    </div>`;

const SHEETS = {
  conditions: () => head("当前查询条件") + h`
      <h2>助手目前的理解</h2>
      <div class="context"><span>儿童玩具</span><span>德国</span><span>欧盟</span><span>亚马逊</span><span>FBA</span><span>不带电</span></div>
      <div class="sheet__section"><h3>只改需要改变的条件</h3>
        <p>可以直接在对话里说「市场改成美国」或「不是 FBA」，助手会保留其他条件并更新结果。</p></div>
      <div class="sheet__actions">
        <button class="btn btn--primary btn--block" data-action="nav" data-to="assistant">回对话修改</button>
      </div></div>`,

  history: () => head("历史结果") + h`
      <h2>保留当时条件的 3 份结果</h2>
      <div class="list">
        <button class="history-item" data-action="detail" data-id="h0"><span class="menu-row__icon">${ic("doc")}</span><span class="history-item__copy"><b>德国市场行动清单</b><span>今天 14:32 · 儿童玩具 / 德国 / 亚马逊</span></span>${ic("chevron")}</button>
        <button class="history-item" data-action="detail" data-id="h1"><span class="menu-row__icon">${ic("doc")}</span><span class="history-item__copy"><b>欧盟玩具法规清单</b><span>今天 11:08 · 儿童玩具 / 欧盟</span></span>${ic("chevron")}</button>
        <button class="history-item" data-action="detail" data-id="h2"><span class="menu-row__icon">${ic("doc")}</span><span class="history-item__copy"><b>欧美玩具目录对比</b><span>昨天 18:45 · 儿童玩具</span></span>${ic("chevron")}</button>
      </div>
      <p class="fine">历史结果会校验当时条件；条件变化后需要重新查询。</p></div>`,

  voice: () => head("语音输入") + h`
      <h2>说完先确认，再发送</h2>
      <p class="sheet__lead">识别结果会先进输入框做预编辑。确认产品名称、国家和数字无误后，再点发送。</p>
      <div class="sheet__status">${ic("check")}本地语音引擎已启用 · 最长 60 秒</div>
      <div class="sheet__section"><h3>使用边界</h3>
        <p>录音由界面临时存储，应用不另存音频。云端转写会把录音发送到语音服务；请勿输入客户敏感资料。</p></div></div>`,

  coverage: () => head("数据覆盖与版本") + h`
      <h2>目录、核对与截止日期</h2>
      <div class="stat-row">
        <div class="stat"><b>86</b><span>部法规</span></div>
        <div class="stat"><b>5</b><span>类商品</span></div>
        <div class="stat"><b>28</b><span>条逐条核对</span></div>
        <div class="stat"><b>58</b><span>条负责人声明确认</span></div>
      </div>
      <div class="sheet__section"><h3>数据快照</h3>
        <p>截止 2026-10-19。目录标记、机器读取与用户自述均不等于商品已合规；请逐条查看适用条件与证据状态。</p></div></div>`,

  privacy: () => head("隐私与使用边界") + h`
      <h2>数据怎么处理</h2>
      <div class="sheet__section"><h3>会话</h3>
        <p>业务状态默认保存在服务内存，不写入原始对话日志。导出使用临时文件。</p></div>
      <div class="sheet__section"><h3>模型</h3>
        <p>模型只用于理解输入。结论来自已核对语料和确定性规则；输入文字可能发送给模型服务。</p></div>
      <div class="sheet__section"><h3>语音</h3>
        <p>录音由界面临时存储；云端转写会发送录音。请勿输入客户敏感资料。</p></div></div>`,

  about: () => head("关于") + h`
      <h2>出海合规雷达</h2>
      <p class="sheet__lead">从问题到下一步。先理解你的生意，再从已核对语料里给出法规、日期和行动。</p>
      <div class="sheet__section"><h3>版本</h3><p class="mono">2026.10.19-chat1.6 · 原型 v2</p></div>
      <div class="sheet__section"><h3>边界</h3>
        <p>有帮助，有来源，有边界。不构成法律意见；涉及产品责任、合同或争议时，请让专业人员复核。</p></div></div>`,

  help: () => head("怎么用") + h`
      <h2>四步用好这个助手</h2>
      <div class="steps">
        ${[["说清生意", "一句自然语言就够：毛绒玩具卖到德国亚马逊。不用先选菜单。"],
           ["回答追问", "助手一次只问一个条件，比如是否带电、FBA 还是自发货。"],
           ["看行动与依据", "先看现在先做的三项；点条目核对适用条件和官方原文。"],
           ["查正文、导出、存档", "在法规中心里按编号查条款；结果可以导出，也可以回看历史。"]]
          .map(([t, s], i) => h`
            <div class="step"><span class="step__no">${i + 1}</span>
              <span><b>${t}</b><span>${s}</span></span></div>`)}
      </div></div>`,
};

/** 兜底：条目详情与未知 id 都走这里，保证任何 id 都有可读内容。 */
const fallback = (id) => head("详情") + h`
      <h2>${id}</h2>
      <p class="sheet__lead">这一条来自当前目录；M2 接入后显示适用条件、原文摘录与官方来源链接。</p></div>`;

export const detailHtml = (id) => (SHEETS[id] ? SHEETS[id]() : fallback(String(id ?? "")));
```

- [ ] **Step 4: 在 `main.js` 注册详情渲染器**

把 `web/js/main.js` 里现有的

```js
import { detailSheet } from "./ui/detail.js";
```

改为

```js
import { detailSheet, registerDetail } from "./ui/detail.js";
```

并在其上方新增一行

```js
import { detailHtml } from "./views/detail.js";
```

并在 `start(render);` 之前加：

```js
registerDetail(detailHtml);
```

- [ ] **Step 5: 运行测试确认通过**

```bash
"C:/Users/ymc/Desktop/agent/_recon/probe-venv/Scripts/python.exe" scripts/selftest_web_ui.py
```

Expected: PASS（DetailSheetTests 4 全通过，既有类无回归）

- [ ] **Step 6: 提交**

```bash
git add web/js/views/detail.js web/js/main.js scripts/selftest_web_ui.py
git commit -m "feat(web): the seven bottom sheets"
```

---

## Task 10: 响应式——桌面端去掉手机壳

**Files:**
- Modify: `web/styles/shell.css`（覆盖 Task 3 搬运来的 `.app-shell` 桌面规则）
- Test: `scripts/selftest_web_ui.py`（追加测试类）

**Interfaces:**
- Consumes: Task 3 搬运的 `shell.css`（含原型 `71-91` 的 `.app-shell` 与 `@media (min-width: 700px)`）
- Produces: 无导出；行为约束——≥700px 时无手机壳装饰，窄栏仍居中且为手机比例

**规格第 7 节**：桌面端去掉边框、圆角、阴影、桌面底纹；内容窄栏居中 `max-width: 480px`；标签栏保持底部。

原型在 `@media (min-width: 700px)` 里给 `body` 加了 `display:grid; place-items:center; padding:24px`，给 `.app-shell` 加了 `height: min(900px, calc(100dvh - 48px))`、`border`、`border-radius:30px`、`box-shadow`。本任务把这段改为"去壳"版本。

- [ ] **Step 1: 写失败的测试**

在 `scripts/selftest_web_ui.py` 的 `if __name__ == "__main__":` 块**之前**追加。
追加到文件末尾会让新测试类定义晚于 `unittest.main()`，这些用例会被**静默跳过**——
输出仍显示 PASS，实际一个都没跑。追加后务必确认运行输出里出现了本任务新增的用例名。

```python
class ResponsiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Browser.start()

    def _style(self, width, prop):
        _Browser.page.set_viewport_size({"width": width, "height": 900})
        _Browser.page.goto(f"{BASE}#/home", wait_until="load")
        _Browser.page.wait_for_timeout(350)
        return _Browser.page.evaluate(
            "() => { const el = document.querySelector('.app-shell'); const cs = getComputedStyle(el);"
            "return { prop: cs.getPropertyValue(%r), rect: el.getBoundingClientRect().toJSON() };"
            % prop)

    def test_wide_viewport_has_no_phone_shell_decoration(self):
        """规格第 7 节：桌面端去壳。"""
        for prop in ["border-top-width", "box-shadow"]:
            with self.subTest(prop=prop):
                got = self._style(1440, prop)
                self.assertIn(got["prop"], ["0px", "none"],
                              f"桌面端不应保留手机壳装饰：{prop}={got['prop']}")

    def test_wide_viewport_keeps_the_phone_proportions_and_centering(self):
        got = self._style(1440, "width")
        rect = got["rect"]
        self.assertLessEqual(rect["width"], 481, "桌面端内容栏不得超过 480px")
        centre = rect["x"] + rect["width"] / 2
        self.assertAlmostEqual(centre, 720, delta=2, msg="内容栏必须居中")

    def test_narrow_viewport_keeps_the_phone_shell(self):
        """移动端严格照原型：满宽、满高。"""
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
                self.assertLessEqual(abs(box["bottom"] - box["vh"]), 2,
                                     "标签栏必须贴在视口底部")
                self.assertGreater(box["w"], 300, "标签栏不得塌陷")
```

- [ ] **Step 2: 运行测试确认失败**

```bash
"C:/Users/ymc/Desktop/agent/_recon/probe-venv/Scripts/python.exe" scripts/selftest_web_ui.py ResponsiveTests
```

Expected: FAIL —— `test_wide_viewport_has_no_phone_shell_decoration`（搬来的原型规则仍带边框、圆角、阴影）

- [ ] **Step 3: 在 `web/styles/shell.css` 追加去壳覆盖**

追加到 `web/styles/shell.css` **末尾**（覆盖原型 `71-91` 的桌面规则；原型原文保留在文件中不动，便于日后对照）：

```css
/* ============================================================
   桌面端去壳（规格第 7 节）
   原型在 ≥700px 渲染居中手机壳；本项目改为保留手机比例与排布，
   但去掉边框、圆角、阴影与桌面底纹。
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
"C:/Users/ymc/Desktop/agent/_recon/probe-venv/Scripts/python.exe" scripts/selftest_web_ui.py ResponsiveTests
```

Expected: PASS（4 个用例）

- [ ] **Step 5: 全量回归并提交**

```bash
"C:/Users/ymc/Desktop/agent/_recon/probe-venv/Scripts/python.exe" scripts/selftest_web_ui.py
git add web/styles/shell.css scripts/selftest_web_ui.py
git commit -m "style(web): drop the phone shell on wide viewports, keep phone proportions"
```

---

## Task 11: 像素验收、可访问性验收与门禁接入

**Files:**
- Create: `scripts/check_web_browser.py`
- Create: `scripts/compare_web_screenshots.py`
- Modify: `scripts/selftest_all.py`（把 `selftest_web_api.py` 加入门禁）
- Test: 本身即为验收工具

**Interfaces:**
- Consumes: 全部前序任务的产物；`docs/ui-preview/prototype-v2.html`（Task 1 入库的基准）
- Produces:
  - `scripts/check_web_browser.py --url URL [--out DIR]` → 逐路由截图 + `web-report.json`
  - `scripts/compare_web_screenshots.py --prototype DIR --rebuilt DIR [--out FILE]` → 像素比对报告；调 `rea compare-web-screenshots`

**为什么要两个脚本**：截图必须由 Playwright 在**固定视口**下采集（REA 抓的是真实窗口可视区，尺寸受窗口边框影响，拆解时实测为 496×751 而非 390×844）；比对则由 REA 独立完成。这是"确定性采集 + 独立比对"的分工。

- [ ] **Step 1: 写 `scripts/check_web_browser.py`**

```python
"""逐路由截图与结构检查；需要 Playwright。沿用 scripts/check_chat_browser.py 的范式。

用法：
  python app.py &                              # 或 PORT=7899 python app.py
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
                  activeTab: document.querySelector('#tabbar [aria-current="page"]')?.innerText.trim() || null,
                  accentRoles: [...document.querySelectorAll('#view [role]')].map(n => n.getAttribute('role')).slice(0, 40),
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

原型是静态文件，用同一个脚本采一份基准（视口与参数完全一致，保证可比）：

```bash
python -m http.server 8899 --bind 127.0.0.1 --directory docs/ui-preview &
sleep 2
"C:/Users/ymc/Desktop/agent/_recon/probe-venv/Scripts/python.exe" scripts/check_web_browser.py \
  --url http://127.0.0.1:8899/prototype-v2.html \
  --out docs/ui-preview/prototype-baseline
kill %1
```

Expected: `routes=32 failures=...`（原型的 7 个工具页里有的没有 `.filterbar`，失败条目不致命——基准图的用途只是像素比对，不是门禁）

- [ ] **Step 3: 写 `scripts/compare_web_screenshots.py`**

```python
"""原型 vs 改造后的像素比对；由 REA 独立完成比对，不在本脚本内实现像素算法。

用法：
  python scripts/compare_web_screenshots.py \
    --prototype docs/ui-preview/prototype-baseline/shots \
    --rebuilt   docs/ui-preview/rebuilt/shots
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def rea_available():
    return shutil.which("rea") is not None


def snapshot(path):
    """把一张 PNG 交给 REA 的截图产物格式：{sha256, bytes, media_type, data_base64}。"""
    import base64
    import hashlib
    data = path.read_bytes()
    return {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
            "media_type": "image/png", "data_base64": base64.b64encode(data).decode()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prototype", required=True)
    parser.add_argument("--rebuilt", required=True)
    parser.add_argument("--out", default=None)
    parser.add_argument("--threshold", type=float, default=0.02,
                        help="允许的差异像素占比")
    args = parser.parse_args()

    if not rea_available():
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
            result = json.loads(proc.stdout)
            norm = result.get("normalized_result", result)
            entry = {"name": name,
                     "status": norm.get("status"),                    # "identical" | "different"
                     "changed_ratio": norm.get("changed_ratio"),      # 0.0 ~ 1.0
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

`rea compare-web-screenshots` 的契约已实测确认（不要自己实现像素算法）：

- 位置参数：`<beforeJson> <afterJson>`，两者都是截图产物 JSON **文件路径**
- 截图产物 JSON 形状：`{"sha256", "bytes", "media_type": "image/png", "data_base64"}`
- 输出（`normalized_result`）：`status`（`"identical"` / `"different"`）、`changed_ratio`（0.0~1.0）、`changed_pixels`、`compared_pixels`、`maximum_channel_delta`、`mean_absolute_channel_delta`
- 只接受**非交错 8-bit RGB/RGBA PNG**；比对不含 OCR、不做语义布局分析、不做感知色彩校正

实测对照：两张不同页面的 `changed_ratio` 为 `0.4727`，同一张图为 `0.0` 且 `status: "identical"`。

- [ ] **Step 4: 运行像素比对**

```bash
"C:/Users/ymc/Desktop/agent/_recon/probe-venv/Scripts/python.exe" scripts/compare_web_screenshots.py \
  --prototype docs/ui-preview/prototype-baseline/shots \
  --rebuilt docs/ui-preview/rebuilt/shots \
  --out docs/ui-preview/web-pixel-diff.json
```

Expected: 输出每题差异占比；M1 的目标是**移动端（`@mobile`）同路由差异显著低于桌面端**——桌面端按规格第 7 节刻意去壳，与原型必然不同，属**预期差异**。

在 `web-pixel-diff.json` 旁边写一份 `docs/ui-preview/web-pixel-diff.md`，逐条说明哪些差异是规格允许的（桌面去壳）、哪些是待修的。

- [ ] **Step 5: 把 API 门禁加入离线总闸**

在 `scripts/selftest_all.py` 的 `SCRIPTS` 列表末尾追加（保持与既有条目同样的注释风格）：

```python
    # SPA 静态托管与 /api/* 契约：Gradio 的根路由被接管后必须仍然可用。
    "scripts/selftest_web_api.py",
```

- [ ] **Step 6: 跑完整门禁**

```bash
"C:/Users/ymc/Desktop/agent/_recon/probe-venv/Scripts/python.exe" scripts/selftest_all.py 2>&1 | tail -8
```

Expected: 与 Task 1 记录的同一条既有失败（`selftest_recall_flow.py`，`runtime-assets/law-store.bundle` 缺失）之外**不得新增失败**。新条目 `selftest_web_api.py` 必须通过。

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

## M2 预告（不在本计划范围）

把 M1 的示例数据逐路由替换为 `/api/*`（规格第 5 节），并补 `/api/search` 空命中、`/api/route` 的 `ok:false` 分支契约测试。