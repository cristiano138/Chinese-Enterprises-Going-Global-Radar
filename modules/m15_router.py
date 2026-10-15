# -*- coding: utf-8 -*-
"""
M1.5 · 输入驱动路由层（modules/m15_router.py）

一句话：卖家用大白话描述业务（例：「我要把洋娃娃卖到美国去」）→
        自动识别「品类 × 市场」→ 复用 M1 确定性查表 → 输出针对这单的「判定卡」。

产品定位（写给团队 / 评委）：
    不做「合规聊天机器人」。模型只负责**理解输入**（归类路由），
    法规结论 100% 来自本地核对语料表 + 官方链接，模型无权新增 / 改写 / 编造。
    这是「公开规则 × 企业真实业务」之间的那一层：
    —— 判定这一单受哪些法规影响、还缺什么资料、依据是什么。

两级解析（降级设计，演示永不中断）：
    ① 模型解析（模型链路可用时）：从自然语言抽「品类 / 市场」槽位（严格 JSON）
    ② 本地词典解析（零依赖兜底）：关键词匹配，纯确定性代码，永不失败
    任一级失败自动落到下一级；两级都失败 → 诚实拒绝，不硬编答案。

隐私边界（企业数据治理最小演示）：
    · 输入原文只在内存中处理；路由调用禁用 LLM 磁盘缓存（原文不落盘）
    · 判定只依赖「品类 + 市场」两个槽位；企业上下文仅辅助识别，不存储
    · 页面固定提示：请勿输入个人隐私与客户敏感信息

用法：
    from modules import m15_router
    res = m15_router.route("我要把洋娃娃卖到美国去，要做哪些合规工作")
    自检：python modules/m15_router.py
"""

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)

from core import corpus, llm  # noqa: E402
from modules import m1_map  # noqa: E402

# ── 本地词典（兜底解析，确定性代码）──────────────────────────────────
# 命中即计数，取命中最多的类目 / 市场；全部落空 → 诚实拒绝。
MARKET_WORDS = {
    "欧盟": ["欧盟", "欧洲", "ce标志", "ce认证", "德国", "法国", "意大利",
             "西班牙", "荷兰", "波兰", "瑞典", "eur-lex", "en71", "en 71"],
    "美国": ["美国", "美区", "usa", "北美", "fda", "cpsc", "ca65", "加州65",
             "亚马逊美国", "ecfr", "cpc证书"],
}

# 注意：「儿童 / 小孩 / 幼儿」是人群修饰词不算品类信号；
#       「儿童服装」→ 纺织服装（纺织优先规则见 _best）。
CATEGORY_WORDS = {
    "儿童玩具": ["玩具", "娃娃", "玩偶", "洋娃娃", "积木", "毛绒", "童车",
                 "滑板车", "摇铃", "弹珠", "益智"],
    "电子电器": ["电子", "电器", "充电器", "插头", "电池", "蓝牙", "耳机",
                 "音箱", "家电", "台灯", "灯具", "照明", "适配器", "电源",
                 "遥控", "智能手表"],
    "纺织服装": ["纺织", "服装", "衣服", "面料", "童装", "袜子", "毛巾",
                 "围巾", "帽子", "手套", "床上用品", "窗帘", "鞋子", "鞋"],
    "美妆个护": ["美妆", "化妆品", "护肤", "面膜", "口红", "洗发", "沐浴",
                 "香水", "指甲油", "防晒", "牙膏"],
    "食品接触材料": ["食品接触", "餐具", "餐盒", "饭盒", "水杯", "保温杯",
                    "杯子", "奶嘴", "厨具", "炊具", "砧板"],
    "标签标识": ["标签", "标识", "说明书", "警告语", "成分表", "吊牌"],
    "通用": ["gpsr", "一般产品安全", "通用安全"],
}

