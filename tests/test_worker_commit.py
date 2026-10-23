"""End-to-end propagation of real Worker commit exhaustion to the parent CLI."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class WorkerCommitTests(unittest.TestCase):
    @unittest.skipUnless(os.name=='nt','Actual Windows Worker Job quota test')
    def test_actual_extractor_worker_oom_is_fatal_and_invalidates_previous_report(self):
        repo=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix='ecra worker commit ') as folder:
            evidence=Path(folder).resolve()/'worker'
            proc=subprocess.run([sys.executable,str(repo/'scripts/probe_worker_memory.py'),
                '--engine',str(repo),'--python',sys.executable,'--evidence',str(evidence),'--limit-mib','192'],
                capture_output=True,text=True,encoding='utf-8',timeout=60)
            self.assertEqual(proc.returncode,0,proc.stdout+proc.stderr)
            result=json.loads((evidence/'result.json').read_text(encoding='utf-8'))
            self.assertTrue(result['passed'])
            self.assertTrue(result['actual_worker_entry'])
            self.assertTrue(result['actual_clang_extraction_completed'])
            self.assertTrue(result['real_allocator_exhaustion'])
            self.assertFalse(result['experimental_extra_reserve'])
            self.assertNotEqual(result['worker_pid'],result['parent_pid'])
            self.assertEqual(result['worker_parse_status'],'FAILED')
            self.assertEqual(result['failed_cli_exit'],3)
            self.assertFalse(result['analysis_valid'])
            self.assertTrue(result['checkpoint_removed'])
            self.assertTrue(result['lock_removed'])
            self.assertGreaterEqual(result['worker_peak_memory']['peak_process_commit_bytes'],191*1024*1024)
