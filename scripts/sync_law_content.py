# -*- coding: utf-8 -*-
"""官方更新信号→正文候选→审阅哈希确认→全文与切片；默认只生成候选。"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core import law_content, law_store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--law', help='CELEX 或 US:编:Part；新法规同样使用此入口')
    parser.add_argument('--signals', help='check_metadata_freshness 生成的 metadata_check_latest.json')
    parser.add_argument('--db', help='正式条款库路径；必须已存在')
    parser.add_argument('--staging', default=str(ROOT / 'data/content_staging'))
    parser.add_argument('--apply', help='经审阅的候选 JSON 文件')
    parser.add_argument('--confirm-sha256', help='明确确认的正文 SHA256')
    args = parser.parse_args()
    if args.apply:
        if not args.confirm_sha256:
            parser.error('--apply 必须提供 --confirm-sha256')
        result = law_content.apply(args.apply, args.confirm_sha256, args.db)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result['ok'] else 1
    identifiers = [args.law] if args.law else []
    if args.signals:
        signals = json.loads(Path(args.signals).read_text(encoding='utf-8'))
        identifiers += [x['law_id'] for x in signals.get('changes', [])]
    identifiers = sorted(set(identifiers))
    if not identifiers:
        parser.error('提供 --law 或 --signals；抓取不会自动写入正式库')
    results = [law_content.stage(identifier, args.staging, args.db) for identifier in identifiers]
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if all(x['ok'] for x in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