# 「缺什么资料」清单 —— 按品类给出判定还差的关键信息。
# 这是 M3 待办清单的「输入侧」接口：M3 上线后把缺失资料映射到
# 「动作 → 条款 → 链接」即可（本期不强求）。
MISSING_INFO = {
    "儿童玩具": [
        "适用年龄段（是否供 3 岁以下儿童使用 —— 影响小零件 / 绳索等要求）",
        "材质与结构（是否含电池、磁铁、化学品；是否存在小零件）",
        "已有测试报告（欧盟 EN 71 / 美国 ASTM F963）",
        "标签与包装稿（警告语、追溯信息）",
    ],
    "电子电器": [
        "供电方式（电池 / 插电 —— 决定适用法规）",
        "是否带无线模块（蓝牙 / WiFi 会触发无线电相关要求）",
        "已有认证（CE / FCC / UL 报告）",
        "额定电压与插头类型",
    ],
    "纺织服装": [
        "纤维成分表",
        "目标人群（成人 / 婴幼儿 —— 婴幼儿有专属要求）",
        "标签稿（成分、洗护、原产国）",
        "是否做功能性宣称（防水 / 抗菌等）",
    ],
    "美妆个护": [
        "产品类别与功效宣称",
        "全成分表（INCI）",
        "是否面向儿童等特殊人群",
        "已有注册 / 备案信息",
    ],
    "食品接触材料": [
        "材质类型（塑料 / 金属 / 陶瓷 / 硅胶）",
        "接触食品类型（水性 / 酸性 / 油脂）与使用温度",
        "已有迁移测试报告",
    ],
    "标签标识": [
        "具体产品品类",
        "标签稿全文",
        "销售渠道（线上 / 线下）",
    ],
    "通用": [
        "具体产品品类与描述",
        "销售市场与渠道",
    ],
}

PARSE_PROMPT = """你是跨境电商合规查询系统的路由器。从用户输入中抽取两个字段，输出严格的 JSON，不要输出任何其他文字：
{{"品类": "", "市场": "", "命中依据": "用户原话中的关键短语"}}

品类只能取以下之一：儿童玩具 / 电子电器 / 纺织服装 / 美妆个护 / 食品接触材料 / 标签标识 / 通用
市场只能取以下之一：欧盟 / 美国
判断不出来就填空字符串，不要猜。

用户输入：{text}
补充上下文：{context}"""


def parse_local(text, context=""):
    """本地词典解析（确定性）。返回 {品类, 市场, 命中词}，识别不出为空串。"""
    blob = f"{text or ''} {context or ''}".lower()

    def _best(words):
        hits = {}
        for label, ws in words.items():
            matched = [w for w in ws if w in blob]
            if matched:
                hits[label] = matched
        if not hits:
            return "", []
        # 「儿童服装」类输入不应误归玩具 —— 纺织与玩具同分时归纺织
        if "纺织服装" in hits and "儿童玩具" in hits:
            return "纺织服装", hits["纺织服装"]
        label = max(hits, key=lambda k: len(hits[k]))
        return label, hits[label]

    market, m_hits = _best(MARKET_WORDS)
    category, c_hits = _best(CATEGORY_WORDS)
    return {"品类": category, "市场": market, "命中词": m_hits + c_hits}


def parse_model(text, context=""):
    """模型解析：从自然语言抽槽位。

    返回 ({品类, 市场, 命中依据}, meta)；失败返回 (None, meta)。
    注意 use_cache=False：路由提示词含用户原文，**禁止落盘缓存**（隐私边界）。
    """
    prompt = PARSE_PROMPT.format(text=(text or "")[:500],
                                 context=(context or "")[:500] or "（无）")
    out, meta = llm.chat(prompt, max_tokens=300, temperature=0, use_cache=False)
    if not meta.get("ok"):
        return None, meta
    m = re.search(r"\{.*\}", out, re.S)
    if not m:
        return None, {"ok": False, "reason": "模型输出中未找到 JSON", "cached": False}
    try:
        data = json.loads(m.group(0))
    except Exception:
        return None, {"ok": False, "reason": "模型 JSON 解析失败", "cached": False}
    return {"品类": str(data.get("品类") or "").strip(),
            "市场": str(data.get("市场") or "").strip(),
            "命中依据": str(data.get("命中依据") or "").strip()}, meta


