"""Local OpenCode 1.18.35 paths and read-only import of provider settings."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile, TemporaryDirectory
import uuid

from .common import read_json, replace_file, write_json
from .runtime_storage import temporary_environment
from .storage_activity import DataActivity
from .workspace import control_path, managed_path


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


def isolated_environment(scope, scratch, database, *, environment=None, data=None):
    """Every write-bearing path is set before OpenCode loads its global module."""
    scope, scratch, database = map(managed_path, (scope, scratch, database))
    data = managed_path(data) if data is not None else scope/'data'
    temporary = managed_path(scratch/'tmp')
    temporary.mkdir()
    env = temporary_environment(temporary, environment)
    # Clear write redirects and keep provider credentials from the environment.
    inherited = {'OPENCODE_AUTH_CONTENT', 'OPENCODE_DISABLE_MODELS_FETCH', 'OPENCODE_MODELS_URL',
                 'OPENCODE_MODELS_PATH', 'OPENCODE_CONSOLE_TOKEN', 'OPENCODE_DISABLE_DEFAULT_PLUGINS'}
    for key in list(env):
        if key.upper().startswith('OPENCODE_') and key.upper() not in inherited:
            del env[key]
    env.update(
        XDG_DATA_HOME=str(data), XDG_CONFIG_HOME=str(scope/'config'),
        XDG_STATE_HOME=str(scope/'state'), XDG_CACHE_HOME=str(scope/'cache'),
        XDG_RUNTIME_DIR=str(temporary), HOME=str(scratch), USERPROFILE=str(scratch),
        LOCALAPPDATA=str(scratch/'local'), APPDATA=str(scratch/'roaming'),
        OPENCODE_TEST_HOME=str(scratch), OPENCODE_DB=str(database),
        OPENCODE_TEST_MANAGED_CONFIG_DIR=str(scope/'managed-config'),
        OPENCODE_DISABLE_PROJECT_CONFIG='true', OPENCODE_DISABLE_AUTOUPDATE='true',
        OPENCODE_PURE='true', OPENCODE_DISABLE_FFF='true',
        # Discovery starts at the nearest .git even with project config off.
        # An explicit private, nonexistent GIT_DIR keeps it from writing
        # OpenCode's project identity file in the tool or firmware Git metadata.
        GIT_DIR=str(scratch/'no-git'), GIT_OPTIONAL_LOCKS='0',
        BUN_INSTALL=str(scope/'cache/bun'), BUN_INSTALL_CACHE_DIR=str(scope/'cache/bun/install'),
        NPM_CONFIG_CACHE=str(scope/'cache/npm'), NPM_CONFIG_PREFIX=str(scope/'cache/npm-prefix'),
        NPM_CONFIG_USERCONFIG=str(scope/'config/npmrc'), NPM_CONFIG_GLOBALCONFIG=str(scope/'config/npmrc'),
    )
    if os.name == 'nt':
        env.update(HOMEDRIVE=scratch.drive, HOMEPATH=str(scratch)[len(scratch.drive):])
    return env


class ReviewStorage:
    def __init__(self, out, *, project=None, progress=print):
        self.environment = os.environ.copy()
        override = self.environment.get('OPENCODE_DB')
        if override:
            try:
                managed_path(override, label='OPENCODE_DB')
            except ValueError as exc:
                raise ValueError(f'{exc} ECRA 为每轮复核分配独立会话库。'
                                 '请在启动 ECRA 的环境中移除 OPENCODE_DB，保留原 OpenCode 会话库。') from exc
            progress(f'检测到 OPENCODE_DB={override}。本轮复核使用 ECRA 分配的独立会话库。')
        self.scope = managed_path(Path(out)/'opencode'/uuid.uuid4().hex)
        self.scope.mkdir(parents=True)
        self.database = self.scope/'sessions.db'
        home = Path.home()
        config = _xdg_input(self.environment, 'XDG_CONFIG_HOME', home/'.config')/'opencode'
        auth = _xdg_input(self.environment, 'XDG_DATA_HOME', home/'.local/share')/'opencode/auth.json'
        profile = hashlib.sha256(os.path.normcase(str(auth.resolve())).encode()).hexdigest()[:24]
        self.data = control_path('opencode', profile, 'data')
        for folder, directories, files in os.walk(self.data, followlinks=False):
            for name in directories + files:
                managed_path(Path(folder)/name)
        self._seed_auth(auth)
        paths = [config/name for name in _CONFIG_FILES]
        explicit = self.environment.get('OPENCODE_CONFIG')
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
        config = managed_path(self.scope/'config/opencode')
        config.mkdir(parents=True)
        # Keep OpenCode's config layering without loading external MCP servers,
        # plugins or commands. The files used by OpenCode are private copies.
        layers = [_settings(path, home) for path in paths if path.is_file()]
        # OpenCode inserts the schema in place when it is absent. Populate it
        # before workers start so they never read a partly rewritten config.
        merged = {'$schema': 'https://opencode.ai/config.json'}
        for layer in layers:
            for key, value in layer.items():
                if key == 'provider' and isinstance(value, dict):
                    _merge(merged.setdefault(key, {}), value)
                else:
                    merged[key] = value
        write_json(config/'opencode.json', merged)

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
        with TemporaryDirectory(prefix='c-', dir=self.scope, ignore_cleanup_errors=True) as name:
            cwd = Path(name)
            yield cwd, isolated_environment(self.scope, cwd, self.database,
                                            environment=self.environment, data=self.data)


def _merge(destination, source):
    for key, value in source.items():
        if isinstance(destination.get(key), dict) and isinstance(value, dict):
            _merge(destination[key], value)
        else:
            destination[key] = value
