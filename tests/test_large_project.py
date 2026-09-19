"""Real Clang scale fixtures; model protocol simulations are explicitly mocked."""
import copy
import json
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

import test_ecra
from ecra.cli import run
from ecra.review import review_all, validate_investigation, verify_receipt
from tests.review_fixtures import structured_fields


class ScreeningTests(unittest.TestCase):
    setUp = test_ecra.ProjectTest.setUp
    project = test_ecra.ProjectTest.project
    extract = test_ecra.ProjectTest.extract

    def test_unused_recursive_component_and_dead_writer_are_safe(self):
        cfg = self.project({'a.c': '''
            int dead, readonly; static int unused;
            void B(void); void A(void){dead++;B();} void B(void){A();}
            static void DeadWriter(void){readonly++;}
            int main(void){return readonly;}
        '''}, contexts=[dict(id='main', kind='MAIN', functions=['main'])])
        facts, report = self.extract(cfg)
        vars = {v['name']: v for v in facts['variables']}
        self.assertEqual(vars['dead']['screening_reason'], 'UNREACHABLE_ACCESSORS')
        self.assertEqual(vars['readonly']['screening_reason'], 'ONLY_READS')
        self.assertEqual(vars['unused']['screening_reason'], 'NO_RUNTIME_ACCESSES')
        self.assertEqual(vars['dead']['accesses'][0]['reachability'], 'PROVEN_UNREACHABLE')
        self.assertEqual(report['coverage']['unknown_accesses'], 0)

    def test_opaque_library_does_not_poison_private_objects(self):
        cfg = self.project({'a.c': '''
            void Library(void); static int private_state, readonly; int exported;
            static void Write(void){private_state++;}
            void UnknownReader(void){int a=readonly;}
            int main(void){Library();Write();return exported;}
        '''}, contexts=[dict(id='main', kind='MAIN', functions=['main'])])
        facts, _ = self.extract(cfg)
        vars = {v['name']: v for v in facts['variables']}
        self.assertEqual(vars['private_state']['screening_reason'], 'SINGLE_ACCESS_SITE')
        self.assertEqual(vars['readonly']['screening_reason'], 'ONLY_READS')
        self.assertIn('EXTERNAL_CALLEE', vars['exported']['screening_blockers'])
        self.assertIsNone(vars['exported']['screening_reason'])

    def test_escaped_and_attributed_functions_are_not_dead(self):
        cfg = self.project({'a.c': '''
            static int callback_state, startup_state;
            static void Callback(void){callback_state++;}
            void (*hook)(void)=Callback;
            static void __attribute__((constructor)) Startup(void){startup_state++;}
            int main(void){return 0;}
        '''}, contexts=[dict(id='main', kind='MAIN', functions=['main'])])
        facts, _ = self.extract(cfg)
        for v in facts['variables']:
            if v['name'].endswith('_state'):
                self.assertIsNone(v['screening_reason'])
                self.assertEqual(v['accesses'][0]['reachability'], 'UNKNOWN_ENTRY')

    def test_reentrant_single_write_remains_candidate(self):
        cfg = self.project({'a.c': 'static int state; void Task(void){state++;}'},
            contexts=[dict(id='task', kind='TASK', functions=['Task'], reentrant=True)])
        facts, report = self.extract(cfg)
        self.assertIsNone(facts['variables'][0]['screening_reason'])
        self.assertIn('GS-MULTI-WRITER', report['findings'][0]['rules'])

    def test_assembly_entry_and_variable_references_are_not_screened_away(self):
        cfg = self.project({'a.c': '''
            static int startup_state, normal; int assembly_state;
            void Startup(void){startup_state++;} int main(void){normal++;return 0;}
        '''}, contexts=[dict(id='main', kind='MAIN', functions=['main'])])
        (self.root/'startup.s').write_text('.word Startup\nbl main\n.word assembly_state\n',encoding='utf-8')
        database = self.root/'compile_commands.json'
        entries = json.loads(database.read_text(encoding='utf-8'))
        entries.append(dict(directory=str(self.root),file='startup.s',arguments=['arm-none-eabi-gcc','-c','startup.s']))
        database.write_text(json.dumps(entries),encoding='utf-8')
        facts, report = self.extract(cfg)
        variables = {v['name']: v for v in facts['variables']}
        self.assertIsNone(variables['startup_state']['screening_reason'])
        self.assertIsNone(variables['assembly_state']['screening_reason'])
        self.assertEqual(variables['normal']['screening_reason'], 'SINGLE_ACCESS_SITE')
        self.assertEqual(report['coverage']['assembly_sources'], ['startup.s'])

    def test_supplemental_and_missing_definition_have_variable_review_items(self):
        self.project({'a.c': 'extern int missing; int main(void){return missing;}',
                      'orphan.h': 'static int orphan;'},
                     contexts=[dict(id='main',kind='MAIN',functions=['main'])])
        with patch('builtins.print'):
            self.assertEqual(run(self.root,no_review=True),2)
        out = self.root/'.ecra'
        facts = json.loads((out/'facts.json').read_text(encoding='utf-8'))
        report = json.loads((out/'reports/global_static_concurrency.json').read_text(encoding='utf-8'))
        self.assertEqual({f['symbol_id'] for f in report['findings'] if f.get('symbol_id')},
                         {v['symbol_id'] for v in facts['variables']})
        self.assertEqual({v['name'] for v in facts['variables']},{'missing','orphan'})

    def test_local_pointees_and_function_dereferences_do_not_poison_globals(self):
        cfg = self.project({'a.c': '''
            static int readonly; static void Callback(void){}
            int main(void){int local=0; int *p=&local; *p=1;
                void (*cb)(void)=Callback; (*cb)(); return readonly;}
        '''}, contexts=[dict(id='main',kind='MAIN',functions=['main'])])
        facts, _ = self.extract(cfg)
        self.assertFalse(any(u['kind']=='UNRESOLVED_POINTEE' for u in facts['unknowns']))
        self.assertEqual(facts['variables'][0]['screening_reason'],'ONLY_READS')

    def test_dma_buffer_risk_does_not_become_pointer_storage_risk(self):
        cfg = self.project({'a.c': '''
            int HAL_UART_Receive_DMA(void *, unsigned char *, unsigned);
            static unsigned char buffer[16]; static unsigned char * const pointer=buffer;
            int main(void){HAL_UART_Receive_DMA(0,pointer,16);return 0;}
        '''}, contexts=[dict(id='main',kind='MAIN',functions=['main'])])
        facts, _ = self.extract(cfg)
        variables = {v['name']:v for v in facts['variables']}
        self.assertEqual(variables['pointer']['screening_reason'],'ONLY_READS')
        self.assertIsNone(variables['buffer']['screening_reason'])

    def test_250_files_1001_variables_full_pipeline(self):
        sources = {}
        for i in range(125):
            sources[f'module{i}.h'] = f'static int header_{i}; const int constant_{i}={i};\n'
            sources[f'module{i}.c'] = f'''#include "module{i}.h"
                static int unused_{i}; int readonly_{i}={i};
                static int serial_{i}, dead_{i}, one_{i};
                void Dead_{i}(void){{dead_{i}++;}}
                void Step_{i}(void){{static int local_{i}; local_{i}++; serial_{i}++;
                    header_{i}++; one_{i}=readonly_{i};}}
            '''
        sources['module0.c'] += '\n'.join(f'void Step_{i}(void);' for i in range(1,125))
        sources['module0.c'] += '\nint main(void){' + ''.join(f'Step_{i}();' for i in range(125)) + 'return 0;}\n'
        sources['module0.c'] += '''static int race; static void Update(void){race++;}
            void TIM2_IRQHandler(void){Update();} void TIM3_IRQHandler(void){Update();}'''
        self.project(sources, contexts=[dict(id='main', kind='MAIN', functions=['main'])])
        with patch('builtins.print'):
            code = run(self.root, no_review=True)
        self.assertIn(code, (0, 2))
        out = self.root/'.ecra'
        facts = json.loads((out/'facts.json').read_text(encoding='utf-8'))
        report = json.loads((out/'reports/global_static_concurrency.json').read_text(encoding='utf-8'))
        variables = facts['variables']
        self.assertEqual(len(variables), 1001)
        self.assertEqual(len({v['symbol_id'] for v in variables}), 1001)
        self.assertEqual(len(report['coverage']['file_coverage']), 250)
        self.assertTrue(all(r['parse_status']=='PARSED' and r['symbol_ids'] for r in report['coverage']['file_coverage']))
        self.assertEqual(report['coverage']['variable_accountability'],
                         dict(total=1001, screened=1000, queued=1, missing=0, duplicate_ids=0))
        self.assertEqual(report['risk_summary']['counts']['screened_safe'], 1000)
        self.assertEqual(report['risk_summary']['counts']['likely'], 1)
        queued = json.loads((out/'review/queue.json').read_text(encoding='utf-8'))
        self.assertEqual(len(queued), 1)
        self.assertEqual(queued[0]['finding_id'], report['findings'][0]['finding_id'])
        self.assertEqual(report['findings'][0]['variable_name'], 'race')
        html = (out/'index.html').read_text(encoding='utf-8')
        for v in variables:
            self.assertIn(v['qualified_name'], html)


