"""Test-controller failures must stay failures and retain active fixture data."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from ecra.storage_activity import DataActivity
from tests.async_jobs import wait_task,stop_and_settle_tasks,cleanup_temporary


class Client:
    def __init__(self, manager, *, stop_status=200):
        self.manager=manager;self.stop_status=stop_status;self.state='RUNNING';self.posts=[]
    def get(self,path):
        return SimpleNamespace(status_code=200,text='status',json=lambda:dict(state=self.state))
    def post(self,path):
        self.posts.append(path)
        if self.stop_status==200:
            self.state='INTERRUPTED';self.manager.active=None
        return SimpleNamespace(status_code=self.stop_status,text='stop')


class AsyncJobControllerTests(unittest.TestCase):
    def test_timeout_is_not_a_completed_result(self):
        manager=SimpleNamespace(active=('owned',));client=Client(manager)
        with self.assertRaisesRegex(AssertionError,'real terminal state'):
            wait_task(client,manager,'owned',timeout=0)
        self.assertEqual(client.state,'RUNNING');self.assertIsNotNone(manager.active)

    def test_failure_cleanup_uses_stop_and_keeps_interruption_separate_from_success(self):
        manager=SimpleNamespace(active=('owned',));client=Client(manager);case=SimpleNamespace()
        stop_and_settle_tasks(case,client,manager)
        self.assertIn('/api/tasks/owned/stop',client.posts)
        self.assertEqual(client.state,'INTERRUPTED');self.assertIsNone(manager.active)
        self.assertFalse(getattr(case,'_retain_async_root',False))
        manager.active=('owned',);denied=Client(manager,stop_status=400)
        with self.assertRaisesRegex(AssertionError,'could not request product stop'):
            stop_and_settle_tasks(case,denied,manager)
        self.assertTrue(case._retain_async_root)

    def test_real_active_lease_prevents_temporary_directory_deletion(self):
        temporary=tempfile.TemporaryDirectory(prefix='async cleanup lease ')
        self.addCleanup(temporary.cleanup)
        root=Path(temporary.name);data=root/'data';original=root/'original.bin';original.write_bytes(b'preserved')
        case=SimpleNamespace(data=data,base=root)
        with DataActivity(data,exclusive=True,purpose='scan-budget'),patch('tests.async_jobs.CLEANUP_SECONDS',0):
            with self.assertRaisesRegex(AssertionError,'live owner'):
                cleanup_temporary(case,temporary)
            self.assertTrue(root.is_dir());self.assertEqual(original.read_bytes(),b'preserved')


if __name__=='__main__':unittest.main()
