"""Controlled real-TU pointer regression; never a native full-scan acceptance."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import traceback


def encoded_hash(value):
    sha = hashlib.sha256()
    for fragment in json.JSONEncoder(sort_keys=True, ensure_ascii=False, separators=(',', ':')).iterencode(value):
        sha.update(fragment.encode('utf-8'))
    return sha.hexdigest()


def fingerprints(facts):
    result = {}
    for table, value in facts.items():
        if table in ('pointer_target_encoding', 'pointer_target_block_bits'):
            continue
        if table == 'pointer_target_sets':
            # Independent integer reconstruction checks the complete new
            # representation against V1. At most one set is expanded at once.
            rows = []
            for ident, encoded in value.items():
                if isinstance(encoded, str):
                    bitmap = int(encoded, 16)
                else:
                    bitmap = 0
                    for index, chunk in encoded:
                        bitmap |= int(chunk, 16) << (index*facts['pointer_target_block_bits'])
                rows.append((ident, hashlib.sha256(format(bitmap, 'x').encode('ascii')).hexdigest()))
            result[table] = dict(count=len(rows), sha256=encoded_hash(sorted(rows)))
        elif isinstance(value, list) and table != 'pointer_target_atoms':
            rows = sorted(bytes.fromhex(encoded_hash(row)) for row in value)
            sha = hashlib.sha256()
            for row in rows:
                sha.update(row)
            result[table] = dict(count=len(rows), sha256=sha.hexdigest())
        else:
            result[table] = dict(sha256=encoded_hash(value), ordered=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('engine', 'workers', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--count', type=int, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.engine.resolve()))
    from ecra.analysis import merge
    from ecra.fact_parts import FactParts
    from ecra.points_to import Solver
    import psutil  # External test dependency, never an ECRA runtime requirement.
    available = sorted(p for p in args.workers.glob('TU-*.response.json') if '.dependencies.' not in p.name)
    if not 0 < args.count <= len(available):
        parser.error('count must refer to actual captured translation units')
    data = dict(controlled_replay=True, full_scan_acceptance=False, python=sys.version,
                translation_units=args.count, complete=False, files=[])
    start = time.monotonic()
    phase = 'merge'
    try:
        parts = FactParts()
        for path in available[:args.count]:
            meta = Path(str(path)+'.metadata.json')
            metadata = json.loads(meta.read_text(encoding='utf-8'))
            parts.append_metadata(path, metadata)
            data['files'].append(dict(path=str(path),bytes=path.stat().st_size,
                metadata_sha256=hashlib.sha256(meta.read_bytes()).hexdigest()))
        facts = merge(parts)
        parts.clear()
        data['merge_seconds'] = time.monotonic()-start
        data['before_solver_memory'] = psutil.Process().memory_info()._asdict()
        phase = 'pointer_solver'
        begin = time.monotonic()
        solver = Solver(facts)
        solver.solve()
        data.update(solver_seconds=time.monotonic()-begin,
                    pointer_encoding=facts.get('pointer_target_encoding'),
                    after_solver_memory=psutil.Process().memory_info()._asdict())
        phase = 'semantic_fingerprint'
        data['fingerprints'] = fingerprints(facts)
        data['representation_fields_compared_semantically'] = [
            'pointer_target_encoding', 'pointer_target_block_bits', 'pointer_target_sets']
        data['complete'] = True
    except BaseException:
        data.update(failed_phase=phase, traceback=traceback.format_exc())
        raise
    finally:
        data.update(seconds=time.monotonic()-start, memory=psutil.Process().memory_info()._asdict())
        with args.output.open('w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
    print(str(args.output))


if __name__ == '__main__':
    main()
