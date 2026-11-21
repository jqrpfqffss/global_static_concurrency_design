import fnmatch
import json
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path

from .common import read_json, relative, write_json
from .build_execution import execute, save_logs
from .build_tree import OWNER_MARKER, clean_owned_directory, owns_build_directory as _owns_build_directory
from .path_io import filesystem_path, resolved_path
from .scope import AuditScope
from .workspace import build_path as workspace_build_path, results_path, context, no_links
from .portable import (bundle_root, tool_path, tool_environment, check_cache, read_cache,
                       audit_executable, probe_tool, build_path)


CXX_SOURCE_SUFFIXES = frozenset({'.cc', '.cpp', '.cxx', '.c++', '.mpp'})
C_SOURCE_SUFFIXES = CXX_SOURCE_SUFFIXES | {'.c'}


def source_language(source, arguments=()):
    """Return the C, C++ or assembly language of an actual compiler input."""
    language = None
    options = iter(arguments)
    for arg in options:
        if arg == '-x':
            language = next(options, None)
        elif arg.startswith('-x'):
            language = arg[2:]
    if language and language != 'none':
        if language in {'c', 'c-header', 'cpp-output', 'c-cpp-output'}:
            return 'c'
        if language in {'c++', 'c++-header', 'c++-cpp-output'}:
            return 'c++'
        if language in {'assembler', 'assembler-with-cpp'}:
            return 'asm'
        return None
    path = Path(source)
    if path.suffix == '.C' or path.suffix.lower() in CXX_SOURCE_SUFFIXES | {'.ii'}:
        return 'c++'
    if path.suffix.lower() in {'.c', '.i'}:
        return 'c'
    if path.suffix.lower() in {'.s', '.asm'}:
        return 'asm'
    return None


def cmake_toolchain_input(root, build, value):
    """Resolve the configure input using CMake's build-first relative contract."""
    path = Path(value)
    if not path.is_absolute():
        built = Path(build) / path
        path = built if filesystem_path(built).is_file() else Path(root) / path
    return resolved_path(path)


def _validated_build_directory(root, requested, boundary=None):
    build = no_links(requested)
    boundary = no_links(boundary or root)
    if build == boundary or not build.is_relative_to(boundary):
        raise ValueError(f'analysis.cmake.build_dir 必须位于独立且归属明确的构建边界内: {boundary}')
    return build


def cmake_build_directory(root, analysis):
    """Select a stable owned build tree without adopting an existing user's tree.

    Older runs and manual builds have no owner marker. When cleaning is enabled,
    preserve them and configure in a sibling tree instead, including for doctor.
    Keep the saved analysis configuration unchanged for review/resume digests.
    """
    from .build_execution import FROZEN_BUILD
    sealed=FROZEN_BUILD.get()
    active=sealed[2]() if sealed is not None else None
    if active is not None and active.connection is not None and no_links(root)==sealed[0]:
        # Constructor-map lookup and all parent selections must use the same
        # real prepared tree as Clang, without mutating analysis configuration.
        return no_links(sealed[1])
    settings = analysis['cmake']
    boundary = root if settings.get('location') == 'project' else Path(context(root, analysis).build_root)
    configured = _validated_build_directory(root, workspace_build_path(root, analysis), boundary)
    out = results_path(root, analysis)
    build = configured
    suffix = 0
    while True:
        build = _validated_build_directory(root, build, boundary)
        if out == build or out.is_relative_to(build):
            raise ValueError(f'构建目录不可包含 ECRA 输出目录: {build} / {out}')
        disk = filesystem_path(build)
        if (not settings.get('clean_before_configure', False) or not disk.exists() or
                (disk.is_dir() and (not any(disk.iterdir()) or _owns_build_directory(build, root)))):
            break
        suffix += 1
        build = configured.with_name(configured.name + '-ecra' + (f'-{suffix}' if suffix > 1 else ''))
    return build


def cmake_input_records(root, build):
    """Bind the selected target's actual configure inputs to InputSnapshot."""
    from .cmake_file_api import FileAPI
    try:
        records = {}
        api = FileAPI(root, build, records)
        api.inputs()
        # Its filename is generation-specific; protected/explicit Ninja retain
        # the existing input set rather than depending on a volatile pointer.
        records.pop(str(api.index))
        records.pop(str(api.reply/api.references['cmakeFiles-v1']['jsonFile']))
        return records
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError('所选目标的 CMake 构建输入无法校验，禁止发布分析结果') from exc


