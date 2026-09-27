"""Initialization proof adversaries: actual Clang CFG, never source ordering."""
import unittest

from tests import test_ecra as fixtures
from ecra.initialization import prove_initialization


class InitializationPhaseTests(unittest.TestCase):
    setUp = fixtures.ProjectTest.setUp
    project = fixtures.ProjectTest.project
    extract = fixtures.ProjectTest.extract

    def check(self, body, expected, *, extra='', handler='TIM4_IRQHandler'):
        source = '''
            enum { TIM4_IRQn = 30, USART1_IRQn = 37 };
            void NVIC_EnableIRQ(int); void NVIC_DisableIRQ(int);
            static unsigned value;
            void HANDLER(void) { (void)value; }
            EXTRA
            int main(void) { BODY }
        '''.replace('HANDLER', handler).replace('EXTRA', extra).replace('BODY', body)
        cfg = self.project({'main.c': source}, contexts=[dict(id='main', kind='MAIN', functions=['main'])])
        facts, _ = self.extract(cfg)
        variable = next(variable for variable in facts['variables'] if variable['name'] == 'value')
        contexts = {context['id']: context for context in facts['contexts']}
        proof = prove_initialization(variable, variable['accesses'], facts, contexts, cfg)
        self.assertEqual(proof is not None, expected, proof)
        if proof:
            self.assertTrue(proof['write_access_ids'])
            self.assertTrue(proof['irq_barriers'])
            self.assertTrue(proof['cfg_id'])
        return variable, proof

    def test_disable_write_enable_and_read_only_runtime_loop(self):
        self.check('NVIC_DisableIRQ(TIM4_IRQn); value = 7; NVIC_EnableIRQ(TIM4_IRQn); '
                   'while (1) { (void)value; }', True)

    def test_write_after_enable_is_not_initialization(self):
        self.check('NVIC_DisableIRQ(TIM4_IRQn); NVIC_EnableIRQ(TIM4_IRQn); value = 7; return value;', False)

    def test_main_is_not_proof_of_initially_disabled_irq(self):
        self.check('value = 7; NVIC_EnableIRQ(TIM4_IRQn); return value;', False)

    def test_writer_loop_rejects_even_if_textually_before_enable(self):
        self.check('NVIC_DisableIRQ(TIM4_IRQn); while (value < 3) { value++; } '
                   'NVIC_EnableIRQ(TIM4_IRQn); return value;', False)

    def test_conditional_writer_does_not_dominate_enable(self):
        self.check('NVIC_DisableIRQ(TIM4_IRQn); if (condition) { value = 7; } '
                   'NVIC_EnableIRQ(TIM4_IRQn); return value;', False, extra='extern int condition;')

    def test_conditional_disable_does_not_dominate_writer(self):
        self.check('if (condition) { NVIC_DisableIRQ(TIM4_IRQn); } value = 7; '
                   'NVIC_EnableIRQ(TIM4_IRQn); return value;', False, extra='extern int condition;')

    def test_conditional_enable_does_not_prove_unique_phase_boundary(self):
        self.check('NVIC_DisableIRQ(TIM4_IRQn); value = 7; '
                   'if (condition) { NVIC_EnableIRQ(TIM4_IRQn); } return value;', False,
                   extra='extern int condition;')

    def test_unknown_irq_enable_is_not_assumed_unrelated(self):
        self.check('NVIC_DisableIRQ(TIM4_IRQn); NVIC_EnableIRQ(dynamic_irq); value = 7; '
                   'NVIC_EnableIRQ(TIM4_IRQn); return value;', False, extra='extern int dynamic_irq;')

    def test_unknown_call_in_initialization_prefix_rejects_proof(self):
        self.check('NVIC_DisableIRQ(TIM4_IRQn); HardwareSetup(); value = 7; '
                   'NVIC_EnableIRQ(TIM4_IRQn); return value;', False, extra='void HardwareSetup(void);')

    def test_peripheral_pointer_store_can_enable_hardware(self):
        self.check('NVIC_DisableIRQ(TIM4_IRQn); *(volatile unsigned *)0xE000E100 = 1; '
                   'value = 7; NVIC_EnableIRQ(TIM4_IRQn); return value;', False)

    def test_systick_cannot_be_proven_by_nvic_external_irq_switch(self):
        self.check('NVIC_DisableIRQ(TIM4_IRQn); value = 7; '
                   'NVIC_EnableIRQ(TIM4_IRQn); return value;', False, handler='SysTick_Handler')

    def test_nmi_is_not_disabled_by_nvic_api(self):
        self.check('NVIC_DisableIRQ(TIM4_IRQn); value = 7; '
                   'NVIC_EnableIRQ(TIM4_IRQn); return value;', False, handler='NMI_Handler')

    def test_every_competing_irq_needs_disabled_phase(self):
        self.check('NVIC_DisableIRQ(TIM4_IRQn); value = 7; '
                   'NVIC_EnableIRQ(TIM4_IRQn); return value;', False,
                   extra='void USART1_IRQHandler(void) { (void)value; }')

    def test_two_competing_irqs_have_explicit_boundaries(self):
        self.check('NVIC_DisableIRQ(TIM4_IRQn); NVIC_DisableIRQ(USART1_IRQn); value = 7; '
                   'NVIC_EnableIRQ(TIM4_IRQn); NVIC_EnableIRQ(USART1_IRQn); return value;', True,
                   extra='void USART1_IRQHandler(void) { (void)value; }')

    def test_helper_write_is_outside_initial_supported_proof(self):
        self.check('NVIC_DisableIRQ(TIM4_IRQn); Initialize(); '
                   'NVIC_EnableIRQ(TIM4_IRQn); return value;', False,
                   extra='static void Initialize(void) { value = 7; }')


if __name__ == '__main__':
    unittest.main()
