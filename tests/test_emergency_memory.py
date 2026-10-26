"""Exercise real allocator exhaustion, beyond a mock MemoryError exception."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from ecra.emergency_memory import CommitReserve, python_reserve
from ecra.scan_diagnostics import memory


class EmergencyMemoryTests(unittest.TestCase):
    def test_small_object_reserve_is_independent_of_analysis(self):
        first, second = python_reserve(), python_reserve()
        self.assertIsNot(first, second)
        self.assertGreater(len(first), 7000)
        self.assertTrue(any(type(value) is object for value in first))
        self.assertTrue(any(type(value) is float for value in first))
        self.assertTrue(any(type(value) is bytes and len(value) >= 400 for value in first))

    def test_private_commit_is_returned_and_close_is_idempotent(self):
        before = memory()
        reserve = CommitReserve()
        allocated = memory()
        reserve.close()
        reserve.close()
        after = memory()
        if os.name == 'nt':
            self.assertGreaterEqual(allocated['private_bytes']-before['private_bytes'], 7*1024*1024)
            self.assertGreaterEqual(allocated['private_bytes']-after['private_bytes'], 7*1024*1024)

    @unittest.skipUnless(os.name == 'nt', 'Actual Windows Job commit-limit test')
    def test_main_and_worker_diagnostics_at_actual_commit_exhaustion(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix='ecra real memory failure ') as folder:
            for origin in ('MAIN', 'WORKER'):
                with self.subTest(origin=origin):
                    evidence = Path(folder)/origin
                    proc = subprocess.run([sys.executable, str(root/'scripts/probe_diagnostic_memory.py'),
                        '--engine', str(root), '--python', sys.executable, '--evidence', str(evidence),
                        '--origin', origin, '--limit-mib', '128'], capture_output=True, text=True,
                        encoding='utf-8', timeout=60)
                    self.assertEqual(proc.returncode, 0, proc.stdout+proc.stderr)
                    result = json.loads((evidence/'result.json').read_text(encoding='utf-8'))
                    self.assertTrue(result['diagnostic_handling_complete'])
                    self.assertFalse(result['full_scan_acceptance'])
                    self.assertFalse(result['experimental_private_and_python_reserves'])
                    self.assertEqual(result['origin'], origin)
                    self.assertGreaterEqual(result['memory']['peak_process_commit_bytes'], 127*1024*1024)
                    info = json.loads((evidence/'diagnostics/exception.json').read_text(encoding='utf-8'))
                    self.assertEqual(info['origin'], origin)
                    self.assertEqual(info['exception_type'], 'MemoryError')
                    self.assertFalse(info['analysis_valid'])

    @unittest.skipUnless(os.name == 'nt', 'Actual Windows Job commit-limit CLI test')
    def test_real_cli_commit_exhaustion_invalidates_previous_report(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix='ecra real cli memory failure ') as folder:
            evidence = Path(folder)/'cli'
            proc = subprocess.run([sys.executable, str(root/'scripts/probe_diagnostic_memory.py'),
                '--engine', str(root), '--python', sys.executable, '--evidence', str(evidence),
                '--cli', '--limit-mib', '192', '--setup-timeout-seconds', '180'],
                capture_output=True, text=True, encoding='utf-8', timeout=240)
            self.assertEqual(proc.returncode, 0, proc.stdout+proc.stderr)
            result = json.loads((evidence/'result.json').read_text(encoding='utf-8'))
            self.assertTrue(result['actual_clang_fixture'])
            self.assertTrue(result['prior_success'])
            self.assertTrue(result['failed_report_invalid'])
            self.assertTrue(result['checkpoint_removed'])
            self.assertTrue(result['lock_removed'])
            self.assertEqual(result['cli_exit_code'], 3)


if __name__ == '__main__':
    unittest.main()
