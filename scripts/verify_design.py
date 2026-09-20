"""Run reproducible verification and retain logs plus all twenty demo reports."""
import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--all', action='store_true', help='run the entire test suite')
    parser.add_argument('--out', type=Path, default=ROOT/'output/design-acceptance')
    args = parser.parse_args()
    destination = args.out.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    os.environ['ECRA_ACCEPTANCE_OUT'] = str(destination)
    suite = (unittest.defaultTestLoader.discover(str(ROOT/'tests')) if args.all else
             unittest.defaultTestLoader.loadTestsFromName('tests.test_design_acceptance'))
    log = io.StringIO()
    start = time.time()
    original = Path.cwd()
    try:
        with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    finally:
        os.chdir(original)
    summary = dict(success=result.wasSuccessful(), tests=result.testsRun,
        failures=len(result.failures), errors=len(result.errors),
        skipped=[dict(test=t.id(), reason=reason) for t,reason in result.skipped],
        elapsed_seconds=round(time.time()-start, 3),
        command='python scripts/verify_design.py' + (' --all' if args.all else ''),
        scenarios={case: dict(index=str(destination/case/'.ecra/index.html'),
                             review=str(destination/case/'.ecra/opencode_review.html'))
                   for case in ('D%02d'%i for i in range(1,21))})
    (destination/'verification.log').write_text(log.getvalue(), encoding='utf-8')
    (destination/'verification.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    for test, trace in result.failures + result.errors:
        print(test.id(), trace)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
