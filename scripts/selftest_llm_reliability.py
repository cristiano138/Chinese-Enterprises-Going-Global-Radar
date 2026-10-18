# -*- coding: utf-8 -*-
"""
模型调用可靠性回归（scripts/selftest_llm_reliability.py）

只验证 core/llm.py 的可靠性边界，**不打真实模型 API**、不需要 Token。
做法：把底层 HTTP 调用替换成本地桩，控制返回速度与内容。

覆盖：
1. 缓存键隔离 —— 换 Base / Model / 生成参数 / 思考开关必须重新调用，且不写入 Token；
2. 缓存容错 —— 目录不可建、文件损坏时按未命中处理，异常不外抛；
3. 过期与容量 —— 超 TTL 不复用；条目数有上限；单条超限不落盘；
4. 并发准入 —— 池满时快速降级，不无界排队；
5. 超时与恢复 —— 慢模型在预算内降级，恢复后新请求照常成功。
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
sys.path.insert(0, PROJECT)

import core.llm as llm  # noqa: E402

CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


def _reset(tmpdir, **attrs):
    """把每个用例的运行环境重置干净（临时缓存目录 + 已知配置）。"""
    llm.READY = True
    llm.CACHE_DIR = tmpdir
    llm.BASE = "https://api.deepseek.com"
    llm.MODEL = "deepseek-reasoner"
    llm.MAX_INFLIGHT = 4
    llm.CACHE_TTL_SECONDS = 3600
    llm.CACHE_MAX_FILES = 512
    llm.CACHE_MAX_BYTES = 200 * 1024
    llm.DEFAULT_TIMEOUT = None  # 该用例自己控制预算
    for k, v in attrs.items():
        setattr(llm, k, v)


class Stub:
    """记录调用次数、可注入延迟的底层调用桩。"""

    def __init__(self, text="OK|||示例", delay=0.0):
        self.text = text
        self.delay = delay
        self.calls = 0
        self.kwargs_seen = []
        self.lock = threading.Lock()

    def __call__(self, prompt, max_tokens, temperature, thinking=True,
                 http_timeout=None):
        with self.lock:
            self.calls += 1
            self.kwargs_seen.append({
                "max_tokens": max_tokens, "temperature": temperature,
                "thinking": thinking, "http_timeout": http_timeout})
        if self.delay:
            time.sleep(self.delay)
        return self.text


@case("缓存键隔离：相同配置命中缓存，换配置必须重新调用")
def t_cache_key_isolation(tmp):
    stub = Stub()
    llm._call_api = stub
    _reset(tmp)
    text, m = llm.chat("同一句话", timeout=5)
    assert text == "OK|||示例" and m["ok"] and not m["cached"], (text, m)
    text2, m2 = llm.chat("同一句话", timeout=5)
    assert m2["cached"] is True and text2 == text, m2
    calls_after_same = stub.calls
    assert calls_after_same == 1, f"相同配置应命中缓存，实际调用 {calls_after_same} 次"

    for label, kwargs in [
        ("max_tokens", {"max_tokens": 8000}),
        ("temperature", {"temperature": 0.9}),
        ("thinking", {"thinking": False}),
    ]:
        before = stub.calls
        _, mm = llm.chat("同一句话", timeout=5, **kwargs)
        assert mm["cached"] is False, f"{label} 不应命中旧缓存"
        assert stub.calls == before + 1, f"{label} 未触发新调用"

    llm.MODEL = "deepseek-chat"          # 换模型
    before = stub.calls
    _, mm = llm.chat("同一句话", timeout=5)
    assert mm["cached"] is False and stub.calls == before + 1, "换模型未触发新调用"

    llm.BASE = "https://another.example/v1"   # 换服务地址
    before = stub.calls
    _, mm = llm.chat("同一句话", timeout=5)
    assert mm["cached"] is False and stub.calls == before + 1, "换服务地址未触发新调用"

    keyfile = os.path.join(tmp, [n for n in os.listdir(tmp)][0])
    with open(keyfile, encoding="utf-8") as f:
        blob = f.read()
    assert "deepseek" not in blob, "缓存文件不应含模型名等明文"
    return True


@case("缓存键不写入 Token：配置 Token 也不落盘")
def t_no_token_in_cache(tmp):
    stub = Stub()
    llm._call_api = stub
    _reset(tmp)
    try:
        llm.TOKEN = "sk-secret-token-value"
        llm.chat("保密检查", timeout=5)
        for name in os.listdir(tmp):
            with open(os.path.join(tmp, name), encoding="utf-8") as f:
                assert "sk-secret-token-value" not in f.read(), name
    finally:
        pass
    return True


@case("缓存容错：目录不可建时仍能正常返回")
def t_cache_dir_unwritable(tmp):
    stub = Stub()
    llm._call_api = stub
    _reset(tmp)
    real_makedirs = os.makedirs

    def boom(*a, **k):
        raise PermissionError("只读挂载")

    os.makedirs = boom
    try:
        text, meta = llm.chat("不可写场景", timeout=5)
    finally:
        os.makedirs = real_makedirs
    assert meta["ok"] is True and text == "OK|||示例", (text, meta)
    return True


@case("缓存容错：文件内容损坏时按未命中处理并重算")
def t_cache_corrupted(tmp):
    stub = Stub()
    llm._call_api = stub
    _reset(tmp)
    key = llm.cache_key("损坏场景", 4000, 0.2, True)
    os.makedirs(tmp, exist_ok=True)
    with open(llm._cache_path(key), "w", encoding="utf-8") as f:
        f.write("{ 这不是合法 JSON")
    text, meta = llm.chat("损坏场景", timeout=5)
    assert meta["ok"] is True and meta["cached"] is False and text == "OK|||示例", meta
    assert stub.calls == 1, "损坏缓存不应被当作命中"
    _, meta2 = llm.chat("损坏场景", timeout=5)
    assert meta2["cached"] is True, "重算后应重新写入可用缓存"
    return True


@case("缓存治理：过期不复用、容量有上限、单条超限不落盘")
def t_cache_retention(tmp):
    stub = Stub()
    llm._call_api = stub
    _reset(tmp, CACHE_TTL_SECONDS=1, CACHE_MAX_FILES=4)

    llm.chat("过期用例", timeout=5)
    key = llm.cache_key("过期用例", 4000, 0.2, True)
    path = llm._cache_path(key)
    assert os.path.exists(path), "首次结果应落盘"
    old = time.time() - 10
    os.utime(path, (old, old))           # 伪造成过期
    _, meta = llm.chat("过期用例", timeout=5)
    assert meta["cached"] is False, "过期缓存不应命中"
    assert stub.calls == 2, "过期后应重新调用"

    for i in range(10):                   # 写入远超上限的条目
        llm.chat(f"容量用例-{i}", timeout=5)
        time.sleep(0.01)
    left = [n for n in os.listdir(tmp) if n.startswith("llm_") and n.endswith(".json")]
    assert len(left) <= 4, f"缓存条目应有上限，实际 {len(left)}"

    big = "X" * (100 * 1024)             # 单条 100KB，仍在默认限内
    llm.chat(big, timeout=5)
    llm.CACHE_MAX_BYTES = 1024           # 收紧单条上限
    llm.chat("超长内容" + "Y" * 5000, timeout=5)
    oversize = [n for n in os.listdir(tmp)
                if n.startswith("llm_") and os.path.getsize(os.path.join(tmp, n)) > 4096]
    assert not oversize, "超长条目不应落盘"
    return True


@case("并发准入：在途占满后快速降级，不无限排队")
def t_inflight_limit(tmp):
    barrier = threading.Event()

    def slow(prompt, max_tokens, temperature, thinking=True, http_timeout=None):
        barrier.wait(5)
        return "SLOW|||慢"

    llm._call_api = slow
    _reset(tmp, MAX_INFLIGHT=2)
    pool = llm._timeout_pool()
    futures = [pool.submit(llm.chat, f"慢请求-{i}", 4000, 0.2, True, 5)
               for i in range(2)]
    deadline = time.time() + 3
    while time.time() < deadline:
        time.sleep(0.02)
        if llm._INFLIGHT >= 2:
            break
    assert llm._INFLIGHT >= 2, "前置条件：应有两个在途请求"
    text, meta = llm.chat("第三个请求", timeout=5)   # 池满，应立刻降级
    assert meta["ok"] is False and meta.get("busy") is True, meta
    assert time.time() < deadline + 1, "满池请求应快速返回，不应排队等待"
    barrier.set()
    for f in futures:
        f.result(timeout=10)
    assert llm._INFLIGHT == 0, "计数应随请求结束归零"
    return True


@case("超时与恢复：慢模型在预算内降级，恢复后新请求成功")
def t_timeout_and_recovery(tmp):
    def slow(prompt, max_tokens, temperature, thinking=True, http_timeout=None):
        assert http_timeout, "预算必须传到底层 HTTP"
        time.sleep(http_timeout + 5)
        return "LATE|||迟到"

    llm._call_api = slow
    _reset(tmp)
    begin = time.time()
    text, meta = llm.chat("慢模型", timeout=1)
    cost = time.time() - begin
    assert meta["ok"] is False and meta.get("timeout") is True, meta
    assert text == "", text
    assert cost < 6, f"超时应及时返回，实际耗时 {cost:.1f}s"

    llm._call_api = Stub(text="RECOVERED|||已恢复")
    text, meta = llm.chat("恢复后请求", timeout=5)
    assert meta["ok"] is True and text == "RECOVERED|||已恢复", (text, meta)
    return True


def main():
    passed, failed = 0, []
    for name, fn in CASES:
        tmp = tempfile.mkdtemp(prefix="cr_llm_reliability_")
        try:
            fn(tmp)
            passed += 1
            print(f"  PASS  {name}")
        except AssertionError as e:
            failed.append((name, f"断言失败：{e}"))
            print(f"  FAIL  {name}\n        {e}")
        except Exception as e:  # pragma: no cover - 真实异常回显
            failed.append((name, f"{type(e).__name__}: {e}"))
            print(f"  FAIL  {name}\n        {type(e).__name__}: {e}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    print(f"\nLLM 可靠性: {passed}/{len(CASES)} 通过")
    if failed:
        for name, err in failed:
            print(f"  - {name}: {err}")
        return 1
    print("LLM 可靠性: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
