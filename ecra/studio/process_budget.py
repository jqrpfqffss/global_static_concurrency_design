"""Windows Job ownership and complete descendant-process resource accounting."""
import ctypes
from ctypes import wintypes
import os


class ProcessBudget:
    def __init__(self, limit_bytes=16*1024**3):
        self.handle = None
        self.limit = limit_bytes
        if os.name != 'nt':
            return
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.kernel.CreateJobObjectW.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        self.kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.kernel.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p]
        class Basic(ctypes.Structure):
            _fields_ = [('process_time',ctypes.c_longlong), ('job_time',ctypes.c_longlong),
                ('flags',wintypes.DWORD), ('min_ws',ctypes.c_size_t), ('max_ws',ctypes.c_size_t),
                ('active_limit',wintypes.DWORD), ('affinity',ctypes.c_size_t),
                ('priority',wintypes.DWORD), ('scheduling',wintypes.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(key,ctypes.c_ulonglong) for key in ('read_ops','write_ops','other_ops','read_bytes','write_bytes','other_bytes')]
        class Extended(ctypes.Structure):
            _fields_ = [('basic',Basic), ('io',IO), ('process_limit',ctypes.c_size_t),
                ('job_limit',ctypes.c_size_t), ('peak_process',ctypes.c_size_t), ('peak_job',ctypes.c_size_t)]
        self.Extended = Extended
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        info = Extended()
        info.basic.flags = 0x2000 | 0x200  # KILL_ON_JOB_CLOSE | JOB_MEMORY
        info.job_limit = limit_bytes
        if not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            self.close()
            raise ctypes.WinError(ctypes.get_last_error())

    def assign(self, process):
        if self.handle and not self.kernel.AssignProcessToJobObject(self.handle, int(process._handle)):
            raise ctypes.WinError(ctypes.get_last_error())

    def contains(self,pid):
        """Verify a declared worker PID belongs to this exact owned Job."""
        if not self.handle or type(pid) is not int or pid<=0:return False
        self.kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        self.kernel.OpenProcess.restype=wintypes.HANDLE
        self.kernel.IsProcessInJob.argtypes=[wintypes.HANDLE,wintypes.HANDLE,ctypes.POINTER(wintypes.BOOL)]
        process=self.kernel.OpenProcess(0x1000,False,pid)
        if not process:return False
        try:
            answer=wintypes.BOOL()
            if not self.kernel.IsProcessInJob(process,self.handle,ctypes.byref(answer)):raise ctypes.WinError(ctypes.get_last_error())
            return bool(answer.value)
        finally:self.kernel.CloseHandle(process)

    def sample(self):
        if not self.handle:
            return dict(available=False, reason='此版本的进程树预算只在 Windows Job Object 下验证')
        info = self.Extended()
        if not self.kernel.QueryInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info), None):
            raise ctypes.WinError(ctypes.get_last_error())
        # JOBOBJECT_BASIC_PROCESS_ID_LIST is variable length. Grow until every
        # assigned process is present; no top-N approximation is allowed.
        size = 4096
        while True:
            buffer = ctypes.create_string_buffer(size)
            if self.kernel.QueryInformationJobObject(self.handle, 3, buffer, size, None):
                count = ctypes.c_ulong.from_buffer(buffer, 4).value
                ids = (ctypes.c_size_t*count).from_buffer(buffer, 8)
                break
            if ctypes.get_last_error() != 234:
                raise ctypes.WinError(ctypes.get_last_error())
            size *= 2
        class Counters(ctypes.Structure):
            _fields_ = [('cb',wintypes.DWORD), ('faults',wintypes.DWORD),
                *[(key,ctypes.c_size_t) for key in ('peak_ws','ws','peak_pp','pp','peak_np','np','commit','peak_commit','private')]]
        self.kernel.OpenProcess.argtypes = [wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        psapi = ctypes.WinDLL('psapi', use_last_error=True)
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE,ctypes.c_void_p,wintypes.DWORD]
        rss = private = sampled = 0
        for pid in ids:
            handle = self.kernel.OpenProcess(0x410, False, pid)
            if not handle:
                continue  # a process may exit between enumeration and reading
            try:
                counters = Counters(); counters.cb = ctypes.sizeof(counters)
                if psapi.GetProcessMemoryInfo(handle,ctypes.byref(counters),counters.cb):
                    rss += counters.ws; private += counters.private; sampled += 1
            finally:
                self.kernel.CloseHandle(handle)
        return dict(available=True, working_set_bytes=rss, private_bytes=private,
                    peak_job_commit_bytes=info.peak_job, limit_bytes=self.limit,
                    enforced_job_commit_limit_bytes=info.job_limit,job_limit_flags=info.basic.flags,
                    processes=count, sampled_processes=sampled, write_bytes=info.io.write_bytes)

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
