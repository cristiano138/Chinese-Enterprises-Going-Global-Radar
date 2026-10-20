"""原型 vs 改造后的像素比对；比对由 REA 完成。

用法：
  python scripts/compare_web_screenshots.py \
    --prototype docs/ui-preview/prototype-baseline/shots \
    --rebuilt   docs/ui-preview/rebuilt/shots \
    --out       docs/ui-preview/web-pixel-diff.json
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def snapshot(path):
    data = path.read_bytes()
    return {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
            "media_type": "image/png", "data_base64": base64.b64encode(data).decode()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prototype", required=True)
    parser.add_argument("--rebuilt", required=True)
    parser.add_argument("--out", default=None)
    parser.add_argument("--threshold", type=float, default=0.02, help="允许的差异像素占比")
    args = parser.parse_args()

    rea = shutil.which("rea")
    if rea is None:
        print("REA 未安装：npm install --global rea-agents", file=sys.stderr)
        return 2

    proto_dir, rebuilt_dir = Path(args.prototype), Path(args.rebuilt)
    names = sorted(p.name for p in proto_dir.glob("*.png"))
    if not names:
        print(f"基准目录没有截图：{proto_dir}", file=sys.stderr)
        return 2

    report = {"pairs": [], "over_threshold": []}
    with tempfile.TemporaryDirectory() as tmp:
        for name in names:
            rebuilt = rebuilt_dir / name
            if not rebuilt.is_file():
                report["over_threshold"].append({"name": name, "reason": "缺少改造后截图"})
                continue
            before = Path(tmp) / f"{name}.before.json"
            after = Path(tmp) / f"{name}.after.json"
            before.write_text(json.dumps(snapshot(proto_dir / name)), encoding="utf-8")
            after.write_text(json.dumps(snapshot(rebuilt)), encoding="utf-8")
            proc = subprocess.run(
                [rea, "compare-web-screenshots", str(before), str(after), "--json"],
                capture_output=True, text=True, encoding="utf-8", shell=False)
            if proc.returncode != 0:
                report["over_threshold"].append(
                    {"name": name, "reason": f"REA 退出码 {proc.returncode}: {proc.stderr[:200]}"})
                continue
            norm = json.loads(proc.stdout).get("normalized_result", {})
            entry = {"name": name, "status": norm.get("status"),
                     "changed_ratio": norm.get("changed_ratio"),
                     "changed_pixels": norm.get("changed_pixels"),
                     "compared_pixels": norm.get("compared_pixels"),
                     "maximum_channel_delta": norm.get("maximum_channel_delta")}
            report["pairs"].append(entry)
            ratio = entry["changed_ratio"]
            if isinstance(ratio, (int, float)) and ratio > args.threshold:
                report["over_threshold"].append(entry)

    text = json.dumps(report, ensure_ascii=False, indent=1)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)
    return 1 if report["over_threshold"] else 0


if __name__ == "__main__":
    sys.exit(main())
