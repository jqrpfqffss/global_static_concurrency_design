"""Representation equivalence and lossless large-pointer-evidence round trips."""
import json
import random
import unittest

from ecra.points_to import Solver
from ecra.target_set import TargetPool, point_targets


class TargetSetTests(unittest.TestCase):
    def test_bitmap_operations_match_python_sets_with_different_intern_orders(self):
        randomizer = random.Random(47)
        atoms = ['object:'+str(i) for i in range(1000)] + ['fn:callback', 'unknown:external']
        pool, other = TargetPool(), TargetPool()
        other.make(reversed(atoms))
        for _ in range(30):
            left, right = set(randomizer.sample(atoms, 200)), set(randomizer.sample(atoms, 150))
            a, b = pool.make(left), pool.make(right)
            self.assertEqual(a | b, left | right)
            self.assertEqual(a & b, left & right)
            self.assertEqual(a - b, left - right)
            self.assertEqual(a | other.make(right), left | right)
            self.assertEqual(a & other.make(right), left & right)
            self.assertEqual(a - other.make(right), left - right)
            self.assertEqual(a, other.make(left))
            self.assertEqual(set(a), left)
            self.assertEqual(set(type(a)(pool, a.bits & pool.unknown_mask)), left & {'unknown:external'})

    def test_large_solution_serialization_retains_every_target(self):
        facts = dict(variables=[], functions=[], accesses=[], calls=[], unknowns=[])
        solver = Solver(facts)
        atoms = {'object:'+str(i) for i in range(1500)}
        for i in range(80):
            solver.add_points('local:'+str(i), atoms)
        solver.solve()
        decoded = json.loads(json.dumps(facts))
        self.assertEqual(decoded['points_to_stats']['targets'], 120000)
        self.assertEqual(decoded['pointer_target_encoding'], 'INTERNED_BITMAP_V1')
        self.assertEqual(len(decoded['pointer_target_sets']), 1)
        for point in decoded['pointer_targets']:
            self.assertEqual(set(point_targets(decoded, point)), atoms)
        self.assertLess(len(json.dumps(decoded)), 50000)


if __name__ == '__main__':
    unittest.main()
