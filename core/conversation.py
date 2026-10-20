# -*- coding: utf-8 -*-
"""Session-only conversation service shared by text and button interactions.

This layer routes to the existing seven modules. It never creates legal rules,
persists a conversation, or treats a user's checkbox as an evidence review.
Module responses remain available in ``raw``; exports use that stored response,
never a fresh query. Gradio components belong in the UI, not in this module.
"""
from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import os
import re
import uuid
from datetime import date, datetime
from urllib.parse import urlsplit

from core import corpus, llm, snapshot
from modules import (m1_map, m2_timeline, m3_todo, m4_compare, m5_compare,
                     m6_multi_region, m7_opc_readiness, m15_router)


CAPABILITIES = [
    {"action": "map", "label": "查看相关法规", "description": "按产品和市场查看法规目录及来源。"},
    {"action": "todo", "label": "我现在需要做什么", "description": "整理准备事项、依据与待确认条件。"},
    {"action": "timeline", "label": "查看变化与关键日期", "description": "查看近 6 或 12 个月的记录和未来节点。"},
    {"action": "compare", "label": "比较两个市场", "description": "对照本地法规目录，保留各区域来源。"},
    {"action": "multi", "label": "一起查看多个市场", "description": "按欧盟、美国分别整理已有资料。"},
    {"action": "readiness", "label": "整理上线准备计划", "description": "按阶段、责任角色组织原有准备清单。"},
    {"action": "model", "label": "查看回答方法与来源差异", "description": "查看真实对照回放；没有样本时如实说明。"},
]
_TITLES = {item["action"]: item["label"] for item in CAPABILITIES}
_TITLES.update(journey="从选品到售后的行动路线", question="补充一个条件",
               capabilities="你可以这样使用合规雷达", message="已更新业务情况",
               unsupported="当前资料覆盖范围", error="本次查询未完成")
_CONTEXT_DEFAULTS = {
    "category": "", "product": "", "market": "", "country": "",
    "platform": "", "site": "", "fulfillment": "", "stage": "",
    "preparation": "", "age": "", "electric": None, "materials": "",
    "conditions": {}, "completed": {}, "reports": [], "markets": [],
    "window": "近 12 个月", "use_llm": False, "product_revision": 0,
    "presentation": "overview",
}
_FINGERPRINT_FIELDS = ("category", "product", "market", "country", "platform",
                       "site", "fulfillment", "stage", "preparation", "age",
                       "electric", "materials", "conditions", "reports",
                       "markets", "window", "product_revision")
_TASK_SCOPE_FIELDS = ("category", "product", "market", "country", "platform", "site",
                      "product_revision")
_BUSINESS_ACTIONS = set(_TITLES) - {"question", "message", "unsupported", "error", "capabilities"}
_NEW_PRODUCT_RE = re.compile(r"另一(?:个|款|种)?(?:产品|商品)|另一个(?:是|为)|换(?:一款|个|一种)(?:产品|商品)|新产品|产品改成")
_REPORT_RE = re.compile(r"(?:已经|已有|有了?|拿到|做过|完成).{0,8}(?:检测报告|测试报告|认证报告|标签稿|包装稿|技术文件|符合性声明|CE证书)")
_NEGATIVE_REPORT_RE = re.compile(r"(?:还没|没有|尚未|未做|没做|暂时没有).{0,8}(?:报告|标签|包装|文件|声明|证书)")
_EU_COUNTRIES = ("德国", "法国", "意大利", "西班牙", "荷兰", "波兰", "瑞典", "奥地利", "比利时", "爱尔兰", "葡萄牙")
_DESTINATION_WORDS = sorted(set(_EU_COUNTRIES + tuple(m15_router.OUT_OF_SCOPE_MARKET_WORDS)
                                + ("欧盟", "欧洲", "美国", "美区", "北美")), key=len, reverse=True)
_DESTINATION_PATTERN = "(?:" + "|".join(re.escape(word) for word in _DESTINATION_WORDS) + ")"
_STATUS_ZH = {"confirmed": "资料已关联，仍需核对适用条件", "evidence_pending": "证据待核验",
              "condition_pending": "条件待确认", "user_reported_done": "用户自述已完成",
              "historical": "历史资料", "excluded": "已隔离，未作为当前要求"}


def new_session():
    """Return fresh state; no mutable values are shared between sessions."""
    return {"version": 1, "id": uuid.uuid4().hex, "context": copy.deepcopy(_CONTEXT_DEFAULTS),
            "messages": [], "results": [], "active_result_id": None,
            "pending_action": None, "completion_by_scope": {}, "last_action": None}


def _state(state):
    result = copy.deepcopy(state) if isinstance(state, dict) else new_session()
    result.setdefault("id", uuid.uuid4().hex)
    result.setdefault("context", {})
    for key, value in _CONTEXT_DEFAULTS.items():
        result["context"].setdefault(key, copy.deepcopy(value))
    for key, value in (("messages", []), ("results", []), ("active_result_id", None),
                       ("pending_action", None), ("completion_by_scope", {}), ("last_action", None)):
        result.setdefault(key, copy.deepcopy(value))
    return result


def _json_default(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, set):
        return sorted(value)
    return str(value)


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    default=_json_default).encode("utf-8")).hexdigest()[:24]


def context_fingerprint(context):
    return _digest({key: context.get(key) for key in _FINGERPRINT_FIELDS})


def _task_scope(context):
    return _digest({key: context.get(key) for key in _TASK_SCOPE_FIELDS})


def context_summary(context):
    """A compact, editable-context label; it contains no inferred compliance result."""
    parts = [context.get("product") or context.get("category"),
             context.get("country") or context.get("market")]
    platform = context.get("platform", "")
    if platform:
        parts.append(platform + context.get("site", ""))
    parts.extend([context.get("fulfillment"), context.get("stage")])
    return " · ".join(str(part) for part in parts if part) or "尚未确认产品和市场"


def _actions(kind):
    related = {"map": ("todo", "timeline", "journey"), "todo": ("journey", "map", "readiness"),
               "timeline": ("todo", "map", "compare"), "compare": ("multi", "todo", "map"),
               "multi": ("compare", "todo", "readiness"), "readiness": ("journey", "todo", "map"),
               "model": ("map", "todo", "timeline"), "journey": ("todo", "map", "timeline")}
    return [{"label": _TITLES[action], "action": action}
            for action in related.get(kind, ("map", "todo", "journey"))]


def _result(kind, context, summary="", raw=None, **extra):
    result = {"id": uuid.uuid4().hex, "kind": kind, "title": _TITLES.get(kind, kind),
              "summary": summary, "context": copy.deepcopy(context),
              "context_fingerprint": context_fingerprint(context),
              "data_version": {"snapshot": snapshot.SNAPSHOT_VERSION, "cutoff": snapshot.DATA_CUTOFF,
                               "query_date": snapshot.now_bjt()},
              "items": [], "gaps": [], "raw": raw or {}, "actions": _actions(kind),
              "presentation": context.get("presentation", "overview")}
    result.update(extra)
    return result


def _record(state, result, replace=False):
    if replace:
        for index, existing in enumerate(state["results"]):
            if existing["id"] == result["id"]:
                state["results"][index] = result
                break
        else:
            state["results"].append(result)
    else:
        state["results"].append(result)
        state["messages"].append({"role": "assistant", "content": result["summary"],
                                  "result_id": result["id"]})
    state["active_result_id"] = result["id"]
    return state, result


def _active(state):
    return next((item for item in reversed(state["results"])
                 if item["id"] == state.get("active_result_id")), None)


def _question(state, action, summary, options=None):
    state["pending_action"] = action
    return _record(state, _result("question", state["context"], summary,
                                 options=options or [], actions=[]))


def _safe_url(url):
    try:
        parsed = urlsplit(str(url))
        if parsed.scheme in ("http", "https") and parsed.hostname and not parsed.username:
            return str(url)
    except (ValueError, TypeError):
        pass
    return ""


def _source(row):
    url = row.get("来源条款链接") or row.get("官方原文链接") or row.get("官方链接") or row.get("url")
    title = row.get("依据法规") or row.get("法规中文名") or row.get("title") or row.get("官方编号")
    excerpt = row.get("证据摘录") or row.get("excerpt") or ""
    if row.get("证据摘录"):
        excerpt = "语料中文摘要，非条文原文：" + str(excerpt)
    return {"title": str(title or "官方来源"), "url": _safe_url(url or ""),
            "excerpt": str(excerpt), "locator": row.get("locator") or row.get("官方编号") or "未收录条款定位",
            "status": row.get("核验状态") or row.get("status") or "条款与适用范围待核验"}


