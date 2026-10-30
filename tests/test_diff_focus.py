"""Difference views need positive dependencies, not undirected connectivity."""
import unittest
import json
import copy

from ecra.git_diff import compare, summarize, presentation_view
from ecra.html_report import final_conclusion
from tests import test_ecra


class DiffFocusTests(unittest.TestCase):
    setUp = test_ecra.ProjectTest.setUp
    project = test_ecra.ProjectTest.project
    extract = test_ecra.ProjectTest.extract

    def delta(self, before, after):
        contexts = [dict(id='main', kind='MAIN', functions=['main'])]
        cfg = self.project(before, contexts=contexts)
        bf, br = self.extract(cfg)
        cfg = self.project(after, contexts=contexts)
        hf, hr = self.extract(cfg)
        hr['git_diff'] = compare(summarize(bf, br), summarize(hf, hr),
                                 dict(files=[], head_sha='h', base_sha='b'))
        return hf, hr

    def selected(self, facts, report):
        return {v['qualified_name'] for v in presentation_view(facts, report)[0]['variables']}

    def test_changed_void_helper_does_not_spread_through_main_to_siblings(self):
        source = '''int changed,unrelated;
            void Update(void){changed=1;}void Other(void){unrelated++;}
            int main(void){Update();Other();return 0;}'''
        facts, report = self.delta({'a.c': source}, {'a.c': source.replace('changed=1', 'changed=2')})
        self.assertEqual(self.selected(facts, report), {'changed'})
        self.assertEqual(len(facts['variables']), 2)

    def test_unrelated_unknown_does_not_turn_all_variables_into_differences(self):
        source = '''int changed,unrelated;void Opaque(void);
            void Update(void){changed=1;}void Other(void){Opaque();unrelated++;}
            int main(void){Update();Other();return 0;}'''
        facts, report = self.delta({'a.c': source}, {'a.c': source.replace('changed=1', 'changed=2')})
        self.assertTrue(facts['unknowns'])
        self.assertEqual(self.selected(facts, report), {'changed'})
        self.assertIn('c:@unrelated', report['git_diff']['conservative_symbol_ids'])

    def test_ignored_scalar_return_does_not_change_the_callers_other_variables(self):
        source = '''int input,unrelated;int Get(void){return input;}
            int main(void){Get();unrelated++;return 0;}'''
        facts, report = self.delta({'a.c': source}, {'a.c': source.replace('return input;', 'return !input;')})
        self.assertEqual(self.selected(facts, report), {'input'})

    def test_consumed_return_keeps_control_dependency(self):
        source = '''int input,output;int Get(void){return input;}
            void Set(void){output++;}int main(void){if(Get())Set();return 0;}'''
        facts, report = self.delta({'a.c': source}, {'a.c': source.replace('return input;', 'return !input;')})
        self.assertEqual(self.selected(facts, report), {'input', 'output'})

    def test_changed_header_macro_only_selects_actual_consumers(self):
        before = {'h.h': '#define VALUE 1\n#define UNUSED 42\n',
                  'a.c': '#include "h.h"\nint changed,unrelated;void Set(void){changed=VALUE;}void Other(void){unrelated++;}int main(void){Set();Other();return 0;}'}
        after = dict(before, **{'h.h': '#define VALUE 2\n#define UNUSED 42\n'})
        facts, report = self.delta(before, after)
        self.assertEqual(self.selected(facts, report), {'changed'})

    def test_nested_macro_dependency_and_unused_header_definitions(self):
        before = {'h.h': '#define INNER 1\n#define OUTER INNER\n#define UNUSED 42\n',
                  'a.c': '#include "h.h"\nint changed,unrelated;void Set(void){changed=OUTER;}int main(void){Set();unrelated++;return 0;}'}
        facts, report = self.delta(before, dict(before, **{'h.h': before['h.h'].replace('INNER 1', 'INNER 2')}))
        self.assertEqual(self.selected(facts, report), {'changed'})
        facts, report = self.delta(before, dict(before, **{'h.h': before['h.h'].replace('UNUSED 42', 'UNUSED 43')}))
        self.assertEqual(self.selected(facts, report), set())

    def test_unresolved_potential_impact_cannot_produce_no_issues_verdict(self):
        report = dict(findings=[], analysis_status='MODELED_SCOPE_COMPLETE',
                      git_diff=dict(fallback_reasons=['unknown dependency'], conservative_symbol_ids=['g']))
        self.assertEqual(final_conclusion(report, [])['verdict'], 'INCONCLUSIVE')

    def test_command_line_macro_change_keeps_its_consumer_in_the_diff(self):
        source = '''int changed,unrelated;void Set(void){changed=VALUE;}
            void Other(void){unrelated++;}int main(void){Set();Other();return 0;}'''
        cfg = self.project({'a.c': source}, contexts=[dict(id='main', kind='MAIN', functions=['main'])])
        database = self.root/'compile_commands.json'
        rows = json.loads(database.read_text(encoding='utf-8'))
        rows[0]['arguments'].insert(1, '-DVALUE=1')
        database.write_text(json.dumps(rows), encoding='utf-8')
        bf, br = self.extract(cfg)
        rows[0]['arguments'][1] = '-DVALUE=2'
        database.write_text(json.dumps(rows), encoding='utf-8')
        hf, hr = self.extract(cfg)
        hr['git_diff'] = compare(summarize(bf, br), summarize(hf, hr), dict(files=[], head_sha='h', base_sha='b'))
        self.assertEqual(self.selected(hf, hr), {'changed'})

    def test_macro_only_initializer_change_is_a_direct_storage_change(self):
        for declaration in ('unsigned changed=VALUE;',
                            'const char *changed=VALUE;'):
            with self.subTest(declaration=declaration):
                first, second = ('1', '2') if 'unsigned' in declaration else ('"old"', '"new"')
                before = {'h.h': '#define VALUE '+first+'\n',
                          'a.c': '#include "h.h"\n'+declaration+'\nint unrelated;int main(void){return !!changed;}void Other(void){unrelated++;}'}
                facts, report = self.delta(before, dict(before, **{'h.h': '#define VALUE '+second+'\n'}))
                self.assertEqual(self.selected(facts, report), {'changed'})
                self.assertIn('DIRECT_CHANGED', report['git_diff']['impacts']['c:@changed']['reasons'])

    def test_macro_array_initializer_reaches_elements_without_unrelated_state(self):
        before = {'h.h': '#define VALUE 1\n',
                  'a.c': '#include "h.h"\nunsigned table[2]={VALUE,0};int unrelated;int main(void){return table[0];}void Other(void){unrelated++;}'}
        facts, report = self.delta(before, dict(before, **{'h.h': '#define VALUE 2\n'}))
        self.assertIn('table[0]', self.selected(facts, report))
        self.assertNotIn('unrelated', self.selected(facts, report))

    def test_preceding_counter_expansion_changes_an_unchanged_initializer(self):
        source = 'unsigned changed=__COUNTER__;int unrelated;int main(void){return changed;}void Other(void){unrelated++;}'
        facts, report = self.delta({'a.c': source}, {'a.c': 'unsigned earlier=__COUNTER__;\n'+source})
        self.assertTrue({'changed','earlier'} <= self.selected(facts, report))
        self.assertNotIn('unrelated', self.selected(facts, report))

    def test_counter_reordering_and_prior_macro_multiplicity_keep_consumers(self):
        before = {'h.h': '#define PREFIX __COUNTER__\n',
                  'a.c': '#include "h.h"\nunsigned earlier=PREFIX;unsigned changed=__COUNTER__;int unrelated;int main(void){return changed;}void Other(void){unrelated++;}'}
        after = dict(before, **{'h.h': '#define PREFIX (__COUNTER__+__COUNTER__)\n'})
        facts, report = self.delta(before, after)
        self.assertIn('changed', self.selected(facts, report))
        self.assertNotIn('unrelated', self.selected(facts, report))
        source = 'unsigned a=__COUNTER__;unsigned b=__COUNTER__;int main(void){return a+b;}'
        facts, report = self.delta({'a.c': source}, {'a.c': source.replace('unsigned a=__COUNTER__;unsigned b=__COUNTER__;', 'unsigned b=__COUNTER__;unsigned a=__COUNTER__;')})
        self.assertEqual(self.selected(facts, report), {'a','b'})

    def test_known_irq_priority_change_selects_only_that_contexts_variables(self):
        source = '''unsigned changed,unrelated;int main(void){changed++;unrelated++;return 0;}
            void USART2_IRQHandler(void){changed++;}void TIM2_IRQHandler(void){unrelated++;}'''
        cfg = self.project({'a.c': source}, contexts=[dict(id='main',kind='MAIN',functions=['main'])])
        facts, report = self.extract(cfg)
        usart = next(c['id'] for c in facts['contexts'] if 'USART2' in c['id'])
        timer = next(c['id'] for c in facts['contexts'] if 'TIM2' in c['id'])
        facts['nvic_priorities'] = [dict(context_ids=[usart], configured_preemption=1),
                                    dict(context_ids=[timer], configured_preemption=2)]
        before = summarize(facts, report)
        facts = copy.deepcopy(facts)
        facts['nvic_priorities'][0]['configured_preemption'] = 0
        report['git_diff'] = compare(before, summarize(facts, report), dict(files=[],head_sha='h',base_sha='b'))
        self.assertEqual(self.selected(facts, report), {'changed'})
        self.assertIn('EXECUTION_CONTEXT_CHANGED', report['git_diff']['impacts']['c:@changed']['reasons'])

    def test_function_like_macro_flag_is_part_of_its_consumers_signature(self):
        source = '''typedef int (*Leaf)(int,int);typedef Leaf (*Maker)(void*,void*);
            static int LeafBody(int a,int b){return a+b;}
            static Leaf Make(void*a,void*b){return LeafBody;}
            static void *x;static Maker y=Make;int a,b,changed;
            #define F(x,y) (x,y)
            int main(void){changed=!!F(a,b);return 0;}'''
        facts, report = self.delta({'a.c': source}, {'a.c': source.replace('#define F(x,y)', '#define F (x,y)')})
        self.assertIn('changed', self.selected(facts, report))
        self.assertIn('c:@F@main', report['git_diff']['modified_function_ids'])


if __name__ == '__main__':
    unittest.main()
