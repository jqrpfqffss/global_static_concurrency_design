"""Graph evidence stays complete when explicit call paths are exponential."""
import unittest

from ecra.analysis import context_graph
from tests import test_ecra as project_fixtures


def fixture(edges, contexts=None):
    names = {name for edge in edges for name in edge[:2]}
    functions = [dict(function_id=name, name=name, qualified_name=name,
                      file='graph.c', line=1, parameter_count=0) for name in sorted(names)]
    calls = [dict(caller_function_id=edge[0], callee_function_id=edge[1],
                  callee_name=edge[1], call_kind='DIRECT', file='graph.c', line=i+1,
                  **({'allowed_contexts':edge[2]} if len(edge)>2 else {}))
             for i,edge in enumerate(edges)]
    facts = dict(functions=functions,calls=calls,unknowns=[],registrations=[])
    cfg = dict(project={},analysis=dict(auto_contexts=False,inline_call_path_budget=32),call_edges=[],
               contexts=contexts or [dict(id='main',kind='MAIN',functions=['main'])])
    return facts, cfg


class CallGraphRepresentationTests(unittest.TestCase):
    def test_billion_paths_keep_all_edges_without_enumeration(self):
        edges = []
        previous = 'main'
        for i in range(30):
            left, right, merge = f'l{i}', f'r{i}', f'm{i}'
            edges.extend([(previous,left),(previous,right),(left,merge),(right,merge)])
            previous = merge
        facts, cfg = fixture(edges)
        _, paths, witnesses = context_graph(facts,cfg)
        graph = facts['context_call_graph']
        self.assertEqual(graph['representation'],'COMPLETE_GRAPH_WITH_WITNESSES')
        self.assertTrue(graph['complete'])
        self.assertFalse(graph['path_lists_complete'])
        self.assertEqual({tuple(e) for e in graph['edges']['main']},set(edges))
        self.assertEqual(len(paths),91)
        self.assertEqual(sum(len(routes) for per in witnesses.values() for routes in per.values()),91)
        self.assertIn('main',paths['m29'])

    def test_explicit_path_limit_still_fails_closed(self):
        facts,cfg=fixture([('main','a'),('main','b'),('a','c'),('b','c'),('c','d')])
        cfg['analysis'].update(inline_call_path_budget=2,max_call_paths=4)
        with self.assertRaisesRegex(ValueError,'CALL_PATH_LIMIT'):
            context_graph(facts,cfg)

    def test_context_restricted_edges_do_not_create_cross_context_reachability(self):
        facts,cfg=fixture([('main','dispatch'),('IRQ','dispatch'),
            ('dispatch','foreground_only',['main']),('dispatch','irq_only',['irq']),
            ('dispatch','unreachable',[])],
            [dict(id='main',kind='MAIN',functions=['main']),dict(id='irq',kind='ISR',functions=['IRQ'])])
        _,paths,_=context_graph(facts,cfg)
        self.assertEqual(set(paths['foreground_only']),{'main'})
        self.assertEqual(set(paths['irq_only']),{'irq'})
        self.assertNotIn('unreachable',paths)
        self.assertNotIn(['dispatch','irq_only'],facts['context_call_graph']['edges']['main'])

    def test_unrestricted_callsite_keeps_same_edge_open(self):
        facts,cfg=fixture([('main','use',[]),('main','use')])
        _,paths,_=context_graph(facts,cfg)
        self.assertIn('main',paths['use'])

    def test_recursive_edges_are_retained_in_compact_graph(self):
        facts,cfg=fixture([('main','a'),('a','b'),('b','a'),('b','use')])
        cfg['analysis']['inline_call_path_budget']=1
        context_graph(facts,cfg)
        self.assertIn(['b','a'],facts['context_call_graph']['edges']['main'])
        self.assertTrue(facts['recursive_edges'])


