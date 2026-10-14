# -*- coding: utf-8 -*-
"""
批量检查骨架表里的官方链接能不能打开。

用途：
    「每条结论必须附官方原文链接」是本项目的核心承诺，
    所以链接能不能打开，必须**逐个实测**，不能靠猜。

做法：
    用 HEAD 请求（省流量）+ 浏览器 UA（部分政府站会拦爬虫 UA）。
    遇到 405/403 再退回 GET。

输出：
    控制台结果 + data/链接检查报告.txt

用法：
    python scripts/check_links.py
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

# 伪装成正常浏览器，避免被政府站的反爬 UA 规则拦掉
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def probe(url, timeout=25):
    """返回 (状态码, 判定, 说明)。

    判定分三档：
        200系列且不是 202 → 可程序验证
        202 且正文含 awswaf   → 人机验证墙（需人工在浏览器打开）
        其他              → 有问题
    """
    for method in ("HEAD", "GET"):
        try:
            req = urllib.request.Request(url, method=method, headers={
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml,*/*",
                "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
            })
            with urllib.request.urlopen(req, timeout=timeout) as r:
                status = r.status
                body = b""
                if method == "GET":
                    body = r.read(4096)
            # 202 是「已接受但未处理」，政府站的 WAF 常用它来发挑战页
            if status == 202:
                if method == "HEAD":
                    continue      # HEAD 读不到正文，换 GET 拿挑战页内容
                txt = body.decode("utf-8", "ignore").lower()
                if "awswaf" in txt or "challenge" in txt:
                    return "202", "WAF", "人机验证墙（需人工在浏览器打开）"
                return "202", "可疑", "返回 202，需人工确认"
            if 200 <= status < 300:
                return str(status), "OK", "可程序验证"
            return str(status), "BAD", f"HTTP {status}"
        except urllib.error.HTTPError as e:
            if e.code in (403, 405, 501) and method == "HEAD":
                continue          # 不支持 HEAD → 换 GET 再试
            if e.code == 403:
                return "403", "BAD", "被拒绝"
            if e.code == 404:
                return "404", "BAD", "页面不存在"
            return str(e.code), "BAD", f"HTTP {e.code}"
        except Exception as e:
            if method == "HEAD":
                continue
            return type(e).__name__, "BAD", str(e)[:80]
    return "?", "BAD", "所有方法均失败"


def main():
    src = os.path.join(DATA, "语料核对表_骨架总表.csv")
    if not os.path.exists(src):
        print(f"找不到 {src}，请先运行 merge_corpus.py")
        return

    with open(src, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    print("=" * 70)
    print(f"  官方链接实测 —— 共 {len(rows)} 条")
    print("=" * 70)

    lines = ["=" * 70, "  官方链接检查报告", "=" * 70, ""]
    ok = 0
    wall = []
    bad = []

    for i, r in enumerate(rows, 1):
        url = r["官方链接"]
        key = r["CELEX号"] or r["官方编号"]
        print(f"  [{i:>2}/{len(rows)}] {r['机构']} {key} ...", end=" ", flush=True)

        code, verdict, note = probe(url)
        if verdict == "OK":
            ok += 1
            print(f"✔ {code} {note}")
        elif verdict == "WAF":
            print(f"△ {code} {note}")
            wall.append((r, code, note))
        else:
            print(f"✘ {code} {note}")
            bad.append((r, code, note))

        lines.append(f"{verdict:<5} {code:<6} {r['机构']} {key:<22} {note}")
        time.sleep(0.6)

    lines.append("")
    lines.append("-" * 70)
    lines.append(f"可程序验证 {ok} / {len(rows)}")
    lines.append(f"人机验证墙 {len(wall)} / {len(rows)}")
    lines.append(f"有问题     {len(bad)} / {len(rows)}")
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

    # ── 回填骨架表：把「链接可打开」列写成实测结论 ──────────
    verdict_map = {}
    for r, code, note in wall:
        verdict_map[r["CELEX号"] or r["官方编号"]] = "需人工浏览器验证（WAF）"
    for r, code, note in bad:
        verdict_map[r["CELEX号"] or r["官方编号"]] = f"有问题：{code}"

    src_rows = None
    with open(src, encoding="utf-8-sig") as f:
        src_rows = list(csv.DictReader(f))
    for r in src_rows:
        key = r["CELEX号"] or r["官方编号"]
        if key in verdict_map:
            r["链接可打开"] = verdict_map[key]
        else:
            r["链接可打开"] = "是（程序实测 200）"
        # 来源类型：能程序验证的写官方原文，WAF 的写官方原文（数据接口已验证）
        if not r["来源类型"]:
            r["来源类型"] = "官方原文"
    with open(src, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(src_rows[0].keys()))
        w.writeheader()
        w.writerows(src_rows)

    print()
    print("-" * 70)
    print(f"  可程序验证 {ok} / {len(rows)}")
    print(f"  人机验证墙 {len(wall)} / {len(rows)}（欧盟整站，正常现象）")
    print(f"  有问题     {len(bad)} / {len(rows)}")
    print(f"  已回填「链接可打开」列 → {src}")
    print(f"  报告：{txt}")
    print("=" * 70)


if __name__ == "__main__":
    main()
