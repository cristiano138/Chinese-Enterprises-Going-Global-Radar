# -*- coding: utf-8 -*-
"""
查看魔搭当前可用的模型清单

用途：
    当 .env 里的 MODEL_NAME 报错「has no provider supported」时，
    双击本文件（或运行 list_models.bat），看看现在有哪些模型可用，
    然后把想要的名字填回 .env 的 MODEL_NAME。
"""

import os
import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

TOKEN = os.getenv("MODEL_API_TOKEN", "").strip()
BASE = os.getenv("MODEL_API_BASE", "").strip()

if not TOKEN:
    print("[X] 没读到 MODEL_API_TOKEN，检查 .env 文件是否存在。")
    input("按回车键关闭...")
    sys.exit(1)

from openai import OpenAI

client = OpenAI(api_key=TOKEN, base_url=BASE, timeout=60)

try:
    models = client.models.list()
except Exception as e:
    print("[X] 获取模型列表失败：", type(e).__name__)
    print(str(e)[:1000])
    input("按回车键关闭...")
    sys.exit(1)

ids = sorted(m.id for m in models.data)

print("=" * 58)
print(f"  魔搭当前可用模型（共 {len(ids)} 个）")
print("=" * 58)
print()
for i in ids:
    print("  ", i)
print()
print("  推荐用于法规理解任务：")
for i in ids:
    low = i.lower()
    if "deepseek" in low or "qwen3" in low or "glm" in low:
        print("     ->", i)
print()
input("按回车键关闭...")
