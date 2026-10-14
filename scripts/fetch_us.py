# -*- coding: utf-8 -*-
"""
美国法规骨架数据抓取器（eCFR 官方 API）

用途：
    调用 eCFR 官方 API，把「法规清单」的骨架数据（法规名、编号、链接、
    生效/修订日期）批量抓出来，生成可直接填进语料核对表的 CSV。

数据源：
    https://www.ecfr.gov/api/versioner/v1/   （免费、免密钥）

输出：
    data/us_regulations.csv

用法：
    python scripts/fetch_us.py
"""

import csv
import json
import os
import sys
import time
import urllib.request
import urllib.error

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE = "https://www.ecfr.gov/api/versioner/v1"
HEADERS = {
    "User-Agent": "compliance-radar/1.0 (academic research; contact via project repo)",
    "Accept": "application/json",
}
# 官方 API 建议：请求要慢一点，别打太快
REQUEST_INTERVAL = 1.0

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
OUT_DIR = os.path.join(PROJECT, "data")


def api_get(path, retries=3):
    """调 eCFR API，带重试。"""
    url = f"{BASE}/{path}"
    last_err = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code}"
            if e.code in (429, 503):
                time.sleep(2 * (i + 1))
                continue
            raise
        except Exception as e:
            last_err = str(e)
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"请求失败：{url} —— {last_err}")


def get_current_date():
    """拿 eCFR 当前数据日期。"""
    data = api_get("titles.json")
    meta = data.get("meta", {})
    return meta.get("date"), data.get("titles", [])


def flatten(node, chain, out, want_types=("part",)):
    """
    递归遍历 CFR 结构树，抽出指定层级的节点。
    chain 记录从顶到当前的路径，用于拼 URL。
    """
    t = node.get("type")
    ident = str(node.get("identifier", "")).strip()
    label = (node.get("label") or node.get("label_description") or "").strip()

    new_chain = chain + [{"type": t, "identifier": ident, "label": label}]

    if t in want_types:
        out.append({"node": node, "chain": list(new_chain)})

    for child in node.get("children") or []:
        flatten(child, new_chain, out, want_types)


def get_versions(tnum, part_id):
    """
    拿某个 Part 的修订历史。
    返回 (最新修订日期, 修订次数, 最近的修订列表, 最早的修订日期)
    """
    try:
        d = api_get(f"versions/title-{tnum}.json?part={part_id}")
    except Exception:
        return "", 0, [], ""

    meta = d.get("meta", {}) or {}
    latest = meta.get("latest_amendment_date") or meta.get("latest_issue_date") or ""
    cv = d.get("content_versions", []) or []

    # 只看实质性修订，按日期倒序，取最近 3 次
    subst = [v for v in cv if v.get("substantive")]
    seen = set()
    recent = []
    for v in sorted(subst, key=lambda x: x.get("amendment_date", ""), reverse=True):
        dt = v.get("amendment_date", "")
        if dt and dt not in seen:
            seen.add(dt)
            recent.append(dt)
        if len(recent) >= 3:
            break

    # 最早的修订日期 —— 美国 CFR 是持续修订的汇编，没有单一"生效日"，
    # 用最早记录作为「首次收录/首次生效参考」，并在备注里标明性质
    dates = [v.get("amendment_date", "") for v in cv if v.get("amendment_date")]
    earliest = min(dates) if dates else ""

    return latest, len(cv), recent, earliest


def build_url(chain, date):
    """根据层级链拼出 eCFR 官方链接。"""
    parts = []
    for seg in chain:
        t = seg["type"]
        ident = seg["identifier"]
        if t == "title":
            parts.append(f"title-{ident}")
        elif t == "part":
            parts.append(f"part-{ident}")
        elif t == "chapter":
            # 章节用罗马数字，eCFR URL 里通常省略，先跳过
            continue
        elif t == "subchapter":
            continue
        elif t == "subpart":
            parts.append(f"subpart-{ident}")
        elif t == "section":
            parts.append(f"section-{ident}")
    if not parts:
        return ""
    return "https://www.ecfr.gov/current/" + "/".join(parts)


# ── 我们要抓的目标（按品类组织） ─────────────────────────────
# 只抓跟项目品类直接相关的 Part，不全量抓（避免几千条）
TARGETS = [
    # ── 儿童玩具（CPSC） ──
    {"title": 16, "category": "儿童玩具", "agency": "CPSC", "part_keys": ["1250", "1303", "1307", "1500", "1501"]},
    # ── 电子电器（FCC + CPSC） ──
    {"title": 47, "category": "电子电器", "agency": "FCC", "part_keys": ["15", "18"]},
    {"title": 16, "category": "电子电器", "agency": "CPSC", "part_keys": ["1505", "1120"]},
    # ── 纺织服装（FTC 标签法规） ──
    {"title": 16, "category": "纺织服装", "agency": "FTC", "part_keys": ["300", "301", "303", "423"]},
    # ── 美妆个护（FDA） ──
    {"title": 21, "category": "美妆个护", "agency": "FDA", "part_keys": ["700", "710", "720", "740"]},
    # ── 食品接触材料（FDA） ──
    {"title": 21, "category": "食品接触材料", "agency": "FDA", "part_keys": ["174", "175", "176", "177", "178", "180"]},

    # ═══ 扩充部分（10.14 晚补足到 40 条）═══
    # ── 儿童玩具：玩具安全法规全集 ──
    {"title": 16, "category": "儿童玩具", "agency": "CPSC",
     "part_keys": ["1112", "1113", "1200", "1201", "1202", "1203", "1204",
                   "1205", "1207", "1209", "1210", "1211", "1212", "1213",
                   "1220", "1224", "1230", "1241", "1243", "1251", "1252"]},
    # ── 电子电器：家用电器安全 + 电池 ──
    {"title": 16, "category": "电子电器", "agency": "CPSC",
     "part_keys": ["1101", "1105", "1107", "1109", "1110", "1120"]},
    # ── 纺织服装：阻燃与服装安全 ──
    {"title": 16, "category": "纺织服装", "agency": "CPSC",
     "part_keys": ["1610", "1611", "1615", "1616", "1630", "1631", "1632"]},
    # ── 美妆个护：化妆品与化学品标签 ──
    {"title": 21, "category": "美妆个护", "agency": "FDA",
     "part_keys": ["701", "730", "740"]},
    # ── 食品接触材料：详细章节 ──
    {"title": 21, "category": "食品接触材料", "agency": "FDA",
     "part_keys": ["170", "171", "172", "173", "179", "181", "186"]},
    # ── 通用/标签标识：公平包装与标签法 ──
    {"title": 16, "category": "标签标识", "agency": "FTC",
     "part_keys": ["500", "501", "502", "503"]},
]


