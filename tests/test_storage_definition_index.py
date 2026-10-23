"""Storage-layout sharing preserves the old bounds/prefix query relation."""
import copy
import random
import unittest

from ecra.points_to import storage_definition_index


def original_index(rows, pruned):
    definitions = {}
    for row in rows:
        if row.get('function_id') in pruned:
            continue
        key = row['location']
        if key not in definitions:
            definitions[key] = dict(row, paths=set(row['paths']), array_extents=dict(row.get('array_extents', {})))
        else:
            current = definitions[key]
            current['paths'].update(row['paths'])
            for prefix, size in row.get('array_extents', {}).items():
                if size is not None or prefix not in current['array_extents']:
                    current['array_extents'][prefix] = size
            if row.get('array_size') is not None:
                current['array_size'] = row['array_size']
    return {key: dict(paths={path[:end] for path in row['paths']
                for end in [len(path)] + [i for i, ch in enumerate(path) if ch == '/' and i]},
            array_extents=row['array_extents'], array_size=row.get('array_size'))
            for key, row in definitions.items()}


class StorageDefinitionIndexTests(unittest.TestCase):
    def test_declarations_bounds_and_all_path_prefixes_match_original(self):
        rng = random.Random(20261022)
        paths = ['', '/a', '/a/b', '/[*]/x', '/field/[1]/x', '/field/[2]/nested/value']
        rows = [dict(location='local:'+str(rng.randrange(40)), function_id=rng.choice(['live', 'dead', None]),
                     paths=rng.sample(paths, rng.randrange(1, 5)), array_size=rng.choice([None, 0, 1, 8]),
                     array_extents={key: rng.choice([None, 0, 2, 16]) for key in rng.sample(['', '/field', '/a'], 2)})
                for _ in range(600)]
        before = copy.deepcopy(rows)
        expected = original_index(rows, {'dead'})
        actual = storage_definition_index(rows, {'dead'})
        self.assertEqual(expected, {key: dict(value) for key, value in actual.items()})
        self.assertEqual(rows, before)

    def test_equal_layouts_share_immutable_projection_without_sharing_locations(self):
        rows = [dict(location=f'local:{i}', function_id=f'f{i}', paths=['', '/a/b'],
                     array_size=4, array_extents={'': 4, '/a': None}) for i in range(2000)]
        result = storage_definition_index(rows)
        self.assertEqual(len(result), len(rows))
        self.assertTrue(all(value is result['local:0'] for value in result.values()))
        self.assertEqual(result['local:0']['paths'], {'', '/a', '/a/b'})
        with self.assertRaises(TypeError):
            result['local:0']['array_extents'][''] = 2
        with self.assertRaises(TypeError):
            result['local:0']['array_size'] = 2
        self.assertEqual(rows[-1]['array_size'], 4)

    def test_known_definition_survives_later_incomplete_extern(self):
        rows = [dict(location='obj:a', paths=['/[0]/field'], array_size=8, array_extents={'': 8}),
                dict(location='obj:a', paths=['/extra'], array_size=None, array_extents={'': None})]
        value = storage_definition_index(rows)['obj:a']
        self.assertEqual(value['array_size'], 8)
        self.assertEqual(value['array_extents'][''], 8)
        self.assertEqual(value['paths'], {'/[0]', '/[0]/field', '/extra'})

    def test_scalar_types_are_not_coalesced_by_layout_cache(self):
        rows = [dict(location='a', paths=[''], array_size=True, array_extents={'': True}),
                dict(location='b', paths=[''], array_size=1, array_extents={'': 1})]
        values = storage_definition_index(rows)
        self.assertIs(values['a']['array_size'], True)
        self.assertIs(type(values['b']['array_size']), int)
        self.assertIsNot(values['a'], values['b'])


if __name__ == '__main__':
    unittest.main()
