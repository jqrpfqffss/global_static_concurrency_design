"""Missing C++ storage layouts must form a finite, conservative lattice."""
import copy
import unittest

from ecra.points_to import Solver
from tests.test_pointer_worklist import FullRescanSolver, addr, loc


ROOT = 'local:src/common/hwio.cpp:c:adc.hpp@660'


def facts(constraints=()):
    return dict(variables=[], functions=[], accesses=[], calls=[], unknowns=[],
                pointer_constraints=list(constraints))


class UnmodeledStorageTests(unittest.TestCase):
    def test_overlap_summary_absorbs_all_further_projections_without_layout(self):
        solver = Solver(facts())
        self.assertEqual(solver.storage_location(ROOT + '/$overlap/field/$overlap/[7]'),
                         ROOT + '/$overlap')

    def test_offset_images_of_missing_layout_stabilize_and_keep_original_address(self):
        solver = Solver(facts())
        expression = dict(op='offset', value=loc('p'), index='*')
        solver.add_points('p', {ROOT})
        for _ in range(12):
            solver.add_points('p', solver.value(expression))
        self.assertEqual(solver.points['p'],
                         {ROOT, ROOT + '/$overlap', 'unknown:storage-layout:' + ROOT})

    def test_recursive_fields_and_indices_are_opaque_without_a_layout(self):
        for projection in (dict(op='field', field='next'), dict(op='index', index='1')):
            with self.subTest(projection=projection):
                solver = Solver(facts())
                expression = dict(projection, base=dict(op='deref', value=loc('p')))
                solver.add_points('p', {ROOT})
                for _ in range(12):
                    solver.add_points('p', solver.locations(expression))
                self.assertEqual(solver.points['p'],
                                 {ROOT, ROOT + '/$overlap', 'unknown:storage-layout:' + ROOT})

    def test_worklist_matches_full_rescan_and_retains_late_targets_and_alias_gap(self):
        constraints = [
            dict(left=loc('p'), right=addr(ROOT)),
            dict(left=loc('p'), right=dict(op='offset', value=loc('p'), index='*')),
            dict(left=loc('out'), right=dict(op='deref', value=loc('p'))),
            dict(left=loc(ROOT + '/pointer'), right=addr('obj:payload')),
            dict(left=loc(ROOT + '/callback'), right=dict(op='function', id='Handler')),
        ]
        data = facts(constraints)
        data['variables'] = [dict(symbol_id='payload', name='payload')]
        data['indirect_accesses'] = [dict(location=dict(op='deref', value=loc('out')),
            mode='WRITE', function_id='Writer', file='a.cpp', line=7, offset=3)]
        for cls in (Solver, FullRescanSolver):
            with self.subTest(solver=cls.__name__):
                solver = cls(copy.deepcopy(data))
                # A regression fails promptly instead of waiting for resource
                # exhaustion. This observer changes no production algorithm.
                original = solver.add_points

                def observed(location, values):
                    self.assertLess(len(solver.target_pool.values), 100)
                    return original(location, values)

                solver.add_points = observed
                solver.solve()
                self.assertTrue(solver.facts['points_to_stats']['complete'])
                self.assertLess(solver.facts['points_to_stats']['evaluations'], 80)
                self.assertIn('obj:payload', solver.points['out'])
                self.assertIn('fn:Handler', solver.points['out'])
                self.assertIn('unknown:storage-layout:' + ROOT, solver.points['out'])
                self.assertTrue(any(a['symbol_id'] == 'payload' and a['access_kind'] == 'WRITE'
                                    for a in solver.facts['accesses']))
                self.assertTrue(any(u['kind'] == 'UNRESOLVED_POINTEE'
                                    and u.get('symbol_id') == 'payload'
                                    for u in solver.facts['unknowns']))
                if cls is Solver:
                    expected = dict(solver.points)
                else:
                    self.assertEqual(expected, dict(solver.points))


if __name__ == '__main__':
    unittest.main()
