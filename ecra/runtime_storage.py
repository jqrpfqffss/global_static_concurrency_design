"""Process-local scratch for Python, SQLite and ECRA's child processes."""
import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path
from threading import Lock

from .workspace import control_path, managed_path, studio_data_root


TEMP_KEYS = ('TEMP', 'TMP', 'TMPDIR', 'SQLITE_TMPDIR')
_process_temp = None
_lock = Lock()


def temporary_environment(directory, environment=None):
    directory = managed_path(directory, label='ECRA 临时目录')
    if not directory.is_dir():
        raise ValueError(f'ECRA 临时目录不存在: {directory}')
    env = dict(os.environ if environment is None else environment)
    env.update(dict.fromkeys(TEMP_KEYS, str(directory)))
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    env.pop('PYTHONPYCACHEPREFIX', None)
    # Compiler launchers can otherwise use a per-user cache even with TEMP set.
    env['CCACHE_DIR'] = str(directory/'ccache')
    env['CCACHE_TEMPDIR'] = str(directory/'ccache-tmp')
    env['SCCACHE_DIR'] = str(directory/'sccache')
    # An existing shared sccache daemon retains the environment it started with.
    env['SCCACHE_NO_DAEMON'] = '1'
    return env


def initialize(data=None, *, directory=None):
    """Run before imports or handlers that may need a default scratch path."""
    global _process_temp
    if data is not None:
        studio_data_root(data)
    from .portable import alias_root, bundle_root
    alias_root()  # Validate an explicit alias override even before the first build.
    bundle_root()
    config = os.environ.get('ECRA_CONFIG_HOME')
    if config and (not Path(config).is_absolute() or not Path(config).is_dir()):
        raise ValueError(f'ECRA_CONFIG_HOME 必须指向可读取的已有绝对配置目录: {config}')
    with _lock:
        if directory is None and _process_temp is None:
            base = control_path('tmp')
            base.mkdir(parents=True, exist_ok=True)
            directory = Path(tempfile.mkdtemp(prefix='p-', dir=base))
            atexit.register(shutil.rmtree, directory, ignore_errors=True)
        directory = managed_path(directory if directory is not None else _process_temp)
        env = temporary_environment(directory)
        os.environ.update({key: env[key] for key in TEMP_KEYS})
        os.environ["PYTHONDONTWRITEBYTECODE"] = '1'
        sys.dont_write_bytecode = True
        # tempfile may have resolved and cached the user's TEMP before startup.
        tempfile.tempdir = str(directory)
        _process_temp = directory
    if data is not None:
        from .data_transfer import register_location
        register_location(data)
    return directory


def child_environment(environment=None):
    """Respect a caller's isolated task scratch once process storage is active."""
    env = dict(os.environ if environment is None else environment)
    if _process_temp is not None:
        scratch = env.get('TEMP') or _process_temp
        return temporary_environment(scratch, env)
    return env
