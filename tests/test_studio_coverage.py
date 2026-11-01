from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ecra.scan_store import EvidenceProvider,publish_scan
from ecra.report_package import sha256
from ecra.studio.coverage import CoverageService


class StudioCoverageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='ECRA coverage ');self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'scan.db'
        pointer=dict(kind='POINTER_DEREFERENCE',symbol_id='a',file='a.c',line=9)
        self.facts=dict(variables=[dict(symbol_id='a',name='g_a',static_classification='UNKNOWN',translation_units=['a.c']),
            dict(symbol_id='b',name='g_b',static_classification='SUSPECT',translation_units=['a.c','b.c'])],
            unknowns=[dict(kind='PARSE_FAILED',file='a.c',diagnostic='缺失头文件'*5000),pointer,pointer,
                dict(symbol_id='not-in-inventory',message='未提供kind'),dict(kind=dict(future=True)),42],
            translation_units=[dict(tu_id='TU-0',source_file='a.c',parse_status='FAILED',diagnostics=[dict(message='bad')]),
                dict(tu_id='TU-1',source_file='b.c',parse_status='PARSED'),
                dict(tu_id='TU-2',source_file='zero.c',parse_status='PARSED')])
        self.report=dict(analysis_status='INCOMPLETE',findings=[],coverage=dict(
            blocker_fanout=[dict(blocker_id='B1',kind='PARTIAL_PARSE_REGION',file='a.c',symbol_ids=['a','b'],
                blocker_fanout=2,relevance_proofs=[dict(symbol_id='a'),dict(symbol_id='b')]),
                dict(blocker_id='B2',kind='FUTURE_KIND',symbol_ids=['not-in-inventory'],blocker_fanout=1)],
            build_closure=dict(complete=False,missing_objects=['a.o']),excluded_sources=['Drivers/ignored.c']))

    def publish(self):
        publish_scan(self.path,self.facts,self.report,scan_id='coverage',project_id='p')
        return CoverageService(self.path)

    def test_raw_groups_retain_duplicates_unbound_and_unprojected_entries_without_full_load(self):
        query=self.publish();before=sha256(self.path)
        with patch.object(EvidenceProvider,'load',side_effect=AssertionError('whole evidence restore')):
            summary=query.summary();groups=query.groups(limit=2)
            self.assertEqual(summary['unknown_records'],5);self.assertEqual(summary['unprojected_unknowns'],1)
            self.assertEqual(summary['tu_records'],3);self.assertEqual(summary['unprojected_tus'],0)
            statuses={row['raw']:row['count'] for row in summary['tu_statuses']}
            self.assertEqual(statuses,dict(FAILED=1,PARSED=2))
            self.assertEqual(groups['total'],4)
            pointer=next(row for row in query.groups()['items'] if row['raw']=='POINTER_DEREFERENCE')
            self.assertEqual((pointer['records'],pointer['direct_symbols'],pointer['unbound_records']),(2,1,0))
            one=query.issues(kind_node=pointer['node'],limit=1)
            two=query.issues(kind_node=pointer['node'],offset=one['next_offset'],limit=1)
            self.assertEqual(one['total'],2);self.assertEqual(one['items'][0]['node'],two['items'][0]['node'])
            self.assertNotEqual(one['items'][0]['ordinal'],two['items'][0]['ordinal'])
            self.assertEqual(query.issues(missing_kind=True)['total'],1)
        self.assertEqual(sha256(self.path),before)

    def test_engine_blocker_symbol_lists_are_complete_paged_and_never_guess_missing_identities(self):
        query=self.publish();page=query.blockers(limit=1)
        self.assertEqual((page['total'],page['items'][0]['archived_symbol_ids_count']),(2,2))
        node=page['items'][0]['node']
        first=query.related(node,limit=1);second=query.related(node,offset=1,limit=1)
        self.assertEqual([first['items'][0]['symbol_id'],second['items'][0]['symbol_id']],['a','b'])
        self.assertTrue(first['items'][0]['available']);self.assertIsNone(second['next_offset'])
        missing=query.blockers(offset=1)['items'][0]
        self.assertFalse(query.related(missing['node'])['items'][0]['available'])
        with self.assertRaises(ValueError):query.related(EvidenceProvider(self.path).resolve('report'))

    def test_tus_include_zero_object_rows_and_use_explicit_origin_lists(self):
        query=self.publish();page=query.translation_units(limit=2)
        self.assertEqual(page['total'],3)
        self.assertEqual([row['associated_objects'] for row in page['items']],[2,1])
        zero=query.translation_units(zero_only=True)
        self.assertEqual(zero['total'],1);self.assertEqual(zero['items'][0]['summary']['source_file'],'zero.c')
        parsed=next(row['node'] for row in query.summary()['tu_statuses'] if row['raw']=='PARSED')
        self.assertEqual(query.translation_units(status_node=parsed)['total'],2)
        self.assertEqual(query.translation_units(search='zero')['total'],1)
        self.assertEqual(query.translation_units(search="' OR 1=1 --")['total'],0)

    def test_missing_origin_or_duplicate_compile_variants_disable_unproved_zero_filter(self):
        self.facts['variables'][0].pop('translation_units')
        self.facts['translation_units'].append(dict(tu_id='TU-3',source_file='a.c',parse_status='PARTIAL'))
        query=self.publish();summary=query.summary()
        self.assertFalse(summary['zero_filter_available'])
        self.assertEqual(summary['objects_without_tu_origin'],1);self.assertEqual(summary['ambiguous_tu_source_names'],1)
        with self.assertRaisesRegex(ValueError,'不能证明零关联对象'):
            query.translation_units(zero_only=True)
        self.assertEqual(query.translation_units()['total'],4)

    def test_missing_collections_are_explicit_and_long_diagnostics_keep_complete_node_refs(self):
        query=self.publish();issue=query.issues()['items'][0]
        self.assertNotIn('diagnostic',issue['summary'])
        self.assertGreater(issue['fields']['diagnostic']['total'],16384)
        self.assertEqual(EvidenceProvider(self.path).text(issue['fields']['diagnostic']['id'])['value'],
            ('缺失头文件'*5000)[:2730])
        other=Path(self.temp.name)/'minimal.db'
        publish_scan(other,dict(variables=[]),dict(findings=[]),scan_id='minimal',project_id='p')
        missing=CoverageService(other).summary()
        self.assertIsNone(missing['translation_units']);self.assertIsNone(missing['unprojected_tus'])
        self.assertFalse(missing['zero_filter_available']);self.assertFalse(CoverageService(other).blockers()['available'])

    def test_all_page_bounds_are_enforced(self):
        query=self.publish()
        for function in [query.groups,query.issues,query.blockers,query.translation_units]:
            with self.assertRaises(ValueError):function(limit=10000)

    def test_status_summary_is_bounded_and_does_not_label_future_states_safe(self):
        self.facts['translation_units'] += [dict(source_file=f'future-{i}.c',parse_status=f'FUTURE-{i}') for i in range(80)]
        self.facts['translation_units'].append(dict(source_file='future-safe.c',parse_status='SAFE_PROVEN'))
        query=self.publish();summary=query.summary()
        self.assertEqual(len(summary['tu_statuses']),50)
        self.assertEqual(summary['tu_status_types'],83)
        self.assertEqual({row['raw'] for row in summary['tu_statuses'][:2]},{'FAILED','PARSED'})
        self.assertEqual(query.translation_units()['total'],84)


if __name__=='__main__':unittest.main()
