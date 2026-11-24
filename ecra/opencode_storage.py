"""Separate authorization inputs from workspace-owned OpenCode runtime writes."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from tempfile import NamedTemporaryFile, TemporaryDirectory
import uuid

from .common import read_json, replace_file, write_json
from .review_opencode_sessions import Unverifiable, store_identity
from .runtime_storage import temporary_environment
from .storage_activity import DataActivity, DataBusy
from .workspace import _local_path, control_path, managed_path, no_links


_CONFIG_FILES = ('config.json', 'opencode.json', 'opencode.jsonc')
_MODEL_FIELDS = {'provider', 'model', 'small_model', 'enabled_providers', 'disabled_providers'}
_JSONC = re.compile(r'"(?:\\.|[^"\\])*"|//[^\r\n]*|/\*[\s\S]*?\*/')
_TRAILING_COMMA = re.compile(r'"(?:\\.|[^"\\])*"|,(?=\s*[}\]])')
_FILE_REF = re.compile(r'\{file:([^}]+)\}')


def _settings(path, home):
    def original_file(match):
        reference = match[1]
        source = home/reference[2:] if reference.startswith('~/') else path.parent/reference
        return '{file:' + source.resolve().as_posix() + '}'

    try:
        text = path.read_text(encoding='utf-8-sig')
        text = _JSONC.sub(lambda m: m[0] if m[0].startswith('"') else ' ', text)
        text = _TRAILING_COMMA.sub(lambda m: m[0] if m[0].startswith('"') else '', text)
        value = json.loads(text)
        if not isinstance(value, dict):
            raise ValueError()
    except (UnicodeError, ValueError):
        raise ValueError(f'OpenCode 模型配置无法解析: {path}') from None

    def references(value):
        if isinstance(value, str):
            return _FILE_REF.sub(original_file, value)
        if isinstance(value, list):
            return [references(item) for item in value]
        if isinstance(value, dict):
            return {key: references(item) for key, item in value.items()}
        return value

    return references({key: value[key] for key in _MODEL_FIELDS if key in value})


def _xdg_input(env, key, default):
    path = Path(env.get(key) or default)
    if not path.is_absolute():
        raise ValueError(f'{key} 必须为绝对的只读 OpenCode 配置来源: {path}')
    return path


def database_path(value, *, shared=False):
    if not shared:
        return managed_path(value, label='OpenCode 会话数据库')
    path = no_links(_local_path(value, 'OPENCODE_DB'))
    if not path.parent.is_dir():
        raise ValueError(f'OPENCODE_DB 的上级目录不存在或不可访问: {path.parent}')
    return path


def isolated_environment(scope, scratch, database, *, shared=False, environment=None, data=None):
    """Every write-bearing path is set before OpenCode loads its global module."""
    scope, scratch = map(managed_path, (scope, scratch))
    database = database_path(database, shared=shared)
    data = managed_path(data if data is not None else scope/'data')
    temporary = managed_path(scratch/'tmp')
    temporary.mkdir()
    env = temporary_environment(temporary, environment)
    env.pop('PWD', None)  # OpenCode run uses PWD in preference to the process cwd.
    # Clear write redirects and keep provider credentials from the environment.
    # Only known configuration/service redirects are replaced. Enterprise
    # credential variables must not disappear just because of their prefix.
    for key in ('OPENCODE_CONFIG', 'OPENCODE_CONFIG_DIR', 'OPENCODE_CONFIG_CONTENT',
                'OPENCODE_PERMISSION', 'OPENCODE_SERVER_PASSWORD', 'OPENCODE_SERVER_USERNAME',
                'OPENCODE_ATTACH', 'OPENCODE_URL', 'OPENCODE_SERVER_URL', 'OPENCODE_PURE',
                'OPENCODE_PLUGIN_META_FILE'):
        env.pop(key, None)
    env.update(
        XDG_DATA_HOME=str(data), XDG_CONFIG_HOME=str(scope/'config'),
        XDG_STATE_HOME=str(scope/'state'), XDG_CACHE_HOME=str(scope/'cache'),
        XDG_RUNTIME_DIR=str(temporary), OPENCODE_DB=str(database),
        OPENCODE_TEST_MANAGED_CONFIG_DIR=str(scope/'managed-config'),
        OPENCODE_DISABLE_PROJECT_CONFIG='true', OPENCODE_DISABLE_AUTOUPDATE='true',
        OPENCODE_DISABLE_FFF='true',
        # Discovery starts at the nearest .git even with project config off.
        # An explicit private, nonexistent GIT_DIR keeps it from writing
        # OpenCode's project identity file in the tool or firmware Git metadata.
        GIT_DIR=str(scratch/'no-git'), GIT_OPTIONAL_LOCKS='0',
        BUN_INSTALL=str(scope/'cache/bun'), BUN_INSTALL_CACHE_DIR=str(scope/'cache/bun/install'),
        NPM_CONFIG_CACHE=str(scope/'cache/npm'), NPM_CONFIG_PREFIX=str(scope/'cache/npm-prefix'),
        NPM_CONFIG_USERCONFIG=str(scope/'config/npmrc'), NPM_CONFIG_GLOBALCONFIG=str(scope/'config/npmrc'),
    )
    # Keep the configured OS/enterprise login context. A fresh HOME per call
    # hides credentials used by distributions outside standard auth.json.
    # XDG state/cache, database and temporary writes remain workspace-owned.
    return env


def release_runtime(scope, *, retire=False, abandoned=False):
    """Only the dedicated vendor scratch tree can be retired. Sessions live beside it."""
    scope = managed_path(scope)
    if scope.parent.name != 'opencode' or not re.fullmatch('[0-9a-f]{32}', scope.name):
        raise ValueError('OpenCode 私有工作目录身份不符')
    work = managed_path(scope/'runtime')
    marker = managed_path(scope/'runtime-retired.json')
    owner = managed_path(scope/'runtime-owner.json')
    if retire and owner.is_file():
        # Closing the lease requires no new payload allocation on a full volume.
        try:
            replace_file(owner, marker)
        except OSError:
            marker = owner
    elif abandoned and not marker.exists():
        marker = owner
    if marker.is_file():
        record = read_json(marker)
        if record.get('scope') != scope.name or record.get('version') not in {1, 2}:
            raise ValueError('OpenCode 工作目录归属无效')
        targets = [(work, record.get('identity'))]
        if record['version'] == 2:
            targets.append((control_path('oc', scope.name[:16]), record.get('calls_identity')))
        for target, identity in targets:
            if target.exists():
                info = target.stat()
                if identity != [info.st_dev, info.st_ino] or not info.st_ino:
                    raise ValueError('OpenCode 工作目录已被替换，保留现场')
        for target, _ in targets:
            if target.exists():
                # rmtree unlinks child links without traversing them (including Windows junctions).
                shutil.rmtree(target)
        marker.unlink(missing_ok=True)


def retry_retired_runtime(out, progress):
    for scope in (out/'opencode').glob('*'):
        try:
            if not re.fullmatch('[0-9a-f]{32}', scope.name):
                continue
            # Windows launches both model and maintenance processes suspended
            # into KILL_ON_JOB_CLOSE jobs before letting them access scratch.
            abandoned = os.name == 'nt' and (scope/'runtime-owner.json').is_file()
            if not abandoned and not (scope/'runtime-retired.json').is_file():
                continue
            with DataActivity(managed_path(scope), exclusive=True):
                release_runtime(scope, abandoned=abandoned)
        except DataBusy:
            continue
        except (OSError, ValueError) as exc:
            progress(f'OpenCode 已结束的私有缓存保留待清理：{exc}')


class ReviewStorage:
    def __init__(self, out, *, project=None, environment=None, settings=None, lifetime=None):
        self.environment = dict(os.environ if environment is None else environment)
        self.settings = (settings or {}).get('runtime', {})
        override = self.environment.get('OPENCODE_DB')
        self.scope = managed_path(Path(out)/'opencode'/uuid.uuid4().hex)
        self.shared = bool(override)
        self.database = database_path(override, shared=True) if self.shared else self.scope/'sessions.db'
        from threading import Lock
        self._startup_lock = Lock()
        self.identity = None
        self.runtime = None
        self.scope.mkdir(parents=True)
        self.work = managed_path(self.scope/'runtime')
        self.work.mkdir()
        self.call_root = control_path('opencode-calls')
        if lifetime is not None:
            # Short CreateProcess cwd even for deeply nested portable scan paths.
            self.call_root = control_path('oc', self.scope.name[:16])
            self.call_root.mkdir(parents=True, exist_ok=False)
            from .review_archive import write_receipt
            lifetime.enter_context(DataActivity(self.scope, exclusive=True))
            info = self.work.stat()
            calls = self.call_root.stat()
            write_receipt(self.scope/'runtime-owner.json', dict(version=2, scope=self.scope.name,
                          identity=[info.st_dev, info.st_ino], calls_identity=[calls.st_dev, calls.st_ino]))
            lifetime.callback(self.close)
        home = Path(self.environment.get('USERPROFILE') or self.environment.get('HOME') or Path.home())
        config = _xdg_input(self.environment, 'XDG_CONFIG_HOME', home/'.config')/'opencode'
        auth = _xdg_input(self.environment, 'XDG_DATA_HOME', home/'.local/share')/'opencode/auth.json'
        if self.settings.get('auth_file'):
            auth = Path(self.settings['auth_file'])
            if not auth.is_absolute() or not auth.is_file():
                raise ValueError('review.runtime.auth_file 必须指向已有标准 OpenCode auth.json 的绝对路径')
        profile = hashlib.sha256(os.path.normcase(str(auth.resolve())).encode()).hexdigest()[:24]
        self.data = control_path('opencode', profile, 'data')
        for folder, directories, files in os.walk(self.data, followlinks=False):
            for name in directories + files:
                managed_path(Path(folder)/name)
        self._seed_auth(auth)
        paths = [config/name for name in _CONFIG_FILES]
        self.auth_source = str(auth) if auth.is_file() else None
        explicit = self.environment.get('OPENCODE_CONFIG')
        explicit = self.settings.get('config_file') or explicit
        if explicit:
            value = Path(explicit)
            if not value.is_absolute() or not value.is_file():
                raise ValueError(f'OPENCODE_CONFIG 必须指向现有文件的绝对路径: {value}')
            paths.append(value)
        if project is not None:
            paths.extend(Path(project)/name for name in _CONFIG_FILES[1:])
        extra = self.environment.get('OPENCODE_CONFIG_DIR')
        if extra:
            value = Path(extra)
            if not value.is_absolute() or not value.is_dir():
                raise ValueError(f'OPENCODE_CONFIG_DIR 必须指向现有配置目录的绝对路径: {value}')
            paths.extend(value/name for name in _CONFIG_FILES)
        config = managed_path(self.work/'config/opencode')
        config.mkdir(parents=True)
        # Keep OpenCode's config layering without loading external MCP servers,
        # plugins or commands. The files used by OpenCode are private copies.
        layers = [_settings(path, home) for path in paths if path.is_file()]
        self.config_sources = [str(path) for path in paths if path.is_file()]
        if self.environment.get('OPENCODE_CONFIG_CONTENT'):
            self.config_sources.append('OPENCODE_CONFIG_CONTENT')
        if self.environment.get('OPENCODE_CONFIG_CONTENT'):
            try:
                content = json.loads(self.environment['OPENCODE_CONFIG_CONTENT'])
                if not isinstance(content, dict):
                    raise ValueError()
            except (ValueError, TypeError):
                raise ValueError('OPENCODE_CONFIG_CONTENT 必须包含有效的 JSON 配置对象') from None
            layers.append({key:value for key,value in content.items() if key in _MODEL_FIELDS})
        # OpenCode inserts the schema in place when it is absent. Populate it
        # before workers start so they never read a partly rewritten config.
        merged = {'$schema': 'https://opencode.ai/config.json'}
        for layer in layers:
            for key, value in layer.items():
                if key == 'provider' and isinstance(value, dict):
                    _merge(merged.setdefault(key, {}), value)
                else:
                    merged[key] = value
        plugins = self.settings.get('auth_plugins', [])
        if plugins:
            merged['plugin'] = plugins
        if plugins:
            self.environment['OPENCODE_DISABLE_DEFAULT_PLUGINS'] = 'false'
        write_json(config/'opencode.json', merged)

    def prepare(self, runtime):
        """Local preparation only. The first OpenCode process is the real run."""
        runtime.context = dict(scope=self.work, data=self.data, environment=self.environment, startup=self.startup, scratch=self.call_root)
        self.runtime = runtime
        self.identity_error = None
        self.bind_identity()
        runtime.capabilities.update(initialization='LOCAL_READY', storage='UNVERIFIABLE' if self.identity_error
                                    else 'IDENTITY_BOUND' if self.identity else 'IDENTITY_PENDING')

    @contextmanager
    def startup(self, stop):
        # OpenCode opens/migrates its SQLite store at process startup. Allow one
        # opening at a time; streamed session identity releases the next worker.
        while not self._startup_lock.acquire(timeout=.1):
            stop.check()
        held = True
        def ready():
            nonlocal held
            if held:
                held = False
                self._startup_lock.release()
        try:
            stop.check()
            yield ready
        finally:
            ready()

    def close(self):
        try:
            release_runtime(self.scope, retire=True)
        except (OSError, ValueError) as exc:
            from .scan_diagnostics import diagnostic_log
            diagnostic_log(f'OpenCode 私有运行缓存待清理 {self.scope}：{exc}')

    def bind_identity(self):
        """Optional cleanup ownership; absence must never block a model call."""
        try:
            actual = store_identity(self.database, allow_missing=True)
            if self.identity is not None and actual != self.identity:
                raise Unverifiable(f'OpenCode 会话数据库已更换: {self.database}')
            self.identity = actual
        except (ValueError, OSError) as exc:
            self.identity_error = str(exc)
        return self.identity

    def _seed_auth(self, source):
        if self.environment.get('OPENCODE_AUTH_CONTENT') or not source.is_file():
            return
        target = managed_path(self.data/'opencode/auth.json')
        if source.resolve() == target:
            return
        raw = source.read_bytes()
        try:
            credentials = json.loads(raw)
            if not isinstance(credentials, dict):
                raise ValueError()
        except (ValueError, UnicodeError):
            raise ValueError(f'OpenCode 登录数据无法读取: {source}') from None
        seal = managed_path(self.data/'auth-source.json')
        hashed = hashlib.sha256(raw).hexdigest()
        with DataActivity(self.data, exclusive=True, wait=10):
            if target.is_file() and seal.is_file() and read_json(seal).get('sha256') == hashed:
                return  # Reuse OAuth refreshes saved by the isolated OpenCode processes.
            target.parent.mkdir(parents=True, exist_ok=True)
            pending = None
            try:
                with NamedTemporaryFile(prefix='auth-', dir=target.parent, delete=False) as stream:
                    pending = Path(stream.name)
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                replace_file(pending, target)
                write_json(seal, {'sha256': hashed})
            finally:
                if pending is not None:
                    pending.unlink(missing_ok=True)

    @contextmanager
    def call(self):
        self.call_root.mkdir(parents=True, exist_ok=True)
        scratch = TemporaryDirectory(prefix='c-', dir=self.call_root, ignore_cleanup_errors=True)
        cwd = Path(scratch.name)
        try:
            yield cwd, isolated_environment(self.work, cwd, self.database, shared=self.shared,
                                            environment=self.environment, data=self.data)
        finally:
            from .scan_diagnostics import diagnostic_log
            try:
                scratch.cleanup()
            except OSError as exc:
                diagnostic_log(f'调用工作目录保留待清理 {cwd}：{exc}')
            if cwd.exists():
                diagnostic_log(f'调用进程工作目录仍被占用，将按批次归属补偿清理：{cwd}')


def _merge(destination, source):
    for key, value in source.items():
        if isinstance(destination.get(key), dict) and isinstance(value, dict):
            _merge(destination[key], value)
        else:
            destination[key] = value
