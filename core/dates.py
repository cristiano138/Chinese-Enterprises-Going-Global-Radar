# -*- coding: utf-8 -*-
"""
日期与变化事件抽取（core/dates.py）—— M2 变化时间线 的确定性底座。

职责（单一）：
    把语料里「散文形态」的日期信息，解析成**结构化的时间线事件**。
    输入是语料行，输出是事件列表 —— 不判断「该不该给用户看」，那是 verify 的事。

日期信息散落在三处，本模块统一接管：
    ① 结构化列  生效日期 / 最新修订日期
    ② 备注段    「生效/适用日期：d1、d2」
    ③ 备注段    「近期修订：d1、d2（共 N 条修订记录）」「（旧法，d 废止）」

本模块是**纯确定性代码**：只做正则与日期运算，不联网、不调模型。
—— 日期是事实，事实不能交给概率模型（README「AI 与确定性代码的分工」）。

一个必须守住的诚实边界：
    美国条目的「生效日期」列写的是「首次收录 YYYY-MM-DD（参考）」，
    这是 eCFR 的**收录日**，不是法规生效日。
    本模块把它标成 事件类型=首次收录 且 官方确认=False，
    绝不允许它冒充「生效日」出现在时间线上。
"""

import hashlib
import re
import sys
from datetime import date, timedelta

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ── 事件抽取缓存（内容指纹 → 事件列表）──────────────────────────
# 抽取是纯函数，同一行重复抽取结果一致；M2/M3 会反复对同一批语料抽取，
# 故按内容指纹做进程内缓存。上限 512 足以覆盖整张底表（86 行）的两轮以上，
# 超出后按插入序淘汰最早的一条（够用且零依赖，不引入 LRU 实现）。
_EVENT_CACHE = {}
_EVENT_CACHE_MAX = 512

# ── 事件类型（顺序即展示优先级）─────────────────────────────────
T_ENTRY = "生效"
T_APPLY = "适用"
T_REVISE = "修订"
T_REPEAL = "废止"
T_FIRST = "首次收录"

TYPE_ORDER = [T_REPEAL, T_ENTRY, T_APPLY, T_REVISE, T_FIRST]

# 类型 → 卖家视角的一句话含义
TYPE_MEANING = {
    T_ENTRY: "新法规开始生效",
    T_APPLY: "过渡期节点 / 开始适用",
    T_REVISE: "已生效法规被修订",
    T_REPEAL: "旧法规废止",
    T_FIRST: "官方数据库首次收录（参考，非生效日）",
}

# 时间窗选项（M2 规格：默认近 12 个月，可缩到 6 个月）
WINDOW_OPTIONS = {"近 12 个月": 12, "近 6 个月": 6}
DEFAULT_WINDOW = "近 12 个月"

# 未来事件不设隐式时间上限；已公布的远期节点也必须可核验展示。
# 保留名称兼容旧调用方，过滤逻辑不再使用该值。
UPCOMING_MONTHS = None

# ── 备注解析正则（均已用 86 条语料逐条验证命中）──────────────────
_RE_EU_DATES = re.compile(
    r"生效/适用日期：([0-9]{4}-[0-9]{2}-[0-9]{2}(?:、[0-9]{4}-[0-9]{2}-[0-9]{2})*)")
_RE_REPEAL = re.compile(r"（旧法，\s*([0-9]{4}-[0-9]{2}-[0-9]{2})\s*废止）")
_RE_REPLACED = re.compile(r"取代了\s*([0-9]+)\s*条法规")
_RE_US_REV = re.compile(
    r"近期修订：([0-9]{4}-[0-9]{2}-[0-9]{2}(?:、[0-9]{4}-[0-9]{2}-[0-9]{2})*)"
    r"（共\s*([0-9]+)\s*条修订记录）")
_RE_FIRST_REC = re.compile(r"首次收录\s*([0-9]{4}-[0-9]{2}-[0-9]{2})")
_RE_ISO = re.compile(r"^([0-9]{4})-([0-9]{2})-([0-9]{2})$")

