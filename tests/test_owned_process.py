"""Real Windows venv redirector, descendants and bounded allocator failure."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from ecra.studio.process_budget import ProcessBudget
from ecra.studio.write_guard import OwnedProcess


@unittest.skipUnless(os.name=='nt','Actual Windows Job and venv redirector required')
class OwnedProcessTests(unittest.TestCase):
    def test_file_gate_does_not_retroactively_own_a_venv_child_created_before_job_assignment(self):
        # Reproduce only the launcher race, with a waiting child and no memory
        # stress. Never rerun the old uncontrolled exhaustion experiment.
        with tempfile.TemporaryDirectory(prefix='ECRA late Job 中文 ') as folder:
            root=Path(folder).resolve();venv=root/'venv'
            subprocess.run([getattr(sys,'_base_executable',sys.executable),'-m','venv','--without-pip',str(venv)],check=True,capture_output=True)
            code='''import json,os,sys,time
from pathlib import Path
root=Path(sys.argv[1]);(root/'ready.json').write_text(json.dumps(dict(pid=os.getpid())))
deadline=time.monotonic()+15
while not (root/'release').is_file() and time.monotonic()<deadline:time.sleep(.02)
'''
            budget=ProcessBudget(128*1024**2);process=None
            try:
                with (root/'console.log').open('wb') as log:
                    process=subprocess.Popen([str(venv/'Scripts/python.exe'),'-B','-c',code,str(root)],stdout=log,stderr=subprocess.STDOUT)
                    deadline=time.monotonic()+10
                    while not (root/'ready.json').exists():
                        if process.poll() is not None or time.monotonic()>deadline:self.fail('Actual venv worker did not start')
                        time.sleep(.02)
                    actual=json.loads((root/'ready.json').read_text())['pid']
                    self.assertNotEqual(process.pid,actual)
                    budget.assign(process)
                    self.assertTrue(budget.contains(process.pid));self.assertFalse(budget.contains(actual))
                    (root/'release').write_text('NO_ALLOCATION')
                    self.assertEqual(process.wait(timeout=10),0)
            finally:
                (root/'release').touch()
                if process is not None:process.wait(timeout=20)
                budget.close()

    def test_suspended_venv_and_actual_descendant_are_owned_before_any_allocator_runs(self):
        with tempfile.TemporaryDirectory(prefix='ECRA owned process 中文 ') as folder:
            root=Path(folder).resolve();venv=root/'venv'
            subprocess.run([getattr(sys,'_base_executable',sys.executable),'-m','venv','--without-pip',str(venv)],check=True,capture_output=True)
            child_code='''import json,os,sys,time
from pathlib import Path
root=Path(sys.argv[1]);(root/'descendant.json').write_text(json.dumps(dict(pid=os.getpid())))
while not (root/'release').is_file():time.sleep(.01)
chunks=[];logging_reserve=bytearray(1024**2)
try:
 while True:chunks.append(bytes(1024**2))
except MemoryError:
 logging_reserve=None
 (root/'caught.json').write_text(json.dumps(dict(pid=os.getpid(),caught_memory_error=True)))
 while not (root/'finish').is_file():time.sleep(.01)
 chunks.clear();print(json.dumps(dict(pid=os.getpid(),caught_memory_error=True)),flush=True)
'''
            parent_code='''import json,os,subprocess,sys
from pathlib import Path
root=Path(sys.argv[1]);(root/'parent.json').write_text(json.dumps(dict(pid=os.getpid())))
value=subprocess.check_output([sys.executable,'-B','-c',sys.argv[2],str(root)],text=True)
(root/'result.json').write_text(value)
'''
            budget=ProcessBudget(128*1024**2);process=None
            try:
                with (root/'console.log').open('wb') as log:
                    process=OwnedProcess([str(venv/'Scripts/python.exe'),'-B','-c',parent_code,str(root),child_code],
                        cwd=root,env=dict(os.environ),log=log)
                    self.assertIsNone(process.poll());self.assertFalse((root/'parent.json').exists())
                    budget.assign(process);self.assertTrue(budget.contains(process.pid));process.resume()
                    deadline=time.monotonic()+15
                    while not (root/'descendant.json').exists():
                        if process.poll() is not None or time.monotonic()>deadline:self.fail((root/'console.log').read_text(errors='replace'))
                        time.sleep(.02)
                    parent=json.loads((root/'parent.json').read_text())['pid'];descendant=json.loads((root/'descendant.json').read_text())['pid']
                    self.assertNotEqual(parent,process.pid,'Must actually exercise the Windows venv redirector')
                    self.assertTrue(budget.contains(parent));self.assertTrue(budget.contains(descendant))
                    self.assertFalse(budget.contains(os.getpid()))
                    (root/'release').write_text('OWNED')
                    deadline=time.monotonic()+15
                    while not (root/'caught.json').exists():
                        if process.poll() is not None or time.monotonic()>deadline:self.fail((root/'console.log').read_text(errors='replace'))
                        time.sleep(.02)
                    # Measure actual private commit while all payload remains
                    # retained and workers are idle. The raw historical Job
                    # peak is separately retained; failed commit accounting is
                    # not documented to equal successful private allocation.
                    measured=budget.sample()
                    self.assertEqual(measured['enforced_job_commit_limit_bytes'],128*1024**2)
                    self.assertTrue(measured['job_limit_flags']&0x200)
                    self.assertLess(measured['private_bytes'],128*1024**2)
                    self.assertGreater(measured['peak_job_commit_bytes'],120*1024**2)
                    (root/'finish').write_text('MEASURED')
                    self.assertEqual(process.wait(timeout=20),0,(root/'console.log').read_text(errors='replace'))
                    result=json.loads((root/'result.json').read_text());self.assertTrue(result['caught_memory_error'])
                    self.assertEqual(result['pid'],descendant)
            finally:
                budget.close()
                if process is not None:process.wait(timeout=10);process.close()

    def test_nonexistent_executable_refuses_before_child_creation(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            with (root/'log').open('wb') as log,self.assertRaises(ValueError):
                OwnedProcess([str(root/'missing.exe')],cwd=root,env=dict(os.environ),log=log)
            self.assertEqual(sorted(p.name for p in root.iterdir()),['log'])


if __name__=='__main__':unittest.main()
