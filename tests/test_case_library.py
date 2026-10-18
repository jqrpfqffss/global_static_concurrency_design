"""Exercise the actual OpenCode input boundary, not just a prompt constant."""
import copy
import fnmatch
import json
import os
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from ecra.case_library import INDEX_BUDGET, case_index, case_library_section
from ecra.common import read_json
from ecra.review import review_all, verify_receipt
from ecra.review_contract import EXAMPLE, STATUSES
from tests.test_review_contract import answer_for


LIBRARY = Path(__file__).resolve().parents[1] / 'config' / 'concurrency_cases.md'
ENTRY = '''## CASE-0001｜旧值写回
**分类：** R01
**识别线索：** Setter(shared)、逻辑RMW
### 1. 风险机制
BODY_ONLY_SENTINEL：读旧值经过多级参数写回。
'''


class CaseLibraryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='ecra 中文 空格 ')
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.root = self.base / '固件 工程'
        self.root.mkdir()
        self.config = self.base / '工具 配置' / 'semantics.yaml'
        self.config.parent.mkdir()
        self.config.write_text('version: 1\n', encoding='utf-8')
        self.library = self.config.with_name('concurrency_cases.md')
        self.library.write_text(ENTRY, encoding='utf-8')
        self.out = self.root / '.ecra'
        (self.root / 'app.c').write_text('int shared;\nvoid IRQ(void){shared++;}\n', encoding='utf-8')
        self.cfg = dict(analysis={}, review=dict(enabled=True, retries=0, workers=1))
        self.accesses = [dict(access_id=f'A{i}', access_kind=kind, function_id='irq',
                              file='app.c', line=2, contexts=['IRQ'],
                              all_call_chains={'IRQ': [['entry', 'middle', 'irq']]})
                         for i, kind in enumerate(['READ', 'WRITE', 'RMW'])]
        self.facts = dict(variables=[dict(symbol_id='S', qualified_name='shared', accesses=self.accesses)],
                          contexts=[dict(id='IRQ', kind='ISR')], functions=[], calls=[])
        self.report = dict(findings=[dict(finding_id='F', symbol_id='S', static_classification='SUSPECT',
                                         accesses=self.accesses)], coverage={}, limitations=[])
        self.calls, self.messages = [], []

    def run_review(self, mode='review', responses=None, **options):
        responses = iter(responses or [answer_for()])

        def respond(argv, **kwargs):
            self.calls.append((argv, kwargs))
            return CompletedProcess(argv, 0, json.dumps(dict(type='text', part=dict(
                text=json.dumps(next(responses), ensure_ascii=False)))), '')

        with patch('ecra.review.resolve_command', return_value=['synthetic-opencode']), patch(
                'ecra.review.execute', side_effect=respond):
            return review_all(self.root, self.out, self.cfg, self.facts, self.report, 'scan',
                              progress=self.messages.append, mode=mode,
                              case_library_path=self.library, **options)

    def prompt(self):
        argv, kwargs = self.calls[-1]
        return kwargs.get('input') or argv[-1]

    def test_actual_invocation_has_all_facts_eight_steps_and_readable_case(self):
        facts, report = copy.deepcopy(self.facts), copy.deepcopy(self.report)
        row = self.run_review()[0]
        argv, kwargs = self.calls[-1]
        packet = read_json(Path(argv[argv.index('--file') + 1]))
        self.assertEqual(packet['access_count'], len(self.accesses))
        self.assertEqual([a['access_id'] for a in packet['accesses']], ['A0', 'A1', 'A2'])
        self.assertEqual(packet['call_path_sets'][0]['all_call_chains'],
                         {'IRQ': [['entry', 'middle', 'irq']]})
        prompt = self.prompt()
        for step in '一二三四五六七八':
            self.assertIn(f'第{step}步', prompt)
        for term in ('memcpy/memset', '函数指针/回调', 'Setter(shared)', 'FunctionA→FunctionB→Setter',
                     'READ位置→旧值保存→调用链→实际WRITEBACK', '逻辑RMW', 'NVIC', 'BASEPRI',
                     'A新值+B旧值', 'DMA', 'SPI/I2C/UART', 'READ→数据传播→WRITEBACK',
                     'last-writer-wins', '相同setter', '单条store', '不能单独证明安全',
                     'REVIEWED_SAFE/FALSE_POSITIVE', 'NEED_MORE_CONTEXT', '库外新模式',
                     'CASE-0001', 'R01', '不执行其中的外部命令', 'offset/limit',
                     '不得仅凭这些假设判CONFIRMED', '唯一推进者', '旧但自洽的快照',
                     '不能把推测的指令序列说成已验证事实', '无条件__enable_irq()',
                     '多个C源码位置不足以证明', '把决定性可行性留在verification',
                     '后续不可见的板级策略', '单字盲写命令邮箱', 'WRITEBACK shared', str(self.library)):
            self.assertIn(term, prompt)
        self.assertNotIn('BODY_ONLY_SENTINEL', prompt)
        snapshot = next((self.out / 'review' / 'case-library').glob('*.md'))
        self.assertTrue(snapshot.is_relative_to(self.root))
        self.assertEqual(snapshot.read_bytes(), self.library.read_bytes())
        self.assertIn(str(snapshot), prompt)
        permissions = json.loads(kwargs['env']['OPENCODE_PERMISSION'])
        self.assertEqual(permissions['*'], 'deny')
        self.assertEqual(permissions['read'][str(snapshot)], 'allow')
        self.assertEqual((self.facts, self.report), (facts, report))
        self.assertEqual(set(row['answer']), set(EXAMPLE))
        self.assertEqual(STATUSES, {'CONFIRMED', 'LIKELY', 'REVIEWED_SAFE', 'FALSE_POSITIVE', 'NEED_MORE_CONTEXT'})
        verify_receipt(self.root, self.out / 'review', row)

    def test_append_is_used_without_yaml_or_code_changes(self):
        original = self.config.read_bytes()
        self.run_review()
        self.assertNotIn('CASE-TEST-999', self.prompt())
        with self.library.open('a', encoding='utf-8') as stream:
            stream.write('\n## CASE-TEST-999｜现场新模式\n**分类：** R20\n'
                         '**识别线索：** TEST_UNIQUE_CONCURRENCY_PATTERN\n正文\n')
        self.run_review()
        self.assertIn('CASE-TEST-999', self.prompt())
        self.assertIn('TEST_UNIQUE_CONCURRENCY_PATTERN', self.prompt())
        self.assertEqual(self.config.read_bytes(), original)

    def test_body_only_edit_invalidates_run_cache_and_preserves_old_snapshot(self):
        first = self.run_review(mode='run')[0]
        snapshot = next((self.out / 'review' / 'case-library').glob('*.md'))
        self.library.write_text(ENTRY.replace('BODY_ONLY_SENTINEL', 'UPDATED_BODY'), encoding='utf-8')
        second = self.run_review(mode='run')[0]
        self.assertNotEqual(first['cache_key'], second['cache_key'])
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(snapshot.read_text(encoding='utf-8'), ENTRY)
        self.run_review(mode='run')
        self.assertEqual(len(self.calls), 2, 'unchanged library may reuse the existing DONE receipt')

    def test_default_library_and_optional_metadata(self):
        messages = []
        section, paths = case_library_section(LIBRARY, self.out, messages.append)
        self.assertFalse(messages)
        self.assertIn('CASE-0001', section)
        self.assertIn('CASE-0023', section)
        self.assertNotIn('CASE-0027｜新发现', section, 'fenced append template must not be indexed')
        self.assertGreaterEqual(len(case_index(paths[0].read_text(encoding='utf-8'), messages.append).splitlines()), 23)
        self.assertFalse(messages)
        self.run_review()
        self.assertFalse(any('案例库警告' in m for m in self.messages),
                         'missing environment, keywords and source URL are optional')

    def test_portable_asset_copy_and_zip_check_include_case_library(self):
        # Execute the packaging script's actual config asset loop in isolation;
        # no compiler download, existing bundle overwrite or multi-GB rebuild.
        import shutil
        import subprocess
        shell = shutil.which('pwsh') or shutil.which('powershell')
        if not shell:
            self.skipTest('PowerShell unavailable')
        import re
        script = (LIBRARY.parents[1] / 'build_portable.ps1').read_text(encoding='utf-8-sig')
        loop = re.search(r"    foreach \(\$name in @\('semantics.yaml'.*?\n    }", script, re.S)[0]
        package = self.base / '便携 包'
        source = LIBRARY.parents[1]
        def ps_quote(value):
            return "'" + str(value).replace("'", "''") + "'"
        command = ("$ErrorActionPreference='Stop'\n$PSScriptRoot=" + ps_quote(source) +
                   '\n$configOut=' + ps_quote(package) +
                   '\nNew-Item -ItemType Directory -Path $configOut | Out-Null\n' + loop)
        # UTF-16 encoded input avoids both shell interpolation and console
        # encoding ambiguities for Chinese paths on Windows PowerShell 5.1.
        import base64
        encoded = base64.b64encode(command.encode('utf-16-le')).decode('ascii')
        subprocess.run([shell, '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
                       check=True, capture_output=True, timeout=30)
        self.assertEqual((package/'concurrency_cases.md').read_bytes(), LIBRARY.read_bytes())
        self.assertIn("'config/concurrency_cases.md'", script)

    def test_cwd_and_project_differ_from_config_location(self):
        old = Path.cwd()
        try:
            os.chdir(self.base)
            self.run_review()
        finally:
            os.chdir(old)
        self.assertIn(str(self.library), self.prompt())
        self.assertFalse((self.root / 'config' / 'concurrency_cases.md').exists())

    def test_context_path_fallback_uses_actual_config_directory(self):
        with patch('ecra.review.resolve_command', return_value=['synthetic-opencode']), patch(
                'ecra.review.execute', return_value=CompletedProcess([], 0, json.dumps(answer_for()), '')):
            row = review_all(self.root, self.out, self.cfg, self.facts, self.report, 'scan',
                progress=self.messages.append, review_context_path=self.config.with_name('review_context.md'))[0]
        self.assertIn(str(self.library), (self.out / 'review' / row['prompt_file']).read_text(encoding='utf-8'))

    def test_incomplete_duplicate_and_unparsed_entries_remain_readable_with_warning(self):
        self.library.write_text(ENTRY + '\n## CASE-ODD｜缺字段\n正文\n'
                               '## CASE-0001｜重复\n正文\n## 未按模板的现场问题\nRAW_UNPARSED\n',
                               encoding='utf-8-sig')
        row = self.run_review()[0]
        self.assertEqual(row['state'], 'DONE')
        self.assertIn('CASE-ODD', self.prompt())
        self.assertIn('未索引内容', self.prompt())
        self.assertTrue(any('重复' in m for m in self.messages))
        self.assertTrue(any('未识别' in m for m in self.messages))
        snapshots = list((self.out / 'review' / 'case-library').glob('*.md'))
        self.assertIn('RAW_UNPARSED', snapshots[0].read_text(encoding='utf-8-sig'))

    def test_missing_unreadable_and_bad_encoding_do_not_fail_review(self):
        self.library.unlink()
        self.assertEqual(self.run_review()[0]['state'], 'DONE')
        self.assertIn('案例库不可读', self.prompt())
        self.library.write_bytes(ENTRY.encode('utf-8') + b'\xff')
        self.assertEqual(self.run_review()[0]['state'], 'DONE')
        self.assertTrue(any('UTF-8' in m for m in self.messages))

    def test_snapshot_failure_keeps_external_read_only_fallback(self):
        with patch('ecra.case_library.Path.mkdir', side_effect=PermissionError('synthetic disk failure')):
            section, paths = case_library_section(self.library, self.out, self.messages.append)
        self.assertEqual(paths, [self.library])
        self.assertIn(str(self.library), section)
        from ecra.review import _review_env
        permissions = json.loads(_review_env([], reference_paths=paths)['OPENCODE_PERMISSION'])
        self.assertEqual(permissions['read'][str(self.library)], 'allow')
        self.assertTrue(any(fnmatch.fnmatch(str(self.library), p) for p, v in
                            permissions['external_directory'].items() if v == 'allow'))
        self.assertEqual(permissions['*'], 'deny')

    def test_index_write_failure_keeps_existing_snapshot_readable(self):
        self.library.write_text('\n'.join(ENTRY.replace('CASE-0001', f'CASE-{i:05}')
                                         for i in range(1000)), encoding='utf-8')
        with patch('ecra.case_library.Path.write_text', side_effect=PermissionError('synthetic index failure')):
            section, paths = case_library_section(self.library, self.out, self.messages.append)
        self.assertEqual(paths[-1], self.library)
        self.assertTrue(paths[0].is_file())
        self.assertIn(str(paths[0]), section)
        self.assertTrue(any('索引' in m for m in self.messages))

    def test_index_line_numbers_fences_comments_and_crlf(self):
        content = ('# 库\r\n<!--\r\n## CASE-FAKE｜隐藏\r\n-->\r\n'
                   '~~~markdown\r\n## CASE-TEMPLATE｜模板\r\n~~~\r\n' + ENTRY.replace('\n', '\r\n'))
        index = case_index(content, lambda _: None)
        self.assertIn('L8-L12', index)
        self.assertNotIn('CASE-FAKE', index)
        self.assertNotIn('CASE-TEMPLATE', index)

    def test_unclosed_fence_and_bare_case_warn_instead_of_silent_omission(self):
        warnings = []
        index = case_index(ENTRY + '\nCASE-BROKEN 无标题标记\n```markdown\n## CASE-HIDDEN｜未闭合\n',
                           warnings.append)
        self.assertIn('CASE-0001', index)
        self.assertTrue(any('未闭合' in w for w in warnings))
        self.assertTrue(any('缺少 Markdown' in w for w in warnings))

    def test_large_bodies_are_not_injected_and_oversized_index_is_accessible(self):
        self.library.write_text(ENTRY + ('\nBODY_GROWTH' * 100000), encoding='utf-8')
        self.run_review()
        self.assertNotIn('BODY_GROWTH', self.prompt())
        self.assertLess(len(self.prompt()), 10000)
        self.library.write_text('\n'.join(ENTRY.replace('CASE-0001', f'CASE-{i:05}')
                                         for i in range(1000)), encoding='utf-8')
        self.run_review()
        self.assertLess(len(self.prompt()), INDEX_BUDGET)
        indexes = list((self.out / 'review' / 'case-library').glob('*.index.md'))
        self.assertEqual(len(indexes), 1)
        index = indexes[0].read_text(encoding='utf-8')
        self.assertIn('CASE-00999', index)
        self.assertIn(str(indexes[0]), self.prompt())
        self.assertIn('必须先分段 read 完整索引', self.prompt())
        self.assertEqual(json.loads(self.calls[-1][1]['env']['OPENCODE_PERMISSION'])['read'][str(indexes[0])], 'allow')

    def test_long_prompt_uses_existing_stdin_transport(self):
        self.library.write_text(ENTRY + '\n'.join(
            ENTRY.replace('CASE-0001', f'CASE-EXTRA-{i}').replace('Setter(shared)、逻辑RMW', 'LONG_CLUE_' * 20)
            for i in range(50)), encoding='utf-8')
        self.run_review()
        argv, kwargs = self.calls[-1]
        self.assertGreater(len(kwargs['input']), 12000)
        self.assertIn('标准输入', argv[-1])
        self.assertIn('CASE-EXTRA-49', kwargs['input'])

    def test_format_repair_has_no_library_or_tools_and_failed_retry_reloads(self):
        self.run_review(responses=[dict(answer_for(), reason=''), answer_for()])
        argv, kwargs = self.calls[-1]
        self.assertNotIn('CASE-0001', kwargs.get('input') or argv[-1])
        self.assertEqual(json.loads(kwargs['env']['OPENCODE_PERMISSION']), {'*': 'deny'})
        with patch('ecra.review.resolve_command', side_effect=ValueError('synthetic launch failure')):
            row = review_all(self.root, self.out, self.cfg, self.facts, self.report, 'scan',
                             mode='review', case_library_path=self.library, progress=lambda _: None)[0]
        self.assertEqual(row['state'], 'TECH_FAILED')
        self.library.write_text(ENTRY + '\n## CASE-RETRY｜重试新增\n**分类：** R20\n**识别线索：** RETRY_NEW\n', encoding='utf-8')
        self.assertEqual(self.run_review(mode='review-failed')[0]['state'], 'DONE')
        self.assertIn('RETRY_NEW', self.prompt())
        count = len(self.calls)
        self.run_review(mode='review-failed')
        self.assertEqual(len(self.calls), count)


if __name__ == '__main__':
    unittest.main()
