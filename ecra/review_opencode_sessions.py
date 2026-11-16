"""OpenCode 1.18.35's local run protocol and private maintenance API."""
import base64
from contextlib import closing, contextmanager
import http.client
import json
import os
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory, TemporaryFile
import time
from urllib.parse import urlencode
import uuid

from .report_package import sha256
from .review_process import owned_process
from .workspace import canonical, managed_path, no_links


# Pinned to the release whose local (non-attach) run, DB override, JSONL
# protocol and recursive delete have been checked against source and runtime.
VERSION = '1.18.35'
SESSION_ID = re.compile(r'ses_[0-9a-f]{12}[0-9A-Za-z]{14}')
PART_TYPES = dict(text='text', tool_use='tool', step_start='step-start',
                  step_finish='step-finish', reasoning='reasoning')
STARTUP_TIMEOUT = 10
REQUEST_TIMEOUT = 3


class Unverifiable(ValueError):
    """Ownership, process scope or the protocol could not be proved."""


class Unavailable(OSError):
    """A verified operation may be retried without rerunning the model."""


class DeleteFailed(RuntimeError):
    """The service is reachable but this session was not deleted."""


def _unique_json(pairs):
    obj = dict(pairs)
    if len(obj) != len(pairs):
        raise Unverifiable('JSON 对象含重复字段')
    return obj


def session_from_jsonl(raw):
    """Use only CLI envelopes. Never search text, tool output or nested IDs."""
    ids, invalid = set(), False
    for line in raw.split('\n'):
        try:
            event = json.loads(line, object_pairs_hook=_unique_json)
        except (ValueError, RecursionError):
            # A truncated or ambiguous envelope is not a usable transcript.
            if line.lstrip().startswith('{'):
                invalid = True
            continue
        if not isinstance(event, dict):
            continue
        kind = event.get('type')
        if not isinstance(kind, str) or kind not in (*PART_TYPES, 'error'):
            continue
        sid = event.get('sessionID')
        if isinstance(sid, str) and SESSION_ID.fullmatch(sid):
            ids.add(sid)
        else:
            invalid = True
        if type(event.get('timestamp')) is not int:
            invalid = True
        if kind == 'error':
            error = event.get('error')
            if not isinstance(error, dict) or not isinstance(error.get('name'), str):
                invalid = True
        else:
            part = event.get('part')
            if (not isinstance(part, dict) or part.get('type') != PART_TYPES[kind]
                    or part.get('sessionID') != sid):
                invalid = True
    if len(ids) > 1:
        return None, ids, '同一调用含多个顶层 Session ID'
    if invalid:
        return None, ids, 'OpenCode JSONL 会话事件不完整或身份无效'
    if not ids:
        return None, ids, 'OpenCode JSONL 未提供顶层 Session ID'
    return next(iter(ids)), ids, ''


def file_identity(path):
    st = no_links(path).stat()
    if not path.is_file() or not st.st_ino or st.st_nlink != 1:
        raise Unverifiable('OpenCode 存储不是可确认的本地独立文件')
    return [st.st_dev, st.st_ino]


class Runtime:
    def __init__(self, command):
        if len(command) != 1:
            raise Unverifiable('仅支持直接调用原生 OpenCode；保留自定义启动器的会话')
        self.exe = Path(command[0]).resolve(strict=True)
        with self.exe.open('rb') as source:
            magic = source.read(4)
        if not (magic.startswith(b'MZ') if os.name == 'nt'
                else magic in {b'\x7fELF', b'\xcf\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xca\xfe\xba\xbe'}):
            raise Unverifiable('无法确认 OpenCode 原生程序')
        self.hash = sha256(self.exe)
        self.stat = self.exe.stat()

    def check_exe(self):
        st = self.exe.stat()
        keys = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns')
        if any(getattr(st, k) != getattr(self.stat, k) for k in keys):
            raise Unverifiable('OpenCode 程序在复核期间变化')

    @contextmanager
    def maintenance(self, database):
        from .opencode_storage import isolated_environment
        database = managed_path(database, label='OpenCode 会话数据库')
        with TemporaryDirectory(prefix='m-', dir=database.parent, ignore_cleanup_errors=True) as name:
            cwd = Path(name)
            env = {k: v for k, v in os.environ.items() if not k.upper().startswith('OPENCODE_')}
            env = isolated_environment(cwd, cwd, database, environment=env)
            env.update(OPENCODE_DISABLE_MODELS_FETCH='true', OPENCODE_DISABLE_DEFAULT_PLUGINS='true',
                       OPENCODE_SERVER_USERNAME='ecra', OPENCODE_SERVER_PASSWORD=uuid.uuid4().hex)
            yield Maintenance(self, cwd, env, database)