def configure_cmake(root, analysis, progress, build_firmware, *, project=None, diagnostics=None):
    """Managed CMake mode refreshes the database on every run, even if present."""
    settings = analysis['cmake']
    configured_target = effective_target = settings.get('target')
    variant = settings.get('build_type', 'Debug')
    build = cmake_build_directory(root, analysis)
    disk = filesystem_path(build)
    if disk.exists() and not disk.is_dir():
        raise ValueError(f'CMake 构建路径被非目录占用：{build}；请选择独立的构建目录。')
    owned = _owns_build_directory(build, root)
    empty = not disk.exists() or not any(disk.iterdir())
    if settings.get('location', 'workspace') == 'workspace' and not empty and not owned:
        raise ValueError(f'外置构建目录没有当前源码所有权，拒绝接管: {build}')
    configured = resolved_path(root / settings.get('build_dir', 'build/ecra'))
    requested = analysis.get('compile_database', 'auto')
    # Explicit paths referring to the configured tree remain valid after isolation;
    # managed CMake always returns the freshly generated database in the chosen tree.
    if requested != 'auto' and resolved_path(root/requested) not in {
            configured / 'compile_commands.json', build / 'compile_commands.json'}:
        raise ValueError(f'analysis.compile_database 与 cmake.build_dir 不匹配；应为 {build / "compile_commands.json"}')
    if build != configured:
        progress(f'保留非 ECRA 专用构建目录: {configured}；自动使用独立构建目录: {build}')
    database = build / 'compile_commands.json'
    disk_database = filesystem_path(database)
    out = results_path(root, analysis)
    out.mkdir(parents=True, exist_ok=True)
    generator = settings.get('generator', 'Ninja')
    if generator not in {'Ninja', 'MinGW Makefiles', 'Unix Makefiles'}:
        raise ValueError(f'不支持导出编译数据库的 Generator: {generator}')
    if configured_target and generator == 'Unix Makefiles':
        raise ValueError('analysis.cmake.target 需要 Ninja 或 MinGW Makefiles')
    cmake = tool_path('cmake') if bundle_root() else 'cmake'
    make = None
    if bundle_root():
        name = {'Ninja': 'ninja', 'MinGW Makefiles': 'mingw32-make', 'Unix Makefiles': 'make'}[generator]
        make = tool_path(name)
        if generator == 'Unix Makefiles':
            make = shutil.which('make', path=tool_environment()['PATH'])
            if not make:
                raise ValueError('Unix Makefiles 需要兼容的 make 环境；本包提供 MinGW Makefiles 和 Ninja')
        lock = read_json(bundle_root()/'portable-lock.json')
        for tool in ('cmake', name):
            probe = probe_tool(tool, lock['version_patterns'].get(tool))
            if not probe.get('matching', probe['running']):
                raise ValueError(f'Portable 工具版本不匹配: {probe}')
    args = settings.get('args', [])
    if any(x in {'-S', '-B', '-G', '--preset', '--build', '--install'} or x.startswith(('-S', '-B', '-G', '--preset=')) for x in args):
        raise ValueError('cmake.args 不可覆盖源码/构建目录或生成器；请使用对应配置字段')
    if make and any('CMAKE_MAKE_PROGRAM' in arg for arg in args):
        raise ValueError('Portable 的 CMAKE_MAKE_PROGRAM 由 Generator 选择；不可用 cmake.args 覆盖')
    outputs = re.compile(r'(?:CMAKE_(?:RUNTIME|LIBRARY|ARCHIVE|PDB|COMPILE_PDB)_OUTPUT_DIRECTORY(?:_\w+)?|'
                         r'CMAKE_INSTALL_PREFIX)(?::\w+)?=(.*)', re.I)
    for arg in args:
        match = outputs.fullmatch(arg.removeprefix('-D').strip())
        if match:
            value = match[1]
            if '$<' in value or ';' in value or not no_links(build/value).is_relative_to(build):
                raise ValueError(f'CMake 输出参数超出本项目构建目录 {build}: {arg}')
    records = []

    allow_external = analysis.get('allow_external_toolchain', settings.get('allow_external_toolchain', False))
    from .build_execution import BUILD_EXECUTOR
    from .build_target_checkpoint import check_previous_selection, protected_baseline, save_selection
    from .cmake_auto_target import eligibility
    protected = BUILD_EXECUTOR.get() is not None
    build_args = settings.get('build_args', [])
    reason = None if configured_target else eligibility(
        analysis, project or {}, build_firmware, protected or protected_baseline.get())
    try_auto = not configured_target and reason is None
    resolve_target = bool(configured_target or try_auto)
    selection = dict(source='explicit' if configured_target else 'automatic' if try_auto else
                     'build_args' if build_args else 'default', configured_target=configured_target,
                     effective_target=None, build_type=variant, reason=reason, candidates=[])
    if diagnostics is not None:
        diagnostics.update(target=None, target_selection=selection, variant=variant, cmake_steps=records)
    if not protected:
        check_previous_selection(root, build, resolve_target)

    if empty:
        try:
            disk.mkdir(parents=True, exist_ok=True)
            with (disk / OWNER_MARKER).open('x', encoding='utf-8') as stream:
                stream.write(str(resolved_path(root)))
        except OSError as exc:
            raise ValueError(f'CMake 初始化构建目录失败：{build}；请检查目录占用与写入权限。{exc}') from exc
        owned = True

    will_clean = settings.get('clean_before_configure', False) and build_firmware
    if will_clean:
        progress('清理 CMake 构建目录…')
        previous_cache = read_cache(build)
        clean_owned_directory(build, root)
        records.append(dict(stage='clean', command=['clean-build-tree', str(build)], exit_code=0,
                            previous_cache=previous_cache))

    cache, _ = check_cache(build, root, generator, make, allow_external)
    if bundle_root():
        for key in ('CC', 'CXX', 'ASM'):
            if os.environ.get(key):
                audit_executable(os.environ[key], root, allow_external=allow_external)
        for key in ('GCC_EXEC_PREFIX', 'COMPILER_PATH', 'LIBRARY_PATH', 'CPATH', 'C_INCLUDE_PATH', 'CPLUS_INCLUDE_PATH'):
            if os.environ.get(key) and not allow_external:
                raise ValueError(f'Portable 检测到宿主编译环境变量 {key}={os.environ[key]}；'
                                 '请清除它或明确选择 allow_external_toolchain')

    # The generator adds target, object, depfile and TryCompile directories
    # after -B is selected. Even a short physical root can exhaust Win32's
    # budget. Keep CMake's entire owned build on one compact tool-side path.
    source_spelling = str(root)
    source_alias = os.name == 'nt' and (not source_spelling.isascii() or ' ' in source_spelling
                                      or len(source_spelling) > 120)
    build_alias = os.name == 'nt' and (owned or bool(bundle_root())
                                      or not str(build).isascii() or len(str(build)) > 120)
    source_path = build_path(root, prefer_junction=True) if source_alias else source_spelling
    build_command_path = build_path(build, prefer_junction=True) if build_alias else str(build)
    if source_path != str(root) or build_command_path != str(build):
        progress(f'CMake Windows 路径别名（同一目录）：{root} -> {source_path}；{build} -> {build_command_path}')
    command = [cmake, '-S', source_path, '-B', build_command_path, '-G', generator]
    command += ['-DCMAKE_BUILD_TYPE=' + settings.get('build_type', 'Debug')]
    if settings.get('toolchain_file'):
        toolchain = resolved_path(root/settings['toolchain_file'])
        previous_toolchain = cache.get('CMAKE_TOOLCHAIN_FILE')
        same_toolchain = (filesystem_path(toolchain).is_file() and previous_toolchain
                          and cmake_toolchain_input(root, build, previous_toolchain) == toolchain)
        # Preserve CMake's initialized FILEPATH metadata on incremental runs.
        if not same_toolchain:
            toolchain_path = (str(Path(source_path)/toolchain.relative_to(root)) if source_alias and toolchain.is_relative_to(root)
                              else build_path(toolchain) if bundle_root() else str(toolchain))
            command += ['-DCMAKE_TOOLCHAIN_FILE=' + toolchain_path]
    command += args + ['-DCMAKE_EXPORT_COMPILE_COMMANDS=ON',
                       '-DCMAKE_EXPORT_PACKAGE_REGISTRY=OFF', '-DCMAKE_EXPORT_NO_PACKAGE_REGISTRY=ON']
    if make:
        command += ['-DCMAKE_MAKE_PROGRAM:FILEPATH=' + make]

    path_warning = False

    def invoke(argv, name):
        from .scan_stop import check_stop
        nonlocal path_warning
        check_stop()
        step = dict(stage=name, command=argv, exit_code=None)
        if name == 'build' and effective_target:
            step['target'] = effective_target
        records.append(step)
        try:
            proc = execute(argv, cwd=source_path, env=tool_environment(), timeout=settings.get('timeout_seconds', 600),
                           text=False, encoding=None, errors=None)
        except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
            log, raw_logs, _ = save_logs(out, name, getattr(exc, 'output', None), getattr(exc, 'stderr', None))
            step.update(log=str(log), raw_logs=raw_logs)
            message = f'CMake {name} '+('已中断' if isinstance(exc, KeyboardInterrupt) else '超时')+f'，停止扫描。日志: {log}'
            if isinstance(exc, KeyboardInterrupt):
                raise KeyboardInterrupt(message) from exc
            raise ValueError(message) from exc
        except OSError as exc:
            raise ValueError(f'CMake {name} 无法启动：{argv[0]}；工作目录：{source_path}。'
                             f'请检查工具和路径：{exc}') from exc
        log, raw_logs, message = save_logs(out, name, proc.stdout, proc.stderr)
        step.update(exit_code=proc.returncode, log=str(log), raw_logs=raw_logs)
        if name == 'configure':
            path_warning = (os.name == 'nt' and 'CMAKE_OBJECT_PATH_MAX' in message
                            and 'cannot be safely placed under this directory' in message)
        if proc.returncode:
            hint = ''
            if path_warning and 'opening dependency file' in message and 'No such file or directory' in message:
                hint = (f'\nCMake 报告对象路径超过生成器预算，编译器无法创建依赖文件。'
                        f'实际构建路径：{build_command_path}。请缩短别名所在路径或工程的构建子目录。')
            raise ValueError(f'CMake {name} 失败 (退出码 {proc.returncode})，停止扫描。日志: {log}'
                             + hint + '\n' + message[-6000:])
        check_stop()
    from .cmake_file_api import FileAPI, TargetGraph, latest_index, request
    from .input_snapshot import read_consumed_text, record_consumed_file, verify_consumed_files
    from .scan_stop import check_stop

    def index_stamp():
        path = latest_index(build)
        return (path, filesystem_path(path).stat().st_mtime_ns) if path is not None else None

    if try_auto:
        request(build, 'cmakeFiles-v1', 'codemodel-v2', 'toolchains-v1')
    elif configured_target:
        request(build, 'cmakeFiles-v1', 'codemodel-v2')
    elif protected:
        request(build, 'cmakeFiles-v1')
    previous_index = index_stamp() if resolve_target else None
    previous_db = disk_database.stat() if resolve_target and disk_database.is_file() else None
    progress('CMake 配置并刷新编译数据库…')
    invoke(command, 'configure')
    configure_step = records[-1]
    cache, _ = check_cache(build, root, generator, make, allow_external)
    cached_build = cache.get('CMAKE_CACHEFILE_DIR')
    if cached_build and resolved_path(cached_build) != build:
        raise ValueError(f'CMakeCache 构建目录身份不一致：{cached_build}，要求实际目录 {build}；请检查旧构建路径。')
    consumed = {}
    if resolve_target:
        current_index = index_stamp()
        if current_index is None or current_index == previous_index:
            raise ValueError('CMake configure 未刷新本轮 File API 索引；禁止使用旧目标证据')
        api = FileAPI(root, build, consumed, generator)
        graph = TargetGraph(api, variant)
        if configured_target:
            target = graph.named(configured_target)
    if not disk_database.is_file():
        raise ValueError(f'CMake 未生成 {database}，无法校验编译证据。本次未执行构建。')
    if previous_db is not None and previous_db.st_mtime_ns == disk_database.stat().st_mtime_ns:
        raise ValueError(f'CMake configure 未刷新 {database}；禁止使用旧编译数据库')

    def audit_database(entries=None):
        if bundle_root():
            for entry in read_json(disk_database) if entries is None else entries:
                raw = entry.get('arguments') or split_command(entry.get('command', ''))
                if not raw:
                    raise ValueError(f'空编译命令: {database}')
                count = 2 if Path(raw[0]).stem.lower() in {'ccache','sccache'} else 1
                for executable in raw[:count]:
                    audit_executable(executable, entry.get('directory', root), allow_external=allow_external)

    def read_ninja(target):
        ninja = make or cache.get('CMAKE_MAKE_PROGRAM')
        if not ninja:
            raise ValueError('指定 cmake.target 时无法确定实际 Ninja 程序')
        argv = [ninja, '-C', build_command_path, '-t', 'compdb-targets', '-x', target]
        check_stop()
        proc = execute(argv, cwd=source_path, env=tool_environment(), timeout=settings.get('timeout_seconds', 600))
        check_stop()
        if proc.returncode:
            raise ValueError('目标编译闭包读取失败；需要支持 compdb-targets 的 Ninja 和有效目标：'
                             + target + '\n' + proc.stderr[-4000:])
        try:
            raw = json.loads(proc.stdout)
            if not isinstance(raw, list) or any(not isinstance(row, dict) or
                    not all(isinstance(row.get(k), str) and row[k] for k in ('directory', 'file', 'command', 'output'))
                    for row in raw):
                raise ValueError('无效目标编译数据库')
            compiler_rows = []
            for row in raw:
                arguments = split_command(row['command'])
                if '-c' not in arguments:
                    continue
                if source_language(row['file'], arguments) is None:
                    raise ValueError('目标闭包含无法识别的编译语言: ' + row['file'])
                compiler_rows.append(row)
            if not compiler_rows:
                raise ValueError('目标没有可解析编译单元')
            return compiler_rows, raw, argv
        except (ValueError, TypeError) as exc:
            raise ValueError('目标编译闭包无效，禁止回退混用全目标数据库：' + target) from exc

    rows, outputs, sources = [], set(), set()
    if resolve_target:
        from .cmake_auto_target import ninja_graph_evidence, select_firmware
        from .make_target import target_entries
        from .portable import resolved_executable

        api.inputs()
        full = json.loads(read_consumed_text(no_links(database), consumed))
        if not isinstance(full, list) or not full:
            raise ValueError('编译数据库必须是非空数组')
        if owned:
            record_consumed_file(no_links(build/OWNER_MARKER), consumed)
        if read_cache(build, consumed_inputs=consumed) != cache:
            raise ValueError('CMakeCache 在目标选择时改变')
        if generator == 'Ninja':
            ninja_graph_evidence(api)
        if not cache.get('CMAKE_MAKE_PROGRAM'):
            raise ValueError('CMakeCache 缺少当前生成器的构建工具')
        record_consumed_file(resolved_executable(cache['CMAKE_MAKE_PROGRAM'], build), consumed)

        def closure(target):
            if generator != 'Ninja':
                entries, files = target_entries(root, build, database, generator, target['name'], consumed,
                                                graph=graph, rows=full)
                return entries, files, None, None
            entries, rules, command = read_ninja(target['name'])
            files = {api.build_path(Path(row['directory'])/row['output']) for row in entries}
            artifacts = set(api.artifacts(target))
            native_outputs = {api.build_path(Path(row['directory'])/row['output']) for row in rules}
            if artifacts - native_outputs:
                raise ValueError(f'Ninja 入口与逻辑目标 {target["name"]} 的产物不一致：{min(artifacts - native_outputs)}')
            files.update(artifacts)
            return entries, files, rules, command

        if configured_target:
            rows, outputs, ninja_raw, argv = closure(target)
            reason = '精确匹配当前配置的 CMake 逻辑目标'
        else:
            effective_target, rows, outputs, ninja_raw, argv, artifact, reason = select_firmware(
                graph, analysis, generator, full, closure, selection['candidates'], execute)
            selection['artifact'] = str(artifact)
            for candidate in selection['candidates']:
                if not candidate['eligible']:
                    progress(f'CMake 跳过候选 {candidate["target"]}：{candidate["reason"]}')
        sources = {resolved_path(Path(row['directory'])/row['file']) for row in rows}
        for source in sources:
            if not source.is_relative_to(build):
                record_consumed_file(source, consumed)
        step = dict(stage='target-closure', exit_code=0, target=effective_target,
                    compile_entries=len(rows), outputs=len(outputs))
        if argv is None:
            step['source'] = 'cmake-file-api+compile_commands'
        else:
            step['command'] = argv
        records.append(step)

    selection.update(effective_target=effective_target, reason=reason)
    configure_step['target_selection'] = selection
    if diagnostics is not None:
        diagnostics['target'] = effective_target
    progress(f'CMake 目标选择 [{selection["source"]}]：{effective_target or "沿用原构建计划"}；{reason}')
    if consumed:
        verify_consumed_files(consumed)
        if not protected:
            save_selection(root, build, selection, consumed, api.index)
    audit_database(rows if resolve_target else None)
    if settings.get('build', True) and build_firmware:
        command = [cmake, '--build', build_command_path, '--config', variant]
        if resolve_target:
            if not effective_target:
                raise ValueError('固件构建缺少已解析的 CMake 目标')
            command.extend(['--target', effective_target])
        command.extend(build_args)
        progress('CMake 实际构建命令：' + subprocess.list2cmdline(command))
        invoke(command, 'build')
        if effective_target:
            verify_consumed_files(consumed)
            if latest_index(build) != api.index:
                raise ValueError('构建期间 CMake File API 索引改变；请重新扫描')
            if generator == 'Ninja' and read_ninja(effective_target)[1] != ninja_raw:
                raise ValueError('构建期间目标编译闭包改变；禁止复用配置前的数据库，请重新扫描')
            for path in sorted(outputs | sources):
                if not filesystem_path(path).is_file():
                    raise ValueError(f'CMake 目标 {effective_target} 构建后缺少实际编译输入或对象: {path}')
            for path in api.artifacts(graph.named(effective_target)):
                record_consumed_file(path, consumed)

    if consumed:
        consumed.pop(str(api.index))
        configure_step['consumed_inputs'] = consumed
    if effective_target:
        database = build/'ecra-target-compile_commands.json'
        write_json(filesystem_path(no_links(database)), rows)
        step['database'] = str(database)
    return database, records


