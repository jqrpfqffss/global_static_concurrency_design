"""Exact escape closures with indexed concrete/wildcard storage overlap."""
import random
import unittest
from unittest.mock import patch

from ecra.context_points import ContextSolver, scoped_location
from ecra.points_to import Solver


class EscapeSlotIndexTests(unittest.TestCase):
    def test_index_matches_complete_shape_scan_including_deep_and_wildcard_views(self):
        solver = Solver(dict(variables=[], functions=[]))
        rng = random.Random(20261026)
        locations = set()
        for depth in (0, 1, 2, 5, 6, 9):
            for _ in range(30):
                locations.add('array' + ''.join('/[' + rng.choice(['*', '-1', '0', '2', '19']) + ']'
                                              for _ in range(depth)))
        locations.update(('record/first', 'record/second', 'array/[0]/field/[1]'))
        for location in locations:
            solver.add_points(location, {'target:' + location})
        for location in locations | {'array/[1234]', 'missing', 'array/[0]/field/[*]'}:
            expected = {slot for slot in solver.slots_by_shape.get(solver.shape(location), ())
                        if solver.overlaps(slot, location)}
            self.assertEqual(solver.overlapping_slots(location), expected, location)

    def test_closure_keeps_cycles_descendants_wildcards_unknowns_and_late_writes(self):
        solver = Solver(dict(variables=[], functions=[]))
        solver.add_points('array/[1]', {'record'})
        solver.add_points('array/[2]', {'unrelated'})
        solver.add_points('array/[*]', {'wildcard'})
        solver.add_points('record/pointer', {'array/[1]', 'unknown:opaque'})
        self.assertEqual(solver.reachable_pointer_values({'array/[1]'}),
                         {'array/[1]', 'record', 'wildcard', 'unknown:opaque'})
        self.assertEqual(solver.copied_pointer_values({'array/[1]'}),
                         {'array/[1]', 'record', 'wildcard', 'unknown:opaque'})
        solver.add_points('array/[*]', {'late'})
        self.assertIn('late', solver.reachable_pointer_values({'array/[1]'}))
        self.assertIn('unrelated', solver.reachable_pointer_values({'array/[*]'}))

    def test_contextual_getter_returns_remain_reachable(self):
        solver = ContextSolver(dict(variables=[], functions=[], semantic_calls=[dict(_context_id='irq')]))
        returned = scoped_location('Get:return', 'irq')
        solver.add_points(returned + '/field', {'table/[3]'})
        solver.add_points('table/[*]', {'payload'})
        self.assertEqual(solver.reachable_pointer_values({'fn:Get'}), {'fn:Get', 'table/[3]', 'payload'})

    def test_concrete_array_closure_does_not_compare_every_sibling(self):
        solver = Solver(dict(variables=[], functions=[]))
        for i in range(1500):
            solver.add_points('table/[' + str(i) + ']', {'payload'})
        with patch.object(solver, 'overlaps', wraps=solver.overlaps) as comparisons:
            self.assertEqual(solver.reachable_pointer_values({'table/[0]'}), {'table/[0]', 'payload'})
            self.assertLess(comparisons.call_count, 10)


if __name__ == '__main__':
    unittest.main()
