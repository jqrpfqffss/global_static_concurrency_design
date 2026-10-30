"""Getter-returned snapshots and derived parameter writes retain value flow."""
import unittest

from tests import test_ecra


class StaleReturnValueTests(unittest.TestCase):
    setUp = test_ecra.ProjectTest.setUp
    project = test_ecra.ProjectTest.project
    extract = test_ecra.ProjectTest.extract

    def hints(self, sources, name='shared'):
        cfg = self.project(sources)
        facts, _ = self.extract(cfg)
        variable = next(v for v in facts['variables'] if v['qualified_name'] == name)
        return variable.get('concurrency_hints', [])

    def test_getter_to_derived_store_across_translation_units(self):
        hints = self.hints({
            'read.c': 'unsigned shared;unsigned Snapshot(void){return shared;}',
            'app.c': '''extern unsigned shared;unsigned Snapshot(void);
                void __disable_irq(void);void __enable_irq(void);
                static void Commit(unsigned old){__disable_irq();shared=old+1;__enable_irq();}
                void Task(void){Commit(Snapshot());}void ISR(void){shared+=100;}''',
        })
        self.assertEqual(len(hints), 1)
        self.assertEqual(hints[0]['read_site']['file'], 'read.c')
        self.assertEqual(hints[0]['write_site']['file'], 'app.c')
        self.assertEqual(hints[0]['read_contexts'], ['task'])
        self.assertTrue(hints[0]['derived_value'])
        self.assertGreaterEqual(len(hints[0]['read_return_path']), 2)

    def test_nested_getters_and_parameter_forwarding(self):
        hints = self.hints({'a.c': '''unsigned shared;
            unsigned Read(void){return shared;}unsigned Read2(void){return Read();}
            void Store(unsigned x){shared=x;}void Forward(unsigned x){Store(x+2);}
            void Task(void){Forward(Read2());}void ISR(void){shared++;}'''})
        self.assertEqual(len(hints), 1)
        self.assertEqual(len(hints[0]['read_return_path']), 3)
        self.assertTrue(hints[0]['derived_value'])

    def test_direct_read_with_constant_arithmetic_keeps_original_read(self):
        hints = self.hints({'a.c': '''unsigned shared;void Store(unsigned x){shared=x-1;}
            void Task(void){Store(shared+4);}void ISR(void){shared++;}'''})
        self.assertEqual(len(hints), 1)
        self.assertTrue(hints[0]['derived_value'])

    def test_different_storage_read_does_not_create_writeback(self):
        self.assertEqual(self.hints({'a.c': '''unsigned shared,other;
            unsigned Read(void){return other;}void Store(unsigned x){shared=x+1;}
            void Task(void){Store(Read());}void ISR(void){shared++;}'''}), [])

    def test_getter_that_does_not_return_read_value_is_not_a_source(self):
        self.assertEqual(self.hints({'a.c': '''volatile unsigned shared;
            unsigned Read(void){(void)shared;return 7;}void Store(unsigned x){shared=x;}
            void Task(void){Store(Read());}void ISR(void){shared++;}'''}), [])

    def test_overwritten_or_escaped_parameter_is_not_forwarded(self):
        for body in ('x=7;shared=x;', 'x++;shared=x;', 'void Touch(unsigned*);Touch(&x);shared=x;'):
            with self.subTest(body=body):
                self.assertEqual(self.hints({'a.c': '''unsigned shared;
                    unsigned Read(void){return shared;}void Store(unsigned x){''' + body + '''}
                    void Task(void){Store(Read());}void ISR(void){shared++;}'''}), [])

    def test_unresolved_getter_does_not_guess_which_storage_it_returns(self):
        self.assertEqual(self.hints({'a.c': '''unsigned shared;unsigned External(void);
            void Store(unsigned x){shared=x;}
            void Task(void){Store(External());}void ISR(void){shared++;}'''}), [])

    def test_recursive_getter_terminates_and_keeps_concrete_return(self):
        hints = self.hints({'a.c': '''unsigned shared;
            unsigned Read(void){if(shared)return shared;return Read();}
            void Store(unsigned x){shared=x;}
            void Task(void){Store(Read());}void ISR(void){shared++;}'''})
        self.assertEqual(len(hints), 1)

    def test_unreachable_return_is_not_a_source(self):
        self.assertEqual(self.hints({'a.c': '''unsigned shared;
            unsigned Read(void){if(0)return shared;return 7;}
            void Store(unsigned x){shared=x;}
            void Task(void){Store(Read());}void ISR(void){shared++;}'''}), [])


if __name__ == '__main__':
    unittest.main()
