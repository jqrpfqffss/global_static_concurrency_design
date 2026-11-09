"""Real build/input checks before native extraction; never a safety verdict.

Runs only in an owned worker. Reuses the engine's build and dependency paths;
the plan is a paged diagnostic, not a second interpretation of compile flags.
"""
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

from ..common import execute, read_json, write_json
from ..workspace import formal_workspace, no_links, validate_analysis_inputs


def run_preflight(config, data, folder, progress=print, *, _compiler_view=None):
    from ..config import configured_project_root, load_config
    from ..compilation import prepare, cmake_toolchain_input
    from ..input_snapshot import InputSnapshot
    from ..portable import resolved_executable, tool_environment, tool_path
    from ..report_package import sha256
    from ..scan_diagnostics import ScanDiagnostics
    from ..workflow import engine_digest
    folder = no_links(folder); folder.mkdir(parents=True, exist_ok=False)
    result = dict(passed=False, state='PRECHECK', config_sha256=sha256(config),
                  started=datetime.now(timezone.utc).isoformat(), tools=[])
    receipt = folder/'preflight.json'
    write_json(receipt, result)
    diagnostics = ScanDiagnostics(folder/'diagnostics', progress)
    frozen=None
    try:
        diagnostics.stage('预检查：配置与独立数据边界')
        consumed = {}; root = configured_project_root(config)
        cfg, config = load_config(root, config, consumed_inputs=consumed)
        result['target'] = cfg['analysis'].get('cmake', {}).get('target')
        if cfg['analysis']['git_diff'].get('include_uncommitted') and _compiler_view is None:
            raise ValueError('未提交输入预检查缺少固定输入描述；请从Studio任务入口重新固定并检查，不能改用实时工作区')
        analysis = dict(cfg['analysis'])
        if analysis.get('output', {}).get('location', 'user') == 'user':
            analysis['output'] = dict(location='custom', custom_dir=str(data))
        if _compiler_view is not None:
            from ..dirty_inputs import supported
            from ..frozen_scan import execution_workspace,ScanFiles
            supported(analysis)
            ws=execution_workspace(root,analysis,_compiler_view)
        else:ws = formal_workspace(root, analysis)
        if Path(ws.workspace_root) != Path(data):
            raise ValueError('配置输出与本地Studio不同，请使用 output.location: user')
        ws = replace(ws.initialize(), results_root=str(folder), snapshots_root=str(folder/'snapshots'))
        ws.bind(cfg['analysis'])
        if _compiler_view is not None:
            frozen=ScanFiles(_compiler_view,root,cfg)
        write_json(folder/'storage.json', dict(version=1, scan_id=folder.parent.name,
                   project_id=ws.project_id, profile_id='preflight-only'))
        original_root = root; fixed = None; tools = result['tools']; executables = []

        def probe(name, cwd, field):
            path = resolved_executable(name, cwd)
            try:
                if not path.is_file():
                    raise ValueError('文件不存在')
                proc = execute([str(path), '--version'], cwd=cwd, env=tool_environment(), timeout=20)
                text = (proc.stdout+proc.stderr).strip()
                if proc.returncode:
                    raise ValueError('退出码 '+str(proc.returncode)+'；'+text[-2000:])
            except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
                raise ValueError(field+'：工具不可运行 '+str(path)+'；请修正该工具路径/安装对应Portable资产后重新检查。'+str(exc)) from exc
            if str(path) not in executables:
                executables.append(str(path)); tools.append(dict(field=field, path=str(path),
                    version=text, sha256=sha256(path), available=True))
            return path

        def named_tool(name, cwd, field):
            try: name = tool_path(name)
            except ValueError as exc:
                raise ValueError(field+'：'+str(exc)+'；请修复完整Portable工具资产后重新检查。') from exc
            return probe(name, cwd, field)

        if cfg['analysis']['git_diff']['enabled']:
            named_tool('git', root, 'analysis.git_diff / Git')
            from ..git_diff import pin, prepare_current
            fixed = pin(root, cfg)
            root, cfg = prepare_current(root, folder, cfg, fixed, progress)
        if 'cmake' in cfg['analysis']:
            named_tool('cmake', root, 'analysis.cmake / CMake')
            generator = cfg['analysis']['cmake'].get('generator', 'Ninja')
            program = {'Ninja': 'ninja', 'MinGW Makefiles': 'mingw32-make', 'Unix Makefiles': 'make'}.get(generator)
            if program:
                named_tool(program, root, 'analysis.cmake.generator / '+program)
        diagnostics.stage('预检查：加载实际libclang')
        from clang import cindex
        if cfg['analysis'].get('libclang_file'):
            requested = Path(cfg['analysis']['libclang_file']).resolve()
            if cindex.Config.loaded:
                if Path(cindex.conf.lib._name).resolve() != requested:
                    raise ValueError('已加载其他libclang；请在新进程中检查 '+str(requested))
            else:
                cindex.Config.set_library_file(str(requested))
        cindex.Index.create()
        library = Path(cindex.conf.get_filename()).resolve()
        if not library.is_file():
            raise ValueError('analysis.libclang_file：实际libclang文件不可校验 '+str(library))
        executables.append(str(library))
        tools.append(dict(field='Clang AST', path=str(library), sha256=sha256(library), available=True))
        diagnostics.stage('预检查：真实构建与编译命令')
        engine = engine_digest()
        prepared={} if frozen is None else dict(file_view=frozen)
        units, compilation = prepare(root, cfg, progress=progress, build_firmware=True,**prepared)
        diagnostics.total_units = len(units)
        for unit in units:
            if unit['missing_defines']:
                raise ValueError('analysis.expected_defines：'+unit['source_file']+' 缺少预期宏 '+', '.join(unit['missing_defines'])+'；请修正真实构建参数。')
            raw = unit['original_arguments']
            count = 2 if Path(raw[0]).stem.lower() in {'ccache', 'sccache'} else 1
            for name in raw[:count]:
                if str(resolved_executable(name, unit['directory'])) not in executables:
                    probe(name, unit['directory'], '编译数据库 / '+unit['source_file'])
        explicit = [config, compilation['compile_database'], *executables]
        explicit += [Path(unit['source']) for unit in units]
        explicit += [Path(path) for unit in units for path in unit['response_files']]
        explicit += [root/path for path in compilation.get('assembly_sources', [])]
        consumed_closure=compilation.get('build_closure',cfg['analysis'].get('build_closure',{}))
        explicit += [root/consumed_closure[key] for key in ('elf', 'map') if consumed_closure.get(key)]
        cache = Path(compilation['compile_database']).parent/'CMakeCache.txt'
        if cache.is_file(): explicit.append(cache)
        for key in ('CMAKE_TOOLCHAIN_FILE', 'CMAKE_COMMAND', 'CMAKE_MAKE_PROGRAM', 'CMAKE_C_COMPILER',
                    'CMAKE_CXX_COMPILER', 'CMAKE_ASM_COMPILER', 'CMAKE_AR', 'CMAKE_RANLIB', 'CMAKE_LINKER'):
            path = compilation.get('cmake_cache', {}).get(key)
            if path and key=='CMAKE_TOOLCHAIN_FILE':
                explicit.append(cmake_toolchain_input(root,cache.parent,path))
            elif path and Path(path).is_file():
                explicit.append(resolved_executable(path,root))
        snapshot = InputSnapshot(root, folder/'diagnostics', explicit,
                                 dict(consumed, **compilation.get('consumed_inputs', {})),file_view=frozen)
        workers = folder/'workers'; workers.mkdir()
        diagnostics.stage('预检查：全部TU真实编译输入')
        from ..cli import dependency_results
        tool = Path(__file__).resolve().parents[2]
        env = dict(os.environ, PYTHONPATH=str(tool)+os.pathsep+os.environ.get('PYTHONPATH', ''))
        frozen_args={} if frozen is None else dict(compiler_view=_compiler_view)
        for i, (unit, inputs, signature) in enumerate(dependency_results(root, units, cfg, workers, env, tool,**frozen_args)):
            snapshot.discover(unit, inputs, signature)
            diagnostics.completed_units = i+1
            progress('编译输入检查 '+str(i+1)+'/'+str(len(units))+': '+unit['source_file'])
        snapshot.seal()
        validate_analysis_inputs(root, cfg['analysis'], snapshot.before, config_file=config, compilation=compilation)
        diagnostics.snapshot_status = snapshot.status
        if engine_digest() != engine or sha256(config) != result['config_sha256']:
            raise ValueError('引擎或配置在检查中变化，请重新检查')
        with closing(sqlite3.connect(folder/'plan.db')) as db, db:
            db.execute('CREATE TABLE units (ordinal INTEGER PRIMARY KEY, body TEXT NOT NULL)')
            db.executemany('INSERT INTO units VALUES (?,?)', ((i,json.dumps(unit,ensure_ascii=True)) for i,unit in enumerate(units)))
        cmake = cfg['analysis'].get('cmake', {})
        result.update(passed=True, state='PRECHECK_READY', project_id=ws.project_id,
            project_root=str(original_root), analysis_root=str(root), data_root=str(data),
            build_root=str(Path(compilation['compile_database']).parent) if cmake else None,
            compile_database=compilation['compile_database'],
            variant=cmake.get('build_type'), cmake_steps=compilation.get('cmake_steps', []),
            git=fixed, engine_digest=engine, translation_units=len(units),
            input_files=len(snapshot.before), snapshot_status=snapshot.status,
            plan_sha256=sha256(folder/'plan.db'),
            note='真实构建与全部TU编译输入检查通过；尚未进行并发风险分类。正式扫描会重新检查输入与覆盖。')
        if frozen is not None:
            frozen.assert_valid();result['frozen_working_inputs']=dict(_compiler_view)
        return result
    except BaseException as exc:
        result.update(state='INTERRUPTED' if isinstance(exc, KeyboardInterrupt) else 'PRECHECK_FAILED',
                      error=f'{type(exc).__name__}: {exc}',
                      repair='请按具体字段/工具路径修正配置，重新保存并检查；上一有效结果和人工记录保留。')
        diagnostics.failure(exc)
        raise
    finally:
        if frozen is not None:frozen.close()
        diagnostics.close()
        result['finished'] = datetime.now(timezone.utc).isoformat()
        write_json(receipt, result)


def plan_page(folder, offset=0, limit=20):
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError('编译计划分页参数无效')
    folder = no_links(folder); result = read_json(no_links(folder/'preflight.json'))
    if not result.get('passed'):
        return dict(check=result, items=[], total=0, next_offset=None)
    path = no_links(folder/'plan.db')
    from ..report_package import sha256
    if sha256(path) != result['plan_sha256']:
        raise ValueError('编译计划摘要不一致，请保留诊断并重新检查真实构建')
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True)) as db:
        db.execute('PRAGMA query_only=ON'); db.execute('PRAGMA trusted_schema=OFF')
        total = db.execute('SELECT count(*) FROM units').fetchone()[0]
        items = [dict(ordinal=i, **json.loads(raw)) for i,raw in db.execute(
            'SELECT ordinal,body FROM units ORDER BY ordinal LIMIT ? OFFSET ?', (limit, offset))]
    return dict(check=result, items=items, total=total, offset=offset, limit=limit,
                next_offset=offset+limit if offset+limit < total else None)
