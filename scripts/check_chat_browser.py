"""Real browser acceptance checks; requires Playwright only for development.

Start app.py first, then run python scripts/check_chat_browser.py --url URL.
Screenshots and a report are written to docs/ui-preview. No model calls are
enabled by these scenarios, and no production data or external account is used.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent


class ModelScopeEmbeddedPage:
    """Supply only a parent frame; load the deployed app without alteration."""

    def __init__(self, page):
        self.outer = page
        self.frame = None

    def goto(self, url, **kwargs):
        from html import escape
        self.outer.route("**/__cr_acceptance_harness__", lambda route: route.fulfill(
            content_type="text/html",
            body='<html><body style="margin:0"><iframe name="cr-app" style="border:0;width:100vw;height:100vh" src="'
            + escape(url, quote=True) + '"></iframe></body></html>'))
        response = self.outer.goto("https://www.modelscope.cn/__cr_acceptance_harness__", **kwargs)
        self._attach()
        return response

    def _attach(self):
        self.outer.frame_locator('iframe[name="cr-app"]').locator("#cr-input textarea").wait_for(timeout=60000)
        self.frame = self.outer.frame(name="cr-app")

    def reload(self, **kwargs):
        response = self.outer.reload(**kwargs)
        self._attach()
        return response

    def __getattr__(self, name):
        if name in ("locator", "get_by_role", "get_by_text", "get_by_label", "evaluate", "wait_for_function"):
            return getattr(self.frame, name)
        return getattr(self.outer, name)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:7861")
    parser.add_argument("--output", type=Path, help="Separate output directory for an online acceptance run")
    parser.add_argument("--auth-from-git", action="store_true", help="Read ModelScope credentials from Git's credential manager")
    parser.add_argument("--modelscope-embed", action="store_true", help="Embed the real runtime under the required ModelScope parent origin; does not validate the public portal")
    parser.add_argument("--direct-network", action="store_true", help="Use a direct test-browser connection without changing system proxy settings")
    args = parser.parse_args()
    response_timeout = 90000 if args.modelscope_embed else 25000
    output = args.output or ROOT / "docs" / "ui-preview"
    output.mkdir(parents=True, exist_ok=True)
    checks = []
    token = None
    report = {"url": args.url, "browser": "Playwright Chromium", "checks": checks,
              "authenticated_runtime": args.auth_from_git,
              "modelscope_parent_harness": args.modelscope_embed,
              "network": "direct HTTP/1.1" if args.direct_network else "system browser network",
              "completed": False,
              "skipped": (["storage failure injection", "initialization failure injection"] if args.modelscope_embed else []),
              "note": "线上不注入平台 SDK 启动故障；故障注入保留在本地完整检查。语音准确率另行验收。"}
    (output / "browser-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    target = urlsplit(args.url)
    if args.modelscope_embed and (target.scheme != "https" or not re.fullmatch(r"(?:studio-[a-z0-9-]+\.api-inference\.modelscope\.net|[a-z0-9-]+\.ms\.show)", target.netloc)):
        parser.error("Embedded acceptance is restricted to ModelScope Studio runtime hosts")
    if args.auth_from_git:
        if target.scheme != "https" or not re.fullmatch(r"studio-[a-z0-9-]+\.api-inference\.modelscope\.net", target.netloc):
            parser.error("Credential authentication is restricted to ModelScope Studio API runtime hosts")
        credential = subprocess.run(["git", "credential", "fill"], cwd=ROOT,
                                    input="protocol=https\nhost=www.modelscope.cn\n\n",
                                    capture_output=True, text=True, timeout=25,
                                    env=dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="Never"))
        fields = dict(line.split("=", 1) for line in credential.stdout.splitlines() if "=" in line)
        token = fields.get("password")
        if not token:
            parser.error("No stored ModelScope credential is available")

    def record(name, condition):
        checks.append({"scenario": name, "passed": bool(condition)})
        (output / "browser-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        if not condition:
            page.screenshot(path=str(output / "failure.png"), full_page=True)
            raise AssertionError(name)
        print("PASS", name, flush=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--no-proxy-server", "--disable-http2", "--disable-quic"] if args.direct_network else [])
        def new_page(context):
            page = context.new_page()
            return ModelScopeEmbeddedPage(page) if args.modelscope_embed else page
        def make_context(**kwargs):
            context = browser.new_context(**kwargs)
            if token:
                def authenticate(route):
                    if urlsplit(route.request.url).netloc == target.netloc:
                        route.continue_(headers={**route.request.headers, "Authorization": "Bearer " + token})
                    else:
                        route.continue_()
                context.route("**/*", authenticate)
            return context

        context = make_context(viewport={"width": 1440, "height": 1080})
        page = new_page(context)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(args.url, wait_until="domcontentloaded")
        page.locator("#cr-input textarea").wait_for()
        page.wait_for_function("window.__crChatInitialized === true")
        record("component ready script actually initializes", page.evaluate("window.__crChatInitialized === true"))
        record("first visit plays the radar intro", page.locator(".cr-intro.cr-play").is_visible())
        page.wait_for_timeout(2100)
        record("empty composer and no unsolicited result", page.locator("#cr-input textarea").input_value() == "" and page.locator(".cr-result-header").count() == 0)
        record("animation completes without blocking input", not page.locator(".cr-intro").is_visible())
        record("desktop no horizontal overflow", page.evaluate("document.documentElement.scrollWidth <= innerWidth"))
        page.screenshot(path=str(output / "01-desktop.png"), full_page=True)
        page.locator('[data-cr-panel="cr-discover"]').click()
        record("all seven functions discoverable", all(page.get_by_role("button", name=title).count() for title in
               ("相关法规", "合规待办", "变化与关键日期", "两个市场对比", "多个市场汇总", "上线准备计划", "回答方法与来源对照")))
        page.screenshot(path=str(output / "02-capabilities.png"), full_page=True)
        page.locator('[data-cr-panel="cr-discover"]').click()

        def ask(text, title):
            before = page.locator(".cr-result-header").get_attribute("data-result-id") if page.locator(".cr-result-header").count() else ""
            page.locator("#cr-input textarea").fill(text)
            page.locator("#cr-send").click()
            try:
                page.wait_for_function("before => {const h=document.querySelector('.cr-result-header'); return h && h.dataset.resultId !== before}", arg=before, timeout=response_timeout)
                page.locator(".cr-result-header h2").filter(has_text=title).wait_for(timeout=response_timeout)
            except Exception as error:
                checks.append({"scenario": "query completes: " + title, "passed": False,
                               "error_type": type(error).__name__})
                (output / "browser-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                page.screenshot(path=str(output / "failure.png"), full_page=True)
                print(page.locator("body").inner_text()[-6500:], flush=True)
                raise
            page.wait_for_timeout(600)

        ask("我想把毛绒玩具卖到德国亚马逊，请查看全流程", "从选品到售后")
        record("new answer scrolls into reading position", page.locator(".cr-result-header").bounding_box()["y"] >= -2 and page.locator(".cr-result-header").bounding_box()["y"] < 200)
        record("main route exposes all six stages", page.locator(".cr-stage").count() == 6)
        record("main route offers current priority tasks", page.get_by_text("现在先核对这几项", exact=False).count() > 0)
        for label, next_label in (("3岁以上", "不带电"), ("不带电", "亚马逊配送 FBA")):
            page.get_by_role("button", name=label, exact=True).click()
            page.get_by_role("button", name=next_label, exact=True).wait_for(timeout=response_timeout)
        page.get_by_role("button", name="亚马逊配送 FBA", exact=True).click()
        page.get_by_role("button", name="亚马逊配送 FBA", exact=True).wait_for(state="detached", timeout=response_timeout)
        record("one question at a time updates known conditions", page.get_by_text("补充一个条件", exact=False).count() == 0 and page.locator(".cr-stage").count() == 6)
        page.locator(".cr-stage > button").first.click()
        task = page.locator(".cr-stage").first.locator(".cr-item > button").first
        task.click()
        done = page.get_by_role("button", name="我已准备此项（仅记录自述）", exact=True).first
        done.wait_for()
        record("stage task expands real details", page.get_by_text("适用条件", exact=False).count() > 0)
        done.click()
        page.get_by_role("button", name="撤回自述完成", exact=True).first.wait_for()
        record("self report changes task status", page.get_by_text("用户自述已完成", exact=False).count() > 0)
        page.screenshot(path=str(output / "03-stages-expanded.png"), full_page=True)

        ask("先看合规待办", "我现在需要做什么")
        task = page.locator(".cr-task > button").first
        task.click()
        page.get_by_role("button", name="依据与官方原文", exact=False).first.wait_for()
        record("task card exposes evidence control", page.get_by_role("button", name="依据与官方原文", exact=False).count() > 0)
        page.get_by_role("button", name="依据与官方原文", exact=False).first.click()
        record("official source has a real external URL", page.locator(".cr-item a[href^='https://']").count() > 0)
        page.screenshot(path=str(output / "04-task-evidence.png"), full_page=True)
        page.locator('[data-cr-panel="cr-export-panel"]').click()
        page.get_by_role("button", name="生成当前结果的导出文件", exact=True).click()
        download = page.get_by_role("button", name="下载这份结果", exact=True)
        download.wait_for()
        with page.expect_download() as event:
            download.click()
        file = event.value
        file.save_as(str(output / "acceptance-todo.csv"))
        record("actual CSV download succeeds", file.suggested_filename.endswith(".csv") and (output / "acceptance-todo.csv").stat().st_size > 30)
        todo_id = page.locator(".cr-result-header").get_attribute("data-result-id")
        page.locator("#cr-input textarea").fill("导出当前待办")
        page.locator("#cr-send").click()
        # The generated file has identical bytes, so Gradio may reuse its hash
        # URL. Wait for this submission's textbox update, not the old notice.
        page.wait_for_function("document.querySelector('#cr-input textarea').value === ''", timeout=25000)
        page.locator('[data-cr-panel="cr-export-panel"]').click()
        record("natural export preserves current result and creates download", page.locator(".cr-result-header").get_attribute("data-result-id") == todo_id and download.is_visible())

        ask("比较欧盟和美国的法规目录", "比较两个市场")
        page.locator(".cr-comparison").wait_for()
        record("comparison is a real table", page.locator(".cr-comparison table").count() > 0)
        choice = page.get_by_label("选择一条法规，查看这行的官方来源")
        choice.fill("Regulation (EU) 2025/2509")
        choice.press("Enter")
        page.get_by_text("目录记录，适用性待核验", exact=False).wait_for()
        record("comparison row detail has source", page.get_by_text("目录记录，适用性待核验", exact=False).count() > 0)
        page.screenshot(path=str(output / "05-comparison.png"), full_page=True)
        ask("查看变化时间线", "查看变化与关键日期")
        record("timeline uses actual date nodes", page.locator(".cr-timeline-label").count() > 0)
        page.locator(".cr-item > button").first.click()
        page.screenshot(path=str(output / "06-timeline.png"), full_page=True)
        ask("多个市场汇总", "一起查看多个市场")
        page.get_by_role("button", name="欧盟 · 点击查看逐条法规与来源", exact=False).click()
        record("multi region has reachable individual sources", page.locator(".cr-item .cr-item").count() > 0)
        ask("整理上线准备计划", "整理上线准备计划")
        record("readiness has interactive phase panels", page.locator(".cr-stage").count() > 0)
        page.locator(".cr-stage > button").first.click()
        record("readiness phase includes actual task cards", page.locator(".cr-stage .cr-item").count() > 0)
        ask("查看模型对照", "查看回答方法与来源差异")
        record("model view shows real replay or explicit empty state",
               page.get_by_text("真实回放", exact=False).count() > 0
               or page.get_by_text("尚无可展示的真实回放记录", exact=False).count() > 0)
        page.locator('[data-cr-panel="cr-history"]').click()
        history = page.get_by_label("历史结果", exact=True)
        history.fill("我现在需要做什么")
        history.press("Enter")
        page.get_by_role("button", name="打开选中的结果", exact=True).click()
        page.wait_for_function("id => document.querySelector('.cr-result-header')?.dataset.resultId === id", arg=todo_id, timeout=25000)
        record("history opens the saved result", page.locator(".cr-result-header h2").inner_text() == "我现在需要做什么")

        page.locator('[data-cr-panel="cr-coverage"]').click()
        page.get_by_label("按法规编号检索条款", exact=True).fill("32009L0048")
        page.get_by_role("button", name="检索已有条款", exact=True).click()
        page.locator("#cr-clause-result").get_by_text("查看官方原文", exact=False).first.wait_for(timeout=response_timeout)
        record("desktop database returns clauses with official provenance", page.locator("#cr-clause-result a[href*='eur-lex.europa.eu']").count() > 0 and "EU:32009L0048" in page.locator("#cr-clause-result").inner_text())
        page.screenshot(path=str(output / "09-clause-retrieval.png"), full_page=True)
        page.locator('[data-cr-panel="cr-coverage"]').click()

        page.locator("#cr-reset").click()
        page.locator("#cr-input textarea").wait_for()
        page.locator(".cr-result-header").wait_for(state="detached", timeout=25000)
        record("new chat clears visible result without replaying intro", page.locator(".cr-result-header").count() == 0 and not page.locator(".cr-intro").is_visible())
        page.reload(wait_until="domcontentloaded")
        page.locator("#cr-input textarea").wait_for()
        page.wait_for_function("window.__crChatInitialized === true")
        record("same browser session remembers intro", page.evaluate("sessionStorage.getItem('compliance-radar-intro-v1') === 'played'") and not page.locator(".cr-intro").is_visible())
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(300)
        record("mobile no horizontal overflow", page.evaluate("document.documentElement.scrollWidth <= innerWidth"))
        page.screenshot(path=str(output / "07-mobile.png"), full_page=True)
        ask("儿童玩具卖到欧盟，相关法规", "查看相关法规")
        page.locator(".cr-item > button").first.click()
        record("mobile expanded result no horizontal overflow", page.evaluate("document.documentElement.scrollWidth <= innerWidth"))
        page.screenshot(path=str(output / "08-mobile-expanded.png"), full_page=True)
        reduced = make_context(viewport={"width": 390, "height": 844}, reduced_motion="reduce")
        small = new_page(reduced)
        small.goto(args.url, wait_until="domcontentloaded")
        small.locator("#cr-input textarea").wait_for()
        small.wait_for_function("window.__crChatInitialized === true")
        record("reduced motion bypasses intro", not small.locator(".cr-intro").is_visible())
        methods = ("skip", "focus") if args.modelscope_embed else ("skip", "focus", "storage failure", "initialization failure")
        for method in methods:
            fallback = make_context()
            if method == "storage failure":
                fallback.add_init_script("Object.defineProperty(window, 'sessionStorage', {get(){throw new Error('storage unavailable')}})")
            if method == "initialization failure":
                fallback.add_init_script("Object.defineProperty(window, '__crChatInitialized', {value:true,writable:false})")
            probe = new_page(fallback)
            probe.goto(args.url, wait_until="domcontentloaded")
            probe.locator("#cr-input textarea").wait_for()
            probe.wait_for_function("window.__crChatInitialized === true")
            if method in ("skip", "focus"):
                probe.locator(".cr-intro.cr-play").wait_for()
                if method == "skip":
                    probe.get_by_role("button", name="跳过开场", exact=True).click()
                else:
                    probe.locator("#cr-input textarea").focus()
            record("intro remains usable: " + method, not probe.locator(".cr-intro").is_visible())
            if method in ("storage failure", "initialization failure"):
                probe.locator("#cr-input textarea").fill("功能目录")
                probe.locator("#cr-send").click()
                probe.locator(".cr-result-header h2").filter(has_text="你可以这样使用").wait_for(timeout=25000)
                record("queries work after " + method, probe.locator(".cr-result-header").count() == 1)
            fallback.close()
        record("no browser script errors", not errors)
        reduced.close()
        context.close()
        browser.close()
    report["completed"] = True
    (output / "browser-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Browser acceptance: {len(checks)} checks passed")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
