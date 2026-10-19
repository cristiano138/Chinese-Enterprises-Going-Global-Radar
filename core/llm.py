# -*- coding: utf-8 -*-
"""
大模型接入（core/llm.py）

分工铁律（README「AI 与确定性代码的分工」）：
    LLM 只做「理解、归类、摘要、翻译」四件事。
    抓取、URL 校验、引用对齐、缓存去重 —— 全部由确定性代码完成，
    绝不交给概率模型。

因此本模块的定位很窄：
    把**已经确定的**法规数据组织成中文表达，不负责判断「有哪些法规」。
    硬约束：只能使用给定内容，不得补充自行「知道」的法规。

降级设计（README「这套设计的额外好处」）：
    即使模型调用失败或配额耗尽，程序依然能输出原始法规清单
    （只是没有中文润色）—— 演示不会因 API 问题而中断。
"""

import hashlib
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
CACHE_DIR = os.path.join(PROJECT, "data", "cache")


def _env_float(name, default):
    try:
        v = float(os.getenv(name, "").strip() or default)
        return v if v > 0 else default
    except Exception:
        return default


def _env_int(name, default):
    try:
        v = int(float(os.getenv(name, "").strip() or default))
        return v if v > 0 else default
    except Exception:
        return default


# ── 缓存治理默认值（可用环境变量覆盖，不改 DeepSeek 三件套配置）──────
# 过期时间：默认 7 天。法规口径与提示词都会变，长期复用旧文本风险高于省下的额度。
CACHE_TTL_SECONDS = _env_float("LLM_CACHE_TTL_SECONDS", 7 * 24 * 3600)
# 条目上限：防止缓存目录无限增长
CACHE_MAX_FILES = _env_int("LLM_CACHE_MAX_FILES", 512)
# 单条上限：防止异常长文本撑爆磁盘（200KB）
CACHE_MAX_BYTES = _env_int("LLM_CACHE_MAX_BYTES", 200 * 1024)
# 单次调用总预算（秒）：超时即降级，不让用户干等
DEFAULT_TIMEOUT = _env_float("LLM_TIMEOUT_SECONDS", 45)
# 同时在途调用上限：等于超时线程池大小，避免无界排队
MAX_INFLIGHT = _env_int("LLM_MAX_INFLIGHT", 4)
# 缓存键格式版本：结构变更时整体失效，避免新旧格式互相误读
CACHE_VERSION = "v2"


def _load_env():
    """读取 .env（若存在）。没有 python-dotenv 也不阻塞。"""
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(PROJECT, ".env"), override=True)
    except Exception:
        # 退化为手写解析，保证「没有第三方库也能跑」
        env_path = os.path.join(PROJECT, ".env")
        if os.path.exists(env_path):
            with open(env_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())


_load_env()

TOKEN = os.getenv("MODEL_API_TOKEN", "").strip()
BASE = os.getenv("MODEL_API_BASE", "").strip().rstrip("/")
MODEL = os.getenv("MODEL_NAME", "").strip()

# 明确的「未就绪」标记，供上层做降级判断
READY = bool(TOKEN and BASE and MODEL) and TOKEN != "your_token_here"

_client = None


def is_ready():
    """模型链路是否可用（Token / Base / Model 三项齐全）。"""
    return READY


def _thinking_capable():
    """只有推理类模型才接受 thinking=enabled；普通对话模型必须关闭。"""
    name = (MODEL or "").casefold()
    return any(tag in name for tag in ("reasoner", "-r1", "thinking", "reasoning"))


def config_summary():
    """给界面展示的非敏感配置摘要（**不泄露 Token**）。"""
    return {
        "ready": READY,
        "base": BASE or "（未配置）",
        "model": MODEL or "（未配置）",
        "token": "已配置" if (TOKEN and TOKEN != "your_token_here") else "未配置",
    }


