import json
import math
import random
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from ecra.shared_json import Plan, read, write


class SharedJsonTests(unittest.TestCase):
    def test_public_readers_and_streamed_rows_return_the_original_schema(self):
        from ecra.common import read_json
        from ecra.workflow import read_saved_json
        from ecra.json_rows import rows
        row = dict(access_id='A', symbol_id='g', access_kind='READ', function_id='f', file='a.c', offset=1)
        source = dict(accesses=[row], variables=[dict(symbol_id='g', accesses=[row])], metadata=True)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'facts.json';write(path, source, threshold=0)
            self.assertEqual(read_json(path), source)
            actual = read_saved_json(path, canonical_accesses=True)
            self.assertEqual(actual, source)
            self.assertIs(actual['accesses'][0], actual['variables'][0]['accesses'][0])
            streamed = list(rows(path, chunk_size=3))
        self.assertEqual(streamed, [('accesses', row, True), ('variables', source['variables'][0], True),
                                    ('metadata', True, False)])

    def test_sqlite_cells_restore_all_pool_values(self):
        import sqlite3
        from ecra.report import write_database
        from ecra.shared_json import DatabasePool
        access = dict(access_id='A', symbol_id='g', access_kind='READ', function_id='f', contexts=['MAIN'])
        source = dict(accesses=[access], variables=[dict(symbol_id='g', accesses=[access])])
        report = dict(findings=[dict(finding_id='F', accesses=[access])])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'facts.db';write_database(path, source, report, shared_threshold=0)
            with closing(sqlite3.connect(path)) as connection:
                pool = DatabasePool(connection)
                for table in ('variables', 'findings'):
                    value = connection.execute('SELECT accesses FROM '+table).fetchone()[0]
                    self.assertEqual(pool.loads(value), [access])
                self.assertEqual(connection.execute('SELECT count(*) FROM accesses').fetchone()[0], 1)

    def test_equal_distinct_records_share_without_collapsing_scalar_types(self):
        source = [dict(v=[True, -0.0]), dict(v=[True, -0.0]), dict(v=[1, 0.0])]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'facts.json';write(path, source, threshold=0);actual = read(path)
        self.assertEqual(actual, source)
        self.assertIs(actual[0], actual[1])
        self.assertIsNot(actual[0], actual[2])

    def test_logical_digest_is_independent_of_aliases_and_detects_hidden_changes(self):
        from ecra.shared_json import logical_digest
        row = dict(duplicate=['A', 'A'], value=True)
        aliased = [row, row]
        copied = json.loads(json.dumps(aliased))
        self.assertEqual(logical_digest(aliased), logical_digest(copied))
        copied[1]['value'] = 1
        self.assertNotEqual(logical_digest(aliased), logical_digest(copied))

    def test_roundtrip_retains_types_order_duplicates_and_shared_evidence(self):
        row = dict(symbol_id='中文 静态', values=[True, 1, -0.0, None, '"\\\n'])
        source = dict(variables=[row, row], accesses=[row], other=[[], {}, [row, row]])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'facts.json'
            write(path, source, threshold=0)
            actual = read(path)
        self.assertEqual(actual, source)
        self.assertIs(actual['variables'][0], actual['accesses'][0])
        self.assertIs(actual['variables'][0], actual['variables'][1])
        self.assertIs(type(actual['accesses'][0]['values'][0]), bool)
        self.assertIs(type(actual['accesses'][0]['values'][1]), int)
        self.assertLess(math.copysign(1, actual['accesses'][0]['values'][2]), 0)
        self.assertEqual(list(actual), list(source))

    def test_reference_marker_cannot_collide_with_source_fields(self):
        node = {'$ecra_ref': 0, '$ecra_ref_': {'$ecra_ref': '源字段'}}
        source = [node, node]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'inventory.json'
            write(path, source, threshold=0)
            self.assertEqual(read(path), source)

    def test_rejects_missing_forward_boolean_and_extra_field_references(self):
        for bad in ({'$ecra_ref': 0}, {'$ecra_ref': True}, {'$ecra_ref': -1},
                    {'$ecra_ref': 0, 'hidden': '证据'}):
            with self.subTest(bad=bad), tempfile.TemporaryDirectory() as folder:
                path = Path(folder)/'broken.json'
                path.write_text(json.dumps(dict(_ecra_shared_json=1, reference_key='$ecra_ref',
                                               pool=[bad], value=None), separators=(',', ':')), encoding='utf-8')
                with self.assertRaises(ValueError):
                    read(path)

    def test_cycles_fail_before_replacing_a_valid_file(self):
        value = [];value.append(value)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'valid.json';path.write_text('旧的有效文件', encoding='utf-8')
            with self.assertRaises(ValueError):
                write(path, value, threshold=0)
            self.assertEqual(path.read_text(encoding='utf-8'), '旧的有效文件')

    def test_public_readers_reject_unsupported_codec_versions(self):
        from ecra.workflow import read_saved_json
        from ecra.common import read_json
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'future.json'
            path.write_text('{"_ecra_shared_json":2,"pool":[],"value":{}}', encoding='utf-8')
            for load in (read_json, read_saved_json):
                with self.assertRaises(ValueError):load(path)

    def test_complete_large_sources_are_written_once(self):
        ids = [f'A-{i:07}-'+'来源'*8 for i in range(3000)]
        source = dict(evidence=[dict(coherence_id=f'MC-{i}', writer_access_ids=ids,
                                     reader_access_ids=ids) for i in range(120)])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'large.json';write(path, source, threshold=0)
            actual = read(path)
            self.assertLess(path.stat().st_size, len(json.dumps(ids, ensure_ascii=False).encode('utf-8'))*2)
        self.assertEqual(actual, source)
        self.assertEqual(len(actual['evidence']), 120)
        self.assertEqual(actual['evidence'][-1]['reader_access_ids'], ids)

    def test_random_graphs_match_plain_json_values(self):
        for seed in range(100):
            rng = random.Random(seed)
            nodes = [[], {}, [True, False, None, -0.0, '中文']]
            for i in range(40):
                children = [rng.choice(nodes) for _ in range(rng.randrange(4))]
                nodes.append(children if rng.randrange(2) else {str(k): v for k, v in enumerate(children)})
            source = nodes[-6:]
            with self.subTest(seed=seed), tempfile.TemporaryDirectory() as folder:
                path = Path(folder)/'graph.json';write(path, source, threshold=0)
                self.assertEqual(read(path), json.loads(json.dumps(source)))

    def test_plan_releases_transient_graph_without_cyclic_gc(self):
        import gc
        import weakref
        from ecra.shared_json import Plan
        class Root(list):pass
        root=Root([dict(index=i, values=['完整来源']*8) for i in range(3000)])
        tracked=weakref.ref(root)
        enabled=gc.isenabled();gc.disable()
        try:
            plan=Plan(root)
            del root
            self.assertIsNone(tracked(), '计划构建的递归闭包不得保留完整输入和临时签名')
            del plan
        finally:
            if enabled:gc.enable()

    def test_all_signature_hash_collisions_still_compare_complete_typed_values(self):
        from unittest.mock import patch
        source = [dict(v=[True, -0.0]), dict(v=[1, 0.0]), dict(v=[True, -0.0]),
                  dict(a=1, b=2), dict(b=2, a=1), [None], (None,),
                  dict(v=[False, -0.0]), dict(v=[True, 0.0])]
        with tempfile.TemporaryDirectory() as folder, patch('ecra.shared_json._signature_hash', return_value=0):
            path=Path(folder)/'collisions.json'
            write(path, source, threshold=0)
            actual=read(path)
        self.assertEqual(actual, json.loads(json.dumps(source)))
        self.assertIs(actual[0],actual[2])
        self.assertIsNot(actual[0],actual[1])
        self.assertIsNot(actual[0],actual[7])
        self.assertIsNot(actual[0],actual[8])
        self.assertIs(actual[5],actual[6])
        self.assertEqual(list(actual[3]),['a','b'])
        self.assertEqual(list(actual[4]),['b','a'])

    def test_plan_retains_complete_references_without_duplicate_signature_graph(self):
        import tracemalloc
        source=[dict(index=i, values=[i,True,'完整来源']) for i in range(30000)]
        tracemalloc.start()
        try:
            plan=Plan(source)
            current,peak=tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        # The previous retained typed-child signature graph used >30 MiB for
        # this fixture. This bound covers indexing overhead, not input facts.
        self.assertLess(peak,30*1024*1024)
        self.assertEqual(len(plan.references),0)
        self.assertEqual(plan.logical_bytes,len(json.dumps(source,ensure_ascii=False,separators=(',',':')).encode('utf-8')))

    def test_merkle_memo_does_not_accumulate_between_digests(self):
        import gc
        import tracemalloc
        from ecra.shared_json import logical_digest
        source=[dict(index=i,values=['A','B',i]) for i in range(6000)]
        expected=logical_digest(source)
        enabled=gc.isenabled();gc.disable();tracemalloc.start()
        try:
            for _ in range(8):self.assertEqual(logical_digest(source),expected)
            current,_=tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
            if enabled:gc.enable()
        self.assertLess(current,1024*1024)


if __name__ == '__main__':
    unittest.main()
