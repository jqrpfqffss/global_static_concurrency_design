"""Repeatable external full-scan harness (psutil is a test-only dependency).

Use --engine to run an archived baseline without changing its analysis code.
No source/scope filtering is performed. Evidence is kept outside the firmware.
"""
import argparse
import cProfile
import ctypes
from datetime import datetime, timezone
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sqlite3
import struct
import sys
import threading
import time
import traceback
import tracemalloc


def dump(path, value):
    with Path(path).open('w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def system_commit():
    class Performance(ctypes.Structure):
        _fields_ = [('cb', ctypes.c_ulong), *[(name, ctypes.c_size_t) for name in
            ('CommitTotal', 'CommitLimit', 'CommitPeak', 'PhysicalTotal', 'PhysicalAvailable',
             'SystemCache', 'KernelTotal', 'KernelPaged', 'KernelNonpaged', 'PageSize')],
            ('HandleCount', ctypes.c_ulong), ('ProcessCount', ctypes.c_ulong), ('ThreadCount', ctypes.c_ulong)]
    info = Performance()
    info.cb = ctypes.sizeof(info)
    if not ctypes.windll.psapi.GetPerformanceInfo(ctypes.byref(info), info.cb):
        raise ctypes.WinError()
    return {name: getattr(info, name)*info.PageSize for name in ('CommitTotal', 'CommitLimit', 'CommitPeak')}


def inside(args):
    sys.path.insert(0, str(args.engine.resolve()))
    import importlib.metadata
    dump(args.evidence/'interpreter.json',dict(executable=sys.executable,version=sys.version,
         pointer_bits=struct.calcsize('P')*8,libclang=importlib.metadata.version('libclang'),
         pyyaml=importlib.metadata.version('PyYAML')))
    from ecra import cli
    original_hashes = cli.file_hashes
    calls = 0
    def hashes(*a, **kw):
        nonlocal calls
        result = original_hashes(*a, **kw)
        calls += 1
        dump(args.evidence / f'hashes-{calls}.json', result)
        return result
    cli.file_hashes = hashes
    if not args.no_profile:
        tracemalloc.start(1)
    gate_passed = False
    def analysis_gate():
        nonlocal gate_passed
        if gate_passed or args.analysis_after_acceptance is None:
            return
        begin = time.monotonic()
        dump(args.evidence/'analysis-resource-wait.json',dict(status='WAITING',
             acceptance=str(args.analysis_after_acceptance),reason='Serialize memory-intensive phases of independent experiments'))
        print('资源调度：完整提取已保存，等待指定前置任务完成并释放内存后进入重型分析。',flush=True)
        while True:
            try:
                receipt = json.loads(args.analysis_after_acceptance.read_text(encoding='utf-8-sig'))
            except (FileNotFoundError,json.JSONDecodeError):
                receipt = {}
            if receipt.get('complete'):
                break
            if any(not row['validation'].get('acceptance_passed') for row in receipt.get('runs', [])):
                raise RuntimeError('Resource gate stopped: prerequisite acceptance failed; retained full TU facts are diagnostic only')
            time.sleep(3)
        gate_passed = True
        dump(args.evidence/'analysis-resource-wait.json',dict(status='COMPLETE',seconds=time.monotonic()-begin,
             acceptance=str(args.analysis_after_acceptance)))
    def wrap(name):
        original = getattr(cli, name)
        def measured(*a, **kw):
            if name == 'merge':
                analysis_gate()
            begin = time.monotonic()
            profile = None if args.no_cprofile else cProfile.Profile()
            if profile:
                profile.enable()
            try:
                return original(*a, **kw)
            except BaseException:
                (args.evidence / f'{name}-exception.log').write_text(traceback.format_exc(), encoding='utf-8')
                raise
            finally:
                if profile:
                    profile.disable()
                    profile.dump_stats(str(args.evidence / f'{name}.prof'))
                data = dict(seconds=time.monotonic()-begin,cprofile_enabled=bool(profile))
                if tracemalloc.is_tracing():
                    snap = tracemalloc.take_snapshot()
                    data.update(traced_bytes=tracemalloc.get_traced_memory(),
                        top=[dict(trace=str(stat.traceback), bytes=stat.size, count=stat.count)
                             for stat in snap.statistics('lineno')[:40]])
                dump(args.evidence / f'{name}-profile.json', data)
        setattr(cli, name, measured)
    for name in ('merge', 'analyze', 'generate'):
        wrap(name)
    return cli.main(['run', '--project', str(args.project), '--config', str(args.config), '--no-review'])


def validate(args):
    import yaml
    from contextlib import closing
    cfg = yaml.safe_load(args.config.read_text(encoding='utf-8-sig'))
    from ecra.workflow import output_path
    out = output_path(args.project, cfg)
    result = dict(all_scope=True, checks={}, output=str(out))
    for key in ('include_dirs','exclude_dirs','exclude_files','exclude'):
        if cfg['analysis'].get(key):
            result['all_scope'] = False
    required = ['facts.json','facts.db','index.html','reports/global_static_concurrency.json','input_manifest.json','scan_state.json']
    result['checks']['artifacts'] = all((out/p).is_file() and (out/p).stat().st_size for p in required)
    state = json.loads((out/'run.json').read_text(encoding='utf-8')) if (out/'run.json').exists() else {}
    result['state'] = state
    result['checks']['process_completed'] = state.get('state') in {'INCOMPLETE','REVIEW_COMPLETE'}
    execution_file = args.evidence/'execution.json'
    execution = json.loads(execution_file.read_text(encoding='utf-8')) if execution_file.is_file() else state
    result['checks']['exit_status'] = execution.get('exit_code') in {0, 1, 2}
    validity_file = out/'result_validity.json'
    validity = json.loads(validity_file.read_text(encoding='utf-8')) if validity_file.is_file() else {}
    result['checks']['result_valid'] = validity.get('analysis_valid') is True
    if (out/'diagnostics/completion.json').is_file():
        completion = json.loads((out/'diagnostics/completion.json').read_text(encoding='utf-8'))
        result['completion'] = completion
        result['checks']['completion_valid'] = completion.get('analysis_valid') is True
        result['checks']['fingerprint'] = (bool(completion.get('fingerprint')) and
            completion['fingerprint'] == validity.get('fingerprint') == state.get('fingerprint'))
        accountability = completion.get('variable_accountability') or {}
        result['checks']['variable_accountability'] = (accountability.get('missing') == 0 and
            accountability.get('duplicate_ids') == 0)
        db_path = args.project/cfg['analysis']['compile_database']
        entries = json.loads(db_path.read_text(encoding='utf-8-sig'))
        expected = sum(Path(entry['file']).suffix.lower() in {'.c','.cc','.cpp','.cxx'} for entry in entries)
        result['expected_translation_units'] = expected
        result['checks']['all_units'] = completion['translation_units_total'] == expected and expected >= args.min_units
        total = completion['translation_units_total']
        result['parse_rates'] = {key:round(100*completion[key]/total,3) for key in ('parsed','partial','failed')}
        result['checks']['coverage_accounting'] = sum(completion[key] for key in ('parsed','partial','failed')) == total
        result['checks']['no_failed_units'] = completion['failed'] == 0
        result['checks']['snapshot'] = completion['snapshot_status'] == 'VERIFIED'
    else:
        result['checks']['completion_receipt'] = False
    if result['checks']['process_completed'] and (out/'facts.db').is_file():
        with closing(sqlite3.connect(f"{(out/'facts.db').resolve().as_uri()}?mode=ro",uri=True)) as connection:
            result['checks']['sqlite_integrity'] = connection.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            result['sqlite_counts'] = {table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] for table in tables}
        with (out/'index.html').open(encoding='utf-8') as stream:
            html = stream.read(65536)
        result['checks']['html'] = '<html' in html.lower() and '不能使用旧结论' not in html
    result['acceptance_passed'] = result['all_scope'] and all(result['checks'].values())
    responses = [path for path in (out/'workers').glob('*.response.json') if '.dependencies.' not in path.name]
    result['extraction_json'] = dict(count=len(responses),bytes=sum(p.stat().st_size for p in responses),
                                   max_bytes=max((p.stat().st_size for p in responses),default=0))
    dump(args.evidence/'validation.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--no-profile', action='store_true', help='Skip tracemalloc; retain cProfile and OS measurements')
    parser.add_argument('--no-cprofile', action='store_true', help='Record stage/OS metrics without cProfile overhead')
    parser.add_argument('--analysis-after-acceptance',type=Path,help='Queue heavy phases after an acceptance/resource completion receipt')
    parser.add_argument('--python', type=Path, default=Path(sys.executable), help='Interpreter under test (outer monitor keeps psutil)')
    parser.add_argument('--min-units', type=int, default=226)
    parser.add_argument('--validate-only', action='store_true')
    parser.add_argument('--inside', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    args.evidence.mkdir(parents=True, exist_ok=True)
    if args.validate_only:
        print(json.dumps(validate(args),ensure_ascii=False))
        return 0
    if args.inside:
        return inside(args)
    import psutil
    command = [str(args.python), '-u', str(Path(__file__).resolve()), '--inside', '--engine', str(args.engine),
               '--project', str(args.project), '--config', str(args.config), '--evidence', str(args.evidence)]
    if args.no_profile:
        command.append('--no-profile')
    if args.no_cprofile:
        command.append('--no-cprofile')
    if args.analysis_after_acceptance is not None:
        command.extend(['--analysis-after-acceptance',str(args.analysis_after_acceptance)])
    start = time.monotonic()
    peaks = {}
    reserve = [bytearray(256*1024)]
    with (args.evidence / 'console.log').open('w', encoding='utf-8') as log, \
            (args.evidence / 'memory.jsonl').open('w', encoding='utf-8') as memory:
        proc = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        root = psutil.Process(proc.pid)
        dump(args.evidence/'execution-start.json',dict(command=command,pid=proc.pid,
             created_unix=root.create_time(),started=datetime.now(timezone.utc).isoformat(),
             harness_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()))
        while proc.poll() is None:
            monitor_sample(root, start, peaks, memory, psutil, args.evidence/'monitor_errors.log', reserve=reserve)
            time.sleep(0.5)
    dump(args.evidence / 'execution.json', dict(command=command, pid=proc.pid, exit_code=proc.returncode,
         seconds=time.monotonic()-start, peaks=peaks, monitor_python=sys.version,
         interpreter_under_test=str(args.python)))
    validate(args)
    print(json.dumps(dict(exit_code=proc.returncode, seconds=time.monotonic()-start, evidence=str(args.evidence))))
    return proc.returncode


def monitor_sample(root, start, peaks, memory, psutil, error_path, *, reserve=None):
    """A resource-starved collector must keep waiting on its child process."""
    try:
        collect(root, start, peaks, memory, psutil)
        return True
    except (MemoryError, OSError) as exc:
        if isinstance(exc, OSError) and getattr(exc, 'winerror', None) not in (8, 14, 1455):
            raise
        if reserve is not None:
            reserve.clear()
        with Path(error_path).open('a',encoding='utf-8') as error:
            error.write(f'{type(exc).__name__} in external monitor (winerror={getattr(exc, "winerror", None)}); sample unavailable; child still running\n')
        return False


def collect(root, start, peaks, memory, psutil):
    try:
        processes = [root, *root.children(recursive=True)]
    except psutil.Error:
        processes = []
    sample = dict(seconds=time.monotonic()-start, processes=[], system=psutil.virtual_memory()._asdict())
    if os.name == 'nt':
        # Windows virtual_memory.total is physical RAM, not commit.
        sample['system_commit_bytes'] = system_commit()
    for process in processes:
        try:
            info = process.memory_info()._asdict()
            created = process.create_time()
            row = dict(pid=process.pid, created_unix=created, parent=process.ppid(), memory=info)
            sample['processes'].append(row)
            # Windows can reuse PIDs during a long scan. A PID alone
            # would conflate different workers and their peak usage.
            key = f'{process.pid}@{created:.6f}'
            peak = peaks.setdefault(key, dict(pid=process.pid,created_unix=created,
                                    command=process.cmdline(), memory={}))
            for key, value in info.items():
                peak['memory'][key] = max(value, peak['memory'].get(key, 0))
        except psutil.Error:
            pass
    memory.write(json.dumps(sample)+'\n')
    memory.flush()


if __name__ == '__main__':
    raise SystemExit(main())
