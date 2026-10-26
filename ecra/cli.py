import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys
import time

from . import __version__
from .analysis import analyze, merge
from .common import digest, execute, read_json, relative, write_json
from .compilation import cmake_build_directory, excluded, prepare
from .config import (TEMPLATE, CMAKE_TEMPLATE, TOOL_ROOT, SEMANTICS_FILE,
                     configured_project_root, load_config, resolve_config_path,
                     discover_arm_toolchains)
from .report import generate
from .html_report import QUALITY_PAGE, REVIEW_PAGE, write_failure, write_html, review_records, category
from .review import review_all, resolve_command


def file_hashes(root, out, extra=(), audit_roots=(), *, exact=False):
    paths = set(Path(p).resolve() for p in extra)
    roots = [] if exact else [root]
    for folder in sorted(audit_roots, key=lambda p: len(p.parts)):
        if not any(folder.is_relative_to(r) for r in roots):
            roots.append(folder)
    for base, dirs, files in (row for tree in roots for row in os.walk(tree)):
        dirs[:] = [d for d in dirs if d not in {".git", "node_modules", "__pycache__"}
                   and (Path(base) / d).resolve() != out]
        for name in files:
            # Build products, model logs and reports are outputs, not analysis
            # inputs. Hashing them made every review stale and read gigabytes of
            # unrelated vendor assets. Explicit config/database/include inputs
            # above remain included regardless of extension.
            if (Path(name).suffix.lower() in {".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx", ".s", ".inc", ".ld", '.cmake'}
                    or name in {'CMakeLists.txt', 'CMakePresets.json', 'CMakeUserPresets.json'}):
                paths.add((Path(base) / name).resolve())
    result = {}
    for p in sorted(paths):
        if p.is_file():
            import hashlib
            h = hashlib.sha256()
            with p.open("rb") as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b""):
                    h.update(chunk)
            result[relative(p, root)] = h.hexdigest()
    return result


def dependency_inputs(root, unit, cfg, worker_dir, env, tool_root):
    """Discover with Clang itself; GCC depfiles can miss Clang-specific inputs."""
    request = worker_dir / (unit['tu_id'] + '.dependencies.request.json')
    response = worker_dir / (unit['tu_id'] + '.dependencies.response.json')
    write_json(request, dict(root=str(root), unit=unit, config=cfg,
                            verify_inputs=True, dependencies_only=True,
                            diagnostics_dir=str(worker_dir.parent / 'diagnostics/dependencies')))
    response.unlink(missing_ok=True)
    proc = execute([sys.executable, '-B', '-m', 'ecra.extract', str(request), str(response)],
                   cwd=tool_root, env=env, timeout=float(cfg['analysis'].get('parse_timeout_seconds', 180)))
    if proc.returncode or not response.is_file():
        raise ValueError(f"Clang 依赖发现失败 {unit['source_file']}: {proc.returncode} {proc.stderr[-4000:]}")
    result = read_json(response)
    if not isinstance(result.get('input_snapshot'), dict):
        raise ValueError(f"Clang 无法验证输入 {unit['source_file']}: {result.get('diagnostics')}")
    return result['input_snapshot'], result.get('preprocessor_signature')


def dependency_results(root, units, cfg, worker_dir, env, tool_root):
    from collections import deque
    from concurrent.futures import ThreadPoolExecutor
    count = cfg['analysis'].get('extraction_workers', 1)
    pool = ThreadPoolExecutor(max_workers=count)
    todo = iter(units)
    pending = deque()
    def submit():
        unit = next(todo, None)
        if unit is not None:
            pending.append((unit, pool.submit(dependency_inputs, root, unit, cfg, worker_dir, env, tool_root)))
    try:
        for _ in range(count):
            submit()
        while pending:
            unit, future = pending.popleft()
            inputs, signature = future.result()
            yield unit, inputs, signature
            submit()
    finally:
        pool.shutdown(wait=True, cancel_futures=True)


def extraction_responses(root, units, cfg, worker_dir, env, tool_root, out, cache=None):
    """Run bounded workers; only paths/exit metadata cross thread boundaries.

    Consume in DB order so weak/strong selection, function declaration choice
    and evidence order remain identical to a sequential scan.
    """
    from concurrent.futures import ThreadPoolExecutor
    def job(unit):
        request = worker_dir / (unit['tu_id'] + '.request.json')
        response = worker_dir / (unit['tu_id'] + '.response.json')
        metadata = Path(str(response) + '.metadata.json')
        write_json(request, dict(root=str(root), unit=unit, config=cfg, verify_inputs=True,
                   write_metadata=True, diagnostics_dir=str(out / 'diagnostics/workers')))
        response.unlink(missing_ok=True)
        metadata.unlink(missing_ok=True)
        if cache is not None and cache.restore(unit, response, metadata):
            return unit, response, metadata
        try:
            proc = execute([sys.executable, '-B', '-m', 'ecra.extract', str(request), str(response)],
                           cwd=tool_root, env=env, timeout=float(cfg['analysis'].get('parse_timeout_seconds', 180)))
        except MemoryError:
            raise
        except Exception as exc:
            write_json(response, dict(parse_status='FAILED', diagnostics=[dict(severity=4,
                       message=f'{type(exc).__name__}: {exc}')]))
            return unit, response, metadata
        if proc.returncode or not response.is_file():
            # A dead/crashed worker is an infrastructure failure. It must not
            # become an apparently successful incomplete static report.
            raise RuntimeError(f"Worker {unit['tu_id']} {unit['source_file']} 退出 {proc.returncode}: {proc.stderr[-4000:]}")
        return unit, response, metadata
    pool = ThreadPoolExecutor(max_workers=cfg['analysis'].get('extraction_workers', 1))
    futures = [pool.submit(job, unit) for unit in units]
    try:
        for future in futures:
            yield future.result()
    finally:
        pool.shutdown(wait=True, cancel_futures=True)


