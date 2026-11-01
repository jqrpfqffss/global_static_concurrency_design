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


def file_identity(path):
    """Fixed-buffer content proof, including a concurrent-write check."""
    sha = hashlib.sha256()
    with path.open('rb') as stream:
        before = os.fstat(stream.fileno())
        while chunk := stream.read(1024 * 1024):
            sha.update(chunk)
        after = os.fstat(stream.fileno())
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise RuntimeError(f'Replay input changed while hashing: {path}')
    return dict(path=str(path.resolve()), bytes=after.st_size,
                mtime_ns=after.st_mtime_ns, sha256=sha.hexdigest())


def ordered_digest(value):
    # Preserve every object/array order, duplicate, bool/int and signed zero.
    sha = hashlib.sha256()
    encoder = json.JSONEncoder(ensure_ascii=True, separators=(',', ':'), allow_nan=False)
    for chunk in encoder.iterencode(value):
        sha.update(chunk.encode('ascii'))
    return sha.hexdigest()


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
    available = sorted(p for p in args.workers.glob('TU-*.response.json') if '.dependencies.' not in p.name)
    if args.count < 1 or args.repeat < 1 or args.count > len(available):
        parser.error('Requested replay size must refer to available actual extraction facts')
    if args.limit_mib < 0:
        parser.error('Memory limit must be nonnegative')
    # Evidence is append-only: an earlier run, even a failed run, stays intact.
    outputs = [args.output, args.output.with_suffix('.limit.json'),
               args.output.with_suffix('.prof'), args.output.with_suffix('.reservation')]
    if any(path.exists() for path in outputs):
        parser.error('Choose a fresh output path; prior replay evidence is never overwritten')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with outputs[-1].open('x', encoding='utf-8') as claim:
        claim.write(json.dumps(dict(pid=os.getpid(), started_unix=time.time())))
    if args.limit_mib:
        receipt = args.output.with_suffix('.limit.json')
        controller = subprocess.Popen([sys.executable,str(Path(__file__).with_name('windows_memory_limit.py')),
            '--pid',str(os.getpid()),'--gib',str(args.limit_mib/1024),'--evidence',str(receipt)])
        deadline = time.monotonic()+10
        while not receipt.is_file():
            if controller.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError('Controlled memory limit was not applied')
            time.sleep(0.05)
        limit = json.loads(receipt.read_text(encoding='utf-8'))
        if limit['pid'] != os.getpid() or limit['process_commit_limit_bytes'] != args.limit_mib * 1024**2:
            raise RuntimeError('Replay allocator PID/limit mismatch')
    sys.path.insert(0, str(args.engine.resolve()))
    from ecra.common import read_json
    from ecra.analysis import merge
    import psutil
    def memory():
        return psutil.Process().memory_info()._asdict()
    selected = available[:args.count]
    input_paths = [path for p in selected for path in (p, Path(str(p)+'.metadata.json')) if path.is_file()]
    input_before = [file_identity(path) for path in input_paths]
    engine_before = [file_identity(args.engine/name) for name in
                     ('ecra/fact_parts.py', 'ecra/analysis.py', 'ecra/json_rows.py')]
    start = time.monotonic()
    if not args.no_profile:
        tracemalloc.start(1)
    files = selected * args.repeat
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
    merged_memory = memory()
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
    full_digest = ordered_digest(facts)
    input_after = [file_identity(path) for path in input_paths]
    engine_after = [file_identity(args.engine/name) for name in
                    ('ecra/fact_parts.py', 'ecra/analysis.py', 'ecra/json_rows.py')]
    if input_before != input_after or engine_before != engine_after:
        raise RuntimeError('Replay inputs/engine changed; this run is invalid')
    result = dict(controlled_replay=True, scope='CONTROLLED_REPLAY_NOT_NATIVE_G2_OR_G3',
        count=len(files), loaded=loaded,
        seconds=time.monotonic()-start, merge_seconds=merge_seconds, memory=memory(),
        merged_memory=merged_memory, pid=os.getpid(), limit_mib=args.limit_mib,
        trace=tracemalloc.get_traced_memory() if tracemalloc.is_tracing() else None,
        tracemalloc_enabled=not args.no_profile, cprofile_enabled=bool(profile),
        input_before=input_before, input_after=input_after, engine=engine_after,
        ordered_full_facts_sha256=full_digest, fingerprints=fingerprints)
    with args.output.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(result, indent=2))
        stream.flush()
        os.fsync(stream.fileno())
    print(str(args.output))


if __name__ == '__main__':
    main()
