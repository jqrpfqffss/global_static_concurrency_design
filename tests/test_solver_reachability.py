"""Conservative internal-function pruning for the pointer fixed point."""
import unittest

from ecra.points_to import Solver
from ecra.solver_reachability import prepare
from ecra.analysis import merge
from ecra.compilation import prepare as prepare_build
from ecra.extract import Extractor
from tests import test_ecra as fixtures


def function(name, static=True, **extra):
    return dict(function_id=name, name=name, qualified_name=name,
                file='helper.h' if static else 'main.c', is_static=static,
                linkage='INTERNAL' if static else 'EXTERNAL',
                parameter_count=0, **extra)


def location(name):
    return dict(op='loc', id=name)


def address(name):
    return dict(op='addr', value=location(name))


def constraint(owner, destination, target):
    return dict(function_id=owner, left=location(destination), right=address(target))


class SolverReachabilityTests(unittest.TestCase):
    def facts(self):
        return dict(functions=[function('entry', False), function('called'),
                               function('addressed'), function('configured'),
                               function('dead')], variables=[], accesses=[], unknowns=[],
                    registrations=[], pointer_storage=[], semantic_calls=[],
                    indirect_accesses=[], calls=[dict(caller_function_id='entry',
                                                      callee_function_id='called')],
                    pointer_constraints=[constraint('called', 'live', 'live_target'),
                                         constraint('dead', 'dead_slot', 'dead_target')],
                    build_closure=dict(missing_objects=[]))

    def test_direct_address_and_configured_entries_are_retained(self):
        facts = self.facts()
        facts['unknowns'].append(dict(kind='FUNCTION_ADDRESS', target_function_id='addressed'))
        cfg = dict(contexts=[dict(functions=['configured'])], call_edges=[])
        proof = prepare(facts, cfg)
        self.assertEqual(proof['pruned_function_ids'], ['dead'])
        solver = Solver(facts, cfg)
        solver.solve()
        self.assertEqual(solver.points['live'], {'live_target'})
        self.assertNotIn('dead_slot', solver.points)
        self.assertEqual(len(facts['pointer_constraints']), 2)

    def test_pointer_function_designator_keeps_target_body(self):
        facts = self.facts()
        facts['pointer_constraints'].append(dict(function_id='entry',
            left=location('callback'), right=dict(op='function', id='addressed')))
        proof = prepare(facts, dict(contexts=[], call_edges=[]))
        self.assertEqual(proof['pruned_function_ids'], ['configured', 'dead'])
        solver = Solver(facts)
        solver.solve()
        self.assertEqual(solver.points['callback'], {'fn:addressed'})

    def test_incomplete_build_disables_pruning(self):
        facts = self.facts()
        facts['unknowns'].append(dict(kind='PARSE_FAILED', file='missing.c'))
        self.assertEqual(prepare(facts, dict(contexts=[], call_edges=[]))['pruned_function_ids'], [])
        solver = Solver(facts)
        solver.solve()
        self.assertEqual(solver.points['dead_slot'], {'dead_target'})
        for missing in ({'unlisted_sources': ['extra.c']},
                        {'translation_units_failed': 1}):
            with self.subTest(missing=missing):
                clean = self.facts()
                self.assertEqual(prepare(clean, dict(contexts=[], call_edges=[]), missing)
                                 ['pruned_function_ids'], [])

    def test_implicit_entry_attribute_keeps_body(self):
        facts = self.facts()
        functions = {row['function_id']: row for row in facts['functions']}
        functions['addressed']['entry_attributes'] = ['CONSTRUCTOR_ATTR']
        functions['addressed']['attribute_spellings'] = ['constructor']
        functions['dead']['entry_attributes'] = ['UNEXPOSED_ATTR']
        functions['dead']['attribute_spellings'] = ['always_inline ) ) static']
        self.assertIn('dead', prepare(facts, dict(contexts=[], call_edges=[]))['pruned_function_ids'])
        self.assertNotIn('addressed', facts['pointer_solver_pruning']['pruned_function_ids'])

    def test_address_in_dead_body_does_not_create_an_entry(self):
        facts = self.facts()
        facts['functions'].append(function('hidden'))
        facts['unknowns'].append(dict(kind='FUNCTION_ADDRESS', function_id='dead',
                                      target_function_id='hidden'))
        facts['pointer_constraints'].append(dict(function_id='dead',
            left=location('slot'), right=dict(op='function', id='hidden')))
        proof = prepare(facts, dict(contexts=[], call_edges=[]))
        self.assertIn('hidden', proof['pruned_function_ids'])
        self.assertIn('dead', proof['pruned_function_ids'])


class ExtractedReachabilityTests(unittest.TestCase):
    setUp = fixtures.ProjectTest.setUp
    project = fixtures.ProjectTest.project
    extract = fixtures.ProjectTest.extract

    def test_header_helper_and_addressed_callback_keep_alias_writes(self):
        cfg = self.project({'helper.h': '''
            extern int shared;
            static inline int *Get(void) { return &shared; }
            static void Dead(void) { int *p = &shared; *p = 3; }
        ''', 'main.c': '''
            #include "helper.h"
            int shared;
            static void Callback(void) { int *p = &shared; *p = 2; }
            int main(void) {
                void (*cb)(void) = Callback; cb();
                int *p = Get(); *p = 1; return shared;
            }
        '''}, contexts=[dict(id='main', kind='MAIN', functions=['main'])])
        units, audit = prepare_build(self.root, cfg)
        parts = [Extractor(dict(root=str(self.root), unit=unit, config=cfg)).run()
                 for unit in units]
        self.assertTrue(all(part['parse_status'] == 'PARSED' for part in parts))
        facts = merge(parts)
        facts['build_closure'] = audit.get('build_closure', {})
        proof = prepare(facts, cfg)
        functions = {row['function_id']: row['name'] for row in facts['functions']}
        self.assertEqual({functions[fid] for fid in proof['pruned_function_ids']}, {'Dead'})
        Solver(facts, cfg).solve()
        shared = next(row['symbol_id'] for row in facts['variables'] if row['name'] == 'shared')
        writes = {functions[row['function_id']] for row in facts['accesses']
                  if row['symbol_id'] == shared and row['access_kind'] == 'WRITE'
                  and row.get('via_alias') == 'interprocedural points-to'}
        self.assertEqual(writes, {'Callback', 'main'})

    def test_dead_function_address_does_not_make_target_reachable(self):
        cfg = self.project({'a.c': '''
            int shared;
            static void Hidden(void) { shared++; }
            static void Dead(void) { void (*cb)(void) = Hidden; cb(); }
            int main(void) { return shared; }
        '''}, contexts=[dict(id='main', kind='MAIN', functions=['main'])])
        facts, _ = self.extract(cfg)
        functions = {row['name']: row for row in facts['functions']}
        self.assertIn(functions['Hidden']['function_id'],
                      facts['pointer_solver_pruning']['pruned_function_ids'])
        self.assertEqual(functions['Hidden']['reachability'], 'PROVEN_UNREACHABLE')


if __name__ == '__main__':
    unittest.main()