def add_build_unknowns(facts, cfg, units, compilation):
    """Identical coverage preparation for cached and independent full scans."""
    if len({u['source_file'] for u in units}) != len(units):
        facts['unknowns'].append(dict(kind='MULTIPLE_BUILD_VARIANTS', hint='为每个固件配置分别导出数据库并扫描'))
    known = {f['function_id'] for f in facts['functions']}
    from .protection import NEUTRAL
    summarized = set(NEUTRAL) | {'memcpy', 'memmove', 'memset', 'memcmp', 'xTaskCreate', 'xTaskCreateStatic',
        'osThreadNew', 'xTaskCreatePinnedToCore', '__disable_irq', '__enable_irq', '__get_PRIMASK', '__set_PRIMASK',
        '__get_BASEPRI', '__set_BASEPRI', '__set_BASEPRI_MAX', '__disable_fault_irq', '__enable_fault_irq'}
    summarized.update(s[k] for s in cfg.get('critical_sections', []) for k in ('enter', 'exit', 'save', 'restore') if k in s)
    for call in facts['calls']:
        if call['call_kind'] == 'DIRECT' and call['callee_function_id'] not in known and call['callee_name'] not in summarized:
            facts['unknowns'].append(dict(kind='EXTERNAL_CALLEE', function_id=call['caller_function_id'],
                callee=call['callee_name'], file=call['file'], line=call['line']))
    for path in compilation['unlisted_sources']:
        facts['unknowns'].append(dict(kind='SOURCE_NOT_IN_DATABASE', file=path))
    for unit in units:
        if unit['parse_status'] == 'FAILED':
            facts['unknowns'].append(dict(kind='PARSE_FAILED', file=unit['source_file'], diagnostics=unit['diagnostics']))


def safe_review_samples(facts, count, shared_count=0):
    """Select deterministic screened samples without changing risk accounting."""
    if not count and not shared_count:
        return []
    samples = []
    for classification, limit, prefix in (
            ('SAFE_PROVEN', count, 'SAFE-SAMPLE-'),
            ('SHARED_NO_REVIEW', shared_count, 'SHARED-SAMPLE-')):
        selected = [v for v in facts['variables'] if v.get('static_classification') == classification]
        for variable in sorted(selected, key=lambda v: v['symbol_id'])[:limit]:
            samples.append(dict(
                finding_id=prefix + digest(variable['symbol_id'])[:16],
                symbol_id=variable['symbol_id'], variable_name=variable['qualified_name'],
                rules=['SAFE_SAMPLE' if classification == 'SAFE_PROVEN' else 'SHARED_NO_REVIEW_SAMPLE'],
                risk_level='LOW', confidence='HIGH', status='NEED_OPENCODE_REVIEW',
                review_safe_sample=True, review_screened_sample=True,
                static_classification=classification,
                protection_status=variable.get('protection_status', 'NOT_FOUND'),
                protection_note=variable.get('protection_note'), accesses=variable.get('accesses', []),
                definition=dict(file=variable.get('definition_file'), line=variable.get('definition_line')),
                context_pairs=[], concurrency_relations=variable.get('concurrency_relations', []),
                screening_blockers=variable.get('screening_blockers', []), uncertainties=[],
                concurrency_reason=('SAFE_PROVEN 抽样复核：核对静态安全依据是否覆盖全部已解析访问和调用链。'
                    if classification == 'SAFE_PROVEN' else
                    'SHARED_NO_REVIEW 抽样复核：核对单写者门禁、访问原子性和协议排除证据。')))
    return samples


