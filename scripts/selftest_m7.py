# -*- coding: utf-8 -*-
"""M7 OPC 上线准备度离线回归测试。"""
from __future__ import annotations

import os
import sys
from datetime import date

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)

from modules import m7_opc_readiness  # noqa: E402


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print("PASS: " + message)


result = m7_opc_readiness.query("儿童玩具", ["欧盟", "美国"], today=date(2026, 10, 17))
check(result["ok"], "M7 查询成功")
check(result["市场"] == ["欧盟", "美国"], "M7 返回两个区域")
check(len(result["区域"]) == 2, "M7 区域结果完整")
check(result["总动作数"] == sum(r["动作条数"] for r in result["区域"]), "M7 动作数量守恒")
check(all(phase["名称"] in m7_opc_readiness.PHASES for r in result["区域"] for phase in r["阶段"]), "M7 阶段值在允许范围")
check(all(item["责任角色"] for r in result["区域"] for item in r["动作"]), "M7 每项动作有责任角色")
check(all(item["官方链接"].startswith("http") for r in result["区域"] for item in r["动作"]), "M7 每项动作保留官方链接")
check(not m7_opc_readiness.query("汽车配件", ["欧盟"])["ok"], "M7 范围外品类明确拒绝")
print("M7: PASS")
