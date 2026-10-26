"""Changed-edge witnesses retain deep/cyclic graphs without path enumeration."""
import unittest

from ecra.git_diff import representative_paths


class DiffGraphWitnessTests(unittest.TestCase):
    def test_deep_chain_reconstructs_only_requested_witness(self):
        count = 12000
        vertices = [str(i) for i in range(count)]
        edges = list(zip(vertices, vertices[1:]))
        variable = dict(graph=dict(edges=edges, roots=['0']), accessors=[vertices[-1]])
        self.assertEqual(representative_paths(variable, {edges[count // 2]}), [vertices])

    def test_cycles_multiple_roots_and_disconnected_edges(self):
        variable = dict(graph=dict(roots=['main', 'irq'], edges=[
            ('main', 'a'), ('irq', 'b'), ('a', 'b'), ('b', 'a'), ('b', 'read'),
            ('lost', 'orphan'), ('orphan', 'read')]), accessors=['read'])
        paths = representative_paths(variable, {('a', 'b'), ('lost', 'orphan')})
        self.assertEqual(paths, [['main', 'a', 'b', 'read'], ['lost', 'orphan', 'read']])
        self.assertEqual(representative_paths(variable, set()), [])
        self.assertEqual(representative_paths(None, {('a', 'b')}), [])


if __name__ == '__main__':
    unittest.main()
