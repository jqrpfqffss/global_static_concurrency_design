"""Pointer evidence comparison follows targets rather than bitmap atom order."""
import unittest

from ecra.git_diff import summarize
from ecra.points_to import Solver


class DiffPointerEncodingTests(unittest.TestCase):
    def summary(self, reverse=False, compressed=True, extra=None):
        facts = dict(variables=[], functions=[], accesses=[], calls=[], unknowns=[])
        solver = Solver(facts)
        atoms = ['object:' + str(i) for i in range(1400)]
        universe = atoms + ['unused:' + str(i) for i in range(300)]
        solver.target_pool.make(reversed(universe) if reverse else universe)
        for i in range(80 if compressed else 1):
            solver.add_points('local:' + str(i), atoms + ([extra] if extra else []))
        solver.solve()
        if compressed:
            self.assertIn('pointer_target_encoding', facts)
        return facts, summarize(facts, dict(findings=[], coverage={}, analysis_status='COMPLETE'))

    def test_compressed_atom_intern_order_does_not_change_alias_semantics(self):
        left, a = self.summary()
        right, b = self.summary(reverse=True)
        # Equal sets may use entirely different numeric atom assignments.
        self.assertNotEqual(left['pointer_target_atoms'], right['pointer_target_atoms'])
        self.assertEqual(a, b)

    def test_compressed_and_explicit_storage_have_identical_semantic_hashes(self):
        facts, a = self.summary()
        from ecra.target_set import point_targets
        facts['pointer_targets'] = [dict(location=row['location'], targets=list(point_targets(facts, row)))
                                   for row in facts['pointer_targets']]
        b = summarize(facts, dict(findings=[], coverage={}, analysis_status='COMPLETE'))
        self.assertEqual(a, b)

    def test_different_pointee_is_a_semantic_change(self):
        _, a = self.summary()
        _, b = self.summary(extra='unknown:missing')
        self.assertNotEqual(a['semantics']['pointer_targets'], b['semantics']['pointer_targets'])


if __name__ == '__main__':
    unittest.main()
