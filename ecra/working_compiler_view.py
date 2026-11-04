"""Pinned Clang VFS over independent working-byte and SDK copies.

This is an internal extractor input, not authorization for formal dirty scans.
Parent-analysis reads and build/Diff closure still need the same integration.
"""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import uuid

from .common import write_json
from .workspace import canonical, context, no_links
from . import working_snapshot as working

SCHEMA = '''CREATE TABLE files(logical TEXT PRIMARY KEY,physical TEXT NOT NULL,
sha256 TEXT NOT NULL,size INTEGER NOT NULL,mtime_ns INTEGER NOT NULL);'''
SHA = re.compile(r'[0-9a-f]{64}')


def _files(root):
    for base, dirs, names in os.walk(root, followlinks=False):
        dirs.sort();names.sort()
        for name in dirs+names:no_links(Path(base)/name)
        for name in names:
            path=Path(base)/name
            if not path.is_file():raise ValueError('编译视图输入不是普通文件：'+str(path))
            yield path


def _copy(source, target):
    target.parent.mkdir(parents=True,exist_ok=True)
    before=source.stat();hashed=hashlib.sha256();size=0
    with source.open('rb') as reader,target.open('xb') as writer:
        for block in iter(lambda:reader.read(1024**2),b''):
            if shutil.disk_usage(target.parent).free<len(block)+512*1024**2:
                raise ValueError('冻结编译输入的工作盘空闲不足；原输入保留')
            writer.write(block);hashed.update(block);size+=len(block)
        writer.flush();os.fsync(writer.fileno())
    after=source.stat()
    if ((before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns)
            or working._hash(source)!=hashed.hexdigest()):
        raise ValueError('复制期间外部编译输入已变化：'+str(source))
    shutil.copystat(source,target)
    if (working._hash(target)!=hashed.hexdigest() or target.stat().st_mtime_ns!=before.st_mtime_ns):
        raise ValueError('外部编译输入副本未保持原始字节或时间')
    return hashed.hexdigest(),size,before.st_mtime_ns


