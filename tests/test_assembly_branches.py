"""Literal ARM bootstrap branches inherit their caller's physical context."""
import unittest
from tests import test_preopencode_classification as fixtures


class AssemblyBranchTests(unittest.TestCase):
    setUp = fixtures.PreOpenCodeClassificationTests.setUp
    project = fixtures.PreOpenCodeClassificationTests.project
    extract = fixtures.PreOpenCodeClassificationTests.extract
    scan = fixtures.PreOpenCodeClassificationTests.scan
    variable = fixtures.PreOpenCodeClassificationTests.variable
    assert_classified = fixtures.PreOpenCodeClassificationTests.assert_classified

    def test_void_bootstrap_branch_is_foreground(self):
        self.scan('''static unsigned value;
            static void Stage(void) { value++; }
            int main(void) { __asm volatile("bx %0" : : "r"(Stage)); return 0; }
        ''')
        self.assert_classified('value','SAFE','SAFE_SINGLE_FOREGROUND')
        self.assertTrue(any(c.get('implicit_call')=='ARM_LITERAL_BRANCH'
                            for c in self.facts['semantic_calls']))

    def test_branch_in_irq_inherits_irq(self):
        self.scan('''static unsigned value;
            static void Stage(void) { value++; }
            void TIM4_IRQHandler(void) { __asm volatile("bx %0" : : "r"(Stage)); }
            int main(void) { return 0; }
        ''')
        self.assert_classified('value','SAFE','SAFE_SINGLE_IRQ')

    def test_extra_data_use_of_function_address_stays_opaque(self):
        self.scan('''static unsigned value;
            static void Stage(void) { value++; }
            int main(void) { __asm volatile("str %0, [r1]\\n bx %0" : : "r"(Stage)); return 0; }
        ''')
        self.assert_classified('value','UNKNOWN','UNKNOWN_EXECUTION_CONTEXT')

    def test_pointer_return_is_not_hidden_from_opaque_assembly(self):
        self.scan('''static unsigned value;
            static unsigned *Getter(void) { return &value; }
            int main(void) { __asm volatile("blx %0" : : "r"(Getter)); return 0; }
        ''')
        self.assert_classified('value','UNKNOWN','UNKNOWN_INLINE_ASM')


if __name__ == '__main__':
    unittest.main()