def _known_issue(row, context):
    """Quarantine demonstrable metadata mismatches; do not repair or sign off law."""
    blob = " ".join(str(row.get(key, "")) for key in
                    ("key", "CELEX号", "官方编号", "法规中文名", "依据法规", "官方标题（英文）", "官方英文标题"))
    category = context.get("category")
    if ("32023R1670" in blob or "2023/1670" in blob) and category != "电子电器":
        return "原始目录混入手机等产品生态设计法规；未取得适用于本产品的依据，已隔离。"
    if ("32011R1169" in blob or "2011/1169" in blob or "食品信息" in blob or "食品标签" in blob):
        return "该来源针对食品信息；当前支持的产品类目不等于食品，不能直接套用。"
    if ("31994L0011" in blob or "1994/11" in blob or "鞋类" in blob) and not any(
            word in context.get("product", "") for word in ("鞋", "靴")):
        return "该来源针对鞋类标签；未确认产品属于鞋类，已从当前义务中隔离。"
    return ""


def _is_historical(row):
    validity = str(row.get("现行效力") or row.get("是否仍有效") or row.get("状态") or "")
    identity = " ".join(str(row.get(key, "")) for key in ("key", "CELEX号", "官方编号", "依据法规"))
    return "已废止" in validity or "32001L0095" in identity or "Directive 2001/95" in identity


def _task_id(row, context):
    if row.get("action_id"):
        return row["action_id"]
    # OPC deliberately stores fewer fields than M3. Recover its original row
    # identity so recording the same action in either view shares the progress.
    official = row.get("官方编号")
    market = context.get("market", "")
    code = corpus.SUPPORTED_MARKETS.get(market, market)
    source = next((source for source in corpus.load_corpus()
                   if source.get("官方编号") == official and source.get("机构") == code), None)
    if source and row.get("动作类型"):
        identity = "|".join((source.get("机构", ""), source.get("类目", ""),
                              source.get("CELEX号") or official or "", row["动作类型"]))
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
    return _digest([kind for kind in (market, official, row.get("动作"), row.get("阶段"))])


def _item(row, context, kind="regulation", group="", index=0):
    original = copy.deepcopy(row.get("source_original", row))
    item_id = (_task_id(row, context) if kind == "task" else None) or row.get("id") or row.get("event_key") or _digest(
        [kind, group, row.get("key"), row.get("官方编号"), row.get("动作"), index])
    title = (row.get("动作") or row.get("title") or row.get("变化摘要") or row.get("法规中文名")
             or row.get("依据法规") or row.get("名称") or "来源记录")
    summary = (row.get("summary") or row.get("影响说明") or row.get("卖家提示")
               or row.get("类型含义") or row.get("官方编号") or "")
    gaps = []
    issue = _known_issue(row, context)
    validity = str(row.get("现行效力") or row.get("是否仍有效") or row.get("状态") or "")
    if issue:
        status, gaps = "excluded", [issue]
    elif _is_historical(row):
        status, gaps = "historical", ["历史资料，不将原义务直接作为当前执行事项；请核对替代规则。"]
    else:
        status = "condition_pending"
        gaps.append("已保留原始来源；条款适用范围、经营者身份和当前产品条件仍需核对。")
        if kind == "task":
            gaps.append("语料中文摘要不等于条文证据；下列事项作为准备与核验候选。")
    identity = str(row.get("key", "")) + str(row.get("官方编号", ""))
    if "32025R2509" in identity or "2025/2509" in identity:
        gaps.append("新条例Article 59规定一般自2030-08-01适用，部分条款自2026-01-01适用；Article 56规定2009年指令自2030-08-01废止。不能将新条例生效当作所有义务立即适用。")
    details = copy.deepcopy(row)
    details["original"] = original
    details["group"] = group
    details["证据说明"] = "来源目录及中文摘要；并非对当前产品逐条审核通过。"
    source = _source(row)
    if not source["url"]:
        status = "evidence_pending" if not issue else status
        gaps.append("当前条目缺少可打开的 HTTP(S) 来源链接。")
    completed = context.get("completed") or {}
    if kind == "task" and item_id in completed and status not in ("excluded", "historical"):
        status = "user_reported_done"
        details["completion"] = completed[item_id] if isinstance(completed, dict) else "用户自述已完成"
        gaps.append("完成仅为用户自述，未核验文件真实性、市场覆盖或平台接受情况。")
    return {"id": str(item_id), "title": str(title), "summary": str(summary), "kind": kind,
            "status": status, "status_label": _STATUS_ZH.get(status, status),
            "details": details, "sources": [source] if source["url"] else [], "gaps": gaps,
            "group": group, "can_complete": kind == "task" and status not in ("excluded", "historical")}


def _parse(text, context, use_model=False):
    """Extract only input fields. The model is never asked for legal conclusions."""
    destination_text = _affirmative_destinations(text)
    local = m15_router.parse_local(destination_text)
    if re.search(r"玩具|娃娃|玩偶|积木|毛绒|摇铃", text) and local.get("品类") != m15_router.OOS:
        # Batteries and wireless features describe a toy; they do not silently
        # turn it into a different product category when more feature words hit.
        local["品类"] = "儿童玩具"
    elif context.get("category") and not _NEW_PRODUCT_RE.search(text):
        hits = [word for word in m15_router.CATEGORY_WORDS.get(local.get("品类"), []) if word in text.lower()]
        if hits and set(hits) <= {"电池", "蓝牙", "电子", "电源", "遥控", "插头"}:
            local["品类"] = ""
    # Labels and warning-language requests describe an action, not a new product.
    if local.get("品类") in corpus.CROSS_CUTTING:
        local["品类"] = ""
    # A report/certification name is not confirmation of a sales destination.
    if local.get("市场") in corpus.SUPPORTED_MARKETS and not _market_mentions(text):
        local["市场"] = ""
    # Unsupported targets must not be hidden by a simultaneous supported mention.
    unsupported = [word for word in m15_router.OUT_OF_SCOPE_MARKET_WORDS if word.lower() in destination_text.lower()]
    if unsupported and re.search(r"(?:卖|销|市场|站|改|出口|发|比较|对比|和|与|及|到)", destination_text):
        local["市场"] = m15_router.OOS
        local["用户市场"] = "、".join(unsupported)
    meta = {"via": "本地词典", "model_used": False}
    # 规则没解析出品类/市场时，只要配置了模型就自动补位（可用 LLM_AUTO_FALLBACK=0 关闭）。
    # 这样"连衣裙卖到法国"这类词表没收录的新说法不会退化成反复追问同一句话。
    auto_model = os.getenv("LLM_AUTO_FALLBACK", "1").strip().lower() not in ("0", "false", "off", "no")
    needs_model = not local.get("品类") or not local.get("市场")
    if needs_model and llm.is_ready() and (use_model or auto_model) and len(destination_text.strip()) >= 4:
        try:
            slots, info = m15_router.parse_model(destination_text[:500], "")
            if slots is not None:
                for key, allowed in (("品类", corpus.ENTRY_CATEGORIES),
                                     ("市场", corpus.SUPPORTED_MARKETS)):
                    value = slots.get(key)
                    if not local.get(key) and (value in allowed or value == m15_router.OOS):
                        local[key] = value
                        meta.update(via="模型理解与本地词典", model_used=True)
                for key in ("用户品类", "用户市场"):
                    if not local.get(key):
                        local[key] = slots.get(key, "")
            else:
                meta["note"] = "模型理解暂不可用，已使用本地词典；可直接补充产品或市场。"
        except Exception:
            meta["note"] = "模型理解暂不可用，已使用本地词典；可直接补充产品或市场。"
    return local, meta


def _affirmative_destinations(text):
    """Discard explicitly rejected locations before collecting positive slots.

    This is deliberately confined to named destinations. Product negations such
    as '不带电' remain intact and keep their separate attribute parsing.
    """
    text = re.sub(r"(?:不是|不卖|不去|不发|不要|不做|不在|不销往|不出口|不销售|并非)"
                  r"\s*(?:到|去|往|向|在|卖到|卖|销往|出口到)?\s*(?:亚马逊|amazon)?\s*"
                  + _DESTINATION_PATTERN + r"(?:站)?", " ", text, flags=re.I)
    return re.sub(_DESTINATION_PATTERN + r"(?:站)?\s*(?:不卖了|不要了|不做了|不去了)", " ", text)


