"""Lossless dependency propagation at high fan-in/fan-out."""
from collections import defaultdict, deque
from collections.abc import Mapping
from copy import deepcopy
import random
import tracemalloc
import unittest
from unittest.mock import patch

from ecra.diff_impact import _ImpactGraph, classify_impacts
from ecra.diff_dependencies import bind_dependencies


class ExpandedGraph:
    """Small-case oracle: the original explicit relation, never used at scale."""
    def __init__(self):
        self.rows = defaultdict(list)

    def edge(self, source, target, strength, reason, witness):
        if tuple(source) != tuple(target):
            self.rows[tuple(source)].append((tuple(target), strength, reason, witness))

    def effect(self, fid, row, complete, side):
        witness = dict(row['witness'], side=side)
        for output in row['outputs']:
            strength = output['certainty'] if complete else 'UNCERTAIN'
            self.edge(['entry', fid], output['node'], strength, 'CALL_DEPENDENCY',
                      dict(witness, uncertainty_reasons=output.get('uncertainty_reasons', [])))
            for source in row['inputs']:
                certainty = 'DEFINITE' if strength == source['certainty'] == 'DEFINITE' else 'UNCERTAIN'
                reason = ('RETURN_DEPENDENCY' if source['node'][0] == 'return' else
                          'PARAMETER_DEPENDENCY' if source['node'][0] == 'parameter' else
                          'CONTROL_DEPENDENCY' if source.get('dependency_kind') == 'CONTROL' else 'DATA_DEPENDENCY')
                self.edge(source['node'], output['node'], certainty, reason,
                          dict(witness, uncertainty_reasons=sorted(set(source.get('uncertainty_reasons', [])
                               + output.get('uncertainty_reasons', [])))))
        for observed in row['observed']:
            self.edge(['entry', fid], observed['node'], observed['certainty'] if complete else 'UNCERTAIN',
                      'CALL_DEPENDENCY', dict(witness, uncertainty_reasons=observed.get('uncertainty_reasons', [])))

    def neighbors(self, node, certainty, origins):
        return iter(self.rows[node])


def propagate(graph, phases):
    origins, queue = {}, deque()
    for number, seeds in enumerate(phases):
        for node, certainty, storage in seeds:
            key = (tuple(node), certainty, storage)
            if key not in origins:
                origins[key] = dict(reason='SEED', witness=dict(phase=number), previous=None)
                queue.append(key)
        while queue:
            key = queue.popleft()
            for target, strength, reason, witness in graph.neighbors(key[0], key[1], origins):
                effective = 'DEFINITE' if key[1] == strength == 'DEFINITE' else 'UNCERTAIN'
                following = (target, effective, False)
                if following not in origins:
                    origins[following] = dict(reason=reason, witness=witness, previous=key)
                    queue.append(following)
    return list(origins.items())