def _client_get():
    global _client
    if _client is None:
        from openai import OpenAI
        # max_retries=0：SDK 默认自带重试会把一次慢请求放大成多次，
        # 与本模块自己的超时预算叠加，反而更难在预算内返回/降级。
        _client = OpenAI(api_key=TOKEN, base_url=BASE, timeout=120, max_retries=0)
    return _client


# ── 缓存：高频调用结果缓存，省额度、免重复计费（README 2.1.6）──────────
def cache_key(prompt, max_tokens, temperature, thinking):
    """计算缓存键。

    只纳入**非敏感**模型配置：服务地址、模型名、生成参数、思考开关与格式版本。
    **绝不写入 Token**（下同），避免凭据落盘。
    早期实现只按提示词取键，导致换模型/换参数后仍返回旧文本（配置表面改了实际没生效）。
    """
    payload = json.dumps({
        "v": CACHE_VERSION,
        "prompt": prompt,
        "base": BASE,
        "model": MODEL,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "thinking": bool(thinking),
    }, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _cache_path(key):
    return os.path.join(CACHE_DIR, f"llm_{key}.json")


def _cache_get(key, ttl=None):
    """读缓存。任何故障（目录不可建、文件损坏、过期）都按「未命中」处理，
    绝不向上抛异常 —— 缓存是优化，不能成为主链路的单点故障。"""
    ttl = CACHE_TTL_SECONDS if ttl is None else ttl
    try:
        p = _cache_path(key)
        if not os.path.exists(p):
            return None
        if ttl and (time.time() - os.path.getmtime(p)) > ttl:
            # 过期即弃用，不让旧结论冒充新结果
            try:
                os.remove(p)
            except Exception:
                pass
            return None
        with open(p, encoding="utf-8") as f:
            val = json.load(f).get("text")
        return val if isinstance(val, str) and val.strip() else None
    except Exception:
        return None


def _cache_put(key, text, max_files=None, max_bytes=None):
    """写缓存：原子落盘 + 单条尺寸上限 + 目录条目上限（按最旧优先淘汰）。"""
    max_files = CACHE_MAX_FILES if max_files is None else max_files
    max_bytes = CACHE_MAX_BYTES if max_bytes is None else max_bytes
    try:
        if len((text or "").encode("utf-8")) > max_bytes:
            return
        os.makedirs(CACHE_DIR, exist_ok=True)
        p = _cache_path(key)
        tmp = f"{p}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"text": text, "ts": time.time()}, f, ensure_ascii=False)
        os.replace(tmp, p)  # 原子替换：并发下不会读到写了一半的文件
        _cache_enforce_limit(max_files)
    except Exception:
        pass


def _cache_enforce_limit(max_files):
    try:
        names = [n for n in os.listdir(CACHE_DIR)
                 if n.startswith("llm_") and n.endswith(".json")]
        if len(names) <= max_files:
            return
        paths = [(os.path.getmtime(os.path.join(CACHE_DIR, n)), n) for n in names]
        paths.sort()
        for _, n in paths[:len(paths) - max_files]:
            try:
                os.remove(os.path.join(CACHE_DIR, n))
            except Exception:
                pass
    except Exception:
        pass


def _call_api(prompt, max_tokens, temperature, thinking=True, http_timeout=None):
    """实际发起一次模型请求（同步阻塞）。抽出来便于外层加硬超时。

    DeepSeek 思考模式开关：通过 extra_body={"thinking": {"type": "enabled/disabled"}}
    控制思维链输出（OpenAI 兼容格式，见官方文档「思考模式开关与思考强度控制」）。
    thinking 参数由调用方（chat()）按场景决定——
    主模型（M1/M2/M3 润色）默认开启；M1.5 路由层单独关闭（见 m15_router.py）。

    http_timeout：把外层剩余预算传到底层 HTTP，避免「外层已放弃、底层还在慢慢重连」。
    """
    kwargs = dict(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        temperature=temperature,
        extra_body={"thinking": {"type": "enabled" if thinking else "disabled"}},
    )
    if http_timeout:
        # 留出一点余量，让外层 FuturesTimeout 先触发，返回可控的降级文案
        kwargs["timeout"] = max(1.0, http_timeout - 1.0)
    resp = _client_get().chat.completions.create(**kwargs)
    return resp.choices[0].message.content or ""


# ── 超时执行器（全局单例）─────────────────────────────────────────
# 早期实现每次带 timeout 的调用都新建一个 ThreadPoolExecutor(max_workers=1)，
# 超时后 shutdown(wait=False) 把线程丢在后台继续跑（HTTP 请求无法强杀）。
# 于是「每超时一次就泄漏一个线程 + 一个执行器」，长时间运行的 Web 服务里
# 会越积越多。改为全局复用一个小池：线程本来就要等请求自己结束，复用一个池
# 既不增加泄漏面，也省掉反复创建/销毁的开销。
_TIMEOUT_POOL = None
_TIMEOUT_POOL_LOCK = threading.Lock()


def _timeout_pool():
    global _TIMEOUT_POOL
    if _TIMEOUT_POOL is None:
        with _TIMEOUT_POOL_LOCK:
            if _TIMEOUT_POOL is None:
                _TIMEOUT_POOL = ThreadPoolExecutor(
                    max_workers=MAX_INFLIGHT, thread_name_prefix="llm-timeout")
    return _TIMEOUT_POOL


# 在途计数：线程池的等待队列是无界的，慢模型期间新请求会一直排队，
# 排到超时才失败 —— 对调用方表现为「整个功能卡住」。
# 这里做准入：池满就直接返回降级结果，不再递交注定排不到执行的任务。
_INFLIGHT = 0
_INFLIGHT_LOCK = threading.Lock()


def _acquire_slot():
    global _INFLIGHT
    with _INFLIGHT_LOCK:
        if _INFLIGHT >= MAX_INFLIGHT:
            return False
        _INFLIGHT += 1
        return True


def _release_slot():
    global _INFLIGHT
    with _INFLIGHT_LOCK:
        _INFLIGHT = max(0, _INFLIGHT - 1)


def chat(prompt, max_tokens=4000, temperature=0.2, use_cache=True, timeout=None,
         thinking=None):
    """调用模型。返回 (text, meta)。

    meta 说明调用是否成功、是否命中缓存，供上层如实标注。
    任何异常都不抛出 —— 上层靠 meta 判断并降级。

    timeout（秒，默认 None = 不限）：对整次请求加硬超时。
    客户端自身的 timeout=120 只管单次 socket 读写，而推理模型「慢慢想」
    能在额度内拖满几十秒（实测 26.7s）—— 交互入口（如 M1.5 路由）应传
    一个上限，超时及时降级，不让用户干等。
    超时后被遗弃的线程仍在后台把这次请求跑完（无法强杀 HTTP），结果丢弃。

    thinking（默认 None）：是否开启模型思考模式（思维链）。
    默认按模型名自动判断：推理类模型开启，deepseek-chat 这类对话模型关闭，
    否则部分服务端会返回空内容或截断。M1.5 路由层显式传 thinking=False。
    """
    if not READY:
        return "", {"ok": False, "reason": "模型链路未配置（缺 Token/Base/Model）",
                    "cached": False}

    if thinking is None:
        thinking = _thinking_capable()
    # 未显式指定时套用总预算（默认 45s）。润色是可选增强，
    # 不能因为模型变慢就把确定性清单一起拖住。
    budget = DEFAULT_TIMEOUT if timeout is None else timeout
    key = cache_key(prompt, max_tokens, temperature, thinking)

    if use_cache:
        hit = _cache_get(key)
        if hit is not None:
            return hit, {"ok": True, "reason": "", "cached": True}

    if not _acquire_slot():
        return "", {"ok": False,
                    "reason": f"模型并发已满（上限 {MAX_INFLIGHT}），已跳过润色",
                    "cached": False, "busy": True}
    try:
        if budget:
            fut = _timeout_pool().submit(
                _call_api, prompt, max_tokens, temperature, thinking, budget)
            try:
                text = fut.result(timeout=budget)
            finally:
                fut.cancel()   # 尚未开始跑就撤掉；已在跑则等它自己结束
        else:
            text = _call_api(prompt, max_tokens, temperature, thinking)
        if not text.strip():
            # 推理模型 token 给少了的典型症状：返回空
            return "", {"ok": False, "reason": "模型返回空内容（可能 max_tokens 不足）",
                        "cached": False}
        if use_cache:
            _cache_put(key, text)
        return text, {"ok": True, "reason": "", "cached": False}
    except FuturesTimeout:
        return "", {"ok": False,
                    "reason": f"模型响应超过 {budget}s，已及时降级",
                    "cached": False, "timeout": True}
    except Exception as e:
        return "", {"ok": False,
                    "reason": f"{type(e).__name__}: {str(e)[:160]}",
                    "cached": False}
    finally:
        _release_slot()


# ── M1 专用提示词 ────────────────────────────────────────────────
M1_PROMPT = """你是跨境电商合规助理。下面给出的是**已经从官方数据库检索到的**
法规条目（编号、官方英文标题、中文名、作用说明、链接、生效日期、现行效力）。

请为每条法规写一段**给卖家看的中文说明**，帮助他快速理解这条法规管什么。

【不可违反的硬约束】
1. 只允许使用下面给出的内容。**不得补充任何你认为「应该还有」的法规**。
2. **不得修改、推断或新增**任何法规编号、日期、链接 —— 这些是事实，一律照抄。
3. 如果某条信息下面没有给出（例如缺日期），就写「官方未标注」，**不要猜**。
4. 语气务实，不用营销腔，不承诺「保证合规」。

【输出格式】
严格每条一行，用 ||| 分隔，不要 markdown 表格，不要加解释：
编号|||一句话卖家提示（40 字以内）

法规条目：
{items}
"""


def build_m1_items(rows):
    """把语料记录拍平成提示词里的条目文本。"""
    lines = []
    for r in rows:
        key = r.get("CELEX号") or r.get("官方编号")
        lines.append(
            f"{key}|||{r.get('法规中文名','')}|||{r.get('官方标题（英文）','')}"
            f"|||{r.get('现行效力','')}|||{r.get('生效日期','') or '官方未标注'}"
        )
    return "\n".join(lines)


def parse_keyed_lines(text):
    """解析「编号|||内容」格式 → {编号: 内容}。"""
    out = {}
    for line in (text or "").splitlines():
        line = line.strip().lstrip("-•* ").strip()
        if "|||" not in line:
            continue
        parts = [p.strip() for p in line.split("|||")]
        if len(parts) < 2:
            continue
        key = parts[0].strip().strip("`* ")
        val = "|||".join(parts[1:]).strip()
        if key and val:
            out[key] = val
    return out


def m1_tips(rows):
    """M1 的可选润色步骤：给每条法规生成一句话卖家提示。

    返回 (tips_dict, meta)。模型不可用时 tips_dict 为空 ——
    上层照常输出原始清单，只是没有这句提示。
    """
    if not rows:
        return {}, {"ok": True, "reason": "无条目", "cached": False}
    prompt = M1_PROMPT.format(items=build_m1_items(rows))
    text, meta = chat(prompt, max_tokens=4000)
    if not meta["ok"]:
        return {}, meta
    return parse_keyed_lines(text), meta


# ── 通用解析：三列（键|||A|||B）────────────────────────────────
def parse_keyed_triples(text):
    """解析「键|||A|||B」格式 → {键: (A, B)}。

    多余的分段并入 B（模型偶尔会多吐一段），不因此丢行。
    """
    out = {}
    for line in (text or "").splitlines():
        line = line.strip().lstrip("-•* ").strip()
        if "|||" not in line:
            continue
        parts = [p.strip() for p in line.split("|||")]
        if len(parts) < 3:
            continue
        key = parts[0].strip("`* ")
        a = parts[1].strip()
        b = "|||".join(parts[2:]).strip()
        if key and (a or b):
            out[key] = (a, b)
    return out


# ── M2 专用提示词：变化摘要 + 影响说明 ───────────────────────────
M2_PROMPT = """你是跨境电商合规助理。下面是**已经从官方数据库检索到的**法规变化事件
（事件键、事件类型、日期、法规名、官方编号、事件说明）。

请为每条事件写两段给卖家看的中文：
1. 变化摘要 —— 发生了什么（25 字以内，不要重复法规名，不要复述日期）
2. 影响说明 —— 对卖家意味着什么、要关注什么（40 字以内）

【不可违反的硬约束】
1. 只允许使用下面给出的内容。**不得补充任何你认为「应该还有」的法规或日期**。
2. **不得修改、推断或新增**任何法规编号、日期、链接 —— 一律照抄。
3. **不得预测未来**，不得出现「将会」「预计」这类推断（除非事件本身日期在未来）。
4. 信息不足就写「官方未说明」，**不要猜**。语气务实，不承诺「保证合规」。

【输出格式】
严格每条一行，用 ||| 分隔，不要 markdown 表格，不要加解释：
事件键|||变化摘要|||影响说明

事件列表：
{items}
"""


def build_m2_items(events):
    """把事件拍平成提示词条目。**只给事实字段，不给模型任何发挥空间。**"""
    lines = []
    for e in events:
        lines.append("|||".join([
            e["event_key"],
            e["事件类型"],
            e["日期"],
            e.get("法规中文名", ""),
            e.get("官方编号", ""),
            (e.get("备注") or "无补充说明"),
        ]))
    return "\n".join(lines)


def m2_summaries(events):
    """M2 的可选润色：为每条事件生成 (变化摘要, 影响说明)。

    返回 ({event_key: (摘要, 影响)}, meta)。模型不可用时返回空字典 ——
    上层用确定性摘要顶上，时间线照样完整。
    """
    if not events:
        return {}, {"ok": True, "reason": "无条目", "cached": False}
    prompt = M2_PROMPT.format(items=build_m2_items(events))
    text, meta = chat(prompt, max_tokens=4000)
    if not meta["ok"]:
        return {}, meta
    return parse_keyed_triples(text), meta


# ── M3 专用提示词：法规语言 → 可执行动作 ────────────────────────
M3_PROMPT = """你是跨境电商合规助理。下面是**已经从官方数据库核验过的**法规义务
（法规键、法规名、官方编号、义务说明）。

请把每条义务改写成**一条可执行动作**：动词开头，说清「做什么」，
像给同事派活一样，20 字以内的短句。

【不可违反的硬约束】
1. **只能依据**下面给出的义务说明改写，**不得新增要求、不得扩大适用范围**。
2. **不得推荐**任何具体服务商、实验室品牌、产品或第三方机构。
3. **不得承诺**「保证合规」，不得编造时限（下面没给的期限不要写）。
4. 拿不准就照抄义务说明 —— **宁可啰嗦，也不要自行发挥**。

【输出格式】
严格每条一行，用 ||| 分隔，不要 markdown 表格，不要加解释：
法规键|||可执行动作

义务列表：
{items}
"""


def build_m3_items(actions):
    """把动作候选拍平成提示词条目（包含确定性回退文本，供模型改写）。"""
    lines = []
    for a in actions:
        lines.append("|||".join([
            a["key"],
            a.get("依据法规", ""),
            a.get("官方编号", ""),
            a.get("动作", ""),
        ]))
    return "\n".join(lines)


def m3_actions(actions):
    """M3 的可选润色：把义务说明改写成可执行动作。

    返回 ({key: 动作文本}, meta)。模型不可用时返回空字典 ——
    上层直接用 core/actions.py 抽好的确定性文本，条条有依据。
    """
    if not actions:
        return {}, {"ok": True, "reason": "无条目", "cached": False}
    prompt = M3_PROMPT.format(items=build_m3_items(actions))
    text, meta = chat(prompt, max_tokens=4000)
    if not meta["ok"]:
        return {}, meta
    return parse_keyed_lines(text), meta
