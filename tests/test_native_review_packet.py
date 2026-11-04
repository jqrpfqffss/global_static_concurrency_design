"""Complete serialized Packet comparisons; never a real model/G2 claim."""
import json
import random
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ecra import scan_store
from ecra.native_review_packet import PacketInputs,packet_inputs,shared_context
from ecra.review import build_variable_review_packet
from ecra.scan_store import EvidenceProvider,publish_scan
from scripts.validate_studio_baseline import strict_difference
from tests import test_deep_review as fixtures


class NativePacketReaderTests(unittest.TestCase):
    def test_streamed_review_cache_digest_is_exact_old_json_digest(self):
        from ecra.common import digest as original
        from ecra.review_hash import digest
        scalars=[None,True,False,0,1,-1,2**150,-0.0,0.0,1e-17,'中😀\n\t"\\',float('inf'),float('nan')]
        cases=[scalars,dict(z=scalars,a=[dict(b='value',a=1),dict(a=1,b='value')]),{'long':'汉😀'*100000}]
        rng=random.Random(19271)
        cases.extend({str(index):[rng.choice(scalars) for unused in range(23)] for index in range(50)} for unused in range(15))
        for value in cases:self.assertEqual(digest(value),original(value))
        for function in (original,digest):
            with self.assertRaises(UnicodeEncodeError):function({'surrogate':'\ud800'})

    def assert_packet(self,path,root,facts,finding,*,forbidden_nodes=()):
        options=dict(facts_path=Path('facts-navigation.json'),shared_path=Path('project-evidence.json'),report_path=Path('report-navigation.json'))
        expected=build_variable_review_packet(root,facts,finding,**options)
        original=PacketInputs.value
        def guarded(reader,node):
            self.assertNotIn(node,forbidden_nodes,'Unrelated/CFG node payload must stay in the authority')
            return original(reader,node)
        with patch.object(EvidenceProvider,'load',side_effect=AssertionError('Whole facts reconstruction forbidden')),patch.object(PacketInputs,'value',new=guarded):
            with packet_inputs(path,finding['finding_id']) as (selected,current):
                actual=build_variable_review_packet(root,selected,current,**options)
        # Compare the actual JSON Packet contract. Existing tuple -> JSON array
        # encoding is unchanged; order, duplicates and every typed value remain.
        self.assertIsNone(strict_difference(json.loads(json.dumps(expected)),json.loads(json.dumps(actual))))
        self.assertEqual(json.dumps(expected,ensure_ascii=True),json.dumps(actual,ensure_ascii=True))
        return actual

    def test_six_actual_clang_deep_review_packets_equal_original_full_facts(self):
        for filename,statuses in fixtures.CASES:
            with self.subTest(filename=filename):
                case=fixtures.DeepReviewTests(methodName='runTest');case.setUp();self.addCleanup(case.doCleanups)
                cfg,facts,report,packet,out=case.prepare_case(filename)
                path=out/'packet-test/scan.db';publish_scan(path,facts,report,scan_id='s',project_id='p')
                self.assert_packet(path,case.root,facts,report['findings'][0])
                expected=dict(contexts=facts.get('contexts',[]),coverage=report.get('coverage',{}),limitations=report.get('limitations',[]),
                    compile_commands=[{key:row[key] for key in ('source_file','arguments','parse_status','diagnostics') if key in row}
                        for row in facts.get('translation_units',[])],
                    source_files=sorted({row['file'] for row in facts.get('functions',[]) if row.get('file')}))
                self.assertEqual(json.dumps(expected,ensure_ascii=True),json.dumps(shared_context(path),ensure_ascii=True))

    def test_legacy_and_current_order_duplicates_reverse_closure_alias_fields_and_global_candidate(self):
        access=dict(access_id='a',function_id='leaf',file='main.c',line=1,
            call_chains=dict(irq=['entry','leaf']),all_call_chains=dict(irq=[['entry','leaf'],['outer','leaf']]))
        variable=dict(symbol_id='s',name='shared',definition_file='main.c',accesses=[access,access],
            variable_evidence_slice=dict(function_ids=['extra'],address_taken=[access]),initialization_proof={'value':-0.0})
        finding=dict(finding_id='F',symbol_id='s',static_classification='SUSPECT',accesses=[access,access],function_ids=['audit'])
        global_finding=dict(finding_id='G',static_classification='UNKNOWN',function_ids=['leaf'])
        facts=dict(variables=[variable],functions=[dict(function_id=x,file='main.c') for x in ['unrelated','entry','leaf','outer','extra','audit','root','cycle','outbound']],
            calls=[dict(caller_function_id='root',callee_function_id='entry',caller='WRONG_ALIAS',callee='WRONG_ALIAS'),
                   dict(caller_function_id='cycle',callee_function_id='root'),dict(caller_function_id='root',callee_function_id='cycle'),
                   dict(caller_function_id='leaf',callee_function_id='outbound'),dict(caller_function_id='root',callee_function_id='entry'),
                   dict(caller='alias_only',callee='leaf')],
            unknowns=[dict(symbol_id='s',file='main.c'),dict(target_function_id='root'),dict(function_id='unrelated')],
            protection_events=[dict(function_id='root'),dict(function_id='root'),dict(function_id='unrelated')],
            context_bindings=[dict(function_id='outer')],mask_windows=[dict(symbol_id='s'),dict(symbol_id=None),dict(note='missing key is None')],
            pointer_targets=[dict(location='obj:s'),dict(location='obj:s/member'),dict(location='obj:s_other')],
            control_flow=[dict(function_id='leaf',nodes=[{'unnecessary_large_body':'中'*10000},{}],other=['retained',True,2**100]),dict(function_id='unrelated',nodes=[])],
            recursive_edges=[['leaf','root'],['unrelated','unrelated'],dict(caller_function_id='root',callee_function_id='leaf')],
            giant_unrelated=[dict(body='x'*100000)],contexts=[],physical_contexts=[],irq_priority_events=[],nvic_recovery=dict(probe=-0.0))
        with tempfile.TemporaryDirectory() as folder:
            for version in (1,3):
                path=Path(folder)/str(version)/'scan.db'
                with patch.object(scan_store,'SCHEMA_VERSION',version),patch.object(scan_store,'SCHEMA',scan_store.LEGACY_SCHEMA if version==1 else scan_store.SCHEMA):
                    publish_scan(path,facts,dict(findings=[finding,global_finding]),scan_id='s',project_id='p')
                provider=EvidenceProvider(path)
                forbidden=[provider.resolve('facts',['control_flow',0,'nodes']),provider.resolve('facts',['giant_unrelated'])]
                for row in (finding,global_finding):
                    with self.subTest(version=version,finding=row['finding_id']):self.assert_packet(path,Path(folder),facts,row,forbidden_nodes=forbidden)

    def test_real_recursive_clang_graph_arrays_are_retained_in_packet(self):
        case=fixtures.DeepReviewTests(methodName='runTest');case.setUp();self.addCleanup(case.doCleanups)
        cfg=case.project({'app.c':'''int shared; void b(void);
void a(void){shared++; if(shared<10)b();}
void b(void){if(shared<10)a();}
void ISR(void){shared++;}
int main(void){a();return shared;}
'''},contexts=[dict(id='main',kind='MAIN',functions=['main']),dict(id='irq',kind='ISR',functions=['ISR'])])
        facts,report=case.extract(cfg);self.assertTrue(facts['recursive_edges'])
        finding=next(row for row in report['findings'] if row.get('symbol_id'))
        path=case.root/'recursive-packet/scan.db';publish_scan(path,facts,report,scan_id='s',project_id='p')
        packet=self.assert_packet(path,case.root,facts,finding)
        self.assertTrue(packet['recursive_edges']);self.assertTrue(all(isinstance(edge,(list,tuple)) for edge in packet['recursive_edges']))

    def test_malformed_unrelated_record_is_rejected_instead_of_disappearing(self):
        finding=dict(finding_id='F',symbol_id='s')
        shared=[dict(caller_function_id='root',callee_function_id='leaf')]
        cases=[dict(variables=[dict(symbol_id='s')],calls=[],functions=[],unknowns=[['bad record']]),
               dict(variables=[dict(symbol_id='s')],calls=shared,functions=shared)]
        with tempfile.TemporaryDirectory() as folder:
            for index,facts in enumerate(cases):
                with self.subTest(index=index):
                    path=Path(folder)/str(index)/'scan.db';publish_scan(path,facts,dict(findings=[finding]),scan_id='s',project_id='p')
                    with self.assertRaisesRegex(ValueError,'非对象|缺少必要身份'):
                        with packet_inputs(path,'F') as (selected,current):
                            self.fail('Malformed relation must not be filtered into an apparently complete Packet')
