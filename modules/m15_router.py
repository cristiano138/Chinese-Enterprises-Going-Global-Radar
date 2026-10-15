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

拒绝的三种情形（文案完全不同，别混）：
    · bad_category / bad_market —— 用户**说了**，但不在本期覆盖范围
      槽位取 OOS 哨兵，并把用户原话放进「用户品类 / 用户市场」用于点名
    · partial_品类 / partial_市场 —— 用户**没说**，提示补充
    · no_slots —— 品类和市场都没识别出来
    混掉前两者的后果：用户按提示补充「日本」，得到的还是「没确认出目标市场」—— 死循环。

不变量：ok 为 True ⇒ m1["ok"] 为 True。
    判定卡不会出现「上面说判定成功、下面报 M1·error」。兜底在 route() 第 ④ 步。

隐私边界（企业数据治理最小演示）：
    · 输入原文只在内存中处理；路由调用禁用 LLM 磁盘缓存（原文不落盘）
    · 判定只依赖「品类 + 市场」两个槽位；企业上下文仅辅助识别，不存储
    · 页面固定提示：请勿输入个人隐私与客户敏感信息
    · 模型回显的用户原文进 HTML 前一律 html.escape（render_parse 的 _esc）

用法：
    from modules import m15_router
    res = m15_router.route("我要把洋娃娃卖到美国去，要做哪些合规工作")
    自检（词典路径，离线）：python modules/m15_router.py
    自检（模型路径，桩注入）：python scripts/selftest_m15.py
