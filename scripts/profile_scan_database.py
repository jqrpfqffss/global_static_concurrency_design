"""Read-only B-tree allocation diagnostic, using an explicit DBSTAT-enabled CLI.

Developer measurement only: no database rewrite, cleanup or native-G4 claim.
Windows Python's SQLite need not include DBSTAT; the supplied local executable
is versioned/hashed separately and never becomes a Portable dependency.
"""
import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ecra.common import write_json
from ecra.report_package import sha256
from ecra.scan_store import EvidenceProvider
from ecra.studio.process_budget import ProcessBudget
from ecra.studio.resource_policy import temporary_environment
from ecra.studio.write_guard import OwnedProcess
from ecra.workspace import no_links,studio_data_root


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['database','sqlite','work']:parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--expected-sha256',required=True)
    parser.add_argument('--max-seconds',type=float,default=1200,help='Finite query deadline; incomplete diagnostics never become PASS')
    args=parser.parse_args()
    if not math.isfinite(args.max_seconds) or args.max_seconds<=0:parser.error('--max-seconds must be finite and positive')
    if len(args.expected_sha256)!=64 or any(c not in '0123456789abcdef' for c in args.expected_sha256):parser.error('Expected SHA-256 must be 64 lowercase hex characters')
    database=no_links(args.database.resolve());tool=no_links(args.sqlite.resolve());work=studio_data_root(args.work.resolve())
    if not database.is_file() or not tool.is_file():raise ValueError('Database and SQLite executable must already exist')
    if database.is_relative_to(work) or work.is_relative_to(database.parent):raise ValueError('Measurement scratch cannot overlap the source archive')
    if any(Path(str(database)+suffix).exists() for suffix in ['-wal','-journal']):raise ValueError('Use a frozen checkpointed database; active WAL/journal is outside this diagnostic scope')
    before=(database.stat().st_size,database.stat().st_mtime_ns)
    binding=EvidenceProvider(database).metadata()
    work.mkdir(parents=True,exist_ok=False);(work/'controller.py').write_bytes(Path(__file__).read_bytes())
    receipt=dict(passed=False,status='PRECHECK',scope=__doc__,database=str(database),source_binding=binding,
                 source_bytes=before[0],expected_source_sha256=args.expected_sha256,
                 sqlite_executable=str(tool),sqlite_executable_sha256=sha256(tool),
                 sqlite_version=subprocess.check_output([str(tool),'-version'],text=True).strip(),
                 documentation='https://sqlite.org/dbstat.html',budget_bytes=1024**3,peaks={})
    receipt['query_deadline_seconds']=args.max_seconds
    target=work/'acceptance.json'
    def save():write_json(target,receipt)
    save();process=None;budget=ProcessBudget(1024**3);started=time.monotonic()
    query=('PRAGMA trusted_schema=OFF; PRAGMA query_only=ON; PRAGMA cache_size=-32768; '
           'SELECT name,pageno AS btree_pages,ncell AS btree_cells,pgsize AS logical_page_bytes,'
           'payload AS payload_bytes,unused AS unused_bytes,mx_payload AS max_cell_payload_bytes '
           'FROM dbstat WHERE aggregate=TRUE ORDER BY pgsize DESC;')
    command=[str(tool),'-batch','-readonly','-init','NUL','-json',str(database),query]
    receipt.update(command=command,status='RUNNING_DBSTAT');save()
    try:
        env=temporary_environment(work,dict(os.environ,PYTHONIOENCODING='utf-8'))
        env['SQLITE_TMPDIR']=env['TEMP']
        with (work/'dbstat.json').open('xb') as output:
            process=OwnedProcess(command,cwd=work,env=env,log=output);budget.assign(process);process.resume()
            while process.poll() is None:
                sample=budget.sample()
                for key in ['working_set_bytes','private_bytes','peak_job_commit_bytes']:
                    receipt['peaks'][key]=max(receipt['peaks'].get(key,0),sample.get(key,0))
                receipt.update(seconds=time.monotonic()-started);save();time.sleep(2)
                if time.monotonic()-started>args.max_seconds and process.poll() is None:
                    receipt['safety_stop']='DIAGNOSTIC_QUERY_TIME_LIMIT';save();process.terminate();break
            code=process.wait(timeout=30)
            sample=budget.sample()
            receipt['peaks']['peak_job_commit_bytes']=max(receipt['peaks'].get('peak_job_commit_bytes',0),sample.get('peak_job_commit_bytes',0))
        if code:raise RuntimeError('DBSTAT exited '+str(code)+'; preserve raw dbstat.json')
        rows=json.loads((work/'dbstat.json').read_text('utf-8'))
        if not rows or not any(r['name']=='nodes' for r in rows):raise ValueError('No recognized evidence-graph B-trees')
        if any(type(r['logical_page_bytes']) is not int or r['logical_page_bytes']<0 for r in rows):raise ValueError('Invalid page accounting')
        total=sum(r['logical_page_bytes'] for r in rows)
        if total>before[0]:raise ValueError('Reported B-tree bytes exceed source file')
        receipt.update(status='VERIFYING_SOURCE',dbstat_seconds=time.monotonic()-started,btree_allocations=rows,
                       btree_logical_bytes=total,unattributed_logical_bytes=before[0]-total,
                       omissions='DBSTAT excludes freelist/pointer-map/lock pages; also excludes filesystem metadata, all other archives/cache/build/worktree/WAL and physical-disk peak')
        save();actual=sha256(database)
        unchanged=(database.stat().st_size,database.stat().st_mtime_ns)==before and actual==args.expected_sha256
        receipt.update(passed=unchanged,status='COMPLETE' if unchanged else 'FAIL_SOURCE_CHANGED',source_sha256=actual,
                       source_unchanged=unchanged,seconds=time.monotonic()-started)
    except BaseException as exc:
        receipt.update(passed=False,status='FAILED',error=repr(exc));raise
    finally:
        budget.close()
        if process is not None:
            if process.poll() is None:process.wait(timeout=30)
            process.close()
        save();print(json.dumps(dict(passed=receipt['passed'],status=receipt['status'],receipt=str(target))),flush=True)
    return 0 if receipt['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
