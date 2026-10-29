"""存储粒度转换不能被根对象的汇总分类误报为新增或消除风险。"""
import copy
import json
import unittest

from ecra.git_diff import compare, summarize
from ecra.analysis import analyze, merge
from ecra.compilation import prepare
from ecra.extract import Extractor
from ecra.report import generate
from tests import test_ecra


SCALAR = 'int shared;void main(void){shared++;}void ISR(void){shared++;}'
STRUCT = ('struct State {int value;} shared;'
          'void main(void){shared.value++;}void ISR(void){shared.value++;}')
ARRAY = 'int shared[2];void main(void){shared[0]++;}void ISR(void){shared[0]++;}'


class StorageShapeDiffTests(unittest.TestCase):
    setUp = test_ecra.ProjectTest.setUp
    project = test_ecra.ProjectTest.project

    def extract(self, cfg):
        units, audit = prepare(self.root, cfg)
        parts = [Extractor(dict(root=str(self.root), unit=u, config=cfg)).run() for u in units]
        for part in parts:
            self.assertEqual(part['parse_status'], 'PARSED', part['diagnostics'])
        facts = merge(parts)
        facts['translation_units'] = [dict(u, parse_status=p['parse_status'], diagnostics=p['diagnostics'],
            semantic_macros_digest=p.get('semantic_macros_digest'), includes=p.get('includes', []))
            for u, p in zip(units, parts)]
        coverage = dict(audit, translation_units_total=len(units), translation_units_parsed=len(units),
                        translation_units_partial=0, translation_units_failed=0, parse_coverage_percent=100)
        return facts, analyze(facts, cfg, coverage)

    def snapshots(self, old, new):
        contexts = [dict(id='main', kind='MAIN', functions=['main']),
                    dict(id='irq', kind='ISR', functions=['ISR'])]
        cfg = self.project({'a.c': old}, contexts=contexts)
        bf, br = self.extract(cfg)
        base = summarize(bf, br)
        cfg = self.project({'a.c': new}, contexts=contexts)
        hf, hr = self.extract(cfg)
        head = summarize(hf, hr)
        return base, head, hf, hr

    def delta(self, base, head):
        before = json.dumps([base, head], sort_keys=True)
        result = compare(base, head, dict(files=[], head_sha='head', base_sha='base',
            current_ref='feature', target_ref='base', compare_mode='direct', base_source_root=str(self.root)))
        self.assertEqual(before, json.dumps([base, head], sort_keys=True))
        return result

    def root_id(self, summary):
        return next(sid for sid, v in summary['variables'].items() if v['name'] == 'shared')

    def test_scalar_to_struct_keeps_member_risk_and_cannot_claim_removed(self):
        base, head, facts, report = self.snapshots(SCALAR, STRUCT)
        result = self.delta(base, head)
        sid = self.root_id(head)
        self.assertEqual(base['variables'][sid]['dimensions']['classification'], 'SUSPECT')
        self.assertEqual(head['variables'][sid]['dimensions']['classification'], 'CONTAINER')
        impact = result['impacts'][sid]
        self.assertEqual(impact['risk_change'], '无法判断变化结果')
        self.assertEqual(impact['risk_comparison_status'], 'STORAGE_SHAPE_CHANGED')
        self.assertIn('MATCH_UNCERTAIN', impact['reasons'])
        member = next(v for v in facts['variables'] if v['qualified_name'] == 'shared.value')
        self.assertEqual(member['static_classification'], 'SUSPECT')
        self.assertIn(member['symbol_id'], result['selected_symbol_ids'])
        self.assertEqual(report['coverage']['variable_accountability']['missing'], 0)
        self.assertEqual(report['coverage']['variable_accountability']['duplicate_ids'], 0)

    def test_struct_to_scalar_does_not_claim_new_risk_from_container(self):
        base, head, _, _ = self.snapshots(STRUCT, SCALAR)
        result = self.delta(base, head)
        sid = self.root_id(head)
        self.assertEqual(result['impacts'][sid]['risk_change'], '无法判断变化结果')
        self.assertIn('MATCH_UNCERTAIN', result['impacts'][sid]['reasons'])
        self.assertEqual(head['variables'][sid]['dimensions']['classification'], 'SUSPECT')
        removed = next(v for v in result['deleted_variables'] if v['name'] == 'shared.value')
        self.assertEqual(removed['impact']['risk_change'], '无法判断变化结果')
        self.assertNotIn(removed['symbol_id'], result['selected_symbol_ids'])

    def test_scalar_array_transitions_are_not_risk_comparisons(self):
        for old, new in ((SCALAR, ARRAY), (ARRAY, SCALAR)):
            with self.subTest(new=new):
                base, head, _, _ = self.snapshots(old, new)
                impact = self.delta(base, head)['impacts'][self.root_id(head)]
                self.assertEqual(impact['risk_change'], '无法判断变化结果')
                self.assertEqual(impact['risk_comparison_status'], 'STORAGE_SHAPE_CHANGED')

    def test_non_storage_and_unassessed_versions_are_not_new_risk_proofs(self):
        original, head, _, _ = self.snapshots(SCALAR, SCALAR)
        sid = self.root_id(head)
        for state in ('NON_STORAGE', 'OUT_OF_BUILD', None, 'UNKNOWN'):
            with self.subTest(state=state):
                base = copy.deepcopy(original)
                base['variables'][sid]['dimensions']['classification'] = state
                impact = self.delta(base, head)['impacts'][sid]
                self.assertEqual(impact['risk_change'], '无法判断变化结果')
                self.assertNotEqual(impact['risk_comparison_status'], 'COMPARABLE')
                self.assertTrue(impact['risk_comparison_note'])

    def test_comparable_scalar_risk_changes_keep_original_meaning(self):
        safe = 'int shared;void main(void){shared++;}void ISR(void){}'
        base, head, _, _ = self.snapshots(SCALAR, safe)
        sid = self.root_id(head)
        self.assertEqual(head['variables'][sid]['dimensions']['classification'], 'SAFE_PROVEN')
        for old, new, label in ((base, head, '风险可能已消除'), (head, base, '新增疑似风险')):
            with self.subTest(label=label):
                impact = self.delta(old, new)['impacts'][sid]
                self.assertEqual(impact['risk_change'], label)
                self.assertEqual(impact['risk_comparison_status'], 'COMPARABLE')
                self.assertNotIn('MATCH_UNCERTAIN', impact['reasons'])

    def test_aggregate_details_explain_uncertainty_in_existing_index(self):
        after = STRUCT.replace('int value;', 'int value;int other;').replace('shared.value++;', 'shared.value+=2;')
        base, head, facts, report = self.snapshots(STRUCT, after)
        result = self.delta(base, head)
        sid = self.root_id(head)
        self.assertEqual(result['impacts'][sid]['risk_comparison_status'], 'AGGREGATE_OR_UNASSESSED')
        self.assertNotIn('MATCH_UNCERTAIN', result['impacts'][sid]['reasons'])
        report['git_diff'] = result
        for v in facts['variables']:
            if v['symbol_id'] in result['impacts']:
                v['impact'] = result['impacts'][v['symbol_id']]
        generate(self.root/'.ecra', facts, report, {})
        documents = list((self.root/'.ecra').rglob('*.html'))
        self.assertTrue(any('不是可直接比较的变量风险结论' in p.read_text(encoding='utf-8') for p in documents))
        self.assertTrue((self.root/'.ecra/index.html').is_file())
        self.assertFalse((self.root/'.ecra/diff_index.html').exists())
        self.assertEqual(report['coverage']['variable_accountability']['missing'], 0)


if __name__ == '__main__':
    unittest.main()
