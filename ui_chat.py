"""A small conversation shell over the existing ComplianceRadar services.

Result controls render native Gradio components. Expanding evidence does not call
the model or rerun a query. Every callback carries a result ID, never parsed HTML.
"""
from copy import deepcopy
import html
import json
from pathlib import Path
import tempfile
from urllib.parse import urlsplit

import gradio as gr

from core import asr, conversation, corpus, law_store, llm, snapshot
from modules import m2_timeline

ROOT = Path(__file__).resolve().parent
CSS = (ROOT / "assets" / "chat.css").read_text(encoding="utf-8")
JS = (ROOT / "assets" / "chat.js").read_text(encoding="utf-8")
BUILD_VERSION = "2026.10.19-chat1"
CAPABILITIES = [
    ("map", "相关法规", "查看品类与市场对应的法规、来源及覆盖范围"),
    ("todo", "合规待办", "整理下一步、后续准备与待确认事项"),
    ("timeline", "变化与关键日期", "区分生效、适用与历史参考日期"),
    ("compare", "两个市场对比", "按官方编号对照欧盟、美国的法规目录"),
    ("multi", "多个市场汇总", "分市场查看法规与各自的数据状态"),
    ("readiness", "上线准备计划", "按阶段、责任和依赖组织已有待办"),
    ("model", "回答方法与来源对照", "查看真实回放；缺样本时如实说明"),
]
STATUS = {"evidence_pending": "依据待核验", "condition_pending": "适用条件待确认",
          "confirmed": "有来源 · 请核对适用性", "user_reported_done": "用户自述已完成",
          "historical": "历史资料", "excluded": "已隔离 · 不列入当前行动"}
KIND = {"law": "法律法规", "legal": "法律法规", "platform": "平台规则",
        "regulation": "法律法规", "task": "法律法规",
        "advice": "操作建议", "guidance": "操作建议", "legal_requirement": "法律法规",
        "platform_rule": "平台规则", "recommendation": "操作建议"}


def _e(value):
    return html.escape(str(value or ""), quote=True)


def _md(value):
    """Escape user/data text, allowing only explicitly constructed source links."""
    return html.escape(str(value or "")).replace("[", "\\[").replace("]", "\\]")


def _link(title, url):
    try:
        parsed = urlsplit(str(url))
        if parsed.scheme not in ("https", "http") or not parsed.netloc:
            return _md(title)
        return f"[{_md(title)}]({str(url).replace(')', '%29').replace(' ', '%20')})"
    except ValueError:
        return _md(title)


def context_html(context, label="当前理解"):
    parts = []
    for key in ("product", "category", "market", "country", "platform", "site", "fulfillment", "stage"):
        value = context.get(key)
        if value and str(value) not in parts:
            parts.append(str(value))
    if not parts:
        return ""
    return '<div class="cr-context"><span class="cr-context-label">' + _e(label) + '</span>' + "".join(
        f"<span>{_e(value)}</span>" for value in parts) + '</div>'


def _unpack(state, result, notice=""):
    messages = state.get("messages", [])
    return (state, result, gr.update(value=messages, visible=bool(messages)),
            gr.update(visible=not bool(messages)), gr.update(visible=not bool(messages)),
            context_html(state.get("context", {})), "", notice,
            gr.update(value=None, visible=False), gr.update(visible=bool(messages)), gr.update(value=None))


def _result_map(state):
    values = state.get("results", [])
    return values if isinstance(values, dict) else {item["id"]: item for item in values}


def submit_message(text, state, action=None):
    state = state or conversation.new_session()
    if not (text or "").strip() and not action:
        return _unpack(state, _result_map(state).get(state.get("active_result_id")),
                       "先写下你的产品和问题，或选择一个示例。")
    try:
        next_state, result = conversation.respond((text or "").strip(), state, action=action)
        if result.get("export_requested"):
            output = list(_unpack(next_state, result))
            output[8], output[7] = prepare_export(next_state, result)
            return tuple(output)
        return _unpack(next_state, result, "已更新。点击结果标题展开详情，也可以继续追问。")
    except Exception:
        # Keep the actual request in the textbox so that retry is one click.
        output = list(_unpack(state, _result_map(state).get(state.get("active_result_id")),
                              "这次查询暂未完成，请重试；已有会话仍保留。"))
        output[6] = text or ""
        return tuple(output)


def reset_session():
    return _unpack(conversation.new_session(), None, "新对话已开始。")


def prepare_export(state, result):
    if not result:
        return gr.update(value=None, visible=False), "先生成一份结果再导出。"
    try:
        filename, data = conversation.export_result(state, result["id"])
        # A separate temporary directory per export prevents cross-session names
        # colliding. Gradio serves only the returned file, not the project root.
        directory = Path(tempfile.mkdtemp(prefix="cr-export-"))
        path = directory / Path(filename).name
        path.write_bytes(data if isinstance(data, bytes) else str(data).encode("utf-8-sig"))
        return gr.update(value=str(path), visible=True), "导出已生成，包含这份结果的查询背景。"
    except (ValueError, KeyError, RuntimeError):
        return gr.update(value=None, visible=False), "查询条件已变化或此结果不可导出，请重新查询。"


