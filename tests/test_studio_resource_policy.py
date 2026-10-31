import tempfile
import unittest
from pathlib import Path

from ecra.common import read_json,write_json
from ecra.storage_activity import DataActivity
from ecra.studio.tasks import TaskManager
from ecra.studio.resource_policy import policy


class ResourcePolicyTests(unittest.TestCase):
    def test_other_studio_cannot_mark_owned_running_task_interrupted(self):
        with tempfile.TemporaryDirectory() as folder:
            data=Path(folder);path=data/'work/tasks/a/task.json';path.parent.mkdir(parents=True)
            write_json(path,dict(id='a',state='RUNNING',started='now'))
            with DataActivity(data,exclusive=True,purpose='scan-budget'):
                TaskManager(data)
                self.assertEqual(read_json(path)['state'],'RUNNING')
                with self.assertRaises(ValueError):
                    with DataActivity(data,exclusive=True,purpose='scan-budget'):pass
            TaskManager(data)
            self.assertEqual(read_json(path)['state'],'INTERRUPTED')

    def test_resource_presets_and_manual_bounds(self):
        self.assertEqual(policy()['peak_bytes'],16*1024**3)
        self.assertEqual(policy(dict(preset='low',workers=8))['workers'],1)
        self.assertEqual(policy(dict(preset='manual',peak_gib=12,workers=3))['soft_bytes'],9*1024**3)
        for value in [dict(preset='unknown'),dict(preset='manual',peak_gib=200),dict(workers=0),dict(workers=True)]:
            with self.assertRaises(ValueError):policy(value)
