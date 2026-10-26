"""Build relocation must understand real Windows Portable directory aliases."""
import os
from pathlib import Path
import tempfile
import unittest

from ecra.git_diff import build_arguments


class DiffBuildPathTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='ecra diff paths ')
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        self.roots = [self.folder/'基准工程', self.folder/'当前工程']
        self.aliases = [self.folder/'base-alias', self.folder/'head-alias']
        for root, alias in zip(self.roots, self.aliases):
            (root/'include').mkdir(parents=True)
            (root/'app.c').write_text('int g;', encoding='utf-8')
            if os.name == 'nt':
                from ecra.portable import _junction
                _junction(alias, root)
            else:
                alias.symlink_to(root, target_is_directory=True)

    def unit(self, alias, macro='1'):
        return dict(original_arguments=['cc', '-I' + str(alias/'include'), '-DVALUE=' + macro,
                                       '-c', str(alias/'app.c'), '-o', str(alias/'build/output.o')])

    def test_distinct_ascii_aliases_of_logical_snapshots_compare_equal(self):
        left, right = [build_arguments(self.unit(alias), root) for root, alias in zip(self.roots, self.aliases)]
        self.assertEqual(left, right)
        self.assertIn('<工程>/app.c', left)
        self.assertIn('-I<工程>/include', left)
        self.assertEqual(build_arguments(self.unit(self.roots[0]), self.roots[0]), left)

    def test_real_macro_and_compiler_changes_are_preserved(self):
        left = build_arguments(self.unit(self.aliases[0]), self.roots[0])
        self.assertNotEqual(left, build_arguments(self.unit(self.aliases[1], '2'), self.roots[1]))
        unit = self.unit(self.aliases[1])
        unit['original_arguments'][0] = 'cc++'
        self.assertNotEqual(left, build_arguments(unit, self.roots[1]))
        for alias, root in zip(self.aliases, self.roots):
            unit = self.unit(alias)
            literal = '-DROOT_STRING="' + str(alias) + '"'
            unit['original_arguments'].append(literal)
            self.assertEqual(build_arguments(unit, root)[-1], literal)

    def test_external_and_wrong_target_aliases_do_not_become_project_paths(self):
        external = self.folder/'external'
        external.mkdir()
        left, right = self.unit(self.aliases[0]), self.unit(self.aliases[1])
        left['original_arguments'].append('-I' + str(external))
        right['original_arguments'].append('-I' + str(self.folder/'other-external'))
        self.assertNotEqual(build_arguments(left, self.roots[0]), build_arguments(right, self.roots[1]))
        wrong = build_arguments(self.unit(self.aliases[1]), self.roots[0])
        self.assertNotIn('<工程>/app.c', wrong)


if __name__ == '__main__':
    unittest.main()