def run(root, config_path=None, no_review=False, doctor_only=False, review_safe_sample=0,
        review_shared_sample=0, scan_mode=None, _cache_enabled=False):
    started = datetime.now(timezone.utc).isoformat()
    started_ns = time.time_ns()
    consumed_config = {}
    cfg, config_file = load_config(root, config_path, consumed_inputs=consumed_config)
    if scan_mode is not None:
        if scan_mode not in ('full', 'diff'):
            raise ValueError('scan_mode 必须是 full/diff')
        cfg['analysis']['git_diff']['enabled'] = scan_mode == 'diff'
    if no_review:
        cfg["review"]["enabled"] = False
    out = (root / cfg["analysis"].get("output_dir", ".ecra")).resolve()
    if out == root or not out.is_relative_to(root):
        raise ValueError("analysis.output_dir 必须是工程根目录下的独立子目录")
    out.mkdir(parents=True, exist_ok=True)
    lock = out / "scan.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise ValueError(f"已有扫描锁 {lock}；确认没有扫描进程后移除过期锁") from exc
    os.write(fd, json.dumps(dict(pid=os.getpid(), started=started)).encode())
    os.close(fd)
    run_info = dict(version=__version__, started=started, project_root=str(root), state="RUNNING",
                    review_mode='disabled_by_cli' if no_review else
                    ('enabled' if cfg['review'].get('enabled', True) else 'disabled_by_config'))
    doctor = dict(project_root=str(root), python=sys.executable, python_version=sys.version,
                  semantics_found=True, config=str(config_file), ready_for_scan=False)
    log_started = False

    def progress(message):
        nonlocal log_started
        print(message, flush=True)
        with (out / ('doctor.log' if doctor_only else 'run.log')).open(
                'a' if log_started else 'w', encoding='utf-8') as stream:
            stream.write(datetime.now(timezone.utc).isoformat() + ' ' + message + '\n')
        log_started = True

    from .scan_diagnostics import ScanDiagnostics
    diagnostics = ScanDiagnostics(out / ('diagnostics/doctor' if doctor_only else 'diagnostics'), progress)
    report_can_replace = True
    source_token = None
    diff_pin = base_summary_file = None
    tu_cache = None
    try:
        # Keep previous logs/diagnostics intact until they have been archived.
        diagnostics.stage('扫描准备与历史归档', announce=False)
        if doctor_only:
            from .portable import diagnostics as portable_diagnostics
            doctor.update(portable_diagnostics(cfg['analysis'].get('libclang_file')))
            for name, info in doctor['tools'].items():
                progress(f'{name}: ' + json.dumps(info, ensure_ascii=False))
        from .workflow import engine_digest
        engine_at_start = engine_digest()
        previous_ids = set()
        old_report = out / "reports/global_static_concurrency.json"
        if old_report.is_file():
            report_can_replace = False
            # Do not retain the last scan's full access/call evidence during a
            # new scan. Only IDs are needed for the baseline delta.
            import sqlite3
            try:
                with closing(sqlite3.connect(f"{(out / 'facts.db').as_uri()}?mode=ro", uri=True)) as connection:
                    previous_ids = {row[0] for row in connection.execute('SELECT finding_id FROM findings')}
            except sqlite3.Error:
                previous_ids = {f['finding_id'] for f in read_json(old_report).get('findings', [])}
        if ((out / "run.json").is_file() or old_report.is_file()) and not doctor_only:
            snapshot = out / "snapshots" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            snapshot.mkdir(parents=True)
            for name in ("facts.json", "facts.db", "run.json", "scan_state.json", "input_manifest.json", "input_closure.json", "doctor.json", "run.log", "index.html", REVIEW_PAGE, QUALITY_PAGE, "inventory", "reports", "review", 'diagnostics', 'result_validity.json', 'html_details'):
                p = out / name
                if p.is_dir():
                    if name == 'review':
                        reviewed = {x.name.split('.attempt')[0] for x in p.glob('*.attempt*')}
                        def derived_packets(directory, names):
                            return [n for n in names if any(n.endswith(suffix) and n[:-len(suffix)] not in reviewed
                                    for suffix in ('.input.json','.prompt.txt'))]
                        shutil.copytree(p, snapshot / name, ignore=derived_packets)
                    else:
                        shutil.copytree(p, snapshot / name)
                elif p.is_file():
                    shutil.copy2(p, snapshot / name)
            report_can_replace = True
        if not doctor_only:
            (out/'scan_state.json').unlink(missing_ok=True)
            (out/'input_closure.json').unlink(missing_ok=True)
            write_json(out / "run.json", run_info)
            write_json(out / 'result_validity.json', dict(analysis_valid=False, state='RUNNING', started=started))
            write_failure(out, state='RUNNING')
        if cfg['analysis']['git_diff']['enabled']:
            from .git_diff import pin, prepare_base
            diff_pin = pin(root, cfg)
            doctor['git_diff'] = diff_pin
            if not doctor_only:
                diagnostics.stage('Git 基准版本完整分析')
                base_summary_file = prepare_base(root, out, cfg, diff_pin, progress)
        diagnostics.stage('编译数据库准备')
        progress("检查配置、libclang 和真实编译数据库…")
        if no_review:
            progress('本次命令使用 --no-review，已跳过 OpenCode；候选项只会保存为 PENDING。')
        elif not cfg['review'].get('enabled', True):
            progress('review.enabled 为 false，已跳过 OpenCode；候选项只会保存为 PENDING。')
        from clang import cindex
        if cfg["analysis"].get("libclang_file"):
            requested_library = Path(cfg['analysis']['libclang_file']).resolve()
            if cindex.Config.loaded:
                if Path(cindex.conf.lib._name).resolve() != requested_library:
                    raise ValueError(f'已加载其他 libclang；请在新进程中使用所配置的 {requested_library}')
            else:
                cindex.Config.set_library_file(str(requested_library))
        cindex.Index.create()
        doctor["libclang_found"] = True
        from .scope import AuditScope
        scope = AuditScope(root, cfg['analysis'])
        if scope.active:
            progress('排查目录：' + (', '.join(scope.include_dirs) or '全部') + '；排除目录：' + (', '.join(scope.exclude_dirs) or '无'))
            progress('范围外编译依赖只用于恢复调用链和目标变量的访问，不生成第三方变量候选。')
        units, compilation = prepare(root, cfg, progress=progress, build_firmware=not doctor_only)
        doctor.update(compilation, compile_database_found=True, translation_units_total=len(units), ready_for_scan=True)
        if doctor_only:
            cache = compilation.get('cmake_cache', {})
            doctor['acceptance']['cmake_configure'] = 'PASS' if compilation.get('cmake_steps') else 'NOT_RUN'
            doctor['cmake_make_program'] = cache.get('CMAKE_MAKE_PROGRAM')
            doctor['actual_c_compiler'] = cache.get('CMAKE_C_COMPILER')
            doctor['actual_cxx_compiler'] = cache.get('CMAKE_CXX_COMPILER')
            doctor['generator'] = cache.get('CMAKE_GENERATOR', cfg['analysis'].get('cmake', {}).get('generator'))
            progress('CMake / 编译器 / 外部依赖: ' + json.dumps(dict(generator=doctor['generator'],
                make=doctor['cmake_make_program'], c=doctor['actual_c_compiler'], cxx=doctor['actual_cxx_compiler'],
                database=compilation['compile_database'], external=compilation.get('external_tools', [])), ensure_ascii=False))
        doctor['review_enabled'] = cfg['review'].get('enabled', True)
        if doctor['review_enabled']:
            try:
                command=resolve_command(cfg['review'].get('command',['opencode']))
                doctor.update(opencode_command_found=True, opencode_executable=command[0])
            except ValueError as exc:
                doctor.update(opencode_command_found=False, opencode_error=str(exc))
                progress('源码仍会正常盘点；OpenCode 尚不可用：'+str(exc))
        write_json(out / "doctor.json", doctor)
        if doctor_only:
            doctor['acceptance']['opencode_review'] = ('COMMAND_FOUND_NOT_TESTED' if doctor.get('opencode_command_found')
                else 'NOT_TESTED' if doctor['review_enabled'] else 'DISABLED')
            progress('验收状态: ' + json.dumps(doctor['acceptance'], ensure_ascii=False))
            write_json(out / 'doctor.json', doctor)
            run_info["state"] = "DOCTOR_READY"
            if doctor['portable_root'] and any(not info.get('matching', True) for info in doctor['tools'].values()):
                progress('Portable 工具版本/运行检查失败，详见 doctor.json。')
                return 3
            if doctor.get('opencode_command_found') is False:
                progress('源码分析环境可用；请安装 OpenCode 或修正 review.command。')
                return 2
            progress("环境检查通过。尚未进行源码覆盖、模型提供商连接和并发分析。")
            return 0
        # CMake may regenerate headers legitimately before extraction begins.
        diagnostics.total_units = len(units)
        diagnostics.stage('扫描输入快照建立')
        response_files = {p for u in units for p in u.get('response_files', [])}
        sources = [u['source'] for u in units]
        sources.extend(str((root / p).resolve()) for p in compilation.get('assembly_sources', []))
        worker_dir = out / "workers"
        worker_dir.mkdir(exist_ok=True)
        from .fact_parts import FactParts
        from .input_snapshot import InputSnapshot, SOURCE_READS
        parts, all_includes = FactParts(), set()
        tool_root = Path(__file__).resolve().parent.parent
        env = os.environ.copy()
        env["PYTHONPATH"] = str(tool_root) + os.pathsep + env.get("PYTHONPATH", "")
        explicit = [config_file, compilation['compile_database'], *sources, *response_files]
        explicit.extend(root / cfg['analysis']['build_closure'][key] for key in ('elf', 'map')
                        if cfg['analysis'].get('build_closure', {}).get(key))
        if not cfg['analysis'].get('build_closure_only', True):
            from .supplemental import selected_files
            explicit.extend(root / p for p in selected_files(root, scope, out))
        cache = Path(compilation['compile_database']).parent / 'CMakeCache.txt'
        if cache.is_file():
            explicit.append(cache)
            toolchain = compilation.get('cmake_cache', {}).get('CMAKE_TOOLCHAIN_FILE')
            if toolchain:
                explicit.append(toolchain)
        snapshot_inputs = InputSnapshot(root, out / 'diagnostics', explicit,
                                       dict(consumed_config, **compilation.get('consumed_inputs', {})))
        from .initialization import constructor_map_directory
        constructor_root = Path(cfg.get('project',{}).get('root') or root)
        snapshot_inputs.register_selection(constructor_map_directory(constructor_root,cfg),'*.map')
        source_token = SOURCE_READS.set(snapshot_inputs)

        def read_verified_source(path, **kwargs):
            try:
                return snapshot_inputs.read_text(path, **kwargs)
            finally:
                diagnostics.snapshot_status = snapshot_inputs.status

        snapshot_inputs.save()
        diagnostics.snapshot_status = snapshot_inputs.status
        snapshot_inputs.assert_valid()
        for i, (unit, inputs, signature) in enumerate(dependency_results(root, units, cfg, worker_dir, env, tool_root)):
            progress(f"依赖快照 {i+1}/{len(units)}: {unit['source_file']}")
            snapshot_inputs.discover(unit, inputs, signature)
        snapshot_inputs.seal()
        if _cache_enabled or (diff_pin and cfg['analysis']['git_diff']['cache_enabled']):
            from .tu_cache import TUCache
            tu_cache = TUCache(out/'cache/tu-v1', cfg, snapshot_inputs)
            # Fix keys before workers mutate live unit dictionaries.
            for unit in units:
                tu_cache.key(unit)
        diagnostics.snapshot_status = snapshot_inputs.status
        diagnostics.stage('Clang 翻译单元提取')
        for i, (unit, response, metadata_file) in enumerate(extraction_responses(
                root, units, cfg, worker_dir, env, tool_root, out, cache=tu_cache)):
            role = ' [依赖]' if scope.active and unit.get('audit_role') == 'dependency' else ''
            progress(f"Clang {i + 1}/{len(units)}{role}: {unit['source_file']}")
            try:
                metadata_only = metadata_file.is_file()
                part = read_json(metadata_file if metadata_only else response)
            except Exception as exc:
                if isinstance(exc, MemoryError):
                    raise
                part = dict(parse_status="FAILED", diagnostics=[dict(severity=4, message=str(exc))])
                write_json(response, part)
                metadata_only = False
            if part.get('worker_exception'):
                raise RuntimeError(f"Worker {unit['tu_id']} {unit['source_file']}: "
                                   f"{part['worker_exception']}；详见 diagnostics/workers")
            if unit["missing_defines"]:
                if metadata_only:
                    part = read_json(response)
                    metadata_only = False
                part["parse_status"] = "FAILED"
                part.setdefault("diagnostics", []).append(dict(severity=4, message="缺少预期宏: " + ", ".join(unit["missing_defines"])))
                write_json(response, part)
            unit["parse_status"] = part["parse_status"]
            unit["diagnostics"] = part.get("diagnostics", [])
            unit["includes"] = part.get("includes", [])
            unit['semantic_macros_digest'] = part.get('semantic_macros_digest')
            for variable in part.get("variables", []):
                variable["parse_status"] = part["parse_status"]
            all_includes.update(part.get("includes", []))
            if isinstance(part.get('input_snapshot'), dict):
                snapshot_inputs.observe(unit, part['input_snapshot'], signature=part.get('preprocessor_signature'))
                if tu_cache is not None:
                    tu_cache.store(unit, response, part)
            else:
                # A timed-out/failed extraction supplies no safe facts. Keep
                # the parse gap; final discovery still verifies its inputs.
                unit['input_verification'] = 'NO_EXTRACTION_BUFFER_PARSE_FAILED'
            if metadata_only:
                parts.append_metadata(response, part)
            else:
                parts.append(response, part)
            diagnostics.completed_units = i+1
            diagnostics.fact_counts = parts.counts
            del part
        diagnostics.stage('输入一致性验证')
        for unit, inputs, signature in dependency_results(root, units, cfg, worker_dir, env, tool_root):
            snapshot_inputs.observe(unit, inputs, phase='FINAL_DISCOVERY', signature=signature)
        after = snapshot_inputs.verify_disk()
        snapshot_inputs.save()
        diagnostics.snapshot_status = snapshot_inputs.status
        snapshot_inputs.assert_valid()
        diagnostics.stage('跨翻译单元事实归并')
        facts = merge(parts)
        diagnostics.fact_source = facts
        diagnostics.fact_counts = {key: len(value) for key, value in facts.items() if isinstance(value, list)}
        diagnostics.fact_counts_scope = 'merged_facts'
        parts.clear()
        facts['translation_units'] = units
        from .supplemental import supplement, selected_files, build_file_coverage
        all_supplemental_tus, supplemental_includes = ([], set())
        if not cfg['analysis'].get('build_closure_only', True):
            all_supplemental_tus, supplemental_includes = supplement(
                root, out, facts, units, cfg, scope, worker_dir, env, tool_root, progress,
                source_reader=read_verified_source)
        all_includes.update(supplemental_includes)
        facts['translation_units'] = units + all_supplemental_tus
        included_paths = {relative(p, root) for u in units for p in u.get('includes', [])}
        unlisted_headers = [p for p in selected_files(root, scope, out)
                            if Path(p).suffix.lower() in {'.h', '.hh', '.hpp', '.hxx', '.inc'} and p not in included_paths]
        compilation['unlisted_headers'] = unlisted_headers if not cfg['analysis'].get('build_closure_only', True) else []
        compilation['excluded_headers_from_build'] = unlisted_headers
        if unlisted_headers and not cfg['analysis'].get('build_closure_only', True):
            facts['unknowns'].append(dict(kind='HEADERS_NOT_INCLUDED', files=unlisted_headers,
                hint='已尝试补充声明盘点；这些头文件不属于当前构建的访问证据。'))
        diagnostics.stage('输入一致性验证')
        after = snapshot_inputs.verify_disk()
        snapshot_inputs.save()
        diagnostics.snapshot_status = snapshot_inputs.status
        snapshot_inputs.assert_valid()
        add_build_unknowns(facts, cfg, units, compilation)
        parsed = sum(u["parse_status"] == "PARSED" for u in units)
        partial = sum(u["parse_status"] == "PARTIAL" for u in units)
        failed = sum(u["parse_status"] == "FAILED" for u in units)
        cov = dict(translation_units_total=len(units), translation_units_parsed=parsed,
                   translation_units_partial=partial, translation_units_failed=failed,
                   parse_coverage_percent=round(100 * (parsed + partial) / len(units), 2),
                   **compilation)
        # Build per-file coverage table for source-level accountability
        from .supplemental import build_file_coverage
        diagnostics.fact_counts = {key: len(value) for key, value in facts.items() if isinstance(value, list)}
        diagnostics.stage('指针、函数指针及调用图分析')
        report = analyze(facts, cfg, cov, root=root, source_reader=read_verified_source)
        if diff_pin:
            from .git_diff import summarize, compare
            diagnostics.stage('双版本完整证据比较与语义影响传播')
            report['git_diff'] = compare(read_json(base_summary_file), summarize(facts, report), diff_pin)
            report['git_diff']['tu_cache'] = tu_cache.stats() if tu_cache else dict(total=len(units), hits=0, extracted=len(units), corrupt=0)
            for variable in facts['variables']:
                if variable['symbol_id'] in report['git_diff']['impacts']:
                    variable['impact'] = report['git_diff']['impacts'][variable['symbol_id']]
            if cfg['analysis']['git_diff']['verify_against_full']:
                from .git_diff import verify_full
                report['git_diff']['full_verification'] = verify_full(root, out, cfg, units, cov, facts, report,
                                                                       worker_dir, env, tool_root, read_verified_source)
        snapshot_inputs.finalize_parent_inputs()
        diagnostics.fact_counts = {key: len(value) for key, value in facts.items() if isinstance(value, list)}
        samples = safe_review_samples(facts, review_safe_sample, review_shared_sample)
        if samples:
            # Samples are deliberately separate from report.findings: they do
            # not turn a SAFE result into a risk candidate or alter TOTAL
            # accounting.  Packets/queue records remain fully auditable.
            report['review_safe_samples'] = samples
            if diff_pin:
                selected = set(report['git_diff']['selected_symbol_ids'])
                report['review_safe_samples'] = [s for s in samples if s.get('symbol_id') in selected]
            cfg['review']['prepare_packets'] = True
        cov['file_coverage'] = build_file_coverage(facts, units, all_supplemental_tus, scope, root, output_dir=out)
        # Static extraction/classification changes require a fresh scan.
        # Review prompts and presentation changes use the saved facts directly.
        from .workflow import engine_digest, analysis_config
        if engine_digest() != engine_at_start:
            raise ValueError('扫描期间分析实现已变化；请重新运行 run，不能保存混用版本的证据')
        # Static analysis and report construction can be long on large builds.
        # Recheck the input bytes before publishing the first checkpoint too.
        diagnostics.stage('发布前输入一致性验证')
        for unit, inputs, signature in dependency_results(root, units, cfg, worker_dir, env, tool_root):
            snapshot_inputs.observe(unit, inputs, phase='PRE_PUBLICATION', signature=signature)
        snapshot_inputs.verify_disk()
        snapshot_inputs.save()
        snapshot_inputs.assert_valid()
        if diff_pin:
            from .git_diff import assert_pin
            assert_pin(root, cfg, diff_pin)
        analysis_inputs = {p:h for p,h in after.items() if p != relative(config_file,root)}
        fingerprint = digest([__version__, engine_digest(), analysis_config(cfg), analysis_inputs,
                              snapshot_inputs.preprocessor, [u["arguments"] for u in units],
                              snapshot_inputs.consumed_selections(), diff_pin])
        report.update(fingerprint=fingerprint, generated_at=started, tool_version=__version__)
        try:
            git = execute(["git", "rev-parse", "HEAD"], cwd=root, timeout=10)
            report["git_commit"] = git.stdout.strip() if git.returncode == 0 else "unknown"
        except OSError:
            report["git_commit"] = "unknown"
        old_ids = previous_ids
        new_ids = {f["finding_id"] for f in report["findings"]}
        report["baseline"] = dict(new=sorted(new_ids - old_ids), unchanged=sorted(new_ids & old_ids),
                                  no_longer_observed=sorted(old_ids - new_ids),
                                  note="不再观察到不等于已修复；覆盖变化和证据变化必须复核")
        write_json(out / "input_manifest.json", after)
        single_publication = (not cfg['review'].get('enabled', True)
                              and not cfg['review'].get('prepare_packets', False))
        from .workflow import save_scan
        if not single_publication:
            diagnostics.stage('报告生成与存储')
            generate(out, facts, report, [])
            save_scan(root, out, cfg, config_file, report)
        else:
            progress('未启用自动复核及证据包；完成最终输入校验后单次发布完整报告。')
        progress(f"已盘点 {len(facts['variables'])} 个变量，生成 {len(report['findings'])} 个候选/盲区复核项。")
        last_checkpoint = time.monotonic()

        def checkpoint(current):
            nonlocal last_checkpoint
            if time.monotonic() - last_checkpoint < 30:
                return
            records = review_records(report, current)
            report['review_summary'] = dict(total=len(records), unresolved=sum(category(r) == 'unresolved' for r in records))
            report['run_status'] = 'REVIEW_RUNNING'
            write_html(out, facts, report, current)
            last_checkpoint = time.monotonic()

        diagnostics.stage('可选 OpenCode 复核')
        reviews = review_all(root, out, cfg, facts, report, fingerprint, progress, on_result=checkpoint,
                             review_context_path=config_file.parent/'review_context.md',
                             case_library_path=config_file.parent/'concurrency_cases.md')
        end_hashes = file_hashes(root, out, [root / p for p in after], exact=True)
        if end_hashes != after:
            report["analysis_status"] = "INCOMPLETE"
            report["limitations"].append("复核期间源码或输入发生变化；本轮证据需重新生成。")
            from .review_integrity import mark_review_stale
            for r in reviews:
                mark_review_stale(out/'review', r, '复核期间源码或输入发生变化；本轮证据需重新生成。')
            write_json(out/'review/queue.json', reviews)
        if cfg['review'].get('enabled', True):
            for unit, inputs, signature in dependency_results(root, units, cfg, worker_dir, env, tool_root):
                snapshot_inputs.observe(unit, inputs, phase='POST_REVIEW', signature=signature)
        snapshot_inputs.verify_disk()
        snapshot_inputs.save()
        diagnostics.snapshot_status = snapshot_inputs.status
        snapshot_inputs.assert_valid()
        from .review_integrity import review_integrity
        integrity = review_integrity(report, reviews, require_terminal=True)
        pending = sum(r["state"] != "DONE" or r.get("status") in {"NEED_MORE_CONTEXT", "LIKELY"} for r in reviews)
        report["review_summary"] = dict(total=len(reviews), unresolved=pending, **integrity)
        review_by_id = {r["finding_id"]: r for r in reviews}
        for finding in report["findings"]:
            r = review_by_id.get(finding["finding_id"], {})
            finding["review_state"] = r.get("state", "PENDING")
            finding["review_status"] = r.get('status')
            if r.get("state") == "DONE":
                finding["status"] = r["status"]
                finding["review"] = r["answer"]
        report["run_status"] = "INCOMPLETE" if report["analysis_status"] == "INCOMPLETE" or pending or not integrity['complete'] else "REVIEW_COMPLETE"
        diagnostics.stage('报告生成与存储（单次发布）' if single_publication else '最终报告生成与存储')
        generate(out, facts, report, reviews)
        if single_publication:
            save_scan(root, out, cfg, config_file, report, initialize_queue=False)
        # Exporting gigabytes can take longer than extraction. Bind the proof
        # to input bytes/lookup state after every publication/checkpoint write.
        diagnostics.stage('报告发布后输入一致性验证')
        if engine_digest() != engine_at_start:
            raise ValueError('扫描期间静态分析实现已变化；不能发布混用版本的安全证明，请重新运行 run')
        for unit, inputs, signature in dependency_results(root, units, cfg, worker_dir, env, tool_root):
            snapshot_inputs.observe(unit, inputs, phase='POST_PUBLICATION', signature=signature)
        snapshot_inputs.verify_disk()
        snapshot_inputs.save()
        diagnostics.snapshot_status = snapshot_inputs.status
        snapshot_inputs.assert_valid()
        if diff_pin:
            assert_pin(root, cfg, diff_pin)
        diagnostics.stage('最终完整性验收')
        write_json(out / 'result_validity.json', dict(analysis_valid=True, state='STATIC_SCAN_SAVED',
                   snapshot_status=snapshot_inputs.status, fingerprint=fingerprint))
        write_json(out / 'diagnostics/completion.json', dict(fingerprint=fingerprint,
                   translation_units_total=len(units), parsed=parsed, partial=partial, failed=failed,
                   fact_counts={key: len(value) for key, value in facts.items() if isinstance(value, list)},
                   variable_accountability=cov.get('variable_accountability'),
                   classifications=cov.get('static_classification'), snapshot_status=snapshot_inputs.status,
                   static_analysis_status=report['analysis_status'], analysis_valid=True,
                   output_files={str(path.relative_to(out)): path.stat().st_size for path in
                     [out/'facts.json', out/'facts.db', out/'index.html', out/'reports/global_static_concurrency.json']}))
        code = 2 if report["run_status"] == "INCOMPLETE" else (1 if report["findings"] else 0)
        run_info.update(state=report["run_status"], exit_code=code, fingerprint=fingerprint,
                        report=str(out / "index.html"), review_report=str(out / REVIEW_PAGE), review_summary=report["review_summary"])
        progress(f"完成：{report['run_status']}；变量与风险 {out / 'index.html'}；OpenCode 结果 {out / REVIEW_PAGE}")
        if cfg['analysis'].get('open_report', False):
            try:
                import webbrowser
                if not webbrowser.open((out / 'index.html').as_uri()):
                    progress('浏览器未自动打开，请打开上述 index.html。')
            except Exception as exc:
                progress(f'报告已生成，浏览器未打开：{exc}')
        return code
    except KeyboardInterrupt as exc:
        if source_token is not None:
            diagnostics.snapshot_status = snapshot_inputs.status
        # Release Python pools before allocating a bound call/frame for the
        # handler; true allocator exhaustion differs from raising a mock OOM.
        diagnostics.reserve = None
        diagnostics.failure(exc)
        run_info.update(state='INTERRUPTED', exit_code=130)
        if not doctor_only and (out/'scan_state.json').exists():
            queue=read_json(out/'review/queue.json')
            report['run_status']='INTERRUPTED'
            generate(out, facts, report, queue)
        progress('已中断；完成静态扫描后可用 review 继续复核，否则重新运行 run。')
        if not doctor_only:
            write_failure(out, state='INTERRUPTED', write_report=report_can_replace)
            (out / 'scan_state.json').unlink(missing_ok=True)
            write_json(out / 'result_validity.json', dict(analysis_valid=False, state='INTERRUPTED'))
        return 130
    except Exception as exc:
        if source_token is not None:
            diagnostics.snapshot_status = snapshot_inputs.status
        diagnostics.reserve = None
        diagnostics.failure(exc)
        run_info.update(state="FAILED", exit_code=3, error=f"{type(exc).__name__}: {exc}")
        doctor.update(ready_for_scan=False, error=run_info["error"])
        if doctor_only and cfg['analysis'].get('cmake'):
            from .portable import read_cache
            try:
                cache = read_cache(cmake_build_directory(root, cfg['analysis']))
            except (OSError, ValueError):
                cache = {}
            doctor.update(cmake_cache=cache, cmake_make_program=cache.get('CMAKE_MAKE_PROGRAM'),
                          actual_c_compiler=cache.get('CMAKE_C_COMPILER'),
                          actual_cxx_compiler=cache.get('CMAKE_CXX_COMPILER'))
        write_json(out / "doctor.json", doctor)
        if not doctor_only:
            write_failure(out, write_report=report_can_replace)
            (out / 'scan_state.json').unlink(missing_ok=True)
            write_json(out / 'result_validity.json', dict(analysis_valid=False, state='FAILED', error=run_info['error']))
        progress("失败：" + run_info["error"])
        return 3
    finally:
        if source_token is not None:
            source_token.var.reset(source_token)
        diagnostics.close()
        run_info["finished"] = datetime.now(timezone.utc).isoformat()
        if not doctor_only:
            write_json(out / "run.json", run_info)
        lock.unlink(missing_ok=True)


