"""Variadic forwarding must not hide accesses to named storage."""
import unittest

from tests import test_ecra as fixtures


class VariadicPointerTests(unittest.TestCase):
    setUp = fixtures.ProjectTest.setUp
    project = fixtures.ProjectTest.project
    extract = fixtures.ProjectTest.extract

    def scan(self, body):
        header = '''typedef __builtin_va_list va_list;
#define va_start(a,last) __builtin_va_start(a,last)
#define va_arg(a,t) __builtin_va_arg(a,t)
#define va_copy(a,b) __builtin_va_copy(a,b)
#define va_end(a) __builtin_va_end(a)
'''
        cfg = self.project({'a.c': header + body}, contexts=[dict(id='main',kind='MAIN',functions=['main'])])
        facts, _ = self.extract(cfg)
        return {v['name']:v for v in facts['variables']}, facts

    def test_variadic_writer_is_a_known_conflict(self):
        variables, facts = self.scan('''
            static int value;
            static void Store(int tag, ...) { va_list ap; va_start(ap,tag); int *p=va_arg(ap,int*); *p=7; va_end(ap); }
            int main(void) { Store(0,&value); return 0; }
            void TIM4_IRQHandler(void) { value++; }
        ''')
        self.assertEqual(variables['value']['static_classification'], 'SUSPECT', variables['value'])
        self.assertTrue(any(a.get('via_alias') == 'interprocedural points-to' and a['access_kind']=='WRITE'
                            for a in variables['value']['accesses']))

    def test_old_style_function_definition_does_not_fail_the_translation_unit(self):
        variables, facts = self.scan('''
            static int value;
            void Work() { value++; }
            int main() { Work(); return value; }
        ''')
        self.assertEqual(variables['value']['safe_reason_code'], 'SAFE_SINGLE_FOREGROUND')
        self.assertFalse(any(f.get('is_variadic') for f in facts['functions']))

    def test_va_list_copy_and_helper_forwarding_keep_the_pointee(self):
        variables, facts = self.scan('''
            static int value;
            static void Forward(va_list incoming) { va_list copied; va_copy(copied,incoming); int *p=va_arg(copied,int*); *p=7; va_end(copied); }
            static void Store(int tag, ...) { va_list ap; va_start(ap,tag); Forward(ap); va_end(ap); }
            int main(void) { Store(0,&value); return 0; }
        ''')
        self.assertEqual(variables['value']['safe_reason_code'], 'SAFE_SINGLE_FOREGROUND', variables['value'])
        self.assertTrue(any(a['access_kind']=='WRITE' for a in variables['value']['accesses']))

    def test_variadic_arguments_remain_separate_between_irq_domains(self):
        variables, _ = self.scan('''
            static int first, second;
            static void Store(int tag, ...) { va_list ap; va_start(ap,tag); int *p=va_arg(ap,int*); *p=7; }
            void USART1_IRQHandler(void) { Store(0,&first); }
            void USART2_IRQHandler(void) { Store(0,&second); }
            int main(void) { return 0; }
        ''')
        for name in ('first','second'):
            self.assertEqual(variables[name]['safe_reason_code'], 'SAFE_SINGLE_IRQ', variables[name])

    def test_integer_encoded_variadic_pointer_keeps_a_writer(self):
        variables, _ = self.scan('''
            static int value;
            static void Store(int tag, ...) {
                va_list ap; va_start(ap,tag); unsigned long raw=va_arg(ap,unsigned long);
                *(int *)raw=7;
            }
            int main(void) { Store(0,(unsigned long)&value); return 0; }
            void TIM4_IRQHandler(void) { (void)value; }
        ''')
        self.assertEqual(variables['value']['static_classification'], 'SUSPECT')

    def test_record_variadic_pointer_keeps_a_writer(self):
        variables, _ = self.scan('''
            static int value;
            struct Ref {int *pointer;};
            static void Store(int tag, ...) {
                va_list ap; va_start(ap,tag); struct Ref ref=va_arg(ap,struct Ref); *ref.pointer=7;
            }
            int main(void) { Store(0,(struct Ref){&value}); return 0; }
            void TIM4_IRQHandler(void) { (void)value; }
        ''')
        self.assertEqual(variables['value']['static_classification'], 'SUSPECT')


if __name__ == '__main__':
    unittest.main()
