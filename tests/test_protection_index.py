"""保护索引必须保留原判定、证据顺序及快照边界。"""
from collections import Counter
import copy
import json
import random
import unittest
from unittest.mock import patch

from ecra.analysis import analyze, merge
from ecra.compilation import prepare
from ecra.extract import Extractor
from ecra.protection import ProtectionIndex, assess
from tests.protection_reference import legacy_assess
from tests import test_ecra


def encoded(value):
    # Python 的 True == 1；序列化对照同时检查类型与列表顺序。
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


class ProtectionIndexTest(unittest.TestCase):
    def test_randomized_legacy_oracle(self):
        rng, statuses = random.Random(20261028), Counter()
        for number in range(5000):
            contexts = {str(i): dict(kind=rng.choice(['MAIN', 'ISR', 'TASK']),
                                    unmaskable=rng.choice([True, False]))
                        for i in range(rng.randint(1, 5))}
            functions = [dict(function_id=str(rng.randrange(5)),
                              name=rng.choice(['F', 'main', 'NMI_Handler', 'HardFault_Handler']))
                         for _ in range(rng.randrange(12))]
            bindings = [dict(function_id=str(rng.randrange(5)), context_id=rng.choice(list(contexts)),
                             call_depth=rng.randrange(3)) for _ in range(rng.randrange(12))]
            windows = [dict(symbol_id=rng.choice(['target', 'other']),
                            context_id=rng.choice(list(contexts)), primask=rng.choice([True, False]),
                            faultmask=rng.choice([True, False]), basepri_known=rng.choice([True, False]),
                            basepri_values=rng.choice([[], [0], [32], [128], [0, 128]]))
                       for _ in range(rng.randrange(30))]
            relations = [dict(contexts=rng.sample(list(contexts), min(2, len(contexts))),
                              relation=rng.choice(['SERIAL', 'PREEMPT', 'UNKNOWN']))
                         for _ in range(rng.randrange(8))]
            facts = dict(functions=functions, context_bindings=bindings,
                         mask_windows=windows, preemption_relations=relations)
            accesses = []
            for i in range(rng.randrange(12)):
                cids = rng.sample(list(contexts), rng.randrange(len(contexts) + 1))
                states = [dict(context_id=c, complete=rng.choice([True, False]),
                               irq_state=rng.choice(['UNKNOWN', 'DISABLED', 'ENABLED'])) for c in cids]
                accesses.append(dict(access_id=str(i), access_kind=rng.choice(['READ', 'WRITE', 'RMW', 'ADDRESS']),
                                     symbol_id='target', function_id=str(rng.randrange(5)), file='case.c',
                                     line=i + 1, contexts=cids, mask_states=states))
            events = {str(i): [dict(event_kind=rng.choice(['primask_set', 'lock_enter', 'lock_exit']),
                                    protection_type=rng.choice(['primask', 'basepri', 'faultmask', 'barrier']))
                               for _ in range(rng.randrange(4))] for i in range(5)}
            before = encoded([facts, accesses, events, contexts])
            expected = legacy_assess(accesses, events, contexts, facts, {})
            indexed = assess(accesses, events, contexts, facts, {}, index=ProtectionIndex(facts))
            self.assertEqual(encoded(expected), encoded(indexed), number)
            self.assertEqual(encoded(expected), encoded(assess(accesses, events, contexts, facts, {})), number)
            self.assertEqual(before, encoded([facts, accesses, events, contexts]), number)
            statuses[expected[0]] += 1
        self.assertEqual(set(statuses), {'EFFECTIVE', 'INEFFECTIVE', 'UNRESOLVED',
                                         'NOT_FOUND', 'PARTIAL', 'DETECTED'})

    def test_index_lifetime_order_and_duplicate_function_identity(self):
        first = dict(function_id='f', name='NMI_Handler')
        last = dict(function_id='f', name='IRQHandler')
        windows = [dict(symbol_id='g', context_id='main', primask=True),
                   dict(symbol_id='other', context_id='main', primask=False),
                   dict(symbol_id='g', context_id='main', primask=False)]
        facts = dict(functions=[first, last], mask_windows=windows)
        index = ProtectionIndex(facts)
        self.assertIs(index.functions['f'], last)
        self.assertEqual([id(w) for w in index.windows_by_symbol['g']], [id(windows[0]), id(windows[2])])
        with self.assertRaisesRegex(ValueError, '快照不一致'):
            assess([], {}, {}, copy.deepcopy(facts), {}, index=index)
        for field in ('functions', 'mask_windows'):
            old = facts[field]
            facts[field] = list(old)
            with self.assertRaises(ValueError):
                assess([], {}, {}, facts, {}, index=index)
            facts[field] = old
            old.append(old[0])
            with self.assertRaises(ValueError):
                assess([], {}, {}, facts, {}, index=index)
            old.pop()
        index.validate(facts)
        for invalid in (None, [dict(context_id='main')]):
            with self.assertRaises((TypeError, KeyError)):
                ProtectionIndex(dict(functions=[], mask_windows=invalid))
        empty = dict(functions=[])
        self.assertEqual(assess([], {}, {}, empty, {}, index=ProtectionIndex(empty))[0], 'NOT_FOUND')

    def test_repeated_assessments_do_not_rescan_global_collections(self):
        class Counted(list):
            def __iter__(self):
                self.iterations = getattr(self, 'iterations', 0) + 1
                return super().__iter__()
        functions = Counted([dict(function_id='f', name='main')])
        windows = Counted([dict(symbol_id='g', context_id='main', primask=True)] * 1000)
        facts = dict(functions=functions, mask_windows=windows, context_bindings=[])
        contexts = dict(main=dict(kind='MAIN'), irq=dict(kind='ISR'))
        accesses = [dict(access_id=c, access_kind='RMW', symbol_id='g', function_id='f',
                         contexts=[c], file='a.c', line=1,
                         mask_states=[dict(context_id=c, complete=True, irq_state='DISABLED')])
                    for c in contexts]
        events = dict(f=[dict(event_kind='lock_enter', protection_type='primask')])
        index = ProtectionIndex(facts)
        for _ in range(200):
            self.assertEqual(assess(accesses, events, contexts, facts, {}, index=index)[0], 'EFFECTIVE')
        self.assertEqual((functions.iterations, windows.iterations), (1, 1))
        self.assertEqual(len(index.windows_by_symbol['g']), 1000)
        # 重复窗口必须保留；不能用去重或数量上限换取性能。
        windows[-1] = dict(symbol_id='g', context_id='main', primask=False)
        fresh = ProtectionIndex(facts)
        self.assertNotEqual(assess(accesses, events, contexts, facts, {}, index=fresh)[0], 'EFFECTIVE')

    def test_clang_analysis_matches_frozen_legacy_with_full_evidence(self):
        fixture = test_ecra.ProjectTest('runTest')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        cfg = fixture.project({'a.c': '''
int protected_value, unprotected_value;
void __disable_irq(void); void __enable_irq(void);
void Helper(void){ protected_value++; }
void ISR(void){ protected_value++; unprotected_value++; }
void main(void){ __disable_irq(); Helper(); __enable_irq(); unprotected_value++; }
'''}, contexts=[dict(id='main', kind='MAIN', functions=['main']),
               dict(id='irq', kind='ISR', functions=['ISR'])])
        units, audit = prepare(fixture.root, cfg)
        parts = [Extractor(dict(root=str(fixture.root), unit=u, config=cfg)).run() for u in units]
        self.assertTrue(all(p['parse_status'] == 'PARSED' for p in parts))
        raw = merge(parts)
        indexed, reference = copy.deepcopy(raw), copy.deepcopy(raw)
        coverage = dict(translation_units_failed=0, **audit)
        actual = analyze(indexed, cfg, copy.deepcopy(coverage))
        def original(accesses, events, contexts, facts, config, *, index=None):
            return legacy_assess(accesses, events, contexts, facts, config)
        with patch('ecra.analysis.protection_assessment', side_effect=original):
            expected = analyze(reference, cfg, copy.deepcopy(coverage))
        self.assertEqual(encoded(indexed), encoded(reference))
        self.assertEqual(encoded(actual), encoded(expected))
        by_name = {v['name']: v for v in indexed['variables']}
        self.assertEqual(by_name['protected_value']['static_classification'], 'SAFE_PROVEN')
        self.assertEqual(by_name['unprotected_value']['static_classification'], 'SUSPECT')
        self.assertEqual(set(by_name['protected_value']['contexts']), {'main', 'irq'})
        self.assertTrue(indexed['mask_windows'])


if __name__ == '__main__':
    unittest.main()