class ReviewScaleTests(unittest.TestCase):
    setUp = test_ecra.ProjectTest.setUp

    def answer(self, packet):
        return dict(finding_id=packet['finding']['finding_id'], status='REVIEWED_SAFE',
            evidence=[dict(file='app.c',line=1,quote='int x;',claim='Protocol fixture only')],
            **{k:'Protocol fixture only' for k in ('reason','interleaving','protection','impact','fix','verification')},
            **structured_fields('REVIEWED_SAFE', review_type='VARIABLE'),
            investigation=[dict(id=r['id'],assessment='Protocol fixture only',evidence_refs=[1])
                           for r in packet['investigation_requirements']])

    def test_packet_includes_all_ancestors_and_marks_omitted_source(self):
        (self.root/'app.c').write_text('int x;\n' * 1800,encoding='utf-8')
        functions = [dict(function_id=f, name=f, file='app.c', line=1,
                          end_line=1800 if f=='Left' else 1) for f in ('Root','Left','Right','Use')]
        calls = [dict(caller_function_id=a, callee_function_id=b) for a,b in
                 [('Root','Left'),('Root','Right'),('Left','Use'),('Right','Use'),('Use','Use')]]
        facts = dict(variables=[], contexts=[], functions=functions, calls=calls)
        report = dict(findings=[dict(finding_id='F',symbol_id='x',accesses=[dict(
            access_id='A',function_id='Use',file='app.c',line=1,access_kind='READ',
            call_chains={'main':['Root','Left','Use']})])],coverage={},limitations=[])
        cfg = dict(review=dict(enabled=False,prepare_packets=True),analysis={})
        review_all(self.root,self.root/'.ecra',cfg,facts,report,'scan',lambda _:None)
        packet = json.loads((self.root/'.ecra/review/F.input.json').read_text(encoding='utf-8'))
        self.assertEqual({f['function_id'] for f in packet['functions']},{'Root','Left','Right','Use'})
        self.assertFalse(next(f for f in packet['source_context_manifest'] if f['function_id']=='Left')['complete'])
        self.assertIn('function:Right',{r['id'] for r in packet['investigation_requirements']})

    def test_one_broken_packet_does_not_abandon_remaining_variables(self):
        from ecra.common import write_json
        (self.root/'app.c').write_text('int x;\n',encoding='utf-8')
        facts = dict(variables=[],contexts=[],functions=[],calls=[])
        report = dict(findings=[dict(finding_id=f,symbol_id=f,accesses=[]) for f in ('Bad','Good')],
                      coverage={},limitations=[])
        cfg = dict(review=dict(enabled=True,workers=2,retries=0),analysis={})
        def write(path, value):
            if path.name=='Bad.input.json':
                raise OSError('Protocol fixture: unreadable packet')
            return write_json(path,value)
        def execute(argv,**kwargs):
            packet=json.loads(Path(argv[argv.index('--file')+1]).read_text(encoding='utf-8'))
            answer=self.answer(packet)
            return CompletedProcess(argv,0,json.dumps(dict(type='text',part=dict(text=json.dumps(answer)))), '')
        with patch('ecra.review.resolve_command',return_value=['fake-protocol-only']), patch(
                'ecra.review.execute',side_effect=execute), patch('ecra.review.write_json',side_effect=write):
            rows=review_all(self.root,self.root/'.ecra',cfg,facts,report,'scan',lambda _:None)
        self.assertEqual([r['state'] for r in rows],['FAILED','DONE'])
        queue=json.loads((self.root/'.ecra/review/queue.json').read_text(encoding='utf-8'))
        self.assertEqual([r['finding_id'] for r in queue],['Bad','Good'])

    def test_250_items_resume_exactly_and_reject_omitted_access(self):
        (self.root/'app.c').write_text('int x;\n', encoding='utf-8')
        findings = [dict(finding_id=f'F{i}', symbol_id=f'x{i}', rules=['GS-UNKNOWN-CONTEXT'],
            screening_blockers=['FUNCTION_ADDRESS'], accesses=[dict(access_id=f'A{i}',
                function_id='f', file='app.c', line=1, access_kind='WRITE')]) for i in range(250)]
        facts = dict(variables=[], contexts=[], functions=[], calls=[])
        report = dict(findings=findings, coverage={}, limitations=[])
        cfg = dict(review=dict(enabled=True, workers=4, max_items=73, retries=1), analysis={})
        seen = []
        def execute(argv, **kwargs):
            packet = json.loads(Path(argv[argv.index('--file')+1]).read_text(encoding='utf-8'))
            answer = self.answer(packet)
            seen.append(answer['finding_id'])
            if answer['finding_id'] == 'F0' and seen.count('F0') == 1:
                answer['investigation'].pop(0)
            return CompletedProcess(argv, 0, json.dumps(dict(type='text',part=dict(text=json.dumps(answer)))), '')
        with patch('ecra.review.resolve_command',return_value=['fake-protocol-only']), patch('ecra.review.execute',side_effect=execute):
            first = review_all(self.root,self.root/'.ecra',cfg,facts,report,'scan',lambda _:None)
            self.assertEqual(sum(r['state']=='DONE' for r in first),73)
            self.assertEqual(len(first),250)
            cfg['review']['max_items']=0
            second = review_all(self.root,self.root/'.ecra',cfg,facts,report,'scan',lambda _:None)
        self.assertEqual(len(seen),251)  # All 250 IDs, plus the rejected first answer.
        self.assertEqual(len(set(seen)),250)
        self.assertEqual(sum(r.get('cached',False) for r in second),73)
        self.assertTrue(all(r['state']=='DONE' for r in second))
        self.assertEqual([r['finding_id'] for r in second],[f['finding_id'] for f in findings])
        folder = self.root/'.ecra/review'
        packet = folder/'F0.input.json'
        data = json.loads(packet.read_text(encoding='utf-8'))
        verify_receipt(self.root, folder, second[0])
        missing = copy.deepcopy(second[0]['answer'])
        missing['investigation'].pop()
        with self.assertRaisesRegex(ValueError,'逐项覆盖'):
            validate_investigation(missing,data['investigation_requirements'])
        packet.write_text('{}',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'证据包'):
            verify_receipt(self.root, folder, second[0])


if __name__ == '__main__':
    unittest.main()
