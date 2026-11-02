import copy
import gc
import hashlib
import importlib.util
import json
from pathlib import Path
import random
import tracemalloc
import unittest
from unittest.mock import patch

from ecra.analysis import merge
from ecra.cfg_sharing import ReadOnlyGraphPool


REFERENCE = Path(__file__).parent/'fixtures/v21_merge.py'
spec = importlib.util.spec_from_file_location('ecra._merge_allocation_reference', REFERENCE)
reference = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reference)


def encoded(value):
    return json.dumps(value, ensure_ascii=True, separators=(',', ':'))


def parts(count=20):
    templates = [[dict(id=i, op='entry' if i == 0 else 'assign', successors=[i+1] if i < 9 else [],
        file='头文件.h', line=i+1, offset=i*10, end_offset=i*10+9,
        value=dict(constant=(i+variant) % 5), future=dict(values=[True, 1, -0.0, 10**50, '中😀']))
        for i in range(10)] for variant in range(3)]
    return [dict(parse_status='PARSED', functions=[dict(function_id=f'fn{i}', name='name'+str(i),
        file='source'+str(i)+'.c')], control_flow=[dict(function_id=f'fn{i}', cfg_id=f'cfg{i}',
        entry=0, exit=9, nodes=copy.deepcopy(templates[i % 3]), parameters=['arg'],
        complete=bool(i % 2), unsupported=[], future_graph=dict(tu=f'tu{i}'))]) for i in range(count)]


class CFGSharingTests(unittest.TestCase):
    def compare(self, value):
        old = reference.merge(copy.deepcopy(value))
        preserved = encoded(value)
        result = merge(value)
        self.assertEqual(encoded(result), encoded(old), 'All tables/graph identities/types/field and array order must match')
        self.assertEqual(encoded(value), preserved, 'Input logical evidence cannot change')
        return result

    def test_original_merge_pin_and_distinct_tu_graphs_all_survive_with_full_future_fields(self):
        raw = REFERENCE.read_text('utf-8'); raw = raw[raw.index('def merge('):]
        self.assertEqual(hashlib.sha256(raw.encode()).hexdigest(),
            'e5ef68bd270d53bd04304cd4b6e9632aa18c0a162a0235136d1a119e45682db1')
        result = self.compare(parts(20))
        self.assertEqual(len(result['control_flow']), 20)
        self.assertEqual(len({r['function_id'] for r in result['control_flow']}), 20)
        self.assertEqual(sum(len(r['nodes']) for r in result['control_flow']), 200)

    def test_seeded_orders_duplicates_weak_bodies_parse_failures_and_constant_regions_match(self):
        rng = random.Random(20261102)
        for case in range(25):
            rows = parts(12)
            rows[0]['functions'][0]['is_weak'] = True
            strong = copy.deepcopy(rows[0]); strong['functions'][0]['is_weak'] = False
            strong['control_flow'][0]['nodes'][1]['value']['constant'] = 91
            rows += [strong, copy.deepcopy(rows[2])]
            rows[1]['parse_status'] = 'FAILED'
            rows[1]['unknowns'] = [dict(kind='EXPLICIT_PARSE_GAP', file='source1.c')]
            rows[3]['constant_regions'] = [dict(function_id='fn3', file='source3.c', offset=0, end_offset=50)]
            rows[3]['accesses'] = [dict(function_id='fn3', file='source3.c', offset=10, access_kind='WRITE')]
            for row in rows:
                if rng.randrange(3) == 0: row['control_flow'][0]['nodes'][0]['different_future'] = case
            rng.shuffle(rows)
            with self.subTest(case=case): self.compare(rows)

    def test_forced_fingerprints_cannot_merge_scalar_types_key_order_duplicates_or_unicode(self):
        pool = ReadOnlyGraphPool(cache_size=3)
        values = [[dict(value=v)] for v in [None, True, 1, 1.0, -0.0, 0.0, '中', '\\u4e2d', '\udcff', 10**60]]
        values += [[dict(a=1, b=2)], [dict(b=2, a=1)], [1, 1, 2], [1, 2, 1]]
        with patch('ecra.cfg_sharing._fingerprint', return_value=b'x'*32):
            for value in values:
                self.assertEqual(encoded(pool.share(value)), encoded(value))
        self.assertLessEqual(len(pool.cache), 3)

    def test_mutated_entries_and_unsupported_future_types_bypass_without_normalization(self):
        invalid = parts(1)
        invalid[0]['control_flow'][0]['nodes'][0]['invalid_unicode'] = '\udcff'
        for function in [reference.merge, merge]:
            with self.assertRaises(UnicodeEncodeError):
                function(copy.deepcopy(invalid))
        pool = ReadOnlyGraphPool(cache_size=1)
        first = [dict(x=1)]; pool.share(first); first[0]['x'] = 2
        self.assertEqual(encoded(pool.share([dict(x=1)])), '[{"x":1}]')
        class Computed(list):
            pass
        for value in [(1, 2), {1: 'numeric key'}, Computed([1]), {'nan': float('nan')}, {'unknown': {1, 2}}]:
            self.assertIs(pool.share(value), value)
        # Empty/small cache is an acceleration choice, never an evidence limit.
        for size in range(4):
            pool = ReadOnlyGraphPool(cache_size=size)
            for i in range(40):
                value = [dict(node=i % 5)]
                self.assertEqual(encoded(pool.share(value)), encoded(value))
            self.assertLessEqual(len(pool.cache), size)

    def test_complete_merge_retains_all_graphs_and_nodes_with_lower_live_allocation(self):
        live, hashes = [], []
        for function in [reference.merge, merge]:
            gc.collect(); tracemalloc.start(1)
            try:
                original = parts(2400)
                facts = function(original)
                live.append(tracemalloc.get_traced_memory()[0])
            finally:
                tracemalloc.stop()
            self.assertEqual(len(facts['control_flow']), 2400)
            self.assertEqual(sum(len(r['nodes']) for r in facts['control_flow']), 24000)
            hashes.append(hashlib.sha256(encoded(facts).encode()).hexdigest())
            del original, facts
        self.assertEqual(hashes[0], hashes[1])
        self.assertLess(live[1], live[0] * 0.8)


if __name__ == '__main__':
    unittest.main()
