"""Measure ordered mask evidence against a frozen independent original module.

Generated CFG/access capacity inputs exercise the real MaskAnalysis.run method.
This is not a native project, largeG1/G2/G3, physical32GB, hardware test or disk
saving. Every original observation, window, duplicate and array remains hashed.
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
from ecra.protection import MaskAnalysis
from ecra.workspace import no_links


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--symbols', type=int, default=5000)
    args = parser.parse_args()
    if not 1000 <= args.symbols <= 12000:
        parser.error('Use1000..12000 capacity symbols; not a native validation')
    work = no_links(args.work.resolve())
    work.mkdir(parents=True, exist_ok=False)
    spec = importlib.util.spec_from_file_location('mask_allocation_inputs', ROOT/'tests/test_mask_evidence_allocation.py')
    harness = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(harness)
    paths = [ROOT/'ecra/protection.py', ROOT/'ecra/read_only_evidence.py', ROOT/'ecra/json_rows.py',
             ROOT/'tests/fixtures/v19_mask_analysis.py', ROOT/'tests/test_mask_evidence_allocation.py']
    original = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    metrics = []
    for name, cls in [('frozen_v19_mask_analysis', harness.reference.MaskAnalysis), ('candidate', MaskAnalysis)]:
        facts = harness.inputs(args.symbols)
        gc.collect(); start = time.monotonic(); tracemalloc.start(1)
        try:
            cls(facts, dict(critical_sections=[])).run()
            live, peak = tracemalloc.get_traced_memory()
            seconds = time.monotonic()-start
        finally:
            tracemalloc.stop()
        digest = hashlib.sha256()
        for chunk in json.JSONEncoder(ensure_ascii=False, separators=(',', ':')).iterencode(facts):
            digest.update(chunk.encode('utf-8'))
        metrics.append(dict(engine=name, accesses=len(facts['accesses']), windows=len(facts['mask_windows']),
            observations=sum(len(a['mask_states']) for a in facts['accesses']), ordered_full_sha256=digest.hexdigest(),
            measured_python_live_bytes=live, measured_python_peak_bytes=peak, instrumented_seconds=seconds))
        del facts
        gc.collect()
    differences = [str(p) for p in paths if hashlib.sha256(p.read_bytes()).hexdigest() != original[str(p)]]
    result = dict(passed=not differences and metrics[0]['ordered_full_sha256'] == metrics[1]['ordered_full_sha256']
        and metrics[1]['measured_python_live_bytes'] < metrics[0]['measured_python_live_bytes']
        and all(m['accesses'] == args.symbols*5 and m['windows'] == args.symbols*2 for m in metrics),
        scope=__doc__, metrics=metrics, implementation_sha256=original, implementation_differences=differences,
        native_scan='NOT_EXERCISED', physical32GB='NOT_VERIFIED', large_G1_G3='NOT_VERIFIED')
    (work/'acceptance.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', 'utf-8')
    print(json.dumps(result), flush=True)
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
