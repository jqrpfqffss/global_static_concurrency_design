"""Verify complete solver fixed points in hash-bound, arbitrarily large facts.

Scan bytes in bounded chunks; do not deserialize the fact rows. Known metadata
keys must occur exactly once, and the entire file is hashed in the same pass.
"""
import argparse
import codecs
import hashlib
import json
import os
from pathlib import Path
import time
import traceback

KEYS = ('points_to_stats', 'context_points_to_stats')
METADATA_BYTES = 65536


def read_solver_stats(path, expected_sha256=None, *, chunk_bytes=8*1024*1024):
    if chunk_bytes <= 0:
        raise ValueError('chunk_bytes must be positive')
    found = {key: {} for key in KEYS}
    needles = {key: ('"'+key+'"').encode() for key in KEYS}
    sha = hashlib.sha256()
    tail = b''
    consumed = 0
    start = time.monotonic()
    with Path(path).open('rb') as stream:
        before = os.fstat(stream.fileno())
        while True:
            block = stream.read(chunk_bytes)
            eof = not block
            sha.update(block)
            base = consumed-len(tail)
            data = tail+block
            for key, needle in needles.items():
                offset = data.find(needle)
                while offset >= 0:
                    absolute = base+offset
                    if absolute not in found[key] and (offset == 0 or data[offset-1] != 92):
                        at = offset+len(needle)
                        while at < len(data) and data[at] in b' \t\r\n':
                            at += 1
                        if at < len(data) and data[at] == 58:
                            at += 1
                            while at < len(data) and data[at] in b' \t\r\n':
                                at += 1
                            try:
                                text = codecs.getincrementaldecoder('utf-8')().decode(
                                    data[at:at+METADATA_BYTES], final=False)
                                value, _ = json.JSONDecoder().raw_decode(text)
                            except (UnicodeDecodeError, json.JSONDecodeError):
                                if eof or len(data)-at >= METADATA_BYTES:
                                    raise ValueError('Invalid or oversized solver metadata: '+key)
                            else:
                                if not isinstance(value, dict) or type(value.get('complete')) is not bool:
                                    raise ValueError('Missing Boolean solver completeness: '+key)
                                found[key][absolute] = value
                    offset = data.find(needle, offset+len(needle))
            consumed += len(block)
            if eof:
                break
            tail = data[-METADATA_BYTES:]
        after = os.fstat(stream.fileno())
    if (before.st_size,before.st_mtime_ns) != (after.st_size,after.st_mtime_ns):
        raise ValueError('Facts changed during solver metadata verification')
    digest = sha.hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise ValueError('Facts hash differs from the completed scan checkpoint')
    if any(len(values) != 1 for values in found.values()):
        raise ValueError('Missing or ambiguous solver metadata')
    summaries = {key: next(iter(found[key].values())) for key in KEYS}
    return dict(source=str(Path(path).resolve()),bytes=consumed,sha256=digest,
                hash_bound=expected_sha256 is not None,solver_summaries=summaries,
                all_complete=all(value['complete'] for value in summaries.values()),
                seconds=time.monotonic()-start)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('facts',type=Path)
    parser.add_argument('--state',type=Path,help='Defaults to adjacent scan_state.json')
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    result = dict(all_complete=False,hash_bound=False)
    try:
        state = args.state or args.facts.with_name('scan_state.json')
        expected = json.loads(state.read_text(encoding='utf-8'))['facts_sha256']
        if not isinstance(expected,str) or len(expected) != 64:
            raise ValueError('A completed checkpoint facts hash is required')
        result = read_solver_stats(args.facts,expected)
        args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps(result))
        return 0 if result['all_complete'] else 1
    except Exception:
        result['traceback'] = traceback.format_exc()
        args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
        raise


if __name__ == '__main__':
    raise SystemExit(main())