def transcribe(audio, original):
    if not audio:
        return original or "", "请先录音或上传音频。"
    try:
        text, meta = asr.transcribe(audio)
        if text and meta.get("ok"):
            return text, "已转写到输入框。请核对产品、市场和数字，再点击发送；尚未发起业务查询。"
    except Exception:
        pass
    return original or "", "语音暂未识别成功，可以重录或直接输入；原文字已保留。"


def _details(item, key):
    summary = item.get("summary") or item.get("action") or ""
    if summary:
        gr.Markdown(_md(summary))
    details = item.get("details", {})
    if isinstance(details, str):
        gr.Markdown(_md(details))
    elif isinstance(details, dict):
        # Source dictionaries remain available in a final fold, rather than
        # dumping whole JSON objects into every card.
        labels = {"conditions": "适用条件", "materials": "需要准备", "dependencies": "前置事项", "kind": "信息类型",
                  "evidence_status": "证据状态", "applicability_status": "适用状态"}
        useful = {"适用条件", "怎么做", "责任角色", "依据法规", "官方编号", "日期", "事件类型",
                  "期限", "期限说明", "现行效力", "是否仍有效", "证据说明", "阶段", "日期核验提示"} | set(labels)
        for label, value in details.items():
            if value is None or value == "" or value == [] or value == {} or label not in useful:
                continue
            if isinstance(value, (dict, list)):
                if len(str(value)) > 1600:
                    continue
                value = json.dumps(value, ensure_ascii=False) if isinstance(value, dict) else "、".join(map(str, value))
            gr.Markdown(f"**{_md(labels.get(label, label))}**　{_md(value)}")
        extras = {label: value for label, value in details.items()
                  if label not in useful and not label.startswith("_")
                  and label not in ("original", "source_original", "raw", "sources", "全部官方链接", "官方原文链接", "ELI链接", "key")
                  and any("\u4e00" <= letter <= "\u9fff" for letter in label)
                  and isinstance(value, (str, int, bool)) and value != ""}
        if extras:
            with gr.Accordion("更多原始目录信息", open=False, key=key + "-fields", preserved_by_key=["open"]):
                for label, value in extras.items():
                    gr.Markdown(f"**{_md(label)}**　{_md(value)}")
    gaps = item.get("gaps", [])
    if isinstance(gaps, str):
        gaps = [gaps]
    for gap in gaps:
        gr.HTML('<div class="cr-callout">待确认：' + _e(gap) + '</div>')
    sources = item.get("sources", [])
    if sources:
        with gr.Accordion("依据与官方原文 · 点击展开", open=False, key=key + "-sources",
                          preserved_by_key=["open"], elem_classes="cr-item"):
            for source in sources:
                if not isinstance(source, dict):
                    gr.Markdown(_md(source))
                    continue
                title = source.get("title") or source.get("标题") or "查看官方原文"
                url = source.get("url") or source.get("官方链接")
                gr.Markdown(_link(title + " ↗", url))
                excerpt = source.get("excerpt") or source.get("片段")
                if excerpt:
                    gr.Markdown("支持片段／语料摘要：\n\n> " + _md(excerpt).replace("\n", "\n> "))
                locator = source.get("locator")
                status = source.get("status") or source.get("verification_status")
                if locator or status:
                    gr.Markdown(" · ".join(_md(v) for v in (locator, status) if v))
    else:
        gr.Markdown("暂无可展示的条款原文证据；此项不能据此认定已满足要求。")


def _item_card(item, result_id, index, state_component, result_component, status_component,
               allow_complete=False):
    item_id = str(item.get("id", index))
    key = result_id + "-" + item_id
    status = item.get("status", "evidence_pending")
    status_text = STATUS.get(status, status or "待核验")
    label = f"{item.get('title', '查看条目')}  ·  {status_text}"
    with gr.Accordion(label, open=False, key=key, preserved_by_key=["open"], elem_classes="cr-item"):
        if item.get("information_type") or item.get("stage_title"):
            gr.Markdown(" · ".join(_md(item.get(name)) for name in ("information_type", "stage_title") if item.get(name)))
        _details(item, key)
        if allow_complete and item.get("can_complete", True) and status not in ("excluded", "historical"):
            label = "撤回自述完成" if status == "user_reported_done" else "我已准备此项（仅记录自述）"
            button = gr.Button(label, size="sm", key=key + "-done")

            def mark_done(current_state, rid=result_id, iid=item_id):
                try:
                    updated_state, updated_result = conversation.complete_task(current_state, rid, iid)
                    return updated_state, updated_result, "已更新自述进度；证据核验状态保持独立。"
                except (ValueError, KeyError, RuntimeError):
                    return current_state, gr.skip(), "这份结果属于历史条件，请在当前结果中记录进度。"

            button.click(mark_done, inputs=state_component,
                         outputs=[state_component, result_component, status_component],
                         show_progress="hidden", concurrency_limit=1, concurrency_id="conversation")


