"""Executable risk-verdict gates use protocol fixtures, not model truth."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch
import yaml

from ecra.config import CMAKE_TEMPLATE, TEMPLATE
from ecra.review import review_all
from ecra.review_risk import risk_focus, validate_risk_result
from tests.review_fixtures import structured_fields


class RiskGateTests(unittest.TestCase):
    def setUp(self):
        self.a = dict(access_id='A', symbol_id='s', function_id='main_write',
                      access_kind='RMW', file='src.c', line=2,
                      canonical_path='shared', contexts=['main'], reachability='REACHABLE')
        self.b = dict(access_id='B', symbol_id='s', function_id='irq_write',
                      access_kind='WRITE', file='src.c', line=3,
                      canonical_path='shared', contexts=['irq'], reachability='REACHABLE')
        self.pair = dict(conflict_id='C', participant_a=dict(access_id='A', file='src.c', line=2,
                         canonical_path='shared', context_id='main', access_kind='RMW'),
                         participant_b=dict(access_id='B', file='src.c', line=3,
                         canonical_path='shared', context_id='irq', access_kind='WRITE'),
                         relation=dict(relation='CAN_PREEMPT', higher='irq', lower='main'),
                         mhp='YES', may_concurrent=True, has_write_conflict=True)
        self.packet = dict(finding=dict(symbol_id='s', accesses=[self.a, self.b],
                           conflict_pairs=[self.pair], protection_status='NOT_FOUND'),
                           variable=dict(symbol_id='s', canonical_path='shared', size_bytes=4,
                                         alignment_bytes=4, is_pointer=False),
                           project_native_word_bits=32)
        self.answer = dict(status='CONFIRMED', evidence=[dict(file='src.c', line=2),
            dict(file='src.c', line=3)], **structured_fields())

    def test_real_rmw_main_isr_pair_can_remain_confirmed(self):
        validate_risk_result(self.answer, self.packet)
        focus = risk_focus(self.packet)
        self.assertEqual(focus['candidate_interleaving_pair_ids'], ['C'])
        self.assertEqual(focus['object_identity']['canonical_path'], 'shared')

    def test_new_project_templates_enable_adversarial_review(self):
        self.assertTrue(yaml.safe_load(TEMPLATE)['review']['audit_verdicts'])
        self.assertTrue(yaml.safe_load(CMAKE_TEMPLATE)['review']['audit_verdicts'])

    def test_same_priority_irq_and_initialization_pair_cannot_confirm(self):
        for change in (dict(relation=dict(relation='SERIAL'), mhp='NO', may_concurrent=False),
                       dict(relation=dict(relation='CAN_PREEMPT'), mhp='NO', may_concurrent=False)):
            with self.subTest(change=change):
                packet = copy.deepcopy(self.packet)
                packet['finding']['conflict_pairs'][0].update(change)
                with self.assertRaisesRegex(ValueError, 'risk_override'):
                    validate_risk_result(self.answer, packet)

    def test_unknown_irq_priority_is_not_confirmed(self):
        packet = copy.deepcopy(self.packet)
        packet['finding']['conflict_pairs'][0].update(
            relation=dict(relation='UNKNOWN_PREEMPTION'), mhp='MAYBE')
        with self.assertRaisesRegex(ValueError, 'risk_override'):
            validate_risk_result(self.answer, packet)

    def test_distinct_members_without_invariant_cannot_confirm(self):
        packet = copy.deepcopy(self.packet)
        packet['finding']['conflict_pairs'][0]['participant_b']['canonical_path'] = 'config.period'
        packet['finding']['conflict_pairs'][0]['participant_a']['canonical_path'] = 'config.limit'
        with self.assertRaisesRegex(ValueError, 'risk_override'):
            validate_risk_result(self.answer, packet)

    def test_pointer_slot_without_write_is_not_pointee_risk(self):
        packet = copy.deepcopy(self.packet)
        packet['variable'].update(is_pointer=True, canonical_path='g_buf')
        packet['finding']['accesses'] = [dict(self.a, access_kind='READ', canonical_path='g_buf')]
        packet['finding']['conflict_pairs'] = []
        with self.assertRaisesRegex(ValueError, 'risk_override'):
            validate_risk_result(self.answer, packet)
        self.assertTrue(risk_focus(packet)['object_identity']['pointer_slot_separate_from_pointee'])

    def test_plain_aligned_stores_need_source_backed_protocol_invariant(self):
        packet = copy.deepcopy(self.packet)
        for access in packet['finding']['accesses']:
            access['access_kind'] = 'WRITE'
        with self.assertRaisesRegex(ValueError, '多个原子/对齐 store'):
            validate_risk_result(self.answer, packet)
        answer = copy.deepcopy(self.answer)
        answer['risk_override'] = dict(reason='source-backed state protocol', evidence_refs=[1, 2],
            schedule_evidence_ref=1, protection_evidence_ref=1, outcome_evidence_ref=2,
            invariant_evidence_refs=[1], accesses=[
                dict(kind='WRITE', file='src.c', line=2, evidence_ref=1,
                     context_id='main', canonical_path='shared'),
                dict(kind='WRITE', file='src.c', line=3, evidence_ref=2,
                     context_id='irq', canonical_path='shared')])
        validate_risk_result(answer, packet)

    def test_likely_requires_a_real_write_or_source_override(self):
        packet = copy.deepcopy(self.packet)
        packet['finding']['accesses'] = [dict(self.a, access_kind='ADDRESS_TAKEN')]
        answer = dict(self.answer, status='LIKELY')
        with self.assertRaisesRegex(ValueError, 'LIKELY 缺少'):
            validate_risk_result(answer, packet)

    def test_likely_requires_two_cited_accesses_and_can_keep_unknown_priority(self):
        packet = copy.deepcopy(self.packet)
        packet['finding']['conflict_pairs'][0].update(
            relation=dict(relation='UNKNOWN_PREEMPTION'), mhp='MAYBE')
        answer = dict(self.answer, status='LIKELY')
        validate_risk_result(answer, packet)
        answer['evidence'] = [dict(file='src.c', line=2)]
        with self.assertRaisesRegex(ValueError, '两个候选访问点'):
            validate_risk_result(answer, packet)

    def test_override_cannot_use_pointee_for_pointer_slot(self):
        packet = copy.deepcopy(self.packet)
        packet['variable'].update(is_pointer=True, canonical_path='g_buf')
        packet['finding']['conflict_pairs'] = []
        answer = copy.deepcopy(self.answer)
        answer['risk_override'] = dict(reason='pointee changed', evidence_refs=[1, 2],
            schedule_evidence_ref=1, protection_evidence_ref=1, outcome_evidence_ref=2,
            accesses=[dict(kind='WRITE', file='src.c', line=2, evidence_ref=1,
                           context_id='main', canonical_path='*g_buf'),
                      dict(kind='READ', file='src.c', line=3, evidence_ref=2,
                           context_id='irq', canonical_path='*g_buf')])
        with self.assertRaisesRegex(ValueError, '其他存储对象'):
            validate_risk_result(answer, packet)

    def test_compact_context_product_uses_cited_accesses_not_representatives(self):
        packet = copy.deepcopy(self.packet)
        packet['finding']['accesses'] += [
            dict(self.a, access_id='A2', line=5, access_kind='READ'),
            dict(self.b, access_id='B2', line=6, access_kind='WRITE')]
        pair = packet['finding']['conflict_pairs'][0]
        pair.update(representation='CONTEXT_ACCESS_PRODUCT',
                    participant_a_write_access_ids=['A'], participant_a_read_access_ids=['A2'],
                    participant_b_write_access_ids=['B2'], participant_b_read_access_ids=[])
        answer = copy.deepcopy(self.answer)
        answer['evidence'] = [dict(file='src.c', line=5), dict(file='src.c', line=6)]
        validate_risk_result(answer, packet)
        answer['evidence'] = [dict(file='src.c', line=2), dict(file='src.c', line=5)]
        with self.assertRaisesRegex(ValueError, 'risk_override'):
            validate_risk_result(answer, packet)

    def test_review_retries_unsupported_risk_then_archives_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'src.c').write_text('int shared;\nvoid main_write(void){shared++;}\n'
                                      'void irq_write(void){shared=1;}\n', encoding='utf-8')
            packet_finding = dict(self.packet['finding'], finding_id='F',
                                  conflict_pairs=copy.deepcopy(self.packet['finding']['conflict_pairs']))
            packet_finding['conflict_pairs'][0].update(
                relation=dict(relation='SERIAL'), mhp='NO', may_concurrent=False)
            first = dict(self.answer, finding_id='F',
                         evidence=[dict(file='src.c', line=2, quote='shared++;', claim='main write'),
                                   dict(file='src.c', line=3, quote='shared=1;', claim='irq write')],
                         **{key: 'fixture' for key in ('reason', 'interleaving', 'protection',
                                                      'impact', 'fix', 'verification')})
            second = copy.deepcopy(first)
            second.update(status='REVIEWED_SAFE', **structured_fields('REVIEWED_SAFE'))
            responses = [first, second]
            def execute(argv, **kwargs):
                answer = copy.deepcopy(responses.pop(0))
                packet = json.loads(Path(argv[argv.index('--file') + 1]).read_text(encoding='utf-8'))
                answer['investigation'] = [dict(id=r['id'], assessment='fixture checked',
                                                evidence_refs=[1])
                                           for r in packet['investigation_requirements']]
                event = json.dumps(dict(type='text', part=dict(text=json.dumps(answer))))
                return CompletedProcess(argv, 0, event, '')
            facts = dict(variables=[self.packet['variable']], contexts=[], functions=[], calls=[])
            report = dict(findings=[packet_finding], coverage={}, limitations=[])
            cfg = dict(review=dict(enabled=True, retries=1, workers=1, audit_verdicts=False), analysis={})
            with patch('ecra.review.resolve_command', return_value=['fake-risk-review']), \
                 patch('ecra.review.execute', side_effect=execute):
                result = review_all(root, root/'.ecra', cfg, facts, report, 'scan', lambda _: None)[0]
            self.assertEqual(result['state'], 'DONE', result.get('error'))
            self.assertEqual(result['status'], 'REVIEWED_SAFE')
            self.assertEqual(len(result['attempts']), 2)
            self.assertIn('risk_override', result['attempts'][0]['error_message'])
            self.assertEqual(responses, [])
            packet = json.loads((root/'.ecra/review/F.input.json').read_text(encoding='utf-8'))
            self.assertEqual(next(iter(packet)), 'review_focus')
            self.assertEqual(packet['review_focus']['serial_or_excluded_pair_ids'], ['C'])
            self.assertFalse({'status', 'risk_level', 'confidence', 'static_classification'}
                             & set(packet['finding']))
            self.assertFalse({'static_classification', 'audit_status'} & set(packet['variable']))

    def test_review_keeps_source_backed_rmw_interleaving(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'src.c').write_text('int shared;\nvoid main_write(void){shared++;}\n'
                                      'void irq_write(void){shared=1;}\n', encoding='utf-8')
            finding = dict(self.packet['finding'], finding_id='F')
            answer = dict(self.answer, finding_id='F',
                          evidence=[dict(file='src.c', line=2, quote='shared++;', claim='read and write'),
                                    dict(file='src.c', line=3, quote='shared=1;', claim='IRQ write')],
                          **{key: 'fixture' for key in ('reason', 'interleaving', 'protection',
                                                       'impact', 'fix', 'verification')})
            def execute(argv, **kwargs):
                packet = json.loads(Path(argv[argv.index('--file') + 1]).read_text(encoding='utf-8'))
                value = dict(answer, investigation=[dict(id=r['id'], assessment='fixture checked',
                                                        evidence_refs=[1])
                                                    for r in packet['investigation_requirements']])
                event = json.dumps(dict(type='text', part=dict(text=json.dumps(value))))
                return CompletedProcess(argv, 0, event, '')
            facts = dict(variables=[self.packet['variable']], contexts=[], functions=[], calls=[])
            report = dict(findings=[finding], coverage={}, limitations=[])
            cfg = dict(review=dict(enabled=True, retries=0, workers=1, audit_verdicts=False), analysis={})
            with patch('ecra.review.resolve_command', return_value=['fake-risk-review']), \
                 patch('ecra.review.execute', side_effect=execute):
                result = review_all(root, root/'.ecra', cfg, facts, report, 'scan', lambda _: None)[0]
            self.assertEqual((result['state'], result['status']), ('DONE', 'CONFIRMED'),
                             result.get('error'))


if __name__ == '__main__':
    unittest.main()
