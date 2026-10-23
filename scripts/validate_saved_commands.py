"""Exercise real report/status commands on a completed large scan.

The outer interpreter needs psutil (test-only). The interpreter under test
uses the actual packaged CLI. Complete facts are compared by streamed SHA-256,
never by loading the entire JSON in this monitor.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import traceback


def sha256(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def modules(engine):
    return {p.name: sha256(p) for p in (engine / 'ecra').glob('*.py')}


def run_command(command, folder, name):
    import psutil
    from large_stm32_scan import monitor_sample
    start = time.monotonic()
    peaks = {}
    with (folder / f'{name}.log').open('w', encoding='utf-8') as output, \
            (folder / f'{name}-memory.jsonl').open('w', encoding='utf-8') as memory:
        proc = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        root = psutil.Process(proc.pid)
        execution = dict(command=command,pid=proc.pid,created_unix=root.create_time(),
                         started=datetime.now(timezone.utc).isoformat(),status='RUNNING',exit_code=None)
        receipt = folder/f'{name}-execution.json'
        def save():
            receipt.write_text(json.dumps(execution,indent=2),encoding='utf-8')
        save()
        reserve = [bytearray(256*1024)]
        try:
            while proc.poll() is None:
                monitor_sample(root,start,peaks,memory,psutil,folder/f'{name}-monitor_errors.log',reserve=reserve)
                time.sleep(0.5)
        except Exception:
            execution.update(status='MONITOR_FAILED',traceback=traceback.format_exc(),
                             exit_status_unknown=proc.poll() is None)
            raise
        finally:
            execution.update(exit_code=proc.poll(),seconds=time.monotonic()-start,peaks=peaks,
                             measurement_gap=(folder/f'{name}-monitor_errors.log').is_file())
            if execution['status'] == 'RUNNING':
                execution['status'] = 'COMPLETE'
            save()
    return execution


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('engine', 'python', 'project', 'config', 'output-dir', 'evidence'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--wait-for', type=Path, help='Native full-scan validation receipt')
    args = parser.parse_args()
    args.evidence.mkdir(parents=True, exist_ok=False)
    result = dict(passed=False, started=datetime.now(timezone.utc).isoformat(), commands=[])
    def save():
        (args.evidence / 'acceptance.json').write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    try:
        if args.wait_for:
            while not args.wait_for.is_file():
                time.sleep(2)
            receipt = json.loads(args.wait_for.read_text(encoding='utf-8'))
            if not receipt.get('acceptance_passed'):
                raise ValueError('Native scan did not pass; saved-command test must not bless failed facts')
        out = args.output_dir
        if (out / 'scan.lock').exists():
            raise ValueError('Scan is still locked')
        validity = json.loads((out / 'result_validity.json').read_text(encoding='utf-8'))
        if validity.get('analysis_valid') is not True:
            raise ValueError('Native scan result is invalid')
        initial = modules(args.engine)
        config_hash = sha256(args.config)
        state = json.loads((out / 'scan_state.json').read_text(encoding='utf-8'))
        result['facts_before'] = sha256(out / 'facts.json')
        result['fingerprint'] = state['fingerprint']
        result['engine_files'] = initial
        result['config_sha256'] = config_hash
        if state['facts_sha256'] != result['facts_before']:
            raise ValueError('Initial saved facts hash does not match checkpoint')
        save()
        for name, expected in (('report', (0, 1, 2)), ('status', (0,))):
            command = [str(args.python), '-u', str(args.engine / 'run_ecra.py'), name,
                       '--project', str(args.project), '--config', str(args.config)]
            if name == 'status':
                command.append('--json')
            run = run_command(command, args.evidence, name)
            result['commands'].append(run)
            save()
            if run['exit_code'] not in expected:
                raise ValueError(f'{name} failed with exit {run["exit_code"]}; see complete command log')
        status = json.loads((args.evidence / 'status.log').read_text(encoding='utf-8-sig'))
        result['status'] = status
        result['facts_after'] = sha256(out / 'facts.json')
        result['checks'] = dict(facts_unchanged=result['facts_before'] == result['facts_after'],
            resumable=status.get('resumable') is True, no_lock=not status.get('scan_lock', True),
            engine_unchanged=initial == modules(args.engine), config_unchanged=config_hash == sha256(args.config))
        result['passed'] = all(result['checks'].values())
        if not result['passed']:
            raise ValueError('Saved-command integrity checks failed')
        return 0
    except BaseException:
        result['traceback'] = traceback.format_exc()
        raise
    finally:
        result['finished'] = datetime.now(timezone.utc).isoformat()
        save()


if __name__ == '__main__':
    raise SystemExit(main())