def _filter_items(items, selection):
    def info_type(item):
        raw_kind = str(item.get("details", {}).get("kind", item.get("kind", "")))
        if "平台" in raw_kind:
            return "平台规则"
        if "建议" in raw_kind:
            return "操作建议"
        if "法律" in raw_kind or "监管" in raw_kind:
            return "法律法规"
        return KIND.get(item.get("kind"), item.get("kind"))

    if selection == "待确认":
        return [item for item in items if item.get("status") in ("evidence_pending", "condition_pending")]
    if selection in ("法律法规", "平台规则", "操作建议"):
        return [item for item in items if info_type(item) == selection]
    return items


def _timeline(items, result_id, state, result, notice):
    if not items:
        gr.Markdown("当前时间窗内暂无可展示的日期记录。可以调整时间窗；这不代表没有法规变化。")
    for index, item in enumerate(items):
        details = item.get("details", {})
        date = (details.get("日期") or details.get("date") or item.get("date") or "日期含义待核验") if isinstance(details, dict) else "日期含义待核验"
        gr.HTML('<div class="cr-timeline-label">' + _e(date) + '</div>')
        _item_card(item, result_id, index, state, result, notice)


def _task_groups(current, items, state, result, notice):
    rid = current["id"]
    groups = {"下一步": [], "后续事项": [], "待确认": [], "用户自述已完成": []}
    for task in items:
        group = ("用户自述已完成" if task.get("status") == "user_reported_done" else task.get("group"))
        if group not in groups:
            group = "待确认" if task.get("status") in ("condition_pending", "evidence_pending") else "后续事项"
        groups[group].append(task)
    if current.get("presentation") == "table":
        rows = [[task.get("title", ""), group, task.get("stage_title", ""),
                 STATUS.get(task.get("status"), task.get("status", "待核验"))]
                for group, tasks in groups.items() for task in tasks]
        gr.Dataframe(rows, headers=["行动", "分组", "阶段", "资料状态"], interactive=False,
                     wrap=True, elem_classes="cr-comparison", key=rid + "-task-table")
        gr.Markdown("点击下面的任务标题，继续查看执行说明、资料和依据。")
    preview = "下一步" if groups["下一步"] else "待确认"
    for group, tasks in groups.items():
        if not tasks:
            continue
        if group == preview or current.get("presentation") == "all":
            gr.HTML('<div class="cr-section-heading">' + _e(group) + ' · ' + str(len(tasks)) + ' 项</div>')
            limit = len(tasks) if current.get("presentation") == "all" else 3
            for index, task in enumerate(tasks[:limit]):
                _item_card(task, rid, index, state, result, notice, allow_complete=True)
            remaining = tasks[limit:]
            if remaining:
                with gr.Accordion("查看其余 " + str(len(remaining)) + " 项" + group, open=False,
                                  key=rid + "-remaining-" + group, preserved_by_key=["open"], elem_classes="cr-item"):
                    for index, task in enumerate(remaining):
                        _item_card(task, rid, index + limit, state, result, notice, allow_complete=True)
        elif current.get("presentation") != "next":
            with gr.Accordion(group + " · " + str(len(tasks)) + " 项，点击展开", open=False,
                              key=rid + "-group-" + group, preserved_by_key=["open"], elem_classes="cr-item"):
                for index, task in enumerate(tasks):
                    _item_card(task, rid, index, state, result, notice, allow_complete=True)


def _comparison(raw, items, rid, state, result, notice, selection="全部"):
    regions = raw.get("区域", [])
    markets = [region.get("市场", "") for region in regions]
    by_identifier = {}
    for region in regions:
        for record in region.get("记录", []):
            identifier = record.get("官方编号") or record.get("CELEX号") or record.get("法规中文名")
            if not identifier:
                continue
            entry = by_identifier.setdefault(identifier, {"title": record.get("法规中文名") or record.get("中文名") or identifier})
            entry[region["市场"]] = record.get("人工核对") or record.get("审核状态") or "目录有记录 · 适用性待核验"
    if markets and by_identifier:
        rows = [[identifier, entry["title"]] + [entry.get(market, "目录未收录") for market in markets]
                for identifier, entry in by_identifier.items()]
        table = gr.Dataframe(value=rows, headers=["官方编号", "法规名称"] + markets,
                             interactive=False, wrap=True, elem_classes="cr-comparison", key=rid + "-table")
        selected_source = gr.Markdown("点击表格任意一行，就近查看该条目的来源。", key=rid + "-selected-source")
        identifiers = list(by_identifier)

        def row_details(index):
            if not isinstance(index, int) or not 0 <= index < len(identifiers):
                return "请选择一条记录。"
            identifier = identifiers[index]
            text = ["**" + _md(identifier) + "** · 目录记录，适用性待核验"]
            for region in regions:
                for record in region.get("记录", []):
                    if (record.get("官方编号") or record.get("CELEX号") or record.get("法规中文名")) == identifier:
                        text.append(_md(region.get("市场")) + "：" + _link(record.get("法规中文名") or "官方来源 ↗", record.get("官方链接")))
            return "\n\n".join(text)

        def select_record(evt: gr.SelectData):
            return row_details(evt.index[0] if isinstance(evt.index, (list, tuple)) else evt.index)

        table.select(select_record, outputs=selected_source, queue=False)
        record_choice = gr.Dropdown(choices=[(entry["title"] + " · " + identifier, identifier)
                                            for identifier, entry in by_identifier.items()], value=None,
                                    label="选择一条法规，查看这行的官方来源", key=rid + "-row-choice")
        record_choice.change(lambda value: row_details(identifiers.index(value)) if value in identifiers else "请选择一条法规。",
                             inputs=record_choice, outputs=selected_source, queue=False)
    else:
        rows = [[item.get("title", ""), item.get("summary", ""),
                 STATUS.get(item.get("status"), item.get("status", "待核验"))] for item in items]
        if rows:
            gr.Dataframe(value=rows, headers=["对照条目", "目录信息", "核验状态"],
                         interactive=False, wrap=True, elem_classes="cr-comparison", key=rid + "-table")
    gr.Markdown("目录是否收录不等于要求等效。**点击下方对应条目，展开来源与差异详情。**")
    for item in items:
        _region_cards(item, rid, state, result, notice, selection)


