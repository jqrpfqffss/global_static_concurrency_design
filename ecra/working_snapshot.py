"""Capture dirty Git inputs outside firmware; not enabled in the formal UI yet.

The caller must still prove relocated compiler/build semantics before using a
capture for analysis. This module preserves bytes and Git staging, not that proof.
"""
from contextlib import closing
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import subprocess
import uuid

from .workspace import context,no_links,canonical,studio_data_root
from .portable import bundle_root

SCHEMA="""
CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE files(relative TEXT PRIMARY KEY,sha256 TEXT NOT NULL,size INTEGER NOT NULL,mtime_ns INTEGER NOT NULL);
CREATE TABLE index_objects(oid TEXT PRIMARY KEY);
"""


def _git_argv(root,*args):
    bundle=bundle_root()
    exe=str(bundle/'tools/git/cmd/git.exe') if bundle else 'git'
    if bundle and not Path(exe).is_file():raise ValueError('隔离输入需要完整离线Git运行时')
    return [exe,'-c','core.longpaths=true','-c','core.fsmonitor=false','-C',str(root),*args]


def _environment():
    env=os.environ.copy()
    for key in ('GIT_DIR','GIT_WORK_TREE','GIT_INDEX_FILE','GIT_OBJECT_DIRECTORY','GIT_ALTERNATE_OBJECT_DIRECTORIES','GIT_COMMON_DIR'):
        if env.get(key):raise ValueError('未能证明Git环境隔离，先移除 '+key)
    env['GIT_OPTIONAL_LOCKS']='0'
    return env


def _git(root,*args,output=subprocess.PIPE):
    result=subprocess.run(_git_argv(root,*args),env=_environment(),stdout=output,stderr=subprocess.PIPE,timeout=300)
    if result.returncode:raise ValueError('工作输入Git捕获失败: '+result.stderr.decode('utf-8',errors='replace'))
    return result.stdout


def _hash(path):
    value=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):value.update(chunk)
    return value.hexdigest()


def _z_records(path):
    remaining=b''
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(65536),b''):
            parts=(remaining+chunk).split(b'\0');remaining=parts.pop()
            yield from parts
    if remaining:raise ValueError('Git阶段清单未完整结束')


def _working_digest(repo,folder,name):
    listing=folder/name
    with listing.open('xb') as stream:_git(repo,'ls-files','--cached','--others','--exclude-standard','-z',output=stream)
    digest=hashlib.sha256()
    for raw in _z_records(listing):
        relative=raw.decode('utf-8');path=repo/relative
        digest.update(raw+b'\0')
        if path.exists():
            if path.is_symlink() or getattr(path.lstat(),'st_file_attributes',0)&stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise ValueError('工作输入含重解析点，未能证明隔离')
            if not path.is_file():raise ValueError('工作输入不是普通文件')
            digest.update(_hash(path).encode())
        else:digest.update(b'DELETED')
        digest.update(b'\0')
    return digest.hexdigest()


def _pack_index_objects(repo,target,folder,conn):
    """Stream indexed blobs to an independent object database, including new blobs."""
    if not conn.execute('SELECT 1 FROM index_objects LIMIT 1').fetchone():return
    source=destination=None
    with (folder/'pack-source.log').open('wb') as source_log,(folder/'pack-destination.log').open('wb') as destination_log:
        try:
            source=subprocess.Popen(_git_argv(repo,'pack-objects','--stdout','--no-reuse-delta','--quiet'),
                stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=source_log,env=_environment())
            destination=subprocess.Popen(_git_argv(target,'index-pack','--stdin'),stdin=source.stdout,
                stdout=destination_log,stderr=destination_log,env=_environment())
            source.stdout.close()
            for (oid,) in conn.execute('SELECT oid FROM index_objects ORDER BY oid'):
                source.stdin.write(oid.encode('ascii')+b'\n')
            source.stdin.close()
            first=source.wait(timeout=300);second=destination.wait(timeout=300)
            if first or second:raise ValueError('Git未提交对象复制不完整，保留pack诊断')
        finally:
            for process in (source,destination):
                if process is not None:
                    if process.poll() is None:process.kill();process.wait(timeout=10)
                    if process.stdin is not None and not process.stdin.closed:process.stdin.close()


