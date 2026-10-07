"""Nonlocal C continuations retain their real asynchronous source."""
import unittest

from tests import test_ecra


class NonlocalJumpTests(unittest.TestCase):
    setUp = test_ecra.ProjectTest.setUp
    project = test_ecra.ProjectTest.project
    extract = test_ecra.ProjectTest.extract

    def test_matching_jump_buffer_connects_irq_to_continuation_only(self):
        cfg = self.project({'a.c': '''
            typedef unsigned jmp_buf[8];
            int setjmp(jmp_buf); void longjmp(jmp_buf, int);
            static jmp_buf jump_state;
            static int shared, before, direct_after;
            static void before_jump(void) { before++; }
            static void on_resume(void) { shared++; }
            void ISR(void) { longjmp(jump_state, 1); }
            int main(void) {
                before_jump();
                if (setjmp(jump_state)) on_resume();
                direct_after++;
                shared++;
                return 0;
            }
        '''}, contexts=[dict(id='main', kind='MAIN', functions=['main']),
                        dict(id='irq', kind='ISR', functions=['ISR'])])
        facts, _ = self.extract(cfg)
        variables = {row['name']: row for row in facts['variables']}
        self.assertEqual('SUSPECT', variables['shared']['static_classification'])
        self.assertEqual({'FOREGROUND', 'IRQ:irq'},
                         set(variables['shared']['variable_evidence_slice']['physical_contexts']))
        self.assertEqual('SAFE_PROVEN', variables['before']['static_classification'])
        self.assertEqual('UNKNOWN', variables['direct_after']['static_classification'])
        self.assertIn('UNKNOWN_EXECUTION_CONTEXT', variables['direct_after']['unknown_reason_codes'])
        self.assertTrue(any(row['callee_name'] == 'on_resume'
                            for row in facts['nonlocal_jump_edges']))


if __name__ == '__main__':
    unittest.main()
