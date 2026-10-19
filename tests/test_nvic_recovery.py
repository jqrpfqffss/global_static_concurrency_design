"""Real Clang AST -> resolved NVIC facts -> preemption -> review packet."""
import json
import unittest
from tests import test_ecra as fixtures
from ecra.interrupts import priority_model
from ecra.review import build_variable_review_packet


HEADER = '''
#define __NVIC_PRIO_BITS 4U
#define NVIC_PRIORITYGROUP_4 3U
#define NVIC_PRIORITYGROUP_2 5U
enum { TIM3_IRQn=29, TIM4_IRQn=30, TIM8_UP_TIM13_IRQn=44, TIM1_UP_TIM16_IRQn=25 };
void HAL_NVIC_SetPriorityGrouping(unsigned);
void HAL_NVIC_SetPriority(int, unsigned, unsigned);
void NVIC_SetPriority(int, unsigned);
void __NVIC_SetPriority(int, unsigned);
void NVIC_SetPriorityGrouping(unsigned);
void HAL_NVIC_EnableIRQ(int); void HAL_NVIC_DisableIRQ(int);
void __disable_irq(void); void __enable_irq(void); void __set_BASEPRI(unsigned);
volatile int shared, condition;
void TIM3_IRQHandler(void){shared++;}
void TIM4_IRQHandler(void){shared++;}
void TIM8_UP_TIM13_IRQHandler(void){shared++;}
void TIM1_UP_TIM16_IRQHandler(void){shared++;}
'''


