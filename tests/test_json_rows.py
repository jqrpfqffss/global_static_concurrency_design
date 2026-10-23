import copy
import io
import json
from pathlib import Path
import tempfile
import unittest

from ecra.json_rows import RowReader, rows
from ecra.fact_parts import FactParts
from ecra.analysis import merge
from ecra.common import write_json


class JsonRowTests(unittest.TestCase):
    def test_standard_json_values_across_every_small_chunk_boundary(self):
        document = dict(words=['中文😺', 'a"\\\n\u0000z', '', 'x'*500],
                        numbers=[-12345.75, 1e100, 0, True, None],
                        nested=[dict(a=[1, dict(b='value')])], empty=[], status='PARSED', meta=dict(x=7))
        expected = [(key, item, True) for key, value in document.items() if isinstance(value, list) for item in value]
        expected.extend((key, value, False) for key, value in document.items() if not isinstance(value, list))
        for size in (1, 2, 3, 7, 31, 65536):
            for indent in (None, 2):
                with self.subTest(size=size, indent=indent):
                    actual = list(RowReader(io.StringIO(json.dumps(document, ensure_ascii=False, indent=indent)),
                                            chunk_size=size).rows())
                    self.assertEqual(actual, expected)

    def test_utf8_bom_and_no_unbounded_stream_reads(self):
        class BoundedStream(io.StringIO):
            def read(self, size=-1):
                if size < 0:
                    raise AssertionError('whole-document read')
                return super().read(size)
        document = dict(values=[dict(text='中文', number=n) for n in range(10000)])
        reader = RowReader(BoundedStream(json.dumps(document, ensure_ascii=False)), chunk_size=4096)
        count = 0
        for key, value, array in reader.rows():
            self.assertEqual((key, array, value['number']), ('values', True, count))
            self.assertLess(len(reader.buffer), 8192)
            count += 1
        self.assertEqual(count, 10000)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'facts.json'
            path.write_bytes(b'\xef\xbb\xbf'+json.dumps(dict(x=['中文']), ensure_ascii=False).encode())
            self.assertEqual(list(rows(path)), [('x', '中文', True)])

    def test_truncation_trailing_data_duplicates_and_invalid_json_fail(self):
        for text in ('{"x":[{"a":1}', '{"x":[1,]}', '{"x":1}garbage',
                     '{"x":[],"x":[]}', '{\v"x":1}', '{"x":[1e]}'):
            with self.subTest(text=text), self.assertRaises((ValueError, json.JSONDecodeError)):
                list(RowReader(io.StringIO(text), chunk_size=1).rows())

    def test_legacy_metadata_stream_keeps_weak_linkage_and_all_tables(self):
        weak = dict(functions=[dict(function_id='f', is_weak=True), dict(function_id='g', is_weak=False)],
                    accesses=[dict(function_id='f', access_id='weak'), dict(function_id='g', access_id='keep')],
                    nvic_globals=[dict(key='global', value=3)], parse_status='PARSED')
        strong = dict(functions=[dict(function_id='f', is_weak=False)], accesses=[], parse_status='PARSED')
        expected = merge(copy.deepcopy([weak, strong]))
        with tempfile.TemporaryDirectory() as folder:
            parts = FactParts()
            for index, part in enumerate((weak, strong)):
                path = Path(folder)/f'{index}.json'
                write_json(path, part, indent=None)
                # Deliberately omit weak_functions, matching persisted v1 metadata.
                parts.append_metadata(path, dict(parse_status='PARSED', strong_functions=[
                    f['function_id'] for f in part['functions'] if not f['is_weak']]))
            self.assertEqual(merge(parts), expected)
        self.assertEqual([a['access_id'] for a in expected['accesses']], ['keep'])
        self.assertEqual(len(expected['nvic_globals']), 1)


if __name__ == '__main__':
    unittest.main()
