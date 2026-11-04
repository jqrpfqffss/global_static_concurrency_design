"""Isolated supervised entry point; wait for Job assignment before any build."""
import argparse
import os
from pathlib import Path
import time


def execute(args):
    deadline = time.monotonic()+30
    while not args.gate.is_file():
        if time.monotonic()>deadline:
            raise RuntimeError('任务监督器未建立资源所有权；拒绝启动构建')
        time.sleep(.05)
    os.environ['ECRA_DATA_ROOT'] = str(args.data_root)
    os.environ['ECRA_JOB_STOP_FILE'] = str(args.stop)
    from ..config import configured_project_root
    if args.mode=='multicore':
        import json
        import threading
        import _thread
        from ..multicore import combine
        from ..scan_diagnostics import ScanDiagnostics
        spec=json.loads((args.result.parent/'multicore.json').read_text('utf-8'))
        finished=threading.Event()
        def stop_derivation():
            while not finished.wait(.2):
                if args.stop.is_file():_thread.interrupt_main();return
        threading.Thread(target=stop_derivation,daemon=True).start()
        diagnostics=ScanDiagnostics(args.result.parent/'multicore-diagnostics',lambda value:print(value,flush=True))
        try:
            diagnostics.stage('固定多核输入完整校验、事实组合与派生判定（剩余量未知）')
            combine(Path(spec['project_root']),[(row['variant'],Path(row['config'])) for row in spec['inputs']],
                    spec['regions'],args.data_root/'scans'/args.scan_id,
                    elf_paths={row['variant']:row['elf'] for row in spec['inputs']},data_root=args.data_root,
                    scan_ids={row['variant']:row['scan_id'] for row in spec['inputs']},
                    profile_ids={row['variant']:row['profile_id'] for row in spec['inputs']},
                    expected_inputs={row['variant']:row['expected'] for row in spec['inputs']},_budget_owned=True)
            return 0
        except BaseException as exc:
            diagnostics.failure(exc);raise
        finally:
            finished.set();diagnostics.close()
    if args.mode in {'scan', 'precheck'}:
        from .preflight import run_preflight
        run_preflight(args.config, args.data_root, args.result.parent/'preflight',
                      progress=lambda text: print(text, flush=True))
        if args.mode == 'precheck': return 0
    else:
        import threading
        import _thread
        finished=threading.Event()
        def watch_stop():
            while not finished.wait(.2):
                if args.stop.is_file():
                    _thread.interrupt_main(); return
        threading.Thread(target=watch_stop,daemon=True).start()
        try:
            from ..workflow import saved_run
            return saved_run(configured_project_root(args.config),args.config,
                failed_only=args.mode=='review-failed',_out=args.data_root/'scans'/args.scan_id,_budget_owned=True)
        finally:
            finished.set()
    from ..scan_persistence import run_canonical
    import json
    fixed_storage=json.loads((args.result.parent/'storage-policy.json').read_text('utf-8'))
    return run_canonical(configured_project_root(args.config), args.config, scan_id=args.scan_id, profile_id=args.profile_id,
                         _budget_owned=True,_storage_policy=fixed_storage)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, required=True)
    parser.add_argument('--scan-id', required=True)
    parser.add_argument('--profile-id', required=True)
    parser.add_argument('--gate', type=Path, required=True)
    parser.add_argument('--stop', type=Path, required=True)
    parser.add_argument('--mode', choices=['scan','precheck','review','review-failed','multicore'], default='scan')
    parser.add_argument('--result', type=Path, required=True)
    args = parser.parse_args()
    error=None
    try:
        code=execute(args)
    except KeyboardInterrupt:
        code=130
    except Exception as exc:
        import traceback
        traceback.print_exc()
        code=3;error=f'{type(exc).__name__}: {exc}'
    from ..common import write_json
    write_json(args.result,dict(exit_code=code,operation_completed=code in {0,1,2},error=error))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
