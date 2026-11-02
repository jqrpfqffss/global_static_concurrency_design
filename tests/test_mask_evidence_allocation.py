import copy
import gc
import hashlib
import importlib.util
import json
from pathlib import Path
import random
import tracemalloc
import unittest
from unittest.mock import patch

from ecra.protection import MaskAnalysis
from ecra.read_only_evidence import ReadOnlyEvidence


REFERENCE = Path(__file__).parent/'fixtures/v19_mask_analysis.py'
spec = importlib.util.spec_from_file_location('ecra._mask_allocation_reference', REFERENCE)
reference = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reference)


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def inputs(symbols=20, variant='normal'):
    operations = [dict(op='entry'), dict(op='call', name='__disable_irq', arguments=[]),
        dict(op='assign', local='saved', value=dict(call='__get_PRIMASK')),
        dict(op='call', name='__set_BASEPRI', arguments=[dict(constant=128)]),
        dict(op='assign', local='temporary', value=dict(constant=7)),
        dict(op='call', name='__enable_irq', arguments=[]),
        dict(op='call', name='__disable_irq', arguments=[]),
        dict(op='call', name='__set_PRIMASK', arguments=[dict(local='saved')]), dict(op='exit')]
    nodes = [dict(id=i, file='中.c', offset=i*10, end_offset=i*10+9,
        successors=[i+1] if i < len(operations)-1 else [], **row) for i, row in enumerate(operations)]
    graph = dict(function_id='f', cfg_id='cfg', entry=0, exit=8, complete=True, parameters=[], nodes=nodes)
    if variant == 'loop': nodes[4]['successors'] = [4, 5]
    if variant == 'branch': nodes[3]['successors'] = [4, 6]
    if variant in {'unknown', 'local-unknown', 'incomplete'}:
        nodes[4].update(op='unknown', reason='UNSEQUENCED_EXPRESSION')
        if variant != 'unknown':
            graph['complete'] = False
            graph['unsupported'] = [dict(file='中.c', offset=40, end_offset=49,
                kind='UNSEQUENCED_EXPRESSION' if variant == 'local-unknown' else 'UNSUPPORTED_ASM')]
    if variant == 'unknown-call': nodes[3].update(name='external_unknown')
    if variant == 'basepri-max': nodes[3].update(name='__set_BASEPRI_MAX')
    if variant == 'faultmask': nodes[1].update(name='__disable_fault_irq')
    if variant == 'recursive': nodes[3].update(name='f', callee='f')
    accesses = []
    for symbol in range(symbols):
        for at, kind in [(2, 'ADDRESS_TAKEN'), (4, 'READ'), (5, 'WRITE'), (6, 'RMW'), (99, 'READ')]:
            accesses.append(dict(access_id=f'a{symbol}.{at}', symbol_id='s'+str(symbol),
                function_id='f', access_kind=kind, file='中.c', offset=at*10+1,
                contexts=['main', 'IRQ'], future_evidence=dict(ordered=[True, 1, -0.0, 10**40])))
    return dict(accesses=accesses, control_flow=[graph],
        context_bindings=[dict(function_id='f', context_id=cid, call_depth=0) for cid in ['main', 'IRQ']],
        context_call_graph=dict(edges={cid: [['f', 'f']] if variant == 'recursive' else [] for cid in ['main', 'IRQ']}))


