"""A classifier change must invalidate a saved scan before review resumes."""

import json
from pathlib import Path
from subprocess import CompletedProcess
import tempfile
import unittest
from unittest.mock import patch

from ecra import workflow
from ecra.common import read_json, write_json
from ecra.workflow import engine_digest, REVIEW_REPORT_MODULES


class EngineDigestCoverageTests(unittest.TestCase):
    def test_digest_includes_classification_and_phase_modules(self):
        seen = []

        def record(path):
            seen.append(path.name)
            return path.name

        with patch('ecra.workflow.file_digest', side_effect=record):
            engine_digest()
        self.assertTrue({'evidence.py', 'initialization.py', 'diagnostics.py',
                         'extract.py', 'points_to.py', 'cli.py', 'config.py',
                         'common.py', 'compilation.py', 'stale_writeback.py'} <= set(seen))
        self.assertFalse(REVIEW_REPORT_MODULES & set(seen))

    def test_review_changes_do_not_change_static_digest_but_new_modules_do(self):
        with tempfile.TemporaryDirectory() as temp:
            package = Path(temp)
            (package / 'analysis.py').write_text('static analysis v1', encoding='utf-8')
            for name in REVIEW_REPORT_MODULES:
                (package / name).write_text('review/report v1', encoding='utf-8')
            with patch('ecra.workflow.__file__', str(package / 'workflow.py')):
                original = engine_digest()
                for name in REVIEW_REPORT_MODULES:
                    (package / name).write_text('review/report v2', encoding='utf-8')
                    self.assertEqual(engine_digest(), original, name)
                (package / 'future_analysis.py').write_text('new analysis', encoding='utf-8')
                with_new_module = engine_digest()
                self.assertNotEqual(with_new_module, original)
                (package / 'analysis.py').write_text('static analysis v2', encoding='utf-8')
                self.assertNotEqual(engine_digest(), with_new_module)


class ReviewResumeDigestTests(unittest.TestCase):
    from tests.test_ecra import ProjectTest as _fixture
    setUp = _fixture.setUp
    project = _fixture.project

    def scan(self):
        from ecra.cli import run
        self.project({'a.c': 'int value;void ISR(void){value++;}void Task(void){value++;}'},
                     review=dict(enabled=True, retries=0, command=['synthetic-cli']))
        self.assertEqual(run(self.root, no_review=True), 2)
        self.out = self.root / '.ecra'
        self.cfg, self.config_file = workflow.load_config(self.root)

    def test_review_and_updated_cases_reuse_scan_and_rerun_done(self):
        self.scan()
        cases = self.config_file.with_name('concurrency_cases.md')
        cases.write_text('## CASE-0001｜ORIGINAL_CASE\nReference only.\n', encoding='utf-8')
        calls, prompts = [], []

        def respond(argv, **kwargs):
            packet = read_json(argv[argv.index('--file') + 1])
            fid = packet['finding_id']
            calls.append(fid)
            prompts.append(kwargs.get('input') or argv[-1])
            answer = dict(finding_id=fid, status='FALSE_POSITIVE', reason='模拟协议测试。',
                          summary='已确认静态误报：value 的模拟互斥访问条件已核实，仅用于协议测试。',
                          evidence=[dict(file='a.c', line=1, claim='测试源码位置。')])
            return CompletedProcess(argv, 0, json.dumps(answer), '')

        original_digest = workflow.file_digest

        def changed_review_only(path):
            return 'updated-review-module' if Path(path).name in REVIEW_REPORT_MODULES else original_digest(path)

        with patch('ecra.review.resolve_command', return_value=['synthetic-cli']), \
                patch('ecra.review.execute', side_effect=respond), \
                patch('ecra.cli.execute', side_effect=AssertionError('review must not build or reparse')):
            self.assertIn(workflow.saved_run(self.root), (1, 2))
            self.assertEqual(read_json(self.out / 'review/queue.json')[0]['state'], 'DONE')
            cases.write_text('## CASE-0001｜UPDATED_CASE\nUpdated reference only.\n', encoding='utf-8')
            with patch('ecra.workflow.file_digest', side_effect=changed_review_only):
                self.assertIn(workflow.saved_run(self.root), (1, 2))
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0], calls[1])
        self.assertIn('ORIGINAL_CASE', prompts[0])
        self.assertIn('UPDATED_CASE', prompts[1])

    def test_old_full_program_checkpoint_requires_one_static_refresh(self):
        self.scan()
        path = self.out / 'scan_state.json'
        state = read_json(path)
        state.pop('engine_scope')
        write_json(path, state)
        with patch('ecra.review.execute') as execute:
            with self.assertRaisesRegex(ValueError, '一次性.*--no-review'):
                workflow.checked_scan(self.root, self.out, self.cfg, self.config_file)
        execute.assert_not_called()

    def test_static_code_and_analysis_config_still_require_rescan(self):
        self.scan()
        original_digest = workflow.file_digest

        def changed_static(path):
            return 'updated-static-module' if Path(path).name == 'evidence.py' else original_digest(path)

        with patch('ecra.workflow.file_digest', side_effect=changed_static):
            with self.assertRaisesRegex(ValueError, '静态分析实现已变化.*--no-review'):
                workflow.checked_scan(self.root, self.out, self.cfg, self.config_file)
        self.cfg['analysis']['include_dirs'] = ['changed-scope']
        with self.assertRaisesRegex(ValueError, '分析配置已变化.*--no-review'):
            workflow.checked_scan(self.root, self.out, self.cfg, self.config_file)


if __name__ == '__main__':
    unittest.main()
