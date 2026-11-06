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
from .scan_stop import check_stop

SCHEMA = '''CREATE TABLE files(logical TEXT PRIMARY KEY,physical TEXT NOT NULL,
sha256 TEXT NOT NULL,size INTEGER NOT NULL,mtime_ns INTEGER NOT NULL);
CREATE TABLE directories(logical TEXT PRIMARY KEY,physical TEXT NOT NULL);'''
SHA = re.compile(r'[0-9a-f]{64}')


def _files(root):
    for base, dirs, names in os.walk(root, followlinks=False):
        check_stop()
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
            check_stop()
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


def create(capture, root, cfg, *, external_directories=(), external_files=(), proof_scope=None, prepared=None):
    """Freeze explicitly audited search directories, including negative probes."""
    captured_proof=working.validate(capture,root,cfg)
    cmake_scope=proof_scope=='COMPLETE_GUARDED_CMAKE_INPUTS_V1'
    if proof_scope not in {None,'COMPLETE_LOGICAL_CLANG_INPUTS_V1','COMPLETE_GUARDED_CMAKE_INPUTS_V1'}:raise ValueError('未知冻结编译输入证明范围')
    ws=context(root,cfg['analysis']);original=no_links(ws.repository_root)
    captured=no_links(capture['folder']);tree=no_links(captured/'source')
    owned_build=None
    if cmake_scope:
        if prepared is None:raise ValueError('只读CMake缺少完整准备结果')
        owned_build=no_links(prepared['directory']);boundary=no_links(ws.build_root)
        relative=owned_build.relative_to(boundary)
        if (len(relative.parts)<3 or not re.fullmatch('working-cmake-[0-9a-f]{32}',relative.parts[0])
                or relative.parts[1]!='builds' or (owned_build/'.ecra-build-owner').read_text('utf-8')!=str(no_links(root))
                or (boundary/relative.parts[0]/'.ecra-write-guard').read_text('ascii')!='LOW_INTEGRITY_PRIVATE_DIRECTORY_V1\n'):
            raise ValueError('CMake生成输入不属于已保护的新建构建目录')
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
        if (path==data or path.is_relative_to(data) or data.is_relative_to(path)) and path!=owned_build:
            raise ValueError('外部编译输入不能包含可变ECRA数据根')
        directories.append(path)
    folder=no_links(captured/('compiler-view-'+uuid.uuid4().hex));folder.mkdir()
    database=folder/'files.db';overlay=folder/'overlay.json'
    alias_roots=[]
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
            if cmake_scope:
                from .working_cmake import registered_aliases
                used=set()
                for target,alias in registered_aliases():
                    if alias.resolve()!=target:raise ValueError('内部编译路径别名已变化')
                    roots=[(original,tree),*remaps]
                    for logical,physical in roots:
                        if target.is_relative_to(logical):
                            virtual,copied=alias,physical/target.relative_to(logical)
                        elif logical.is_relative_to(target):
                            virtual,copied=alias/logical.relative_to(target),physical
                        else:continue
                        if str(virtual) in used:continue
                        used.add(str(virtual))
                        stream.write(separator);json.dump(dict(type='directory-remap',name=virtual.as_posix(),
                            **{'external-contents':copied.as_posix()}),stream,ensure_ascii=False);separator=','
                        item=dict(alias=str(alias),target=str(target))
                        if item not in alias_roots:alias_roots.append(item)
            stream.write(']}\n');stream.flush();os.fsync(stream.fileno())
    record=dict(format='ECRA_FROZEN_COMPILER_VIEW_V1',state='PENDING',root=str(no_links(root)),repository_root=str(original),project_id=ws.project_id,
                capture=capture,capture_sha256=working._hash(captured/'capture.db'),directory_proof=captured_proof['directory_proof'],
                external_directories=[str(path) for path in directories],external_files=fixed_files,
                overlay_sha256=working._hash(overlay),files_sha256=working._hash(database),
                formal_dirty_enabled=False,proof='FROZEN_COMPILER_BYTES_ONLY_NOT_FULL_BUILD_DIFF_EQUIVALENCE')
    if proof_scope is not None:
        record.update(format='ECRA_FROZEN_COMPILER_VIEW_V2',proof_scope=proof_scope)
        del record['formal_dirty_enabled']
    if cmake_scope:
        from .workflow import analysis_config
        from .common import digest
        write_json(folder/'prepared.json',prepared)
        record.update(format='ECRA_FROZEN_COMPILER_VIEW_V3',prepared_sha256=working._hash(folder/'prepared.json'),
                      analysis_digest=digest(analysis_config(cfg)),owned_build_directory=str(owned_build),alias_roots=alias_roots)
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
    legacy=record.get('format')=='ECRA_FROZEN_COMPILER_VIEW_V1' and record.get('formal_dirty_enabled') is False and 'proof_scope' not in record
    modern=((record.get('format')=='ECRA_FROZEN_COMPILER_VIEW_V2' and record.get('proof_scope')=='COMPLETE_LOGICAL_CLANG_INPUTS_V1'
        or record.get('format')=='ECRA_FROZEN_COMPILER_VIEW_V3' and record.get('proof_scope')=='COMPLETE_GUARDED_CMAKE_INPUTS_V1')
        and 'formal_dirty_enabled' not in record)
    if (not (legacy or modern) or record.get('state')!=('PENDING' if _pending else 'COMPLETE')
            or record.get('project_id')!=ws.project_id
            or canonical(record.get('root',''))!=canonical(root)
            or canonical(record.get('repository_root',''))!=canonical(ws.repository_root)
            or no_links(record['capture']['folder'])!=folder.parent):
        raise ValueError('冻结编译视图的工程或能力声明无效')
    if working._hash(no_links(folder/'overlay.json'))!=record.get('overlay_sha256'):
        raise ValueError('冻结编译视图overlay已变化')
    if record.get('capture_sha256') is not None and working._hash(no_links(folder.parent/'capture.db'))!=record['capture_sha256']:
        raise ValueError('冻结捕获目录清单已变化')
    if record.get('format')=='ECRA_FROZEN_COMPILER_VIEW_V3':
        from .workflow import analysis_config
        from .common import digest
        if (working._hash(no_links(folder/'prepared.json'))!=record.get('prepared_sha256')
                or digest(analysis_config(cfg))!=record.get('analysis_digest')):
            raise ValueError('冻结CMake准备结果或有效分析配置已变化')
        for alias in record.get('alias_roots',[]):
            if Path(alias['alias']).resolve()!=no_links(alias['target']):raise ValueError('冻结CMake的内部路径别名已变化')
    return folder,record


