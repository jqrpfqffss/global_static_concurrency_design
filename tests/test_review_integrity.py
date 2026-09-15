"""Protocol tests use an explicit fake process; they are not real model evidence."""
import hashlib
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from ecra.html_report import final_conclusion
from ecra.review import collect_evidence, parse_answer, review_all, verify_receipt


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root/'app.c').write_text('int shared;\nvoid IRQ(void){shared++;}\n', encoding='utf-8')
        self.answer = dict(finding_id='F', status='CONFIRMED',
            evidence=[dict(file='app.c', line=2, quote='shared++;', claim='IRQ writes shared')],
            **{k:'protocol fixture only' for k in ('reason','interleaving','protection','impact','fix','verification')})

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

    def test_parallel_completion_preserves_queue_limit_and_cache(self):
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
            self.assertEqual(len(seen),3)
            self.assertGreater(max(simultaneous),1)
            self.assertEqual(sum(r['state']=='PENDING' for r in first),2)
            cfg['review']['max_items']=0
            second=review_all(self.root,out,cfg,facts,report,'scan',lambda _:None,checkpoint)
            self.assertEqual(len(seen),5)
            self.assertEqual(sum(r.get('cached',False) for r in second),3)
            self.assertTrue(all(r['state']=='DONE' for r in second))

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

    def test_pipeline_exports_audited_verdict_and_reuses_both_passes(self):
        out=self.root/'.ecra'
        facts=dict(variables=[],contexts=[],functions=[],calls=[])
        report=dict(findings=[dict(finding_id='F',accesses=[])],coverage={},limitations=[])
        cfg=dict(review=dict(enabled=True,audit_verdicts=True,workers=2,retries=0),analysis={})
        final=dict(self.answer,status='FALSE_POSITIVE',reason='Protocol fixture correction')
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