def create(capture, root, cfg, *, external_directories=()):
    """Freeze explicitly audited search directories, including negative probes."""
    working.validate(capture,root,cfg)
    ws=context(root,cfg['analysis']);original=no_links(ws.repository_root)
    captured=no_links(capture['folder']);tree=no_links(captured/'source')
    if not isinstance(external_directories,(list,tuple)):
        raise ValueError('外部搜索目录必须显式列为目录序列')
    directories=[]
    for value in external_directories:
        if not isinstance(value,(str,Path)) or not Path(value).is_absolute():
            raise ValueError('外部搜索输入必须使用绝对目录')
        path=no_links(value)
        if not path.is_dir() or path==Path(path.anchor):
            raise ValueError('外部搜索输入必须是明确目录，不能是磁盘根')
        if path==original or path.is_relative_to(original):continue
        if original.is_relative_to(path) or any(path==other or path.is_relative_to(other) or other.is_relative_to(path) for other in directories):
            raise ValueError('外部搜索目录重叠或包含原工程；请提供互不重叠的边界')
        data=Path(ws.workspace_root)
        if path==data or path.is_relative_to(data) or data.is_relative_to(path):
            raise ValueError('外部编译输入不能包含可变ECRA数据根')
        directories.append(path)
    folder=no_links(captured/('compiler-view-'+uuid.uuid4().hex));folder.mkdir()
    database=folder/'files.db';overlay=folder/'overlay.json'
    with closing(sqlite3.connect(database)) as conn:
        conn.execute('PRAGMA synchronous=FULL');conn.executescript(SCHEMA)
        with closing(sqlite3.connect((captured/'capture.db').as_uri()+'?mode=ro',uri=True)) as source:
            source.execute('PRAGMA query_only=ON');source.execute('PRAGMA trusted_schema=OFF')
            for relative,sha,size,mtime in source.execute('SELECT relative,sha256,size,mtime_ns FROM files ORDER BY relative'):
                conn.execute('INSERT INTO files VALUES (?,?,?,?,?)',(str(original/relative),str(tree/relative),sha,size,mtime))
        remaps=[]
        for index,directory in enumerate(directories):
            target=folder/'external'/str(index);target.mkdir(parents=True)
            # Preserve empty search subdirectories as well as all file bytes.
            for base,dirs,names in os.walk(directory,followlinks=False):
                dirs.sort();names.sort()
                for name in dirs:
                    child=no_links(Path(base)/name)
                    (target/child.relative_to(directory)).mkdir(parents=True,exist_ok=True)
                for name in names:
                    path=no_links(Path(base)/name)
                    if not path.is_file():raise ValueError('外部搜索输入不是普通文件')
                    physical=target/path.relative_to(directory)
                    sha,size,mtime=_copy(path,physical)
                    conn.execute('INSERT INTO files VALUES (?,?,?,?,?)',(str(path),str(physical),sha,size,mtime))
            remaps.append((directory,target))
        conn.commit()
        with overlay.open('x',encoding='utf-8') as stream:
            stream.write('{"version":0,"case-sensitive":'+('false' if os.name=='nt' else 'true')+',"use-external-names":false,"redirecting-with":"redirect-only","roots":[')
            separator=''
            prefix=str(folder/'external')+os.sep
            for logical,physical in conn.execute('SELECT logical,physical FROM files WHERE substr(physical,1,?)!=? ORDER BY logical',(len(prefix),prefix)):
                stream.write(separator);json.dump(dict(type='file',name=Path(logical).as_posix(),**{'external-contents':Path(physical).as_posix()}),stream,ensure_ascii=False);separator=','
            for logical,physical in remaps:
                stream.write(separator);json.dump(dict(type='directory-remap',name=logical.as_posix(),**{'external-contents':physical.as_posix()}),stream,ensure_ascii=False);separator=','
            stream.write(']}\n');stream.flush();os.fsync(stream.fileno())
    record=dict(format='ECRA_FROZEN_COMPILER_VIEW_V1',state='PENDING',root=str(no_links(root)),repository_root=str(original),project_id=ws.project_id,
                capture=capture,external_directories=[str(path) for path in directories],
                overlay_sha256=working._hash(overlay),files_sha256=working._hash(database),
                formal_dirty_enabled=False,proof='FROZEN_COMPILER_BYTES_ONLY_NOT_FULL_BUILD_DIFF_EQUIVALENCE')
    write_json(folder/'view.json',record)
    descriptor=dict(file=str(folder/'view.json'),sha256=working._hash(folder/'view.json'))
    validate(descriptor,root,cfg,_pending=True)
    record['state']='COMPLETE'
    write_json(folder/'view.json',record)
    return dict(file=str(folder/'view.json'),sha256=working._hash(folder/'view.json'))


def _load(descriptor, root, cfg, *, _pending=False):
    if (not isinstance(descriptor,dict) or set(descriptor)!={'file','sha256'}
            or not isinstance(descriptor['sha256'],str) or not SHA.fullmatch(descriptor['sha256'])):
        raise ValueError('冻结编译视图身份字段无效')
    path=no_links(descriptor['file']);folder=path.parent;ws=context(root,cfg['analysis'])
    if (path.name!='view.json' or not re.fullmatch('compiler-view-[0-9a-f]{32}',folder.name)
            or not re.fullmatch('working-[0-9a-f]{32}',folder.parent.name)
            or folder.parent.parent!=no_links(ws.worktree_root)):
        raise ValueError('冻结编译视图不属于已有Resolver输入归属')
    if path.stat().st_size>65536 or working._hash(path)!=descriptor['sha256']:
        raise ValueError('冻结编译视图描述已变化或超过读取预算')
    record=json.loads(path.read_bytes())
    if (record.get('format')!='ECRA_FROZEN_COMPILER_VIEW_V1' or record.get('state')!=('PENDING' if _pending else 'COMPLETE')
            or record.get('project_id')!=ws.project_id
            or canonical(record.get('root',''))!=canonical(root)
            or canonical(record.get('repository_root',''))!=canonical(ws.repository_root)
            or no_links(record['capture']['folder'])!=folder.parent
            or record.get('formal_dirty_enabled') is not False):
        raise ValueError('冻结编译视图的工程或能力声明无效')
    if working._hash(no_links(folder/'overlay.json'))!=record.get('overlay_sha256'):
        raise ValueError('冻结编译视图overlay已变化')
    return folder,record


