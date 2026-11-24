"""Run one OpenCode invocation with live transcripts and owned cancellation."""
from contextlib import ExitStack, contextmanager
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


@contextmanager
def owned_process(argv, *, cwd, env, stdout, stderr, stdin=None, stop=None):
    """Contain each OpenCode process and release its helpers before returning."""
    from .opencode_command import launch_argv
    argv, env = launch_argv(argv, env)
    with ExitStack() as stack:
        if os.name == 'nt':
            from .studio.process_budget import ProcessBudget
            from .studio.write_guard import OwnedProcess
            job = ProcessBudget(None)
            stack.callback(job.close)
            proc = OwnedProcess(argv, cwd=cwd, env=env, log=stdout, stderr_log=stderr, stdin_log=stdin)
            stack.callback(proc.close)
            try:
                job.assign(proc)
                if stop is not None:
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
            yield proc
        finally:
            # Also release helpers that survive an otherwise successful launcher.
            stop_tree()
            proc.wait(timeout=3)


def execute(argv, *, cwd, env, timeout, input=None, stop, stdout_path, stderr_path, on_exit=None, diagnostic=None, startup=None):
    stop.check()
    from .opencode_protocol import redactor, AuthenticationRequired, interactive_prompt, ProtocolError
    from .opencode_command import display_command
    import json
    scrub = redactor(env)
    record = diagnostic if diagnostic is not None else {}
    started = time.monotonic()
    record.update(operation_stage='run', cli_launch_attempts=0, model_calls=0,
                  argv=[scrub(arg) for arg in display_command(argv)], cwd=str(cwd),
                  database=env.get('OPENCODE_DB'), timeout_seconds=timeout,
                  outcome='starting', returncode_before_reap=None, ecra_requested_reap=False)
    interrupted, proc = None, None
    try:
        with ExitStack() as stack:
            initialized = stack.enter_context(startup(stop)) if startup else None
            started = time.monotonic()
            stdout = stack.enter_context(stdout_path.open('wb'))
            stderr = stack.enter_context(stderr_path.open('wb'))
            stdin = None
            if input is not None:
                from .workspace import managed_path
                stdin = stack.enter_context(TemporaryFile(dir=managed_path(env['TEMP'])))
                stdin.write(input.encode('utf-8'))
                stdin.seek(0)
            record.update(cli_launch_attempts=1, model_calls=None)
            with owned_process(argv, cwd=cwd, env=env, stdout=stdout, stderr=stderr, stdin=stdin, stop=stop) as proc:
                record.update(pid=proc.pid, outcome='running')
                try:
                    deadline = time.monotonic() + timeout
                    while proc.poll() is None:
                        stop.check()
                        for path in (stdout_path, stderr_path):
                            with path.open('rb') as output:
                                prefix = output.read(65536).decode('utf-8', errors='replace')
                            if initialized and path == stdout_path:
                                for line in prefix.splitlines():
                                    try:
                                        event = json.loads(line)
                                    except ValueError:
                                        continue
                                    if isinstance(event, dict) and event.get('sessionID'):
                                        initialized()
                                        initialized = None
                                        break
                            if interactive_prompt(prefix):
                                raise AuthenticationRequired('OpenCode run 要求交互域认证；本批次停止继续派发，请使用发行版正式登录入口')
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise subprocess.TimeoutExpired(record['argv'], timeout)
                        try:
                            proc.wait(timeout=min(remaining, .1))
                        except subprocess.TimeoutExpired:
                            continue
                except BaseException as exc:
                    interrupted = exc
                finally:
                    record.update(returncode_before_reap=proc.poll(), ecra_requested_reap=proc.poll() is None)
            if initialized and proc.returncode == 0:
                initialized()
            if on_exit is not None:
                on_exit()
    except BaseException as exc:
        if interrupted is not None:
            record['reap_error'] = scrub(str(exc))
        interrupted = interrupted or exc
        # owned_process reaps the tree before leaving, including on cancellation.
        if proc is not None and proc.returncode is not None and on_exit is not None:
            on_exit()
    decoded = []
    for path in (stdout_path, stderr_path):
        raw = path.read_bytes() if path.exists() else b''
        try:
            text = raw.decode('utf-8-sig')
        except UnicodeError:
            interrupted = interrupted or ProtocolError('OpenCode 重定向输出不是有效 UTF-8；已保留容错显示的脱敏诊断，不能用于协议判断')
            text = raw.decode('utf-8', errors='replace')
        safe = scrub(text)
        if safe != text or interrupted is not None:
            path.write_text(safe, encoding='utf-8')
        decoded.append(safe)
    if interrupted is None and any(interactive_prompt(text) for text in decoded):
        interrupted = AuthenticationRequired('OpenCode run 返回了交互域认证提示；本批次停止继续派发')
    # CLI starts are not model calls. Without response evidence the count is
    # unknown, including silent timeout/login/nonzero failures after launch.
    observed = False
    for line in decoded[0].splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and (event.get('type') == 'step_finish' or
                event.get('type') == 'error' and isinstance(event.get('error'), dict) and
                isinstance(event['error'].get('data'), dict) and event['error']['data'].get('statusCode')):
            observed = True
    record.update(model_requests_observed=observed, model_calls_lower_bound=1 if observed else 0,
                  elapsed_seconds=time.monotonic()-started,
                  returncode_after_reap=proc.returncode if proc is not None else None)
    if interrupted is not None:
        record.update(outcome='cancelled' if isinstance(interrupted, KeyboardInterrupt) else
                      'timeout' if isinstance(interrupted, subprocess.TimeoutExpired) else 'failed',
                      error_code=getattr(interrupted, 'code', type(interrupted).__name__))
        raise interrupted
    record['outcome'] = 'completed' if proc.returncode == 0 else 'nonzero_exit'
    return subprocess.CompletedProcess(argv, proc.returncode, *decoded)
