"""Guarded original-path CMake preparation for fixed working-byte scans."""
import copy
from dataclasses import replace
import json
import os
import re
from pathlib import Path
import uuid

from .common import digest
from .workspace import no_links
from .input_snapshot import file_record


def registered_aliases(*,used_path=None):
    """Both 8.3 and expanded parent spellings of our exact junctions."""
    from .portable import _BUILD_ALIASES
    for target, alias in _BUILD_ALIASES.items():
        for spelling in dict.fromkeys((alias, alias.parent.resolve()/alias.name)):
            if spelling.resolve() != target:
                if used_path is not None and (used_path==spelling or used_path.is_relative_to(spelling)):
                    raise ValueError('内部编译路径别名已变化：'+str(spelling))
                continue
            try:no_links(spelling.parent)
            except ValueError:
                if used_path is not None and (used_path==spelling or used_path.is_relative_to(spelling)):raise
                continue
            yield target, spelling


def input_path(path):
    """Resolve only aliases created by the existing Portable path registry."""
    path=Path(path)
    try:return no_links(path)
    except ValueError:
        for target,alias in registered_aliases(used_path=path):
            if path==alias or path.is_relative_to(alias):
                expected=target/path.relative_to(alias)
                if path.resolve()==expected.resolve():return no_links(expected)
        raise


def policy(analysis):
    settings = analysis.get('cmake', {})
    if (os.name != 'nt' or settings.get('generator', 'Ninja') != 'Ninja'
            or analysis.get('compile_database','auto')!='auto'
            or settings.get('location', 'workspace') != 'workspace'
            or analysis.get('auto_configure_cmake', False)
            or not analysis.get('build_closure_only', True)
            or analysis.get('build_closure')):
        raise ValueError('未提交CMake目前要求compile_database: auto、Windows/Ninja外置构建、build_closure_only且无未绑定的显式ELF/MAP闭包；原输入保留')


