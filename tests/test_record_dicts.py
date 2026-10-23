import json
import unittest

from ecra.fact_parts import FactParts
from ecra.json_rows import RecordDicts


class RecordDictTests(unittest.TestCase):
    def test_plain_dict_values_order_and_json_are_exact(self):
        factory = RecordDicts()
        inputs = [{}, {'op': 'addr', 'id': 'obj:全局'},
                  {'size': True, 'values': [None, 1, 'x']},
                  {'values': [None, 1, 'x'], 'size': 1},
                  {str(i): i for i in range(40)},
                  {'__dict__': 'ordinary JSON field', '/path': None}]
        for source in inputs * 50:
            with self.subTest(keys=list(source)):
                result = factory(tuple(source))
                for key, value in source.items():
                    result[key] = value
                self.assertIs(type(result), dict)
                self.assertEqual(list(result.items()), list(source.items()))
                self.assertEqual(json.dumps(result, ensure_ascii=False),
                                 json.dumps(source, ensure_ascii=False))

    def test_record_mutations_do_not_change_other_records(self):
        factory = RecordDicts()
        first, second = factory(('a', 'b')), factory(('a', 'b'))
        first['a'], first['b'] = 1, 2
        second['a'], second['b'] = 3, 4
        first.pop('a')
        first['extra'] = 5
        self.assertEqual(second, dict(a=3, b=4))
        second.clear()
        self.assertEqual(first, dict(b=2, extra=5))

    def test_schema_cache_is_bounded_without_retaining_record_values(self):
        factory = RecordDicts(maxsize=2)
        records = []
        for i in range(100):
            record = factory((f'field{i}',))
            record[f'field{i}'] = [i]
            records.append(record)
        self.assertEqual(factory.cache_info().currsize, 2)
        self.assertEqual([list(row.values()) for row in records], [[[i]] for i in range(100)])

    def test_real_fact_hook_keeps_complete_schema_and_nested_values(self):
        parts = FactParts()
        rows = [dict(location=f'local:{i}', function_id='fn', paths=['', '/a/b'],
                     array_size=8, array_extents={'': 8}) for i in range(2000)]
        source = json.dumps(rows, ensure_ascii=False)
        actual = json.loads(source, object_hook=parts._object)
        self.assertEqual(actual, rows)
        self.assertEqual(json.dumps(actual, ensure_ascii=False), source)
        actual[0]['function_id'] = 'another'
        actual[0]['array_extents'][''] = 9
        self.assertEqual(actual[-1]['function_id'], 'fn')
        self.assertEqual(actual[-1]['array_extents'][''], 8)


if __name__ == '__main__':
    unittest.main()
