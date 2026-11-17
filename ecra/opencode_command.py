"""Keep the configured installation entry intact, including enterprise wrappers."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess


class WindowsCommand(list):
    """An already quoted cmd.exe /c tail; CRT quoting does not apply to it."""
    pass


FORBIDDEN = {'--attach', '--continue', '-c', '--session', '-s', '--fork', '--dir',
             '--share', '--interactive', '-i', '--mini', '--service', '--port',
             '--hostname', '--auto', '--yolo', '--dangerously-skip-permissions'}


def display_command(command):
    result, secret = [], False
    for arg in command:
        if secret:
            result.append('<redacted>')
            secret = False
        elif arg.startswith('-') and re.search(r'password|token|secret|api[-_]?key|auth', arg.split('=', 1)[0], re.I):
            result.append(arg.split('=', 1)[0] + ('=<redacted>' if '=' in arg else ''))
            secret = '=' not in arg
        else:
            result.append(re.sub(r'(https?://)[^\s/@]+:[^\s/@]+@', r'\1<redacted>@', arg))
    return result


def resolve_command(command):
    if not isinstance(command, (list, tuple)) or not command or any(
            not isinstance(arg, str) or '\x00' in arg for arg in command) or not command[0]:
        raise ValueError('review.command 必须是非空参数数组')
    if any(arg.split('=', 1)[0] in FORBIDDEN for arg in command[1:]):
        raise ValueError('ECRA 复核只能启动独立的本地 OpenCode 会话；请移除复用、服务或权限覆盖参数')
    entry = shutil.which(command[0])
    if not entry and Path(command[0]).is_file():
        entry = str(Path(command[0]).resolve())
    if not entry:
        raise FileNotFoundError(f'找不到 OpenCode 命令: {command[0]}')
    return [str(Path(entry).resolve()), *command[1:]]


def launch_argv(argv, env):
    """Resolve a script host without embedding caller text in executable code.

    cmd expands these environment references once, with delayed expansion off.
    Quotes/newlines cannot be safely forwarded by arbitrary legacy batch files;
    reject those arguments explicitly (review prompts always use stdin).
    """
    suffix = Path(argv[0]).suffix.lower()
    if os.name != 'nt' or suffix not in {'.cmd', '.bat', '.ps1'}:
        return list(argv), env
    env = dict(env)
    if suffix == '.ps1':
        host = shutil.which('pwsh.exe') or shutil.which('powershell.exe')
        if not host:
            raise FileNotFoundError('PowerShell 脚本入口需要 powershell.exe')
        if Path(host).name.lower() == 'powershell.exe' and any(arg == '' or '"' in arg for arg in argv[1:]):
            raise ValueError('Windows PowerShell 5 无法可靠转发空值/引号参数；请使用 PowerShell 7 或直接 Node 入口')
        literal = lambda s: "'" + s.replace("'", "''") + "'"
        # Splat a named array. Passing an array expression directly nests it
        # inside the script's $args; npm shims using "$args" then collapse all
        # arguments into one native argument (e.g. the directory "run --help").
        script = '$ecraArguments = @(' + ','.join(map(literal, argv[1:])) + '); & ' + literal(argv[0]) + ' @ecraArguments; exit $LASTEXITCODE'
        encoded = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
        return [host, '-NoLogo', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded], env
    if any(any(c in arg for c in ('"', '\r', '\n')) for arg in argv):
        raise ValueError('批处理入口不能可靠传递引号或换行参数；请使用正式 Node/PowerShell 自动化入口，提示词使用 stdin')
    host = str(Path(env.get('SystemRoot', r'C:\Windows'))/'System32/cmd.exe')
    words = []
    for i, arg in enumerate(argv):
        if not arg:
            words.append('""')
            continue
        # A forwarding batch file preserves the quotes in %*. Escape trailing
        # backslashes for the eventual native Windows argv decoder.
        env[f'ECRA_OC_ARG_{i}'] = re.sub(r'(\\+)$', r'\1\1', arg) if i else arg
        words.append(f'"%ECRA_OC_ARG_{i}%"')
    command = '"' + ' '.join(words) + '"'
    result = WindowsCommand([host, '/d', '/v:off', '/s', '/c', command])
    result.windows_command_line = subprocess.list2cmdline(result[:-1]) + ' ' + command
    return result, env


def identity(command):
    from .report_package import sha256
    files = []
    inputs = list(command)
    # Hash npm wrapper dependencies without bypassing their executable entry.
    entry = Path(command[0])
    if entry.suffix.lower() in {'.cmd', '.bat', '.ps1'}:
        package = entry.parent/'node_modules/opencode-ai'
        inputs.extend(str(package/name) for name in ('package.json', 'bin/opencode', 'bin/opencode.exe'))
    for arg in inputs:
        path = Path(arg)
        if path.is_absolute() and path.is_file():
            stat = path.stat()
            files.append(dict(path=str(path), sha256=sha256(path),
                              size=stat.st_size, mtime_ns=stat.st_mtime_ns))
    return dict(command=display_command(command), arguments_sha256=hashlib.sha256(
        json.dumps(list(command), ensure_ascii=False).encode()).hexdigest(), files=files)


def identity_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