def arguments(descriptor, root, cfg, unit):
    """Check a pinned internal Worker request without rehashing every TU's tree."""
    folder,record=_load(descriptor,root,cfg)
    repo=no_links(record['repository_root'])
    directory=no_links(unit['directory'])
    cwd_allowed=directory.is_relative_to(repo) or any(directory.is_relative_to(no_links(path)) for path in record['external_directories'])
    source=no_links(unit['source']);build=record.get('owned_build_directory')
    source_allowed=source.is_relative_to(repo) or build is not None and source.is_relative_to(no_links(build))
    if not source_allowed or not cwd_allowed:
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


def validate(descriptor, root, cfg, *, reverify_original=True, _pending=False, review_config_path=None):
    folder,record=_load(descriptor,root,cfg,_pending=_pending)
    working.validate(record['capture'],root,cfg,reverify_original=reverify_original)
    database=no_links(folder/'files.db')
    if working._hash(database)!=record['files_sha256']:raise ValueError('冻结编译文件清单已变化')
    with closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)) as conn:
        conn.execute('PRAGMA query_only=ON');conn.execute('PRAGMA trusted_schema=OFF')
        compatible_config=None
        if review_config_path is not None:
            from .config import load_config
            from .workflow import analysis_config
            from .common import digest
            candidate=no_links(review_config_path)
            if str(candidate) not in record.get('external_files',[]):
                raise ValueError('复核配置未作为原扫描元数据固定，不能豁免源码输入')
            row=_file_row(conn,candidate)
            if row is None:raise ValueError('原复核配置缺少固定字节')
            pinned,_=load_config(root,no_links(row[1]))
            # CLI mode is an explicit invocation override, not YAML content.
            pinned['analysis']['git_diff']['enabled']=cfg['analysis']['git_diff']['enabled']
            if digest(analysis_config(pinned))!=digest(analysis_config(cfg)):
                raise ValueError('冻结扫描的有效分析配置已变化，不能复用原事实')
            compatible_config=candidate
        total=0
        for logical,physical,sha,size,mtime in conn.execute('SELECT logical,physical,sha256,size,mtime_ns FROM files ORDER BY logical'):
            check_stop()
            path=no_links(physical)
            if not path.is_relative_to(folder.parent) or not path.is_file() or path.stat().st_size!=size or path.stat().st_mtime_ns!=mtime or working._hash(path)!=sha:
                raise ValueError('冻结编译文件副本已变化：'+logical)
            if reverify_original:
                source=no_links(logical)
                if source!=compatible_config and (not source.is_file() or source.stat().st_size!=size
                        or source.stat().st_mtime_ns!=mtime or working._hash(source)!=sha):
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
    result=dict(valid=True,files=total,original_reverified=reverify_original,full_build_diff_equivalence='NOT_VERIFIED')
    result.update(dict(proof_scope=record['proof_scope']) if record.get('format') in {'ECRA_FROZEN_COMPILER_VIEW_V2','ECRA_FROZEN_COMPILER_VIEW_V3'}
                  else dict(formal_dirty_enabled=False))
    return result


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
        if self.record.get('format') in {'ECRA_FROZEN_COMPILER_VIEW_V2','ECRA_FROZEN_COMPILER_VIEW_V3'}:
            del self.identity['formal_dirty_enabled'];self.identity['proof_scope']=self.record['proof_scope']
        self.build_token=None
        self.source_names=None
        if self.record.get('format')=='ECRA_FROZEN_COMPILER_VIEW_V3':
            from .build_execution import FROZEN_BUILD
            import weakref
            self.build_token=FROZEN_BUILD.set((no_links(root),no_links(self.record['owned_build_directory']),weakref.ref(self)))

    def prepared_compilation(self):
        if self.record.get('format')!='ECRA_FROZEN_COMPILER_VIEW_V3':return None
        from .common import read_json, digest
        from .workflow import analysis_config
        if (working._hash(self.folder/'prepared.json')!=self.record['prepared_sha256']
                or digest(analysis_config(self.config))!=self.record['analysis_digest']):
            raise ValueError('CMake准备结果/分析配置已变化，禁止重新构建或回退')
        prepared=read_json(self.folder/'prepared.json')
        if prepared.get('directory')!=self.record['owned_build_directory']:
            raise ValueError('CMake准备结果的构建归属不一致')
        out=no_links(context(self.record['root'],self.config['analysis']).results_root)
        for index,step in enumerate(prepared['compilation'].get('cmake_steps',[])):
            if not step.get('log'):continue
            raw=self.read_bytes(step['log']);target=out/'diagnostics/cmake-preparation'/('step-'+str(index)+'.log')
            target.parent.mkdir(parents=True,exist_ok=True)
            if target.exists() and target.read_bytes()!=raw:raise ValueError('已归档CMake日志不一致')
            if not target.exists():target.write_bytes(raw)
            step['log']=str(target)
        for index,row in enumerate(prepared['compilation'].get('guarded_build',{}).get('trace_files',[])):
            raw=self.read_bytes(row['file'])
            if hashlib.sha256(raw).hexdigest()!=row['sha256']:raise ValueError('CMake原始执行审计已变化')
            target=out/'diagnostics/cmake-preparation'/('trace-'+str(index)+'.jsonl');target.parent.mkdir(parents=True,exist_ok=True)
            if target.exists() and target.read_bytes()!=raw:raise ValueError('已归档CMake执行审计不一致')
            if not target.exists():target.write_bytes(raw)
            row['file']=str(target)
        return prepared['units'],prepared['compilation']

    def __enter__(self):return self
    def __exit__(self,*_):self.close()
    def close(self):
        if self.connection is not None:self.connection.close();self.connection=None
        if self.build_token is not None:
            from .build_execution import FROZEN_BUILD
            FROZEN_BUILD.reset(self.build_token);self.build_token=None

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

    def _directory_path(self,directory):
        if self.connection is None:raise ValueError('冻结父进程文件视图已经关闭')
        logical=no_links(directory);repo=no_links(self.record['repository_root'])
        if logical.is_relative_to(repo):physical=self.folder.parent/'source'/logical.relative_to(repo)
        else:
            physical=None
            for index,original in enumerate(self.record['external_directories']):
                origin=no_links(original)
                if logical.is_relative_to(origin):physical=self.folder/'external'/str(index)/logical.relative_to(origin);break
            if physical is None:raise ValueError('父进程文件选择目录没有完整捕获边界：'+str(logical))
        return logical,no_links(physical)

    def walk(self,directory):
        """Enumerate the captured namespace using original logical paths."""
        self.assert_valid()
        logical,physical=self._directory_path(directory)
        for current,dirs,names in os.walk(physical,followlinks=False):
            for name in dirs+names:no_links(Path(current)/name)
            self._verify_names(logical/Path(current).relative_to(physical),dirs,names)
            # Preserve os.walk's mutable dirs contract for caller pruning.
            yield str(logical/Path(current).relative_to(physical)),dirs,names

    def _verify_names(self,logical,dirs,names):
        if self.record.get('format')!='ECRA_FROZEN_COMPILER_VIEW_V3':return
        repo=no_links(self.record['repository_root'])
        if not logical.is_relative_to(repo):return
        if self.source_names is None:
            from collections import defaultdict
            self.source_names=defaultdict(set)
            for table in ('files','directories'):
                for (value,) in self.connection.execute('SELECT logical FROM '+table):
                    path=Path(value)
                    if path!=repo and path.is_relative_to(repo):self.source_names[path.parent].add(path.name)
        actual=set(dirs+names)
        if logical==repo:actual.discard('.git')
        if actual!=self.source_names[logical]:raise ValueError('冻结源码枚举目录与完整清单不一致：'+str(logical))

    def select_files(self,directory,pattern):
        self.assert_valid()
        logical,physical=self._directory_path(directory)
        if self.record.get('format')=='ECRA_FROZEN_COMPILER_VIEW_V3':
            dirs,names=[],[]
            for item in no_links(physical).iterdir():
                no_links(item);(dirs if item.is_dir() else names).append(item.name)
            self._verify_names(logical,dirs,names)
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
