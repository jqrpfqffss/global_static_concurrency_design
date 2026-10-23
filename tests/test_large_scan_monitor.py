import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts.large_stm32_scan import monitor_sample


class LargeScanMonitorTests(unittest.TestCase):
    def test_resource_exhaustion_does_not_abandon_child_and_sampling_can_resume(self):
        with tempfile.TemporaryDirectory() as folder:
            errors=Path(folder)/'monitor_errors.log'
            cases=[MemoryError()]
            for number in (8,14,1455):
                error=OSError('Windows resource exhaustion')
                error.winerror=number
                cases.append(error)
            for error in cases:
                with self.subTest(type=type(error).__name__,winerror=getattr(error,'winerror',None)), \
                        patch('scripts.large_stm32_scan.collect',side_effect=[error,None]) as collect:
                    reserve=[bytearray(100)]
                    self.assertFalse(monitor_sample(None,0,{},None,None,errors,reserve=reserve))
                    self.assertEqual(reserve,[])
                    self.assertTrue(monitor_sample(None,0,{},None,None,errors))
                    self.assertEqual(collect.call_count,2)
            self.assertEqual(len(errors.read_text(encoding='utf-8').splitlines()),4)
            self.assertIn('1455',errors.read_text(encoding='utf-8'))

    def test_unrelated_oserror_remains_visible(self):
        error=OSError('Access denied')
        error.winerror=5
        with patch('scripts.large_stm32_scan.collect',side_effect=error),self.assertRaises(OSError):
            monitor_sample(None,0,{},None,None,Path('unused-monitor-error.log'))
