"""Full projection equality without rebuilding millions of index rows."""
from contextlib import closing
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest

from ecra.scan_store import (
    EvidenceProvider, _project, _validate_projections, connect_readonly, publish_scan,
)


class StreamingProjectionValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ecra projection streams ')
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'scan.db'

    def publish(self, *, count=200):
        symbols = [dict(symbol_id='s'+str(i), name=True if i % 2 else 1.25,
                        definition_line=line, static_classification=False,
                        resource_kind=2.5, analysis_coverage=True)
                   for i, line in enumerate(['0010', '1.25', 'not-an-integer', True, None, -0.0])]
        values = [None, False, True, 0, -0.0, 3.141592653589793, 1e30, '', '函数', '0']
        calls = [None, 1, [], {}, {'symbol_id': ['not-an-id']}]
        calls += [dict(function_id=values[i % len(values)], symbol_id='s0',
                       caller_function_id=values[i % len(values)], caller='old', caller_id='old-id',
                       callee_function_id=values[(i+2) % len(values)], callee='', callee_id='fallback',
                       diagnostic='ignored-'*100)
                  for i in range(count)]
        facts = dict(variables=symbols, calls=calls, empty=[], scalar='not-a-relation',
                     ignored=[None, 1, [dict(symbol_id='nested')]])
        report = dict(findings=[dict(symbol_id='s0'), {}, None])
        publish_scan(self.path, facts, report, scan_id='scan', project_id='project')

    def test_exact_sqlite_affinity_and_legacy_alias_precedence_are_preserved(self):
        self.publish()
        original_graph = None
        for version in (1, 2, 3):
            with self.subTest(version=version):
                # Recreate the reference projections using the unchanged writer
                # for each protocol's caller/callee precedence.
                with sqlite3.connect(self.path) as conn:
                    conn.execute('PRAGMA user_version='+str(version))
                    conn.execute('DELETE FROM symbols')
                    conn.execute('DELETE FROM records')
                    for name, root in conn.execute('SELECT name,node FROM roots').fetchall():
                        if name in ('facts', 'report'):
                            _project(conn, name, root)
                before = hashlib.sha256(self.path.read_bytes()).hexdigest()
                events = []
                with closing(connect_readonly(self.path)) as conn:
                    _validate_projections(conn, progress=events.append)
                    self.assertEqual(events[-1]['completed'], conn.execute('SELECT count(*) FROM records').fetchone()[0])
                    self.assertEqual(events[-1]['total'], events[-1]['completed'])
                    graph = tuple(tuple(row) for row in conn.execute('SELECT name,n.hash FROM roots r JOIN nodes n ON n.id=r.node ORDER BY name'))
                if original_graph is None:
                    original_graph = graph
                self.assertEqual(graph, original_graph)
                self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), before)

    def test_checks_missing_extra_tail_and_unknown_relation_rows(self):
        self.publish(count=20)
        original = self.path.read_bytes()
        corruptions = [
            "DELETE FROM records WHERE dataset='facts' AND relation='calls' AND ordinal=5",
            "UPDATE records SET source_id='changed' WHERE dataset='facts' AND relation='calls' AND ordinal=24",
            "INSERT INTO records SELECT dataset,'phantom',ordinal,node,symbol_id,function_id,source_id,target_id FROM records WHERE relation='calls' LIMIT 1",
            "INSERT INTO records SELECT dataset,relation,999,node,symbol_id,function_id,source_id,target_id FROM records WHERE relation='calls' LIMIT 1",
            "DELETE FROM symbols WHERE ordinal=5",
            "UPDATE symbols SET definition_line='changed' WHERE ordinal=5",
            "INSERT INTO symbols SELECT 'extra',999,node,name,static_classification,resource_kind,definition_file,definition_line,analysis_coverage FROM symbols LIMIT 1",
        ]
        for sql in corruptions:
            with self.subTest(sql=sql):
                self.path.write_bytes(original)
                with sqlite3.connect(self.path) as conn:
                    conn.execute(sql)
                with closing(connect_readonly(self.path)) as conn:
                    with self.assertRaisesRegex(ValueError, '投影'):
                        _validate_projections(conn)

    def test_queries_scale_with_relations_not_records(self):
        facts = dict(variables=[], unknowns=[dict(code=i, symbol_id='same') for i in range(2000)])
        publish_scan(self.path, facts, dict(findings=[]), scan_id='scan', project_id='project')
        statements = []
        with closing(connect_readonly(self.path)) as conn:
            conn.set_trace_callback(statements.append)
            _validate_projections(conn)
        self.assertLess(len(statements), 30)
        EvidenceProvider(self.path).validate(deep=True)

    def test_empty_non_object_root_keeps_writer_compatibility(self):
        publish_scan(self.path, [[], [None]], [], scan_id='scan', project_id='project')
        EvidenceProvider(self.path).validate(deep=True)