def capture(root,cfg,progress=None):
    """Return an independently owned working-byte capture, without scanning it."""
    progress=progress or (lambda _:None)
    workspace=context(root,cfg['analysis']);repo=no_links(workspace.repository_root)
    actual=Path(_git(root,'rev-parse','--show-toplevel').decode('utf-8').strip()).resolve()
    if canonical(actual)!=canonical(repo):raise ValueError('原仓库与WorkspaceResolver身份不符')
    parent=no_links(workspace.worktree_root)
    data=studio_data_root(workspace.workspace_root)
    if not parent.is_relative_to(data):raise ValueError('隔离树越出既有数据根')
    if not no_links(Path(workspace.project_workspace)/'project.json').is_file():raise ValueError('缺少已有Resolver归属凭据')
    if parent==repo or parent.is_relative_to(repo):raise ValueError('工作输入隔离目录不能在原固件内')
    folder=no_links(parent/('working-'+uuid.uuid4().hex));folder.mkdir(parents=True)
    tree=folder/'source';database=folder/'capture.db'
    with closing(sqlite3.connect(database)) as conn:
        conn.execute('PRAGMA synchronous=FULL');conn.executescript(SCHEMA)
        def meta(key,value):conn.execute('INSERT OR REPLACE INTO meta VALUES (?,?)',(key,json.dumps(value,ensure_ascii=False)))
        meta('state','PENDING');meta('project_id',workspace.project_id);meta('repository_root',str(repo));conn.commit()
        try:
            head=_git(repo,'rev-parse','HEAD').decode('ascii').strip();meta('head',head)
            working_before=_working_digest(repo,folder,'working-before.z')
            relative_index=Path(_git(repo,'rev-parse','--git-path','index').decode('utf-8').strip())
            index=no_links(relative_index if relative_index.is_absolute() else repo/relative_index)
            index_before=_hash(index)
            shutil.copy2(index,folder/'original-index')
            if _hash(folder/'original-index')!=index_before:raise ValueError('读取期间原索引变化')
            with (folder/'index-entries.z').open('xb') as stream:_git(repo,'ls-files','--stage','-z',output=stream)
            for record in _z_records(folder/'index-entries.z'):
                header,name=record.split(b'\t',1);mode,oid,stage=header.split()
                if stage!=b'0':raise ValueError('未解决的索引冲突尚未支持隔离；原索引保留')
                if mode==b'160000':raise ValueError('子模块的独立输入捕获尚未接入；不跳过子模块')
                conn.execute('INSERT OR IGNORE INTO index_objects VALUES (?)',(oid.decode('ascii'),))
            for name,args in [('status.z',('status','--porcelain=v2','--untracked-files=all','-z')),
                    ('staged.patch',('diff','--cached','--binary','--no-ext-diff','--no-textconv','HEAD','--')),
                    ('unstaged.patch',('diff','--binary','--no-ext-diff','--no-textconv','--'))]:
                with (folder/name).open('xb') as stream:_git(repo,*args,output=stream)
            template=folder/'empty-template';template.mkdir()
            progress('复制独立Git对象库，不更改原.git管理目录')
            _git(repo,'clone','--quiet','--no-checkout','--no-local','--no-hardlinks','--template='+str(template),'--',str(repo),str(tree))
            if _git(tree,'rev-parse','HEAD').decode('ascii').strip()!=head:raise ValueError('复制期间HEAD变化')
            _git(tree,'config','core.hooksPath',str(template))
            _pack_index_objects(repo,tree,folder,conn)
            shutil.copy2(folder/'original-index',tree/'.git/index')
            if _git(tree,'ls-files','--stage','-z')!=(folder/'index-entries.z').read_bytes():
                raise ValueError('隔离索引条目不等价')
            files=total=0
            for base,dirs,names in os.walk(repo,followlinks=False):
                current=Path(base);dirs.sort();names.sort()
                if current==repo:
                    dirs[:]=[name for name in dirs if name!='.git'];names=[name for name in names if name!='.git']
                elif '.git' in dirs or '.git' in names:
                    raise ValueError('发现未实现的嵌套Git输入边界；不跳过')
                for name in dirs+names:
                    item=current/name
                    if item.is_symlink() or getattr(item.lstat(),'st_file_attributes',0)&stat.FILE_ATTRIBUTE_REPARSE_POINT:
                        raise ValueError('输入含重解析点，未能证明隔离等价: '+str(item))
                for name in names:
                    source=current/name;relative=source.relative_to(repo).as_posix();target=no_links(tree/relative)
                    if not source.is_file():raise ValueError('输入不是普通文件: '+relative)
                    target.parent.mkdir(parents=True,exist_ok=True)
                    if shutil.disk_usage(folder).free<512*1024**2:raise ValueError('隔离工作盘空闲不足，保留未完成现场')
                    hashed=hashlib.sha256();size=0
                    with source.open('rb') as reader,target.open('xb') as writer:
                        for block in iter(lambda:reader.read(1024*1024),b''):
                            writer.write(block);hashed.update(block);size+=len(block)
                        writer.flush()
                    if _hash(source)!=hashed.hexdigest():raise ValueError('复制期间输入字节变化: '+relative)
                    shutil.copystat(source,target)
                    conn.execute('INSERT INTO files VALUES (?,?,?,?)',(relative,hashed.hexdigest(),size,target.stat().st_mtime_ns))
                    files+=1;total+=size
                    if files%100==0:conn.commit();progress(f'工作输入已复制 {files} 个文件 / {total} 字节，剩余量未知')
            if _hash(index)!=index_before or _git(repo,'rev-parse','HEAD').decode('ascii').strip()!=head:
                raise ValueError('复制期间原索引或HEAD变化，不能发布输入快照')
            if _working_digest(repo,folder,'working-after.z')!=working_before:raise ValueError('复制期间工作输入字节变化')
            with (folder/'final-status.z').open('xb') as stream:_git(repo,'status','--porcelain=v2','--untracked-files=all','-z',output=stream)
            if (folder/'final-status.z').read_bytes()!=(folder/'status.z').read_bytes():raise ValueError('复制期间工作区状态变化')
            meta('state','COMPLETE');meta('files',files);meta('bytes',total);meta('index_sha256',index_before)
            meta('working_digest',working_before)
            meta('index_entries_sha256',_hash(folder/'index-entries.z'))
            meta('status_sha256',_hash(folder/'status.z'))
            meta('captured_at',datetime.now(timezone.utc).isoformat());conn.commit()
            progress(f'工作输入捕获完成 {files} 个文件；尚未证明构建与宏等价')
            return dict(folder=str(folder),source_root=str(tree/Path(root).resolve().relative_to(repo)),
                repository_root=str(tree),manifest=str(database),project_id=workspace.project_id,files=files,bytes=total,
                proof='BYTES_AND_INDEX_ONLY_NOT_BUILD_EQUIVALENCE')
        except BaseException as exc:
            meta('state','FAILED');meta('error',str(exc));conn.commit();raise


