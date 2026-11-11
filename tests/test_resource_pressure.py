import os
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from concurrent.futures import ThreadPoolExecutor
import io
import multiprocessing
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ecra.cli import extraction_responses
from ecra.common import execute, read_json, write_json
from ecra.resource_control import ResourceControlError


class ResourcePressureTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.pressure = self.root / 'resource-pressure.json'
        self.submitted = []
        self.consumed = []

    def scan(self, count, budget, *, controlled=True):
        submitted = self.submitted

        class RecordingPool(ThreadPoolExecutor):
            def submit(self, job, unit):
                submitted.append(unit['tu_id'])
                return super().submit(job, unit)

        def worker(argv, **kwargs):
            if hasattr(self, 'worker'):
                return self.worker(argv, **kwargs)
            write_json(argv[-1], dict(parse_status='PARSED'))
            return SimpleNamespace(returncode=0, stderr='')

        units = [dict(tu_id=str(i), source_file=f'{i}.c') for i in range(count)]
        environment = dict(os.environ)
        for key in ('ECRA_RESOURCE_PRESSURE_FILE', 'ECRA_EXTRACTION_WORKERS', 'ECRA_JOB_STOP_FILE'):
            environment.pop(key, None)
        if controlled:
            environment['ECRA_RESOURCE_PRESSURE_FILE'] = str(self.pressure)
        environment.update(getattr(self, 'scan_environment', {}))
        with (patch.dict(os.environ, environment, clear=True),
              patch('concurrent.futures.ThreadPoolExecutor', RecordingPool),
              patch('ecra.cli.execute', side_effect=worker)):
            for unit, _, _ in extraction_responses(self.root, units,
                    dict(analysis=dict(extraction_workers=budget)), self.root, {}, self.root, self.root):
                self.consumed.append(unit['tu_id'])

    def test_permission_denied_without_winerror_at_178_recovers_in_order(self):
        write_json(self.pressure, dict(parallel_limit=4))
        original_open = Path.open
        attempts = []

        def open_file(path, *args, **kwargs):
            if path == self.pressure and len(self.consumed) == 178:
                attempts.append(len(self.submitted))
                if len(attempts) <= 3:
                    error = PermissionError(13, 'injected denial', str(path))
                    self.assertIsNone(getattr(error, 'winerror', None))
                    raise error
            return original_open(path, *args, **kwargs)

        with patch.object(Path, 'open', open_file):
            self.scan(220, 4)
        self.assertEqual(attempts, [181] * 4)
        self.assertEqual(self.submitted, [str(i) for i in range(220)])
        self.assertEqual(self.consumed, self.submitted)

    def test_first_failure_recovers_with_single_parallel_slot(self):
        write_json(self.pressure, dict(parallel_limit=8))
        original_open = Path.open
        events = []

        def open_file(path, *args, **kwargs):
            if path == self.pressure and not events:
                raise PermissionError(13, 'one refusal', str(path))
            return original_open(path, *args, **kwargs)

        with (patch.object(Path, 'open', open_file),
              patch('ecra.scan_diagnostics.record_resource_control', side_effect=events.append)):
            self.scan(4, 1)
        self.assertEqual(self.consumed, ['0', '1', '2', '3'])
        self.assertEqual(self.submitted, self.consumed)
        self.assertEqual([row['status'] for row in events], ['RETRYING', 'RECOVERED'])
        self.assertEqual(events[-1]['retries'], 1)

    def test_existing_worker_is_kept_during_retry_and_limit_is_clamped(self):
        write_json(self.pressure, dict(parallel_limit=8))
        waiting, release = threading.Event(), threading.Event()
        original_open = Path.open
        events = []
        cancellations = []

        def worker(argv, *, cancel_event, **kwargs):
            if Path(argv[-1]).name == '1.response.json':
                cancellations.append(cancel_event)
                waiting.set()
                release.wait(3)
            write_json(argv[-1], {})
            return SimpleNamespace(returncode=0, stderr='')

        def open_file(path, *args, **kwargs):
            if path == self.pressure and len(self.consumed) == 1 and not events:
                self.assertEqual(self.submitted, ['0', '1'])
                self.assertTrue(waiting.wait(2))
                raise PermissionError(13, 'while second worker is active', str(path))
            return original_open(path, *args, **kwargs)

        def record(event):
            self.assertEqual(self.submitted, ['0', '1'])
            self.assertFalse(cancellations[0].is_set())
            events.append(event['status'])
            if event['status'] == 'RECOVERED':
                release.set()

        self.worker = worker
        with (patch.object(Path, 'open', open_file),
              patch('ecra.scan_diagnostics.record_resource_control', side_effect=record)):
            self.scan(6, 2)
        self.assertEqual(events, ['RETRYING', 'RECOVERED'])
        self.assertEqual(self.consumed, [str(i) for i in range(6)])
        self.assertEqual(self.submitted, self.consumed)

    def test_persistent_permission_error_is_bounded_and_keeps_original_cause(self):
        original_open = Path.open

        def open_file(path, *args, **kwargs):
            if path == self.pressure:
                raise PermissionError(13, 'continuous denial', str(path))
            return original_open(path, *args, **kwargs)

        with patch.object(Path, 'open', open_file), self.assertRaises(ResourceControlError) as raised:
            self.scan(3, 2)
        cause = raised.exception.__cause__
        self.assertIsInstance(cause, PermissionError)
        self.assertEqual(cause.filename, str(self.pressure))
        event = raised.exception.resource_control
        self.assertEqual((event['operation'], event['status'], event['errno'], event['winerror']),
                         ('read', 'FAILED', 13, None))
        self.assertIn('continuous denial', event['exception_chain'])
        self.assertGreaterEqual(event['retries'], 1)
        self.assertLessEqual(event['attempts'], 5)
        self.assertLess(event['elapsed_seconds'], 1)
        self.assertEqual((self.submitted, self.consumed), ([], []))

    def test_missing_file_recovers_when_published_and_fails_if_still_missing(self):
        events = []

        def publish(event):
            events.append(event['status'])
            self.assertEqual(self.submitted, [])
            if event['status'] == 'RETRYING':
                write_json(self.pressure, dict(parallel_limit=1))

        with patch('ecra.scan_diagnostics.record_resource_control', side_effect=publish):
            self.scan(3, 3)
        self.assertEqual(events, ['RETRYING', 'RECOVERED'])
        self.assertEqual(self.consumed, ['0', '1', '2'])
        self.submitted.clear()
        self.pressure.unlink()
        with self.assertRaises(ResourceControlError) as raised:
            self.scan(3, 3)
        self.assertIsInstance(raised.exception.__cause__, FileNotFoundError)
        self.assertEqual(raised.exception.resource_control['status'], 'FAILED')
        self.assertEqual(self.submitted, [])

    def test_invalid_controls_fail_immediately(self):
        for raw in ('{', '[]', '{}', '{"parallel_limit":true}', '{"parallel_limit":null}',
                    '{"parallel_limit":"2"}', '{"parallel_limit":1.5}', '{"parallel_limit":0}',
                    '{"parallel_limit":9}', None):
            with self.subTest(raw=raw):
                if raw is None:
                    self.pressure.unlink()
                    self.pressure.mkdir()
                else:
                    self.pressure.write_text(raw, encoding='utf-8')
                with self.assertRaises(ResourceControlError) as raised:
                    self.scan(4, 4)
                self.assertEqual(raised.exception.resource_control['status'], 'INVALID')
                self.assertEqual(raised.exception.resource_control['retries'], 0)
                self.assertEqual(self.submitted, [])
        self.scan_environment = {'ECRA_RESOURCE_PRESSURE_FILE': ''}
        with self.assertRaises(ResourceControlError) as raised:
            self.scan(2, 1)
        self.assertEqual(raised.exception.resource_control['status'], 'INVALID')

    def test_stop_during_wait_cancels_without_admission(self):
        stop = self.root / 'stop'
        self.scan_environment = {'ECRA_JOB_STOP_FILE': str(stop)}
        events = []

        def record(event):
            events.append(event)
            if event['status'] == 'RETRYING':
                self.timer.start()

        self.timer = threading.Timer(.08, stop.touch)
        try:
            with (patch('ecra.scan_diagnostics.record_resource_control', side_effect=record),
                  self.assertRaises(KeyboardInterrupt)):
                self.scan(5, 2)
        finally:
            if self.timer.ident is not None:
                self.timer.join(1)
        self.assertEqual([event['status'] for event in events], ['RETRYING', 'CANCELLED'])
        self.assertLess(events[-1]['elapsed_seconds'], .4)
        self.assertEqual(events[-1]['exception_type'], 'FileNotFoundError')
        self.assertEqual(self.submitted, [])

    def test_exhausted_admission_and_normal_cli_never_read_control(self):
        write_json(self.pressure, dict(parallel_limit=2))
        original_open = Path.open
        reads = []

        def open_file(path, *args, **kwargs):
            if path == self.pressure:
                reads.append(len(self.submitted))
                self.assertEqual(reads, [0])
            return original_open(path, *args, **kwargs)

        with patch.object(Path, 'open', open_file):
            self.scan(2, 2)
            self.assertEqual(self.consumed, ['0', '1'])
            self.submitted.clear()
            self.consumed.clear()
            self.scan(3, 2, controlled=False)
        self.assertEqual(self.consumed, ['0', '1', '2'])
        self.assertEqual(self.submitted, self.consumed)

    def test_persistent_failure_reaps_running_owned_worker(self):
        write_json(self.pressure, dict(parallel_limit=2))
        ready = self.root / 'ready'
        worker_exit = []
        command = [sys.executable, '-c',
                   'from pathlib import Path; import sys,time; Path(sys.argv[1]).touch(); time.sleep(60)', str(ready)]
        original_open = Path.open

        def worker(argv, *, cancel_event, **kwargs):
            if Path(argv[-1]).name == '1.response.json':
                try:
                    execute(command, timeout=60, cancel_event=cancel_event)
                except KeyboardInterrupt:
                    worker_exit.append('cancelled')
                    raise
            end = time.monotonic() + 5
            while not ready.is_file() and time.monotonic() < end:
                time.sleep(.02)
            write_json(argv[-1], {})
            return SimpleNamespace(returncode=0, stderr='')

        def open_file(path, *args, **kwargs):
            if path == self.pressure and self.consumed:
                self.assertTrue(ready.is_file())
                raise PermissionError(13, 'worker still running', str(path))
            return original_open(path, *args, **kwargs)

        self.worker = worker
        started = time.monotonic()
        with patch.object(Path, 'open', open_file), self.assertRaises(ResourceControlError):
            self.scan(5, 2)
        self.assertEqual(worker_exit, ['cancelled'])
        self.assertEqual((self.submitted, self.consumed), (['0', '1'], ['0']))
        self.assertLess(time.monotonic() - started, 8)


