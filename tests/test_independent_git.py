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
        return subprocess.check_output(['git','-C',str(root),'-c','core.longpaths=true','-c','commit.gpgSign=false',*map(str,args)],
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

    def test_fixed_metadata_never_refreshes_when_original_refs_and_checkout_change(self):
        before = self.files(self.repo)
        frozen = snapshots.freeze(self.repo, self.ws)
        snapshots.prepare_frozen(self.tree, self.head, self.ws, frozen)
        self.assertEqual(self.files(self.repo), before)
        original = self.git(self.tree, 'describe', '--tags', '--always')
        self.git(self.repo, 'tag', 'v2')
        self.git(self.repo, 'tag', '-f', 'v1', self.head)
        self.git(self.repo, 'checkout', '-b', 'other', self.base)
        before = self.files(self.repo)
        snapshots.prepare_frozen(self.tree, self.head, self.ws, frozen)
        self.assertEqual(self.git(self.tree, 'describe', '--tags', '--always'), original)
        self.assertEqual(self.files(self.repo), before)
        newer = snapshots.freeze(self.repo, self.ws)
        self.assertNotEqual(newer['id'], frozen['id'])
        snapshots.check_frozen(frozen, self.ws)
        repository = Path(frozen['repository'])
        self.git(repository, 'tag', 'tampered')
        with self.assertRaisesRegex(ValueError, '改变|损坏'):
            snapshots.check_frozen(frozen, self.ws)

    def test_global_git_configuration_remains_a_verified_external_build_input(self):
        config = self.home/'global.gitconfig'
        config.write_text('[core]\n\tabbrev = 10\n', 'utf-8')
        with patch.dict(os.environ, dict(GIT_CONFIG_GLOBAL=str(config))):
            frozen = snapshots.freeze(self.repo, self.ws)
            snapshots.prepare_frozen(self.tree, self.head, self.ws, frozen)
            config.write_text('[core]\n\tabbrev = 12\n', 'utf-8')
            with self.assertRaisesRegex(ValueError, '外部构建配置'):
                snapshots.check_frozen(frozen, self.ws)

    def test_template_hook_is_isolated_before_mirror_and_checkout(self):
        template = self.home/'custom template'
        hooks = template/'hooks'
        hooks.mkdir(parents=True)
        witness = self.home/'unexpected hook'
        hook = hooks/'post-checkout'
        hook.write_text(f"#!/bin/sh\ntouch '{witness.as_posix()}'\n", 'utf-8')
        hook.chmod(0o755)
        with patch.dict(os.environ, GIT_TEMPLATE_DIR=str(template)):
            frozen = snapshots.freeze(self.repo, self.ws)
            snapshots.prepare_frozen(self.tree, self.head, self.ws, frozen)
            self.assertEqual(snapshots.freeze(self.repo, self.ws), frozen)
        self.assertFalse(witness.exists())
        self.assertTrue(hook.is_file())

    def test_hooks_in_source_global_config_and_build_child(self):
        witness = self.home/'executed'
        external = self.home/'global hooks'
        external.mkdir()
        for directory in (external, self.repo/'.git/hooks'):
            hook = directory/'post-checkout'
            hook.write_text(f"#!/bin/sh\ntouch '{witness.as_posix()}'\n", 'utf-8')
            hook.chmod(0o755)
            (directory/'README').write_text('ordinary file')
        config = self.home/'global.gitconfig'
        self.git(self.repo, 'config', '--file', config, 'core.hooksPath', external.as_posix())
        self.git(self.repo, 'config', '--add', 'example.Mixed.paths', 'one')
        self.git(self.repo, 'config', '--add', 'example.Mixed.paths', 'two')
        with patch.dict(os.environ, GIT_CONFIG_GLOBAL=str(config)):
            for local in (False, True):
                if local:
                    self.git(self.repo, 'config', 'core.hooksPath', '.git/hooks')
                before = self.files(self.repo)
                frozen = snapshots.freeze(self.repo, self.ws)
                private = Path(frozen['repository'])
                for name, sha in [('current', self.head), ('base', self.base)]:
                    tree = self.tree.with_name(f'{name}-{local}')
                    snapshots.prepare_frozen(tree, sha, self.ws, frozen)
                    # A fresh, ordinary Git process, as invoked by CMake.
                    self.git(tree, 'checkout', '--detach', sha)
                    self.assertEqual(self.git(tree, 'config', '--get-all', 'example.Mixed.paths'), 'one\ntwo')
                    self.assertEqual(Path(self.git(tree, 'config', 'core.hooksPath')), private.parents[1]/'empty-hooks')
                self.assertEqual(self.files(self.repo), before)
                self.assertEqual(snapshots.freeze(self.repo, self.ws), frozen)
                self.assertFalse(witness.exists())
            (private.parents[1]/'empty-hooks'/'unexpected').touch()
            with self.assertRaisesRegex(ValueError, '空 Hook 目录'):
                snapshots.check_frozen(frozen, self.ws)
            self.git(self.tree.parent/'base-True', '-c', 'core.hooksPath='+str(external), 'hook', 'run', 'post-checkout')
            self.assertTrue(witness.is_file())

    def test_plain_linked_worktree_keeps_its_head_and_original_registrations(self):
        linked = self.home/'linked'
        self.git(self.repo, 'worktree', 'add', '-b', 'linked-side', linked, self.base)
        ws = WorkspaceResolver.resolve(linked, dict(output=dict(location='custom', custom_dir=str(self.home/'linked-data')))).initialize()
        before = self.files(self.repo/'.git')
        original = self.git(self.repo, 'worktree', 'list', '--porcelain')
        frozen = snapshots.freeze(linked, ws)
        tree = Path(ws.worktree_root)/'linked-base'
        snapshots.prepare_frozen(tree, self.base, ws, frozen)
        self.assertEqual(self.git(Path(frozen['repository']), 'symbolic-ref', 'HEAD'), 'refs/heads/linked-side')
        self.assertEqual(self.git(self.repo, 'worktree', 'list', '--porcelain'), original)
        self.assertEqual(self.files(self.repo/'.git'), before)

    def test_interrupted_clone_can_retry_without_adopting_partial_data(self):
        real = snapshots._git
        def interrupt(root, *args):
            result = real(root, *args)
            if 'clone' in args:
                raise InterruptedError('stop after mirror clone')
            return result
        before = self.files(self.repo)
        with patch.object(snapshots, '_git', side_effect=interrupt), self.assertRaises(InterruptedError):
            snapshots.freeze(self.repo, self.ws)
        fixed = Path(self.ws.project_workspace)/'git-fixed'
        markers = list(fixed.glob('*/state.json'))
        self.assertEqual(len(markers), 1)
        self.assertIn('CREATING', markers[0].read_text())
        frozen = snapshots.freeze(self.repo, self.ws)
        self.assertEqual(snapshots.check_frozen(frozen, self.ws), Path(frozen['repository']))
        self.assertIn('CREATING', markers[0].read_text())
        self.assertEqual(self.files(self.repo), before)

    def test_change_during_copy_does_not_publish_mixed_configuration_or_refs(self):
        original = snapshots._git
        def change(root, *args):
            value = original(root, *args)
            if 'clone' in args:
                self.git(self.repo, 'config', 'example.counter', '2')
                self.git(self.repo, 'tag', 'after-copy')
            return value
        with patch.object(snapshots, '_git', side_effect=change), self.assertRaisesRegex(ValueError, '复制后复核'):
            snapshots.freeze(self.repo, self.ws)
        markers = list((Path(self.ws.project_workspace)/'git-fixed').glob('*/state.json'))
        self.assertTrue(all('READY' not in p.read_text() for p in markers))
        private = Path(snapshots.freeze(self.repo, self.ws)['repository'])
        self.assertEqual(self.git(private, 'config', 'example.counter'), '2')
        self.assertEqual(self.git(private, 'rev-parse', 'after-copy'), self.head)

    def test_multiple_unsupported_layouts_identified_before_clone(self):
        self.git(self.repo, 'config', 'include.path', 'relative')
        alternates = self.repo/'.git/objects/info/alternates'
        alternates.touch()
        before = self.files(self.repo)
        with self.assertRaises(ValueError) as caught:
            snapshots.freeze(self.repo, self.ws)
        for detail in ('采集原仓库', str(self.repo), 'include.path', str(alternates)):
            self.assertIn(detail, str(caught.exception))
        self.assertEqual(self.files(self.repo), before)

    def test_inactive_worktree_config_is_observed_without_redirecting_the_copy(self):
        inactive = self.repo/'.git/config.worktree'
        inactive.write_text('[example]\n  inactive = yes\n', 'utf-8')
        self.git(self.repo, 'config', 'extensions.worktreeConfig', 'false')
        before = self.files(self.repo)
        frozen = snapshots.freeze(self.repo, self.ws)
        snapshots.prepare_frozen(self.tree, self.head, self.ws, frozen)
        self.assertEqual(frozen['source_state']['inactive_worktree_config'],
                         hashlib.sha256(inactive.read_bytes()).hexdigest())
        self.assertNotIn('example.inactive', self.git(self.tree, 'config', '--name-only', '--list').splitlines())
        self.assertEqual(self.files(self.repo), before)
        self.git(self.repo, 'config', 'extensions.worktreeConfig', 'true')
        with self.assertRaisesRegex(ValueError, 'worktreeconfig=true.*config.worktree'):
            snapshots.freeze(self.repo, self.ws)

    def test_corrupt_owned_object_blocks_snapshot_reuse(self):
        frozen = snapshots.freeze(self.repo, self.ws)
        private = Path(frozen['repository'])
        blob = self.git(private, 'rev-parse', 'HEAD:a.c')
        path = private/'objects'/blob[:2]/blob[2:]
        path.chmod(stat.S_IWRITE | stat.S_IREAD)
        path.write_bytes(b'injected private object corruption')
        with self.assertRaisesRegex(ValueError, '校验私有 Git 对象') as caught:
            snapshots.freeze(self.repo, self.ws)
        self.assertIn(blob, str(caught.exception))
        self.assertEqual(self.git(self.repo, 'show', 'HEAD:a.c'), 'int g; void main(void){g++;}')


    def test_command_hook_config_refused_without_disclosing_or_running_command(self):
        config = self.home/'named-hooks.gitconfig'
        witness = self.home/'named hook ran'
        self.git(self.repo, 'config', '--file', config, 'hook.example.command', f"touch '{witness.as_posix()}'")
        self.git(self.repo, 'config', '--file', config, 'hook.example.event', 'reference-transaction')
        with patch.dict(os.environ, GIT_CONFIG_GLOBAL=str(config)):
            with self.assertRaisesRegex(ValueError, 'hook.example.event') as caught:
                snapshots.freeze(self.repo, self.ws)
        self.assertNotIn('touch', str(caught.exception))
        self.assertFalse(witness.exists())

    def test_conditional_command_hook_cannot_run_before_worktree_revalidation(self):
        config, include = self.home/'global.gitconfig', self.home/'detached.gitconfig'
        witness = self.home/'checkout hook ran'
        self.git(self.repo, 'config', '--file', config, 'includeIf.gitdir:**/worktrees/**.path', include.as_posix())
        self.git(self.repo, 'config', '--file', include, 'hook.conditional.event', 'post-checkout')
        self.git(self.repo, 'config', '--file', include, 'hook.conditional.command', f"touch '{witness.as_posix()}'")
        with patch.dict(os.environ, GIT_CONFIG_GLOBAL=str(config)):
            frozen = snapshots.freeze(self.repo, self.ws)
            with self.assertRaisesRegex(ValueError, 'hook.conditional.event'):
                snapshots.prepare_frozen(self.tree, self.head, self.ws, frozen)
        self.assertFalse(witness.exists())
        self.assertIn('CREATING', (self.ws.git_admin_home(self.tree)/'state.json').read_text())


    def test_promisor_storage_and_missing_blob_are_not_independent(self):
        self.git(self.repo, 'config', 'remote.MixedCase.promisor', 'true')
        marker = self.repo/'.git/objects/pack/pack-test.promisor'
        marker.touch()
        with self.assertRaisesRegex(ValueError, r'remote.MixedCase.promisor.*pack-test\.promisor'):
            snapshots.freeze(self.repo, self.ws)
        self.git(self.repo, 'config', 'remote.MixedCase.promisor', 'false')
        marker.unlink()
        frozen = snapshots.freeze(self.repo, self.ws)
        private = Path(frozen['repository'])
        blob = self.git(private, 'rev-parse', 'HEAD:a.c')
        path = private/'objects'/blob[:2]/blob[2:]
        path.chmod(stat.S_IWRITE | stat.S_IREAD)
        path.unlink()
        with self.assertRaisesRegex(ValueError, blob):
            snapshots.freeze(self.repo, self.ws)


    def test_global_relative_include_preserves_order_case_and_external_identity(self):
        config = self.home/'global.gitconfig'
        nested = self.home/'extra'/'common.gitconfig'
        nested.parent.mkdir()
        nested.write_text('[example "Mixed"]\n value = one\n value = two\n', 'utf-8')
        config.write_text('[example "Mixed"]\n value = before\n[include]\n path = extra/common.gitconfig\n'
                          '[example "Mixed"]\n value = after\n[example "mixed"]\n value = separate\n', 'utf-8')
        with patch.dict(os.environ, GIT_CONFIG_GLOBAL=str(config)):
            frozen = snapshots.freeze(self.repo, self.ws)
            for name, sha in [('base', self.base), ('current', self.head)]:
                tree = self.tree.with_name(name)
                snapshots.prepare_frozen(tree, sha, self.ws, frozen)
                self.assertEqual(self.git(tree, 'config', '--get-all', 'example.Mixed.value').splitlines(),
                                 ['before', 'one', 'two', 'after'])
                self.assertEqual(self.git(tree, 'config', '--get-all', 'example.mixed.value'), 'separate')
            nested.write_text('[example "Mixed"]\n value = changed\n', 'utf-8')
            with self.assertRaisesRegex(ValueError, '外部构建配置'):
                snapshots.check_frozen(frozen, self.ws)


if __name__=='__main__':unittest.main()
