"""Schema/retry tests use synthetic subprocess output, never review evidence."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from ecra.review import parse_answer, review_all
from ecra.review_contract import CONTRACT_PROMPT, validate_explanation
from ecra.review_presentation import explanation, review_markdown
from tests.review_fixtures import structured_fields
from tests.test_review_presentation import VisibleText


def answer_for(status='CONFIRMED'):
    return dict(finding_id='F', status=status,
                evidence=[dict(file='src.c', line=1, quote='count++;', claim='Protocol fixture access')],
                **{k: 'Protocol fixture only' for k in ('reason', 'interleaving', 'protection', 'impact', 'fix', 'verification')},
                **structured_fields(status))


class ContractTests(unittest.TestCase):
    def test_rejects_missing_actors_steps_states_and_broken_references(self):
        original = answer_for()
        changes = [
            (lambda a: a.pop('schema_version'), 'schema_version'),
            (lambda a: a.pop('explanation'), 'explanation'),
            (lambda a: a['explanation'].pop('participants'), 'participants'),
            (lambda a: a['explanation']['participants'][1].update(id='A'), '不能重复'),
            (lambda a: a['explanation']['participants'][1].update(eligibility='EXCLUDED'), '已排除'),
            (lambda a: a['explanation']['scenarios'][0]['steps'][0].update(actor_id='ghost'), '不存在'),
            (lambda a: a['explanation']['scenarios'][0]['steps'][0].pop('state_before'), 'state_before'),
            (lambda a: a['explanation']['scenarios'][0]['steps'][0].update(evidence_refs=[2]), '序号'),
            (lambda a: a['explanation']['scenarios'][0]['steps'].pop(), '至少两步'),
            (lambda a: a['explanation'].update(summary='长'*181), '180'),
            (lambda a: a['evidence'][0].pop('claim'), 'claim'),
        ]
        for change, message in changes:
            with self.subTest(message=message):
                value = copy.deepcopy(original)
                change(value)
                with self.assertRaisesRegex(ValueError, message):
                    validate_explanation(value, required=True)

    def test_safe_unknown_and_gaps_do_not_require_fabricated_conflicts(self):
        for status in ['CONFIRMED', 'REVIEWED_SAFE', 'FALSE_POSITIVE', 'NEED_MORE_CONTEXT', 'LIKELY']:
            self.assertTrue(validate_explanation(answer_for(status), required=True))
        safe = answer_for('REVIEWED_SAFE')
        safe['explanation']['scenarios'][0]['kind'] = 'CONFLICT'
        with self.assertRaisesRegex(ValueError, '非确认结论'):
            validate_explanation(safe, required=True)
        unknown = answer_for('NEED_MORE_CONTEXT')
        unknown['explanation']['missing_evidence'] = []
        with self.assertRaisesRegex(ValueError, '还缺什么'):
            validate_explanation(unknown, required=True)
        gap = answer_for()
        gap['review_type'] = 'EVIDENCE_GAP'
        gap['explanation'].update(participants=[], scenarios=[])
        self.assertTrue(validate_explanation(gap, expected_type='EVIDENCE_GAP', required=True))
        with self.assertRaisesRegex(ValueError, 'symbol_id'):
            validate_explanation(gap, expected_type='VARIABLE', required=True)

    def test_v2_display_is_only_opencode_fields_and_links(self):
        answer = answer_for()
        story = answer['explanation']
        story['summary'] = 'MODEL_SUMMARY <script>bad()</script>'
        story['participants'][0]['label'] = 'MODEL_ACTOR_A'
        story['scenarios'][0]['steps'][0]['action'] = 'MODEL_ACTION_A'
        story['scenarios'][0]['actual'] = 'MODEL_RESULT'
        html = explanation(answer, 'confirmed', citation_link=lambda i: '#source-' + str(i))
        visible = ''.join(VisibleText(html).parts)
        for text in ['MODEL_SUMMARY', 'MODEL_ACTOR_A', 'MODEL_ACTION_A', 'MODEL_RESULT', 'Fixture before', 'Fixture after']:
            self.assertIn(text, visible)
        self.assertIn('href="#source-1"', html)
        self.assertNotIn('<script>', html)
        self.assertIn('OpenCode 原始结构化回答', visible)
        md = '\n'.join(review_markdown(answer))
        self.assertIn('1. **MODEL_ACTOR_A**：MODEL_ACTION_A', md)
        self.assertIn('**此过程的结果：**MODEL_RESULT', md)
        self.assertNotIn("'participants':", md)
        legacy = answer_for()
        for key in ['schema_version', 'review_type', 'explanation']:
            legacy.pop(key)
        self.assertIn('旧版 OpenCode', explanation(legacy, 'confirmed'))
        self.assertNotIn('统一协议 v2', explanation(legacy, 'confirmed'))
        answer['explanation']['participants'] = []
        self.assertIn('未通过校验', explanation(answer, 'confirmed'))
        self.assertNotIn('MODEL_ACTION_A', explanation(answer, 'confirmed'))

    def test_same_contract_across_project_roots_checks_each_projects_actual_quotes(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            for project in ['项目甲', 'Different Project B']:
                root = base/project
                root.mkdir()
                (root/'src.c').write_text('count++;\n', encoding='utf-8')
                answer = answer_for()
                raw = json.dumps(dict(type='text', part=dict(text=json.dumps(answer))))
                self.assertEqual(parse_answer(raw, 'F', root, require_quotes=True, require_schema=True, expected_type='VARIABLE'), answer)
            (base/'Different Project B/src.c').write_text('count += 2;\n', encoding='utf-8')
            raw = json.dumps(dict(type='text', part=dict(text=json.dumps(answer))))
            with self.assertRaisesRegex(ValueError, '原文与源码不符'):
                parse_answer(raw, 'F', base/'Different Project B', require_schema=True)

    def test_new_review_rejects_legacy_and_returns_error_to_opencode_for_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'src.c').write_text('count++;\n', encoding='utf-8')
            complete = answer_for()
            incomplete = copy.deepcopy(complete)
            incomplete['explanation'].pop('participants')
            values = [incomplete, complete]
            prompts = []
            def execute(argv, **kwargs):
                prompts.append(argv[-1])
                value = values[len(prompts)-1]
                return CompletedProcess(argv, 0, json.dumps(dict(type='text', part=dict(text=json.dumps(value)))), '')
            cfg = dict(review=dict(enabled=True, workers=1, retries=1), analysis={})
            facts = dict(variables=[], contexts=[], functions=[], calls=[])
            report = dict(findings=[dict(finding_id='F', symbol_id='count', accesses=[])], coverage={}, limitations=[])
            with patch('ecra.review.resolve_command', return_value=['fake-protocol-only']), patch('ecra.review.execute', side_effect=execute):
                result = review_all(root, root/'.ecra', cfg, facts, report, 'scan', lambda _: None)[0]
            self.assertEqual(len(prompts), 2)
            self.assertTrue(all(CONTRACT_PROMPT in prompt for prompt in prompts))
            self.assertIn('participants', prompts[1])
            self.assertIn('上一次输出未通过校验', prompts[1])
            self.assertEqual(result['answer'], complete)  # No fields supplied by renderer/validator.
            self.assertEqual(result['execution']['schema_version'], 2)
            legacy = copy.deepcopy(complete)
            for key in ['schema_version', 'review_type', 'explanation']:
                legacy.pop(key)
            raw = json.dumps(dict(type='text', part=dict(text=json.dumps(legacy))))
            with self.assertRaisesRegex(ValueError, 'schema_version'):
                parse_answer(raw, 'F', root, require_schema=True)
            self.assertEqual(parse_answer(raw, 'F', root), legacy)  # Read-only historical compatibility.


if __name__ == '__main__':
    unittest.main()
