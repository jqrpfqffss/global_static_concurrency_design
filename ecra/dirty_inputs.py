"""Automatically inventory an explicit database before fixed working-byte scans.

This planner does not enable formal dirty workflows. It supplies the existing
strict compiler view, whose original/frozen buffers are compared at every gate.
"""
from pathlib import Path
import os
import sys

from .common import digest,write_json
from .config import load_config
from .workspace import no_links,studio_data_root


def supported(analysis):
    if ('cmake' in analysis or analysis.get('auto_configure_cmake',False)
            or analysis.get('compile_database','auto')=='auto' or not analysis.get('build_closure_only',True)):
        raise ValueError('未提交输入的自动固定目前要求显式编译数据库；CMake/自动构建/补充扫描须先完成独立构建等价验收')


def _search_directories(unit):
    separate={'-I','-iquote','-isystem','-idirafter','-F','-iframework','-isysroot','--sysroot','-resource-dir'}
    prefixes=sorted(separate,key=len,reverse=True)
    args=unit['arguments'];index=0
    while index<len(args):
        arg=args[index];value=None
        if arg in separate:
            index+=1
            if index>=len(args):raise ValueError('编译搜索参数缺少目录：'+arg)
            value=args[index]
        else:
            for prefix in prefixes:
                if arg.startswith(prefix) and len(arg)>len(prefix):
                    value=arg[len(prefix):].lstrip('=');break
        if value and value!='-':yield no_links(Path(unit['directory'])/value)
        index+=1


def capture_inputs(root,config,folder,progress=lambda text:None,*,scan_mode=None):
    from .frozen_scan import execution_workspace
    consumed={};cfg,config=load_config(root,config,consumed_inputs=consumed);supported(cfg['analysis'])
    if scan_mode is not None:
        if scan_mode not in {'full','diff'}:raise ValueError('scan_mode必须是full或diff')
        cfg['analysis']['git_diff']['enabled']=scan_mode=='diff'
    # The existing private integration deliberately bypasses only the dirty
    # switch; every Resolver/firmware/install boundary remains enforced.
    ws=execution_workspace(root,cfg['analysis'],object()).initialize();ws.bind(cfg['analysis'])
    folder=studio_data_root(folder)
    if not folder.is_relative_to(Path(ws.workspace_root)):
        raise ValueError('未提交输入盘点必须位于本工程既有独立数据根')
    folder.mkdir(parents=True,exist_ok=False)
    from .scan_diagnostics import ScanDiagnostics
    diagnostics=ScanDiagnostics(folder/'diagnostics',progress)
    try:
        return _capture_inputs(root,config,cfg,consumed,ws,folder,progress,diagnostics)
    except BaseException as exc:
        diagnostics.failure(exc);raise
    finally:diagnostics.close()


