"""Physical IRQ entry recovery from Cortex-M vector storage."""
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


if __name__ == '__main__':
    unittest.main()