def validate(result,root,cfg,*,reverify_original=True):
    """Validate a complete byte capture before any compiler may consume it.

    This deliberately remains separate from compiler/macro equivalence. A
    missing original can be viewed later but cannot be called reverified.
    """
    from .report_package import validate_schema
    workspace=context(root,cfg['analysis']);folder=no_links(result['folder'])
    if (folder.parent!=no_links(workspace.worktree_root) or not folder.name.startswith('working-')
            or not folder.is_relative_to(studio_data_root(workspace.workspace_root))):
        raise ValueError('捕获目录不属于已有Resolver工作树范围')
    database=no_links(folder/'capture.db');tree=no_links(folder/'source')
    validate_schema(database,SCHEMA)
    with closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)) as conn:
        conn.execute('PRAGMA query_only=ON');conn.execute('PRAGMA trusted_schema=OFF')
        meta={key:json.loads(value) for key,value in conn.execute('SELECT key,value FROM meta')}
        if (meta.get('state')!='COMPLETE' or meta.get('project_id')!=workspace.project_id
                or canonical(meta.get('repository_root',''))!=canonical(workspace.repository_root)):
            raise ValueError('捕获未完成或工程归属不符')
        if _hash(folder/'original-index')!=meta['index_sha256'] or _hash(folder/'index-entries.z')!=meta['index_entries_sha256']:
            raise ValueError('捕获的索引审计损坏')
        if _hash(folder/'status.z')!=meta['status_sha256']:raise ValueError('捕获状态审计损坏')
        if _git(tree,'rev-parse','HEAD').decode('ascii').strip()!=meta['head']:raise ValueError('隔离HEAD已变化')
        if _git(tree,'ls-files','--stage','-z')!=(folder/'index-entries.z').read_bytes():raise ValueError('隔离索引阶段已变化')
        observed=0
        for base,dirs,names in os.walk(tree,followlinks=False):
            if Path(base)==tree:dirs[:]=[name for name in dirs if name!='.git'];names=[name for name in names if name!='.git']
            for name in dirs+names:
                item=Path(base)/name
                if item.is_symlink() or getattr(item.lstat(),'st_file_attributes',0)&stat.FILE_ATTRIBUTE_REPARSE_POINT:
                    raise ValueError('隔离树出现重解析点')
            for name in names:
                relative=(Path(base)/name).relative_to(tree).as_posix()
                if not conn.execute('SELECT 1 FROM files WHERE relative=?',(relative,)).fetchone():raise ValueError('隔离树出现未记录的输入')
                observed+=1
        if observed!=meta['files']:raise ValueError('隔离输入数量改变')
        repo=no_links(workspace.repository_root)
        if reverify_original:
            original_count=0
            for base,dirs,names in os.walk(repo,followlinks=False):
                if Path(base)==repo:
                    dirs[:]=[name for name in dirs if name!='.git'];names=[name for name in names if name!='.git']
                for name in dirs+names:
                    item=Path(base)/name
                    if item.is_symlink() or getattr(item.lstat(),'st_file_attributes',0)&stat.FILE_ATTRIBUTE_REPARSE_POINT:
                        raise ValueError('原工作目录出现重解析点')
                for name in names:
                    relative=(Path(base)/name).relative_to(repo).as_posix()
                    if not conn.execute('SELECT 1 FROM files WHERE relative=?',(relative,)).fetchone():
                        raise ValueError('原工作目录出现未记录的输入: '+relative)
                    original_count+=1
            if original_count!=meta['files']:raise ValueError('原工作目录输入数量变化')
        for relative,hashed,size,mtime in conn.execute('SELECT relative,sha256,size,mtime_ns FROM files ORDER BY relative'):
            rel=Path(relative)
            if rel.is_absolute() or '..' in rel.parts:raise ValueError('捕获清单路径越界')
            target=no_links(tree/rel)
            if not target.is_relative_to(tree) or not target.is_file() or target.stat().st_size!=size or target.stat().st_mtime_ns!=mtime or _hash(target)!=hashed:
                raise ValueError('隔离输入已改变: '+relative)
            if reverify_original:
                original=no_links(repo/rel)
                if not original.is_file() or original.stat().st_size!=size or original.stat().st_mtime_ns!=mtime or _hash(original)!=hashed:
                    raise ValueError('原工作输入已变化: '+relative)
        if reverify_original:
            index=Path(_git(repo,'rev-parse','--git-path','index').decode('utf-8').strip())
            if not index.is_absolute():index=repo/index
            if _hash(no_links(index))!=meta['index_sha256'] or _git(repo,'rev-parse','HEAD').decode('ascii').strip()!=meta['head']:
                raise ValueError('原索引或HEAD已变化')
            # A fresh path listing also detects additions that were absent
            # from the captured files (no temporary writes in the firmware).
            current=_git(repo,'ls-files','--cached','--others','--exclude-standard','-z')
            digest=hashlib.sha256()
            for raw in current.split(b'\0'):
                if not raw:continue
                path=no_links(repo/raw.decode('utf-8'));digest.update(raw+b'\0')
                digest.update(_hash(path).encode() if path.is_file() else b'DELETED');digest.update(b'\0')
            if digest.hexdigest()!=meta['working_digest']:raise ValueError('原工作目录清单已变化')
        return dict(valid=True,project_id=workspace.project_id,files=observed,original_reverified=reverify_original,
            build_equivalence='NOT_VERIFIED')