class CallGraphProtectionTests(unittest.TestCase):
    setUp=project_fixtures.ProjectTest.setUp
    project=project_fixtures.ProjectTest.project
    extract=project_fixtures.ProjectTest.extract

    def classify_diamond(self, second_masked):
        body = '__disable_irq(); Write(); __enable_irq();' if second_masked else 'Write();'
        cfg=self.project({'a.c':'''int g;
void __disable_irq(void); void __enable_irq(void);
void Write(void){g++;}
void A(void){__disable_irq();Write();__enable_irq();}
void B2(void){'''+body+'''}
void B(void){B2();}
void main(void){A();B();}
void USART1_IRQHandler(void){g++;}
'''},contexts=[dict(id='main',kind='MAIN',functions=['main']),
               dict(id='irq',kind='ISR',functions=['USART1_IRQHandler'])])
        cfg['analysis']['inline_call_path_budget']=1
        facts,report=self.extract(cfg)
        return facts,report,next(v for v in facts['variables'] if v['name']=='g')

    def test_shortest_masked_witness_cannot_hide_unprotected_longer_route(self):
        facts,report,g=self.classify_diamond(False)
        self.assertEqual(g['static_classification'],'SUSPECT')
        self.assertNotEqual(g['protection_status'],'EFFECTIVE')
        access=next(a for a in g['accesses'] if a['function_id'].endswith('Write'))
        self.assertFalse(access['call_path_lists_complete'])
        witness=access['all_call_chains']['main'][0]
        self.assertFalse(any(fid.endswith('B2') for fid in witness))
        sliced=facts['call_graph_slices'][access['call_graph_slice']]
        self.assertTrue(any(fid.endswith('B2') for fid in sliced['function_ids']))
        self.assertTrue(any(s['irq_state']=='ENABLED' for s in access['mask_states']))
        from ecra.html_report import write_html
        write_html(self.root/'.ecra',facts,report,[])
        html=(self.root/'.ecra/index.html').read_text(encoding='utf-8')
        self.assertIn('见证数量不是全部路径数量',html)
        self.assertIn('context_call_graph / call_graph_slices / calls',html)

    def test_effective_protection_requires_both_routes_masked(self):
        _,_,g=self.classify_diamond(True)
        self.assertEqual(g['static_classification'],'SAFE')
        self.assertEqual(g['safe_reason_code'],'SAFE_EFFECTIVE_PROTECTION')
        self.assertEqual(g['protection_status'],'EFFECTIVE')

    def test_mask_windows_do_not_cross_context_specific_pointees(self):
        from ecra.protection import MaskAnalysis
        accesses=[dict(access_id='a'+cid,symbol_id='g'+cid,function_id='helper',
            file='x.c',line=1,offset=10,access_kind='RMW',contexts=[cid],allowed_contexts=[cid])
            for cid in ('main','irq')]
        def graph(fid,callee=None):
            step=dict(id=1,op='call' if callee else 'step',file='x.c',offset=10,end_offset=20,
                      successors=[2])
            if callee:
                step.update(callee=callee,name=callee,arguments=[])
            return dict(function_id=fid,cfg_id=fid,complete=True,parameters=[],entry=0,exit=2,
                nodes=[dict(id=0,op='entry',successors=[1]),step,dict(id=2,op='exit',successors=[])])
        facts=dict(accesses=accesses,control_flow=[graph('root_main','helper'),graph('root_irq','helper'),graph('helper')],
            context_bindings=[dict(function_id='root_'+cid,context_id=cid,call_depth=0) for cid in ('main','irq')],
            context_call_graph=dict(edges={cid:[['root_'+cid,'helper']] for cid in ('main','irq')}))
        masks=MaskAnalysis(facts,dict(critical_sections=[]))
        masks.run()
        self.assertEqual(masks.touched[('root_main','main')],{'gmain'})
        self.assertEqual(masks.touched[('root_irq','irq')],{'girq'})
        self.assertEqual({(w['symbol_id'],w['context_id']) for w in facts['mask_windows']},
                         {('gmain','main'),('girq','irq')})
        for access in accesses:
            self.assertEqual({s['context_id'] for s in access['mask_states']},set(access['allowed_contexts']))


if __name__ == '__main__':
    unittest.main()
