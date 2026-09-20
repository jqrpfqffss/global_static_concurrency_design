import unittest
from unittest.mock import patch

from ecra.common import replace_file


class AtomicOutputTests(unittest.TestCase):
    def windows_error(self, code):
        error = PermissionError('simulated file sharing denial')
        error.winerror = code
        return error

    def test_transient_windows_lock_retries_atomic_replace(self):
        with patch('ecra.common.Path.replace', side_effect=[self.windows_error(32), None]) as replace, \
                patch('ecra.common.time.sleep') as sleep:
            replace_file('temporary.json', 'destination.json')
        self.assertEqual(replace.call_count, 2)
        sleep.assert_called_once_with(0.05)

    def test_permanent_windows_denial_is_not_swallowed(self):
        with patch('ecra.common.Path.replace', side_effect=self.windows_error(5)) as replace, \
                patch('ecra.common.time.sleep') as sleep:
            with self.assertRaises(PermissionError):
                replace_file('temporary.json', 'destination.json')
        self.assertEqual(replace.call_count, 5)
        self.assertEqual(sleep.call_count, 4)

    def test_non_windows_permission_error_is_not_retried(self):
        with patch('ecra.common.Path.replace', side_effect=PermissionError('denied')) as replace, \
                patch('ecra.common.time.sleep') as sleep:
            with self.assertRaises(PermissionError):
                replace_file('temporary.json', 'destination.json')
        replace.assert_called_once()
        sleep.assert_not_called()
