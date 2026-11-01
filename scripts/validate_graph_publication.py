"""Re-publish an explicitly small frozen native graph and compare every root.

This exercises in-memory publication, including shared object identity. It is
not a native extraction, a large-graph reader, or a resource/semantic G1 gate.
The size guard prevents this diagnostic from restoring a large scan in RAM.
"""
import argparse
from contextlib import closing
import json
from pathlib import Path
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ecra.report_package import sha256
from ecra.scan_store import EvidenceProvider,connect_readonly,publish_scan


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--work',type=Path,required=True)
    args=parser.parse_args();source=args.source.resolve();work=args.work.resolve()
    if source.stat().st_size>32*1024**2:raise ValueError('Only an explicitly small frozen graph (<=32MiB) may be restored by this diagnostic')
    work.mkdir(parents=True,exist_ok=False);before=sha256(source);start=time.monotonic()
    provider=EvidenceProvider(source);provider.validate(deep=True)
    with closing(connect_readonly(source)) as conn:
        scan=dict(conn.execute('SELECT * FROM scans').fetchone())
        expected={row['name']:conn.execute('SELECT hash FROM nodes WHERE id=?',(row['node'],)).fetchone()[0]
            for row in conn.execute('SELECT * FROM roots')}
    if set(expected)!={'facts','report','provenance'}:raise ValueError('Unexpected roots; do not silently omit one')
    roots={name:provider.load(name) for name in expected}
    target=work/'republished.db'
    actual=publish_scan(target,roots['facts'],roots['report'],scan_id=scan['scan_id'],
        project_id=scan['project_id'],profile_id=scan['profile_id'],provenance=roots['provenance'],validation_state=scan['state'])
    EvidenceProvider(target).validate(deep=True)
    actual={name:value[1] for name,value in actual.items()}
    unchanged=sha256(source)==before
    result=dict(passed=expected==actual and unchanged,scope=__doc__,source=str(source),
        source_bytes=source.stat().st_size,source_sha256=before,source_unchanged=unchanged,
        target=str(target),target_bytes=target.stat().st_size,expected_roots=expected,
        actual_roots=actual,seconds=round(time.monotonic()-start,3),
        scan_store_sha256=sha256(Path(__file__).resolve().parents[1]/'ecra/scan_store.py'))
    with (work/'acceptance.json').open('x',encoding='utf-8') as stream:json.dump(result,stream,ensure_ascii=True,indent=2)
    print(json.dumps(dict(passed=result['passed'],seconds=result['seconds'])))
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
