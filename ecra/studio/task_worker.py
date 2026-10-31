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
    if args.mode != 'scan':
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
    return run_canonical(configured_project_root(args.config), args.config, scan_id=args.scan_id, profile_id=args.profile_id,_budget_owned=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, required=True)
    parser.add_argument('--scan-id', required=True)
    parser.add_argument('--profile-id', required=True)
    parser.add_argument('--gate', type=Path, required=True)
    parser.add_argument('--stop', type=Path, required=True)
    parser.add_argument('--mode', choices=['scan','review','review-failed'], default='scan')
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