def _capture_inputs(root,config,cfg,consumed,ws,folder,progress,diagnostics):
    from .working_snapshot import capture,validate as validate_capture
    from .working_compiler_view import create,validate,ParentFiles
    from .compilation import prepare
    from .portable import resolved_executable,tool_path
    from .cli import dependency_results
    from .workflow import analysis_config,engine_digest
    from clang import cindex
    engine=engine_digest();diagnostics.stage('固定原HEAD、索引与工作区字节/目录')
    fixed=capture(root,cfg,progress)
    diagnostics.stage('盘点真实编译参数与完整外部搜索边界')
    units,compilation=prepare(root,cfg,progress=progress,build_firmware=False)
    requested=cfg['analysis'].get('libclang_file')
    if requested:
        requested=no_links(requested)
        if cindex.Config.loaded:
            if no_links(cindex.conf.lib._name)!=requested:raise ValueError('已加载其他libclang，请在新任务进程中固定指定工具链')
        else:cindex.Config.set_library_file(str(requested))
    cindex.Index.create()
    files={no_links(config),no_links(compilation['compile_database']),no_links(cindex.conf.lib._name)}
    directories=[];repo=no_links(ws.repository_root)
    if cfg['analysis']['git_diff'].get('enabled'):
        files.add(no_links(resolved_executable(tool_path('git'),root)))
    files.update(no_links(root/cfg['analysis']['build_closure'][key]) for key in ('elf','map')
        if cfg['analysis'].get('build_closure',{}).get(key))
    cache=Path(compilation['compile_database']).parent/'CMakeCache.txt'
    if cache.is_file():files.add(no_links(cache))
    for key in ('CMAKE_TOOLCHAIN_FILE','CMAKE_COMMAND','CMAKE_MAKE_PROGRAM','CMAKE_C_COMPILER',
            'CMAKE_CXX_COMPILER','CMAKE_ASM_COMPILER','CMAKE_AR','CMAKE_RANLIB','CMAKE_LINKER'):
        path=compilation.get('cmake_cache',{}).get(key)
        if path and Path(path).is_file():files.add(no_links(path))
    from .initialization import constructor_map_directory
    directories.append(no_links(constructor_map_directory(Path(cfg['project']['root']),cfg)))
    for unit in units:
        # A precompiled AST/module or caller-supplied VFS needs a separate
        # complete dependency proof; never silently drop those flags.
        if any(arg in {'-load','-plugin','-add-plugin'} or arg.startswith(('-fmodules','-fmodule-file',
                '-fprebuilt-module-path','-fimplicit-modules','-fimplicit-module-maps','-include-pth',
                '-fmodule-map-file','-include-pch','-ivfsoverlay','-vfsoverlay','-Xclang=-load','-fplugin',
                '-fpass-plugin')) for arg in unit['arguments']):
            raise ValueError('此编译数据库含尚未证明可冻结的模块/PCH/自带VFS/插件参数，请保留原配置并先完成该模式验收')
        directories.extend(_search_directories(unit))
        cwd=no_links(unit['directory'])
        if not cwd.is_relative_to(repo):directories.append(cwd)
        files.update(no_links(p) for p in unit['response_files'])
        raw=unit['original_arguments'];count=2 if Path(raw[0]).stem.lower() in {'ccache','sccache'} else 1
        files.update(no_links(resolved_executable(p,unit['directory'])) for p in raw[:count])
    workers=folder/'dependency-probe';workers.mkdir()
    tool=Path(__file__).resolve().parents[1]
    env=dict(os.environ,PYTHONPATH=str(tool)+os.pathsep+os.environ.get('PYTHONPATH',''))
    observed={}
    diagnostics.total_units=len(units);diagnostics.stage('原始Clang编译输入盘点')
    for unit,inputs,signature in dependency_results(root,units,cfg,workers,env,tool):
        observed[unit['tu_id']]=dict(inputs=inputs,preprocessor_signature=signature)
        for path,row in inputs.items():
            if row.get('status')=='OK' and not no_links(path).is_relative_to(repo):directories.append(no_links(path).parent)
        diagnostics.completed_units+=1
    # Preserve complete existing directory namespaces, including currently
    # unused siblings and negative probes. Missing roots remain unavailable in
    # the closed VFS; original/frozen preprocessor checks reject any divergence.
    external=[]
    for path in sorted(set(directories),key=lambda p:(len(p.parts),str(p))):
        if path.is_relative_to(repo) or not path.exists():continue
        if not path.is_dir():raise ValueError('编译搜索路径不是目录：'+str(path))
        if any(path==parent or path.is_relative_to(parent) for parent in external):continue
        external.append(path)
    files.update(no_links(p) for p in compilation.get('consumed_inputs',{}))
    validate_capture(fixed,root,cfg,reverify_original=True)
    diagnostics.total_units=diagnostics.completed_units=0
    diagnostics.stage('固定SDK完整目录与元数据，重新核对原输入；剩余量未知')
    descriptor=create(fixed,root,cfg,external_directories=external,external_files=sorted(files),
        proof_scope='COMPLETE_LOGICAL_CLANG_INPUTS_V1')
    with ParentFiles(descriptor,root,cfg) as view:
        expected=dict(consumed,**compilation.get('consumed_inputs',{}))
        for path,row in expected.items():
            actual=view.file_record(path)
            if any(actual.get(key)!=row.get(key) for key in ('status','sha256','size')):
                raise ValueError('配置/数据库/响应文件在盘点消费与固定之间变化：'+str(path))
        for value in observed.values():
            for path,row in value['inputs'].items():
                actual=view.file_record(path)
                if any(actual.get(key)!=row.get(key) for key in ('status','sha256','size')):
                    raise ValueError('实际Clang输入在盘点与固定之间变化：'+str(path))
    validate(descriptor,root,cfg,reverify_original=True)
    if engine_digest()!=engine:raise ValueError('固定输入期间引擎已变化，请重新检查')
    write_json(folder/'capture-plan.json',dict(format='ECRA_DIRTY_INPUT_PLAN_V1',compiler_view=descriptor,
        project_id=ws.project_id,engine_digest=engine,effective_analysis_digest=digest(analysis_config(cfg)),
        external_directories=[str(path) for path in external],external_files=[str(path) for path in sorted(files)],
        observed=observed,admission='REQUIRES_CONFIG_AND_FULL_PIPELINE_VALIDATION'))
    return descriptor
