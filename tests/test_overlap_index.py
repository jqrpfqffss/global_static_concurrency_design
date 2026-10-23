"""Complete overlap propagation, including ordering and conservative storage."""
import copy
import unittest

from ecra.storage import propagate_overlapping_members


class OverlapIndexTests(unittest.TestCase):
    def facts(self, fields, **root_options):
        root = dict(symbol_id='r', member_definitions=[], **root_options)
        members = [dict(symbol_id='r.'+name, root_symbol_id='r', resource_kind='STRUCT_MEMBER',
                        canonical_path='state.'+name, field_path=name, **options)
                   for name, options in fields]
        return dict(variables=[root, *members], accesses=[], unknowns=[])

    def access(self, facts, name):
        facts['accesses'].append(dict(access_id='a.'+name, symbol_id='r.'+name, access_kind='WRITE'))
        facts['unknowns'].append(dict(kind='ADDRESS_ESCAPE', symbol_id='r.'+name))

    def check_targets(self, facts, access_targets, unknown_targets):
        original_accesses = copy.deepcopy(facts['accesses'])
        original_unknowns = copy.deepcopy(facts['unknowns'])
        propagate_overlapping_members(facts)
        self.assertEqual(facts['accesses'][:len(original_accesses)], original_accesses)
        self.assertEqual(facts['unknowns'][:len(original_unknowns)], original_unknowns)
        self.assertEqual([(row['inherited_from_access_id'], row['symbol_id'])
                          for row in facts['accesses'][len(original_accesses):]], access_targets)
        self.assertEqual([row['symbol_id'] for row in facts['unknowns'][len(original_unknowns):]], unknown_targets)

    def test_multiple_groups_bitfields_and_order_without_duplicate_effects(self):
        facts = self.facts([
            ('a', dict(overlap_groups=['x', 'y'])),
            ('b', dict(overlap_groups=['y'])),
            ('c', dict(overlap_groups=['x', 'y'])),
            ('bits1', dict(is_bitfield_container=True)),
            ('bits2', dict(is_bitfield_container=True)),
            ('plain', {})])
        for name in ('a', 'bits1', 'plain'):
            self.access(facts, name)
        self.check_targets(facts, [('a.a', 'r.b'), ('a.a', 'r.c'), ('a.bits1', 'r.bits2')],
                           ['r.b', 'r.c', 'r.bits2'])

    def test_union_propagates_to_every_other_member(self):
        facts = self.facts([(name, {}) for name in ('a', 'b', 'c')], is_union=True)
        self.access(facts, 'b')
        self.check_targets(facts, [('a.b', 'r.a'), ('a.b', 'r.c')], ['r.a', 'r.c'])

    def test_flexible_storage_keeps_full_interval_and_wildcard_checks(self):
        facts = self.facts([
            ('header', dict(offset_bits=0, size_bytes=1)),
            ('payload[3]', dict(offset_bits=32, size_bytes=1)),
            ('payload[*]', dict(offset_bits=None, size_bytes=1)),
            ('next', dict(offset_bits=32, size_bytes=1)),
            ('later', dict(offset_bits=80, size_bytes=1))])
        facts['variables'][0]['member_definitions'] = [dict(field_path='payload', is_array=True,
            array_size=None, offset_bits=8, array_element_size_bytes=1)]
        self.access(facts, 'payload[3]')
        self.access(facts, 'payload[*]')
        self.check_targets(facts, [('a.payload[3]', 'r.next'), ('a.payload[*]', 'r.next'),
                                   ('a.payload[*]', 'r.later')], ['r.next', 'r.next', 'r.later'])

    def test_wide_disjoint_record_retains_all_accesses_and_uncertainties(self):
        facts = self.facts([(str(index), dict(offset_bits=index*32, size_bytes=4)) for index in range(5000)])
        for index in range(0, 5000, 50):
            self.access(facts, str(index))
        before = copy.deepcopy(facts)
        propagate_overlapping_members(facts)
        self.assertEqual(facts, before)


if __name__ == '__main__':
    unittest.main()
