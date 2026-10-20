"""Run the configured real firmware and audit genuine OpenCode concurrency receipts."""
import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ecra.cli import file_hashes
from ecra.common import read_json, write_json
from ecra.config import SEMANTICS_FILE, configured_project_root, load_config
from ecra.review import verify_receipt
from ecra.review_integrity import assert_review_archive, assert_review_integrity
from ecra.workflow import checked_scan, output_path


def source_hashes(root, out, cfg):
    build = (root / cfg['analysis'].get('cmake', {}).get('build_dir', 'build')).resolve()
    return {name: checksum for name, checksum in file_hashes(root, out).items()
            if not (root / name).resolve().is_relative_to(build)
            and not set(Path(name).parts) & {'build', 'Debug', 'Release'}}


def audit_intervals(rows, started_after):
    calls, variables = [], []
    for row in rows:
        attempts = row.get('attempts', [])[row.get('attempt_start', 0):]
        current = [dict(finding_id=row['finding_id'], stage=a['stage'],
                        started=a['started'], finished=a['finished'], state=a['state'])
                   for a in attempts if a.get('started') and a.get('finished')
                   and datetime.fromisoformat(a['started']) >= started_after]
        calls.extend(current)
        analyses = [a for a in current if a['stage'] == 'ANALYZE']
        if analyses:
            variables.append(dict(finding_id=row['finding_id'],
                                  started=min(a['started'] for a in analyses),
                                  finished=max(a['finished'] for a in current)))
    events = [(datetime.fromisoformat(c[k]), delta) for c in calls
              for k, delta in (('started', 1), ('finished', -1))]
    active = peak = 0
    for _, delta in sorted(events):
        active += delta
        peak = max(peak, active)
    variables.sort(key=lambda v: v['started'])
    refills = []
    for index, variable in enumerate(variables):
        unfinished = [old['finding_id'] for old in variables[:index]
                      if old['finished'] > variable['started']]
        if index and unfinished:
            refills.append(dict(finding_id=variable['finding_id'], started=variable['started'],
                                earlier_items_still_running=unfinished))
    return dict(peak_calls=peak, calls=calls, variables=variables, overlapping_starts=refills)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=SEMANTICS_FILE)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--mode', choices=('run', 'review', 'review-failed'), default='run')
    args = parser.parse_args()
    config = args.config.resolve()
    root = configured_project_root(config)
    cfg, config = load_config(root, config)
    out = output_path(root, cfg)
    now = datetime.now(timezone(timedelta(hours=8)))
    evidence = (args.output or ROOT / 'output' / ('review-workers-' + now.strftime('%Y%m%d-%H%M%S'))).resolve()
    evidence.mkdir(parents=True, exist_ok=False)
    before = source_hashes(root, out, cfg)
    config_before = config.read_bytes()
    write_json(evidence / 'source-before.json', before)
    command = [sys.executable, '-u', str(ROOT / 'run_ecra.py'), args.mode, '--config', str(config)]
    result = dict(started=now.isoformat(), project=str(root), config=str(config),
                  workers=cfg['review'].get('workers', 1), command=command,
                  evidence=str(evidence), passed=False)
    write_json(evidence / 'validation.json', result)
    try:
        env = dict(os.environ, PYTHONIOENCODING='utf-8')
        with (evidence / 'run.log').open('w', encoding='utf-8') as log:
            with subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  encoding='utf-8', errors='replace', env=env) as proc:
                for line in proc.stdout:
                    print(line, end='', flush=True)
                    log.write(line)
                    log.flush()
                result['exit_code'] = proc.wait()
        if result['exit_code'] not in {0, 1, 2}:
            raise RuntimeError('CLI did not finish normally')
        facts, report, state = checked_scan(root, out, cfg, config)
        rows = read_json(out / 'review/queue.json')
        integrity = assert_review_integrity(report, rows, require_terminal=True)
        assert_review_archive(report, rows, out / 'review')
        verified = 0
        for row in rows:
            if row['state'] == 'DONE':
                verify_receipt(root, out / 'review', row, summary_config=cfg['review']['summary'])
                verified += 1
        timeline = audit_intervals(rows, now)
        workers = result['workers']
        later_refills = [v for v in timeline['overlapping_starts']
                        if v['finding_id'] in {v['finding_id'] for v in timeline['variables'][workers:]}]
        after = source_hashes(root, out, cfg)
        write_json(evidence / 'source-after.json', after)
        result.update(integrity=integrity, verified_receipts=verified,
                      semantic_counts=dict(Counter(r.get('status') for r in rows if r['state'] == 'DONE')),
                      analysis_status=report['analysis_status'], scan_fingerprint=state['fingerprint'],
                      source_files=len(before), sources_unchanged=before == after,
                      config_unchanged=config.read_bytes() == config_before,
                      scan_lock_removed=not (out / 'scan.lock').exists(),
                      peak_calls=timeline['peak_calls'], primary_review_items=len(timeline['variables']),
                      refill_while_earlier_item_running=later_refills,
                      errors=[dict(finding_id=r['finding_id'], error=r.get('error'))
                              for r in rows if r['state'] != 'DONE'])
        write_json(evidence / 'timeline.json', timeline)
        write_json(evidence / 'queue.json', rows)
        assert integrity['all_done'], 'Some reviews did not finish successfully'
        assert result['sources_unchanged'], 'Firmware inputs changed'
        assert result['config_unchanged'], 'Validation changed the user configuration'
        assert result['scan_lock_removed'], 'Scan lock was not cleaned up'
        assert timeline['peak_calls'] <= workers, 'Worker concurrency exceeded'
        if len(timeline['variables']) > workers > 1:
            assert timeline['peak_calls'] == workers, 'Real calls did not reach configured concurrency'
            assert later_refills, 'No live evidence of a refill while an earlier item was running'
        result['passed'] = True
    except Exception as exc:
        result['error'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        result['finished'] = datetime.now(timezone(timedelta(hours=8))).isoformat()
        write_json(evidence / 'validation.json', result)
        print('Validation evidence: ' + str(evidence / 'validation.json'), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
