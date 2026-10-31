"""Portable tool selection and diagnostics; no changes to analysis semantics."""
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
from importlib.metadata import version

from .common import execute


_BUILD_ALIASES = {}


def _short_path(path):
    import ctypes
    buf = ctypes.create_unicode_buffer(32768)
    size = ctypes.windll.kernel32.GetShortPathNameW(str(path), buf, len(buf))
    return buf.value if size and size < len(buf) else str(path)


def _junction(alias, target):
    """Create an unprivileged NTFS directory alias, without evaluating a shell."""
    import ctypes
    from ctypes import wintypes
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    api.CreateFileW.argtypes = [wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,
                               wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
    api.CreateFileW.restype = wintypes.HANDLE
    api.DeviceIoControl.argtypes = [wintypes.HANDLE,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,
        ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(wintypes.DWORD),ctypes.c_void_p]
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    alias.mkdir()
    handle = api.CreateFileW(str(alias),0x40000000,7,None,3,0x02200000,None)
    if handle == ctypes.c_void_p(-1).value:
        alias.rmdir()
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        import struct
        substitute = ('\\??\\' + str(target)).encode('utf-16-le')
        display = str(target).encode('utf-16-le')
        names = substitute + b'\0\0' + display + b'\0\0'
        data = struct.pack('<IHHHHHH',0xA0000003,8+len(names),0,0,len(substitute),
                           len(substitute)+2,len(display)) + names
        buffer = ctypes.create_string_buffer(data)
        returned = wintypes.DWORD()
        if not api.DeviceIoControl(handle,0x900A4,buffer,len(data),None,0,ctypes.byref(returned),None):
            raise ctypes.WinError(ctypes.get_last_error())
    except Exception:
        api.CloseHandle(handle)
        handle = None
        alias.rmdir() # only the just-created empty alias, never the target
        raise
    finally:
        if handle is not None:
            api.CloseHandle(handle)


def build_path(value, *, prefer_junction=False):
    """Same files under an ASCII spelling for Make 4.4.1's ANSI subprocess API.

    Prefer native 8.3 names. On volumes without them, keep a deterministic
    junction in the user's ASCII temp directory so CMakeCache/compile_commands
    paths remain valid on later commands. Existing unrelated paths are refused.
    """
    path = Path(value).absolute()
    compact = prefer_junction and (not str(path).isascii() or len(str(path)) > 180)
    if os.name != 'nt' or (str(path).isascii() and not compact):
        return str(path)
    for root, alias in sorted(_BUILD_ALIASES.items(), key=lambda item: len(str(item[0])), reverse=True):
        junction = (alias.exists() and bool(getattr(alias.lstat(), 'st_file_attributes', 0)
                                            & stat.FILE_ATTRIBUTE_REPARSE_POINT)) if compact else False
        if path.is_relative_to(root) and str(alias/path.relative_to(root)).isascii() and (not compact or junction):
            return str(alias/path.relative_to(root))
    # A tool-side workspace may contain a Chinese project name even when the
    # package directory itself is ASCII. Aliasing only the package left that
    # suffix unchanged and ARM ar/ranlib could fail in CMake's compiler probe.
    # Cover the nearest existing directory, including non-ASCII descendants.
    root = path if path.is_dir() else path.parent
    while not root.is_dir():
        root = root.parent
    root = root.resolve()
    alias = Path(_short_path(root))
    # CMake expands native 8.3 names back to long Unicode paths in Makefiles.
    # A virtual junction keeps deeply nested build/probe paths short as well.
    if compact or not str(alias).isascii():
        import hashlib
        import time
        parent = Path(tempfile.gettempdir())/'ECRA-paths'
        parent.mkdir(parents=True,exist_ok=True)
        parent = Path(_short_path(parent))
        if not str(parent).isascii():
            raise ValueError('GNU Make 4.4.1 需要 ASCII 兼容路径；请设置可写的 ASCII TEMP 目录或将工具/工程放入 ASCII 路径')
        alias = parent/hashlib.sha256(str(root).casefold().encode('utf-8')).hexdigest()[:32]
        try:
            if not os.path.lexists(alias):
                _junction(alias,root)
        except FileExistsError:
            pass # another ECRA process may have created the identical alias
        for attempt in range(5):
            if alias.resolve() == root:
                break
            if attempt == 4:
                raise ValueError(f'ASCII 路径别名冲突，拒绝覆盖: {alias}；要求指向 {root}')
            time.sleep(0.05)
    if alias.resolve() != root:
        raise ValueError(f'路径别名未指向原目录: {alias} -> {root}')
    _BUILD_ALIASES[root] = alias
    return str(alias/path.relative_to(root))


def bundle_root():
    value = os.environ.get('ECRA_PORTABLE_ROOT')
    root = Path(value).resolve() if value else Path(__file__).resolve().parent.parent
    return root if (root / 'portable-lock.json').is_file() else None


def tool_environment():
    """Build processes see bundled tools and Windows only; review keeps host PATH."""
    env = os.environ.copy()
    root = bundle_root()
    if root:
        windows = Path(env.get('SystemRoot', r'C:\Windows'))
        paths = [root/'runtime', root/'tools/cmake/bin', root/'tools/ninja',
                 root/'tools/mingw/bin', root/'tools/mingw/opt/bin', root/'tools/arm-gcc/bin',
                 windows/'System32', windows, windows/'System32/Wbem',
                 windows/'System32/WindowsPowerShell/v1.0']
        env['PATH'] = os.pathsep.join(build_path(p) for p in paths)
        env.pop('PYTHONHOME', None)
        env.pop('PYTHONPATH', None)
    return env


def tool_path(name):
    root = bundle_root()
    paths = {'cmake': 'cmake/bin/cmake.exe', 'ninja': 'ninja/ninja.exe',
             'mingw32-make': 'mingw/bin/mingw32-make.exe', 'gcc': 'mingw/bin/gcc.exe',
             'g++': 'mingw/bin/g++.exe', 'arm-none-eabi-gcc': 'arm-gcc/bin/arm-none-eabi-gcc.exe',
             'arm-none-eabi-g++': 'arm-gcc/bin/arm-none-eabi-g++.exe'}
    if root and name in paths:
        path = root/'tools'/paths[name]
        if not path.is_file():
            raise ValueError(f'Portable 缺少工具: {path}；重新生成完整包')
        return build_path(path)
    return shutil.which(name, path=tool_environment().get('PATH')) or name


def read_cache(build, *, consumed_inputs=None):
    result = {}
    def text(file):
        if consumed_inputs is None:
            return file.read_text(encoding='utf-8-sig',errors='replace')
        from .input_snapshot import read_consumed_text
        return read_consumed_text(file,consumed_inputs,errors='replace')
    path = Path(build)/'CMakeCache.txt'
    if path.is_file():
        for line in text(path).splitlines():
            if line.startswith(('#', '//')) or '=' not in line or ':' not in line.split('=', 1)[0]:
                continue
            key, value = line.split('=', 1)
            result[key.split(':', 1)[0]] = value
        # Toolchain files may set compilers as ordinary CMake variables, so
        # CMakeCache alone does not necessarily contain them. Read CMake's
        # generated literal compiler metadata; never execute project CMake code.
        import re
        version_dir = '.'.join(result.get('CMAKE_CACHE_' + part + '_VERSION', '')
                               for part in ('MAJOR','MINOR','PATCH'))
        if re.fullmatch(r'\d+\.\d+\.\d+', version_dir):
            for file in sorted((Path(build)/'CMakeFiles'/version_dir).glob('CMake*Compiler.cmake')):
                for line in text(file).splitlines():
                    match = re.fullmatch(r'set\((CMAKE_(?:C|CXX|ASM)_COMPILER(?:_VERSION)?) "([^"]*)"\)',line.strip())
                    if match:
                        result.setdefault(match[1],match[2])
    return result


def resolved_executable(value, cwd, env=None):
    path = Path(value)
    if path.is_absolute():
        return path.resolve()
    return Path(shutil.which(value, path=(env or tool_environment()).get('PATH')) or (Path(cwd)/path)).resolve()


def audit_executable(value, cwd, *, allow_external=False):
    path = resolved_executable(value, cwd)
    root = bundle_root()
    external = bool(root and not path.is_relative_to(root))
    if external and not allow_external:
        raise ValueError(f'检测到 Portable 外部工具路径: {path}。未替换编译器或编译参数；'
                         '请修正工程工具链/旧缓存，或明确设置 analysis.allow_external_toolchain: true'
                         '（兼容 analysis.cmake.allow_external_toolchain）')
    if root and not path.is_file():
        raise ValueError(f'工具路径不存在: {path}')
    return dict(path=str(path), external=external)


def check_cache(build, root, generator, make=None, allow_external=False):
    cache = read_cache(build)
    if cache.get('CMAKE_GENERATOR', generator) != generator:
        raise ValueError(f'CMakeCache Generator 冲突: {build}: {cache["CMAKE_GENERATOR"]} != {generator}；'
                         '请选择新的 ECRA 专用 build_dir，不删除正式构建目录')
    if cache.get('CMAKE_HOME_DIRECTORY') and Path(cache['CMAKE_HOME_DIRECTORY']).resolve() != root.resolve():
        raise ValueError(f'CMakeCache 属于另一工程: {build}: {cache["CMAKE_HOME_DIRECTORY"]}')
    if make and cache.get('CMAKE_MAKE_PROGRAM'):
        actual = resolved_executable(cache['CMAKE_MAKE_PROGRAM'], root)
        if actual != Path(make).resolve():
            raise ValueError(f'CMakeCache CMAKE_MAKE_PROGRAM 冲突/旧电脑路径: {actual}；'
                             f'要求 {make}。请选择新的 ECRA 专用 build_dir')
    tools = {}
    for key in ('CMAKE_C_COMPILER', 'CMAKE_CXX_COMPILER', 'CMAKE_ASM_COMPILER',
                'CMAKE_AR', 'CMAKE_RANLIB', 'CMAKE_LINKER'):
        if cache.get(key) and not cache[key].endswith('-NOTFOUND'):
            tools[key] = audit_executable(cache[key], root, allow_external=allow_external)
    return cache, tools


def probe_tool(name, expected=None):
    path = tool_path(name)
    proc = execute([path, '--version'], env=tool_environment(), timeout=20)
    text = (proc.stdout + proc.stderr).strip()
    result = dict(path=path, canonical_path=str(Path(path).resolve()), version=text.splitlines()[0] if text else '', running=proc.returncode == 0)
    if expected:
        import re
        result['required'] = expected
        result['matching'] = bool(proc.returncode == 0 and re.search(expected, text))
    return result


def diagnostics(libclang_file=None):
    """Actual version probes, even if project configuration subsequently fails."""
    root = bundle_root()
    lock = json.loads((root/'portable-lock.json').read_text(encoding='utf-8-sig')) if root else {}
    required = lock.get('version_patterns', {})
    tools = {'python': dict(path=sys.executable, version=sys.version.split()[0], running=True,
                           matching=not root or sys.version.split()[0] == lock['versions']['python'])}
    for name in ('cmake', 'ninja', 'gcc', 'g++', 'mingw32-make', 'arm-none-eabi-gcc'):
        try:
            tools[name] = probe_tool(name, required.get(name))
        except (OSError, ValueError) as exc:
            tools[name] = dict(running=False, matching=False, error=str(exc))
    for package, module in (('PyYAML', 'yaml'), ('libclang', 'clang.cindex')):
        try:
            import importlib
            loaded = importlib.import_module(module)
            if package == 'libclang':
                if libclang_file and not loaded.Config.loaded:
                    loaded.Config.set_library_file(libclang_file)
                loaded.Index.create()
            tools[package] = dict(version=version(package), loaded=True, path=loaded.__file__,
                                  matching=not root or version(package) == lock['dependencies'][package])
            if package == 'libclang':
                tools[package]['library'] = str(loaded.conf.lib._name)
        except Exception as exc:
            tools[package] = dict(loaded=False, matching=False, error=str(exc))
    return dict(portable_root=str(root) if root else None, tools=tools,
                acceptance=dict(portable_runtime='PASS' if all(tools[k].get('matching', True) for k in
                    ('python','PyYAML','libclang')) else 'FAIL', cmake_configure='NOT_RUN',
                    cmake_build='NOT_RUN', arm_cross_compile='NOT_RUN', static_scan='NOT_RUN',
                    opencode_review='NOT_TESTED'))