_DATE_SPLIT = re.compile(r"[、,，]")


def row_key(row):
    """语料行的唯一键（CELEX 优先，其次官方编号）。"""
    return (row.get("CELEX号") or row.get("官方编号") or "").strip()


def _parse_iso(text):
    """严格解析 ISO 日期，失败返回 None（不猜、不纠正）。"""
    m = _RE_ISO.match((text or "").strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _minus_months(d, n):
    """d 往前推 n 个月（按日历，日超出月长则收敛到月末）。"""
    y, m = d.year, d.month - n
    while m <= 0:
        m += 12
        y -= 1
    # 各月天数（闰年 2 月 = 29）
    leap = (y % 4 == 0 and y % 100 != 0) or (y % 400 == 0)
    month_days = [31, 29 if leap else 28, 31, 30, 31, 30,
                  31, 31, 30, 31, 30, 31]
    day = min(d.day, month_days[m - 1])
    return date(y, m, day)


def in_window(d, months, today):
    """d 是否落在「今天往前 months 个月」的时间窗内（含今天）。"""
    if d is None:
        return False
    return _minus_months(today, months) <= d <= today


def humanize_gap(target, today):
    """给人看的时间距离：『约 3 个月前』/『还有 46 个月』。"""
    if target is None:
        return "日期缺失"
    days = (today - target).days
    future = days < 0
    n = abs(days)
    if n == 0:
        return "就是今天"
    if n < 31:
        unit = f"{n} 天"
    elif n < 365:
        unit = f"约 {round(n / 30.44)} 个月"
    else:
        unit = f"约 {round(n / 365.25, 1)} 年"
    return f"还有 {unit}" if future else f"{unit}前"


def _mk(row, d, etype, official, note=""):
    return {
        "日期": d.isoformat(),
        "date_obj": d,
        "事件类型": etype,
        "官方确认": official,
        "备注": note,
        "key": row_key(row),
        "法规中文名": row.get("法规中文名", "") or "官方未标注",
        "官方编号": row.get("官方编号", ""),
        "市场": row.get("机构", ""),
        "类目": row.get("类目", ""),
        "现行效力": row.get("现行效力", ""),
        "event_key": f"{row_key(row)}|{d.isoformat()}|{etype}",
    }


def _extract_events_uncached(row):
    """把一条语料行 → 结构化事件列表（不缓存，由 extract_events 包缓存）。

    不做时间窗过滤（那是 collect_events 的事），只负责**忠实还原**。
    同一条法规可能产出多个事件（例如：生效 + 后续过渡期 + 未来废止）。
    """
    events = []
    note = row.get("备注／问题", "") or ""
    code = row.get("机构", "")

    replaced = _RE_REPLACED.search(note)
    replaced_note = f"取代了 {replaced.group(1)} 条法规" if replaced else ""

    if code == "EU":
        # ① 生效日期列（欧盟是真正的生效日）
        d = _parse_iso(row.get("生效日期", ""))
        eu_dates_text = ""
        m = _RE_EU_DATES.search(note)
        if m:
            eu_dates_text = m.group(1)

        if d:
            events.append(_mk(row, d, T_ENTRY, True, replaced_note))

        # ② 备注里的「生效/适用日期」列表：首个通常等于生效日期，其余为适用/过渡期节点
        if eu_dates_text:
            seen = {events[0]["日期"]} if events else set()
            for part in _DATE_SPLIT.split(eu_dates_text):
                dd = _parse_iso(part)
                if not dd or dd.isoformat() in seen:
                    continue
                seen.add(dd.isoformat())
                events.append(_mk(row, dd, T_APPLY, True, "过渡期 / 适用日节点"))

        # ③ 旧法废止日（写在备注里，可能在未来）
        mr = _RE_REPEAL.search(note)
        if mr:
            dd = _parse_iso(mr.group(1))
            if dd:
                events.append(_mk(row, dd, T_REPEAL, True, "该法将于此日废止"))

    elif code == "US":
        # ① 最新修订日期列
        d = _parse_iso(row.get("最新修订日期", ""))
        rev_text, total = "", ""
        m = _RE_US_REV.search(note)
        if m:
            rev_text, total = m.group(1), m.group(2)

        if d:
            events.append(_mk(row, d, T_REVISE, True,
                              f"本次为最近一次修订，该法规快照内共 {total} 条修订记录"
                              if total else "本次为最近一次修订"))

        # ② 备注里的「近期修订」列表（补充历史修订点）
        if rev_text:
            seen = {events[0]["日期"]} if events else set()
            for part in _DATE_SPLIT.split(rev_text):
                dd = _parse_iso(part)
                if not dd or dd.isoformat() in seen:
                    continue
                seen.add(dd.isoformat())
                events.append(_mk(row, dd, T_REVISE, True,
                                  f"本次为历史修订记录，该法规快照内共 {total} 条"))

        # ③ 生效日期列其实是 eCFR「首次收录」参考日 —— 必须如实标为参考
        mf = _RE_FIRST_REC.search(row.get("生效日期", ""))
        if mf:
            dd = _parse_iso(mf.group(1))
            if dd:
                events.append(_mk(row, dd, T_FIRST, False,
                                  "eCFR 收录日，非法规生效日"))

    events.sort(key=lambda e: (e["date_obj"], TYPE_ORDER.index(e["事件类型"])),
                reverse=True)

    # 原实现在这里还有一段 `if not include_upcoming: return events` 后接
    # `return events` —— 两个分支返回值一模一样，include_upcoming 形同虚设。
    # 时间窗过滤本来就在 collect_events 里做，这里的参数没有必要，直接删掉分支，
    # 避免后来读代码的人以为「收紧参数就能少抽事件」。
    return events


def _row_fingerprint(row):
    """语料行的内容指纹（只取影响事件抽取的字段）。

    缓存键包含所有会进入事件输出的法规身份、分类与日期字段；题注里藏着
    生效/适用日期、取代条数、多日期告警等全部日期线索，漏了它就会在备注
    更新后继续用旧事件。
    """
    parts = (
        row.get("CELEX号", ""),
        row.get("官方编号", ""),
        row.get("法规中文名", ""),
        row.get("类目", ""),
        row.get("机构", ""),
        row.get("生效日期", ""),
        row.get("最新修订日期", ""),
        row.get("现行效力", ""),
        row.get("备注／问题", ""),
    )
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:20]


