"""Cross-process reader/writer barrier for scans, imports and data cleanup."""
import os
from pathlib import Path
import time

from .workspace import managed_path, no_links


class DataBusy(ValueError):
    """A live owner, rather than a damaged or unavailable data directory."""


class DataActivity:
    def __init__(self, data_root, *, exclusive=False, purpose='storage', read_only=False, wait=0):
        if purpose not in {'storage','scan-budget','cleanup-job','legacy-import','storage-policy','api','root-transfer','export-job','import-job','report-import'}:raise ValueError('未知数据活动锁')
        self.root=no_links(data_root) if read_only else managed_path(data_root)
        self.exclusive=exclusive
        self.purpose=purpose
        self.read_only=read_only
        self.wait=wait
        self.stream=None

    def __enter__(self):
        folder=no_links(self.root/'settings')
        if not self.read_only:
            folder.mkdir(parents=True,exist_ok=True)
        path=no_links(folder/(self.purpose+'-activity.lock'))
        try:
            stream=path.open('rb' if self.read_only else 'a+b')
        except FileNotFoundError:
            if not self.read_only:
                raise
            return self
        self.stream=stream
        try:
            deadline=time.monotonic()+self.wait
            while True:
                try:
                    self._lock(stream)
                    break
                except OSError as exc:
                    remaining=deadline-time.monotonic()
                    busy=isinstance(exc,BlockingIOError) or getattr(exc,'winerror',None) in {32,33}
                    if not busy or remaining<=0:raise
                    time.sleep(min(remaining,.05))
        except BaseException as exc:
            stream.close();self.stream=None
            if isinstance(exc,OSError):
                raise DataBusy(f'数据根正在扫描、复核、导入、整理或整套复制，等待当前操作结束后重试: {path}') from exc
            raise
        return self

    def _lock(self, stream):
        if os.name=='nt':
            import msvcrt
            import ctypes
            from ctypes import wintypes
            class Overlapped(ctypes.Structure):
                _fields_=[('Internal',ctypes.c_size_t),('InternalHigh',ctypes.c_size_t),
                          ('Offset',wintypes.DWORD),('OffsetHigh',wintypes.DWORD),('hEvent',wintypes.HANDLE)]
            self.kernel=ctypes.WinDLL('kernel32',use_last_error=True)
            self.kernel.LockFileEx.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.DWORD,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p]
            self.kernel.UnlockFileEx.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p]
            self.overlapped=Overlapped()
            self.handle=msvcrt.get_osfhandle(stream.fileno())
            if not self.kernel.LockFileEx(self.handle,1|(2 if self.exclusive else 0),0,1,0,ctypes.byref(self.overlapped)):
                raise ctypes.WinError(ctypes.get_last_error())
        else:
            import fcntl
            fcntl.flock(stream.fileno(),(fcntl.LOCK_EX if self.exclusive else fcntl.LOCK_SH)|fcntl.LOCK_NB)

    def __exit__(self,*_):
        if self.stream:
            if os.name=='nt':
                import ctypes
                self.kernel.UnlockFileEx(self.handle,0,1,0,ctypes.byref(self.overlapped))
            self.stream.close();self.stream=None


def review_data_root(path):
    path=Path(path).resolve()
    return path.parent.parent.parent if path.parent.parent.name=='scans' else None


def guarded_operation(selector):
    """Guard the complete operation, including snapshot and publication."""
    from functools import wraps
    import inspect
    def decorate(function):
        signature=inspect.signature(function)
        @wraps(function)
        def guarded(*args,**kwargs):
            arguments=signature.bind(*args,**kwargs).arguments
            from .workspace import studio_data_root
            root=studio_data_root(selector(arguments))
            with DataActivity(root):
                return function(*args,**kwargs)
        return guarded
    return decorate


def scan_data_root(directory):
    path=Path(directory).resolve()
    return path.parent.parent if path.parent.name=='scans' else path.parent
