import tempfile
import unittest
from pathlib import Path

from ecra.human_reviews import ReviewStore
from ecra.scan_store import EvidenceProvider,publish_scan
from ecra.scan_persistence import append_runtime
from ecra.studio.query import QueryService


class StudioFilterTests(unittest.TestCase):
    def test_empty_baseline_selection_does_not_open_or_validate_baseline(self):
        from unittest.mock import patch
        from ecra.diff_review import DiffReviewEvidence
        for baseline_rows in (None, [], [dict(symbol_id='excluded', impact_class='EXCLUDED')]):
            with self.subTest(baseline_rows=baseline_rows), tempfile.TemporaryDirectory() as folder:
                out = Path(folder)
                diff = dict(selected_symbol_ids=['current'], conservative_symbol_ids=[],
                    deleted_variables=[], baseline_only_variables=baseline_rows)
                if baseline_rows is None:
                    del diff['baseline_only_variables']
                publish_scan(out/'scan.db', dict(variables=[dict(symbol_id='current', name='current',
                    static_classification='SAFE_PROVEN')]), dict(findings=[], git_diff=diff),
                    scan_id='empty-base-selection', project_id='p')
                ReviewStore(out/'reviews.db', EvidenceProvider(out/'scan.db').metadata())
                query = QueryService(out)
                with patch.object(DiffReviewEvidence, 'baseline',
                                  side_effect=AssertionError('No selected baseline objects: do not read baseline')):
                    self.assertEqual(query.symbols(diff='changes')['total'], 1)
                    for scope in ('baseline', 'deleted'):
                        page = query.symbols(diff=scope)
                        self.assertEqual(page['total'], 0)
                        self.assertEqual(page['items'], [])
                        self.assertIsNone(page['next_offset'])

    def test_impact_partition_and_regional_gaps_are_paged_without_full_restore(self):
        from unittest.mock import patch
        from ecra.diff_impact import IMPACT_SCHEMA
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            rows = [dict(object_id=sid, symbol_id=sid, name=sid, impact_class=category,
                         evidence_side='current', container=False)
                    for sid, category in [('a', 'DEFINITE'), ('b', 'UNCERTAIN'), ('c', 'EXCLUDED')]]
            diff = dict(impact_schema=IMPACT_SCHEMA, object_accounting=rows,
                impact_counts=dict(DEFINITE=1, UNCERTAIN=1, EXCLUDED=1), identified_object_count=3,
                container_count=0, identified_objects_accounted=True, real_object_inventory_complete=False,
                selected_symbol_ids=['a', 'b'], definite_symbol_ids=['a'], conservative_symbol_ids=['b'],
                excluded_symbol_ids=['c'], regional_gaps=[dict(side='base', kind='EXTRACTION_REGION',
                    source_file='failed.c', parse_status='FAILED', unidentified_objects_possible=True)])
            facts = dict(variables=[dict(symbol_id=sid, name=sid, static_classification='UNKNOWN') for sid in 'abc'])
            publish_scan(out/'scan.db', facts, dict(findings=[], git_diff=diff), scan_id='diff', project_id='p')
            ReviewStore(out/'reviews.db', EvidenceProvider(out/'scan.db').metadata())
            with patch.object(EvidenceProvider, 'load', side_effect=AssertionError('must page evidence')):
                query = QueryService(out)
                summary = query.diff_summary()
                self.assertEqual(summary['impact_accounting_status'], 'AVAILABLE')
                self.assertEqual(summary['impact_counts'], diff['impact_counts'])
                self.assertEqual(summary['regional_gap_count'], 1)
                self.assertFalse(summary['real_object_inventory_complete'])
                first = query.diff_changes('accounting', limit=2)
                last = query.diff_changes('accounting', offset=first['next_offset'], limit=2)
                self.assertEqual([row['impact_class'] for row in first['items'] + last['items']],
                                 ['DEFINITE', 'UNCERTAIN', 'EXCLUDED'])
                self.assertEqual(query.diff_changes('regional_gaps')['items'][0]['source_file'], 'failed.c')
                for selection, expected in [('selected', 'ab'), ('direct', 'a'), ('conservative', 'b'), ('excluded', 'c')]:
                    self.assertEqual({row['symbol_id'] for row in query.symbols(diff=selection)['items']}, set(expected))

    def test_server_sorting_has_stable_pages_counts_and_independent_review_order(self):
        from ecra.report_package import sha256
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder)/'data/scans/sorted';out.mkdir(parents=True)
            facts=dict(variables=[dict(symbol_id=str(index),name=name,definition_file=file,definition_line=line,
                static_classification=kind) for index,name,file,line,kind in [
                (0,'same','b.c',3,'SAFE_PROVEN'),(1,'zeta','a.c',9,'UNKNOWN'),
                (2,'same','a.c',2,'SUSPECT'),(3,'alpha','a.c',2,'UNKNOWN')]])
            publish_scan(out/'scan.db',facts,dict(findings=[]),scan_id='sorted',project_id='p')
            provider=EvidenceProvider(out/'scan.db');store=ReviewStore(out/'reviews.db',provider.metadata())
            store.append('2',provider.fingerprint('2'),reviewer='声明',decision='CONFIRMED_RISK',expected_heads=[])
            before=sha256(out/'scan.db');query=QueryService(out)
            ids=lambda **options:[row['symbol_id'] for row in query.symbols(**options)['items']]
            self.assertEqual(ids(),['2','1','3','0'])
            self.assertEqual(ids(sort='name'),['3','0','2','1'])
            self.assertEqual(ids(sort='name',order='desc'),['1','0','2','3'])
            self.assertEqual(ids(sort='definition'),['2','3','1','0'])
            # No-signature static-safe variables are not human todos.
            self.assertEqual(ids(sort='review_priority'),['1','3','2','0'])
            first=query.symbols(sort='name',limit=2);second=query.symbols(sort='name',limit=2,offset=first['next_offset'])
            self.assertEqual([row['symbol_id'] for row in first['items']+second['items']],['3','0','2','1'])
            self.assertEqual(first['total'],second['total']);self.assertIsNone(second['next_offset'])
            self.assertEqual(ids(sort='definition',classification='UNKNOWN'),['3','1'])
            for options in [dict(sort='name; DROP TABLE symbols'),dict(order='desc;--'),dict(sort='unknown')]:
                with self.assertRaises(ValueError):query.symbols(**options)
            self.assertEqual(sha256(out/'scan.db'),before)

    def test_combined_filters_use_same_identity_and_independent_latest_decisions(self):
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder)/'data/scans/s1';out.mkdir(parents=True)
            facts=dict(variables=[dict(symbol_id=s,name=s,definition_file=file,static_classification='UNKNOWN',analysis_coverage=coverage)
                for s,file,coverage in [('x','a.c','PARTIAL'),('y','b.c','COMPLETE')]],
                accesses=[dict(symbol_id='x',function_id='main',contexts=['main','irq']),dict(symbol_id='y',function_id='worker',contexts=['irq'])])
            report=dict(findings=[dict(symbol_id=s,finding_id='f'+s) for s in ('x','y')],
                git_diff=dict(selected_symbol_ids=['x','y'],conservative_symbol_ids=['y'],pin=dict(base_ref='base',current_ref='HEAD'),impact_coverage='CONSERVATIVE'))
            publish_scan(out/'scan.db',facts,report,scan_id='s1',project_id='p')
            provider=EvidenceProvider(out/'scan.db');store=ReviewStore(out/'reviews.db',provider.metadata())
            store.append('x',provider.fingerprint('x'),reviewer='声明',decision='CONFIRMED_RISK',handling_status='FIXING',comment='待修复')
            append_runtime(out,report,[dict(finding_id='fx',state='TECH_FAILED'),dict(finding_id='fy',state='DONE')])
            query=QueryService(out)
            all_filters=dict(file='a.c',function='main',context='main',coverage='PARTIAL',classification='UNKNOWN',
                human_decision='CONFIRMED_RISK',handling_status='FIXING',ai_state='TECH_FAILED',diff='direct')
            self.assertEqual([row['symbol_id'] for row in query.symbols(**all_filters)['items']],['x'])
            for key,value in [('file','b.c'),('function','worker'),('context','unresolved'),('ai_state','DONE'),('diff','conservative'),('handling_status','CLOSED')]:
                changed=dict(all_filters,**{key:value});self.assertEqual(query.symbols(**changed)['total'],0,key)
            self.assertEqual(query.symbols(ai_state='DONE')['items'][0]['symbol_id'],'y')
            append_runtime(out,report,[dict(finding_id='fx',state='DONE'),dict(finding_id='fy',state='DONE')])
            self.assertEqual(query.symbols(ai_state='TECH_FAILED')['total'],0)
            self.assertEqual(query.symbols(ai_state='DONE')['total'],2)
            self.assertEqual(query.symbols(context="irq' OR 1=1 --")['total'],0)
            summary = query.diff_summary()
            self.assertEqual(summary['risk_comparison_status'], 'LEGACY_EVIDENCE')
            self.assertIn('旧变化标签', summary['risk_comparison_note'])
            self.assertEqual(summary['conservative_symbol_ids_count'], 1)
            self.assertNotIn('file_count', summary)
            self.assertNotIn('deleted_variable_count', summary)

    def test_diff_summary_and_pages_include_base_only_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            files = [dict(status='R100', old_path='old.c', new_path='new.c'),
                     dict(status='D', old_path='gone.c', new_path='gone.c')]
            diff = dict(pin=dict(base_ref='base', current_ref='feature', files=files),
                        selected_symbol_ids=[], conservative_symbol_ids=[],
                        deleted_variables=[dict(symbol_id='gone', name='deleted_variable', impact={})],
                        fallback_reasons=['构建输入变化'])
            publish_scan(out/'scan.db', dict(variables=[]), dict(findings=[], git_diff=diff),
                         scan_id='diff', project_id='p')
            query = QueryService(out)
            summary = query.diff_summary()
            self.assertEqual(summary['pin'], dict(base_ref='base', current_ref='feature'))
            self.assertEqual(summary['file_count'], 2)
            self.assertEqual(summary['deleted_variable_count'], 1)
            self.assertEqual(summary['selected_symbol_ids_count'], 0)
            self.assertEqual(summary['fallback_reasons'], ['构建输入变化'])
            first = query.diff_changes('files', limit=1)
            second = query.diff_changes('files', offset=first['next_offset'], limit=1)
            self.assertEqual(first['items'][0]['old_path'], 'old.c')
            self.assertEqual(first['items'][0]['new_path'], 'new.c')
            self.assertEqual(second['items'][0]['status'], 'D')
            self.assertIsNone(second['next_offset'])
            deleted = query.diff_changes('deleted')['items'][0]
            self.assertEqual(deleted['name'], 'deleted_variable')
            self.assertEqual(deleted['node'], query.evidence.resolve('report', ['git_diff', 'deleted_variables', 0]))
            with self.assertRaises(ValueError):
                query.diff_changes('unsupported')

    def test_comparison_counts_and_unobserved_baseline_rows_survive_native_pages(self):
        from unittest.mock import patch
        from ecra.diff_risk import COMPARISON_SCHEMA
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            counts = dict(basis='SELECTED_DIFF_OBJECTS', transitions={'SUSPECT_DISCOVERED': 1},
                objects={'EXISTENCE_UNCERTAIN': 1}, counts_as_new_risk=0, counts_as_risk_resolution=0,
                current_suspect=1, prior_risk_unclosed=1)
            diff = dict(comparison_schema=COMPARISON_SCHEMA, change_counts=counts,
                selected_symbol_ids=[], deleted_variables=[], baseline_only_variables=[
                    dict(symbol_id='missing', name='maybe_present', impact=dict(
                        object_change=dict(event='EXISTENCE_UNCERTAIN')))])
            publish_scan(out/'scan.db', dict(variables=[]), dict(findings=[], git_diff=diff),
                         scan_id='diff', project_id='p')
            with patch.object(EvidenceProvider, 'load', side_effect=AssertionError('UI must page evidence')):
                query = QueryService(out)
                summary = query.diff_summary()
                self.assertEqual(summary['risk_comparison_status'], 'AVAILABLE')
                self.assertEqual(summary['change_counts'], counts)
                self.assertEqual(summary['deleted_variable_count'], 0)
                self.assertEqual(summary['baseline_only_variable_count'], 1)
                page = query.diff_changes('baseline_only', limit=1)
                self.assertEqual(page['items'][0]['symbol_id'], 'missing')
                self.assertIsNone(page['next_offset'])
