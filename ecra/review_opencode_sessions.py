"""Local launch context and optional, ownership-checked session maintenance."""
import base64
from contextlib import closing, contextmanager
import http.client
import json
import os
from pathlib import Path
import re
import stat
import subprocess
from tempfile import TemporaryDirectory
import time
from urllib.parse import urlencode
import uuid

from .review_process import ReviewStop, owned_process
from .common import write_json
from .workspace import canonical, managed_path, no_links
from .opencode_protocol import (AuthenticationRequired, ProtocolError, interactive_prompt,
                                parse_json, protocol_text)


SESSION_ID = re.compile(r'ses_[0-9a-f]{12}[0-9A-Za-z]{14}')
PART_TYPES = dict(text='text', tool_use='tool', step_start='step-start',
                  step_finish='step-finish', reasoning='reasoning')
MAINTENANCE_TIMEOUT = 60
REQUEST_TIMEOUT = 3


class Unverifiable(ValueError):
    """Ownership, process scope or the protocol could not be proved."""
    code = 'protocol_unverified'


class Unavailable(OSError):
    """A verified operation may be retried without rerunning the model."""
    code = 'startup_failed'


class DatabaseIncompatible(Unverifiable):
    code = 'database_incompatible'


class DatabaseUnavailable(Unavailable):
    code = 'database_unavailable'


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
    if not stat.S_ISREG(st.st_mode) or not st.st_ino or st.st_nlink != 1:
        raise Unverifiable(f'OpenCode 存储必须是本地普通文件且不能有硬链接: {path}')
    return [st.st_dev, st.st_ino]


def store_identity(database, *, allow_missing=False):
    sidecars = False
    for suffix in ('-wal', '-shm', '-journal'):
        try:
            file_identity(database.with_name(database.name + suffix))
        except FileNotFoundError:
            continue  # SQLite may create or remove a sidecar between calls.
        sidecars = True
    try:
        return file_identity(database)
    except FileNotFoundError as exc:
        if not allow_missing:
            raise
        if sidecars:
            raise Unverifiable(f'OpenCode 会话数据库缺少主文件且存在伴随文件: {database}') from exc
        return None


class Runtime:
    def __init__(self, command, *, timeout=MAINTENANCE_TIMEOUT, stop=None):
        import math
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('review.maintenance_timeout_seconds 必须大于 0')
        self.timeout, self.stop = timeout, stop or ReviewStop()
        from .opencode_command import resolve_command, identity, identity_hash
        self.command = resolve_command(command)
        self.exe = Path(self.command[0])
        self.entry_identity = identity(self.command)
        self.hash = identity_hash(self.entry_identity)
        self.context = {}
        self.version = None
        self.product = None
        self.adapter = 'local-jsonl-v1'
        self.capabilities = dict(initialization='NOT_TESTED', authentication='AWAITING_FIRST_RUN', review='NOT_TESTED', storage='NOT_TESTED',
                                 cleanup='NOT_TESTED', compaction='NOT_TESTED')

    def check_exe(self):
        from .opencode_command import identity
        if identity(self.command) != self.entry_identity:
            raise Unverifiable('OpenCode 程序在复核期间变化')

    @contextmanager
    def maintenance(self, database, *, workdir, shared=False, environment=None, scope=None, data=None):
        from .opencode_storage import database_path, isolated_environment
        from .workspace import control_path
        database = database_path(database, shared=shared)
        # CreateProcess rejects overly long current directories even when
        # Python/Bun can open the corresponding files. Recovery adds another
        # journal/probe level, so keep process cwd separate from diagnostics.
        scratch = control_path('opencode-maintenance')
        scratch.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix='m-', dir=scratch, ignore_cleanup_errors=True) as name:
            cwd = Path(name)
            source = self.context.get('environment', os.environ) if environment is None else environment
            env = isolated_environment(scope or self.context.get('scope', cwd), cwd, database,
                                       shared=shared, environment=source, data=data or self.context.get('data'))
            env.update(OPENCODE_DISABLE_MODELS_FETCH='true',
                       OPENCODE_SERVER_USERNAME='ecra', OPENCODE_SERVER_PASSWORD=uuid.uuid4().hex)
            yield Maintenance(self, cwd, env, database, shared=shared,
                              diagnostics=managed_path(workdir)/'maintenance-logs'/cwd.name)

    def report(self):
        from .opencode_command import display_command
        return dict(command=display_command(self.command), identity=self.entry_identity, product=self.product, version=self.version,
                    adapter=self.adapter, capabilities=self.capabilities, version_status="NOT_QUERIED")

    def validate_run(self, raw):
        from .opencode_protocol import validate_run
        sid = validate_run(raw)
        self.capabilities['review'] = 'PASSED'
        self.capabilities['authentication'] = 'PASSED'
        return sid


