from contextlib import ExitStack
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from ecra.common import read_json,write_json
from ecra.storage_activity import DataActivity
from ecra.studio.tasks import TaskManager
from ecra.studio.resource_policy import policy


class ResourcePolicyTests(unittest.TestCase):
    def test_initial_publication_failure_never_spawns_or_releases_gate(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            data, firmware = root/'data', root/'firmware'
            firmware.mkdir()
            config = root/'semantics.yaml'
            write_json(config, dict(version=1, project=dict(root=str(firmware)),
                       analysis=dict(output=dict(location='custom', custom_dir=str(data)))))
            manager = TaskManager(data)

            def publish(path, value, **kwargs):
                if path.name == 'resource-pressure.json':
                    raise PermissionError(13, 'initial publish denied', str(path))
                return write_json(path, value, **kwargs)

            with (patch('ecra.studio.tasks.write_json', side_effect=publish),
                  patch('ecra.scan_diagnostics.memory', return_value={}),
                  patch('ecra.studio.tasks.ProcessBudget') as budget,
                  patch('ecra.studio.tasks.subprocess.Popen') as popen,
                  patch('ecra.studio.write_guard.OwnedProcess') as owned):
                with self.assertRaisesRegex(ValueError, '资源调度信息初始化失败'):
                    manager.start(config, profile_id='profile')
            for launch in (budget, popen, owned):
                launch.assert_not_called()
            record, = manager.list()
            task = manager.work/record['id']
            self.assertEqual(record['state'], 'FAILED')
            self.assertIn('initial publish denied', record['error'])
            self.assertIn('initial publish denied', (task/'supervisor.log').read_text('utf-8'))
            self.assertFalse((task/'start').exists())
            self.assertFalse((task/'worker-result.json').exists())
            self.assertIsNone(manager.active)
            with DataActivity(data, exclusive=True, purpose='scan-budget'):
                pass

    def test_failed_publication_does_not_skip_any_resource_stop_or_diagnostics(self):
        gib = 1024**3
        cases = (
            ('进程树', {'private_bytes': 15*gib}, {}, gib, False),
            ('提交额度', {}, {'system_commit_limit_bytes': 16*gib, 'system_commit_bytes': 15*gib}, gib, False),
            ('物理内存', {}, {'system_commit_limit_bytes': 16*gib, 'system_commit_bytes': 13*gib,
                           'system_physical_available_bytes': gib//4}, gib, False),
            ('可用空间', {}, {}, 0, False),
            ('进程树', {'private_bytes': 15*gib}, {}, gib, True),
        )
        for reason, job, host, disk, deny_stop in cases:
            with self.subTest(reason=reason, deny_stop=deny_stop), tempfile.TemporaryDirectory() as folder:
                manager = TaskManager(Path(folder).resolve())
                task = manager.work/'worker'
                task.mkdir()
                limits = policy()
                value = dict(id='worker', scan_id='scan', mode='scan', state='RUNNING', started='now',
                             resource_policy=limits, budget_bytes=limits['peak_bytes'], samples=[])
                if not deny_stop:
                    write_json(task/'worker-result.json', dict(exit_code=130, operation_completed=False, error=None))
                process = Mock(returncode=3 if deny_stop else 130)
                process.poll.side_effect = [None, process.returncode]
                budget = Mock()
                budget.sample.return_value = job
                original_write = Path.write_text

                def publish(path, payload):
                    if path.name == 'resource-pressure.json':
                        raise PermissionError(13, 'publish denied', str(path))
                    write_json(path, payload)

                def write_file(path, *args, **kwargs):
                    if deny_stop and path == task/'stop':
                        raise PermissionError(13, 'stop denied', str(path))
                    return original_write(path, *args, **kwargs)

                with (patch('ecra.studio.tasks.write_json', side_effect=publish),
                      patch('ecra.studio.tasks.terminate_owned') as terminate,
                      patch('ecra.studio.tasks.shutil.disk_usage', return_value=SimpleNamespace(free=disk)),
                      patch('ecra.scan_diagnostics.memory', return_value=host),
                      patch.object(Path, 'write_text', write_file)):
                    manager.monitor(task, value, process, budget, None, ExitStack())
                record = read_json(task/'task.json')
                sample = json.loads((task/'resources.jsonl').read_text('utf-8'))
                self.assertIn('publish denied', sample['pressure_publish_error'])
                self.assertIn(reason, record['error'])
                self.assertIn('publish denied', (task/'supervisor.log').read_text('utf-8'))
                if deny_stop:
                    terminate.assert_called_once_with(process, budget)
                    self.assertEqual(record['state'], 'FAILED')
                    self.assertIn('stop denied', record['error'])
                    self.assertNotIn('已请求安全停止', record['error'])
                    self.assertFalse((task/'stop').exists())
                else:
                    terminate.assert_not_called()
                    self.assertEqual(record['state'], 'INTERRUPTED')
                    self.assertIn('已请求安全停止', record['error'])
                    self.assertTrue((task/'stop').is_file())

    def test_profile_workers_are_used_unless_user_overrides_and_low_memory_still_limits(self):
        self.assertEqual(policy({'preset':'auto'},configured_workers=7)['workers'],7)
        self.assertEqual(policy({'workers':2},configured_workers=7)['workers'],2)
        self.assertEqual(policy({'preset':'low'},configured_workers=7)['workers'],1)
        with self.assertRaises(ValueError):policy({},configured_workers=True)

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
            write_json(path,dict(id='a',scan_id='a',mode='scan',state='RUNNING',started='now'))
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