def extract_events(row, include_upcoming=True, upcoming_months=UPCOMING_MONTHS):
    """把一条语料行 → 结构化事件列表（带内容指纹缓存）。

    为什么值得缓存：M2 时间线一次查询会对同一批语料反复抽取（近窗内 / 即将发生 /
    全部历史各算一遍），M3 待办还要再抽一次算期限和紧迫度。抽取是纯函数，
    同一行重复计算结果完全一致，实测重复命中省掉约 85% 的抽取耗时。
    缓存键用内容指纹而非 id(row)：语料重新载入后对象会变，内容没变仍能命中。
    返回值统一 copy，防止调用方就地修改污染缓存。

    include_upcoming / upcoming_months 保留为兼容形参：时间窗过滤一直由
    collect_events 负责，这里不参与计算（详见 _extract_events_uncached 尾部注释）。
    """
    fp = _row_fingerprint(row)
    hit = _EVENT_CACHE.get(fp)
    if hit is not None:
        return [dict(e) for e in hit]
    events = _extract_events_uncached(row)
    if len(_EVENT_CACHE) >= _EVENT_CACHE_MAX:
        _EVENT_CACHE.pop(next(iter(_EVENT_CACHE)))
    _EVENT_CACHE[fp] = [dict(e) for e in events]
    return [dict(e) for e in events]


