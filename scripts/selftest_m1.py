# -*- coding: utf-8 -*-
"""
M1 自检（scripts/selftest_m1.py）

用**确定性断言**把 M1 的验收标准跑一遍，不依赖人手点界面：
    1. 覆盖率：每个「品类 × 市场」组合都能查出条目，且与 README 覆盖矩阵一致
    2. 链接回挂率：100%（红线 —— 无官方链接的条目一律不输出）
    3. 链接官方性：全部落在官方域名白名单内
    4. 唯一性：同一组合内无重复编号
    5. 边界：范围外输入被明确拒绝，不硬编答案
    6. 防幻觉：编造的编号会被引用对齐拦下
    7. 降级：模型不可用时仍能输出完整清单

用法：
    python scripts/selftest_m1.py
退出码 0 = 全绿；1 = 有失败项。
"""

import os
import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)

from core import corpus, verify, snapshot  # noqa: E402
from modules import m1_map  # noqa: E402

# README「语料现状」表 —— 自检的期望值（不重算，直接对照文档口径）
EXPECTED = {
    ("儿童玩具", "欧盟"): 3, ("儿童玩具", "美国"): 15,
    ("电子电器", "欧盟"): 9, ("电子电器", "美国"): 9,
    ("纺织服装", "欧盟"): 4, ("纺织服装", "美国"): 11,
    ("美妆个护", "欧盟"): 1, ("美妆个护", "美国"): 5,
    ("食品接触材料", "欧盟"): 7, ("食品接触材料", "美国"): 13,
}

PASS, FAIL = [], []


def check(name, cond, detail=""):
    if cond:
        PASS.append(name)
        print(f"  ✅ {name}")
    else:
        FAIL.append((name, detail))
        print(f"  ❌ {name}  {detail}")


def main():
    print("=" * 74)
    print("  M1 合规地图 · 自检")
    print("=" * 74)
    s = corpus.stats()
    print(f"  语料文件：{s['file']}　总条数：{s['total']}")
    print()

    # ── 1. 覆盖率 ────────────────────────────────────────────
    print("【1】覆盖率（与 README 覆盖矩阵逐项对照）")
    total_records = 0
    for (cat, mkt), exp in EXPECTED.items():
        res = m1_map.query(cat, mkt, use_llm=False)
        got = len(res["primary"])
        total_records += got
        check(f"{cat} × {mkt} = {got} 条（期望 {exp}）", got == exp,
              f"实际 {got}，期望 {exp}")
    cross_n = s["category"].get("标签标识", 0) + s["category"].get("通用", 0)
    check(f"覆盖矩阵合计 {total_records} 条 + 横切 {cross_n} 条 = 语料 {s['total']} 条",
          total_records + cross_n == s["total"],
          f"合计 {total_records}+{cross_n} vs {s['total']}")
    chk = corpus.search("儿童玩具", "欧盟")
    check(f"横切不作独立入口（PRD 第 3 节），随品类附带 {len(chk['cross'])} 条",
          len(chk["cross"]) > 0)
    print()

    # ── 2. 链接回挂率 100%（红线）────────────────────────────
    print("【2】引用对齐：链接回挂率 100%（红线）")
    checked = 0
    no_link = 0
    not_official = 0
    for cat in corpus.ALL_QUERYABLE:
        for mkt in corpus.SUPPORTED_MARKETS:
            res = m1_map.query(cat, mkt, use_llm=False)
            for r in res["primary"] + res["cross"]:
                checked += 1
                if not r["官方原文链接"]:
                    no_link += 1
                elif not verify.is_official_url(r["官方原文链接"]):
                    not_official += 1
    check(f"逐条检查 {checked} 条输出，0 条缺链接", no_link == 0, f"缺 {no_link} 条")
    check(f"全部链接域名在官方白名单内（{len(verify.OFFICIAL_HOSTS)} 个域）",
          not_official == 0, f"非官方 {not_official} 条")
    print()

    # ── 3. 唯一性 ────────────────────────────────────────────
    print("【3】唯一性：同一组合内无重复编号")
    dup_total = 0
    for cat in corpus.ALL_QUERYABLE:
        for mkt in corpus.SUPPORTED_MARKETS:
            res = m1_map.query(cat, mkt, use_llm=False)
            keys = [r["key"] for r in res["primary"] + res["cross"]]
            dup = len(keys) - len(set(keys))
            dup_total += dup
    check("全部组合内无重复编号", dup_total == 0, f"重复 {dup_total} 处")
    print()

    # ── 4. 边界：范围外输入 ─────────────────────────────────
    print("【4】边界：范围外输入必须被明确拒绝")
    for cat, mkt in [("汽车配件", "欧盟"), ("儿童玩具", "日本"),
                     ("", "欧盟"), ("儿童玩具", "")]:
        res = m1_map.query(cat, mkt, use_llm=False)
        check(f"拒绝「{cat or '空'} × {mkt or '空'}」",
              res["ok"] is False and bool(res["reason"]),
              f"ok={res['ok']}")
    print()

    # ── 5. 防幻觉：编造编号被拦 ──────────────────────────────
    print("【5】防幻觉：编造编号必须被引用对齐拦下")
    fake = [{"key": "32015R1000"}, {"key": "32025R2509"}]
    real_keys = {"32025R2509"}
    aligned, rejected = verify.align_output(fake, real_keys)
    check("编造编号 32015R1000 被拦下",
          len(rejected) == 1 and rejected[0][0]["key"] == "32015R1000",
          f"rejected={rejected}")
    check("真实编号 32025R2509 通过", len(aligned) == 1, f"aligned={aligned}")
    print()

    # ── 5b. 官方链接解析安全 ─────────────────────────────────
    print("【5b】官方链接解析：拒绝用户信息与异常端口绕过")
    check("用户信息绕过链接被拒绝",
          not verify.is_official_url("https://ecfr.gov:443@attacker.example/"))
    check("非标准端口链接被拒绝",
          not verify.is_official_url("https://ecfr.gov:8443/title/1"))
    check("官方 HTTPS 链接通过",
          verify.is_official_url("https://www.ecfr.gov/current/title-16"))
    check("空分母回挂率为未测",
          verify.rate([], 0) is None)
    print()

    # ── 6. 降级：模型不可用仍输出完整清单 ────────────────────
    print("【6】降级：模型不可用时仍输出完整清单")
    res = m1_map.query("电子电器", "美国", use_llm=False)
    check("LLM 关闭时仍返回完整法规记录",
          res["ok"] and len(res["primary"]) == 9, f"primary={len(res['primary'])}")
    txt = m1_map.render_text(res)
    check("文本渲染含免责声明", snapshot.DISCLAIMER in txt)
    print()

    # ── 7. 效力状态可见（已废止必须标出）────────────────────
    print("【7】失效法规必须显式标出，且沉到列表后面")
    res = m1_map.query("电子电器", "欧盟", use_llm=False)
    expired = [r for r in res["primary"] if r["是否仍有效"].startswith("⚠️")]
    check("欧盟电子电器含已废止条目且已标注", len(expired) >= 1,
          f"找到 {len(expired)} 条")
    print()

    print("=" * 74)
    print(f"  结果：通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    for name, detail in FAIL:
        print(f"    ❌ {name}  {detail}")
    print("=" * 74)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