def audit_trace(executor, compilation, source):
    """Unproved external generators must not acquire a complete capability."""
    from .portable import resolved_executable
    builtin = input_path(compilation['cmake_cache']['CMAKE_ROOT'])
    compiler = {str(no_links(resolved_executable(p,source))) for k,p in compilation['cmake_cache'].items()
                if k in {'CMAKE_C_COMPILER','CMAKE_CXX_COMPILER','CMAKE_ASM_COMPILER','CMAKE_AR','CMAKE_RANLIB'}}
    forbidden = {'add_custom_command','add_custom_target','try_run'}
    source=no_links(source);files=set();directories=set()
    build_roots=[p for p in (executor.namespace/'builds').glob('*') if p.is_dir()] if hasattr(executor,'namespace') else []
    def inventory(value,origin,*,namespace=False):
        path=Path(value)
        if not path.is_absolute():
            # The complete original source namespace is already captured.
            # An included external script must spell its reads explicitly.
            if '..' in path.parts or not origin.is_relative_to(source):
                raise ValueError('CMake相对配置读取尚未证明归属，请使用明确绝对输入：'+value)
            return
        path=input_path(path)
        if path.is_relative_to(source) or any(path.is_relative_to(p) for p in build_roots):return
        if path.is_file():files.add(path)
        parent=path if namespace and path.is_dir() else path.parent
        while not parent.exists():parent=parent.parent
        if parent==Path(parent.anchor):raise ValueError('CMake配置读取边界不能扩大到磁盘根：'+str(path))
        directories.add(parent)
    for trace in executor.traces:
        with trace.open('r',encoding='utf-8') as stream:
            for line in stream:
                if not line.startswith('{'):continue  # Preserve ordinary stderr in the raw audit.
                row = json.loads(line)
                if 'cmd' not in row: continue
                command = row['cmd'].lower(); origin = no_links(Path(row['file']).resolve())
                args = row.get('args', [])
                trusted = origin.is_relative_to(builtin)
                if command in forbidden or not trusted and command=='try_compile':
                    raise ValueError('未提交CMake包含尚未证明的项目生成/执行命令：'+command+' '+str(origin))
                if command == 'file' and args and str(args[0]).upper() in {'DOWNLOAD','UPLOAD'}:
                    raise ValueError('未提交CMake不允许未固定的联网输入')
                if command=='file' and len(args)>1:
                    operation=str(args[0]).upper()
                    if operation in {'READ','STRINGS','TIMESTAMP','SIZE','MD5','SHA1','SHA224','SHA256','SHA384','SHA512'}:
                        inventory(args[1],origin)
                    if operation in {'GLOB','GLOB_RECURSE'} and not trusted:
                        index=2
                        while index<len(args):
                            value=args[index];index+=1
                            if value=='CONFIGURE_DEPENDS':continue
                            if value in {'RELATIVE','LIST_DIRECTORIES'}:index+=1;continue
                            prefix=re.split(r'[*?\[]',value,maxsplit=1)[0]
                            path=Path(prefix if prefix.endswith(('/','\\')) else str(Path(prefix).parent))
                            if not path.is_absolute():
                                if '..' in path.parts or not origin.is_relative_to(source):
                                    raise ValueError('CMake相对GLOB尚未证明归属')
                            else:
                                actual=input_path(path)
                                if not actual.is_relative_to(source) and not any(actual.is_relative_to(p) for p in build_roots):
                                    raise ValueError('CMake外部GLOB尚未证明完整目录闭包')
                    if operation in {'COPY','COPY_FILE','INSTALL','ARCHIVE_EXTRACT','GET_RUNTIME_DEPENDENCIES'} and not trusted:
                        raise ValueError('CMake项目文件选择/复制尚未证明完整配置闭包：'+operation)
                if command=='if':
                    for index,arg in enumerate(args[:-1]):
                        if arg in {'EXISTS','IS_DIRECTORY','IS_SYMLINK'} and not trusted:
                            inventory(args[index+1],origin,namespace=True)
                        if arg=='IS_WRITABLE' and not trusted:
                            raise ValueError('CMake项目依赖写权限条件，不能保证只读构建等价')
                if command == 'execute_process':
                    if not args or args[0] != 'COMMAND': raise ValueError('CMake项目进程缺少明确输入闭包')
                    from .portable import resolved_executable
                    executable = str(no_links(resolved_executable(args[1],source)))
                    query = [arg for arg in args[2:] if arg]
                    allowed = {'--version','-dumpmachine','-dumpversion','-print-sysroot','-print-search-dirs'}
                    query_only=(query and (query[0] in allowed or query[0].startswith('-print-file-name='))
                        and (len(query)==1 or query[1] in {'OUTPUT_VARIABLE','ERROR_VARIABLE','RESULT_VARIABLE',
                            'OUTPUT_STRIP_TRAILING_WHITESPACE','ERROR_STRIP_TRAILING_WHITESPACE'}))
                    compiler_id=(trusted and origin==builtin/'Modules/CMakeDetermineCompilerId.cmake'
                        and any(Path(arg).name in {'CMakeCCompilerId.c','CMakeCXXCompilerId.cpp','CMakeASMCompilerId.S'} for arg in query))
                    # CMake 3.29's GNU module checks Ninja's depfile support.
                    # Bind the exact built-in site, configured tool and query;
                    # this is not permission for Ninja targets or project code.
                    make=compilation['cmake_cache'].get('CMAKE_MAKE_PROGRAM')
                    ninja_version=(origin==builtin/'Modules/Compiler/GNU.cmake'
                        and compilation['cmake_cache'].get('CMAKE_GENERATOR')=='Ninja' and make
                        and executable==str(no_links(resolved_executable(make,source)))
                        and query==['--version','OUTPUT_VARIABLE','_ninja_version','ERROR_VARIABLE','_ninja_version'])
                    if args.count('COMMAND')!=1 or not (ninja_version or executable in compiler and (query_only or compiler_id)):
                        raise ValueError('CMake项目自定义进程尚未固定完整输入，禁止准入：'+str(origin))
    return dict(files=sorted(files),directories=sorted(directories))


def _signature(units, root):
    from .git_diff import build_arguments
    rows = []
    for unit in units:
        source = no_links(unit['source']); build = no_links(unit['ecra_build_root'])
        name = '<构建>/'+source.relative_to(build).as_posix() if source.is_relative_to(build) else str(source)
        rows.append([name,build_arguments(unit,root)])
    return digest(rows)


