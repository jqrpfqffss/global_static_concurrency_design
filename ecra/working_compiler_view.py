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
sha256 TEXT NOT NULL,size INTEGER NOT NULL,mtime_ns INTEGER NOT NULL);
CREATE TABLE directories(logical TEXT PRIMARY KEY,physical TEXT NOT NULL);'''
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


def create(capture, root, cfg, *, external_directories=(), external_files=()):
    """Freeze explicitly audited search directories, including negative probes."""
    captured_proof=working.validate(capture,root,cfg)
    ws=context(root,cfg['analysis']);original=no_links(ws.repository_root)
    captured=no_links(capture['folder']);tree=no_links(captured/'source')
    if not isinstance(external_directories,(list,tuple)):
        raise ValueError('外部搜索目录必须显式列为目录序列')
    if not isinstance(external_files,(list,tuple)):
        raise ValueError('单文件元数据输入必须显式列为文件序列')
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
            if captured_proof['directory_proof']:
                conn.execute('INSERT INTO directories VALUES (?,?)',(str(original),str(tree)))
                for (relative,) in source.execute('SELECT relative FROM directories ORDER BY relative'):
                    conn.execute('INSERT INTO directories VALUES (?,?)',(str(original/relative),str(tree/relative)))
        remaps=[]
        for index,directory in enumerate(directories):
            target=folder/'external'/str(index);target.mkdir(parents=True)
            conn.execute('INSERT INTO directories VALUES (?,?)',(str(directory),str(target)))
            # Preserve empty search subdirectories as well as all file bytes.
            for base,dirs,names in os.walk(directory,followlinks=False):
                dirs.sort();names.sort()
                for name in dirs:
                    child=no_links(Path(base)/name)
                    (target/child.relative_to(directory)).mkdir(parents=True,exist_ok=True)
                    conn.execute('INSERT INTO directories VALUES (?,?)',(str(child),str(target/child.relative_to(directory))))
                for name in names:
                    path=no_links(Path(base)/name)
                    if not path.is_file():raise ValueError('外部搜索输入不是普通文件')
                    physical=target/path.relative_to(directory)
                    sha,size,mtime=_copy(path,physical)
                    conn.execute('INSERT INTO files VALUES (?,?,?,?,?)',(str(path),str(physical),sha,size,mtime))
            remaps.append((directory,target))
        fixed_files=[]
        for index,value in enumerate(external_files):
            if not isinstance(value,(str,Path)) or not Path(value).is_absolute():
                raise ValueError('单文件元数据输入必须使用绝对路径')
            path=no_links(value)
            if not path.is_file():raise ValueError('单文件元数据输入不是普通文件')
            fixed_files.append(str(path))
            if _file_row(conn,path) is not None:continue
            physical=folder/'pinned'/str(index)/'input';sha,size,mtime=_copy(path,physical)
            conn.execute('INSERT INTO files VALUES (?,?,?,?,?)',(str(path),str(physical),sha,size,mtime))
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
                capture=capture,capture_sha256=working._hash(captured/'capture.db'),directory_proof=captured_proof['directory_proof'],
                external_directories=[str(path) for path in directories],external_files=fixed_files,
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
    if record.get('capture_sha256') is not None and working._hash(no_links(folder.parent/'capture.db'))!=record['capture_sha256']:
        raise ValueError('冻结捕获目录清单已变化')
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
            row=_file_row(conn,logical);expected=row[2:4] if row is not None else None
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
        if record.get('directory_proof'):
            for logical,physical in conn.execute('SELECT logical,physical FROM directories ORDER BY logical'):
                if not no_links(physical).is_dir():raise ValueError('冻结编译目录副本已变化：'+logical)
                if reverify_original and not no_links(logical).is_dir():raise ValueError('原编译目录已变化：'+logical)
            for index,original in enumerate(record['external_directories']):
                copied=folder/'external'/str(index);origin=no_links(original)
                for base in ([origin,copied] if reverify_original else [copied]):
                    count=1
                    for current,dirs,_ in os.walk(base,followlinks=False):
                        for name in dirs:
                            path=no_links(Path(current)/name);mapped=origin/path.relative_to(base)
                            if _directory_row(conn,mapped) is None:raise ValueError('编译搜索目录出现未记录的目录：'+str(path))
                            count+=1
                    prefix=str(copied)+os.sep
                    expected=1+conn.execute('SELECT count(*) FROM directories WHERE substr(physical,1,?)=?',(len(prefix),prefix)).fetchone()[0]
                    if count!=expected:raise ValueError('编译搜索目录集合已变化')
    return dict(valid=True,files=total,original_reverified=reverify_original,formal_dirty_enabled=False,
                full_build_diff_equivalence='NOT_VERIFIED')


def _file_row(conn, logical):
    """Keep Windows logical path spelling from changing file identity."""
    path=str(Path(logical));query='SELECT logical,physical,sha256,size,mtime_ns FROM files'
    exact=conn.execute(query+' WHERE logical=?',(path,)).fetchone()
    if exact is not None or os.name!='nt':return exact
    key=os.path.normcase(os.path.normpath(path)).casefold()
    for row in conn.execute(query):
        if os.path.normcase(os.path.normpath(row[0])).casefold()==key:return row
    return None


def _directory_row(conn,logical):
    path=str(Path(logical));query='SELECT logical,physical FROM directories'
    exact=conn.execute(query+' WHERE logical=?',(path,)).fetchone()
    if exact is not None or os.name!='nt':return exact
    key=os.path.normcase(os.path.normpath(path)).casefold()
    return next((row for row in conn.execute(query) if os.path.normcase(os.path.normpath(row[0])).casefold()==key),None)


class ParentFiles:
    """Explicit, context-owned frozen filesystem for InputSnapshot parent reads.

    Closing the object invalidates it. Original-input final reverification is
    still mandatory before any future formal publication or resume support.
    """
    def __init__(self, descriptor, root, cfg):
        self.config=cfg
        self.folder,self.record=_load(descriptor,root,cfg)
        validation=working.validate(self.record['capture'],root,cfg,reverify_original=False)
        if not validation['directory_proof'] or not self.record.get('directory_proof') or not self.record.get('capture_sha256'):
            raise ValueError('旧捕获缺少目录集合证据；不能证明冻结父进程文件选择，请重新捕获')
        database=no_links(self.folder/'files.db')
        if working._hash(database)!=self.record['files_sha256']:raise ValueError('冻结编译文件清单已变化')
        self.connection=sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)
        self.connection.execute('PRAGMA query_only=ON');self.connection.execute('PRAGMA trusted_schema=OFF')
        self.connection.execute('BEGIN')
        self.identity=dict(descriptor,original_final_reverification_required=True,formal_dirty_enabled=False)

    def __enter__(self):return self
    def __exit__(self,*_):self.close()
    def close(self):
        if self.connection is not None:self.connection.close();self.connection=None

    def _row(self, path):
        if self.connection is None:raise ValueError('冻结父进程文件视图已经关闭')
        row=_file_row(self.connection,no_links(path))
        if row is None:raise ValueError('父进程请求未固定输入；不回退到实时文件：'+str(path))
        physical=no_links(row[1])
        if not physical.is_relative_to(self.folder.parent):raise ValueError('冻结父进程文件越出捕获范围')
        return row

    def file_record(self,path):
        from .input_snapshot import file_record
        if self.connection is None:raise ValueError('冻结父进程文件视图已经关闭')
        directory=_directory_row(self.connection,no_links(path))
        if directory is not None:
            physical=no_links(directory[1])
            if not physical.is_relative_to(self.folder.parent) or not physical.is_dir():
                raise ValueError('冻结父进程目录副本已变化：'+str(path))
            return file_record(physical)
        row=self._row(path);observed=file_record(row[1])
        if (observed.get('status')!='OK' or observed.get('sha256')!=row[2]
                or observed.get('size')!=row[3] or observed.get('mtime_ns')!=row[4] or observed.get('unstable')):
            raise ValueError('冻结父进程文件副本已变化：'+str(path))
        return observed

    def read_bytes(self,path):
        if self.connection is None:raise ValueError('冻结父进程文件视图已经关闭')
        if _directory_row(self.connection,no_links(path)) is not None:raise IsADirectoryError(str(path))
        row=self._row(path);data=no_links(row[1]).read_bytes()
        if len(data)!=row[3] or hashlib.sha256(data).hexdigest()!=row[2]:
            raise ValueError('冻结父进程实际读取字节已变化：'+str(path))
        return data

    def select_files(self,directory,pattern):
        if self.connection is None:raise ValueError('冻结父进程文件视图已经关闭')
        self.assert_valid()
        logical=no_links(directory);repo=no_links(self.record['repository_root'])
        if logical.is_relative_to(repo):physical=self.folder.parent/'source'/logical.relative_to(repo)
        else:
            physical=None
            for index,original in enumerate(self.record['external_directories']):
                origin=no_links(original)
                if logical.is_relative_to(origin):physical=self.folder/'external'/str(index)/logical.relative_to(origin);break
            if physical is None:raise ValueError('父进程文件选择目录没有完整捕获边界')
        selected=[]
        for path in no_links(physical).glob(pattern):
            no_links(path);mapped=logical/path.relative_to(physical)
            if path.is_file():self._row(mapped)
            elif _directory_row(self.connection,mapped) is None:raise ValueError('冻结文件选择出现未记录的目录')
            selected.append(mapped)
        return selected

    def assert_valid(self):
        if self.connection is None:raise ValueError('冻结父进程文件视图已经关闭')
        validate(dict(file=self.identity['file'],sha256=self.identity['sha256']),self.record['root'],
                 self.config,reverify_original=False)
