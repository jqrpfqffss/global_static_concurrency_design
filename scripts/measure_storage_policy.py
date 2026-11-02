"""Read-only Windows file allocation for explicit, complete retention scopes.

File-backed identity ledger deduplicates hardlinks within each policy. No file
contents, attributes, compression or user data are changed. Reports exclude
directory/MFT/ADS allocation and cannot reconstruct a historical peak. Scope
and stability must be reviewed before a result is used for the G4 gate.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time

TOOL=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(TOOL))
from ecra.workspace import no_links,studio_data_root
from scripts.native_metrics import FileAllocation


def category(relative, component):
    names=[s.lower() for s in relative.parts]
    name=relative.name.lower()
    if component!='data':return 'shared_build_or_worktree'
    if name.endswith(('-wal','-shm','-journal')):return 'database_sidecars'
    if name=='scan.db':return 'canonical_static_db'
    if name=='reviews.db':return 'ai_human_db'
    if 'evidence' in names:return 'archived_evidence_objects'
    if 'workers' in names:return 'raw_worker_responses'
    if 'cache' in names:return 'cache'
    if 'builds' in names or 'build' in names:return 'build'
    if 'worktrees' in names or 'worktree' in names:return 'git_worktree'
    if 'exports' in names or name.endswith(('.ecra-report','.ecra-review-delta')):return 'exports'
    if name=='facts.db':return 'legacy_facts_db'
    if name=='facts.json':return 'legacy_facts_json'
    if 'reports' in names or 'inventory' in names or name.endswith(('.html','.md')):return 'legacy_derived_reports'
    if 'work' in names:return 'temporary_and_recovery_work'
    if 'diagnostics' in names or 'review' in names:return 'diagnostics_and_audit'
    return 'settings_and_other_retained_files'


def files(root):
    no_links(root)
    if root.is_file():
        yield root
        return
    if not root.is_dir():raise ValueError('Required retention scope does not exist: '+str(root))
    pending=[root]
    while pending:
        folder=pending.pop()
        with os.scandir(folder) as entries:
            for entry in entries:
                path=Path(entry.path);stat=entry.stat(follow_symlinks=False)
                if entry.is_symlink() or getattr(stat,'st_file_attributes',0)&0x400:
                    raise ValueError('Link/reparse point in retention scope: '+str(path))
                if entry.is_dir(follow_symlinks=False):pending.append(path)
                elif entry.is_file(follow_symlinks=False):yield path
                else:raise ValueError('Unsupported retained object: '+str(path))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--spec',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    spec=json.loads(args.spec.read_text('utf-8'))
    output=no_links(args.output);assert not output.exists()
    studio_data_root(output.parent)
    for components in spec['policies'].values():
        for component in components:
            root=no_links(component['path'])
            if output==root or output.is_relative_to(root):
                raise ValueError('Observation output and temporary ledger must be outside every retained input root')
    output.parent.mkdir(parents=True,exist_ok=True)
    allocation=FileAllocation();start=time.monotonic();results={}
    with tempfile.TemporaryDirectory(prefix='allocation-ledger-',dir=output.parent) as temporary, closing(sqlite3.connect(str(Path(temporary)/'ledger.db'))) as conn:
        conn.execute('PRAGMA cache_size=-4096')
        conn.execute('CREATE TABLE identities(policy TEXT, volume TEXT, file_id BLOB, PRIMARY KEY(policy,volume,file_id)) WITHOUT ROWID')
        conn.execute('CREATE TABLE entries(policy TEXT,path TEXT,logical INTEGER,mtime INTEGER,volume TEXT,file_id BLOB,allocated INTEGER,PRIMARY KEY(policy,path)) WITHOUT ROWID')
        for policy,components in spec['policies'].items():
            roots=[no_links(item['path']) for item in components]
            if any(a==b or a.is_relative_to(b) or b.is_relative_to(a) for i,a in enumerate(roots) for b in roots[i+1:]):
                raise ValueError('Overlapping scope roots would double-count logical files')
            result=dict(roots=[dict(name=x['name'],path=str(root)) for x,root in zip(components,roots)],
                        files=0,logical_bytes=0,allocated_bytes=0,unique_files=0,categories={},stable=False)
            results[policy]=result
            with conn:
                for item,root in zip(components,roots):
                    for file in files(root):
                        stat=file.stat();size,identity=allocation.information(file);volume=str(identity[0]);fid=identity[1]
                        relative=file.relative_to(root) if file!=root else Path(file.name)
                        kind=category(relative,item['name']);row=result['categories'].setdefault(kind,dict(files=0,logical_bytes=0,allocated_bytes=0,unique_files=0))
                        conn.execute('INSERT INTO entries VALUES (?,?,?,?,?,?,?)',(policy,str(file),stat.st_size,stat.st_mtime_ns,volume,fid,size))
                        added=conn.execute('INSERT OR IGNORE INTO identities VALUES (?,?,?)',(policy,volume,fid)).rowcount
                        for total in [row,result]:
                            total['files']+=1;total['logical_bytes']+=stat.st_size
                            if added:total['allocated_bytes']+=size;total['unique_files']+=1
            differences=[];observed=0
            for root in roots:
                for file in files(root):
                    stat=file.stat();size,identity=allocation.information(file);observed+=1
                    previous=conn.execute('SELECT logical,mtime,volume,file_id,allocated FROM entries WHERE policy=? AND path=?',(policy,str(file))).fetchone()
                    current=(stat.st_size,stat.st_mtime_ns,str(identity[0]),identity[1],size)
                    if previous!=current:differences.append(str(file))
            result.update(stable=not differences and observed==result['files'],verification_files=observed,differences=differences)
            print(json.dumps(dict(policy=policy,files=result['files'],allocated_bytes=result['allocated_bytes'],stable=result['stable'])),flush=True)
    receipt=dict(passed=all(r['stable'] for r in results.values()),recorded_utc=datetime.now(timezone.utc).isoformat(),
                 seconds=time.monotonic()-start,scope=__doc__,spec=spec,policies=results,
                 historical_disk_peak='NOT_RECONSTRUCTABLE',standard_package='NOT_INCLUDED_UNLESS_EXPLICIT_SCOPE',
                 full_G4='NOT_CLOSED_BY_THIS_OBSERVER',retained_file_contents_read_or_written=False,
                 allocation_scope='NTFS FILE_STANDARD_INFO allocation, hardlink-deduplicated per policy; excludes directory/MFT/ADS')
    output.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n','utf-8')
    return 0 if receipt['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
