"""The complete schema must seed CPython's shared keys before row insertion."""
import json
import sys
import unittest

from ecra.json_rows import RecordDicts


class SeededRecordTests(unittest.TestCase):
    def test_medium_and_large_plain_records_share_schema_keys(self):
        factory = RecordDicts()
        for count in (6, 12, 20, 24, 40):
            with self.subTest(fields=count):
                keys = tuple(f'field{i}' for i in range(count))
                rows = []
                for number in range(50):
                    row = factory(keys)
                    for key in keys:
                        row[key] = number
                    rows.append(row)
                self.assertIs(type(rows[-1]), dict)
                self.assertEqual(tuple(rows[-1]), keys)
                expected = dict.fromkeys(keys, 49)
                self.assertEqual(json.dumps(rows[-1]), json.dumps(expected))
                if sys.implementation.name == 'cpython' and sys.version_info[:2] == (3, 10):
                    self.assertLess(sys.getsizeof(rows[-1]), sys.getsizeof(expected))
                rows[0][keys[0]] = 'independent'
                self.assertEqual(rows[-1][keys[0]], 49)

    def test_special_attribute_names_are_ordinary_independent_json_keys(self):
        factory = RecordDicts()
        source = {'__dict__': 'value', '__class__': True, '__weakref__': [], '/field': None, '': 1}
        first, second = factory(tuple(source)), factory(tuple(source))
        for key, value in source.items():
            first[key] = second[key] = value
        self.assertIs(type(first), dict)
        self.assertEqual(list(first.items()), list(source.items()))
        first['__dict__'] = 'changed'
        self.assertEqual(second['__dict__'], 'value')
