"""真实 Git 补丁完整性；不调用模型、不改写用户索引。"""
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from ecra.common import read_json, write_json
from ecra.config import load_config
from ecra.git_diff import git, pin, write_comparison_patch
from ecra.review import build_variable_review_packet
from tests import test_git_diff


class GitPatchTests(unittest.TestCase):
    setUp = test_git_diff.GitIntegrationTests.setUp
    project = test_git_diff.GitIntegrationTests.project
    repository = test_git_diff.GitIntegrationTests.repository
    command = test_git_diff.GitIntegrationTests.command
    scan = test_git_diff.GitIntegrationTests.scan

    def snapshot(self, root=None):
        cfg, _ = load_config(self.root)
        cfg['analysis']['git_diff']['include_uncommitted'] = True
        return pin(root or self.root, cfg)

    def test_staged_unstaged_unicode_binary_empty_and_leading_dash_roundtrip(self):
        self.repository()
        (self.root/'a.c').write_text('int g;void Task(void){g=71;}void ISR(void){g++;}', encoding='utf-8')
        self.command('add', 'a.c')
        (self.root/'b.c').write_text('int unrelated;void Other(void){unrelated=72;}', encoding='utf-8')
        additions = {'新 文件.h': b'#define ADDED_VALUE 314159\n', 'empty.h': b'',
                     'data.bin': b'\x00\xffBINARY\x00', '-[special].h': b'#define SPECIAL 42\n'}
        for name, value in additions.items():
            (self.root/name).write_bytes(value)
        pinned = self.snapshot()
        before = (self.root/'.git/index').read_bytes()
        destination = self.root/'.ecra/patches/change.patch'
        write_comparison_patch(pinned, destination)
        data = destination.read_bytes()
        self.assertIn(b'314159', data)
        self.assertIn(b'GIT binary patch', data)
        self.assertIn(b'empty.h', data)
        self.assertEqual(before, (self.root/'.git/index').read_bytes())
        self.assertEqual(pinned, self.snapshot())
        # Applying the archive to a separate clone proves added/deleted bytes
        # and binary payloads, rather than merely searching patch text.
        with tempfile.TemporaryDirectory(prefix='ecra-patch-clone-') as name:
            clone = Path(name)/'clone'
            subprocess.check_output(['git', 'clone', '--no-hardlinks', str(self.root), str(clone)], stderr=subprocess.STDOUT)
            subprocess.check_output(['git', '-C', str(clone), '-c', 'core.autocrlf=false',
                                     'apply', '--binary', str(destination)], stderr=subprocess.STDOUT)
            for name in ('a.c', 'b.c', *additions):
                self.assertEqual((self.root/name).read_bytes(), (clone/name).read_bytes())

    def test_project_subdirectory_uses_repository_relative_paths(self):
        self.repository()
        sub = self.root/'固件 子目录'
        sub.mkdir()
        (sub/'新 文件.h').write_bytes(b'#define SUBDIR_VALUE 161803\n')
        pinned = self.snapshot(sub)
        destination = self.root/'.ecra/subdir.patch'
        write_comparison_patch(pinned, destination)
        with tempfile.TemporaryDirectory(prefix='ecra-patch-subdir-') as name:
            clone = Path(name)/'clone'
            subprocess.check_output(['git', 'clone', '--no-hardlinks', str(self.root), str(clone)], stderr=subprocess.STDOUT)
            subprocess.check_output(['git', '-C', str(clone), '-c', 'core.autocrlf=false',
                                     'apply', str(destination)], stderr=subprocess.STDOUT)
            self.assertEqual((sub/'新 文件.h').read_bytes(), (clone/'固件 子目录/新 文件.h').read_bytes())

    def test_failure_preserves_old_archive_and_removes_pending(self):
        self.repository()
        source = self.root/'new.h'
        source.write_bytes(b'#define NEW_VALUE 5\n')
        pinned = self.snapshot()
        destination = self.root/'.ecra/existing.patch'
        destination.write_bytes(b'previous complete archive')
        real_git = git
        def fail(root, *args, **kwargs):
            if '--no-index' in args:
                raise ValueError('模拟新增文件补丁失败')
            return real_git(root, *args, **kwargs)
        with patch('ecra.git_diff.git', side_effect=fail):
            with self.assertRaisesRegex(ValueError, '模拟'):
                write_comparison_patch(pinned, destination)
        self.assertEqual(destination.read_bytes(), b'previous complete archive')
        self.assertFalse(list(destination.parent.glob('.patch-*.pending')))
        # Git no-index also returns 1 on an unreadable/disappeared input. It
        # must not be accepted as the normal "difference found" return code.
        source.unlink()
        with self.assertRaises(ValueError):
            write_comparison_patch(pinned, destination)
        self.assertEqual(destination.read_bytes(), b'previous complete archive')
        self.assertFalse(list(destination.parent.glob('.patch-*.pending')))

    def test_new_header_definition_reaches_saved_diff_and_complete_packet(self):
        self.repository()
        cfg = read_json(self.root/'.ecra/semantics.yaml')
        cfg['analysis']['git_diff']['include_uncommitted'] = True
        write_json(self.root/'.ecra/semantics.yaml', cfg)
        (self.root/'新 文件.h').write_text('#define ADDED_VALUE 314159\n', encoding='utf-8')
        (self.root/'a.c').write_text('#include "新 文件.h"\nint g;void Task(void){g=ADDED_VALUE;}void ISR(void){g++;}', encoding='utf-8')
        report = self.scan()
        facts = read_json(self.root/'.ecra/facts.json')
        finding = next(f for f in report['findings'] if f.get('symbol_id') == 'c:@g')
        packet = build_variable_review_packet(self.root, facts, finding,
            facts_path='facts.json', shared_path='shared.json', report_path='report.json')
        saved = Path(packet['git_diff_impact']['diff_patch_path'])
        self.assertIn(b'314159', saved.read_bytes())
        self.assertEqual(str(saved), report['git_diff']['pin']['diff_patch_path'])
        self.assertTrue({'Task', 'ISR'}.issubset({f['name'] for f in packet['functions']}))


if __name__ == '__main__':
    unittest.main()
