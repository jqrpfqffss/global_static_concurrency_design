"""Conservative fallbacks retain private non-escape proofs, without hiding changes."""
import unittest

from ecra.git_diff import compare, summarize
from tests import test_ecra


class PrivateIsolationTests(unittest.TestCase):
    setUp = test_ecra.ProjectTest.setUp
    project = test_ecra.ProjectTest.project
    extract = test_ecra.ProjectTest.extract

    def delta(self, declaration='static unsigned private;', use='private++;', **pinned):
        src = declaration + '\nunsigned changed;void Task(void){changed++;}void ISR(void){' + use + '}'
        cfg = self.project({'a.c': src})
        bf, br = self.extract(cfg)
        base = summarize(bf, br)
        cfg = self.project({'a.c': src.replace('changed++;', 'changed+=2;')})
        hf, hr = self.extract(cfg)
        head = summarize(hf, hr)
        # An unresolved boundary forces L1; the private scalar still has its
        # complete non-escape proof, derived independently by analyze().
        head['unknowns'].append('unrelated opaque boundary')
        diff = compare(base, head, dict(files=[], head_sha='h', base_sha='b', **pinned))
        return diff, hf, base, head

    def test_disconnected_private_scalar_is_exempt_from_global_fallback(self):
        diff, facts, _, _ = self.delta()
        private = next(v for v in facts['variables'] if v['name'] == 'private')
        self.assertEqual(diff['fallback_level'], 'L1')
        self.assertNotIn(private['symbol_id'], diff['selected_symbol_ids'])
        self.assertIn(private['symbol_id'], diff['fallback_exemptions'])
        self.assertIn('c:@changed', diff['selected_symbol_ids'])

    def test_externally_visible_or_address_taken_storage_cannot_be_exempt(self):
        for declaration, use in [('unsigned private;', 'private++;'),
                ('static unsigned private;void Escape(unsigned*);', 'Escape(&private);private++;'),
                ('static unsigned private[2];', 'private[0]++;')]:
            with self.subTest(declaration=declaration):
                diff, facts, _, _ = self.delta(declaration, use)
                variables = [v for v in facts['variables'] if v['name'] == 'private']
                self.assertTrue(variables)
                self.assertTrue(all(v['symbol_id'] in diff['conservative_symbol_ids'] for v in variables))
                self.assertTrue(all(v['symbol_id'] not in diff['selected_symbol_ids'] for v in variables))

    def test_build_semantics_change_prevents_exemption(self):
        diff, facts, base, head = self.delta()
        head['macros']['a.c'] = 'changed macro value'
        diff = compare(base, head, dict(files=[], head_sha='h', base_sha='b'))
        self.assertFalse(diff['fallback_exemptions'])
        self.assertTrue(all(v['symbol_id'] in set(diff['selected_symbol_ids']) | set(diff['conservative_symbol_ids']) for v in facts['variables']))
        private = next(v for v in facts['variables'] if v['name'] == 'private')
        self.assertNotIn(private['symbol_id'], diff['selected_symbol_ids'])

    def test_changed_private_accessor_keeps_dependency_selection(self):
        diff, facts, base, head = self.delta()
        fid = next(f for f in head['functions'] if f.endswith('@ISR'))
        head['functions'][fid]['digest'] = 'changed private accessor'
        diff = compare(base, head, dict(files=[], head_sha='h', base_sha='b'))
        private = next(v for v in facts['variables'] if v['name'] == 'private')
        self.assertIn(private['symbol_id'], diff['selected_symbol_ids'])
        self.assertNotIn(private['symbol_id'], diff['fallback_exemptions'])


if __name__ == '__main__':
    unittest.main()
