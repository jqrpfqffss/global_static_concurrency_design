import hashlib
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile

import pytest

from ecra.data_transfer import preview, register_location, retired_roots, transfer
from ecra.portable import _junction, alias_root, build_path
from ecra.runtime_storage import TEMP_KEYS, initialize, temporary_environment
from ecra.studio_preferences import preview as preference_preview, save, startup_selection
from ecra.workspace import managed_path, studio_data_root


@pytest.fixture
def tool(tmp_path, monkeypatch):
    tool = tmp_path/'ecra'
    tool.mkdir()
    (tool/'.git').mkdir()
    monkeypatch.setattr('ecra.workspace.TOOL_ROOT', tool)
    monkeypatch.delenv('ECRA_DATA_ROOT', raising=False)
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path/'old-profile'))
    return tool


def test_default_ignores_cwd_and_replaces_cached_temporary_directory(tool, tmp_path, monkeypatch):
    other = tmp_path/'terminal'
    other.mkdir()
    monkeypatch.chdir(other)
    monkeypatch.setattr(tempfile, 'tempdir', str(other))
    assert startup_selection()['root'] == tool/'workspace'
    scratch = initialize(studio_data_root())
    assert scratch.is_relative_to(tool/'workspace')
    assert Path(tempfile.gettempdir()) == scratch
    assert all(Path(os.environ[key]) == scratch for key in TEMP_KEYS)
    one, two = scratch/'one', scratch/'two'
    one.mkdir()
    two.mkdir()
    assert temporary_environment(one)['TEMP'] != temporary_environment(two)['TEMP']
    assert not list(other.iterdir())
    assert not (tmp_path/'old-profile').exists()


@pytest.mark.skipif(os.name != 'nt', reason='Windows drives and Junctions')
def test_c_drive_and_junction_are_rejected_before_data_is_created(tool, tmp_path, monkeypatch):
    with monkeypatch.context() as options:
        options.setattr('ecra.workspace.TOOL_ROOT', Path(r'C:\Windows'))
        with pytest.raises(ValueError, match='当前工具位于 C 盘'):
            initialize()
    junction = tool/'workspace'
    _junction(junction, Path(r'C:\Windows'))
    try:
        with pytest.raises(ValueError, match='Junction'):
            initialize()
    finally:
        junction.rmdir()
    monkeypatch.setenv('ECRA_PATH_ALIAS_ROOT', str(tmp_path/'old-aliases'))
    with pytest.raises(ValueError, match='ECRA_PATH_ALIAS_ROOT'):
        initialize()
    assert not (tmp_path/'old-aliases').exists()


@pytest.mark.skipif(os.name != 'nt', reason='Windows build aliases')
def test_short_alias_does_not_fall_back_when_native_short_names_are_unavailable(tool, monkeypatch):
    renamed = tool.with_name('工具 中文 路径')
    tool.rename(renamed)
    monkeypatch.setattr('ecra.workspace.TOOL_ROOT', renamed)
    monkeypatch.setattr('ecra.portable._short_path', str)
    output = renamed/'workspace/projects/data/build'
    with pytest.raises(ValueError, match='短英文目录'):
        build_path(output, prefer_junction=True)
    assert alias_root() == renamed/'workspace/a'
    assert not any(alias_root().iterdir())


def test_saved_data_root_and_retired_location_follow_a_moved_tool(tool, monkeypatch):
    workspace = tool/'workspace'
    workspace.mkdir()
    target = workspace/'data-roots/history'
    plan = preference_preview(str(target), workspace)
    save(str(target), workspace, plan_id=plan['plan_id'], revision=plan['revision'])
    register_location(target)
    move = tool.with_name('moved')
    from ecra.common import replace_file
    replace_file(tool, move)
    monkeypatch.setattr('ecra.workspace.TOOL_ROOT', move)
    current = startup_selection()['root']
    assert current == move/'workspace/data-roots/history'
    register_location(current)
    assert target in retired_roots(current)
    assert not tool.exists()


