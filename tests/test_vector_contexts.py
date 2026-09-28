"""Physical IRQ entry recovery from Cortex-M vector storage."""
import json
import unittest
from tests import test_ecra as fixtures


class VectorContextTests(unittest.TestCase):
    setUp = fixtures.ProjectTest.setUp
    project = fixtures.ProjectTest.project
    extract = fixtures.ProjectTest.extract

    def scan(self, source):
        cfg = self.project({'main.c': source}, contexts=[dict(id='main', kind='MAIN', functions=['main'])])
        facts, report = self.extract(cfg)
        return next(v for v in facts['variables'] if v['name']=='value'), facts

    def scan_assembly(self, source, assembly):
        cfg = self.project({'main.c': source, 'startup.s': assembly},
                           contexts=[dict(id='main', kind='MAIN', functions=['main'])])
        database = self.root / 'compile_commands.json'
        commands = json.loads(database.read_text(encoding='utf-8'))
        commands.append(dict(directory=str(self.root), file='startup.s',
                             arguments=['arm-none-eabi-gcc', '-c', 'startup.s']))
        database.write_text(json.dumps(commands), encoding='utf-8')
        facts, report = self.extract(cfg)
        self.assertEqual(report['coverage']['assembly_sources'], ['startup.s'])
        return next(v for v in facts['variables'] if v['name'] == 'value'), facts

    def test_custom_vector_symbol_inherits_physical_irq(self):
        value, facts = self.scan('''typedef void (*handler)(void);static unsigned value;
            void custom_interrupt(void){value++;} void reset(void){}
            const handler vectors[18] __attribute__((section(".isr_vector"),used)) =
                {[1]=reset,[17]=custom_interrupt};
            int main(void){return value;}''')
        self.assertEqual(value['static_classification'], 'SUSPECT', value)
        self.assertIn('IRQ:slot:17', value['variable_evidence_slice']['physical_contexts'])

    def test_shared_handler_in_two_vector_slots_keeps_two_executors(self):
        value, facts = self.scan('''typedef void (*handler)(void);static unsigned value;
            void shared(void){value++;}
            const handler vectors[18] __attribute__((section(".vectors"),used)) =
                {[16]=shared,[17]=shared};int main(void){return 0;}''')
        self.assertEqual(value['static_classification'], 'SUSPECT', value)

    def test_struct_vector_table_uses_layout_offsets(self):
        value, facts = self.scan('''typedef void (*handler)(void);static unsigned value;
            void custom(void){value++;}void reset(void){}
            struct Vector {void *sp;handler reset;handler exceptions[14];handler irq[2];};
            const struct Vector vectors __attribute__((section(".vectors"),used)) =
                {.reset=reset,.irq={[1]=custom}};int main(void){return value;}''')
        self.assertEqual(value['static_classification'], 'SUSPECT', value)
        self.assertIn('IRQ:slot:17', value['variable_evidence_slice']['physical_contexts'])

    def test_vector_nmi_cannot_be_protected_by_primask(self):
        value, facts = self.scan('''typedef void (*handler)(void);static unsigned value;
            void custom_nmi(void){value++;}void __disable_irq(void);void __enable_irq(void);
            const handler vectors[3] __attribute__((section(".vectors"),used))={[2]=custom_nmi};
            int main(void){__disable_irq();value++;__enable_irq();return 0;}''')
        self.assertEqual(value['static_classification'], 'SUSPECT', value)
        self.assertNotEqual(value['protection_status'], 'EFFECTIVE')

    def test_ordinary_function_pointer_table_is_not_an_irq_table(self):
        value, facts = self.scan('''typedef void (*handler)(void);static unsigned value;
            static void task(void){value++;}static const handler tasks[]={task};
            int main(void){tasks[0]();return 0;}''')
        self.assertEqual(value['safe_reason_code'], 'SAFE_SINGLE_FOREGROUND', value)
        self.assertFalse(facts['vector_entries'])

    def test_assembly_table_recovers_custom_irq_after_reserved_slots(self):
        value, facts = self.scan_assembly('''static unsigned value;
            void custom(void) { value++; } void reset(void) {}
            int main(void) { return 0; }''', '''
            .section .isr_vector,"a",%progbits
            .word _estack, reset
            .space 56
            .word custom
            .section .text
        ''')
        self.assertEqual(value['safe_reason_code'], 'SAFE_SINGLE_IRQ', value)
        self.assertEqual(value['variable_evidence_slice']['physical_contexts'], ['IRQ:slot:16'])

    def test_assembly_shared_handler_in_distinct_slots_is_not_serial(self):
        value, facts = self.scan_assembly('''static unsigned value;
            void custom(void) { value++; } void reset(void) {}
            int main(void) { return 0; }''', '''
            .section .vectors
            .word _estack, reset
            .zero 56
            .word custom, custom
        ''')
        self.assertEqual(value['static_classification'], 'SUSPECT', value)
        self.assertEqual(set(value['variable_evidence_slice']['physical_contexts']),
                         {'IRQ:slot:16', 'IRQ:slot:17'})

    def test_assembly_nmi_is_not_masked_by_primask(self):
        value, facts = self.scan_assembly('''static unsigned value;
            void custom(void) { value++; } void reset(void) {}
            void __disable_irq(void); void __enable_irq(void);
            int main(void) { __disable_irq(); value++; __enable_irq(); return 0; }''', '''
            .section .isr_vector
            .word _estack, reset, custom
        ''')
        self.assertEqual(value['static_classification'], 'SUSPECT', value)
        self.assertNotEqual(value['protection_status'], 'EFFECTIVE')

    def test_unsupported_assembly_repetition_cannot_turn_irq_into_reset(self):
        value, facts = self.scan_assembly('''static unsigned value;
            void custom(void) { value++; }
            int main(void) { return 0; }''', '''
            .section .isr_vector
            .rept 16
            .word 0
            .endr
            .word custom
        ''')
        self.assertEqual(value['static_classification'], 'UNKNOWN', value)
        self.assertIn('UNKNOWN_EXECUTION_CONTEXT', value['unknown_reason_codes'])
        self.assertFalse(facts['vector_entries'])

    def test_unknown_table_layout_blocks_even_a_conventional_handler(self):
        value, facts = self.scan_assembly('''static unsigned value;
            void TIM4_IRQHandler(void) { value++; }
            int main(void) { return 0; }''', '''
            .section .vectors
            .word _estack
            .rept 17
            .word TIM4_IRQHandler
            .endr
        ''')
        self.assertEqual(value['static_classification'], 'UNKNOWN', value)
        self.assertTrue(any(g['kind'] == 'UNRESOLVED_VECTOR_ENTRY' for g in value['blocking_evidence']))

    def test_dynamic_c_vector_slot_is_an_unknown_entry(self):
        value, facts = self.scan('''typedef void (*handler)(void);static unsigned value;
            static void custom(void) { value++; }
            static handler vectors[32] __attribute__((section(".vectors"),used));
            int main(int index) { vectors[index] = custom; return 0; }''')
        self.assertEqual(value['static_classification'], 'UNKNOWN', value)
        self.assertTrue(any(g['kind'] == 'UNRESOLVED_VECTOR_ENTRY' for g in value['blocking_evidence']))


if __name__ == '__main__':
    unittest.main()
