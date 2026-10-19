# -*- coding: utf-8 -*-
"""Small, offline, evidence-linked journey for the Germany toy pilot.

The source registry records machine access, never human approval. The legacy
legal services remain responsible for other categories and markets. This module
does not make a legal clearance decision, submit documents, or call a model.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

SOURCE_PATH = Path(__file__).resolve().parents[1] / "data" / "journey_sources.json"
STAGES = (
    ("selection", "选品与销售准入", "先确认产品范围、经营角色和销售前提。"),
    ("business", "主体与税务准备", "整理主体资料，按库存与交易模式核验税务。"),
    ("testing", "检测、标识与资料", "让产品、技术资料、声明与标签相互对应。"),
    ("listing", "商品刊登与提交", "核对在线信息与平台实际提出的资料请求。"),
    ("fulfillment", "发货、清关与履约", "按实际履约与进口分工核验包装和运输。"),
    ("aftersales", "售后与账户风险", "准备消费者售后、事故处理与平台通知路径。"),
)


def load_sources() -> dict[str, Any]:
    """Read a fresh snapshot so callers cannot mutate another session's data."""
    with SOURCE_PATH.open(encoding="utf-8") as stream:
        data = json.load(stream)
    for source in data["sources"]:
        source["retrieved_on"] = data["retrieved_on"]
        source["review_status"] = data["review_status"]
        source["human_verified"] = False
    return data


def _text(value: Any) -> str:
    return str(value or "").strip().casefold()


def _electric(value: Any) -> bool | None:
    if value is True or value is False:
        return value
    value = _text(value)
    if value in {"yes", "true", "带电", "是", "有", "电动", "含电池"}:
        return True
    if value in {"no", "false", "不带电", "否", "无", "非电动", "无电池"}:
        return False
    return None


def _completed(context: dict) -> set[str]:
    values = context.get("completed") or []
    if isinstance(values, dict):
        return {str(key) for key, value in values.items() if value}
    if isinstance(values, (list, tuple, set)):
        return {str(value) for value in values}
    return set()


