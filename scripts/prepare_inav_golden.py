"""Prepare a rebuildable public INAV golden candidate, never a formal dirty snapshot.

Copies tracked working bytes and nonignored untracked inputs into an independent
Git clone. Existing ignored builds/scan archives remain untouched at the source.
An actual fresh build and complete consumed-input audit are required next; this
preparation alone establishes neither semantic equivalence nor any G gate.
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

TOOL=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(TOOL))
from ecra.working_snapshot import _git,_hash,_z_records
from ecra.workspace import no_links


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--work',type=Path,required=True)
    args=parser.parse_args()
    original_config_bytes=no_links(args.config).read_bytes()
    source=no_links(args.source);work=no_links(args.work)
    if work==source or work.is_relative_to(source) or source.is_relative_to(work):
        raise ValueError('Golden work must not overlap the original firmware')
    if work.exists():raise FileExistsError('Preserve existing evidence; choose a new golden work directory')
    if Path(_git(source,'rev-parse','--show-toplevel').decode().strip()).resolve()!=source:
        raise ValueError('Use the explicitly authorized repository root')
    work.mkdir(parents=True);tree=work/'firmware';template=work/'empty-template';template.mkdir()
    head=_git(source,'rev-parse','HEAD').decode('ascii').strip()
    index_path=Path(_git(source,'rev-parse','--git-path','index').decode().strip())
    index=no_links(index_path if index_path.is_absolute() else source/index_path)
    initial_index=_hash(index)
    status=_git(source,'status','--porcelain=v2','--untracked-files=all','-z')
    (work/'original-status.z').write_bytes(status)
    for name,commands in [('tracked.z',('ls-files','--stage','-z')),
            ('untracked.z',('ls-files','--others','--exclude-standard','-z')),
            ('ignored-not-copied.z',('ls-files','--others','--ignored','--exclude-standard','-z')),
            ('working.patch',('diff','HEAD','--binary','--no-ext-diff','--no-textconv','--')),
            ('staged.patch',('diff','--cached','--binary','--no-ext-diff','--no-textconv','HEAD','--'))]:
        with (work/name).open('xb') as output:_git(source,*commands,output=output)
    result=dict(scope=__doc__,state='PREPARING',original=str(source),head=head,source_index_sha256=initial_index,
        working_patch_sha256=_hash(work/'working.patch'),staged_patch_sha256=_hash(work/'staged.patch'),
        ignored_scope='Not copied. Existing build/archives retained at original. Fresh build and consumed-input audit REQUIRED.',
        production_dirty_isolation='NOT_PROVEN',native_golden='NOT_RUN',source_unchanged=False)
    receipt=work/'preparation.json'
    def save():receipt.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    save()
    try:
        if (work/'staged.patch').stat().st_size:
            raise ValueError('This rebuild-input helper does not reconstruct a changed staged index; use a separately proven capture')
        print('Creating independent local Git clone; original worktree/index untouched',flush=True)
        _git(source,'clone','--quiet','--no-checkout','--no-local','--no-hardlinks','--template='+str(template),'--',str(source),str(tree))
        if _git(tree,'rev-parse','HEAD').decode().strip()!=head:raise ValueError('Source HEAD changed during clone')
        _git(tree,'config','core.hooksPath',str(template))
        _git(tree,'read-tree','HEAD')
        with closing(sqlite3.connect(work/'files.db')) as conn:
            conn.execute('PRAGMA synchronous=FULL')
            conn.execute('CREATE TABLE files(path TEXT PRIMARY KEY,kind TEXT,mode TEXT,sha256 TEXT,size INTEGER,mtime_ns INTEGER)')
            count=total=0
            def capture(raw,kind,mode=''):
                nonlocal count,total
                relative=raw.decode('utf-8');original=no_links(source/relative);destination=no_links(tree/relative)
                if not destination.is_relative_to(tree):raise ValueError('Input path escaped independent clone')
                if not original.exists():
                    conn.execute('INSERT INTO files VALUES (?,?,?,?,?,?)',(relative,kind,mode,'DELETED',None,None));return
                before=original.stat()
                if not original.is_file() or getattr(before,'st_file_attributes',0)&stat.FILE_ATTRIBUTE_REPARSE_POINT:
                    raise ValueError('Unsupported nonregular source input: '+relative)
                destination.parent.mkdir(parents=True,exist_ok=True)
                hashed=_hash(original);shutil.copy2(original,destination)
                after=original.stat()
                if (_hash(destination)!=hashed or _hash(original)!=hashed or before.st_mtime_ns!=after.st_mtime_ns
                        or before.st_size!=after.st_size):raise ValueError('Input changed during copy: '+relative)
                conn.execute('INSERT INTO files VALUES (?,?,?,?,?,?)',(relative,kind,mode,hashed,before.st_size,before.st_mtime_ns))
                count+=1;total+=before.st_size
                if count%100==0:conn.commit();print(f'Captured {count} source inputs / {total} bytes; remaining unknown',flush=True)
            for record in _z_records(work/'tracked.z'):
                header,name=record.split(b'\t',1);mode,oid,stage=header.split()
                if stage!=b'0' or mode not in {b'100644',b'100755'}:
                    raise ValueError('Unproved conflict/submodule/link input; original data preserved')
                capture(name,'tracked',mode.decode())
            for name in _z_records(work/'untracked.z'):capture(name,'untracked')
            conn.commit()
            if _hash(index)!=initial_index or _git(source,'rev-parse','HEAD').decode().strip()!=head:
                raise ValueError('Original HEAD/index changed')
            if _git(source,'status','--porcelain=v2','--untracked-files=all','-z')!=status:
                raise ValueError('Original working status changed')
            if _git(tree,'ls-files','--stage','-z')!=(work/'tracked.z').read_bytes():
                raise ValueError('Private index entries differ; do not use this candidate')
            if _git(tree,'status','--porcelain=v2','--untracked-files=all','-z')!=status:
                raise ValueError('Private Git working status differs; do not use this candidate')
            # Verify every copied original byte again before accepting this candidate.
            for relative,hashed,mtime in conn.execute('SELECT path,sha256,mtime_ns FROM files ORDER BY path'):
                original=no_links(source/relative)
                if hashed=='DELETED':
                    if original.exists():raise ValueError('Deleted source reappeared')
                elif _hash(original)!=hashed or original.stat().st_mtime_ns!=mtime:
                    raise ValueError('Original changed after capture: '+relative)
            result.update(source_files=count,source_logical_bytes=total,source_unchanged=True,
                private_index_entries_equal=True,private_working_status_equal=True)
        # Keep exact original config bytes separately. Adapt obsolete syntax only;
        # freeze the resulting explicit configuration before either engine runs.
        (work/'original-semantics.yaml').write_bytes(original_config_bytes)
        import yaml
        config=yaml.safe_load(original_config_bytes.decode('utf-8-sig'))
        config['project']['root']=str(tree)
        analysis=config['analysis'];analysis['output']=dict(location='custom',custom_dir=str(work/'original-data'))
        old_options=analysis['git_diff'];old_options.pop('target_ref',None);old_options.pop('compare_mode',None)
        old_options.update(enabled=False,base_ref='HEAD^',current_ref='HEAD',include_uncommitted=False)
        target=work/'semantics.yaml';target.write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
        result.update(state='SOURCE_CANDIDATE_CAPTURED_BUILD_NOT_VERIFIED',config_sha256=_hash(target),
            original_config_sha256=_hash(work/'original-semantics.yaml'),files_manifest_sha256=_hash(work/'files.db'))
        save();print(json.dumps(result,ensure_ascii=True),flush=True)
    except BaseException as exc:
        result.update(state='FAILED',error=str(exc));save();raise


if __name__=='__main__':main()
