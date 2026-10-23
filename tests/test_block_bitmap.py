import json
from contextlib import closing
from pathlib import Path
import random
import sqlite3
import sys
import tempfile
import unittest

from ecra.block_bitmap import BLOCK_BITS, BlockBitmap
from ecra.common import digest
from ecra.points_to import Solver
from ecra.report import write_database
from ecra.target_set import point_targets


class BlockBitmapTests(unittest.TestCase):
    def test_integer_operations_hash_and_index_order_are_exact(self):
        rng = random.Random(20261022)
        for _ in range(150):
            left = {rng.randrange(150000) for _ in range(rng.randrange(1, 70))}
            right = {rng.randrange(150000) for _ in range(rng.randrange(1, 70))}
            a, b = sum(1 << i for i in left), sum(1 << i for i in right)
            x, y = BlockBitmap.from_int(a), BlockBitmap.from_int(b)
            for actual, expected in ((x | y, a | b), (x & y, a & b), (x ^ y, a ^ b),
                                     (x & ~y, a & ~b), (x & ~b, a & ~b), (a & y, a & b)):
                self.assertEqual(int(actual), expected)
                self.assertEqual(hash(actual), hash(expected))
                self.assertEqual(actual.bit_count(), expected.bit_count())
                self.assertEqual(actual.bit_length(), expected.bit_length())
                self.assertEqual(list(actual.indices()), sorted(i for i in left | right if expected & (1 << i)))
            self.assertEqual({x: 'same mathematical key'}[a], 'same mathematical key')

    def test_dense_blocks_boundaries_and_legacy_identifiers(self):
        for start, count in ((0, 0), (0, 6000), (4095, 4), (900000, 6500)):
            value = ((1 << count)-1) << start
            actual = BlockBitmap.from_int(value)
            self.assertEqual(list(actual.indices()), list(range(start, start+count)))
            self.assertEqual(actual.evidence_identifier(), 'PTS-'+digest(format(value, 'x'))[:20])
            self.assertEqual(''.join(actual.hexadecimal_fragments()), format(value, 'x'))
            self.assertEqual(int(-1 & actual), value)
        self.assertEqual(int(BlockBitmap.from_blocks([(1, 1), (1, 2), (0, 0)])), 3 << BLOCK_BITS)
        with self.assertRaises(ValueError):
            BlockBitmap.from_blocks([(-1, 1)])
        with self.assertRaises(ValueError):
            BlockBitmap.from_blocks([(0, 1 << BLOCK_BITS)])

    @unittest.skipUnless(sys.implementation.name == 'cpython', 'CPython allocation measurement')
    def test_sparse_high_indices_do_not_allocate_full_width_integers(self):
        values = [BlockBitmap.bit(900000+i) for i in range(1000)]
        actual = sum(value.referenced_storage_bytes() for value in values)
        original = sum(sys.getsizeof(1 << (900000+i)) for i in range(1000))
        self.assertLess(actual, original//20)
        self.assertEqual(sum(value.bit_count() for value in values), 1000)

    def test_large_block_encoding_keeps_all_targets_and_sqlite_definitions(self):
        facts = dict(variables=[], functions=[], accesses=[], calls=[], unknowns=[])
        solver = Solver(facts)
        for i in range(10000):
            solver.target_pool.bit('padding:'+str(i))
        atoms = {'object:'+str(i) for i in range(1500)}
        for i in range(80):
            solver.add_points('local:'+str(i), atoms)
        solver.solve()
        self.assertEqual(facts['pointer_target_encoding'], 'INTERNED_BLOCK_BITMAP_V2')
        self.assertEqual(facts['points_to_stats']['targets'], 120000)
        decoded = json.loads(json.dumps(facts))
        for row in decoded['pointer_targets']:
            self.assertEqual(set(point_targets(decoded, row)), atoms)
        ident = next(iter(facts['pointer_target_sets']))
        self.assertEqual(ident, solver.points['local:0'].bits.evidence_identifier())
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'facts.db'
            write_database(path, facts, dict(findings=[]))
            with closing(sqlite3.connect(path)) as db:
                stored_atoms = [row[0] for row in db.execute('SELECT target FROM pointer_target_atoms ORDER BY target_index')]
                entries = list(db.execute('SELECT target_set_id,encoding,block_bits,data FROM pointer_target_sets'))
                self.assertEqual(stored_atoms, facts['pointer_target_atoms'])
                self.assertEqual(len(entries), 1)
                key, encoding, block_bits, data = entries[0]
                reconstructed = dict(pointer_target_atoms=stored_atoms, pointer_target_sets={key: json.loads(data)},
                                     pointer_target_block_bits=block_bits, pointer_target_encoding=encoding)
                self.assertEqual(set(point_targets(reconstructed, dict(target_set_id=key))), atoms)


if __name__ == '__main__':
    unittest.main()
