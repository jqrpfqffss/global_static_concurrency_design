"""Replay evidence must distinguish ordered data and refuse stale outputs."""
from pathlib import Path
import tempfile
import unittest

from scripts.benchmark_fact_merge import file_identity, ordered_digest


class MergeMeasurementTests(unittest.TestCase):
    def test_complete_order_type_and_duplicate_changes_cannot_share_a_digest(self):
        cases = [True, 1, 1.0, -0.0, 0.0, ['a', 'b'], ['b', 'a'], ['a', 'a', 'b'],
                 {'a': 1, 'b': 2}, {'b': 2, 'a': 1}, '\ud800', '中文']
        self.assertEqual(len({ordered_digest(value) for value in cases}), len(cases))

    def test_input_identity_detects_same_length_byte_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'worker.json'
            path.write_bytes(b'{"value":1}')
            before = file_identity(path)
            path.write_bytes(b'{"value":2}')
            after = file_identity(path)
            self.assertEqual(before['bytes'], after['bytes'])
            self.assertNotEqual(before['sha256'], after['sha256'])


if __name__ == '__main__':
    unittest.main()