def _region_cards(item, rid, state, result, notice, selection="全部"):
    with gr.Accordion(item.get("title", "市场") + " · 点击查看逐条法规与来源", open=False,
                      key=rid + "-region-" + str(item.get("id")), preserved_by_key=["open"], elem_classes="cr-item"):
        gr.Markdown(_md(item.get("summary")))
        for gap in item.get("gaps", []):
            gr.HTML('<div class="cr-callout">' + _e(gap) + '</div>')
        leaves = _filter_items(item.get("details", {}).get("items", []), selection)
        for index, leaf in enumerate(leaves):
            _item_card(leaf, rid, index, state, result, notice)
        if not leaves:
            gr.Markdown("当前市场没有符合筛选的已核对目录条目；不代表没有适用要求。")


def _stages(current, state, result, notice, selection="全部"):
    rid = current["id"]
    raw = current.get("raw") or {}
    stages = [item["details"] for item in current.get("items", []) if item.get("kind") == "stage"]
    if stages:
        original_order = {stage.get("id"): index for index, stage in enumerate(stages)}
        preparation = current.get("context", {}).get("stage", "")
        focus = {"准备上架": "listing", "已销售": "aftersales", "准备中": "testing"}.get(preparation, "selection")
        stages = sorted(stages, key=lambda stage: 0 if stage.get("id") == focus else 1)
        gr.Markdown("按当前准备阶段推荐先查看标记的阶段；这是浏览顺序建议，不代表其他阶段已经完成。")
        for stage in stages:
            index = original_order.get(stage.get("id"), 0)
            sid = str(stage.get("id", index))
            label = ("建议先看 · " if sid == focus else "") + f"{index + 1:02d}　{stage.get('title', '准备阶段')}　· 点击查看任务与缺口"
            with gr.Accordion(label, open=False, key=rid + "-stage-" + sid,
                              preserved_by_key=["open"], elem_classes=["cr-item", "cr-stage"]):
                gr.Markdown(_md(stage.get("summary") or stage.get("status") or "资料覆盖情况见以下任务与缺口。"))
                for gap in stage.get("gaps", []):
                    gr.HTML('<div class="cr-callout">' + _e(gap) + '</div>')
                tasks = _filter_items(stage.get("tasks", []), selection)
                if not tasks:
                    gr.Markdown("此阶段当前筛选下没有任务；可切换“全部”查看覆盖与缺口。")
                for task_index, task in enumerate(tasks):
                    task = dict(task)
                    task.setdefault("details", {"信息类型": KIND.get(task.get("kind"), task.get("kind", "")),
                                                 "适用条件": task.get("conditions", "")})
                    _item_card(task, rid, task_index, state, result, notice, allow_complete=True)
    else:
        for index, region in enumerate(raw.get("区域", [])):
            gr.Markdown("**" + _md(region.get("市场", "")) + "**")
            gr.Markdown("资料状态：" + _md(region.get("状态", "待核验")) + " · 待核对记录：" + str(region.get("待核对", 0)))
            for gap in region.get("待确认", []):
                gr.HTML('<div class="cr-callout">' + _e(gap.get("需确认", "") if isinstance(gap, dict) else gap) + '</div>')
            if region.get("错误") or not region.get("动作"):
                gr.HTML('<div class="cr-callout">' + _e(region.get("错误") or "此市场暂无可生成的已核对动作；请先核验目录资料。") + '</div>')
            for phase_index, phase in enumerate(region.get("阶段", [])):
                with gr.Accordion(phase.get("名称", "准备阶段") + " · 点击展开", open=False,
                                  key=f"{rid}-phase-{index}-{phase_index}", preserved_by_key=["open"],
                                  elem_classes=["cr-item", "cr-stage"]):
                    tasks = [item for item in current.get("items", []) if item.get("details", {}).get("阶段") == phase.get("名称")
                             and item.get("group", "").startswith(region.get("市场", ""))]
                    tasks = _filter_items(tasks, selection)
                    for task_index, task in enumerate(tasks):
                        _item_card(task, rid, task_index, state, result, notice, allow_complete=True)
                    if not tasks:
                        gr.Markdown("此阶段当前筛选下暂无任务。")
        if not raw.get("区域"):
            gr.Markdown("当前范围尚无可核验的阶段任务。相关覆盖缺口见上方说明。")


