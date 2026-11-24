"""验收脚本的真实基准审计与中断恢复，不执行模型。"""
import json
from pathlib import Path
import subprocess
import sys
import unittest

from tests import test_ecra


class BenchmarkAuditTests(unittest.TestCase):
    setUp = test_ecra.ProjectTest.setUp
    project = test_ecra.ProjectTest.project

    def invoke(self, evidence, *options):
        return subprocess.run([sys.executable, '-B', str(test_ecra.ROOT/'scripts/benchmark_project_scan.py'),
            '--project', str(self.root), '--config', str(self.root/'.ecra/semantics.yaml'),
            '--scan-mode', 'diff', '--evidence', str(evidence), '--legacy-output', *options],
            capture_output=True, encoding='utf-8', errors='replace', timeout=120)

    def test_real_baseline_audit_saved_resume_and_changed_inputs_rejected(self):
        self.project({'a.c': 'int g;void Task(void){g=1;}void ISR(void){g++;}'},
                     review=dict(enabled=False, prepare_packets=False))
        config = self.root/'.ecra/semantics.yaml'
        cfg = json.loads(config.read_text(encoding='utf-8'))
        cfg['analysis']['git_diff'] = dict(enabled=True, base_ref='audit-base', current_ref='HEAD', include_uncommitted=False)
        config.write_text(json.dumps(cfg), encoding='utf-8')
        (self.root/'.gitignore').write_text('.ecra/\n', encoding='utf-8')
        def git(*args):
            subprocess.run(['git', '-C', str(self.root), *args], check=True, capture_output=True)
        git('init', '-q')
        git('add', 'a.c', '.gitignore', 'compile_commands.json')
        git('-c', 'user.name=验收测试', '-c', 'user.email=ecra-test@example.invalid', 'commit', '-qm', '基准')
        git('tag', 'audit-base')
        (self.root/'a.c').write_text('int g;void Task(void){g=2;}void ISR(void){g++;}', encoding='utf-8')
        git('-c', 'user.name=验收测试', '-c', 'user.email=ecra-test@example.invalid', 'commit', '-qam', '当前输入')
        evidence = self.root.parent/(self.root.name+'-audit')
        evidence.mkdir()
        self.addCleanup(lambda: __import__('shutil').rmtree(evidence))
        evidence = evidence/'first'
        first = self.invoke(evidence, '--audit-baseline')
        console = evidence/'console.log'
        self.assertEqual(first.returncode, 0, first.stdout+first.stderr+
                         (console.read_text('utf-8')[-2500:] if console.is_file() else ''))
        receipt = evidence/'execution.json'
        original = json.loads(receipt.read_text(encoding='utf-8'))
        self.assertTrue(original['complete'])
        self.assertTrue(original['baseline_artifact_audit']['passed'])
        self.assertFalse(original['review_executed'])
        def interrupted():
            record = dict(original, complete=False)
            receipt.write_text(json.dumps(record), encoding='utf-8')
        interrupted()  # 明确模拟审计记录未完成，保留真实 CLI 的测量与产物。
        resumed = self.invoke(evidence, '--audit-baseline', '--audit-saved')
        self.assertEqual(resumed.returncode, 0, resumed.stdout+resumed.stderr)
        saved = json.loads(receipt.read_text(encoding='utf-8'))
        self.assertTrue(saved['complete'])
        for key in ('seconds', 'peak_tree_rss_bytes', 'exit_code', 'command'):
            self.assertEqual(saved[key], original[key])
        self.assertFalse(saved['audit_resumptions'][0]['ast_extraction_executed'])
        self.assertEqual(self.invoke(evidence, '--audit-baseline', '--audit-saved').returncode, 1)
        interrupted()
        self.assertNotEqual(self.invoke(evidence, '--audit-saved').returncode, 0)  # 不能取消既定的基准审计。
        (self.root/'a.c').write_text('int g;void Task(void){g=3;}void ISR(void){g++;}', encoding='utf-8')
        git('-c', 'user.name=验收测试', '-c', 'user.email=ecra-test@example.invalid', 'commit', '-qam', '更新当前输入')
        # A moving live branch leaves the scan's frozen evidence valid. Mutate
        # the actual pinned input in this disposable fixture to test rejection.
        scan = Path(original['output'])
        pin = json.loads((scan/'scan_state.json').read_bytes())['git_diff_pin']
        with Path(pin['base_summary_path']).open('ab') as stream:
            stream.write(b' ')
        invalid = self.invoke(evidence, '--audit-baseline', '--audit-saved')
        self.assertNotEqual(invalid.returncode, 0)
        self.assertFalse(json.loads(receipt.read_text(encoding='utf-8'))['complete'])

    def test_cli_rejects_incompatible_audit_options_before_scanning(self):
        scripts = test_ecra.ROOT/'scripts'
        common = ['--project', str(self.root), '--config', str(self.root/'missing.yaml'),
                  '--evidence', str(self.root/'missing')]
        commands = [
            [str(scripts/'benchmark_project_scan.py'), *common, '--scan-mode', 'full', '--audit-baseline'],
            [str(scripts/'validate_inav_git_diff.py'), *common, '--ruby-bin', str(self.root),
             '--start-at-diff', '--baseline-reference', str(self.root/'missing.json')]]
        for command in commands:
            with self.subTest(script=command[0]):
                result = subprocess.run([sys.executable, '-B', *command], capture_output=True, timeout=30)
                self.assertEqual(result.returncode, 2)
        self.assertFalse((self.root/'missing').exists())


if __name__ == '__main__':
    unittest.main()
