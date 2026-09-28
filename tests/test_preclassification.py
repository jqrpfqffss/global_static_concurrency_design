"""T01-T18：冲突优先的 Pre-OpenCode 静态分类单元测试。

覆盖需求：
- SAFE 证明规则（SAFE_SINGLE_FOREGROUND / SAFE_MULTI_CONTEXT_READ_ONLY /
  SAFE_SINGLE_IRQ / SAFE_EFFECTIVE_PROTECTION …）必须大胆而正确；
- 已知冲突在优先级/保护未解析时必须 SUSPECT 而不是 UNKNOWN；
- 无关 blocker（未解析函数指针、其它 TU 解析失败）不得传播；
- UNKNOWN 只能由变量直接相关的证据缺口产生（精准 reason code）。
"""
import unittest

from tests import test_ecra
from ecra.analysis import merge
from ecra.compilation import prepare
from ecra.extract import Extractor

class PreClassificationTests(unittest.TestCase):
    setUp = test_ecra.ProjectTest.setUp
    project = test_ecra.ProjectTest.project

    MAIN = [dict(id='main', kind='MAIN', functions=['main'])]

    def extract(self, cfg, allow_fail=()):
        units, audit = prepare(self.root, cfg)
        parts = []
        for u in units:
            part = Extractor(dict(root=str(self.root), unit=u, config=cfg)).run()
            if part['parse_status'] != 'PARSED' and u['source_file'] not in allow_fail:
                self.fail('unexpected parse failure: ' + str(part['diagnostics']))
            parts.append(part)
        facts = merge(parts)
        # 复现 cli.py 对解析失败 TU 的覆盖记录，保持与分析流水线一致。
        for part, unit in zip(parts, units):
            if part['parse_status'] != 'PARSED':
                facts['unknowns'].append(dict(kind='PARSE_FAILED', file=unit['source_file'],
                                              diagnostics=part['diagnostics']))
        audit['translation_units_failed'] = sum(p['parse_status'] != 'PARSED' for p in parts)
        coverage = dict(audit)
        return facts, audit, coverage

    def analyze(self, sources, contexts=None, nvic_bits=None, configure=None, allow_fail=()):
        cfg = self.project(sources, contexts=contexts or self.MAIN)
        if nvic_bits:
            cfg['project']['nvic_priority_bits'] = nvic_bits
        if configure:
            configure(cfg)
        facts, audit, coverage = self.extract(cfg, allow_fail=allow_fail)
        from ecra.analysis import analyze
        report = analyze(facts, cfg, coverage, root=self.root)
        return facts, report

    def variable(self, facts, name, path=None):
        if path:
            return next(v for v in facts['variables'] if v.get('canonical_path') == path
                        or v.get('qualified_name') == path)
        return next(v for v in facts['variables'] if v['name'] == name)

    # ---- SAFE 证明规则 --------------------------------------------------

    def test_T01_main_multi_function_read_write_is_single_foreground_safe(self):
        facts, report = self.analyze({'a.c': '''
            static int g;
            void HelperA(void){g = g + 1;}
            void HelperB(void){g *= 2; int x = g;}
            void Step(void){HelperA(); HelperB();}
            int main(void){while(1){Step();} return 0;}
        '''})
        v = self.variable(facts, 'g')
        self.assertEqual(v['static_classification'], 'SAFE')
        self.assertEqual(v['screening_reason'], 'SAFE_SINGLE_FOREGROUND')
        self.assertIn('静态已判安全', v['classification_reason'])
        self.assertFalse(any(f.get('symbol_id') == v['symbol_id'] for f in report['findings']))

    def test_T02_multiple_isr_all_read_is_multi_context_read_only(self):
        facts, _ = self.analyze({'a.c': '''
            const int table[4] = {1,2,3,4};
            int cfg_value = 7;
            void TIM2_IRQHandler(void){int x = cfg_value; (void)x;}
            void TIM3_IRQHandler(void){int y = cfg_value; (void)y;}
            void USART1_IRQHandler(void){int z = cfg_value; (void)z;}
            int main(void){return cfg_value;}
        '''})
        v = self.variable(facts, 'cfg_value')
        self.assertEqual(v['static_classification'], 'SAFE')
        self.assertEqual(v['screening_reason'], 'SAFE_MULTI_CONTEXT_READ_ONLY')
        self.assertGreaterEqual(len(v['contexts']), 3)

    def test_T03_single_irq_read_write_rmw_is_single_irq_safe(self):
        facts, _ = self.analyze({'a.c': '''
            static int counter;
            static void Bump(void){counter++;}
            void TIM4_IRQHandler(void){Bump(); counter = counter + 1; int x = counter; (void)x;}
        '''})
        v = self.variable(facts, 'counter')
        self.assertEqual(v['static_classification'], 'SAFE')
        self.assertEqual(v['screening_reason'], 'SAFE_SINGLE_IRQ')

    def test_T04_main_read_isr_write_is_suspect(self):
        facts, report = self.analyze({'a.c': '''
            int value;
            void TIM4_IRQHandler(void){value = 2;}
            int main(void){return value;}
        '''})
        v = self.variable(facts, 'value')
        self.assertEqual(v['static_classification'], 'SUSPECT')
        self.assertTrue(any(f.get('symbol_id') == v['symbol_id'] for f in report['findings']))

    def test_T05_isr_write_plus_isr_read_priority_unknown_is_suspect_not_unknown(self):
        facts, _ = self.analyze({'a.c': '''
            int value;
            void TIM2_IRQHandler(void){value = 1;}
            void TIM3_IRQHandler(void){int x = value; (void)x;}
        '''})
        v = self.variable(facts, 'value')
        self.assertEqual(v['static_classification'], 'SUSPECT')
        # 已知跨 ISR 冲突：priority unknown => MAY_INTERLEAVE => SUSPECT。
        self.assertIn('抢占优先级待确认', v.get('classification_reason', '') + str(v.get('pending_confirmation')))

    def test_T06_isr_write_plus_isr_write_priority_unknown_is_suspect_not_unknown(self):
        facts, _ = self.analyze({'a.c': '''
            int value;
            void TIM2_IRQHandler(void){value = 1;}
            void TIM3_IRQHandler(void){value = 2;}
        '''})
        v = self.variable(facts, 'value')
        self.assertEqual(v['static_classification'], 'SUSPECT')
        self.assertEqual(v['analysis_coverage'], 'COMPLETE')

    def test_T07_unrelated_unresolved_function_pointer_does_not_poison_file_static(self):
        facts, _ = self.analyze({'a.c': '''
            typedef unsigned int uint32_t;
            static uint32_t g_counter;
            void (*unrelated_callback)(void);
            void Dispatch(void){unrelated_callback();}
            int main(void){g_counter++; Dispatch(); return 0;}
        '''})
        v = self.variable(facts, 'g_counter')
        self.assertEqual(v['static_classification'], 'SAFE')
        self.assertEqual(v['screening_reason'], 'SAFE_SINGLE_FOREGROUND')
        self.assertEqual(v['screening_blockers'], [])

    def test_T08_address_passed_to_unresolved_external_is_unknown_address_escape(self):
        facts, _ = self.analyze({'a.c': '''
            static int g_config;
            void External_Process(int *);
            int main(void){External_Process(&g_config); return 0;}
        '''})
        v = self.variable(facts, 'g_config')
        self.assertEqual(v['static_classification'], 'UNKNOWN')
        self.assertIn('UNKNOWN_ADDRESS_ESCAPE', v['unknown_reason'])

    def test_T09_other_tu_parse_failure_does_not_poison_file_static(self):
        facts, _ = self.analyze(
            {'a.c': '''
                static int value;
                void Setup(void){value = 3;}
                int main(void){Setup(); return value;}
            ''',
             'broken.c': 'this is not valid C source code @#$%',
             }, allow_fail=('broken.c',))
        v = self.variable(facts, 'value')
        self.assertEqual(v['static_classification'], 'SAFE')
        self.assertEqual(v['screening_reason'], 'SAFE_SINGLE_FOREGROUND')
        self.assertEqual(v['screening_blockers'], [])

    def test_T10_function_static_called_only_from_main_is_safe(self):
        facts, _ = self.analyze({'a.c': '''
            void Worker(void);
            int main(void){Worker(); return 0;}
        ''', 'b.c': '''
            void Worker(void){static int budget; budget--;}
        '''}, contexts=[dict(id='main', kind='MAIN', functions=['main'])])
        v = self.variable(facts, 'budget')
        self.assertEqual(v['static_classification'], 'SAFE')
        self.assertEqual(v['screening_reason'], 'SAFE_SINGLE_FOREGROUND')

    def test_T11_function_static_from_main_and_isr_is_suspect(self):
        facts, _ = self.analyze({'a.c': '''
            void Worker(void);
            void TIM4_IRQHandler(void){Worker();}
            int main(void){Worker(); return 0;}
        ''', 'b.c': '''
            void Worker(void){static int budget; budget--;}
        '''})
        v = self.variable(facts, 'budget')
        self.assertEqual(v['static_classification'], 'SUSPECT')

    def test_T12_all_read_with_multiple_callback_contexts_is_safe(self):
        def configure(cfg):
            cfg['entry_registrations'] = [
                dict(api='RegisterA', callback_arg=0, kind='CALLBACK', context_id='cb_a', may_repeat=False),
                dict(api='RegisterB', callback_arg=0, kind='CALLBACK', context_id='cb_b', may_repeat=False),
            ]
        facts, _ = self.analyze({'a.c': '''
            int status;
            void RegisterA(void (*)(void)); void RegisterB(void (*)(void));
            static void PollA(void){int x = status; (void)x;}
            static void PollB(void){int y = status; (void)y;}
            int main(void){RegisterA(PollA); RegisterB(PollB); return status;}
        '''}, configure=configure)
        v = self.variable(facts, 'status')
        self.assertEqual(v['static_classification'], 'SAFE')
        self.assertIn(v['screening_reason'], {'SAFE_MULTI_CONTEXT_READ_ONLY', 'SAFE_READ_ONLY'})

    def test_T13_primask_covering_whole_conflict_window_is_effective_protection(self):
        facts, _ = self.analyze({'a.c': '''
            int value;
            void __disable_irq(void); void __enable_irq(void);
            void TIM4_IRQHandler(void){value++;}
            int main(void){__disable_irq(); value++; __enable_irq(); return 0;}
        '''})
        v = self.variable(facts, 'value')
        self.assertEqual(v['protection_status'], 'EFFECTIVE')
        self.assertEqual(v['static_classification'], 'SAFE')
        self.assertEqual(v['screening_reason'], 'SAFE_EFFECTIVE_PROTECTION')

    def test_T14_primask_covering_only_part_of_rmw_is_suspect(self):
        facts, _ = self.analyze({'a.c': '''
            int value;
            void __disable_irq(void); void __enable_irq(void);
            void TIM4_IRQHandler(void){value = 1800;}
            int main(void){int old; __disable_irq(); old = value; __enable_irq(); value = old + 1; return 0;}
        '''})
        v = self.variable(facts, 'value')
        self.assertEqual(v['protection_status'], 'PARTIAL')
        self.assertEqual(v['static_classification'], 'SUSPECT')
        self.assertIn('保护有效性待确认', v['classification_reason'])

    def test_T15_basepri_unresolved_with_known_cross_isr_write_conflict_is_suspect(self):
        facts, _ = self.analyze({'a.c': '''
            int value; void __set_BASEPRI(unsigned);
            void TIM2_IRQHandler(void){value++;}
            void TIM3_IRQHandler(void){value++;}
            int main(void){__set_BASEPRI(0x50); value++; __set_BASEPRI(0); return 0;}
        '''}, nvic_bits=4)
        v = self.variable(facts, 'value')
        self.assertEqual(v['protection_status'], 'UNRESOLVED')
        self.assertEqual(v['static_classification'], 'SUSPECT')

    def test_T16_dma_ownership_unresolved_is_unknown_dma_lifetime(self):
        facts, _ = self.analyze({'a.c': '''
            unsigned char value[16];
            void HAL_UART_Receive_DMA(void *, unsigned char *, unsigned);
            int main(void){HAL_UART_Receive_DMA(0, value, 16); value[0] = 1; return 0;}
        '''})
        v = self.variable(facts, 'value')
        self.assertEqual(v['static_classification'], 'UNKNOWN')
        self.assertIn('UNKNOWN_DMA_LIFETIME', v['unknown_reason'])
        self.assertTrue(any(r['kind'] == 'UNKNOWN_DMA_LIFETIME' for r in v['required_context']))

    def test_T17_field_sensitive_member_access_kinds(self):
        facts, _ = self.analyze({'a.c': '''
            struct Config {unsigned period; unsigned limit;};
            static struct Config active_config;
            void Service_Rx(void){active_config.limit = active_config.period * 2;}
            void USART1_IRQHandler(void){Service_Rx();}
            int main(void){active_config.period = 7; return active_config.limit;}
        '''})
        limit = self.variable(facts, 'active_config', 'active_config.limit')
        period = self.variable(facts, 'active_config', 'active_config.period')
        # 赋值语句字段敏感：Service_Rx 内 limit 仅 WRITE、period 仅 READ，
        # active_config 不被视为整体 RMW。
        service = next(f['function_id'] for f in facts['functions'] if f['name'] == 'Service_Rx')
        self.assertEqual(sorted({a['access_kind'] for a in limit['accesses'] if a['function_id'] == service}), ['WRITE'])
        self.assertEqual(sorted({a['access_kind'] for a in period['accesses'] if a['function_id'] == service}), ['READ'])
        self.assertEqual(limit['static_classification'], 'SUSPECT')

    def test_T18_dynamic_array_index_pollutes_only_the_array_object(self):
        facts, _ = self.analyze({'a.c': '''
            static int arr[8];
            static int unrelated;
            unsigned idx;
            void USART1_IRQHandler(void){arr[idx] = 5;}
            int main(void){idx = 1; unrelated = 2; return arr[0] + unrelated;}
        '''})
        arr = self.variable(facts, 'arr')
        unrelated = self.variable(facts, 'unrelated')
        idx = self.variable(facts, 'idx')
        # 动态下标 arr[i] 只影响 array[*]（arr 整体对象）；idx 确实跨上下文
        # 访问（MAIN 写 + ISR 读）=> SUSPECT 是正确结论；无关变量不受污染。
        self.assertEqual(arr['static_classification'], 'SUSPECT')
        self.assertEqual(idx['static_classification'], 'SUSPECT')
        self.assertEqual(unrelated['static_classification'], 'SAFE')
        self.assertEqual(unrelated['screening_reason'], 'SAFE_SINGLE_FOREGROUND')
        self.assertEqual(unrelated['screening_blockers'], [])

    # ---- 独立 dispatcher 函数表：FOREGROUND 串行域（Section 6/11） --------

    def test_cooperative_task_table_dispatch_is_single_foreground(self):
        facts, _ = self.analyze({'a.c': '''
            typedef void (*task_fn)(void);
            static int ticks_a, ticks_b;
            static void TaskA(void){ticks_a++;}
            static void TaskB(void){ticks_b++;}
            static const task_fn tasks[] = {TaskA, TaskB};
            int main(void){
                for(;;){ for(unsigned i=0;i<2;i++){tasks[i]();} }
            }
        '''})
        for name in ('ticks_a', 'ticks_b'):
            v = self.variable(facts, name)
            self.assertEqual(v['static_classification'], 'SAFE', name)
            self.assertEqual(v['screening_reason'], 'SAFE_SINGLE_FOREGROUND', name)
            self.assertEqual(v['contexts'], ['main'])

    def test_callback_inherits_caller_irq_context_and_conflicts_with_main(self):
        facts, _ = self.analyze({'a.c': '''
            int count;
            static void Service_Rx(void){count++;}
            void USART1_IRQHandler(void){Service_Rx();}
            int main(void){count = 0; return 0;}
        '''})
        v = self.variable(facts, 'count')
        # Service_Rx 继承 USART1 IRQ 上下文，与 MAIN 写构成真实 multi-context。
        self.assertEqual(v['static_classification'], 'SUSPECT')
        contexts = set(v['contexts'])
        self.assertTrue(any('USART1' in c for c in contexts), contexts)
        self.assertIn('main', contexts)

    def test_same_irq_multiple_paths_is_not_self_concurrent(self):
        facts, _ = self.analyze({'a.c': '''
            static int counter;
            static void A(void){counter++;}
            static void B(void){counter++;}
            void TIM4_IRQHandler(void){ if(counter & 1){A();} else {B();} }
        '''})
        v = self.variable(facts, 'counter')
        # 同一 IRQ 向量内的多条调用路径仍是单一物理执行上下文。
        self.assertEqual(v['static_classification'], 'SAFE')
        self.assertEqual(v['screening_reason'], 'SAFE_SINGLE_IRQ')

    # ---- UNKNOWN 精准 reason code / 不传播 -------------------------------

    def test_unknown_reason_codes_are_precise_and_local(self):
        facts, _ = self.analyze({'a.c': '''
            int escaped; int plain;
            void External_Process(int *);
            int main(void){External_Process(&escaped); plain = 1; return 0;}
        '''})
        escaped = self.variable(facts, 'escaped')
        plain = self.variable(facts, 'plain')
        self.assertEqual(escaped['static_classification'], 'UNKNOWN')
        self.assertEqual(escaped['unknown_reason'], ['UNKNOWN_ADDRESS_ESCAPE'])
        self.assertEqual(plain['static_classification'], 'SAFE')
        self.assertTrue(escaped['blocking_evidence'])
        self.assertTrue(all(r['action'] for r in escaped['required_context']))

    def test_blocker_fanout_report_is_generated(self):
        facts, report = self.analyze({'a.c': '''
            int a; int b;
            void External_Process(int *);
            int main(void){External_Process(&a); External_Process(&b); return 0;}
        '''})
        coverage = report['coverage']
        self.assertIn('blocker_fanout', coverage)
        reasons = {row['reason']: row for row in coverage['blocker_fanout']}
        self.assertIn('UNKNOWN_ADDRESS_ESCAPE', reasons)
        self.assertGreaterEqual(reasons['UNKNOWN_ADDRESS_ESCAPE']['variables'], 2)
        self.assertIn('unknown_reason_distribution', coverage)
        self.assertIn('safe_reason_distribution', coverage)


if __name__ == '__main__':
    unittest.main()
