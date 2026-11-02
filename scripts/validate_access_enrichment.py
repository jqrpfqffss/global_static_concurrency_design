"""Measure complete access-container allocation against the frozen v19 loop.

This is a capacity fixture, not INAV/native G1/G2, a physical32GB G3 run, or a
disk-reduction claim. Both passes retain every access/path/duplicate and hash
the complete ordered result after measuring Python allocation. No firmware,
archive, cache or original baseline is modified.
"""
import argparse
import gc
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time
import tracemalloc

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ecra.access_enrichment import enrich_accesses
from ecra.workspace import no_links


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--count', type=int, default=128000)
    args = parser.parse_args()
    if not 16000 <= args.count <= 250000:
        parser.error('Use16000..250000 fixture accesses; this is not a full native scan')
    work = no_links(args.work.resolve())
    work.mkdir(parents=True, exist_ok=False)
    spec = importlib.util.spec_from_file_location('access_allocation_inputs', ROOT/'tests/test_access_enrichment.py')
    harness = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(harness)
    paths = [ROOT/'ecra/analysis.py', ROOT/'ecra/access_enrichment.py',
             ROOT/'tests/fixtures/v19_access_enrichment.py', ROOT/'tests/test_access_enrichment.py']
    original = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    metrics = []
    for name, function in [('frozen_v19_loop', harness.reference.enrich_accesses), ('candidate', enrich_accesses)]:
        data = harness.inputs([dict(access_id=str(i), function_id='f'+str(i % 4), symbol_id='s'+str(i % 40))
            for i in range(args.count)])
        gc.collect(); start = time.monotonic(); tracemalloc.start(1)
        try:
            facts, by_var = harness.run(function, data)
            live, peak = tracemalloc.get_traced_memory()
            seconds = time.monotonic()-start
        finally:
            tracemalloc.stop()
        digest = hashlib.sha256()
        for chunk in json.JSONEncoder(ensure_ascii=False, separators=(',', ':')).iterencode((facts, by_var)):
            digest.update(chunk.encode('utf-8'))
        metrics.append(dict(engine=name, accesses=len(facts['accesses']),
            by_var_accesses=sum(len(v) for v in by_var.values()), ordered_full_sha256=digest.hexdigest(),
            measured_python_live_bytes=live, measured_python_peak_bytes=peak, instrumented_seconds=seconds))
        del data, facts, by_var
        gc.collect()
    differences = [str(p) for p in paths if hashlib.sha256(p.read_bytes()).hexdigest() != original[str(p)]]
    result = dict(passed=not differences and metrics[0]['ordered_full_sha256'] == metrics[1]['ordered_full_sha256']
        and metrics[1]['measured_python_live_bytes'] < metrics[0]['measured_python_live_bytes']
        and all(m['accesses'] == args.count == m['by_var_accesses'] for m in metrics),
        scope=__doc__, metrics=metrics, implementation_sha256=original, implementation_differences=differences,
        native_scan='NOT_EXERCISED', physical32GB='NOT_VERIFIED', large_G1_G3='NOT_VERIFIED')
    (work/'acceptance.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', 'utf-8')
    print(json.dumps(result), flush=True)
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
