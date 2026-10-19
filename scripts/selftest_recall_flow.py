# -*- coding: utf-8 -*-
"""
两层召回流程 · 离线自检（scripts/selftest_recall_flow.py）

桩掉 core.llm.chat / is_ready，验证：
    1. 路由层：编号目录、提示词参数、law_ref 映射、无效 ref 兜底
    2. 检索层：候选表、selected ref 校验、citation_map、无效 ref 兜底
    3. 确定性兜底：无模型时按 M1.5 词典 + 目录过滤
    4. run()：路由+检索编排、内存缓存、隐私参数（use_cache=False）

依赖真实 DB 里已经建好的目录树（tree_version 非空）；不联网。

用法：
    python scripts/selftest_recall_flow.py
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
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from core import llm, recall  # noqa: E402
from modules import recall_flow as rf  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    if cond:
        PASS.append(name)
        print("  ✅ %s" % name)
    else:
        FAIL.append((name, detail))
        print("  ❌ %s  %s" % (name, detail))


_ORIG_CHAT = llm.chat
_ORIG_READY = llm.is_ready
CALLS = []
RESPONSES = []


def stub_sequence(responses, ready=True):
    """按顺序返回模型输出；CALLS 记录每次调用参数。"""
    RESPONSES.clear()
    RESPONSES.extend(responses)
    CALLS.clear()
    rf.clear_cache()

    def fake_chat(prompt, max_tokens=4000, temperature=0.2, use_cache=True,
                  timeout=None, thinking=True):
        CALLS.append({
            "prompt": prompt, "max_tokens": max_tokens,
            "temperature": temperature, "use_cache": use_cache,
            "timeout": timeout, "thinking": thinking,
        })
        text = RESPONSES.pop(0) if RESPONSES else ""
        return text, {"ok": True, "reason": "", "cached": False}

    llm.chat = fake_chat
    llm.is_ready = lambda: ready


def unstub():
    llm.chat = _ORIG_CHAT
    llm.is_ready = _ORIG_READY


def _law_ref(law_id):
    for c in recall.law_catalog():
        if c["law_id"] == law_id:
            return c["ref"]
    return None


def main():
    print("=" * 74)
    print("  两层法规召回 · 自检（桩注入，不联网）")
    print("=" * 74)
    version = recall.tree_version()
    if not version:
        print("  ❌ 目录树未构建；请先运行 scripts/build_recall_tree.py")
        return 1
    print("  目录树版本：%s" % version)
    print()

    try:
        # ── 1. 路由层 ───────────────────────────────────────────
        print("【1】路由层：编号目录 + ref 校验")
        stub_sequence(['{"law_refs":[1,2],"facets":["chemical safety","labeling"],'
                       '"sub_questions":["玩具化学要求"],"catalog_gaps":[]}'])
        res = rf.route_laws("带蓝牙的毛绒玩具卖欧盟和美国")
        check("模型路由成功", res["ok"] and res["route_via"] == "模型路由", str(res.get("reason")))
        check("law_refs 映射到目录条目", len(res["laws"]) == 2 and
              res["laws"][0]["ref"] == 1 and res["laws"][1]["ref"] == 2)
        check("facets 被保留", res["facets"] == ["chemical safety", "labeling"])
        c = CALLS[0] if CALLS else {}
        check("路由 use_cache=False（原文不落盘）", c.get("use_cache") is False)
        check("路由 thinking=False", c.get("thinking") is False)
        check("路由 timeout=ROUTER_TIMEOUT", c.get("timeout") == rf.ROUTER_TIMEOUT)
        check("路由 temperature=0", c.get("temperature") == 0)
        check("提示词包含编号目录", "法规目录" in (c.get("prompt") or "")
              and "1 |" in (c.get("prompt") or ""))

        stub_sequence(['{"law_refs":[999,"x"],"facets":["labeling"]}'])
        res = rf.route_laws("儿童玩具 欧盟")
        check("全部 ref 无效 -> 词典兜底", res["route_via"] == "词典兜底" and res["ok"],
              str(res))
        check("无效 ref 被记录", len(res["invalid_refs"]) == 2, str(res["invalid_refs"]))
        check("兜底法规属于 EU 且覆盖品类/横切",
              bool(res["laws"]) and all(l["jurisdiction"] == "EU" for l in res["laws"]))
        print()

        # ── 2. 检索层 ───────────────────────────────────────────
        print("【2】检索层：候选表 + selected ref 校验 + citation_map")
        catalog = recall.law_catalog()
        laws = [c for c in catalog if c["law_id"] in ("EU:32009L0048", "US:16:1500")]
        cands = recall.candidate_nodes([l["law_id"] for l in laws], ["labeling"], 6)
        check("候选非空", bool(cands), "candidate_nodes 返回空")
        stub_sequence(['{"selected":[{"ref":1,"facet":"labeling","why":"标签要求"}],'
                       '"coverage":"sufficient","gaps":[]}'])
        ret = rf.retrieve("玩具标签要求", laws, ["labeling"])
        check("检索成功", ret["ok"] and len(ret["selected"]) == 1, str(ret.get("reason")))
        check("selected 带 citation_id/正文", ret["selected"][0]["citation_id"] == "c1"
              and bool(ret["selected"][0]["body"]))
        check("citation_map 含 c1", "c1" in ret["citation_map"])
        check("coverage 来自模型", ret["coverage"] == "sufficient")
        c = CALLS[0] if CALLS else {}
        check("检索 use_cache=False", c.get("use_cache") is False)
        check("检索 thinking=False", c.get("thinking") is False)
        check("检索 timeout=RETRIEVAL_TIMEOUT", c.get("timeout") == rf.RETRIEVAL_TIMEOUT)
        check("提示词包含候选切片", "候选切片" in (c.get("prompt") or ""))

        stub_sequence(['{"selected":[{"ref":999,"facet":"labeling"}],'
                       '"coverage":"sufficient"}'])
        ret = rf.retrieve("玩具标签要求", laws, ["labeling"])
        check("检索 ref 无效 -> 回退候选集", ret["ok"] and bool(ret["selected"]))
        check("检索无效 ref 被记录", 999 in ret["invalid_refs"])
        check("回退时 coverage=partial", ret["coverage"] == "partial")
        print()

        # ── 3. 无模型兜底 ───────────────────────────────────────
        print("【3】无模型时的确定性兜底")
        stub_sequence([], ready=False)
        res = rf.route_laws("儿童玩具 欧盟")
        check("词典兜底识别品类/市场", res["ok"] and res["route_via"] == "词典兜底"
              and bool(res["laws"]))
        check("兜底 facets 非空", bool(res["facets"]))
        res = rf.route_laws("玩具")
        check("缺市场时诚实拒绝", not res["ok"] and "市场" in res["reason"], str(res))
        res = rf.route_laws("钢材 欧盟")
        check("范围外品类被拒绝", not res["ok"], str(res))
        print()

        # ── 4. run() 编排与缓存 ─────────────────────────────────
        print("【4】run() 编排、缓存、隐私")
        toy_ref = _law_ref("EU:32009L0048")
        check("Toy Directive 在目录中", toy_ref is not None)
        stub_sequence([
            '{"law_refs":[%d],"facets":["labeling","chemical safety"],"sub_questions":[]}' % (toy_ref,),
            '{"selected":[{"ref":1,"facet":"labeling","why":"标签"}],"coverage":"sufficient","gaps":[]}',
        ])
        r1 = rf.run("玩具出口欧盟的标签要求")
        check("run 成功并带 citation_map",
              r1["ok"] and bool(r1["retrieval"]["citation_map"]), str(r1.get("reason")))
        check("run 路由到 Toy Directive",
              r1["route"]["laws"][0]["law_id"] == "EU:32009L0048")
        n_calls = len(CALLS)
        r2 = rf.run("玩具出口欧盟的标签要求")
        check("同一输入二次 run 命中缓存", r2.get("cached") is True)
        check("二次 run 未再调用模型", len(CALLS) == n_calls,
              "又调了 %d 次" % (len(CALLS) - n_calls))
        keys = list(rf._CACHE.keys())
        check("缓存键是 sha256 哈希（不含原文）",
              all(len(k) == 64 and "玩具" not in k for k in keys), str(keys[:1]))
        print()

        print("=" * 74)
        print("  通过 %d 项，失败 %d 项" % (len(PASS), len(FAIL)))
        if FAIL:
            for name, detail in FAIL:
                print("  FAIL: %s  %s" % (name, detail))
            print("=" * 74)
            return 1
        print("  ALL PASS")
        print("=" * 74)
        return 0
    finally:
        unstub()


if __name__ == "__main__":
    sys.exit(main())