def _include_probe_encodings():
    encodings = ['utf-8']
    if os.name == 'nt':
        import ctypes
        import codecs
        encoding = 'cp' + str(ctypes.windll.kernel32.GetACP())
        if codecs.lookup(encoding).name != codecs.lookup('utf-8').name:
            encodings.append(encoding)
    return encodings


def _include_probe_diagnostic(stderr):
    if isinstance(stderr, str):
        return stderr[-2000:]
    variants = []
    seen = set()
    for encoding in _include_probe_encodings():
        try:
            text = stderr.decode(encoding, errors='strict')
        except UnicodeDecodeError:
            continue
        if text not in seen:
            seen.add(text)
            variants.append('[' + encoding + ']\n' + text[-2000:])
    return '\n'.join(variants) if variants else '无法严格解码输出；原始stderr字节(hex)：' + stderr[-1000:].hex(' ')


def _include_probe_paths(stderr, directory):
    start = '#include <...> search starts here:'
    end = 'End of search list.'
    capture = complete = False
    paths = []
    encodings = _include_probe_encodings()
    for line in stderr.splitlines():
        marker = line.strip()
        if marker == (start.encode('ascii') if isinstance(line, bytes) else start):
            capture = True
        elif marker == (end.encode('ascii') if isinstance(line, bytes) else end):
            if capture:
                complete = True
            capture = False
        elif capture and marker:
            texts = []
            if isinstance(marker, str):
                texts.append(marker)
            else:
                for encoding in encodings:
                    try:
                        texts.append(marker.decode(encoding, errors='strict'))
                    except UnicodeDecodeError:
                        continue
            existing = {}
            for text in texts:
                try:
                    path = (Path(directory) / text).resolve()
                    if path.is_dir():
                        existing[os.path.normcase(str(path))] = str(path)
                except (OSError, ValueError, RuntimeError):
                    continue
            if len(existing) > 1:
                raise ValueError('头文件路径编码有歧义，存在不同的实际目录：' + '；'.join(existing.values()))
            if not existing:
                raise ValueError('无法无损恢复GCC报告的头文件目录：' + repr(marker))
            paths.append(next(iter(existing.values())))
    if not complete or capture:
        raise ValueError('GCC输出缺少完整的标准头搜索列表')
    return list(dict.fromkeys(paths))


