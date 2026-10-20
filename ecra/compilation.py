import fnmatch
import os
import shlex
import shutil
import subprocess
import time
import stat
from pathlib import Path

from .common import execute, read_json, relative
from .scope import AuditScope
from .portable import (bundle_root, tool_path, tool_environment, check_cache, read_cache,
                       audit_executable, probe_tool, build_path)


def configure_cmake(root, analysis, progress, build_firmware):
    """Managed CMake mode refreshes the database on every run, even if present."""
    settings = analysis['cmake']
    requested_build = root / settings.get('build_dir', 'build/ecra')
    for item in (requested_build, *requested_build.parents):
        if item.exists() and (item.is_symlink() or getattr(item.lstat(), 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise ValueError(f'拒绝使用含链接的构建路径: {item}')
        if item == root:
            break
    build = requested_build.resolve()
    if build == root.resolve() or not build.is_relative_to(root.resolve()):
        raise ValueError('analysis.cmake.build_dir 必须是工程根目录下的独立构建目录')
    database = build / 'compile_commands.json'
    requested = analysis.get('compile_database', 'auto')
    if requested != 'auto' and (root/requested).resolve() != database:
        raise ValueError(f'analysis.compile_database 与 cmake.build_dir 不匹配；应为 {database}')
    out = (root / analysis.get('output_dir', '.ecra')).resolve()
    if out == build or out.is_relative_to(build):
        raise ValueError(f'构建目录不可包含 ECRA 输出目录: {build} / {out}')
    out.mkdir(parents=True, exist_ok=True)
    generator = settings.get('generator', 'Ninja')
    if generator not in {'Ninja', 'MinGW Makefiles', 'Unix Makefiles'}:
        raise ValueError(f'不支持导出编译数据库的 Generator: {generator}')
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
    source_path = build_path(root) if bundle_root() else str(root)
    build_command_path = build_path(build) if bundle_root() else str(build)
    if source_path != str(root) or build_command_path != str(build):
        progress(f'GNU Make 路径兼容别名（同一目录）: {root} -> {source_path}; {build} -> {build_command_path}')
    command = [cmake, '-S', source_path, '-B', build_command_path, '-G', generator]
    command += ['-DCMAKE_BUILD_TYPE=' + settings.get('build_type', 'Debug')]
    if settings.get('toolchain_file'):
        toolchain = (root/settings['toolchain_file']).resolve()
        command += ['-DCMAKE_TOOLCHAIN_FILE=' + (build_path(toolchain) if bundle_root() else str(toolchain))]
    args = settings.get('args', [])
    if any(x in {'-S', '-B', '-G', '--preset', '--build', '--install'} or x.startswith(('-S', '-B', '-G', '--preset=')) for x in args):
        raise ValueError('cmake.args 不可覆盖源码/构建目录或生成器；请使用对应配置字段')
    command += args + ['-DCMAKE_EXPORT_COMPILE_COMMANDS=ON']
    if make:
        if any('CMAKE_MAKE_PROGRAM' in arg for arg in args):
            raise ValueError('Portable 的 CMAKE_MAKE_PROGRAM 由 Generator 选择；不可用 cmake.args 覆盖')
        command += ['-DCMAKE_MAKE_PROGRAM:FILEPATH=' + make]
    records = []

    allow_external = settings.get('allow_external_toolchain', False)
    marker = build / '.ecra-build-owner'
    owner = str(root.resolve())
    # Only ECRA-owned directories may be recursively removed. Existing formal
    # build trees are usable incrementally, but never adopted for deletion.
    if build.is_symlink() or (hasattr(build, 'is_junction') and build.is_junction()):
        raise ValueError(f'拒绝清理链接构建目录: {build}')
    if not build.exists() or not any(build.iterdir()):
        build.mkdir(parents=True, exist_ok=True)
        marker.write_text(owner, encoding='utf-8')

    if settings.get('clean_before_configure', False) and build_firmware and build.exists():
        progress('清理 CMake 构建目录…')
        previous_cache = read_cache(build)
        if not marker.is_file() or marker.read_text(encoding='utf-8') != owner:
            raise ValueError(f'拒绝清理非 ECRA 专用构建目录: {build}；请选择新的 build/ecra 目录')
        for item in build.rglob('*'):
            if item.is_symlink() or (hasattr(item, 'is_junction') and item.is_junction()):
                raise ValueError(f'拒绝清理含链接的目录: {item}')
        for attempt in range(5):
            try:
                shutil.rmtree(build)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.1 * 2**attempt)
        build.mkdir()
        marker.write_text(owner, encoding='utf-8')
        records.append(dict(stage='clean', command=['remove-directory', str(build)], exit_code=0,
                            previous_cache=previous_cache))

    check_cache(build, root, generator, make, allow_external)
    if bundle_root():
        for key in ('CC', 'CXX', 'ASM'):
            if os.environ.get(key):
                audit_executable(os.environ[key], root, allow_external=allow_external)
        for key in ('GCC_EXEC_PREFIX', 'COMPILER_PATH', 'LIBRARY_PATH', 'CPATH', 'C_INCLUDE_PATH', 'CPLUS_INCLUDE_PATH'):
            if os.environ.get(key) and not allow_external:
                raise ValueError(f'Portable 检测到宿主编译环境变量 {key}={os.environ[key]}；'
                                 '请清除它或明确选择 allow_external_toolchain')

    def invoke(argv, name):
        progress('CMake ' + ('配置并刷新编译数据库…' if name == 'configure' else '增量构建固件…'))
        proc = execute(argv, cwd=root, env=tool_environment(), timeout=settings.get('timeout_seconds', 600))
        log = out / ('cmake-' + name + '.log')
        log.write_text(proc.stdout + proc.stderr, encoding='utf-8')
        records.append(dict(stage=name, command=argv, exit_code=proc.returncode, log=str(log)))
        if proc.returncode:
            raise ValueError(f'CMake {name} 失败，停止扫描。日志: {log}\n' + (proc.stdout+proc.stderr)[-6000:])
    invoke(command, 'configure')
    check_cache(build, root, generator, make, allow_external)
    if not database.is_file():
        raise ValueError(f'CMake 未生成 {database}；请使用 Ninja 或 Makefiles 生成器')
    if bundle_root():
        for entry in read_json(database):
            raw = entry.get('arguments') or split_command(entry.get('command', ''))
            if not raw:
                raise ValueError(f'空编译命令: {database}')
            count = 2 if Path(raw[0]).stem.lower() in {'ccache','sccache'} else 1
            for executable in raw[:count]:
                audit_executable(executable, entry.get('directory', root), allow_external=allow_external)
    if settings.get('build', True) and build_firmware:
        invoke([cmake, '--build', build_command_path, '--config', settings.get('build_type', 'Debug'),
                *settings.get('build_args', [])], 'build')
    return database, records


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
        if arg.startswith('--sysroot='):
            sysroot.append(arg)
        elif arg in {'--sysroot', '-isysroot'} and i+1 < len(args):
            sysroot.extend([arg, args[i+1]])
    proc = execute([executable, *sysroot, '-E', '-x', 'c', '-v', '-'], stdin=subprocess.DEVNULL,
                   cwd=unit['directory'], env=dict(tool_environment(), LC_ALL='C'), timeout=20)
    paths, capture = [], False
    for line in proc.stderr.splitlines():
        if '#include <...> search starts here:' in line:
            capture = True
        elif 'End of search list.' in line:
            capture = False
        elif capture:
            p = (Path(unit['directory']) / line.strip()).resolve()
            if p.is_dir():
                paths.append(str(p))
    if proc.returncode or not paths:
        raise ValueError(f'Arm GCC 标准头文件探测失败: {compiler}\n{proc.stderr[-2000:]}')
    return list(dict.fromkeys(paths))


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


def expand_response(args, directory, seen=None, files=None):
    seen = set() if seen is None else seen
    result = []
    for arg in args:
        if arg.startswith("@"):
            path = (directory / arg[1:]).resolve()
            if files is not None:
                files.add(str(path))
            if path in seen or len(seen) > 20:
                raise ValueError(f"响应文件循环/过深: {path}")
            # Windows gives argv[0] special quote rules; response files contain
            # options only, so supply a dummy executable before tokenizing.
            content = path.read_text(encoding="utf-8-sig")
            parsed = split_command("ecra-dummy " + content)[1:]
            result.extend(expand_response(parsed, directory, seen | {path}, files))
        else:
            result.append(arg)
    return result


def normalize(entry, root, analysis):
    directory = Path(entry.get("directory", root))
    if not directory.is_absolute():
        directory = root / directory
    directory = directory.resolve()
    source = (directory / entry["file"]).resolve()
    raw = entry.get("arguments") or split_command(entry.get("command", ""))
    if not raw or not isinstance(raw, list):
        raise ValueError(f"空编译命令: {source}")
    response_files = set()
    args = expand_response(raw, directory, files=response_files)
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
        if (arg in single_drop or arg in gcc_codegen or arg.startswith('-mapcs-')
                or arg.startswith(joined_drop) or arg.startswith('-Werror=')
                or any(arg.startswith(prefix) and len(arg) > len(prefix)
                       for prefix in value_joined_drop)
                or arg.startswith('-M')):
            removed.append(arg)
        elif not arg.startswith('-') and (directory / arg).resolve() == source:
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


def prepare(root, cfg, progress=None, build_firmware=True):
    a = cfg["analysis"]
    progress = progress or (lambda message: None)
    scope = AuditScope(root, a)
    configured = a.get("compile_database", "auto")
    candidates = []
    requested = None
    cmake_steps = []
    if 'cmake' in a:
        database, cmake_steps = configure_cmake(root, a, progress, build_firmware)
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
        if bundle_root():
            legacy = dict(a, cmake=dict(build_dir=a.get('cmake_build_dir', 'build/ecra'),
                generator=a.get('cmake_generator', 'Ninja'), args=a.get('cmake_args', []), build=False))
            if a.get('cmake_toolchain_file'):
                legacy['cmake']['toolchain_file'] = a['cmake_toolchain_file']
            database, cmake_steps = configure_cmake(root, legacy, progress, False)
            candidates = [database]
    if not candidates and a.get("auto_configure_cmake", False):
        build = root / a.get("cmake_build_dir", "build")
        generated = (build / 'compile_commands.json').resolve()
        if requested is not None and requested != generated:
            raise ValueError(f"analysis.compile_database 与 cmake_build_dir 不匹配：CMake 将生成 {generated}，配置却指定 {requested}")
        cmd = ["cmake", "-S", str(root), "-B", str(build), "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON"]
        if a.get("cmake_generator"):
            cmd += ["-G", a["cmake_generator"]]
        if a.get("cmake_toolchain_file"):
            cmd.append("-DCMAKE_TOOLCHAIN_FILE=" + str((root / a["cmake_toolchain_file"]).resolve()))
        cmd += a.get("cmake_args", [])
        proc = execute(cmd, cwd=root, timeout=300)
        cmake_log = proc.stdout + proc.stderr
        if proc.returncode:
            raise ValueError("CMake 配置失败:\n" + cmake_log[-6000:])
        if not generated.is_file():
            raise ValueError(f"CMake 配置成功但未生成 {generated}；请使用 Ninja 或 Makefiles 生成器并启用 CMAKE_EXPORT_COMPILE_COMMANDS")
        candidates = [generated]
    if not candidates:
        raise ValueError("没有 compile_commands.json；导出真实固件编译数据库，或开启 auto_configure_cmake")
    entries = read_json(candidates[0])
    if not isinstance(entries, list) or not entries:
        raise ValueError("编译数据库必须是非空数组")
    units, ignored, assembly_sources = [], [], []
    closure = a.get('build_closure', {})
    linked_sources = closure.get('linked_sources')
    linked_objects = closure.get('linked_objects')
    def absolute(value, directory=root):
        return str((Path(directory) / value).resolve()).casefold()
    source_filter = {absolute(p) for p in linked_sources} if linked_sources is not None else None
    object_filter = {absolute(p) for p in linked_objects} if linked_objects is not None else None
    include_cache = {}
    compiler_audit = []
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict) or not entry.get("file"):
            raise ValueError(f"无效编译条目 #{i}")
        unit = normalize(entry, root, a)
        if bundle_root():
            raw = unit['original_arguments']
            index = 1 if Path(raw[0]).stem.lower() in {'ccache', 'sccache'} else 0
            for compiler in raw[:index+1]:
                record = audit_executable(compiler, unit['directory'],
                    allow_external=a.get('cmake', {}).get('allow_external_toolchain', False))
                if record not in compiler_audit:
                    compiler_audit.append(record)
        unit["tu_id"] = f"TU-{i:05d}"
        # A target's actual link inputs narrow a multi-target compile database.
        # Paths come from build evidence, never name/path heuristics.
        args = unit['original_arguments']
        obj = entry.get('output')
        if not obj and '-o' in args and args.index('-o') + 1 < len(args):
            obj = args[args.index('-o') + 1]
        if ((source_filter is not None and absolute(unit['source']) not in source_filter)
                or (object_filter is not None and (not obj or absolute(obj, unit['directory']) not in object_filter))):
            ignored.append(unit['source_file'])
            continue
        if Path(unit['source']).suffix.lower() == '.s' and not excluded(unit['source_file'], a.get('exclude', [])):
            assembly_sources.append(unit['source_file'])
        if excluded(unit["source_file"], a.get("exclude", [])) or Path(unit['source']).suffix.lower() not in {'.c', '.cc', '.cpp', '.cxx'}:
            ignored.append(unit["source_file"])
        else:
            if a.get('auto_system_includes', 'cmake' in a):
                # Keep sysroot and working-directory differences in the key.
                key = (unit['directory'], tuple(unit['original_arguments'][:2]),
                       tuple(x for x in unit['arguments'] if 'sysroot' in x or x == '-isysroot'))
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
    output = (root / a.get("output_dir", ".ecra")).resolve()
    for base, dirs, files in (row for tree in scope.walk_roots() for row in os.walk(tree)):
        dirs[:] = [d for d in dirs if d not in {".git", "__pycache__", "node_modules"}
                   and (Path(base) / d).resolve() != output]
        for name in files:
            p = Path(base) / name
            if p.suffix.lower() in {".c", ".cc", ".cpp", ".cxx"}:
                rel = relative(p, root)
                # Unbuilt/out-of-scope vendor files are not missing user code.
                (excluded_sources if excluded(rel, a.get("exclude", [])) or not scope.contains(p) else sources).append(rel)
    covered = {u["source_file"] for u in units}
    return units, dict(project_root=str(root), compile_database=str(candidates[0]), candidates=list(map(str, candidates)),
                       selection_reason='managed cmake' if 'cmake' in a else ("explicit" if configured != "auto" else "unique candidate"),
                       unlisted_sources=sorted(set(sources) - covered) if not a.get('build_closure_only', True) else [],
                       excluded_from_build=sorted(set(sources) - covered),
                       build_closure=dict(closure, source='linked_inputs' if source_filter is not None or object_filter is not None
                           else 'compile_database', translation_units=sorted(covered),
                           complete=not bool(closure.get('missing_objects')), missing_objects=closure.get('missing_objects', [])),
                       assembly_sources=sorted(set(assembly_sources)),
                       excluded_sources=sorted(set(ignored + excluded_sources)), cmake_log=cmake_log, cmake_steps=cmake_steps,
                       dependency_sources=[u['source_file'] for u in units if u['audit_role']=='dependency'],
                       cmake_cache=read_cache(Path(candidates[0]).parent), compilers=compiler_audit,
                       external_tools=[c for c in compiler_audit if c['external']])
