"""Real Git stat caches and Windows admission boundaries; no restored scan state."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ecra import git_diff, working_snapshot
from ecra.portable import bundle_root
from ecra.workspace import WorkspaceResolver


class GitFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ECRA-Q207-')
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve()
        self.assertEqual(self.home.parent, Path(tempfile.gettempdir()).resolve())
        bundle = bundle_root()
        self.exe = str(bundle/'tools/git/cmd/git.exe') if bundle else shutil.which('git')
        if not self.exe: self.skipTest('Actual Git required')
        self.origin = self.home/'origin'; self.origin.mkdir()
        self.repo = self.origin
        self.run_git('init', '-q')
        self.run_git('config', 'user.name', 'ECRA isolated regression')
        self.run_git('config', 'user.email', 'quality@localhost.invalid')
        self.run_git('config', 'core.autocrlf', 'false')
        for name, body in [('main.c', b'int counter;\n'), ('value.h', b'#define STEP 1\n'),
                           ('stable.c', b'int stable;\n')]:
            (self.repo/name).write_bytes(body)
        self.run_git('add', '.')
        self.run_git('commit', '-qm', 'base')
        (self.repo/'main.c').write_bytes(b'int counter; void tick(void){counter++;}\n')
        self.run_git('add', 'main.c'); self.run_git('commit', '-qm', 'current')

    def run_git(self, *args, root=None):
        hooks=self.home/'empty-hooks'; hooks.mkdir(exist_ok=True)
        argv=[self.exe, '-c', 'core.longpaths=true', '-c', 'core.fsmonitor=false',
              '-c', 'diff.autoRefreshIndex=false', '-c', 'commit.gpgsign=false',
              '-c', 'gc.auto=0', '-c', 'maintenance.auto=false', '-c', 'core.hooksPath='+str(hooks),
              '-C', str(root or self.repo), *args]
        result=subprocess.run(argv, env=dict(os.environ, GIT_OPTIONAL_LOCKS='0'), capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def fresh_stat_copy(self):
        (self.origin/'main.c').write_bytes(b'int counter; void tick(void){counter+=2;}\n')
        self.run_git('add', 'main.c', root=self.origin)
        (self.origin/'value.h').write_bytes(b'#define STEP 7\n')
        self.repo=self.home/'fresh-stat-copy'
        shutil.copytree(self.origin,self.repo,copy_function=shutil.copy2)
        # A real stat-only mismatch must not make a read-only comparison save
        # a refreshed index. Actual staged and dirty content remain distinct.
        stable=self.repo/'stable.c'; stamp=stable.stat()
        os.utime(stable,ns=(stamp.st_atime_ns,stamp.st_mtime_ns+2_000_000_000))

    def index(self): return (self.repo/'.git/index').read_bytes()

    def reference_patches(self):
        return (self.run_git('diff-index','--cached','-p','--binary','--no-ext-diff','--no-textconv','HEAD','--'),
                self.run_git('diff-files','-p','--binary','--no-ext-diff','--no-textconv','--'))


class ReadonlyGitTests(GitFixture):
    def check_helper(self, helper):
        self.fresh_stat_copy(); before=self.index(); staged,dirty=self.reference_patches()
        self.assertIn(b'counter+=2',staged);self.assertIn(b'+#define STEP 7',dirty)
        self.assertNotIn(b'stable.c',staged+dirty)
        actual_staged=helper(self.repo,'diff','--cached','--binary','--no-ext-diff','--no-textconv','HEAD','--')
        actual_dirty=helper(self.repo,'diff','--binary','--no-ext-diff','--no-textconv','--')
        self.assertEqual(actual_staged,staged);self.assertEqual(actual_dirty,dirty)
        self.assertEqual(self.index(),before,'read-only comparison must not rewrite caller index stat data')

    def test_working_snapshot_git_preserves_fresh_stat_index_and_patch(self): self.check_helper(working_snapshot._git)
    def test_comparison_git_preserves_fresh_stat_index_and_patch(self): self.check_helper(git_diff.git)

    def test_actual_changed_path_selection_is_unchanged_and_index_readonly(self):
        self.fresh_stat_copy(); before=self.index()
        changes=git_diff.changes(self.repo,'HEAD')
        self.assertEqual(changes,[dict(status='M',old_path='main.c',new_path='main.c'),
                                  dict(status='M',old_path='value.h',new_path='value.h')])
        self.assertEqual(self.index(),before)

    def test_real_working_capture_preserves_fresh_stat_staging_and_dirty_bytes(self):
        self.fresh_stat_copy();before=self.index();staged,dirty=self.reference_patches()
        analysis=dict(output=dict(location='custom',custom_dir=str(self.home/'data')))
        ws=WorkspaceResolver.resolve(self.repo,analysis).initialize();ws.bind(analysis)
        result=working_snapshot.capture(self.repo,dict(analysis=analysis))
        self.assertEqual(self.index(),before)
        folder=Path(result['folder']);copy=Path(result['source_root'])
        self.assertEqual((folder/'staged.patch').read_bytes(),staged)
        self.assertEqual((folder/'unstaged.patch').read_bytes(),dirty)
        self.assertEqual((copy/'value.h').read_bytes(),b'#define STEP 7\n')
        self.assertTrue(working_snapshot.validate(result,self.repo,dict(analysis=analysis))['valid'])

    def test_stat_only_isolated_tree_is_clean_but_real_byte_change_is_rejected(self):
        self.repo=self.home/'clean-stat-copy';shutil.copytree(self.origin,self.repo,copy_function=shutil.copy2)
        stable=self.repo/'stable.c';stamp=stable.stat()
        os.utime(stable,ns=(stamp.st_atime_ns,stamp.st_mtime_ns+2_000_000_000))
        before=self.index();head=self.run_git('rev-parse','HEAD').strip().decode()
        git_diff.check_isolated_tree(self.repo,head)
        self.assertEqual(self.index(),before)
        stable.write_bytes(b'int real_source_change;\n')
        with self.assertRaisesRegex(ValueError,'隔离源码已变化'):git_diff.check_isolated_tree(self.repo,head)
        self.assertEqual(self.index(),before)

    def test_difference_exit_code_does_not_accept_a_technical_failure(self):
        self.fresh_stat_copy()
        failed=subprocess.CompletedProcess([],1,b'',b'file read failed')
        with patch('ecra.git_diff.subprocess.run',return_value=failed):
            with self.assertRaisesRegex(ValueError,'Git 比较失败'):git_diff.changes(self.repo,'HEAD')


class ContentNameEvidenceTests(GitFixture):
    def test_zero_line_rename_in_spaced_unicode_repository_is_retained(self):
        self.repo=self.home/'spaced repo 中文';shutil.copytree(self.origin,self.repo,copy_function=shutil.copy2)
        self.run_git('mv','value.h','renamed header 中文.h');before=self.index()
        self.assertEqual(git_diff.changes(self.repo,'HEAD'),[
            dict(status='R100',old_path='value.h',new_path='renamed header 中文.h')])
        self.assertEqual(self.index(),before)

    def test_binary_and_zero_byte_added_deleted_files_are_retained(self):
        (self.repo/'binary.bin').write_bytes(b'\0old binary\xff')
        (self.repo/'empty.delete').write_bytes(b'')
        self.run_git('add','.');self.run_git('commit','-qm','binary and empty baseline')
        (self.repo/'binary.bin').write_bytes(b'\0new binary\xfe')
        (self.repo/'empty.delete').unlink()
        stable=self.repo/'stable.c';stamp=stable.stat()
        os.utime(stable,ns=(stamp.st_atime_ns,stamp.st_mtime_ns+2_000_000_000))
        before=self.index();rows=git_diff.changes(self.repo,'HEAD')
        self.assertEqual({r['new_path']:r['status'] for r in rows},
                         {'binary.bin':'M','empty.delete':'D'})
        self.assertEqual(self.index(),before)
        # Test addition separately: simultaneous deletion/addition of identical
        # empty blobs is a legitimate 100%-similar Git rename, covered above.
        (self.repo/'empty.delete').write_bytes(b'')
        (self.repo/'empty.add').write_bytes(b'');self.run_git('add','empty.add')
        before=self.index();rows=git_diff.changes(self.repo,'HEAD')
        self.assertEqual({r['new_path']:r['status'] for r in rows},
                         {'binary.bin':'M','empty.add':'A'})
        self.assertEqual(self.index(),before)

    def test_pure_tracked_mode_change_is_retained_even_when_blob_is_equal(self):
        self.run_git('update-index','--chmod=+x','stable.c');self.run_git('commit','-qm','mode only')
        self.assertEqual(self.run_git('rev-parse','HEAD:stable.c'),self.run_git('rev-parse','HEAD^:stable.c'))
        before=self.index()
        self.assertEqual(git_diff.changes(self.repo,'HEAD^','HEAD'),[
            dict(status='M',old_path='stable.c',new_path='stable.c')])
        self.assertEqual(self.index(),before)

    def test_user_textconv_and_external_diff_are_not_executed_or_trusted(self):
        marker=self.home/'converter-called';converter=self.home/'marker_converter.py'
        converter.write_text('from pathlib import Path\nPath('+repr(marker.as_posix())+').write_text("called")\n'
                             'print("constant old and new output")\n','utf-8')
        command='"'+Path(sys.executable).as_posix()+'" "'+converter.as_posix()+'"'
        (self.repo/'.gitattributes').write_text('main.c diff=qa-marker\n','utf-8')
        self.run_git('add','.gitattributes');self.run_git('commit','-qm','local converter contract')
        self.run_git('config','diff.qa-marker.textconv',command)
        (self.repo/'main.c').write_bytes(b'int real_changed_source;\n')
        self.run_git('diff','--textconv','--','main.c');self.assertTrue(marker.exists());marker.unlink()
        self.run_git('config','diff.external',command)
        self.run_git('diff','--ext-diff','--no-textconv','--','main.c')
        self.assertTrue(marker.exists());marker.unlink()
        before=self.index()
        self.assertEqual(git_diff.changes(self.repo,'HEAD'),[
            dict(status='M',old_path='main.c',new_path='main.c')])
        self.assertFalse(marker.exists(),'Content proof must not execute or trust repository converters')
        self.assertEqual(self.index(),before)

    def test_incomplete_content_protocol_is_a_failure_not_an_empty_diff(self):
        def query(root,*args,**kwargs):
            return b'1\t1\tmain.c' if '--numstat' in args else b'M\0main.c\0'
        with patch('ecra.git_diff.git',side_effect=query):
            with self.assertRaisesRegex(ValueError,'内容差异记录未完整结束'):git_diff.changes(self.repo,'HEAD')

    def test_unmatched_real_content_record_is_never_silently_dropped(self):
        def query(root,*args,**kwargs):
            return b'1\t1\tother.c\0' if '--numstat' in args else b'M\0main.c\0'
        with patch('ecra.git_diff.git',side_effect=query):
            with self.assertRaisesRegex(ValueError,'拒绝丢弃真实源码变化'):git_diff.changes(self.repo,'HEAD')


class CaptureReached(Exception): pass


@unittest.skipUnless(os.name=='nt','Actual Windows security/notification contract')
class GuardedAdmissionTests(GitFixture):
    def setUp(self):
        super().setUp()
        self.repo=self.home/'fresh-real-clone'
        self.run_git('clone','--no-hardlinks',str(self.origin),str(self.repo),root=self.origin)
        self.run_git('remote','remove','origin')
        (self.repo/'value.h').write_bytes(b'#define STEP 7\n')
        self.config=self.home/'semantics.json';self.config.write_text('{}','utf-8')
        self.cfg=dict(analysis=dict(compile_database='auto',cmake=dict(generator='Ninja',location='workspace')))
        self.workspace=SimpleNamespace(repository_root=str(self.repo))

    def boundary(self, action=None):
        from ecra.guarded_cmake import InputWatch
        from ecra.working_cmake import prepare
        # This test deliberately stops after real permission checks and kernel
        # watch installation. It is not counted as a complete CMake/scan pass.
        with InputWatch() as watch:
            def capture(*args,**kwargs):
                if action:action()
                watch.check()
                raise CaptureReached()
            with patch('ecra.working_snapshot.capture',side_effect=capture):
                prepare(self.repo,self.config,self.cfg,self.workspace,self.home/'unused',lambda _:None,
                        SimpleNamespace(stage=lambda _:None),watch)

    def test_fresh_real_clone_admission_reaches_capture_without_false_notification(self):
        before=self.index()
        with self.assertRaises(CaptureReached):self.boundary()
        self.assertEqual(self.index(),before)

    def test_source_byte_change_and_restore_after_freeze_is_still_rejected(self):
        file=self.repo/'main.c';raw=file.read_bytes();stamp=file.stat()
        def change():
            file.write_bytes(raw+b'int changed;\n');file.write_bytes(raw)
            os.utime(file,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
        with self.assertRaisesRegex(ValueError,'CMake输入目录.*变化'):self.boundary(change)

    def test_actual_head_change_and_restore_after_freeze_is_still_rejected(self):
        head=self.run_git('rev-parse','HEAD').strip().decode();old=self.run_git('rev-parse','HEAD^').strip().decode()
        def change():
            self.run_git('update-ref','HEAD',old);self.run_git('update-ref','HEAD',head)
        with self.assertRaisesRegex(ValueError,'CMake输入目录.*变化'):self.boundary(change)

    def test_actual_index_change_after_freeze_is_still_rejected(self):
        def change():self.run_git('add','value.h')
        with self.assertRaisesRegex(ValueError,'CMake输入目录.*变化'):self.boundary(change)

    def label(self, level):
        result=subprocess.run(['icacls',str(self.repo/'main.c'),'/setintegritylevel',level],capture_output=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_actual_acl_change_and_restore_after_freeze_is_still_rejected(self):
        def change():
            try:self.label('L')
            finally:self.label('M')
        with self.assertRaisesRegex(ValueError,'CMake输入目录.*变化'):self.boundary(change)

    def test_permission_change_between_admission_and_watch_is_checked_again(self):
        from ecra import guarded_cmake
        original=guarded_cmake.require_protected_source;calls=[]
        def check(root):
            calls.append(root);original(root)
            if len(calls)==1:self.label('L')
        try:
            with patch('ecra.guarded_cmake.require_protected_source',side_effect=check):
                with self.assertRaisesRegex(ValueError,'原源码完整性标签不能保证只读'):self.boundary()
            self.assertEqual(len(calls),2,'the mandatory second check closes the permission gap')
        finally:self.label('M')


if __name__=='__main__':unittest.main()