def system_includes(unit):
    """Ask the actual Arm GCC for its search path; never evaluate a shell line."""
    raw = unit['original_arguments']
    compiler_index = 1 if Path(raw[0]).stem.lower() in {'ccache', 'sccache'} else 0
    compiler = raw[compiler_index]
    if Path(compiler).stem.lower() not in {'arm-none-eabi-gcc', 'arm-none-eabi-g++'}:
        return []
    executable = shutil.which(compiler, path=tool_environment().get('PATH')) or str((Path(unit['directory']) / compiler).resolve())
    if not Path(executable).is_file():
        raise ValueError(f'找不到 Arm GCC 以探测标准头文件: {compiler}；修正 PATH 或关闭 auto_system_includes 并填写 extra_args')
    sysroot = []
    args = unit['arguments']
    for i, arg in enumerate(args):
        if arg.startswith(('--sysroot=', '-mcpu=', '-march=', '-mfpu=', '-mfloat-abi=', '-mabi=')) or arg in {'-mthumb', '-marm'}:
            sysroot.append(arg)
        elif arg in {'--sysroot', '-isysroot'} and i+1 < len(args):
            sysroot.extend([arg, args[i+1]])
    language = system_include_language(unit)
    proc = execute([executable, *sysroot, '-E', '-x', language, '-v', '-'], stdin=subprocess.DEVNULL,
                   cwd=unit['directory'], env=dict(tool_environment(), LC_ALL='C'), timeout=20,
                   text=False, encoding=None, errors=None)
    try:
        if proc.returncode:
            raise ValueError('编译器退出码：' + str(proc.returncode))
        paths = _include_probe_paths(proc.stderr, unit['directory'])
        if not paths:
            raise ValueError('标准头搜索列表为空')
    except ValueError as exc:
        raise ValueError(f'Arm GCC 标准头文件探测失败: {compiler}\n{exc}\n{_include_probe_diagnostic(proc.stderr)}') from exc
    return paths


