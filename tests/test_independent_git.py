"""Real Git isolation: original bytes, fixed revisions, refresh and failures."""
import hashlib
import os
from pathlib import Path
import subprocess
import stat
import tempfile
import unittest
from unittest.mock import patch

from ecra import independent_git as snapshots
from ecra.workspace import WorkspaceResolver


class IndependentGitTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='ecra private Git 中文 ')
        self.addCleanup(self.temp.cleanup);self.home=Path(self.temp.name).resolve()
        self.environment=patch.dict(os.environ,dict(GIT_CONFIG_GLOBAL='NUL' if os.name=='nt' else '/dev/null',
            GIT_CONFIG_NOSYSTEM='1',GIT_OPTIONAL_LOCKS='0'))
        self.environment.start();self.addCleanup(self.environment.stop)
        self.repo=self.home/'原固件';self.repo.mkdir();self.git(self.repo,'init')
        self.git(self.repo,'config','user.name','ECRA test');self.git(self.repo,'config','user.email','ecra@example.invalid')
        self.git(self.repo,'config','core.autocrlf','false')
        (self.repo/'a.c').write_bytes(b'int g;\n');self.git(self.repo,'add','.');self.git(self.repo,'commit','-m','base')
        self.base=self.git(self.repo,'rev-parse','HEAD');self.git(self.repo,'tag','v1')
        (self.repo/'a.c').write_bytes(b'int g; void main(void){g++;}\n')
        self.git(self.repo,'commit','-am','current');self.head=self.git(self.repo,'rev-parse','HEAD')
        self.git(self.repo,'config','remote.origin.url','https://example.invalid/firmware.git')
        self.git(self.repo,'update-ref','refs/remotes/origin/main',self.head)
        self.git(self.repo,'symbolic-ref','refs/remotes/origin/HEAD','refs/remotes/origin/main')
        self.ws=WorkspaceResolver.resolve(self.repo,dict(output=dict(location='custom',custom_dir=str(self.home/'数据')))).initialize()
        self.tree=Path(self.ws.worktree_root)/('current-'+self.head[:16])

    def git(self,root,*args):
        return subprocess.check_output(['git','-C',str(root),'-c','commit.gpgSign=false',*map(str,args)],
            stderr=subprocess.DEVNULL).decode('utf-8').strip()

    def files(self,root):
        return {str(p.relative_to(root)):(hashlib.sha256(p.read_bytes()).hexdigest(),p.stat().st_mtime_ns)
            for p in root.rglob('*') if p.is_file()}

    def test_fixed_worktree_preserves_all_original_git_source_and_dirty_bytes(self):
        (self.repo/'a.c').write_bytes(b'int staged;\n');self.git(self.repo,'add','a.c')
        (self.repo/'a.c').write_bytes(b'int later_dirty;\n');(self.repo/'untracked.h').write_bytes(b'#define VALUE 3\n')
        before=self.files(self.repo)
        result=snapshots.prepare(self.repo,self.tree,self.head,self.ws)
        private=Path(result['repository'])
        self.assertTrue(private.is_relative_to(Path(self.ws.project_workspace)))
        self.assertFalse((self.repo/'.git/worktrees').exists())
        self.assertEqual(self.files(self.repo),before)
        self.assertEqual((self.tree/'a.c').read_bytes(),b'int g; void main(void){g++;}\n')
        self.assertEqual(self.git(self.tree,'rev-parse','HEAD'),self.head)
        for args in [('describe','--tags','--always'),('for-each-ref','--format=%(refname) %(objectname)'),('remote','get-url','origin')]:
            self.assertEqual(self.git(self.tree,*args),self.git(self.repo,*args))
        self.assertFalse((private/'objects/info/alternates').exists())
        original_object=next(p for p in (self.repo/'.git/objects').glob('*/*') if p.is_file())
        copied=private/'objects'/original_object.relative_to(self.repo/'.git/objects')
        self.assertTrue(copied.is_file());self.assertFalse(os.path.samefile(original_object,copied))
        old=copied.read_bytes();original_object.chmod(stat.S_IWRITE | stat.S_IREAD)
        original_object.write_bytes(b'test-only source object damage')
        self.assertEqual(copied.read_bytes(),old)
        self.assertEqual(self.git(self.tree,'show','HEAD:a.c'),'int g; void main(void){g++;}')

    def test_reuse_and_source_ref_refresh_keep_fixed_files_and_audit_previous_refs(self):
        first=snapshots.prepare(self.repo,self.tree,self.head,self.ws)
        before=self.files(self.repo);source=(self.tree/'a.c').read_bytes()
        self.assertEqual(snapshots.prepare(self.repo,self.tree,self.head,self.ws),first)
        self.assertEqual(self.files(self.repo),before)
        self.git(self.repo,'tag','v2');self.git(self.repo,'tag','-d','v1')
        before=self.files(self.repo)
        refreshed=snapshots.prepare(self.repo,self.tree,self.head,self.ws)
        self.assertEqual(refreshed,first);self.assertEqual((self.tree/'a.c').read_bytes(),source)
        self.assertEqual(self.git(self.tree,'describe','--tags','--always'),'v2')
        self.assertEqual(self.files(self.repo),before)
        states=Path(first['repository']).parent/'states'
        self.assertEqual(len(list(states.iterdir())),2)
        self.assertTrue(any(b'refs/tags/v1' in (p/'refs').read_bytes() for p in states.iterdir()))

    def test_existing_legacy_worktree_and_unknown_directory_are_never_adopted(self):
        self.tree.parent.mkdir(parents=True)
        self.git(self.repo,'worktree','add','--detach',self.tree,self.head)
        before=self.files(self.repo);reference=(self.tree/'.git').read_bytes()
        with self.assertRaisesRegex(ValueError,'历史|未知|独立数据根'):
            snapshots.prepare(self.repo,self.tree,self.head,self.ws)
        self.assertEqual((self.tree/'.git').read_bytes(),reference);self.assertEqual(self.files(self.repo),before)

    def test_interrupted_creation_and_mutated_private_refs_refuse_reuse(self):
        real=snapshots._git
        def interrupted(root,*args,**kwargs):
            if 'worktree' in args:raise OSError('injected before checkout')
            return real(root,*args,**kwargs)
        before=self.files(self.repo)
        with patch.object(snapshots,'_git',side_effect=interrupted),self.assertRaises(OSError):
            snapshots.prepare(self.repo,self.tree,self.head,self.ws)
        self.assertEqual(self.files(self.repo),before)
        with self.assertRaisesRegex(ValueError,'中断|未完成|现场'):
            snapshots.prepare(self.repo,self.tree,self.head,self.ws)
        second=Path(self.ws.worktree_root)/('base-'+self.base[:16])
        result=snapshots.prepare(self.repo,second,self.base,self.ws)
        self.git(Path(result['repository']),'tag','unexpected-private-tag')
        with self.assertRaisesRegex(ValueError,'改变|损坏'):
            snapshots.prepare(self.repo,second,self.base,self.ws)

    def test_wrong_sha_foreign_target_and_git_overrides_refuse_without_source_write(self):
        before=self.files(self.repo)
        with self.assertRaises(ValueError):snapshots.prepare(self.repo,self.tree,'0'*40,self.ws)
        with self.assertRaises(ValueError):snapshots.prepare(self.repo,self.repo/'forbidden',self.head,self.ws)
        with patch.dict(os.environ,dict(GIT_INDEX_FILE=str(self.repo/'.git/index'))),self.assertRaises(ValueError):
            snapshots.prepare(self.repo,self.tree,self.head,self.ws)
        self.assertEqual(self.files(self.repo),before)

    def test_unsupported_git_inputs_refuse_before_creating_snapshot_and_keep_original(self):
        hook=self.repo/'.git/hooks/post-checkout';hook.write_bytes(b'#!/bin/sh\nexit 0\n')
        before=self.files(self.repo)
        with self.assertRaisesRegex(ValueError,'钩子'):
            snapshots.prepare(self.repo,self.tree,self.head,self.ws)
        self.assertEqual(self.files(self.repo),before);self.assertFalse(self.tree.exists())
        hook.unlink()
        self.git(self.repo,'config','include.path','relative-user-config')
        before=self.files(self.repo)
        with self.assertRaisesRegex(ValueError,'include'):
            snapshots.prepare(self.repo,self.tree,self.head,self.ws)
        self.assertEqual(self.files(self.repo),before);self.assertFalse(self.tree.exists())


if __name__=='__main__':unittest.main()