def _market_mentions(text):
    text = _affirmative_destinations(text)
    markets = []
    geographic = {"欧盟": ("欧盟", "欧洲", "eu市场") + _EU_COUNTRIES,
                  "美国": ("美国", "美区", "usa", "北美", "加州", "us市场")}
    for market, words in geographic.items():
        if any(word.lower() in text.lower() for word in words):
            markets.append(market)
    return markets


def _update_context(state, text, action, use_model=None):
    context = state["context"]
    active = _active(state)
    previous_scope = _task_scope(active["context"]) if active else _task_scope(context)
    enable_model = bool(context.get("use_llm")) if use_model is None else bool(use_model)
    slots, parse_meta = _parse(text, context, use_model=enable_model) if text else ({}, {})
    category = slots.get("品类", "")
    market = slots.get("市场", "")
    ui_product_change = bool(active and any(context.get(key) != active["context"].get(key)
                                           for key in ("category", "product")))
    new_product = ui_product_change or bool(_NEW_PRODUCT_RE.search(text)) or bool(
        category in corpus.ENTRY_CATEGORIES and context.get("category") and category != context["category"])
    if new_product:
        edited_category = context.get("category") if ui_product_change else ""
        edited_product = context.get("product") if ui_product_change else ""
        for key in ("age", "materials", "preparation", "stage"):
            context[key] = ""
        context.update(electric=None, conditions={}, reports=[], completed={}, product="", category="")
        if ui_product_change:
            context.update(category=edited_category, product=edited_product or edited_category)
        context["product_revision"] = int(context.get("product_revision") or 0) + 1
    if category:
        context["category"] = category
        if category == m15_router.OOS:
            context["product"] = slots.get("用户品类") or "当前产品（范围外）"
        elif not context.get("product") or new_product:
            hits = [word for word in m15_router.CATEGORY_WORDS.get(category, []) if word in text.lower()]
            context["product"] = max(hits, key=len) if hits else category
    destination_text = _affirmative_destinations(text)
    mentions = _market_mentions(destination_text)
    if len(mentions) > 1 and action in ("compare", "multi", "readiness"):
        context["markets"] = mentions
    elif market:
        if market != context.get("market"):
            context["country"], context["site"] = "", ""
            # An explicit market change must not silently carry Germany platform rules.
            if context.get("platform") == "亚马逊":
                context["site"] = ""
        context["market"] = market
        context["markets"] = [market] if market in corpus.SUPPORTED_MARKETS else []
    countries = [country for country in _EU_COUNTRIES if country in destination_text]
    if countries and market != m15_router.OOS and not (len(mentions) > 1 and action in ("compare", "multi")):
        country = countries[0] if len(countries) == 1 else ""
        if country != context.get("country"):
            context["site"] = ""
        context.update(market="欧盟", country=country)
        context["markets"] = ["欧盟"]
    elif market == "欧盟" and re.search(r"改|不是|不卖|换|只卖", text) and "德国" not in destination_text:
        context["country"], context["site"] = "", ""
    if re.search(r"(?:没|未|还没|尚未).{0,6}(?:选|定|确定)?平台|只看法规|纯法规", text):
        context["platform"], context["site"] = "", ""
    platform_pattern = r"(?:亚马逊|amazon|ebay|temu|tiktok|沃尔玛|独立站|速卖通)"
    platform_text = re.sub(r"(?:不是|不在|不做|不卖|不用|不选|不要)\s*(?:在)?\s*" + platform_pattern,
                           " ", text, flags=re.I)
    rejected_platform = platform_text != text
    if ("亚马逊" in platform_text or "amazon" in platform_text.lower()) and not re.search(
            r"(?:没|未|还没|尚未).{0,6}(?:选|定|确定)?平台|只看法规|纯法规", text):
        context["platform"] = "亚马逊"
        if context.get("country") == "德国":
            context["site"] = "德国站"
        elif context.get("market") == "美国":
            context["site"] = "美国站"
    elif any(word in platform_text.lower() for word in ("ebay", "temu", "tiktok", "沃尔玛", "独立站", "速卖通")):
        context["platform"] = next(word for word in ("ebay", "temu", "tiktok", "沃尔玛", "独立站", "速卖通")
                                   if word in platform_text.lower())
        context["site"] = ""
    elif rejected_platform:
        context["platform"], context["site"] = "", ""
    if "德国站" in destination_text and context.get("platform") == "亚马逊":
        context.update(market="欧盟", country="德国", site="德国站")
    if "美国站" in destination_text and context.get("platform") == "亚马逊":
        context.update(market="美国", country="", site="美国站")
    if "是否带电暂不确定" in text:
        context["electric"] = None
    elif re.search(r"(?:不|无|非|没有)带?电|不用电|无电池|不含电池", text):
        context["electric"] = False
    elif re.search(r"带电|电动|含电池|有电池|充电|电池供电|插电", text):
        context["electric"] = True
    age_match = re.search(r"(?:适合|面向|供)?\s*(\d{1,2}\s*(?:[-—至到~]\s*\d{1,2})?\s*岁(?:以下|以上)?)", text)
    if "年龄暂不确定" in text:
        context["age"] = ""
    elif age_match:
        context["age"] = age_match.group(1)
    elif "婴幼儿" in text:
        context["age"] = "婴幼儿（具体年龄未确认）"
    for material in ("毛绒", "塑料", "木制", "金属", "硅胶", "陶瓷", "棉", "玻璃"):
        if material in text:
            context["materials"] = material
            break
    if re.search(r"(?<![A-Za-z])fba(?![A-Za-z])|亚马逊(?:仓|配送)", text, re.I):
        context["fulfillment"] = "FBA"
    elif re.search(r"(?<![A-Za-z])fbm(?![A-Za-z])|自发货|自行发货|卖家自配送", text, re.I):
        context["fulfillment"] = "自发货"
    elif re.search(r"(?:未定|没定|没有确定|还没选).{0,4}(?:履约|发货)|履约.*(?:未定|没定|暂不确定)", text):
        context["fulfillment"] = ""
    phase_words = [("选品", "选品与销售准入"), ("打样", "检测、标识与资料"),
                   ("准备上架", "商品刊登与提交"), ("准备上线", "商品刊登与提交"),
                   ("已上架", "售后与账户风险"), ("已经上架", "售后与账户风险"),
                   ("准备发货", "发货、清关与履约"), ("清关", "发货、清关与履约"),
                   ("售后", "售后与账户风险")]
    for word, phase in phase_words:
        if word in text:
            context["stage"] = context["preparation"] = phase
            break
    report = _REPORT_RE.search(text)
    negative_report = _NEGATIVE_REPORT_RE.search(text)
    if negative_report:
        rejected = negative_report.group(0)
        topic = next((word for word in ("报告", "标签", "包装", "文件", "声明", "证书") if word in rejected), "")
        if topic:
            context["reports"] = [description for description in context["reports"] if topic not in description]
    elif report:
        description = report.group(0)
        if description not in context["reports"]:
            context["reports"].append(description)
    context["conditions"] = dict(context.get("conditions") or {}, age=context.get("age", ""),
                                  electric=context.get("electric"), materials=context.get("materials", ""))
    deferred = list(context["conditions"].get("deferred_questions") or [])
    for key, phrase in (("age", "年龄暂不确定"), ("electric", "是否带电暂不确定"),
                        ("fulfillment", "履约方式暂不确定")):
        if phrase in text and key not in deferred:
            deferred.append(key)
    context["conditions"]["deferred_questions"] = deferred
    if context.get("stage"):
        context["preparation"] = context["stage"]
    current_scope = _task_scope(context)
    if previous_scope != current_scope:
        if context.get("completed"):
            previous_completed = active["context"].get("completed", {}) if active else context["completed"]
            state["completion_by_scope"][previous_scope] = copy.deepcopy(previous_completed)
        context["completed"] = copy.deepcopy(state["completion_by_scope"].get(current_scope, {}))
    return slots, parse_meta, new_product