def system_include_language(unit):
    return 'c++' if source_language(unit.get('source', ''), unit['arguments']) == 'c++' else 'c'


def system_include_args(paths):
    """Prefer C-runtime/Clang-compatible headers to GCC's private intrinsics.

    GCC's stdatomic.h uses GCC-specific handling of _Atomic. Keep its private
    directory only as a fallback (e.g. for stddef.h in minimal libclang wheels).
    Explicit user -I/-isystem settings are not changed.
    """
    args = []
    for folder in paths:
        private = (Path(folder)/'stddef.h').is_file() and (Path(folder)/'stdarg.h').is_file()
        args.extend(['-idirafter' if private else '-isystem', folder])
    return args


def split_command(command):
    if os.name != "nt":
        return shlex.split(command)
    import ctypes
    from ctypes import wintypes
    api = ctypes.windll.shell32.CommandLineToArgvW
    api.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    api.restype = ctypes.POINTER(wintypes.LPWSTR)
    count = ctypes.c_int()
    ptr = api(command, ctypes.byref(count))
    if not ptr:
        raise ValueError("无法拆分编译命令，请使用 arguments 数组")
    try:
        return [ptr[i] for i in range(count.value)]
    finally:
        ctypes.windll.kernel32.LocalFree(ctypes.cast(ptr, ctypes.c_void_p))