def build_ui():
    with gr.Blocks(title="出海合规雷达 · 从问题到下一步", analytics_enabled=False,
                   delete_cache=(3600, 3600)) as demo:
        session = gr.State(value=conversation.new_session, time_to_live=7200)
        active = gr.State(value=None)
        gr.HTML('<div class="cr-intro" aria-hidden="true"><div class="cr-radar"><div class="cr-sweep"></div></div>'
                '<div class="cr-intro-title">出海合规雷达</div><div class="cr-intro-caption">COMPLIANCE RADAR</div>'
                '<button class="cr-intro-skip" type="button">跳过开场</button></div>')
        with gr.Row(elem_id="cr-topbar"):
            gr.HTML('<div class="cr-brand"><span class="cr-logo" aria-hidden="true"></span>'
                    '<div><b>出海合规雷达</b><small>COMPLIANCE RADAR</small></div></div>')
            reset = gr.Button("＋ 新建对话", scale=0, elem_id="cr-reset")
        with gr.Column(visible=True, elem_id="cr-welcome-wrap") as welcome:
            gr.HTML('<div class="cr-welcome"><div class="cr-eyebrow">从一个问题，到清楚的下一步</div>'
                    '<h1>出海的第一步，<br>从说清你的生意开始。</h1>'
                    '<p>告诉我你准备卖什么、卖到哪里、在哪个平台销售。<br>'
                    '一起梳理相关要求，按需要展开行动和依据。</p></div>')
        chat = gr.Chatbot(value=[], show_label=False, height=200, visible=False, buttons=[],
                          feedback_options=None, elem_id="cr-chat", layout="bubble", autoscroll=False)
        context = gr.HTML("")
        result_filter = gr.Radio(["全部", "待确认", "法律法规", "平台规则", "操作建议"], value="全部",
                                 label="筛选当前结果", visible=False)
        with gr.Row(visible=True, elem_id="cr-examples") as examples:
            example_1 = gr.Button("毛绒玩具卖到德国亚马逊，\n从哪里开始？")
            example_2 = gr.Button("儿童玩具卖到欧盟，\n先看相关法规")
            example_3 = gr.Button("比较欧盟和美国，\n儿童玩具的法规目录")
        status = gr.Markdown("", elem_id="cr-status")

        @gr.render(inputs=[active, result_filter], show_progress="hidden",
                   concurrency_limit=1, concurrency_id="result-render")
        def render_result(current, selected_filter):
            if not current:
                gr.HTML("", key="empty-result")
                return
            rid = str(current.get("id", "current"))
            kind = current.get("kind", "question")
            gr.HTML('<div class="cr-result-header" data-result-id="' + _e(rid) + '"><span class="cr-eyebrow">' + _e(
                {"map": "法规清单", "todo": "行动清单", "timeline": "日期节点", "compare": "区域对照",
                 "multi": "分市场汇总", "readiness": "上线准备", "model": "方法对照", "journey": "六阶段行动路线"}.get(kind, "继续梳理")) +
                '</span><h2>' + _e(current.get("title", "你的查询结果")) + '</h2><p>' +
                _e(current.get("summary", "")) + '</p></div>')
            gr.HTML(context_html(current.get("context", {}), label="本次查询条件"))
            version = current.get("data_version") or snapshot.SNAPSHOT_VERSION
            if isinstance(version, dict):
                version = str(version.get("snapshot", "")) + " · 目录截止 " + str(version.get("cutoff", "未知")) + " · 查询 " + str(version.get("query_date", "未知")) + (" · 路线资料获取 " + str(version.get("sources_retrieved_on")) if version.get("sources_retrieved_on") else "")
            gr.HTML('<div class="cr-result-meta">结果 ' + _e(rid[:8]) + ' · 数据版本 ' +
                    _e(version) + ' · 点击条目标题展开，无需重复提问</div>')
            for gap in current.get("gaps", [])[:2]:
                gr.HTML('<div class="cr-callout">' + _e(gap) + '</div>')
            if len(current.get("gaps", [])) > 2:
                with gr.Accordion("其他资料边界与待确认事项 · 点击展开", open=False,
                                  key=rid + "-gaps", preserved_by_key=["open"], elem_classes="cr-item"):
                    for gap in current["gaps"][2:]:
                        gr.Markdown(_md(gap))
            items = _filter_items(current.get("items", []), selected_filter)
            raw = current.get("raw") or {}
            if kind == "timeline":
                _timeline(items, rid, session, active, status)
            elif kind == "todo":
                _task_groups(current, items, session, active, status)
            elif kind == "compare":
                _comparison(raw, current.get("items", []), rid, session, active, status, selected_filter)
            elif kind in ("journey", "readiness"):
                _stages(current, session, active, status, selected_filter)
            elif kind == "model":
                gr.Markdown("观察日期：" + _md(raw.get("观察日期", "未知")) + "\n\n固定题干：" + _md(raw.get("固定题干", "未提供")))
                if raw.get("回放列表"):
                    for index, replay in enumerate(raw["回放列表"]):
                        with gr.Accordion("真实回放 " + str(index + 1) + " · 点击查看", open=False,
                                          key=f"{rid}-replay-{index}", elem_classes="cr-item"):
                            with gr.Row():
                                with gr.Column():
                                    gr.Markdown("**通用回答**\n\n" + _md(replay.get("generic_answer", "无记录")))
                                with gr.Column():
                                    gr.Markdown("**本工具回答**\n\n" + _md(replay.get("tool_answer", "无记录")))
                else:
                    gr.Markdown("尚无可展示的真实回放记录；不生成模拟对照结果。")
            elif kind == "multi":
                for item in current.get("items", []):
                    _region_cards(item, rid, session, active, status, selected_filter)
            else:
                done = [item for item in items if item.get("status") == "user_reported_done"]
                pending = [item for item in items if item.get("status") in ("excluded", "historical")]
                normal = [item for item in items if item not in done and item not in pending]
                limit = min(len(normal), 3 if kind == "todo" else 5) if current.get("presentation") != "all" else len(normal)
                for index, item in enumerate(normal[:limit]):
                    _item_card(item, rid, index, session, active, status, allow_complete=kind == "todo")
                if len(normal) > limit:
                    with gr.Accordion(f"查看后续 {len(normal) - limit} 项 · 点击展开", open=False,
                                      key=rid + "-more", preserved_by_key=["open"], elem_classes="cr-item"):
                        for index, item in enumerate(normal[limit:], start=limit):
                            _item_card(item, rid, index, session, active, status, allow_complete=kind == "todo")
                for group_title, group, suffix in (("用户自述已完成 · 不代表已核验", done, "done"),
                                                    ("历史及隔离资料 · 不列入当前义务", pending, "isolated")):
                    if group:
                        with gr.Accordion(group_title, open=False, key=rid + "-" + suffix,
                                          preserved_by_key=["open"], elem_classes="cr-item"):
                            for index, item in enumerate(group):
                                _item_card(item, rid, index, session, active, status, allow_complete=kind == "todo")
            excluded = current.get("excluded", [])
            if excluded:
                with gr.Accordion(f"查看已隔离的 {len(excluded)} 条记录与原因", open=False,
                                  key=rid + "-excluded", preserved_by_key=["open"], elem_classes="cr-item"):
                    for index, item in enumerate(excluded):
                        _item_card(item, rid, index, session, active, status)
            options = current.get("options", [])
            if options:
                with gr.Row(elem_classes="cr-actions"):
                    for option in options[:3]:
                        button = gr.Button(option.get("label", "补充条件"))
                        button.click(lambda s, o=option: submit_message(o.get("text", ""), s, o.get("action")),
                                     inputs=session, outputs=outputs, show_progress="minimal",
                                     concurrency_id="conversation", concurrency_limit=1)
            actions = current.get("actions", []) if kind == "capabilities" else current.get("actions", [])[:3]
            if actions:
                gr.Markdown("**接下来可以** · 点击打开，或直接输入你的问题")
                with gr.Row(elem_classes="cr-actions"):
                    for action in actions:
                        if isinstance(action, str):
                            action = {"action": action, "label": action}
                        action_kind = action.get("action") or action.get("kind")
                        button = gr.Button(action.get("label", "继续查看"), key=rid + "-action-" + str(action_kind))
                        button.click(lambda s, a=action_kind: submit_message("", s, a), inputs=session,
                                     outputs=outputs, show_progress="minimal", concurrency_id="conversation", concurrency_limit=1)

        with gr.Accordion("调整业务摘要与查询条件 · 也可以直接打字纠正", open=False,
                          visible=False, elem_id="cr-settings") as settings:
            gr.Markdown("只修改需要改变的条件；留空的选项保留当前理解。平台未选也能查询法规。")
            with gr.Row():
                category = gr.Dropdown(corpus.SUPPORTED_CATEGORIES, value=None, label="商品类目")
                market = gr.Dropdown(list(corpus.SUPPORTED_MARKETS), value=None, label="法规市场")
                country = gr.Dropdown(["德国", "法国", "意大利", "西班牙", "美国", "未确定"], value=None, label="销售国家")
            with gr.Row():
                platform = gr.Dropdown(["亚马逊", "未选择平台／仅法规"], value=None, label="平台")
                fulfillment = gr.Dropdown(["FBA", "自行发货", "未确定"], value=None, label="履约方式")
                stage = gr.Dropdown(["尚未开始", "准备中", "准备上架", "已销售"], value=None, label="准备阶段")
            with gr.Row():
                window = gr.Radio(m2_timeline.WINDOW_CHOICES, value=m2_timeline.DEFAULT_WINDOW, label="时间线窗口")
                markets = gr.CheckboxGroup(list(corpus.SUPPORTED_MARKETS), value=list(corpus.SUPPORTED_MARKETS), label="对比／汇总／上线准备市场")
                use_model = gr.Checkbox(value=False, label="使用已配置模型理解输入", interactive=llm.config_summary()["ready"])
            apply_context = gr.Button("应用条件并更新当前结果", size="sm")

        with gr.Accordion("查看历史结果 · 保留当时条件", open=False, visible=False, elem_id="cr-history") as history_panel:
            history = gr.Dropdown(choices=[], value=None, label="历史结果", interactive=True)
            history_btn = gr.Button("打开选中的结果", size="sm")

        export_btn = gr.Button("生成当前结果的导出文件", size="sm", visible=False)
        download = gr.DownloadButton("下载这份结果", visible=False)
        with gr.Column(elem_id="cr-composer"):
            with gr.Column(elem_id="cr-composer-inner"):
                text = gr.Textbox(value="", lines=2, max_lines=5, label="你的问题", show_label=False,
                                  placeholder="例如：我想把毛绒玩具卖到德国亚马逊，需要先准备什么？",
                                  elem_id="cr-input", max_length=6000)
                with gr.Row(elem_id="cr-composer-tools"):
                    gr.HTML('<div class="cr-input-hint">Enter 发送 · Shift + Enter 换行</div>')
                    send = gr.Button("发送 ↑", variant="primary", scale=0, elem_id="cr-send")
            with gr.Accordion("更多功能 · 查看全部 7 项能力", open=False, elem_id="cr-discover"):
                gr.Markdown("选择一项打开；助手会复用当前业务信息，缺少条件时再询问。")
                capability_buttons = []
                for offset in range(0, len(CAPABILITIES), 2):
                    with gr.Row(elem_classes="cr-capability-row"):
                        for action, title, description in CAPABILITIES[offset:offset + 2]:
                            capability_buttons.append((gr.Button(title + "\n" + description), action))
                journey_btn = gr.Button("德国亚马逊六阶段路线 · 查看各阶段任务与资料缺口", size="sm")

        with gr.Accordion("语音输入 · 转写后确认再发送", open=False, elem_id="cr-voice"):
            enabled = bool(asr.config_summary().get("enabled"))
            gr.Markdown("尽量靠近麦克风说完整短句，核对产品名称、国家和数字后再发送。" if enabled else "当前环境语音服务未启用；可以继续使用文字。管理员配置后此入口自动启用。")
            audio = gr.Audio(sources=["microphone", "upload"], type="filepath", format="wav",
                             label="录音或音频（最长60秒）", interactive=enabled)
            voice_btn = gr.Button("转写到输入框", interactive=enabled, size="sm")
        with gr.Accordion("资料覆盖、来源与条款检索", open=False, elem_id="cr-coverage"):
            gr.Markdown(snapshot.DISCLAIMER)
            gr.Markdown("现有法规目录支持欧盟、美国及五类商品；德国亚马逊六阶段路线为首期重点。其他范围不保证相同深度。\n\n"
                        "目录标记、机器读取与用户自述均不等于商品已合规。请在每项结果旁查看适用条件、证据状态及缺口。\n\n"
                        "会话业务状态默认保存在服务内存，不写入原始对话日志；网页录音与导出使用临时文件。模型理解可能发送输入文字，云端语音会发送录音。请勿输入客户敏感资料。")
            gr.Markdown("数据快照：" + _md(snapshot.SNAPSHOT_VERSION) + " · 截止：" + _md(snapshot.DATA_CUTOFF) +
                        "\n\n条款检索状态：" + _md(law_store.status().get("reason")))
            clause_id = gr.Textbox(label="按法规编号检索条款", placeholder="如 16 CFR Part 1250")
            clause_heading = gr.Textbox(label="条款标题关键词（可选）")
            clause_btn = gr.Button("检索已有条款", size="sm")
            clause_out = gr.Markdown()
        gr.HTML('<div class="cr-footer">有来源，有边界。帮助你准备下一步，不构成法律意见。 · ' + BUILD_VERSION + '</div>')

        outputs = [session, active, chat, welcome, examples, context, text, status, download, settings, history]
        # Attach a single service to both typed requests and every visible action.
        common = dict(inputs=[text, session], outputs=outputs, show_progress="minimal",
                      concurrency_id="conversation", concurrency_limit=1, trigger_mode="always_last")
        send.click(submit_message, **common)
        text.submit(submit_message, **common)
        reset.click(reset_session, outputs=outputs, show_progress="hidden",
                    concurrency_id="conversation", concurrency_limit=1)
        for button, value in ((example_1, "我想把毛绒玩具卖到德国亚马逊，从哪里开始？"),
                              (example_2, "儿童玩具卖到欧盟，先看相关法规"),
                              (example_3, "比较欧盟和美国的儿童玩具法规目录")):
            button.click(lambda s, q=value: submit_message(q, s), inputs=session, outputs=outputs,
                         show_progress="minimal", concurrency_id="conversation", concurrency_limit=1)
        for button, action in capability_buttons + [(journey_btn, "journey")]:
            button.click(lambda s, a=action: submit_message("", s, a), inputs=session, outputs=outputs,
                         show_progress="minimal", concurrency_id="conversation", concurrency_limit=1)
        export_btn.click(prepare_export, inputs=[session, active], outputs=[download, status], show_progress="minimal")
        voice_btn.click(transcribe, inputs=[audio, text], outputs=[text, status], concurrency_id="asr", concurrency_limit=1)
        audio.stop_recording(transcribe, inputs=[audio, text], outputs=[text, status], concurrency_id="asr", concurrency_limit=1)

        def update_conditions(current_state, cat, mkt, nation, sales_platform, delivery, preparation, time_window, regions, model):
            updated = deepcopy(current_state or conversation.new_session())
            ctx = updated["context"]
            if cat and cat != ctx.get("category"):
                # Product-specific evidence cannot carry into another category.
                for name in ("age", "electric", "conditions", "completed", "materials", "reports"):
                    ctx.pop(name, None)
                ctx["product"] = cat
                ctx["stage"] = preparation or "尚未开始"
            for name, value in (("category", cat), ("market", mkt), ("country", nation),
                                ("platform", sales_platform), ("fulfillment", delivery), ("stage", preparation)):
                if value:
                    ctx[name] = value
            if mkt == "美国":
                ctx.update(country="美国", site="美国站" if ctx.get("platform") == "亚马逊" else "")
            elif nation == "德国":
                ctx.update(market="欧盟", site="德国站" if ctx.get("platform") == "亚马逊" else "")
            elif nation in ("法国", "意大利", "西班牙"):
                ctx.update(market="欧盟", site=nation + "站" if ctx.get("platform") == "亚马逊" else "")
            elif nation == "未确定":
                ctx.update(country="", site="")
            if sales_platform == "未选择平台／仅法规":
                ctx.update(platform="", site="")
            ctx.update(window=time_window, markets=regions, use_llm=bool(model))
            previous = _result_map(current_state).get(current_state.get("active_result_id"), {})
            return submit_message("", updated, previous.get("kind") if previous.get("kind") in {a for a, _, _ in CAPABILITIES} | {"journey"} else "map")

        apply_context.click(update_conditions, inputs=[session, category, market, country, platform, fulfillment,
                                                       stage, window, markets, use_model], outputs=outputs,
                            show_progress="minimal", concurrency_id="conversation", concurrency_limit=1)
        def result_controls(r, selection, state):
            choices = ["全部", "待确认", "法律法规", "平台规则", "操作建议"] if r and r.get("kind") == "journey" else ["全部", "待确认"]
            ctx = (state or {}).get("context", {})
            nation = ctx.get("country") or ("美国" if ctx.get("market") == "美国" else None)
            sales_platform = ctx.get("platform") or None
            delivery = ctx.get("fulfillment") or None
            return (gr.update(visible=bool(r and r.get("items")), choices=choices,
                              value=selection if selection in choices else "全部"),
                    gr.update(visible=bool(r and r.get("kind") not in ("question", "message", "capabilities", "unsupported", "error"))),
                    gr.update(visible=bool(r)), gr.update(value=ctx.get("category") or None),
                    gr.update(value=ctx.get("market") or None),
                    gr.update(value=nation, choices=list(dict.fromkeys(["德国", "法国", "意大利", "西班牙", "美国", "未确定"] + ([nation] if nation else [])))),
                    gr.update(value=sales_platform, choices=list(dict.fromkeys(["亚马逊", "未选择平台／仅法规"] + ([sales_platform] if sales_platform else [])))),
                    gr.update(value=delivery, choices=list(dict.fromkeys(["FBA", "自行发货", "未确定"] + ([delivery] if delivery else [])))),
                    gr.update(value=ctx.get("stage") or None),
                    gr.update(value=ctx.get("window") or m2_timeline.DEFAULT_WINDOW),
                    gr.update(value=ctx.get("markets", [])), gr.update(value=bool(ctx.get("use_llm"))))

        active.change(result_controls, inputs=[active, result_filter, session],
                      outputs=[result_filter, export_btn, history_panel, category, market, country,
                               platform, fulfillment, stage, window, markets, use_model], queue=False)

        def history_options(state):
            results = _result_map(state)
            return gr.update(choices=[(item.get("title", "结果") + " · " + str(rid)[:8], rid)
                                      for rid, item in results.items()], value=None)

        session.change(history_options, inputs=session, outputs=history, queue=False)

        def open_history(rid, state):
            found = _result_map(state).get(rid)
            return (found or gr.skip()), ("正在查看历史结果；记录进度与导出会校验当时条件。" if found else "请先选择一份历史结果。")

        history_btn.click(open_history, inputs=[history, session], outputs=[active, status],
                          show_progress="hidden", concurrency_id="conversation", concurrency_limit=1)

        def search_clauses(identifier, heading):
            result = law_store.retrieve(identifier or "", heading or "")
            text_parts = [_md(result.get("reason", ""))]
            for unit in result.get("units", []):
                text_parts.append("**" + _md(unit.get("heading") or unit.get("locator")) + "**\n\n" +
                                  _md(unit.get("body")) + "\n\n" + _md(unit.get("parse_status")))
            return "\n\n".join(text_parts)

        clause_btn.click(search_clauses, inputs=[clause_id, clause_heading], outputs=clause_out)
        # Bind initialization to the component-ready event; the launch-time
        # hook did not run reliably before the controls appeared in 6.2.
        demo.load(fn=None, js=JS, queue=False)
    return demo
