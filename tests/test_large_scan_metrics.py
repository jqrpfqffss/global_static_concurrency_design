import json
from pathlib import Path
import tempfile
import unittest

from scripts.summarize_large_scan import summarize


class LargeMetricsTests(unittest.TestCase):
    def test_recovered_monitor_keeps_unknown_exit_and_all_observation_files(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder)
            (folder/'execution.json').write_text(json.dumps(dict(seconds=None,exit_code=None,
                exit_status_unknown=True,measurement_gap=True)),encoding='utf-8')
            for name,commit in [('memory.jsonl',300),('memory-recovered.jsonl',100)]:
                (folder/name).write_text(json.dumps(dict(seconds=1,
                    system_commit_bytes=dict(CommitTotal=commit)))+'\n',encoding='utf-8')
            result=summarize(folder,folder/'output')
            self.assertIsNone(result['seconds'])
            self.assertIsNone(result['exit_code'])
            self.assertTrue(result['exit_status_unknown'])
            self.assertTrue(result['measurement_gap'])
            self.assertEqual(result['os_observations'],2)
            self.assertEqual(result['system_commit_at_max_observed_total']['CommitTotal'],300)

    def test_explicit_resource_queue_is_separate_from_elapsed_and_cpu_time(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            evidence, output = folder/'evidence', folder/'output'
            evidence.mkdir()
            (output/'diagnostics').mkdir(parents=True)
            (evidence/'execution.json').write_text(json.dumps(dict(seconds=100,exit_code=2)),encoding='utf-8')
            (evidence/'analysis-resource-wait.json').write_text(json.dumps(dict(status='COMPLETE',seconds=75)),encoding='utf-8')
            (output/'diagnostics/scan_stages.json').write_text(json.dumps([
                dict(stage='跨翻译单元事实归并',status='COMPLETE',seconds=80)]),encoding='utf-8')
            (evidence/'memory.jsonl').write_text(json.dumps(dict(seconds=90,
                system_commit_bytes=dict(CommitTotal=1000,CommitPeak=999999)))+'\n',encoding='utf-8')
            result = summarize(evidence, output)
            self.assertEqual(result['seconds'], 100)
            self.assertEqual(result['resource_wait_seconds'], 75)
            self.assertEqual(result['wall_seconds_excluding_resource_wait'], 25)
            self.assertEqual(result['stages'][0]['seconds'], 80)
            self.assertEqual(result['stages'][0]['seconds_excluding_resource_wait'], 5)
            self.assertEqual(result['system_commit_at_max_observed_total']['CommitTotal'], 1000)
            (evidence/'analysis-resource-wait.json').write_text(json.dumps(dict(status='WAITING')),encoding='utf-8')
            pending = summarize(evidence, output)
            self.assertFalse(pending['resource_wait_accounting_valid'])
            self.assertIsNone(pending['wall_seconds_excluding_resource_wait'])