def main(argv=None):
    # Match UTF-8 report files and Windows IDE terminals, regardless of ACP.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="STM32 全局/static 清单、读写调用链与 OpenCode 并发复核")
    parser.add_argument("command", nargs="?", choices=["run", "init", "doctor", "review", "review-failed", "report", "status"], default="run",
                        help='run 全流程；review 重跑全部疑似/未知；review-failed 仅重跑技术失败；report 刷新报告；status 查看进度；doctor 环境检查')
    parser.add_argument("--project", type=Path, help="临时覆盖 semantics.yaml 中的 project.root")
    parser.add_argument("--config", help="显式配置文件路径；正常使用唯一的 config/semantics.yaml")
    parser.add_argument("--compile-database", help="init 时写入真实编译数据库路径（相对工程根目录）")
    parser.add_argument("--model", help="init 时写入已配置的 OpenCode provider/model")
    parser.add_argument('--toolchain-file', help='init 时指定 CMake Arm 工具链文件（相对固件根目录）')
    parser.add_argument("--no-review", action="store_true", help="只生成静态报告与待复核清单，不调用 OpenCode")
    parser.add_argument('--scan-mode', choices=['full', 'diff'], help='覆盖本次全量/分支差异模式，不修改 YAML')
    parser.add_argument("--review-safe-sample", type=int, default=0, metavar='N',
                        help='额外抽取 N 个 SAFE_PROVEN 项生成质量复核证据包；不改变风险队列')
    parser.add_argument("--review-shared-sample", type=int, default=0, metavar='N',
                        help='额外抽取 N 个 SHARED_NO_REVIEW 项生成质量复核证据包；不改变风险队列')
    parser.add_argument("--json", action="store_true", help="status 输出可供脚本读取的 JSON")
    args = parser.parse_args(argv)
    try:
        if args.scan_mode is not None and args.command not in {'run', 'doctor'}:
            raise ValueError('--scan-mode 仅用于 run/doctor；恢复命令沿用已保存范围')
        if args.json and args.command != 'status':
            raise ValueError('--json 仅用于 status')
        if args.review_safe_sample < 0:
            raise ValueError('--review-safe-sample 必须是非负整数')
        if args.review_shared_sample < 0:
            raise ValueError('--review-shared-sample 必须是非负整数')
        if (args.review_safe_sample or args.review_shared_sample) and args.command != 'run':
            raise ValueError('--review-safe-sample/--review-shared-sample 仅用于 run')
        if args.command != 'init' and (args.compile_database is not None or args.model is not None or args.toolchain_file is not None):
            raise ValueError('--compile-database / --model / --toolchain-file 仅用于 init；已有工程请编辑 semantics.yaml')
        if args.command != 'init':
            config_path = resolve_config_path(args.project, args.config)
            root = args.project.resolve() if args.project else configured_project_root(config_path)
            if not root.is_dir():
                raise ValueError(f"工程目录不存在: {root}")
        if args.command in {'review', 'review-failed', 'report', 'status'}:
            from .workflow import saved_run, status
            if args.no_review:
                raise ValueError('--no-review 仅用于 run；仅刷新报告请使用 report')
            if args.command == 'status':
                info=status(root, str(config_path))
                if args.json:
                    print(json.dumps(info, ensure_ascii=False, indent=2))
                else:
                    print(f"工程：{root}\n已保存状态：{info['state']}")
                    if 'variables' in info:
                        print(f"变量 {info['variables']} · 复核项 {info['findings']} · 未完成 {info['unresolved']}")
                    print('下一步：'+info['next_action'])
                    if 'inventory_html' in info:
                        print('变量报告：'+info['inventory_html']+'\n复核报告：'+info['review_html'])
                return 0
            return saved_run(root, str(config_path), render_only=args.command=='report',
                             failed_only=args.command=='review-failed')
        if args.command == "init":
            import yaml
            if not args.project:
                raise ValueError('init 需要 --project <固件目录>，它会创建唯一的 config/semantics.yaml')
            root = args.project.resolve()
            if not root.is_dir():
                raise ValueError(f"工程目录不存在: {root}")
            path = resolve_config_path(root, args.config) if args.config else SEMANTICS_FILE
            if path.exists():
                raise ValueError(f"唯一配置已存在，不覆盖: {path}；请直接编辑 project.root 切换项目")
            managed_cmake = (root/'CMakeLists.txt').is_file() and args.compile_database is None
            content = CMAKE_TEMPLATE if managed_cmake else TEMPLATE
            try:
                root_text = str(root.relative_to(path.parent))
            except ValueError:
                root_text = str(root)
            content = content.replace('root: ../firmware/MyBoard', 'root: ' + json.dumps(root_text, ensure_ascii=False), 1)
            # Keep custom BSP/User/Services directories. A shortlist of familiar
            # Cube folders silently excluded application code on other boards.
            if not managed_cmake:
                content = content.replace('include_dirs: []', 'include_dirs: [.]', 1)
                content = content.replace('exclude_dirs: []',
                    'exclude_dirs: [Drivers, Middlewares, ThirdParty, build, .ecra]', 1)
            if args.toolchain_file and not managed_cmake:
                raise ValueError('--toolchain-file 需要 CMake 工程，且不可与 --compile-database 同用')
            if managed_cmake:
                choices = [(root/args.toolchain_file).resolve()] if args.toolchain_file else discover_arm_toolchains(root)
                if len(choices) == 1:
                    if not choices[0].is_file():
                        raise ValueError(f'工具链文件不存在: {choices[0]}')
                    content = content.replace('# toolchain_file: cmake/arm-none-eabi.cmake',
                        'toolchain_file: ' + json.dumps(relative(choices[0], root), ensure_ascii=False), 1)
                elif choices:
                    print('发现多个 Arm 工具链；请在配置中选择 toolchain_file：' + ', '.join(map(str, choices)))
            # Serialize user values as quoted YAML scalars; Windows paths and
            # characters such as '#' must survive without becoming YAML syntax.
            if args.compile_database is not None:
                content = content.replace('compile_database: auto', 'compile_database: ' +
                                          json.dumps(args.compile_database, ensure_ascii=False), 1)
            if args.model is not None:
                if not args.model.strip() or '/' not in args.model:
                    raise ValueError('--model 必须是已配置的 provider/model')
                content = content.replace('# model: provider/model', 'model: ' +
                                          json.dumps(args.model, ensure_ascii=False), 1)
                content = content.replace('enabled: false', 'enabled: true', 1)
            yaml.safe_load(content)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('x', encoding='utf-8') as stream:
                stream.write(content)
            print(f"已生成 {path}\n确认排查/排除目录、CMake 配置和复核设置后即可执行一键排查。")
            launcher = f'"{sys.executable}" "{Path(__file__).resolve().parent.parent / "run_ecra.py"}"'
            if not (Path(__file__).resolve().parent.parent / 'run_ecra.py').is_file():
                launcher = 'ecra'
            elif os.name == 'nt':
                launcher = '& ' + launcher  # PowerShell quoted executable
            print('环境检查：' + launcher + ' doctor')
            print('一键排查：' + launcher)
            return 0
        return run(root, str(config_path), args.no_review, args.command == "doctor",
                   args.review_safe_sample, args.review_shared_sample, scan_mode=args.scan_mode)
    except (ValueError, OSError, ImportError) as exc:
        print(f"ECRA: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
