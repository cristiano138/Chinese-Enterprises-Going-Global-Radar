# -*- coding: utf-8 -*-
"""
链路自检脚本 —— 验证「能不能连上魔搭模型」

用法：
    在当前目录打开终端，执行：
        python test_connection.py

    或者在文件资源管理器里直接双击 run_test.bat

预期结果：
    屏幕打印出模型的中文回复，最后出现「链路打通」字样。
"""

import os
import sys

# ── 让中文在 Windows 控制台正常显示 ──────────────────────────────
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("MODEL_API_TOKEN", "").strip()
BASE = os.getenv("MODEL_API_BASE", "").strip()
MODEL = os.getenv("MODEL_NAME", "").strip()

LINE = "=" * 58


def fail(title, detail):
    print()
    print(LINE)
    print(f"[X] {title}")
    print(LINE)
    print(detail)
    print()
    input("按回车键关闭窗口...")
    sys.exit(1)


print(LINE)
print("  出海合规雷达 —— 模型链路自检")
print(LINE)
print()

# ── 检查 0：配置文件是否存在 ────────────────────────────────────
if not TOKEN:
    fail(
        "没找到 MODEL_API_TOKEN",
        "请确认当前目录下存在 .env 文件，且其中一行是：\n"
        "    MODEL_API_TOKEN=ms-xxxxxxxxxxxx\n\n"
        "注意：文件名必须精确等于 .env（不是 .env.example，也不能是 .env.txt）",
    )

if TOKEN == "your_token_here":
    fail(
        "Token 还是模板里的占位文字",
        "请把 .env 里的 MODEL_API_TOKEN 换成你在魔搭「访问令牌」页面生成的真实值。",
    )

# ── 检查 1：Token 长相对不对 ────────────────────────────────────
masked = TOKEN[:11] + "*" * 8 + TOKEN[-4:] if len(TOKEN) > 20 else TOKEN
print(f"  接口地址 : {BASE}")
print(f"  模型名称 : {MODEL}")
print(f"  Token    : {masked}")
print()

if not TOKEN.startswith("ms-"):
    print("  [!] 提示：魔搭的 Token 通常以 ms- 开头，你这个不是。")
    print("      如果后面报 401 错误，回去检查是不是复制错了。")
    print()

# ── 检查 2：依赖库有没有装 ──────────────────────────────────────
try:
    from openai import OpenAI
except ImportError:
    fail(
        "缺少 openai 这个库",
        "请在终端里执行下面这一行，装完再重新运行：\n"
        "    pip install openai python-dotenv",
    )

# ── 检查 3：真正发一次请求 ──────────────────────────────────────
print("  正在向模型发问，请稍候（推理模型，通常 5~35 秒）...")
print()

client = OpenAI(api_key=TOKEN, base_url=BASE, timeout=60)

QUESTION = "请用一句中文回答：如果你收到这条消息，就回复『链路已打通』。"
print(f"  [提问] {QUESTION}")
print()

try:
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": QUESTION}],
        temperature=0.1,
        # ⚠️ 必须给足 8000+：实测 DeepSeek-V4.1-Flash 是推理模型，
        #    思考过程可达 10000+ 字符（思考/答案比约 160:1）。
        #    给 2500 会直接返回空字符串，给 8000 才稳定拿到答案。
        max_tokens=8000,
    )
except Exception as e:
    msg = str(e)
    hint = ""
    if "401" in msg or "Unauthorized" in msg or "authentication" in msg.lower():
        hint = (
            "\n\n可能原因：Token 无效或已过期。\n"
            "  解决：去魔搭「头像 → 访问令牌」重新生成一个，替换 .env 里的值。"
        )
    elif "403" in msg or "real-name" in msg or "verified" in msg:
        hint = (
            "\n\n可能原因：阿里云账号还没实名认证。\n"
            "  解决：打开 https://www.modelscope.cn/my/accountsettings 完成实名。"
        )
    elif "bind" in msg.lower() or "Aliyun account" in msg:
        hint = (
            "\n\n可能原因：还没绑定阿里云账号。\n"
            "  解决：魔搭「个人中心 → 账号设置」里绑定阿里云账号。"
        )
    elif "has no provider supported" in msg:
        hint = (
            "\n\n可能原因：这个模型名魔搭现在已经不提供了。\n"
            "  解决：运行 list_models.py 查看当前可用模型，把名字填进 .env。"
        )
    elif "404" in msg or "not found" in msg.lower():
        hint = (
            "\n\n可能原因：模型名称写错了。\n"
            "  解决：检查 .env 里的 MODEL_NAME，确认模型在魔搭上确实存在。"
        )
    elif "timeout" in msg.lower() or "timed out" in msg.lower():
        hint = "\n\n可能原因：网络超时。\n  解决：检查网络连接，或稍后重试。"
    fail("调用失败", f"原始错误信息：\n{msg}{hint}")

answer = (resp.choices[0].message.content or "").strip()

if not answer:
    reasoning = getattr(resp.choices[0].message, "reasoning_content", "") or ""
    fail(
        "模型返回了空内容",
        f"模型确实被调用了（消耗 {getattr(resp.usage, 'total_tokens', '?')} tokens），"
        "但 content 字段是空的。\n\n"
        "最常见原因：max_tokens 给小了，推理模型的思考过程把额度用完了。\n"
        f"  当前脚本设置：max_tokens=8000（实测思考过程可达 10000+ 字符）\n"
        f"  模型思考内容前 200 字：{reasoning[:200]}\n\n"
        "如果反复出现，把 .env 里的 MODEL_NAME 换成一个非推理模型试试。",
    )

print("  [回答] " + answer)
print()
print("  Token 消耗：", getattr(resp.usage, "total_tokens", "未知"), "tokens")
print()
print(LINE)
print("  [OK] 链路打通！")
print(LINE)
print()
print("  说明：代码已经能正常调用魔搭模型了。")
print("        下一步就可以让模型开始干正经活了 ——")
print("        读法规、归类、写摘要。")
print()
input("按回车键关闭窗口...")
