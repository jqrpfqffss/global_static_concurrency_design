"""Bounded scan diagnostics using only the Portable Python standard library."""
from contextvars import ContextVar
from contextlib import contextmanager
from datetime import datetime, timezone
import ctypes
import json
import os
from pathlib import Path
import sys
import threading
import time
import traceback
import tracemalloc

from .common import write_json
from .emergency_memory import CommitReserve, python_reserve

ACTIVE = ContextVar('ecra_scan_diagnostics', default=None)


def diagnostic_log(message):
    try:
        print(message, file=sys.stderr, flush=True)
    except (OSError, ValueError):
        pass


def record_resource_control(record):
    from .resource_control import EVENT_LOG
    active = ACTIVE.get()
    if active is not None:
        if active.current is not None:
            record['stage'] = active.current['stage']
        active.resource_control = record
        try:
            with (active.folder / EVENT_LOG).open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + '\n')
        except (OSError, MemoryError) as exc:
            diagnostic_log(f'资源调度诊断写入失败：{exc}\n{record}')
    try:
        (active.progress if active is not None else print)(record['message'])
    except (OSError, ValueError) as exc:
        diagnostic_log(f'资源调度日志写入失败：{exc}\n{record}')


@contextmanager
def interruptible_sqlite(connection):
    """Bridge an explicit scan stop to SQLite's thread-safe interrupt API.

    Python's pending KeyboardInterrupt alone waits for sqlite3_step to return.
    A complete integrity check can spend minutes inside that call.
    """
    active = ACTIVE.get()
    if active is None:
        yield connection
        return
    from .scan_stop import check_stop
    with active.sqlite_lock:
        active.sqlite_connections.add(connection)
    try:
        check_stop()
        yield connection
    except Exception as exc:
        import sqlite3
        if isinstance(exc, sqlite3.OperationalError) and str(exc) == 'interrupted':
            check_stop()  # Preserve a requested stop as KeyboardInterrupt/130.
        raise
    finally:
        with active.sqlite_lock:
            active.sqlite_connections.discard(connection)


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
                      system_commit_peak_bytes=info.CommitPeak * info.PageSize,
                      system_physical_total_bytes=info.PhysicalTotal*info.PageSize,
                      system_physical_available_bytes=info.PhysicalAvailable*info.PageSize)
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
        self.sqlite_lock = threading.Lock()
        self.sqlite_connections = set()
        self.extraction_polls_stop = False
        self.resource_control = None
        self.reserve = python_reserve()
        self.commit_reserve = CommitReserve()
        self.failed = False
        self.token = ACTIVE.set(self)
        self.trace_owned = bool(os.environ.get('ECRA_PROFILE_MEMORY')) and not tracemalloc.is_tracing()
        if self.trace_owned:
            tracemalloc.start(1)
        self.thread = threading.Thread(target=self.sample_loop, daemon=True)
        self.thread.start()

    @contextmanager
    def cooperative_extraction_stop(self):
        # Extraction polls while waiting for admission and worker results.
        # Avoid a second asynchronous interrupt while it reaps its workers.
        with self.sqlite_lock:
            self.extraction_polls_stop = True
        try:
            yield
        except BaseException:
            self.stop.set()
            raise
        finally:
            with self.sqlite_lock:
                self.extraction_polls_stop = False

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
            request = os.environ.get('ECRA_JOB_STOP_FILE')
            if request and Path(request).is_file():
                import _thread
                with self.sqlite_lock:
                    if self.extraction_polls_stop or self.stop.is_set():
                        continue
                    # Queue the Python stop before SQLite can return. Doing
                    # this afterward could deliver a second interrupt while
                    # the main thread is already unwinding the SQL exception.
                    _thread.interrupt_main()
                    for connection in self.sqlite_connections:
                        connection.interrupt()
                return
            try:
                self.sample()
                write_json(self.folder/'scan_progress.json', dict(completed_units=self.completed_units,
                    total_units=self.total_units, snapshot_status=self.snapshot_status,
                    stage=self.current['stage'] if self.current else None, fact_counts=self.fact_counts))
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
        try:
            measured = self.sample()
        except (OSError, MemoryError) as error:
            diagnostic_log(f'失败时的资源采样不可用：{error}')
            measured = {}
        info = dict(origin=origin, pid=os.getpid(), exception_type=type(exc).__name__, message=str(exc),
                    stage=self.current, completed_units=self.completed_units, total_units=self.total_units,
                    pending_units=self.total_units-self.completed_units, fact_counts=self.fact_counts,
                    fact_counts_scope=self.fact_counts_scope,
                    memory=measured, peak_memory=self.peaks, snapshot_status=self.snapshot_status,
                    analysis_valid=False)
        control = getattr(exc, 'resource_control', None)
        if isinstance(exc, KeyboardInterrupt) and (self.resource_control or {}).get('status') == 'CANCELLED':
            control = self.resource_control
        if control is not None:
            info['resource_control'] = control
        try:
            with (self.folder / 'exception.log').open('w', encoding='utf-8') as stream:
                stream.write(json.dumps(info, ensure_ascii=False, indent=2)+'\n')
                traceback.print_exception(type(exc), exc, exc.__traceback__, file=stream)
        except (OSError, MemoryError) as error:
            diagnostic_log(f'异常堆栈写入失败：{error}\n' +
                           ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
        try:
            write_json(self.folder / 'exception.json', info)
        except (OSError, MemoryError) as error:
            diagnostic_log(f'异常诊断写入失败：{error}\n{info}')
        try:
            self.finish_stage('INTERRUPTED' if isinstance(exc, KeyboardInterrupt) else 'FAILED')
        except (OSError, MemoryError) as error:
            self.current = None
            diagnostic_log(f'失败阶段诊断写入失败：{error}')

    def close(self):
        self.reserve = None
        self.commit_reserve.close()
        self.stop.set()
        self.thread.join(timeout=2)
        self.finish_stage()
        if self.fact_source is not None:
            self.fact_counts = {key: len(value) for key, value in self.fact_source.items() if isinstance(value, list)}
        try:
            write_json(self.folder / 'memory_profile.json', dict(pid=os.getpid(), current=self.sample(), peaks=self.peaks,
                       fact_counts=self.fact_counts, fact_counts_scope=self.fact_counts_scope,
                       completed_units=self.completed_units, total_units=self.total_units))
            if self.trace_owned:
                if self.failed:
                    write_json(self.folder / 'python_allocations.json', dict(
                        full_snapshot=False, reason='Failed scan: avoid copying all allocation traces during exception cleanup',
                        traced_memory=tracemalloc.get_traced_memory()))
                else:
                    snapshot = tracemalloc.take_snapshot()
                    write_json(self.folder / 'python_allocations.json', [dict(trace=str(stat.traceback), bytes=stat.size,
                               count=stat.count) for stat in snapshot.statistics('lineno')[:50]])
        except (OSError, MemoryError) as error:
            if not self.failed:
                raise
            diagnostic_log(f'扫描诊断收尾失败：{error}')
        finally:
            if self.trace_owned:
                tracemalloc.stop()
            ACTIVE.reset(self.token)
            self.fact_source = None