def expand_response(args, directory, seen=None, files=None, consumed_inputs=None):
    seen = set() if seen is None else seen
    result = []
    for arg in args:
        if arg.startswith("@"):
            path = resolved_path(directory / arg[1:])
            if files is not None:
                files.add(str(path))
            if path in seen or len(seen) > 20:
                raise ValueError(f"响应文件循环/过深: {path}")
            # Windows gives argv[0] special quote rules; response files contain
            # options only, so supply a dummy executable before tokenizing.
            if consumed_inputs is None:
                content = filesystem_path(path).read_text(encoding="utf-8-sig")
            else:
                from .input_snapshot import read_consumed_text
                content = read_consumed_text(path, consumed_inputs)
            parsed = split_command("ecra-dummy " + content)[1:]
            result.extend(expand_response(parsed, directory, seen | {path}, files, consumed_inputs))
        else:
            result.append(arg)
    return result


def normalize(entry, root, analysis, consumed_inputs=None):
    directory = Path(entry.get("directory", root))
    if not directory.is_absolute():
        directory = root / directory
    directory = resolved_path(directory)
    source = resolved_path(directory / entry["file"])
    raw = entry.get("arguments") or split_command(entry.get("command", ""))
    if not raw or not isinstance(raw, list):
        raise ValueError(f"空编译命令: {source}")
    response_files = set()
    args = expand_response(raw, directory, files=response_files, consumed_inputs=consumed_inputs)
    if Path(args[0]).stem.lower() in {"ccache", "sccache"}:
        args = args[1:]
    compiler, args = args[0], args[1:]
    filtered, removed = normalize_clang_arguments(args, directory, source,
                                                   analysis.get('remove_args', []))
    extra = analysis.get("extra_args", [])
    inferred_target = None
    if "arm-none-eabi" in compiler.lower() and not any(a.startswith(("--target", "-target")) for a in filtered + extra):
        inferred_target = "arm-none-eabi"
        filtered.append("--target=arm-none-eabi")
    filtered.extend(extra)
    # Preserve command-line order: -U cancels a definition and a later -D
    # replaces it. NAME checks presence; NAME=value also checks the variant.
    defines = {}
    options = iter(filtered)
    for arg in options:
        if arg in {'-D', '-U'}:
            flag, value = arg, next(options, '')
        elif arg.startswith(('-D', '-U')):
            flag, value = arg[:2], arg[2:]
        else:
            continue
        name, sep, expansion = value.partition('=')
        if flag == '-U':
            defines.pop(name, None)
        elif name:
            defines[name] = expansion if sep else '1'
    missing = []
    for expected in analysis.get('expected_defines', []):
        name, sep, expansion = expected.partition('=')
        if name not in defines or (sep and defines[name] != expansion):
            missing.append(expected)
    return dict(source_file=relative(source, root), source=str(source), directory=str(directory),
                original_arguments=raw, arguments=filtered, removed_arguments=removed, response_files=sorted(response_files),
                inferred_target=inferred_target,
                missing_defines=sorted(set(missing)))


