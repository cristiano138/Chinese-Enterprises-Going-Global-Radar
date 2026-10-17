# -*- coding: utf-8 -*-
"""
待办动作候选抽取（core/actions.py）—— M3 待办清单 的确定性底座。

职责（单一且严格）：
    判定**哪些语料条目能落到一个可执行动作**，并给出动作的分类、紧迫度、期限。
    「不能落到动作」的条目一律**不产出**，并如实统计出来 ——
    这是 M3 规格里的硬约束：只做「能落到动作」的条目。

为什么这一步必须用确定性代码？
    它决定了「什么该出现在待办清单里」。一旦交给模型，模型就会开始
    「想到什么写什么」—— 待办清单会变成建议清单，链接也会对不上条款。
    所以：规则引擎负责**选条目 + 定类型 + 挂链接**，
    模型只负责把法条语言改写成动词开头的短句（见 llm.m3_actions）。

本模块是**纯确定性代码**：只用关键词规则与日期运算，不联网、不调模型。

降级设计：
    回退动作文本由「备注第一段的义务从句」确定性抽取得到，
    因此即使模型不可用，待办清单依然条目完整、条条有依据、条条可核验。
"""

import os
import re
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)

from core import dates  # noqa: E402

# ── 动作类型（按判定优先级排列，先命中先归类）──────────────────
# 顺序有意设计：**动作导向**的关键词排在**法规性质**的关键词前面。
# 例如「禁止含铅油漆…卖家须检测铅含量」应归为「检测测试」，
# 因为卖家真正要做的事是检测，不是「禁止」。
TYPE_RULES = [
    ("标签标识", ["标签", "标识", "标注", "唛头", "警告语", "警示", "标示"]),
    ("检测测试", ["检测", "测试", "检验", "试验", "化验", "送检"]),
    ("注册备案", ["注册", "备案", "申报", "登记", "提交报告"]),
    ("认证文件", ["认证", "符合性", "证书", "技术文件", "声明", "认可实验室"]),
    ("记录留存", ["留存", "存档", "记录", "保存"]),
    ("切换替换", ["取代", "替代", "切换", "过渡"]),
    ("限制禁售", ["禁止", "不得", "禁售", "禁用", "限量", "限制"]),
]

TYPE_ORDER = [t for t, _ in TYPE_RULES] + ["合规确认"]

TYPE_MEANING = {
    "标签标识": "包装 / 标签上的标识义务",
    "检测测试": "需要送检或自测的项目",
    "注册备案": "向监管机构报送的义务",
    "认证文件": "需要取得或保存的合规文件",
    "记录留存": "需要留档备查的材料",
    "切换替换": "法规更替带来的切换动作",
    "限制禁售": "不得触碰的红线",
    "合规确认": "需要逐项确认的通用义务",
}

# 紧迫度权重（排序用）
URGENCY_RANK = {"高": 0, "中": 1, "低": 2}

# 义务从句抽取：优先「主体责任人 + 义务词」的从句
_RE_DUTY_SUBJECT = re.compile(
    r"(卖家|出口商|进口商|生产商|销售者|经营者)"
    r"[^，,。；;｜【】]{0,40}?(?:须|需|应|必须|不得|禁止)"
    r"[^，,。；;｜【】]{0,60}")
_RE_DUTY_ANY = re.compile(
    r"[^，,。；;｜【】]{0,30}?(?:须|需|应|必须|不得|禁止)"
    r"[^，,。；;｜【】]{0,60}")

# 过短 / 无信息量的动作从句（如「卖家需合规。」）→ 退回完整说明，避免清单里全是空话
_MIN_ACTION_LEN = 12


def row_key(row):
    return (row.get("CELEX号") or row.get("官方编号") or "").strip()


def clean_name(name):
    """规范法规名：去掉语料自带的《》，统一由展示层加。"""
    n = (name or "官方未标注").strip()
    if n.startswith("《") and n.endswith("》"):
        n = n[1:-1]
    return n


def _seg0(row):
    """备注第一段 = 语料自带的一句话中文说明（AI 预生成，已固化在 CSV 里）。"""
    return (row.get("备注／问题", "") or "").split("｜")[0].strip()


def classify(row, note_text=""):
    """判定动作类型。返回类型名；无法归类时返回空串。

    返回空串 = 「这条落不到动作」—— 调用方据此把它排除在待办清单外，
    并计入「未产出动作」如实上报，而不是硬编一个动作。
    """
    text = f"{_seg0(row)} {note_text}"

    # 已废止的条目，动作本质是「切换」——优先级最高，不参与关键词竞争
    if (row.get("现行效力", "") == "已废止"):
        return "切换替换"

    for tname, kws in TYPE_RULES:
        if any(k in text for k in kws):
            return tname

    # 兜底：只含通用义务词的，归为「合规确认」
    if _RE_DUTY_ANY.search(text):
        return "合规确认"
    return ""


def extract_action_text(row):
    """确定性抽取动作文本（模型不可用时的回退，也是模型的输入）。

    优先取「卖家/进口商… + 须/需/应/不得」的义务从句；
    从句过短或无信息量时退回整段说明（宁可啰嗦，也不要一句空话）。
    **绝不改写、绝不补充。**
    """
    seg0 = _seg0(row)
    m = _RE_DUTY_SUBJECT.search(seg0) or _RE_DUTY_ANY.search(seg0)
    text = (m.group(0) if m else seg0).strip(" ，,。；;｜")
    if len(text) < _MIN_ACTION_LEN and seg0:
        text = seg0.strip(" ，,。；;｜")
    if text and not text.endswith("。"):
        text += "。"
    return text