class Maintenance:
    def __init__(self, runtime, cwd, env, database):
        self.runtime, self.cwd, self.env, self.database = runtime, cwd, env, database

    def _argv(self, *args):
        self.runtime.check_exe()
        return [str(self.runtime.exe), '--pure', *args]

    def cli(self, *args):
        with TemporaryFile(dir=self.cwd) as stdout, TemporaryFile(dir=self.cwd) as stderr:
            with owned_process(self._argv(*args), cwd=self.cwd, env=self.env, stdout=stdout, stderr=stderr) as proc:
                try:
                    proc.wait(timeout=STARTUP_TIMEOUT)
                except subprocess.TimeoutExpired as exc:
                    raise Unavailable('OpenCode 维护命令超时') from exc
            if proc.returncode != 0:
                raise Unavailable('OpenCode 维护命令失败')
            stdout.seek(0)
            return stdout.read(65536).decode('utf-8').strip()

    def verify(self):
        if self.cli('--version') != VERSION:
            raise Unverifiable(f'当前目录隔离协议仅验证过 OpenCode {VERSION}；请使用此版本的原生程序')
        if canonical(self.cli('db', 'path')) != canonical(self.database):
            raise Unverifiable('OpenCode 未使用本次任务的独立会话库')

    def checkpoint(self):
        raw = self.cli('db', '--format', 'json', 'PRAGMA wal_checkpoint(TRUNCATE)')
        if json.loads(raw, object_pairs_hook=_unique_json) != [{'busy': 0, 'log': 0, 'checkpointed': 0}]:
            raise Unavailable('OpenCode 独立会话库的 WAL 未完成写回')

    def compact(self):
        # Official CLI maintenance, on the private store only. The API, never
        # SQL, removes sessions. v1.18.35 can leave the compacted pages in
        # its WAL when the CLI exits, so also request a truncating checkpoint.
        self.cli('db', 'VACUUM')
        self.checkpoint()

    @contextmanager
    def server(self):
        # The startup line names the port selected by the owned launcher.
        with (self.cwd/'server.out').open('wb') as stdout, TemporaryFile(dir=self.cwd) as stderr:
            with owned_process(self._argv('serve', '--hostname', '127.0.0.1', '--port', '0'),
                               cwd=self.cwd, env=self.env, stdout=stdout, stderr=stderr) as proc:
                yield from self._open_api(proc, self.cwd/'server.out')

    def _open_api(self, proc, log_path):
        deadline = time.monotonic() + STARTUP_TIMEOUT
        listen = re.compile(rb'^opencode server listening on http://127\.0\.0\.1:([1-9][0-9]{0,4})\r?$', re.M)
        with log_path.open('rb') as stream:
            while proc.poll() is None and time.monotonic() < deadline:
                stream.seek(0)
                match = listen.search(stream.read(65536))
                if match and (port := int(match[1])) <= 65535:
                    api = API(port, self.env['OPENCODE_SERVER_PASSWORD'], alive=lambda: proc.poll() is None)
                    api.verify()
                    yield api
                    return
                time.sleep(.05)
        raise Unavailable('无法启动本次任务的 OpenCode 回环维护服务')


