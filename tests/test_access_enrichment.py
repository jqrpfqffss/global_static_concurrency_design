from collections import defaultdict
import copy
import gc
import hashlib
import importlib.util
import json
from pathlib import Path
import random
import tracemalloc
import unittest

from ecra.access_enrichment import enrich_accesses
from ecra.call_graph import AccessGraphSlices


REFERENCE = Path(__file__).parent/'fixtures/v19_access_enrichment.py'
spec = importlib.util.spec_from_file_location('ecra._access_enrichment_reference', REFERENCE)
reference = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reference)


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'),
        default=lambda v: dict(container=type(v).__name__, items=sorted(v)))


def inputs(rows):
    contexts = ['main', 'IRQ', '中断']
    edges = [('entry', 'f0'), ('f0', 'f1'), ('f1', 'f2'), ('f2', 'f1'), ('f2', 'f3')]
    facts = dict(accesses=rows,
        calls=[dict(caller_function_id=a, callee_function_id=b) for a, b in edges+edges[:2]],
        unknowns=[dict(kind='INDIRECT_CALL', function_id='f1'),
            dict(kind='EXTERNAL_CALLEE', target_function_id='f3'), dict(kind='OTHER', function_id='f2')],
        recursive_edges=[['f1', 'f2'], ['f2', 'f1']],
        context_call_graph=dict(representation='COMPLETE_GRAPH', edges={c: edges for c in contexts}))
    paths = {f: {c: ['entry', f] for c in contexts} for f in ['f0', 'f1', 'f2', 'f3']}
    complete = {f: {c: [['entry', f], ['entry', 'f0', f], ['entry', f]] for c in contexts}
                for f in paths}
    events = defaultdict(list, {f: [dict(function_id=f, event_kind=kind, line=i)
        for i, kind in enumerate(['lock_enter', 'unknown', 'lock_exit', 'lock_enter'])] for f in paths})
    return facts, paths, complete, {'missing'}, events


def run(function, data, **kwargs):
    facts, paths, complete, unreachable, events = data
    graph = AccessGraphSlices(facts, paths)
    by_var = defaultdict(list)
    function(facts, paths, complete, unreachable, events, graph, False, by_var, **kwargs)
    facts['call_graph_slices'] = graph.cache
    return facts, by_var


class AccessEnrichmentTests(unittest.TestCase):
    def compare(self, rows, **kwargs):
        before = inputs(rows)
        preserved = encoded(before[1:3])
        reference_data = copy.deepcopy(before)
        old = run(reference.enrich_accesses, reference_data)
        new = run(enrich_accesses, before, **kwargs)
        self.assertEqual(encoded(new), encoded(old), 'Every field/order/duplicate and graph edge must match')
        self.assertEqual(encoded(before[1:3]), preserved)
        # defaultdict's original events[fid] lookup inserts a missing empty
        # bucket. Preserve that behavior too, rather than assert no mutation.
        self.assertEqual(encoded(before[4]), encoded(reference_data[4]))
        return new

    def test_frozen_original_loop_and_complete_fields_keep_duplicate_routes_cycles_and_missing_contexts(self):
        raw = REFERENCE.read_text('utf-8').split('def enrich_accesses(', 1)[1].split('\n', 1)[1]
        self.assertEqual(hashlib.sha256(raw.encode()).hexdigest(),
            '7635719f65ca00c5e1962eacc0e8b938250d511cffafdf34ef7943ddaad46715')
        selectors = [None, [], ['IRQ', 'main', 'IRQ'], ('中断', 'main'), {'IRQ'}, frozenset(['main']), ['absent']]
        rows = [dict(access_id=str(i), function_id=fid, symbol_id='s'+str(i % 2), allowed_contexts=allowed,
            context_proven_unreachable=i % 4 == 0, resolved_call_edges=['old'], unresolved_call_edges=['old'])
            for i, (fid, allowed) in enumerate((f, a) for f in ['f0', 'f1', 'missing'] for a in selectors)]
        result, by_var = self.compare(rows)
        self.assertEqual(sum(len(v) for v in by_var.values()), len(rows))
        self.assertTrue(any(a['reachability'] == 'UNKNOWN_ENTRY' for a in result['accesses']))
        self.assertTrue(any(a['call_chain_cycles'] for a in result['accesses']))

    def test_seeded_context_selectors_and_evictions_preserve_full_ordered_results(self):
        rng = random.Random(1812026)
        for case in range(40):
            rows = [dict(access_id=str(i), symbol_id='s'+str(rng.randrange(5)),
                function_id=rng.choice(['f0', 'f1', 'f2', 'f3', 'missing']),
                allowed_contexts=None if rng.randrange(4) == 0 else
                    rng.choices(['main', 'IRQ', '中断', 'absent'], k=rng.randrange(5))) for i in range(70)]
            with self.subTest(case=case):
                self.compare(rows, cache_size=case % 4)

    def test_unknown_membership_objects_keep_per_access_evaluation(self):
        class ChangingMembership:
            def __init__(self): self.calls = 0
            def __contains__(self, value):
                self.calls += 1
                return self.calls % 2 == 0
        results = []
        for function in [reference.enrich_accesses, enrich_accesses]:
            selector = ChangingMembership()
            rows = [dict(access_id=str(i), function_id='f1', symbol_id='s', allowed_contexts=selector)
                for i in range(5)]
            facts, _ = run(function, inputs(rows))
            results.append((selector.calls, encoded([{k: v for k, v in a.items() if k != 'allowed_contexts'}
                                                      for a in facts['accesses']])))
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[1][0], 15)

    def test_repeated_enrichment_replaces_old_views_and_keeps_access_mutations_independent(self):
        rows = [dict(access_id=str(i), function_id='f1', symbol_id='s') for i in range(3)]
        data = inputs(rows)
        run(enrich_accesses, data)
        rows[0]['mask_states'] = [{'complete': False}]
        self.assertNotIn('mask_states', rows[1])
        data[1]['f1'] = {'IRQ': ['replacement', 'f1']}
        data[2]['f1'] = {'IRQ': [['replacement', 'f1']]}
        actual = run(enrich_accesses, data)
        expected = run(reference.enrich_accesses, copy.deepcopy(data))
        self.assertEqual(encoded(actual), encoded(expected))
        self.assertEqual(rows[0]['call_chains'], {'IRQ': ['replacement', 'f1']})

    def test_complete_access_enrichment_uses_less_retained_allocation_without_dropping_any_access(self):
        metrics, hashes = [], []
        for function in [reference.enrich_accesses, enrich_accesses]:
            data = inputs([dict(access_id=str(i), function_id='f'+str(i % 4), symbol_id='s'+str(i % 40))
                for i in range(16000)])
            gc.collect(); tracemalloc.start(1)
            try:
                result = run(function, data)
                metrics.append(tracemalloc.get_traced_memory()[0])
            finally:
                tracemalloc.stop()
            hashes.append(hashlib.sha256(encoded(result).encode()).hexdigest())
            del data, result
        self.assertEqual(hashes[0], hashes[1])
        self.assertLess(metrics[1], metrics[0] * 0.8,
            'Only repeated read-only containers may disappear; all16000 accesses remain')


if __name__ == '__main__':
    unittest.main()
