import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from ecra.scan_store import EvidenceProvider, GraphWriter, publish_scan,SCHEMA


class ScanStoreTests(unittest.TestCase):
    def test_bound_immutable_roots_reuse_shared_graph_beyond_the_python_cache_without_changing_hashes(self):
        shared=dict(rows=[dict(shared_record=i,trace=['main','irq',i]) for i in range(180)])
        values=[('facts',dict(variables=[],first=shared,churn=[dict(churn=i) for i in range(200)],again=shared)),
            ('report',dict(findings=[],third=shared)),('provenance',{})]
        results=[];writes=[]
        for bound in [False,True]:
            with closing(sqlite3.connect(self.temp.name+('/bound.db' if bound else '/reference.db'))) as conn:
                conn.executescript(SCHEMA);conn.execute('PRAGMA temp_store=FILE')
                counter=[0]
                def trace(statement):
                    if statement.startswith('INSERT INTO edges VALUES'):counter[0]+=1
                conn.set_trace_callback(trace);writer=GraphWriter(conn,cache_size=4)
                roots=writer.put_roots(values) if bound else {name:writer.put(value) for name,value in values}
                results.append({name:row[1] for name,row in roots.items()});writes.append(counter[0])
                if bound:
                    self.assertIsNone(writer._roots)
                    self.assertEqual(conn.execute('SELECT count(*) FROM ecra_identity').fetchone()[0],0)
        self.assertEqual(results[0],results[1])
        # One repeated subtree is beyond the small Python cache; the next
        # reference happens while it is still cached even in the reference
        # writer. Count the actual repeated subtree rather than inventing a
        # percentage of unrelated root/churn work that must disappear.
        shared_edges=1+180+180*(2+3)
        self.assertGreaterEqual(writes[0]-writes[1],shared_edges,
            'The complete shared subtree must not be expanded again after cache eviction')

    def test_identity_scope_never_reuses_a_released_root_and_unknown_subclasses_keep_temporary_children_safe(self):
        class Generated(dict):
            def __len__(self):return 300
            def items(self):
                for i in range(300):yield str(i),dict(value=i)
        with sqlite3.connect(self.path) as conn:
            conn.executescript(SCHEMA);writer=GraphWriter(conn,cache_size=1)
            for value in range(400):
                node,_=writer.put_roots([('r',dict(value=value))])['r']
                raw=conn.execute("SELECT n.value FROM edges e JOIN nodes n ON n.id=e.child WHERE e.parent=? AND e.key='value'",(node,)).fetchone()[0]
                self.assertEqual(int(raw),value)
            node,_=writer.put_roots([('r',dict(generated=Generated()))])['r']
            generated=conn.execute("SELECT child FROM edges WHERE parent=? AND key='generated'",(node,)).fetchone()[0]
            for key,n in conn.execute('SELECT key,child FROM edges WHERE parent=? ORDER BY ordinal',(generated,)):
                raw=conn.execute("SELECT value FROM nodes WHERE id=(SELECT child FROM edges WHERE parent=? AND key='value')",(n,)).fetchone()[0]
                self.assertEqual(int(raw),int(key))

    def test_scalar_acceleration_is_bounded_and_keeps_boolean_integer_and_signed_zero_distinct(self):
        with sqlite3.connect(self.path) as conn:
            conn.executescript(SCHEMA);writer=GraphWriter(conn,cache_size=3)
            nodes=[writer.put(value)[0] for value in [True,1,-0.0,0.0]]
            self.assertEqual(len(set(nodes)),4)
            for value in range(80):writer.put(str(value))
            self.assertLessEqual(len(writer.scalars),3)
            self.assertEqual([writer.put(value)[0] for value in [True,1,-0.0,0.0]],nodes)

    def test_projection_validation_does_not_duplicate_graph_or_decode_unused_large_record_fields(self):
        from contextlib import contextmanager
        import tracemalloc
        from ecra.report_package import sha256
        provider=self.publish(dict(variables=[dict(symbol_id='s',name='s')],
            unknowns=[dict(symbol_id='s',kind='CAPACITY_FIXTURE',diagnostic='x'*(8*1024**2))]))
        before=sha256(self.path);source_bytes=self.path.stat().st_size;sizes=[]
        temporary=tempfile.TemporaryDirectory
        @contextmanager
        def measured_temporary(*args,**kwargs):
            with temporary(*args,**kwargs) as folder:
                yield folder
                sizes.extend(path.stat().st_size for path in Path(folder).rglob('*') if path.is_file())
        owned_trace=not tracemalloc.is_tracing()
        if owned_trace:tracemalloc.start(1)
        try:
            start=tracemalloc.get_traced_memory()[0]
            with patch('tempfile.TemporaryDirectory',measured_temporary):provider.validate(deep=True)
            peak=tracemalloc.get_traced_memory()[1]-start
        finally:
            if owned_trace:tracemalloc.stop()
        self.assertTrue(sizes)
        self.assertLess(max(sizes),source_bytes//4,'temporary validation must contain query projections, not complete source evidence')
        if owned_trace:self.assertLess(peak,7*1024**2,'unused diagnostic must not be decoded while projecting record identities')
        self.assertEqual(sha256(self.path),before)

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