def prepare(root, config, cfg, workspace, folder, progress, diagnostics, watch):
    """Return a real prepared build and the already fixed original Git tree."""
    from .working_snapshot import capture, validate
    from .guarded_cmake import BuildExecutor
    from .build_execution import BUILD_EXECUTOR
    from .compilation import prepare as compile_prepare, cmake_build_directory, cmake_input_records
    from .dirty_inputs import _search_directories
    from .guarded_cmake import require_protected_source
    from .cli import dependency_results
    import sys
    policy(cfg['analysis'])
    watch.directory(workspace.repository_root); watch.file(config)
    require_protected_source(workspace.repository_root)
    diagnostics.stage('固定未提交CMake原HEAD、索引、全部工作字节及目录')
    fixed = capture(root,cfg,progress)
    def build(label):
        executor = BuildExecutor(no_links(Path(workspace.build_root)/('working-cmake-'+uuid.uuid4().hex)),root,watch)
        current = copy.deepcopy(cfg)
        build_ws = replace(workspace,build_root=str(executor.namespace/'builds'),
            results_root=str(executor.namespace/'preparation'),cache_root=str(executor.namespace/'cache'),
            snapshots_root=str(executor.namespace/'snapshots'))
        build_ws.bind(current['analysis'])
        directory = cmake_build_directory(root,current['analysis'])
        directory.mkdir(parents=True,exist_ok=False)
        (directory/'.ecra-build-owner').write_text(str(no_links(root)),encoding='utf-8')
        query = directory/'.cmake/api/v1/query/client-ecra/cmakeFiles-v1'
        query.parent.mkdir(parents=True,exist_ok=True); query.touch()
        token = BUILD_EXECUTOR.set(executor)
        try: units, compilation = compile_prepare(root,current,progress)
        finally: BUILD_EXECUTOR.reset(token)
        compilation['consumed_inputs'].update(cmake_input_records(root,directory))
        watch.check(); extra=audit_trace(executor,compilation,root)
        compilation['consumed_inputs'].update((str(p),file_record(p)) for p in extra['files'])
        compilation['configuration_directories']=[str(p) for p in extra['directories']]
        return units,compilation,directory,executor
    diagnostics.stage('只读受监督CMake探测实际配置和编译闭包')
    probe_units, probe, probe_build, _ = build('probe')
    data = no_links(workspace.workspace_root); repo = no_links(workspace.repository_root)
    directories = []
    directories.extend(no_links(p) for p in probe.get('configuration_directories',[]))
    for unit in probe_units: directories.extend(_search_directories(unit,resolve=input_path))
    for path in probe['consumed_inputs']:
        item = no_links(path)
        if item.is_relative_to(probe_build): continue
        watch.file(item)
        if not item.is_relative_to(repo) and not item.is_relative_to(data): directories.append(item.parent)
    for path in sorted(set(directories),key=lambda p:len(p.parts)):
        if path.is_relative_to(probe_build): continue
        if path.is_relative_to(data): raise ValueError('CMake编译输入越入未封存工具数据目录：'+str(path))
        if path.is_dir(): watch.directory(path)
    def buffers(source_units, build_root, name):
        tool = Path(__file__).resolve().parents[1]
        worker = folder/name; worker.mkdir()
        rows = []
        env = dict(os.environ,PYTHONPATH=str(tool)+os.pathsep+os.environ.get('PYTHONPATH',''))
        for unit, inputs, _ in dependency_results(root,source_units,cfg,worker,env,tool):
            key = no_links(unit['source'])
            name = '<构建>/'+key.relative_to(build_root).as_posix() if key.is_relative_to(build_root) else str(key)
            values = []
            for path,row in inputs.items():
                file = no_links(path)
                logical = '<构建>/'+file.relative_to(build_root).as_posix() if file.is_relative_to(build_root) else str(file)
                values.append([logical,{k:row.get(k) for k in ('status','sha256','size')}])
            rows.append([name,sorted(values)])
        watch.check()
        return digest(rows)
    probe_buffers = buffers(probe_units,probe_build,'probe-inputs')
    diagnostics.stage('全新私有目录完成只读CMake实际构建并核对配置/生成输入')
    units, compilation, directory, executor = build('final')
    before = {p: {k:r.get(k) for k in ('status','sha256','size')} for p,r in probe['consumed_inputs'].items()
              if not no_links(p).is_relative_to(probe_build)}
    after = {p: {k:r.get(k) for k in ('status','sha256','size')} for p,r in compilation['consumed_inputs'].items()
             if not no_links(p).is_relative_to(directory)}
    if (before != after or _signature(probe_units,root) != _signature(units,root)
            or probe_buffers != buffers(units,directory,'final-inputs')):
        raise ValueError('CMake配置输入或实际编译闭包在两次构建间不等价；禁止固定/扫描')
    validate(fixed,root,cfg,reverify_original=True); watch.check()
    compilation['guarded_build'] = dict(version=1,source_readonly=True,namespace_changes_checked=True,
        probe_directory=str(probe_build),directory=str(directory),actual_commands=executor.calls,
        trace_files=[dict(file=str(p),sha256=file_record(p)['sha256']) for p in executor.traces],
        configuration_directories=[str(p) for p in sorted(set(directories))
            if p.is_dir() and not p.is_relative_to(repo) and not p.is_relative_to(data)])
    return fixed,units,compilation,directory