class NVICRecoveryTests(unittest.TestCase):
    setUp = fixtures.ProjectTest.setUp
    project = fixtures.ProjectTest.project
    extract = fixtures.ProjectTest.extract

    def scan(self, body, extra='', group='NVIC_PRIORITYGROUP_4'):
        source = HEADER + extra + '\nint main(void){HAL_NVIC_SetPriorityGrouping(' + group + ');' + body + 'while(1){shared++;}}'
        cfg = self.project({'app.c': source}, contexts=[dict(id='main', kind='MAIN', functions=['main'])])
        facts, report = self.extract(cfg)
        self.facts, self.report, self.cfg = facts, report, cfg
        return {r['irqn'][0]: r for r in facts['nvic_priorities']}

    def test_direct_main_and_cmsis_expansion(self):
        rows = self.scan('HAL_NVIC_SetPriority(TIM3_IRQn,2,0); __NVIC_SetPriority(TIM4_IRQn,1);')
        self.assertEqual(rows['TIM3_IRQn']['preemption_priority'], 2)
        self.assertEqual(rows['TIM4_IRQn']['preemption_priority'], 1)
        self.assertEqual(rows['TIM3_IRQn']['effective_validity'], 'CONFIRMED')

    def test_multilevel_parameters_local_expression_enum_macro(self):
        rows = self.scan('Board();', '''
#define PRI (1U << 1)
void Configure(int irq, unsigned value){unsigned local=value+1; HAL_NVIC_SetPriority(irq,local,0);}
void Inner(unsigned priority){Configure(TIM4_IRQn,priority);}
void Board(void){Inner(PRI);}
''')
        row = rows['TIM4_IRQn']
        self.assertEqual(row['preemption_priority'], 3)
        self.assertEqual([p['function'] for p in row['source_configurations'][0]['call_chain']],
                         ['main', 'Board', 'Inner', 'Configure'])

    def test_hal_msp_pointer_instance_branch_and_strong_callback(self):
        rows = self.scan('MX_TIM4_Init();', '''
typedef struct {void *Instance; unsigned State;} Handle;
#define TIM4 ((void*)0x40000800U)
Handle htim4;
void HAL_TIM_Base_MspInit(Handle *htim){if(htim->Instance==TIM4){HAL_NVIC_SetPriority(TIM4_IRQn,2,0);HAL_NVIC_EnableIRQ(TIM4_IRQn);}}
void HAL_TIM_Base_Init(Handle *htim){if(htim && htim->State==0){HAL_TIM_Base_MspInit(htim);}}
void MX_TIM4_Init(void){htim4.Instance=TIM4;HAL_TIM_Base_Init(&htim4);}
''')
        row = rows['TIM4_IRQn']
        self.assertEqual(row['preemption_priority'], 2, row)
        self.assertTrue(row['enabled'])
        self.assertEqual(row['effective_validity'], 'CONFIRMED')
        self.assertEqual(len(row['source_configurations'][0]['proven_guards']), 2)

    def test_group_encoding_and_subpriority_does_not_preempt(self):
        rows = self.scan('HAL_NVIC_SetPriority(TIM3_IRQn,2,1);HAL_NVIC_SetPriority(TIM4_IRQn,2,3);', group='NVIC_PRIORITYGROUP_2')
        self.assertEqual((rows['TIM3_IRQn']['preemption_bits'], rows['TIM3_IRQn']['subpriority_bits']), (2, 2))
        self.assertEqual(rows['TIM3_IRQn']['logical_priority'], 9)
        pair = next(r for r in self.facts['preemption_relations'] if set(r.get('priorities', {}).values()) == {2})
        self.assertEqual(pair['relation'], 'SERIAL')

    def test_shared_vectors_keep_physical_identity(self):
        rows = self.scan('HAL_NVIC_SetPriority(TIM8_UP_TIM13_IRQn,2,0);HAL_NVIC_SetPriority(TIM1_UP_TIM16_IRQn,1,0);')
        self.assertEqual(rows['TIM8_UP_TIM13_IRQn']['vectors'], ['TIM8_UP_TIM13_IRQHandler'])
        self.assertEqual(rows['TIM1_UP_TIM16_IRQn']['vectors'], ['TIM1_UP_TIM16_IRQHandler'])
        irq_contexts = [c for c in self.facts['contexts'] if c['kind'] == 'ISR']
        self.assertEqual(len(irq_contexts), 4)
        self.assertEqual(len({c['physical_id'] for c in irq_contexts}), 4)

    def test_distinct_vector_slots_sharing_one_handler_keep_distinct_priorities(self):
        source='''
#define __NVIC_PRIO_BITS 4
enum{G_IRQn=5,L_IRQn=6};
void HAL_NVIC_SetPriorityGrouping(unsigned);void HAL_NVIC_SetPriority(int,unsigned,unsigned);
volatile int value;
void CommonDispatcher(void){value++;}
int main(void){HAL_NVIC_SetPriorityGrouping(3);HAL_NVIC_SetPriority(G_IRQn,1,0);HAL_NVIC_SetPriority(L_IRQn,3,0);while(1){value++;}}
typedef void(*Vector)(void);
__attribute__((section(".isr_vector"))) Vector const vectors[23]={[1]=(Vector)main,[21]=CommonDispatcher,[22]=CommonDispatcher};
'''
        cfg=self.project({'app.c':source},contexts=[dict(id='main',kind='MAIN',functions=['main'])])
        facts,_=self.extract(cfg)
        contexts=[c for c in facts['contexts'] if c['kind']=='ISR']
        self.assertEqual(len(contexts),2)
        self.assertEqual(len({c['physical_id'] for c in contexts}),2)
        pair=next(r for r in facts['preemption_relations'] if set(r['contexts'])=={'vector:slot:21','vector:slot:22'})
        self.assertEqual(pair['relation'],'CAN_PREEMPT',pair)
        self.assertEqual(pair['higher'],'vector:slot:21')
        self.assertEqual(set(pair['priorities'].values()),{1,3})

    def test_enable_disable_and_masks_preserved(self):
        rows = self.scan('HAL_NVIC_SetPriority(TIM4_IRQn,2,0);HAL_NVIC_EnableIRQ(TIM4_IRQn);HAL_NVIC_DisableIRQ(TIM4_IRQn);__disable_irq();__set_BASEPRI(0x20);')
        self.assertFalse(rows['TIM4_IRQn']['enabled'])
        self.assertEqual(rows['TIM4_IRQn']['masks'], {'PRIMASK': 1, 'BASEPRI': 32})

    def test_runtime_reconfiguration_keeps_source_configuration(self):
        rows = self.scan('HAL_NVIC_SetPriority(TIM4_IRQn,2,0);',
                         'void Runtime(void){HAL_NVIC_SetPriority(TIM4_IRQn,1,0);}')
        # Uncalled functions cannot change the proven priority.
        self.assertEqual(rows['TIM4_IRQn']['effective_validity'], 'CONFIRMED')
        rows = self.scan('HAL_NVIC_SetPriority(TIM4_IRQn,2,0);while(1){HAL_NVIC_SetPriority(TIM4_IRQn,1,0);}')
        self.assertEqual(rows['TIM4_IRQn']['effective_validity'], 'UNRESOLVED')
        self.assertEqual(rows['TIM4_IRQn']['preemption_priority'], 2)
        self.assertTrue(rows['TIM4_IRQn']['runtime_reconfiguration'])

    def test_dynamic_and_conditional_configurations_remain_unknown(self):
        for body in ('if(condition)HAL_NVIC_SetPriority(TIM4_IRQn,2,0);',
                     'HAL_NVIC_SetPriority(TIM4_IRQn,condition,0);'):
            with self.subTest(body=body):
                row = self.scan(body)['TIM4_IRQn']
                self.assertEqual(row['effective_validity'], 'UNRESOLVED')
                self.assertIsNone(row['preemption_priority'])
                self.assertTrue(row['source_configurations'])

    def test_priority_reconfiguration_final_value_and_opaque_call(self):
        rows = self.scan('HAL_NVIC_SetPriority(TIM4_IRQn,2,0);HAL_NVIC_SetPriority(TIM4_IRQn,1,0);')
        self.assertEqual(rows['TIM4_IRQn']['preemption_priority'], 1)
        rows = self.scan('HAL_NVIC_SetPriority(TIM4_IRQn,2,0);Policy();', 'void Policy(void);')
        self.assertIsNone(rows['TIM4_IRQn']['preemption_priority'])
        self.assertEqual(rows['TIM4_IRQn']['configured_preemption'], 2)

    def test_standard_peripheral_struct_configuration(self):
        rows = self.scan('Setup();', '''
typedef struct{unsigned NVIC_IRQChannel,NVIC_IRQChannelPreemptionPriority,NVIC_IRQChannelSubPriority,NVIC_IRQChannelCmd;} NVIC_InitTypeDef;
void NVIC_Init(NVIC_InitTypeDef*);
void Setup(void){NVIC_InitTypeDef n;n.NVIC_IRQChannel=TIM4_IRQn;n.NVIC_IRQChannelPreemptionPriority=2;
n.NVIC_IRQChannelSubPriority=0;n.NVIC_IRQChannelCmd=1;NVIC_Init(&n);}
''')
        self.assertEqual(rows['TIM4_IRQn']['preemption_priority'], 2)
        self.assertTrue(rows['TIM4_IRQn']['enabled'])

    def test_register_configuration_uses_architecture_addresses(self):
        rows = self.scan('*(volatile unsigned*)0xE000ED0C=0x05FA0300;'
                         '*(volatile unsigned char*)0xE000E41E=0x20;'
                         '*(volatile unsigned*)0xE000E100=(1U<<30);')
        self.assertEqual(rows['TIM4_IRQn']['preemption_priority'], 2)
        self.assertTrue(rows['TIM4_IRQn']['enabled'])

    def test_packet_contains_resolved_values_locations_and_call_chains(self):
        self.scan('HAL_NVIC_SetPriority(TIM4_IRQn,2,0);HAL_NVIC_EnableIRQ(TIM4_IRQn);')
        finding = next(f for f in self.report['findings'] if f.get('symbol_id') == 'c:@shared')
        packet = build_variable_review_packet(self.root, self.facts, finding, facts_path='facts.json', shared_path='project.json', report_path='report.json')
        row = next(r for r in packet['nvic_priorities'] if r['irqn'] == ['TIM4_IRQn'])
        self.assertEqual(row['configured_preemption'], 2)
        event = row['source_configurations'][0]
        self.assertEqual(event['file'], 'app.c')
        self.assertGreater(event['line'], 0)
        self.assertEqual(event['call_chain'][0]['function'], 'main')
        self.assertTrue(packet['preemption_relations'])

    def test_main_isr_does_not_require_numeric_priority(self):
        self.scan('')
        relations = [r for r in self.facts['preemption_relations'] if 'main' in r['contexts']]
        self.assertTrue(relations)
        self.assertTrue(all(r['relation'] == 'CAN_PREEMPT' for r in relations))

    def test_missing_width_and_conflicting_width_do_not_invent_encoding(self):
        from ecra.nvic import recover
        self.scan('HAL_NVIC_SetPriority(TIM4_IRQn,2,0);')
        self.facts['irq_priority_events'] = [e for e in self.facts['irq_priority_events'] if e['api_name'] != 'CMSIS_NVIC_PRIO_BITS']
        recover(self.facts, self.cfg)
        row = next(r for r in self.facts['nvic_priorities'] if r['irqn'] == ['TIM4_IRQn'])
        self.assertEqual(row['configured_preemption'], 2)
        self.assertIsNone(row['priority_bits'])
        self.assertNotIn('TIM4', priority_model(self.facts, self.cfg)[0])
        self.facts['irq_priority_events'] += [dict(api_name='CMSIS_NVIC_PRIO_BITS',argument_values=[b]) for b in (3,4)]
        recover(self.facts,self.cfg)
        self.assertIsNone(self.facts['nvic_recovery']['priority_bits'])

    def test_constant_expression_priority_width(self):
        from ecra.nvic_extract import macro_value
        self.assertEqual(macro_value({'BITS': ['(', '1U', '<<', '2U', ')']}, 'BITS'), 4)
        self.assertIsNone(macro_value({'BITS': ['UNKNOWN']}, 'BITS'))

    def test_aircr_read_modify_write_preserves_unknown_other_bits(self):
        row = self.scan('*(volatile unsigned*)0xE000ED0C='
            '(*(volatile unsigned*)0xE000ED0C & ~0xFFFF0700U) | 0x05FA0300U;'
            'HAL_NVIC_SetPriority(TIM4_IRQn,2,0);')['TIM4_IRQn']
        self.assertEqual(row['preemption_priority'], 2)
        self.assertEqual(row['grouping'], 3)

    def test_struct_initializer_and_do_while_zero_macro(self):
        row = self.scan('Setup();', '''
typedef struct{unsigned NVIC_IRQChannel,NVIC_IRQChannelPreemptionPriority,NVIC_IRQChannelSubPriority,NVIC_IRQChannelCmd;} NVIC_InitTypeDef;
void NVIC_Init(NVIC_InitTypeDef*);
void Setup(void){NVIC_InitTypeDef n={TIM4_IRQn,2,0,1};do{NVIC_Init(&n);}while(0);}
''')['TIM4_IRQn']
        self.assertEqual(row['preemption_priority'], 2)
        self.assertTrue(row['enabled'])

    def test_disabled_struct_command_does_not_reprogram_priority(self):
        row=self.scan('HAL_NVIC_SetPriority(TIM4_IRQn,1,0);Setup();','''
typedef struct{unsigned NVIC_IRQChannel,NVIC_IRQChannelPreemptionPriority,NVIC_IRQChannelSubPriority,NVIC_IRQChannelCmd;} NVIC_InitTypeDef;
void NVIC_Init(NVIC_InitTypeDef*);
void Setup(void){NVIC_InitTypeDef n={TIM4_IRQn,2,0,0};NVIC_Init(&n);}
''')['TIM4_IRQn']
        self.assertEqual(row['preemption_priority'],1)
        self.assertFalse(row['enabled'])
        self.assertEqual(len(row['source_configurations']),1)

    def test_unknown_early_return_cannot_establish_unconditional_priority(self):
        row = self.scan('Setup();', 'void Setup(void){if(condition)return;{shared++;}HAL_NVIC_SetPriority(TIM4_IRQn,2,0);}')['TIM4_IRQn']
        self.assertEqual(row['effective_validity'], 'UNRESOLVED')

    def test_cmsis_encode_priority_and_more_urgent_irq(self):
        rows = self.scan('NVIC_SetPriority(TIM3_IRQn,NVIC_EncodePriority(5,2,1));NVIC_SetPriority(TIM4_IRQn,NVIC_EncodePriority(5,1,3));',
            'unsigned NVIC_EncodePriority(unsigned,unsigned,unsigned);',group='NVIC_PRIORITYGROUP_2')
        self.assertEqual(rows['TIM3_IRQn']['preemption_priority'],2)
        self.assertEqual(rows['TIM4_IRQn']['preemption_priority'],1)
        self.assertTrue(any(r['relation']=='CAN_PREEMPT' and set(r.get('priorities',{}).values())=={1,2} for r in self.facts['preemption_relations']))

    def test_faultmask_protects_normal_irq_but_not_nmi(self):
        for handler, expected in [('TIM4_IRQHandler','EFFECTIVE'),('NMI_Handler','INEFFECTIVE')]:
            source = 'volatile int g;void __disable_fault_irq(void);void __enable_fault_irq(void);'
            source += 'void ' + handler + '(void){g++;}int main(void){__disable_fault_irq();g++;__enable_fault_irq();}'
            cfg=self.project({'app.c':source},contexts=[dict(id='main',kind='MAIN',functions=['main'])])
            facts,_=self.extract(cfg)
            self.assertEqual(next(v for v in facts['variables'] if v['name']=='g')['protection_status'],expected)

    def test_integer_cast_and_short_circuit_follow_c_semantics(self):
        row=self.scan('Setup(258);','void Setup(unsigned p){unsigned char local=(unsigned char)p;'
                      'if(local==2)HAL_NVIC_SetPriority(TIM4_IRQn,2,0);else HAL_NVIC_SetPriority(TIM4_IRQn,3,0);}')['TIM4_IRQn']
        self.assertEqual(row['preemption_priority'],2)
        row=self.scan('if(0 && Configure()){}','int Configure(void){HAL_NVIC_SetPriority(TIM4_IRQn,2,0);return 1;}')['TIM4_IRQn']
        self.assertFalse(row['source_configurations'])

    def test_unmodeled_jump_cannot_prove_a_skipped_configuration(self):
        row=self.scan('Setup();','void Setup(void){goto end;HAL_NVIC_SetPriority(TIM4_IRQn,2,0);end:;}')['TIM4_IRQn']
        self.assertEqual(row['effective_validity'],'UNRESOLVED')


if __name__ == '__main__':
    unittest.main()
