"""Branch isolation and deepcopy equivalence for optimized NVIC state copies."""
import copy
import unittest

from ecra.nvic import copy_state


class NvicStateCopyTests(unittest.TestCase):
    def state(self):
        return dict(mem={'handle': '@device', 'value': 17, 0xE000ED0C: None},
                    priority={2: 3}, enabled={2: True}, masks={'BASEPRI': 32},
                    group=3, opaque=False, incomplete_flow=False)

    def test_scalar_tables_are_equal_and_independently_mutable(self):
        state = self.state()
        branch = copy_state(state)
        self.assertEqual(branch, copy.deepcopy(state))
        for name in ('mem', 'priority', 'enabled', 'masks'):
            self.assertIsNot(branch[name], state[name])
            branch[name]['changed'] = 1
            self.assertNotIn('changed', state[name])

    def test_extended_mutable_values_and_nested_exits_keep_deepcopy_semantics(self):
        state = self.state()
        shared = dict(values=[1, 2])
        state['mem']['extension'] = shared
        state['extension'] = shared
        exit_state = self.state()
        exit_state['mem'] = state['mem']
        state['possible_exits'] = [exit_state]
        branch = copy_state(state)
        self.assertEqual(branch, copy.deepcopy(state))
        self.assertIs(branch['extension'], branch['mem']['extension'])
        self.assertIs(branch['mem'], branch['possible_exits'][0]['mem'])
        branch['extension']['values'].append(3)
        self.assertEqual(shared['values'], [1, 2])

    def test_shared_tables_and_state_cycles_are_preserved_inside_the_copy(self):
        state = self.state()
        state['priority'] = state['mem']
        state['possible_exits'] = [state]
        branch = copy_state(state)
        self.assertIs(branch['priority'], branch['mem'])
        self.assertIs(branch['possible_exits'][0], branch)
        self.assertIsNot(branch['mem'], state['mem'])


if __name__ == '__main__':
    unittest.main()