def route(text, context="", use_llm=True):
    """M1.5 主入口：理解输入 → 路由到确定性查表。

    返回 dict：
        ok        —— 是否识别成功并出清单（False = 诚实拒绝）
        reason    —— 拒绝原因（empty / no_slots / bad_category / bad_market / partial_*）
        识别      —— 识别过程回显（不给用户看原文，只给槽位与依据）
        route_via —— 模型解析 / 本地词典解析 / 混合（模型 + 词典）
        品类 / 市场 —— 识别结果
        命中词    —— 词典命中的关键词（可追溯：为什么这么路由）
        missing   —— 「缺什么资料」清单（衔接 M3 待办）
        m1        —— M1 查表结果（use_llm=False：路由层不再叠加润色调用，省额度）
    """
    text = (text or "").strip()
    context = (context or "").strip()

    if not text and not context:
        return {"ok": False, "reason": "empty", "route_via": "", "note": "",
                "识别": {}, "命中词": [], "missing": [], "m1": None}

    # ── ① 模型解析（可选）────────────────────────────────────
    note = ""
    model_slots = None
    if use_llm:
        if llm.is_ready():
            model_slots, meta = parse_model(text, context)
            if model_slots is None:
                note = f"模型解析不可用（{meta.get('reason', '')}），已用本地词典兜底。"
        else:
            note = "模型链路未配置 —— 使用本地词典解析（确定性、零依赖、不联网）。"

    # ── ② 词典解析 + 槽位合并 ────────────────────────────────
    local = parse_local(text, context)
    cat = model_slots["品类"] if model_slots else ""
    mkt = model_slots["市场"] if model_slots else ""
    basis = model_slots["命中依据"] if model_slots else ""
    src_cat = "模型" if cat else ""
    src_mkt = "模型" if mkt else ""
    if not cat and local["品类"]:
        cat, src_cat = local["品类"], "词典"
    if not mkt and local["市场"]:
        mkt, src_mkt = local["市场"], "词典"
    if src_cat == "模型" and src_mkt == "模型":
        via = "模型解析"
    elif src_cat == "词典" and src_mkt == "词典" or (not src_cat and not src_mkt):
        via = "本地词典解析"
    else:
        via = "混合（模型 + 词典）"

    ident = {"品类": cat, "市场": mkt, "命中依据": basis,
             "命中词": local["命中词"]}

    # ── ③ 校验：识别结果必须落在支持范围内，否则诚实拒绝 ─────
    if not cat and not mkt:
        return {"ok": False, "reason": "no_slots", "route_via": via,
                "note": note, "识别": ident, "命中词": local["命中词"],
                "missing": [], "m1": None}
    if cat and cat not in corpus.ALL_QUERYABLE:
        return {"ok": False, "reason": "bad_category", "route_via": via,
                "note": note, "识别": ident, "命中词": local["命中词"],
                "missing": [], "m1": None}
    if mkt and mkt not in corpus.SUPPORTED_MARKETS:
        return {"ok": False, "reason": "bad_market", "route_via": via,
                "note": note, "识别": ident, "命中词": local["命中词"],
                "missing": [], "m1": None}
    if not cat or not mkt:
        side = "品类" if not cat else "市场"
        return {"ok": False, "reason": f"partial_{side}", "route_via": via,
                "note": note, "识别": ident, "命中词": local["命中词"],
                "missing": [], "m1": None}

    # ── ④ 路由到确定性查表（红线不变：结论全部来自核对语料）──
    m1 = m1_map.query(cat, mkt, use_llm=False)
    return {"ok": True, "reason": "", "品类": cat, "市场": mkt,
            "route_via": via, "note": note,
            "命中词": local["命中词"] or ([basis] if basis else []),
            "missing": MISSING_INFO.get(cat, []), "m1": m1}


