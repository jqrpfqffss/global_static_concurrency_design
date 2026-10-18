"""External-process transport fixture, never a production review provider.

Faults happen in real child processes. In live mode successful calls go to the
real OpenCode executable; fixture answers test mechanics, not AI correctness.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--fault-plan', required=True)
    parser.add_argument('--journal', required=True)
    args, upstream_args = parser.parse_known_args()
    incoming = sys.stdin.read()
    plan = json.loads(Path(args.fault_plan).read_text(encoding='utf-8'))
    if '--file' in upstream_args:
        packet = json.loads(Path(upstream_args[upstream_args.index('--file') + 1]).read_text(encoding='utf-8'))
        fid = packet['finding_id']
        stage = 'ANALYZE'
    else:
        match = re.search(r'GS-[0-9a-f]{16}', incoming or upstream_args[-1])
        if not match:
            raise ValueError('Missing finding identity in auxiliary request')
        fid, stage = match[0], 'AUXILIARY'
    name = plan['names'][fid]
    action = plan.get('faults', {}).get(name, 'pass')
    entry = dict(time=datetime.now(timezone.utc).isoformat(), step=plan['step'],
                 finding_id=fid, variable=name, stage=stage, action=action, backend=plan['backend'])
    with Path(args.journal).open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(entry) + '\n')
    if action == 'exit':
        print('Injected nonzero process exit (17).', file=sys.stderr, flush=True)
        return 17
    if action == 'timeout':
        print(json.dumps(dict(type='step_start', injected=True)), flush=True)
        print('Injected timeout; this partial stderr must be retained.', file=sys.stderr, flush=True)
        time.sleep(30)
        return 18  # ECRA must terminate the process before reaching here.
    if action == 'provider':
        print(json.dumps(dict(type='error', error=dict(name='InjectedProviderError',
            data=dict(message='Injected provider unavailable; not a semantic verdict.')))), flush=True)
        return 0
    if action == 'bad-json':
        print('Injected unrecoverable response: no final JSON.', flush=True)
        return 0
    if plan['backend'] == 'live':
        proc = subprocess.run(plan['upstream'] + upstream_args, input=incoming,
                              text=True, encoding='utf-8', errors='replace')
        return proc.returncode
    status = plan['statuses'][name]
    answer = dict(finding_id=fid, status=status,
        reason='Deterministic external-process fixture; not an AI judgment.',
        interleaving='Fixture text for protocol verification only.',
        protection='Fixture text; no safety claim about a real firmware.',
        impact='No production assessment is made by this fixture.',
        evidence=[dict(file='Core/Src/probes.c', line=1, claim='Fixture source exists.')],
        fix='Not applicable to this transport test.', verification='Inspect the CLI call journal.',
        missing_context=['Actual IRQ activation is outside this intentionally minimal fixture.']
            if status in {'LIKELY', 'NEED_MORE_CONTEXT'} else [])
    print(json.dumps(dict(type='text', part=dict(text=json.dumps(answer)))), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
