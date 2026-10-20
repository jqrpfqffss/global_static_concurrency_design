"""Exercise the real review-failed CLI with real process failures.

No unittest.mock and no fabricated queue states. --live adds genuine read-only
OpenCode calls; the fixture backend is explicitly not a model-quality test.
"""
import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ecra.common import digest, read_json, write_json
from ecra.config import configured_project_root, load_config
from ecra.review import resolve_command, verify_receipt

ADAPTER = ROOT / 'tests/fixtures/review_failed/fault_cli.py'
STATUSES = ['CONFIRMED', 'LIKELY', 'REVIEWED_SAFE', 'FALSE_POSITIVE', 'NEED_MORE_CONTEXT']
LAUNCH = [shutil.which('py'), '-3.10'] if os.name == 'nt' and shutil.which('py') else [sys.executable]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Scenario:
    def __init__(self, base, backend, count, upstream):
        self.base, self.backend = base, backend
        self.root = (base / 'firmware').resolve()
        source = self.root / 'Core/Src/probes.c'
        source.parent.mkdir(parents=True)
        names = [f'probe_{i:02}' for i in range(count)]
        source.write_text('\n'.join([f'volatile unsigned {n};' for n in names] + [
            'void TIM2_IRQHandler(void){' + ''.join(n + '++;' for n in names) + '}',
            'int main(void){for(;;){' + ''.join(n + '++;' for n in names) + '}}', '']), encoding='utf-8')
        compiler = shutil.which('arm-none-eabi-gcc')
        if not compiler:
            compiler = str(ROOT / '.tools-cache/arm-gcc/bin/arm-none-eabi-gcc.exe')
        flags = ['-mcpu=cortex-m3', '-mthumb', '-std=c11', '-O0', '-g', '-c',
                 'Core/Src/probes.c', '-o', 'probes.o']
        build = subprocess.run([compiler, *flags], cwd=self.root, capture_output=True,
                               encoding='utf-8', errors='replace', timeout=60)
        (base / 'arm-build.log').write_text(build.stdout + build.stderr, encoding='utf-8')
        if build.returncode:
            raise RuntimeError(f'ARM build failed: {base / "arm-build.log"}')
        write_json(self.root / 'compile_commands.json', [dict(directory=str(self.root),
                   file='Core/Src/probes.c', arguments=[compiler, *flags])])
        self.plan_path, self.journal = base / 'fault-plan.json', base / 'calls.jsonl'
        self.plan = dict(backend=backend, upstream=upstream, step='scan', faults={}, names={},
                         statuses={name: STATUSES[i % len(STATUSES)] for i, name in enumerate(names)})
        write_json(self.plan_path, self.plan)
        self.config = base / 'semantics.yaml'
        self.cfg = dict(version=1, project=dict(root=str(self.root), chip='STM32F103', core='Cortex-M3'),
            analysis=dict(compile_database='compile_commands.json', include_dirs=['Core/Src'],
                          auto_system_includes=False, output_dir='.ecra', open_report=False),
            contexts=[dict(id='main', kind='MAIN', functions=['main'])],
            review=dict(enabled=False, workers=1, retries=0,
                timeout_seconds=300 if backend == 'live' else 2,
                command=[sys.executable, str(ADAPTER), '--fault-plan', str(self.plan_path),
                         '--journal', str(self.journal)]))
        write_json(self.config, self.cfg)
        (base / 'concurrency_cases.md').write_text('# Isolated CLI transport validation\n', encoding='utf-8')
        self.steps = []
        self.cli('scan', ['--no-review'])
        report = read_json(self.root / '.ecra/reports/global_static_concurrency.json')
        self.plan['names'] = {f['finding_id']: f['variable_name'] for f in report['findings']}
        if set(self.plan['names'].values()) != set(names):
            raise AssertionError('Static scan did not recover every fixture variable')
        self.static_hashes = {p: sha(self.root / '.ecra' / p)
                              for p in ('facts.json', 'input_manifest.json', 'scan_state.json')}
        self.source_sha = sha(source)

    def rows(self):
        return read_json(self.root / '.ecra/review/queue.json')

    def entries(self):
        return [json.loads(line) for line in self.journal.read_text(encoding='utf-8').splitlines()] \
            if self.journal.exists() else []

    def cli(self, label, args):
        argv = [*LAUNCH, str(ROOT / 'run_ecra.py'), *args, '--project', str(self.root),
                '--config', str(self.config)]
        env = dict(os.environ, PYTHONIOENCODING='utf-8')
        proc = subprocess.run(argv, cwd=ROOT, stdin=subprocess.DEVNULL, capture_output=True,
                              encoding='utf-8', errors='replace', env=env, timeout=1800)
        (self.base / (label + '.log')).write_text(proc.stdout + proc.stderr, encoding='utf-8')
        if proc.returncode not in {0, 1, 2}:
            raise RuntimeError(f'Unexpected CLI exit {proc.returncode}: {self.base / (label + ".log")}')
        return argv, proc

    def step(self, label, command, faults, expected=None):
        before = {r['finding_id']: r for r in self.rows()}
        selected = set(before) if command == 'review' else {
            fid for fid, r in before.items() if r['state'] == 'TECH_FAILED'}
        retained = {fid: sha(self.root / '.ecra/review' / (fid + '.result.json'))
                    for fid, row in before.items() if row['state'] == 'DONE' and fid not in selected}
        logs = {p.name: sha(p) for p in (self.root / '.ecra/review').iterdir()
                if p.is_file() and '.attempt' in p.name}
        offset = len(self.entries())
        self.plan.update(step=label, faults=faults)
        write_json(self.plan_path, self.plan)
        argv, proc = self.cli(label, [command])
        after_rows = self.rows()
        after = {r['finding_id']: r for r in after_rows}
        calls = self.entries()[offset:]
        actual = {c['finding_id'] for c in calls if c['stage'] == 'ANALYZE'}
        assert actual == selected, (label, actual, selected)
        for fid, old in before.items():
            if fid not in selected:
                assert after[fid] == old, ('unselected queue row changed', label, fid)
            elif old.get('attempt_count'):
                assert after[fid]['attempt_count'] > old['attempt_count']
        for fid, checksum in retained.items():
            assert sha(self.root / '.ecra/review' / (fid + '.result.json')) == checksum
        for name, checksum in logs.items():
            assert sha(self.root / '.ecra/review' / name) == checksum, ('old log changed', name)
        for row in after_rows:
            if row['state'] == 'DONE':
                verify_receipt(self.root, self.root / '.ecra/review', row)
            if row['state'] == 'TECH_FAILED':
                assert row.get('last_error') and row.get('last_attempt_time') and not row.get('answer')
                for a in row['attempts'][row.get('attempt_start', 0):]:
                    for kind in ('stdout', 'stderr', 'prompt'):
                        assert sha(self.root / '.ecra/review' / a[kind + '_file']) == a[kind + '_sha256']
        states = dict(Counter(r['state'] for r in after_rows))
        if expected is not None:
            assert states == expected, (label, states, expected)
        assert self.static_hashes == {p: sha(self.root / '.ecra' / p) for p in self.static_hashes}
        assert self.source_sha == sha(self.root / 'Core/Src/probes.c')
        assert not (self.root / '.ecra/scan.lock').exists()
        snapshot = self.base / ('queue-' + label + '.json')
        write_json(snapshot, after_rows)
        info = dict(step=label, command=argv, exit_code=proc.returncode,
                    selected=sorted(self.plan['names'][fid] for fid in selected),
                    states=states, calls=calls, unchanged_done=len(retained),
                    old_logs_preserved=len(logs), static_files_unchanged=True,
                    semantic_counts=dict(Counter(r.get('status') for r in after_rows if r['state'] == 'DONE')))
        self.steps.append(info)
        write_json(self.base / 'results.json', dict(backend=self.backend, steps=self.steps))
        print(f'{self.backend}/{label}: selected={len(selected)}, states={states}, calls={len(calls)}', flush=True)
        return after_rows


