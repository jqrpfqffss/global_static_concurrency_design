"""Parse the final actual unittest summary, including failed-run skip counts.

This is accounting only: a release must also check the process exit code,
expected test/skip counts and frozen-source hashes. Never infer a pass merely
from the number of discovered tests or an earlier OK line.
"""
import re


def parse_summary(log):
    runs=list(re.finditer(r'^Ran (\d+) tests? in ([\d.]+)s\s*$',log,re.MULTILINE))
    if not runs:raise ValueError('Missing complete unittest test-count summary')
    run=runs[-1];tail=log[run.end():]
    verdicts=list(re.finditer(r'^(OK|FAILED)(?: \(([^\r\n)]*)\))?\s*$',tail,re.MULTILINE))
    if len(verdicts)!=1:raise ValueError('Missing or ambiguous final unittest verdict')
    verdict=verdicts[0];counts=dict(failures=0,errors=0,skipped=0,expected_failures=0,unexpected_successes=0)
    keys={'failures':'failures','errors':'errors','skipped':'skipped','expected failures':'expected_failures','unexpected successes':'unexpected_successes'}
    if verdict[2]:
        for field in verdict[2].split(', '):
            name,separator,value=field.partition('=')
            if not separator or name not in keys or not value.isdecimal():raise ValueError('Unrecognized unittest summary count')
            key=keys.pop(name);counts[key]=int(value)
    tests=int(run[1]);classified=sum(counts.values())
    if classified>tests:raise ValueError('Unittest terminal counts exceed run count; cannot derive successful cases')
    success=verdict[1]=='OK'
    if success and (counts['failures'] or counts['errors'] or counts['unexpected_successes']):raise ValueError('Inconsistent unittest OK summary')
    if not success and not (counts['failures'] or counts['errors'] or counts['unexpected_successes']):raise ValueError('FAILED summary lacks failure counts')
    return dict(summary_ok=success,tests=tests,passed_tests=tests-classified,seconds=float(run[2]),**counts)