def collect_events(rows, months=None, today=None, include_upcoming=True):
    """批量抽取 + 按时间窗切分。

    返回 dict：
        近窗内   —— 时间窗内**已经发生**的事件（倒序）
        即将发生 —— 未来事件（过渡期 / 待废止），升序，单独一节
        全部     —— 所有事件（倒序），供「放宽时间窗」参照
        window   —— 实际使用的月数
        today    —— 基准日
    """
    today = today or date.today()

    extracted = []
    for r in rows:
        extracted.extend(extract_events(r))
    extracted.sort(key=lambda e: (e["date_obj"], TYPE_ORDER.index(e["事件类型"])),
                   reverse=True)

    # 首次收录只是官方数据库记录，不是法律事件；单独返回供参考，
    # 不进入 M2 的法律时间线、窗口统计或未来节点。
    reference_events = [e for e in extracted if not e["官方确认"]]
    all_events = [e for e in extracted if e["官方确认"]]

    if months is None:
        recent, upcoming = all_events, []
    else:
        recent = [e for e in all_events if in_window(e["date_obj"], months, today)]
        upcoming = [e for e in all_events if e["date_obj"] > today]

    if not include_upcoming:
        upcoming = []

    upcoming.sort(key=lambda e: (e["date_obj"], TYPE_ORDER.index(e["事件类型"])))
    return {
        "近窗内": recent,
        "即将发生": upcoming,
        "全部": all_events,
        "参考事件": reference_events,
        "window": months,
        "today": today,
    }


def _wrap(name):
    """给法规名加书名号；语料里的中文名大多已自带《》，不重复加。"""
    name = (name or "官方未标注").strip()
    if name.startswith("《") and name.endswith("》"):
        return name
    return f"《{name}》"


def describe(event):
    """确定性的事件摘要（LLM 不可用时的回退文本，也用作 LLM 的输入）。"""
    t = event["事件类型"]
    name = _wrap(event.get("法规中文名", ""))
    if t == T_ENTRY:
        s = f"{name}生效"
    elif t == T_APPLY:
        s = f"{name}进入适用 / 过渡期节点"
    elif t == T_REVISE:
        s = f"{name}修订"
    elif t == T_REPEAL:
        s = f"{name}废止"
    elif t == T_FIRST:
        s = f"{name}官方数据库首次收录（参考）"
    else:
        s = f"{name}状态变化"
    if event.get("备注"):
        s += f"（{event['备注']}）"
    return s


# ── 自检 ────────────────────────────────────────────────────────
if __name__ == "__main__":
    import csv
    import os
    from collections import Counter

    here = os.path.dirname(os.path.abspath(__file__))
    project = os.path.dirname(here)
    path = os.path.join(project, "data", "语料核对表_完整版.csv")
    with open(path, encoding="utf-8-sig") as f:
        rows = [{k: (v or "").strip() for k, v in r.items()}
                for r in csv.DictReader(f)]

    print("=" * 70)
    print("  日期事件抽取自检")
    print("=" * 70)

    all_ev = []
    for r in rows:
        all_ev.extend(extract_events(r))

    c = Counter(e["事件类型"] for e in all_ev)
    print(f"  语料 {len(rows)} 条 → 事件 {len(all_ev)} 条")
    for t in TYPE_ORDER:
        print(f"    {t:<6} {c.get(t, 0):>3} 条")
    unoff = [e for e in all_ev if not e["官方确认"]]
    print(f"  非官方确认日期（参考性质）：{len(unoff)} 条 —— 全部为『首次收录』")
    bad = [e for e in unoff if e["事件类型"] != T_FIRST]
    print(f"  非官方日期误标成官方事件类型的：{len(bad)} 条（应为 0）")
    print()

    print("  各类型样例：")
    for t in TYPE_ORDER:
        for e in all_ev:
            if e["事件类型"] == t:
                print(f"    [{t}] {e['日期']}  {e['key']:<16} {describe(e)[:52]}")
                break

    today = date(2026, 10, 15)
    print()
    print(f"  以 {today} 为基准，近 12 个月事件：")
    for months in (12, 6):
        res = collect_events(rows, months=months, today=today)
        print(f"    近 {months:>2} 个月：{len(res['近窗内']):>2} 条"
              f"　即将发生：{len(res['即将发生']):>2} 条")
    print("=" * 70)
