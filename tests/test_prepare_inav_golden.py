import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from ecra.report_package import sha256


TOOL=Path(__file__).resolve().parents[1]


class GoldenPreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='ECRA golden prepare ');self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.source=self.base/'original';self.source.mkdir()
        self.env=dict(os.environ,GIT_OPTIONAL_LOCKS='0',PYTHONIOENCODING='utf-8')
        self.git('init','-q');self.git('config','user.name','Preparation test');self.git('config','user.email','test@invalid')
        self.git('config','core.autocrlf','false')
        for name,content in [('main.c',b'int g;\n'),('deleted.c',b'int deleted;\n'),('.gitignore',b'ignored/\n')]:
            (self.source/name).write_bytes(content)
        self.git('add','.');self.git('commit','-qm','baseline')
        self.config=self.base/'old-semantics.yaml'
        self.config.write_text(json.dumps(dict(version=1,project=dict(root=str(self.source)),analysis=dict(
            git_diff=dict(enabled=False,target_ref='HEAD^',compare_mode='direct',include_uncommitted=True)))),encoding='utf-8')

    def git(self,*args):
        return subprocess.check_output(['git','-C',str(self.source),*args],env=self.env,stderr=subprocess.PIPE)

    def run_helper(self):
        return subprocess.run([sys.executable,'-B',str(TOOL/'scripts/prepare_inav_golden.py'),
            '--source',str(self.source),'--config',str(self.config),'--work',str(self.base/'capture')],
            env=self.env,cwd=TOOL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,encoding='utf-8')

    def test_real_git_capture_preserves_working_bytes_index_deletion_and_untracked_without_claiming_ignored_archive(self):
        (self.source/'main.c').write_bytes(b'int g=2;\n');(self.source/'deleted.c').unlink()
        (self.source/'input.h').write_bytes(b'#define INPUT 7\n')
        ignored=self.source/'ignored/history.bin';ignored.parent.mkdir();ignored.write_bytes(b'old data'*1000)
        index=sha256(self.source/'.git/index');status=self.git('status','--porcelain=v2','--untracked-files=all','-z')
        result=self.run_helper();self.assertEqual(result.returncode,0,result.stdout)
        work=self.base/'capture';tree=work/'firmware';receipt=json.loads((work/'preparation.json').read_text(encoding='utf-8'))
        self.assertEqual(receipt['state'],'SOURCE_CANDIDATE_CAPTURED_BUILD_NOT_VERIFIED')
        self.assertTrue(receipt['private_index_entries_equal']);self.assertTrue(receipt['private_working_status_equal'])
        self.assertEqual((tree/'main.c').read_bytes(),(self.source/'main.c').read_bytes())
        self.assertEqual((tree/'input.h').read_bytes(),(self.source/'input.h').read_bytes())
        self.assertFalse((tree/'deleted.c').exists());self.assertFalse((tree/'ignored').exists())
        self.assertEqual(ignored.read_bytes(),b'old data'*1000)
        self.assertEqual(sha256(self.source/'.git/index'),index)
        self.assertEqual(self.git('status','--porcelain=v2','--untracked-files=all','-z'),status)
        self.assertFalse((tree/'.git/objects/info/alternates').exists())
        self.assertEqual(receipt['native_golden'],'NOT_RUN');self.assertEqual(receipt['production_dirty_isolation'],'NOT_PROVEN')

    def test_changed_staged_index_is_rejected_without_flattening_or_rewriting_the_original(self):
        (self.source/'main.c').write_bytes(b'int staged=1;\n');self.git('add','main.c')
        (self.source/'main.c').write_bytes(b'int working=2;\n')
        index=sha256(self.source/'.git/index');result=self.run_helper()
        self.assertNotEqual(result.returncode,0)
        receipt=json.loads((self.base/'capture/preparation.json').read_text(encoding='utf-8'))
        self.assertEqual(receipt['state'],'FAILED');self.assertIn('staged index',receipt['error'])
        self.assertEqual(sha256(self.source/'.git/index'),index)
        self.assertEqual((self.source/'main.c').read_bytes(),b'int working=2;\n')


if __name__=='__main__':unittest.main()
