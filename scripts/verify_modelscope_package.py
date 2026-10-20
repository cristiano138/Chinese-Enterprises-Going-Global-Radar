# -*- coding: utf-8 -*-
"""Boot a ModelScope deployment folder locally and smoke-test its API.

This is the gate before ``git push`` / Studio deploy. It uses the current
virtualenv, starts ``app.py`` from the staged folder on a spare port, and
checks the same endpoints the SPA calls.

Usage:
  .venv\\Scripts\\python.exe scripts\\verify_modelscope_package.py
  .venv\\Scripts\\python.exe scripts\\verify_modelscope_package.py --dir dist\\modelscope-deploy --port 7862
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests

PROJECT = Path(__file__).resolve().parent.parent
REQUIRED = (
    "app.py", "app_main.py", "web_app.py",
    "requirements.txt", "ms_deploy.json",
    "web/index.html", "web/js/main.js",
    "core/llm.py", "modules/m15_router.py",
    "data/语料核对表_完整版.csv", "data/snapshot.json",
)


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        return sock.connect_ex(("127.0.0.1", port)) != 0


def session() -> requests.Session:
    http = requests.Session()
    http.trust_env = False  # ignore a dead HTTP_PROXY from the host shell
    return http


def wait_up(http: requests.Session, base: str, proc: subprocess.Popen,
            log_path: Path, timeout: int) -> None:
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(
                f"app.py 提前退出（exit={proc.returncode}）\n"
                + "\n".join(log_path.read_text(encoding="utf-8", errors="replace")
                            .splitlines()[-40:]))
        try:
            response = http.get(base + "/api/bootstrap", timeout=3)
            if response.status_code == 200 and response.json().get("ok"):
                return
        except Exception as error:  # noqa: BLE001
            last_error = f"{type(error).__name__}: {error}"
        time.sleep(1)
    tail = "\n".join(log_path.read_text(encoding="utf-8", errors="replace")
                     .splitlines()[-40:])
    raise RuntimeError(f"启动超时（{timeout}s）：{last_error}\n{tail}")


def kill_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                       capture_output=True)
    else:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def check(http: requests.Session, base: str, results: list[dict],
          allow_no_law_store: bool = False) -> None:
    checks = [
        ("SPA 首页", lambda: http.get(base + "/", timeout=10), "text", "出海合规雷达"),
        ("SPA 脚本", lambda: http.get(base + "/web/js/main.js", timeout=10), "status", 200),
        ("bootstrap", lambda: http.get(base + "/api/bootstrap", timeout=10), "json-ok", None),
        ("freshness", lambda: http.get(base + "/api/freshness", timeout=15), "json-ok", None),
        ("法规地图", lambda: http.post(base + "/api/tool/map", timeout=30,
                                      json={"category": "儿童玩具", "market": "欧盟"}),
         "json-ok", None),
        ("合规待办", lambda: http.post(base + "/api/tool/todo", timeout=30,
                                      json={"category": "儿童玩具", "market": "欧盟"}),
         "json-ok", None),
        ("自然语言路由", lambda: http.post(base + "/api/route", timeout=30,
                                          json={"text": "儿童玩具卖到欧盟", "use_llm": False}),
         "json-ok", None),
    ]
    if not allow_no_law_store:
        checks.insert(5, (
            "条款检索",
            lambda: http.get(base + "/api/search", timeout=30,
                             params={"identifier": "32009L0048"}),
            "json-ok", None,
        ))
    for name, call, kind, needle in checks:
        try:
            response = call()
            if kind == "status":
                ok = response.status_code == needle
                detail = f"HTTP {response.status_code}"
            elif kind == "text":
                ok = response.status_code == 200 and needle in response.text
                detail = f"HTTP {response.status_code}, {len(response.text)} chars"
            else:
                payload = response.json()
                ok = response.status_code == 200 and payload.get("ok") is True
                data = payload.get("data")
                detail = f"HTTP {response.status_code}, ok={payload.get('ok')}"
                if isinstance(data, dict):
                    for key in ("records", "actions", "units", "regions"):
                        if isinstance(data.get(key), list):
                            detail += f", {key}={len(data[key])}"
                    if data.get("reason"):
                        detail += f", reason={data['reason']}"
            results.append({"name": name, "ok": bool(ok), "detail": detail})
        except Exception as error:  # noqa: BLE001
            results.append({"name": name, "ok": False,
                            "detail": f"{type(error).__name__}: {error}"})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=Path,
                        default=PROJECT / "dist" / "modelscope-deploy")
    parser.add_argument("--port", type=int, default=7862)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--keep-db", action="store_true",
                        help="保留启动时解压出的 sqlite/regulations.sqlite3")
    parser.add_argument("--allow-no-law-store", action="store_true",
                        help="部署包没带条款库时，跳过 /api/search 检查")
    args = parser.parse_args()

    root = args.dir.expanduser().resolve()
    missing = [name for name in REQUIRED if not (root / name).is_file()]
    if missing:
        print("部署包不完整：\n  " + "\n  ".join(missing), file=sys.stderr)
        return 1
    if not port_free(args.port):
        print(f"端口 {args.port} 已被占用，换一个 --port", file=sys.stderr)
        return 1

    env = os.environ.copy()
    env.update({
        "PORT": str(args.port),
        "CR_UI": "spa",
        "ASR_BACKEND": "off",
        "ASR_ENGINE_AUTO_DOWNLOAD": "0",
        "NO_PROXY": "localhost,127.0.0.1,0.0.0.0",
        "no_proxy": "localhost,127.0.0.1,0.0.0.0",
        "PYTHONUNBUFFERED": "1",
        "PYTHONIOENCODING": "utf-8",
    })

    log_fd, log_name = tempfile.mkstemp(prefix="cr-verify-", suffix=".log")
    os.close(log_fd)
    log_path = Path(log_name)
    results: list[dict] = []
    proc = None
    try:
        with log_path.open("w", encoding="utf-8", errors="replace") as log:
            proc = subprocess.Popen(
                [sys.executable, "app.py"], cwd=root, env=env,
                stdout=log, stderr=subprocess.STDOUT, text=True)
            http = session()
            base = f"http://127.0.0.1:{args.port}"
            print(f"启动 {root}（端口 {args.port}）...")
            wait_up(http, base, proc, log_path, args.timeout)
            print("启动成功，开始 API 检查...\n")
            check(http, base, results,
                  allow_no_law_store=args.allow_no_law_store)
    except Exception as error:  # noqa: BLE001
        print("验证失败：" + str(error), file=sys.stderr)
        return 1
    finally:
        if proc is not None:
            kill_tree(proc)
        sqlite = root / "sqlite"
        if sqlite.exists() and not args.keep_db:
            import shutil
            shutil.rmtree(sqlite, ignore_errors=True)
        import shutil
        for cache in root.rglob("__pycache__"):
            shutil.rmtree(cache, ignore_errors=True)
        try:
            log_path.unlink(missing_ok=True)
        except OSError:
            pass

    failed = [item for item in results if not item["ok"]]
    for item in results:
        print(("PASS " if item["ok"] else "FAIL ") + item["name"] + "  " + item["detail"])
    print(f"\n{len(results) - len(failed)}/{len(results)} 通过")
    if failed:
        print("\n失败项需要先修，再上传。", file=sys.stderr)
        return 1
    print("\n部署包可以推送。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
