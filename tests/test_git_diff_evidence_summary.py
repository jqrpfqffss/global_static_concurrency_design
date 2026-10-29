"""差异详情使用可核对的双版本摘要，不改变完整证据或静态分类。"""
import copy
import json
import re
import unittest

from ecra.git_diff import SUMMARY_SCHEMA
from ecra.html_report import diff_evidence_table
from ecra.html_evidence import HtmlEvidence
from ecra.report import generate
from ecra.review import build_variable_review_packet
from tests import test_git_diff_storage_shape as shapes


class EvidenceSummaryTests(unittest.TestCase):
    setUp = shapes.StorageShapeDiffTests.setUp
    project = shapes.StorageShapeDiffTests.project
    extract = shapes.StorageShapeDiffTests.extract
    snapshots = shapes.StorageShapeDiffTests.snapshots
    delta = shapes.StorageShapeDiffTests.delta
    root_id = shapes.StorageShapeDiffTests.root_id

    def test_write_to_rmw_has_readable_counts_and_preserves_unmodified_irq(self):
        before = 'int shared;void main(void){shared=1;}void ISR(void){shared=2;}'
        base, head, facts, report = self.snapshots(before, before.replace('shared=1', 'shared++'))
        sid = self.root_id(head)
        delta = self.delta(base, head)
        changes = delta['impacts'][sid]['evidence_changes']['accesses']
        self.assertEqual(base['schema'], SUMMARY_SCHEMA)
        self.assertEqual(changes['base'], {'WRITE': 2})
        self.assertEqual(changes['head'], {'RMW': 1, 'WRITE': 1})
        self.assertEqual(base['variables'][sid]['dimensions']['classification'], 'SUSPECT')
        self.assertEqual(head['variables'][sid]['dimensions']['classification'], 'SUSPECT')
        self.assertIn('读改写：1', diff_evidence_table(delta['impacts'][sid]))
        finding = next(f for f in report['findings'] if f.get('symbol_id') == sid)
        packet = build_variable_review_packet(self.root, facts, finding,
            facts_path='facts.json', shared_path='shared.json', report_path='report.json')
        self.assertTrue(any(f['name'] == 'ISR' for f in packet['functions']))
        self.assertTrue(any(a['access_kind'] == 'WRITE' for a in packet['accesses']))

    def test_removed_critical_section_retains_mask_observations(self):
        before = ('void __disable_irq(void);void __enable_irq(void);int shared;'
                  'void main(void){__disable_irq();shared++;__enable_irq();}void ISR(void){shared++;}')
        base, head, facts, _ = self.snapshots(before,
            before.replace('__disable_irq();shared++;__enable_irq();', 'shared++;'))
        sid = self.root_id(head)
        impact = self.delta(base, head)['impacts'][sid]
        self.assertIn('PROTECTION_CHANGED', impact['reasons'])
        changes = impact['evidence_changes']['protection']
        self.assertEqual(changes['base']['status'], 'EFFECTIVE')
        self.assertEqual(changes['head']['status'], 'NOT_FOUND')
        self.assertGreater(changes['base']['primask'].get('DISABLED', 0), 0)
        self.assertEqual(changes['head']['primask'].get('DISABLED', 0), 0)
        self.assertIn('PRIMASK 已屏蔽/未屏蔽/未知', diff_evidence_table(impact))
        self.assertEqual(next(v for v in facts['variables'] if v['symbol_id'] == sid)['static_classification'],
                         head['variables'][sid]['dimensions']['classification'])

    def test_added_irq_caller_exposes_contexts_and_complete_graph_counts(self):
        before = 'int shared;void Store(void){shared++;}void main(void){Store();}void ISR(void){}'
        base, head, facts, _ = self.snapshots(before, before.replace('ISR(void){}', 'ISR(void){Store();}'))
        sid = self.root_id(head)
        impact = self.delta(base, head)['impacts'][sid]
        changes = impact['evidence_changes']
        self.assertEqual({c['kind'] for c in changes['contexts']['base']}, {'MAIN'})
        self.assertEqual({c['kind'] for c in changes['contexts']['head']}, {'MAIN', 'ISR'})
        self.assertEqual(changes['graph']['base'], dict(functions=2, edges=1, roots=1))
        self.assertEqual(changes['graph']['head'], dict(functions=3, edges=2, roots=2))
        self.assertEqual(impact['unchanged_edges_count'], 1)
        self.assertEqual(len(facts['calls']), 2)
        self.assertIn('函数节点：3', diff_evidence_table(impact))

    def test_changed_layout_reports_actual_size_without_treating_container_as_safe(self):
        before = 'int shared[2];void main(void){shared[0]++;}void ISR(void){shared[0]++;}'
        base, head, _, _ = self.snapshots(before, before.replace('shared[2]', 'shared[4]'))
        impact = self.delta(base, head)['impacts'][self.root_id(head)]
        layout = impact['evidence_changes']['declaration']
        self.assertEqual(layout['base']['size_bytes'], 8)
        self.assertEqual(layout['head']['size_bytes'], 16)
        self.assertEqual(impact['risk_change'], '无法判断变化结果')
        html = diff_evidence_table(impact)
        self.assertIn('大小：8 字节', html)
        self.assertIn('大小：16 字节', html)

    def test_comments_and_display_only_metadata_cannot_drive_selection(self):
        before = 'struct {int value;}shared;void main(void){shared.value++;}void ISR(void){shared.value++;}'
        base, head, _, _ = self.snapshots(before, '// 注释\n\n' + before)
        self.assertEqual(self.delta(base, head)['selected_symbol_ids'], [])
        altered = copy.deepcopy(head)
        for value in altered['variables'].values():
            value['evidence_summary'] = dict(declaration=dict(type='仅展示测试'))
        self.assertEqual(self.delta(head, altered)['selected_symbol_ids'], [])

    def test_existing_index_escapes_summary_links_patch_and_handles_legacy_summary(self):
        before = 'int shared;void main(void){shared=1;}void ISR(void){shared=2;}'
        base, head, facts, report = self.snapshots(before, before.replace('shared=1', 'shared++'))
        result = self.delta(base, head)
        out = self.root/'.ecra'
        patch = out/'git_diff'/'current.patch'
        patch.parent.mkdir(parents=True)
        patch.write_text('--- 代码差异\n', encoding='utf-8')
        impact = result['impacts'][self.root_id(head)]
        impact['diff_patch_path'] = str(patch)
        impact['evidence_changes']['declaration'] = dict(base=dict(type='<script>alert(1)</script>'),
                                                       head=dict(type='int', size_bytes=4))
        self.assertNotIn('<script>alert(1)</script>', diff_evidence_table(impact))
        self.assertIn('&lt;script&gt;', diff_evidence_table(impact))
        report['git_diff'] = result
        for v in facts['variables']:
            if v['symbol_id'] in result['impacts']:
                v['impact'] = result['impacts'][v['symbol_id']]
        generate(out, facts, report, {})
        documents = [p.read_text(encoding='utf-8') for p in out.rglob('*.html')]
        self.assertTrue(any('新旧变化摘要' in s and '基准版本' in s and '当前版本' in s for s in documents))
        self.assertTrue(any('git_diff/current.patch' in s and '查看本轮代码差异' in s for s in documents))
        self.assertTrue((out/'index.html').is_file())
        self.assertFalse((out/'diff_index.html').exists())
        self.assertIn('未提供该项摘要', diff_evidence_table(dict(base={}, evidence_changes=dict(accesses=dict(base=None, head=None)))))
        self.assertEqual(report['coverage']['variable_accountability']['duplicate_ids'], 0)
        self.assertEqual(report['coverage']['variable_accountability']['missing'], 0)

    def test_deferred_difference_patch_link_resolves_to_existing_archive(self):
        out = self.root/'.ecra'
        patch = out/'git_diff'/'本轮 变化.patch'
        patch.parent.mkdir(parents=True)
        patch.write_text('完整差异', encoding='utf-8')
        store = HtmlEvidence(out, 'fingerprint', '', threshold=0)
        store.detail('差异变量', '<a href="git_diff/本轮 变化.patch">查看本轮代码差异</a>', 'evidence')
        page = next((out/'html_details').glob('*.html'))
        link = re.search(r'href="([^"]+)">查看本轮代码差异', page.read_text(encoding='utf-8'))[1]
        self.assertEqual((page.parent/link).resolve(), patch.resolve())
        self.assertTrue((page.parent/link).is_file())


if __name__ == '__main__':
    unittest.main()
