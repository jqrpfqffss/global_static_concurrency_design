import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys

import pytest

from ecra.opencode_command import resolve_command
from ecra.opencode_protocol import (AuthenticationRequired, ProtocolError, VersionOutputError,
                                    parse_json, parse_version, validate_run)
from ecra.opencode_storage import ReviewStorage
from ecra.review_opencode_sessions import Runtime, Maintenance, Unverifiable
from ecra.review_process import ReviewStop, execute


@pytest.mark.parametrize('out,err,expected', [
    ('1.18.35', '', ('OpenCode', '1.18.35')),
    ('\ufeff\n\x1b[32mv1.18.35\x1b[0m\n', '', ('OpenCode', '1.18.35')),
    ('欢迎使用研发工具|xOpenCode\n\n1.19.5-h1', '', ('xOpenCode', '1.19.5-h1')),
    ('', 'OpenCode version: 1.20.0-dev.1+vendor', ('OpenCode', '1.20.0-dev.1+vendor')),
    ('opencode 1.19.5', '1.19.5', ('OpenCode', '1.19.5')),
    ('OpenCode v1.19.5', '', ('OpenCode', '1.19.5')),
])
def test_version_contract(out, err, expected):
    assert parse_version(out, err) == expected


@pytest.mark.parametrize('out,err', [('', ''), ('Bun 1.4.4', ''),
    ('build at 2026.11.17\n1.19.5', ''), ('1.19.5', '1.18.35'),
    ('{"version":"1.19.5"}', ''), ('1.19.5\nUnexpected error', '')])
def test_version_rejects_ambiguous_or_unidentified_output(out, err):
    with pytest.raises(VersionOutputError):
        parse_version(out, err)


def test_version_login_and_nonzero():
    with pytest.raises(AuthenticationRequired):
        parse_version('欢迎使用研发工具|xOpenCode\n请输入域账号:')
    with pytest.raises(VersionOutputError):
        parse_version('1.19.5', returncode=1)


def test_only_known_banner_is_removed_from_json():
    assert parse_json('欢迎使用研发工具|xOpenCode\n[ {"file":"中文"} ]') == [{'file': '中文'}]
    for text in ['noise\n{"ok":true}', '{"a":1,"a":2}', '{}\n{}', 'Error\n[]']:
        with pytest.raises(ProtocolError):
            parse_json(text)


def test_final_run_completion_and_error_events():
    sid = 'ses_' + '0'*12 + 'A'*14
    def event(kind, part):
        return json.dumps(dict(type=kind, timestamp=1, sessionID=sid, part=dict(sessionID=sid, **part)))
    text = event('text', dict(type='text', text='answer'))
    finish = event('step_finish', dict(type='step-finish', reason='stop'))
    assert validate_run(text+'\n'+finish) == sid
    for raw in [text, text+'\n'+finish+'\ntruncated', text+'\n'+finish.replace('stop', 'tool-calls')]:
        with pytest.raises(ProtocolError):
            validate_run(raw)


def test_context_is_shared_by_prepare_call_and_maintenance(tmp_path, monkeypatch):
    source = tmp_path/'input'
    auth = source/'opencode/auth.json'
    auth.parent.mkdir(parents=True)
    auth.write_text('{"test":{"type":"api","key":"fixture-only"}}')
    environment = dict(os.environ, XDG_DATA_HOME=str(source), OPENCODE_ENTERPRISE_TOKEN='fixture-only',
                       OPENCODE_AUTH_CONTENT='{"fixture":true}')
    storage = ReviewStorage(tmp_path, environment=environment)
    runtime = Runtime([sys.executable])
    seen = []
    def prepared(maintenance):
        seen.append(maintenance.env)
        maintenance.database.touch()
        from ecra.review_opencode_sessions import store_identity
        return store_identity(maintenance.database)
    monkeypatch.setattr(Maintenance, 'prepare', prepared)
    storage.prepare(runtime)
    with storage.call() as (_, env), runtime.maintenance(storage.database, workdir=tmp_path) as later:
        for key in ['XDG_DATA_HOME', 'XDG_CONFIG_HOME', 'OPENCODE_ENTERPRISE_TOKEN', 'OPENCODE_AUTH_CONTENT']:
            assert seen[0][key] == env[key] == later.env[key]
        assert env['HOME'] != environment.get('HOME')
        assert 'OPENCODE_PURE' not in env
        assert 'OPENCODE_PURE' not in seen[0]
    assert environment['XDG_DATA_HOME'] == str(source)


