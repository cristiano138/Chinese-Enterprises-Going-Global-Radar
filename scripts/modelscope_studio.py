# -*- coding: utf-8 -*-
"""ModelScope Studio deployment helper (OpenAPI + Git).

The OpenAPI is the source of truth; this script only wraps the calls needed
for this project. It never prints the access token and never force-pushes.

Typical use:
  set MODELSCOPE_API_KEY=...                 # PowerShell
  python scripts/modelscope_studio.py check  --studio zhanxy2551/ComplianceRadar-v2
  python scripts/modelscope_studio.py vars   --studio ... --set CR_UI=spa --set ASR_BACKEND=off
  python scripts/modelscope_studio.py push   --studio ... --dir dist/modelscope-deploy --yes
  python scripts/modelscope_studio.py deploy --studio ... --watch
  python scripts/modelscope_studio.py logs   --studio ... --type run
  python scripts/modelscope_studio.py all    --studio ... --dir dist/modelscope-deploy --yes

Token: https://modelscope.cn/my/myaccesstoken
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import quote, urlparse

import requests

PROJECT = Path(__file__).resolve().parent.parent
DEFAULT_ENDPOINT = os.getenv("MODELSCOPE_ENDPOINT", "https://modelscope.cn").rstrip("/")
REQUIRED = (
    "app.py", "app_main.py", "web_app.py",
    "requirements.txt", "ms_deploy.json",
    "web/index.html", "web/js/main.js",
)
RUNNING = {"running", "success", "ready", "deployed"}
FAILED = {"failed", "error", "build_failed", "start_failed"}


def redact(text: str, token: str) -> str:
    if token:
        text = text.replace(token, "***")
        text = text.replace(quote(token, safe=""), "***")
    return re.sub(r"https://oauth2:[^@]+@", "https://oauth2:***@", text)


def studio_parts(value: str) -> tuple[str, str]:
    value = (value or "").strip().strip("/")
    if value.count("/") != 1:
        raise SystemExit("--studio 需要 owner/repo，例如 zhanxy2551/ComplianceRadar-v2")
    owner, repo = value.split("/", 1)
    if not owner or not repo:
        raise SystemExit("--studio 需要 owner/repo")
    return owner, repo


def get_token(args) -> str:
    token = (getattr(args, "token", "") or os.getenv("MODELSCOPE_API_KEY", "")).strip()
    if not token:
        token = getpass.getpass("ModelScope access token (输入不回显): ").strip()
    if not token:
        raise SystemExit("缺少 MODELSCOPE_API_KEY；在 https://modelscope.cn/my/myaccesstoken 生成")
    args.token = token  # cache, so `all` does not prompt twice
    return token


def http_session(token: str) -> requests.Session:
    session = requests.Session()
    session.trust_env = False  # a dead host proxy must not break modelscope.cn
    session.headers.update({
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
        "Accept": "application/json",
    })
    return session


def api(session: requests.Session, endpoint: str, method: str, path: str,
        **kwargs):
    url = endpoint.rstrip("/") + "/openapi/v1" + path
    response = session.request(method, url, timeout=60, **kwargs)
    try:
        payload = response.json()
    except Exception:  # noqa: BLE001
        payload = {"raw": response.text[:1000]}
    if response.status_code >= 400 or payload.get("success") is False:
        raise RuntimeError(
            f"{method} {path} -> HTTP {response.status_code}\n"
            + json.dumps(payload, ensure_ascii=False)[:2000])
    return payload


def whoami(session: requests.Session, endpoint: str) -> str:
    payload = api(session, endpoint, "GET", "/users/me")
    data = payload.get("data") or payload
    if isinstance(data, dict) and isinstance(data.get("user"), dict):
        data = data["user"]
    for key in ("username", "Username", "name", "Name", "user_name"):
        if data.get(key):
            return str(data[key])
    return json.dumps(data, ensure_ascii=False)[:300]


def studio_info(session: requests.Session, endpoint: str,
                owner: str, repo: str) -> dict:
    payload = api(session, endpoint, "GET", f"/studios/{owner}/{repo}")
    data = payload.get("data") or payload
    if isinstance(data, dict) and isinstance(data.get("studio"), dict):
        data = data["studio"]
    return data


def status_of(info: dict) -> str:
    for key in ("status", "Status", "deploy_status", "state"):
        if info.get(key):
            return str(info[key])
    pipeline = info.get("AsyncPipeline") or info.get("async_pipeline") or {}
    if isinstance(pipeline, dict):
        for key in ("Status", "status", "CurrentStage"):
            if pipeline.get(key):
                # Do not mistake a successful *git push* stage for a running app.
                return "pipeline:" + str(pipeline[key])
    return ""


def print_studio(info: dict, owner: str, repo: str, endpoint: str) -> None:
    interesting = {
        "Status": info.get("Status") or info.get("status"),
        "SdkType": info.get("SdkType") or info.get("sdk_type"),
        "SdkVersion": info.get("SdkVersion") or info.get("sdk_version"),
        "Hardware": info.get("Hardware") or info.get("hardware"),
        "InstanceType": info.get("InstanceType") or info.get("instance_type"),
        "Cpu": (info.get("LastDeployConfig") or {}).get("Cpu"),
        "Memory": (info.get("LastDeployConfig") or {}).get("Memory"),
        "Url": f"{endpoint}/studios/{owner}/{repo}",
        "IndependentUrl": info.get("IndependentUrl") or info.get("independent_url"),
    }
    for key, value in interesting.items():
        if value not in (None, "", []):
            print(f"  {key}: {value}")


def command_check(args) -> int:
    token = get_token(args)
    owner, repo = studio_parts(args.studio)
    session = http_session(token)
    user = whoami(session, args.endpoint)
    print(f"登录账号: {user}")
    info = studio_info(session, args.endpoint, owner, repo)
    print(f"空间: {owner}/{repo}")
    print_studio(info, owner, repo, args.endpoint)
    if user != owner:
        print(f"\n[warn] 当前账号 {user} 不是空间 owner {owner}；"
              f"推送会被拒绝。请换账号，或在 {user} 下新建空间。")
    for kind in ("variables", "secrets"):
        try:
            print(f"\n{kind} keys:", sorted(list_keys(session, args.endpoint,
                                                     owner, repo, kind)))
        except Exception as error:  # noqa: BLE001
            print(f"\n{kind} 读取失败:", str(error)[:200])
    return 0


def list_keys(session, endpoint, owner, repo, kind):
    payload = api(session, endpoint, "GET", f"/studios/{owner}/{repo}/{kind}")
    data = payload.get("data") or {}
    items = data.get(kind) if isinstance(data, dict) else data
    if not isinstance(items, list):
        items = []
    return {item.get("key"): item for item in items if isinstance(item, dict)}


def upsert(session, endpoint, owner, repo, kind, key, value):
    existing = list_keys(session, endpoint, owner, repo, kind)
    method = "PUT" if key in existing else "POST"
    api(session, endpoint, method, f"/studios/{owner}/{repo}/{kind}",
        json={"key": key, "value": value})
    print(f"  {kind}:{key} {'更新' if method == 'PUT' else '新增'}")


def command_vars(args) -> int:
    token = get_token(args)
    owner, repo = studio_parts(args.studio)
    session = http_session(token)
    if not (args.set or args.secret or getattr(args, "delete", None)):
        for kind in ("variables", "secrets"):
            items = list_keys(session, args.endpoint, owner, repo, kind)
            print(kind + " keys:", sorted(items))
        return 0
    for item in args.set or []:
        if "=" not in item:
            raise SystemExit("--set 需要 KEY=VALUE")
        key, value = item.split("=", 1)
        upsert(session, args.endpoint, owner, repo, "variables", key, value)
    for item in args.secret or []:
        if "=" in item:
            key, value = item.split("=", 1)
        else:
            key = item
            value = getpass.getpass(f"{key}（输入不回显）: ")
        upsert(session, args.endpoint, owner, repo, "secrets", key, value)
    for key in getattr(args, "delete", None) or []:
        for kind in ("variables", "secrets"):
            if key in list_keys(session, args.endpoint, owner, repo, kind):
                api(session, args.endpoint, "DELETE",
                    f"/studios/{owner}/{repo}/{kind}", json={"key": key})
                print(f"  {kind}:{key} 删除")
    return 0


def git_run(args: list[str], cwd: Path, token: str, check: bool = True) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.update({
        "GIT_LFS_SKIP_SMUDGE": "1",
        "GIT_TERMINAL_PROMPT": "0",
    })
    command = ["git", "-c", "http.proxy=", "-c", "https.proxy=",
               "-c", "credential.helper=", *args]
    result = subprocess.run(command, cwd=cwd, env=env, capture_output=True,
                            text=True, encoding="utf-8", errors="replace")
    if check and result.returncode != 0:
        raise RuntimeError(redact(
            f"git {' '.join(args[:3])} 失败（exit={result.returncode}）\n"
            + (result.stderr or result.stdout)[-2500:], token))
    return result


def copy_tree(src: Path, dst: Path) -> None:
    for item in src.iterdir():
        target = dst / item.name
        if item.name == ".git":
            continue
        if item.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)


def command_push(args) -> int:
    token = get_token(args)
    owner, repo = studio_parts(args.studio)
    staging = Path(args.dir).expanduser().resolve()
    missing = [name for name in REQUIRED if not (staging / name).is_file()]
    if missing:
        raise SystemExit("部署目录不完整：\n  " + "\n  ".join(missing))
    session = http_session(token)
    user = whoami(session, args.endpoint)
    if user != owner:
        message = f"当前账号 {user} 不是空间 owner {owner}"
        if not args.allow_owner_mismatch:
            raise SystemExit(message + "；不会推送。")
        print("[warn] " + message)

    host = "www.modelscope.ai" if "modelscope.ai" in args.endpoint else "www.modelscope.cn"
    auth_url = (f"https://oauth2:{quote(token, safe='')}@{host}"
                f"/studios/{owner}/{repo}.git")
    temp = Path(tempfile.mkdtemp(prefix="cr-studio-"))
    checkout = temp / "repo"
    try:
        print(f"克隆空间仓库 {owner}/{repo}（master）...")
        clone = git_run(["clone", "--branch", "master",
                         auth_url, str(checkout)], temp, token, check=False)
        if clone.returncode != 0:
            print("  master 不存在或仓库为空，改用空白克隆")
            git_run(["clone", auth_url, str(checkout)], temp, token)
            git_run(["checkout", "-B", "master"], checkout, token)

        # Keep the platform's LFS rules; replace the app payload.
        for item in checkout.iterdir():
            if item.name in {".git", ".gitattributes"}:
                continue
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
        copy_tree(staging, checkout)

        big = [path for path in checkout.rglob("*")
               if path.is_file() and path.stat().st_size > 95 * 1024 * 1024]
        if big:
            raise SystemExit("有文件超过 95MB，需要走 LFS：" +
                             ", ".join(str(p.relative_to(checkout)) for p in big))

        git_run(["add", "-A"], checkout, token)
        git_run(["add", "-f", "runtime-assets/law-store.bundle"], checkout, token,
                check=False)
        git_run(["add", "-f", "ms_deploy.json"], checkout, token, check=False)

        status = git_run(["status", "--short"], checkout, token)
        print("\n将提交以下变更（前 40 行）：")
        print("\n".join(status.stdout.splitlines()[:40]))
        if not status.stdout.strip():
            print("没有变更，跳过提交。")
        else:
            if not args.yes:
                print("\n[dry-run] 未提交。确认无误后加 --yes 再运行。")
                return 0
            source = {}
            manifest = staging / "DEPLOY_MANIFEST.json"
            if manifest.is_file():
                source = (json.loads(manifest.read_text(encoding="utf-8"))
                          .get("source") or {})
            message = (f"Deploy {PROJECT.name} from {source.get('git_head', 'unknown')}"
                       f"{' (dirty)' if source.get('dirty') else ''} "
                       f"at {time.strftime('%Y-%m-%d %H:%M')}")
            git_run(["-c", "user.name=ComplianceRadar Deploy",
                     "-c", "user.email=deploy@compliance-radar.local",
                     "commit", "-m", message], checkout, token)
            print("推送到 master ...")
            git_run(["push", "origin", "HEAD:master"], checkout, token)
            print("推送完成。")
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 1
    finally:
        shutil.rmtree(temp, ignore_errors=True)
    return 0


def command_deploy(args) -> int:
    token = get_token(args)
    owner, repo = studio_parts(args.studio)
    session = http_session(token)
    if not args.yes:
        print(f"[dry-run] 将触发 {owner}/{repo} 部署。确认后加 --yes。")
        return 0
    payload = api(session, args.endpoint, "POST",
                  f"/studios/{owner}/{repo}/deploy")
    print("部署已触发：", json.dumps(payload.get("data") or {}, ensure_ascii=False)[:500])
    if not args.watch:
        return 0
    deadline = time.monotonic() + args.timeout
    last = None
    while time.monotonic() < deadline:
        time.sleep(args.interval)
        info = studio_info(session, args.endpoint, owner, repo)
        status = status_of(info)
        if status != last:
            print(f"  [{time.strftime('%H:%M:%S')}] status={status or '(unknown)'}"
                  f" stage={(info.get('AsyncPipeline') or {}).get('CurrentStage') or ''}")
            last = status
        lowered = status.casefold()
        if lowered in RUNNING:
            print("\n部署完成。")
            print_studio(info, owner, repo, args.endpoint)
            return 0
        if lowered in FAILED:
            print("\n部署失败，运行日志：")
            command_logs(argparse.Namespace(token=token, endpoint=args.endpoint,
                                            studio=args.studio, type="run", tail=120))
            return 1
    print("\n等待超时；请到空间页面或 logs 命令查看。", file=sys.stderr)
    return 1


def command_logs(args) -> int:
    token = get_token(args)
    owner, repo = studio_parts(args.studio)
    session = http_session(token)
    payload = api(session, args.endpoint, "GET",
                  f"/studios/{owner}/{repo}/logs/{args.type}")
    data = payload.get("data")
    text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, indent=1)
    lines = text.splitlines()
    print("\n".join(lines[-args.tail:]))
    return 0


def command_create(args) -> int:
    token = get_token(args)
    session = http_session(token)
    owner = args.owner or whoami(session, args.endpoint)
    payload = api(session, args.endpoint, "POST", "/studios", json={
        "owner": owner,
        "repo_name": args.repo,
        "sdk_type": "gradio",
        "display_name": args.display_name or args.repo,
        "visibility": "public" if args.public else "private",
        "hardware": args.hardware,
        "base_image": args.base_image,
        "sdk_version": args.sdk_version,
    })
    print(json.dumps(payload.get("data") or payload, ensure_ascii=False, indent=2)[:2000])
    print(f"\n空间地址: {args.endpoint}/studios/{owner}/{args.repo}")
    return 0


def add_common(parser):
    parser.add_argument("--studio", required=True, help="owner/repo")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--token", default="", help="优先用 MODELSCOPE_API_KEY，避免写在命令里")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("check", help="确认账号、空间归属、SDK/资源和变量 keys")
    add_common(p)

    p = sub.add_parser("vars", help="查看/设置变量与 secrets")
    add_common(p)
    p.add_argument("--set", action="append", help="KEY=VALUE，明文变量")
    p.add_argument("--secret", action="append", help="KEY 或 KEY=VALUE；只给 KEY 时交互输入")
    p.add_argument("--delete", action="append", help="KEY")

    p = sub.add_parser("push", help="把部署目录同步到空间 master 分支")
    add_common(p)
    p.add_argument("--dir", default=str(PROJECT / "dist" / "modelscope-deploy"))
    p.add_argument("--yes", action="store_true")
    p.add_argument("--allow-owner-mismatch", action="store_true")

    p = sub.add_parser("deploy", help="触发部署并等待状态")
    add_common(p)
    p.add_argument("--yes", action="store_true")
    p.add_argument("--watch", action="store_true")
    p.add_argument("--interval", type=int, default=10)
    p.add_argument("--timeout", type=int, default=900)

    p = sub.add_parser("logs", help="查看运行/构建日志")
    add_common(p)
    p.add_argument("--type", choices=("run", "build"), default="run")
    p.add_argument("--tail", type=int, default=120)

    p = sub.add_parser("create", help="在当前账号下新建空间")
    p.add_argument("--repo", required=True)
    p.add_argument("--owner", default="")
    p.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    p.add_argument("--token", default="")
    p.add_argument("--public", action="store_true")
    p.add_argument("--display-name", default="")
    p.add_argument("--hardware", default="platform/2v-cpu-8g-mem")
    p.add_argument("--base-image", default="ubuntu22.04-py311-torch2.9.1-modelscope1.35.0")
    p.add_argument("--sdk-version", default="6.2.0")

    p = sub.add_parser("all", help="check -> vars(可选) -> push -> deploy")
    add_common(p)
    p.add_argument("--dir", default=str(PROJECT / "dist" / "modelscope-deploy"))
    p.add_argument("--yes", action="store_true")
    p.add_argument("--allow-owner-mismatch", action="store_true")
    p.add_argument("--set", action="append", help="部署前设置的明文变量 KEY=VALUE")
    p.add_argument("--secret", action="append", help="部署前设置的 secret KEY 或 KEY=VALUE")
    p.add_argument("--watch", action="store_true")
    p.add_argument("--timeout", type=int, default=900)

    args = parser.parse_args()
    try:
        if args.command == "check":
            return command_check(args)
        if args.command == "vars":
            return command_vars(args)
        if args.command == "push":
            return command_push(args)
        if args.command == "deploy":
            return command_deploy(args)
        if args.command == "logs":
            return command_logs(args)
        if args.command == "create":
            return command_create(args)
        if args.command == "all":
            command_check(args)
            if args.set or args.secret:
                command_vars(args)
            code = command_push(args)
            if code:
                return code
            return command_deploy(argparse.Namespace(
                token=args.token, endpoint=args.endpoint, studio=args.studio,
                yes=args.yes, watch=args.watch, timeout=args.timeout,
                interval=10))
    except (RuntimeError, requests.RequestException) as error:
        print("失败：" + redact(str(error), getattr(args, "token", "") or ""),
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
