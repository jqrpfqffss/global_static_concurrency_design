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
            self.assertEqual(sum(r['state']=='DONE' for r in queue),sum(r['state']=='DONE' for r in results))

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
        facts=dict(variables=[],contexts=[],functions=[],calls=[])
        report=dict(findings=[dict(finding_id='F',accesses=[])],coverage={},limitations=[])
        cfg=dict(review=dict(enabled=True,audit_verdicts=True,workers=2,retries=0),analysis={})
        final=dict(self.answer,status='FALSE_POSITIVE',reason='Protocol fixture correction')
        final.update(structured_fields('FALSE_POSITIVE', 'EVIDENCE_GAP'))
        with patch('ecra.review.resolve_command',return_value=['fake-protocol-test']), patch(
                'ecra.review_audit.resolve_command',return_value=['fake-protocol-test']), patch(
                'ecra.review.execute',return_value=CompletedProcess([],0,self.event(self.answer),'')) as first, patch(
                'ecra.review_audit.execute',return_value=CompletedProcess([],0,self.event(final),'')) as second:
            result=review_all(self.root,out,cfg,facts,report,'scan',lambda _:None)
            queue=json.loads((out/'review/queue.json').read_text(encoding='utf-8'))
            self.assertEqual(queue[0]['answer'],final)
            self.assertEqual(result[0]['previous_reviews'][0]['answer'],self.answer)
            review_all(self.root,out,cfg,facts,report,'scan',lambda _:None)
            self.assertEqual(first.call_count,1)
            self.assertEqual(second.call_count,1)


if __name__ == '__main__':
    unittest.main()
