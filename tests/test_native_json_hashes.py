from contextlib import closing
import copy
import io
import json
from pathlib import Path
import random
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from ecra.scan_store import GraphWriter, SCHEMA
from ecra.shared_json import write
from scripts.compare_native_graphs import NormalizedGraph
from scripts.hash_native_json import JsonHashes, SCOPES, hash_file


class NativeJsonHashTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ecra-json-hash-')
        self.addCleanup(self.temp.cleanup); self.root = Path(self.temp.name); self.serial = 0

    def direct(self, text, **kwargs):
        self.serial += 1
        with JsonHashes(self.root/('direct-'+str(self.serial)), **kwargs) as hasher:
            return hasher.read(io.StringIO(text))

    def expected(self, value, scope):
        # The graph codec admits arbitrary roots; business projections require
        # a report object, so isolate the independent codec from those indexes.
        with closing(sqlite3.connect(':memory:')) as connection:
            connection.row_factory = sqlite3.Row
            connection.executescript(SCHEMA)
            node, _ = GraphWriter(connection).put(value)
            connection.execute('INSERT INTO roots VALUES (?,?)',('report',node))
            graph = NormalizedGraph(connection)
            return graph.hash(graph.root('report'), scope).lower()

    def shared(self, value):
        self.serial += 1; path = self.root/('shared-'+str(self.serial)+'.json')
        write(path,value,threshold=0)
        return path.read_text('utf-8')

    def test_all_scopes_match_independent_graph_for_plain_and_shared_json(self):
        shared = dict(read_started_ns=7,read_completed_ns=9,read_fake_ns=11,
                      status='DONE',review=dict(unsafe='preserve outside finding'),proof=[1,1,2])
        report = dict(generated_at='time',fingerprint='runtime',run_status='SAVED',
            findings=[shared,dict(status='FAILED',static_classification='UNKNOWN'),dict(proof=shared)],
            workspace=dict(results_root='output',project_root='firmware'),
            coverage=dict(consumed_inputs={'a.c':shared,'b.c':dict(size=1)}),
            arbitrary=shared)
        corpus = [report,shared,dict(findings=[],workspace={},coverage={}),[],[shared],
                  [False,0,1,-0.0,0.0,2**90,'中文\ud800',dict(b=2,a=1)]]
        for value in corpus:
            texts = [json.dumps(value,ensure_ascii=True)]
            try: texts.append(self.shared(value))
            except UnicodeEncodeError:
                # The original shared writer rejects literal surrogates; plain
                # escaped JSON still exercises their exact typed graph hash.
                pass
            for text in texts:
                actual = self.direct(text,cache_size=1,key_budget=2)
                for index, scope in enumerate(SCOPES):
                    with self.subTest(scope=scope, value=repr(value)[:50]):
                        try: expected = self.expected(value,scope)
                        except ValueError: self.assertIsNone(actual.hashes[index])
                        else: self.assertEqual(actual.hashes[index].hex(),expected)

    def test_random_nested_values_match_raw_typed_graph_without_sorting(self):
        def tree(rng, depth):
            if not depth: return rng.choice([None,True,False,0,1,2**75,-0.0,0.0,2.5,'中文','\udfff'])
            if rng.randrange(2): return [tree(rng,depth-1) for _ in range(rng.randrange(5))]
            return {key:tree(rng,depth-1) for key in rng.sample(['b','a','','read_fake_ns','status'],rng.randrange(6))}
        for seed in range(30):
            value = tree(random.Random(seed),3)
            actual = self.direct(json.dumps(value,ensure_ascii=True))
            self.assertEqual(actual.hashes[0].hex(),self.expected(value,'opaque'))

    def test_pool_references_beyond_cache_and_same_nodes_under_distinct_scopes(self):
        pool = [dict(status='DONE',review={'n':i},read_started_ns=i,read_fake_ns=i) for i in range(100)]
        value = dict(findings=pool,coverage=dict(consumed_inputs={str(i):row for i,row in enumerate(pool)}),
                     arbitrary=pool)
        text = self.shared(value)
        actual = self.direct(text,cache_size=2,key_budget=3)
        self.assertEqual(actual.hashes[0].hex(),self.expected(value,'opaque'))
        self.assertEqual(actual.hashes[1].hex(),self.expected(value,'report'))

    def test_raw_only_pool_retains_the_same_complete_ordered_facts_hash(self):
        rows = [dict(b=i,a=[True,1,-0.0]) for i in range(90)]
        value = dict(variables=[],future=rows,again=rows)
        for text in [json.dumps(value),self.shared(value)]:
            actual = self.direct(text,normalize=False,cache_size=1)
            self.assertEqual(actual.hashes[0].hex(),self.expected(value,'opaque'))

    def test_duplicate_keys_after_spill_bad_references_and_trailing_data_are_rejected(self):
        prefix = '{"_ecra_shared_json":1,"reference_key":"$r","pool":'
        cases = ['{"a":1,"b":2,"c":3,"a":4}', '[1,]', '{"a":NaN}', '{} false',
                 prefix+'[{"$r":0}],"value":{}}',
                 prefix+'[[]],"value":{"$r":true}}',
                 prefix+'[[]],"value":{"$r":0,"other":1}}',
                 prefix+'[[]],"value":{"$r":-1}}',
                 prefix+'[[]],"value":{"$r":1}}',
                 prefix+'[1],"value":{}}',
                 prefix+'[[],],"value":{}}']
        for text in cases:
            with self.subTest(text=text),self.assertRaises((ValueError,TypeError)):
                self.direct(text,key_budget=1)

    def test_report_shape_and_only_exact_normalization_paths_are_enforced(self):
        original = dict(findings=[dict(proof=dict(generated_at='static',order=[1,1,2]))],
                        coverage=dict(consumed_inputs={'a.c':dict(read_started_ns=1,read_fake_ns=2,size=3)}))
        expected = self.direct(json.dumps(original)).hashes[1]
        allowed = copy.deepcopy(original);allowed['coverage']['consumed_inputs']['a.c']['read_started_ns']=7
        allowed.update(generated_at='new',fingerprint='new')
        self.assertEqual(self.direct(json.dumps(allowed)).hashes[1],expected)
        for path, new in [(('findings',0,'proof','generated_at'),'changed'),
                          (('findings',0,'proof','order'),[1,2,1]),
                          (('coverage','consumed_inputs','a.c','read_fake_ns'),8),
                          (('coverage','consumed_inputs','a.c','size'),True)]:
            changed = copy.deepcopy(original);node=changed
            for part in path[:-1]:node=node[part]
            node[path[-1]]=new
            self.assertNotEqual(self.direct(json.dumps(changed)).hashes[1],expected)
        for bad in [{},dict(findings={}),dict(findings=[1]),dict(findings=[],workspace=[]),
                    dict(findings=[],coverage=dict(consumed_inputs=[]))]:
            self.assertIsNone(self.direct(json.dumps(bad)).hashes[1])

    def test_file_certificate_preserves_raw_bytes_mtime_and_full_hash(self):
        value=dict(findings=[],future=[True,1,-0.0,'中文'])
        path=self.root/'original.json';path.write_bytes(json.dumps(value,ensure_ascii=True).encode())
        before=(path.read_bytes(),path.stat().st_mtime_ns)
        receipt=hash_file(path,self.root/'file-work','report')
        self.assertTrue(receipt['inputs_unchanged'])
        self.assertEqual(receipt['normalized_hash'],self.expected(value,'report'))
        self.assertEqual((path.read_bytes(),path.stat().st_mtime_ns),before)

    def test_cli_refuses_comparison_outputs_in_original_tree_before_any_write(self):
        source=self.root/'original';source.mkdir()
        facts=source/'facts.json';facts.write_text('{"variables":[]}',encoding='utf-8')
        report=source/'report.json';report.write_text('{"findings":[]}',encoding='utf-8')
        before={p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in source.iterdir()}
        script=Path(__file__).resolve().parents[1]/'scripts/hash_native_json.py'
        result=subprocess.run([sys.executable,'-B','-X','utf8',str(script),'--facts',str(facts),
            '--report',str(report),'--work',str(source/'work'),'--receipt',str(self.root/'receipt.json')],
            stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        self.assertNotEqual(result.returncode,0)
        self.assertIn(b'outside original input trees',result.stdout)
        self.assertFalse((self.root/'receipt.json').exists())
        self.assertEqual({p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in source.iterdir()},before)


if __name__ == '__main__': unittest.main()
