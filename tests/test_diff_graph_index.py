"""Large variable inventories share immutable graph evidence without losing edges."""
import copy
import json
import unittest

from ecra.git_diff import SUMMARY_SCHEMA, summarize, compare, variable_graph


class DiffGraphIndexTests(unittest.TestCase):
    def facts(self, count=600):
        return dict(variables=[dict(symbol_id='g'+str(i), name='g'+str(i),
            static_classification='SUSPECT', semantic_digest='definition',
            accesses=[dict(function_id='access', access_kind='RMW')]) for i in range(count)],
            functions=[dict(function_id=f, name=f, semantic_digest=f) for f in ('main', 'other', 'access')],
            calls=[dict(caller_function_id='main', callee_function_id='access')],
            context_call_graph=dict(roots=dict(MAIN=['main']), edges=dict(MAIN=[('main', 'access')])))

    def test_graph_is_serialized_once_for_all_variables(self):
        facts = self.facts()
        report = dict(findings=[], analysis_status='INCOMPLETE')
        summary = json.loads(json.dumps(summarize(facts, report)))
        self.assertEqual(summary['schema'], SUMMARY_SCHEMA)
        self.assertEqual(len(summary['variables']), 600)
        self.assertEqual(len(summary['graphs']), 1)
        for variable in summary['variables'].values():
            self.assertNotIn('graph', variable)
            self.assertEqual(variable_graph(summary, variable)['edges'], [['main', 'access']])
        encoded = json.dumps(summary)
        inline = copy.deepcopy(summary)
        for variable in inline['variables'].values():
            variable['graph'] = variable_graph(summary, variable)
        self.assertGreater(len(json.dumps(inline)), len(encoded))

    def test_roundtrip_preserves_changed_edges_paths_and_complete_graph(self):
        facts = self.facts(3)
        report = dict(findings=[], analysis_status='INCOMPLETE')
        base = summarize(facts, report)
        facts['calls'] = [dict(caller_function_id='main', callee_function_id='other'),
                          dict(caller_function_id='other', callee_function_id='access')]
        facts['context_call_graph']['edges']['MAIN'] = [('main', 'other'), ('other', 'access')]
        head = json.loads(json.dumps(summarize(facts, report)))
        delta = compare(base, head, dict(files=[], head_sha='H', base_sha='B'))
        self.assertEqual(delta['selected_symbol_ids'], ['g0', 'g1', 'g2'])
        for impact in delta['impacts'].values():
            self.assertIn('CALL_GRAPH_CHANGED', impact['reasons'])
            self.assertEqual(impact['removed_paths'], [['main', 'access']])
            self.assertTrue(all(path == ['main', 'other', 'access'] for path in impact['added_paths']))
            self.assertNotIn('graph', impact['base'])
            self.assertIn(impact['base']['graph_id'], base['graphs'])
        self.assertEqual(compare(head, head, dict(files=[], head_sha='H', base_sha='H'))['selected_symbol_ids'], [])


if __name__ == '__main__':
    unittest.main()