class MaskEvidenceAllocationTests(unittest.TestCase):
    def compare(self, facts):
        outputs = []
        for cls in [reference.MaskAnalysis, MaskAnalysis]:
            value = copy.deepcopy(facts)
            analyzer = cls(value, dict(critical_sections=[]))
            analyzer.run()
            outputs.append(encoded((value, dict(analyzer.observations), list(analyzer.windows.items()),
                                    list(analyzer.memo.items()), list(analyzer.effects.items()))))
        self.assertEqual(outputs[0], outputs[1], 'All mask facts, duplicates, windows and solver outcomes must match')

    def test_original_module_pin_and_every_flow_mask_context_and_recursive_case_match(self):
        self.assertEqual(hashlib.sha256(REFERENCE.read_text('utf-8').encode()).hexdigest(),
            'ae246acefc86ae7ab7fe7c91df02829a219e5e894485cc6d78b1fa854b3e46f5')
        for variant in ['normal', 'branch', 'loop', 'unknown', 'local-unknown', 'incomplete',
                        'unknown-call', 'basepri-max', 'faultmask', 'recursive']:
            with self.subTest(variant=variant): self.compare(inputs(7, variant))

    def test_seeded_access_selectors_duplicate_ids_unmatched_and_no_cfg_keep_every_occurrence(self):
        rng = random.Random(1912026)
        for case in range(25):
            facts = inputs(9, rng.choice(['normal', 'branch', 'loop', 'unknown', 'incomplete']))
            for a in facts['accesses']:
                if rng.randrange(3): a['allowed_contexts'] = rng.choices(['main', 'IRQ', 'absent'], k=rng.randrange(4))
                if rng.randrange(7) == 0: a['function_id'] = 'no-cfg'
                if rng.randrange(8) == 0: a['file'] = 'different.c'
            facts['accesses'] += copy.deepcopy(facts['accesses'][:6])
            with self.subTest(case=case): self.compare(facts)

    def test_complete_scalar_type_order_and_unknown_values_are_never_normalized(self):
        pool = ReadOnlyEvidence(cache_size=2)
        records = [dict(value=v) for v in [True, 1, False, 0, -0.0, 0.0, 10**80, '中文', None]]
        result = [pool.record(row, share=True) for row in records]
        self.assertEqual(encoded(result), encoded(records))
        mutable = dict(data=[1, 1, 2], future=dict(n=-0.0))
        first, second = pool.record(mutable, share=True), pool.record(mutable, share=True)
        first['added'] = 1
        self.assertNotIn('added', second)
        self.assertEqual(encoded(pool.record(dict(b=1, a=2), share=True)), '{"b":1,"a":2}')
        self.assertLessEqual(len(pool.records), 2)

    def test_hash_collisions_and_evictions_cannot_merge_different_or_untyped_node_lists(self):
        pool = ReadOnlyEvidence(cache_size=1)
        with patch('ecra.read_only_evidence.hash', return_value=17, create=True):
            for value in [[1, 2, 2], [2, 1, 2], [3, 4, 4], [1, 2, 2], [], [True], [1], [-0.0], [0.0]]:
                self.assertEqual(encoded(pool.integer_list(value)), encoded(value))
        self.assertLessEqual(len(pool.integer_lists), 1)
        # Layout reuse is independent of arbitrary original fields and cannot
        # alias mutable per-row dicts such as the final mask_windows records.
        first, second = pool.record(dict(node_ids=[1, 2])), pool.record(dict(node_ids=[1, 2]))
        first['complete'] = False
        self.assertNotIn('complete', second)

    def test_all_observations_and_windows_remain_with_lower_retained_python_allocation(self):
        live, hashes = [], []
        for cls in [reference.MaskAnalysis, MaskAnalysis]:
            facts = inputs(2200)
            gc.collect(); tracemalloc.start(1)
            try:
                cls(facts, dict(critical_sections=[])).run()
                live.append(tracemalloc.get_traced_memory()[0])
            finally:
                tracemalloc.stop()
            self.assertEqual(len(facts['accesses']), 11000)
            self.assertEqual(len(facts['mask_windows']), 4400)
            hashes.append(hashlib.sha256(encoded(facts).encode()).hexdigest())
            del facts
        self.assertEqual(hashes[0], hashes[1])
        self.assertLess(live[1], live[0] * 0.8,
            'Only physical read-only objects/layout may change,not any observation/window')


if __name__ == '__main__':
    unittest.main()