class Maintenance:
    def __init__(self, runtime, cwd, env, database, *, shared=False, diagnostics=None):
        self.runtime, self.cwd, self.env, self.database = runtime, cwd, env, database
        self.shared = shared
        self.diagnostics = managed_path(diagnostics or cwd/'maintenance-logs')
        self.last_stderr = ''

    def _redact(self, text):
        from .opencode_protocol import redactor
        return redactor(self.env)(text)

    @contextmanager
    def _operation(self, args, stage):
        """Keep diagnostics outside the scratch directory, including on stop."""
        self.runtime.stop.check()
        argv = self._argv(*args)
        target = self.diagnostics/uuid.uuid4().hex
        target.mkdir(parents=True)
        started = time.monotonic()
        from .opencode_command import display_command
        record = dict(stage=stage, argv=[self._redact(a) for a in display_command(argv)],
                      executable=str(self.runtime.exe), executable_sha256=self.runtime.entry_identity['files'][0]['sha256'],
                      entry_identity_sha256=self.runtime.hash,
                      product=self.runtime.product, version=self.runtime.version, adapter=self.runtime.adapter,
                      cwd=str(self.cwd), database=str(self.database), shared=self.shared,
                      timeout_seconds=self.runtime.timeout, started_at=time.time(),
                      environment_paths={k:self.env.get(k) for k in ('HOME', 'USERPROFILE', 'XDG_DATA_HOME',
                          'XDG_CONFIG_HOME', 'XDG_STATE_HOME', 'XDG_CACHE_HOME', 'TEMP', 'OPENCODE_DB')},
                      pid=None, first_output_seconds=None, outcome='starting', ecra_requested_reap=False,
                      returncode_before_reap=None, exited_before_reap=False)
        proc = None
        stdout_path, stderr_path = self.cwd/(target.name+'.out'), self.cwd/(target.name+'.err')
        try:
            with stdout_path.open('wb') as stdout, stderr_path.open('wb') as stderr:
                with owned_process(argv, cwd=self.cwd, env=self.env, stdout=stdout, stderr=stderr,
                                   stop=self.runtime.stop) as proc:
                    record.update(pid=proc.pid, launched_seconds=time.monotonic()-started, outcome='running')
                    try:
                        yield proc, stdout_path, stderr_path, record, started
                        record['outcome'] = 'completed'
                    finally:
                        record.update(returncode_before_reap=proc.poll(), exited_before_reap=proc.poll() is not None,
                                      ecra_requested_reap=proc.poll() is None, reap_started_seconds=time.monotonic()-started)
        except BaseException as exc:
            record['outcome'] = 'cancelled' if isinstance(exc, KeyboardInterrupt) else 'failed'
            record['error'] = self._redact(str(exc))
            record['error_code'] = getattr(exc, 'code', 'startup_failed')
            if isinstance(exc, subprocess.TimeoutExpired):
                record['outcome'] = 'timeout'
                record['error_code'] = 'startup_timeout'
                raise Unavailable(f'OpenCode 维护步骤 {stage} 超时；命令 {record["argv"]}；'
                                  f'等待 {self.runtime.timeout:g} 秒；程序 {self.runtime.exe}；'
                                  f'数据库 {self.database}；详细日志 {target}') from exc
            raise
        finally:
            record.update(elapsed_seconds=time.monotonic()-started, finished_at=time.time(),
                          returncode=proc.returncode if proc else None,
                          process_exited=proc.returncode is not None if proc else None)
            for name, path in [('stdout', stdout_path), ('stderr', stderr_path)]:
                raw = path.read_text('utf-8', errors='replace') if path.exists() else ''
                (target/(name+'.log')).write_text(self._redact(raw), encoding='utf-8')
            write_json(target/'invocation.json', record)

    def _observe(self, stdout, stderr, record, started):
        self.runtime.stop.check()
        self._first_output(stdout, stderr, record, started)
        # Maintenance commands are noninteractive contracts. Match the known
        # complete prompt, not arbitrary words such as “login” in model text.
        for path in (stdout, stderr):
            with path.open('rb') as stream:
                raw = stream.read(65536)
            if interactive_prompt(raw.decode('utf-8', errors='replace')):
                raise AuthenticationRequired('OpenCode 维护阶段要求输入域账号；请使用发行版正式登录入口，诊断：' + str(self.diagnostics))
        if time.monotonic()-started >= self.runtime.timeout:
            raise subprocess.TimeoutExpired(record['argv'], self.runtime.timeout)

    def _first_output(self, stdout, stderr, record, started):
        if record['first_output_seconds'] is not None:
            return
        # Windows directory metadata may retain a zero size while the child
        # still owns the write handle. Observe bytes, not a directory listing.
        for path in (stdout, stderr):
            with path.open('rb') as stream:
                if stream.read(1):
                    record['first_output_seconds'] = time.monotonic()-started
                    return

    def _argv(self, *args):
        self.runtime.check_exe()
        return [*self.runtime.command, *args]

    def cli(self, *args):
        stage = ' '.join(args)
        with self._operation(args, stage) as (proc, stdout, stderr, record, started):
            while proc.poll() is None:
                self._observe(stdout, stderr, record, started)
                try:
                    proc.wait(timeout=.05)
                except subprocess.TimeoutExpired:
                    pass
            record['exit_seconds'] = time.monotonic()-started
            self._first_output(stdout, stderr, record, started)
            self.last_stderr = stderr.read_text('utf-8-sig')
            output = stdout.read_text('utf-8-sig')
            if interactive_prompt(output) or interactive_prompt(self.last_stderr):
                raise AuthenticationRequired('OpenCode 要求交互域认证；请通过发行版正式登录入口续期；诊断：' + str(self.diagnostics))
            if proc.returncode != 0:
                detail = self._redact((stderr.read_text('utf-8', errors='replace').strip()
                                      or stdout.read_text('utf-8', errors='replace').strip())[:8192])
                raise Unavailable(f'OpenCode 维护步骤 {stage} 失败（退出码 {proc.returncode}，'
                                  f'程序 {self.runtime.exe}，数据库 {self.database}）；'
                                  f'详细日志 {self.diagnostics}：{detail}')
            return output.strip()

    def verify(self):
        """Only called for requested maintenance, after a real run/archival."""
        self.runtime.check_exe()
        identity = store_identity(self.database)
        self.verify_path(protocol_text(self.cli('db', 'path')))
        self.opened_database()
        if store_identity(self.database) != identity:
            raise Unverifiable(f'OpenCode 会话数据库已更换: {self.database}')
        return identity

    def verify_path(self, actual):
        if not isinstance(actual, str) or not Path(actual).is_absolute() or canonical(actual) != canonical(self.database):
            raise Unverifiable(f'OpenCode 会话数据库路径不一致，预期 {self.database}，实际 {actual!r}')

    def prepare(self):
        """Compatibility entry for local preparation; never starts OpenCode."""
        self.runtime.check_exe()
        return store_identity(self.database, allow_missing=True)

    def opened_database(self):
        raw = self.cli('db', '--format', 'json', 'PRAGMA database_list')
        try:
            actual, = [row['file'] for row in parse_json(raw) if row['name'] == 'main']
        except (ValueError, KeyError, TypeError) as exc:
            raise Unverifiable('OpenCode 未报告已打开的主数据库路径') from exc
        self.verify_path(actual)

    def checkpoint(self):
        if self.shared:
            raise Unverifiable('强制 WAL 写回仅适用于 ECRA 管理的独立会话库')
        raw = self.cli('db', '--format', 'json', 'PRAGMA wal_checkpoint(TRUNCATE)')
        if parse_json(raw) != [{'busy': 0, 'log': 0, 'checkpointed': 0}]:
            raise Unavailable('OpenCode 独立会话库的 WAL 未完成写回')

    def compact(self):
        # Official CLI maintenance, on the private store only. The API, never
        # SQL, removes sessions. v1.18.35 can leave the compacted pages in
        # its WAL when the CLI exits, so also request a truncating checkpoint.
        if self.shared:
            raise Unverifiable('压缩仅适用于 ECRA 管理的独立会话库')
        self.cli('db', 'VACUUM')
        self.checkpoint()
        self.runtime.capabilities['compaction'] = 'PASSED'

    @contextmanager
    def server(self):
        self.verify()
        # The startup line names the port selected by the owned launcher.
        args = ('serve', '--hostname', '127.0.0.1', '--port', '0')
        with self._operation(args, 'serve readiness') as operation:
            yield from self._open_api(*operation)

    def _open_api(self, proc, log_path, stderr, record, started):
        listen = re.compile(rb'^opencode server listening on http://127\.0\.0\.1:([1-9][0-9]{0,4})\r?$', re.M)
        with log_path.open('rb') as stream:
            while proc.poll() is None:
                self._observe(log_path, stderr, record, started)
                stream.seek(0)
                match = listen.search(stream.read(65536))
                if match and (port := int(match[1])) <= 65535:
                    api = API(port, self.env['OPENCODE_SERVER_PASSWORD'], alive=lambda: proc.poll() is None)
                    api.verify()
                    self.runtime.capabilities['cleanup'] = 'API_VERIFIED'
                    record['ready_seconds'] = time.monotonic()-started
                    yield api
                    return
                time.sleep(.05)
        raise Unavailable(f'无法启动本次任务的 OpenCode 回环维护服务；退出码 {proc.returncode}；'
                          f'程序 {self.runtime.exe}；数据库 {self.database}；详细日志 {self.diagnostics}')


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
        if not isinstance(health, dict) or health.get('healthy') is not True:
            raise Unverifiable('OpenCode 回环服务未报告健康状态')
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
