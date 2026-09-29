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

    def test_gnu_alternate_cleanup_spelling_invalidates_mask(self):
        self.check('__disable_irq(); { unsigned saved __attribute__((__cleanup__(Restore)))=0; } value++;',
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

    @staticmethod
    def reachable(graph):
        reached, pending = set(), [graph['entry']]
        while pending:
            ident = pending.pop()
            if ident not in reached:
                reached.add(ident)
                pending.extend(graph['nodes'][ident]['successors'])
        return reached

    def test_constant_true_loops_have_no_false_exit(self):
        for loop in ['while (1) { value++; }', 'do { value++; } while (1);',
                     'for (; 1;) { value++; }', 'while (2 - 1) { value++; }']:
            with self.subTest(loop=loop):
                _, _, graph = self.check('__disable_irq(); ' + loop + ' __enable_irq();', 'SAFE')
                reached = self.reachable(graph)
                self.assertNotIn(graph['exit'], reached)
                self.assertTrue(all(node['id'] not in reached for node in graph['nodes']
                                    if node.get('name') == '__enable_irq'))

    def test_const_volatile_condition_is_not_folded(self):
        _, _, graph = self.check('__disable_irq(); while (enabled) { value++; } __enable_irq();', 'SAFE',
                                 declarations='const volatile int enabled = 1;\n')
        self.assertIn(graph['exit'], self.reachable(graph))

    def test_constant_false_while_and_for_do_not_execute_body(self):
        for loop in ['while (0) { __enable_irq(); }', 'for (; 0;) { __enable_irq(); }']:
            with self.subTest(loop=loop):
                _, _, graph = self.check('__disable_irq(); ' + loop + ' value++;', 'SAFE')
                reached = self.reachable(graph)
                self.assertIn(graph['exit'], reached)
                self.assertTrue(all(node['id'] not in reached for node in graph['nodes']
                                    if node.get('name') == '__enable_irq'))

    def test_do_false_executes_body_once(self):
        self.check('__disable_irq(); do { __enable_irq(); } while (0); value++;', 'SUSPECT')

    def test_while_and_do_break_exit_infinite_loop(self):
        for loop in ['while (1) { __enable_irq(); break; }',
                     'do { __enable_irq(); break; } while (1);']:
            with self.subTest(loop=loop):
                self.check('__disable_irq(); ' + loop + ' value++;', 'SUSPECT')

    def test_while_and_do_continue_execute_condition(self):
        for loop in ['while (Enable()) { continue; }', 'do { continue; } while (Enable());']:
            with self.subTest(loop=loop):
                self.check('__disable_irq(); ' + loop + ' value++;', 'SUSPECT',
                           helpers='int Enable(void) { __enable_irq(); return 0; }\n')

    def test_for_init_cleanup_does_not_run_on_continue(self):
        self.check('__disable_irq(); for (unsigned saved __attribute__((cleanup(Restore)))=flag; saved; saved=0) '
                   '{ value++; continue; }', 'SAFE', helpers='void Restore(unsigned *saved) { __enable_irq(); }\n')

    def test_inner_break_does_not_cleanup_outer_loop_init(self):
        self.check('__disable_irq(); for (unsigned saved __attribute__((cleanup(Restore)))=flag; saved; saved=0) '
                   '{ for (;;) { break; } value++; }', 'SAFE',
                   helpers='void Restore(unsigned *saved) { __enable_irq(); }\n')

    def test_cleanup_continue_then_increment_can_reestablish_mask(self):
        self.check('__disable_irq(); for (;flag;__disable_irq()) { '
                   'unsigned saved __attribute__((cleanup(Restore)))=0; value++; continue; }', 'SAFE',
                   helpers='void Restore(unsigned *saved) { __enable_irq(); }\n')

    def test_nested_cleanup_on_return_reaches_each_live_scope(self):
        facts, _, _ = self.check('__disable_irq(); Helper(); value++;', 'SUSPECT',
                    helpers='void Restore(unsigned *saved) { __enable_irq(); }\n'
                            'void Helper(void) { unsigned outer __attribute__((cleanup(Restore)))=0; '
                            'for (unsigned inner __attribute__((cleanup(Restore)))=0;;) { return; } }\n')
        helper = next(f['function_id'] for f in facts['functions'] if f['name'] == 'Helper')
        graph = next(g for g in facts['control_flow'] if g['function_id'] == helper)
        reached = self.reachable(graph)
        cleanups = [n for n in graph['nodes'] if n['id'] in reached and n.get('reason') == 'CLEANUP_ATTRIBUTE']
        self.assertEqual(len(cleanups), 2)
        self.assertIn('inner', cleanups[0]['cleanup_variable'])
        self.assertIn('outer', cleanups[1]['cleanup_variable'])

    def test_nested_cleanup_break_preserves_scope_exit_order(self):
        _, _, graph = self.check('__disable_irq(); for (unsigned outer __attribute__((cleanup(Restore)))=1;;) '
                                 '{ unsigned inner __attribute__((cleanup(Restore)))=0; break; } value++;',
                                 'SUSPECT', helpers='void Restore(unsigned *saved) { __enable_irq(); }\n')
        reached = self.reachable(graph)
        cleanups = [n for n in graph['nodes'] if n['id'] in reached and n.get('reason') == 'CLEANUP_ATTRIBUTE']
        self.assertEqual(len(cleanups), 2)
        self.assertIn('inner', cleanups[0]['cleanup_variable'])
        self.assertIn('outer', cleanups[1]['cleanup_variable'])

    def test_implicit_cleanup_access_inherits_caller_context(self):
        facts, value, _ = self.check('int local __attribute__((cleanup(Cleanup)))=0;', 'SUSPECT',
                                     helpers='static void Cleanup(int *p) { value++; }\n')
        cleanup = next(f['function_id'] for f in facts['functions'] if f['name'] == 'Cleanup')
        accesses = [a for a in value['accesses'] if a['function_id'] == cleanup]
        self.assertTrue(accesses)
        self.assertTrue(all('main' in a['contexts'] for a in accesses), accesses)

    def test_implicit_cleanup_receives_address_of_local_pointer(self):
        facts, value, _ = self.check('int *local __attribute__((cleanup(Cleanup)))=&value;', 'SUSPECT',
                                     helpers='static void Cleanup(int **p) { **p=1; }\n')
        cleanup = next(f['function_id'] for f in facts['functions'] if f['name'] == 'Cleanup')
        self.assertTrue(any(a['function_id'] == cleanup and a['access_kind'] == 'WRITE'
                            and 'main' in a['contexts'] for a in value['accesses']), value['accesses'])

    def test_opaque_cleanup_can_escape_pointer_to_target(self):
        cfg = self.project({'a.c': 'static int value; void Cleanup(int **p);\n'
                                 'int main(void) { int *local __attribute__((cleanup(Cleanup)))=&value; return 0; }\n'},
                           contexts=[dict(id='main', kind='MAIN', functions=['main'])])
        facts, _ = self.extract(cfg)
        value = next(v for v in facts['variables'] if v['name'] == 'value')
        self.assertEqual(value['static_classification'], 'UNKNOWN', value)
        self.assertIn('UNKNOWN_ADDRESS_ESCAPE', value['unknown_reason_codes'])


if __name__ == '__main__':
    unittest.main()