def _hold_windows_file(path, share, held, release, released):
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                   ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateFileW(path, 0x80000000, share, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        held.set()
        release.wait(30)
    finally:
        kernel.CloseHandle(handle)
        released.set()


@contextmanager
def windows_file_holder(path, share=0):
    context = multiprocessing.get_context('spawn')
    held, release, released = context.Event(), context.Event(), context.Event()
    process = context.Process(target=_hold_windows_file, args=(str(path), share, held, release, released))
    process.start()
    try:
        if not held.wait(5):
            raise AssertionError(f'Windows file holder did not acquire {path}; exit={process.exitcode}')
        yield release, released
    finally:
        release.set()
        process.join(5)
        if process.is_alive():
            process.terminate()
            process.join(5)
        process.close()


@unittest.skipUnless(os.name == 'nt', 'requires real Windows file sharing modes')
class WindowsResourcePressureTests(unittest.TestCase):
    def setUp(self):
        self.scheduler = ResourcePressureTests()
        self.scheduler.setUp()
        self.addCleanup(self.scheduler.doCleanups)
        self.pressure = self.scheduler.pressure
        write_json(self.pressure, dict(parallel_limit=2))

    def test_real_exclusive_reader_recovers_after_release(self):
        events = []
        with windows_file_holder(self.pressure) as (release, released):
            def record(event):
                events.append(event)
                if event['status'] == 'RETRYING':
                    self.assertEqual(self.scheduler.submitted, [])
                    release.set()

            with patch('ecra.scan_diagnostics.record_resource_control', side_effect=record):
                self.scheduler.scan(5, 2)
            self.assertTrue(released.wait(1))
        self.assertEqual([event['status'] for event in events], ['RETRYING', 'RECOVERED'])
        self.assertEqual(events[0]['exception_type'], 'PermissionError')
        self.assertEqual(events[0]['errno'], 13)
        self.assertEqual(self.scheduler.consumed, [str(i) for i in range(5)])

    def test_real_exclusive_reader_held_until_terminal_failure(self):
        with windows_file_holder(self.pressure) as (_, released):
            with self.assertRaises(ResourceControlError) as raised:
                self.scheduler.scan(5, 2)
            self.assertFalse(released.is_set())
        self.assertIsInstance(raised.exception.__cause__, PermissionError)
        event = raised.exception.resource_control
        self.assertEqual(event['status'], 'FAILED')
        self.assertLess(event['elapsed_seconds'], 1)
        self.assertLessEqual(event['attempts'], 5)
        self.assertEqual(self.scheduler.submitted, [])

    def test_atomic_publication_keeps_old_json_while_replace_is_blocked(self):
        original_replace = Path.replace
        rejected, inspected = threading.Event(), threading.Event()
        errors = []

        def replace(path, target):
            try:
                return original_replace(path, target)
            except PermissionError:
                if target == self.pressure:
                    rejected.set()
                    self.assertTrue(inspected.wait(3))
                raise

        def publish():
            try:
                write_json(self.pressure, dict(parallel_limit=1))
            except Exception as exc:
                errors.append(exc)

        with windows_file_holder(self.pressure, share=1) as (release, released):
            with patch.object(Path, 'replace', replace):
                writer = threading.Thread(target=publish)
                writer.start()
                try:
                    self.assertTrue(rejected.wait(3))
                    self.assertEqual(read_json(self.pressure), dict(parallel_limit=2))
                    self.scheduler.scan(2, 2)
                    self.assertEqual(self.scheduler.consumed, ['0', '1'])
                    release.set()
                    self.assertTrue(released.wait(2))
                finally:
                    inspected.set()
                    writer.join(4)
                self.assertFalse(writer.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(read_json(self.pressure), dict(parallel_limit=1))
        self.assertFalse(self.pressure.with_suffix('.json.tmp').exists())


class ResourcePressurePublicationTests(unittest.TestCase):
    def test_canonical_failure_keeps_valid_pointer_and_diagnostics(self):
        from ecra.config import load_config
        from ecra.report_package import sha256
        from ecra.scan_persistence import run_canonical
        from ecra.workflow import output_path

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            root = base/'firmware'
            root.mkdir()
            (root/'main.c').write_text('int shared; int main(void){return ++shared;}\n', 'utf-8')
            build = base/'native-build'
            build.mkdir()
            database = build/'compile_commands.json'
            write_json(database, [dict(directory=str(root), file='main.c', arguments=['clang', '-c', 'main.c'])])
            data = base/'data'
            config = base/'semantics.yaml'
            write_json(config, dict(version=1, project=dict(root=str(root)),
                       analysis=dict(compile_database=str(database), output=dict(location='custom', custom_dir=str(data))),
                       review=dict(enabled=False, prepare_packets=False)))
            with redirect_stdout(io.StringIO()) as console:
                self.assertIn(run_canonical(root, config, no_review=True, scan_id='prior'), (0, 1, 2), console.getvalue())
            cfg, _ = load_config(root, config)
            previous = output_path(root, cfg)
            previous_hash = sha256(previous/'scan.db')
            pressure = base/'resource-pressure.json'
            original_open = Path.open
            with (patch.dict(os.environ, ECRA_RESOURCE_PRESSURE_FILE=str(pressure)),
                  patch.object(Path, 'open', self.denied_opener(original_open, pressure)),
                  redirect_stdout(io.StringIO()) as console):
                self.assertEqual(run_canonical(root, config, no_review=True, scan_id='denied'), 3, console.getvalue())
            out = data/'scans/denied'
            failure = read_json(out/'diagnostics/exception.json')
            self.assertEqual(failure['stage']['stage'], 'Clang 翻译单元提取')
            self.assertFalse(failure['analysis_valid'])
            self.assertEqual((failure['completed_units'], failure['total_units']), (0, 1))
            self.assertEqual(failure['resource_control']['errno'], 13)
            self.assertIn('open_file', (out/'diagnostics/exception.log').read_text('utf-8'))
            self.assertFalse(read_json(out/'result_validity.json')['analysis_valid'])
            self.assertFalse((out/'manifest.json').exists())
            self.assertFalse((out/'scan_state.json').exists())
            self.assertEqual(output_path(root, cfg), previous)
            self.assertEqual(sha256(previous/'scan.db'), previous_hash)

            with (patch.dict(os.environ, ECRA_RESOURCE_PRESSURE_FILE=str(pressure)),
                  patch.object(Path, 'open', self.denied_opener(original_open, pressure, diagnostics=True)),
                  redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as fallback):
                self.assertEqual(run_canonical(root, config, no_review=True, scan_id='no-diagnostic'), 3)
            self.assertIn('PermissionError', fallback.getvalue())
            self.assertIn('资源调度诊断写入失败', fallback.getvalue())
            self.assertFalse(read_json(data/'scans/no-diagnostic/result_validity.json')['analysis_valid'])
            self.assertEqual(output_path(root, cfg), previous)

    @staticmethod
    def denied_opener(original_open, pressure, *, diagnostics=False):
        def open_file(path, *args, **kwargs):
            if path == pressure or (diagnostics and path.name in {
                    'resource_control.jsonl', 'exception.log', 'exception.json.tmp', 'memory_profile.json.tmp'}):
                raise PermissionError(13, 'injected open failure', str(path))
            return original_open(path, *args, **kwargs)
        return open_file
