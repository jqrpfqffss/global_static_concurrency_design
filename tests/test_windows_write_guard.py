import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from ecra.report_package import sha256
from ecra.studio.process_budget import ProcessBudget
from ecra.studio.write_guard import create_private_directory,GuardedProcess


@unittest.skipUnless(os.name=='nt','Actual Windows mandatory integrity control required')
class WindowsWriteGuardTests(unittest.TestCase):
    def test_real_low_child_and_descendant_can_read_source_but_cannot_mutate_medium_source(self):
        with tempfile.TemporaryDirectory(prefix='ECRA 写入保护 ') as folder:
            root=Path(folder);source=root/'firmware';source.mkdir();(source/'.git').mkdir()
            file=source/'main.c';file.write_text('int original;\n',encoding='utf-8');before=sha256(file)
            private=create_private_directory(root/'private',source_root=source)
            program='''import json,os,sys,ctypes,subprocess
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from ecra.studio.write_guard import Windows
api=Windows();token=ctypes.wintypes.HANDLE()
api.check(api.adv.OpenProcessToken(api.kernel.GetCurrentProcess(),8,ctypes.byref(token)))
try:integrity=api.integrity(token)
finally:api.kernel.CloseHandle(token)
source=Path(sys.argv[2]);private=Path(sys.argv[3]);results={}
for name,action in [('overwrite',lambda:(source/'main.c').write_text('modified')),
 ('new_file',lambda:(source/'new.c').write_text('new')),
 ('delete',lambda:(source/'main.c').unlink()),
 ('new_directory',lambda:(source/'new-dir').mkdir()),
 ('git_metadata',lambda:(source/'.git/worktrees').mkdir())]:
 try:action();results[name]='UNEXPECTED_WRITE'
 except PermissionError:results[name]='DENIED'
(private/'result.txt').write_text('low process output',encoding='utf-8')
descendant=subprocess.run([sys.executable,'-c',"from pathlib import Path; import sys; p=Path(sys.argv[1]); p.write_text('unexpected descendant write')",str(source/'descendant.c')],capture_output=True,text=True)
print(json.dumps(dict(integrity=integrity,results=results,read_source=(source/'main.c').read_text(),descendant_exit_code=descendant.returncode,descendant_stderr=descendant.stderr)),flush=True)
'''
            log=root/'child.log';process=None;budget=ProcessBudget(512*1024**2)
            try:
                with log.open('wb') as output:
                    process=GuardedProcess([sys.executable,'-B','-c',program,str(Path(__file__).resolve().parents[1]),str(source),str(private)],
                        cwd=private,env=dict(os.environ,PYTHONIOENCODING='utf-8',TEMP=str(private),TMP=str(private)),log=output)
                    budget.assign(process);process.resume();code=process.wait(timeout=30)
                text=log.read_text(encoding='utf-8');self.assertEqual(code,0,text)
                result=json.loads(text)
                self.assertEqual(result['integrity'],0x1000)
                self.assertEqual(set(result['results'].values()),{'DENIED'})
                self.assertNotEqual(result['descendant_exit_code'],0)
                self.assertEqual(sha256(file),before);self.assertEqual(result['read_source'],'int original;\n')
                self.assertEqual((private/'result.txt').read_text(),'low process output')
                self.assertEqual(sorted(p.relative_to(source).as_posix() for p in source.rglob('*')),['.git','main.c'])
                self.assertGreater(budget.sample()['peak_job_commit_bytes'],0)
            finally:
                budget.close()
                if process:
                    if process.poll() is None:process.terminate();process.wait(timeout=10)
                    process.close()

    def test_existing_directory_is_never_relabelled(self):
        with tempfile.TemporaryDirectory() as folder:
            file=Path(folder)/'keep';file.write_bytes(b'keep')
            with self.assertRaises(FileExistsError):create_private_directory(folder,source_root=folder)
            self.assertEqual(file.read_bytes(),b'keep')

    def test_new_directories_inside_source_or_installation_are_rejected_before_creation(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'source';source.mkdir()
            for path in [source/'forbidden',Path(__file__).resolve().parents[1]/'forbidden-low-integrity-scope']:
                self.assertFalse(path.exists())
                with self.assertRaises(ValueError):create_private_directory(path,source_root=source)
                self.assertFalse(path.exists())


if __name__=='__main__':unittest.main()
