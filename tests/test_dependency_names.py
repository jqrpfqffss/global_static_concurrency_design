"""Dependency graph nodes share names without losing any reader or target."""
import unittest

from ecra.points_to import Solver


class DependencyNameTests(unittest.TestCase):
    def test_long_ancestor_strings_are_shared_by_all_live_load_dependencies(self):
        solver = Solver(dict(variables=[],functions=[]))
        prefix = 'local:'+'/'.join(('NestedType'+str(i)+'T'*300) for i in range(8))
        solver.add_points(prefix, {'unknown:external'})
        identities = set()
        for index in range(800):
            location = prefix+'/field'+str(index)
            self.assertEqual(solver.load_location(location), {'unknown:external'})
            dependencies = solver.load_cache[('load',location,False)][1]
            ancestor = next(name for name in dependencies if name == prefix)
            identities.add(id(ancestor))
        self.assertEqual(len(solver.load_cache),800)
        self.assertEqual(len(identities),1,'Equal dependency nodes retain repeated long strings')

    def test_shared_names_preserve_all_readers_and_invalidate_after_late_opaque_write(self):
        solver = Solver(dict(variables=[],functions=[]))
        prefix = 'local:'+'TemplateType'*200
        for task,field in ((7,'first'),(8,'second')):
            solver.current_task=task
            self.assertFalse(solver.load_location(prefix+'/'+field))
        solver.current_task=None
        solver.add_points(prefix,{'unknown:late'})
        self.assertEqual(set(solver.pending),{7,8})
        for field in ('first','second'):
            self.assertNotIn(('load',prefix+'/'+field,False),solver.load_cache)
            self.assertEqual(solver.load_location(prefix+'/'+field),{'unknown:late'})


if __name__ == '__main__':
    unittest.main()
