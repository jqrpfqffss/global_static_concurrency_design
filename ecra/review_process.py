"""Run one OpenCode invocation with live transcripts and owned cancellation."""
from contextlib import ExitStack
import os
from pathlib import Path
import signal
import subprocess
from tempfile import TemporaryFile
import time


class ReviewStop:
    def __init__(self):
        from threading import Event
        self.cancelled = Event()
        path = os.environ.get('ECRA_JOB_STOP_FILE')
        self.path = Path(path) if path else None

    def is_set(self):
        return self.cancelled.is_set() or (self.path is not None and self.path.is_file())

    def check(self):
        if self.is_set():
            raise KeyboardInterrupt('已停止 OpenCode 复核，已提交结果保留')


def execute(argv, *, cwd, env, timeout, input=None, stop, stdout_path, stderr_path):
    stop.check()
    with ExitStack() as stack:
        stdout = stack.enter_context(stdout_path.open('wb'))
        stderr = stack.enter_context(stderr_path.open('wb'))
        stdin = None
        if input is not None:
            stdin = stack.enter_context(TemporaryFile())
            stdin.write(input.encode('utf-8'))
            stdin.seek(0)

        if os.name == 'nt':
            from .studio.process_budget import ProcessBudget
            from .studio.write_guard import OwnedProcess
            job = ProcessBudget(None)
            stack.callback(job.close)
            proc = OwnedProcess(argv, cwd=cwd, env=env, log=stdout, stderr_log=stderr, stdin_log=stdin)
            stack.callback(proc.close)
            try:
                job.assign(proc)
                stop.check()
                proc.resume()
            except BaseException:
                proc.terminate()
                proc.wait(timeout=3)
                raise
            stop_tree = job.close
        else:
            proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=stdin or subprocess.DEVNULL,
                                    stdout=stdout, stderr=stderr, start_new_session=True)

            def stop_tree():
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

        try:
            deadline = time.monotonic() + timeout
            while proc.poll() is None:
                stop.check()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(argv, timeout)
                try:
                    proc.wait(timeout=min(remaining, .1))
                except subprocess.TimeoutExpired:
                    continue
        finally:
            # Also release helpers that survive an otherwise successful launcher.
            stop_tree()
            proc.wait(timeout=3)
    return subprocess.CompletedProcess(argv, proc.returncode, stdout_path.read_text('utf-8', errors='replace'),
                                       stderr_path.read_text('utf-8', errors='replace'))
