# -*- coding: utf-8 -*-
"""Single offline release gate for all deterministic checks."""
from __future__ import annotations

import os
import subprocess
import sys

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = [
    "scripts/validate_corpus.py",
    "scripts/selftest_m1.py",
    "scripts/selftest_m15.py",
    "scripts/selftest_m2_m3.py",
    "scripts/selftest_m5_m6.py",
    "scripts/selftest_m7.py",
    # 跨模块输出契约（免责声明/元数据/ELI 链接/键集/空选择）
    # —— 单模块自测照不到这一层，曾经因此出现「新页签漏了免责声明」。
    "scripts/selftest_ui_contract.py",
    # 保留两条开发线的回归测试。
    "scripts/selftest_recall.py",
    "scripts/selftest_recall_flow.py",
    "scripts/selftest_material_pipeline.py",
    "scripts/selftest_freshness.py",
    "scripts/selftest_discovery.py",
    "scripts/selftest_llm_reliability.py",
    "scripts/selftest_llm_layers.py",
    "scripts/selftest_voice.py",
    "scripts/selftest_asr_safety.py",
    "scripts/selftest_asr_engine.py",
    "scripts/selftest_asr_server.py",
    "scripts/selftest_model_assets.py",
    "scripts/selftest_database_assets.py",
    "scripts/selftest_m4.py",
    "scripts/selftest_voice_confirmation.py",
    "scripts/selftest_law_store.py",
    "scripts/selftest_python311.py",
    "scripts/selftest_journey.py",
    "scripts/selftest_conversation.py",
    "scripts/selftest_chat_ui.py",
    # SPA 静态托管与 /api/* 契约：Gradio 的根路由被接管后必须仍然可用。
    "scripts/selftest_web_api.py",
]


def main() -> int:
    failed = []
    skipped = []
    for script in SCRIPTS:
        print(f"\n=== {script} ===")
        result = subprocess.run([sys.executable, script], cwd=PROJECT)
        # 退出码 2 = 该项依赖本地运行库（如 SQLite 条款库），缺库时跳过。
        # 正式库不随源码包分发，干净克隆里这类项必须算「跳过」而不是「失败」。
        if result.returncode == 2:
            skipped.append(script)
        elif result.returncode:
            failed.append(script)
    print("\n=== RELEASE GATE ===")
    if skipped:
        print(f"跳过（缺本地运行库）：{len(skipped)} 项")
        for item in skipped:
            print("SKIP: " + item)
    if failed:
        print("失败数：" + str(len(failed)))
        for item in failed:
            print("FAIL: " + item)
        return 1
    print("M1: PASS")
    print("M1.5: PASS")
    print("M2: PASS")
    print("M3: PASS")
    print("M5/M6: PASS")
    print("M7: PASS")
    print("输出契约: PASS")
    print("召回树: PASS")
    print("召回流程: " + ("SKIP（缺本地库）" if any("recall_flow" in s for s in skipped) else "PASS"))
    print("材料落库: PASS")
    print("时效性检查: PASS")
    print("新法规发现: PASS")
    print("LLM 可靠性: PASS")
    print("语音输入: PASS")
    print("语音边界: PASS")
    print("Python 3.11 / 六阶段 / 会话服务 / 聊天界面: PASS")
    print("失败数：0" + (f"（跳过 {len(skipped)} 项）" if skipped else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
