"""Source and inherited access IDs stay connected through member expansion."""

import copy
import unittest

from ecra.analysis import canonicalize_member_resources
from ecra.storage import canonicalize_arrays


class PrecisionAccessIdTests(unittest.TestCase):
    def test_inherited_member_ids_reference_stable_source(self):
        root = dict(symbol_id='root', qualified_name='state', name='state',
                    is_struct=True, alignment_bytes=4,
                    member_definitions=[dict(field_path='value', name='value',
                                             type='unsigned', size_bytes=4,
                                             offset_bits=0)])
        source = dict(access_id='source-write', symbol_id='root',
                      access_kind='WRITE', access_path='', function_id='main')
        unrelated = dict(access_id='other-read', symbol_id='other',
                         access_kind='READ', access_path='', function_id='main')

        def expanded(order):
            facts = dict(variables=[copy.deepcopy(root)], accesses=copy.deepcopy(order), unknowns=[])
            canonicalize_member_resources(facts)
            ids = [a['access_id'] for a in facts['accesses']]
            self.assertEqual(len(ids), len(set(ids)))
            derived = next(a for a in facts['accesses']
                           if a.get('access_scope') == 'INHERITED_WHOLE_OBJECT_ACCESS')
            self.assertEqual(derived['inherited_from_access_id'], 'source-write')
            self.assertIn(derived['inherited_from_access_id'], ids)
            self.assertIn('source-write', ids)
            return derived['access_id']

        self.assertEqual(expanded([source, unrelated]), expanded([unrelated, source]))

    def test_array_overlap_and_whole_object_have_existing_parents(self):
        root = dict(symbol_id='array', qualified_name='slots', name='slots',
                    type='unsigned[2]', is_array=True, is_struct=False,
                    size_bytes=8, alignment_bytes=4,
                    array_element_size_bytes=4, array_element_alignment_bytes=4)
        accesses = [dict(access_id='indexed', symbol_id='array', access_path='[0]',
                         access_kind='WRITE'),
                    dict(access_id='dynamic', symbol_id='array', access_path='[*]',
                         access_kind='READ'),
                    dict(access_id='whole', symbol_id='array', access_path='',
                         access_kind='WRITE')]
        facts = dict(variables=[root], accesses=accesses, unknowns=[])
        canonicalize_arrays(facts)
        ids = {a['access_id'] for a in facts['accesses']}
        self.assertEqual(len(ids), len(facts['accesses']))
        self.assertTrue(any(a['access_id'] == 'whole' and a['array_source_access']
                            for a in facts['accesses']))
        self.assertTrue(all(a['inherited_from_access_id'] in ids
                            for a in facts['accesses'] if a.get('inherited_from_access_id')))


if __name__ == '__main__':
    unittest.main()
