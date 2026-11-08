"""Recovered physical entries cannot be overwritten by a logical label."""
import copy
import json
from pathlib import Path
import subprocess
import unittest

from tests import test_ecra as fixtures
from ecra.analysis import context_graph
from ecra.portable import tool_environment, tool_path


class ContextEvidenceCollisionTests(unittest.TestCase):
    setUp = fixtures.ProjectTest.setUp
    project = fixtures.ProjectTest.project
    extract = fixtures.ProjectTest.extract

    def compiled(self, source, contexts):
        cfg=self.project({'main.c':source},contexts=contexts)
        entry=json.loads((self.root/'compile_commands.json').read_text('utf-8'))[0]
        result=subprocess.run(entry['arguments'],cwd=self.root,env=tool_environment(),
                              capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        if '.isr_vector' in source:
            objdump=Path(tool_path('arm-none-eabi-gcc')).parent/'arm-none-eabi-objdump.exe'
            proof=subprocess.run([str(objdump),'-r','main.c.o'],cwd=self.root,env=tool_environment(),
                                 capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=30)
            self.assertEqual(proof.returncode,0,proof.stderr)
            self.assertIn('RELOCATION RECORDS FOR [.isr_vector]',proof.stdout)
        return cfg

    def vector(self, slot, supplement=None, mask='__disable_irq();', slots=None):
        slots=slots or [slot]
        source='''typedef void (*handler)(void); int shared;
void __disable_irq(void); void __set_FAULTMASK(unsigned); void __set_BASEPRI(unsigned);
void ExceptionRoute(void){shared++;} void Other(void){}
const handler vectors['''+str(max(slots)+1)+'''] __attribute__((section(".isr_vector"),used))={'''+','.join('['+str(s)+']=ExceptionRoute' for s in slots)+'''};
int main(void){'''+mask+''' shared++; return 0;}
'''
        contexts=[dict(id='main',kind='MAIN',functions=['main'])]
        if supplement is not None:
            context=dict(id='vector:slot:'+str(slot),kind='ISR',functions=['ExceptionRoute'])
            context.update(supplement);contexts.append(context)
        cfg=self.compiled(source,contexts)
        facts,report=self.extract(cfg)
        return next(v for v in facts['variables'] if v['name']=='shared'),facts,report

    def test_missing_identity_keeps_source_nmi_hardfault_and_faultmask_distinction(self):
        for slot in (2,3):
            with self.subTest(slot=slot):
                value,facts,_=self.vector(slot,{})
                self.assertEqual(value['static_classification'],'SUSPECT')
                context=next(c for c in facts['contexts'] if c['id']=='vector:slot:'+str(slot))
                self.assertEqual(context['slot'],slot)
                self.assertTrue(context['unmaskable'])
                self.assertEqual(context['vector'],'slot:'+str(slot))
                self.assertNotEqual(context['discovery'],'configured')
        value,_,_=self.vector(2,{},'__set_FAULTMASK(1);')
        self.assertEqual(value['static_classification'],'SUSPECT')
        value,_,_=self.vector(3,{},'__set_FAULTMASK(1);')
        self.assertEqual(value['static_classification'],'SAFE_PROVEN')
        value,_,_=self.vector(2,dict(enabled=False))
        self.assertEqual(value['static_classification'],'SUSPECT')

    def test_unknown_wrong_vector_and_different_roots_or_kind_are_explicit_errors(self):
        variants=[dict(vector='UnknownVector'),dict(vector='slot:unknown'),dict(vector='TIM2_IRQHandler'),
                  dict(irq=2),dict(slot=17),dict(unmaskable=False),dict(kind='MAIN'),dict(functions=['Other'])]
        for slot in (2,3):
            for value in variants:
                with self.subTest(slot=slot,configuration=value),self.assertRaisesRegex(ValueError,'物理入口冲突'):
                    self.vector(slot,value)

    def test_proved_matching_supplements_keep_separate_configuration_evidence(self):
        for slot,name,irq in ((2,'NMI_Handler',-14),(3,'HardFault_Handler',-13)):
            for supplement in (dict(vector=name),dict(vector='slot:'+str(slot)),dict(irq=irq),dict(unmaskable=True)):
                with self.subTest(slot=slot,supplement=supplement):
                    value,facts,_=self.vector(slot,supplement)
                    self.assertEqual(value['static_classification'],'SUSPECT')
                    context=next(c for c in facts['contexts'] if c['id']=='vector:slot:'+str(slot))
                    self.assertEqual(context['slot'],slot)
                    self.assertEqual(context['vector'],'slot:'+str(slot))
                    self.assertEqual(context['configuration_evidence'][0],dict(id=context['id'],kind='ISR',functions=['ExceptionRoute'],**supplement))

    def test_faultmask_does_not_accept_unknown_or_other_unmaskable_domains(self):
        source='''int shared;void __set_FAULTMASK(unsigned);
void ExceptionRoute(void){shared++;}int main(void){__set_FAULTMASK(1);shared++;return 0;}
'''
        for extra in ({},dict(vector='UnknownVector'),dict(vector='slot:18'),dict(vector='slot:3',irq=2)):
            with self.subTest(identity=extra):
                cfg=self.compiled(source,[dict(id='main',kind='MAIN',functions=['main']),
                    dict(id='exception',kind='ISR',functions=['ExceptionRoute'],unmaskable=True,**extra)])
                facts,_=self.extract(cfg);value=next(v for v in facts['variables'] if v['name']=='shared')
                self.assertNotEqual(value['static_classification'],'SAFE_PROVEN')
                self.assertNotEqual(value['protection_status'],'EFFECTIVE')

    def test_ordinary_irq_and_separate_logical_alias_remain_usable(self):
        for supplement in ({},dict(irq=2),dict(vector='ExceptionRoute'),dict(vector='slot:18'),
                           dict(id='ordinary',vector='slot:18')):
            with self.subTest(supplement=supplement):
                value,facts,_=self.vector(18,supplement)
                self.assertEqual(value['static_classification'],'SAFE_PROVEN')
                context=next(c for c in facts['contexts'] if c.get('physical_id')=='IRQ:slot:18')
                self.assertEqual(context['slot'],18)
                self.assertFalse(context['unmaskable'])
                self.assertIn('c:@F@ExceptionRoute',next(c for c in facts['physical_contexts'] if c['physical_id']=='IRQ:slot:18')['entry_functions'])

    def test_shared_function_keeps_each_actual_slot(self):
        value,facts,_=self.vector(2,{},slots=[2,18])
        self.assertEqual(value['static_classification'],'SUSPECT')
        self.assertEqual({c['slot'] for c in facts['contexts'] if c['kind']=='ISR'},{2,18})
        with self.assertRaisesRegex(ValueError,'物理入口冲突'):
            self.vector(2,dict(vector='slot:18'),slots=[2,18])

    def test_same_slot_multiple_tables_keep_all_actual_roots_and_origins(self):
        for slot in (2,17):
            source='''typedef void(*handler)(void);int shared;void __disable_irq(void);
void First(void){shared++;}void Second(void){shared++;}
const handler vector_a['''+str(slot+1)+'''] __attribute__((section(".isr_vector"),used))={['''+str(slot)+''']=First};
const handler vector_b['''+str(slot+1)+'''] __attribute__((section(".vectors"),used))={['''+str(slot)+''']=Second};
int main(void){__disable_irq();shared++;return 0;}
'''
            cfg=self.compiled(source,[dict(id='main',kind='MAIN',functions=['main'])])
            facts,_=self.extract(cfg);cid='vector:slot:'+str(slot)
            context=next(c for c in facts['contexts'] if c['id']==cid)
            self.assertEqual({row['function_id'] for row in context['source_entries']},{'c:@F@First','c:@F@Second'})
            self.assertEqual({row['function_id'] for row in facts['context_bindings'] if row['context_id']==cid and row['call_depth']==0},{'c:@F@First','c:@F@Second'})
            value=next(v for v in facts['variables'] if v['name']=='shared')
            self.assertEqual(value['static_classification'],'SUSPECT' if slot==2 else 'SAFE_PROVEN')

    def test_source_priority_and_grouping_cannot_be_replaced_or_auto_merged_inconsistently(self):
        source=dict(id='hardware',kind='DMA',function_id='entry',priority=1,grouping=3,channel='one')
        functions=[dict(function_id='entry',name='Entry',qualified_name='Entry()',file='a.c',line=1)]
        def run(hardware,configured):
            facts=dict(functions=copy.deepcopy(functions),calls=[],registrations=[],unknowns=[],hardware_contexts=copy.deepcopy(hardware))
            cfg=dict(call_edges=[],contexts=configured,analysis=dict(auto_contexts=False))
            return context_graph(facts,cfg),facts
        for key,value in (('priority',7),('grouping',5),('channel','two')):
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'物理入口冲突'):
                run([source],[dict(id='hardware',kind='DMA',functions=['Entry'],**{key:value})])
            other=dict(source,**{key:value})
            with self.subTest(source_key=key),self.assertRaisesRegex(ValueError,'矛盾物理证据'):
                run([source,other],[])
        (contexts,_,_),_=run([source],[dict(id='hardware',kind='DMA',functions=['Entry'],priority=1,grouping=3)])
        self.assertEqual((contexts['hardware']['priority'],contexts['hardware']['grouping']),(1,3))

    def test_basepri_uses_actual_slot_priority_and_grouping(self):
        source='''#define __NVIC_PRIO_BITS 4
enum{HIGH_IRQn=0,LOW_IRQn=1};void HAL_NVIC_SetPriorityGrouping(unsigned);
void HAL_NVIC_SetPriority(int,unsigned,unsigned);void __set_BASEPRI(unsigned);int shared;
void High(void){shared++;}void Low(void){shared++;}
typedef void(*handler)(void);const handler vectors[18] __attribute__((section(".isr_vector"),used))={[16]=High,[17]=Low};
int main(void){HAL_NVIC_SetPriorityGrouping(3);HAL_NVIC_SetPriority(HIGH_IRQn,1,0);HAL_NVIC_SetPriority(LOW_IRQn,7,0);__set_BASEPRI(0x50);shared++;return 0;}
'''
        main=dict(id='main',kind='MAIN',functions=['main'])
        for supplement in ({},dict(priority=7,grouping=5)):
            context=dict(id='vector:slot:16',kind='ISR',functions=['High'],**supplement)
            cfg=self.compiled(source,[main,context]);facts,_=self.extract(cfg)
            value=next(v for v in facts['variables'] if v['name']=='shared')
            self.assertEqual(value['static_classification'],'SUSPECT')
            self.assertNotEqual(value['protection_status'],'EFFECTIVE')
            priorities={row['irq_number']:row for row in facts['nvic_priorities']}
            self.assertEqual(priorities[0]['preemption_priority'],1)
            self.assertEqual(priorities[1]['preemption_priority'],7)
            self.assertEqual(priorities[0]['subpriority_bits'],0)
            actual=next(c for c in facts['contexts'] if c['id']=='vector:slot:16')
            self.assertEqual(actual['vector'],'slot:16')
            self.assertNotIn('priority',actual)
            self.assertNotIn('grouping',actual)
        cfg=self.compiled(source,[main,dict(id='vector:slot:16',kind='ISR',functions=['High'],vector='slot:17')])
        with self.assertRaisesRegex(ValueError,'物理入口冲突'):
            self.extract(cfg)

    def test_later_name_discovery_cannot_overwrite_another_configured_entry(self):
        source='''int shared;void __disable_irq(void);void TIM2_IRQHandler(void){shared++;}
void OtherTask(void){shared++;}int main(void){__disable_irq();shared++;return 0;}
'''
        main=dict(id='main',kind='MAIN',functions=['main'])
        cfg=self.compiled(source,[main]);facts,_=self.extract(cfg)
        cid=next(c['id'] for c in facts['contexts'] if c['id'].startswith('auto:TIM2_IRQHandler:'))
        cfg=self.compiled(source,[main,dict(id=cid,kind='TASK',functions=['OtherTask'])])
        with self.assertRaisesRegex(ValueError,'物理入口冲突|上下文标识冲突'):
            self.extract(cfg)

    def test_pattern_split_cannot_overwrite_a_different_configured_entry(self):
        source='''int shared;void TIM1_IRQHandler(void){shared++;}void USART1_IRQHandler(void){shared++;}
void OtherTask(void){shared++;}int main(void){return 0;}
'''
        cfg=self.compiled(source,[dict(id='main',kind='MAIN',functions=['main']),
            dict(id='mux',kind='ISR',patterns=['*_IRQHandler']),
            dict(id='mux:USART1_IRQHandler',kind='TASK',functions=['OtherTask'])])
        with self.assertRaisesRegex(ValueError,'上下文标识冲突'):
            self.extract(cfg)

    def test_legitimate_timer_daemon_reuse_and_wrong_claim_remain_distinct(self):
        source='''void*xTimerCreate(const char*,unsigned,int,void*,void(*)(void*));
int xTimerPendFunctionCall(void(*)(void*,unsigned),void*,unsigned,unsigned);int shared;
void Timer(void*p){shared++;}void Deferred(void*p,unsigned n){shared+=n;}void Other(void){}
int main(void){xTimerCreate("timer",1,1,0,Timer);xTimerPendFunctionCall(Deferred,0,1,0);return 0;}
'''
        main=dict(id='main',kind='MAIN',functions=['main']);cid='auto:freertos:timer_daemon'
        for contexts in ([main],[main,dict(id=cid,kind='TASK',functions=['Timer'])]):
            cfg=self.compiled(source,contexts);facts,_=self.extract(cfg)
            daemon=next(c for c in facts['contexts'] if c['id']==cid)
            self.assertEqual(daemon['kind'],'TASK');self.assertFalse(daemon['reentrant'])
            self.assertEqual({row['function_id'] for row in facts['context_bindings'] if row['context_id']==cid and row['call_depth']==0},{'c:@F@Timer','c:@F@Deferred'})
        cfg=self.compiled(source,[main,dict(id=cid,kind='MAIN',functions=['Other'])])
        with self.assertRaisesRegex(ValueError,'物理入口冲突|上下文标识冲突'):
            self.extract(cfg)

    def test_task_registration_keeps_matching_and_explicit_named_groups(self):
        from ecra.config import load_config
        source='''void Register(void(*entry)(void*));int shared;
void Worker(void*p){shared++;}void Other(void){}int main(void){Register(Worker);return 0;}
'''
        main=dict(id='main',kind='MAIN',functions=['main'])
        def prepared(contexts,context_id=None):
            self.compiled(source,contexts)
            path=self.root/'.ecra/semantics.yaml';cfg=json.loads(path.read_text('utf-8'))
            rule=dict(api='Register',callback_arg=0,kind='TASK',may_repeat=False)
            if context_id is not None:rule['context_id']=context_id
            cfg['entry_registrations']=[rule];path.write_text(json.dumps(cfg),'utf-8')
            return load_config(self.root)[0]
        facts,_=self.extract(prepared([main]))
        generated=next(c['id'] for c in facts['contexts'] if c['id'].startswith('auto:task:Worker:'))
        for cid,explicit in ((generated,None),('legitimate_group','legitimate_group')):
            cfg=prepared([main,dict(id=cid,kind='TASK',functions=['Worker'])],explicit)
            facts,_=self.extract(cfg)
            self.assertIn('c:@F@Worker',{row['function_id'] for row in facts['context_bindings'] if row['context_id']==cid and row['call_depth']==0})
        cfg=prepared([main,dict(id=generated,kind='ISR',functions=['Other'])])
        with self.assertRaisesRegex(ValueError,'物理入口冲突|上下文标识冲突'):
            self.extract(cfg)


if __name__=='__main__':unittest.main()
