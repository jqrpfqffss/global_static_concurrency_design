"""Architectural mask behavior follows the physical vector, not C spelling."""
import unittest

from tests import test_ecra as fixtures


class ExceptionMaskTests(unittest.TestCase):
    setUp = fixtures.ProjectTest.setUp
    project = fixtures.ProjectTest.project
    extract = fixtures.ProjectTest.extract

    def scan(self, context, mask='__disable_irq();', handler='ExceptionRoute'):
        cfg = self.project({'main.c': '''
            int shared;
            void __disable_irq(void); void __enable_irq(void);
            void __set_FAULTMASK(unsigned); void __set_BASEPRI(unsigned);
            void ''' + handler + '''(void) { shared++; }
            int main(void) { ''' + mask + ''' shared++; return 0; }
        '''}, contexts=[dict(id='main', kind='MAIN', functions=['main']),
                        dict(id='exception', kind='ISR', functions=[handler], **context)])
        facts, _ = self.extract(cfg)
        return next(v for v in facts['variables'] if v['name'] == 'shared')

    def test_primask_cannot_mask_configured_nmi_or_hardfault_alias(self):
        for vector in ('NMI_Handler', 'HardFault_Handler', 'slot:2', 'slot:3',
                       'NonMaskableInt_IRQn', 'HardFault_IRQn'):
            with self.subTest(vector=vector):
                value = self.scan(dict(vector=vector))
                self.assertEqual(value['static_classification'], 'SUSPECT')
                self.assertNotEqual(value['protection_status'], 'EFFECTIVE')
                self.assertTrue(value['conflict_pairs'])

    def test_primask_cannot_mask_system_exception_irq_number(self):
        for irq in (-14, -13):
            with self.subTest(irq=irq):
                value = self.scan(dict(irq=irq))
                self.assertEqual(value['static_classification'], 'SUSPECT')

    def test_positive_external_irq_number_is_not_an_abi_slot(self):
        for irq in (2, 3):
            with self.subTest(irq=irq):
                value = self.scan(dict(irq=irq))
                self.assertEqual(value['static_classification'], 'SAFE_PROVEN')
                self.assertEqual(value['protection_status'], 'EFFECTIVE')

    def test_faultmask_still_cannot_mask_nmi_alias(self):
        for context in (dict(vector='NMI_Handler'), dict(vector='slot:2'), dict(irq=-14)):
            with self.subTest(context=context):
                value = self.scan(context, '__set_FAULTMASK(1);')
                self.assertEqual(value['static_classification'], 'SUSPECT')
                self.assertNotEqual(value['protection_status'], 'EFFECTIVE')

    def test_basepri_cannot_make_fixed_exception_safe(self):
        for vector in ('NMI_Handler', 'HardFault_Handler', 'slot:2', 'slot:3'):
            with self.subTest(vector=vector):
                value = self.scan(dict(vector=vector), '__set_BASEPRI(0x50);')
                self.assertEqual(value['static_classification'], 'SUSPECT')
                self.assertNotEqual(value['protection_status'], 'EFFECTIVE')

    def test_ordinary_irq_protection_and_unmaskable_override_remain_distinct(self):
        for mask in ('__disable_irq();', '__set_FAULTMASK(1);'):
            with self.subTest(mask=mask):
                value = self.scan(dict(vector='TIM2_IRQHandler'), mask)
                self.assertEqual(value['static_classification'], 'SAFE_PROVEN')
                value = self.scan(dict(vector='TIM2_IRQHandler', unmaskable=True), mask)
                self.assertEqual(value['static_classification'], 'SUSPECT')

    def test_recovered_vector_table_preserves_custom_exception_identity(self):
        for slot in (2, 3):
            with self.subTest(slot=slot):
                cfg = self.project({'main.c': '''
                    typedef void (*handler)(void);
                    int shared; void __disable_irq(void);
                    void ExceptionRoute(void) { shared++; }
                    const handler vectors[4] __attribute__((section(".isr_vector"),used)) =
                        {[''' + str(slot) + ''']=ExceptionRoute};
                    int main(void) { __disable_irq(); shared++; return 0; }
                '''}, contexts=[dict(id='main', kind='MAIN', functions=['main'])])
                facts, _ = self.extract(cfg)
                value = next(v for v in facts['variables'] if v['name'] == 'shared')
                self.assertEqual(value['static_classification'], 'SUSPECT')
                self.assertTrue(any(c.get('slot') == slot and c.get('unmaskable')
                                    for c in facts['contexts']))


if __name__ == '__main__':
    unittest.main()
