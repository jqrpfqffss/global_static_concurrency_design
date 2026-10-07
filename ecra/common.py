import hashlib
import json
import os
import subprocess
import time
from pathlib import Path


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
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


# ---------------------------------------------------------------------------
# 标准 C 库参数语义（通用事实，非项目特例）
# ---------------------------------------------------------------------------
# 这些函数的指针参数语义由 C 标准完全确定。提取器与分类器据此：
# 1. 按参数方向记录 READ/WRITE 访问（而不是把所有指针参数都当"可能写"）；
# 2. 不把地址流向这些函数当作"流入不透明代码"（语义已知 ⇒ 非不透明）；
# 3. 读取方向的参数不构成写逃逸证据。
# 可变参数函数（printf 家族）不在表内：%n 可经指针实参写入，
# 保守保留其"不透明"语义。
# 键 = 实参序号（0 基），值 = 该实参的访问方向。定长、全参数语义已知
# 的函数才入表；未列出的实参序号维持原有的保守处理。
LIBC_ARG_SEMANTICS = {
    'memcpy': {0: 'WRITE', 1: 'READ'},
    'memmove': {0: 'WRITE', 1: 'READ'},
    'memset': {0: 'WRITE'},
    'memcmp': {0: 'READ', 1: 'READ'},
    'strcpy': {0: 'WRITE', 1: 'READ'},
    'strncpy': {0: 'WRITE', 1: 'READ'},
    'strcat': {0: 'WRITE', 1: 'READ'},
    'strncat': {0: 'WRITE', 1: 'READ'},
    'strlen': {0: 'READ'},
    'strcmp': {0: 'READ', 1: 'READ'},
    'strncmp': {0: 'READ', 1: 'READ'},
    'strcasecmp': {0: 'READ', 1: 'READ'},
    'strncasecmp': {0: 'READ', 1: 'READ'},
    'strchr': {0: 'READ'},
    'strrchr': {0: 'READ'},
    'strstr': {0: 'READ', 1: 'READ'},
}

LIBC_FUNCTION_NAMES = frozenset(LIBC_ARG_SEMANTICS)

import re as _re

# 函数 ID 可能是 USR（c:@F@strcpy、c:string.h@F@memcpy#…）或裸名；
# 逃逸判定与 points-to 语义统一按"被调函数名"查表（OPT-19，FS-10）。
_USR_FUNC_NAME = _re.compile(r'@F@([A-Za-z_]\w*)')


def libc_function_name(function_id):
    """从函数 ID（USR 或裸名，可带 :param: 后缀）中恢复被调函数名。"""
    base = function_id.split(':param:', 1)[0] if ':param:' in function_id else function_id
    match = _USR_FUNC_NAME.search(base)
    return match.group(1) if match else base
