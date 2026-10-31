import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from ecra.common import write_json
from ecra.lock_owner import abandoned,process_identity
from ecra.scan_persistence import project_scan_lock
from ecra.workspace import WorkspaceResolver,lock_path


class LockOwnerTests(unittest.TestCase):
    def test_unknown_or_live_owners_are_not_reclaimed_and_pid_reuse_is_distinct(self):
        with patch('ecra.lock_owner.process_identity',return_value=None):
            self.assertFalse(abandoned(dict(pid=123,creation_filetime=100)))
        with patch('ecra.lock_owner.process_identity',return_value=100):
            self.assertFalse(abandoned(dict(pid=123,creation_filetime=100)))
            self.assertTrue(abandoned(dict(pid=123,creation_filetime=99)))
            self.assertFalse(abandoned(dict(pid=123,started='unparseable')))
        with patch('ecra.lock_owner.process_identity',return_value=False):
            self.assertTrue(abandoned(dict(pid=123)))

    @unittest.skipUnless(os.name=='nt','actual Windows process identity')
    def test_real_process_exit_lock_recovery_preserves_receipt_and_live_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder).resolve();root=base/'firmware';root.mkdir()
            data=base/'data';analysis=dict(output=dict(location='custom',custom_dir=str(data)))
            ws=WorkspaceResolver.resolve(root,analysis).initialize();ws.bind(analysis)
            path=lock_path(root,analysis)
            self.assertIsInstance(process_identity(os.getpid()),int)
            code='''from pathlib import Path
import json,os,sys
from ecra.workspace import WorkspaceResolver
from ecra.scan_persistence import project_scan_lock
root=Path(sys.argv[1]);analysis=json.loads(sys.argv[2]);WorkspaceResolver.resolve(root,analysis).initialize().bind(analysis)
with project_scan_lock(root,analysis):os._exit(99)
'''
            import json
            child=subprocess.run([sys.executable,'-B','-c',code,str(root),json.dumps(analysis)],capture_output=True,timeout=30)
            self.assertEqual(child.returncode,99,child.stderr)
            original=path.read_bytes()
            with project_scan_lock(root,analysis):
                with self.assertRaisesRegex(ValueError,'无法证明过期'):
                    with project_scan_lock(root,analysis):pass
            self.assertFalse(path.exists())
            backups=list(path.parent.glob('scan.lock.recovered-*.json'))
            self.assertEqual(len(backups),1);self.assertEqual(backups[0].read_bytes(),original)
