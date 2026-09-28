"""Real Clang CFG regressions for for-loops and GNU cleanup scope exits."""
import unittest

from tests import test_ecra as fixtures


class ForControlFlowTests(unittest.TestCase):
    setUp = fixtures.ProjectTest.setUp
    project = fixtures.ProjectTest.project
    extract = fixtures.ProjectTest.extract

    def check(self, body, classification, helpers='', declarations=''):
        source = '''int value;
void __disable_irq(void); void __enable_irq(void);
unsigned __get_PRIMASK(void); void __set_PRIMASK(unsigned);
void TIM4_IRQHandler(void) { value++; }
''' + declarations + helpers + '\nint main(int flag) {\n' + body + '\nreturn 0;\n}\n'
        cfg = self.project({'a.c': source}, contexts=[dict(id='main', kind='MAIN', functions=['main'])])
        facts, _ = self.extract(cfg)
        value = next(v for v in facts['variables'] if v['name'] == 'value')
        self.assertEqual(value['static_classification'], classification, value)
        main = next(f['function_id'] for f in facts['functions'] if f['name'] == 'main')
        graph = next(g for g in facts['control_flow'] if g['function_id'] == main)
        self.assertTrue(graph['complete'], graph['unsupported'])
        if classification == 'SAFE':
            self.assertEqual(value['safe_reason_code'], 'SAFE_EFFECTIVE_PROTECTION', value)
        return facts, value, graph

    def test_for_before_complete_primask_window(self):
        self.check('for (int i=0; i<flag; ++i) {}\n'
                   'unsigned saved=__get_PRIMASK(); __disable_irq(); value++; __set_PRIMASK(saved);', 'SAFE')

    def test_protected_write_in_for(self):
        self.check('for (int i=0; i<flag; ++i) { __disable_irq(); value++; __enable_irq(); }', 'SAFE')

    def test_for_condition_and_increment_inside_mask(self):
        self.check('__disable_irq(); for (;value < flag; value++) {} __enable_irq();', 'SAFE')

    def test_conditional_unmask_and_break_reaches_following_write(self):
        self.check('__disable_irq(); for (int i=0; i<flag; ++i) { '
                   'if (flag>1) { __enable_irq(); break; } } value++;', 'SUSPECT')

    def test_unmasked_write_in_for_remains_suspect(self):
        self.check('for (int i=0; i<flag; ++i) { value++; }', 'SUSPECT')

    def test_continue_runs_increment(self):
        self.check('__disable_irq(); for (int i=0; i<flag; __enable_irq()) { continue; } value++;', 'SUSPECT')

    def test_continue_backedge_preserves_possible_unmask(self):
        self.check('__disable_irq(); for (int i=0; i<flag; __enable_irq()) { value++; continue; }', 'SUSPECT')

    def test_break_skips_unmasking_increment(self):
        self.check('__disable_irq(); for (int i=0; i<flag; __enable_irq()) { break; } value++;', 'SAFE')

    def test_nested_break_targets_only_inner_loop(self):
        self.check('__disable_irq(); for (int i=0; i<flag; ++i) { '
                   'for (int j=0; j<flag; ++j) { break; } __enable_irq(); } value++;', 'SUSPECT')

    def test_missing_init_and_increment_are_unambiguous(self):
        self.check('__disable_irq(); for (;flag;) { value++; break; } __enable_irq();', 'SAFE')

    def test_conditionless_loop_has_no_false_exit(self):
        facts, value, graph = self.check('__disable_irq(); for (;;) { value++; }\n__enable_irq();', 'SAFE')
        reachable, pending = set(), [graph['entry']]
        while pending:
            ident = pending.pop()
            if ident not in reachable:
                reachable.add(ident)
                pending.extend(graph['nodes'][ident]['successors'])
        self.assertNotIn(graph['exit'], reachable)
        enable = next(n for n in graph['nodes'] if n.get('name') == '__enable_irq')
        self.assertNotIn(enable['id'], reachable)

    def test_conditionless_loop_break_can_exit(self):
        self.check('__disable_irq(); for (;;) { if(flag) { __enable_irq(); break; } } value++;', 'SUSPECT')

    def test_for_macro_preserves_mask_proof(self):
        self.check('REPEAT(flag) { __disable_irq(); value++; __enable_irq(); }', 'SAFE',
                   declarations='#define REPEAT(n) for (int i=0; i<(n); ++i)\n')

    def test_cleanup_scope_exit_invalidates_prior_mask(self):
        self.check('__disable_irq(); { unsigned saved __attribute__((cleanup(Restore)))=0; } value++;',
                   'SUSPECT', helpers='void Restore(unsigned *saved) { __enable_irq(); }\n')

    def test_cleanup_does_not_invalidate_earlier_protected_access(self):
        self.check('__disable_irq(); { unsigned saved __attribute__((cleanup(Restore)))=0; value++; }',
                   'SAFE', helpers='void Restore(unsigned *saved) { __enable_irq(); }\n')

    def test_protection_can_be_reestablished_after_cleanup(self):
        facts, _, graph = self.check('__disable_irq(); { unsigned saved __attribute__((cleanup(Restore)))=0; } '
                                   '__disable_irq(); value++; __enable_irq();', 'SAFE',
                                   helpers='void Restore(unsigned *saved) { __enable_irq(); }\n')
        self.assertTrue(any(n.get('reason') == 'CLEANUP_ATTRIBUTE' for n in graph['nodes']))

    def test_for_init_cleanup_runs_on_break(self):
        self.check('__disable_irq(); for (unsigned saved __attribute__((cleanup(Restore)))=1; saved; ) '
                   '{ break; } value++;', 'SUSPECT', helpers='void Restore(unsigned *saved) { __enable_irq(); }\n')

    def test_for_init_cleanup_runs_on_condition_false(self):
        self.check('__disable_irq(); for (unsigned saved __attribute__((cleanup(Restore)))=flag; saved; saved=0) '
                   '{} value++;', 'SUSPECT', helpers='void Restore(unsigned *saved) { __enable_irq(); }\n')

    def test_body_cleanup_runs_on_continue(self):
        self.check('__disable_irq(); for (int i=0; i<flag; ++i) { '
                   'unsigned saved __attribute__((cleanup(Restore)))=0; value++; continue; }',
                   'SUSPECT', helpers='void Restore(unsigned *saved) { __enable_irq(); }\n')

    def test_body_cleanup_runs_on_break(self):
        self.check('__disable_irq(); for (;;) { unsigned saved __attribute__((cleanup(Restore)))=0; '
                   'break; } value++;', 'SUSPECT', helpers='void Restore(unsigned *saved) { __enable_irq(); }\n')

    def test_helper_cleanup_runs_on_return(self):
        self.check('__disable_irq(); Helper(); value++;', 'SUSPECT',
                   helpers='void Restore(unsigned *saved) { __enable_irq(); }\n'
                           'void Helper(void) { unsigned saved __attribute__((cleanup(Restore)))=0; return; }\n')

    def test_atomic_macro_cleanup_cannot_protect_following_access(self):
        self.check('__disable_irq(); ATOMIC_BLOCK() {} value++;', 'SUSPECT',
                   helpers='void Restore(unsigned *saved) { __enable_irq(); }\n',
                   declarations='#define ATOMIC_BLOCK() for (unsigned saved __attribute__((cleanup(Restore)))=1; '
                                'saved; saved=0)\n')


if __name__ == '__main__':
    unittest.main()
