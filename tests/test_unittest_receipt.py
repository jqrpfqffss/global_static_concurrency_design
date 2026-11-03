import unittest

from scripts.unittest_receipt import parse_summary


class UnittestReceiptTests(unittest.TestCase):
    def test_success_and_skips_are_reported_as_separate_counts(self):
        result=parse_summary('Ran 1376 tests in 20.5s\n\nOK (skipped=2)\n')
        self.assertTrue(result['summary_ok']);self.assertEqual(result['tests'],1376)
        self.assertEqual((result['passed_tests'],result['skipped'],result['failures']),(1374,2,0))
        self.assertEqual(parse_summary('Ran 1 test in 0.001s\nOK\n')['passed_tests'],1)

    def test_failed_run_retains_skip_error_and_expected_failure_counts(self):
        result=parse_summary('Ran 3 tests in 1.0s\nOK\nnoise\nRan 1371 tests in 2009.813s\n\nFAILED (failures=1, skipped=2)\n')
        self.assertFalse(result['summary_ok']);self.assertEqual((result['tests'],result['passed_tests'],result['failures'],result['skipped']),(1371,1368,1,2))
        result=parse_summary('Ran 9 tests in 2.0s\nFAILED (failures=1, errors=1, skipped=2, expected failures=1, unexpected successes=1)\n')
        self.assertEqual(result['passed_tests'],3);self.assertEqual(result['unexpected_successes'],1)

    def test_incomplete_ambiguous_or_inconsistent_log_cannot_be_a_release_receipt(self):
        for raw in ['OK','Ran 1 test in 0.1s\n','Ran 1 test in 0.1s\nOK\nFAILED (failures=1)',
            'Ran 1 test in 0.1s\nOK (skipped=2)','Ran 1 test in 0.1s\nFAILED',
            'Ran 1 test in 0.1s\nOK (errors=1)','Ran 1 test in 0.1s\nOK (future=1)',
            'Ran 2 tests in 0.1s\nOK (skipped=1, skipped=1)']:
            with self.subTest(raw=raw),self.assertRaises(ValueError):parse_summary(raw)


if __name__=='__main__':unittest.main()
