# -*- coding: utf-8 -*-
"""
批量检查骨架表里的官方链接能不能打开。

用途：
    「每条结论必须附官方原文链接」是本项目的核心承诺，
    所以链接能不能打开，必须**逐个实测**，不能靠猜。

做法：
    用 HEAD 请求（省流量）+ 浏览器 UA（部分政府站会拦爬虫 UA）。
    遇到 405/403 再退回 GET。
    遇到 429/503（限流）做指数退避复测，并把「复测后通过」单独记一档。

输出：
    控制台结果 + data/链接检查报告.txt
    并**非破坏性**回填 data/语料核对表_骨架总表.csv 的「链接可打开」列

用法：
    python scripts/check_links.py            # 只补空值，不覆盖已有结论
    python scripts/check_links.py --force    # 强制用本次实测结果覆盖

变更记录（2026-10-14 修复，对应《代码审查报告-补充》）：
    - [新增问题1] 原报告与主底表结论打架：报告里有 5 条 429 失败，主底表却写"复测通过"，
      而脚本从不复测、也无法产出"复测通过"这一结论。现 probe() 支持 429/503 退避复测，
      并新增「OK复测」档，使报告与主表同源同结论。
    - [新增问题2] 原回填逻辑对任意非 WAF/BAD 的行**无条件**写 "是（程序实测 200）"，
      会覆盖已人工复核的结论（如"首次限流已复测"），不可恢复。现改为**只补空值**，
      已有结论默认保留；需要时用 --force 显式覆盖。
"""

import csv
import os
import sys
import time
import urllib.error
import urllib.request

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
DATA = os.path.join(PROJECT, "data")

# 这些值代表「尚未有结论」，允许被本次实测结果覆盖
PLACEHOLDER = {"", "待查", "待人工核对"}

# 伪装成正常浏览器，避免被政府站的反爬 UA 规则拦掉
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

RETRY_CODES = (429, 503)          # 限流/暂不可用 —— 值得退避复测
MAX_RETRY = 3


