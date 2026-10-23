import contextlib
import io
from pathlib import Path
from types import SimpleNamespace
import unittest

import test_ecra
from ecra.cli import run
from ecra.common import read_json, write_json
from scripts.large_stm32_scan import validate


class LargeScanAcceptanceTests(unittest.TestCase):
    setUp = test_ecra.ProjectTest.setUp
    project = test_ecra.ProjectTest.project

    def test_failed_exit_invalid_result_or_missing_evidence_cannot_pass_acceptance(self):
        self.project({'a.c': 'int shared;void ISR(void){shared++;}',
                      'b.c': 'extern int shared;void Task(void){shared++;}'})
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run(self.root, no_review=True), 2)
        out = self.root/'.ecra'
        evidence = self.root/'acceptance'
        evidence.mkdir()
        args = SimpleNamespace(project=self.root, config=out/'semantics.yaml', evidence=evidence, min_units=2)
        write_json(evidence/'execution.json', dict(exit_code=2))
        self.assertTrue(validate(args)['acceptance_passed'])
        write_json(evidence/'execution.json', dict(exit_code=3))
        self.assertFalse(validate(args)['acceptance_passed'])
        write_json(evidence/'execution.json', dict(exit_code=2))
        validity = read_json(out/'result_validity.json')
        write_json(out/'result_validity.json', dict(validity, analysis_valid=False))
        self.assertFalse(validate(args)['acceptance_passed'])
        write_json(out/'result_validity.json', validity)
        completion_file = out/'diagnostics/completion.json'
        completion = read_json(completion_file)
        write_json(completion_file, dict(completion, fingerprint='different'))
        self.assertFalse(validate(args)['acceptance_passed'])
        write_json(completion_file, dict(completion, variable_accountability=dict(
            completion['variable_accountability'], missing=1)))
        self.assertFalse(validate(args)['acceptance_passed'])
        write_json(completion_file, completion)
        self.assertTrue(validate(args)['acceptance_passed'])


if __name__ == '__main__':
    unittest.main()
