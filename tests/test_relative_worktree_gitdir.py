import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from ecra import git_diff as fix


class RelativeWorktreeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ecra gitdir 中文 ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.repo, self.tree = self.root/'仓库 空格', self.root/'基准 空格'
        self.run_git(self.root, 'init', self.repo)
        (self.repo/'a.c').write_bytes(b'int g;\n')
        self.run_git(self.repo, 'add', 'a.c')
        self.run_git(self.repo, 'commit', '-m', '基准')
        self.sha = self.run_git(self.repo, 'rev-parse', 'HEAD')
        self.run_git(self.repo, 'worktree', 'add', '--detach', self.tree, self.sha)

    def run_git(self, cwd, *args):
        env = dict(os.environ, GIT_CONFIG_GLOBAL='NUL' if os.name=='nt' else '/dev/null', GIT_CONFIG_NOSYSTEM='1')
        return subprocess.check_output(['git','-c','user.name=ECRA test','-c','user.email=ecra@example.invalid',
            '-c','commit.gpgSign=false','-c','core.autocrlf=false','-c','core.hooksPath='+str(self.root/'no-hooks'),
            *map(str,args)],cwd=cwd,env=env,stderr=subprocess.DEVNULL).decode('utf-8').strip()

    def test_legacy_cmake_and_git_keep_exact_snapshot_identity(self):
        directory=self.run_git(self.tree,'rev-parse','--absolute-git-dir')
        self.assertEqual(fix._relative_worktree_gitdir(self.repo,self.tree,self.sha),'RELATIVE')
        data=(self.tree/'.git').read_bytes()
        self.assertFalse(Path(data.decode().strip().split('gitdir: ',1)[1]).is_absolute())
        self.assertEqual(self.run_git(self.tree,'rev-parse','--absolute-git-dir'),directory)
        self.assertEqual(self.run_git(self.tree,'rev-parse','HEAD'),self.sha)
        self.assertEqual(self.run_git(self.repo,'status','--porcelain'),'')
        self.assertEqual(self.run_git(self.tree,'status','--porcelain'),'')
        self.assertEqual((self.tree/'a.c').read_bytes(),b'int g;\n')
        self.assertEqual(fix._relative_worktree_gitdir(self.repo,self.tree,self.sha),'RELATIVE')
        self.assertEqual((self.tree/'.git').read_bytes(),data)
        cmake=shutil.which('cmake')
        if cmake:
            script=self.root/'legacy.cmake'
            script.write_text('file(READ "'+self.tree.as_posix()+'/.git" reference)\n'
                'string(REGEX REPLACE "gitdir: (.*)\\n$" "\\\\1" relative "${reference}")\n'
                'get_filename_component(directory "'+self.tree.as_posix()+'/${relative}" ABSOLUTE)\n'
                'file(READ "${directory}/HEAD" sha)\nstring(STRIP "${sha}" sha)\n'
                'if(NOT sha STREQUAL "'+self.sha+'")\nmessage(FATAL_ERROR "wrong identity")\nendif()\n',encoding='utf-8')
            result=subprocess.run([cmake,'-P',str(script)],capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr.decode('utf-8',errors='replace'))

    def test_foreign_repository_and_wrong_commit_leave_reference_unchanged(self):
        original=(self.tree/'.git').read_bytes()
        with self.assertRaises(ValueError):fix._relative_worktree_gitdir(self.tree,self.repo,self.sha)
        with self.assertRaises(ValueError):fix._relative_worktree_gitdir(self.repo,self.tree,'0'*40)
        other=self.root/'foreign';self.run_git(self.root,'init',other)
        with self.assertRaises(ValueError):fix._relative_worktree_gitdir(other,self.tree,self.sha)
        self.assertEqual((self.tree/'.git').read_bytes(),original)

    def test_cross_volume_keeps_absolute_reference_and_requires_build_validation(self):
        original=(self.tree/'.git').read_bytes()
        with patch.object(fix.os.path,'relpath',side_effect=ValueError('different Windows drives')):
            self.assertEqual(fix._relative_worktree_gitdir(self.repo,self.tree,self.sha),'ABSOLUTE_CROSS_VOLUME')
        self.assertEqual((self.tree/'.git').read_bytes(),original)
        self.assertEqual(self.run_git(self.tree,'rev-parse','HEAD'),self.sha)

    def test_failed_post_write_check_restores_original_reference(self):
        original=(self.tree/'.git').read_bytes();real=fix.text;checks=0
        def changed(root,*args):
            nonlocal checks
            if args==('rev-parse','HEAD'):
                checks+=1
                if checks==2:return '0'*40
            return real(root,*args)
        with patch.object(fix,'text',side_effect=changed),self.assertRaises(ValueError):
            fix._relative_worktree_gitdir(self.repo,self.tree,self.sha)
        self.assertEqual((self.tree/'.git').read_bytes(),original)
        self.assertEqual(self.run_git(self.tree,'rev-parse','HEAD'),self.sha)


if __name__=='__main__':unittest.main()
