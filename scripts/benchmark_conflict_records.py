"""Complete ordered fixture comparison and physical Python allocation only.

Not a native firmware run, a whole-process memory peak, or G2/G3 acceptance.
Both prior functions are independently frozen under tests/fixtures.
"""
import argparse
import gc
import hashlib
import json
from pathlib import Path
import sys
import time
import tracemalloc

TOOL=Path(__file__).resolve().parents[1];sys.path.insert(0,str(TOOL))
from ecra.analysis import conflict_pairs
from tests.test_conflict_allocation import access,encoded,reference
from tests.test_conflict_instances import previous


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--receipt',type=Path,required=True);args=parser.parse_args()
    if args.receipt.exists():raise FileExistsError('Preserve the prior measurement receipt')
    result=dict(passed=False,scope=__doc__,metrics=[],analysis_sha256=hashlib.sha256((TOOL/'ecra/analysis.py').read_bytes()).hexdigest())
    try:
        for case,n,c in [('inline3969',63,2),('overlap32000',2000,16),('single12000',12000,1)]:
            contexts={f'c{i:02d}':dict(physical_id=f'p{i}') for i in range(c)};rows=[]
            if case=='inline3969':rows=[access(i,'c00','WRITE',2) for i in range(n)]+[access(n+i,'c01','READ',3) for i in range(n)]
            else:
                for i in range(n):
                    row=access(i,'c00','READ' if i%2 else 'WRITE');row['all_call_chains']={cid:[[cid,'f'+str(i)]] for cid in contexts};rows.append(row)
            input_hash=hashlib.sha256(encoded(rows).encode()).hexdigest();hashes=[]
            for label,function in [('e69_original',reference.conflict_pairs),('selectors626834e',previous.conflict_pairs),('current',conflict_pairs)]:
                gc.collect();tracemalloc.start(1);start=time.perf_counter()
                try:output=function(rows,[],contexts);elapsed=time.perf_counter()-start;retained,peak=tracemalloc.get_traced_memory()
                finally:tracemalloc.stop()
                hashed=hashlib.sha256(encoded(output).encode()).hexdigest();hashes.append(hashed)
                value=dict(case=case,engine=label,rows=len(output),seconds=elapsed,retained_python_bytes=retained,temporary_python_peak_bytes=peak,full_ordered_json_sha256=hashed)
                result['metrics'].append(value);print(json.dumps(value),flush=True);del output
            assert len(set(hashes))==1,'Ordered output differs in '+case
            assert input_hash==hashlib.sha256(encoded(rows).encode()).hexdigest(),'Source access records changed'
        result['passed']=True
    finally:
        with args.receipt.open('x',encoding='utf-8') as stream:json.dump(result,stream,ensure_ascii=False,indent=2)
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