def main():
    print("=" * 62)
    print("  美国法规骨架抓取 —— eCFR 官方 API")
    print("=" * 62)
    print()

    date, titles = get_current_date()
    print(f"  数据日期：{date}")
    print(f"  Title 总数：{len(titles)}")
    print()

    title_names = {t["number"]: t["name"] for t in titles}

    rows = []
    cache = {}

    for target in TARGETS:
        tnum = target["title"]
        print(f"  处理 Title {tnum}（{title_names.get(tnum, '?')}）...")

        # 结构数据缓存（同一个 title 只拉一次）
        if tnum not in cache:
            try:
                cache[tnum] = api_get(f"structure/{date}/title-{tnum}.json")
            except Exception as e:
                print(f"    [!] 拉取 Title {tnum} 失败：{e}")
                continue
            time.sleep(REQUEST_INTERVAL)
            print(f"    拉取 Title {tnum} 完整结构完成")
            # 立刻落盘缓存，避免重复拉取
            cpath = os.path.join(OUT_DIR, f"_cache_title{tnum}.json")
            with open(cpath, "w", encoding="utf-8") as f:
                json.dump(cache[tnum], f, ensure_ascii=False)

        found = []
        flatten(cache[tnum], [], found, want_types=("part",))

        for item in found:
            part_id = str(item["node"].get("identifier", "")).strip()
            if part_id not in target["part_keys"]:
                continue

            label = (item["node"].get("label") or item["node"].get("label_description") or "").strip()
            # label 形如 "Part 1250—Safety Standard Mandating ASTM F963 for Toys"
            if "—" in label:
                part_title = label.split("—", 1)[1].strip()
            elif " - " in label:
                part_title = label.split(" - ", 1)[1].strip()
            else:
                part_title = label

            url = build_url(item["chain"], date)
            citation = f"{tnum} CFR Part {part_id}"

            # 补：修订历史
            latest_amend, ver_count, recent_dates, earliest = get_versions(tnum, part_id)
            time.sleep(REQUEST_INTERVAL)

            note = "eCFR 为电子版非官方法律版，引用建议同时给 govinfo.gov 官方版"
            if recent_dates:
                note += f"；近期修订：{ '、'.join(recent_dates) }（共 {ver_count} 条修订记录）"

            rows.append({
                "类目": target["category"],
                "机构": target["agency"],
                "法规中文名": "",          # 待人工/AI 补
                "官方标题（英文）": part_title,
                "官方编号": citation,
                "CELEX号": "",             # 美国没有 CELEX
                "ELI标识": "",
                "官方链接": url,
                "来源类型": "官方（eCFR）",
                # 美国 CFR 是持续修订的汇编，无单一"生效日"；
                # 这里填最早修订记录，作为「首次收录参考」，性质已在备注标明
                "生效日期": f"首次收录 {earliest}（参考）" if earliest else "",
                "最新修订日期": latest_amend,
                "链接可打开": "待查",
                "编号核对": "待查",
                "是否官方来源": "官方",
                "核对状态": "待核对",
                "核对人": "",
                "核对日期": "",
                "备注／问题": note,
            })

        time.sleep(REQUEST_INTERVAL)

    print()
    print(f"  共抓到 {len(rows)} 条 Part 级法规")
    print()

    # 写 CSV（给 Excel/WPS 直接打开）
    os.makedirs(OUT_DIR, exist_ok=True)
    out_csv = os.path.join(OUT_DIR, "us_regulations.csv")
    cols = ["类目", "机构", "法规中文名", "官方标题（英文）", "官方编号", "CELEX号",
            "ELI标识", "官方链接", "来源类型", "生效日期", "最新修订日期",
            "链接可打开", "编号核对", "是否官方来源", "核对状态", "核对人", "核对日期", "备注／问题"]

    # utf-8-sig 让 Excel 正确识别中文
    with open(out_csv, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)

    print(f"  已保存：{out_csv}")
    print()

    # 按类目统计
    from collections import Counter
    c = Counter(r["类目"] for r in rows)
    print("  按类目统计：")
    for k, v in c.items():
        print(f"    {k:10s} {v} 条")
    print()
    print("=" * 62)
    print("  完成。下一步：打开 CSV，核对链接是否可打开。")
    print("=" * 62)


if __name__ == "__main__":
    main()
