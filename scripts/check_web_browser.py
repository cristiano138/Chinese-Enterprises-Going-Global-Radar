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
