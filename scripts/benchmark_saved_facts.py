"""Controlled loading of an actual saved JSON artifact, never a scan result.

An optional Windows Job cap protects the rest of the experiments. A failed
load is explicitly saved with its original traceback and OS memory metrics.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import traceback


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', type=Path, required=True)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--limit-mib', type=int, default=0)
    parser.add_argument('--stream', action='store_true')
    parser.add_argument('--roundtrip', action='store_true')
    args = parser.parse_args()
    args.evidence.mkdir(parents=True, exist_ok=True)
    if args.limit_mib:
        receipt = args.evidence/'limit.json'
        receipt.unlink(missing_ok=True)
        controller = subprocess.Popen([sys.executable, str(Path(__file__).with_name('windows_memory_limit.py')),
            '--pid', str(os.getpid()), '--gib', str(args.limit_mib/1024), '--evidence', str(receipt)])
        deadline = time.monotonic()+10
        while not receipt.is_file():
            if controller.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError('Controlled limit was not applied')
            time.sleep(.05)
    sys.path.insert(0, str(args.engine.resolve()))
    from ecra.scan_diagnostics import memory
    from ecra.common import read_json
    reserve = bytearray(256*1024)
    result = dict(controlled_replay=True, input=str(args.input), bytes=args.input.stat().st_size,
                  limit_mib=args.limit_mib, stream=args.stream, interpreter=sys.version, successful=False)
    start = time.monotonic()
    try:
        if args.stream:
            from ecra.workflow import read_saved_json
            data = read_saved_json(args.input, canonical_accesses=True)
        else:
            data = read_json(args.input)
        result['loaded_seconds'] = time.monotonic()-start
        result['loaded_memory'] = memory()
        result['fact_counts'] = {key: len(value) for key, value in data.items() if isinstance(value, list)}
        if args.roundtrip:
            sha = hashlib.sha256()
            for chunk in json.JSONEncoder(ensure_ascii=False, separators=(',', ':')).iterencode(data):
                sha.update(chunk.encode('utf-8'))
            result['roundtrip_sha256'] = sha.hexdigest()
            source = hashlib.sha256()
            with args.input.open('rb') as stream:
                for block in iter(lambda: stream.read(1024*1024), b''):
                    source.update(block)
            result['source_sha256'] = source.hexdigest()
            result['lossless_roundtrip'] = sha.digest() == source.digest()
        result['successful'] = not args.roundtrip or result['lossless_roundtrip']
    except BaseException as exc:
        reserve = None
        result.update(exception_type=type(exc).__name__, message=str(exc))
        frame = exc.__traceback__
        while frame:
            if frame.tb_frame.f_code.co_name == 'read_saved_json':
                state = frame.tb_frame.f_locals
                result['failed_table'] = state.get('key')
                result['loaded_counts_at_failure'] = {key: len(value) for key, value in
                    state.get('result', {}).items() if isinstance(value, (list, dict))}
            frame = frame.tb_next
        (args.evidence/'exception.log').write_text(traceback.format_exc(), encoding='utf-8')
    finally:
        result.update(seconds=time.monotonic()-start, memory=memory())
        (args.evidence/'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result))
    return 0 if result['successful'] else 3


if __name__ == '__main__':
    import os
    raise SystemExit(main())
