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

    def test_macro_section_attribute_recovers_reset_and_irq(self):
        value, facts = self.scan('''
            #define PLACE(S) __attribute__((section(S)))
            #define VISIBLE __attribute__((externally_visible))
            typedef void (*handler)(void); static unsigned value;
            void reset(void) { value++; } void custom(void) { value++; }
            const handler table[18] VISIBLE PLACE(".vector_table") = {[1]=reset,[17]=custom};
            int main(void) { return 0; }
        ''')
        self.assertEqual(value['static_classification'], 'SUSPECT', value)
        self.assertEqual(set(value['variable_evidence_slice']['physical_contexts']), {'FOREGROUND','IRQ:slot:17'})

    def test_extern_before_definition_preserves_section_in_same_translation_unit(self):
        value, facts = self.scan('''
            #define PLACE(S) __attribute__((section(S)))
            typedef void (*handler)(void); extern const handler table[];
            static unsigned value; void custom(void) { value++; }
            const handler table[18] PLACE(".vector_table") = {[17]=custom};
            int main(void) { return value; }
        ''')
        self.assertEqual(value['static_classification'], 'SUSPECT', value)
        table = next(v for v in facts['variables'] if v['name']=='table')
        self.assertEqual(table['linker_section'], '.vector_table')
        self.assertEqual(table['array_size'], 18)

    def test_extern_merge_order_keeps_definition_metadata(self):
        import copy
        from ecra.analysis import merge
        declaration = dict(symbol_id='table',type='handler[]',is_array=True,array_element_type='handler',
            array_size=None,definition_file=None,definition_line=None,declarations=[],definitions=[],translation_units=['a.c'])
        definition = dict(declaration,type='handler[18]',array_size=18,definition_file='b.c',definition_line=3,
            linker_section='.vector_table',translation_units=['b.c'])
        for rows in ((declaration,definition),(definition,declaration)):
            facts = merge([dict(variables=[copy.deepcopy(row)]) for row in rows])
            self.assertEqual(facts['variables'][0]['linker_section'], '.vector_table')
            self.assertEqual(facts['variables'][0]['array_size'], 18)
            self.assertFalse(facts['unknowns'])

    def test_section_looking_initializer_is_not_a_vector_attribute(self):
        value, facts = self.scan('''static unsigned value;
            const char message[] __attribute__((used)) = "section(\\\".vectors\\\")";
            int main(void) { value++; return 0; }''')
        self.assertEqual(value['safe_reason_code'], 'SAFE_SINGLE_FOREGROUND')
        self.assertNotIn('linker_section', next(v for v in facts['variables'] if v['name']=='message'))

    def test_delimited_assembly_reset_calls_inherit_foreground(self):
        value, facts = self.scan_assembly('''static unsigned value;
            void Setup(void) { value++; }
            int main(void) { value++; return 0; }''', '''
            /* Boot calls main. Work is not referenced here. */
            .section .text.Boot
            .type Boot, %function
            Boot:
            bl Setup
            bl main @ Boot enters the application
            bx lr
            .size Boot, .-Boot
            .section .isr_vector
            .word _estack, Boot
        ''')
        self.assertEqual(value['safe_reason_code'], 'SAFE_SINGLE_FOREGROUND', value)
        self.assertTrue(any(c['call_kind']=='ASSEMBLY_LITERAL_CALL' for c in facts['calls']))

    def test_delimited_assembly_irq_call_adds_real_competing_context(self):
        value, facts = self.scan_assembly('''static unsigned value;
            void Work(void) { value++; }
            int main(void) { value++; return 0; }''', '''
            .section .text.Wrapper
            .type Wrapper, %function
            Wrapper:
            bl Work
            bx lr
            .size Wrapper, .-Wrapper
            .section .isr_vector
            .word _estack, 0
            .space 56
            .word Wrapper
        ''')
        self.assertEqual(value['static_classification'], 'SUSPECT', value)

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

    def test_resolved_vectors_do_not_disable_callback_parameter_guards(self):
        value, facts = self.scan_assembly('''static unsigned value;
            struct Device {int state;}; static struct Device first, second;
            static void Done(struct Device *p) { if (p == &second) value++; }
            void first_irq(void) { Done(&first); } void second_irq(void) { Done(&second); }
            void reset(void) {} int main(void) { return 0; }''', '''
            .section .isr_vector
            .word _estack, reset
            .space 56
            .word first_irq, second_irq
            .section .text
            .weak first_irq
            .thumb_set first_irq, Default_Handler
            .global second_irq
            .type second_irq, %function
        ''')
        self.assertEqual(value['safe_reason_code'], 'SAFE_SINGLE_IRQ', value)
        self.assertEqual(value['variable_evidence_slice']['physical_contexts'], ['IRQ:slot:17'])
        self.assertTrue(facts['resolved_assembly_references'])

    def test_additional_assembly_reference_to_known_irq_remains_unknown(self):
        value, facts = self.scan_assembly('''static unsigned value;
            void custom(void) { value++; } void reset(void) {}
            int main(void) { return 0; }''', '''
            .section .isr_vector
            .word _estack, reset
            .space 56
            .word custom
            .section .text
            bl custom
        ''')
        self.assertEqual(value['static_classification'], 'UNKNOWN', value)
        gaps = [g for g in value['blocking_evidence'] if g['kind']=='ASSEMBLY_FUNCTION_REFERENCE']
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0]['source_text'].strip(), 'bl custom')

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
