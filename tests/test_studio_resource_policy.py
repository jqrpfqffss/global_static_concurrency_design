import tempfile
import unittest
from pathlib import Path

from ecra.common import read_json,write_json
from ecra.storage_activity import DataActivity
from ecra.studio.tasks import TaskManager
from ecra.studio.resource_policy import policy


class ResourcePolicyTests(unittest.TestCase):
    def test_host_commit_exhaustion_is_independent_of_free_physical_ram_and_unknown_metrics_are_not_zero(self):
        from ecra.studio.resource_policy import host_pressure
        gib=1024**3
        low=host_pressure(dict(system_physical_available_bytes=42*gib,system_commit_bytes=95*gib,system_commit_limit_bytes=96*gib))
        self.assertTrue(low['stop']);self.assertTrue(low['soft']);self.assertEqual(low['commit_headroom_bytes'],gib)
        self.assertIn('提交额度',low['reason'])
        soft=host_pressure(dict(system_physical_available_bytes=42*gib,system_commit_bytes=93*gib,system_commit_limit_bytes=96*gib))
        self.assertTrue(soft['soft']);self.assertFalse(soft['stop'])
        self.assertFalse(host_pressure(dict(system_physical_available_bytes=42*gib,system_commit_bytes=90*gib,system_commit_limit_bytes=96*gib))['soft'])
        unknown=host_pressure({});self.assertIsNone(unknown['commit_headroom_bytes']);self.assertFalse(unknown['metrics_available'])
        self.assertIsNone(host_pressure(dict(system_commit_bytes=10,system_commit_limit_bytes=2))['commit_headroom_bytes'])

    def test_child_temporary_files_ignore_inherited_firmware_temp_and_broker_environment_stays_unchanged(self):
        import json,os,subprocess,sys
        from ecra.studio.resource_policy import temporary_environment
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'firmware';source.mkdir();owned=root/'task';owned.mkdir()
            inherited=dict(os.environ,TEMP=str(source),TMP=str(source),TMPDIR=str(source),SQLITE_TMPDIR=str(source))
            updated=temporary_environment(owned,inherited)
            code='import tempfile,json,os; from pathlib import Path; f=tempfile.NamedTemporaryFile(delete=False); f.write(b"actual worker scratch"); f.close(); print(json.dumps(dict(path=f.name,temporary=tempfile.gettempdir(),env={k:os.environ[k] for k in ["TEMP","TMP","TMPDIR","SQLITE_TMPDIR"]})))'
            child=subprocess.run([sys.executable,'-B','-c',code],env=updated,capture_output=True,text=True)
            self.assertEqual(child.returncode,0,child.stderr);result=json.loads(child.stdout)
            self.assertTrue(os.path.samefile(Path(result['path']).parent,owned/'temporary'))
            self.assertTrue(all(Path(value).resolve()==(owned/'temporary').resolve() for value in result['env'].values()))
            self.assertEqual(Path(result['path']).read_bytes(),b'actual worker scratch')
            self.assertEqual(inherited['TEMP'],str(source));self.assertEqual(list(source.iterdir()),[])
            with self.assertRaises(FileExistsError):temporary_environment(owned,inherited)

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