def render_parse(res):
    """把路由结果渲染成「判定卡」头部 HTML（法规清单部分由 app.py 复用 M1 渲染）。"""
    if not res.get("ok"):
        r = res.get("reason", "")
        ident = res.get("识别") or {}
        if r == "empty":
            msg = "请先在左侧输入业务描述（例如：我要把儿童玩具卖到欧盟）。"
        elif r == "bad_market":
            msg = (f"识别到目标市场「{ident.get('市场', '')}」—— 本期仅覆盖 "
                   f"{'、'.join(corpus.SUPPORTED_MARKETS.keys())}，"
                   f"其他市场不做硬编答案。")
        elif r == "bad_category":
            msg = (f"识别到品类「{ident.get('品类', '')}」—— "
                   f"不在本期语料覆盖范围内。")
        elif r.startswith("partial_"):
            miss = "目标市场" if r.endswith("市场") else "产品品类"
            msg = (f"识别不完整：没从输入里确认出{miss}。请补充说明，"
                   f"或改用「M1 合规地图」页签下拉选择。")
        else:
            msg = ("没从输入里识别出「品类 × 市场」。请用一句更明确的话描述"
                   "（例：我要把毛绒玩具卖到德国），或改用「M1 合规地图」页签下拉选择。")
        extra = ""
        if ident.get("命中依据"):
            extra = (f'<div class="cr-row"><span class="cr-k">识别依据</span>'
                     f'{ident["命中依据"]}</div>')
        return (
            '<div class="cr-wrap"><div class="cr-err">'
            '<b>M1.5 智能路由 · 无法完成判定</b><br>'
            f'{msg}<br>{extra}<br>'
            '<b>支持的市场：</b>' + "、".join(corpus.SUPPORTED_MARKETS.keys()) +
            '<br><b>支持的品类：</b>' + "、".join(corpus.ALL_QUERYABLE) +
            '<br><span style="color:#6b7280">范围外的问题不做硬编答案 —— '
            '这是本工具与通用聊天机器人的根本区别。</span>'
            '</div></div>'
        )

    via = res.get("route_via", "")
    hits = res.get("命中词") or []
    hit_html = (" ".join(f"<code>{h}</code>" for h in hits)
                if hits else "（无关键词命中，按语义识别）")
    note = res.get("note") or ""
    note_html = f'<div class="cr-note">ℹ️ {note}</div>' if note else ""
    missing_items = "".join(f"<li>{m}</li>" for m in res.get("missing", []))
    return (
        '<div class="cr-wrap">'
        f'<div class="cr-head"><b>M1.5 智能路由 · 判定卡</b>　'
        f'{res["品类"]} × {res["市场"]}'
        f'<span class="cr-badge b-ok">{via}</span></div>'
        f'<div class="cr-row"><span class="cr-k">命中关键词</span>{hit_html}</div>'
        f'{note_html}'
        f'<div class="cr-tip">🧭 路由原则：模型只负责「理解输入」，'
        f'下方法规结论 100% 来自本地核对语料 + 官方链接，模型无权新增或编造。</div>'
        f'<div class="cr-sec">要下更准的判断，这一单还缺这些资料</div>'
        f'<ul style="margin:4px 0 8px 20px;line-height:1.8">{missing_items}</ul>'
        f'<div class="cr-row">更完整的判定还依赖：产品 BOM / 材质单、'
        f'合同或客户合规要求、供应链分工（谁负责清关 / 贴标 / 注册）'
        f'—— 本期版本仅作提示，不做结构化判定。</div>'
        f'<div class="cr-dis">🔒 隐私边界：本次判定只使用「品类 + 市场」两个槽位；'
        f'输入原文只在内存中处理，不落盘、不缓存。'
        f'请勿输入个人隐私或客户敏感信息。</div>'
        f'</div>'
    )


if __name__ == "__main__":
    # 自检：强制词典路径（use_llm=False），结果确定、可离线复跑
    cases = [
        ("我要把洋娃娃卖到美国去，要做哪些合规工作", "", "儿童玩具", "美国", True),
        ("蓝牙耳机出口欧盟", "", "电子电器", "欧盟", True),
        ("食品级硅胶餐盒出口美国加州", "", "食品接触材料", "美国", True),
        ("毛绒玩具发德国亚马逊", "", "儿童玩具", "欧盟", True),
        ("童装卖到日本", "", None, None, False),
        ("帮我写一首诗", "", None, None, False),
    ]
    print("=" * 66)
    print("  M1.5 输入驱动路由 · 自检（词典路径，确定性）")
    print("=" * 66)
    n_ok = 0
    for text, ctx, want_cat, want_mkt, want_ok in cases:
        res = route(text, ctx, use_llm=False)
        ok = (res["ok"] == want_ok)
        if want_ok:
            ok = ok and res["品类"] == want_cat and res["市场"] == want_mkt \
                and res["m1"]["ok"] and bool(res["missing"])
        out = (f"{res['品类']} × {res['市场']}（{res['route_via']}，"
               f"主体 {res['m1']['stats']['主体条数']} 条）"
               if res["ok"] else f"拒绝（{res.get('reason')}）")
        print(f"  [{'PASS' if ok else 'FAIL'}] {text}  →  {out}")
        n_ok += ok
    print(f"  结果：{n_ok}/{len(cases)} 通过")
    print("=" * 66)
    sys.exit(0 if n_ok == len(cases) else 1)
