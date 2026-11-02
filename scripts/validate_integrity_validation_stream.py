"""Complete synthetic graph verifier SQL/heap measurement, not nativeG1/G3/G4."""
import argparse
import gc
import hashlib
import inspect
import json
from pathlib import Path
import sys
import textwrap
import time
import tracemalloc
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import ecra.scan_store as store
from tests.fixtures import v3cf_validate as original


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--work',type=Path,required=True)
    p.add_argument('--objects',type=int,default=12000);args=p.parse_args()
    if args.objects<5000:p.error('Exercise the complete large-object fallback with at least5000 objects')
    work=args.work.resolve();work.mkdir(parents=True,exist_ok=False);path=work/'complete-fixture.db'
    source=ROOT/'ecra/scan_store.py';source_sha=hashlib.sha256(source.read_bytes()).hexdigest()
    reference=textwrap.dedent(inspect.getsource(original.validate_original)).replace('def validate_original(','def validate(',1)
    assert hashlib.sha256(reference.encode()).hexdigest()==original.ORIGINAL_LF_SHA256
    store.publish_scan(path,dict(variables=[],future={str(i):dict(value=str(i),items=['same',i]) for i in range(args.objects)}),
                       dict(findings=[]),scan_id='validation-fixture',project_id='validation-only')
    before=hashlib.sha256(path.read_bytes()).hexdigest();connect=store.connect_readonly;results=[]
    for name,validator in [('original',original.validate_original),('streamed',store.EvidenceProvider.validate)]:
        statements=[0]
        def connection(p):
            conn=connect(p)
            def trace(_):statements[0]+=1
            conn.set_trace_callback(trace);return conn
        gc.collect();tracemalloc.start();started=time.monotonic()
        with patch.object(store,'connect_readonly',connection),patch.object(original,'connect_readonly',connection):
            binding=validator(store.EvidenceProvider(path),deep=True)
        seconds=time.monotonic()-started;current,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
        results.append(dict(name=name,source_sql_statements=statements[0],seconds=seconds,
                            traced_current_bytes=current,traced_peak_bytes=peak,binding=binding))
    r=dict(passed=results[0]['binding']==results[1]['binding'] and results[1]['source_sql_statements']<results[0]['source_sql_statements']//10
           and hashlib.sha256(path.read_bytes()).hexdigest()==before and hashlib.sha256(source.read_bytes()).hexdigest()==source_sha,
           scope=__doc__,objects=args.objects,source_sha256=source_sha,original_lf_sha256=original.ORIGINAL_LF_SHA256,
           fixture_sha256=before,fixture_bytes=path.stat().st_size,results=results,
           timing_scope='Both traced/counted, original first then streamed; not exclusive native performance. Source statements only; complete projection rebuild is unchanged.')
    (work/'acceptance.json').write_text(json.dumps(r,indent=2)+'\n','utf-8');print(json.dumps(r),flush=True)
    return 0 if r['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