def normalize_clang_arguments(args, directory, source, remove_args=()):
    """Keep compile-time language/ABI inputs, discard other build-stage inputs.

    Paired options are consumed with their operands. Unknown switches remain
    visible to Clang: silently removing an unrecognized ABI option would be
    less safe than recording a partial parse with a diagnostic.
    """
    paired_drop = {'-o', '-MF', '-MT', '-MQ', '-MJ', '-Xlinker', '-Xassembler',
                   '-Wl', '-Wa', '--specs', '-u', '-T', '-L', '-l'}
    single_drop = {'-c', '-S', '-E', '-M', '-MM', '-MD', '-MMD', '-MP', '-MG',
                   '-nostartfiles', '-nodefaultlibs', '-nostdlib', '-shared',
                   '-static', '-s', '-Werror', '-pipe'}
    # These GCC ARM flags change code generation, not the preprocessor, ABI,
    # scalar width, or record layout used by libclang's AST.
    gcc_codegen = {'-mthumb-interwork', '-mlong-calls', '-mword-relocations'}
    joined_drop = ('-Wl,', '-Wa,', '-Xlinker=', '-Xassembler=',
                   '--specs=', '-Map=', '-mno-thumb-interwork')
    value_joined_drop = ('-o', '-MF', '-MT', '-MQ', '-MJ', '-u', '-T', '-L', '-l')
    filtered, removed = [], []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg in paired_drop or arg in remove_args:
            # Project overrides may be either a standalone switch or a pair.
            # Only known paired categories consume the following operand.
            count = 2 if arg in paired_drop and index + 1 < len(args) else 1
            removed.extend(args[index:index + count])
            index += count
            continue
        if (arg.startswith('-flto=') and arg[6:].isascii() and arg[6:].isdecimal()
                and int(arg[6:]) > 0):
            # GCC's numeric suffix selects link-time parallel jobs. Clang
            # accepts plain LTO, not this job count. Preserve LTO and retain
            # the original option in the audit trail; no ABI/macro flag moves.
            removed.append(arg)
            filtered.append('-flto')
            index += 1
            continue
        if (arg in single_drop or arg in gcc_codegen or arg.startswith('-mapcs-')
                or arg.startswith(joined_drop) or arg.startswith('-Werror=')
                or any(arg.startswith(prefix) and len(arg) > len(prefix)
                       for prefix in value_joined_drop)
                or arg.startswith('-M')):
            removed.append(arg)
        elif not arg.startswith('-') and resolved_path(directory / arg) == source:
            removed.append(arg)
        else:
            filtered.append(arg)
        index += 1
    return filtered, removed


def excluded(path, patterns):
    return any(fnmatch.fnmatchcase(path, p) for p in patterns)


def discover_databases(root):
    """Find CubeIDE Debug/Release and nested CMake databases without choosing a variant."""
    found = set()
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in {'.git', '.ecra', 'node_modules', '__pycache__',
                                                '.venv', 'venv', 'snapshots'}]
        if 'compile_commands.json' in files:
            found.add((Path(base)/'compile_commands.json').resolve())
    return sorted(found)


def linked_input_filters(root, closure):
    return tuple(None if key not in closure else
                 {str(resolved_path(root/path)).casefold() for path in closure[key]}
                 for key in ('linked_sources', 'linked_objects'))


def linked_input_selected(source, directory, entry, args, filters, make_build=None):
    """Apply the same linked input interpretation to planning and extraction."""
    source_filter, object_filter = filters
    obj = entry.get('output')
    object_dir = make_build if obj and make_build is not None else directory
    if not obj and '-o' in args and args.index('-o') + 1 < len(args):
        obj = args[args.index('-o') + 1]
    return ((source_filter is None or str(resolved_path(source)).casefold() in source_filter)
            and (object_filter is None or (obj and str(resolved_path(Path(object_dir)/obj)).casefold() in object_filter)))