def _intent(text):
    if re.search(r"你(?:能|会|可以)做什么|全部功能|所有功能|更多功能|功能目录|能帮我什么", text):
        return "capabilities"
    if re.search(r"模型对照|模型比较|回答方法|可信|幻觉|为什么相信|来源差异", text):
        return "model"
    if re.search(r"对比|比较|差异|区别", text) and re.search(r"市场|区域|欧盟|德国|美国", text):
        return "compare"
    if re.search(r"多个市场|多区域|一起看|同时看|汇总", text):
        return "multi"
    if re.search(r"近期|最近|变化|修订|时间线|生效|适用日期|截止|关键日期|什么时候", text):
        return "timeline"
    if re.search(r"上线准备|上线计划|准备度|分工|负责人|责任角色|opc", text, re.I):
        return "readiness"
    if re.search(r"待办|下一步|做什么|怎么做|需要做|准备什么|准备哪些|缺什么|行动清单|材料清单", text):
        return "todo"
    if re.search(r"法规|法律|依据|准入|相关要求|哪些要求|什么要求|适用(?!年龄)|标签|标识|警告语", text):
        return "map"
    if re.search(r"全流程|全过程|从.*到|六个阶段|路线|开始做|怎么开始|如何开始|从哪(?:里)?开始", text):
        return "journey"
    return None


def _call(action, context):
    category, market = context["category"], context["market"]
    today = date.fromisoformat(snapshot.now_bjt())
    if action == "map":
        return m1_map.query(category, market, use_llm=False)
    if action == "todo":
        return m3_todo.query(category, market, use_llm=False, today=today)
    if action == "timeline":
        return m2_timeline.query(category, market, window=context.get("window", "近 12 个月"),
                                 use_llm=False, today=today)
    markets = context.get("markets") or ([market] if market else [])
    if action == "compare":
        if len(markets) < 2:
            markets = list(corpus.SUPPORTED_MARKETS)
        return m5_compare.query(category, markets=markets)
    if action == "multi":
        return m6_multi_region.query(category, markets=markets or list(corpus.SUPPORTED_MARKETS))
    if action == "readiness":
        return m7_opc_readiness.query(category, markets=markets or [market], today=today)
    if action == "model":
        return m4_compare.query(category, market)
    if action == "journey":
        from core import journey
        return journey.query(copy.deepcopy(context))
    raise ValueError("未知操作")


def _safety_policy(action, context, original):
    """Make known mismatches visible as quarantined data across every view.

    ``source_raw`` is the complete unmodified module response. ``raw`` otherwise
    represents the displayed/exported candidate set. No CSV audit status is
    changed, and historical dates remain available in the timeline.
    """
    raw = copy.deepcopy(original)
    # M3 把已废止法规单列在「历史关联」：模块层与 CLI 留档要用，但它不是
    # 当前候选集，会话视图与导出都不应带上（完整原响应仍在 source_raw）。
    raw.pop("历史关联", None)
    excluded = []
    corrected = []

    def clarify(row, execute=False):
        before = copy.deepcopy(row)
        identity = " ".join(str(row.get(key, "")) for key in ("key", "官方编号", "CELEX号"))
        if execute:
            # The old extractor assigns a task deadline from the next date in
            # metadata prose. It does not establish that this action is due then.
            row["期限"] = "待核验"
            row["期限说明"] = "原语料日期节点不等于本任务履行期限；需核对条款及产品适用条件。"
            row["紧迫度"] = "待核验"
            row["适用条件"] = str(row.get("适用条件", "")) + "；任务履行期限与紧迫度未核验，不能按原日期节点认定最晚截止。"
            corrected.append("未核验的日期节点没有作为任务最晚截止或紧迫度结论。")
        if "2025/2509" in identity or "32025R2509" in identity:
            row["法律时点说明"] = (
                "Article 59：一般自2030-08-01适用；Articles 28–44、49–55自2026-01-01适用。"
                "Article 56：2009/48/EC自2030-08-01废止；Article 57另含过渡情形。")
            row["日期核验来源"] = "https://eur-lex.europa.eu/eli/reg/2025/2509/oj/eng"
            if "生效日期" in row:
                row["生效日期"] = "具体法律时点见Article 59；不等于所有产品义务开始适用"
            if row.get("日期") == "2026-01-01":
                row["事件类型"] = "部分条款开始适用"
                row["变化摘要"] = "Article 59列明部分条款自2026-01-01适用；不是所有新产品义务的一般适用日期。"
            elif row.get("日期") == "2030-08-01":
                row["事件类型"] = "一般适用与旧指令废止"
                row["变化摘要"] = "新玩具法规一般自2030-08-01适用，2009/48/EC同日废止，仍需核对过渡条款。"
            corrected.append("玩具新法按官方Article 56、57、59区分一般适用、提前适用与旧法过渡。")
        if action == "timeline" and ("2025/40" in identity or "32025R0040" in identity):
            if row.get("日期") == "2026-08-12":
                row["事件类型"] = "一般适用日期（含例外）"
                row["变化摘要"] = "PPWR Article 71给出一般适用日期2026-08-12；具体条款仍有例外或过渡。"
            elif row.get("日期") and "2029-02-12" in str(row.get("日期")):
                row["事件类型"] = "原语料日期，含义待核验"
                row["官方确认"] = False
                row["变化摘要"] = "原语料列出2029-02-12，尚未关联支持当前行动的具体条款，不作为确定适用期限。"
            corrected.append("PPWR节点按已取得条款说明，未核验远期节点保留参考状态。")
        if row != before:
            row["source_original"] = before
        return row

    def clean(rows, row_context, execute=False):
        kept = []
        for index, row in enumerate(rows or []):
            issue = _known_issue(row, row_context)
            validity = str(row.get("现行效力") or row.get("是否仍有效") or row.get("状态") or "")
            if issue or (execute and _is_historical(row)):
                item = _item(row, row_context, kind="task" if execute else "regulation", index=index,
                             group="已隔离记录 · 保留原始来源")
                item["can_complete"] = False
                excluded.append(item)
            else:
                kept.append(clarify(row, execute=execute))
        return kept

    if action == "map":
        raw["primary"] = clean(raw.get("primary"), context)
        raw["cross"] = clean(raw.get("cross"), context)
        raw.setdefault("stats", {}).update(主体条数=len(raw["primary"]), 横切条数=len(raw["cross"]))
    elif action == "todo":
        raw["动作"] = clean(raw.get("动作"), context, execute=True)
        raw["未产出"] = clean(raw.get("未产出"), context)
        raw["分组"] = m3_todo.core_actions.group_by_type(raw["动作"])
        raw.setdefault("stats", {}).update(动作条数=len(raw["动作"]), 未产出条数=len(raw["未产出"]),
                                            涉及法规数=len({row.get("官方编号") for row in raw["动作"]}),
                                            紧迫度分布={"待核验": len(raw["动作"])})
    elif action == "timeline":
        for field in ("近窗内", "即将发生"):
            raw[field] = clean(raw.get(field), context)
        raw.setdefault("stats", {}).update(近窗内条数=len(raw["近窗内"]), 即将发生条数=len(raw["即将发生"]))
    elif action in ("compare", "multi"):
        for region in raw.get("区域", []):
            row_context = dict(context, market=region["市场"])
            field = "记录" if action == "compare" else "法规"
            region[field] = clean(region.get(field), row_context)
            region["原始数量"] = region.get("数量", region.get("条数", len(region[field])))
            region["数量" if action == "compare" else "条数"] = len(region[field])
        if action == "compare" and raw.get("区域"):
            sets = {region["市场"]: {row.get("官方编号") or row.get("CELEX号") for row in region["记录"]}
                    for region in raw["区域"]}
            shared = set.intersection(*sets.values()) if sets else set()
            raw["共同"] = [row for row in raw.get("共同", []) if row.get("key") in shared]
            raw["共同数量"] = len(raw["共同"])
            raw["独有"] = {region["市场"]: [row for row in region["记录"]
                if (row.get("官方编号") or row.get("CELEX号")) not in set().union(
                    *(keys for market, keys in sets.items() if market != region["市场"]))]
                for region in raw["区域"]}
        elif action == "multi":
            raw["总条数"] = sum(region["条数"] for region in raw.get("区域", []))
    elif action == "readiness":
        for region in raw.get("区域", []):
            row_context = dict(context, market=region["市场"])
            # Clean flattened tasks once, then use those identities for phases.
            region["动作"] = clean(region.get("动作"), row_context, execute=True)
            kept = {(row.get("官方编号"), row.get("动作")) for row in region["动作"]}
            for phase in region.get("阶段", []):
                phase["动作"] = [next(task for task in region["动作"]
                                     if (task.get("官方编号"), task.get("动作")) == (row.get("官方编号"), row.get("动作")))
                                 for row in phase.get("动作", []) if (row.get("官方编号"), row.get("动作")) in kept]
                phase["条数"] = len(phase["动作"])
            region["动作条数"] = len(region["动作"])
            region["高优先级"] = 0
            region["紧迫度说明"] = "原始紧迫度来自未核验日期抽取，已降为待核验；不据此制造优先级。"
        raw["总动作数"] = sum(region.get("动作条数", 0) for region in raw.get("区域", []))
        raw["高优先级数"] = 0
    if excluded or corrected:
        raw["source_raw"] = original
        raw["safety_notes"] = list(dict.fromkeys(
            ["已知目录误配和已废止执行项已隔离；未修改原语料核对状态。"] + corrected))
    return raw, excluded


