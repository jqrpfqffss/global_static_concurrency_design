"""Real Clang quality fixtures check complete facts sent to the reviewer.

These tests do not pretend a simulated CLI proves a model's judgment.
"""
import copy
import json
import unittest

from tests import test_ecra as fixtures
from ecra.common import digest
from ecra.review import build_variable_review_packet, REVIEW_PROMPT


class ReviewQualityTests(unittest.TestCase):
    setUp = fixtures.ProjectTest.setUp
    project = fixtures.ProjectTest.project
    extract = fixtures.ProjectTest.extract

    def packet_for(self, source, name='value', *, contexts=None, priority_bits=None):
        cfg = self.project({'app.c': source}, contexts=contexts or [dict(id='main', kind='MAIN', functions=['main'])])
        if priority_bits:
            cfg['project']['nvic_priority_bits'] = priority_bits
        facts, report = self.extract(cfg)
        variable = next(v for v in facts['variables'] if v.get('canonical_path') == name or v['name'] == name)
        finding = next((f for f in report['findings'] if f.get('symbol_id') == variable['symbol_id']),
                       dict(finding_id='QUALITY', symbol_id=variable['symbol_id'],
                            static_classification=variable['static_classification'], accesses=variable['accesses']))
        before = digest(facts)
        packet = build_variable_review_packet(self.root, facts, finding, facts_path=self.root/'.ecra/facts.json',
            shared_path=self.root/'.ecra/review/project-evidence.json', report_path=self.root/'.ecra/reports/global_static_concurrency.json')
        self.assertEqual(digest(facts), before)
        self.assertEqual(len(packet['accesses']), len(variable['accesses']))
        path_sets = {p['id']: p for p in packet['call_path_sets']}
        restored = []
        for row in packet['accesses']:
            row = dict(row)
            if 'call_path_set' in row:
                paths = path_sets[row.pop('call_path_set')]
                row.update({k: v for k, v in paths.items() if k != 'id'})
            restored.append(row)
        self.assertEqual(restored, variable['accesses'])  # exact fields, every route, no sampling
        self.assertNotIn('access_source_context', packet)
        self.assertNotIn('investigation_requirements', packet)
        self.assertNotIn('conflict_pairs', packet['finding'])
        return facts, variable, packet

    def test_foreground_vs_irq_rmw_keeps_real_risk_and_all_paths(self):
        _, variable, packet = self.packet_for('static int value; void TIM2_IRQHandler(void){value++;} int main(void){value++;return 0;}')
        self.assertEqual(variable['static_classification'], 'SUSPECT')
        self.assertTrue(any(a['access_kind'] == 'RMW' for a in packet['accesses']))
        self.assertTrue(packet['concurrency_hints'])

    def test_irq_vs_irq_preemption_and_same_priority_serial_relation_survive(self):
        for priority, expected in [(1, 'CAN_PREEMPT'), (3, 'SERIAL')]:
            source = '''enum {TIM2_IRQn=28,TIM3_IRQn=29}; static int value;
                void HAL_NVIC_SetPriorityGrouping(unsigned); void HAL_NVIC_SetPriority(unsigned,unsigned,unsigned);
                void TIM2_IRQHandler(void){value++;} void TIM3_IRQHandler(void){value++;}
                int main(void){HAL_NVIC_SetPriorityGrouping(3); HAL_NVIC_SetPriority(TIM2_IRQn,PRIORITY,0);
                    HAL_NVIC_SetPriority(TIM3_IRQn,3,0);return 0;}'''.replace('PRIORITY', str(priority))
            _, variable, packet = self.packet_for(source, priority_bits=4)
            self.assertIn(expected, {r['relation'] for r in variable['concurrency_relations']})
            self.assertTrue(packet['irq_priority_events'])

    def test_one_irq_is_serial_and_read_only_is_safe(self):
        for source in [
            'static int value; void A(void){value++;} void B(void){value++;} void TIM2_IRQHandler(void){A();B();} int main(void){return 0;}',
            'static int value; void TIM2_IRQHandler(void){(void)value;} int main(void){return value;}'
        ]:
            _, variable, _ = self.packet_for(source)
            self.assertEqual(variable['static_classification'], 'SAFE_PROVEN')

    def test_full_disable_irq_and_partial_window_are_not_confused(self):
        for body, expected in [('__disable_irq();value++;__enable_irq();', 'SAFE_PROVEN'),
                               ('__disable_irq();int old=value;__enable_irq();value=old+1;', 'SUSPECT')]:
            source = ('static int value; void __disable_irq(void); void __enable_irq(void);'
                      'void TIM2_IRQHandler(void){value++;} int main(void){' + body + 'return 0;}')
            facts, variable, packet = self.packet_for(source)
            self.assertEqual(variable['static_classification'], expected)
            self.assertEqual(packet['known_protection'], variable['protection_details'])
            self.assertTrue(packet['protection_events'])
            self.assertEqual(packet['mask_windows'], [w for w in facts['mask_windows'] if w['symbol_id'] == variable['symbol_id']])

    def test_basepri_complete_priority_evidence_is_preserved(self):
        source = '''enum { TIM4_IRQn=30 }; static int value;
            void __set_BASEPRI(unsigned); void HAL_NVIC_SetPriorityGrouping(unsigned);
            void HAL_NVIC_SetPriority(unsigned,unsigned,unsigned);
            void TIM4_IRQHandler(void){value++;} int main(void){HAL_NVIC_SetPriorityGrouping(3);
              HAL_NVIC_SetPriority(TIM4_IRQn,5,0);__set_BASEPRI(0x50);value++;__set_BASEPRI(0);return 0;}'''
        _, variable, packet = self.packet_for(source, priority_bits=4)
        self.assertEqual(variable['static_classification'], 'SAFE_PROVEN')
        self.assertEqual(variable['protection_status'], 'EFFECTIVE')
        self.assertTrue(packet['known_protection'])

    def test_dma_cpu_and_unresolved_function_pointer_remain_unknown_or_suspect(self):
        facts, variable, packet = self.packet_for('''static unsigned char buffer[16];
            int HAL_UART_Receive_DMA(void*,unsigned char*,unsigned);
            int main(void){HAL_UART_Receive_DMA(0,buffer,16);buffer[0]++;return 0;}''', name='buffer[0]')
        self.assertIn(variable['static_classification'], {'UNKNOWN', 'SUSPECT'})
        self.assertTrue(packet['unknowns'])
        self.assertIn('DMA', json.dumps(packet))
        _, variable, packet = self.packet_for('''static int value; void (*hook)(void);
            void Callback(void){value++;} void Register(void (*f)(void));
            int main(void){Register(Callback);hook();return 0;}''')
        self.assertIn(variable['static_classification'], {'UNKNOWN', 'SUSPECT'})
        self.assertTrue(packet['unknowns'])

    def test_initialization_proof_and_unreachable_access_remain_available(self):
        _, variable, packet = self.packet_for('''enum {TIM4_IRQn=30}; static unsigned value;
            void NVIC_EnableIRQ(int);void NVIC_DisableIRQ(int);
            void TIM4_IRQHandler(void){(void)value;} int main(void){NVIC_DisableIRQ(TIM4_IRQn);
            value=7;NVIC_EnableIRQ(TIM4_IRQn);while(1){(void)value;}}''')
        self.assertTrue(variable.get('initialization_proof'))
        self.assertEqual(packet['initialization_proof'], variable['initialization_proof'])
        _, variable, packet = self.packet_for('static int value; void Dead(void){value++;} int main(void){return value;}')
        self.assertEqual(variable['static_classification'], 'SAFE_PROVEN')
        self.assertTrue(any(a.get('reachability') == 'PROVEN_UNREACHABLE' for a in packet['accesses']))

    def test_members_arrays_aliases_local_and_file_statics_keep_storage_identity(self):
        source = '''static struct S{int x,y;} state; static int array[3]; static int value;
            void Step(void){static int local;local++;}
            void TIM2_IRQHandler(void){state.x++;array[1]++;value++;Step();}
            int main(void){int *p=&value;(*p)++;state.x++;array[1]++;Step();return 0;}'''
        for name in ('state.x', 'array[1]', 'value', 'local'):
            with self.subTest(name=name):
                _, variable, packet = self.packet_for(source, name=name)
                self.assertEqual(packet['variable']['symbol_id'], variable['symbol_id'])
                self.assertEqual(packet['variable'].get('canonical_path', packet['variable']['qualified_name']),
                                 variable.get('canonical_path', variable['qualified_name']))
                if name == 'value':
                    self.assertTrue(any(a.get('via_alias') for a in packet['accesses']))

    def test_unknown_priority_prompt_requires_source_verification_and_no_guessed_safe(self):
        _, variable, packet = self.packet_for('static int value; void TIM2_IRQHandler(void){value++;} void TIM3_IRQHandler(void){value++;} int main(void){return 0;}')
        self.assertNotEqual(variable['static_classification'], 'SAFE_PROVEN')
        self.assertIn('UNKNOWN_PREEMPTION', json.dumps(packet))
        for phrase in ('所有访问点', '完整调用链', 'NVIC', 'BASEPRI', 'DMA', '不要无理由扫描',
                       'NEED_MORE_CONTEXT', '不能猜SAFE', '保护', '别名', '清零后的处理是否已经覆盖该事件'):
            self.assertIn(phrase, REVIEW_PROMPT)


if __name__ == '__main__':
    unittest.main()
