"""Controlled replay of real TU facts; this is not a firmware scan."""
import argparse
import cProfile
import hashlib
import json
import os
from pathlib import Path
import sys
import subprocess
import time
import tracemalloc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', type=Path, required=True)
    parser.add_argument('--workers', type=Path, required=True)
    parser.add_argument('--count', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--stream', action='store_true')
    parser.add_argument('--repeat', type=int, default=1)
    parser.add_argument('--limit-mib', type=int, default=0, help='Explicit controlled Windows Job commit limit')
    parser.add_argument('--no-profile', action='store_true', help='Skip tracemalloc; keep OS memory measurement')
    parser.add_argument('--no-cprofile', action='store_true', help='Skip function profiler overhead')
    args = parser.parse_args()
    if args.limit_mib:
        receipt = args.output.with_suffix('.limit.json')
        receipt.unlink(missing_ok=True)
        controller = subprocess.Popen([sys.executable,str(Path(__file__).with_name('windows_memory_limit.py')),
            '--pid',str(os.getpid()),'--gib',str(args.limit_mib/1024),'--evidence',str(receipt)])
        deadline = time.monotonic()+10
        while not receipt.is_file():
            if controller.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError('Controlled memory limit was not applied')
            time.sleep(0.05)
    sys.path.insert(0, str(args.engine.resolve()))
    from ecra.common import read_json
    from ecra.analysis import merge
    import psutil
    def memory():
        return psutil.Process().memory_info()._asdict()
    start = time.monotonic()
    if not args.no_profile:
        tracemalloc.start(1)
    available = sorted(p for p in args.workers.glob('TU-*.response.json') if '.dependencies.' not in p.name)
    if args.count < 1 or args.repeat < 1 or args.count > len(available):
        parser.error('Requested replay size must refer to available actual extraction facts')
    files = available[:args.count] * args.repeat
    profile = None if args.no_cprofile else cProfile.Profile()
    if profile:
        profile.enable()
    if args.stream:
        from ecra.fact_parts import FactParts
        parts = FactParts()
        for path in files:
            metadata = Path(str(path)+'.metadata.json')
            part = read_json(metadata if metadata.is_file() else path)
            if metadata.is_file():
                parts.append_metadata(path, part)
            else:
                parts.append(path, part)
            del part
    else:
        parts = [read_json(path) for path in files]
    loaded = dict(memory=memory(), trace=tracemalloc.get_traced_memory() if tracemalloc.is_tracing() else None,
                  seconds=time.monotonic()-start)
    merge_started = time.monotonic()
    facts = merge(parts)
    merge_seconds = time.monotonic()-merge_started
    parts.clear()
    if profile:
        profile.disable()
        profile.dump_stats(str(args.output.with_suffix('.prof')))
    fingerprints = {}
    for table, rows in facts.items():
        sha = hashlib.sha256()
        encoder = json.JSONEncoder(sort_keys=True, ensure_ascii=False, separators=(',', ':'))
        for row in rows:
            for chunk in encoder.iterencode(row):
                sha.update(chunk.encode('utf-8'))
        fingerprints[table] = dict(count=len(rows), sha256=sha.hexdigest())
    args.output.write_text(json.dumps(dict(controlled_replay=True, count=len(files), loaded=loaded,
        seconds=time.monotonic()-start, merge_seconds=merge_seconds, memory=memory(),
        trace=tracemalloc.get_traced_memory() if tracemalloc.is_tracing() else None,
        tracemalloc_enabled=not args.no_profile, cprofile_enabled=bool(profile),
        files=[dict(path=str(p),bytes=p.stat().st_size) for p in files],
        fingerprints=fingerprints), indent=2),encoding='utf-8')
    print(str(args.output))


if __name__ == '__main__':
    main()
