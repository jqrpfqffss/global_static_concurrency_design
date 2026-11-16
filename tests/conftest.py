"""Integration fixtures use the same workspace admission as app processes."""
import os
from pathlib import Path
import tempfile

import pytest


def pytest_configure(config):
    from ecra.workspace import managed_root
    parent = managed_root()/'data-roots'
    parent.mkdir(parents=True, exist_ok=True)
    config._ecra_fixture = tempfile.TemporaryDirectory(prefix='qa-', dir=parent, ignore_cleanup_errors=True)
    if config.option.basetemp is None:
        config.option.basetemp = str(Path(config._ecra_fixture.name)/'p')


def pytest_unconfigure(config):
    if getattr(config, '_ecra_fixture', None):
        config._ecra_fixture.cleanup()


@pytest.fixture(autouse=True)
def workspace_scratch(tmp_path_factory, monkeypatch):
    from ecra import runtime_storage
    scratch = tmp_path_factory.mktemp('t')
    monkeypatch.setattr(tempfile, 'tempdir', str(scratch))
    monkeypatch.setattr(runtime_storage, '_process_temp', None)
    for key in runtime_storage.TEMP_KEYS:
        monkeypatch.setenv(key, str(scratch))
    monkeypatch.setenv('ECRA_DATA_ROOT', str(scratch/'data'))
    # Test reviews never use a workstation account's model settings or tokens.
    monkeypatch.setenv('XDG_CONFIG_HOME', str(scratch/'opencode-config-input'))
    monkeypatch.setenv('XDG_DATA_HOME', str(scratch/'opencode-data-input'))
    monkeypatch.setenv('PYTHONDONTWRITEBYTECODE', '1')
