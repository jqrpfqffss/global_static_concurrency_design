import unittest
from unittest.mock import patch

from ecra.interrupts import basepri_status, context_priorities


class InterruptPriorityTests(unittest.TestCase):
    def test_empty_model_keeps_every_entry_unresolved(self):
        facts = dict(functions=[dict(function_id=str(i), name=f'TIM{i}_IRQHandler')
                                for i in range(50000)],
                     contexts=[dict(id='irq')],
                     context_bindings=[dict(call_depth=0, context_id='irq', function_id='3')])
        self.assertEqual(context_priorities(facts, {}), {})

    def test_empty_model_cannot_prove_a_nonzero_basepri_mask(self):
        facts = dict(functions=[], contexts=[dict(id='irq', vector='slot:42')],
                     context_bindings=[dict(call_depth=0, context_id='irq', function_id='missing')])
        with patch('ecra.interrupts.priority_model', return_value=({}, '优先级证据未恢复。')):
            status, reason = basepri_status([dict(basepri_known=True, basepri_values=[128])],
                                           {'irq'}, facts, {})
        self.assertEqual(status, 'UNRESOLVED')
        self.assertIn('无法恢复', reason)

    def test_nonempty_model_requires_consistent_priorities_for_all_bindings(self):
        high, low = dict(logical=1, preemption=1), dict(logical=3, preemption=3)
        facts = dict(functions=[dict(function_id='a', name='TIM1_IRQHandler'),
                                dict(function_id='b', name='TIM2_IRQHandler')],
                     contexts=[dict(id='irq')], context_bindings=[
                         dict(call_depth=0, context_id='irq', function_id='a'),
                         dict(call_depth=0, context_id='irq', function_id='b')])
        self.assertEqual(context_priorities(facts, {'TIM1': high, 'TIM2': low}), {})
        self.assertEqual(context_priorities(facts, {'TIM1': high, 'TIM2': high}), {'irq': high})


if __name__ == '__main__':
    unittest.main()
