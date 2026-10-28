import random
import unittest

from ecra.initialization import InitializationIndex, _phase_entries_closed
from tests.initialization_reference import reference_phase_entries_closed


class InitializationIndexTests(unittest.TestCase):
    def test_all_modeled_entry_closures_match_the_exhaustive_reference(self):
        for seed in range(1000):
            rng = random.Random(seed)
            contexts = dict(main=dict(physical_kind='FOREGROUND'), irq=dict(physical_kind='IRQ'),
                            dma=dict(physical_kind='DMA'), other=dict(physical_kind='FOREGROUND'))
            facts = dict(functions=[dict(function_id=str(i), name='main' if i == 0 else 'f'+str(i))
                                    for i in range(20)],
                         calls=[dict(caller_function_id=str(rng.randrange(20)),
                                     callee_function_id=str(rng.randrange(22)),
                                     call_kind=rng.choice(['DIRECT', 'CONFIGURED', 'ASSEMBLY_LITERAL_CALL']),
                                     offset=rng.choice([None, 4, 8])) for _ in range(25)],
                         vector_entries=[dict(function_id='1', kind='MAIN', slot=1)],
                         context_bindings=[dict(context_id=rng.choice(list(contexts)),
                                                function_id=str(rng.randrange(20)), call_depth=0)
                                           for _ in range(8)],
                         irq_priority_events=[dict(api_name='NVIC_EnableIRQ', function_id='5')])
            cfg = {};index = InitializationIndex(facts, cfg)
            for variable in range(5):
                accesses = [dict(function_id=str(rng.randrange(20)),
                                 access_kind=rng.choice(['READ', 'WRITE', 'RMW', 'ADDRESS_TAKEN']),
                                 contexts=rng.sample(list(contexts), rng.randrange(5))) for _ in range(5)]
                with self.subTest(seed=seed, variable=variable):
                    self.assertEqual(_phase_entries_closed(accesses, facts, contexts, cfg, index),
                                     reference_phase_entries_closed(accesses, facts, contexts, cfg))

    def test_recursive_closure_has_no_fixed_depth_and_is_complete(self):
        count = 3000
        facts = dict(functions=[dict(function_id=str(i), name='main' if i == 0 else 'f') for i in range(count)],
                     calls=[dict(caller_function_id=str(i), callee_function_id=str((i+1)%count))
                            for i in range(count)])
        index = InitializationIndex(facts, {})
        self.assertEqual(index.closure('0'), frozenset(str(i) for i in range(count)))

    def test_index_from_a_different_analysis_cannot_be_reused(self):
        facts, cfg = dict(functions=[]), {}
        index = InitializationIndex(facts, cfg)
        with self.assertRaises(ValueError):
            index.validate(dict(functions=[]), cfg)
        with self.assertRaises(ValueError):
            index.validate(facts, {})


if __name__ == '__main__':
    unittest.main()
