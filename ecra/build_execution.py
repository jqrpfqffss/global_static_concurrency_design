"""CMake subprocess execution and byte-preserving diagnostic logs."""
from contextvars import ContextVar
import hashlib
import os
from .common import execute as ordinary_execute

BUILD_EXECUTOR = ContextVar('ecra_build_executor', default=None)
FROZEN_BUILD = ContextVar('ecra_frozen_build', default=None)


def execute(argv, **kwargs):
    executor = BUILD_EXECUTOR.get()
    return ordinary_execute(argv, **kwargs) if executor is None else executor(argv, **kwargs)


def _windows_code_pages():
    if os.name != 'nt':
        return ()
    import ctypes
    kernel = ctypes.windll.kernel32
    return tuple(dict.fromkeys('cp'+str(page) for page in
        (kernel.GetConsoleOutputCP(), kernel.GetOEMCP(), kernel.GetACP()) if page not in (0, 65001)))


def _decode_log(raw):
    encodings = ('utf-8-sig', *_windows_code_pages())
    used, lines = set(), []
    # CMake can emit UTF-8 and forward a child process using CMD's code page
    # in the same stream. Preserve undecodable bytes in the text preview too.
    for line in raw.splitlines(keepends=True):
        for encoding in encodings:
            try:
                decoded = line.decode(encoding)
            except (UnicodeError, LookupError):
                continue
            used.add('utf-8' if encoding == 'utf-8-sig' else encoding)
            break
        else:
            decoded = line.decode('utf-8', errors='backslashreplace')
            used.add('unknown')
        lines.append(decoded)
    return ''.join(lines), sorted(used)


def save_logs(out, stage, stdout, stderr):
    log = out/f'cmake-{stage}.log'
    evidence, display = {}, []
    for name, raw in (('stdout', stdout), ('stderr', stderr)):
        if isinstance(raw, bytes):
            path = out/f'cmake-{stage}.{name}.bin'
            path.write_bytes(raw)
            decoded, encodings = _decode_log(raw)
            evidence[name] = dict(path=str(path), encodings=encodings, bytes=len(raw),
                                  sha256=hashlib.sha256(raw).hexdigest())
            if 'unknown' in encodings:
                decoded = f'[{name} 编码不确定，原始字节: {path}]\n'+decoded
            display.append(decoded)
        else:
            display.append(raw or '')
    message = '\n'.join(part.replace('\r\n', '\n').rstrip('\n') for part in display if part)
    log.write_text(message, encoding='utf-8', newline='\n')
    return log, evidence, message
