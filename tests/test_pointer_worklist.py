"""Fixed-point equivalence and escape regressions for the pointer solver."""
import copy
import unittest

from ecra.points_to import Solver
from tests.test_preopencode_resolution import ResolutionTests


def loc(name):
    return dict(op='loc', id=name)


def addr(name):
    return dict(op='addr', value=loc(name))


class FullRescanSolver(Solver):
    """Independent scheduling oracle: revisit every equation after a change."""
    def schedule(self, location):
        for task in range(len(self.facts.get('pointer_constraints', []))):
            if task not in self.enqueued:
                self.pending.append(task)
                self.enqueued.add(task)


class PointerWorklistTests(unittest.TestCase):
    def check_fixed_point(self, constraints):
        facts = dict(variables=[], functions=[], accesses=[], calls=[], unknowns=[],
                     pointer_constraints=constraints)
        fast, oracle = Solver(copy.deepcopy(facts)), FullRescanSolver(copy.deepcopy(facts))
        fast.solve()
        oracle.solve()
        self.assertEqual(dict(fast.points), dict(oracle.points))
        self.assertTrue(fast.facts['points_to_stats']['complete'])
        return fast

    def test_backward_chain_revisits_only_dependent_equations(self):
        constraints = [dict(left=loc('p'+str(i+1)), right=loc('p'+str(i))) for i in reversed(range(40))]
        constraints.append(dict(left=loc('p0'), right=addr('target')))
        result = self.check_fixed_point(constraints)
        self.assertEqual(result.points['p40'], {'target'})
        self.assertLess(result.facts['points_to_stats']['evaluations'], 3*len(constraints))

    def test_new_dereference_targets_and_wildcard_slots_trigger_readers(self):
        constraints = [
            dict(left=loc('result'), right=dict(op='deref', value=loc('p'))),
            dict(left=loc('p'), right=addr('table/[*]')),
            dict(left=loc('table/[1]'), right=addr('first')),
            dict(left=loc('table/[7]'), right=addr('second')),
        ]
        result = self.check_fixed_point(constraints)
        self.assertEqual(result.points['result'], {'first', 'second'})

    def test_typed_aggregate_copy_does_not_recursively_embed_its_destination(self):
        constraints = [
            dict(left=loc('pool/pin'), right=loc('pool'), aggregate=True, aggregate_paths=['/callback']),
            dict(left=loc('pool/callback'), right=dict(op='function', id='Work')),
        ]
        result = self.check_fixed_point(constraints)
        self.assertEqual(result.points['pool/pin/callback'], {'fn:Work'})
        self.assertFalse(any('/pin/pin' in p for p in result.points))


class CopyEscapeTests(unittest.TestCase):
    setUp = ResolutionTests.setUp
    project = ResolutionTests.project
    facts = ResolutionTests.facts

    def test_copying_scalar_bytes_does_not_export_source_address(self):
        facts, _ = self.facts({'a.c': '''
            void *Destination(void); void *memcpy(void *, const void *, unsigned);
            static int value;
            int main(void) { memcpy(Destination(), &value, sizeof(value)); return 0; }
        '''})
        self.assertFalse(facts['address_escapes'])

    def test_copying_pointer_to_opaque_storage_exports_the_pointee(self):
        facts, _ = self.facts({'a.c': '''
            void *Destination(void); void *memcpy(void *, const void *, unsigned);
            static int value; static int *pointer=&value;
            int main(void) { memcpy(Destination(), &pointer, sizeof(pointer)); return 0; }
        '''})
        names = {v['symbol_id']: v['name'] for v in facts['variables']}
        self.assertEqual({names[e['symbol_id']] for e in facts['address_escapes']}, {'value'})

    def test_exported_callback_slot_in_complete_build_is_not_an_escape(self):
        facts, _ = self.facts({'a.c': '''
            static int value; static void Work(void) { value++; }
            void (*callback)(void)=Work;
            int main(void) { callback(); return 0; }
        '''})
        self.assertFalse(facts['address_escapes'])


if __name__ == '__main__':
    unittest.main()