class DependencyScalingTests(unittest.TestCase):
    def test_array_overlap_scan_does_not_reload_full_records_for_each_pair(self):
        class CountedMap(Mapping):
            def __init__(self, values): self.values, self.reads = values, 0
            def __len__(self): return len(self.values)
            def __iter__(self): return iter(self.values)
            def __getitem__(self, key):
                self.reads += 1
                return self.values[key]
        count = 128
        rows = {str(i): dict(symbol_id=str(i), root='array', container=False,
                            array_index='['+str(i)+']', offset_bits=i*32, size_bytes=4,
                            accessors=[], dimensions={}, findings=[]) for i in range(count)}
        maps = [CountedMap(rows), CountedMap(deepcopy(rows))]
        summaries = [dict(variables=values, functions={}, edges=[], semantics={}, unknowns=[])
                     for values in maps]
        reasons = defaultdict(set, {sid: {'DIRECT_CHANGED'} for sid in rows})
        result = classify_impacts(*summaries, reasons, set(), build_changed=False)
        self.assertEqual(result['counts'], dict(DEFINITE=count, UNCERTAIN=0, EXCLUDED=0))
        self.assertTrue(all(step['reason'] != 'PHYSICAL_OVERLAP' for evidence in result['evidence'].values()
                            for path in evidence if path.get('kind') == 'DEPENDENCY_PATH'
                            for step in path['path']))
        # A disk-backed summary decodes a complete record on each read. This
        # bound catches N^2 decoding even when the fields are physically disjoint.
        self.assertLess(sum(values.reads for values in maps), count*24)

    def test_compact_relations_preserve_first_witness_order_and_both_certainties(self):
        rng = random.Random(8701)
        nodes = [['variable', 'v'+str(i)] for i in range(5)] + [
            ['entry', 'f'], ['return', 'g'], ['parameter', 'f', 0]]
        for trial in range(80):
            with self.subTest(trial=trial):
                graphs = [ExpandedGraph(), _ImpactGraph()]
                def operand():
                    return dict(node=rng.choice(nodes), certainty=rng.choice(['DEFINITE', 'UNCERTAIN']),
                                dependency_kind=rng.choice(['DATA', 'CONTROL']),
                                uncertainty_reasons=rng.choice([[], ['b', 'a', 'b'], ['a']]))
                records = []
                for index in range(5):
                    row = dict(inputs=[operand() for _ in range(rng.randrange(6))],
                               outputs=[operand() for _ in range(rng.randrange(7))],
                               observed=[operand() for _ in range(rng.randrange(5))],
                               witness=dict(function='f', file='a.c', line=index+1))
                    records.append(deepcopy(row))
                    complete, side = rng.choice([True, False]), rng.choice(['base', 'head'])
                    for graph in graphs:
                        graph.effect('f', row, complete, side)
                    self.assertEqual(row, records[-1])
                for _ in range(3):
                    source, target = rng.choice(nodes), rng.choice(nodes)
                    for graph in graphs:
                        graph.edge(source, target, 'UNCERTAIN', 'FUNCTION_ONLY_DEPENDENCY', dict(function='f'))
                phases = [[(rng.choice(nodes), rng.choice(['DEFINITE', 'UNCERTAIN']), rng.choice([False, True]))
                           for _ in range(4)] for _ in range(3)]
                self.assertEqual(propagate(graphs[0], phases), propagate(graphs[1], phases))

    def test_skipped_self_target_remains_available_to_a_later_source(self):
        a, b = ['variable', 'a'], ['variable', 'b']
        row = dict(inputs=[dict(node=n, certainty='UNCERTAIN') for n in (a, b)],
                   outputs=[dict(node=a, certainty='DEFINITE')], observed=[], witness=dict(function='f'))
        graph = _ImpactGraph(); graph.effect('f', row, True, 'head')
        result = dict(propagate(graph, [[(a, 'DEFINITE', False)], [(b, 'DEFINITE', False)]]))
        self.assertEqual(result[(tuple(a), 'UNCERTAIN', False)]['previous'], (tuple(b), 'DEFINITE', False))

    def test_high_fanout_keeps_all_destinations_without_a_cartesian_allocation(self):
        count = 8000
        inputs = [['variable', 'input'+str(i)] for i in range(count)]
        outputs = [['variable', 'output'+str(i)] for i in range(count)]
        row = dict(inputs=[dict(node=n, certainty='DEFINITE') for n in inputs],
                   outputs=[dict(node=n, certainty='DEFINITE') for n in outputs], observed=[],
                   witness=dict(function='f', file='source.c', line=7))
        tracemalloc.start()
        try:
            graph = _ImpactGraph(); graph.effect('f', row, True, 'head')
            result = dict(propagate(graph, [[(node, 'DEFINITE', False) for node in inputs]]))
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        self.assertEqual(len(result), 2*count)
        for node in outputs:
            record = result[(tuple(node), 'DEFINITE', False)]
            self.assertEqual(record['previous'], (tuple(inputs[0]), 'DEFINITE', False))
            self.assertEqual(record['witness'], dict(function='f', file='source.c', line=7,
                                                     side='head', uncertainty_reasons=[]))
        self.assertLess(peak, 64*1024**2, '64 million conceptual edges must not be allocated')

    def test_position_index_matches_linear_binding_with_aliases_and_duplicate_sites(self):
        class LinearSites:
            def __init__(self, rows, cid): self.rows, self.cid = rows, cid
            def matching(self, file, start, end):
                return (row for row in self.rows if self.cid(row[1].get('file')) == file)
        rng = random.Random(721)
        cid = lambda value: value.removeprefix('./') if isinstance(value, str) else value
        variables = {}
        for index in range(40):
            sid = 'v'+str(index)
            variables[sid] = dict(symbol_id=sid, root=sid, container=False, _dependency_accesses=[
                dict(function_id='f', file=rng.choice(['a.c', './a.c', 'b.c']), offset=rng.randrange(20),
                     line=1, access_id=sid+'-'+str(n), access_kind=rng.choice(['READ', 'WRITE', 'RMW']),
                     via_alias=True, alias_target_count=rng.choice([1, 2]), alias_has_unknown_target=False)
                for n in range(4)])
        effects = []
        for index in range(16):
            site = dict(file=rng.choice(['a.c', './a.c', 'b.c']), offset=index, end_offset=index+3)
            effects.append(dict(kind='write', signature=['constant', index], reads=[site], writes=[site],
                                sources=[], control_reads=[], control_sources=[], site=dict(file=site['file'], line=index+1)))
        functions = dict(f=dict(digest='function', _dependency_program=dict(
            schema=1, complete=True, issues=[], values=[], effects=effects)))
        expected_functions, expected_variables = deepcopy(functions), deepcopy(variables)
        with patch('ecra.diff_dependencies._AccessSites', LinearSites):
            bind_dependencies(expected_functions, expected_variables, cid, lambda value: value)
        bind_dependencies(functions, variables, cid, lambda value: value)
        self.assertEqual(functions, expected_functions)
        self.assertEqual(variables, expected_variables)


if __name__ == '__main__':
    unittest.main()
