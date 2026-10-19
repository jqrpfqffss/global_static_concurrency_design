"""Synthetic protocol tests; no claim to validate model reasoning."""
import copy
import json
import tempfile
import sys
import unittest
from pathlib import Path

from ecra.review import parse_answer, ReviewExecutionError
from ecra.review_contract import STATUSES, validate_minimal_answer
from ecra.review_presentation import explanation, review_markdown
from ecra.review_summary import STATUS_LABELS


def answer_for(status='CONFIRMED', fid='F', variable='shared'):
    return dict(finding_id=fid, status=status,
        summary=STATUS_LABELS[status] + '：' + variable + ' 的测试访问关系已核对，具体依据和适用条件见完整分析。',
        reason='已检查当前源码。',
        interleaving='main 读取；IRQ 更新；main 写回旧副本。',
        protection='未完整保护。', impact='计数更新可能丢失。',
        evidence=[dict(file='app.c', line=2, claim='IRQ 更新 shared。')],
        fix='保护整个 RMW 窗口。', verification='在该窗口内触发 IRQ。',
        missing_context=['尚需核实 NVIC 实际抢占优先级。'] if status in {'LIKELY', 'NEED_MORE_CONTEXT'} else [])


class ContractTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / 'app.c').write_text('int shared;\nvoid IRQ(void){shared++;}\n', encoding='utf-8')

    def test_all_five_semantic_answers_are_valid_without_structured_essays(self):
        for status in STATUSES:
            with self.subTest(status=status):
                value = answer_for(status)
                self.assertEqual(parse_answer(json.dumps(value), 'F', self.root), value)

    def test_plain_prose_fences_and_last_matching_object(self):
        answer = answer_for()
        raw = json.dumps(answer)
        for text in [raw, '\ufeff' + raw, 'Completed.\n' + raw + '\nEnd.',
                     '```json\n' + raw + '\n```', 'Analysis.\n```JSON\n' + raw + '\n```\nDone.',
                     json.dumps(answer_for(fid='OTHER')) + '\n' + raw + '\n' + json.dumps({'metadata': 'end'}),
                     raw + '\n' + json.dumps(answer_for(fid='OTHER'))]:
            with self.subTest(text=text[:30]):
                self.assertEqual(parse_answer(text, 'F', self.root), answer)
        answer['reason'] = 'Literal braces { } and escaped "quotes" are data.'
        self.assertEqual(parse_answer('Final: ' + json.dumps(answer), 'F', self.root), answer)

    def test_jsonl_and_fragmented_text(self):
        answer = answer_for()
        text = json.dumps(answer)
        split = text.index(',') + 1
        raw = '\n'.join(json.dumps(dict(type='text', part=dict(text=part)))
                        for part in ['Finished analysis.', text[:split], text[split:]])
        self.assertEqual(parse_answer(raw, 'F', self.root), answer)
        whole = json.dumps(dict(type='text', part=dict(text='Final:\n' + text)))
        self.assertEqual(parse_answer(whole, 'F', self.root), answer)
        with self.assertRaises(ReviewExecutionError):
            parse_answer(whole + '\n' + json.dumps(dict(type='error', error='provider down')), 'F', self.root)

    def test_execution_events_without_final_text_are_not_analysis(self):
        # Tool transcripts may contain source, so they must never become the
        # original analysis passed into a formatting-only repair.
        for events in [
            [dict(type='step_start'), dict(type='step_finish')],
            [dict(type='tool_use', part=dict(tool='read', state=dict(
                status='completed', output='SOURCE_CONTENT_SHOULD_STAY_LOCAL')))],
            [dict(type='text', part=dict(text='  ')), dict(type='step_finish')]
        ]:
            with self.subTest(events=events), self.assertRaises(ReviewExecutionError):
                parse_answer('\n'.join(json.dumps(e) for e in events), 'F', self.root)

    def test_required_identity_status_reason_and_evidence(self):
        for change in [dict(finding_id='other'), dict(status='SAFE'), dict(status=[]), dict(reason='  '),
                       dict(reason=None), dict(evidence=None), dict(evidence=[])]:
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    validate_minimal_answer(dict(answer_for(), **change), 'F', self.root)

    def test_missing_context_is_required_only_for_uncertain_verdicts(self):
        for status in ('LIKELY', 'NEED_MORE_CONTEXT'):
            for value in (None, [], [''], 'priority'):
                with self.subTest(status=status, missing=value), self.assertRaisesRegex(ValueError, 'missing_context'):
                    validate_minimal_answer(dict(answer_for(status), missing_context=value), 'F', self.root)
            value = dict(answer_for(status), evidence=[])
            self.assertEqual(parse_answer(json.dumps(value), 'F', self.root), value)

    def test_evidence_must_be_inside_project_and_line_in_bounds(self):
        for evidence in [dict(file='../outside.c', line=1), dict(file='missing.c', line=1),
                         dict(file='app.c', line=0), dict(file='app.c', line=999),
                         dict(file='app.c', line=True), dict(file='app.c', line='2')]:
            with self.subTest(evidence=evidence), self.assertRaises(ValueError):
                validate_minimal_answer(dict(answer_for(), evidence=[evidence]), 'F', self.root)
        value = answer_for()
        value['evidence'][0]['file'] = str(self.root / 'app.c')
        self.assertEqual(parse_answer(json.dumps(value), 'F', self.root), value)

    def test_long_natural_language_and_optional_display_fields_cannot_fail_review(self):
        value = answer_for()
        for key in ('reason', 'interleaving', 'protection', 'impact', 'fix', 'verification'):
            value[key] = '很长的源码分析；' * 2000
        value['evidence'][0]['claim'] = '依据' * 5000
        self.assertEqual(parse_answer(json.dumps(value), 'F', self.root), value)
        minimal = {k: v for k, v in value.items() if k in {'finding_id', 'status', 'reason', 'evidence'}}
        self.assertEqual(parse_answer(json.dumps(minimal), 'F', self.root), minimal)
        self.assertIn('未提供', explanation(minimal, 'confirmed'))

    def test_simple_display_keeps_all_fields_and_escapes_html(self):
        value = answer_for('NEED_MORE_CONTEXT')
        value['reason'] = '<script>MODEL_REASON</script>'
        html = explanation(value, 'unresolved')
        self.assertIn('MODEL_REASON', html)
        self.assertNotIn('<script>', html)
        self.assertIn(value['missing_context'][0], html)
        md = '\n'.join(review_markdown(value))
        for key in ('reason', 'interleaving', 'protection', 'impact', 'fix', 'verification'):
            self.assertIn(value[key], md)
        self.assertIn('app.c:2', md)
        value.update(explanation={}, schema_version=2, missing_context=None)
        self.assertIn('MODEL_REASON', explanation(value, 'unresolved'))
        self.assertIn('MODEL_REASON', '\n'.join(review_markdown(value)))

    def test_large_unicode_payload_round_trips_through_process_stdin(self):
        from ecra.common import execute
        text = '已有分析与证据，不得截断。' * 5000
        proc = execute([sys.executable, '-c',
                        'import sys;sys.stdout.buffer.write(sys.stdin.buffer.read())'], input=text, timeout=10)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, text)


if __name__ == '__main__':
    unittest.main()