"""

import html
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)

from core import copy_zh, corpus, llm  # noqa: E402
from modules import m1_map  # noqa: E402

# 枚举「哨兵值」：模型用它明确表达「用户说了，但不在本期支持范围内」。
# 与「空字符串 = 用户没说」严格区分 —— 两者的用户文案完全不同（见 route / render_parse）。
OOS = "范围外"

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

# ── 「范围外」词表（仅用于把「你说了但我们不支持」讲清楚）────────────
# ⚠️ 这两张表**只参与拒绝文案的点名**，绝不参与路由决策：
#    它们只在受支持词表**零命中**时才会被查（见 parse_local），
#    命中后槽位记为 OOS，由 route() 判成 bad_market / bad_category。
#    目的：让「童装卖到日本」不再被说成「你没说市场」（PRD 验收用例 5）。
#    口径：宁缺毋滥 —— 只收明确不属于本期的市场 / 品类，降低误伤。
OUT_OF_SCOPE_MARKET_WORDS = [
    "日本", "韩国", "英国", "加拿大", "澳大利亚", "新西兰", "东南亚",
    "新加坡", "马来西亚", "泰国", "越南", "印尼", "印度", "中东",
    "沙特", "阿联酋", "巴西", "墨西哥", "俄罗斯", "非洲", "拉美",
]

OUT_OF_SCOPE_CATEGORY_WORDS = [
    "钢材", "建材", "五金", "汽车零部件", "汽车整车", "医疗器械", "药品",
    "保健品", "机械", "化工原料", "农药", "软件", "服务",
]

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

# 枚举由 corpus 动态生成 —— 不再硬编，防止路由层与数据层（ENTRY_CATEGORIES）再次漂移。
_CAT_ENUM = " / ".join(corpus.SUPPORTED_CATEGORIES)
_MKT_ENUM = " / ".join(corpus.SUPPORTED_MARKETS.keys())

# 少样本示例：空模板只给了「形状」，给不出「范围外」与「没说」的区别，
# 而这两个槽位的语义正是最容易做错的（照抄原话 vs 填哨兵 vs 留空）。
# ⚠️ 示例刻意**避开 PRD 验收用例的取值**（童装 / 日本）——
#    否则验收测试会因为「答案就在提示词里」而失去意义。
_EXAMPLES = (
    "输入：蓝牙耳机出口欧盟\n"
    '输出：{"品类": "电子电器", "市场": "欧盟", "用户品类": "蓝牙耳机", '
    '"用户市场": "欧盟", "命中依据": "蓝牙耳机、欧盟"}\n'
    "\n"
    "输入：玩具出口韩国\n"
    '输出：{"品类": "儿童玩具", "市场": "范围外", "用户品类": "玩具", '
    '"用户市场": "韩国", "命中依据": "玩具、韩国"}\n'
    "\n"
    "输入：帮我写一首诗\n"
    '输出：{"品类": "", "市场": "", "用户品类": "", "用户市场": "", "命中依据": ""}'
)
# PARSE_PROMPT 走 .format()，示例里的花括号要转义成 {{ }}
_EXAMPLES_ESC = _EXAMPLES.replace("{", "{{").replace("}", "}}")

PARSE_PROMPT = (
    "你是跨境电商合规查询系统的路由器。从用户输入中抽取槽位，"
    "输出严格的 JSON，不要输出任何其他文字：\n"
    '{{"品类": "", "市场": "", "用户品类": "", "用户市场": "", "命中依据": ""}}\n'
    "\n"
    f"品类只能取以下之一：{_CAT_ENUM} / {OOS}\n"
    f"  · 仅当产品明确不属于以上 {len(corpus.SUPPORTED_CATEGORIES)} 个业务类目时才填「{OOS}」"
    "（例：钢材、汽车零部件、医疗器械、软件服务）\n"
    "  · 产品信息不足以判断时填空字符串\n"
    f"市场只能取以下之一：{_MKT_ENUM} / {OOS}\n"
    f"  · 仅当用户明确说了目标市场、但该市场不是 {_MKT_ENUM} 时才填「{OOS}」"
    "（例：日本、英国、加拿大）\n"
    "  · 用户没有提到任何目标市场时填空字符串\n"
    f"「用户品类」「用户市场」照抄用户原话里的说法（即使已判定为「{OOS}」），没有就填空字符串。\n"
    "「命中依据」填用户原话中的关键短语。\n"
    f"不要为了凑答案把{OOS}的产品硬套到最接近的类目；拿不准就填「{OOS}」或空字符串，不要猜。\n"
    "\n"
    "【示例】\n" + _EXAMPLES_ESC + "\n"
    "\n"
    "【现在轮到这一条】\n"
    "用户输入：{text}\n"
    "补充上下文：{context}"
)


def _oos_hit(blob, word_list):
    """在「范围外」词表里找命中词（返回最先前的一个）。只用于点名，不参与路由。"""
    for w in word_list:
        if w in blob:
            return w
    return ""


def parse_local(text, context=""):
    """本地词典解析（确定性）。

    返回 {品类, 市场, 用户品类, 用户市场, 命中词}；识别不出为空串。
    受支持词表命中时，槽位取受支持值；零命中且命中范围外词表时，槽位取 OOS 哨兵
    并把原话词放进「用户品类 / 用户市场」—— 让 route() 能区分「说了但不支持」与「没说」。
    """
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

    # 只在受支持词表**零命中**时才回顾「范围外」词表：
    # 「日本和美国」「钢材和玩具」这类混合输入，受支持侧已命中，不会走到这里。
    user_mkt = "" if market else _oos_hit(blob, OUT_OF_SCOPE_MARKET_WORDS)
    user_cat = "" if category else _oos_hit(blob, OUT_OF_SCOPE_CATEGORY_WORDS)
    if user_mkt:
        market = OOS
    if user_cat:
        category = OOS

    return {"品类": category, "市场": market,
            "用户品类": user_cat, "用户市场": user_mkt,
            "命中词": m_hits + c_hits + [w for w in (user_mkt, user_cat) if w]}


def _slot(data, key):
    """取一个槽位并归一成字符串（缺字段 / None / 非字符串都不炸）。"""
    return str(data.get(key) or "").strip()


def parse_model(text, context=""):
    """模型解析：从自然语言抽槽位。

    返回 ({品类, 市场, 用户品类, 用户市场, 命中依据}, meta)；失败返回 (None, meta)。

    两处刻意的设置：
      · use_cache=False —— 路由提示词含用户原文，**禁止落盘缓存**（隐私边界）。
      · max_tokens=4000 —— 本链路默认模型是**推理模型**，reasoning 计入 max_tokens，
        额度耗尽时 content 会是空串（core/llm.py:137 判为失败）。实测 300/400 必然空返回、
        600 时 JSON 被截断，而**范围外输入恰恰思考最久、最容易被截断**。故给足额度
        （与 core/llm.py 中 M1/M2/M3 的 4000 口径一致）。
        不采用「空返回后重试」：截断时推理 token 已经计费，重试等于付两次推理拿一个答案。
    """
    prompt = PARSE_PROMPT.format(text=(text or "")[:500],
                                 context=(context or "")[:500] or "（无）")
    out, meta = llm.chat(prompt, max_tokens=4000, temperature=0, use_cache=False)
    if not meta.get("ok"):
        return None, meta
    m = re.search(r"\{.*\}", out, re.S)
    if not m:
        return None, {"ok": False, "reason": "模型输出中未找到 JSON", "cached": False}
    try:
        data = json.loads(m.group(0))
    except Exception:
        return None, {"ok": False, "reason": "模型 JSON 解析失败", "cached": False}
    return {"品类": _slot(data, "品类"),
            "市场": _slot(data, "市场"),
            "用户品类": _slot(data, "用户品类"),
            "用户市场": _slot(data, "用户市场"),
            "命中依据": _slot(data, "命中依据")}, meta


def _result(ok, reason, via, note, ident, hits, missing=None, m1=None):
    """统一构造返回字典 —— 保证**所有分支键集完全一致**。

    app.py:565/577 硬下标取 res["m1"]，render_parse 消费其余字段；
    任何一个分支少一个键都会崩，所以这里收口。
    """
    return {"ok": ok, "reason": reason, "route_via": via, "note": note,
            "识别": ident, "命中词": hits, "missing": missing or [],
            "m1": m1,
            "品类": (ident or {}).get("品类", ""),
            "市场": (ident or {}).get("市场", "")}


def _decide_via(src_cat, src_mkt, model_used):
    """按「模型是否真的贡献了槽位」标注路由方式。

    模型调用失败时两个 src_* 都只会是「词典」或空 —— 此时绝不能标成「混合」，
    否则会与同一张卡上的 note（模型解析不可用…）自相矛盾。
    """
    if src_cat == "模型" and src_mkt == "模型":
        return "模型解析"
    if model_used:
        return "混合（模型 + 词典）"
    return "本地词典解析"


def route(text, context="", use_llm=True):
    """M1.5 主入口：理解输入 → 路由到确定性查表。

    返回 dict（**所有分支键集一致**，见 _result）：
        ok        —— 是否识别成功并出清单（False = 诚实拒绝）
        reason    —— empty / no_slots / bad_category / bad_market /
                     partial_品类 / partial_市场 / m1_unavailable
        route_via —— 模型解析 / 本地词典解析 / 混合（模型 + 词典）
        识别      —— 槽位 + 用户原话 + 模型依据 + 各槽位来源（可追溯）
        命中词    —— 词典命中的关键词（与「识别」里的模型依据分开，不混为一谈）
        missing   —— 「缺什么资料」清单（衔接 M3 待办）
        m1        —— M1 查表结果（use_llm=False：路由层不再叠加润色调用，省额度）

    不变量：ok 为 True ⇒ m1["ok"] 为 True。判定卡不会「上面说判定成功、下面报 M1 错误」。
    """
    text = (text or "").strip()
    context = (context or "").strip()

    if not text and not context:
        return _result(False, "empty", "", "", {}, [])

    # ── ① 模型解析（可选）────────────────────────────────────
    note = ""
    model_slots = None
    if use_llm:
        if llm.is_ready():
            model_slots, meta = parse_model(text, context)
            if model_slots is None:
                note = f"{copy_zh.msg_llm_unavailable()}（{meta.get('reason', '')}）"
        else:
            note = "模型链路未配置 —— 使用本地词典解析（确定性、零依赖、不联网）。"

    # ── ② 词典解析 + 槽位合并 ────────────────────────────────
    local = parse_local(text, context)
    m_slots = model_slots or {}
    cat = m_slots.get("品类", "")
    mkt = m_slots.get("市场", "")
    basis = m_slots.get("命中依据", "")
    src_cat = "模型" if cat else ""
    src_mkt = "模型" if mkt else ""
    if not cat and local["品类"]:
        cat, src_cat = local["品类"], "词典"
    if not mkt and local["市场"]:
        mkt, src_mkt = local["市场"], "词典"

    via = _decide_via(src_cat, src_mkt, "模型" in (src_cat, src_mkt))

    # 「用户原话」（用于把「你说了但我们不支持」讲清楚）：模型侧与词典侧取非空的
    user_cat = m_slots.get("用户品类", "") or local["用户品类"]
    user_mkt = m_slots.get("用户市场", "") or local["用户市场"]

    ident = {"品类": cat, "市场": mkt,
             "用户品类": user_cat, "用户市场": user_mkt,
             "命中依据": basis, "命中词": local["命中词"],
             "品类来源": src_cat, "市场来源": src_mkt}

    # ── ③ 校验：三类拒绝要分清 ──────────────────────────────
    #   说了但不在范围内（OOS 哨兵，或模型给出枚举外的值）→ bad_*，点名用户说的原话
    #   没说                                            → partial_*，提示补充
    hits = local["命中词"]
    if not cat and not mkt:
        return _result(False, "no_slots", via, note, ident, hits)
    if cat and (cat == OOS or cat not in corpus.ENTRY_CATEGORIES):
        return _result(False, "bad_category", via, note, ident, hits)
    if mkt and (mkt == OOS or mkt not in corpus.SUPPORTED_MARKETS):
        return _result(False, "bad_market", via, note, ident, hits)
    if not cat or not mkt:
        side = "品类" if not cat else "市场"
        return _result(False, f"partial_{side}", via, note, ident, hits)

    # ── ④ 路由到确定性查表（红线不变：结论全部来自核对语料）──
    m1 = m1_map.query(cat, mkt, use_llm=False)

    # 不变量兜底：查表失败就不许声称成功 ——
    # 防的是「路由层放行、数据层拒绝」再现「上卡成功 + 下卡 M1·error」的自相矛盾卡片。
    if not m1.get("ok"):
        return _result(False, "m1_unavailable", via, note, ident, hits)

    return _result(True, "", via, note, ident, hits,
                   missing=MISSING_INFO.get(cat, []), m1=m1)


def _esc(s):
    """转义模型回显的用户原文。

    「命中依据 / 用户品类 / 用户市场」都是模型照抄的用户输入，
    而本函数的输出直接交给 gr.HTML（不做转义）—— 不转义就是一个注入面。
    """
    return html.escape(str(s or ""), quote=True)


def render_parse(res):
    """把路由结果渲染成「判定卡」头部 HTML（法规清单部分由 app.py 复用 M1 渲染）。"""
    if not res.get("ok"):
        r = res.get("reason", "")
        ident = res.get("识别") or {}
        # 「你说了但我们不支持」要点名原话；「你没说」才提示补充 —— 两者不能混，
        # 否则用户按提示补充市场后还是同一句话（死循环）。
        said_cat = ident.get("用户品类") or ident.get("品类") or ""
        said_mkt = ident.get("用户市场") or ident.get("市场") or ""
        if r == "empty":
            msg = "请先在左侧输入业务描述（例如：我要把儿童玩具卖到欧盟）。"
        elif r == "bad_market":
            msg = (f"识别到目标市场「{_esc(said_mkt)}」—— 本期仅覆盖 "
                   f"{'、'.join(corpus.SUPPORTED_MARKETS.keys())}，"
                   f"其他市场不做硬编答案。")
        elif r == "bad_category":
            msg = copy_zh.msg_category_out_of_scope(said_cat)
        elif r == "m1_unavailable":
            msg = ("识别出的「品类 × 市场」在本期核对语料里没有可用条目，"
                   "不做硬编答案。")
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
                     f'{_esc(ident["命中依据"])}</div>')
        return (
            '<div class="cr-wrap"><div class="cr-err">'
            '<b>无法完成判定</b><br>'
            f'{msg}<br>{extra}<br>'
            '<b>支持的市场：</b>' + "、".join(corpus.SUPPORTED_MARKETS.keys()) +
            '<br><b>支持的品类：</b>' + "、".join(corpus.ENTRY_CATEGORIES) +
            '<br><span style="color:#6b7280">范围外的问题不做硬编答案 —— '
            '这是本工具与通用聊天机器人的根本区别。</span>'
            '</div></div>'
        )

    ident = res.get("识别") or {}
    via = res.get("route_via", "")
    hits = res.get("命中词") or []
    hit_html = (" ".join(f"<code>{_esc(h)}</code>" for h in hits)
                if hits else "（无词典关键词命中，按语义识别）")
    # 模型给的路由依据 —— 这才是「为什么这么路由」的答案，与词典命中词分开显示
    basis = ident.get("命中依据") or ""
    basis_html = (f'<div class="cr-row"><span class="cr-k">识别依据</span>'
                  f'{_esc(basis)}'
                  f'<span style="color:#6b7280">（模型回显的用户原话）</span></div>'
                  if basis else "")
    src_html = (f'<div class="cr-row"><span class="cr-k">槽位来源</span>'
                f'品类 {_esc(ident.get("品类来源") or "—")} · '
                f'市场 {_esc(ident.get("市场来源") or "—")}</div>')
    note = res.get("note") or ""
    note_html = f'<div class="cr-note">ℹ️ {_esc(note)}</div>' if note else ""
    missing_items = "".join(f"<li>{m}</li>" for m in res.get("missing", []))
    return (
        '<div class="cr-wrap">'
        f'<div class="cr-head"><b>判定卡</b>　'
        f'{_esc(res["品类"])} × {_esc(res["市场"])}'
        f'<span class="cr-badge b-ok">{_esc(via)}</span></div>'
        f'{basis_html}'
        f'<div class="cr-row"><span class="cr-k">词典命中</span>{hit_html}</div>'
        f'{src_html}'
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
    # 自检：强制词典路径（use_llm=False），结果确定、可离线复跑。
    # 模型路径非确定，单独放 scripts/selftest_m15.py（用桩注入，不联网）。
    # cases: (输入, 上下文, 期望品类, 期望市场, 期望 ok, 期望 reason)
    cases = [
        ("我要把洋娃娃卖到美国去，要做哪些合规工作", "", "儿童玩具", "美国", True, ""),
        ("蓝牙耳机出口欧盟", "", "电子电器", "欧盟", True, ""),
        ("食品级硅胶餐盒出口美国加州", "", "食品接触材料", "美国", True, ""),
        ("毛绒玩具发德国亚马逊", "", "儿童玩具", "欧盟", True, ""),
        # PRD 验收用例 5：说了市场但不在覆盖范围 —— 必须点名，不能糊成「你没说」
        ("童装卖到日本", "", None, None, False, "bad_market"),
        # 说了品类但不在范围内
        ("把钢材卖到美国", "", None, None, False, "bad_category"),
        ("帮我写一首诗", "", None, None, False, "no_slots"),
    ]
    print("=" * 66)
    print("  M1.5 输入驱动路由 · 自检（词典路径，确定性）")
    print("=" * 66)
    fails = []
    for text, ctx, want_cat, want_mkt, want_ok, want_reason in cases:
        res = route(text, ctx, use_llm=False)
        ok = res["ok"] == want_ok
        if want_ok:
            ok = ok and res["品类"] == want_cat and res["市场"] == want_mkt \
                and res["m1"]["ok"] and bool(res["missing"])
            out = (f"{res['品类']} × {res['市场']}（{res['route_via']}，"
                   f"主体 {res['m1']['stats']['主体条数']} 条）")
        else:
            ok = ok and res.get("reason") == want_reason
            ident = res.get("识别") or {}
            named = ident.get("用户市场") or ident.get("用户品类") or ""
            out = f"拒绝（{res.get('reason')}）" + (f"　点名「{named}」" if named else "")
        print(f"  [{'PASS' if ok else 'FAIL'}] {text}  →  {out}")
        if not ok:
            fails.append(text)

    # ── 不变量：ok 为真 ⇒ m1.ok 为真 ──────────────────────────
    # 这是本次修复的核心承诺：判定卡不会「上面说判定成功、下面报 M1 错误」。
    print()
    print("  【不变量】ok ⇒ m1.ok（遍历 5 类目 × 2 市场）")
    n_norm = 0
    for cat in corpus.ENTRY_CATEGORIES:
        for mkt in corpus.SUPPORTED_MARKETS:
            res = route(f"{cat} 出口 {mkt}", "", use_llm=False)
            if res["ok"] and res["m1"]["ok"]:
                n_norm += 1
            else:
                fails.append(f"不变量/可达性：{cat} × {mkt} → ok={res['ok']}")
    print(f"  [{'PASS' if n_norm == 10 else 'FAIL'}] {n_norm}/10 组成功且 m1.ok")

    # ── 契约：所有返回分支键集一致（app.py:565/577 硬下标 res["m1"]）──
    print()
    print("  【契约】所有返回分支键集一致")
    base_keys = {"ok", "reason", "route_via", "note", "识别", "命中词",
                 "missing", "m1", "品类", "市场"}
    probes = ["我要把洋娃娃卖到美国去", "童装卖到日本", "把钢材卖到美国",
              "我要卖玩具", "帮我写一首诗", ""]
    bad = [p for p in probes
           if set(route(p, "", use_llm=False).keys()) != base_keys]
    print(f"  [{'PASS' if not bad else 'FAIL'}] {len(probes)} 个分支键集一致")
    if bad:
        fails.extend(bad)

    print()
    print("=" * 66)
    if fails:
        print(f"  结果：失败 {len(fails)} 项")
        for f in fails:
            print(f"    ❌ {f}")
    else:
        print("  结果：全部通过")
    print("=" * 66)
    sys.exit(0 if not fails else 1)
