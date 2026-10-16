# -*- coding: utf-8 -*-
"""M5/M6 多区域汇总与区域对比离线自测。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)

from modules import m5_compare, m6_multi_region  # noqa: E402
from core import corpus, verify  # noqa: E402


def check(name, condition, detail=""):
    if not condition:
        raise AssertionError(f"FAIL: {name} {detail}")
    print(f"PASS: {name}")


r6 = m6_multi_region.query("儿童玩具", ["欧盟", "美国"])
check("M6 查询成功", r6["ok"])
check("M6 返回两个区域", [x["市场"] for x in r6["区域"]] == ["欧盟", "美国"])
check("M6 区域法规数量正确", [x["条数"] for x in r6["区域"]] == [8, 19],
      [x["条数"] for x in r6["区域"]])
check("M6 所有输出记录均有官方链接",
      all(verify.accept(row)[0] for x in r6["区域"] for row in x["法规"]))

r5 = m5_compare.query("儿童玩具", ["欧盟", "美国"])
check("M5 查询成功", r5["ok"])
check("M5 共同编号可计算", r5["共同数量"] == len(r5["共同"]))
check("M5 区域集合完整", set(r5["独有"]) == {"欧盟", "美国"})
check("M5 共同编号确实存在于两区",
      all(x["key"] in {
          row.get("官方编号") or row.get("CELEX号")
          for z in r5["区域"] for row in z["记录"]
      } for x in r5["共同"]))
check("M5 范围外品类明确拒绝", not m5_compare.query("汽车配件", ["欧盟", "美国"])["ok"])
print("M5/M6: PASS")
