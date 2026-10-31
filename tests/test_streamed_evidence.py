from contextlib import closing
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from ecra.scan_store import EvidenceProvider, GraphWriter, publish_scan, publish_json_scan, SCHEMA
from ecra.streamed_evidence import StreamedGraph
from ecra import shared_json


class StreamedEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ECRA legacy JSON ')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        access = dict(symbol_id='s', function_id='irq', access_kind='RMW', contexts=['irq','irq'],
            evidence=[None, True, 1, 1.0, -0.0, '\u4e2d\u6587\U0001f600', {}, []])
        self.facts = dict(variables=[dict(symbol_id='s', name='中文变量', static_classification='UNKNOWN')],
            accesses=[access, access], calls=[dict(caller_function_id='main', callee_function_id='irq')],
            extra=dict(z=False,a=[['same','same'],[2,1,2]],n=2**100), empty=[], tiny='')
        self.report = dict(findings=[dict(finding_id='f',symbol_id='s',reason='不得丢失')],
            extra=[self.facts['accesses'], dict(保留='有序字段', repeated=access)])

    def compare(self, shared):
        for name, value in [('facts', self.facts), ('report', self.report)]:
            shared_json.write(self.base/(name+'.json'), value, threshold=0 if shared else 2**63)
        expected = publish_scan(self.base/'object.db', self.facts, self.report, scan_id='s', project_id='p',
            validation_state='LEGACY_READ_ONLY')
        # Whole-file JSON restoration is forbidden in this path. Scalars still
        # use the standard JSON raw decoder, with its original float semantics.
        with patch('json.load', side_effect=AssertionError('whole-file read')):
            actual = publish_json_scan(self.base/'stream.db', self.base/'facts.json', self.base/'report.json',
                scan_id='s', project_id='p')
        self.assertEqual({k:v[1] for k,v in expected.items()}, {k:v[1] for k,v in actual.items()})
        evidence = EvidenceProvider(self.base/'stream.db')
        evidence.validate(deep=True)
        from scripts.validate_studio_baseline import strict_difference
        self.assertIsNone(strict_difference(evidence.load('facts'), self.facts))
        self.assertIsNone(strict_difference(evidence.load('report'), self.report))
        with closing(sqlite3.connect(self.base/'stream.db')) as conn:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
            self.assertNotIn('json_pool', tables)
            self.assertNotIn('json_keys', tables)
            self.assertEqual(conn.execute('SELECT count(*) FROM records WHERE relation=\'accesses\'').fetchone()[0], 2)

    def test_plain_json_has_identical_typed_ordered_roots_and_projections(self):
        self.compare(False)

    def test_shared_json_uses_disk_pool_without_expanding_shared_subtrees(self):
        self.compare(True)

    def read_raw(self, raw):
        with closing(sqlite3.connect(':memory:')) as conn:
            conn.executescript(SCHEMA)
            return StreamedGraph(GraphWriter(conn)).read(io.StringIO(raw))

    def test_malformed_and_lossy_inputs_are_rejected(self):
        for value in ['{"a":1,"a":2}', '[1,]', '{"a":1,}', '[] trailing', '[NaN]', '[Infinity]',
                '{"_ecra_shared_json":1,"reference_key":"@","pool":[{"@":0}],"value":{}}',
                '{"_ecra_shared_json":1,"reference_key":"@","pool":[[]],"value":{"@":true}}',
                '{"_ecra_shared_json":1,"reference_key":"@","pool":[[]],"value":{"@":0,"extra":2}}']:
            with self.subTest(value=value), self.assertRaises((ValueError, TypeError)):
                self.read_raw(value)

    def test_number_token_at_chunk_boundary_and_unicode_surrogates_are_exact(self):
        # Reader's default 64KiB boundary lands inside the exponent token.
        raw='['+' '*65533+'1e3,"\\ud800",-0.0,true,1]'
        with closing(sqlite3.connect(':memory:')) as conn:
            conn.executescript(SCHEMA)
            writer=GraphWriter(conn)
            original=writer.put(json.loads(raw))
            result=StreamedGraph(writer).read(io.StringIO(raw))
            self.assertEqual(original[1],result[1])

    def test_failed_import_cannot_publish_or_replace_a_valid_database(self):
        facts=self.base/'facts.json'; report=self.base/'report.json'
        facts.write_text('{"variables":[]}',encoding='utf-8')
        report.write_text('{"findings":[',encoding='utf-8')
        target=self.base/'scan.db'
        with self.assertRaises(ValueError):
            publish_json_scan(target,facts,report,scan_id='s',project_id='p')
        self.assertFalse(target.exists());self.assertEqual(list(self.base.glob('*.pending')),[])
        publish_scan(target,{}, {},scan_id='valid',project_id='p')
        before=target.read_bytes()
        with self.assertRaises(FileExistsError):
            publish_json_scan(target,facts,report,scan_id='s',project_id='p')
        self.assertEqual(target.read_bytes(),before)

    def test_shared_codec_back_references_retain_duplicate_edges_and_boolean_types(self):
        raw='{"_ecra_shared_json":1,"reference_key":"@","pool":[[true,1],[{"@":0},{"@":0}]],"value":{"array":{"@":1},"other":{"@":0}}}'
        with closing(sqlite3.connect(':memory:')) as conn:
            conn.executescript(SCHEMA)
            writer=GraphWriter(conn)
            self.assertEqual(StreamedGraph(writer).read(io.StringIO(raw))[1],
                writer.put(dict(array=[[True,1],[True,1]],other=[True,1]))[1])

    def test_unicode_text_can_be_paged_forwards_and_backwards_without_expansion(self):
        value='中文😀abc'*9000
        path=self.base/'text.db'
        publish_scan(path,dict(text=value),{},scan_id='text',project_id='p')
        provider=EvidenceProvider(path);node=provider.resolve('facts',['text'])
        offset=0;parts=[]
        while True:
            page=provider.text(node,offset=offset,limit=8192);parts.append(page['value'])
            if offset:
                previous=provider.text(node,offset=page['previous_offset'],limit=8192)
                self.assertLess(previous['offset'],offset)
                self.assertEqual(previous['next_offset'],offset)
            if page['next_offset'] is None:break
            offset=page['next_offset']
        self.assertEqual(''.join(parts),value)


if __name__ == '__main__':
    unittest.main()
