import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from scripts.compare_extracted_facts import fingerprint


class RawFactComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'facts.json'
        self.index = sqlite3.connect(':memory:')
        self.addCleanup(self.index.close)
        self.index.execute('CREATE TABLE hashes(table_name TEXT,digest BLOB)')

    def facts(self, value, normalize=False):
        self.path.write_text(json.dumps(value), encoding='utf-8')
        return fingerprint(self.path, self.index, normalize)

    def test_only_top_level_row_order_is_normalized(self):
        a, b = dict(symbol_id='a', route=['first', 'second']), dict(symbol_id='b', route=[])
        first = self.facts(dict(accesses=[a, b]))
        second = self.facts(dict(accesses=[b, a]))
        self.assertEqual(first['tables'], second['tables'])
        changed = self.facts(dict(accesses=[dict(a, route=['second', 'first']), b]))
        self.assertNotEqual(first['tables'], changed['tables'])

    def test_duplicate_rows_are_not_discarded(self):
        row = dict(symbol_id='a', mode='WRITE')
        first = self.facts(dict(accesses=[row, row]))
        second = self.facts(dict(accesses=[row]))
        self.assertEqual(first['tables']['accesses']['count'], 2)
        self.assertNotEqual(first['tables'], second['tables'])

    def test_parse_state_normalization_is_explicit_and_still_reports_both_states(self):
        row = dict(symbol_id='a', type='int', parse_status='PARTIAL')
        before = dict(variables=[row], parse_status='PARTIAL', diagnostics=[dict(severity=3, message='unsupported option')])
        after = dict(variables=[dict(row, parse_status='PARSED')], parse_status='PARSED', diagnostics=[])
        self.assertNotEqual(self.facts(before)['tables'], self.facts(after)['tables'])
        first, second = self.facts(before, True), self.facts(after, True)
        self.assertEqual(first['tables'], second['tables'])
        self.assertNotEqual(first['parse_status'], second['parse_status'])
        self.assertNotEqual(first['diagnostics'], second['diagnostics'])
        self.assertNotEqual(first['variable_parse_status'], second['variable_parse_status'])

    def test_variable_type_and_access_modes_cannot_be_normalized_away(self):
        first = self.facts(dict(variables=[dict(symbol_id='a', type='int')],
                                accesses=[dict(symbol_id='a', mode='READ')]), True)
        second = self.facts(dict(variables=[dict(symbol_id='a', type='long')],
                                 accesses=[dict(symbol_id='a', mode='WRITE')]), True)
        self.assertNotEqual(first['tables']['variables'], second['tables']['variables'])
        self.assertNotEqual(first['tables']['accesses'], second['tables']['accesses'])


if __name__ == '__main__':
    unittest.main()
