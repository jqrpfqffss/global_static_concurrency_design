"""GNU alias identity must preserve real interrupt bodies and linker choice."""
import copy
import json
from pathlib import Path
import re
import subprocess
import unittest
from unittest.mock import patch

from tests import test_ecra as fixtures
from ecra.analysis import analyze, merge
from ecra.compilation import prepare
from ecra.extract import Extractor
from ecra.portable import tool_environment, tool_path


class FunctionAliasEntryTests(unittest.TestCase):
    setUp = fixtures.ProjectTest.setUp
    project = fixtures.ProjectTest.project

    def compiled(self, sources, *, link=False, contexts=None):
        cfg = self.project(sources, contexts=contexts or [dict(id='main',kind='MAIN',functions=['main'])])
        gcc = tool_path('arm-none-eabi-gcc')
        commands = []
        for name in sources:
            if Path(name).suffix not in {'.c', '.S', '.s'}:
                continue
            argv=[gcc,'-mcpu=cortex-m4','-mthumb','-c',name,'-o',name+'.o']
            result=subprocess.run(argv,cwd=self.root,env=tool_environment(),capture_output=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stderr)
            commands.append(dict(directory=str(self.root),file=name,arguments=argv))
        (self.root/'compile_commands.json').write_text(json.dumps(commands),encoding='utf-8')
        if link:
            objects=[row['file']+'.o' for row in commands]
            linked=subprocess.run([gcc,'-mcpu=cortex-m4','-mthumb','-nostdlib','-Wl,-e,main',
                '-Wl,-Map,firmware.map',*objects,'-o','firmware.elf'],cwd=self.root,
                env=tool_environment(),capture_output=True,timeout=30)
            self.assertEqual(linked.returncode,0,linked.stderr)
            target='firmware.elf'
        else:
            target=commands[0]['file']+'.o'
        tools=Path(gcc).parent
        nm=subprocess.run([str(tools/'arm-none-eabi-nm.exe'),'-n',target],cwd=self.root,
            env=tool_environment(),capture_output=True,check=True,timeout=30).stdout.decode('ascii')
        relocation=subprocess.run([str(tools/'arm-none-eabi-objdump.exe'),'-r',commands[0]['file']+'.o'],
            cwd=self.root,env=tool_environment(),capture_output=True,check=True,timeout=30).stdout.decode('ascii')
        self.native=dict(nm=nm,relocations=relocation,linked=link)
        return cfg

    def facts(self,cfg):
        units,audit=prepare(self.root,cfg)
        parts=[Extractor(dict(root=str(self.root),unit=unit,config=cfg)).run() for unit in units]
        for part in parts:
            self.assertEqual(part['parse_status'],'PARSED',part['diagnostics'])
        facts=merge(parts)
        return facts,dict(translation_units_failed=0,**audit)

    def scan(self,cfg):
        facts,coverage=self.facts(cfg)
        report=analyze(facts,cfg,coverage,self.root)
        return facts,report

    def shared(self,facts):
        return next(v for v in facts['variables'] if v['name']=='shared')

    def native_symbol(self,name):
        return next((int(address,16),kind) for address,kind,symbol in
                    re.findall(r'^([0-9a-fA-F]+)[ \t]+(\w)[ \t]+(\S+)[ \t]*\r?$',self.native['nm'],re.M) if symbol==name)

    def source(self,slot=2,declaration='void ExceptionRoute(void)__attribute__((alias("Impl")));',later=False):
        body='void Impl(void){shared++;}'
        return ('typedef void(*handler)(void);int shared;void __disable_irq(void);\n'
                + (declaration+'\n'+body if later else body+'\n'+declaration)
                + '\nconst handler vectors['+str(slot+1)+'] __attribute__((section(".isr_vector"),used))={['+str(slot)+']=ExceptionRoute};'
                + '\nint main(void){__disable_irq();shared++;return 0;}')

    def test_actual_nmi_and_hardfault_alias_preserve_body_and_slot(self):
        for slot in (2,3):
            with self.subTest(slot=slot):
                cfg=self.compiled({'main.c':self.source(slot)})
                self.assertEqual(self.native_symbol('ExceptionRoute')[0],self.native_symbol('Impl')[0])
                self.assertIn(f'{slot*4:08x}',self.native['relocations'])
                facts,_=self.scan(cfg)
                variable=self.shared(facts)
                self.assertEqual(variable['static_classification'],'SUSPECT')
                self.assertEqual(variable['protection_status'],'INEFFECTIVE')
                alias=next(f for f in facts['functions'] if f['name']=='ExceptionRoute')
                impl=next(f for f in facts['functions'] if f['name']=='Impl')
                self.assertEqual(alias['function_alias']['target_function_id'],impl['function_id'])
                edge=next(c for c in facts['calls'] if c['call_kind']=='GNU_FUNCTION_ALIAS')
                self.assertEqual(edge['caller_function_id'],alias['function_id'])
                self.assertEqual(edge['callee_function_id'],impl['function_id'])
                self.assertEqual(edge['alias_evidence']['declaration']['file'],'main.c')
                entry=next(e for e in facts['vector_entries'] if e['slot']==slot)
                self.assertEqual(entry['function_id'],alias['function_id'])
                self.assertTrue(entry['unmaskable'])
                self.assertTrue(any(b['function_id']==impl['function_id'] and b['call_depth']>0 for b in facts['context_bindings']))

    def test_ordinary_irq_alias_still_allows_complete_primask(self):
        cfg=self.compiled({'main.c':self.source(21)})
        facts,_=self.scan(cfg)
        self.assertEqual(self.shared(facts)['static_classification'],'SAFE_PROVEN')
        self.assertEqual(self.shared(facts)['protection_status'],'EFFECTIVE')
        self.assertTrue(any(e['slot']==21 for e in facts['vector_entries']))
        self.assertTrue(any(c['call_kind']=='GNU_FUNCTION_ALIAS' for c in facts['calls']))

    def test_late_target_and_header_prototype_use_complete_tu(self):
        cfg=self.compiled({'header.h':'void Impl(void); void ExceptionRoute(void);',
                          'main.c':'#include "header.h"\n'+self.source(later=True)})
        facts,_=self.scan(cfg)
        self.assertEqual(self.shared(facts)['static_classification'],'SUSPECT')
        evidence=next(f['function_alias'] for f in facts['functions'] if f['name']=='ExceptionRoute')
        self.assertEqual(evidence['target_definition']['file'],'main.c')
        self.assertGreater(evidence['target_definition']['line'],evidence['declaration']['line'])

    def test_compiler_expanded_macro_attributes_are_exact_evidence(self):
        for definition,use in [('#define ALIAS(x) __attribute__((alias(x)))','ALIAS("Impl")'),
                               ('#define ALIAS(x) __attribute__((alias(#x)))','ALIAS(Impl)'),
                               ('#define FIXED __attribute__((alias("Impl")))','FIXED')]:
            with self.subTest(use=use):
                declaration='void ExceptionRoute(void) '+use+';'
                cfg=self.compiled({'main.c':definition+'\n'+self.source(declaration=declaration,later=True)})
                facts,_=self.scan(cfg)
                self.assertEqual(self.shared(facts)['static_classification'],'SUSPECT')
                alias=next(f['function_alias'] for f in facts['functions'] if f['name']=='ExceptionRoute')
                self.assertEqual(alias['target_symbol'],'Impl')

    def test_non_alias_string_and_comment_do_not_create_alias_edges(self):
        source=self.source(declaration='void ExceptionRoute(void){shared++;}')
        source+='\n/* alias("Impl") */ void Unused(void)__attribute__((annotate("alias(\\"Impl\\")")));'
        cfg=self.compiled({'main.c':source})
        facts,_=self.scan(cfg)
        self.assertFalse(any(f.get('function_alias') for f in facts['functions']))
        self.assertFalse(any(c['call_kind']=='GNU_FUNCTION_ALIAS' for c in facts['calls']))

    def test_static_same_name_target_never_crosses_translation_units(self):
        main=self.source().replace('void Impl(void)','static void Impl(void)',1)
        cfg=self.compiled({'main.c':main,'other.c':'int unrelated;static void Impl(void){unrelated++;}void Other(void){Impl();}'})
        facts,_=self.scan(cfg)
        alias=next(f['function_alias'] for f in facts['functions'] if f['name']=='ExceptionRoute')
        target=next(f for f in facts['functions'] if f['function_id']==alias['target_function_id'])
        self.assertEqual(target['file'],'main.c')
        self.assertTrue(target['is_static'])
        self.assertIn('tu::main.c::',target['function_id'])
        self.assertEqual(self.shared(facts)['static_classification'],'SUSPECT')

    def weak_sources(self,strong_body='shared++;'):
        startup='''typedef void(*handler)(void);extern int shared;int default_only;
void NMI_Handler(void)__attribute__((weak,alias("Default_Handler")));
const handler vectors[3] __attribute__((section(".isr_vector"),used))={[2]=NMI_Handler};
int main(void){shared++;return 0;}
void Default_Handler(void){default_only++;}
'''
        override='int shared;void NMI_Handler(void){'+strong_body+'}'
        return startup,override

    def test_actual_link_strong_c_overrides_weak_alias_in_both_input_orders(self):
        for reverse in (False,True):
            for body in ('shared++;',''):
                with self.subTest(reverse=reverse,body=body):
                    startup,override=self.weak_sources(body)
                    sources=dict([('startup.c',startup),('override.c',override)][::-1 if reverse else 1])
                    cfg=self.compiled(sources,link=True)
                    self.assertEqual(self.native_symbol('NMI_Handler')[1],'T')
                    self.assertNotEqual(self.native_symbol('NMI_Handler')[0],self.native_symbol('Default_Handler')[0])
                    facts,_=self.scan(cfg)
                    chosen=next(f for f in facts['functions'] if f['name']=='NMI_Handler')
                    self.assertEqual(chosen['file'],'override.c')
                    self.assertFalse(chosen.get('function_alias'))
                    self.assertFalse(any(c['call_kind']=='GNU_FUNCTION_ALIAS' for c in facts['calls']))
                    self.assertEqual(self.shared(facts)['static_classification'],'SUSPECT' if body else 'SAFE_PROVEN')

    def test_actual_link_weak_alias_selects_default_without_override(self):
        startup,_=self.weak_sources()
        cfg=self.compiled({'startup.c':startup+'\nint shared;'},link=True)
        self.assertEqual(self.native_symbol('NMI_Handler')[1],'W')
        self.assertEqual(self.native_symbol('NMI_Handler')[0],self.native_symbol('Default_Handler')[0])
        facts,_=self.scan(cfg)
        self.assertTrue(any(c['call_kind']=='GNU_FUNCTION_ALIAS' for c in facts['calls']))

    def test_actual_link_assembler_override_is_explicitly_rejected(self):
        startup,_=self.weak_sources()
        assembly='''.syntax unified
.thumb
.global NMI_Handler
.type NMI_Handler,%function
.thumb_func
NMI_Handler:
ldr r0,=shared
ldr r1,[r0]
adds r1,#1
str r1,[r0]
bx lr
.size NMI_Handler,.-NMI_Handler
'''
        cfg=self.compiled({'startup.c':startup+'\nint shared;','override.S':assembly},link=True)
        self.assertEqual(self.native_symbol('NMI_Handler')[1],'T')
        self.assertNotEqual(self.native_symbol('NMI_Handler')[0],self.native_symbol('Default_Handler')[0])
        facts,coverage=self.facts(cfg)
        self.assertTrue(facts['accesses'])
        with self.assertRaisesRegex(ValueError,'UNRESOLVED_FUNCTION_ALIAS_LINKAGE'):
            analyze(facts,cfg,coverage,self.root)
        self.assertFalse(any('static_classification' in v for v in facts['variables']))

    def test_actual_link_weak_target_interposition_is_not_guessed(self):
        source=self.source().replace('void Impl(void){','void Impl(void)__attribute__((weak));void Impl(void){')
        source=source.replace('void __disable_irq(void);','void __disable_irq(void){}')
        cfg=self.compiled({'main.c':source,'override.c':'void Impl(void){}'},link=True)
        self.assertNotEqual(self.native_symbol('ExceptionRoute')[0],self.native_symbol('Impl')[0])
        facts,coverage=self.facts(cfg)
        with self.assertRaisesRegex(ValueError,'UNRESOLVED_FUNCTION_ALIAS'):
            analyze(facts,cfg,coverage,self.root)
        self.assertTrue(facts['accesses'])

    def test_preprocessed_assembler_cannot_hide_strong_override(self):
        startup,_=self.weak_sources()
        assembly='''#define ROUTE NMI_Handler
.syntax unified
.thumb
.global ROUTE
.type ROUTE,%function
.thumb_func
ROUTE:
bx lr
.size ROUTE,.-ROUTE
'''
        cfg=self.compiled({'startup.c':startup+'\nint shared;','override.S':assembly},link=True)
        self.assertEqual(self.native_symbol('NMI_Handler')[1],'T')
        facts,coverage=self.facts(cfg)
        with self.assertRaisesRegex(ValueError,'UNRESOLVED_FUNCTION_ALIAS_LINKAGE'):
            analyze(facts,cfg,coverage,self.root)
        self.assertTrue(facts['accesses'])

    def test_parameter_forwarding_unsupported_is_explicit_not_empty_safe_body(self):
        source='int shared;void Impl(int *p){(*p)++;}void Alias(int *p)__attribute__((alias("Impl")));int main(void){Alias(&shared);return 0;}'
        cfg=self.compiled({'main.c':source})
        facts,coverage=self.facts(cfg)
        with self.assertRaisesRegex(ValueError,'UNRESOLVED_FUNCTION_ALIAS'):
            analyze(facts,cfg,coverage,self.root)
        self.assertFalse(any('static_classification' in v for v in facts['variables']))

    def test_unavailable_macro_expansion_evidence_never_guesses_target(self):
        cfg=self.compiled({'main.c':'#define ALIAS(x) __attribute__((alias(#x)))\n'+self.source(declaration='void ExceptionRoute(void) ALIAS(Impl);')})
        with patch('ecra.extract.function_alias_target',side_effect=AttributeError('unsupported printing API')):
            facts,coverage=self.facts(cfg)
        alias=next(f['function_alias'] for f in facts['functions'] if f['name']=='ExceptionRoute')
        self.assertEqual(alias['status'],'UNRESOLVED')
        with self.assertRaisesRegex(ValueError,'UNRESOLVED_FUNCTION_ALIAS'):
            analyze(facts,cfg,coverage,self.root)