class API:
    def __init__(self, port, password, *, alive=None):
        self.port = port
        self.authorization = 'Basic ' + base64.b64encode(f'ecra:{password}'.encode()).decode()
        self.alive = alive

    def request(self, method, path, cwd=None, *, allow_missing=False):
        if self.alive is not None and not self.alive():
            raise Unavailable('本次任务的 OpenCode 回环服务已退出')
        if cwd is not None:
            path += '?' + urlencode(dict(directory=cwd))
        # HTTPConnection does not read proxy settings or follow redirects.
        try:
            with closing(http.client.HTTPConnection('127.0.0.1', self.port, timeout=REQUEST_TIMEOUT)) as conn:
                conn.request(method, path, headers={'Authorization': self.authorization, 'Accept': 'application/json'})
                with conn.getresponse() as response:
                    status = response.status
                    if status != 200 and not (allow_missing and status == 404):
                        raise DeleteFailed(f'OpenCode 维护接口 HTTP {status}')
                    if response.headers.get_content_type() != 'application/json':
                        raise Unverifiable('OpenCode 维护接口未返回 JSON')
                    raw = response.read(2**20 + 1)
        except (OSError, http.client.HTTPException) as exc:
            raise Unavailable('OpenCode 维护接口不可用或超时') from exc
        if len(raw) > 2**20:
            raise Unverifiable('OpenCode 维护响应超过上限')
        try:
            value = json.loads(raw, object_pairs_hook=_unique_json)
        except (ValueError, RecursionError) as exc:
            raise Unverifiable('OpenCode 维护响应格式无效') from exc
        if status == 404:
            if not (isinstance(value, dict) and value.get('name') == 'NotFoundError'):
                raise Unverifiable('无法确认 OpenCode 的会话不存在响应')
            return None
        if value is None:
            raise Unverifiable('OpenCode 维护响应缺少结果')
        return value

    def verify(self):
        # Refuse an unsecured or unrelated service before asking about IDs.
        try:
            with closing(http.client.HTTPConnection('127.0.0.1', self.port, timeout=REQUEST_TIMEOUT)) as conn:
                conn.request('GET', '/session/status')
                with conn.getresponse() as response:
                    if response.status != 401:
                        raise Unverifiable('OpenCode 回环服务未要求本次任务的认证')
        except (OSError, http.client.HTTPException) as exc:
            raise Unavailable('无法验证 OpenCode 回环服务认证') from exc
        health = self.request('GET', '/global/health')
        if health != dict(healthy=True, version=VERSION):
            raise Unverifiable('OpenCode 回环服务身份或版本不匹配')
        spec = self.request('GET', '/doc')
        paths = spec.get('paths', {}) if isinstance(spec, dict) else {}
        expected = {
            '/session/{sessionID}': {'get': 'session.get', 'delete': 'session.delete'},
            '/session/{sessionID}/children': {'get': 'session.children'},
            '/session/status': {'get': 'session.status'},
            '/project/current': {'get': 'project.current'},
        }
        for route, methods in expected.items():
            for method, operation in methods.items():
                try:
                    declared = paths[route][method]['operationId']
                except (KeyError, TypeError):
                    declared = None
                if declared != operation:
                    raise Unverifiable('OpenCode 未公布所需的会话接口')

    def delete_owned(self, sid, *, title, cwd, project_id, assert_scope):
        if not SESSION_ID.fullmatch(sid):
            raise Unverifiable('Session ID 无效')
        route = '/session/' + sid
        # Using the maintenance instance directory avoids creating watchers or
        # loading any project config for a review's (possibly removed) cwd.
        info = self.request('GET', route, allow_missing=True)
        if info is None:
            return
        directory = info.get('directory') if isinstance(info, dict) else None
        if (not isinstance(directory, str) or not Path(directory).is_absolute()
                or info.get('id') != sid or info.get('title') != title or canonical(directory) != cwd
                or info.get('version') != VERSION
                or info.get('parentID') is not None or info.get('workspaceID') is not None):
            raise Unverifiable('会话身份、工作目录或父会话不匹配')
        if project_id is None:
            project = self.request('GET', '/project/current', cwd)
            project_id = project.get('id') if isinstance(project, dict) else None
        if not project_id or info.get('projectID') != project_id:
            raise Unverifiable('会话不属于本次 OpenCode 项目')
        status = self.request('GET', '/session/status')
        # This map only describes the maintenance process. The caller has
        # independently proved the original in-process run has terminated.
        if not isinstance(status, dict):
            raise Unverifiable('无法确认 OpenCode 会话状态')
        if sid in status and status[sid] != {'type': 'idle'}:
            raise DeleteFailed('OpenCode 会话状态不是空闲')
        if self.request('GET', route + '/children') != []:
            raise Unverifiable('会话存在未验证的子会话')
        assert_scope()
        if self.request('DELETE', route) is not True:
            raise DeleteFailed('OpenCode 未确认删除')
        if self.request('GET', route, allow_missing=True) is not None:
            raise DeleteFailed('OpenCode 删除后仍能查询到会话')