def _journey_items(raw, context):
    items = []
    for stage in raw.get("stages", []):
        stage_sources = list(stage.get("sources") or [])
        tasks = []
        for original in stage.get("tasks", []):
            task = copy.deepcopy(original)
            task.setdefault("id", _digest([stage.get("id"), task.get("title")]))
            task.setdefault("title", task.get("action", "准备与核验事项"))
            task["information_type"] = original.get("kind", "资料核验")
            task["kind"] = "task"
            task["stage_id"], task["stage_title"] = stage.get("id", ""), stage.get("title", "")
            raw_status = task.get("status", "")
            task["status"] = {"用户自述已完成": "user_reported_done", "已核验": "confirmed",
                              "条件待确认": "condition_pending", "待专业核验": "evidence_pending",
                              "待准备": "condition_pending"}.get(raw_status, raw_status or "evidence_pending")
            if task["id"] in (context.get("completed") or {}):
                task["status"] = "user_reported_done"
            task["status_label"] = _STATUS_ZH.get(task["status"], task["status"])
            task["can_complete"] = task["status"] not in ("excluded", "historical")
            task.setdefault("summary", task.get("action", ""))
            task.setdefault("gaps", [])
            task["details"] = copy.deepcopy(original)
            task["details"].update(阶段=stage.get("title", ""), 期限="待核验", 紧迫度="待核验",
                                    期限说明="未据资料节点推定本任务的法定履行期限。",
                                    information_type=task["information_type"], stage_id=stage.get("id", ""))
            task["sources"] = [_source(source) for source in task.get("sources", [])]
            if task["status"] == "user_reported_done":
                task["gaps"].append("用户自述已完成，未验证材料真实性或平台接受状态。")
            tasks.append(task)
            stage_sources.extend(task["sources"])
        items.append({"id": stage.get("id") or _digest(stage.get("title")), "kind": "stage",
                      "title": stage.get("title", "业务阶段"), "summary": stage.get("summary", ""),
                      "status": stage.get("status", "evidence_pending"),
                      "details": dict(copy.deepcopy(stage), tasks=tasks),
                      "sources": [_source(source) for source in stage_sources],
                      "gaps": list(stage.get("gaps", [])), "can_complete": False})
    _plan_tasks([task for stage in items for task in stage["details"]["tasks"]], context)
    return items


def _focus_stage(context):
    """Map user preparation to navigation, not to presumed legal completion."""
    from core.journey import STAGES
    preferred = str(context.get("stage") or context.get("preparation") or "")
    for index, (stage_id, title, _) in enumerate(STAGES):
        if preferred in (stage_id, title):
            return index
    for pattern, index in ((r"已上架|已销售|运营中|售后", 5), (r"发货|清关|履约", 4),
                           (r"上架|刊登|提交", 3), (r"打样|测试|检测|认证|标识|资料", 2),
                           (r"主体|税务|注册", 1)):
        if re.search(pattern, preferred):
            return index
    return 0


def _plan_tasks(tasks, context):
    """Apply explicit dependencies and user stage without inventing deadlines."""
    from core.journey import STAGES
    order = {stage_id: index for index, (stage_id, _, _) in enumerate(STAGES)}
    focus = _focus_stage(context)
    completed = context.get("completed") or {}
    titles = {task["id"]: task["title"] for task in tasks}
    for task in tasks:
        details = task.setdefault("details", {})
        task_ids = {task["id"], *task.get("aliases", [])}
        done = any(task_id in completed for task_id in task_ids)
        original_status = details.get("status", "")
        stage_index = order.get(task.get("stage_id", details.get("stage_id", "selection")), 0)
        dependencies = list(details.get("dependencies") or task.get("dependencies") or [])
        blocked = [dependency for dependency in dependencies if dependency not in completed]
        details["blocked_by"] = [{"id": dependency, "title": titles.get(dependency, dependency)}
                                  for dependency in blocked]
        details["排序说明"] = "按你选择的准备阶段、显式前置事项与自述进度排序；不代表审核通过或法定截止。"
        if done:
            task["status"], task["status_label"] = "user_reported_done", _STATUS_ZH["user_reported_done"]
            group, reason = "用户自述已完成", "仅记录用户自述，仍保留适用性与证据核验缺口。"
        elif original_status == "条件待确认" or details.get("applicability_status") == "条件待确认":
            group, reason = "待确认", "存在尚未确认的业务条件或具体平台请求。"
        elif blocked:
            group, reason = "后续事项", "先核对前置事项：" + "、".join(titles.get(key, key) for key in blocked)
        elif stage_index == focus:
            group, reason = "下一步", "与你当前选择的准备阶段一致；先查看适用条件和来源。"
        elif stage_index < focus:
            group, reason = "待确认", "属于前序阶段，但没有自述完成记录；不会根据阶段自动认定已完成。"
        else:
            group, reason = "后续事项", "位于你选择阶段之后，保留后续入口，不制造当前截止。"
        task["group"] = group
        details["group"], details["分组原因"] = group, reason
    return tasks


def _pilot_todo(context, raw, legacy_items):
    """Reuse M3 and merge local evidence-backed journey tasks for the pilot."""
    if not (context.get("category") == "儿童玩具" and context.get("market") == "欧盟"
            and context.get("country") == "德国" and context.get("platform") == "亚马逊"
            and context.get("site") == "德国站"):
        return None
    from core import journey
    route = journey.query(copy.deepcopy(context))
    if not route.get("route_supported"):
        return None
    stage_items = _journey_items(route, context)
    tasks = [task for stage in stage_items for task in stage["details"]["tasks"]]
    by_id = {task["id"]: task for task in tasks}
    topic_map = {"32025R2509": "toy-transition", "32009L0048": "toy-safety-docs",
                 "32023R0988": "eu-online-information", "32025R0040": "german-packaging"}
    for legacy in legacy_items:
        record = legacy["details"]
        key = record.get("key") or (record.get("original") or {}).get("key")
        target = by_id.get(topic_map.get(key))
        if target is None:
            legacy.update(information_type="法律法规／原语料核验候选", stage_id="selection", stage_title="选品与销售准入")
            legacy["details"].update(stage_id="selection", 阶段="选品与销售准入")
            tasks.append(legacy)
            continue
        target.setdefault("aliases", []).append(legacy["id"])
        target["details"].setdefault("legacy_actions", []).append(copy.deepcopy(record))
        target["details"]["合并说明"] = "同一法规主题的原语料摘要已关联到这项具体核验行动；保留原信息与多类来源。"
        seen = {(source.get("url"), source.get("locator")) for source in target["sources"]}
        for source in legacy.get("sources", []):
            if (source.get("url"), source.get("locator")) not in seen:
                target["sources"].append(source)
                seen.add((source.get("url"), source.get("locator")))
    _plan_tasks(tasks, context)
    from core.journey import STAGES
    stage_order = {key: index for index, (key, _, _) in enumerate(STAGES)}
    group_order = {"下一步": 0, "后续事项": 1, "待确认": 2, "用户自述已完成": 3}
    tasks.sort(key=lambda task: (group_order.get(task.get("group"), 2),
                                  stage_order.get(task.get("stage_id"), 9), task["id"]))
    raw.setdefault("source_raw", copy.deepcopy(raw))
    raw["journey"] = route
    raw["动作"] = [_todo_action(task) for task in tasks]
    raw["分组"] = [(group, [row for row in raw["动作"] if row.get("会话分组") == group])
                   for group in group_order]
    raw.setdefault("stats", {}).update(动作条数=len(tasks), 路线阶段数=len(route["stages"]),
                                        紧迫度分布={"待核验": len(tasks)})
    stages = [dict(copy.deepcopy(stage), tasks=[task for task in tasks if task.get("stage_id") == stage["id"]])
              for stage in route["stages"]]
    return tasks, stages


