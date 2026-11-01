import hashlib
import importlib.util
import json
from pathlib import Path
import random
import sys
import unittest
from dataclasses import asdict

from ecra.evidence import EvidenceIndex


REFERENCE = Path(__file__).parent / 'fixtures/e69_evidence.py'
spec = importlib.util.spec_from_file_location('ecra._e69_evidence', REFERENCE)
reference = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = reference
spec.loader.exec_module(reference)


def encoded(value):
    return json.dumps(value, ensure_ascii=True, separators=(',', ':'))


def fixture(count, calls):
    variable = dict(symbol_id='v', name='v', qualified_name='v',
                    canonical_path='v', definition_file='main.c', definition_line=1,
                    linkage='INTERNAL', translation_units=['main.c'])
    accesses = [dict(access_id='a'+str(i), function_id='f'+str(i),
                     access_kind='WRITE' if i % 3 else 'READ',
                     file='main.c', line=i+2, contexts=['main'],
                     via_alias=i % 7 == 0,
                     inherited_from_access_id='parent' if i % 11 == 0 else None)
                for i in range(count)]
    facts = dict(variables=[variable], functions=[], calls=calls, unknowns=[])
    contexts = dict(main=dict(physical_id='FOREGROUND', physical_kind='MAIN'))
    return variable, accesses, facts, contexts


class EvidenceAncestorTests(unittest.TestCase):
    def test_reference_is_byte_exact_original_e69_file(self):
        self.assertEqual(hashlib.sha256(REFERENCE.read_bytes()).hexdigest(),
                         'ac4ef73c86026a39b54996a661059fcc472595be40b8c28f6667fcf1259f1829')

    def test_complete_slices_match_original_for_cycles_duplicate_edges_and_opaque_entries(self):
        for seed in range(60):
            rng = random.Random(seed)
            calls = [dict(caller_function_id='f'+str(rng.randrange(24)),
                          callee_function_id='f'+str(rng.randrange(24))) for _ in range(70)]
            calls += [dict(caller_function_id='absent', callee_function_id='f1'),
                      dict(caller_function_id='f1', callee_function_id='f1'),
                      dict(caller_function_id='external', callee_function_id=None)]
            calls += calls[:4]
            variable, accesses, facts, contexts = fixture(24, calls)
            rng.shuffle(accesses)
            accesses += accesses[:8]
            facts['unknowns'] = [dict(kind='FUNCTION_ADDRESS', target_function_id='f'+str(i),
                function_id='publisher', actual_escape=True, file='callback.c', line=i+1)
                for i in range(0, 24, 3)]
            facts['unknowns'] += [dict(kind='UNRESOLVED_POINTEE', symbol_id='v',
                                      function_id='f2', file='main.c', line=4)]
            before = encoded([variable, accesses, facts, contexts])
            expected = reference.EvidenceIndex(facts, {}, {'project': {}}, set())
            actual = EvidenceIndex(facts, {}, {'project': {}}, set())
            for rows in [accesses, accesses[:1], [], accesses[3:12]]:
                with self.subTest(seed=seed, accesses=len(rows)):
                    self.assertEqual(encoded(asdict(actual.build(variable, rows, contexts, []))),
                                     encoded(asdict(expected.build(variable, rows, contexts, []))))
            self.assertEqual(encoded([variable, accesses, facts, contexts]), before)
            self.assertFalse(actual.ancestor_cache)

    def test_cache_eviction_and_oversized_closures_keep_every_ancestor(self):
        calls = [dict(caller_function_id='f'+str(i), callee_function_id='f'+str(i+1))
                 for i in range(300)]
        _, _, facts, _ = fixture(1, calls)
        expected = reference.EvidenceIndex(facts, {}, {'project': {}}, set())
        actual = EvidenceIndex(facts, {}, {'project': {}}, set())
        actual.ancestor_cache_budget = 257
        for i in list(range(301)) + list(reversed(range(301))):
            fid = 'f'+str(i)
            self.assertEqual(actual.ancestors(fid), expected.ancestors(fid))
            self.assertEqual(actual.ancestor_cache_members,
                             sum(map(len, actual.ancestor_cache.values())))
            self.assertLessEqual(actual.ancestor_cache_members, 257)
        self.assertEqual(len(actual.ancestors('f300')), 301)

    def test_non_string_keys_and_invalid_inputs_keep_original_literal_values_and_errors(self):
        for ids in [[True, 1, 1.0], [1.0, True, 1], [None], [0, False], ['plain'], []]:
            _, _, facts, _ = fixture(0, [])
            expected = reference.EvidenceIndex(facts, {}, {'project': {}}, set())
            actual = EvidenceIndex(facts, {}, {'project': {}}, set())
            rows = [dict(function_id=fid) for fid in ids]
            old = set().union(*(expected.ancestors(row['function_id']) for row in rows)) if rows else set()
            self.assertEqual(encoded(list(actual.runtime_ancestors(rows))), encoded(list(old)))
        for rows, error in [([dict(function_id=[])], TypeError),
                            ([dict(function_id=[]), {}], TypeError),
                            ([dict(function_id='valid'), {}], KeyError)]:
            _, _, facts, _ = fixture(0, [])
            with self.assertRaises(error):
                EvidenceIndex(facts, {}, {'project': {}}, set()).runtime_ancestors(rows)
