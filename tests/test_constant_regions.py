"""Compile-time disabled branches must not create runtime aliases/entries."""
import unittest

from tests import test_preopencode_classification as fixtures


class ConstantRegionTests(unittest.TestCase):
    setUp = fixtures.PreOpenCodeClassificationTests.setUp
    project = fixtures.PreOpenCodeClassificationTests.project
    extract = fixtures.PreOpenCodeClassificationTests.extract
    scan = fixtures.PreOpenCodeClassificationTests.scan
    variable = fixtures.PreOpenCodeClassificationTests.variable
    assert_classified = fixtures.PreOpenCodeClassificationTests.assert_classified

    def test_disabled_external_escape_and_assembly_are_retained_as_pruned_evidence(self):
        self.scan('''
            static unsigned value;
            void Opaque(unsigned *);
            int main(void) {
                value++;
                if (0) { Opaque(&value); __asm volatile("" : : "r"(&value)); }
                return 0;
            }
        ''')
        self.assert_classified('value', 'SAFE', 'SAFE_SINGLE_FOREGROUND')
        removed = self.facts['constant_pruned_evidence']
        self.assertTrue(any(r['table']=='semantic_calls' and r['evidence'].get('inline_assembly') for r in removed))

    def test_enabled_else_branch_keeps_a_writer(self):
        self.scan('''static unsigned value;
            int main(void) { if (0) {} else { value++; } return 0; }
            void TIM4_IRQHandler(void) { (void)value; }
        ''')
        self.assert_classified('value', 'SUSPECT')

    def test_discarded_callback_registration_does_not_create_unknown_entry(self):
        self.scan('''static unsigned value;
            void Register(void (*p)(void));
            static void Work(void) { value++; }
            int main(void) { if (1) { Work(); } else { Register(Work); } return 0; }
        ''')
        self.assert_classified('value', 'SAFE', 'SAFE_SINGLE_FOREGROUND')

    def test_mutable_condition_does_not_remove_an_escape(self):
        self.scan('''static unsigned value; volatile const unsigned zero=0;
            void Opaque(unsigned *);
            int main(void) { if (zero) { Opaque(&value); } return 0; }
        ''')
        self.assert_classified('value', 'UNKNOWN', 'UNKNOWN_ADDRESS_ESCAPE')

    def test_goto_into_false_branch_preserves_the_access(self):
        self.scan('''static unsigned value;
            int main(void) { goto enter; if (0) { enter: value++; } return 0; }
            void TIM4_IRQHandler(void) { (void)value; }
        ''')
        self.assert_classified('value', 'SUSPECT')

    def test_case_label_inside_false_branch_preserves_the_access(self):
        self.scan('''static unsigned value;
            int main(void) { switch (1) { if (0) { case 1: value++; } } return 0; }
            void TIM4_IRQHandler(void) { (void)value; }
        ''')
        self.assert_classified('value', 'SUSPECT')

    def test_collapsed_macro_ranges_cannot_remove_neighboring_live_writes(self):
        self.scan('''static unsigned value;
            #define WORK() do { if (0) { (void)value; } value++; } while (0)
            int main(void) { WORK(); return 0; }
            void TIM4_IRQHandler(void) { (void)value; }
        ''')
        self.assert_classified('value', 'SUSPECT')

    def test_disabled_feature_and_runtime_flag_cannot_enable_an_escape(self):
        self.scan('''static unsigned value; volatile unsigned flags;
            void Opaque(unsigned *);
            int main(void) { if (0 && (flags & 1)) { Opaque(&value); } value++; return 0; }
        ''')
        self.assert_classified('value', 'SAFE', 'SAFE_SINGLE_FOREGROUND')

    def test_possible_logical_branch_keeps_an_escape(self):
        self.scan('''static unsigned value; volatile unsigned flags;
            void Opaque(unsigned *);
            int main(void) { if (0 || flags) { Opaque(&value); } return 0; }
        ''')
        self.assert_classified('value', 'UNKNOWN', 'UNKNOWN_ADDRESS_ESCAPE')

    def test_known_false_result_preserves_side_effects_in_the_condition(self):
        self.scan('''static unsigned value;
            void Opaque(unsigned *);
            static int Mutate(void) { value++; return 1; }
            int main(void) { if (Mutate() && 0) { Opaque(&value); } return 0; }
            void TIM4_IRQHandler(void) { (void)value; }
        ''')
        self.assert_classified('value', 'SUSPECT')

    def test_narrowing_cast_changes_the_condition_value(self):
        self.scan('''static unsigned value;
            int main(void) { if ((unsigned char)256) {} else { value++; } return 0; }
            void TIM4_IRQHandler(void) { (void)value; }
        ''')
        self.assert_classified('value', 'SUSPECT')


if __name__ == '__main__':
    unittest.main()
