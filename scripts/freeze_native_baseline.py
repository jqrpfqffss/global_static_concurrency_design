"""Keep an independent, completely verified, read-only native baseline copy.

Only accepts a completed native observer receipt. Never removes a source or
partial destination. Read-only means Windows file attributes, not an ACL mount.
"""
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ecra.report_package import sha256
from ecra.workspace import no_links


def files(root):
    pending=[root]
    while pending:
        with os.scandir(pending.pop()) as entries:
            for entry in entries:
                info=entry.stat(follow_symlinks=False)
                if entry.is_symlink() or getattr(info,'st_file_attributes',0)&0x400:raise ValueError('Baseline copy refuses links/reparse points')
                if entry.is_dir(follow_symlinks=False):pending.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):yield Path(entry.path),info
                else:raise ValueError('Baseline contains a nonregular input')


def freeze(execution,destination,work):
    execution=Path(execution).resolve();run=json.loads(execution.read_text(encoding='utf-8'))
    if not run.get('complete') or run.get('validity',{}).get('analysis_valid') is not True:
        raise ValueError('Only a completed native result can become the golden backup')
    source=no_links(Path(run['data_root']));destination=no_links(destination);work=no_links(work)
    if not source.is_dir():raise ValueError('Original baseline data root is missing')
    roots=[source,destination,work]
    if any(a==b or a.is_relative_to(b) or b.is_relative_to(a) for i,a in enumerate(roots) for b in roots[i+1:]):
        raise ValueError('Original, backup and observer directories must be disjoint')
    if destination.exists() or work.exists():raise FileExistsError('Preserve previous backup attempts; choose fresh paths')
    config=Path(run['config'])
    if sha256(config)!=run['config_sha256']:raise ValueError('Frozen native configuration changed')
    from ecra.config import configured_project_root
    firmware=configured_project_root(config)
    for root in [destination,work]:
        if root==firmware or root.is_relative_to(firmware) or firmware.is_relative_to(root):raise ValueError('Golden backup cannot overlap firmware')
    work.mkdir(parents=True);destination.mkdir(parents=True)
    count=total=0
    for _,info in files(source):count+=1;total+=info.st_size
    if shutil.disk_usage(destination).free<total+8*1024**3:raise ValueError('Insufficient disk for complete independent backup plus8GiB reserve')
    manifest=work/'files.db';receipt=work/'acceptance.json';started=time.monotonic();last=started;copied_bytes=copied_files=0
    result=dict(passed=False,state='COPYING',source=str(source),destination=str(destination),execution=str(execution),
        execution_sha256=sha256(execution),files=count,logical_bytes=total,scope=__doc__)
    def save():
        result.update(copied_files=copied_files,copied_bytes=copied_bytes,seconds=time.monotonic()-started)
        receipt.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    save()
    with closing(sqlite3.connect(manifest)) as conn:
        conn.execute('PRAGMA synchronous=FULL')
        conn.execute('CREATE TABLE files(path TEXT PRIMARY KEY,sha256 TEXT,size INTEGER,mtime_ns INTEGER)')
        try:
            for path,before in files(source):
                relative=path.relative_to(source);target=destination/relative;target.parent.mkdir(parents=True,exist_ok=True)
                digest=hashlib.sha256()
                with path.open('rb') as original,target.open('xb') as backup:
                    while chunk:=original.read(8*1024**2):
                        backup.write(chunk);digest.update(chunk)
                        if time.monotonic()-last>=30:save();print(json.dumps(dict(state='COPYING',files=copied_files,bytes=copied_bytes,current=str(relative))),flush=True);last=time.monotonic()
                    backup.flush();os.fsync(backup.fileno())
                after=path.stat()
                if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns) or sha256(target)!=digest.hexdigest():raise ValueError('Original changed or copied bytes failed verification: '+str(relative))
                shutil.copystat(path,target)
                conn.execute('INSERT INTO files VALUES (?,?,?,?)',(relative.as_posix(),digest.hexdigest(),before.st_size,before.st_mtime_ns))
                copied_files+=1;copied_bytes+=before.st_size
                if copied_files%500==0:conn.commit();save()
            conn.commit();result['state']='VERIFYING_ORIGINAL';save();verified=0
            for path,info in files(source):
                row=conn.execute('SELECT sha256,size,mtime_ns FROM files WHERE path=?',(path.relative_to(source).as_posix(),)).fetchone()
                if row is None or (info.st_size,info.st_mtime_ns)!=(row[1],row[2]) or sha256(path)!=row[0]:raise ValueError('Original baseline changed during backup')
                verified+=1
                if time.monotonic()-last>=30:save();print(json.dumps(dict(state='VERIFYING_ORIGINAL',files=verified)),flush=True);last=time.monotonic()
            if verified!=count or copied_files!=count or copied_bytes!=total:raise ValueError('Baseline inventory changed during backup')
            for root in [source,destination]:
                for path,_ in files(root):path.chmod(stat.S_IREAD)
            result.update(passed=True,state='COMPLETE',source_unchanged=True,independent_copy_verified=True,readonly_scope='FILE_ATTRIBUTES_NOT_ACL_MOUNT')
        except BaseException as exc:result.update(passed=False,state='FAILED',error=str(exc));save();raise
    result['manifest_sha256']=sha256(manifest);save();return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['execution','destination','work']:parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();result=freeze(args.execution,args.destination,args.work)
    print(json.dumps(dict(passed=result['passed'],files=result['files'],bytes=result['logical_bytes'],seconds=result['seconds'])))


if __name__=='__main__':main()
