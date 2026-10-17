# -*- coding: utf-8 -*-
"""
M1.5 路由 · 自检（模型路径，离线、确定性）

为什么要单独一个脚本：
    `modules/m15_router.py` 底部的自检强制走词典路径（use_llm=False），
    覆盖面到不了模型分支。而真实模型**温度 0 也不确定**（实测同一输入
    时而返回「通用」时而返回空串），拿它当回归网等于没有回归网。

做法：**桩掉 `llm.chat` 与 `llm.is_ready`**，注入各种模型返回，断言 route() 的行为。
     ⚠️ `is_ready` 必须一起桩 —— 否则 route() 会认为链路未配置，桩的 chat 根本不会被调用。

用法：
    python scripts/selftest_m15.py     # 退出码 0 = 全绿
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)

from core import llm  # noqa: E402
from modules import m15_router  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    if cond:
        PASS.append(name)
        print(f"  ✅ {name}")
    else:
        FAIL.append((name, detail))
        print(f"  ❌ {name}  {detail}")


# ── 桩：替换 llm.chat / llm.is_ready ────────────────────────────
_ORIG_CHAT = llm.chat
_ORIG_READY = llm.is_ready
CALLS = []


def stub(text, meta=None, ready=True):
    """让模型返回 `text`（meta 缺省为成功）。CALLS 记录每次调用参数。

    同时清空路由层内存缓存 —— 同一输入换桩重测时，不能让旧解析结果
    从缓存里回来冒充本次桩的输出。
    """
    CALLS.clear()
    m15_router._PARSE_CACHE.clear()
    _meta = meta if meta is not None else {"ok": True, "reason": "", "cached": False}

    def fake_chat(prompt, max_tokens=4000, temperature=0.2, use_cache=True,
                  timeout=None, thinking=True):
        # 形参必须与 core/llm.chat() 保持一致：模型侧新增参数时若漏改桩，
        # 整条发布门禁会因 TypeError 直接变红（10-17 复审发现并修复）。
        CALLS.append({"prompt": prompt, "max_tokens": max_tokens,
                      "temperature": temperature, "use_cache": use_cache,
                      "timeout": timeout, "thinking": thinking})
        return text, _meta

    llm.chat = fake_chat
    llm.is_ready = lambda: ready


def unstub():
    llm.chat = _ORIG_CHAT
    llm.is_ready = _ORIG_READY


def main():
    print("=" * 74)
    print("  M1.5 输入驱动路由 · 自检（模型路径，桩注入，不联网）")
    print("=" * 74)
    print()

    # ── 1. 模型调用参数（红线 + 推理模型额度）────────────────
    print("【1】模型调用参数：隐私红线与额度")
    stub('{"品类":"儿童玩具","市场":"美国","用户品类":"洋娃娃","用户市场":"美国","命中依据":"洋娃娃、美国"}')
    m15_router.route("我要把洋娃娃卖到美国去", "")
    c = CALLS[0] if CALLS else {}
    check("路由调用 use_cache=False（隐私红线：输入原文不落盘）",
          c.get("use_cache") is False, f"实际 {c.get('use_cache')}")
    check("max_tokens=4000（推理模型 reasoning 计入额度，300 会空返回）",
          c.get("max_tokens") == 4000, f"实际 {c.get('max_tokens')}")
    check("temperature=0", c.get("temperature") == 0, f"实际 {c.get('temperature')}")
    check("timeout=MODEL_TIMEOUT（硬超时封顶，防止 26s+ 干等）",
          c.get("timeout") == m15_router.MODEL_TIMEOUT,
          f"实际 {c.get('timeout')}")
    check("thinking=False（路由只抽槽位，关思考模式换延迟）",
          c.get("thinking") is False, f"实际 {c.get('thinking')}")
    print()

    # ── 1b. 内存缓存：同一输入第二次不再调用模型（响应提速主力）──
    print("【1b】内存缓存：哈希键、不含原文、命中免调用")
    n_calls = len(CALLS)
    res2 = m15_router.route("我要把洋娃娃卖到美国去", "")
    check("同一输入二次路由 → 未再调用模型（缓存命中）",
          len(CALLS) == n_calls, f"又调了 {len(CALLS) - n_calls} 次")
    check("  缓存命中结果与首次一致", res2["ok"] is True and
          res2.get("品类") == "儿童玩具" and res2.get("市场") == "美国")
    raw_keys = list(m15_router._PARSE_CACHE.keys())
    check("  缓存键是 sha256 哈希（不含原文）",
          all(len(k) == 64 and "洋娃娃" not in k for k in raw_keys),
          f"keys={raw_keys[:1]}")
    print()

    # ── 2. 枚举收紧：模型给出范围外的值不许放行 ────────────────
    print("【2】枚举收紧到 ENTRY_CATEGORIES（5 个）")
    stub('{"品类":"通用","市场":"美国","用户品类":"汽车零部件","用户市场":"","命中依据":"汽车零部件出口到美国"}')
    res = m15_router.route("我要把汽车零部件出口到美国")
    check("模型返回旧枚举「通用」→ 必须拒绝，不许出成功卡片",
          res["ok"] is False, f"ok={res['ok']} 品类={res.get('品类')}")
    check("  理由为 bad_category", res.get("reason") == "bad_category",
          res.get("reason"))
    check("  m1 为 None（没走到查表，不会出现『上卡成功+下卡报错』）",
          res["m1"] is None)
    print()

    # ── 3. 「说了但不支持」必须点名 ───────────────────────────
    print("【3】bad_market / bad_category 由设计保证可达")
    stub('{"品类":"纺织服装","市场":"范围外","用户品类":"童装","用户市场":"日本","命中依据":"童装卖到日本"}')
    res = m15_router.route("童装卖到日本")
    ident = res.get("识别") or {}
    check("模型判出范围外市场 → bad_market", res.get("reason") == "bad_market",
          res.get("reason"))
    check("  点名用户说的市场「日本」", ident.get("用户市场") == "日本",
          f"用户市场={ident.get('用户市场')!r}")

    stub('{"品类":"范围外","市场":"美国","用户品类":"钢材","用户市场":"美国","命中依据":"钢材卖到美国"}')
    res = m15_router.route("把钢材卖到美国")
    check("模型判出范围外品类 → bad_category",
          res.get("reason") == "bad_category", res.get("reason"))
    check("  点名用户说的品类「钢材」",
          (res.get("识别") or {}).get("用户品类") == "钢材")
    print()

    # ── 4. 成功路径：可追溯性 + 不变量 ────────────────────────
    print("【4】成功路径：模型依据透传 + ok ⇒ m1.ok")
    stub('{"品类":"儿童玩具","市场":"美国","用户品类":"洋娃娃","用户市场":"美国","命中依据":"洋娃娃、美国"}')
    res = m15_router.route("我要把洋娃娃卖到美国去")
    ident = res.get("识别") or {}
    check("判定成功", res["ok"] is True, str(res.get("reason")))
    check("  不变量：ok ⇒ m1.ok", res["m1"] is not None and res["m1"]["ok"] is True)
    check("  成功分支也返回「识别」（原来只有失败分支有）",
          "识别" in res and bool(ident), f"keys={sorted(res.keys())}")
    check("  模型的命中依据被透传（可追溯）",
          ident.get("命中依据") == "洋娃娃、美国", repr(ident.get("命中依据")))
    check("  槽位来源标注为「模型」",
          ident.get("品类来源") == "模型" and ident.get("市场来源") == "模型",
          f"{ident.get('品类来源')}/{ident.get('市场来源')}")
    check("  路由方式为「模型解析」", res.get("route_via") == "模型解析",
          res.get("route_via"))
    print()

    # ── 5. 混合与降级：route_via 必须与 note 口径一致 ──────────
    print("【5】route_via 如实标注（模型失败时不许自称「混合」）")
    stub('{"品类":"","市场":"欧盟","用户品类":"","用户市场":"欧盟","命中依据":"欧盟"}')
    res = m15_router.route("蓝牙耳机出口欧盟")
    check("模型只给市场、词典补品类 → 混合（模型 + 词典）",
          res.get("route_via") == "混合（模型 + 词典）", res.get("route_via"))
    check("  且判定成功（词典补上了品类）", res["ok"] is True)

    stub("", meta={"ok": False, "reason": "模型返回空内容（可能 max_tokens 不足）",
                   "cached": False})
    res = m15_router.route("蓝牙耳机出口欧盟")
    check("模型空返回 → route_via 为「本地词典解析」（不是「混合」）",
          res.get("route_via") == "本地词典解析", res.get("route_via"))
    check("  note 告知 AI 不可用（不与 route_via 自相矛盾）",
          "AI服务暂不可用" in (res.get("note") or ""), repr(res.get("note")))
    check("  仍能出结果（降级可用）", res["ok"] is True)

    stub("", ready=False)
    res = m15_router.route("蓝牙耳机出口欧盟")
    check("链路未配置 → 照常走词典（PRD 验收用例 7）",
          res["ok"] is True and res.get("route_via") == "本地词典解析",
          f"ok={res['ok']} via={res.get('route_via')}")
    check("  note 说明未配置", "未配置" in (res.get("note") or ""),
          repr(res.get("note")))
    print()

    # ── 6. 渲染：模型回显的用户原文必须转义 ────────────────────
    print("【6】渲染安全：模型回显的用户原文进 gr.HTML 前必须转义")
    payload = '<img src=x onerror=alert(1)>'
    stub('{"品类":"儿童玩具","市场":"美国","用户品类":"玩具","用户市场":"美国",'
         '"命中依据":"' + payload.replace('"', '\\"') + '"}')
    res = m15_router.route("我要把玩具卖到美国")
    out = m15_router.render_parse(res)
    check("成功卡片里模型回显原文已转义（无裸 <img）",
          payload not in out and "&lt;img" in out,
          "未转义，存在注入面" if payload in out else "未见转义结果")
    print()

    unstub()

    # ── 7. llm.chat 硬超时机制（离线：桩 _call_api 睡眠）────────
    print("【7】llm.chat(timeout=…) 硬超时：慢模型及时降级，不干等")
    import time as _t
    _orig_api, _orig_ready_flag = llm._call_api, llm.READY
    # 形参必须与 core/llm._call_api() 一致（含 thinking）；否则 llm.chat 的
    # 超时分支会把 4 个位置参数传进来，模拟出的「超时」其实是 TypeError 假阳性。
    def _slow_api(prompt, max_tokens, temperature, thinking=True):
        _t.sleep(3)
        return '{"ok":true}'
    llm._call_api = _slow_api
    llm.READY = True
    t0 = _t.time()
    _, meta = llm.chat("任意提示词", timeout=1, use_cache=False)
    dt = _t.time() - t0
    llm._call_api, llm.READY = _orig_api, _orig_ready_flag
    check("慢模型（3s）+ timeout=1 → 1s 左右返回失败", meta["ok"] is False and dt < 2.2,
          f"dt={dt:.1f}s meta={meta}")
    check("  失败原因标注为超时", meta.get("timeout") is True, repr(meta.get("reason")))
    print()

    print("=" * 74)
    if FAIL:
        print(f"  结果：通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
        for name, detail in FAIL:
            print(f"    ❌ {name}  {detail}")
    else:
        print(f"  结果：全部通过（{len(PASS)} 项）")
    print("=" * 74)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())