def _deadline(row, today, events=None):
    """最近一个未来节点（适用 / 生效 / 废止）。返回 (date|None, event|None)。

    events 可传入已抽好的事件列表复用 —— build_candidate 原先对同一行要抽
    3 次（期限一次、紧迫度一次、还有一次在别处），传进来就只抽一次。
    """
    evs = events if events is not None else dates.extract_events(row)
    fut = [e for e in evs
           if e["date_obj"] > today
           and e["事件类型"] in (dates.T_APPLY, dates.T_ENTRY, dates.T_REPEAL)]
    if not fut:
        return None, None
    e = min(fut, key=lambda x: x["date_obj"])
    return e["date_obj"], e


def urgency(row, deadline_obj, today, events=None):
    """紧迫度：高 / 中 / 低（规则可解释，不靠模型判断）。"""
    if row.get("现行效力", "") == "已废止":
        return "高"
    if deadline_obj is not None:
        months = (deadline_obj - today).days / 30.44
        return "高" if months <= 18 else "中"
    evs = events if events is not None else dates.extract_events(row)
    for e in evs:
        if e["官方确认"] and dates.in_window(e["date_obj"], 12, today):
            return "中"
    return "低"


def build_candidate(row, today=None):
    """一条语料行 → 一条动作候选；不能落到动作时返回 None。"""
    today = today or date.today()

    a_type = classify(row)
    if not a_type:
        return None

    events = dates.extract_events(row)     # 只抽一次，下面两处复用
    d_obj, d_ev = _deadline(row, today, events)
    act = extract_action_text(row)
    if not act:
        return None

    return {
        "key": row_key(row),
        "动作": act,
        "动作类型": a_type,
        "类型含义": TYPE_MEANING.get(a_type, ""),
        "紧迫度": urgency(row, d_obj, today, events),
        "期限": d_obj.isoformat() if d_obj else "",
        "期限说明": (f"最晚不迟于 {d_obj.isoformat()}（{dates.TYPE_MEANING[d_ev['事件类型']]}）"
                     if d_obj and d_ev else ""),
        "依据法规": clean_name(row.get("法规中文名", "")),
        "官方编号": row.get("官方编号", ""),
        "监管机构": row.get("监管机构", "") or row.get("机构", ""),
        "类目": row.get("类目", ""),
        "市场": row.get("机构", ""),
        "现行效力": row.get("现行效力", ""),
        "来源条款链接": row.get("官方链接", ""),
        "全部官方链接": [u for u in (row.get("官方链接", ""), row.get("ELI标识", ""))
                         if u and u.startswith("http")],
        "证据摘录": _seg0(row),
        "适用条件": (row.get("备注／问题", "") or "").strip(),
        "状态": row.get("现行效力", ""),
        "_raw": row,
    }


def collect(rows, today=None):
    """批量抽取。返回 (动作列表, 未产出动作的行)。

    未产出的行会如实上报，供界面显示「X 条未产出动作条目」——
    不做静默丢弃。
    """
    today = today or date.today()
    actions, skipped = [], []
    for r in rows:
        c = build_candidate(r, today=today)
        if c is None:
            skipped.append(r)
        else:
            actions.append(c)

    actions.sort(key=lambda a: (
        URGENCY_RANK.get(a["紧迫度"], 9),
        a["期限"] or "9999-99-99",
        TYPE_ORDER.index(a["动作类型"]) if a["动作类型"] in TYPE_ORDER else 99,
        a["key"],
    ))
    return actions, skipped


def group_by_type(actions):
    """按动作类型分组（保持 TYPE_ORDER 顺序），供界面分节展示。"""
    out = []
    for t in TYPE_ORDER:
        bunch = [a for a in actions if a["动作类型"] == t]
        if bunch:
            out.append((t, bunch))
    return out


# ── 自检 ────────────────────────────────────────────────────────
if __name__ == "__main__":
    import csv
    from collections import Counter

    path = os.path.join(PROJECT, "data", "语料核对表_完整版.csv")
    with open(path, encoding="utf-8-sig") as f:
        rows = [{k: (v or "").strip() for k, v in r.items()}
                for r in csv.DictReader(f)]

    today = date(2026, 10, 15)
    actions, skipped = collect(rows, today=today)

    print("=" * 70)
    print("  待办动作候选抽取自检")
    print("=" * 70)
    print(f"  语料 {len(rows)} 条 → 产出动作 {len(actions)} 条，"
          f"未产出 {len(skipped)} 条")
    print()
    print("  类型分布：")
    for t, n in Counter(a["动作类型"] for a in actions).most_common():
        print(f"    {t:<8} {n:>3} 条   （{TYPE_MEANING[t]}）")
    print()
    print("  紧迫度分布：")
    for u, n in Counter(a["紧迫度"] for a in actions).most_common():
        print(f"    {u}  {n:>3} 条")
    print()
    print("  样例（每条都带来源条款链接）：")
    for a in actions[:8]:
        print(f"    [{a['紧迫度']}][{a['动作类型']}] {a['动作'][:44]}")
        print(f"          依据《{a['依据法规']}》 {a['官方编号'][:22]}")
        print(f"          链接 {a['来源条款链接'][:74]}")

    print()
    print("  未产出动作的条目（如实列出，不静默丢弃）：")
    for r in skipped:
        print(f"    - {r['机构']} {r['官方编号'][:24]:24s} "
              f"{_seg0(r)[:46]}")
    print("=" * 70)