def fixture_validation(base):
    scenario = Scenario(base, 'fixture', 10, [])
    scenario.step('pending-only', 'review-failed', {}, {'PENDING': 10})
    scenario.step('initial', 'review', {'probe_08': 'exit', 'probe_09': 'timeout'},
                  {'DONE': 8, 'TECH_FAILED': 2})
    rows = scenario.step('retry-two', 'review-failed', {'probe_09': 'provider'},
                         {'DONE': 9, 'TECH_FAILED': 1})
    assert all(r.get('format_fix_count', 0) == 0 for r in rows)
    rows = scenario.step('retry-bad-json', 'review-failed', {'probe_09': 'bad-json'},
                         {'DONE': 9, 'TECH_FAILED': 1})
    bad = next(r for r in rows if r['state'] == 'TECH_FAILED')
    assert bad['format_fix_count'] == 2
    scenario.step('retry-last', 'review-failed', {}, {'DONE': 10})
    scenario.step('empty', 'review-failed', {'probe_00': 'exit'}, {'DONE': 10})
    return dict(passed=True, root=str(scenario.root), steps=scenario.steps,
                note='Deterministic process fixture, not model accuracy evidence.')


def live_validation(base, upstream):
    scenario = Scenario(base, 'live', 3, upstream)
    rows = scenario.step('initial', 'review', {'probe_01': 'exit', 'probe_02': 'provider'})
    if sum(r['state'] == 'DONE' for r in rows) != 1:
        return dict(passed=False, external_backend_failed=True, root=str(scenario.root),
                    errors=[r.get('error') for r in rows if r['state'] == 'TECH_FAILED'], steps=scenario.steps)
    scenario.step('retry-two', 'review-failed', {'probe_02': 'provider'},
                  {'DONE': 2, 'TECH_FAILED': 1})
    scenario.step('retry-last', 'review-failed', {}, {'DONE': 3})
    scenario.step('empty', 'review-failed', {'probe_00': 'exit'}, {'DONE': 3})
    return dict(passed=True, root=str(scenario.root), steps=scenario.steps)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Also invoke real read-only OpenCode')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    base = (args.output or ROOT / 'output' / ('review-failed-' + datetime.now().strftime('%Y%m%d-%H%M%S'))).resolve()
    base.mkdir(parents=True, exist_ok=False)
    original_root = configured_project_root()
    original_files = [ROOT / 'config/semantics.yaml', original_root / '.ecra/review/queue.json',
                      original_root / '.ecra/scan_state.json']
    original = {str(p): sha(p) for p in original_files if p.is_file()}
    result = dict(date=datetime.now().astimezone().isoformat(), python=sys.version,
                  production_scope='isolated project only', output=str(base))
    try:
        result['fixture'] = fixture_validation(base / 'fixture')
        if args.live:
            cfg, _ = load_config(original_root)
            upstream = resolve_command(cfg['review'].get('command', ['opencode']))
            result['live'] = live_validation(base / 'live', upstream)
        result['original_files_unchanged'] = all(sha(p) == checksum for p, checksum in original.items())
        assert result['original_files_unchanged']
        result['passed'] = result['fixture']['passed'] and (not args.live or result['live']['passed'])
    finally:
        write_json(base / 'validation.json', result)
    print('Evidence: ' + str(base / 'validation.json'), flush=True)
    return 0 if result.get('passed') else 2


if __name__ == '__main__':
    raise SystemExit(main())
