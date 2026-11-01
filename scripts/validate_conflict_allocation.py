"""Compare allocation-only conflict changes against a small frozen native scan.

Existing native data is read, not re-extracted. This diagnostic restores only a
database <=32MiB, compares all existing variable conflict rows, and measures a
separate 12,000-access/48,000-route capacity fixture. It is not large-native G1
or physical-32GB G3 acceptance.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import time
import tracemalloc

TOOL=Path(__file__).resolve().parents[1];sys.path.insert(0,str(TOOL))
from ecra.analysis import conflict_pairs
from ecra.report_package import sha256
from ecra.scan_store import EvidenceProvider


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True);parser.add_argument('--work',type=Path,required=True)
    args=parser.parse_args();source=args.source.resolve();work=args.work.resolve()
    if source.stat().st_size>32*1024**2:raise ValueError('This diagnostic only restores an explicitly small graph <=32MiB')
    work.mkdir(parents=True,exist_ok=False);before=sha256(source)
    spec=importlib.util.spec_from_file_location('ecra._conflict_reference',TOOL/'tests/fixtures/e69_conflict_pairs.py')
    reference=importlib.util.module_from_spec(spec);spec.loader.exec_module(reference)
    provider=EvidenceProvider(source);provider.validate(deep=True);facts=provider.load('facts')
    contexts={row['id']:row for row in facts['contexts']};rows=0;pairs=0
    encode=lambda value:json.dumps(value,ensure_ascii=False,separators=(',',':'))
    for variable in facts['variables']:
        if 'conflict_pairs' not in variable:continue
        accesses=[a for a in variable['accesses'] if a.get('reachability')!='PROVEN_UNREACHABLE']
        actual=conflict_pairs(accesses,variable['concurrency_relations'],contexts)
        if encode(actual)!=encode(variable['conflict_pairs']):raise ValueError('Frozen native conflict mismatch: '+variable['symbol_id'])
        rows+=1;pairs+=len(actual)
    del facts,variable,accesses,actual
    accesses=[dict(access_id='a'+str(i),access_kind='WRITE',function_id='f'+str(i),file='main.c',line=i+1,
        all_call_chains=dict(main=[['entry','f'+str(i)] for _ in range(4)])) for i in range(12000)]
    metrics=[]
    for name,function in [('frozen_e69',reference.conflict_pairs),('candidate',conflict_pairs)]:
        start=time.perf_counter();tracemalloc.start(1)
        try:
            if function(accesses,[],dict(main=dict(physical_id='M')))!=[]:raise ValueError('Single serial context changed')
            metrics.append(dict(engine=name,seconds=time.perf_counter()-start,temporary_python_peak_bytes=tracemalloc.get_traced_memory()[1]))
        finally:tracemalloc.stop()
    result=dict(passed=rows>0 and sha256(source)==before and metrics[1]['temporary_python_peak_bytes']<metrics[0]['temporary_python_peak_bytes']*.85,
        scope=__doc__,source=str(source),source_sha256=before,source_unchanged=sha256(source)==before,
        native_variable_conflicts_compared=rows,native_conflict_rows=pairs,differences=0,capacity_metrics=metrics,
        analysis_sha256=sha256(TOOL/'ecra/analysis.py'),reference_sha256=sha256(TOOL/'tests/fixtures/e69_conflict_pairs.py'))
    (work/'acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=True))
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
