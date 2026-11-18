"""Portable tool selection and diagnostics; no changes to analysis semantics."""
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
from importlib.metadata import version

from .common import execute
from .path_io import filesystem_path, lstat_if_present, resolved_path


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


def _is_junction(path):
    return getattr(lstat_if_present(path), 'st_reparse_tag', None) == stat.IO_REPARSE_TAG_MOUNT_POINT


def default_alias_root():
    from .workspace import managed_path, managed_root
    return managed_path(managed_root()/'a')


def alias_root():
    from .workspace import managed_path
    root = default_alias_root()
    override = os.environ.get('ECRA_PATH_ALIAS_ROOT')
    if not override:
        return root
    value = managed_path(override, label='ECRA_PATH_ALIAS_ROOT')
    if not value.is_relative_to(root):
        raise ValueError(f'ECRA_PATH_ALIAS_ROOT 必须位于 {root}: {value}')
    return value


def build_path(value, *, prefer_junction=False):
    """Same files under an ASCII spelling for Make 4.4.1's ANSI subprocess API.

    Prefer native 8.3 names. On volumes without them, keep a deterministic
    junction in a bounded user-owned ASCII directory so CMakeCache/compile_commands
    paths remain valid on later commands. Existing unrelated paths are refused.
    """
    path = Path(value).absolute()
    # CMake's TryCompile/object suffixes can add >100 characters. Waiting
    # until the build root itself exceeds 180 leaves normal ASCII workspaces
    # beyond Make's path limit. A requested build alias is always compact.
    compact = prefer_junction
    if os.name != 'nt' or (str(path).isascii() and not compact):
        return str(path)
    for root, alias in sorted(_BUILD_ALIASES.items(), key=lambda item: len(str(item[0])), reverse=True):
        # Compact build paths have one deterministic alias per exact directory.
        # Reusing an ancestor would make CMake's cache/database spelling depend
        # on which directories happened to be registered earlier in this run.
        if compact and root != path:
            continue
        if (path.is_relative_to(root) and str(alias/path.relative_to(root)).isascii()
                and (not compact or _is_junction(alias))):
            if resolved_path(alias) != root:
                raise ValueError(f'路径别名未指向原目录: {alias} -> {root}')
            return str(alias/path.relative_to(root))
    # A tool-side workspace may contain a Chinese project name even when the
    # package directory itself is ASCII. Aliasing only the package left that
    # suffix unchanged and ARM ar/ranlib could fail in CMake's compiler probe.
    # Compact callers identify a directory even before its first configure.
    # A junction may target that not-yet-created directory; retaining the exact
    # target makes the first configure and later runs use the same spelling
    # without creating or modifying the target here. Noncompact tool/file paths
    # continue to alias the nearest existing directory and retain sibling layout.
    if compact and filesystem_path(path).exists() and not filesystem_path(path).is_dir():
        raise ValueError('短构建别名要求目录：'+str(path))
    root = path if compact or filesystem_path(path).is_dir() else path.parent
    while not compact and not filesystem_path(root).is_dir():
        root = root.parent
    root = resolved_path(root)
    alias = Path(_short_path(root))
    # CMake expands native 8.3 names back to long Unicode paths in Makefiles.
    # A virtual junction keeps deeply nested build/probe paths short as well.
    if compact or not str(alias).isascii():
        import hashlib
        import time
        # Studio gives each worker its own TEMP. Build references in CMakeCache
        # must survive the worker and be reachable when Studio is reopened.
        parent = alias_root()
        if parent.is_relative_to(root) or root.is_relative_to(parent):
            raise ValueError(f'短路径 Junction 不能指向别名目录及其父目录: {parent} / {root}')
        parent.mkdir(parents=True,exist_ok=True)
        parent = Path(_short_path(parent))
        if not str(parent).isascii() or ' ' in str(parent) or len(str(parent))+33 > 120:
            raise ValueError(f'工具内无法取得足够短的无空格英文构建别名: {parent}；'
                             r'请将整个工具移动到类似 D:\ECRA 的非 C 盘短英文目录。')
        alias = parent/hashlib.sha256(str(root).casefold().encode('utf-8')).hexdigest()[:32]
        try:
            if not os.path.lexists(alias):
                _junction(alias,root)
        except FileExistsError:
            pass # another ECRA process may have created the identical alias
        except OSError as exc:
            raise ValueError(f'无法创建 CMake 短路径 Junction：{alias} -> {root}。'
                             f'请检查工具目录是否可写并支持 Junction。{exc}') from exc
        for attempt in range(5):
            if _is_junction(alias) and resolved_path(alias) == root:
                break
            if attempt == 4:
                raise ValueError(f'ASCII 路径别名冲突，拒绝覆盖: {alias}；要求指向 {root}')
            time.sleep(0.05)
    if resolved_path(alias) != root:
        raise ValueError(f'路径别名未指向原目录: {alias} -> {root}')
    _BUILD_ALIASES[root] = alias
    return str(alias/path.relative_to(root))


def bundle_root():
    from .config import TOOL_ROOT
    value = os.environ.get('ECRA_PORTABLE_ROOT')
    root = resolved_path(TOOL_ROOT)
    if value and (not Path(value).is_absolute() or resolved_path(value) != root):
        raise ValueError(f'ECRA_PORTABLE_ROOT 与正在运行的工具目录不同: {value}；实际目录 {root}')
    return root if (root / 'portable-lock.json').is_file() else None


