"""阶段 1 健全性修复的黄金风险样例（GR，规划 §18.3）。

这些样例在任何优化后都不得被判为 SAFE_PROVEN / SHARED_NO_REVIEW：
- GR-09b（P6）：value+valid 经访问器成对读（OPT-12，FS-2）；
- GR-11b（P28）：同优先级多写者 + 前台 64 位读者（OPT-16，FS-7）；
- GR-12（P1）：union 重叠视图跨域写（OPT-11，FS-1）；
- GR-14（P23）：内联汇编输出操作数 / 汇编文本写（OPT-14，FS-5）；
- GR-15（P9）：未识别使能机制之后的"初始化写"（OPT-13，FS-3）；
- GR-16（P25）：单写者 + 地址逃逸（OPT-10，FS-4）；
- GR-26（P30）：未知上下文读非原子变量（OPT-17，FS-8）；
- GR-27（P29）：库函数经指针写（OPT-19，FS-10）。
同时保留对应的正向精度用例（GR-13 packed 见 test_serial_regressions）。
"""
import unittest

from tests import test_ecra
from tests.test_phase0_metrics import Phase0Tests


class Phase1SoundnessTests(Phase0Tests):
    """复用阶段 0 的提取/分析 harness（project / extract / analyze / variable）。"""

    # ---- GR-09b：访问器方式的 value+valid 成对读 --------------------------

    def test_GR09b_accessor_read_group_is_coherence_suspect(self):
        facts, _ = self.analyze({'a.c': '''
            struct Proto { int value; int valid; };
            struct Proto p;
            void TIM2_IRQHandler(void){ p.value = 1; p.valid = 2; }
            int get_valid(void){ return p.valid; }
            int get_value(void){ return p.value; }
            int main(void){ if (get_valid()) { return get_value(); } return 0; }
            '''})
        for member in ('value', 'valid'):
            v = self.variable(facts, 'p', path='p.' + member)
            self.assertEqual(v['static_classification'], 'SUSPECT',
                             v['classification_reason'])
            self.assertIn('D-07', v['destructive_codes'])

    # ---- GR-11b：同优先级写者组 + 前台 64 位读者 --------------------------

    def test_GR11b_serial_writer_group_with_interleaving_reader(self):
        facts, _ = self.analyze({'a.c': '''
            enum { TIM2_IRQn = 0, TIM3_IRQn = 1 };
            unsigned long long stamp;
            void TIM2_IRQHandler(void){ stamp = 1; }
            void TIM3_IRQHandler(void){ stamp = 2; }
            int HAL_NVIC_SetPriority(unsigned irq, unsigned pre, unsigned sub);
            int main(void){ HAL_NVIC_SetPriority(TIM2_IRQn,1,0); HAL_NVIC_SetPriority(TIM3_IRQn,1,0); return (int)stamp; }
            '''}, configure=lambda cfg: cfg['project'].update(nvic_priority_bits=4))
        v = self.variable(facts, 'stamp')
        self.assertEqual(v['static_classification'], 'SUSPECT',
                         v['classification_reason'])
        self.assertIn('D-08', v['destructive_codes'])

    def test_GR11b_positive_32bit_writer_group_is_no_review(self):
        facts, _ = self.analyze({'a.c': '''
            enum { TIM2_IRQn = 0, TIM3_IRQn = 1 };
            unsigned int counter;
            void TIM2_IRQHandler(void){ counter = 1; }
            void TIM3_IRQHandler(void){ counter = 2; }
            int HAL_NVIC_SetPriority(unsigned irq, unsigned pre, unsigned sub);
            int main(void){ HAL_NVIC_SetPriority(TIM2_IRQn,1,0); HAL_NVIC_SetPriority(TIM3_IRQn,1,0); return (int)counter; }
            '''}, configure=lambda cfg: cfg['project'].update(nvic_priority_bits=4))
        v = self.variable(facts, 'counter')
        self.assertEqual(v['static_classification'], 'SHARED_NO_REVIEW',
                         v['classification_reason'])
        self.assertTrue(v['shared_no_review_evidence']['writer_group_serial'])

    # ---- GR-12：union 重叠视图跨域写 --------------------------------------

    def test_GR12_union_overlap_write_is_suspect(self):
        facts, _ = self.analyze({'a.c': '''
            union U { struct { unsigned lo; unsigned hi; } h; unsigned w; };
            union U u;
            void TIM2_IRQHandler(void){ u.w = 1; }
            int main(void){ u.h.lo = 2; return u.h.lo; }
            '''})
        for path in ('u.w', 'u.h.lo', 'u.h.hi'):
            v = self.variable(facts, 'u', path=path)
            self.assertEqual(v['static_classification'], 'SUSPECT',
                             path + ': ' + v['classification_reason'])
        # 重叠副本行标记 union 模式码 D-05（至少一个成员携带）。
        codes = set()
        for path in ('u.w', 'u.h.lo', 'u.h.hi'):
            v = self.variable(facts, 'u', path=path)
            codes |= set(v['destructive_codes'])
        self.assertTrue(codes & {'D-01', 'D-05'})

    def test_union_disjoint_sibling_fields_not_overlapped(self):
        # 同一嵌套 struct 的兄弟叶子（u.h.lo 与 u.h.hi）不互相制造写冲突：
        # 仅前台写 lo、仅前台写 hi 的单域成员不得因 union 修复误报。
        facts, _ = self.analyze({'a.c': '''
            union U { struct { unsigned lo; unsigned hi; } h; unsigned w; };
            union U u;
            int main(void){ u.h.lo = 1; u.h.hi = 2; return u.h.lo + u.h.hi; }
            '''})
        for path in ('u.h.lo', 'u.h.hi'):
            v = self.variable(facts, 'u', path=path)
            self.assertEqual(v['static_classification'], 'SAFE_PROVEN',
                             path + ': ' + v['classification_reason'])

    # ---- GR-14：内联汇编操作数与文本 --------------------------------------

    def test_GR14_inline_asm_output_operand_and_text_write_not_read_only(self):
        facts, _ = self.analyze({'a.c': '''
            int g_op;
            int g_txt;
            void TIM2_IRQHandler(void){
                asm volatile("" : "=m"(g_op));
                asm volatile("ldr r1, =g_txt; str r0, [r1]");
            }
            int main(void){ return g_op + g_txt; }
            '''})
        op = self.variable(facts, 'g_op')
        txt = self.variable(facts, 'g_txt')
        # 输出操作数按 WRITE 记录（HR-14 不得 SAFE_PROVEN；写已建模、
        # 唯一 ISR 写者 + 原子宽度时可共享无复核，与普通 ISR 写同语义）。
        self.assertTrue(any(a['access_kind'] in {'WRITE', 'RMW'} for a in op['accesses']),
                        '汇编输出操作数必须建模为写访问')
        self.assertNotEqual(op['static_classification'], 'SAFE_PROVEN',
                            op['classification_reason'])
        # 汇编文本经寄存器间接写（ldr/str 字面量池）：宽度与上下文不可恢复
        # → UNKNOWN_INLINE_ASM，不得判安全。
        self.assertNotIn(txt['static_classification'], {'SAFE_PROVEN', 'SHARED_NO_REVIEW'},
                         txt['classification_reason'])
        self.assertEqual(txt['static_classification'], 'UNKNOWN')
        self.assertIn('UNKNOWN_INLINE_ASM', txt['unknown_reason'])

    def test_GR14_positive_asm_input_operand_stays_read(self):
        facts, _ = self.analyze({'a.c': '''
            int g_in;
            void TIM2_IRQHandler(void){ asm volatile("" : : "m"(g_in)); }
            int main(void){ g_in = 1; while(1){ int x = g_in; (void)x; } return 0; }
            '''})
        v = self.variable(facts, 'g_in')
        # 输入操作数是 READ：唯一写者（前台）+ ISR 只读 + 原子宽度。
        self.assertEqual(v['static_classification'], 'SHARED_NO_REVIEW',
                         v['classification_reason'])

    # ---- GR-15：未识别使能机制之后的初始化写 ------------------------------

    def test_GR15_unrecognized_enable_breaks_init_only_write_proof(self):
        facts, _ = self.analyze({'a.c': '''
            void nvic_enable_irq(unsigned irq);
            void SysTick_Config(unsigned ticks);
            unsigned long long stamp;
            void TIM4_IRQHandler(void){ unsigned long long t = stamp; (void)t; }
            int main(void){ nvic_enable_irq(30); stamp = 0x1111ull; SysTick_Config(1000); return 0; }
            '''})
        v = self.variable(facts, 'stamp')
        self.assertNotEqual(v['static_classification'], 'SAFE_PROVEN',
                            v['classification_reason'])
        self.assertEqual(v['static_classification'], 'SUSPECT')

    def test_GR15_external_call_before_write_still_provable(self):
        # 语义已知的库调用不构成使能事件：写仍可证明在使能之前。
        facts, _ = self.analyze({'a.c': '''
            unsigned long long stamp;
            void TIM4_IRQHandler(void){ unsigned long long t = stamp; (void)t; }
            int SysTick_Config(unsigned ticks);
            int main(void){ stamp = 0x1111ull; SysTick_Config(1000); return 0; }
            '''})
        v = self.variable(facts, 'stamp')
        self.assertEqual(v['static_classification'], 'SAFE_PROVEN',
                         v['classification_reason'])
        self.assertEqual(v['screening_reason'], 'SAFE_INIT_ONLY_WRITE')

    # ---- GR-16：单写者 + 地址逃逸不得 NO_REVIEW ----------------------------

    def test_GR16_single_writer_with_address_escape_is_unknown(self):
        facts, _ = self.analyze({'a.c': '''
            int value;
            void TIM2_IRQHandler(void){ value = 5; }
            void External_Process(int *p);
            int main(void){ External_Process(&value); return value; }
            '''})
        v = self.variable(facts, 'value')
        self.assertEqual(v['static_classification'], 'UNKNOWN',
                         v['classification_reason'])
        self.assertIn('UNKNOWN_ADDRESS_ESCAPE', v['unknown_reason'])

    # ---- GR-26：未知上下文读 ----------------------------------------------

    def test_GR26_unknown_context_read_of_non_atomic_is_unknown(self):
        facts, _ = self.analyze({'a.c': '''
            unsigned long long stamp;
            static void (*cb)(void);
            void cb_body(void){ unsigned long long x = stamp; (void)x; }
            int main(void){ cb = cb_body; stamp = 7; while(1){ stamp = 8; } return 0; }
            '''})
        v = self.variable(facts, 'stamp')
        self.assertEqual(v['static_classification'], 'UNKNOWN',
                         v['classification_reason'])
        self.assertIn('UNKNOWN_EXECUTION_CONTEXT', v['unknown_reason'])

    def test_GR26_unknown_context_read_atomic_is_no_review(self):
        facts, _ = self.analyze({'a.c': '''
            unsigned int counter;
            static void (*cb)(void);
            void cb_body(void){ unsigned int x = counter; (void)x; }
            int main(void){ cb = cb_body; counter = 7; while(1){ counter = 8; } return 0; }
            '''})
        v = self.variable(facts, 'counter')
        self.assertEqual(v['static_classification'], 'SHARED_NO_REVIEW',
                         v['classification_reason'])

    def test_GR26_callback_handed_to_opaque_registrant_stays_unknown(self):
        facts, _ = self.analyze({'a.c': '''
            unsigned long long stamp;
            void External_Register(void (*fn)(void));
            void cb_body(void){ unsigned long long x = stamp; (void)x; }
            int main(void){ External_Register(cb_body); stamp = 7; return 0; }
            '''})
        v = self.variable(facts, 'stamp')
        self.assertEqual(v['static_classification'], 'UNKNOWN',
                         v['classification_reason'])

    # ---- GR-27：库函数经指针写必须作为 ISR 写出现 -------------------------

    def test_GR27_libc_write_through_pointer_is_modeled(self):
        facts, _ = self.analyze({'a.c': '''
            char buf[16];
            char *gp;
            int strcpy(char *dst, const char *src);
            void TIM2_IRQHandler(void){ gp = buf; strcpy(gp, "x"); }
            int main(void){ buf[0] = 0; return buf[0]; }
            '''})
        v = self.variable(facts, 'buf')
        # ISR 经 strcpy 写 buf 的行必须存在；buf 不得被判只读安全。
        self.assertNotIn(v['static_classification'], {'SAFE_PROVEN', 'SHARED_NO_REVIEW'},
                         v['classification_reason'])
        self.assertEqual(v['static_classification'], 'SUSPECT')
        # strcpy 的语义已知：buf 地址流入其参数不再产生地址逃逸缺口。
        self.assertNotIn('UNKNOWN_ADDRESS_ESCAPE', v['unknown_reason'])

    def test_GR27_positive_strcmp_read_only_no_escape(self):
        facts, _ = self.analyze({'a.c': '''
            char cmd[8];
            int strcmp(const char *, const char *);
            void use_it(const char *other){ if (strcmp(cmd, other)) { } }
            void Task(void){ use_it("on"); }
            int main(void){ (void)cmd; return 0; }
            '''})
        v = self.variable(facts, 'cmd')
        # strcmp 只读：无地址逃逸缺口；无写者 → 只读安全结论成立。
        self.assertEqual(v['static_classification'], 'SAFE_PROVEN',
                         v['classification_reason'])
        self.assertNotIn('UNKNOWN_ADDRESS_ESCAPE', v['unknown_reason'])


if __name__ == '__main__':
    unittest.main()
