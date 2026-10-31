import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from ecra import garbage_collection as gc
from ecra.studio.cleanup_jobs import CleanupJobs
from ecra.storage_activity import DataActivity
from tests import test_garbage_collection as fixtures


class CleanupJobTests(unittest.TestCase):
    def test_other_instance_preserves_running_owner_and_restart_exposes_recovery(self):
        with tempfile.TemporaryDirectory() as folder:
            data=Path(folder);registry=CleanupJobs(data)
            with registry.connect() as conn:
                conn.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?)',('a','now','quarantine','preview','RUNNING',None))
            with DataActivity(data,exclusive=True,purpose='cleanup-job'):
                self.assertEqual(CleanupJobs(data).get('a')['state'],'RUNNING')
            self.assertEqual(CleanupJobs(data).get('a')['state'],'INTERRUPTED')

    def test_real_process_death_during_quarantine_registry_can_restore_after_restart(self):
        fixture=fixtures.GarbageCollectionTests();fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        plan=gc.preview(fixture.data)
        code='''from pathlib import Path
import os,sys,time
from ecra.studio.cleanup_jobs import CleanupJobs
original=Path.rename
def crash(path,target):
 result=original(path,target)
 if '/trash/' in Path(target).as_posix():os._exit(99)
 return result
Path.rename=crash
registry=CleanupJobs(Path(sys.argv[1]));registry.start('quarantine',sys.argv[2])
while True:time.sleep(.1)
'''
        result=subprocess.run([sys.executable,'-B','-c',code,str(fixture.data),plan['id']],capture_output=True,timeout=30)
        self.assertEqual(result.returncode,99,result.stderr)
        registry=CleanupJobs(fixture.data)
        interrupted=registry.history()['items'][0]
        self.assertEqual(interrupted['state'],'INTERRUPTED');self.assertEqual(interrupted['preview_id'],plan['id'])
        self.assertEqual(gc.status(fixture.data,plan['id'])['state'],'MOVING')
        job=registry.start('restore',plan['id']);deadline=time.monotonic()+10
        while registry.get(job['id'])['state']=='RUNNING':
            self.assertLess(time.monotonic(),deadline);time.sleep(.02)
        self.assertEqual(registry.get(job['id'])['state'],'COMPLETE')
        self.assertTrue(fixture.discard.is_file());self.assertTrue(fixture.kept.is_file())
