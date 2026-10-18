"""Queue/repair/process regression tests with explicitly synthetic responses."""
import copy
import json
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from ecra.common import read_json, write_json
from ecra.review import review_all, verify_receipt
from ecra.review_integrity import review_integrity, assert_review_archive, STATES
from tests.test_review_contract import answer_for


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.out = self.root / '.ecra'
        (self.root / 'app.c').write_text('int shared;\nvoid IRQ(void){shared++;}\n', encoding='utf-8')
        self.facts = dict(variables=[], contexts=[], functions=[], calls=[])
        self.report = dict(findings=[dict(finding_id='F', static_classification='SUSPECT', accesses=[])],
                           coverage={}, limitations=[])
        self.cfg = dict(review=dict(enabled=True, retries=0, workers=1), analysis={})

    def run_review(self, respond, mode='run', progress=lambda _: None, on_result=None):
        with patch('ecra.review.resolve_command', return_value=['synthetic-cli']), patch(
                'ecra.review.execute', side_effect=respond):
            return review_all(self.root, self.out, self.cfg, self.facts, self.report, 'scan',
                              progress, on_result, mode=mode)

    def response(self, value):
        return CompletedProcess([], 0, json.dumps(dict(type='text', part=dict(text=json.dumps(value)))), '')

    def test_each_semantic_status_is_done_and_never_selected_by_review_failed(self):
        for status in ('CONFIRMED', 'LIKELY', 'REVIEWED_SAFE', 'FALSE_POSITIVE', 'NEED_MORE_CONTEXT'):
            with self.subTest(status=status):
                first = self.run_review(lambda *a, **k: self.response(answer_for(status)), mode='review')
                self.assertEqual(first[0]['review_state'], 'DONE')
                self.assertEqual(first[0]['review_status'], status)
                self.run_review(lambda *a, **k: self.fail('DONE must not be re-reviewed'), mode='review-failed')

    def test_format_fix_one_or_two_success_and_two_failures(self):
        for bad_count in (1, 2, 3):
            with self.subTest(bad_count=bad_count):
                self.out = self.root / f'.case{bad_count}'
                calls = []
                original = dict(answer_for(), reason='')

                def respond(argv, **kwargs):
                    calls.append((argv, kwargs))
                    return self.response(original if len(calls) <= bad_count else answer_for())

                row = self.run_review(respond)[0]
                self.assertEqual(len(calls), min(bad_count + 1, 3))
                self.assertEqual(row['state'], 'TECH_FAILED' if bad_count == 3 else 'DONE')
                self.assertEqual(row['format_fix_count'], min(bad_count, 2))
                self.assertIn('--file', calls[0][0])
                for argv, kwargs in calls[1:]:
                    self.assertNotIn('--file', argv)
                    self.assertIn('FORMAT_FIX', argv[-1])
                    self.assertIn('不要重新分析或读取源码', argv[-1])
                    self.assertIn('"reason": ""', argv[-1])
                    permissions = json.loads(kwargs['env']['OPENCODE_PERMISSION'])
                    self.assertEqual(permissions, {'*': 'deny'})
                    self.assertNotIn('project_evidence_path', argv[-1])
                if row['state'] == 'DONE':
                    verify_receipt(self.root, self.out / 'review', row)

    def test_retries_apply_to_transport_only_and_format_fixes_remain_bounded(self):
        self.cfg['review']['retries'] = 1
        calls = []

        def respond(argv, **kwargs):
            calls.append(argv)
            if len(calls) == 1:
                return CompletedProcess([], 1, 'partial', 'provider unavailable')
            return self.response(dict(answer_for(), reason=''))

        row = self.run_review(respond)[0]
        self.assertEqual(len(calls), 4)  # two analysis calls + two formatting calls
        self.assertEqual(sum('--file' in argv for argv in calls), 2)
        self.assertEqual(row['state'], 'TECH_FAILED')

    def test_long_raw_answer_format_fix_uses_stdin_without_packet_or_truncation(self):
        calls = []

        def respond(argv, **kwargs):
            calls.append(argv)
            if len(calls) == 1:
                return self.response(dict(answer_for(), status='BAD_STATUS', reason='已有分析' * 20000))
            self.assertNotIn('--file', argv)
            content = kwargs['input']
            self.assertIn(json.dumps('已有分析' * 100)[1:-1], content)
            self.assertIn('FORMAT_FIX', content)
            self.assertNotIn('project_evidence_path', content)
            self.assertLess(sum(len(a) for a in argv), 12000)
            self.assertEqual(json.loads(kwargs['env']['OPENCODE_PERMISSION']), {'*': 'deny'})
            return self.response(answer_for())

        row = self.run_review(respond)[0]
        self.assertEqual(row['state'], 'DONE')
        self.assertEqual(len(calls), 2)

    def test_timeout_provider_error_exit_and_missing_command_are_technical(self):
        cases = [subprocess.TimeoutExpired(['synthetic'], 1, output=b'partial-output', stderr=b'partial-error'),
                 CompletedProcess([], 1, 'raw stdout', 'provider error'),
                 CompletedProcess([], 0, json.dumps(dict(type='error', error='provider failed')), ''),
                 CompletedProcess([], 0, json.dumps(dict(type='tool_use', part=dict(tool='read',
                    state=dict(status='completed', output='SOURCE_MUST_NOT_ENTER_FORMAT_FIX')))), '')]
        for index, response in enumerate(cases):
            with self.subTest(index=index):
                self.out = self.root / f'.failure{index}'
                calls = []

                def respond(*args, **kwargs):
                    calls.append(args)
                    if isinstance(response, Exception):
                        raise response
                    return response

                row = self.run_review(respond)[0]
                self.assertEqual(row['state'], 'TECH_FAILED')
                self.assertIsNone(row['review_status'])
                self.assertNotIn('answer', row)
                self.assertEqual(row['format_fix_count'], 0)
                self.assertEqual(len(calls), 1)
                for stream in ('stdout', 'stderr'):
                    self.assertTrue((self.out / 'review' / row['execution'][stream + '_file']).is_file())
                self.assertTrue(row['last_error']['type'])
                self.assertTrue(row['last_attempt_time'])
        self.out = self.root / '.launch-failure'
        with patch('ecra.review.resolve_command', side_effect=ValueError('missing OpenCode')):
            row = review_all(self.root, self.out, self.cfg, self.facts, self.report, 'scan', lambda _: None)[0]
        self.assertEqual(row['state'], 'TECH_FAILED')
        self.assertEqual(row['failure_stage'], 'launch')
        self.assertEqual(row['attempt_count'], 1)
        self.assertTrue(row['execution']['stderr_file'])
        self.assertEqual(row['attempts'][0], row['execution'])
        old_stderr = row['execution']['stderr_file']
        fixed = self.run_review(lambda *a, **k: self.response(answer_for()), mode='review-failed')[0]
        self.assertEqual(fixed['state'], 'DONE')
        self.assertEqual(fixed['attempts'][0]['stderr_file'], old_stderr)
        self.assertTrue((self.out / 'review' / old_stderr).is_file())

    def test_nonzero_exit_preserves_stdout_api_error_without_headers_or_format_fix(self):
        event=dict(type='error',error=dict(name='APIError',data=dict(statusCode=429,
            message='Your credit balance is running low',
            responseHeaders={'authorization':'SENSITIVE_HEADER_SENTINEL'},
            responseBody='SENSITIVE_BODY_SENTINEL')))
        calls=[]
        def respond(*args,**kwargs):
            calls.append(args)
            return CompletedProcess([],1,json.dumps(event),'')
        row=self.run_review(respond)[0]
        self.assertEqual(row['state'],'TECH_FAILED')
        self.assertIn('HTTP 429',row['error'])
        self.assertIn('credit balance',row['error'])
        self.assertNotIn('SENSITIVE_',row['error'])
        self.assertEqual(row['format_fix_count'],0)
        self.assertEqual(len(calls),1)
        self.assertNotIn('answer',row)

    def test_review_reruns_all_static_candidates_independent_of_previous_semantics(self):
        statuses = ['CONFIRMED', 'LIKELY', 'REVIEWED_SAFE', 'FALSE_POSITIVE', 'NEED_MORE_CONTEXT'] * 2
        self.report['findings'] = [dict(finding_id=f'F{i}', static_classification='UNKNOWN' if i % 2 else 'SUSPECT', accesses=[])
                                   for i in range(10)]
        calls = []

        def respond(argv, **kwargs):
            packet = read_json(Path(argv[argv.index('--file') + 1]))
            fid = packet['finding_id']
            calls.append(fid)
            return self.response(answer_for(statuses[int(fid[1:])], fid))

        self.run_review(respond)
        calls.clear()
        rows = self.run_review(respond, mode='review')
        self.assertEqual(len(calls), 10)
        self.assertEqual(set(calls), {f'F{i}' for i in range(10)})
        self.assertTrue(all(r['state'] == 'DONE' for r in rows))
        self.assertTrue(all(r['attempt_count'] == 2 for r in rows))

    def test_review_failed_repeats_only_remaining_failures_and_preserves_done_receipts(self):
        self.report['findings'] = [dict(finding_id=f'F{i}', static_classification='SUSPECT', accesses=[]) for i in range(10)]
        failures = {'F8', 'F9'}
        calls = []

        def respond(argv, **kwargs):
            fid = read_json(Path(argv[argv.index('--file') + 1]))['finding_id']
            calls.append(fid)
            if fid in failures:
                return CompletedProcess([], 1, '', 'synthetic transport failure')
            return self.response(answer_for('NEED_MORE_CONTEXT', fid))

        first = self.run_review(respond)
        self.assertEqual(CounterStates(first), {'DONE': 8, 'TECH_FAILED': 2})
        preserved = {f'F{i}': (self.out / 'review' / f'F{i}.result.json').read_bytes() for i in range(8)}
        calls.clear()
        failures.remove('F8')
        second = self.run_review(respond, mode='review-failed')
        self.assertEqual(set(calls), {'F8', 'F9'})
        self.assertEqual(CounterStates(second), {'DONE': 9, 'TECH_FAILED': 1})
        calls.clear()
        self.run_review(respond, mode='review-failed')
        self.assertEqual(calls, ['F9'])
        failures.clear()
        rows = self.run_review(respond, mode='review-failed')
        self.assertEqual(rows[-1]['attempt_count'], 4)
        self.assertTrue(all(r['state'] == 'DONE' for r in rows))
        for fid, data in preserved.items():
            self.assertEqual((self.out / 'review' / (fid + '.result.json')).read_bytes(), data)

    def test_batches_run_to_completion_with_bounded_concurrency_and_complete_ordered_ledger(self):
        self.cfg['review'].update(workers=4, max_items=5)
        self.report['findings'] = [dict(finding_id=f'F{i}', accesses=[]) for i in range(23)]
        active = peak = 0
        calls, batches = [], []
        lock = threading.Lock()

        def respond(argv, **kwargs):
            nonlocal active, peak
            fid = read_json(Path(argv[argv.index('--file') + 1]))['finding_id']
            with lock:
                active += 1
                peak = max(peak, active)
                calls.append(fid)
            time.sleep(.01)
            with lock:
                active -= 1
            return self.response(answer_for(fid=fid))

        def progress(message):
            if '当前批次' in message:
                self.assertEqual(active, 0)
                batches.append(message)

        def checkpoint(current):
            queue = read_json(self.out / 'review/queue.json')
            self.assertEqual([r['finding_id'] for r in queue], [f'F{i}' for i in range(23)])
            self.assertTrue(review_integrity(self.report, queue)['complete'])

        rows = self.run_review(respond, progress=progress, on_result=checkpoint)
        self.assertEqual(len(calls), 23)
        self.assertEqual(len(batches), 5)
        self.assertLessEqual(peak, 4)
        self.assertGreater(peak, 1)
        self.assertTrue(all(r['state'] == 'DONE' for r in rows))
        calls.clear()
        self.run_review(respond)  # only normal run reuses valid receipts
        self.assertEqual(calls, [])

    def test_archive_covers_format_analysis_and_final_answer_and_source(self):
        calls = []

        def respond(*args, **kwargs):
            calls.append(args)
            return self.response(dict(answer_for(), reason='') if len(calls) == 1 else answer_for())

        row = self.run_review(respond)[0]
        folder = self.out / 'review'
        verify_receipt(self.root, folder, row)
        original_log = folder / row['attempts'][0]['stdout_file']
        original_log.write_text('tampered', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '校验失败'):
            verify_receipt(self.root, folder, row)
        replacement = self.run_review(lambda *a, **k: self.response(answer_for()), mode='review')[0]
        verify_receipt(self.root, folder, replacement)
        (self.root / 'app.c').write_text('int changed;\nvoid IRQ(void){changed++;}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '源码'):
            verify_receipt(self.root, folder, replacement)

    def test_preparation_error_does_not_abandon_later_variables(self):
        self.report['findings'].append(dict(finding_id='G', accesses=[]))
        from ecra.review import build_variable_review_packet

        def build(root, facts, finding, **kwargs):
            if finding['finding_id'] == 'F':
                raise OSError('synthetic unreadable source')
            return build_variable_review_packet(root, facts, finding, **kwargs)

        def respond(argv, **kwargs):
            fid = read_json(Path(argv[argv.index('--file') + 1]))['finding_id']
            return self.response(answer_for(fid=fid))

        with patch('ecra.review.build_variable_review_packet', side_effect=build):
            rows = self.run_review(respond)
        self.assertEqual([r['state'] for r in rows], ['TECH_FAILED', 'DONE'])
        assert_review_archive(self.report, rows, self.out / 'review')

    def test_three_states_and_integrity_errors_do_not_count_unknown_verdict_as_failure(self):
        self.assertEqual(STATES, {'PENDING', 'DONE', 'TECH_FAILED'})
        valid = dict(finding_id='F', state='DONE', status='NEED_MORE_CONTEXT', answer=answer_for('NEED_MORE_CONTEXT'))
        stats = review_integrity(self.report, [valid], require_terminal=True)
        self.assertTrue(stats['all_done'])
        self.assertEqual(stats['failed'], 0)
        self.assertTrue(review_integrity(self.report, [valid, valid])['errors'])
        self.assertTrue(review_integrity(self.report, [])['errors'])
        self.assertTrue(review_integrity(self.report, [dict(finding_id='F', state='TECH_FAILED')])['errors'])

    def test_re_review_navigation_never_exposes_previous_model_answers(self):
        self.report['findings'][0].update(review=dict(reason='OLD_MODEL_ANSWER'),
            review_result=dict(answer='OLD_MODEL_ANSWER'), review_state='DONE',
            review_status='REVIEWED_SAFE', status='REVIEWED_SAFE')
        self.report['review_records'] = [dict(answer='OLD_MODEL_ANSWER')]

        def respond(argv, **kwargs):
            packet = read_json(Path(argv[argv.index('--file') + 1]))
            static = Path(packet['static_report_path']).read_text(encoding='utf-8')
            self.assertNotIn('OLD_MODEL_ANSWER', static)
            self.assertNotIn('OLD_MODEL_ANSWER', json.dumps(packet))
            return self.response(answer_for())

        self.assertEqual(self.run_review(respond, mode='review')[0]['state'], 'DONE')


def CounterStates(rows):
    from collections import Counter
    return dict(Counter(r['state'] for r in rows))


if __name__ == '__main__':
    unittest.main()
