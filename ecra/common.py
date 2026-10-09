import hashlib
import json
import os
import subprocess
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


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open('w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
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
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def relative(path, root):
    p = Path(path).resolve()
    try:
        return p.relative_to(root).as_posix()
    except ValueError:
        return p.as_posix()


def execute(argv, **kwargs):
    """No shell evaluation; kill the process tree on a timeout."""
    options = dict(stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                   encoding="utf-8", errors="replace")
    options.update(kwargs)
    timeout = options.pop("timeout", 300)
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW
    else:
        options["start_new_session"] = True
    proc = subprocess.Popen(argv, **options)
    try:
        out, err = proc.communicate(timeout=timeout)
    except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            import signal
            os.killpg(proc.pid, signal.SIGKILL)
        # Windows reader threads often supply output only after the process is
        # terminated. Preserve it so failed real reviews retain their evidence.
        out, err = proc.communicate()
        exc.output, exc.stderr = out, err
        raise
    return subprocess.CompletedProcess(argv, proc.returncode, out, err)
