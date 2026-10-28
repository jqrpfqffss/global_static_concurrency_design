"""Compare grouped transactions with exhaustive source-backed function pairs."""
import random
import json
import unittest

from ecra.analysis import multi_field_coherence
from tests.coherence_reference import reference_coherence


class CoherenceGroupingTests(unittest.TestCase):
    def test_randomized_complete_evidence_matches_exhaustive_reference(self):
        for seed in range(1000):
            rng = random.Random(seed)
            variables = [dict(symbol_id=f'r{root}.m{m}', root_symbol_id=f'r{root}')
                         for root in range(2) for m in range(4)]
            contexts = {'a': dict(physical_id='MAIN'), 'b': dict(physical_id='MAIN'),
                        'x': dict(physical_id='IRQ1'), 'y': dict(physical_id='IRQ2'), 'z': {}}
            accesses = {v['symbol_id']: [] for v in variables}
            for i in range(120):
                sid = rng.choice(variables)['symbol_id']
                row = dict(access_id='A'+str(i//2), function_id='f'+str(rng.randrange(12)),
                           access_kind=rng.choice(['READ', 'WRITE', 'RMW', 'ADDRESS_TAKEN']),
                           contexts=rng.sample(list(contexts), rng.randrange(4)))
                if rng.random() < .1:
                    row['reachability'] = 'PROVEN_UNREACHABLE'
                accesses[sid].append(row)
            calls = [dict(caller_function_id='f'+str(rng.randrange(12)),
                          callee_function_id='f'+str(rng.randrange(12))) for _ in range(15)]
            bindings = [dict(function_id='f'+str(rng.randrange(12)),
                             context_id=rng.choice(list(contexts))) for _ in range(25)]
            args = variables, accesses, contexts, calls, bindings
            with self.subTest(seed=seed):
                self.assertEqual(multi_field_coherence(*args), reference_coherence(*args))

    def test_overlapping_transaction_signatures_preserve_counts_and_witness(self):
        variables = [dict(symbol_id=sid, root_symbol_id='root') for sid in ('a', 'b', 'c')]
        contexts = dict(w=dict(physical_id='MAIN'), r=dict(physical_id='IRQ'))
        accesses = {sid: [] for sid in ('a', 'b', 'c')}
        for function, fields, role, context in [('w1', 'abc', 'WRITE', 'w'), ('w2', 'ab', 'WRITE', 'w'),
                                               ('r1', 'ab', 'READ', 'r'), ('r2', 'abc', 'READ', 'r')]:
            for sid in fields:
                accesses[sid].append(dict(access_id=sid+function, function_id=function,
                                          access_kind=role, contexts=[context]))
        result = multi_field_coherence(variables, accesses, contexts)
        rows = {tuple(row['member_symbol_ids']): row for row in result['a']}
        self.assertEqual(rows['a', 'b']['function_pair_count'], 3)
        self.assertEqual(rows['a', 'b']['writer_function_ids'], ['w1', 'w2'])
        self.assertEqual(rows['a', 'b']['reader_function_ids'], ['r1', 'r2'])
        self.assertEqual(rows['a', 'b']['witness'], dict(writer_function_id='w1', reader_function_id='r1'))
        self.assertEqual(rows['a', 'b', 'c']['function_pair_count'], 1)
        self.assertEqual(result, reference_coherence(variables, accesses, contexts))

    def test_large_cartesian_count_keeps_every_source_id(self):
        count = 3000
        variables = [dict(symbol_id=sid, root_symbol_id='root') for sid in ('a', 'b')]
        contexts = dict(w=dict(physical_id='MAIN'), r=dict(physical_id='IRQ'))
        accesses = {sid: [] for sid in ('a', 'b')}
        for sid in accesses:
            for i in range(count):
                for prefix, role, context in [('w', 'WRITE', 'w'), ('r', 'READ', 'r')]:
                    function = prefix+f'{i:05}'
                    accesses[sid].append(dict(access_id=sid+function, function_id=function,
                                              access_kind=role, contexts=[context]))
        row = multi_field_coherence(variables, accesses, contexts)['a'][0]
        self.assertEqual(row['function_pair_count'], count*count)
        for prefix in ('writer', 'reader'):
            self.assertEqual(len(row[prefix+'_function_ids']), count)
            self.assertEqual(len(row[prefix+'_access_ids']), count*2)
        self.assertEqual(row['witness'], dict(writer_function_id='w00000', reader_function_id='r00000'))

    def test_logical_aliases_do_not_duplicate_physical_function_pairs(self):
        variables = [dict(symbol_id=sid, root_symbol_id='root') for sid in ('a', 'b')]
        contexts = {cid: dict(physical_id=physical) for cid, physical in
                    [('w1', 'MAIN'), ('w2', 'MAIN'), ('r1', 'IRQ'), ('r2', 'IRQ')]}
        accesses = {sid: [dict(access_id=sid+'W', function_id='writer', access_kind='WRITE', contexts=['w1', 'w2']),
                          dict(access_id=sid+'R', function_id='reader', access_kind='READ', contexts=['r1', 'r2'])]
                    for sid in ('a', 'b')}
        row = multi_field_coherence(variables, accesses, contexts)['a'][0]
        self.assertEqual(row['function_pair_count'], 1)
        self.assertEqual(row['writer_access_ids'], ['aW', 'bW'])
        self.assertEqual(row['reader_access_ids'], ['aR', 'bR'])

    def test_many_domains_keep_complete_sources_through_json(self):
        variables = [dict(symbol_id=sid, root_symbol_id='root') for sid in ('a', 'b')]
        contexts = {}
        accesses = {sid: [] for sid in ('a', 'b')}
        for domain in range(16):
            for role, prefix in [('WRITE', 'w'), ('READ', 'r')]:
                cid = prefix+str(domain)
                contexts[cid] = dict(physical_id=cid)
                for i in range(20):
                    fid = cid+'-'+str(i)
                    for sid in accesses:
                        accesses[sid].append(dict(access_id=sid+fid, function_id=fid,
                                                  access_kind=role, contexts=[cid]))
        result = multi_field_coherence(variables, accesses, contexts)
        self.assertEqual(result, reference_coherence(variables, accesses, contexts))
        decoded = json.loads(json.dumps(result))
        self.assertEqual(decoded, result)
        self.assertEqual(len(decoded['a']), 16*16)
        for row in decoded['a']:
            self.assertEqual(row['function_pair_count'], 20*20)
            self.assertEqual(len(row['writer_function_ids']), 20)
            self.assertEqual(len(row['reader_function_ids']), 20)
            self.assertEqual(len(row['writer_access_ids']), 40)
            self.assertEqual(len(row['reader_access_ids']), 40)


if __name__ == '__main__':
    unittest.main()
