# -*- coding: utf-8 -*-
"""一键准备本地语音引擎（scripts/prepare_asr_engine.py）

做三件事，把「配不通」变成一条命令：
    ① 从 GitHub Releases 取 sherpa-onnx 预编译二进制（按平台自动选包）
    ② 取 SenseVoice int8 模型（中/英/日/韩/粤）
    ③ 落到 <项目>/models/sherpa-onnx/（已在 .gitignore，不会进仓库）

为什么不用 pip：
    项目约束「不引入 Python ASR 库」。引擎是独立的 C++ 可执行文件，
    core/asr_engine.py 只用标准库起子进程。

用法：
    python scripts/prepare_asr_engine.py            # 准备（已就位则秒过）
    python scripts/prepare_asr_engine.py --check    # 只检查，不下载
    python scripts/prepare_asr_engine.py --force    # 强制重新下载
    python scripts/prepare_asr_engine.py --mirror https://内网/前缀   # 换下载源

产物：
    models/sherpa-onnx/bin/sherpa-onnx-offline[.exe]
    models/sherpa-onnx/models/<模型包>/{model.int8.onnx,tokens.txt}
"""

import os
import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)


def main():
    args = sys.argv[1:]
    check_only = "--check" in args
    force = "--force" in args
    if "--mirror" in args:
        index = args.index("--mirror")
        if index + 1 < len(args):
            os.environ["ASR_ENGINE_BASE_URL"] = args[index + 1]

    # 环境变量必须在导入前设好，模块级常量只读一次
    from core import asr_engine

    print("=" * 66)
    print("  准备本地语音引擎（sherpa-onnx · SenseVoice）")
    print("=" * 66)
    print(f"  版本：{asr_engine.VERSION}")
    print(f"  模型：{asr_engine.MODEL}")
    print(f"  目录：{asr_engine.ROOT}")
    print(f"  资产：{asr_engine.asset_name()}")
    print()

    state = asr_engine.status()
    if check_only:
        print(f"  状态：{state['detail']}")
        print(f"  可执行：{state['binary'] or '（缺失）'}")
        onnx, tokens = asr_engine.model_files()
        print(f"  模型：{onnx or '（缺失）'}")
        print(f"  词表：{tokens or '（缺失）'}")
        return 0 if state["ready"] else 1

    if state["ready"] and not force:
        print("  已就位，跳过下载。")
        return 0

    print("  开始下载（首次约 250MB，网络慢时请耐心等待）…")
    ok = asr_engine.ensure(force=force)
    print()
    if ok:
        print(f"  完成：{asr_engine.status()['detail']}")
        print("  自检：python core/asr_engine.py")
        return 0
    print(f"  失败：{asr_engine.prepare_state().get('reason') or asr_engine.status()['detail']}")
    print("  可换镜像重试：python scripts/prepare_asr_engine.py --mirror <前缀>")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