def _todo_action(task):
    """Serialize an existing visible task; this does not derive a new obligation."""
    details = task.get("details", {})
    sources = task.get("sources", [])
    original = details.get("original", {})
    conditions = list(details.get("conditions") or [])
    if not conditions and details.get("适用条件"):
        conditions = [str(details["适用条件"])]
    conditions.extend(["信息类型：" + task.get("information_type", "准备候选"),
                       "阶段：" + task.get("stage_title", details.get("阶段", "待确认")),
                       "分组：" + task.get("group", "待确认"),
                       "适用与证据状态：" + task.get("status_label", "待核验")])
    conditions.extend(task.get("gaps", []))
    description = details.get("action") or task.get("summary") or ""
    return {"action_id": task["id"], "动作": task["title"], "行动说明": description,
            "动作类型": task.get("information_type", "合规确认"), "会话分组": task.get("group", "待确认"),
            "适用条件": "；".join(str(value) for value in conditions if value), "期限": "待核验",
            "紧迫度": "待核验", "官方编号": details.get("官方编号") or original.get("官方编号") or "未标注；按官方来源标题核验",
            "来源条款链接": "\n".join(dict.fromkeys(source["url"] for source in sources if source.get("url"))),
            "sources": copy.deepcopy(sources), "证据摘录": "\n".join(
                source.get("excerpt", "") for source in sources if source.get("excerpt")),
            "source_kind": "journey_and_local", "状态": task.get("status", "condition_pending")}


