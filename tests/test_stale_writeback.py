"""Real AST fixtures and synthetic reviewer answers for stale value writeback."""
import json
import os
from pathlib import Path
import shutil
import subprocess
from subprocess import CompletedProcess
import unittest
from unittest.mock import patch

import yaml

from ecra.review import build_variable_review_packet, review_all, verify_receipt, REVIEW_PROMPT
from ecra.review_contract import validate_stale_writeback_safety, StaleWritebackSafetyError
from ecra.cli import safe_review_samples
from tests import test_ecra as fixtures


FIXTURES = Path(__file__).parent / 'fixtures' / 'stale_writeback'


class StaleWritebackTests(unittest.TestCase):
    setUp = fixtures.ProjectTest.setUp
    project = fixtures.ProjectTest.project
    extract = fixtures.ProjectTest.extract

    def scan(self, case='unsafe_direct_writeback', name='g_value', source=None, extra_sources=None):
        semantics = yaml.safe_load((FIXTURES / 'semantics.yaml').read_text(encoding='utf-8'))
        cfg = self.project({'app.c': source or (FIXTURES / (case + '.c')).read_text(),
                            'fixture.h': (FIXTURES / 'fixture.h').read_text(), **(extra_sources or {})},
                           contexts=semantics['contexts'])
        cfg['project'].update(semantics['project'])
        cfg['analysis']['auto_contexts'] = False
        facts, report = self.extract(cfg)
        variable = next(v for v in facts['variables'] if v.get('canonical_path', v['qualified_name']) == name)
        finding = next((f for f in report['findings'] if f['symbol_id'] == variable['symbol_id']), None)
        if finding is None:
            finding = next(f for f in safe_review_samples(facts, len(facts['variables']))
                           if f['symbol_id'] == variable['symbol_id'])
            report['review_safe_samples'] = [finding]
        packet = build_variable_review_packet(self.root, facts, finding, facts_path=self.root/'.ecra/facts.json',
            shared_path=self.root/'.ecra/review/project-evidence.json', report_path=self.root/'.ecra/static-report.json')
        hints = [h for h in packet['concurrency_hints'] if h.get('kind') == 'READ_THEN_WRITEBACK']
        return cfg, facts, report, variable, packet, hints

    def test_direct_argument_has_writeback_fact_and_keeps_both_accesses(self):
        _, facts, _, variable, packet, hints = self.scan()
        self.assertEqual(variable['static_classification'], 'SUSPECT')
        self.assertEqual(variable['size_bytes'], 4)
        self.assertGreaterEqual(variable['alignment_bytes'], 4)
        self.assertEqual(set(variable['writers']), {'IRQ_LOW', 'IRQ_HIGH'})
        self.assertEqual({a['access_kind'] for a in packet['accesses']}, {'READ', 'WRITE'})
        writes = [a for a in packet['accesses'] if a['access_kind'] == 'WRITE']
        self.assertEqual(len({(a['file'], a['line']) for a in writes}), 1)
        self.assertEqual(set(writes[0]['contexts']), {'IRQ_LOW', 'IRQ_HIGH'})
        self.assertTrue(any(r.get('higher') == 'IRQ_HIGH' and r.get('lower') == 'IRQ_LOW'
                            and r['relation'] == 'CAN_PREEMPT' for r in variable['concurrency_relations']))
        self.assertEqual(len(hints), 1)
        self.assertEqual(hints[0]['storage'], 'g_value')
        self.assertEqual(hints[0]['read_contexts'], ['IRQ_LOW'])
        self.assertEqual(hints, variable['concurrency_hints'])
        self.assertTrue(facts['accesses'])

    def run_answer(self, case, answers):
        cfg, facts, report, variable, packet, hints = self.scan(case)
        # Review exactly this variable, including statically safe controls.
        report['findings'] = [f for f in report['findings'] if f['symbol_id'] == variable['symbol_id']]
        cfg['review'].update(enabled=True, workers=1, retries=0)
        calls = []

        def respond(argv, **kwargs):
            calls.append((argv, kwargs))
            value = dict(answers[min(len(calls)-1, len(answers)-1)], finding_id=packet['finding_id'])
            return CompletedProcess([], 0, json.dumps(value, ensure_ascii=False), '')

        with patch('ecra.review.resolve_command', return_value=['synthetic-cli']), patch('ecra.review.execute', side_effect=respond):
            self.review_out = self.root/'.ecra'/case
            row = review_all(self.root, self.review_out, cfg, facts, report, 'scan', lambda _: None)[0]
        return row, calls, packet

    def answer(self, status='REVIEWED_SAFE', **fields):
        result = dict(status=status,
            reason=('LOW读取100后可被HIGH抢占；HIGH写200后LOW仍可将旧值100写回。' if status == 'CONFIRMED'
                    else '32位对齐写访问原子，所有上下文使用相同setter，单一store，last-writer-wins。'),
            evidence=[dict(file='app.c', line=3)], protection='需检查整个READ→WRITEBACK窗口',
            impact='HIGH的更新可能被旧值覆盖', fix='完整屏蔽READ→WRITEBACK窗口',
            verification='建议按确定性交错重放', missing_context=[])
        result.update(fields)
        return result

    def test_atomic_safe_is_challenged_then_corrected(self):
        row, calls, packet = self.run_answer('unsafe_direct_writeback', [self.answer(),
            self.answer('CONFIRMED', interleaving='LOW 读取 100；HIGH 写入 200；LOW 写回 100')])
        self.assertEqual((row['state'], row['status']), ('DONE', 'CONFIRMED'))
        self.assertEqual([a['stage'] for a in row['attempts']], ['ANALYZE', 'STALE_WRITEBACK_CHALLENGE'])
        self.assertEqual(len(calls), 2)
        self.assertEqual(row['format_fix_count'], 0)
        self.assertNotIn('--file', calls[1][0])
        prompt = calls[1][1].get('input') or calls[1][0][-1]
        self.assertIn('STALE_WRITEBACK_CHALLENGE', prompt)
        self.assertNotIn('call_path_sets', prompt)
        self.assertNotIn('accesses', prompt)
        self.assertIn('READ_THEN_WRITEBACK', prompt)
        self.assertNotEqual(json.loads(calls[1][1]['env']['OPENCODE_PERMISSION']), {'*': 'deny'})
        verify_receipt(self.root, self.review_out/'review', row)

    def test_fixture_matrix(self):
        # The existing static protection classifier proves MAIN-vs-IRQ masks;
        # IRQ-vs-IRQ full protection is conservatively left to source review.
        cases = [('safe_irq_protected', 'g_value', True, 'SUSPECT'),
                 ('safe_same_context', 'g_value', True, 'SAFE_PROVEN'),
                 ('different_storage', 'g_value', False, None),
                 ('member_writeback', 'g_state.a', True, 'SUSPECT'),
                 ('member_different_storage', 'g_state.a', False, None),
                 ('unknown_preemption', 'g_value', True, 'SUSPECT')]
        for case, name, expected_hint, classification in cases:
            with self.subTest(case=case):
                _, _, _, variable, _, hints = self.scan(case, name)
                self.assertEqual(bool(hints), expected_hint)
                if classification:
                    self.assertEqual(variable['static_classification'], classification)
                if case == 'member_writeback':
                    self.assertEqual(hints[0]['storage'], name)
                    self.assertEqual(len(hints[0]['call_path']), 3)

    def test_true_safe_controls_are_done_without_challenge(self):
        for case, reason, line in [
                ('safe_irq_protected', 'PRIMASK临界区覆盖整个READ到WRITEBACK窗口，阻止HIGH插入。', 6),
                ('safe_same_context', '所有writer仅在同一不可重入物理IRQ上下文串行运行。', 4)]:
            with self.subTest(case=case):
                answer = self.answer(stale_writeback_assessment=dict(applicable=True, blocked=True,
                    reason=reason, evidence=[dict(file='app.c', line=line)]))
                answer['reason'] = reason
                row, calls, _ = self.run_answer(case, [answer])
                self.assertEqual((row['state'], row['status']), ('DONE', 'REVIEWED_SAFE'))
                self.assertEqual(len(calls), 1)
                self.assertTrue(any(e['line'] == line for e in row['source_evidence']))
                verify_receipt(self.root, self.review_out/'review', row)

    def test_unknown_preemption_is_normal_done(self):
        answer = self.answer('NEED_MORE_CONTEXT', missing_context=['缺少IRQ优先级和屏蔽关系'])
        answer['reason'] = '无法证明HIGH能否抢占LOW。'
        row, calls, packet = self.run_answer('unknown_preemption', [answer])
        self.assertEqual((row['state'], row['status']), ('DONE', 'NEED_MORE_CONTEXT'))
        self.assertIn('UNKNOWN_PREEMPTION', json.dumps(packet))
        self.assertEqual(len(calls), 1)

    def test_repeated_invalid_safe_stops_after_one_challenge(self):
        for status in ('REVIEWED_SAFE', 'FALSE_POSITIVE'):
            with self.subTest(status=status):
                row, calls, _ = self.run_answer('unsafe_direct_writeback', [self.answer(status)])
                self.assertEqual(row['state'], 'TECH_FAILED')
                self.assertNotIn('answer', row)
                self.assertEqual(len(calls), 2)
                self.assertEqual(row['stale_writeback_challenge_count'], 1)
                self.assertEqual(row['format_fix_count'], 0)
                self.assertIn('窗口阻塞证明', row['error'])

    def test_abbreviated_safe_is_semantic_challenge_not_format_fix(self):
        bad = dict(status='REVIEWED_SAFE', reason='32位原子写，所有上下文都调用同一SetValue函数。')
        row, calls, _ = self.run_answer('unsafe_direct_writeback', [bad, self.answer('CONFIRMED')])
        self.assertEqual((row['state'], row['status']), ('DONE', 'CONFIRMED'))
        self.assertEqual(row['format_fix_count'], 0)
        self.assertEqual(len(calls), 2)

    def test_assessment_requires_true_boolean_reason_and_valid_local_evidence(self):
        _, _, _, _, packet, _ = self.scan()
        valid = dict(applicable=True, blocked=True, reason='完整PRIMASK窗口屏蔽其他writer。',
                     evidence=[dict(file='app.c', line=6)])
        mutations = [dict(blocked=False), dict(blocked=1), dict(applicable=False), dict(reason=''),
                     dict(evidence=[]), dict(evidence=[dict(file='missing.c', line=1)]),
                     dict(evidence=[dict(file='app.c', line=9999)]),
                     dict(evidence=[dict(file='../outside.c', line=1)]),
                     dict(reason='32位访问原子，对齐，无撕裂，single store，same setter，last-writer-wins。')]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                with self.assertRaises(StaleWritebackSafetyError):
                    validate_stale_writeback_safety(self.answer(stale_writeback_assessment=valid | mutation), packet, self.root)
        for reason in ('32位写', '自然对齐', '单条store', '不会撕裂', 'last-writer-wins',
                       '最终都调用同一个setter', '相同setter', '最终只有一个源码赋值位置',
                       'same setter', 'single source store position', '最后写者生效'):
            with self.subTest(atomic_only=reason), self.assertRaises(StaleWritebackSafetyError):
                validate_stale_writeback_safety(self.answer(stale_writeback_assessment=valid | dict(reason=reason)), packet, self.root)

    def test_no_writeback_has_no_extra_safe_protocol(self):
        row, calls, _ = self.run_answer('different_storage', [self.answer()])
        self.assertEqual((row['state'], row['status']), ('DONE', 'REVIEWED_SAFE'))
        self.assertEqual(len(calls), 1)

    def test_direct_rule_uses_parameter_value_and_storage_not_names(self):
        source = (FIXTURES / 'unsafe_direct_writeback.c').read_text()
        source = source.replace('g_value', 'renamed_object').replace('SetValue', 'PublishReading')
        _, _, _, _, _, hints = self.scan(name='renamed_object', source=source)
        self.assertEqual(hints[0]['storage'], 'renamed_object')
        for body in ['g_value = 200U;', 'value=7; g_value=value;', '(void)&value; g_value=value;']:
            with self.subTest(body=body):
                source = (FIXTURES / 'unknown_preemption.c').read_text().replace('g_value = value;', body)
                self.assertFalse(self.scan(source=source)[-1])

    def test_only_setter_is_masked_does_not_protect_argument_read(self):
        source = (FIXTURES / 'unsafe_direct_writeback.c').read_text().replace(
            'g_value = value;', '__disable_irq(); g_value = value; __enable_irq();')
        _, _, _, variable, _, hints = self.scan(source=source)
        self.assertTrue(hints)
        self.assertEqual(variable['static_classification'], 'SUSPECT')

    def test_parameter_forwarding_across_translation_units(self):
        source = '''#include "fixture.h"
            extern volatile uint32_t g_value;
            void Relay(uint32_t unrelated, uint32_t old);
            void LOW_IRQHandler(void) { Relay(7, g_value); }
            void HIGH_IRQHandler(void) { Relay(7, 200U); }
            int main(void) { return 0; }'''
        extra = {'setter.c': '''#include "fixture.h"
            volatile uint32_t g_value;
            void Commit(uint32_t value) { g_value = value; }
            void Relay(uint32_t unrelated, uint32_t old) { Commit(old); }'''}
        hints = self.scan(source=source, extra_sources=extra)[-1]
        self.assertEqual(len(hints), 1)
        self.assertEqual(hints[0]['read_site']['file'], 'app.c')
        self.assertEqual(hints[0]['write_site']['file'], 'setter.c')
        self.assertEqual(len(hints[0]['call_path']), 3)

    def test_array_elements_use_exact_canonical_identity(self):
        for index, expect in [(0, True), (1, False)]:
            source = '''#include "fixture.h"
                volatile uint32_t samples[2];
                void Commit(uint32_t value) { samples[0] = value; }
                void LOW_IRQHandler(void) { Commit(samples[INDEX]); }
                void HIGH_IRQHandler(void) { Commit(200U); }
                int main(void) { return 0; }'''.replace('INDEX', str(index))
            with self.subTest(index=index):
                hints = self.scan(source=source, name='samples[0]')[-1]
                self.assertEqual(bool(hints), expect)

    def test_challenge_and_format_fixes_have_separate_budgets(self):
        row, calls, _ = self.run_answer('unsafe_direct_writeback', [self.answer(),
            dict(status='CONFIRMED', reason='LOW被HIGH抢占造成旧值覆盖。'), self.answer('CONFIRMED')])
        self.assertEqual((row['state'], row['status']), ('DONE', 'CONFIRMED'))
        self.assertEqual([a['stage'] for a in row['attempts']],
                         ['ANALYZE', 'STALE_WRITEBACK_CHALLENGE', 'FORMAT_FIX'])
        self.assertEqual(row['format_fix_count'], 1)
        self.assertEqual(json.loads(calls[-1][1]['env']['OPENCODE_PERMISSION']), {'*': 'deny'})
        verify_receipt(self.root, self.review_out/'review', row)

    def test_prompt_explains_window_and_rejects_atomic_shortcuts(self):
        for phrase in ('READ_THEN_WRITEBACK', 'READ位置→旧值保存→调用链→实际WRITEBACK',
                       'last-writer-wins', 'execution writer context', '哪些writer可插入', 'NEED_MORE_CONTEXT'):
            self.assertIn(phrase, REVIEW_PROMPT)

    def test_deterministic_c_interleaving_replays_lost_update(self):
        compiler = shutil.which('clang') or shutil.which('gcc')
        if not compiler:
            self.skipTest('host C compiler unavailable; AST fixtures still run')
        for name in ('fixture.h', 'unsafe_direct_writeback.c', 'replay.c'):
            (self.root / name).write_bytes((FIXTURES / name).read_bytes())
        executable = self.root / ('replay.exe' if os.name == 'nt' else 'replay')
        subprocess.run([compiler, '-std=c11', str(self.root/'replay.c'), '-o', str(executable)],
                       check=True, capture_output=True, text=True, timeout=30)
        replay = subprocess.run([str(executable)], check=True, capture_output=True, text=True, timeout=10)
        self.assertIn('READ 100 -> HIGH WRITE 200 -> LOW WRITEBACK 100; final=100', replay.stdout)

    @unittest.skipUnless(os.environ.get('ECRA_STALE_WRITEBACK_LIVE') == '1', 'opt-in live OpenCode review')
    def test_live_opencode_reviews_new_fixtures(self):
        # Uses only new fixtures in a temporary project. OpenCode has read
        # permissions only; no coding delegation or business source is used.
        for case, expected in [('unsafe_direct_writeback', {'CONFIRMED', 'LIKELY'}),
                               ('safe_irq_protected', {'REVIEWED_SAFE'}),
                               ('safe_same_context', {'REVIEWED_SAFE'})]:
            with self.subTest(case=case):
                cfg, facts, report, variable, _, _ = self.scan(case)
                report['findings'] = [f for f in report['findings'] if f['symbol_id'] == variable['symbol_id']]
                cfg['review'].update(enabled=True, command=['opencode'], workers=1, retries=0, timeout_seconds=90)
                from ecra.common import write_json
                write_json(self.root/'.ecra/facts.json', facts)
                row = review_all(self.root, self.root/'.ecra'/case, cfg, facts, report, 'live-fixture', print)[0]
                print(case, row['state'], row.get('status'), row.get('error', ''))
                self.assertEqual(row['state'], 'DONE', row.get('error'))
                self.assertIn(row['status'], expected)


if __name__ == '__main__':
    unittest.main()
