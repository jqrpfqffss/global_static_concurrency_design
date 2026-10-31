"""Bounded command-line navigation over the same provider used by Studio."""
import argparse
import json
from pathlib import Path

from .scan_store import EvidenceProvider


def main(argv=None):
    parser = argparse.ArgumentParser(description='完整证据分页读取；next_offset 为空表示当前节点读完')
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--root', choices=['facts', 'report', 'provenance'], default='facts')
    parser.add_argument('--path', default='[]', help='精确 JSON 路径，例如 ["calls",0]；整数表示数组下标')
    parser.add_argument('--node', type=int)
    parser.add_argument('--text', action='store_true')
    parser.add_argument('--offset', type=int, default=0)
    parser.add_argument('--limit', type=int, default=50)
    args = parser.parse_args(argv)
    path = json.loads(args.path)
    if not isinstance(path, list) or any(type(key) not in {str, int} for key in path):
        raise ValueError('path 必须是字符串/整数列表')
    provider = EvidenceProvider(args.database)
    node = args.node if args.node is not None else provider.resolve(args.root, path)
    page = provider.text(node, offset=args.offset, limit=args.limit) if args.text else provider.node(node, offset=args.offset, limit=args.limit)
    print(json.dumps(dict(database=str(args.database.resolve()), root=args.root, path=path, **page), ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
