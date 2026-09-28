"""Physical callers must not exchange their helper's pointer arguments."""
import unittest

from tests import test_ecra as fixtures


class CallsiteSensitivityTests(unittest.TestCase):
    setUp = fixtures.ProjectTest.setUp
    project = fixtures.ProjectTest.project
    extract = fixtures.ProjectTest.extract

    def scan(self, source):
        cfg = self.project({'a.c': source}, contexts=[dict(id='main', kind='MAIN', functions=['main'])])
        return self.extract(cfg)

    def test_different_irq_arguments_do_not_create_cross_handle_writers(self):
        facts, _ = self.scan('''
            typedef struct { unsigned state; } Device;
            static Device first, second;
            static void Update(Device *device) { device->state++; }
            void USART1_IRQHandler(void) { Update(&first); }
            void USART2_IRQHandler(void) { Update(&second); }
            int main(void) { return 0; }
        ''')
        for name in ('first.state', 'second.state'):
            variable = next(v for v in facts['variables'] if v['qualified_name'] == name)
            self.assertEqual(variable['static_classification'], 'SAFE', variable)
            self.assertEqual(variable['safe_reason_code'], 'SAFE_SINGLE_IRQ')
            self.assertEqual(len(variable['writers']), 1)

    def test_same_object_passed_by_two_irqs_still_conflicts(self):
        facts, _ = self.scan('''
            typedef struct { unsigned state; } Device;
            static Device shared;
            static void Update(Device *device) { device->state++; }
            void USART1_IRQHandler(void) { Update(&shared); }
            void USART2_IRQHandler(void) { Update(&shared); }
            int main(void) { return 0; }
        ''')
        variable = next(v for v in facts['variables'] if v['qualified_name'] == 'shared.state')
        self.assertEqual(variable['static_classification'], 'SUSPECT')
        self.assertEqual(len(variable['writers']), 2)

    def test_local_alias_and_return_wrapper_keep_calling_irq_identity(self):
        facts, _ = self.scan('''
            typedef struct { unsigned state; } Device;
            static Device first, second;
            static Device *Forward(Device *device) { return device; }
            static void Update(Device *device) { Device *local=Forward(device); local->state++; }
            void USART1_IRQHandler(void) { Update(&first); }
            void USART2_IRQHandler(void) { Update(&second); }
            int main(void) { return 0; }
        ''')
        for name in ('first.state', 'second.state'):
            variable = next(v for v in facts['variables'] if v['qualified_name'] == name)
            self.assertEqual(variable['static_classification'], 'SAFE', variable)
            self.assertEqual(variable['safe_reason_code'], 'SAFE_SINGLE_IRQ')
            self.assertEqual(len(variable['writers']), 1)

    def test_main_registered_pointer_remains_shared_with_irq(self):
        facts, _ = self.scan('''
            typedef struct { unsigned state; } Device;
            static Device shared; static Device *registered;
            static void Install(Device *device) { registered=device; }
            static void Update(Device *device) { device->state++; }
            void USART1_IRQHandler(void) { Update(registered); }
            int main(void) { Install(&shared); Update(&shared); return 0; }
        ''')
        variable = next(v for v in facts['variables'] if v['qualified_name'] == 'shared.state')
        self.assertEqual(variable['static_classification'], 'SUSPECT')
        self.assertEqual(len(variable['writers']), 2)

    def test_callback_parameter_guard_keeps_only_its_matching_irq(self):
        facts, _ = self.scan('''
            typedef struct { unsigned state; } Device;
            static Device first, second; static unsigned completed;
            static void Complete(Device *device) { if (device == &second) completed++; }
            static void Dispatch(Device *device) { Complete(device); }
            void USART1_IRQHandler(void) { Dispatch(&first); }
            void USART2_IRQHandler(void) { Dispatch(&second); }
            int main(void) { return 0; }
        ''')
        variable = next(v for v in facts['variables'] if v['name'] == 'completed')
        self.assertEqual(variable['static_classification'], 'SAFE', variable)
        self.assertEqual(variable['safe_reason_code'], 'SAFE_SINGLE_IRQ')
        self.assertEqual(len(variable['writers']), 1)
        self.assertIn('USART2', variable['writers'][0])

    def test_else_arm_of_inequality_has_the_same_disjointness_proof(self):
        facts, _ = self.scan('''
            typedef struct { unsigned state; } Device;
            static Device first, second; static unsigned completed;
            static void Complete(Device *device) { if (device != &second) {} else completed++; }
            void USART1_IRQHandler(void) { Complete(&first); }
            void USART2_IRQHandler(void) { Complete(&second); }
            int main(void) { return 0; }
        ''')
        variable = next(v for v in facts['variables'] if v['name'] == 'completed')
        self.assertEqual(variable['static_classification'], 'SAFE', variable)
        self.assertEqual(variable['safe_reason_code'], 'SAFE_SINGLE_IRQ')

    def test_opaque_pointer_in_other_irq_does_not_taint_known_private_target(self):
        facts, _ = self.scan('''
            static unsigned value; unsigned *Opaque(void);
            static void Update(unsigned *pointer) { (*pointer)++; }
            void USART1_IRQHandler(void) { Update(&value); }
            void USART2_IRQHandler(void) { Update(Opaque()); }
            int main(void) { return 0; }
        ''')
        variable = next(v for v in facts['variables'] if v['name'] == 'value')
        self.assertEqual(variable['static_classification'], 'SAFE', variable)
        self.assertEqual(variable['safe_reason_code'], 'SAFE_SINGLE_IRQ')

    def test_known_and_opaque_pointer_in_same_irq_keeps_relevant_gap(self):
        facts, _ = self.scan('''
            static unsigned value; unsigned *Opaque(void);
            static void Update(unsigned *pointer) { (*pointer)++; }
            void USART1_IRQHandler(void) { Update(&value); Update(Opaque()); }
            int main(void) { return 0; }
        ''')
        variable = next(v for v in facts['variables'] if v['name'] == 'value')
        self.assertEqual(variable['static_classification'], 'UNKNOWN', variable)
        self.assertIn('UNKNOWN_RELEVANT_ALIAS', variable['unknown_reason_codes'])

    def test_null_alternative_cannot_be_erased_by_singleton_may_target(self):
        facts, _ = self.scan('''
            typedef struct { unsigned state; } Device;
            static Device first; static unsigned completed;
            static void Complete(Device *device) { if (device != &first) completed++; }
            void USART1_IRQHandler(void) { Complete(&first); Complete((Device *)0); }
            int main(void) { completed++; return 0; }
        ''')
        variable = next(v for v in facts['variables'] if v['name'] == 'completed')
        self.assertEqual(variable['static_classification'], 'SUSPECT', variable)

    def test_parameter_address_escape_disables_guard_proof(self):
        facts, _ = self.scan('''
            typedef struct { unsigned state; } Device;
            static Device first, second; static unsigned completed; void Change(Device **);
            static void Complete(Device *device) { Change(&device); if (device == &second) completed++; }
            void USART1_IRQHandler(void) { Complete(&first); }
            void USART2_IRQHandler(void) { Complete(&second); }
            int main(void) { return 0; }
        ''')
        variable = next(v for v in facts['variables'] if v['name'] == 'completed')
        self.assertEqual(variable['static_classification'], 'SUSPECT', variable)


if __name__ == '__main__':
    unittest.main()
