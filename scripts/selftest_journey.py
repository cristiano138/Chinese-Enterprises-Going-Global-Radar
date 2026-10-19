# -*- coding: utf-8 -*-
"""Evidence scope, condition branches and self-report boundaries for the pilot."""
from copy import deepcopy
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.journey import load_sources, query


def tasks(result):
    return {task["id"]: task for stage in result["stages"] for task in stage["tasks"]}


def main():
    pilot = {"product": "积木玩具", "category": "儿童玩具", "market": "欧盟", "country": "德国", "platform": "亚马逊", "site": "德国站"}
    original = deepcopy(pilot)
    baseline = query(pilot)
    assert pilot == original
    assert baseline["route_supported"] and len(baseline["stages"]) == 6
    assert all(stage["tasks"] and stage["gaps"] for stage in baseline["stages"])
    assert all(item["sources"] and not item["human_verified"] for item in tasks(baseline).values())
    assert "choose-fulfillment" in tasks(baseline)
    assert "amazon-fba-preparation" not in tasks(baseline)
    assert "toy-electric-review" in tasks(baseline)
    non_electric = query({**pilot, "conditions": {"electric": False, "age": "3岁以上"}, "fulfillment": "自发货"})
    assert "toy-electric-review" not in tasks(non_electric)
    assert "amazon-fbm-preparation" in tasks(non_electric)
    assert "amazon-fba-preparation" not in tasks(non_electric)
    fba = query({**pilot, "fulfillment": "FBA"})
    assert "amazon-fba-preparation" in tasks(fba) and "choose-fulfillment" not in tasks(fba)
    done = query({**pilot, "completed": {"toy-safety-docs": True}})
    assert tasks(done)["toy-safety-docs"]["status"] == "用户自述已完成"
    assert not tasks(done)["toy-safety-docs"]["human_verified"]
    assert tasks(query(pilot))["toy-safety-docs"]["status"] == "待准备"
    for other in ({**pilot, "market": "美国"}, {**pilot, "category": "电子电器"}, {}):
        result = query(other)
        assert not result["route_supported"] and len(result["stages"]) == 6
        assert not result["sources"] and not tasks(result)
    eu_only = query({**pilot, "country": ""})
    assert not eu_only["route_supported"]
    assert all(source["jurisdiction"] == "欧盟" or source["jurisdiction"] == "欧盟消费交易" for source in eu_only["sources"])
    no_platform = query({**pilot, "platform": "", "site": ""})
    assert not no_platform["route_supported"]
    assert not any("amazon" in source["id"] for source in no_platform["sources"])
    for source in load_sources()["sources"]:
        assert source["url"].startswith("https://")
        assert source["retrieved_on"] == "2026-10-19"
        assert source["excerpt"] and source["locator"] and source["access_status"]
        assert not source["human_verified"]
    baseline["sources"][0]["human_verified"] = True
    assert not query(pilot)["sources"][0]["human_verified"]
    print("PASS: six stages; category/market/country/site filtering; electric and fulfillment branches; self-report isolation; source metadata")


if __name__ == "__main__":
    main()
