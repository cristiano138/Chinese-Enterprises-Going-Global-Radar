# -*- coding: utf-8 -*-
"""
语音链路自检（scripts/selftest_voice.py）

覆盖三件事，全部离线可跑（不联网、不要求模型已下载）：
    A · core/asr.py      —— 降级行为、返回契约、归一化不越界
    B · modules/m15_router —— 词典路径 7 个用例 + ok⇒m1.ok 不变量 + 键集契约
    C · app_main.run_route_with_voice —— 2 元组契约、回填原文、坏音频降级

设计原则（与全项目一致）：
    断言的是「不会静默出错」，不是「识别得多准」。
    ASR 准确率取决于模型与口音，不能在 CI 里假装是确定值。

用法：
    python scripts/selftest_voice.py
退出码 0 = 全绿。
"""

import os
import sys
import tempfile

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)

from core import asr, corpus  # noqa: E402
from modules import m15_router  # noqa: E402

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}"
          + (f"　{detail}" if detail else ""))


def section(title):
    print()
    print(f"  ── {title} " + "─" * max(0, 56 - len(title)))


# ── A · ASR 层 ────────────────────────────────────────────────
def test_asr():
    section("A · core/asr.py")

    text, meta = asr.transcribe("C:/definitely/not/here.wav")
    check("文件不存在 → 空文本 + 明确原因（不抛异常）",
          text == "" and not meta["ok"] and bool(meta["reason"]),
          meta["reason"][:30])

    need = {"ok", "reason", "backend", "cached", "seconds", "lang"}
    check("返回字段固定 6 个", set(meta.keys()) == need, f"{len(meta)} 个")

    cases = [("  我要把毛绒玩具卖到德国。 ", "我要把毛绒玩具卖到德国"),
             ("嗯，蓝牙耳机出口欧盟，", "嗯，蓝牙耳机出口欧盟"),
             ("", "")]
    bad = [(r, asr.normalize(r)) for r, w in cases if asr.normalize(r) != w]
    check(f"{len(cases)} 条归一化用例", not bad, str(bad)[:60] if bad else "")

    # 归一化只去噪、不补全：不许凭空加类目词汇
    probe = asr.normalize("卖到那边")
    check("归一化不替用户补内容",
          "玩具" not in probe and "欧盟" not in probe and probe == "卖到那边",
          repr(probe))

    cfg = asr.config_summary()
    check("配置摘要不含密钥明文",
          "key" in cfg and cfg["key"] in ("已配置", "未配置"), cfg["detail"][:28])

    # 缓存：必须按后端隔离，否则切换 local/cloud 会复用另一套模型的结果，
    # 界面还会把旧结果标成新后端（违反「如实标注」）。
    import shutil
    old_dir = asr.CACHE_DIR
    tmp_dir = tempfile.mkdtemp(prefix="cr_asr_cache_")
    try:
        asr.CACHE_DIR = tmp_dir
        d = "0" * 64
        k_local = asr._cache_key("local", d)
        k_cloud = asr._cache_key("cloud", d)
        check("缓存键按后端隔离（local ≠ cloud）", k_local != k_cloud)
        asr._cache_put(k_local, "本地结果", "local")
        check("缓存写回后端名（命中时可如实标注）",
              asr._cache_get(k_local) == ("本地结果", "local"),
              str(asr._cache_get(k_local)))
        check("换后端不串味（另一个键查不到）", asr._cache_get(k_cloud) is None)
    finally:
        asr.CACHE_DIR = old_dir
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # 静音音频：后端可用则必须不炸；不可用则必须给出原因
    tmp = os.path.join(tempfile.gettempdir(), "cr_voice_selftest.wav")
    asr._write_silent_wav(tmp)
    t2, m2 = asr.transcribe(tmp)
    if m2["backend"]:
        check("后端可用时静音音频不抛异常", isinstance(t2, str),
              m2["reason"] or "转写成功")
    else:
        check("后端不可用时给出原因（不是静默失败）", bool(m2["reason"]),
              m2["reason"][:30])
    try:
        os.remove(tmp)
    except Exception:
        pass