def _once(url, method, timeout):
    """发一次请求，返回 (status, body, headers, exc)。"""
    req = urllib.request.Request(url, method=method, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,*/*",
        "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read(4096) if method == "GET" else b""
            return r.status, body, dict(r.headers), None
    except urllib.error.HTTPError as e:
        return e.code, b"", dict(e.headers or {}), e
    except Exception as e:
        return None, b"", {}, e


def probe(url, timeout=25):
    """返回 (状态码, 判定, 说明, 重试次数)。

    判定分档：
        OK      —— 首次即 200 系列
        OK复测   —— 先遇 429/503，退避后重试通过
        WAF     —— 202 且命中 WAF 特征（响应头 x-amzn-waf-action 或正文含 awswaf/challenge）
        SUSPECT —— 202 但无挑战特征，需人工确认
        BAD     —— 其他问题
    """
    retries = 0
    while True:
        status, body, headers, exc = None, b"", {}, None
        for method in ("HEAD", "GET"):
            status, body, headers, exc = _once(url, method, timeout)
            if exc is not None:
                # HEAD 不被支持（403/405/501/406）→ 换 GET 再试
                if getattr(exc, "code", None) in (403, 405, 501, 406) and method == "HEAD":
                    continue
                break
            # ⚠️ 202 是挑战页状态码，HEAD 读不到正文 → 必须换 GET 拿正文再判定
            if method == "HEAD" and status == 202:
                continue
            break

        if exc is not None:
            sc = getattr(exc, "code", None)
            if sc in RETRY_CODES and retries < MAX_RETRY:
                retries += 1
                time.sleep(2 * retries)
                continue
            if sc == 403:
                return "403", "BAD", "被拒绝", retries
            if sc == 404:
                return "404", "BAD", "页面不存在", retries
            if sc is None:
                return type(exc).__name__, "BAD", str(exc)[:80], retries
            return str(sc), "BAD", f"HTTP {sc}", retries

        if status == 202:
            waf_hdr = (headers.get("x-amzn-waf-action") or "").lower()
            txt = body.decode("utf-8", "ignore").lower()
            if "challenge" in waf_hdr or "awswaf" in txt or "challenge" in txt:
                return "202", "WAF", "人机验证墙（需人工在浏览器打开）", retries
            return "202", "SUSPECT", "返回 202，需人工确认", retries
        if status is not None and 200 <= status < 300:
            if retries:
                return str(status), "OK复测", f"首遇限流，退避复测 {retries} 次后通过", retries
            return str(status), "OK", "可程序验证", retries
        return str(status), "BAD", f"HTTP {status}", retries


def main():
    force = "--force" in sys.argv

    src = os.path.join(DATA, "语料核对表_骨架总表.csv")
    if not os.path.exists(src):
        print(f"找不到 {src}，请先运行 merge_corpus.py")
        return

    with open(src, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    print("=" * 70)
    print(f"  官方链接实测 —— 共 {len(rows)} 条"
          f"{'（--force 覆盖已有结论）' if force else '（只补空值）'}")
    print("=" * 70)

    lines = ["=" * 70, "  官方链接检查报告", "=" * 70, ""]
    ok = ok_retry = 0
    wall, bad, suspect = [], [], []

    for i, r in enumerate(rows, 1):
        url = r["官方链接"]
        key = r["CELEX号"] or r["官方编号"]
        print(f"  [{i:>2}/{len(rows)}] {r['机构']} {key} ...", end=" ", flush=True)

        code, verdict, note, retries = probe(url)
        if verdict == "OK":
            ok += 1
            print(f"✔ {code} {note}")
        elif verdict == "OK复测":
            ok_retry += 1
            print(f"✔ {code} {note}")
        elif verdict == "WAF":
            print(f"△ {code} {note}")
            wall.append((r, code, note))
        elif verdict == "SUSPECT":
            print(f"? {code} {note}")
            suspect.append((r, code, note))
        else:
            print(f"✘ {code} {note}")
            bad.append((r, code, note))

        rt = f"（重试{retries}次）" if retries else ""
        lines.append(f"{verdict:<8} {code:<6} {r['机构']} {key:<22} {note}{rt}")
        time.sleep(0.6)

    lines.append("")
    lines.append("-" * 70)
    lines.append(f"可程序验证（首次 200） {ok} / {len(rows)}")
    lines.append(f"限流复测后通过         {ok_retry} / {len(rows)}")
    lines.append(f"人机验证墙             {len(wall)} / {len(rows)}")
    lines.append(f"待人工确认(202)        {len(suspect)} / {len(rows)}")
    lines.append(f"有问题                 {len(bad)} / {len(rows)}")
    lines.append("")
    lines.append("说明：")
    lines.append("  人机验证墙 = 网站对程序访问有 AWS WAF 挑战，真人在浏览器点开是正常的。")
    lines.append("  欧盟 EUR-Lex 整站都属于这一类，所以欧盟数据一律走官方 SPARQL 数据接口验证。")
    lines.append("")
    if bad:
        lines.append("需要人工处理的：")
        for r, code, note in bad:
            lines.append(f"  - {r['机构']} {r['CELEX号'] or r['官方编号']}  [{code}] {note}")
            lines.append(f"    {r['官方链接']}")

    txt = os.path.join(DATA, "链接检查报告.txt")
    with open(txt, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    # ── 非破坏性回填「链接可打开」列 ──────────────────────
    # 先按唯一键建「结论表」，再逐行决定是否写入（默认只补空值）
    verdict_map = {}
    for rr, code, note in wall:
        verdict_map[rr["CELEX号"] or rr["官方编号"]] = "需人工浏览器验证（WAF）"
    for rr, code, note in suspect:
        verdict_map[rr["CELEX号"] or rr["官方编号"]] = f"待人工确认：{code}"
    for rr, code, note in bad:
        verdict_map[rr["CELEX号"] or rr["官方编号"]] = f"有问题：{code}"
    for rr in rows:
        key = rr["CELEX号"] or rr["官方编号"]
        verdict_map.setdefault(key, "是（程序实测 200）")

    changed = kept = 0
    with open(src, encoding="utf-8-sig") as f:
        src_rows = list(csv.DictReader(f))
    for r in src_rows:
        old = (r.get("链接可打开", "") or "").strip()
        val = verdict_map.get(r["CELEX号"] or r["官方编号"], "是（程序实测 200）")
        if force or old in PLACEHOLDER:
            if old != val:
                changed += 1
            r["链接可打开"] = val
        else:
            kept += 1
    with open(src, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(src_rows[0].keys()))
        w.writeheader()
        w.writerows(src_rows)

    print()
    print("-" * 70)
    print(f"  可程序验证 {ok}   限流复测 {ok_retry}   人机墙 {len(wall)}   "
          f"待确认 {len(suspect)}   有问题 {len(bad)}")
    print(f"  「链接可打开」列：写入/更新 {changed} 条，保留已有结论 {kept} 条")
    print(f"  报告：{txt}")
    print("=" * 70)


if __name__ == "__main__":
    main()
