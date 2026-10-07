"""阶段 2 OPT-20（访问路径代数）测试。

- GP-03（P2）：嵌套成员写不污染兄弟成员（路径不再逆序）；
- GP-04（P32）：结构体内数组写不污染兄弟成员（buf[] 匹配数组成员）；
- M-40（P33）：指针成员解引用终止左值链（Instance 只 READ，写归属 pointee）；
- 别名基路径：p = &s.inner; p->y = 3 记到 s.inner.y；
- M-07：路径不匹配的整对象回退显式记录 fallback_reason。
"""
import unittest

from tests.test_phase0_metrics import Phase0Tests


class Phase2PathTests(Phase0Tests):

    def test_GP03_nested_member_write_no_sibling_pollution(self):
        facts, _ = self.analyze({'a.c': '''
            struct Inner { int x; int y; };
            struct Outer { int x; struct Inner inner; };
            struct Outer s;
            void TIM2_IRQHandler(void){
                s.inner.x = 5;
                struct Inner *p = &s.inner;
                p->y = 3;
            }
            int main(void){ s.x = 1; return s.x; }
            '''})
        s_x = self.variable(facts, 's', path='s.x')
        inner_x = self.variable(facts, 's', path='s.inner.x')
        inner_y = self.variable(facts, 's', path='s.inner.y')
        # 兄弟成员 s.x 只被前台访问：不再被回退继承污染。
        self.assertEqual(s_x['screening_reason'], 'SAFE_SINGLE_FOREGROUND',
                         s_x['classification_reason'])
        # 路径按自然顺序记录（旧实现逆序为 x.inner / y）。
        paths = {a.get('access_path') for a in facts['accesses']
                 if a.get('access_path') and a['symbol_id'].endswith(('inner.x', 'inner.y'))}
        self.assertIn('inner.x', paths)
        self.assertIn('inner.y', paths)
        self.assertNotIn('x.inner', paths)
        self.assertEqual(inner_x['screening_reason'], 'SAFE_SINGLE_IRQ',
                         inner_x['classification_reason'])
        self.assertEqual(inner_y['screening_reason'], 'SAFE_SINGLE_IRQ',
                         inner_y['classification_reason'])

    def test_GP04_struct_array_write_no_sibling_pollution(self):
        facts, _ = self.analyze({'a.c': '''
            struct Ring { int head; int tail; int buf[4]; };
            struct Ring r;
            void TIM2_IRQHandler(void){ r.buf[0] = 1; r.head = 2; }
            int main(void){ r.tail = 3; while(1){ int x = r.tail; (void)x; } return 0; }
            '''})
        tail = self.variable(facts, 'r', path='r.tail')
        head = self.variable(facts, 'r', path='r.head')
        buf = self.variable(facts, 'r', path='r.buf')
        # r.tail 只被前台写/读：不再因 ISR 写 r.buf[] 的回退继承成为双写者。
        self.assertEqual(tail['screening_reason'], 'SAFE_SINGLE_FOREGROUND',
                         tail['classification_reason'])
        self.assertEqual(head['screening_reason'], 'SAFE_SINGLE_IRQ',
                         head['classification_reason'])
        self.assertEqual(buf['screening_reason'], 'SAFE_SINGLE_IRQ',
                         buf['classification_reason'])

    def test_M40_pointer_member_deref_truncates_lvalue_chain(self):
        facts, _ = self.analyze({'a.c': '''
            struct USART_Type { unsigned int CR1; };
            struct UART_Handle { struct USART_Type *Instance; unsigned gState; };
            struct UART_Handle huart2;
            struct USART_Type fake_usart;
            void TIM2_IRQHandler(void){ huart2.Instance->CR1 |= 0x20; }
            int main(void){ huart2.Instance = &fake_usart; return huart2.gState; }
            '''}, configure=lambda cfg: cfg['project'].update(nvic_priority_bits=4))
        inst = self.variable(facts, 'huart2', path='huart2.Instance')
        cr1 = self.variable(facts, 'fake_usart', path='fake_usart.CR1')
        # Instance 在 ISR 中只有 READ（读作地址）；写者只有前台初始化。
        isr_rows = [a for a in inst['accesses'] if 'TIM2' in ' '.join(
            c for c in (a.get('contexts') or ())) or a.get('contexts')]
        isr_accesses = [a for a in inst['accesses']
                        if any('TIM2' in str(c) for c in (a.get('contexts') or ()))]
        self.assertTrue(isr_accesses)
        self.assertTrue(all(a['access_kind'] == 'READ' for a in isr_accesses),
                        str([(a['access_kind'], a.get('access_path')) for a in isr_accesses]))
        # CR1 的 RMW 记在被指向对象上，而不是 Instance。
        self.assertTrue(any(a['access_kind'] in {'RMW', 'WRITE'} for a in cr1['accesses']),
                          'CR1 必须承载 ISR 的 RMW')
        self.assertEqual(cr1['screening_reason'], 'SAFE_SINGLE_IRQ',
                         cr1['classification_reason'])

    def test_alias_base_path_composes_relative_path(self):
        facts, _ = self.analyze({'a.c': '''
            struct Cfg { int limit; int period; };
            struct Cfg cfg;
            void Task(void){
                struct Cfg *p = &cfg;
                p->limit = 10;
            }
            '''})
        limit = self.variable(facts, 'cfg', path='cfg.limit')
        paths = {a.get('access_path') for a in facts['accesses']
                 if a['symbol_id'] == limit['symbol_id']
                 and a.get('via_alias') not in (None, 'interprocedural points-to')}
        self.assertEqual(paths, {'limit'})

    def test_nested_alias_base_path(self):
        facts, _ = self.analyze({'a.c': '''
            struct Inner { int x; int y; };
            struct Outer { struct Inner inner; };
            struct Outer o;
            int main(void){
                struct Inner *p = &o.inner;
                p->y = 3;
                return 0;
            }
            '''})
        y = self.variable(facts, 'o', path='o.inner.y')
        paths = {a.get('access_path') for a in facts['accesses']
                 if a['symbol_id'] == y['symbol_id']
                 and a.get('via_alias') not in (None, 'interprocedural points-to')}
        # 基路径 inner + 相对路径 y → inner.y（旧实现只记 y）。
        self.assertEqual(paths, {'inner.y'})
        self.assertEqual(y['screening_reason'], 'SAFE_SINGLE_FOREGROUND',
                         y['classification_reason'])

    def test_fallback_reason_recorded_for_type_punning(self):
        facts, _ = self.analyze({'a.c': '''
            struct Pair { int a; int b; };
            struct Pair sp;
            void Task(void){
                unsigned char *cp = (unsigned char *)&sp;
                cp[0] = 1;
            }
            '''})
        # 类型双关（float* 指向 struct）无法匹配成员 → 显式回退原因。
        fallbacks = [a for a in facts['accesses'] if a.get('fallback_reason') == 'path_unmatched']
        self.assertTrue(fallbacks, '类型双关应记录 fallback_reason')


if __name__ == '__main__':
    unittest.main()