def prepare(root, cfg, progress=None, build_firmware=True, *, file_view=None, build_diagnostics=None):
    if file_view is not None and 'cmake' in cfg['analysis']:
        prepared=file_view.prepared_compilation()
        if prepared is None:raise ValueError('未提交CMake缺少已封存准备结果，禁止实时重构建')
        return prepared
    a = cfg["analysis"]
    progress = progress or (lambda message: None)
    from .workspace import context
    from .data_transfer import reject_retired_inputs
    active_data=context(root,a).workspace_root
    reject_retired_inputs(active_data,a)
    scope = AuditScope(root, a)
    configured = a.get("compile_database", "auto")
    candidates = []
    requested = None
    cmake_steps = []
    if 'cmake' in a:
        database, cmake_steps = configure_cmake(root, a, progress, build_firmware, project=cfg.get('project'),
                                                diagnostics=build_diagnostics)
        candidates = [database]
    elif configured != "auto":
        requested = (root / configured).resolve()
        if requested.is_file():
            candidates = [requested]
        elif not a.get("auto_configure_cmake", False):
            raise ValueError(f"编译数据库不存在: {requested}")
    else:
        candidates = discover_databases(root)
        # Keep explicit legacy .ecra build locations discoverable; recursive
        # search otherwise avoids report archives containing stale databases.
        for p in ('.ecra/cmake-build/compile_commands.json',
                  str(Path(a.get('cmake_build_dir', 'build'))/'compile_commands.json')):
            candidate = (root/p).resolve()
            if candidate.is_file() and candidate not in candidates:
                candidates.append(candidate)
        if len(candidates) > 1:
            raise ValueError("发现多个编译数据库，请显式设置 analysis.compile_database: " + ", ".join(map(str, candidates)))
    cmake_log = None
    if not candidates and a.get("auto_configure_cmake", False):
        legacy = dict(a, cmake=dict(build_dir=a.get('cmake_build_dir', 'build/ecra'),
            generator=a.get('cmake_generator', 'Ninja'), args=a.get('cmake_args', []), build=False))
        if a.get('cmake_toolchain_file'):
            legacy['cmake']['toolchain_file'] = a['cmake_toolchain_file']
        database, cmake_steps = configure_cmake(root, legacy, progress, False)
        candidates = [database]
    if not candidates:
        raise ValueError("没有 compile_commands.json；导出真实固件编译数据库，或开启 auto_configure_cmake")
    from .input_snapshot import read_consumed_text
    consumed_inputs = {path: row for step in cmake_steps for path, row in step.get('consumed_inputs', {}).items()}
    entries = json.loads(read_consumed_text(candidates[0], consumed_inputs))
    if not isinstance(entries, list) or not entries:
        raise ValueError("编译数据库必须是非空数组")
    units, ignored, assembly_sources = [], [], []
    from .managed_build_closure import resolve as resolve_managed_closure
    closure,closure_binding=resolve_managed_closure(root,a,Path(candidates[0]).parent,cmake_steps,consumed_inputs)
    filters = linked_input_filters(root, closure)
    include_cache = {}
    compiler_audit = []
    target_selection = next((step['target_selection'] for step in cmake_steps if 'target_selection' in step), None)
    make_target = (target_selection and target_selection['effective_target']
                   and a.get('cmake', {}).get('generator') == 'MinGW Makefiles')
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict) or not entry.get("file"):
            raise ValueError(f"无效编译条目 #{i}")
        unit = normalize(entry, root, a, consumed_inputs)
        reject_retired_inputs(active_data,dict(directory=unit['directory'],source=unit['source'],arguments=unit['original_arguments']))
        if cmake_steps:
            # The real database is produced by this version's managed build.
            # Canonical comparison may normalize this proven build root only;
            # extraction and cache keys retain the actual paths and bytes.
            unit['ecra_build_root'] = str(resolved_path(candidates[0].parent))
        if bundle_root():
            raw = unit['original_arguments']
            index = 1 if Path(raw[0]).stem.lower() in {'ccache', 'sccache'} else 0
            for compiler in raw[:index+1]:
                record = audit_executable(compiler, unit['directory'],
                    allow_external=a.get('allow_external_toolchain',
                                         a.get('cmake', {}).get('allow_external_toolchain', False)))
                if record not in compiler_audit:
                    compiler_audit.append(record)
        unit["tu_id"] = f"TU-{i:05d}"
        # A target's actual link inputs narrow a multi-target compile database.
        # Paths come from build evidence, never name/path heuristics.
        if not linked_input_selected(unit['source'], unit['directory'], entry, unit['original_arguments'],
                                     filters, candidates[0].parent if make_target else None):
            ignored.append(unit['source_file'])
            continue
        language = source_language(unit['source'], unit['arguments'])
        excluded_unit = excluded(unit['source_file'], a.get('exclude', []))
        if language == 'asm' and not excluded_unit:
            assembly_sources.append(unit['source_file'])
        if excluded_unit or language not in {'c', 'c++'}:
            ignored.append(unit["source_file"])
            if not excluded_unit and language is None and '-c' in unit['removed_arguments']:
                raise ValueError('编译数据库包含无法识别的编译语言: ' + unit['source_file'])
        else:
            if a.get('auto_system_includes', 'cmake' in a):
                # Keep sysroot and working-directory differences in the key.
                key = (unit['directory'], tuple(unit['original_arguments'][:2]),
                       system_include_language(unit),
                       tuple(x for x in unit['arguments'] if 'sysroot' in x or x == '-isysroot'
                             or x.startswith(('-mcpu=', '-march=', '-mfpu=', '-mfloat-abi=', '-mabi='))
                             or x in {'-mthumb', '-marm'}))
                # Arguments following a separated --sysroot are also relevant.
                for j, arg in enumerate(unit['arguments'][:-1]):
                    if arg in {'--sysroot', '-isysroot'}:
                        key += (unit['arguments'][j+1],)
                if key not in include_cache:
                    include_cache[key] = system_includes(unit)
                unit['system_include_dirs'] = include_cache[key]
                unit['arguments'].extend(system_include_args(unit['system_include_dirs']))
            unit['audit_role'] = 'target' if scope.contains(unit['source']) else 'dependency'
            units.append(unit)
    if not units:
        raise ValueError("所有编译单元均被排除")
    # Audit files outside the database instead of silently assuming they are unused.
    sources, excluded_sources = [], []
    output = results_path(root, a)
    walk = os.walk if file_view is None else file_view.walk
    for base, dirs, files in (row for tree in scope.walk_roots() for row in walk(tree)):
        dirs[:] = [d for d in dirs if d not in {".git", "__pycache__", "node_modules"}
                   and (Path(base) / d).resolve() != output]
        for name in files:
            p = Path(base) / name
            if source_language(p) in {'c', 'c++'}:
                rel = relative(p, root)
                # Unbuilt/out-of-scope vendor files are not missing user code.
                (excluded_sources if excluded(rel, a.get("exclude", [])) or not scope.contains(p) else sources).append(rel)
    covered = {u["source_file"] for u in units}
    compilation = dict(project_root=str(root), compile_database=str(candidates[0]), candidates=list(map(str, candidates)),
                       selection_reason='managed cmake' if 'cmake' in a else ("explicit" if configured != "auto" else "unique candidate"),
                       unlisted_sources=sorted(set(sources) - covered) if not a.get('build_closure_only', True) else [],
                       excluded_from_build=sorted(set(sources) - covered),
                       build_closure=dict(closure, source='linked_inputs' if any(f is not None for f in filters)
                           else 'compile_database', translation_units=sorted(covered),
                           complete=not bool(closure.get('missing_objects')), missing_objects=closure.get('missing_objects', [])),
                       assembly_sources=sorted(set(assembly_sources)),
                       excluded_sources=sorted(set(ignored + excluded_sources)), cmake_log=cmake_log, cmake_steps=cmake_steps,
                       dependency_sources=[u['source_file'] for u in units if u['audit_role']=='dependency'],
                       cmake_cache=read_cache(Path(candidates[0]).parent,consumed_inputs=consumed_inputs), compilers=compiler_audit,
                       external_tools=[c for c in compiler_audit if c['external']], consumed_inputs=consumed_inputs)
    if closure_binding is not None:compilation['build_closure_binding']=closure_binding
    if target_selection is not None:
        compilation['cmake_target_selection'] = target_selection
    return units,compilation
