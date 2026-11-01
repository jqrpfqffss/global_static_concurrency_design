"""Real Windows commit exhaustion; isolated diagnostic test, never a scan.

The optional extra reserve is an experimental harness intervention. It must
not be presented as the engine's native handling until implemented and tested.
"""
import argparse
import gc
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
sys.path.insert(0, str(Path(__file__).resolve().parent))
from commit_reserve import CommitReserve, python_reserve as make_python_reserve


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def exhaust_allocators():
    retained, used = [None] * 200000, 0
    for size in (1024*1024, 4096, *range(8, 512, 8)):
        try:
            while True:
                retained[used] = bytes(size)
                used += 1
        except MemoryError:
            pass
    while True:
        retained[used] = bytes(512)
        used += 1


def wait_limit(args):
    deadline = time.monotonic() + 30
    while not (args.evidence / 'limit.json').is_file():
        if time.monotonic() > deadline:
            raise RuntimeError('Explicit Job limit was not applied')
        time.sleep(0.05)
    value=json.loads((args.evidence/'limit.json').read_text(encoding='utf-8'))
    if value.get('pid')!=os.getpid() or value.get('process_commit_limit_bytes')!=int(args.limit_mib*1024**2):
        raise RuntimeError('Fault allocator PID or commit limit mismatches; refusing allocation')


def cli_probe(args):
    from ecra import cli
    from ecra.scan_diagnostics import memory
    # Windows TEMP can use an 8.3 alias; the CLI API expects a resolved root.
    root = (args.evidence/'fixture').resolve()
    root.mkdir()
    (root/'app.c').write_text('int shared; void IRQ(void){shared++;} int main(void){shared++;return 0;}', encoding='utf-8')
    dump(root/'compile_commands.json', [dict(directory=str(root), file='app.c',
         arguments=['arm-none-eabi-gcc', '-mcpu=cortex-m4', '-mthumb', '-c', 'app.c'])])
    cfg = root/'semantics.yaml'
    dump(cfg, dict(version=1, analysis=dict(output=dict(location='project'),compile_database='compile_commands.json'),
         contexts=[dict(id='main',kind='MAIN',functions=['main']),dict(id='irq',kind='ISR',functions=['IRQ'])],
         review=dict(enabled=False,prepare_packets=False)))
    assert cli.run(root, str(cfg), no_review=True) in (0, 1, 2)
    out = root/'.ecra'
    assert json.loads((out/'result_validity.json').read_text(encoding='utf-8'))['analysis_valid'] is True
    original = cli.merge
    def merge(*a, **kw):
        original(*a, **kw)
        dump(args.evidence/'ready.json', dict(pid=os.getpid(),memory=memory(),prior_success=True))
        wait_limit(args)
        exhaust_allocators()
    cli.merge = merge
    code = cli.run(root, str(cfg), no_review=True)
    assert code == 3, code
    assert json.loads((out/'result_validity.json').read_text(encoding='utf-8'))['analysis_valid'] is False
    assert not (out/'scan_state.json').exists()
    assert not (out/'scan.lock').exists()
    assert '不能使用旧结论' in (out/'index.html').read_text(encoding='utf-8')
    assert json.loads((out/'run.json').read_text(encoding='utf-8'))['state'] == 'FAILED'
    assert 'MemoryError' in (out/'diagnostics/exception.log').read_text(encoding='utf-8')
    dump(args.evidence/'result.json', dict(controlled_fault_injection=True,full_scan_acceptance=False,
         actual_clang_fixture=True,prior_success=True,failed_report_invalid=True,checkpoint_removed=True,
         lock_removed=True,cli_exit_code=code,experimental_private_and_python_reserves=False,
         interpreter=sys.version,memory=memory()))
    return 0


