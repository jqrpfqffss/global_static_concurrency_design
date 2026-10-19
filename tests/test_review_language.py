"""Language repair is a separate audited operation, never a semantic rewrite."""
import copy
import json
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch
from tests.test_review_integrity import IntegrityTests as _Fixture
from tests.test_review_contract import answer_for
from ecra.review import review_all, verify_receipt
from ecra.review_language import language_issues, validate_correction, display_answer
from ecra.review_contract import validate_nvic_missing_facts, NVICFactConflictError


class ReviewLanguageTests(unittest.TestCase):
    setUp = _Fixture.setUp

    def english(self):
        value = answer_for('LIKELY')
        value.update(reason='The IRQ can overwrite the old value at priority 2.',
                     missing_context=['Actual IRQ mask state during the foreground write window.'])
        value['evidence'][0]['claim'] = 'The IRQ writes shared.'
        return value

    def translated(self):
        value = self.english()
        value.update(reason='IRQ 在优先级 2 下可覆盖旧值。',
                     missing_context=['尚需核实前台写入窗口内的实际 IRQ 屏蔽状态。'])
        value['evidence'][0]['claim'] = 'IRQ 写入 shared。'
        return value

    def run_review(self, answers, **options):
        iterator, calls = iter(answers), []
        def respond(argv, **kwargs):
            calls.append((argv, kwargs))
            return CompletedProcess(argv, 0, json.dumps(next(iterator), ensure_ascii=False), '')
        with patch('ecra.review.resolve_command', return_value=['synthetic-cli']), patch('ecra.review.execute', side_effect=respond):
            rows = review_all(self.root, self.out, self.cfg, self.facts, self.report, 'scan', lambda _: None, **options)
        return rows[0], calls

    def test_detects_each_natural_language_field_and_allows_identifiers(self):
        for key in ('reason','interleaving','protection','impact','fix','verification'):
            value = answer_for()
            value[key] = 'Actual interrupt configuration is missing from the source.'
            self.assertIn(key, language_issues(value))
        self.assertFalse(language_issues(answer_for()))
        self.assertFalse(language_issues(dict(reason='TIM4_IRQn 优先级为 2；HAL_NVIC_SetPriority() 使用 PRIMASK。')))
        self.assertFalse(language_issues(dict(reason='UART_SetConfig 只读取 huart->Init.StopBits 并写 USART 寄存器，不修改 huart->Instance。')))
        self.assertFalse(language_issues(dict(reason='访问事实 ID：A-0a6e7c833dd93a795ced、A-1345a4e167dda227dd62、A-b5c7b20f9f73e9d5cb70、A-e978743f78a7984a281b')))
        self.assertFalse(language_issues(dict(reason='执行入口：vector:slot:1、vector:slot:54、auto:timer_callback。')))
        self.assertTrue(language_issues(dict(explanation=dict(participants=[dict(entry='foreground execution entry')]))))
        original=dict(reason='入口已核对。',explanation=dict(participants=[dict(entry='Task → Init')]))
        self.assertFalse(language_issues(original))
        changed=copy.deepcopy(original);changed['explanation']['participants'][0]['entry']='Task → Other'
        with self.assertRaises(ValueError):validate_correction(original,changed)

    def test_language_repair_preserves_original_receipt_and_has_no_tools(self):
        row, calls = self.run_review([self.english(), self.translated()])
        self.assertEqual((row['state'], row['status']), ('DONE', 'LIKELY'), row)
        self.assertEqual(row['language_fix_count'], 1)
        self.assertEqual(row['format_fix_count'], 0)
        self.assertEqual(json.loads(calls[1][1]['env']['OPENCODE_PERMISSION']), {'*': 'deny'})
        self.assertNotIn('--file', calls[1][0])
        original = self.out / 'review' / row['language_correction']['source_stdout_file']
        self.assertEqual(json.loads(original.read_text(encoding='utf-8')), self.english())
        self.assertEqual(verify_receipt(self.root, self.out/'review', row), self.translated())
        cached, unused = self.run_review([])
        self.assertTrue(cached['cached'])
        self.assertEqual(unused, [])

    def test_rejects_changes_to_status_values_coordinates_and_technical_names(self):
        for mutation in ('status', 'number', 'location', 'api', 'delete'):
            value = self.translated()
            if mutation == 'status': value['status'] = 'REVIEWED_SAFE'
            elif mutation == 'number': value['reason'] = value['reason'].replace('2', '1')
            elif mutation == 'location': value['evidence'][0]['line'] = 1
            elif mutation == 'api': value['reason'] = value['reason'].replace('IRQ', 'NVIC')
            else: value.pop('impact')
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                validate_correction(self.english(), value)

    def test_failed_language_repair_keeps_static_suspect_and_raw_evidence(self):
        bad = dict(self.translated(), status='REVIEWED_SAFE')
        row, _ = self.run_review([self.english(), bad, bad])
        self.assertEqual(row['state'], 'TECH_FAILED')
        self.assertEqual(row['static_classification'], 'SUSPECT')
        self.assertEqual(len(row['attempts']), 3)
        self.assertNotIn('answer', row)

    def test_legacy_prose_is_not_mixed_into_current_chinese_reports(self):
        raw = self.english()
        localized = display_answer(raw)
        self.assertFalse(language_issues(localized))
        self.assertEqual(localized['status'], raw['status'])
        self.assertEqual(localized['evidence'][0]['line'], 2)
        self.assertEqual(raw, self.english())

    def test_both_html_and_markdown_use_same_chinese_view_and_keep_raw_json(self):
        import os
        from tests import test_ecra as fixtures
        from ecra.report import generate
        from ecra.common import read_json
        cwd=Path.cwd()
        self.addCleanup(lambda:os.chdir(cwd))
        self.out.mkdir(exist_ok=True)
        cfg=fixtures.ProjectTest.project(self,{'app.c':'int shared;void IRQ(void){shared++;}void Task(void){shared++;}'},
            contexts=[dict(id='irq',kind='ISR',functions=['IRQ']),dict(id='task',kind='TASK',functions=['Task'])])
        facts,report=fixtures.ProjectTest.extract(self,cfg)
        facts['translation_units']=[]
        report['coverage'].update(translation_units_total=1,translation_units_parsed=1,parse_coverage_percent=100)
        answer=self.english()
        answer['finding_id']=report['findings'][0]['finding_id']
        record=dict(finding_id=answer['finding_id'],state='DONE',status='LIKELY',answer=answer)
        original=copy.deepcopy(record)
        generate(self.out,facts,report,[record])
        for name in ('index.html','opencode_review.html','reports/opencode_global_static_review.md'):
            text=(self.out/name).read_text(encoding='utf-8')
            self.assertNotIn(answer['reason'],text)
            self.assertIn('历史英文说明尚待中文复核',text)
        archived=read_json(self.out/'reports/global_static_concurrency.json')['review_records'][0]
        self.assertEqual(archived['answer'],answer)
        self.assertEqual(record,original)

    def test_false_nvic_missing_claim_gets_semantic_challenge(self):
        self.facts['nvic_priorities'] = [dict(irqn=['TIM4_IRQn'], vectors=['TIM4_IRQHandler'],
            source_configurations=[dict(file='app.c',line=1)], configured_preemption=2)]
        bad = dict(answer_for('LIKELY'), missing_context=['尚未核实 TIM4_IRQn 优先级。'])
        with self.assertRaises(NVICFactConflictError):
            validate_nvic_missing_facts(bad, self.facts)
        good = dict(bad, missing_context=['尚需核实实际运行窗口内的中断触发条件。'])
        row, calls = self.run_review([bad, good])
        self.assertEqual((row['state'],row['status']), ('DONE','LIKELY'), row)
        self.assertEqual(row['nvic_fact_challenge_count'], 1)
        self.assertEqual(row['format_fix_count'], 0)


del _Fixture

if __name__ == '__main__':
    unittest.main()
