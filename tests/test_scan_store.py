import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from ecra.scan_store import EvidenceProvider, GraphWriter, publish_scan


class ScanStoreTests(unittest.TestCase):
    def test_engine_tuple_arrays_and_shared_restore_preserve_json_contract(self):
        shared = {'all_edges': [1, 2, 2, {'name': '中文'}]}
        provider = self.publish(dict(variables=[], repeated=(shared, shared)))
        restored = provider.load('facts')
        self.assertEqual(json.dumps(restored,ensure_ascii=False), json.dumps(self.facts,ensure_ascii=False))
        self.assertIs(restored['repeated'][0], restored['repeated'][1])
        self.assertEqual(provider.load('facts', ['repeated',1,'all_edges']), [1,2,2,{'name':'中文'}])
        node = provider.resolve('facts',['repeated',0,'all_edges',3,'name'])
        self.assertEqual(provider.node(node)['value'],'中文')

    def test_actual_engine_call_ids_are_indexed_and_v1_projection_remains_valid(self):
        provider = self.publish(dict(variables=[], calls=[dict(caller_function_id='main',callee_function_id='callee')]))
        self.assertEqual(provider.records('calls',source_id='main')['total'],1)
        self.assertEqual(provider.records('calls',target_id='callee')['total'],1)
        with sqlite3.connect(self.path) as conn:
            conn.execute('UPDATE records SET source_id=NULL,target_id=NULL')
            conn.execute('PRAGMA user_version=1')
        provider.validate(deep=True)
        self.assertEqual(provider.load('facts'),self.facts)

    def test_source_navigation_uses_archived_text_without_live_file_reads(self):
        publish_scan(self.path,dict(variables=[]),dict(findings=[]),scan_id='source',project_id='p',
            provenance=dict(archived_sources=[dict(file='main.c',text='int archived_value;')]))
        provider=EvidenceProvider(self.path)
        with patch.object(Path,'read_bytes',side_effect=AssertionError('live source read forbidden')):
            reference=provider.archived_source('main.c')
            self.assertTrue(reference['available'])
            self.assertEqual(provider.node(reference['text_node'])['value'],'int archived_value;')
            self.assertFalse(provider.archived_source('../../Windows/win.ini')['available'])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ecra 静态证据 ')
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'scan.db'

    def publish(self, facts=None, report=None):
        self.facts = facts if facts is not None else dict(variables=[
            dict(symbol_id='file-static::a::state', qualified_name='state', static_classification='SUSPECT'),
            dict(symbol_id='file-static::b::state', qualified_name='state', static_classification='UNKNOWN')],
            accesses=[dict(symbol_id='file-static::a::state', access_kind='RMW', function_id='main')],
            calls=[dict(caller='main', callee='callback')])
        self.report = report if report is not None else dict(findings=[dict(finding_id='f1', symbol_id='file-static::a::state')])
        publish_scan(self.path, self.facts, self.report, scan_id='s1', project_id='p1')
        return EvidenceProvider(self.path)

    def test_all_fields_types_order_duplicates_and_signed_zero_survive(self):
        values = [None, False, True, 0, 1, -0.0, 0.0, 1.25, 10**80, '', '中文😀', {'b': 1, 'a': 2}]
        facts = dict(variables=[], future={'order': values + values, 'nested': [[{'new': 'field'}]]})
        provider = self.publish(facts, dict(findings=[], future=values))
        restored = provider.load('facts')
        self.assertEqual(json.dumps(restored, ensure_ascii=False), json.dumps(facts, ensure_ascii=False))
        self.assertEqual(provider.load('report'), self.report)
        self.assertEqual(provider.validate(deep=True)['state'], 'UNVERIFIED')

    def test_equal_containers_deduplicate_but_multiplicity_and_order_stay(self):
        provider = self.publish(dict(variables=[], repeated=[{'x': [1, 1, 2]}, {'x': [1, 1, 2]}, {'x': [2, 1, 1]}]))
        with sqlite3.connect(self.path) as conn:
            hashes = list(conn.execute("SELECT hash FROM nodes WHERE kind='object'"))
            self.assertEqual(len(hashes), len(set(hashes)))
        self.assertEqual(provider.load('facts'), self.facts)
        provider.validate(deep=True)

    def test_indexed_symbol_access_call_queries_never_load_whole_facts(self):
        provider = self.publish()
        with patch.object(provider, 'load', side_effect=AssertionError('no full load')):
            self.assertEqual(provider.symbols(search='state', limit=1)['total'], 2)
            self.assertEqual(provider.symbols(classification='UNKNOWN')['items'][0]['symbol_id'], 'file-static::b::state')
            page = provider.records('accesses', symbol_id='file-static::a::state')
            self.assertEqual(page['total'], 1)
            self.assertEqual(provider.records('calls', source_id='main')['total'], 1)
            self.assertEqual(provider.counts(), dict(SUSPECT=1, UNKNOWN=1))

    def test_every_edge_can_be_paged_with_totals_and_references(self):
        provider = self.publish(dict(variables=[], values=list(range(207))))
        root = next(x for x in provider.roots() if x['name'] == 'facts')
        fields = provider.node(root['id'])['items']
        node = next(x['id'] for x in fields if x['key'] == 'values')
        page, values = provider.node(node, limit=31), []
        while True:
            values.extend(x['value'] for x in page['items'])
            self.assertEqual(page['total'], 207)
            if page['next_offset'] is None:
                break
            page = provider.node(node, offset=page['next_offset'], limit=31)
        self.assertEqual(values, list(range(207)))

    def test_twenty_thousand_symbols_use_bounded_pages(self):
        provider = self.publish(dict(variables=[dict(symbol_id=str(i), name='g'+str(i), static_classification='UNKNOWN') for i in range(20007)]))
        page = provider.symbols(offset=20000, limit=50)
        self.assertEqual(page['total'], 20007)
        self.assertEqual(len(page['items']), 7)
        self.assertIsNone(page['next_offset'])
        with self.assertRaises(ValueError):
            provider.symbols(limit=20007)

    def test_publish_failure_does_not_leave_an_archive_or_touch_existing(self):
        with patch.object(GraphWriter, 'put', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.publish()
        self.assertFalse(self.path.exists())
        self.assertEqual(list(self.path.parent.glob('*.pending')), [])
        self.publish()
        original = self.path.read_bytes()
        with self.assertRaises(FileExistsError):
            self.publish()
        self.assertEqual(self.path.read_bytes(), original)

    def test_corruption_of_evidence_and_projection_is_rejected(self):
        provider = self.publish()
        with sqlite3.connect(self.path) as conn:
            conn.execute("UPDATE symbols SET static_classification='SAFE_PROVEN'")
        with self.assertRaisesRegex(ValueError, '投影'):
            provider.validate(deep=True)

    def test_corruption_of_root_hash_is_rejected(self):
        provider = self.publish()
        with sqlite3.connect(self.path) as conn:
            conn.execute("UPDATE scans SET facts_hash='tampered'")
        with self.assertRaisesRegex(ValueError, '权威根'):
            provider.validate(deep=True)

    def test_new_evidence_changes_fingerprint_even_with_same_name(self):
        provider = self.publish()
        old = provider.fingerprint('file-static::a::state')
        second = self.path.with_name('second.db')
        self.facts['accesses'][0]['access_kind'] = 'WRITE'
        publish_scan(second, self.facts, self.report, scan_id='s2', project_id='p1')
        self.assertNotEqual(EvidenceProvider(second).fingerprint('file-static::a::state'), old)

    def test_large_text_has_explicit_complete_segments(self):
        value = '中文证据😀\x00\n'*6000
        provider = self.publish(dict(variables=[], source=value))
        root = next(x for x in provider.roots() if x['name'] == 'facts')
        item = next(x for x in provider.node(root['id'])['items'] if x['key'] == 'source')
        self.assertIsNone(item['value'])
        parts, offset = [], 0
        while True:
            page = provider.text(item['id'], offset=offset)
            parts.append(page['value'])
            offset = page['next_offset']
            if offset is None:
                break
        self.assertEqual(''.join(parts), value)


if __name__ == '__main__':
    unittest.main()
