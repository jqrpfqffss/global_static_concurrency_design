"""Protocol tests use an explicit fake process; they are not real model evidence."""
import hashlib
import json
import re
import tempfile
import threading
import time
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from ecra.html_report import final_conclusion
from ecra.review import collect_evidence, parse_answer, review_all, verify_receipt
from ecra.review_integrity import assert_review_archive, assert_review_integrity, review_integrity
from tests.review_fixtures import structured_fields


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root/'app.c').write_text('int shared;\nvoid IRQ(void){shared++;}\n', encoding='utf-8')
        self.answer = dict(finding_id='F', status='CONFIRMED',
            evidence=[dict(file='app.c', line=2, quote='shared++;', claim='IRQ writes shared')],
            **{k:'protocol fixture only' for k in ('reason','interleaving','protection','impact','fix','verification')})
        self.answer.update(structured_fields(review_type='EVIDENCE_GAP'))

    def event(self, answer):
        return json.dumps(dict(type='text', part=dict(text=json.dumps(answer))))

    def test_rejects_fabricated_quote_and_missing_quote(self):
        raw = self.event(self.answer)
        self.assertEqual(parse_answer(raw, 'F', self.root, require_quotes=True), self.answer)
        self.answer['evidence'][0]['quote'] = 'disable_interrupts();'
        with self.assertRaisesRegex(ValueError, '原文与源码不符'):
            parse_answer(self.event(self.answer), 'F', self.root, require_quotes=True)
        self.answer['evidence'][0].pop('quote')
        with self.assertRaisesRegex(ValueError, 'quote'):
            parse_answer(self.event(self.answer), 'F', self.root, require_quotes=True)

    def test_receipt_requires_original_log_answer_and_source(self):
        log = self.root/'F.attempt0.jsonl'
        log.write_text(self.event(self.answer), encoding='utf-8')
        receipt = dict(finding_id='F', answer=self.answer, status='CONFIRMED',
            source_evidence=collect_evidence(self.root,self.answer),
            execution=dict(stdout_file=log.name, stdout_sha256=hashlib.sha256(log.read_bytes()).hexdigest()))
        verify_receipt(self.root,self.root,receipt)
        receipt['answer'] = dict(self.answer, reason='edited conclusion')
        with self.assertRaisesRegex(ValueError,'日志不一致'):
            verify_receipt(self.root,self.root,receipt)
        receipt['answer'] = self.answer
        log.write_text(log.read_text()+'\n{}',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'日志校验失败'):
            verify_receipt(self.root,self.root,receipt)
        log.unlink()
        with self.assertRaisesRegex(ValueError,'缺少原始'):
            verify_receipt(self.root,self.root,receipt)

    def test_parallel_completion_preserves_batch_size_and_cache(self):
        findings = [dict(finding_id='F'+str(i), status='NEED_OPENCODE_REVIEW', accesses=[]) for i in range(5)]
        facts = dict(variables=[], contexts=[], functions=[], calls=[])
        report = dict(findings=findings, coverage={}, limitations=[])
        cfg = dict(review=dict(enabled=True, workers=3, max_items=3, retries=0), analysis={})
        out = self.root/'.ecra'
        seen, simultaneous = [], []
        active = 0
        lock = threading.Lock()

        def execute(argv, **kwargs):
            nonlocal active
            packet = json.loads(Path(argv[argv.index('--file')+1]).read_text(encoding='utf-8'))
            fid = packet['finding']['finding_id']
            with lock:
                active += 1
                simultaneous.append(active)
                seen.append(fid)
            time.sleep(.08 if fid == 'F0' else .02)
            with lock:
                active -= 1
            return CompletedProcess(argv,0,self.event(dict(self.answer,finding_id=fid)),'')

        def checkpoint(results):
            queue=json.loads((out/'review/queue.json').read_text(encoding='utf-8'))
            self.assertEqual([r['finding_id'] for r in queue], [f['finding_id'] for f in findings])
            self.assertGreaterEqual(sum(r['state']=='DONE' for r in queue),sum(r['state']=='DONE' for r in results))

        with patch('ecra.review.resolve_command',return_value=['fake-protocol-test']), patch('ecra.review.execute',side_effect=execute):
            first=review_all(self.root,out,cfg,facts,report,'scan',lambda _:None,checkpoint)
            self.assertEqual(len(seen),5)
            self.assertGreater(max(simultaneous),1)
            self.assertLessEqual(max(simultaneous),3)
            self.assertTrue(all(r['state']=='DONE' for r in first))
            cfg['review']['max_items']=0
            second=review_all(self.root,out,cfg,facts,report,'scan',lambda _:None,checkpoint)
            self.assertEqual(len(seen),5)
            self.assertEqual(sum(r.get('cached',False) for r in second),5)
            self.assertTrue(all(r['state']=='DONE' for r in second))

    def test_batch_sizes_concurrency_and_single_run_completion(self):
        facts = dict(variables=[], contexts=[], functions=[], calls=[])
        for total, workers, limit, sizes in (
                (10, 1, 1, [1] * 10),
                (23, 4, 5, [5, 5, 5, 5, 3]),
                (23, 8, 5, [5, 5, 5, 5, 3]),
                (23, 4, 0, [23])):
            with self.subTest(total=total, workers=workers, max_items=limit):
                out = self.root/f'.ecra-{workers}-{limit}'
                report = dict(findings=[dict(finding_id=f'F{i}', accesses=[]) for i in range(total)],
                              coverage={}, limitations=[])
                cfg = dict(review=dict(enabled=True, workers=workers, max_items=limit, retries=0), analysis={})
                active = peak = 0
                started = []
                batch_sizes = []
                current_batch = 0
                lock = threading.Lock()

                def progress(message):
                    nonlocal current_batch
                    match = re.search(r'当前批次 (\d+)/(\d+)，本批 (\d+) 项', message)
                    if match:
                        with lock:
                            self.assertEqual(active, 0)
                            current_batch = int(match.group(1))
                            batch_sizes.append(int(match.group(3)))

                def execute(argv, **kwargs):
                    nonlocal active, peak
                    packet = json.loads(Path(argv[argv.index('--file')+1]).read_text(encoding='utf-8'))
                    fid = packet['finding']['finding_id']
                    with lock:
                        active += 1
                        peak = max(peak, active)
                        started.append((current_batch, fid))
                    time.sleep(.01)
                    with lock:
                        active -= 1
                    return CompletedProcess(argv, 0, self.event(dict(self.answer, finding_id=fid)), '')

                def checkpoint(results):
                    queue = json.loads((out/'review/queue.json').read_text(encoding='utf-8'))
                    self.assertEqual(len(queue), total)
                    for row in results:
                        self.assertEqual(row['state'], 'DONE')
                        self.assertTrue((out/'review'/(row['finding_id']+'.result.json')).is_file())

                with patch('ecra.review.resolve_command', return_value=['fake-protocol-test']), patch(
                        'ecra.review.execute', side_effect=execute):
                    rows = review_all(self.root, out, cfg, facts, report, 'scan', progress, checkpoint)
                self.assertEqual(batch_sizes, sizes)
                self.assertEqual([sum(batch == i for batch, _ in started) for i in range(1, len(sizes)+1)], sizes)
                self.assertEqual(len({fid for _, fid in started}), total)
                self.assertLessEqual(peak, min(workers, max(sizes)))
                self.assertTrue(all(row['state'] == 'DONE' for row in rows))

    def test_failed_item_does_not_stop_later_batch_and_resume_reuses_completed(self):
        out = self.root/'.ecra-failure'
        facts = dict(variables=[], contexts=[], functions=[], calls=[])
        report = dict(findings=[dict(finding_id=f'F{i}', accesses=[]) for i in range(7)],
                      coverage={}, limitations=[])
        cfg = dict(review=dict(enabled=True, workers=4, max_items=5, retries=1), analysis={})
        calls = []
        fail = True

        def execute(argv, **kwargs):
            packet = json.loads(Path(argv[argv.index('--file')+1]).read_text(encoding='utf-8'))
            fid = packet['finding']['finding_id']
            calls.append(fid)
            if fail and fid == 'F2':
                return CompletedProcess(argv, 1, '', 'simulated failure')
            return CompletedProcess(argv, 0, self.event(dict(self.answer, finding_id=fid)), '')

        with patch('ecra.review.resolve_command', return_value=['fake-protocol-test']), patch(
                'ecra.review.execute', side_effect=execute):
            first = review_all(self.root, out, cfg, facts, report, 'scan', lambda _: None)
            self.assertEqual([r['state'] for r in first],
                             ['DONE', 'DONE', 'FAILED', 'DONE', 'DONE', 'DONE', 'DONE'])
            self.assertEqual(calls.count('F2'), 2)
            self.assertIn('F6', calls)
            queue = json.loads((out/'review/queue.json').read_text(encoding='utf-8'))
            self.assertEqual(queue[2]['state'], 'FAILED')
            fail = False
            second = review_all(self.root, out, cfg, facts, report, 'scan', lambda _: None)
        self.assertEqual(calls.count('F2'), 3)
        self.assertEqual(len(calls), 9)
        self.assertEqual(sum(bool(r.get('cached')) for r in second), 6)
        self.assertTrue(all(r['state'] == 'DONE' for r in second))

    def test_final_conclusion_distinguishes_defect_from_completion(self):
        report=dict(analysis_status='MODELED_SCOPE_COMPLETE',findings=[dict(finding_id='F',symbol_id='s')])
        def conclusion(status, state='DONE'):
            return final_conclusion(report,[dict(finding_id='F',status=status,state=state)])
        self.assertEqual(conclusion('CONFIRMED')['verdict'],'HAS_ISSUES')
        self.assertEqual(conclusion('REVIEWED_SAFE')['verdict'],'NO_ISSUES_IN_SCOPE')
        for status in ('LIKELY','NEED_MORE_CONTEXT'):
            self.assertEqual(conclusion(status)['verdict'],'INCONCLUSIVE')
        self.assertEqual(conclusion('CONFIRMED','FAILED')['verdict'],'INCONCLUSIVE')
        report['findings'][0]['symbol_id']=None
        self.assertNotEqual(conclusion('CONFIRMED')['verdict'],'HAS_ISSUES')
        report['analysis_status']='INCOMPLETE'
        self.assertEqual(conclusion('REVIEWED_SAFE')['verdict'],'INCONCLUSIVE')

    def test_second_pass_revises_answer_and_preserves_original(self):
        from ecra.review_audit import audit_reviews
        out=self.root/'.ecra';folder=out/'review';folder.mkdir(parents=True)
        log=folder/'F.attempt0.jsonl'
        log.write_text(self.event(self.answer),encoding='utf-8')
        original=dict(finding_id='F',state='DONE',status='CONFIRMED',answer=self.answer,cache_key='original',
            source_evidence=collect_evidence(self.root,self.answer),
            execution=dict(stdout_file=log.name,stdout_sha256=hashlib.sha256(log.read_bytes()).hexdigest()))
        revised=dict(self.answer,status='NEED_MORE_CONTEXT',reason='Need actual consumer or invariant')
        revised.update(structured_fields('NEED_MORE_CONTEXT', 'EVIDENCE_GAP'))
        cfg=dict(review=dict(workers=2,retries=0))
        with patch('ecra.review_audit.resolve_command',return_value=['fake-protocol-test']), patch(
                'ecra.review_audit.execute',return_value=CompletedProcess([],0,self.event(revised),'')) as execute:
            rows=audit_reviews(self.root,out,cfg,[original],lambda _:None)
            self.assertEqual(rows[0]['status'],'NEED_MORE_CONTEXT')
            self.assertEqual(rows[0]['previous_reviews'][0]['answer'],self.answer)
            self.assertEqual(original['status'],'CONFIRMED')
            verify_receipt(self.root,folder,rows[0])
            audit_reviews(self.root,out,cfg,[original],lambda _:None)
            self.assertEqual(execute.call_count,1)

    def test_second_pass_uses_same_batch_concurrency_limit(self):
        from ecra.review_audit import audit_reviews
        out = self.root/'.ecra-audit-batches'
        folder = out/'review'
        folder.mkdir(parents=True)
        originals = [dict(finding_id=f'F{i}', state='FAILED', status='NEED_MORE_CONTEXT',
                          error='First pass failed') for i in range(6)]
        for original in originals:
            (folder/(original['finding_id']+'.input.json')).write_text(
                json.dumps(dict(finding=dict(finding_id=original['finding_id']),
                                investigation_requirements=[])), encoding='utf-8')
        cfg = dict(review=dict(command=['fake-protocol-test'], workers=8, max_items=5, retries=0))
        active = peak = 0
        finished = set()
        lock = threading.Lock()

        def execute(argv, **kwargs):
            nonlocal active, peak
            packet = json.loads(Path(argv[argv.index('--file')+1]).read_text(encoding='utf-8'))
            fid = packet['finding']['finding_id']
            with lock:
                if fid == 'F5':
                    self.assertEqual(len(finished), 5)
                active += 1
                peak = max(peak, active)
            time.sleep(.01)
            with lock:
                active -= 1
                finished.add(fid)
            return CompletedProcess(argv, 0, self.event(dict(self.answer, finding_id=fid)), '')

        with patch('ecra.review_audit.resolve_command', return_value=['fake-protocol-test']), patch(
                'ecra.review_audit.execute', side_effect=execute):
            rows = audit_reviews(self.root, out, cfg, originals, lambda _: None)
        self.assertEqual(len(finished), 6)
        self.assertLessEqual(peak, 5)
        self.assertTrue(all(r['state'] == 'DONE' for r in rows))

    def test_pipeline_exports_audited_verdict_and_reuses_both_passes(self):
        out=self.root/'.ecra'
        context_path=self.root/'review_context.md'
        context_path.write_text('<!-- 模板说明 -->\nIRQ_A 与 IRQ_B 因互斥使能不会同时运行。', encoding='utf-8')
        facts=dict(variables=[],contexts=[],functions=[],calls=[])
        report=dict(findings=[dict(finding_id='F',accesses=[])],coverage={},limitations=[])
        cfg=dict(review=dict(enabled=True,audit_verdicts=True,workers=2,retries=0),analysis={})
        final=dict(self.answer,status='FALSE_POSITIVE',reason='Protocol fixture correction')
        final.update(structured_fields('FALSE_POSITIVE', 'EVIDENCE_GAP'))
        with patch('ecra.review.resolve_command',return_value=['fake-protocol-test']), patch(
                'ecra.review_audit.resolve_command',return_value=['fake-protocol-test']), patch(
                'ecra.review.execute',return_value=CompletedProcess([],0,self.event(self.answer),'')) as first, patch(
                'ecra.review_audit.execute',return_value=CompletedProcess([],0,self.event(final),'')) as second:
            result=review_all(self.root,out,cfg,facts,report,'scan',lambda _:None,
                              review_context_path=context_path)
            queue=json.loads((out/'review/queue.json').read_text(encoding='utf-8'))
            self.assertEqual(queue[0]['answer'],final)
            self.assertEqual(result[0]['previous_reviews'][0]['answer'],self.answer)
            for call in (first, second):
                prompt=call.call_args.args[0][-1]
                self.assertIn('IRQ_A 与 IRQ_B',prompt)
                self.assertNotIn('模板说明',prompt)
            review_all(self.root,out,cfg,facts,report,'scan',lambda _:None,
                       review_context_path=context_path)
            self.assertEqual(first.call_count,1)
            self.assertEqual(second.call_count,1)
            context_path.write_text('IRQ_A 与 IRQ_B 可能嵌套。', encoding='utf-8')
            review_all(self.root,out,cfg,facts,report,'scan',lambda _:None,
                       review_context_path=context_path)
            self.assertEqual(first.call_count,2)
            self.assertEqual(second.call_count,2)
            self.assertIn('可能嵌套', first.call_args.args[0][-1])
            self.assertIn('可能嵌套', second.call_args.args[0][-1])

    def test_101_targets_all_batches_archived(self):
        report = dict(findings=[dict(finding_id=f'F{i}', accesses=[]) for i in range(101)],
                      coverage={}, limitations=[])
        facts = dict(variables=[], contexts=[], functions=[], calls=[])
        cfg = dict(review=dict(enabled=True, workers=4, max_items=5, retries=0), analysis={})
        out = self.root/'.ecra-101'
        seen = []
        def execute(argv, **kwargs):
            fid = json.loads(Path(argv[argv.index('--file')+1]).read_text(encoding='utf-8'))['finding']['finding_id']
            seen.append(fid)
            return CompletedProcess(argv, 0, self.event(dict(self.answer, finding_id=fid)), '')
        with patch('ecra.review.resolve_command', return_value=['fake']), patch('ecra.review.execute', side_effect=execute):
            rows = review_all(self.root, out, cfg, facts, report, 'scan', lambda _: None)
        summary = assert_review_integrity(report, rows, require_terminal=True)
        self.assertEqual((summary['targets'], summary['archived'], summary['missing'], summary['duplicate']),
                         (101, 101, 0, 0))
        self.assertEqual(len(seen), 101)
        self.assertEqual(len(json.loads((out/'review/queue.json').read_text(encoding='utf-8'))), 101)

    def test_failure_types_leave_receipts_and_later_items_run(self):
        report = dict(findings=[dict(finding_id=f'F{i}', accesses=[]) for i in range(10)],
                      coverage={}, limitations=[])
        facts = dict(variables=[], contexts=[], functions=[], calls=[])
        cfg = dict(review=dict(enabled=True, workers=1, max_items=5, retries=0), analysis={})
        out = self.root/'.ecra-failures'
        def execute(argv, **kwargs):
            fid = json.loads(Path(argv[argv.index('--file')+1]).read_text(encoding='utf-8'))['finding']['finding_id']
            i = int(fid[1:])
            if i == 1:
                raise TimeoutError('simulated timeout')
            if i == 2:
                return CompletedProcess(argv, 7, 'partial output', 'stderr diagnostic')
            if i == 3:
                return CompletedProcess(argv, 0, 'not json', '')
            answer = dict(self.answer, finding_id=fid)
            if i == 4: answer['finding_id'] = 'WRONG'
            if i == 5: answer['status'] = 'INVALID'
            if i == 6: answer['evidence'] = [dict(file='app.c', line=100, quote='bad', claim='bad')]
            return CompletedProcess(argv, 0, self.event(answer), '')
        with patch('ecra.review.resolve_command', return_value=['fake']), patch('ecra.review.execute', side_effect=execute):
            rows = review_all(self.root, out, cfg, facts, report, 'scan', lambda _: None)
        self.assertEqual([r['state'] for r in rows], ['DONE']+['FAILED']*6+['DONE']*3)
        self.assertEqual((review_integrity(report, rows)['missing'], review_integrity(report, rows)['duplicate']), (0, 0))
        for row in rows[1:7]:
            self.assertTrue(row['error'])
            self.assertTrue(row['attempts'])
            self.assertTrue((out/'review'/(row['finding_id']+'.result.json')).is_file())
            self.assertTrue((out/'review'/row['attempts'][-1]['prompt_file']).is_file())

    def test_duplicate_and_invalid_terminal_invariants(self):
        report = dict(findings=[dict(finding_id='F')])
        invalid = [dict(finding_id='F', state='DONE', status='REVIEWED_SAFE')]
        self.assertIn('DONE 缺少', ' '.join(review_integrity(report, invalid)['errors']))
        with self.assertRaisesRegex(ValueError, '重复'):
            assert_review_integrity(report, invalid+invalid)
        self.assertFalse(review_integrity(report, [dict(finding_id='F', state='FAILED')])['complete'])
        self.assertIn('不得携带当前有效 status', ' '.join(review_integrity(report, [dict(
            finding_id='F', state='FAILED', status='NEED_MORE_CONTEXT', error='timeout')])['errors']))

    def test_terminal_failure_is_archived_but_not_successfully_done(self):
        report = dict(findings=[dict(finding_id='F')])
        row = dict(finding_id='F', state='FAILED', error='timeout')
        summary = review_integrity(report, [row], require_terminal=True)
        self.assertTrue(summary['complete'])
        self.assertFalse(summary['all_done'])
        self.assertEqual((summary['done'], summary['failed']), (0, 1))

    def test_archive_comparison_detects_queue_result_disagreement(self):
        report = dict(findings=[dict(finding_id='F')])
        folder = self.root/'review'
        folder.mkdir()
        row = dict(finding_id='F', state='FAILED', error='timeout')
        (folder/'queue.json').write_text(json.dumps([row]), encoding='utf-8')
        (folder/'F.result.json').write_text(json.dumps(dict(row, error='different')), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'result 与 queue'):
            assert_review_archive(report, [row], folder)

    def test_duplicate_old_queue_is_logged_and_repaired(self):
        report = dict(findings=[dict(finding_id='F', accesses=[])], coverage={}, limitations=[])
        facts = dict(variables=[], contexts=[], functions=[], calls=[])
        cfg = dict(review=dict(enabled=True, retries=0), analysis={})
        out = self.root/'.ecra-duplicate'
        folder = out/'review'
        folder.mkdir(parents=True)
        (folder/'queue.json').write_text(json.dumps([dict(finding_id='F', state='PENDING')]*2), encoding='utf-8')
        with patch('ecra.review.resolve_command', return_value=['fake']), patch(
                'ecra.review.execute', return_value=CompletedProcess([], 0, self.event(self.answer), '')):
            rows = review_all(self.root, out, cfg, facts, report, 'scan', lambda _: None)
        self.assertEqual(len(rows), 1)
        self.assertEqual(review_integrity(report, rows)['duplicate'], 0)
        self.assertEqual(json.loads((folder/'queue_repair.json').read_text(encoding='utf-8'))['integrity']['duplicate'], 1)

    def test_invalid_old_done_row_is_rechecked(self):
        report = dict(findings=[dict(finding_id='F', accesses=[])], coverage={}, limitations=[])
        facts = dict(variables=[], contexts=[], functions=[], calls=[])
        cfg = dict(review=dict(enabled=True, retries=0), analysis={})
        out = self.root/'.ecra-bad-queue'
        folder = out/'review'
        folder.mkdir(parents=True)
        (folder/'queue.json').write_text(json.dumps([dict(finding_id='F', state='DONE', status='REVIEWED_SAFE')]),
                                         encoding='utf-8')
        with patch('ecra.review.resolve_command', return_value=['fake']), patch(
                'ecra.review.execute', return_value=CompletedProcess([], 0, self.event(self.answer), '')):
            rows = review_all(self.root, out, cfg, facts, report, 'scan', lambda _: None)
        self.assertEqual(rows[0]['state'], 'DONE')
        self.assertTrue((folder/'queue_repair.json').exists())

    def test_resume_after_interrupt_uses_prior_receipt(self):
        report = dict(findings=[dict(finding_id=f'F{i}', accesses=[]) for i in range(3)],
                      coverage={}, limitations=[])
        facts = dict(variables=[], contexts=[], functions=[], calls=[])
        cfg = dict(review=dict(enabled=True, workers=1, max_items=1, retries=0), analysis={})
        out = self.root/'.ecra-interrupt'
        calls = []
        interrupt = True
        def execute(argv, **kwargs):
            fid = json.loads(Path(argv[argv.index('--file')+1]).read_text(encoding='utf-8'))['finding']['finding_id']
            calls.append(fid)
            if interrupt and fid == 'F1': raise KeyboardInterrupt()
            return CompletedProcess(argv, 0, self.event(dict(self.answer, finding_id=fid)), '')
        with patch('ecra.review.resolve_command', return_value=['fake']), patch('ecra.review.execute', side_effect=execute):
            with self.assertRaises(KeyboardInterrupt):
                review_all(self.root, out, cfg, facts, report, 'scan', lambda _: None)
            queue = json.loads((out/'review/queue.json').read_text(encoding='utf-8'))
            self.assertEqual([r['state'] for r in queue], ['DONE', 'PENDING', 'PENDING'])
            interrupt = False
            rows = review_all(self.root, out, cfg, facts, report, 'scan', lambda _: None)
        self.assertEqual(calls, ['F0', 'F1', 'F1', 'F2'])
        self.assertEqual((review_integrity(report, rows)['missing'], review_integrity(report, rows)['duplicate']), (0, 0))

    def test_audit_failure_preserves_first_pass_for_resume(self):
        report = dict(findings=[dict(finding_id='F', accesses=[])], coverage={}, limitations=[])
        facts = dict(variables=[], contexts=[], functions=[], calls=[])
        cfg = dict(review=dict(enabled=True, audit_verdicts=True, workers=1, max_items=1, retries=0), analysis={})
        out = self.root/'.ecra-audit-failure'
        with patch('ecra.review.resolve_command', return_value=['fake']), patch(
                'ecra.review_audit.resolve_command', return_value=['fake']), patch(
                'ecra.review.execute', return_value=CompletedProcess([], 0, self.event(self.answer), '')) as first, patch(
                'ecra.review_audit.execute', side_effect=[CompletedProcess([], 1, '', 'audit failed'),
                                                           CompletedProcess([], 0, self.event(self.answer), '')]) as second:
            failed = review_all(self.root, out, cfg, facts, report, 'scan', lambda _: None)
            self.assertEqual(failed[0]['state'], 'FAILED')
            self.assertEqual(failed[0]['failure_stage'], 'audit')
            self.assertEqual(failed[0]['previous_reviews'][0]['state'], 'DONE')
            resumed = review_all(self.root, out, cfg, facts, report, 'scan', lambda _: None)
        self.assertEqual(resumed[0]['state'], 'DONE')
        self.assertEqual(first.call_count, 1)
        self.assertEqual(second.call_count, 2)

    def test_each_item_is_audited_and_archived_before_next_starts(self):
        report = dict(findings=[dict(finding_id=f'F{i}', accesses=[]) for i in range(3)],
                      coverage={}, limitations=[])
        facts = dict(variables=[], contexts=[], functions=[], calls=[])
        cfg = dict(review=dict(enabled=True, audit_verdicts=True, workers=1,
                               max_items=2, timeout_seconds=300, retries=0), analysis={})
        out = self.root/'.ecra-item-order'
        folder = out/'review'
        events = []

        def first(argv, **kwargs):
            fid = json.loads(Path(argv[argv.index('--file')+1]).read_text(encoding='utf-8'))['finding']['finding_id']
            self.assertEqual(kwargs['timeout'], 300)
            if fid != 'F0':
                prior = json.loads((folder/'queue.json').read_text(encoding='utf-8'))[int(fid[1:])-1]
                receipt = json.loads((folder/(prior['finding_id']+'.result.json')).read_text(encoding='utf-8'))
                self.assertEqual(prior, receipt)
                self.assertEqual(prior['state'], 'FAILED' if fid == 'F2' else 'DONE')
                self.assertIn('audit_key', prior)
            events.append('first:'+fid)
            return CompletedProcess(argv, 0, self.event(dict(self.answer, finding_id=fid)), '')

        def audit(argv, **kwargs):
            fid = Path(argv[argv.index('--file')+1]).name.split('.')[0]
            self.assertEqual(kwargs['timeout'], 300)
            events.append('audit:'+fid)
            if fid == 'F1':
                return CompletedProcess(argv, 1, '', 'simulated audit failure')
            return CompletedProcess(argv, 0, self.event(dict(self.answer, finding_id=fid)), '')

        with patch('ecra.review.resolve_command', return_value=['fake']), patch(
                'ecra.review_audit.resolve_command', return_value=['fake']), patch(
                'ecra.review.execute', side_effect=first), patch(
                'ecra.review_audit.execute', side_effect=audit):
            rows = review_all(self.root, out, cfg, facts, report, 'scan', lambda _: None)
        self.assertEqual(events, ['first:F0', 'audit:F0', 'first:F1', 'audit:F1',
                                  'first:F2', 'audit:F2'])
        self.assertEqual([r['state'] for r in rows], ['DONE', 'FAILED', 'DONE'])
        summary = assert_review_archive(report, rows, folder)
        self.assertEqual((summary['targets'], summary['archived'], summary['missing']), (3, 3, 0))

    def test_project_configuration_failure_stops_relaunches_and_can_resume(self):
        report = dict(findings=[dict(finding_id=f'F{i}', accesses=[]) for i in range(3)],
                      coverage={}, limitations=[])
        facts = dict(variables=[], contexts=[], functions=[], calls=[])
        cfg = dict(review=dict(enabled=True, audit_verdicts=True, workers=1,
                               retries=2), analysis={})
        out = self.root/'.ecra-bad-opencode-config'
        calls = []
        messages = []
        broken = True

        def first(argv, **kwargs):
            fid = json.loads(Path(argv[argv.index('--file')+1]).read_text(encoding='utf-8'))['finding']['finding_id']
            calls.append(fid)
            if broken:
                return CompletedProcess(argv, 1, '',
                                        'Error: Configuration is invalid at .opencode/agent/bad.md')
            return CompletedProcess(argv, 0, self.event(dict(self.answer, finding_id=fid)), '')

        def audit(argv, **kwargs):
            fid = Path(argv[argv.index('--file')+1]).name.split('.')[0]
            return CompletedProcess(argv, 0, self.event(dict(self.answer, finding_id=fid)), '')

        with patch('ecra.review.resolve_command', return_value=['fake']), patch(
                'ecra.review_audit.resolve_command', return_value=['fake']), patch(
                'ecra.review.execute', side_effect=first), patch(
                'ecra.review_audit.execute', side_effect=audit) as audit_call:
            failed = review_all(self.root, out, cfg, facts, report, 'scan', messages.append)
            self.assertEqual(calls, ['F0'])
            audit_call.assert_not_called()
            self.assertEqual([r['state'] for r in failed], ['FAILED'] * 3)
            self.assertTrue(all(r['error_type'] == 'OpenCodeConfigurationError' for r in failed))
            self.assertTrue(all(r['failure_stage'] == 'configuration' for r in failed))
            self.assertEqual(len(failed[0]['attempts']), 1)
            self.assertEqual(sum('项目配置无效，已停止后续调用' in m for m in messages), 1)
            assert_review_archive(report, failed, out/'review')

            broken = False
            recovered = review_all(self.root, out, cfg, facts, report, 'scan', lambda _: None)
            self.assertEqual([r['state'] for r in recovered], ['DONE'] * 3)
            self.assertEqual(calls, ['F0', 'F0', 'F1', 'F2'])
            self.assertEqual(audit_call.call_count, 3)
            assert_review_archive(report, recovered, out/'review')

    def test_audit_configuration_failure_preserves_first_pass_and_stops_queue(self):
        report = dict(findings=[dict(finding_id=f'F{i}', accesses=[]) for i in range(2)],
                      coverage={}, limitations=[])
        facts = dict(variables=[], contexts=[], functions=[], calls=[])
        cfg = dict(review=dict(enabled=True, audit_verdicts=True, workers=1,
                               retries=2), analysis={})
        out = self.root/'.ecra-audit-config'
        first_calls = []
        audit_calls = []

        def first(argv, **kwargs):
            fid = json.loads(Path(argv[argv.index('--file')+1]).read_text(encoding='utf-8'))['finding']['finding_id']
            first_calls.append(fid)
            return CompletedProcess(argv, 0, self.event(dict(self.answer, finding_id=fid)), '')

        def audit(argv, **kwargs):
            fid = Path(argv[argv.index('--file')+1]).name.split('.')[0]
            audit_calls.append(fid)
            return CompletedProcess(argv, 1, '',
                                    'Error: Configuration is invalid at .opencode/agent/bad.md')

        with patch('ecra.review.resolve_command', return_value=['fake']), patch(
                'ecra.review_audit.resolve_command', return_value=['fake']), patch(
                'ecra.review.execute', side_effect=first), patch(
                'ecra.review_audit.execute', side_effect=audit):
            rows = review_all(self.root, out, cfg, facts, report, 'scan', lambda _: None)
        self.assertEqual(first_calls, ['F0'])
        self.assertEqual(audit_calls, ['F0'])
        self.assertEqual([r['state'] for r in rows], ['FAILED', 'FAILED'])
        self.assertEqual(rows[0]['previous_reviews'][0]['state'], 'DONE')
        self.assertTrue(all(r['error_type'] == 'OpenCodeConfigurationError' for r in rows))
        assert_review_archive(report, rows, out/'review')

    def test_damaged_cache_is_reexecuted_and_noted(self):
        report = dict(findings=[dict(finding_id='F', accesses=[])], coverage={}, limitations=[])
        facts = dict(variables=[], contexts=[], functions=[], calls=[])
        cfg = dict(review=dict(enabled=True, workers=1, retries=0), analysis={})
        out = self.root/'.ecra-damaged'
        folder = out/'review'
        folder.mkdir(parents=True)
        (folder/'F.result.json').write_text('{broken', encoding='utf-8')
        with patch('ecra.review.resolve_command', return_value=['fake']), patch(
                'ecra.review.execute', return_value=CompletedProcess([], 0, self.event(self.answer), '')):
            rows = review_all(self.root, out, cfg, facts, report, 'scan', lambda _: None)
        self.assertEqual(rows[0]['state'], 'DONE')
        self.assertIn('缓存损坏', rows[0]['cache_error'])


if __name__ == '__main__':
    unittest.main()