def inside(args):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    sys.path.insert(0, str(args.engine))
    if args.cli:
        return cli_probe(args)
    from ecra.scan_diagnostics import ScanDiagnostics, memory
    diagnostics = ScanDiagnostics(args.evidence / 'diagnostics')
    diagnostics.stage('受控实际提交额度耗尽', announce=False)
    diagnostics.total_units = diagnostics.completed_units = 1
    diagnostics.snapshot_status = 'NOT_A_SCAN'
    reserve = CommitReserve() if args.mapped_reserve else None
    python_reserve = make_python_reserve() if reserve is not None else None
    release_reserve = reserve.close if reserve is not None else lambda: None
    if reserve is not None:
        diagnostics.reserve = None
    dump(args.evidence / 'ready.json', dict(pid=os.getpid(), memory=memory()))
    wait_limit(args)
    # Preallocate references so a list resize does not become the first limit.
    # Fill every small-object size class as well as the C heap. Real analysis
    # owns millions of dicts/tuples/strings, unlike a bytearray-only toy probe.
    retained, used = [None] * 200000, 0
    sizes = (1024*1024, 4096, *range(8, 512, 8))
    try:
        for size in sizes:
            try:
                while True:
                    retained[used] = bytes(size)
                    used += 1
            except MemoryError:
                pass
        while True:
            retained[used] = bytes(512)
            used += 1
    except MemoryError as exc:
        python_reserve = None
        # The production caller must release this before entering the handler.
        if hasattr(diagnostics, 'commit_reserve'):
            diagnostics.reserve = None
        release_reserve()
        try:
            diagnostics.failure(exc, origin=args.origin)
            diagnostics.close()
        except BaseException:
            # Release test payload only after observing the handler's behavior.
            retained.clear()
            gc.collect()
            dump(args.evidence / 'handler-failed.json', dict(traceback=traceback.format_exc(), memory=memory()))
            raise
    retained.clear()
    gc.collect()
    info = json.loads((args.evidence / 'diagnostics/exception.json').read_text(encoding='utf-8'))
    assert info['exception_type'] == 'MemoryError' and info['analysis_valid'] is False
    assert info['origin'] == args.origin
    assert 'MemoryError' in (args.evidence / 'diagnostics/exception.log').read_text(encoding='utf-8')
    dump(args.evidence / 'result.json', dict(controlled_fault_injection=True, full_scan_acceptance=False,
        diagnostic_handling_complete=True, experimental_private_and_python_reserves=args.mapped_reserve,
        origin=args.origin, interpreter=sys.version, memory=memory()))
    return 0


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ('engine', 'python', 'evidence'):
        parser.add_argument('--'+field, type=Path, required=True)
    parser.add_argument('--limit-mib', type=int, default=192)
    parser.add_argument('--setup-timeout-seconds', type=float, default=30,
                        help='建立实际 Clang 夹具的就绪时限；不改变注入后的内存额度')
    parser.add_argument('--origin', choices=('MAIN', 'WORKER'), default='MAIN')
    parser.add_argument('--cli', action='store_true', help='Actually scan a disposable Clang fixture, then exhaust merge commit and verify prior-report invalidation')
    parser.add_argument('--experimental-reserve', '--mapped-reserve', dest='mapped_reserve', action='store_true',
                        help='Add test-only Python/private reserves; never claim native engine handling from this mode')
    parser.add_argument('--inside', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not 0 < args.setup_timeout_seconds <= 600:
        parser.error('准备阶段时限必须大于 0 且不超过 600 秒')
    if args.cli and (args.mapped_reserve or args.origin != 'MAIN'):
        parser.error('--cli uses the engine native MAIN handling only')
    if args.inside:
        return inside(args)
    if os.name != 'nt':
        parser.error('This controlled experiment requires a Windows Job Object')
    args.evidence.mkdir(parents=True, exist_ok=False)
    begin = time.monotonic()
    command = [str(args.python), '-u', str(Path(__file__).resolve()), *sys.argv[1:], '--inside']
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    from ecra.studio.write_guard import OwnedProcess
    from ecra.studio.process_budget import ProcessBudget
    budget=ProcessBudget(512*1024**2);child=controller=None
    try:
      with (args.evidence / 'console.log').open('w', encoding='utf-8') as log:
        child=OwnedProcess(command,cwd=args.engine,env=os.environ.copy(),log=log)
        budget.assign(child);child.resume()
        while not (args.evidence / 'ready.json').is_file():
            if child.poll() is not None:
                raise RuntimeError('Child failed before test limit:\n' +
                                   (args.evidence/'console.log').read_text(encoding='utf-8', errors='replace'))
            if time.monotonic()-begin > args.setup_timeout_seconds:
                raise RuntimeError('Child setup timed out')
            time.sleep(0.05)
        actual=json.loads((args.evidence/'ready.json').read_text(encoding='utf-8'))['pid']
        if not budget.contains(actual):raise RuntimeError('Declared real allocator is not in the owned512MiB Job')
        controller = subprocess.Popen([sys.executable, str(Path(__file__).with_name('windows_memory_limit.py')),
            '--pid', str(actual), '--gib', str(args.limit_mib/1024), '--evidence', str(args.evidence/'limit.json')],
            stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
        code = child.wait(timeout=120)
        controller.wait(timeout=10)
        peak=budget.sample()['peak_job_commit_bytes']
    finally:
        budget.close()
        if child is not None:
            child.wait(timeout=10);child.close()
        if controller is not None and controller.poll() is None:
            controller.wait(timeout=10)
    dump(args.evidence / 'execution.json', dict(controlled_fault_injection=True, full_scan_acceptance=False,
        exit_code=code, seconds=time.monotonic()-begin, command=command,launcher_pid=child.pid,
        allocator_pid=actual,allocator_in_owned_job=True,outer_job_limit_bytes=512*1024**2,outer_peak_job_commit_bytes=peak))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
