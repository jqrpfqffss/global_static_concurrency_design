"""Variable-local, proof-carrying bare-metal classification using real Clang ASTs.

T01--T18 are the requested acceptance cases.  The additional adversarial cases
guard against reducing UNKNOWN by silently discarding possible writers.
"""
import unittest

from tests import test_ecra as fixtures
from ecra.analysis import analyze, merge
from ecra.compilation import prepare
from ecra.extract import Extractor


class PreOpenCodeClassificationTests(unittest.TestCase):
    setUp = fixtures.ProjectTest.setUp
    project = fixtures.ProjectTest.project
    extract = fixtures.ProjectTest.extract

    def scan(self, source, *, contexts=None, configure=None, allow_failed=False):
        sources = {'main.c': source} if isinstance(source, str) else source
        cfg = self.project(sources, contexts=contexts or [
            dict(id='main', kind='MAIN', functions=['main'])])
        if configure:
            configure(cfg)
        if allow_failed:
            units, audit = prepare(self.root, cfg)
            parts = [Extractor(dict(root=str(self.root), unit=unit, config=cfg)).run()
                     for unit in units]
            failed = sum(part['parse_status'] != 'PARSED' for part in parts)
            self.assertGreater(failed, 0, 'Fixture must actually exercise a failed TU')
            facts = merge(parts)
            report = analyze(facts, cfg, dict(translation_units_failed=failed, **audit), self.root)
        else:
            facts, report = self.extract(cfg)
        self.facts, self.report = facts, report
        return facts, report

    def variable(self, name):
        matches = [v for v in self.facts['variables']
                   if v.get('qualified_name') == name or v.get('canonical_path') == name]
        if not matches:
            matches = [v for v in self.facts['variables'] if v['name'] == name]
        self.assertEqual(len(matches), 1, (name, [v['qualified_name'] for v in self.facts['variables']]))
        return matches[0]

    def assert_classified(self, name, expected, reason=None):
        variable = self.variable(name)
        self.assertEqual(variable['static_classification'], expected, variable)
        findings = [f for f in self.report['findings'] if f.get('symbol_id') == variable['symbol_id']]
        self.assertEqual(len(findings), 0 if expected == 'SAFE' else 1,
                         'Review queue must contain exactly one item per non-SAFE variable')
        if expected == 'SAFE':
            self.assertTrue(variable.get('safe_evidence'), variable)
            self.assertEqual(variable.get('safe_reason_code'), reason, variable)
        elif expected == 'UNKNOWN':
            self.assertIn(reason, variable.get('unknown_reason_codes', []), variable)
            self.assertTrue(variable.get('blocking_evidence'), variable)
        return variable

    def test_t01_multiple_foreground_functions_are_one_serial_domain(self):
        self.scan('''
            static unsigned value;
            static void TaskA(void) { value = 1; }
            static unsigned TaskB(void) { value++; return value; }
            int main(void) { TaskA(); return TaskB(); }
        ''')
        self.assert_classified('value', 'SAFE', 'SAFE_SINGLE_FOREGROUND')

    def test_t02_multiple_irqs_all_read(self):
        self.scan('''
            static unsigned value = 7;
            void TIM2_IRQHandler(void) { (void)value; }
            void USART1_IRQHandler(void) { (void)value; }
            int main(void) { return 0; }
        ''')
        self.assert_classified('value', 'SAFE', 'SAFE_MULTI_CONTEXT_READ_ONLY')

    def test_t03_single_irq_multiple_paths_and_rmw(self):
        self.scan('''
            static unsigned value;
            static void Read(void) { (void)value; }
            static void Write(void) { value = 3; }
            static void Increment(void) { value++; }
            void TIM4_IRQHandler(void) { Read(); Write(); Increment(); Read(); }
            int main(void) { return 0; }
        ''')
        value = self.assert_classified('value', 'SAFE', 'SAFE_SINGLE_IRQ')
        self.assertFalse(any(p['may_concurrent'] and p['has_write_conflict']
                             for p in value.get('conflict_pairs', [])))

    def test_t04_main_read_irq_write_is_suspect(self):
        self.scan('''static unsigned value;
            void TIM4_IRQHandler(void) { value = 1; }
            int main(void) { return value; }''')
        self.assert_classified('value', 'SUSPECT')

    def test_t05_two_irqs_unknown_priority_write_read_is_suspect(self):
        self.scan('''static unsigned value;
            void TIM2_IRQHandler(void) { value = 1; }
            void USART1_IRQHandler(void) { (void)value; }
            int main(void) { return 0; }''')
        self.assert_classified('value', 'SUSPECT')

    def test_t06_two_irqs_unknown_priority_write_write_is_suspect(self):
        self.scan('''static unsigned value;
            void TIM2_IRQHandler(void) { value = 1; }
            void USART1_IRQHandler(void) { value = 2; }
            int main(void) { return 0; }''')
        self.assert_classified('value', 'SUSPECT')

    def test_t07_unrelated_indirect_call_does_not_taint_sibling(self):
        self.scan('''
            static unsigned value;
            extern void (*unresolved_hook)(void);
            static void Unrelated(void) { unresolved_hook(); }
            static void Use(void) { value++; }
            int main(void) { Unrelated(); Use(); return value; }
        ''')
        self.assertTrue(any(u['kind'] == 'INDIRECT_CALL' for u in self.facts['unknowns']))
        self.assert_classified('value', 'SAFE', 'SAFE_SINGLE_FOREGROUND')

    def test_t08_variable_address_escapes_to_external_code(self):
        self.scan('''
            static unsigned value;
            void External_Process(unsigned *);
            int main(void) { External_Process(&value); return 0; }
        ''')
        self.assert_classified('value', 'UNKNOWN', 'UNKNOWN_ADDRESS_ESCAPE')

    def test_t09_failed_unrelated_tu_cannot_name_private_storage(self):
        self.scan({
            'main.c': 'static unsigned value; int main(void) { value++; return value; }',
            'broken.c': '#include "missing_device_header.h"\nint unrelated;\n',
        }, allow_failed=True)
        self.assert_classified('value', 'SAFE', 'SAFE_SINGLE_FOREGROUND')

    def test_t10_function_static_only_foreground(self):
        self.scan('''static unsigned Step(void) { static unsigned value; return ++value; }
            int main(void) { Step(); return Step(); }''')
        self.assert_classified('value', 'SAFE', 'SAFE_SINGLE_FOREGROUND')

    def test_t11_function_static_foreground_and_irq(self):
        self.scan('''static unsigned Step(void) { static unsigned value; return ++value; }
            void TIM4_IRQHandler(void) { Step(); }
            int main(void) { return Step(); }''')
        self.assert_classified('value', 'SUSPECT')

    def test_t12_callbacks_inherit_caller_contexts_and_read_only_is_safe(self):
        self.scan('''static unsigned value;
            static void CallbackA(void) { (void)value; }
            static void CallbackB(void) { (void)value; }
            void TIM2_IRQHandler(void) { CallbackA(); }
            void USART1_IRQHandler(void) { CallbackB(); }
            int main(void) { CallbackA(); CallbackB(); return 0; }''')
        value = self.assert_classified('value', 'SAFE', 'SAFE_MULTI_CONTEXT_READ_ONLY')
        self.assertEqual(len(value['contexts']), 3)

    def test_t13_full_primask_proves_protection(self):
        self.scan('''static unsigned value;
            void __disable_irq(void); void __enable_irq(void);
            void TIM4_IRQHandler(void) { value++; }
            int main(void) { __disable_irq(); value++; __enable_irq(); return 0; }''')
        value = self.assert_classified('value', 'SAFE', 'SAFE_EFFECTIVE_PROTECTION')
        self.assertEqual(value['protection_status'], 'EFFECTIVE')

    def test_t14_partial_rmw_window_is_suspect(self):
        self.scan('''static unsigned value;
            void __disable_irq(void); void __enable_irq(void);
            void TIM4_IRQHandler(void) { value++; }
            int main(void) { unsigned old = value; __disable_irq();
                value = old + 1; __enable_irq(); return 0; }''')
        value = self.assert_classified('value', 'SUSPECT')
        self.assertNotEqual(value['protection_status'], 'EFFECTIVE')

    def test_t15_unresolved_basepri_does_not_hide_known_conflict(self):
        self.scan('''static unsigned value;
            void __set_BASEPRI(unsigned);
            void TIM2_IRQHandler(void) { __set_BASEPRI(0x50); value++; __set_BASEPRI(0); }
            void USART1_IRQHandler(void) { value++; }
            int main(void) { return 0; }''')
        value = self.assert_classified('value', 'SUSPECT')
        self.assertEqual(value['analysis_coverage'], 'PARTIAL')

    def test_t16_dma_lifetime_is_local_unknown(self):
        self.scan('''static unsigned char buffer[16];
            int HAL_UART_Receive_DMA(void *, unsigned char *, unsigned);
            int main(void) { HAL_UART_Receive_DMA(0, buffer, 16); return 0; }''')
        self.assert_classified('buffer', 'UNKNOWN', 'UNKNOWN_DMA_LIFETIME')

    def test_cpu_and_dma_only_read_do_not_require_exclusive_ownership(self):
        self.scan('''static const unsigned char buffer[16]={1};
            int HAL_UART_Transmit_DMA(void *, const unsigned char *, unsigned);
            int main(void) { HAL_UART_Transmit_DMA(0, buffer, 16); return buffer[0]; }''')
        leaves = [v for v in self.facts['variables'] if v.get('static_classification') != 'CONTAINER']
        self.assertTrue(leaves)
        for leaf in leaves:
            self.assertEqual(leaf['static_classification'], 'SAFE', leaf)
            self.assertIn(leaf['safe_reason_code'], {'SAFE_READ_ONLY', 'SAFE_MULTI_CONTEXT_READ_ONLY'})

    def test_t17_member_assignment_has_separate_read_and_write(self):
        self.scan('''static struct Config { unsigned limit, period; } active_config;
            int main(void) { active_config.limit = active_config.period * 2; return 0; }''')
        self.assertEqual({a['access_kind'] for a in self.variable('active_config.limit')['accesses']}, {'WRITE'})
        self.assertEqual({a['access_kind'] for a in self.variable('active_config.period')['accesses']}, {'READ'})
        self.assert_classified('active_config.limit', 'SAFE', 'SAFE_SINGLE_FOREGROUND')
        self.assert_classified('active_config.period', 'SAFE', 'SAFE_READ_ONLY')

    def test_t18_dynamic_array_overlap_does_not_taint_other_storage(self):
        self.scan('''static unsigned slots[4], independent;
            void TIM4_IRQHandler(void) { slots[0] = 1; }
            int main(void) { unsigned i = independent & 3; slots[i]++; independent++; return 0; }''')
        self.assert_classified('independent', 'SAFE', 'SAFE_SINGLE_FOREGROUND')
        slots = [v for v in self.facts['variables'] if v.get('canonical_path', '').startswith('slots[')
                 and v.get('static_classification') != 'CONTAINER']
        self.assertTrue(slots, 'Array accesses must be canonical storage resources')
        self.assertTrue(any(v.get('canonical_path') == 'slots[*]' for v in slots))
        self.assertTrue(any(v['static_classification'] == 'SUSPECT' for v in slots), slots)

    def test_no_runtime_access_has_positive_proof(self):
        self.scan('static unsigned value = 3; int main(void) { return 0; }')
        self.assert_classified('value', 'SAFE', 'SAFE_NO_RUNTIME_ACCESS')

    def test_resolved_local_alias_does_not_count_as_escape(self):
        self.scan('''static unsigned value;
            static void Store(unsigned *p) { *p = 7; }
            int main(void) { unsigned *local = &value; Store(local); return value; }''')
        self.assert_classified('value', 'SAFE', 'SAFE_SINGLE_FOREGROUND')

    def test_callback_address_escape_adds_unknown_context_to_known_main(self):
        self.scan('''static unsigned value;
            void Register(void (*)(void));
            static void Callback(void) { value++; }
            int main(void) { Callback(); Register(Callback); return 0; }''')
        self.assert_classified('value', 'UNKNOWN', 'UNKNOWN_EXECUTION_CONTEXT')

    def test_known_conflict_wins_over_address_escape_and_queue_is_deduplicated(self):
        self.scan('''static unsigned value;
            void External_Process(unsigned *);
            static void Left(void) { value++; }
            static void Right(void) { Left(); value += 2; }
            void TIM4_IRQHandler(void) { Left(); Right(); }
            int main(void) { Left(); Right(); External_Process(&value); return 0; }''')
        value = self.assert_classified('value', 'SUSPECT')
        self.assertEqual(value['analysis_coverage'], 'PARTIAL')
        self.assertGreater(len(value['conflict_pairs']), 1)

    def test_unknown_pointer_without_target_evidence_is_not_global_alias(self):
        self.scan('''static unsigned value;
            unsigned *UnknownPointer(void);
            static void Unrelated(void) { unsigned *p = UnknownPointer(); *p = 10; }
            int main(void) { Unrelated(); value++; return value; }''')
        self.assert_classified('value', 'SAFE', 'SAFE_SINGLE_FOREGROUND')

    def test_unknown_call_without_address_escape_does_not_poison_global(self):
        self.scan('''unsigned value;
            void Library(void);
            int main(void) { Library(); value++; return value; }''')
        self.assert_classified('value', 'SAFE', 'SAFE_SINGLE_FOREGROUND')

    def test_readonly_dynamic_callback_context_cannot_invent_writer(self):
        self.scan('''static unsigned value;
            void Register(void (*)(void));
            static void Callback(void) { (void)value; }
            int main(void) { Register(Callback); return 0; }''')
        self.assert_classified('value', 'SAFE', 'SAFE_READ_ONLY')

    def test_const_function_table_inherits_foreground(self):
        self.scan('''static unsigned value;
            static void TaskA(void) { value++; }
            static void TaskB(void) { value = 2; }
            typedef struct { void (*func)(void); } task_t;
            static const task_t tasks[] = {{.func=TaskA}, {.func=TaskB}};
            static void Dispatch(unsigned i) { tasks[i & 1].func(); }
            int main(void) { Dispatch(0); Dispatch(1); return value; }''')
        self.assert_classified('value', 'SAFE', 'SAFE_SINGLE_FOREGROUND')
        targets = {c.get('callee_name') for c in self.facts['calls'] if c.get('call_kind') == 'INDIRECT_RESOLVED'}
        self.assertTrue({'TaskA', 'TaskB'} <= targets)

    def test_constant_array_elements_are_disjoint(self):
        self.scan('''static unsigned slots[2];
            void TIM4_IRQHandler(void) { slots[1]++; }
            int main(void) { slots[0]++; return 0; }''')
        for path in ('slots[0]', 'slots[1]'):
            variable = self.variable(path)
            self.assertEqual(variable['static_classification'], 'SAFE', variable)
            self.assertIn(variable.get('safe_reason_code'),
                          {'SAFE_SINGLE_FOREGROUND', 'SAFE_SINGLE_IRQ', 'SAFE_DISJOINT_STORAGE'})
            self.assertTrue(variable.get('safe_evidence'))

    def test_whole_object_write_prevents_false_safe_member(self):
        self.scan('''static struct Config { unsigned limit, period; } active_config;
            static const struct Config defaults = { 1, 2 };
            void TIM4_IRQHandler(void) { (void)active_config.period; }
            int main(void) { active_config = defaults; return 0; }''')
        self.assert_classified('active_config.period', 'SUSPECT')

    def test_volatile_word_and_single_writer_do_not_prove_safe(self):
        self.scan('''static volatile unsigned value;
            void TIM4_IRQHandler(void) { value = 1; }
            int main(void) { return value; }''')
        self.assert_classified('value', 'SUSPECT')

    def test_same_irq_diamond_has_no_self_concurrency(self):
        self.scan('''static unsigned value;
            static void Update(void) { value++; }
            static void Left(void) { Update(); }
            static void Right(void) { Update(); }
            void TIM4_IRQHandler(void) { Left(); Right(); }
            int main(void) { return 0; }''')
        value = self.assert_classified('value', 'SAFE', 'SAFE_SINGLE_IRQ')
        self.assertEqual(len(value['contexts']), 1)
        self.assertGreater(value['resolved_call_path_count'], 1)

    def test_configured_irq_group_does_not_merge_distinct_vectors(self):
        self.scan('''static unsigned value;
            void TIM2_IRQHandler(void) { value++; }
            void USART1_IRQHandler(void) { (void)value; }
            int main(void) { return 0; }''', contexts=[
                dict(id='main', kind='MAIN', functions=['main']),
                dict(id='interrupts', kind='ISR', functions=['TIM2_IRQHandler', 'USART1_IRQHandler'])])
        self.assert_classified('value', 'SUSPECT')

    def test_same_callback_registered_to_two_physical_irqs_is_shared(self):
        def configure(cfg):
            cfg['entry_registrations'] = [
                dict(api='RegisterTimer', callback_arg=0, kind='ISR', context_id='timer_irq', may_repeat=False),
                dict(api='RegisterUart', callback_arg=0, kind='ISR', context_id='uart_irq', may_repeat=False)]
        self.scan('''static unsigned value;
            void RegisterTimer(void (*)(void)); void RegisterUart(void (*)(void));
            static void Callback(void) { value++; }
            int main(void) { RegisterTimer(Callback); RegisterUart(Callback); return 0; }''', configure=configure)
        self.assert_classified('value', 'SUSPECT')

    def test_union_members_share_storage(self):
        self.scan('''static union State { unsigned a, b; } state;
            void TIM4_IRQHandler(void) { (void)state.b; }
            int main(void) { state.a++; return 0; }''')
        self.assert_classified('state.a', 'SUSPECT')
        self.assert_classified('state.b', 'SUSPECT')

    def test_nested_union_overlaps_but_unrelated_member_does_not(self):
        self.scan('''static struct State { union { unsigned a, b; } shared; unsigned independent; } state;
            void TIM4_IRQHandler(void) { (void)state.shared.b; }
            int main(void) { state.shared.a++; state.independent++; return 0; }''')
        self.assert_classified('state.shared.a', 'SUSPECT')
        self.assert_classified('state.shared.b', 'SUSPECT')
        self.assert_classified('state.independent', 'SAFE', 'SAFE_SINGLE_FOREGROUND')

    def test_array_of_structs_keeps_element_storage_disjoint(self):
        self.scan('''static struct Slot { unsigned state; } channels[2];
            void TIM4_IRQHandler(void) { channels[1].state++; }
            int main(void) { channels[0].state++; return 0; }''')
        self.assert_classified('channels[0].state', 'SAFE', 'SAFE_SINGLE_FOREGROUND')
        self.assert_classified('channels[1].state', 'SAFE', 'SAFE_SINGLE_IRQ')

    def test_array_of_structs_dynamic_index_overlaps_known_element(self):
        self.scan('''static struct Slot { unsigned state; } channels[2];
            void TIM4_IRQHandler(void) { (void)channels[0].state; }
            int main(void) { unsigned i = 0; channels[i].state++; return 0; }''')
        self.assert_classified('channels[0].state', 'SUSPECT')
        self.assert_classified('channels[*].state', 'SUSPECT')

    def test_escaped_getter_callback_also_escapes_returned_variable_address(self):
        self.scan('''static unsigned value;
            static unsigned *Get(void) { return &value; }
            void Register(unsigned *(*getter)(void));
            int main(void) { Register(Get); value++; return 0; }''')
        self.assert_classified('value', 'UNKNOWN', 'UNKNOWN_ADDRESS_ESCAPE')


if __name__ == '__main__':
    unittest.main()
