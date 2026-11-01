"""Compare complete variable evidence against frozen e69; Python allocations only."""
import argparse
from dataclasses import asdict
import gc
import hashlib
import json
from pathlib import Path
import sys
import time
import tracemalloc

TOOL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL))
from ecra.evidence import EvidenceIndex
from tests.test_evidence_ancestors import fixture, reference, REFERENCE, encoded


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--count', type=int, default=2000)
    parser.add_argument('--receipt', type=Path, required=True)
    args = parser.parse_args()
    if args.count < 1: parser.error('count must be positive')
    if args.receipt.exists(): raise FileExistsError(args.receipt)
    calls = [dict(caller_function_id='f'+str(i), callee_function_id='f'+str(i+1))
             for i in range(args.count-1)]
    variable, accesses, facts, contexts = fixture(args.count, calls)
    before = encoded([variable, accesses, facts, contexts])
    results = []
    for name, cls in [('e69', reference.EvidenceIndex), ('current', EvidenceIndex)]:
        gc.collect(); tracemalloc.start(); start = time.perf_counter()
        index = cls(facts, {}, {'project': {}}, set())
        evidence = index.build(variable, accesses, contexts, [])
        seconds = time.perf_counter()-start
        retained, peak = tracemalloc.get_traced_memory(); tracemalloc.stop()
        data = encoded(asdict(evidence)).encode('utf-8')
        assert len(evidence.function_ids) == args.count
        assert len(evidence.call_edge_indices) == args.count-1
        results.append(dict(engine=name,seconds=seconds,python_retained_bytes=retained,
                            python_peak_bytes=peak,output_sha256=hashlib.sha256(data).hexdigest(),
                            functions=len(evidence.function_ids),call_edges=len(evidence.call_edge_indices),
                            cached_closures=len(index.ancestor_cache)))
        del evidence, index, data
    passed = (results[0]['output_sha256'] == results[1]['output_sha256']
              and before == encoded([variable, accesses, facts, contexts]))
    receipt = dict(passed=passed,scope=__doc__,count=args.count,results=results,
                   inputs_unchanged=True,original_sha256=hashlib.sha256(REFERENCE.read_bytes()).hexdigest(),
                   implementation_sha256=hashlib.sha256((TOOL/'ecra/evidence.py').read_bytes()).hexdigest(),
                   limits='Capacity fixture only; excludes native RSS/Job, G1 large project, G3 and physical32GB')
    args.receipt.write_text(json.dumps(receipt,indent=2)+'\n','utf-8')
    print(json.dumps(receipt),flush=True)
    raise SystemExit(0 if passed else 1)


if __name__ == '__main__': main()
