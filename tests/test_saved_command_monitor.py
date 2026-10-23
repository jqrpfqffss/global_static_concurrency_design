"""Test-only monitor fault injection; the real child must still finish."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import large_stm32_scan as monitor
from scripts.validate_saved_commands import run_command


@unittest.skipUnless(importlib.util.find_spec('psutil'), 'Optional external monitor dependency')
class SavedCommandMonitorTests(unittest.TestCase):
    def test_resource_sample_failure_keeps_waiting_and_records_actual_child_exit(self):
        error=OSError('Injected collector resource failure')
        error.winerror=1455
        for failure in (MemoryError('Injected collector failure'),error):
            with self.subTest(type=type(failure).__name__),tempfile.TemporaryDirectory() as folder:
                folder=Path(folder)
                original=monitor.collect
                calls=0
                def collect(*args,**kwargs):
                    nonlocal calls
                    calls+=1
                    if calls==1:
                        raise failure
                    return original(*args,**kwargs)
                with patch.dict(sys.modules,{'large_stm32_scan':monitor}),patch.object(monitor,'collect',side_effect=collect):
                    result=run_command([sys.executable,'-c','import time;time.sleep(.8);print("child-complete")'],folder,'report')
                saved=json.loads((folder/'report-execution.json').read_text(encoding='utf-8'))
                self.assertEqual(saved['exit_code'],0)
                self.assertEqual(saved['pid'],result['pid'])
                self.assertEqual(saved['status'],'COMPLETE')
                self.assertTrue(saved['measurement_gap'])
                self.assertIn('child-complete',(folder/'report.log').read_text())

    def test_unrelated_monitor_failure_never_claims_complete_or_invents_exit(self):
        import psutil
        error=OSError('Injected collector access failure')
        error.winerror=5
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder)
            with patch.dict(sys.modules,{'large_stm32_scan':monitor}), \
                    patch.object(monitor,'collect',side_effect=error),self.assertRaises(OSError):
                run_command([sys.executable,'-c','import time;time.sleep(.8)'],folder,'report')
            saved=json.loads((folder/'report-execution.json').read_text(encoding='utf-8'))
            self.assertEqual(saved['status'],'MONITOR_FAILED')
            self.assertIsNone(saved['exit_code'])
            self.assertTrue(saved['exit_status_unknown'])
            self.assertIn('Injected collector access failure',saved['traceback'])
            # Wait for the owned child. Do not leave a test process behind.
            try:
                child=psutil.Process(saved['pid'])
                if child.create_time()==saved['created_unix']:
                    child.wait(timeout=5)
            except psutil.NoSuchProcess:
                pass
