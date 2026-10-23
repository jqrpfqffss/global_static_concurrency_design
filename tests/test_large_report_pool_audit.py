"""Independent artifact validation must inspect complete encoded pointer pools."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from ecra.report import write_database
from scripts.validate_large_report import audit_fact_database, fact_values


class PoolAuditTests(unittest.TestCase):
    def audit(self, facts, mutate=None):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            path = folder / 'facts.json'
            path.write_text(json.dumps(facts), encoding='utf-8')
            write_database(folder / 'facts.db', facts, dict(findings=[]))
            with closing(sqlite3.connect(folder / 'facts.db')) as source, \
                    closing(sqlite3.connect(':memory:')) as index:
                if mutate:
                    mutate(source)
                return audit_fact_database(path, source, index)

    @staticmethod
    def facts(blocked=True):
        value = dict(accesses=[], variables=[dict(symbol_id='x')],
                     pointer_targets=[dict(location='slot', target_set_id='PTS-x', target_count=2)],
                     pointer_target_atoms=['obj:x', 'obj:y'],
                     pointer_target_encoding='INTERNED_BLOCK_BITMAP_V2' if blocked else 'INTERNED_BITMAP_V1',
                     pointer_target_sets={'PTS-x': [[0, '3']] if blocked else '3'})
        if blocked:
            value['pointer_target_block_bits'] = 4096
        return value

    def test_both_encodings_and_inline_schema(self):
        for blocked in (True, False):
            with self.subTest(blocked=blocked):
                result = self.audit(self.facts(blocked))
                self.assertEqual(result['differences'], {})
                self.assertEqual(result['pools']['error_count'], 0)
                self.assertEqual(result['pools']['atoms'], 2)
                self.assertEqual(result['pools']['sets'], 1)
        result = self.audit(dict(accesses=[], variables=[], pointer_targets=[dict(location='x', targets=['obj:x'])]))
        self.assertEqual(result['pools']['error_count'], 0)

    def test_atom_payload_cardinality_and_missing_pool_are_detected(self):
        mutations = [
            "UPDATE pointer_target_atoms SET target='obj:changed' WHERE target_index=1",
            "UPDATE pointer_target_sets SET data='[[0,\"1\"]]'",
            "UPDATE pointer_targets SET target_count=1",
            'DELETE FROM pointer_target_sets',
            'DROP TABLE pointer_target_sets',
        ]
        for sql in mutations:
            with self.subTest(sql=sql):
                result = self.audit(self.facts(), lambda source: source.execute(sql))
                self.assertGreater(result['pools']['error_count'], 0)

    def test_missing_ordinary_table_and_invalid_bitmap_are_detected(self):
        result = self.audit(self.facts(), lambda source: source.execute('DROP TABLE variables'))
        self.assertEqual(result['differences']['variables'], dict(json=1, sqlite=None))
        for encoded in ([[1, '1']], [[0, '1'], [0, '2']], [[-1, '1']], [[0, '0']]):
            facts = self.facts()
            facts['pointer_target_sets']['PTS-x'] = encoded
            result = self.audit(facts)
            self.assertIn('invalid_bitmap', {r['kind'] for r in result['pools']['errors']})

    def test_pool_entries_are_streamed_and_duplicate_keys_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'facts.json'
            path.write_text('{"pointer_target_sets":{"a":[[0,"1"]],"b":[[1,"2"]]},"x":[]}', encoding='utf-8')
            self.assertEqual(list(fact_values(path)), [
                ('pointer_target_sets', ('a', [[0, '1']]), False),
                ('pointer_target_sets', ('b', [[1, '2']]), False)])
            path.write_text('{"x":[],"x":[]}', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'repeated'):
                list(fact_values(path))

    def test_valid_pools_do_not_hide_incomplete_or_absent_solver_fixed_points(self):
        for complete in (True, False, None):
            with self.subTest(complete=complete):
                facts = self.facts()
                facts['points_to_stats'] = dict(complete=True,evaluations=10)
                if complete is not None:
                    facts['context_points_to_stats'] = dict(complete=complete,iterations=8)
                result = self.audit(facts)
                self.assertEqual(result['pools']['error_count'],0)
                self.assertEqual(result['solver_fixed_points_complete'],complete is True)
                self.assertEqual(result['solver_summaries']['points_to_stats']['evaluations'],10)


if __name__ == '__main__':
    unittest.main()
