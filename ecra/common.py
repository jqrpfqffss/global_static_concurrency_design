import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path


# C library pointer-argument effects. A name enters the no-escape contract
# only when both extraction and points-to use this same table.
LIBC_POINTER_MODES = {
    'memcpy': {0: 'WRITE', 1: 'READ'},
    'memmove': {0: 'WRITE', 1: 'READ'},
    'memset': {0: 'WRITE'},
    'memcmp': {0: 'READ', 1: 'READ'},
    'strcpy': {0: 'WRITE', 1: 'READ'},
    'strncpy': {0: 'WRITE', 1: 'READ'},
    'strcat': {0: 'RMW', 1: 'READ'},
    'strncat': {0: 'RMW', 1: 'READ'},
    'strcmp': {0: 'READ', 1: 'READ'},
    'strncmp': {0: 'READ', 1: 'READ'},
    'strlen': {0: 'READ'},
    # Formatted output writes only its destination. Format strings and
    # pointer-valued substitutions are read; none of these APIs retains a
    # caller pointer or registers an asynchronous entry.
    'vsnprintf': {0: 'WRITE', 2: 'READ', 3: 'READ'},
    'snprintf': {0: 'WRITE', 2: 'READ'},
    'vsprintf': {0: 'WRITE', 1: 'READ', 2: 'READ'},
    'sprintf': {0: 'WRITE', 1: 'READ'},
}


def libc_pointer_modes(name, argument_count):
    modes = dict(LIBC_POINTER_MODES.get(name, {}))
    first_variadic = {'snprintf': 3, 'sprintf': 2}.get(name)
    if first_variadic is not None:
        modes.update({index: 'READ' for index in range(first_variadic, argument_count)})
    return modes


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def write_json(path, value, *, indent=2):
    path = Path(path)
    from .scan_persistence import queue_directory, append_runtime, runtime
    directory = queue_directory(path)
    if directory is not None:
        return append_runtime(directory,runtime(directory,with_reviews=False).get('report',{}),value)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open('w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=indent,
                  separators=(',', ':') if indent is None else None)
    replace_file(temp, path)


def replace_file(source, destination):
    """Keep atomic replacement, tolerating brief Windows sharing violations.

    Do not delete the old destination or fall back to a non-atomic copy.
    Permanent access failures remain visible after a bounded 0.75 s retry.
    """
    for attempt in range(5):
        try:
            Path(source).replace(destination)
            return
        except PermissionError as exc:
            if getattr(exc, 'winerror', None) not in {5, 32, 33} or attempt == 4:
                raise
            time.sleep(0.05 * (2 ** attempt))


def read_json(path):
    from .scan_persistence import artifact, read, queue_directory, runtime
    directory = queue_directory(path)
    if directory is not None:
        return runtime(directory).get('reviews',[])
    if artifact(path) is not None:
        return read(path)
    from .shared_json import encoded_stream, read_stream
    with Path(path).open(encoding='utf-8-sig') as stream:
        return read_stream(stream) if encoded_stream(stream) else json.load(stream)


def relative(path, root):
    p = Path(path).resolve()
    try:
        return p.relative_to(root).as_posix()
    except ValueError:
        return p.as_posix()


def execute(argv, *, input=None, cancel_event=None, **kwargs):
    """No shell evaluation; kill the process tree on a timeout."""
    options = dict(stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                   encoding="utf-8", errors="replace")
    options.update(kwargs)
    if input is not None:
        options['stdin'] = subprocess.PIPE
    timeout = options.pop("timeout", 300)
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW
    else:
        options["start_new_session"] = True
    def check_cancel():
        if cancel_event is not None and cancel_event.is_set():
            raise KeyboardInterrupt('已停止所属的翻译单元提取进程')

    check_cancel()
    proc = subprocess.Popen(argv, **options)
    try:
        if cancel_event is None:
            out, err = proc.communicate(input=input, timeout=timeout)
        else:
            deadline = time.monotonic() + timeout
            while True:
                check_cancel()
                remaining = deadline - time.monotonic()
                try:
                    out, err = proc.communicate(input=input, timeout=max(0, min(remaining, .05)))
                    break
                except subprocess.TimeoutExpired as exc:
                    if time.monotonic() >= deadline:
                        exc.timeout = timeout
                        raise
                    input = None  # communicate retains the original input across retries
    except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
        try:
            if os.name == "nt":
                try:
                    if proc.poll() is None:
                        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], timeout=3,
                                       capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
                finally:
                    if proc.poll() is None:
                        proc.kill()
            else:
                import signal
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            # Windows pipe readers may supply output only after termination.
            exc.output, exc.stderr = proc.communicate(timeout=2)
        except (OSError, subprocess.TimeoutExpired) as cleanup_error:
            try:
                print(f'进程 {proc.pid} 清理失败：{cleanup_error}', file=sys.stderr, flush=True)
            except (OSError, ValueError):
                pass
        raise
    return subprocess.CompletedProcess(argv, proc.returncode, out, err)