# ── B · 路由层 ────────────────────────────────────────────────
def test_router():
    section("B · modules/m15_router.py")

    cases = [
        ("我要把洋娃娃卖到美国去", "儿童玩具", "美国", True, ""),
        ("蓝牙耳机出口欧盟", "电子电器", "欧盟", True, ""),
        ("食品级硅胶餐盒出口美国加州", "食品接触材料", "美国", True, ""),
        ("毛绒玩具发德国亚马逊", "儿童玩具", "欧盟", True, ""),
        ("童装卖到日本", None, None, False, "bad_market"),
        ("把钢材卖到美国", None, None, False, "bad_category"),
        ("帮我写一首诗", None, None, False, "no_slots"),
    ]
    bad = []
    for text, cat, mkt, want_ok, want_reason in cases:
        res = m15_router.route(text, use_llm=False)
        if want_ok:
            ok = res["ok"] and res["品类"] == cat and res["市场"] == mkt
        else:
            ok = (not res["ok"]) and res["reason"] == want_reason
        if not ok:
            bad.append(text)
    check(f"词典路径 {len(cases)} 个用例", not bad, str(bad)[:60] if bad else "")

    # 不变量：ok 为真 ⇒ m1.ok 为真（判定卡不能自相矛盾）
    bad = []
    for cat in corpus.ENTRY_CATEGORIES:
        for mkt in corpus.SUPPORTED_MARKETS:
            res = m15_router.route(f"{cat} 出口 {mkt}", use_llm=False)
            if not (res["ok"] and res["m1"]["ok"]):
                bad.append(f"{cat}×{mkt}")
    check(f"不变量 ok⇒m1.ok（{len(corpus.ENTRY_CATEGORIES)}×"
          f"{len(corpus.SUPPORTED_MARKETS)} 组）", not bad, str(bad)[:60])

    # 键集契约：所有分支同形，下游才不会 KeyError
    base = {"ok", "reason", "route_via", "note", "识别", "命中词",
            "missing", "m1", "品类", "市场"}
    probes = ["我要把洋娃娃卖到美国去", "童装卖到日本", "把钢材卖到美国",
              "我要卖玩具", "帮我写一首诗", ""]
    bad = [p for p in probes if set(m15_router.route(p, "", use_llm=False).keys()) != base]
    check(f"键集契约（{len(probes)} 个分支）", not bad, str(bad)[:60])

    # 拒绝文案要点名「你说了但不支持」的市场，不能糊成「你没说」
    res = m15_router.route("童装卖到日本", use_llm=False)
    hit = "日本" in m15_router.render_parse(res)
    check("bad_market 文案点名用户原话", hit)


# ── C · 界面回调契约 ──────────────────────────────────────────
def test_app_callback():
    section("C · app_main.run_route_with_voice")
    try:
        import app_main
    except Exception as e:  # noqa: BLE001
        check("app_main 可导入", False, f"{type(e).__name__}: {str(e)[:60]}")
        return
    check("app_main 可导入", True)

    html, filled = app_main.run_route_with_voice(
        None, "我要把毛绒玩具卖到德国", "")
    check("返回 2 元组（判定 HTML + 回填文本）",
          isinstance((html, filled), tuple) and isinstance(filled, str))
    check("成功时回填原文供用户确认", filled == "我要把毛绒玩具卖到德国")
    check("成功时渲染判定卡与官方原文",
          "判定卡" in html and "官方原文" in html)
    check("始终回显「听到了什么」", "听到" in html)
    check("文字输入标注为「文字输入」而非语音", "文字输入" in html)

    html2, _ = app_main.run_route_with_voice(None, "童装卖到日本", "")
    check("拒绝时给出可核验的拒绝理由（点名原话）", "日本" in html2)
    check("拒绝时不出法规清单", "判定卡" not in html2)

    html3, _ = app_main.run_route_with_voice(None, "", "")
    check("空输入不静默（有明确提示）", "请先说一句话" in html3)

    # 音频路径不存在时：必须降级成提示，而不是抛异常、也不能出结论
    html4, _ = app_main.run_route_with_voice("C:/not/a/real/audio.wav", "", "")
    check("坏音频不抛异常且不出结论",
          "没听清" in html4 and "判定卡" not in html4)


def main():
    print("=" * 66)
    print("  语音链路自检 · A 语音层 / B 路由层 / C 界面契约")
    print("=" * 66)
    test_asr()
    test_router()
    test_app_callback()

    print()
    print("=" * 66)
    total = len(PASS) + len(FAIL)
    if FAIL:
        print(f"  结果：通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
        for f in FAIL:
            print(f"    ❌ {f}")
    else:
        print(f"  结果：通过 {total} 项，失败 0 项")
    print("=" * 66)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