def test_known_login_prompt_ends_early_and_records_before_reap(tmp_path, monkeypatch):
    runtime = Runtime([sys.executable], timeout=15)
    with runtime.maintenance(tmp_path/'db', workdir=tmp_path) as maintenance:
        monkeypatch.setattr(maintenance, '_argv', lambda *a: [sys.executable, '-u', '-c',
            "import time,sys;sys.stdout.buffer.write('欢迎使用研发工具|xOpenCode\\n请输入域账号:'.encode());sys.stdout.flush();time.sleep(30)"])
        with pytest.raises(AuthenticationRequired):
            maintenance.cli('--version')
    record = json.loads(next(tmp_path.glob('maintenance-logs/*/*/invocation.json')).read_text('utf-8'))
    assert record['elapsed_seconds'] < 5
    assert record['ecra_requested_reap']
    assert record['returncode_before_reap'] is None
    assert record['error_code'] == 'authentication_required'
    assert record['outcome'] == 'failed'


def test_shared_database_not_started_before_private_probe(tmp_path, monkeypatch):
    database = tmp_path/'history.db'
    with sqlite3.connect(database) as conn:
        conn.execute('CREATE TABLE history (message TEXT)')
        conn.execute("INSERT INTO history VALUES ('keep')")
    before = database.read_bytes()
    runtime = Runtime([sys.executable])
    def reject(maintenance):
        assert maintenance.database == database
        raise Unverifiable('probe rejected before shared launch')
    monkeypatch.setattr(runtime, 'probe', reject)
    monkeypatch.setattr(Maintenance, 'cli', lambda *a: pytest.fail('shared database command started'))
    with runtime.maintenance(database, workdir=tmp_path, shared=True) as maintenance:
        with pytest.raises(Unverifiable):
            maintenance.prepare()
    assert database.read_bytes() == before


@pytest.mark.skipif(os.name != 'nt', reason='Windows script argument contract')
@pytest.mark.parametrize('suffix,forwarding', [('.cmd', None), ('.bat', None), ('.ps1', '@args'), ('.ps1', '$args')])
def test_windows_script_preserves_arguments_and_entry(tmp_path, suffix, forwarding):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node unavailable: not a passed launcher test')
    script = tmp_path/'中文 & 空格 100% !^ entry.js'
    script.write_text('process.stdout.write(JSON.stringify(process.argv.slice(2)))', encoding='utf-8')
    entry = tmp_path/('企业 & 入口' + suffix)
    if suffix == '.ps1':
        entry.write_text("& '"+node+"' '"+str(script)+"' "+forwarding+"\nexit $LASTEXITCODE", encoding='utf-8-sig')
    else:
        # Refer to the path through a variable so percent literals are not
        # embedded in this fixture's batch program text either.
        entry.write_text('@echo off\n"'+node+'" "%ECRA_TEST_SCRIPT%" %*\n', encoding='utf-8')
    args = ['中文 空格', 'a&b|c<d>e^f%PATH%!literal!', '', 'trailing\\']
    argv = resolve_command([str(entry), *args])
    assert argv[0] == str(entry)
    env = dict(os.environ, ECRA_TEST_SCRIPT=str(script), TEMP=str(tmp_path))
    result = execute(argv, cwd=tmp_path, env=env, timeout=8, stop=ReviewStop(),
                     stdout_path=tmp_path/'stdout', stderr_path=tmp_path/'stderr')
    assert result.returncode == 0, result.stderr
    # Windows PowerShell 5 drops empty native arguments. Reject that entry
    # capability until a wrapper preserves them; cmd forwarding is exact.
    assert json.loads(result.stdout) == args


def test_entry_content_change_invalidates_runtime(tmp_path):
    script = tmp_path/'entry.js'
    script.write_text('old')
    runtime = Runtime([sys.executable, str(script)])
    script.write_text('new')
    with pytest.raises(Unverifiable):
        runtime.check_exe()


@pytest.mark.parametrize('version,accepted', [('1.99.123-company.7', True), ('2.0.7', False)])
def test_unseen_version_is_provisional_by_protocol_and_daemon_is_not_adopted(tmp_path, monkeypatch, version, accepted):
    runtime = Runtime([sys.executable])
    commands = []
    def cli(agent, *args):
        commands.append(args)
        assert agent.database != tmp_path/'historical.db'
        if args == ('--version',):
            return version
        if args == ('run','--help'):
            return '--format --agent --model --file --title'
        if args == ('db','path'):
            return str(agent.database)
        return json.dumps([dict(name='main', file=str(agent.database))])
    monkeypatch.setattr(Maintenance, 'cli', cli)
    monkeypatch.setattr(Maintenance, 'schema_signature', lambda *a:'fixture-schema')
    with runtime.maintenance(tmp_path/'historical.db', workdir=tmp_path, shared=True) as maintenance:
        if accepted:
            runtime.probe(maintenance)
            assert runtime.version == version
            assert runtime.capabilities['review'] == 'AWAITING_FIRST_RUN'
            assert runtime.capabilities['cleanup'] == 'NOT_TESTED'
        else:
            with pytest.raises(Unverifiable, match='后台服务'):
                runtime.probe(maintenance)
            assert commands == [('--version',), ('run','--help')]
    assert not any(args[0]=='run' and args != ('run','--help') for args in commands)


