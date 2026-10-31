"""Conservative process identity for recovering abandoned Windows scan locks."""
from datetime import datetime,timezone
import os


def process_identity(pid):
    """Return live creation FILETIME, False for exited/missing, None if unknown."""
    if type(pid) is not int or pid<=0:return None
    if os.name!='nt':
        try:os.kill(pid,0)
        except ProcessLookupError:return False
        except OSError:return None
        return None  # no reliable creation identity on this platform
    import ctypes
    from ctypes import wintypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
    kernel.GetProcessTimes.argtypes=[wintypes.HANDLE,*([ctypes.POINTER(wintypes.FILETIME)]*4)]
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=kernel.OpenProcess(0x1000,False,pid)
    if not handle:return False if ctypes.get_last_error()==87 else None
    try:
        status=wintypes.DWORD()
        if not kernel.GetExitCodeProcess(handle,ctypes.byref(status)):return None
        if status.value!=259:return False
        times=[wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle,*(ctypes.byref(value) for value in times)):return None
        return (times[0].dwHighDateTime<<32)|times[0].dwLowDateTime
    finally:kernel.CloseHandle(handle)


def abandoned(marker):
    current=process_identity(marker.get('pid'))
    if current is False:return True
    if current is None:return False
    if type(marker.get('creation_filetime')) is int:
        return current!=marker['creation_filetime']  # same PID, different process
    # Old versions recorded UTC scan start but not process creation. A reused
    # PID starts after that receipt. Ambiguous/unparseable locks stay blocked.
    try:
        started=datetime.fromisoformat(marker['started'])
        if started.tzinfo is None:return False
        recorded=int((started.astimezone(timezone.utc).timestamp()+11644473600)*10000000)
        return current>recorded
    except (KeyError,ValueError,TypeError,OverflowError):return False
