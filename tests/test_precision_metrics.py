"""Build and inventory review rates use separate, explicit denominators."""

import json
import tempfile
import unittest
from pathlib import Path

from scripts.preopencode_benchmark_summary import summarize


class PrecisionMetricsTests(unittest.TestCase):
    def test_benchmark_summary_keeps_out_of_build_inventory(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            rows = [
                dict(symbol_id='safe', kind='GLOBAL', static_classification='SAFE_PROVEN'),
                dict(symbol_id='suspect', kind='GLOBAL', static_classification='SUSPECT'),
                dict(symbol_id='inactive', kind='GLOBAL', static_classification='OUT_OF_BUILD'),
            ]
            (root / 'classification-index.json').write_text(json.dumps(rows), encoding='utf-8')
            result = summarize(root)
            self.assertEqual(result['rr_build'],
                             dict(numerator=1, denominator=2, percent=50.0))
            self.assertEqual(result['rr_all'],
                             dict(numerator=2, denominator=3, percent=66.67))
            self.assertEqual(result['variant_inventory'], 1)


if __name__ == '__main__':
    unittest.main()