def tool_environment():
    """Build processes see bundled tools and Windows only; review keeps host PATH."""
    from .runtime_storage import child_environment
    env = child_environment()
    root = bundle_root()
    if root:
        # Keep GCC's bin/libexec siblings, without aliasing an ancestor of workspace.
        build_path(root/'tools')
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
    paths = {'cmake': 'cmake/bin/cmake.exe', 'ninja': 'ninja/ninja.exe', 'git': 'git/cmd/git.exe',
             'mingw32-make': 'mingw/bin/mingw32-make.exe', 'gcc': 'mingw/bin/gcc.exe',
             'g++': 'mingw/bin/g++.exe', 'arm-none-eabi-gcc': 'arm-gcc/bin/arm-none-eabi-gcc.exe',
             'arm-none-eabi-g++': 'arm-gcc/bin/arm-none-eabi-g++.exe'}
    if name == 'git':
        if not root:
            return shutil.which(name) or name
        path = root/'tools'/paths[name]
        if path.is_file():
            return str(path)
        lock = json.loads((root/'portable-lock.json').read_text('utf-8-sig'))
        declared = lock.get('git_runtime_version') or lock.get('versions', {}).get('git')
        manifest = root/'FILES.sha256.json'
        if not declared and manifest.is_file():
            declared = any(p.startswith('tools/git/') for p in json.loads(manifest.read_text('utf-8-sig')))
        nested = next((root/'tools/git').glob('**/cmd/git.exe'), None)
        if nested:
            detail = f'解压层级错误，实际入口 {nested}'
        elif declared:
            detail = '清单已声明 Git，当前安装不完整'
        else:
            detail = '旧包未声明 Git'
        raise ValueError(f'{detail}。缺少 {path}；差异比较、版本选择及未提交输入捕获需要完整 MinGit。'
                         '请将通过验收的完整 ZIP 解压到新目录，并按升级说明保留 workspace。')
    if root and name in paths:
        build_path(root/'tools')
        path = root/'tools'/paths[name]
        if not path.is_file():
            raise ValueError(f'Portable 缺少工具: {path}；重新生成完整包')
        return build_path(path)
    return shutil.which(name, path=tool_environment().get('PATH')) or name


def check_git_components(root):
    """Check distribution structure independently of the generated hash manifest."""
    git = root/'tools/git'
    native = next((p for p in (git/'ucrt64', git/'mingw64') if (p/'bin/git.exe').is_file()), None)
    if native is None:
        raise ValueError(f'Git 运行组件缺失：{git} 下需要 ucrt64/bin/git.exe 或 mingw64/bin/git.exe。'
                         '请在新目录完整解压经校验的 ZIP。')
    for file in (git/'cmd/git.exe', git/'etc/gitconfig', git/'LICENSE.txt', git/'usr/bin/sh.exe',
                 git/'usr/bin/msys-2.0.dll', native/'bin/git-upload-pack.exe',
                 native/'share/git-core/templates/description', native/'libexec/git-core/git-sh-setup'):
        if not file.is_file():
            raise ValueError(f'Git 运行组件缺失：{file}；请在新目录完整解压经校验的 ZIP')


def git_status(expected=None):
    root = bundle_root()
    path = str(root/'tools/git/cmd/git.exe') if root else 'git'
    try:
        path = tool_path('git')
        if root:
            check_git_components(root)
    except (OSError, ValueError) as exc:
        return dict(path=path, running=False, matching=False, version='', error=str(exc))
    repair = ('请对照 FILES.sha256.json 核对 tools/git，并从已校验的 ZIP 完整解压到新目录。'
              if root else '请检查系统 Git 安装和 PATH。')
    try:
        result = _probe_version(path, expected, None)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return dict(path=path, running=False, matching=False, version='', error=f'{path} --version：{exc}。{repair}')
    if not result['running']:
        result.update(matching=False, error=f'{path} --version 退出码 {result["exit_code"]}，{result["version"]}。{repair}')
    return result


def require_git(feature):
    status = git_status()
    if not status['running']:
        raise ValueError(f'{feature} 需要可运行的 Git：{status["path"]}。{status["error"]}')
    return status


def read_cache(build, *, consumed_inputs=None):
    result = {}
    def text(file):
        if consumed_inputs is None:
            return filesystem_path(file).read_text(encoding='utf-8-sig',errors='replace')
        from .input_snapshot import read_consumed_text
        return read_consumed_text(file,consumed_inputs,errors='replace')
    path = Path(build)/'CMakeCache.txt'
    if filesystem_path(path).is_file():
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
            compiler_dir = filesystem_path(Path(build)/'CMakeFiles'/version_dir)
            for file in sorted(compiler_dir.glob('CMake*Compiler.cmake')):
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
    if cache.get('CMAKE_HOME_DIRECTORY') and resolved_path(cache['CMAKE_HOME_DIRECTORY']) != resolved_path(root):
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
    return _probe_version(path, expected, tool_environment())


def _probe_version(path, expected, env):
    proc = execute([path, '--version'], env=env, timeout=20)
    text = (proc.stdout + proc.stderr).strip()
    result = dict(path=path, canonical_path=str(Path(path).resolve()), version=text.splitlines()[0] if text else '', running=proc.returncode == 0, exit_code=proc.returncode)
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
    tools['git'] = git_status(required.get('git'))
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
                    git_diff_scan='NOT_RUN', cmake_build='NOT_RUN', arm_cross_compile='NOT_RUN', static_scan='NOT_RUN',
                    opencode_review='NOT_TESTED'))