def query(context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return six navigable stages, scoped tasks, and source access gaps.

    ``market`` and ``country`` remain independent. Germany cannot be inferred
    from EU membership or an Amazon site. An explicit US market always excludes
    EU/Germany source material even if stale country/site fields are supplied.
    ``completed`` is a list of stable task IDs or an ID -> self-report mapping.
    """
    context = deepcopy(context or {})
    market, country = _text(context.get("market")), _text(context.get("country"))
    category, product = _text(context.get("category")), _text(context.get("product"))
    explicit_us = market in {"美国", "us", "usa", "united states"}
    european = not explicit_us and (market in {"欧盟", "eu", "european union", "德国", "de", "germany"} or (not market and country in {"德国", "de", "germany"}))
    german = european and country in {"德国", "de", "germany"}
    # A known conflicting category takes precedence over a word in free text.
    toy = category in {"儿童玩具", "玩具", "toy", "toys"} or (not category and any(word in product for word in ("玩具", "toy")))
    amazon = _text(context.get("platform")) in {"亚马逊", "amazon", "amazon.de", "亚马逊德国站"}
    german_site = _text(context.get("site")) in {"德国站", "德国", "amazon.de", "de", "germany", "亚马逊德国站"}
    pilot = toy and german and amazon and german_site
    conditions = context.get("conditions") if isinstance(context.get("conditions"), dict) else {}
    electric = _electric(conditions.get("electric", context.get("electric")))
    age = conditions.get("age", context.get("age"))
    fulfillment = _text(context.get("fulfillment"))
    fba = fulfillment in {"fba", "亚马逊配送", "亚马逊物流", "amazon fba"}
    fbm = fulfillment in {"fbm", "自发货", "自行发货", "卖家自配送"}
    completed = _completed(context)
    stages = [{"id": key, "title": title, "summary": summary, "status": "资料未覆盖", "tasks": [], "gaps": []} for key, title, summary in STAGES]
    by_stage = {stage["id"]: stage for stage in stages}
    try:
        registry = load_sources()
    except (OSError, ValueError, KeyError):
        gap = "主路线资料快照缺失或无法读取；原法规查询仍可使用，不能生成已核验的全流程结论。"
        for stage in stages:
            stage["gaps"] = [gap]
        return {"stages": stages, "sources": [], "gaps": [gap], "coverage": "资料快照不可用", "route_supported": False, "context": context, "version": "unavailable"}
    sources = {source["id"]: source for source in registry["sources"]}
    used: set[str] = set()

    def task(stage_id: str, task_id: str, title: str, kind: str, action: str,
             source_ids: list[str], *, criteria: list[str] | None = None,
             gaps: list[str] | None = None, conditional: bool = False,
             materials: list[str] | None = None, dependencies: list[str] | None = None) -> None:
        linked = [deepcopy(sources[source_id]) for source_id in source_ids]
        used.update(source_ids)
        is_done = task_id in completed
        status = "用户自述已完成" if is_done else "条件待确认" if conditional else "待准备"
        entry = {"id": task_id, "title": title, "kind": kind, "action": action,
                 "conditions": criteria or [], "sources": linked, "status": status,
                 "applicability_status": "条件待确认" if conditional else "路线范围内，具体适用待核验",
                 "evidence_status": "官方资料机器读取；未人工或专业核验", "human_verified": False,
                 "self_reported_complete": is_done, "gaps": list(gaps or []),
                 "materials": materials or [], "dependencies": dependencies or []}
        if is_done:
            entry["gaps"].append("这是用户自述记录，未核验材料有效性、完整性或平台审核结果。")
        by_stage[stage_id]["tasks"].append(entry)

    if toy and european:
        task("selection", "toy-scope", "确认玩具范围、年龄与经营角色", "法律要求／范围核验",
             "先记录产品用途、目标年龄、材质和供货关系，再对照官方玩具范围与制造商/进口商/经销商分工；年龄标签不能由模型代定。",
             ["eu-toys-guide"], criteria=["儿童玩具，进入欧盟市场"], conditional=not bool(age),
             gaps=["尚未复核具体产品是否属于玩具及法定年龄分组。"], materials=["产品描述与照片要点", "目标年龄", "材质与供货方角色"])
        task("selection", "toy-transition", "区分现行准备与新玩具法规过渡", "法律要求／时间核验",
             "2025/2509的一般适用日期是2030-08-01，部分条款已提前适用。当前不能据此把数字产品护照列为每款玩具的普遍上架前提，也不能将2009/48/EC全盘视为已废止。",
             ["eu-toys-transition"], gaps=["具体上市时点、过渡存货与提前适用条款需逐条复核。"])
        task("testing", "toy-safety-docs", "核对安全评估、技术资料与符合性声明", "法律要求",
             "按经营者角色整理安全评估、适当符合性评估、技术资料和EC符合性声明。已有检测报告要核对型号、材料、标准版本与覆盖范围；不将任何一份报告当作自动通过。",
             ["eu-toys-guide"], materials=["安全评估", "技术资料", "检测报告及适用范围", "EC符合性声明"], dependencies=["toy-scope"],
             gaps=["未确定该产品适用的具体协调标准，也未核验是否须公告机构参与。"])
        task("testing", "toy-labels", "核对CE、追溯信息、说明与警告", "法律要求",
             "对照实体玩具、包装和随附文件，核对CE标志、产品识别、经营者联系方式以及说明和安全警告；按德国适用语言要求复核文案。",
             ["eu-toys-guide"], materials=["产品和包装标签稿", "型号/批次信息", "说明书与警告稿"], dependencies=["toy-safety-docs"],
             gaps=["本资料没有给出该款玩具的完整德语警告模板或标识位置判断。"])
        if electric is not False:
            task("testing", "toy-electric-review", "确认带电情况并补核电气风险", "操作建议",
                 "带电玩具的安全评估需要关注电气风险；确认电源、电池、无线和充电功能后，再核验相关产品与运输规则。",
                 ["eu-toys-guide"], conditional=electric is None,
                 criteria=["仅在带电情况未知或用户说明带电时呈现"],
                 gaps=["本次未补齐电池、无线、电气、WEEE等分支的完整现行证据；不能据此自动判定登记或测试义务。"])
        task("listing", "eu-online-information", "核对在线商品信息与实体资料一致", "法律要求／条件核验",
             "若在线向欧盟消费者销售，对照GPSR Article 19核对制造商联系方式、产品识别与安全警告；制造商不在欧盟时还需核验欧盟责任人信息。",
             ["eu-gpsr"], criteria=["通过网络或其他远程方式向欧盟消费者提供产品", "责任人信息的分支取决于制造商所在地"],
             conditional=not amazon, materials=["商品图片与型号", "制造商联系方式", "适用责任人资料", "警告和安全信息"],
             gaps=["GPSR与玩具专项法的补充适用、制造商所在地和责任人身份尚未个案核验。"])
        task("aftersales", "consumer-aftersales", "准备消费者退货与质量问题处理", "法律要求／条件核验",
             "为面向消费者的远程销售准备撤回、退款和质量问题处理路径；官方说明中的通常14天撤回权与法定质量保障需结合例外和国家实施核验，不能套成每笔订单的同一倒计时。",
             ["eu-consumer-guarantees"], conditional=True, materials=["售后联系渠道", "退货说明", "退款与质量问题记录"],
             gaps=["未逐项收录德国实施、撤回例外、通知格式和时点；平台退货政策另行核验。"])
        task("aftersales", "product-safety-response", "建立安全事故记录与官方通知核验路径", "法律要求／条件核验",
             "如收到伤害或安全事故线索，保留产品、批次、事故经过和已知影响；对照GPSR Article 20按经营者角色核验Safety Business Gateway通知责任，并联系供应链责任方。",
             ["eu-gpsr"], conditional=True, materials=["批次与订单关联", "投诉/事故记录", "供应链联系信息"],
             gaps=["事故严重程度、主体角色、召回范围及具体处置须由实际责任方和专业人员核验；本项目不代发通知或申诉。"])

    if toy and german:
        task("fulfillment", "german-packaging", "核验包装生产者身份与LUCID准备", "法律要求／条件核验",
             "先按2026年制度确认包装供应链中的producer身份、包装类型及德国分支情况；有相应责任时再核对LUCID注册、授权代表、系统参与和数量申报。",
             ["de-packaging", "eu-packaging-dates"], conditional=True,
             materials=["包装种类与材料", "包装首次投放主体", "企业及德国分支情况", "已有LUCID/系统参与记录（自述）"],
             gaps=["2026-08-12为PPWR一般适用日，非所有包装条款的统一生效日；旧指南与当前角色必须复核。"])
        task("fulfillment", "customs-responsibility", "明确进口与报关分工后核验EORI", "操作建议／官方核验入口",
             "若从非欧盟发货，先与实际进口方/报关代理明确谁申报、谁承担进口责任，再打开德国海关EORI官方入口核验；本次仅取得官方搜索摘要。",
             ["de-eori"], conditional=True, materials=["发货地与库存地", "进口责任人与申报人", "报关代理及贸易安排"],
             gaps=["海关正文未取得；不推定EORI登记义务、税号、税则、税额或报关期限。"])

    if pilot:
        task("selection", "amazon-category-access", "核对德国站类目与产品合规请求", "平台规则／条件核验",
             "从Amazon德国站官方合规目录进入欧盟玩具帮助与合规控制面板，核对当前账户、品类和ASIN请求；创建账户或存在相同商品均不代表该产品已获准销售。",
             ["amazon-compliance"], conditional=True,
             gaps=["未取得玩具帮助页完整正文及真实账户请求，不能生成确定的审核通过结论。"])
        task("business", "amazon-account-docs", "按真实主体准备卖家核验资料", "平台规则",
             "按实际主体注册国家和主体类型，对照Amazon官方注册指南准备身份、地址、公司（适用时）与收款核验资料。仅记录准备状态，敏感原件在平台官方流程内提交。",
             ["amazon-registration"], materials=["主体注册地及类型", "身份/地址/公司材料准备状态", "收款资料准备状态"],
             gaps=["不推定中国企业必须设立德国本地主体；当前账户最终请求与核验结果未接入。"])
        task("business", "vat-model-review", "按库存与交易模式核验税务准备", "操作建议／税务核验",
             "先列主体注册地、库存国、发货地、进口责任人和消费者所在国，再沿官方平台VAT知识中心及其税务机关入口核验。选FBA或Amazon代收部分税款都不代表所有登记申报责任已解决。",
             ["amazon-vat", "de-vat-authority"], conditional=True, materials=["主体与库存国家", "销售链与进口责任分工", "现有税务登记状态（自述）"],
             gaps=["未核验个案税务义务；不提供税额、申报周期或确定登记期限。"])
        task("listing", "amazon-compliance-submission", "核对并响应真实商品合规资料请求", "平台规则／条件核验",
             "在德国站合规控制面板查看实际请求，将相同型号的产品信息、安全资料和适用联系人信息对应整理后，由卖家按平台请求提交。公开目录与GPSR法律条款分别显示，不冒充已取得全部平台字段。",
             ["amazon-compliance", "amazon-gpsr-help", "eu-gpsr"], conditional=True,
             dependencies=["toy-safety-docs", "toy-labels", "eu-online-information"],
             materials=["型号/ASIN与资料对应表", "平台实际请求（非敏感要点）", "适用经营者信息"],
             gaps=["责任人帮助页政策正文未取得，提交字段、报告要求和平台处理时限待合法登录核对。"])
        if fba:
            task("fulfillment", "amazon-fba-preparation", "按FBA路径核验入仓与库存安排", "操作建议／平台履约",
                 "FBA是先将库存送到Amazon履约中心，由其配送并处理相关客服与退货；先确认实际库存国家，再核验账户中的入仓、包装和受限运输请求。",
                 ["amazon-fulfillment"], criteria=["用户明确选择FBA"],
                 gaps=["本次未取得该款产品入仓标签、危险品及运输规则，不能据公开说明生成完整发货清单。"])
        elif fbm:
            task("fulfillment", "amazon-fbm-preparation", "按自行发货路径核验配送与售后", "操作建议／平台履约",
                 "自行发货由卖家安排库存和配送；确认发货地、承运安排和退货处理责任，再核对德国站当前配送模板与实际运输限制。",
                 ["amazon-fulfillment"], criteria=["用户明确选择自行发货"],
                 gaps=["未取得该账户配送时效、承运人及退货模板配置；不套用FBA入仓步骤。"])
        else:
            task("fulfillment", "choose-fulfillment", "确认由Amazon配送还是自己发货", "操作建议",
                 "FBA是先把货送到Amazon仓库，再由Amazon配送；自行发货由你安排发货。先选实际方式和库存国家，才能进一步核对发货与税务分支。",
                 ["amazon-fulfillment"], conditional=True,
                 gaps=["履约方式未知，未默认选择FBA；海关、运输和税务任务均未据此作确定判断。"])
        task("aftersales", "amazon-account-notices", "按真实平台通知核验账户与商品风险", "平台规则／操作建议",
             "留意德国站实际合规通知，将通知对应到产品、资料版本和供应链联系人；按官方合规与召回入口核对处理路径。公开指南提到不合规可能导致商品受限或失去销售资格，不能据此推断某账户必被停用。",
             ["amazon-compliance"], materials=["平台通知要点", "相关型号/ASIN", "提交资料与处理记录"],
             gaps=["没有接入店铺通知、申诉规则或账户审核，无法给出个案通过率、处罚预测或恢复承诺。"])

    global_gaps = ["本路线来自小规模官方资料快照，未经过人工法律/平台适用性核验，不代表已穷尽义务或可直接上架。"]
    if not toy:
        global_gaps.append("新增六阶段资料仅覆盖儿童玩具；当前品类请使用原法规查询、待办或跨市场能力，不能套用玩具任务。")
    if not european:
        global_gaps.append("当前市场不属于德国玩具路线；未返回欧盟、德国或德国站规则。请使用对应市场的原法规服务。")
    elif not german:
        global_gaps.append("目标市场为欧盟不等于德国；当前仅呈现可关联的欧盟玩具资料，未套用德国包装、海关或德国站平台资料。")
    elif not pilot:
        global_gaps.append("仅在确认亚马逊及德国站后才关联该平台资料；未选平台仍可查看法律资料。")
    for stage in stages:
        if not stage["tasks"]:
            stage["gaps"] = ["当前业务范围在本阶段没有已接入资料；可继续使用原功能查询，不能据空清单认为无义务。"]
        else:
            stage["status"] = "部分官方资料已获取；适用性待核验"
            stage["gaps"] = list(dict.fromkeys(gap for item in stage["tasks"] for gap in item["gaps"]))
    stage_index = {key: index for index, (key, _, _) in enumerate(STAGES)}
    preferred = _text(context.get("stage") or context.get("preparation"))
    focus = 5 if preferred in {"已销售", "运营中", "已上架"} else 2 if preferred in {"准备上架", "准备刊登"} else 0
    for stage in stages:
        for item in stage["tasks"]:
            item["group"] = "用户自述已完成" if item["self_reported_complete"] else "待确认" if item["status"] == "条件待确认" else "下一步" if stage_index[stage["id"]] <= focus else "后续事项"
    return {"stages": stages, "sources": [deepcopy(source) for source in registry["sources"] if source["id"] in used],
            "gaps": global_gaps, "coverage": "德国玩具×亚马逊德国站的六阶段最小资料集" if pilot else "主路线之外，仅保留有对应范围的资料与目录",
            "route_supported": pilot, "context": context, "version": registry["version"], "retrieved_on": registry["retrieved_on"],
            "review_status": registry["review_status"], "human_verified": False}
