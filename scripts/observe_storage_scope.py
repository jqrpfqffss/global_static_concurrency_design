"""Observe an explicit multi-root storage scope without changing its files.

Windows file allocation, hardlinks deduplicated across roots. Samples are
non-atomic directory walks, not an exact instantaneous or historical peak.
Open unlinked files, directory/MFT/ADS allocation remain unobservable here.
This tool never grants the full G4 gate or deletes/compresses user data.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ecra.workspace import no_links, studio_data_root
from scripts.native_metrics import FileAllocation


def read(path):
    try:
        return json.loads(Path(path).read_text('utf-8'))
    except (OSError, ValueError):
        return {}


def validate_roots(spec, output):
    roots = []
    for item in spec['roots']:
        if not isinstance(item.get('name'), str) or not item['name']:
            raise ValueError('Each scope requires a name')
        root = no_links(item['path'])
        if output == root or output.is_relative_to(root):
            raise ValueError('Observer output must be outside every observed root')
        roots.append(dict(item, path=root))
    if not roots or len({row['name'] for row in roots}) != len(roots):
        raise ValueError('Scope names must be nonempty and unique')
    for index, first in enumerate(roots):
        for second in roots[index+1:]:
            a, b = first['path'], second['path']
            if a == b or a.is_relative_to(b) or b.is_relative_to(a):
                raise ValueError('Overlapping scope paths are not allowed')
    return roots


def sample(roots, ledger):
    started = time.monotonic()
    value = dict(started_utc=datetime.now(timezone.utc).isoformat(), roots=[], files=0,
                 logical_bytes=0, allocated_bytes=0, unique_files=0,
                 sampling_partial=False, errors=[], non_atomic_window=True)
    allocation = FileAllocation()
    ledger.execute('DELETE FROM identities')
    for item in roots:
        root = item['path']
        row = dict(name=item['name'], path=str(root), files=0, logical_bytes=0,
                   allocated_bytes=0, unique_files=0, state='OBSERVED')
        value['roots'].append(row)
        try:
            no_links(root)
        except ValueError as error:
            row['state']='REJECTED_LINK';value['errors'].append(dict(path=str(root),error=str(error)));continue
        if not root.exists():
            row['state'] = 'NOT_CREATED_YET' if item.get('allow_missing_until_created') is True and not item.get('_observed_exists') else 'MISSING'
            if row['state'] == 'MISSING':
                value['errors'].append(dict(path=str(root),error='Required scope missing'))
            continue
        item['_observed_exists']=True
        pending = [root]
        while pending:
            folder = pending.pop()
            try:
                no_links(folder)
                with os.scandir(folder) as entries:
                    for entry in entries:
                        path = Path(entry.path)
                        try:
                            before = entry.stat(follow_symlinks=False)
                            if entry.is_symlink() or getattr(before,'st_file_attributes',0)&0x400:
                                value['errors'].append(dict(path=str(path),error='Link/reparse object not followed; target scope unverified'))
                                continue
                            if entry.is_dir(follow_symlinks=False):
                                pending.append(path); continue
                            if not entry.is_file(follow_symlinks=False):
                                raise ValueError('Unsupported observed object')
                            allocated, identity = allocation.information(path)
                            after = path.stat()
                            if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):
                                value['errors'].append(dict(path=str(path),error='File changed during allocation sample'))
                            added = ledger.execute('INSERT OR IGNORE INTO identities VALUES (?,?)',
                                                   (str(identity[0]),identity[1])).rowcount
                            for total in (row,value):
                                total['files'] += 1; total['logical_bytes'] += before.st_size
                                if added:
                                    total['unique_files'] += 1; total['allocated_bytes'] += allocated
                        except (OSError,ValueError) as error:
                            value['errors'].append(dict(path=str(path),error=str(error)))
            except (OSError,ValueError) as error:
                value['errors'].append(dict(path=str(folder),error=str(error)))
    ledger.commit()
    value.update(sampling_partial=bool(value['errors']),seconds=time.monotonic()-started,
                 completed_utc=datetime.now(timezone.utc).isoformat())
    return value


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--interval-seconds',type=float,default=30)
    parser.add_argument('--maximum-hours',type=float,default=24)
    parser.add_argument('--once',action='store_true')
    args=parser.parse_args()
    if not 1<=args.interval_seconds<=300 or not 0<args.maximum_hours<=72:
        raise ValueError('Use1–300 second intervals and a positive maximum up to72hours')
    spec=read(args.spec);output=studio_data_root(args.output)
    roots=validate_roots(spec,output);output.mkdir(parents=True,exist_ok=False)
    summary=dict(passed=False,observation_complete=False,all_gates_passed=False,status='OBSERVING',pid=os.getpid(),scope=__doc__,spec=spec,
                 samples=0,partial_samples=0,peak_observed_window_allocated_bytes=0,
                 peak_observed_window_logical_bytes=0,peak_complete_window_allocated_bytes=0,
                 file_contents_read_or_written=False,full_G4='NOT_CLOSED_AUTOMATICALLY')
    def save():
        target=output/'summary.json';temporary=output/'summary.pending'
        temporary.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n','utf-8');os.replace(temporary,target)
    save();started=time.monotonic()
    with closing(sqlite3.connect(output/'identities.db')) as ledger, (output/'samples.jsonl').open('x',encoding='utf-8') as stream:
        ledger.execute('PRAGMA cache_size=-4096')
        ledger.execute('CREATE TABLE identities(volume TEXT,file_id BLOB,PRIMARY KEY(volume,file_id)) WITHOUT ROWID')
        while True:
            value=sample(roots,ledger)
            value['elapsed_seconds']=time.monotonic()-started
            gate=read(spec['gate']) if spec.get('gate') else {}
            value['gate_status']=gate.get('status','NOT_AVAILABLE')
            if spec.get('phase_file'):value['phase']=read(spec['phase_file']).get('phase','NOT_AVAILABLE')
            stream.write(json.dumps(value,ensure_ascii=True)+'\n');stream.flush();os.fsync(stream.fileno())
            summary.update(samples=summary['samples']+1,last=value,elapsed_seconds=value['elapsed_seconds'])
            summary['partial_samples']+=int(value['sampling_partial'])
            for key in ['logical','allocated']:
                field='peak_observed_window_'+key+'_bytes';summary[field]=max(summary[field],value[key+'_bytes'])
            if not value['sampling_partial']:
                summary['peak_complete_window_allocated_bytes']=max(summary['peak_complete_window_allocated_bytes'],value['allocated_bytes'])
            if args.once:
                all_present=all(row['state']=='OBSERVED' for row in value['roots'])
                summary.update(observation_complete=True,all_roots_created=all_present,passed=not value['sampling_partial'] and all_present,status='ONE_SAMPLE_COMPLETE');save();break
            status=gate.get('status','')
            if status in {'PASS_SCOPED','FAIL'} or status.startswith('NOT_RUN'):
                all_present=all(row['state']=='OBSERVED' for row in value['roots'])
                summary.update(observation_complete=True,gate_status=status,gate_passed=gate.get('passed') is True,
                               all_roots_created=all_present,passed=gate.get('passed') is True and summary['partial_samples']==0 and all_present,status='GATE_FINISHED');save();break
            if value['elapsed_seconds']>=args.maximum_hours*3600:
                summary.update(status='TIME_LIMIT_GATE_NOT_FINISHED');save();break
            save();time.sleep(max(0,args.interval_seconds-value['seconds']))
    print(json.dumps({key:summary[key] for key in ['passed','samples','partial_samples','peak_observed_window_allocated_bytes','status','full_G4']}),flush=True)
    return 0 if summary['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
