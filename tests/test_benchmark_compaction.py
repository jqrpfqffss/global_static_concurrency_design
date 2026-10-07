import unittest

from scripts.preopencode_benchmark_scan import compact_conflict_scenarios, stratified_audit_sample
from ecra.analysis import conflict_pairs, multi_field_coherence
from ecra.evidence import VariableEvidenceSlice, classify


class BenchmarkConflictCompactionTests(unittest.TestCase):
    def test_large_context_product_retains_all_writers_and_init_does_not_clear_runtime_writer(self):
        contexts = {'main': dict(physical_id='FOREGROUND', physical_kind='FOREGROUND'),
                    'irq': dict(physical_id='IRQ:TIMER', physical_kind='IRQ')}
        relation = [dict(contexts=['main', 'irq'], relation='MAY_PREEMPT')]
        accesses = [dict(access_id=f'w{i}', access_kind='WRITE', function_id='main',
                         file='main.c', line=i + 1, contexts=['main'],
                         all_call_chains={'main': [['main']]}) for i in range(66)]
        accesses += [dict(access_id=f'r{i}', access_kind='READ', function_id='ISR',
                          file='irq.c', line=i + 1, contexts=['irq'],
                          all_call_chains={'irq': [['ISR']]}) for i in range(66)]
        pairs = conflict_pairs(accesses, relation, contexts)
        self.assertEqual(1, len(pairs))
        self.assertEqual('CONTEXT_ACCESS_PRODUCT', pairs[0]['representation'])
        self.assertEqual(66 * 66, pairs[0]['pair_count'])
        self.assertEqual(66, len(pairs[0]['participant_a_write_access_ids'])
                         + len(pairs[0]['participant_b_write_access_ids']))
        compact = compact_conflict_scenarios(pairs)
        self.assertEqual(66 * 66, compact[0]['pair_count'])
        self.assertEqual(132, len(compact[0]['participant_a_access_ids'])
                         + len(compact[0]['participant_b_access_ids']))
        evidence = VariableEvidenceSlice(symbol_id='v', canonical_path='v',
                                         definition={}, linkage='INTERNAL')
        verdict = classify(evidence, accesses, contexts, pairs, 'NOT_FOUND', '',
                           init_proof=dict(write_access_ids=['w0']), variable={}, cfg={})
        self.assertEqual('SUSPECT', verdict['static_classification'])

    def test_pair_product_is_grouped_without_losing_access_ids(self):
        pairs = []
        for left in ('read-a', 'read-b'):
            for right in ('write-a', 'write-b'):
                pairs.append(dict(
                    participant_a=dict(access_id=left, access_kind='READ', context_id='main',
                                       function_id='reader', file='main.c', line=3),
                    participant_b=dict(access_id=right, access_kind='WRITE', context_id='irq',
                                       function_id='writer', file='irq.c', line=9),
                    relation=dict(relation='MAY_PREEMPT', contexts=['main', 'irq']),
                    mhp='YES', may_concurrent=True, has_write_conflict=True,
                    path_combination_count=6))

        rows = compact_conflict_scenarios(pairs)

        self.assertEqual(1, len(rows))
        self.assertEqual(4, rows[0]['pair_count'])
        self.assertEqual(24, rows[0]['path_combination_count'])
        self.assertEqual(['read-a', 'read-b'], rows[0]['participant_a_access_ids'])
        self.assertEqual(['write-a', 'write-b'], rows[0]['participant_b_access_ids'])
        self.assertEqual('read-a', rows[0]['witness']['participant_a']['access_id'])

    def test_safe_audit_sample_covers_storage_kinds_and_proofs(self):
        variables = [dict(symbol_id=f'c{i:02}', kind='STRUCT_MEMBER',
                          safe_reason_code='SAFE_NO_RUNTIME_ACCESS',
                          static_classification='SAFE_PROVEN') for i in range(40)]
        variables += [dict(symbol_id='z1', kind='FILE_STATIC',
                           safe_reason_code='SAFE_SINGLE_FOREGROUND',
                           static_classification='SAFE_PROVEN'),
                      dict(symbol_id='z2', kind='GLOBAL',
                           safe_reason_code='SAFE_READ_ONLY',
                           static_classification='SAFE_PROVEN')]
        sample = stratified_audit_sample(variables, 'SAFE_PROVEN', 30)
        self.assertEqual(30, len(sample))
        self.assertEqual({'STRUCT_MEMBER', 'FILE_STATIC', 'GLOBAL'},
                         {row['kind'] for row in sample})
        self.assertEqual({'SAFE_NO_RUNTIME_ACCESS', 'SAFE_SINGLE_FOREGROUND', 'SAFE_READ_ONLY'},
                         {row['safe_reason_code'] for row in sample})

    def test_audit_sample_meets_each_available_proof_floor(self):
        variables = [dict(symbol_id=f'a{i:02}', kind='GLOBAL',
                          safe_reason_code='SAFE_READ_ONLY',
                          static_classification='SAFE_PROVEN') for i in range(80)]
        variables += [dict(symbol_id=f'b{i:02}', kind='STRUCT_MEMBER',
                           safe_reason_code='SAFE_SINGLE_IRQ',
                           static_classification='SAFE_PROVEN') for i in range(18)]
        sample = stratified_audit_sample(variables, 'SAFE_PROVEN', 60)
        counts = {reason: sum(row['safe_reason_code'] == reason for row in sample)
                  for reason in {'SAFE_READ_ONLY', 'SAFE_SINGLE_IRQ'}}
        self.assertEqual(60, len(sample))
        self.assertGreaterEqual(counts['SAFE_READ_ONLY'], 10)
        self.assertGreaterEqual(counts['SAFE_SINGLE_IRQ'], 10)
        self.assertEqual([row['symbol_id'] for row in sample],
                         [row['symbol_id'] for row in stratified_audit_sample(variables, 'SAFE_PROVEN', 60)])

    def test_coherence_function_product_has_one_source_backed_group(self):
        variables = [dict(symbol_id=f'field-{i}', root_symbol_id='root') for i in range(2)]
        accesses = {row['symbol_id']: [] for row in variables}
        for row in variables:
            for fid in ('writer-a', 'writer-b', 'writer-c'):
                accesses[row['symbol_id']].append(dict(access_id=f'{fid}-{row["symbol_id"]}',
                    access_kind='WRITE', function_id=fid, contexts=['irq']))
            for fid in ('reader-a', 'reader-b'):
                accesses[row['symbol_id']].append(dict(access_id=f'{fid}-{row["symbol_id"]}',
                    access_kind='READ', function_id=fid, contexts=['main']))
        groups = multi_field_coherence(variables, accesses, {
            'irq': dict(physical_id='IRQ:TIM4'), 'main': dict(physical_id='FOREGROUND')})
        for row in variables:
            self.assertEqual(1, len(groups[row['symbol_id']]))
            proof = groups[row['symbol_id']][0]
            self.assertEqual(6, proof['function_pair_count'])
            self.assertEqual(3, len(proof['writer_function_ids']))
            self.assertEqual(2, len(proof['reader_function_ids']))
            self.assertEqual(6, len(proof['writer_access_ids']))
            self.assertEqual(4, len(proof['reader_access_ids']))


if __name__ == '__main__':
    unittest.main()
