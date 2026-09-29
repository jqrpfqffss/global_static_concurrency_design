"""Fixed-point equivalence and escape regressions for the pointer solver."""
import copy
import gc
import unittest
import weakref

from ecra.points_to import Solver
from tests import test_preopencode_resolution as fixtures


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

    def load_location(self, location, decay=False):
        return self.compute_load(location, decay)[0]


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

    def test_location_caches_do_not_retain_completed_solvers(self):
        solver = Solver(dict(variables=[], functions=[]))
        solver.storage_location('local:x/field')
        solver.symbol('local:x/field')
        reference = weakref.ref(solver)
        del solver
        gc.collect()
        self.assertIsNone(reference())

    def test_escape_cache_tracks_new_pointees_and_contextual_getter_returns(self):
        from ecra.context_points import ContextSolver, scoped_location
        facts = dict(variables=[], functions=[], semantic_calls=[dict(_context_id='irq')])
        solver = ContextSolver(facts)
        slot = scoped_location('Get:return', 'irq')
        solver.add_points(slot + '/pointer', {'first'})
        self.assertEqual(solver.reachable_pointer_values({'fn:Get'}), {'fn:Get', 'first'})
        solver.add_points(slot + '/pointer', {'second'})
        self.assertEqual(solver.reachable_pointer_values({'fn:Get'}), {'fn:Get', 'first', 'second'})

    def test_new_dereference_targets_and_wildcard_slots_trigger_readers(self):
        constraints = [
            dict(left=loc('result'), right=dict(op='deref', value=loc('p'))),
            dict(left=loc('p'), right=addr('table/[*]')),
            dict(left=loc('table/[1]'), right=addr('first')),
            dict(left=loc('table/[7]'), right=addr('second')),
        ]
        result = self.check_fixed_point(constraints)
        self.assertEqual(result.points['result'], {'first', 'second'})

    def test_cached_loads_invalidate_for_opaque_ancestors_and_new_overlap_fields(self):
        solver = Solver(dict(variables=[], functions=[], pointer_storage=[
            dict(location='record', paths=['/first', '/second'], array_size=None)]))
        self.assertFalse(solver.value(loc('record/first')))
        solver.add_points('record', {'unknown:opaque'})
        self.assertEqual(solver.value(loc('record/first')), {'unknown:opaque'})
        solver.value(loc('record/$overlap'))
        solver.add_points('record/second', {'new-pointee'})
        self.assertIn('new-pointee', solver.value(loc('record/$overlap')))
        solver.add_points('record/$overlap', {'overlapping-pointee'})
        self.assertIn('overlapping-pointee', solver.value(loc('record/first')))

    def test_cached_wildcard_load_sees_late_array_slots_and_updates(self):
        solver = Solver(dict(variables=[], functions=[]))
        self.assertFalse(solver.value(loc('table/[*]')))
        solver.add_points('table/[1]', {'first'})
        self.assertEqual(solver.value(loc('table/[*]')), {'first'})
        solver.add_points('table/[1]', {'second'})
        solver.add_points('table/[9]', {'third'})
        self.assertEqual(solver.value(loc('table/[*]')), {'first','second','third'})

    def test_cached_random_graphs_match_uncached_full_rescan(self):
        import random
        rng = random.Random(3817)
        for _ in range(20):
            constraints = [dict(left=loc('p'+str(i)), right=addr('p'+str((i+1)%8))) for i in range(8)]
            for _ in range(30):
                left, right = loc('p'+str(rng.randrange(8))), loc('p'+str(rng.randrange(8)))
                if rng.randrange(2):
                    right = dict(op='deref', value=right)
                if rng.randrange(3) == 0:
                    left = dict(op='deref', value=left)
                constraints.append(dict(left=left,right=right))
            rng.shuffle(constraints)
            self.check_fixed_point(constraints)

    def test_typed_aggregate_copy_does_not_recursively_embed_its_destination(self):
        constraints = [
            dict(left=loc('pool/pin'), right=loc('pool'), aggregate=True, aggregate_paths=['/callback']),
            dict(left=loc('pool/callback'), right=dict(op='function', id='Work')),
        ]
        result = self.check_fixed_point(constraints)
        self.assertEqual(result.points['pool/pin/callback'], {'fn:Work'})
        self.assertFalse(any('/pin/pin' in p for p in result.points))

    def test_incompatible_record_views_have_finite_variable_local_overlap(self):
        facts = dict(variables=[dict(symbol_id='object', name='object', is_struct=True,
                       member_definitions=[dict(field_path='next')])], functions=[],
                     accesses=[], calls=[], unknowns=[], pointer_constraints=[
            dict(left=loc('p'), right=addr('obj:object')),
            dict(left=loc('p'), right=dict(op='addr', value=dict(op='field',
                 base=dict(op='deref', value=loc('p')), field='other'))),
        ])
        solver = Solver(facts)
        solver.solve()
        self.assertEqual(solver.points['p'], {'obj:object', 'obj:object/$overlap'})
        self.assertIn('unknown:overlap:object', solver.value(loc('obj:object/$overlap')))
        self.assertLess(facts['points_to_stats']['evaluations'], 10)

    def test_local_cast_cycle_is_finite_and_keeps_stored_global_targets(self):
        facts = dict(variables=[], functions=[], accesses=[], calls=[], unknowns=[],
                     pointer_storage=[dict(location='local:record', paths=['/pointer'], array_size=None)],
                     pointer_constraints=[
            dict(left=loc('p'), right=addr('local:record')),
            dict(left=loc('p'), right=dict(op='addr', value=dict(op='field',
                 base=dict(op='deref', value=loc('p')), field='other'))),
            dict(left=loc('local:record/pointer'), right=addr('target')),
            dict(left=loc('out'), right=dict(op='deref', value=loc('p'))),
        ])
        solver = Solver(facts)
        solver.solve()
        self.assertEqual(solver.points['p'], {'local:record', 'local:record/$overlap'})
        self.assertIn('target', solver.points['out'])
        self.assertIn('unknown:overlap:local:record', solver.points['out'])
        self.assertLess(facts['points_to_stats']['evaluations'], 20)

    def test_local_array_offset_cycle_uses_one_overlap_beyond_declared_extent(self):
        facts = dict(variables=[], functions=[], accesses=[], calls=[], unknowns=[],
                     pointer_storage=[dict(location='local:array', paths=['/[*]'], array_size=3)],
                     pointer_constraints=[
            dict(left=loc('p'), right=addr('local:array/[0]')),
            dict(left=loc('q'), right=dict(op='offset', value=loc('p'), index='1')),
            dict(left=loc('p'), right=loc('q')),
        ])
        solver = Solver(facts)
        solver.solve()
        self.assertIn('local:array/$overlap', solver.points['p'])
        self.assertNotIn('local:array/[3]', solver.points['p'])
        self.assertTrue(facts['points_to_stats']['complete'])

    def test_global_nested_arrays_preserve_fields_and_finite_extents(self):
        solver = Solver(dict(variables=[dict(symbol_id='object',name='object')],functions=[],pointer_storage=[
            dict(location='obj:object',paths=['/items','/items/[*]','/items/[*]/callback','/items/[*]/data',
                 '/matrix','/matrix/[*]','/matrix/[*]/[*]','/matrix/[*]/[*]/[*]'],array_size=None,
                 array_extents={'/items':4,'/matrix':2,'/matrix/[*]':3,'/matrix/[*]/[*]':5})]))
        field = 'obj:object/items/[2]/callback'
        self.assertEqual(solver.storage_location(field),field)
        matrix = 'obj:object/matrix/[1]/[2]/[4]'
        self.assertEqual(solver.storage_location(matrix),matrix)
        self.assertEqual(solver.storage_location('obj:object/matrix/[1]/[2]/[5]'),'obj:object/$overlap')
        solver.add_points('obj:object/items/[2]/data',{'buffer'})
        solver.add_points(field,{'fn:Callback'})
        self.assertEqual(solver.value(loc(field)),{'fn:Callback'})


