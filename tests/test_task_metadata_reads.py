import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ecra.studio.tasks import read_task_json


class TaskMetadataReadTests(unittest.TestCase):
    def test_transient_permission_error_recovers_real_bytes_and_permanent_error_is_bounded(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'task.json';raw=b'{"state":"COMPLETE","published":true}';path.write_bytes(raw)
            from ecra.common import read_json
            with patch('ecra.studio.tasks.read_json',side_effect=[PermissionError('sharing'),PermissionError('sharing'),read_json(path)]) as read:
                self.assertEqual(read_task_json(path),dict(state='COMPLETE',published=True));self.assertEqual(read.call_count,3)
            with patch('ecra.studio.tasks.read_json',side_effect=PermissionError('permanent')) as read:
                with self.assertRaises(PermissionError):read_task_json(path)
                self.assertEqual(read.call_count,5)
            self.assertEqual(path.read_bytes(),raw)

    def test_corrupt_or_missing_metadata_is_never_retried_or_replaced_with_stale_data(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'task.json';path.write_bytes(b'{broken')
            with patch('ecra.studio.tasks.time.sleep') as sleep:
                with self.assertRaises(json.JSONDecodeError):read_task_json(path)
                sleep.assert_not_called()
                with self.assertRaises(FileNotFoundError):read_task_json(path.with_name('missing.json'))
                sleep.assert_not_called()