def _export_pilot_csv(raw):
    """Keep the original ten columns while correctly labeling official excerpts."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, quoting=csv.QUOTE_ALL)
    writer.writerow(m3_todo.CSV_COLUMNS)
    route = raw.get("journey", {})
    version_note = ("；目录快照：" + snapshot.SNAPSHOT_VERSION + "；路线资料版本：" + str(route.get("version", "未知"))
                    + "；官方资料获取日期：" + str(route.get("retrieved_on", "未知")) + "（不是政策生效日）")
    for row in raw.get("动作", []):
        source_text = "\n".join(
            "；".join(part for part in (source.get("title", ""), source.get("locator", ""),
                                        source.get("excerpt", ""), source.get("status", "")) if part)
            for source in row.get("sources", []))
        values = [raw.get("品类", ""), corpus.SUPPORTED_MARKETS.get(raw.get("市场"), raw.get("市场", "")),
                  row["动作"] + ("：" + row["行动说明"] if row.get("行动说明") else ""),
                  row.get("适用条件", "") + version_note, row.get("期限", "待核验"), row.get("官方编号", "未标注"),
                  source_text or "条款原文与定位待核验", row.get("来源条款链接", ""), snapshot.DATA_CUTOFF,
                  snapshot.DISCLAIMER]
        writer.writerow([m3_todo._csv_safe(value) for value in values])
    return m3_todo.csv_filename(raw.get("品类", ""), raw.get("市场", ""), raw.get("today")), \
        buffer.getvalue().encode("utf-8-sig")


def _normalize(action, context, raw):
    raw, excluded = _safety_policy(action, context, raw)
    result = _result(action, context, raw=raw, excluded=excluded)
    if raw.get("ok") is False:
        result.update(summary=raw.get("reason", "当前条件没有可用结果。"),
                      gaps=[raw.get("reason", "当前范围未覆盖")])
        return result
    items = []
    if action == "map":
        for field, group in (("primary", "产品法规候选"), ("cross", "关联法规，需核对适用条件")):
            items.extend(_item(row, context, group=group, index=i) for i, row in enumerate(raw.get(field, [])))
        result["summary"] = "已整理相关法规目录。点击条目查看原始信息与官方来源；目录命中不等于每条要求均适用。"
    elif action == "todo":
        items = [_item(row, context, kind="task", group=row.get("动作类型", "准备事项"), index=i)
                 for i, row in enumerate(raw.get("动作", []))]
        # 已废止法规由 M3 单列在「历史关联」：不生成动作，也不进当前待办视图
        # （契约见 selftest_conversation「known mismatches are quarantined」）。
        # 需要看历史来源时走「查看相关法规」，那里会以 historical 状态展示。
        result["summary"] = "先核对以下准备候选，再按适用条件执行。可以展开依据、记录自述进度或导出这份清单。"
        result["gaps"].extend(item.get("需确认", "") for item in raw.get("待确认", []))
        pilot = _pilot_todo(context, raw, items)
        if pilot:
            items, result["stages"] = pilot
            result["summary"] = "已把原法规候选与德国站六阶段行动合并。按你的准备阶段、前置事项和自述进度分组，展开任务查看法律、平台规则或操作建议及资料缺口。"
            result["gaps"].extend(raw["journey"].get("gaps", []))
    elif action == "timeline":
        for field, group in (("近窗内", "近窗内记录"), ("即将发生", "未来节点")):
            items.extend(_item(row, context, kind="event", group=group, index=i)
                         for i, row in enumerate(raw.get(field, [])))
        result["summary"] = (f"以下为{context.get('window', '近 12 个月')}已有记录与未来节点。"
                             "点击节点查看日期含义和出处；收录日期不代表生效日期。")
        if not items:
            result["summary"] = "当前时间窗没有可展示的变化记录。这不代表法规没有变化，可切换时间窗或查看官方原文。"
    elif action in ("compare", "multi"):
        for region in raw.get("区域", []):
            rows = region.get("记录", region.get("法规", []))
            region_items = [_item(row, dict(context, market=region["市场"]),
                                  group=region["市场"], index=i) for i, row in enumerate(rows)]
            items.append({"id": _digest([action, region["市场"]]), "title": region["市场"],
                          "summary": (f"本地目录 {len(rows)} 条；待核对 {region.get('待核对', 0)} 条。"
                                      "（" + snapshot.audit_note() + "）"),
                          "kind": "region", "status": "condition_pending", "sources": [],
                          "details": dict(copy.deepcopy(region), items=region_items), "gaps": [],
                          "can_complete": False})
        result["summary"] = ("这里比较的是本地法规目录及官方编号覆盖，不能据此判断哪个市场更容易，"
                             "也不把名称相似的法规视为等效。" if action == "compare"
                             else "已按市场整理资料，展开各区域查看来源与核验缺口；各地要求分别判断。")
        result["gaps"].append("目录对比尚未提供逐项实质要求的等效性比较。")
    elif action == "readiness":
        for region in raw.get("区域", []):
            for phase in region.get("阶段", []):
                for index, row in enumerate(phase.get("动作", [])):
                    items.append(_item(row, dict(context, market=region["市场"]), kind="task",
                                       group=region["市场"] + " · " + phase["名称"], index=index))
        result["summary"] = "已按阶段与责任角色整理原有上线准备计划。准备清单覆盖不代表商品已通过合规审核。"
        result["gaps"].append("责任角色与阶段属于执行组织建议；商品适用条件仍需逐项确认。")
    elif action == "model":
        replays = raw.get("回放列表") or []
        result["summary"] = ("以下为已保存的真实历史回放，可并列查看原答与证据记录；不预设比较结论。"
                             if replays else "尚未生成对照记录。保留真实回放入口，当前不提供模拟回答或胜负结论。")
        for index, replay in enumerate(replays):
            items.append({"id": _digest(["replay", index, replay.get("timestamp")]),
                          "title": "历史回放 " + str(replay.get("observation_date", replay.get("timestamp", index + 1))),
                          "summary": str(replay.get("verdict", "未记录核验结论")), "kind": "replay",
                          "status": "historical", "sources": [], "details": copy.deepcopy(replay),
                          "gaps": [], "can_complete": False})
        if not replays:
            result["gaps"].append("缺少同一题干、同一观察日期的真实模型原答及核验记录。")
    elif action == "journey":
        items = _journey_items(raw, context)
        result["stages"] = [dict(copy.deepcopy(stage), tasks=item["details"]["tasks"])
                            for stage, item in zip(raw.get("stages", []), items)]
        result["summary"] = raw.get("summary") or "点击六个阶段查看已有行动、资料来源和缺口。每个阶段可访问，不代表要求已穷尽。"
        result["gaps"].extend(raw.get("gaps", []))
    result["items"] = items
    if excluded:
        result["gaps"].append(f"已隔离 {len(excluded)} 条疑似类目误配记录；详情仍保留原始来源。")
    if context.get("reports"):
        result["gaps"].append("你提到已有资料：" + "、".join(context["reports"]) + "。仅记录自述，未验证有效性、目标市场覆盖或平台接受情况。")
    if action in ("todo", "journey", "readiness") and context.get("category") == "儿童玩具":
        if not context.get("age"):
            result["gaps"].append("适用年龄未确认；可直接回复年龄段，避免推定具体测试或警告要求。")
        if context.get("electric") is None:
            result["gaps"].append("是否带电未确认；未据此新增电气、无线或电池义务。")
    route = raw if action == "journey" else raw.get("journey", {})
    if route.get("version"):
        result["data_version"]["journey"] = route["version"]
        result["data_version"]["sources_retrieved_on"] = route.get("retrieved_on", "未知")
    return _action_guidance(result, context)


def _action_guidance(result, context):
    """Make existing tasks and one relevant unknown visible; never invent rules."""
    result["next_actions"], result["follow_up"] = [], []
    if (result.get("kind") not in ("todo", "journey", "readiness")
            or context.get("category") != "儿童玩具" or context.get("market") != "欧盟"):
        return result
    seen = set()
    for task in _all_tasks(result):
        details = task.get("details", {})
        if (task.get("id") in seen or task.get("group") != "下一步"
                or task.get("status") in ("user_reported_done", "excluded", "historical")
                or details.get("blocked_by") or not task.get("sources")):
            continue
        seen.add(task["id"])
        result["next_actions"].append({"task_id": task["id"], "title": task["title"],
            "reason": details.get("分组原因", "先核对适用条件与来源，再决定如何执行。"),
            "status": task.get("status"), "sources": copy.deepcopy(task["sources"])})
        if len(result["next_actions"]) == 3:
            break
    deferred = context.get("conditions", {}).get("deferred_questions", [])
    candidates = [
        ("age", not context.get("age"), "这款玩具面向哪个年龄段？可以按实际设计年龄直接填写。",
         [("3岁以上", "适用年龄3岁以上"), ("3岁以下", "适用年龄3岁以下"), ("暂不确定", "年龄暂不确定")]),
        ("electric", context.get("electric") is None, "这款玩具是否带电或含电池？这会影响需要进一步核对的分支。",
         [("不带电", "这款产品不带电"), ("带电或含电池", "这款产品带电"), ("暂不确定", "是否带电暂不确定")]),
        ("fulfillment", not context.get("fulfillment") and context.get("country") == "德国"
         and context.get("platform") == "亚马逊" and context.get("site") == "德国站",
         "计划怎样发货？FBA 是亚马逊仓储配送；自行发货由卖家安排履约。",
         [("亚马逊配送 FBA", "采用FBA发货"), ("自行发货", "采用自行发货"), ("暂不确定", "履约方式暂不确定")]),
    ]
    for key, needed, question, options in candidates:
        if needed and key not in deferred:
            result["follow_up"] = [{"field": key, "question": question,
                "options": [{"label": label, "text": text} for label, text in options],
                "note": "补充后更新当前结果；暂不确定也可继续查看已有资料。"}]
            break
    return result


def respond(text, state=None, action=None):
    """Return ``(new_state, structured_result)`` for both text and quick actions.

    ``action`` is one of map/todo/timeline/compare/multi/readiness/model/journey.
    ``capabilities`` displays the complete directory without executing queries.
    The caller may edit context fields before calling this function. All results
    snapshot their own context so historical cards cannot mutate a new product.
    """
    state = _state(state)
    text = str(text or "").strip()
    if len(text) > 6000:
        return _record(state, _result("error", state["context"],
                                      "这条消息超过6000字，请拆成几条补充。尚未执行查询或更改业务条件。",
                                      gaps=["未截断处理，避免丢失消息后半段的业务条件。"], actions=[]))
    if text:
        state["messages"].append({"role": "user", "content": text})
    intent = action or _intent(text)
    if intent == "capabilities":
        return _record(state, _result("capabilities", state["context"],
                                      "选择一项即可使用，也可以直接输入问题。已有条件会继续沿用。",
                                      actions=copy.deepcopy(CAPABILITIES)))
    if intent and intent not in _BUSINESS_ACTIONS:
        return _record(state, _result("error", state["context"], "未识别这个操作，可从更多功能选择。"))
    active = _active(state)
    export_requested = bool(re.search(r"导出|下载清单", text))
    parsed_context = None
    if not intent and active and re.fullmatch(r"(?:请)?(?:先简单说|简单说|列成表格|展开全部|只看下一步|展开|收起)[。！!]?", text):
        value = ("table" if "表格" in text else "all" if "全部" in text else
                 "next" if "下一步" in text else "overview")
        state["context"]["presentation"] = value
        active["presentation"] = value
        return _record(state, active, replace=True)
    if export_requested:
        parsed_context = _update_context(state, text, intent, use_model=False)
        if active and active.get("context_fingerprint") == context_fingerprint(state["context"]):
            if active.get("kind") in _BUSINESS_ACTIONS and (not intent or intent == active.get("kind")):
                active["export_requested"] = True
                active["export_result_id"] = active["id"]
                active["export_notice"] = "点击此结果下方的“导出当前结果”；使用当前条件与数据版本，保留来源和缺口。"
                return _record(state, active, replace=True)
        if not intent:
            return _question(state, "todo", "请先生成当前条件下的结果，再导出对应版本；也可以明确说要导出哪个市场的待办。")
    slots, parse_meta, new_product = parsed_context or _update_context(state, text, intent)
    context = state["context"]
    if context.get("category") == m15_router.OOS:
        return _record(state, _result("unsupported", context,
                                      f"当前产品“{context.get('product', '')}”不在本期五个品类范围。不会套用玩具或其他相近品类规则。",
                                      gaps=["支持：" + "、".join(corpus.ENTRY_CATEGORIES)]))
    if slots.get("市场") == m15_router.OOS or context.get("market") == m15_router.OOS:
        return _record(state, _result("unsupported", context,
                                      f"目标市场“{slots.get('用户市场') or '当前市场'}”暂无资料覆盖；目前保留欧盟、美国查询。",
                                      gaps=["未将德国、欧盟或美国要求套用于范围外市场。"], actions=[]))
    intent = intent or state.get("pending_action")
    if not intent and re.search(r"为什么|怎么理解|依据是什么|解释一下", text) and active:
        matching = next((item for item in active.get("items", [])
                         if any(str(word) in text for word in (item.get("id"), item.get("title")) if word)), None)
        if matching:
            answer = matching["title"] + "。" + "；".join(matching.get("gaps", []))
            return _record(state, _result("message", context, answer, items=[copy.deepcopy(matching)], actions=[]))
        return _question(state, None, "请点击要了解的条目“查看详情”，或输入条目名称；我会沿用这张结果的来源解释。")
    if not intent and re.search(r"我已经做过|这项完成|已经完成了|做完了", text):
        return _question(state, None, "请在对应任务卡片点击“记录自述完成”。这会记录进度，并保留证据待核验状态。")
    if not intent:
        if new_product or slots.get("品类") or slots.get("市场"):
            if active and not new_product and state.get("last_action"):
                intent = state["last_action"]
            else:
                intent = "journey" if (context.get("country") == "德国" and context.get("platform") == "亚马逊"
                                        and context.get("category") == "儿童玩具") else "map"
        elif active and context_fingerprint(context) != active.get("context_fingerprint"):
            intent = state.get("last_action") or "journey"
        else:
            return _question(state, None, "你现在想了解相关法规、整理下一步，还是查看全流程？可以直接说，也可以点下面的入口。",
                             options=[{"label": "相关法规", "action": "map"},
                                      {"label": "下一步", "action": "todo"},
                                      {"label": "全流程", "action": "journey"}])
    if intent == "model" and not context.get("category") and not context.get("market"):
        # M4 has its own honest fixed-question scope. Opening the entry is not
        # confirmation that this is the user's product or current sales market.
        result = _normalize("model", context, m4_compare.query())
        result["gaps"].append("模型对照的固定样本背景为儿童玩具×欧盟；未修改你的业务条件。")
        return _record(state, result)
    if not context.get("category"):
        return _question(state, intent, "你准备卖什么产品？例如毛绒玩具、蓝牙耳机或儿童服装。")
    if not context.get("market") and intent not in ("compare", "multi"):
        return _question(state, intent, "准备卖到哪个市场？目前支持欧盟、美国；德国可继续说明具体平台。",
                         options=[{"label": "德国", "text": "德国"}, {"label": "欧盟", "text": "欧盟"},
                                  {"label": "美国", "text": "美国"}])
    if not context.get("market") and intent in ("compare", "multi"):
        context["markets"] = list(corpus.SUPPORTED_MARKETS)
    if intent == "timeline":
        if re.search(r"6\s*个?月|六个月|半年", text):
            context["window"] = "近 6 个月"
        elif re.search(r"12\s*个?月|十二个月|一年", text):
            context["window"] = "近 12 个月"
    state["pending_action"] = None
    state["last_action"] = intent
    try:
        raw = _call(intent, context)
        result = _normalize(intent, context, raw)
    except Exception:
        # No stack traces, credentials, endpoints or business input in UI/errors.
        result = _result("error", context, "本次功能暂时没有完成。已保留业务条件，可以重试，或选择其他功能。",
                         gaps=["未生成新业务结论。"], actions=[{"label": "重试", "action": intent}])
    if parse_meta:
        result["understanding"] = parse_meta
        if parse_meta.get("note"):
            result["gaps"].append(parse_meta["note"])
    if export_requested and result.get("kind") in _BUSINESS_ACTIONS:
        result["export_requested"] = True
        result["export_result_id"] = result["id"]
    return _record(state, result)


def _find_result(state, result_id):
    return next((result for result in state.get("results", []) if result.get("id") == result_id), None)


def _all_tasks(result):
    for item in result.get("items", []):
        if item.get("kind") == "task":
            yield item
        for task in item.get("details", {}).get("tasks", []):
            yield task


def complete_task(state, result_id, item_id):
    """Toggle self-reported progress; stale results cannot edit current business."""
    state = _state(state)
    result = _find_result(state, result_id)
    if not result or state.get("active_result_id") != result_id:
        raise ValueError("这张结果已不是当前结果，请在当前结果中记录进度。")
    if result.get("context_fingerprint") != context_fingerprint(state["context"]):
        raise ValueError("业务条件已经变化，请重新查询后再记录进度。")
    item = next((task for task in _all_tasks(result) if task.get("id") == item_id), None)
    if not item or not item.get("can_complete", True) or item.get("status") in ("excluded", "historical"):
        raise ValueError("当前条目不能记录为执行完成；可查看其适用条件与资料缺口。")
    completed = state["context"].setdefault("completed", {})
    linked_ids = {item_id, *item.get("aliases", [])}
    for key, record in completed.items():
        if key in linked_ids and isinstance(record, dict):
            linked_ids.update(record.get("aliases") or [])
            linked_ids.add(record.get("canonical_id") or key)
    withdrawing = any(key in completed for key in linked_ids)
    completion = {"status": "用户自述已完成", "date": snapshot.now_bjt(),
                  "result_id": result_id, "evidence_verified": False,
                  "canonical_id": item_id, "aliases": sorted(linked_ids)}
    if withdrawing:
        for key in linked_ids:
            completed.pop(key, None)
    else:
        for key in linked_ids:
            completed[key] = copy.deepcopy(completion)
    state["completion_by_scope"][_task_scope(state["context"])] = copy.deepcopy(state["context"]["completed"])
    if not withdrawing:
        item.setdefault("details", {})["completion_previous_status"] = item["status"]
    item["status"] = (item.setdefault("details", {}).pop("completion_previous_status", "condition_pending")
                      if withdrawing else "user_reported_done")
    item["status_label"] = _STATUS_ZH[item["status"]]
    if withdrawing:
        item.setdefault("details", {}).pop("completion", None)
    else:
        item.setdefault("details", {})["completion"] = completion
    warning = "仅记录用户自述；材料有效性、目标市场覆盖和平台接受情况尚未核验。"
    if warning not in item.setdefault("gaps", []):
        item["gaps"].append(warning)
    result["context"]["completed"] = copy.deepcopy(state["context"]["completed"])
    for stage in result.get("stages", []):
        for task in stage.get("tasks", []):
            if task.get("id") == item_id:
                task.update(status=item["status"], status_label=item["status_label"])
    if result.get("kind") == "journey" or result.get("kind") == "todo" and result.get("raw", {}).get("journey"):
        tasks = list(_all_tasks(result))
        _plan_tasks(tasks, state["context"])
        by_id = {task["id"]: task for task in tasks}
        for stage in result.get("stages", []):
            for task in stage.get("tasks", []):
                planned = by_id.get(task.get("id"))
                if planned:
                    task.update(status=planned["status"], status_label=planned["status_label"], group=planned["group"],
                                details=copy.deepcopy(planned["details"]))
    if result.get("kind") == "todo" and result.get("raw", {}).get("journey"):
        result["raw"]["动作"] = [_todo_action(task) for task in result["items"]]
        result["raw"]["分组"] = [(group, [row for row in result["raw"]["动作"] if row.get("会话分组") == group])
                                 for group in ("下一步", "后续事项", "待确认", "用户自述已完成")]
    _action_guidance(result, state["context"])
    return _record(state, result, replace=True)


def export_result(state, result_id):
    """Export the active, matching result without rerunning any query.

    Original todo and OPC CSV formats are kept. Other views use JSON so no
    sources, snapshots, contexts, gaps or raw fields are truncated by the UI.
    """
    result = _find_result(state or {}, result_id)
    if not result or (state or {}).get("active_result_id") != result_id:
        raise ValueError("请选择当前结果导出。历史结果需先重新打开并确认条件。")
    if result.get("context_fingerprint") != context_fingerprint(state.get("context", {})):
        raise ValueError("业务条件已变化，不能静默导出旧结果。请先重新查询。")
    if result.get("kind") in ("question", "capabilities", "unsupported", "message", "error"):
        raise ValueError("当前回答没有可导出的业务结果。")
    raw = copy.deepcopy(result.get("raw", {}))
    # SPA 会话会经 JSON 往返，date 会变成 ISO 字符串；导出层仍要求 date。
    if isinstance(raw.get("today"), str):
        try:
            raw["today"] = date.fromisoformat(raw["today"][:10])
        except ValueError:
            raw.pop("today", None)
    tasks = list(_all_tasks(result))
    if result["kind"] == "todo":
        allowed = {task["id"]: task for task in tasks if task.get("status") not in ("excluded", "historical")}
        for action in raw.get("动作", []):
            task = allowed.get(action.get("action_id"))
            if task:
                status = _STATUS_ZH.get(task.get("status"), "条件待确认")
                action["适用条件"] = str(action.get("适用条件", "")) + "；会话状态：" + status
        if raw.get("journey"):
            raw["动作"] = [row for row in raw.get("动作", []) if row.get("action_id") in allowed]
            return _export_pilot_csv(raw)
        return m3_todo.export_csv(raw, selected_action_ids=list(allowed))
    if result["kind"] == "readiness":
        excluded = {(task["details"].get("官方编号"), task["details"].get("动作"))
                    for task in tasks if task.get("status") in ("excluded", "historical")}
        for region in raw.get("区域", []):
            region["动作"] = [row for row in region.get("动作", [])
                             if (row.get("官方编号"), row.get("动作")) not in excluded]
            for row in region["动作"]:
                task = next((task for task in tasks if task["details"].get("官方编号") == row.get("官方编号")
                             and task["details"].get("动作") == row.get("动作")), None)
                row["状态"] = _STATUS_ZH.get((task or {}).get("status"), "条件待确认")
        return m7_opc_readiness.export_csv(raw, today=date.fromisoformat(result["data_version"]["query_date"]))
    stamp = result["data_version"]["query_date"].replace("-", "")
    name = f"ComplianceRadar_{result['kind']}_{stamp}_{result_id[:8]}.json"
    return name, json.dumps(result, ensure_ascii=False, indent=2, default=_json_default).encode("utf-8")
