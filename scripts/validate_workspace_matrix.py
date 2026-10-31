"""Run real workspace integration cases and retain bounded replay evidence."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

TOOL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL))
from ecra.common import write_json
from ecra.workspace import file_hash
from tests.test_workspace import WorkspaceTests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    evidence = args.evidence.resolve()
    evidence.mkdir(parents=True, exist_ok=False)

    class RetainedTests(WorkspaceTests):
        def setUp(self):
            super().setUp()
            self.case = evidence/self._testMethodName
            self.case.mkdir()
            self.steps = []
            self.retain('initial')

        def retain(self, name):
            folder = self.case/name
            folder.mkdir(exist_ok=True)
            files = {}
            # Only the isolated fixture's own inputs/configuration are copied.
            # Skip output trees, .git internals and links; git bundle below
            # retains the committed input versions without copying the tool.
            for path in [self.config, *self.root.glob('*')]:
                if path.is_file() and not path.is_symlink() and path.stat().st_size <= 1024*1024:
                    dest = folder/path.name
                    shutil.copyfile(path, dest)
                    files[path.name] = dict(bytes=path.stat().st_size, sha256=file_hash(dest))
            self.steps.append(dict(name=name, config=str(self.config), project=str(self.root), files=files))

        def scan(self, mode='diff'):
            self.save()
            self.retain(f'before-scan-{len(self.steps)}-{mode}')
            result = super().scan(mode)
            out, report, log = result
            step = self.case/f'publication-{len(self.steps)}'
            step.mkdir()
            for name in ('facts.json', 'facts.db', 'index.html', 'project.json', 'scan_state.json', 'input_manifest.json',
                         'input_closure.json', 'migration.json', 'result_validity.json'):
                path = out/name
                if path.is_file() and path.stat().st_size <= 10*1024*1024:
                    shutil.copyfile(path, step/name)
            write_json(step/'static-report.json', report)
            (step/'console.log').write_text(log, encoding='utf-8')
            return result

        def tearDown(self):
            try:
                self.retain('final-inputs')
                result = subprocess.run(['git', '-C', str(self.repo), 'bundle', 'create',
                    str(self.case/'input-commits.bundle'), '--all'], capture_output=True)
                legacy = self.root/'.ecra'
                if legacy.is_dir():
                    for path in legacy.rglob('*'):
                        if path.is_file() and not path.is_symlink() and path.stat().st_size <= 1024*1024:
                            dest = self.case/'legacy-final'/path.relative_to(legacy)
                            dest.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copyfile(path, dest)
                write_json(self.case/'inputs.json', dict(method=self._testMethodName, steps=self.steps,
                    git_bundle_exit=result.returncode, expected='全部测试断言成立；具体断言见保留的测试源码',
                    command=[sys.executable, '-m', 'unittest', 'tests.test_workspace.WorkspaceTests.'+self._testMethodName, '-v']))
            finally:
                super().tearDown()

    shutil.copyfile(TOOL/'tests/test_workspace.py', evidence/'test_workspace.py')
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(RetainedTests)
    with (evidence/'unittest.log').open('w', encoding='utf-8') as stream:
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    failures = {case._testMethodName: text for case, text in result.failures + result.errors}
    names = unittest.defaultTestLoader.getTestCaseNames(RetainedTests)
    write_json(evidence/'acceptance.json', dict(complete=result.wasSuccessful(), tests=result.testsRun,
        failures=len(result.failures), errors=len(result.errors), skipped=len(result.skipped),
        cases={name: dict(actual='FAILED' if name in failures else 'PASSED', evidence=str(evidence/name),
                         error=failures.get(name)) for name in names}))
    raise SystemExit(0 if result.wasSuccessful() else 1)


if __name__ == '__main__':
    main()
