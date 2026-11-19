"""Stage three acceptance: precise dependencies and complete three-way accounting."""
import copy
import json
import unittest

from ecra.git_diff import compare, summarize, presentation_view
from tests import test_diff_risk_contract as risk_fixture
from tests import test_scope_cmake as scope_fixture


class ImpactContractTests(unittest.TestCase):
    setUp = risk_fixture.RiskContractTests.setUp
    snapshot = risk_fixture.RiskContractTests.snapshot
    delta = risk_fixture.RiskContractTests.delta

    def project(self, sources, contexts=None, review=None):
        # The phase-two fixture always configures an IRQ. Absence of that
        # entry is an unrelated artificial gap in these dependence fixtures.
        active = [c for c in contexts or [] if any(
            name + '(' in text for name in c['functions'] for text in sources.values())]
        return risk_fixture.RiskContractTests.project(self, sources, contexts=active, review=review)

    def code_delta(self, source, replacement):
        base, _, _ = self.snapshot({'a.c': source})
        head, facts, report = self.snapshot({'a.c': replacement})
        result = self.delta(base, head)
        return result, facts, report

    def category(self, result, name):
        return result['impacts']['c:@' + name]['impact_class']

    def test_T03_unbuilt_and_inactive_changes_do_not_create_runtime_impacts(self):
        source = ('int active;void main(void){active++;}\n'
                  '#if 0\nint hidden;void inactive(void){active=1;hidden++;}\n#endif\n')
        base, _, _ = self.snapshot({'a.c': source})
        head, facts, report = self.snapshot({
            'a.c': source.replace('active=1;', 'active=2;'),
            'unbuilt.c': 'extern int active;int outside;void Other(void){active++;outside++;}',
        }, compiled=['a.c'])
        result = self.delta(base, head, files=[dict(status='M', new_path='a.c'),
                                               dict(status='A', new_path='unbuilt.c')])
        self.assertIn('unbuilt.c', report['coverage']['excluded_from_build'])
        self.assertEqual({row['name'] for row in facts['variables']}, {'active'})
        self.assertEqual({row['name'] for row in facts['functions']}, {'main'})
        self.assertEqual(result['selected_symbol_ids'], [])
        self.assertEqual(result['impact_counts'], dict(DEFINITE=0, UNCERTAIN=0, EXCLUDED=1))
        self.assertFalse(result['change_counts']['counts_as_new_risk'])
        self.assertFalse(result['change_counts']['counts_as_risk_resolution'])

    def test_T10_independent_statements_in_one_function_have_exclusion_proof(self):
        source = 'int a,b;void main(void){a=1;b++;}'
        result, facts, report = self.code_delta(source, source.replace('a=1', 'a=2'))
        self.assertEqual(self.category(result, 'a'), 'DEFINITE')
        self.assertEqual(self.category(result, 'b'), 'EXCLUDED')
        self.assertEqual(result['impacts']['c:@b']['exclusion_proof']['proof'], 'COMPLETE_DEPENDENCY_SEPARATION')
        self.assertEqual(len(facts['variables']), 2)
        report['git_diff'] = result
        self.assertEqual([v['name'] for v in presentation_view(facts, report)[0]['variables']], ['a'])

    def test_T06_consumed_return_selects_only_its_real_data_and_control_sinks(self):
        source = ('int input,out,guarded,other,discarded;int Get(void){return input;}'
                  'void main(void){int x=Get();out=x+1;if(x)guarded++;other++;}'
                  'void ISR(void){Get();discarded++;}')
        result, _, _ = self.code_delta(source, source.replace('return input;', 'return !input;'))
        for name in ('input', 'out', 'guarded'):
            self.assertEqual(self.category(result, name), 'DEFINITE', name)
        for name in ('other', 'discarded'):
            self.assertEqual(self.category(result, name), 'EXCLUDED', name)
        self.assertTrue(any(step['reason'] == 'RETURN_DEPENDENCY'
            for row in result['impacts']['c:@out']['impact_evidence']
            for step in row.get('path', [])))

    def test_T07_transitive_global_local_dataflow_preserves_independent_siblings(self):
        source = ('int raw,filtered,out,other;void main(void){raw=1;}'
                  'void Filter(void){int tmp=raw+1;filtered=tmp;other++;}'
                  'void ISR(void){out=filtered;}')
        result, _, _ = self.code_delta(source, source.replace('raw=1', 'raw=2'))
        for name in ('raw', 'filtered', 'out'):
            self.assertEqual(self.category(result, name), 'DEFINITE', name)
        self.assertEqual(self.category(result, 'other'), 'EXCLUDED')
        paths = [row['path'] for row in result['impacts']['c:@out']['impact_evidence'] if 'path' in row]
        self.assertTrue(any([step['node'] for step in path] ==
                            [['variable', 'c:@raw'], ['variable', 'c:@filtered'], ['variable', 'c:@out']]
                            for path in paths))

    def test_scalar_parameter_change_does_not_select_independent_callee_effect(self):
        source = 'int out,other;void Set(int x){out=x;other++;}void main(void){Set(1);}'
        result, _, _ = self.code_delta(source, source.replace('Set(1)', 'Set(2)'))
        self.assertEqual(self.category(result, 'out'), 'DEFINITE')
        self.assertEqual(self.category(result, 'other'), 'EXCLUDED')

    def test_overwritten_local_does_not_forward_old_input(self):
        source = 'int raw,out;void main(void){raw=1;}void ISR(void){int x=raw;x=0;out=x;}'
        result, _, _ = self.code_delta(source, source.replace('raw=1', 'raw=2'))
        self.assertEqual(self.category(result, 'raw'), 'DEFINITE')
        self.assertEqual(self.category(result, 'out'), 'EXCLUDED')

    def test_reused_local_expression_is_stored_as_a_dag(self):
        source = 'int raw,out;void main(void){int x=raw;' + 'x=x+x;' * 50 + 'out=x;}'
        _, facts, _ = self.snapshot({'a.c': source})
        proof = next(f['diff_dependencies'] for f in facts['functions'] if f['name'] == 'main')
        self.assertTrue(proof['complete'])
        self.assertLess(len(json.dumps(proof)), 100000)

    def test_T05_new_irq_call_keeps_unchanged_main_access_and_full_witness(self):
        source = 'int g;void Store(void){g++;}void main(void){Store();}void ISR(void){}'
        result, facts, _ = self.code_delta(source, source.replace('ISR(void){}', 'ISR(void){Store();}'))
        self.assertEqual(self.category(result, 'g'), 'DEFINITE')
        self.assertTrue(result['impacts']['c:@g']['added_paths'])
        accesses = next(v for v in facts['variables'] if v['name'] == 'g')['accesses']
        self.assertTrue(any('main' in a['contexts'] and 'irq' in a['contexts'] for a in accesses))

    def test_T09_shared_caller_does_not_spread_to_unchanged_callee(self):
        source = 'int a,b;void Update(void){a=1;}void Other(void){b++;}void main(void){Update();Other();}'
        result, _, _ = self.code_delta(source, source.replace('a=1', 'a=2'))
        self.assertEqual(self.category(result, 'a'), 'DEFINITE')
        self.assertEqual(self.category(result, 'b'), 'EXCLUDED')

    def test_T11_disjoint_fields_and_constant_elements_in_same_function(self):
        source = 'struct S{int x,y;}s;int arr[2];void main(void){s.x=1;s.y++;arr[0]=1;arr[1]++;}'
        result, facts, _ = self.code_delta(source, source.replace('s.x=1', 's.x=2').replace('arr[0]=1', 'arr[0]=2'))
        by_name = {v['qualified_name']: result['impacts'][v['symbol_id']] for v in facts['variables']}
        for name in ('s.x', 'arr[0]'):
            self.assertEqual(by_name[name]['impact_class'], 'DEFINITE', name)
        for name in ('s.y', 'arr[1]'):
            self.assertEqual(by_name[name]['impact_class'], 'EXCLUDED', name)
        self.assertEqual(result['container_count'], 2)
        self.assertEqual(result['identified_object_count'], 4)

    def test_T12_fixed_union_overlap_is_definite_dynamic_array_overlap_is_not(self):
        source = 'union U{int x,y;}u;int arr[2],i;void main(void){u.x=1;arr[i]=1;}void ISR(void){u.y++;arr[0]++;}'
        result, facts, _ = self.code_delta(source, source.replace('u.x=1', 'u.x=2').replace('arr[i]=1', 'arr[i]=2'))
        by_name = {v['qualified_name']: result['impacts'][v['symbol_id']] for v in facts['variables']}
        self.assertEqual(by_name['u.y']['impact_class'], 'DEFINITE')
        self.assertEqual(by_name['arr[0]']['impact_class'], 'UNCERTAIN')
        self.assertEqual(by_name['arr[*]']['impact_class'], 'UNCERTAIN')

    def test_T12_multiple_pointer_targets_are_not_all_promoted_to_definite(self):
        source = 'int a,b,flag;void main(void){int*p=flag?&a:&b;*p=1;}void ISR(void){a++;b++;}'
        result, _, _ = self.code_delta(source, source.replace('*p=1', '*p=2'))
        for name in ('a', 'b'):
            self.assertEqual(self.category(result, name), 'UNCERTAIN', name)

    def test_T08_macro_change_is_localized_to_actual_statement(self):
        sources = {'h.h': '#define VALUE 1\n#define UNUSED 9\n',
                   'a.c': '#include "h.h"\nint a,b;void main(void){a=VALUE;b++;}'}
        base, _, _ = self.snapshot(sources)
        head, _, _ = self.snapshot(dict(sources, **{'h.h': sources['h.h'].replace('VALUE 1', 'VALUE 2')}))
        result = self.delta(base, head)
        self.assertEqual(self.category(result, 'a'), 'DEFINITE')
        self.assertNotEqual(self.category(result, 'b'), 'DEFINITE')
        unused, _, _ = self.snapshot(dict(sources, **{'h.h': sources['h.h'].replace('UNUSED 9', 'UNUSED 10')}))
        result = self.delta(base, unused)
        self.assertEqual(result['selected_symbol_ids'], [])

    def test_header_local_type_change_is_detected_without_function_token_edit(self):
        sources = {'h.h': 'typedef unsigned char Byte;\n',
                   'a.c': '#include "h.h"\nint out,other;void main(void){Byte x=256;out=x;other++;}'}
        base, _, _ = self.snapshot(sources)
        head, _, _ = self.snapshot(dict(sources, **{'h.h': 'typedef unsigned short Byte;\n'}))
        result = self.delta(base, head)
        self.assertEqual(self.category(result, 'out'), 'DEFINITE')
        self.assertEqual(self.category(result, 'other'), 'EXCLUDED')

    def test_macro_operands_sharing_source_offset_remain_distinct(self):
        source = '#define VALUE 1\n#define UPDATE (a=VALUE,b++)\nint a,b;void main(void){UPDATE;}'
        result, _, _ = self.code_delta(source, source.replace('VALUE 1', 'VALUE 2'))
        self.assertEqual(self.category(result, 'a'), 'DEFINITE')
        self.assertEqual(self.category(result, 'b'), 'EXCLUDED')

    def test_ambiguous_pointer_macro_sites_cannot_prove_each_target_affected(self):
        source = ('#define VALUE 1\n#define UPDATE (*p=VALUE,*q=7)\n'
                  'int a,b;void main(void){int*p=&a;int*q=&b;UPDATE;}')
        result, _, _ = self.code_delta(source, source.replace('VALUE 1', 'VALUE 2'))
        self.assertEqual(self.category(result, 'b'), 'UNCERTAIN')
        self.assertTrue(any('AMBIGUOUS_SOURCE_SITE' in row.get('uncertainty_reasons', [])
                            for row in result['impacts']['c:@b']['impact_evidence']))

    def test_effect_order_changes_cannot_be_excluded_by_equal_multisets(self):
        source = 'int a,b;void main(void){a=1;b=a;}'
        result, _, _ = self.code_delta(source, source.replace('a=1;b=a;', 'b=a;a=1;'))
        self.assertEqual(self.category(result, 'a'), 'UNCERTAIN')
        self.assertEqual(self.category(result, 'b'), 'UNCERTAIN')

    def test_protection_change_is_not_a_function_wide_access_change(self):
        source = ('void __disable_irq(void);void __enable_irq(void);int a,b;'
                  'void main(void){__disable_irq();a++;__enable_irq();b++;}'
                  'void ISR(void){a++;b++;}')
        result, _, _ = self.code_delta(source, source.replace('__disable_irq();a++;__enable_irq();', 'a++;'))
        self.assertEqual(self.category(result, 'a'), 'DEFINITE')
        self.assertNotEqual(self.category(result, 'b'), 'DEFINITE')

    def test_original_review_packet_keeps_dependency_internals_in_authority(self):
        from ecra.review import build_variable_review_packet
        _, facts, report = self.snapshot({'a.c': 'int shared;void main(void){shared++;}void ISR(void){shared++;}'})
        finding = next(f for f in report['findings'] if f.get('symbol_id') == 'c:@shared')
        packet = build_variable_review_packet(self.root, facts, finding,
            facts_path='facts.json', shared_path='shared.json', report_path='report.json')
        self.assertTrue(any('diff_dependencies' in f for f in facts['functions']))
        self.assertTrue(all('diff_dependencies' not in f for f in packet['functions']))

    def test_T37_missing_or_unbound_fine_grain_proof_defaults_to_uncertain(self):
        base, _, _ = self.snapshot({'a.c': 'int a,b;void main(void){a=1;b++;}'})
        head = copy.deepcopy(base)
        head['functions']['c:@F@main']['digest'] = 'unexplained edit'
        result = self.delta(base, head)
        for name in ('a', 'b'):
            self.assertEqual(self.category(result, name), 'UNCERTAIN')
            self.assertFalse(result['impacts']['c:@'+name]['exclusion_proof'])

    def test_unsupported_flow_remains_uncertain_instead_of_function_wide_definite(self):
        source = 'int a,b;void main(void){for(int i=0;i<3;i++)a++;b++;}'
        result, _, _ = self.code_delta(source, source.replace('i<3', 'i<4'))
        self.assertEqual(self.category(result, 'a'), 'UNCERTAIN')
        self.assertEqual(self.category(result, 'b'), 'UNCERTAIN')

    def test_T36_partition_includes_all_identified_objects_and_baseline_only(self):
        base, _, _ = self.snapshot({'a.c': 'static int a;int b;void main(void){a++;b++;}',
                                    'gone.c': 'int gone;void Old(void){gone++;}'})
        head, _, _ = self.snapshot({'a.c': 'static int a;int b;int added;void main(void){a+=2;b++;added++;}'})
        result = self.delta(base, head, [dict(status='D', old_path='gone.c', new_path='gone.c')])
        rows = list(result['impacts'].values()) + [row['impact'] for row in result['baseline_only_variables']]
        self.assertEqual(len(rows), len(base['variables'].keys() | head['variables'].keys()))
        self.assertEqual(sum(result['impact_counts'].values()), result['identified_object_count'])
        sets = [set(result[key]) for key in ('definite_symbol_ids', 'conservative_symbol_ids', 'excluded_symbol_ids')]
        self.assertFalse(sets[0] & sets[1] or sets[0] & sets[2] or sets[1] & sets[2])
        self.assertEqual(set.union(*sets), {v['symbol_id'] for v in head['variables'].values()})
        self.assertTrue(all(row['reasons'] for row in rows))

    def test_T20_T21_T38_failed_region_has_local_limits_and_no_invented_objects(self):
        source = 'static int isolated;int exposed,changed;void main(void){isolated++;exposed++;changed=1;}void ISR(void){exposed++;}'
        base, _, _ = self.snapshot({'a.c': source})
        head, _, _ = self.snapshot({'a.c': source.replace('changed=1', 'changed=2')})
        for summary in (base, head):
            summary['comparison_scope']['units'].append(dict(source_file='failed.c', tu_id='failed', parse_status='FAILED'))
            summary['unknowns'].append('failed region')
            summary['impact_unknowns'].append(dict(kind='PARSE_FAILED', file='failed.c'))
        result = self.delta(base, head)
        isolated = next(v['symbol_id'] for v in head['variables'].values() if v['name'] == 'isolated')
        self.assertEqual(result['impacts'][isolated]['impact_class'], 'EXCLUDED')
        self.assertEqual(self.category(result, 'exposed'), 'UNCERTAIN')
        self.assertEqual(result['impacts']['c:@exposed']['head_classification'], 'SUSPECT')
        self.assertTrue(result['impacts'][isolated]['impact_coverage_evidence']['head']['excluded_gaps'])
        self.assertTrue(result['regional_gaps'])
        self.assertFalse(result['real_object_inventory_complete'])
        self.assertTrue(result['identified_objects_accounted'])
        self.assertEqual(result['identified_object_count'], 3)

    def test_failed_region_cannot_hide_changes_when_observed_summaries_are_equal(self):
        source = 'int exposed;static int independent,derived;void main(void){independent=1;derived=exposed;}'
        base, _, _ = self.snapshot({'a.c': source})
        head = copy.deepcopy(base)
        for summary in (base, head):
            summary['comparison_scope']['units'].append(dict(source_file='failed.c', tu_id='failed', parse_status='FAILED'))
            summary['unknowns'].append('same parse failure')
            summary['impact_unknowns'].append(dict(kind='PARSE_FAILED', file='failed.c'))
        result = self.delta(base, head, [dict(status='M', old_path='failed.c', new_path='failed.c')])
        names = {v['name']: v['symbol_id'] for v in head['variables'].values()}
        self.assertEqual(result['impacts'][names['exposed']]['impact_class'], 'UNCERTAIN')
        self.assertEqual(result['impacts'][names['derived']]['impact_class'], 'UNCERTAIN')
        self.assertEqual(result['impacts'][names['independent']]['impact_class'], 'EXCLUDED')


