"""Real refs/status and authenticated pages without original Git writes."""
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from ecra.studio.git_versions import inspect_versions
from ecra.studio.server import create_app


class GitVersionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='ECRA 版本 中文 ');self.addCleanup(self.tmp.cleanup)
        self.home=Path(self.tmp.name).resolve();self.repo=self.home/'firmware';self.repo.mkdir()
        self.env=patch.dict(os.environ,dict(GIT_CONFIG_GLOBAL='NUL' if os.name=='nt' else '/dev/null',GIT_CONFIG_NOSYSTEM='1'))
        self.env.start();self.addCleanup(self.env.stop)
        self.git('init');self.git('config','user.name','Test');self.git('config','user.email','test@example.invalid')
        (self.repo/'a.c').write_bytes(b'int g;\n');self.git('add','.');self.git('commit','-m','base')
        self.base=self.git('rev-parse','HEAD');self.git('tag','v1')
        (self.repo/'a.c').write_bytes(b'int g; void main(void){g++;}\n');self.git('commit','-am','current')
        self.head=self.git('rev-parse','HEAD')
        updates=''.join(f'update refs/heads/feature/{i:03d} {self.head}\n' for i in range(120))
        subprocess.run(['git','-C',str(self.repo),'update-ref','--stdin'],input=updates.encode(),check=True,stdout=subprocess.DEVNULL)
        self.work=self.home/'data/work/git-versions'

    def git(self,*args):
        return subprocess.check_output(['git','-C',str(self.repo),'-c','commit.gpgSign=false',*args],stderr=subprocess.DEVNULL).decode().strip()

    def files(self):
        return {p.relative_to(self.repo).as_posix():(hashlib.sha256(p.read_bytes()).hexdigest(),p.stat().st_mtime_ns) for p in self.repo.rglob('*') if p.is_file()}

    def read(self,**kwargs):return inspect_versions(str(self.repo),self.work,**kwargs)

    def test_real_ref_pages_search_and_annotated_commit_resolution_preserve_all_source_bytes(self):
        self.git('tag','-a','release-中文','-m','real annotated tag',self.base)
        before=self.files();first=self.read(base_ref='release-中文',current_ref='HEAD',limit=50)
        second=self.read(limit=50,offset=50)
        self.assertEqual(first['base_sha'],self.base);self.assertEqual(first['current_sha'],self.head)
        self.assertEqual(first['head'],self.head);self.assertEqual(first['next_offset'],50)
        self.assertEqual(len(first['items']),50);self.assertEqual(len(second['items']),50)
        self.assertFalse({x['ref'] for x in first['items']}&{x['ref'] for x in second['items']})
        self.assertEqual(self.read(search='feature/11')['total'],10)
        self.assertEqual(self.files(),before);self.assertEqual(list(self.work.iterdir()),[])

    def test_staged_unstaged_rename_and_untracked_are_truthful_and_never_included(self):
        self.git('mv','a.c','renamed.c');(self.repo/'renamed.c').write_bytes(b'int later;\n')
        (self.repo/'未跟踪.txt').write_bytes(b'keep')
        before=self.files();value=self.read(base_ref='HEAD^')
        self.assertEqual(value['dirty'],dict(staged=1,unstaged=1,untracked=1,conflicted=0))
        self.assertFalse(value['include_uncommitted']);self.assertEqual(self.files(),before)

    def test_bad_ref_arguments_no_git_and_source_overlap_fail_without_source_write(self):
        before=self.files()
        for options in [dict(base_ref='--output=x'),dict(current_ref='not-a-real-ref'),dict(limit=True),dict(offset=-1)]:
            with self.subTest(options=options),self.assertRaises(ValueError):self.read(**options)
        with self.assertRaisesRegex(ValueError,'重叠'):
            inspect_versions(str(self.repo),self.repo/'forbidden')
        self.assertFalse((self.repo/'forbidden').exists());self.assertEqual(self.files(),before)
        other=self.home/'non-git';other.mkdir()
        self.assertFalse(inspect_versions(str(other),self.work)['available'])
        with patch('ecra.git_diff.subprocess.run',side_effect=FileNotFoundError('missing git')):
            with self.assertRaisesRegex(ValueError,'Git 无法运行'):self.read()

    def test_authenticated_api_real_values_and_page_limit_survive_reopen(self):
        data=self.home/'api-data';before=self.files()
        def client():return TestClient(create_app(data,token='test',authority='127.0.0.1:12345'),base_url='http://127.0.0.1:12345',headers={'x-ecra-session':'test','origin':'http://127.0.0.1:12345'})
        with client() as c:
            response=c.post('/api/profiles/git-versions',json=dict(project_root=str(self.repo),base_ref='v1',current_ref='HEAD',limit=20))
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(response.json()['base_sha'],self.base);self.assertEqual(len(response.json()['items']),20)
            self.assertLess(len(response.content),12000)
            self.assertEqual(c.post('/api/profiles/git-versions',json=dict(project_root=str(self.repo)),headers={'origin':'http://evil.invalid'}).status_code,403)
        with client() as c:
            response=c.post('/api/profiles/git-versions',json=dict(project_root=str(self.repo),offset=20,limit=20))
            self.assertEqual(response.status_code,200,response.text);self.assertEqual(response.json()['offset'],20)
        self.assertEqual(self.files(),before)


if __name__=='__main__':unittest.main()
