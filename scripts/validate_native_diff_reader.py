"""Measure cold summary reading of one immutable native authority on Windows.

full restores the original complete facts/report and calls original summarize;
selected calls that same algorithm through the per-field reader. Compare the
complete summary.json bytes from independent runs. This is not a new scan,
whole Diff, physical 32GB gate, or full disk gate. Allocation samples exclude
directory/MFT metadata and ADS; paging counters describe the entire host.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys
import time
import traceback


def worker(args):
    from ecra.common import write_json
    from ecra.git_diff import summarize
    from ecra.native_diff_summary import summarize_native
    from ecra.report_package import sha256
    from ecra.scan_store import EvidenceProvider
    from unittest.mock import patch
    work = args.work
    start = time.monotonic()
    if args.mode == 'full':
        write_json(work/'phase.json', dict(phase='FULL_FACTS_AND_REPORT'))
        provider = EvidenceProvider(args.source)
        facts, report = provider.load('facts'), provider.load('report')
        write_json(work/'phase.json', dict(phase='ORIGINAL_SUMMARIZE'))
        summary = summarize(facts, report)
    else:
        write_json(work/'phase.json', dict(phase='SELECTED_ORIGINAL_SUMMARIZE'))
        with patch.object(EvidenceProvider, 'load', side_effect=AssertionError('Whole root restoration forbidden')):
            summary = summarize_native(args.source)
    write_json(work/'phase.json', dict(phase='SERIALIZE_COMPLETE_SUMMARY'))
    write_json(work/'summary.json', summary, indent=None)
    write_json(work/'result.json', dict(passed=True, mode=args.mode, seconds=time.monotonic()-start,
        summary_sha256=sha256(work/'summary.json'), summary_bytes=(work/'summary.json').stat().st_size,
        variables=len(summary['variables']), functions=len(summary['functions']),
        full_field_oracle='Compare complete summary.json bytes against independent full mode; counts alone are not acceptance'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True, help='Immutable scan.db')
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--engine', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--mode', choices=['full', 'selected'], required=True)
    parser.add_argument('--job-gib', type=float, required=True)
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    args.engine = args.engine.resolve(); sys.path.insert(0, str(args.engine))
    if args.worker:
        return worker(args)
    from ecra.common import write_json
    from ecra.report_package import sha256
    from ecra.scan_diagnostics import memory
    from ecra.studio.process_budget import ProcessBudget
    from ecra.studio.resource_policy import temporary_environment
    from ecra.studio.write_guard import OwnedProcess
    from ecra.workspace import no_links, studio_data_root
    from scripts.native_metrics import directory_size, PagingRates
    args.source = no_links(args.source); args.work = studio_data_root(args.work)
    if args.source.parent == args.work or args.work.is_relative_to(args.source.parent) or args.source.is_relative_to(args.work):
        raise ValueError('观察输出必须在原authority外')
    if os.name != 'nt' or not .25 <= args.job_gib <= 32:
        raise ValueError('需要实际Windows Job及0.25–32GiB预算')
    args.work.mkdir(parents=True, exist_ok=False)
    started = time.monotonic(); process = paging = None
    budget = ProcessBudget(int(args.job_gib*1024**3))
    state = dict(passed=False, status='RUNNING', scope=__doc__, mode=args.mode,
        source=str(args.source), engine=str(args.engine), job_limit_bytes=budget.limit,
        started_utc=datetime.now(timezone.utc).isoformat(), peaks={}, all_gates_passed=False,
        physical_32GB='NOT_VERIFIED', source_before_sha256=sha256(args.source))
    def save():
        state['seconds'] = time.monotonic()-started
        write_json(args.work/'execution.json', state)
    def peak(sample):
        for key in ('working_set_bytes', 'private_bytes', 'peak_job_commit_bytes'):
            state['peaks'][key] = max(state['peaks'].get(key, 0), sample.get(key, 0))
    save()
    try:
        paging = PagingRates()
        with (args.work/'console.log').open('xb') as log, (args.work/'resources.jsonl').open('x', encoding='utf-8') as samples:
            command = [sys.executable, '-B', '-X', 'utf8', str(Path(__file__).resolve()), '--worker',
                '--source', str(args.source), '--work', str(args.work), '--engine', str(args.engine),
                '--mode', args.mode, '--job-gib', str(args.job_gib)]
            process = OwnedProcess(command, cwd=args.engine, log=log,
                env=temporary_environment(args.work, dict(os.environ, PYTHONPATH=str(args.engine),
                    PYTHONHASHSEED='0', PYTHONDONTWRITEBYTECODE='1')))
            budget.assign(process); process.resume(); state.update(pid=process.pid, command=command); save()
            while process.poll() is None:
                if (args.work/'stop').is_file():
                    raise KeyboardInterrupt('收到显式停止请求；只停止本次自有Job')
                sample = budget.sample(); peak(sample)
                system = memory(); disk = directory_size(args.work)
                sample.update(system=system, disk=disk, paging=paging.sample())
                for key in ('logical_bytes', 'allocated_bytes'):
                    name = 'sampled_output_'+key
                    state['peaks'][name] = max(state['peaks'].get(name, 0), disk[key])
                samples.write(json.dumps(sample)+'\n'); samples.flush(); save()
                if (system.get('system_physical_available_bytes', 2**63) < 8*1024**3
                        or system.get('system_commit_limit_bytes', 2**63)-system.get('system_commit_bytes', 0) < 8*1024**3):
                    raise MemoryError('主机余量不足8GiB，停止自有Job；原件保留')
                if shutil.disk_usage(args.work).free < 2*1024**3:
                    raise OSError('观察输出盘空闲不足2GiB')
                time.sleep(1)
            process.wait(timeout=30); peak(budget.sample())
            state.update(exit_code=process.returncode, final_job_sampled=True)
            if process.returncode:
                raise RuntimeError('Worker失败，保留原始日志和资源采样')
        result = json.loads((args.work/'result.json').read_text('utf-8'))
        manifest = args.engine.with_name(args.engine.name+'.sha256.json')
        if manifest.is_file():
            frozen = json.loads(manifest.read_text('utf-8'))
            differences = [row['file'] for row in frozen['files'] if sha256(args.engine/row['file']) != row['sha256']]
            if differences:
                raise ValueError('冻结源码变化：'+str(differences))
            state.update(engine_manifest_sha256=sha256(manifest), engine_differences=differences)
        state.update(passed=True, status='PASS_SCOPED', result=result)
    except BaseException:
        state.update(status='FAIL', error=traceback.format_exc())
        raise
    finally:
        budget.close()
        if process is not None: process.close()
        if paging is not None: paging.close()
        state['source_after_sha256'] = sha256(args.source)
        state['source_unchanged'] = state['source_before_sha256'] == state['source_after_sha256']
        state['final_output'] = directory_size(args.work)
        if not state['source_unchanged']:
            state.update(passed=False, status='FAIL', source_error='原authority变化')
        save()
        if not state['source_unchanged']:
            raise ValueError('原authority变化，禁止将本次观察结果作为通过证据')
    print(json.dumps(dict(passed=state['passed'], seconds=state['seconds'], peaks=state['peaks'])), flush=True)


if __name__ == '__main__':
    main()
