"""Root-cause artifacts cite existing conflict and blocker evidence."""

import unittest

from ecra.diagnostics import root_causes
from ecra.evidence import EvidenceIndex


class PrecisionDiagnosticsTests(unittest.TestCase):
    def test_blockers_have_stable_order_independent_of_input_order(self):
        variable = dict(symbol_id='v', qualified_name='v', definition_file='main.c',
                        definition_line=1, linkage='INTERNAL', declarations=[],
                        translation_units=['main.c'])
        issues = [dict(kind='UNRESOLVED_POINTEE', symbol_id='v', file='main.c',
                       line=line, function_id='f') for line in (3, 2, 4)]
        def build(order):
            facts = dict(variables=[variable], functions=[], calls=[], unknowns=order)
            index = EvidenceIndex(facts, {'build_closure': {}}, {'project': {}}, set())
            return [gap['blocker_id'] for gap in index.build(variable, [], {}, []).critical_gaps]
        self.assertEqual(build(issues), build(list(reversed(issues))))

    def test_shared_entry_gap_record_is_reused_across_variables(self):
        variables = [dict(symbol_id=sid, qualified_name=sid, definition_file='main.c',
                          definition_line=1, linkage='INTERNAL', declarations=[],
                          translation_units=['main.c']) for sid in ('first', 'second')]
        # The shared entry gap represents a proven opaque consumer, not mere
        # address formation inside a synchronous function table.
        issue = dict(kind='FUNCTION_ADDRESS', target_function_id='f',
                     actual_escape=True, file='main.c', line=2)
        facts = dict(variables=variables, functions=[], calls=[], unknowns=[issue])
        index = EvidenceIndex(facts, {'build_closure': {}}, {'project': {}}, set())
        contexts = {'main': dict(physical_id='FOREGROUND', physical_kind='MAIN')}
        def evidence(variable):
            access = dict(access_id=variable['symbol_id'], function_id='f',
                          access_kind='WRITE', file='main.c', line=3,
                          contexts=['main'])
            return index.build(variable, [access], contexts, []).critical_gaps[0]
        first, second = (evidence(variable) for variable in variables)
        self.assertIs(first, second)
        self.assertEqual(first['reason_code'], 'UNKNOWN_EXECUTION_CONTEXT')

    def test_opaque_function_address_sites_share_one_target_blocker(self):
        variable = dict(symbol_id='value', qualified_name='value',
                        definition_file='main.c', definition_line=1,
                        linkage='INTERNAL', declarations=[],
                        translation_units=['main.c'])
        sites = [dict(kind='FUNCTION_ADDRESS', target_function_id='f',
                      actual_escape=True, file='main.c', line=line,
                      function_id='publisher') for line in (8, 6, 7)]
        facts = dict(variables=[variable], functions=[], calls=[], unknowns=sites)
        index = EvidenceIndex(facts, {'build_closure': {}}, {'project': {}}, set())
        self.assertEqual(len(index.entries['f']), 1)
        access = dict(access_id='A', function_id='f', access_kind='WRITE',
                      file='main.c', line=10, contexts=['main'])
        contexts = {'main': dict(physical_id='FOREGROUND', physical_kind='MAIN')}
        gaps = index.build(variable, [access], contexts, []).critical_gaps
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0]['entry_site_count'], 3)
        self.assertEqual(gaps[0]['line'], 6)
        self.assertEqual(facts['unknowns'], sites)

    def test_unreachable_callback_registration_cannot_create_entry_gap(self):
        variable = dict(symbol_id='value', qualified_name='value',
                        definition_file='main.c', definition_line=1,
                        linkage='INTERNAL', declarations=[],
                        translation_units=['main.c'])
        issue = dict(kind='FUNCTION_ADDRESS', target_function_id='callback',
                     function_id='unused_dma_start', actual_escape=True,
                     file='hal.c', line=42)
        facts = dict(variables=[variable], functions=[], calls=[], unknowns=[issue])
        contexts = {'main': dict(physical_id='FOREGROUND', physical_kind='MAIN')}
        access = dict(access_id='A', function_id='callback', access_kind='WRITE',
                      file='main.c', line=5, contexts=['main'])
        unreachable = EvidenceIndex(facts, {'build_closure': {}}, {'project': {}},
                                    {'unused_dma_start'})
        self.assertFalse(unreachable.build(variable, [access], contexts, []).critical_gaps)
        reachable = EvidenceIndex(facts, {'build_closure': {}}, {'project': {}}, set())
        self.assertEqual(reachable.build(variable, [access], contexts, []).critical_gaps[0]['reason_code'],
                         'UNKNOWN_EXECUTION_CONTEXT')

    def test_irq_callback_entry_after_all_init_writes_is_not_a_gap(self):
        variable = dict(symbol_id='config', qualified_name='config',
                        definition_file='main.c', definition_line=1,
                        linkage='INTERNAL', declarations=[], translation_units=['main.c'])
        issue = dict(kind='FUNCTION_ADDRESS', target_function_id='callback',
                     function_id='irq_dispatch', actual_escape=True,
                     file='hal.c', line=30)
        facts = dict(variables=[variable], functions=[], calls=[], unknowns=[issue],
                     contexts=[dict(id='irq', physical_kind='IRQ', physical_id='IRQ:slot:54', slot=54)],
                     context_bindings=[dict(function_id='irq_dispatch', context_id='irq')])
        contexts = dict(main=dict(physical_id='FOREGROUND', physical_kind='MAIN'),
                        irq=facts['contexts'][0])
        accesses = [dict(access_id='write', function_id='init', access_kind='WRITE',
                         file='main.c', line=3, contexts=['main']),
                    dict(access_id='read', function_id='callback', access_kind='READ',
                         file='hal.c', line=35, contexts=['irq'])]
        proof = dict(write_access_ids=['write'], irq_barriers=[dict(enables=[dict(argument_values=[38])])])
        index = EvidenceIndex(facts, {'build_closure': {}}, {'project': {}}, set())
        self.assertFalse(index.build(variable, accesses, contexts, [], proof).critical_gaps)
        wrong_irq = dict(write_access_ids=['write'], irq_barriers=[dict(enables=[dict(argument_values=[39])])])
        self.assertEqual(index.build(variable, accesses, contexts, [], wrong_irq).critical_gaps[0]['reason_code'],
                         'UNKNOWN_EXECUTION_CONTEXT')
        facts['calls'].append(dict(caller_function_id='callback', callee_function_id='init'))
        reentrant = EvidenceIndex(facts, {'build_closure': {}}, {'project': {}}, set())
        self.assertEqual(reentrant.build(variable, accesses, contexts, [], proof).critical_gaps[0]['reason_code'],
                         'UNKNOWN_EXECUTION_CONTEXT')
        facts['calls'].clear()
        facts['unknowns'].append(dict(kind='FUNCTION_ADDRESS', target_function_id='callback',
                                      actual_escape=True, file='unknown.c', line=7))
        unowned = EvidenceIndex(facts, {'build_closure': {}}, {'project': {}}, set())
        self.assertEqual(unowned.build(variable, accesses, contexts, [], proof).critical_gaps[0]['reason_code'],
                         'UNKNOWN_EXECUTION_CONTEXT')
        facts['unknowns'].pop()
        facts['unknowns'].append(dict(kind='UNKNOWN_CALLBACK_ENTRY', target_function_id='irq_dispatch',
                                      file='unknown.c', line=8))
        extra_entry = EvidenceIndex(facts, {'build_closure': {}}, {'project': {}}, set())
        self.assertEqual(extra_entry.build(variable, accesses, contexts, [], proof).critical_gaps[0]['reason_code'],
                         'UNKNOWN_EXECUTION_CONTEXT')

    def test_conflict_witness_and_variable_local_gap(self):
        pair = dict(conflict_id='C-1', may_concurrent=True, has_write_conflict=True,
                    mhp='MAYBE', relation=dict(relation='UNKNOWN_PREEMPTION'),
                    participant_a=dict(access_id='A-write', context_id='irq',
                                       file='main.c', line=4),
                    participant_b=dict(access_id='A-read', context_id='main',
                                       file='main.c', line=8))
        rows = [dict(symbol_id='risky', qualified_name='risky',
                     static_classification='SUSPECT', conflict_pairs=[pair],
                     shared_no_review_rejections=['SHARED_RMW']),
                dict(symbol_id='opaque', qualified_name='opaque',
                     static_classification='UNKNOWN',
                     blocking_evidence=[dict(blocker_id='B-1',
                                             reason_code='UNKNOWN_ADDRESS_ESCAPE',
                                             file='driver.c')])]
        rates = dict(rr_build=dict(numerator=2, denominator=2, percent=100.0),
                     rr_all=dict(numerator=2, denominator=2, percent=100.0),
                     variant_inventory=0)
        data = root_causes(rows, rates)
        by_id = {row['symbol_id']: row for row in data['variables']}
        self.assertEqual(by_id['risky']['witness']['participant_a']['access_id'], 'A-write')
        self.assertEqual(by_id['opaque']['blocker_ids'], ['B-1'])
        self.assertEqual(data['reason_counts'],
                         {'SHARED_RMW': 1, 'UNKNOWN_ADDRESS_ESCAPE': 1})
        self.assertEqual(data['counterfactual_upper_bounds'],
                         {'UNKNOWN_ADDRESS_ESCAPE': 1})

    def test_coherence_pattern_cites_all_member_accesses(self):
        pair = dict(conflict_id='C-2', may_concurrent=True, has_write_conflict=True,
                    mhp='YES', relation=dict(relation='CAN_PREEMPT'),
                    participant_a=dict(access_id='A-write', access_kind='WRITE',
                                       context_id='irq'),
                    participant_b=dict(access_id='A-read', access_kind='READ',
                                       context_id='main'))
        variable = dict(symbol_id='member', static_classification='SUSPECT',
                        conflict_pairs=[pair],
                        shared_no_review_rejections=['SHARED_MULTI_FIELD_COHERENCE'],
                        multi_field_coherence=[dict(member_symbol_ids=['a', 'b'],
                            writer_access_ids=['w-a', 'w-b'],
                            reader_access_ids=['r-a', 'r-b'])])
        rates = dict(rr_build=dict(numerator=1, denominator=1, percent=100.0),
                     rr_all=dict(numerator=1, denominator=1, percent=100.0),
                     variant_inventory=0)
        result = root_causes([variable], rates)['variables'][0]
        self.assertEqual(result['destructive_codes'], ['D-07'])
        self.assertEqual(result['coherence_witnesses'][0]['reader_access_ids'], ['r-a', 'r-b'])


if __name__ == '__main__':
    unittest.main()
