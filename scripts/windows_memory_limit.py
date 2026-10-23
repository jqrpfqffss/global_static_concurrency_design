"""Apply an explicit controlled per-process commit limit to an existing PID.

Use only for labelled fault-injection runs, never describe them as natural OOM.
The job handle stays open here until the process exits; it does not kill the
process when this controller exits.
"""
import argparse
import ctypes
import json
from pathlib import Path
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pid', type=int, required=True)
    parser.add_argument('--gib', type=float, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    from ctypes import wintypes as w
    class Basic(ctypes.Structure):
        _fields_ = [('PerProcessUserTimeLimit', ctypes.c_longlong), ('PerJobUserTimeLimit', ctypes.c_longlong),
                    ('LimitFlags', w.DWORD), ('MinimumWorkingSetSize', ctypes.c_size_t),
                    ('MaximumWorkingSetSize', ctypes.c_size_t), ('ActiveProcessLimit', w.DWORD),
                    ('Affinity', ctypes.c_size_t), ('PriorityClass', w.DWORD), ('SchedulingClass', w.DWORD)]
    class IO(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in ('ReadOperationCount','WriteOperationCount',
                    'OtherOperationCount','ReadTransferCount','WriteTransferCount','OtherTransferCount')]
    class Extended(ctypes.Structure):
        _fields_ = [('BasicLimitInformation', Basic), ('IoInfo', IO), ('ProcessMemoryLimit', ctypes.c_size_t),
                    ('JobMemoryLimit', ctypes.c_size_t), ('PeakProcessMemoryUsed', ctypes.c_size_t),
                    ('PeakJobMemoryUsed', ctypes.c_size_t)]
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]; k.CreateJobObjectW.restype = w.HANDLE
    k.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
    k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]; k.OpenProcess.restype = w.HANDLE
    k.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
    k.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
    k.CloseHandle.argtypes = [w.HANDLE]
    job = k.CreateJobObjectW(None, None)
    process = k.OpenProcess(0x0100 | 0x0001 | 0x00100000, False, args.pid)
    limit = Extended();limit.BasicLimitInformation.LimitFlags = 0x100
    limit.ProcessMemoryLimit = int(args.gib * 1024**3)
    try:
        if not job or not process or not k.SetInformationJobObject(job, 9, ctypes.byref(limit), ctypes.sizeof(limit)):
            raise ctypes.WinError(ctypes.get_last_error())
        if not k.AssignProcessToJobObject(job, process):
            raise ctypes.WinError(ctypes.get_last_error())
        evidence = dict(controlled_fault_injection=True, pid=args.pid, process_commit_limit_bytes=limit.ProcessMemoryLimit,
                        applied_unix=time.time(), source='Windows Job Object JOB_OBJECT_LIMIT_PROCESS_MEMORY')
        args.evidence.write_text(json.dumps(evidence,indent=2),encoding='utf-8')
        while k.WaitForSingleObject(process, 500) == 258:
            pass
    finally:
        if process: k.CloseHandle(process)
        if job: k.CloseHandle(job)


if __name__ == '__main__':
    main()
