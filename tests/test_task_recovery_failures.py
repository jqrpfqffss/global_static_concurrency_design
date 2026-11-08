"""Damaged operational receipts must not conceal valid evidence or live state."""
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from fastapi.testclient import TestClient

from ecra.common import read_json, write_json
from ecra.data_transfer import registry
from ecra.studio.root_transfers import RootTransfers
from ecra.studio.server import create_app
from ecra.studio.tasks import TaskManager


class TaskRecoveryFailureTests(unittest.TestCase):
    def test_corrupt_and_wrong_shape_records_do_not_block_startup_or_valid_history(self):
        for raw in (b'{truncated', b'null', b'[]', b'{}', b'{"id":"bad","state":[],"started":"now"}',
                    b'{"id":"bad","state":"FAILED","started":"now"}',
                    b'{"id":"bad","state":"FAILED","started":"now","mode":"scan","scan_id":[]}',
                    b'{"id":"bad","state":"FAILED","started":"now","mode":"unknown","scan_id":"scan"}'):
            with self.subTest(raw=raw), tempfile.TemporaryDirectory() as temporary:
                data=Path(temporary);bad=data/'work/tasks/bad/task.json';bad.parent.mkdir(parents=True)
                bad.write_bytes(raw)
                good=data/'work/tasks/good/task.json';good.parent.mkdir()
                write_json(good,dict(id='good',scan_id='scan',mode='scan',state='RUNNING',started='now'))
                manager=TaskManager(data)
                rows={item['id']:item for item in manager.list()}
                self.assertEqual(rows['good']['state'],'INTERRUPTED')
                self.assertEqual(rows['bad']['state'],'UNREADABLE')
                self.assertTrue(rows['bad']['metadata_error'])
                self.assertIn(str(bad.resolve()),rows['bad']['error'])
                self.assertIn('重新发起任务',rows['bad']['error'])
                self.assertEqual(manager.detail('bad')['state'],'UNREADABLE')
                self.assertEqual(bad.read_bytes(),raw)

    def test_corrupt_task_and_transfer_history_keep_studio_and_saved_results_accessible(self):
        with tempfile.TemporaryDirectory() as temporary:
            data=Path(temporary)/'data'
            app=create_app(data,token='test',authority='testserver')
            headers={'x-ecra-session':'test','origin':'http://testserver'}
            with TestClient(app,headers=headers) as client:
                sample=client.post('/api/sample/open',json={})
                self.assertEqual(sample.status_code,200,sample.text)
                scan=sample.json()['scan_id']
                summary=client.get('/api/scans/'+scan+'/summary').json()
            raw=b'{incomplete task'
            task=data/'work/tasks/broken/task.json';task.parent.mkdir(parents=True);task.write_bytes(raw)
            folder=registry(data);folder.mkdir(parents=True,exist_ok=True)
            transfer=folder/'job-broken.json';transfer.write_bytes(raw)
            reopened=create_app(data,token='test',authority='testserver')
            with TestClient(reopened,headers=headers) as client:
                self.assertEqual(client.get('/api/bootstrap').status_code,200)
                tasks=client.get('/api/tasks');self.assertEqual(tasks.status_code,200,tasks.text)
                self.assertTrue(tasks.json()['items'][0]['metadata_error'])
                detail=client.get('/api/tasks/broken');self.assertEqual(detail.status_code,200,detail.text)
                self.assertEqual(detail.json()['state'],'UNREADABLE')
                self.assertEqual(client.post('/api/tasks/broken/stop',json={}).status_code,400)
                self.assertEqual(client.post('/api/tasks/broken/retry',json={}).status_code,400)
                self.assertIsNone(reopened.state.task_manager.active)
                self.assertFalse((task.parent/'stop').exists())
                history=client.get('/api/data-transfers');self.assertEqual(history.status_code,200,history.text)
                self.assertEqual(history.json()['items'][0]['state'],'UNREADABLE')
                self.assertEqual(client.get('/api/data-transfers/broken').json()['state'],'UNREADABLE')
                self.assertEqual(client.post('/api/data-transfers/broken/resume',json={}).status_code,400)
                after=client.get('/api/scans/'+scan+'/summary')
                self.assertEqual(after.status_code,200,after.text)
                self.assertEqual(after.json(),summary)
            self.assertEqual(task.read_bytes(),raw);self.assertEqual(transfer.read_bytes(),raw)

    def test_transfer_valid_running_sibling_is_recovered_without_rewriting_broken_record(self):
        with tempfile.TemporaryDirectory() as temporary:
            data=Path(temporary)/'data';folder=registry(data);folder.mkdir(parents=True)
            bad=folder/'job-bad.json';bad.write_bytes(b'[]')
            good=folder/'job-good.json';write_json(good,dict(id='good',state='COPYING',started='now',source=str(data),target=str(data.parent/'copy')))
            transfers=RootTransfers(data)
            self.assertEqual(transfers.get('good')['state'],'INTERRUPTED')
            self.assertEqual(transfers.get('bad')['state'],'UNREADABLE')
            self.assertEqual(len(transfers.history()),2)
            self.assertEqual(bad.read_bytes(),b'[]')

    def test_publishing_supervisor_crash_is_interrupted_with_original_recovery_journal(self):
        with tempfile.TemporaryDirectory() as temporary:
            data=Path(temporary)/'data';folder=registry(data);folder.mkdir(parents=True)
            journal=folder/'publication-journal.json';raw=b'{"state":"PUBLISHING","preserve":"original"}';journal.write_bytes(raw)
            good=folder/'job-good.json'
            write_json(good,dict(id='good',state='PUBLISHING',started='now',source=str(data),
                                 target=str(data.parent/'copy'),journal=str(journal)))
            transfers=RootTransfers(data);saved=transfers.get('good')
            self.assertEqual(saved['state'],'INTERRUPTED')
            self.assertEqual(saved['journal'],str(journal))
            self.assertEqual(journal.read_bytes(),raw)

    def test_exited_worker_with_unverifiable_receipt_never_stays_running_or_reports_success(self):
        receipts=(None,b'{truncated',b'[]',b'{}',b'{"exit_code":1,"operation_completed":true}',
                  b'{"exit_code":0,"operation_completed":"yes"}',
                  b'{"exit_code":0,"operation_completed":true,"error":"worker failed"}')
        for receipt in receipts:
            with self.subTest(receipt=receipt),tempfile.TemporaryDirectory() as temporary:
                data=Path(temporary);manager=TaskManager(data)
                task=manager.work/'worker';task.mkdir()
                value=dict(id='worker',scan_id='scan',mode='scan',state='RUNNING',started='now')
                write_json(task/'task.json',value)
                published=data/'scans/scan/manifest.json';published.parent.mkdir(parents=True)
                published.write_text('published marker','utf-8')
                if receipt is not None:(task/'worker-result.json').write_bytes(receipt)
                process=SimpleNamespace(returncode=0,poll=lambda:0)
                manager.active=('worker',process,None)
                closed=[];ownership=ExitStack();ownership.callback(lambda:closed.append(True))
                manager.monitor(task,value,process,None,None,ownership)
                saved=read_json(task/'task.json')
                self.assertEqual(saved['state'],'FAILED');self.assertTrue(saved['published'])
                self.assertIn('完成状态未能校验',saved['error'])
                self.assertIsNone(manager.active);self.assertEqual(closed,[True])
                if receipt is not None:self.assertEqual((task/'worker-result.json').read_bytes(),receipt)

    def test_valid_receipt_finishes_and_missing_log_does_not_hide_failure_or_retry_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            data=Path(temporary);manager=TaskManager(data);task=manager.work/'worker';task.mkdir()
            value=dict(id='worker',scan_id='scan',mode='scan',state='RUNNING',started='now')
            published=data/'scans/scan/manifest.json';published.parent.mkdir(parents=True);published.write_text('{}')
            write_json(task/'worker-result.json',dict(exit_code=2,operation_completed=True,error=None))
            manager.monitor(task,value,SimpleNamespace(returncode=2,poll=lambda:2),None,None,ExitStack())
            detail=manager.detail('worker')
            self.assertEqual(detail['state'],'COMPLETE')
            self.assertIn('任务日志无法读取',detail['log']['error'])
            self.assertEqual(detail['log']['text'],'')

    def test_malformed_precheck_receipt_is_a_terminal_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            data=Path(temporary);manager=TaskManager(data);task=manager.work/'worker';task.mkdir()
            value=dict(id='worker',scan_id='scan',mode='precheck',state='RUNNING',started='now')
            write_json(task/'worker-result.json',dict(exit_code=0,operation_completed=True,error=None))
            (task/'preflight').mkdir();(task/'preflight/preflight.json').write_text('[]')
            manager.monitor(task,value,SimpleNamespace(returncode=0,poll=lambda:0),None,None,ExitStack())
            saved=read_json(task/'task.json')
            self.assertEqual(saved['state'],'FAILED');self.assertIn('编译输入检查收据字段无效',saved['error'])
            detail=manager.detail('worker')
            self.assertEqual(detail['state'],'FAILED')
            self.assertIn('任务诊断无法读取',detail['diagnostic_errors'][0])

    def test_corrupt_diagnostic_preserves_task_state_logs_and_other_diagnostics(self):
        with tempfile.TemporaryDirectory() as temporary:
            data=Path(temporary);manager=TaskManager(data);task=manager.work/'worker';task.mkdir()
            write_json(task/'task.json',dict(id='worker',scan_id='scan',mode='scan',state='FAILED',started='now'))
            (task/'console.log').write_text('actual log','utf-8')
            diagnostics=data/'scans/scan/diagnostics';diagnostics.mkdir(parents=True)
            raw=b'{truncated';(diagnostics/'scan_stages.json').write_bytes(raw)
            write_json(diagnostics/'exception.json',dict(message='actual failure'))
            detail=manager.detail('worker')
            self.assertEqual(detail['state'],'FAILED');self.assertEqual(detail['log']['text'],'actual log')
            self.assertEqual(detail['failure']['message'],'actual failure')
            self.assertIn('scan_stages.json',detail['diagnostic_errors'][0])
            self.assertNotIn('stages',detail)
            self.assertEqual((diagnostics/'scan_stages.json').read_bytes(),raw)


if __name__=='__main__':unittest.main()
