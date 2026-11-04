import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ecra.studio.tasks import read_task_json


class TaskMetadataReadTests(unittest.TestCase):
    def test_review_uses_its_own_real_counters_instead_of_old_scan_or_preflight_progress(self):
        from ecra.common import write_json
        from ecra.studio.tasks import TaskManager
        with tempfile.TemporaryDirectory() as folder:
            data=Path(folder);manager=TaskManager(data);task=manager.work/'review1';task.mkdir()
            (task/'console.log').write_text('actual review log','utf-8')
            old=data/'scans/static1/diagnostics';old.mkdir(parents=True)
            write_json(old/'scan_progress.json',dict(completed_units=388,total_units=388))
            write_json(old/'tu_cache.json',dict(hits=388))
            (task/'preflight').mkdir();write_json(task/'preflight/preflight.json',dict(passed=True))
            for mode in ('review','review-failed'):
                write_json(task/'task.json',dict(id='review1',scan_id='static1',mode=mode,state='COMPLETE',started='now'))
                detail=manager.detail('review1');self.assertEqual(detail['progress_kind'],'AI_REVIEW')
                self.assertNotIn('progress',detail);self.assertNotIn('tu_cache',detail);self.assertNotIn('preflight',detail)
                own=task/'review-diagnostics';own.mkdir(exist_ok=True)
                write_json(own/'scan_progress.json',dict(completed_units=2,total_units=6))
                self.assertEqual(manager.detail('review1')['progress'],dict(completed_units=2,total_units=6))
                (own/'scan_progress.json').unlink()

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