def test_redactor_scrubs_individual_credentials_without_serializing_environment(tmp_path):
    from ecra.opencode_protocol import redactor
    auth = tmp_path/'opencode/auth.json'
    auth.parent.mkdir()
    auth.write_text(json.dumps({'vendor': {'access':'fixture-access-secret','refresh':'fixture-refresh-secret'}}))
    scrub = redactor({'XDG_DATA_HOME':str(tmp_path),'OPENCODE_AUTH_CONTENT':json.dumps({'p':{'key':'fixture-inline-secret'}})})
    assert scrub('fixture-access-secret fixture-refresh-secret fixture-inline-secret') == '<redacted> <redacted> <redacted>'


def test_invalid_utf8_cannot_be_used_as_protocol_data(tmp_path):
    with pytest.raises(ProtocolError, match='UTF-8'):
        execute([sys.executable,'-c',"import sys;sys.stdout.buffer.write(b'\\xff{\\\"sessionID\\\":\\\"wrong\\\"}')"],
                cwd=tmp_path, env=dict(os.environ,TEMP=str(tmp_path)),timeout=5, stop=ReviewStop(),
                stdout_path=tmp_path/'stdout',stderr_path=tmp_path/'stderr')


def test_timeout_diagnostic_does_not_expose_command_credentials(tmp_path):
    import subprocess
    with pytest.raises(subprocess.TimeoutExpired) as failure:
        execute([sys.executable, '-c', 'import time;time.sleep(5)', '--api-key', 'fixture-command-secret'],
                cwd=tmp_path, env=dict(os.environ, TEMP=str(tmp_path)), timeout=.15, stop=ReviewStop(),
                stdout_path=tmp_path/'stdout', stderr_path=tmp_path/'stderr')
    assert 'fixture-command-secret' not in str(failure.value)
    assert '<redacted>' in str(failure.value)


@pytest.mark.skipif(os.name != 'nt', reason='Windows CreateProcess cwd limit')
def test_deep_archive_keeps_actual_maintenance_cwd_short(tmp_path):
    entry = tmp_path/'version.py'
    entry.write_text('print("1.18.35")', encoding='utf-8')
    archive = tmp_path/('nested-'*18)/('journal-'*12)
    archive.mkdir(parents=True)
    assert len(str(archive)) > 260
    runtime = Runtime([sys.executable, str(entry)])
    with runtime.maintenance(tmp_path/'test.db', workdir=archive) as maintenance:
        assert len(str(maintenance.cwd)) < 240
        assert maintenance.diagnostics.is_relative_to(archive)
        assert maintenance.cli('--version') == '1.18.35'


def test_auth_and_config_changes_require_new_private_probe(tmp_path, monkeypatch):
    runtime = Runtime([sys.executable])
    versions = []
    def cli(agent, *args):
        assert agent.database != tmp_path/'historical.db'
        if args == ('--version',):
            versions.append(args)
            return '1.99.123-company.7'
        if args == ('run', '--help'):
            return '--format --agent --model --file --title'
        if args == ('db', 'path'):
            return str(agent.database)
        return json.dumps([dict(name='main', file=str(agent.database))])
    monkeypatch.setattr(Maintenance, 'cli', cli)
    monkeypatch.setattr(Maintenance, 'schema_signature', lambda *a:'fixture-schema')
    with runtime.maintenance(tmp_path/'historical.db', workdir=tmp_path, shared=True) as maintenance:
        auth = Path(maintenance.env['XDG_DATA_HOME'])/'opencode/auth.json'
        auth.parent.mkdir(parents=True)
        auth.write_text('{"fixture":{"key":"first-fixture-key"}}')
        runtime.probe(maintenance)
        runtime.probe(maintenance)
        assert len(versions) == 1
        auth.write_text('{"fixture":{"key":"renewed-fixture-key"}}')
        runtime.probe(maintenance)
        assert len(versions) == 2
        maintenance.env['OPENCODE_CONFIG_CONTENT'] = '{"model":"fixture/new"}'
        runtime.probe(maintenance)
        assert len(versions) == 3
        maintenance.env['OPENCODE_ENTERPRISE_AUTH_TOKEN'] = 'changed-fixture-token'
        runtime.probe(maintenance)
        assert len(versions) == 4
    assert runtime.capabilities['authentication'] == 'AWAITING_FIRST_RUN'
    assert not (tmp_path/'historical.db').exists()
