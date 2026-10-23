"""Bounded scan diagnostics using only the Portable Python standard library."""
from contextvars import ContextVar
from datetime import datetime, timezone
import ctypes
import json
import os
from pathlib import Path
import threading
import time
import traceback
import tracemalloc

from .common import write_json
from .emergency_memory import CommitReserve, python_reserve

ACTIVE = ContextVar('ecra_scan_diagnostics', default=None)


def memory():
    if os.name != 'nt':
        import resource
        return dict(peak_working_set_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024)
    class Counters(ctypes.Structure):
        _fields_ = [('cb', ctypes.c_ulong), ('PageFaultCount', ctypes.c_ulong),
                    *[(key, ctypes.c_size_t) for key in ('PeakWorkingSetSize', 'WorkingSetSize',
                      'QuotaPeakPagedPoolUsage', 'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage',
                      'QuotaNonPagedPoolUsage', 'PagefileUsage', 'PeakPagefileUsage', 'PrivateUsage')]]
    kernel = ctypes.windll.kernel32
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    process = kernel.GetCurrentProcess()
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    api = ctypes.windll.psapi.GetProcessMemoryInfo
    api.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
    if not api(process, ctypes.byref(counters), counters.cb):
        raise ctypes.WinError()
    result = dict(private_bytes=counters.PrivateUsage, working_set_bytes=counters.WorkingSetSize,
                  peak_working_set_bytes=counters.PeakWorkingSetSize,
                  peak_process_commit_bytes=counters.PeakPagefileUsage)
    class Performance(ctypes.Structure):
        _fields_ = [('cb', ctypes.c_ulong), *[(name, ctypes.c_size_t) for name in
            ('CommitTotal', 'CommitLimit', 'CommitPeak', 'PhysicalTotal', 'PhysicalAvailable',
             'SystemCache', 'KernelTotal', 'KernelPaged', 'KernelNonpaged', 'PageSize')],
            ('HandleCount', ctypes.c_ulong), ('ProcessCount', ctypes.c_ulong), ('ThreadCount', ctypes.c_ulong)]
    info = Performance()
    info.cb = ctypes.sizeof(info)
    if ctypes.windll.psapi.GetPerformanceInfo(ctypes.byref(info), info.cb):
        result.update(system_commit_bytes=info.CommitTotal * info.PageSize,
                      system_commit_limit_bytes=info.CommitLimit * info.PageSize,
                      system_commit_peak_bytes=info.CommitPeak * info.PageSize)
    return result


def start_stage(name, operation=None):
    active = ACTIVE.get()
    if active:
        active.stage(name, operation)


class ScanDiagnostics:
    def __init__(self, folder, progress=None):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.progress = progress or (lambda _: None)
        self.current = None
        self.stages = []
        self.completed_units = 0
        self.total_units = 0
        self.fact_counts = {}
        self.fact_source = None
        self.fact_counts_scope = 'translation_unit_rows_including_duplicates'
        self.snapshot_status = 'NOT_CAPTURED'
        self.peaks = {}
        self.stop = threading.Event()
        self.reserve = python_reserve()
        self.commit_reserve = CommitReserve()
        self.failed = False
        self.token = ACTIVE.set(self)
        self.trace_owned = bool(os.environ.get('ECRA_PROFILE_MEMORY')) and not tracemalloc.is_tracing()
        if self.trace_owned:
            tracemalloc.start(1)
        self.thread = threading.Thread(target=self.sample_loop, daemon=True)
        self.thread.start()

    def sample(self):
        result = memory()
        for key, value in result.items():
            if key != 'system_commit_limit_bytes':
                self.peaks[key] = max(value, self.peaks.get(key, 0))
        if tracemalloc.is_tracing():
            result['tracemalloc_current_bytes'], result['tracemalloc_peak_bytes'] = tracemalloc.get_traced_memory()
        return result

    def sample_loop(self):
        while not self.stop.wait(0.5):
            try:
                self.sample()
            except (OSError, MemoryError):
                pass

    def finish_stage(self, status='COMPLETE'):
        if self.current is None:
            return
        self.current.update(finished=datetime.now(timezone.utc).isoformat(),
                            seconds=time.monotonic()-self.begin, status=status, memory_end=self.sample())
        self.stages.append(self.current)
        self.current = None
        write_json(self.folder / 'scan_stages.json', self.stages)

    def stage(self, name, operation=None, *, announce=True):
        self.finish_stage()
        self.begin = time.monotonic()
        self.current = dict(stage=name, operation=operation or name, started=datetime.now(timezone.utc).isoformat(),
                            memory_start=self.sample(), status='RUNNING')
        if announce:
            self.progress('阶段开始：' + name)
            write_json(self.folder / 'scan_stages.json', [*self.stages, self.current])

    def failure(self, exc, origin='MAIN'):
        self.reserve = None
        self.commit_reserve.close()
        self.failed = True
        self.stop.set()
        if self.fact_source is not None:
            self.fact_counts = {key: len(value) for key, value in self.fact_source.items() if isinstance(value, list)}
        info = dict(origin=origin, pid=os.getpid(), exception_type=type(exc).__name__, message=str(exc),
                    stage=self.current, completed_units=self.completed_units, total_units=self.total_units,
                    pending_units=self.total_units-self.completed_units, fact_counts=self.fact_counts,
                    fact_counts_scope=self.fact_counts_scope,
                    memory=self.sample(), peak_memory=self.peaks, snapshot_status=self.snapshot_status,
                    analysis_valid=False)
        with (self.folder / 'exception.log').open('w', encoding='utf-8') as stream:
            stream.write(json.dumps(info, ensure_ascii=False, indent=2)+'\n')
            traceback.print_exception(type(exc), exc, exc.__traceback__, file=stream)
        write_json(self.folder / 'exception.json', info)
        self.finish_stage('INTERRUPTED' if isinstance(exc, KeyboardInterrupt) else 'FAILED')

    def close(self):
        self.reserve = None
        self.commit_reserve.close()
        self.stop.set()
        self.thread.join(timeout=2)
        self.finish_stage()
        if self.fact_source is not None:
            self.fact_counts = {key: len(value) for key, value in self.fact_source.items() if isinstance(value, list)}
        write_json(self.folder / 'memory_profile.json', dict(pid=os.getpid(), current=self.sample(), peaks=self.peaks,
                   fact_counts=self.fact_counts, fact_counts_scope=self.fact_counts_scope,
                   completed_units=self.completed_units, total_units=self.total_units))
        if self.trace_owned:
            try:
                if self.failed:
                    write_json(self.folder / 'python_allocations.json', dict(
                        full_snapshot=False, reason='Failed scan: avoid copying all allocation traces during exception cleanup',
                        traced_memory=tracemalloc.get_traced_memory()))
                else:
                    snapshot = tracemalloc.take_snapshot()
                    write_json(self.folder / 'python_allocations.json', [dict(trace=str(stat.traceback), bytes=stat.size,
                               count=stat.count) for stat in snapshot.statistics('lineno')[:50]])
            finally:
                tracemalloc.stop()
        ACTIVE.reset(self.token)
        self.fact_source = None