class CopyEscapeTests(unittest.TestCase):
    setUp = fixtures.ResolutionTests.setUp
    project = fixtures.ResolutionTests.project
    facts = fixtures.ResolutionTests.facts

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

    def test_nested_field_write_does_not_write_its_inline_parent(self):
        facts, _ = self.facts({'a.c': '''
            struct Inner {int first, second;}; struct Outer {struct Inner inner;} object;
            void Set(struct Outer *p) { p->inner.first=7; }
            int main(void) { Set(&object); return 0; }
        '''})
        writes = [a['access_path'] for a in facts['accesses']
                  if a['access_kind'] in {'WRITE','RMW'} and a.get('via_alias') == 'interprocedural points-to']
        self.assertEqual(writes, ['/inner/first'])

    def test_write_through_pointer_member_reads_the_pointer_slot(self):
        facts, _ = self.facts({'a.c': '''
            struct Regs {int data;}; static struct Regs registers;
            struct Handle {struct Regs *instance;} handle={&registers};
            void Set(struct Handle *p) { p->instance->data=7; }
            int main(void) { Set(&handle); handle.instance->data=9; return 0; }
        '''})
        handle = next(v for v in facts['variables'] if v['name']=='handle')
        writes = [a for a in facts['accesses'] if a['symbol_id']==handle['symbol_id']
                  and a['access_kind'] in {'WRITE','RMW'}]
        self.assertEqual(writes, [])
        self.assertTrue(any(a['access_path']=='/data' and a['access_kind']=='WRITE' for a in facts['accesses']))


if __name__ == '__main__':
    unittest.main()