class ScopeImpactTests(unittest.TestCase):
    setUp = scope_fixture.ScopeCMakeTest.setUp
    fixture = scope_fixture.ScopeCMakeTest.fixture
    save = scope_fixture.ScopeCMakeTest.save
    extract = scope_fixture.ScopeCMakeTest.extract

    def test_T04_excluded_driver_keeps_target_pointer_and_callback_evidence(self):
        sources = {
            'App/main.c': 'int count;void Dispatch(void);void Write(int*);void Callback(void){count++;}'
                          'void USART2_IRQHandler(void){Dispatch();}int main(void){Write(&count);return 0;}',
            'Vendor/hal.c': 'int driver_private;void Callback(void);void Dispatch(void){driver_private++;Callback();}'
                            'void Write(int*p){*p+=1;}',
        }
        cfg = self.fixture(sources, include_dirs=['App'], exclude_dirs=['Vendor'])
        facts, report = self.extract(cfg)
        base = summarize(facts, report)
        cfg = self.fixture(dict(sources, **{'Vendor/hal.c': sources['Vendor/hal.c'].replace('*p+=1', '*p+=2')}),
                           include_dirs=['App'], exclude_dirs=['Vendor'])
        facts, report = self.extract(cfg)
        result = compare(base, summarize(facts, report), dict(files=[], head_sha='h', base_sha='b'))
        self.assertEqual(list(result['impacts']), ['c:@count'])
        self.assertEqual(result['impacts']['c:@count']['impact_class'], 'DEFINITE')
        self.assertTrue(any(a['file'] == 'Vendor/hal.c' for a in facts['variables'][0]['accesses']))
        self.assertTrue(any(len(path) == 3 for a in facts['variables'][0]['accesses'] for path in a['call_chains'].values()))

    def test_excluded_storage_initializer_still_reaches_target_data_consumer(self):
        sources = {'App/main.c': 'int out;void Transfer(void);int main(void){Transfer();return 0;}',
                   'Vendor/hal.c': 'extern int out;static int calibration=1;void Transfer(void){out=calibration;}'}
        cfg = self.fixture(sources, include_dirs=['App'], exclude_dirs=['Vendor'])
        facts, report = self.extract(cfg)
        base = summarize(facts, report)
        cfg = self.fixture(dict(sources, **{'Vendor/hal.c': sources['Vendor/hal.c'].replace('calibration=1', 'calibration=2')}),
                           include_dirs=['App'], exclude_dirs=['Vendor'])
        facts, report = self.extract(cfg)
        result = compare(base, summarize(facts, report), dict(files=[], head_sha='h', base_sha='b'))
        self.assertEqual(list(result['impacts']), ['c:@out'])
        self.assertEqual(result['impacts']['c:@out']['impact_class'], 'DEFINITE')
        self.assertEqual(result['identified_object_count'], 1)
        # The native reader must retain this dependency-only relation too.
        from ecra.compilation import prepare
        from ecra.native_diff_summary import summarize_native
        from ecra.scan_store import publish_scan
        units, _ = prepare(self.root, cfg)
        facts['translation_units'] = [dict(unit, parse_status='PARSED') for unit in units]
        database = self.root/'native-dependency.db'
        publish_scan(database, facts, report, scan_id='scope', project_id='scope')
        self.assertEqual(summarize_native(database), summarize(facts, report))


if __name__ == '__main__':
    unittest.main()