def arguments(descriptor, root, cfg, unit):
    """Check a pinned internal Worker request without rehashing every TU's tree."""
    folder,record=_load(descriptor,root,cfg)
    repo=no_links(record['repository_root'])
    directory=no_links(unit['directory'])
    cwd_allowed=directory.is_relative_to(repo) or any(directory.is_relative_to(no_links(path)) for path in record['external_directories'])
    if not no_links(unit['source']).is_relative_to(repo) or not cwd_allowed:
        raise ValueError('冻结编译视图只接收原工程内逻辑源码和明确捕获的工作目录')
    return ['-ivfsoverlay',str(folder/'overlay.json')]


def verify_consumed(descriptor, root, cfg, inputs):
    """Bind the actual Clang buffers to the pinned copy, without a graph replay."""
    folder,record=_load(descriptor,root,cfg)
    database=no_links(folder/'files.db')
    if working._hash(database)!=record['files_sha256']:raise ValueError('冻结编译文件清单已变化')
    with closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)) as conn:
        conn.execute('PRAGMA query_only=ON');conn.execute('PRAGMA trusted_schema=OFF')
        for logical,consumed in inputs.items():
            expected=conn.execute('SELECT sha256,size FROM files WHERE logical=?',(str(Path(logical)),)).fetchone()
            if (expected is None or consumed.get('status')!='OK'
                    or (consumed.get('sha256'),consumed.get('size'))!=expected):
                raise ValueError('Clang实际输入不属于已固定编译字节：'+logical)


def validate(descriptor, root, cfg, *, reverify_original=True, _pending=False):
    folder,record=_load(descriptor,root,cfg,_pending=_pending)
    working.validate(record['capture'],root,cfg,reverify_original=reverify_original)
    database=no_links(folder/'files.db')
    if working._hash(database)!=record['files_sha256']:raise ValueError('冻结编译文件清单已变化')
    with closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)) as conn:
        conn.execute('PRAGMA query_only=ON');conn.execute('PRAGMA trusted_schema=OFF')
        total=0
        for logical,physical,sha,size,mtime in conn.execute('SELECT logical,physical,sha256,size,mtime_ns FROM files ORDER BY logical'):
            path=no_links(physical)
            if not path.is_relative_to(folder.parent) or not path.is_file() or path.stat().st_size!=size or path.stat().st_mtime_ns!=mtime or working._hash(path)!=sha:
                raise ValueError('冻结编译文件副本已变化：'+logical)
            if reverify_original:
                source=no_links(logical)
                if not source.is_file() or source.stat().st_size!=size or source.stat().st_mtime_ns!=mtime or working._hash(source)!=sha:
                    raise ValueError('原编译输入已变化：'+logical)
            total+=1
        for index,directory in enumerate(record['external_directories']):
            original=no_links(directory);copied=folder/'external'/str(index)
            for base in ([original,copied] if reverify_original else [copied]):
                count=0
                for path in _files(base):
                    logical=str(original/path.relative_to(base))
                    if not conn.execute('SELECT 1 FROM files WHERE logical=?',(logical,)).fetchone():
                        raise ValueError('编译搜索目录出现未记录输入：'+str(path))
                    count+=1
                prefix=str(copied)+os.sep
                expected=conn.execute('SELECT count(*) FROM files WHERE substr(physical,1,?)=?',(len(prefix),prefix)).fetchone()[0]
                if count!=expected:raise ValueError('编译搜索目录输入数量变化')
    return dict(valid=True,files=total,original_reverified=reverify_original,formal_dirty_enabled=False,
                full_build_diff_equivalence='NOT_VERIFIED')
