"""Initialization proof adversaries: actual Clang CFG, never source ordering."""
import unittest

from tests import test_ecra as fixtures
from ecra.initialization import prove_initialization
from ecra.evidence import VariableEvidenceSlice, classify


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

    def test_writer_loop_stays_in_init_phase_before_enable(self):
        self.check('NVIC_DisableIRQ(TIM4_IRQn); while (value < 3) { value++; } '
                   'NVIC_EnableIRQ(TIM4_IRQn); return value;', True)

    def test_conditional_writer_is_still_before_enable_on_every_write_path(self):
        self.check('NVIC_DisableIRQ(TIM4_IRQn); if (condition) { value = 7; } '
                   'NVIC_EnableIRQ(TIM4_IRQn); return value;', True, extra='extern int condition;')

    def test_conditional_disable_does_not_dominate_writer(self):
        self.check('if (condition) { NVIC_DisableIRQ(TIM4_IRQn); } value = 7; '
                   'NVIC_EnableIRQ(TIM4_IRQn); return value;', False, extra='extern int condition;')

    def test_conditional_enable_is_safe_when_disabled_branch_never_runs_irq(self):
        self.check('NVIC_DisableIRQ(TIM4_IRQn); value = 7; '
                   'if (condition) { NVIC_EnableIRQ(TIM4_IRQn); } return value;', True,
                   extra='extern int condition;')

    def test_unknown_irq_enable_is_not_assumed_unrelated(self):
        self.check('NVIC_DisableIRQ(TIM4_IRQn); NVIC_EnableIRQ(dynamic_irq); value = 7; '
                   'NVIC_EnableIRQ(TIM4_IRQn); return value;', False, extra='extern int dynamic_irq;')

    def test_other_enabled_irq_may_activate_the_target(self):
        self.check('NVIC_DisableIRQ(TIM4_IRQn); NVIC_EnableIRQ(USART1_IRQn); value = 7; '
                   'NVIC_EnableIRQ(TIM4_IRQn); return value;', False,
                   extra='void USART1_IRQHandler(void) { NVIC_EnableIRQ(TIM4_IRQn); }')

    def test_nmi_opaque_call_may_activate_target_before_write(self):
        self.check('NVIC_DisableIRQ(TIM4_IRQn); value = 7; '
                   'NVIC_EnableIRQ(TIM4_IRQn); return value;', False,
                   extra='void Opaque(void); void NMI_Handler(void) { Opaque(); }')

    def test_other_foreground_root_can_reinvoke_init_helper(self):
        source = '''
            enum { TIM4_IRQn = 30 };
            void NVIC_EnableIRQ(int); void NVIC_DisableIRQ(int);
            static unsigned value;
            static void Init(void) { value = 7; }
            void TIM4_IRQHandler(void) { (void)value; }
            void Later(void) { Init(); }
            int main(void) { NVIC_DisableIRQ(TIM4_IRQn); Init();
                             NVIC_EnableIRQ(TIM4_IRQn); return value; }
        '''
        cfg = self.project({'main.c': source}, contexts=[
            dict(id='main', kind='MAIN', functions=['main', 'Later'])])
        facts, _ = self.extract(cfg)
        variable = next(row for row in facts['variables'] if row['name'] == 'value')
        contexts = {row['id']: row for row in facts['contexts']}
        self.assertIsNone(prove_initialization(variable, variable['accesses'], facts, contexts, cfg))
        self.assertNotEqual('SAFE_PROVEN', variable['static_classification'])

    def test_configured_call_without_cfg_site_can_reinvoke_writer(self):
        source = '''
            enum { TIM4_IRQn = 30 };
            void NVIC_EnableIRQ(int); void NVIC_DisableIRQ(int);
            static unsigned value;
            static void Init(void) { value = 7; }
            static void Runtime(void) { }
            void TIM4_IRQHandler(void) { (void)value; }
            int main(void) { NVIC_DisableIRQ(TIM4_IRQn); Init();
                             NVIC_EnableIRQ(TIM4_IRQn); Runtime(); return value; }
        '''
        cfg = self.project({'main.c': source}, contexts=[
            dict(id='main', kind='MAIN', functions=['main'])])
        cfg['call_edges'] = [dict(caller='Runtime', callee='Init')]
        facts, _ = self.extract(cfg)
        variable = next(row for row in facts['variables'] if row['name'] == 'value')
        contexts = {row['id']: row for row in facts['contexts']}
        self.assertIsNone(prove_initialization(variable, variable['accesses'], facts, contexts, cfg))
        self.assertNotEqual('SAFE_PROVEN', variable['static_classification'])

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

    def test_helper_write_inherits_the_callers_init_phase(self):
        self.check('NVIC_DisableIRQ(TIM4_IRQn); Initialize(); '
                   'NVIC_EnableIRQ(TIM4_IRQn); return value;', True,
                   extra='static void Initialize(void) { value = 7; }')

    def test_enable_inside_known_helper_closes_init_phase(self):
        self.check('NVIC_DisableIRQ(TIM4_IRQn); value = 7; Enable(); return value;', True,
                   extra='static void Enable(void) { NVIC_EnableIRQ(TIM4_IRQn); }')

    def test_verified_reset_vector_supplies_initial_disabled_state(self):
        source = '''
            enum { TIM4_IRQn = 30 };
            void NVIC_EnableIRQ(int);
            static unsigned value;
            void TIM4_IRQHandler(void) { (void)value; }
            int main(void) { value=7; NVIC_EnableIRQ(TIM4_IRQn); while (1) { (void)value; } }
            void Reset_Handler(void) { (void)main(); }
            typedef void (*handler_t)(void);
            handler_t vectors[17] __attribute__((section(".isr_vector"))) = {
                [1]=Reset_Handler, [16]=TIM4_IRQHandler
            };
        '''
        cfg = self.project({'main.c': source}, contexts=[dict(id='main', kind='MAIN', functions=['main'])])
        facts, _ = self.extract(cfg)
        variable = next(variable for variable in facts['variables'] if variable['name'] == 'value')
        self.assertEqual(variable['static_classification'], 'SAFE_PROVEN', variable)
        self.assertEqual(variable['safe_reason_code'], 'SAFE_INIT_ONLY_WRITE', variable)
        proof = variable['initialization_proof']
        self.assertEqual(proof['proof'], 'INIT_WRITES_BEFORE_ASYNC_ENABLE')
        self.assertIn('reset vector', proof['initial_state_evidence'])

    def test_init_proof_preserves_uncovered_runtime_writer_conflict(self):
        evidence = VariableEvidenceSlice('v', 'value', {}, 'INTERNAL')
        contexts = {
            'main': dict(physical_kind='FOREGROUND', physical_id='FOREGROUND'),
            'irq_a': dict(physical_kind='IRQ', physical_id='IRQ:A'),
            'irq_b': dict(physical_kind='IRQ', physical_id='IRQ:B'),
        }
        accesses = [
            dict(access_id='init', access_kind='WRITE', contexts=['main']),
            dict(access_id='a', access_kind='WRITE', contexts=['irq_a']),
            dict(access_id='b', access_kind='WRITE', contexts=['irq_b']),
        ]

        def pair(left, right):
            return dict(participant_a=dict(access_id=left['access_id'], context_id=left['contexts'][0]),
                        participant_b=dict(access_id=right['access_id'], context_id=right['contexts'][0]),
                        relation=dict(relation='UNKNOWN_PREEMPTION'), mhp='MAYBE',
                        may_concurrent=True, has_write_conflict=True)

        pairs = [pair(accesses[0], accesses[1]), pair(accesses[1], accesses[2])]
        verdict = classify(evidence, accesses, contexts, pairs, 'NOT_FOUND', '',
                           init_proof=dict(write_access_ids=['init']),
                           variable=dict(canonical_path='value'), cfg={})
        self.assertEqual('SUSPECT', verdict['static_classification'])
        self.assertFalse(pairs[0]['may_concurrent'])
        self.assertTrue(pairs[1]['may_concurrent'])


if __name__ == '__main__':
    unittest.main()
