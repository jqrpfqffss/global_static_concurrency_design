"""Clean owned CMake trees without following links or discarding ownership."""
from contextlib import ExitStack, contextmanager, nullcontext
import os
import shutil
import stat
import time

from .path_io import filesystem_path, is_link, lstat_if_present, ordinary_path, resolved_path
from .scan_stop import check_stop


OWNER_MARKER = '.ecra-build-owner'


def owns_build_directory(build, root):
    marker = filesystem_path(build / OWNER_MARKER)
    info = lstat_if_present(marker)
    return (info is not None and stat.S_ISREG(info.st_mode) and not is_link(info)
            and info.st_nlink == 1 and marker.read_text(encoding='utf-8') == str(resolved_path(root)))


def _operate(action, path, operation):
    for attempt in range(5):
        check_stop()
        try:
            return operation(path)
        except FileNotFoundError as exc:
            subject = ordinary_path(path)
            if lstat_if_present(path) is None:
                raise ValueError(f'CMake 清理失败（{action}）：路径在清理期间消失：{subject}。'
                                 '请等待其他构建或清理进程退出后重试。') from exc
            raise ValueError(f'CMake 清理失败（{action}）：路径仍存在：{subject}。'
                             f'请检查目录状态及文件系统错误：{exc}') from exc
        except OSError as exc:
            if getattr(exc, 'winerror', None) in {32, 33} and attempt < 4:
                time.sleep(.05 * 2**attempt)
                continue
            raise ValueError(f'CMake 清理失败（{action}）：{ordinary_path(path)}。'
                             f'请检查文件占用和目录权限：{exc}') from exc


class _WindowsDirectoryPins:
    """Prevent rename and replacement of directories while visiting children."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes

        self.api = ctypes.WinDLL('kernel32', use_last_error=True)
        self.api.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                        ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        self.api.CreateFileW.restype = wintypes.HANDLE
        self.api.GetFileInformationByHandleEx.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                         ctypes.c_void_p, wintypes.DWORD]
        self.api.GetFileInformationByHandleEx.restype = wintypes.BOOL
        self.api.CloseHandle.argtypes = [wintypes.HANDLE]

    @contextmanager
    def hold(self, path):
        import ctypes
        from ctypes import wintypes

        def open_directory(value):
            # Open the reparse point itself. Share read access only so the
            # directory cannot be renamed or made into a junction in place.
            handle = self.api.CreateFileW(str(value), 0x80000000, 1, None, 3, 0x02200000, None)
            if handle in (None, ctypes.c_void_p(-1).value):
                raise ctypes.WinError(ctypes.get_last_error())
            return handle

        handle = _operate('打开目录', path, open_directory)
        try:
            info = (wintypes.DWORD * 2)()  # FILE_ATTRIBUTE_TAG_INFO
            if not self.api.GetFileInformationByHandleEx(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
                error = ctypes.WinError(ctypes.get_last_error())
                raise ValueError(f'CMake 清理失败（校验目录句柄）：{ordinary_path(path)}。{error}') from error
            if not info[0] & stat.FILE_ATTRIBUTE_DIRECTORY or info[0] & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise ValueError(f'拒绝清理链接或非普通构建目录：{ordinary_path(path)}')
            yield
        finally:
            self.api.CloseHandle(handle)


def _inspect(path, expected=None):
    info = _operate('检查目录项', path, lambda item: item.lstat())
    if is_link(info):
        raise ValueError(f'拒绝清理含链接的目录：{ordinary_path(path)}')
    if expected is not None and not os.path.samestat(info, expected):
        raise ValueError(f'CMake 清理期间目录项被替换：{ordinary_path(path)}；请结束其他构建后重试。')
    return info


def clean_owned_directory(build, root):
    """Validate before deleting and keep the root and its owner marker intact."""
    from .workspace import no_links

    build = filesystem_path(no_links(build))
    children = {}
    pin = _WindowsDirectoryPins().hold if os.name == 'nt' else lambda _: nullcontext()

    def inventory(folder):
        names = _operate('列出目录', folder, os.listdir)
        children[folder] = {}
        for name in names:
            child = folder / name
            info = _inspect(child)
            children[folder][child] = info
            if stat.S_ISDIR(info.st_mode):
                with pin(child):
                    inventory(child)

    def remove_children(folder):
        for child, expected in children[folder].items():
            if folder == build and child.name == OWNER_MARKER:
                continue
            info = _inspect(child, expected)
            if stat.S_ISDIR(info.st_mode):
                with pin(child):
                    remove_children(child)
                _inspect(child, expected)
                _operate('删除目录', child, os.rmdir)
            else:
                _operate('删除文件', child, os.unlink)

    with ExitStack() as stack:
        for path in reversed((build, *build.parents)):
            stack.enter_context(pin(path))
        if not owns_build_directory(build, root):
            raise ValueError(f'拒绝清理非 ECRA 专用构建目录：{ordinary_path(build)}；请选择独立的构建目录。')
        inventory(build)
        if os.name != 'nt':
            # Keep shutil's fd-relative, symlink-resistant deletion on POSIX.
            _operate('删除构建树', build, shutil.rmtree)
            if lstat_if_present(build) is not None:
                raise ValueError(f'CMake 清理后构建目录仍存在：{build}')
            _operate('重建构建目录', build, lambda item: item.mkdir())
            _operate('重建构建目录归属', build / OWNER_MARKER,
                     lambda item: item.write_text(str(resolved_path(root)), encoding='utf-8'))
            return
        remove_children(build)
        if set(_operate('确认清理结果', build, os.listdir)) != {OWNER_MARKER} or not owns_build_directory(build, root):
            raise ValueError(f'CMake 清理期间构建目录内容或归属发生变化：{ordinary_path(build)}；请结束其他构建后重试。')