@pytest.mark.parametrize('outside_workspace', [True, False])
def test_only_explicit_opencode_database_can_leave_workspace(tool, tmp_path, monkeypatch, outside_workspace):
    from ecra.opencode_storage import ReviewStorage, isolated_environment

    workspace = tool/'workspace'
    outside = tmp_path/'external'
    outside.mkdir()
    location = (outside if outside_workspace else workspace)/'OpenCode 临时库'
    location.mkdir(parents=True)
    database = location/'历史 会话.db'
    monkeypatch.setenv('OPENCODE_DB', str(database))
    storage = ReviewStorage(workspace/'scans/test')
    assert storage.shared
    assert storage.database == database
    monkeypatch.setenv('OPENCODE_DB', str(outside/'different.db'))
    with storage.call() as (cwd, env), storage.call() as (other, other_env):
        assert cwd != other
        assert env['OPENCODE_DB'] == other_env['OPENCODE_DB'] == str(database)
        assert env['TEMP'] != other_env['TEMP']
        for key in (*TEMP_KEYS, 'XDG_DATA_HOME',
                    'XDG_CONFIG_HOME', 'XDG_STATE_HOME', 'XDG_CACHE_HOME', 'XDG_RUNTIME_DIR'):
            assert Path(env[key]).is_relative_to(workspace)
        for scope, scratch, data in ((outside, cwd, None), (storage.scope, outside, None),
                                      (storage.scope, cwd, outside)):
            with pytest.raises(ValueError, match='数据区域之外'):
                isolated_environment(scope, scratch, database, shared=True, data=data)
    assert os.environ['OPENCODE_DB'] == str(outside/'different.db')
    assert not list(location.iterdir())
    with pytest.raises(ValueError, match='数据区域之外'):
        ReviewStorage(outside/'scans/test')


@pytest.mark.parametrize('override', [None, ''])
def test_unset_or_empty_opencode_database_uses_managed_store(tool, monkeypatch, override):
    from ecra.opencode_storage import ReviewStorage

    if override is not None:
        monkeypatch.setenv('OPENCODE_DB', override)
    storage = ReviewStorage(tool/'workspace/scans/test')
    assert not storage.shared
    with storage.call() as (cwd, env):
        assert Path(env['OPENCODE_DB']) == storage.scope/'sessions.db'
        assert cwd.is_relative_to(tool/'workspace')


@pytest.mark.parametrize('value', ['relative.db', ':memory:'])
def test_invalid_explicit_opencode_path_reports_the_configured_value(tool, monkeypatch, value):
    from ecra.opencode_storage import ReviewStorage

    monkeypatch.setenv('OPENCODE_DB', value)
    with pytest.raises(ValueError, match='OPENCODE_DB.*绝对路径') as error:
        ReviewStorage(tool/'workspace/scans/test')
    assert value in str(error.value)
    assert not (tool/'workspace').exists()


def test_external_wal_migration_never_creates_source_locks(tool, tmp_path):
    source = tmp_path/'legacy/ECRAStudio/data'
    (source/'settings').mkdir(parents=True)
    (source/'settings/device.json').write_text('{"device":"device-old"}', 'utf-8')
    db = source/'settings/old.db'
    with sqlite3.connect(db) as conn:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('CREATE TABLE progress(indexed INTEGER)')
        conn.commit()
        conn.execute('INSERT INTO progress VALUES (77)')
        conn.commit()
        assert db.with_name('old.db-wal').stat().st_size > 0
        # Preserve the exact on-disk state of a terminated writer that left a WAL.
        fixture = tmp_path/'offline/ECRAStudio'
        shutil.copytree(source, fixture/'data')
    conn.close()
    source = fixture/'data'
    hashes = lambda path: {p.relative_to(path): hashlib.sha256(p.read_bytes()).hexdigest()
                           for p in path.rglob('*') if p.is_file()}
    before = hashes(source)
    target = tool/'workspace/data-roots/migrated'
    with pytest.raises(ValueError, match='退出|关闭'):
        preview(fixture, str(target))
    plan = preview(fixture, str(target), closed=True)
    result = transfer(fixture, str(target), closed=True, expected=plan['revision'])
    assert hashes(source) == before
    assert result['state'] == 'COMPLETE'
    assert Path(result['verified_source']) == source
    assert managed_path(result['journal']).is_file()
    with sqlite3.connect(target/'settings/old.db') as restored:
        assert restored.execute('SELECT indexed FROM progress').fetchone() == (77,)
    restored.close()
