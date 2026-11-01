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


def hash_file(path,buffer):
    value=hashlib.sha256();view=memoryview(buffer)
    with Path(path).open('rb',buffering=0) as stream:
        while size:=stream.readinto(buffer):value.update(view[:size])
    return value.hexdigest()


def freeze(execution,destination,work,*,resume_receipt=None):
    execution=Path(execution).resolve();run=json.loads(execution.read_text(encoding='utf-8'))
    if not run.get('complete') or run.get('validity',{}).get('analysis_valid') is not True:
        raise ValueError('Only a completed native result can become the golden backup')
    source=no_links(Path(run['data_root']));destination=no_links(destination);work=no_links(work)
    if not source.is_dir():raise ValueError('Original baseline data root is missing')
    roots=[source,destination,work]
    if any(a==b or a.is_relative_to(b) or b.is_relative_to(a) for i,a in enumerate(roots) for b in roots[i+1:]):
        raise ValueError('Original, backup and observer directories must be disjoint')
    if work.exists():raise FileExistsError('Preserve previous observer attempts; choose a fresh work path')
    previous=None
    if destination.exists():
        if resume_receipt is None:raise FileExistsError('Preserve previous backup attempts; choose fresh paths or explicitly verify a failed backup')
        previous=json.loads(no_links(resume_receipt).read_text(encoding='utf-8'))
        if (previous.get('passed') is not False or previous.get('state')!='FAILED'
                or no_links(previous.get('source',''))!=source or no_links(previous.get('destination',''))!=destination
                or previous.get('execution_sha256')!=sha256(execution)):
            raise ValueError('Resume requires the matching failed backup receipt; no destination is overwritten')
    elif resume_receipt is not None:raise ValueError('Resume backup destination is missing')
    config=Path(run['config'])
    if sha256(config)!=run['config_sha256']:raise ValueError('Frozen native configuration changed')
    from ecra.config import configured_project_root
    firmware=configured_project_root(config)
    for root in [destination,work]:
        if root==firmware or root.is_relative_to(firmware) or firmware.is_relative_to(root):raise ValueError('Golden backup cannot overlap firmware')
    work.mkdir(parents=True)
    if previous is None:destination.mkdir(parents=True)
    count=total=0
    for _,info in files(source):count+=1;total+=info.st_size
    if shutil.disk_usage(destination).free<total+8*1024**3:raise ValueError('Insufficient disk for complete independent backup plus8GiB reserve')
    manifest=work/'files.db';receipt=work/'acceptance.json';started=time.monotonic();last=started;copied_bytes=copied_files=0
    result=dict(passed=False,state='COPYING',source=str(source),destination=str(destination),execution=str(execution),
        execution_sha256=sha256(execution),files=count,logical_bytes=total,scope=__doc__,
        resumed_from=str(resume_receipt) if previous is not None else None,reused_verified_files=0,
        buffer_policy='One reusable1MiB readinto buffer; no per-file oversized bytes allocation')
    def save():
        result.update(copied_files=copied_files,copied_bytes=copied_bytes,seconds=time.monotonic()-started)
        receipt.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    save();buffer=bytearray(1024**2);view=memoryview(buffer)
    with closing(sqlite3.connect(manifest)) as conn:
        conn.execute('PRAGMA synchronous=FULL')
        conn.execute('CREATE TABLE files(path TEXT PRIMARY KEY,sha256 TEXT,size INTEGER,mtime_ns INTEGER)')
        try:
            for path,before in files(source):
                relative=path.relative_to(source);target=destination/relative;target.parent.mkdir(parents=True,exist_ok=True)
                digest=hashlib.sha256()
                if target.exists():
                    no_links(target)
                    if previous is None or not target.is_file() or target.stat().st_size!=before.st_size:
                        raise ValueError('Existing partial differs; retained without overwrite: '+str(relative))
                    original_hash=hash_file(path,buffer)
                    if hash_file(target,buffer)!=original_hash:raise ValueError('Existing partial differs; retained without overwrite: '+str(relative))
                    digest_value=original_hash;result['reused_verified_files']+=1
                else:
                    with path.open('rb',buffering=0) as original,target.open('xb',buffering=0) as backup:
                        while size:=original.readinto(buffer):
                            part=view[:size];written=0
                            while written<size:
                                actual=backup.write(part[written:])
                                if not actual:raise OSError('Backup write made no progress')
                                written+=actual
                            digest.update(part)
                            if time.monotonic()-last>=30:save();print(json.dumps(dict(state='COPYING',files=copied_files,bytes=copied_bytes,current=str(relative))),flush=True);last=time.monotonic()
                        backup.flush();os.fsync(backup.fileno())
                    digest_value=digest.hexdigest()
                after=path.stat()
                if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns) or hash_file(target,buffer)!=digest_value:raise ValueError('Original changed or copied bytes failed verification: '+str(relative))
                if previous is None or target.stat().st_mtime_ns!=before.st_mtime_ns:shutil.copystat(path,target)
                conn.execute('INSERT INTO files VALUES (?,?,?,?)',(relative.as_posix(),digest_value,before.st_size,before.st_mtime_ns))
                copied_files+=1;copied_bytes+=before.st_size
                if time.monotonic()-last>=30:save();print(json.dumps(dict(state='COPYING',files=copied_files,bytes=copied_bytes,reused=result['reused_verified_files'],current=str(relative))),flush=True);last=time.monotonic()
                if copied_files%500==0:conn.commit();save()
            conn.commit();result['state']='VERIFYING_ORIGINAL';save();verified=0
            for path,info in files(source):
                row=conn.execute('SELECT sha256,size,mtime_ns FROM files WHERE path=?',(path.relative_to(source).as_posix(),)).fetchone()
                if row is None or (info.st_size,info.st_mtime_ns)!=(row[1],row[2]) or hash_file(path,buffer)!=row[0]:raise ValueError('Original baseline changed during backup')
                verified+=1
                if time.monotonic()-last>=30:save();print(json.dumps(dict(state='VERIFYING_ORIGINAL',files=verified)),flush=True);last=time.monotonic()
            if verified!=count or copied_files!=count or copied_bytes!=total:raise ValueError('Baseline inventory changed during backup')
            backup_count=0
            for path,info in files(destination):
                row=conn.execute('SELECT size FROM files WHERE path=?',(path.relative_to(destination).as_posix(),)).fetchone()
                if row is None or row[0]!=info.st_size:raise ValueError('Backup contains unknown or changed files; retained')
                backup_count+=1
            if backup_count!=count:raise ValueError('Backup inventory differs; retained')
            for root in [source,destination]:
                for path,_ in files(root):path.chmod(stat.S_IREAD)
            result.update(passed=True,state='COMPLETE',source_unchanged=True,independent_copy_verified=True,readonly_scope='FILE_ATTRIBUTES_NOT_ACL_MOUNT')
        except BaseException as exc:result.update(passed=False,state='FAILED',error=str(exc),error_type=type(exc).__name__);save();raise
    result['manifest_sha256']=sha256(manifest);save();return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['execution','destination','work']:parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--resume-receipt',type=Path)
    args=parser.parse_args();result=freeze(args.execution,args.destination,args.work,resume_receipt=args.resume_receipt)
    print(json.dumps(dict(passed=result['passed'],files=result['files'],bytes=result['logical_bytes'],seconds=result['seconds'])))


if __name__=='__main__':main()
