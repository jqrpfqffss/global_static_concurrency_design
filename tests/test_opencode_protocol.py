import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys

import pytest

from ecra.opencode_command import resolve_command
from ecra.opencode_protocol import (AuthenticationRequired, ProtocolError,
                                    parse_json, validate_run)
from ecra.opencode_storage import ReviewStorage
from ecra.review_opencode_sessions import Runtime, Maintenance, Unverifiable
from ecra.review_process import ReviewStop, execute


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
    monkeypatch.setattr(Maintenance, 'prepare', lambda *_: pytest.fail('maintenance before run'))
    storage.prepare(runtime)
    assert storage.identity is None
    with storage.call() as (_, env), runtime.maintenance(storage.database, workdir=tmp_path) as later:
        for key in ['XDG_DATA_HOME', 'XDG_CONFIG_HOME', 'OPENCODE_ENTERPRISE_TOKEN', 'OPENCODE_AUTH_CONTENT',
                    'HOME', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA']:
            assert env.get(key) == later.env.get(key)
        for key in ['HOME', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA']:
            assert env.get(key) == environment.get(key)
        assert 'OPENCODE_PURE' not in env
    assert environment['XDG_DATA_HOME'] == str(source)


def test_known_login_prompt_ends_early_and_records_before_reap(tmp_path, monkeypatch):
    runtime = Runtime([sys.executable], timeout=15)
    with runtime.maintenance(tmp_path/'db', workdir=tmp_path) as maintenance:
        monkeypatch.setattr(maintenance, '_argv', lambda *a: [sys.executable, '-u', '-c',
            "import time,sys;sys.stdout.buffer.write('欢迎使用研发工具|xOpenCode\\n请输入域账号:'.encode());sys.stdout.flush();time.sleep(30)"])
        with pytest.raises(AuthenticationRequired):
            maintenance.cli('db', 'path')
    record = json.loads(next(tmp_path.glob('maintenance-logs/*/*/invocation.json')).read_text('utf-8'))
    assert record['elapsed_seconds'] < 5
    assert record['ecra_requested_reap']
    assert record['returncode_before_reap'] is None
    assert record['error_code'] == 'authentication_required'
    assert record['outcome'] == 'failed'


def test_shared_database_local_preparation_does_not_open_or_migrate(tmp_path, monkeypatch):
    database = tmp_path/'history.db'
    database.write_bytes(b'unknown enterprise database')
    storage = ReviewStorage(tmp_path, environment=dict(os.environ, OPENCODE_DB=str(database)))
    runtime = Runtime([sys.executable])
    monkeypatch.setattr(Maintenance, 'cli', lambda *a: pytest.fail('database command before run'))
    storage.prepare(runtime)
    assert storage.identity is not None
    assert database.read_bytes() == b'unknown enterprise database'
    assert runtime.version is None
    assert not list(tmp_path.rglob('protocol.db'))


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
    entry = tmp_path/'maintenance.py'
    entry.write_text('print("fixture-maintenance")', encoding='utf-8')
    archive = tmp_path/('nested-'*18)/('journal-'*12)
    archive.mkdir(parents=True)
    assert len(str(archive)) > 260
    runtime = Runtime([sys.executable, str(entry)])
    with runtime.maintenance(tmp_path/'test.db', workdir=archive) as maintenance:
        assert len(str(maintenance.cwd)) < 240
        assert maintenance.diagnostics.is_relative_to(archive)
        assert maintenance.cli('db', 'path') == 'fixture-maintenance'


def test_auth_and_config_changes_never_launch_a_probe(tmp_path, monkeypatch):
    from ecra.opencode_check import check
    monkeypatch.setattr(Maintenance, 'cli', lambda *a: pytest.fail('local check launched CLI'))
    for key, value in [('OPENCODE_ENTERPRISE_AUTH_TOKEN', 'new-fixture-token'),
                       ('OPENCODE_CONFIG_CONTENT', '{"model":"fixture/new"}')]:
        monkeypatch.setenv(key, value)
        result = check({'command': [sys.executable]}, project=tmp_path)
        assert result['ready'] and result['version'] is None
        assert result['cli_launch_attempts'] == result['model_calls'] == 0
        assert result['capabilities']['authentication'] == 'AWAITING_FIRST_RUN'


@pytest.mark.parametrize('health', [{'healthy': True}, {'healthy': True, 'version': '2.99-enterprise', 'extra': 7}])
def test_optional_api_health_ignores_unrelated_version_metadata(monkeypatch, health):
    from ecra.review_opencode_sessions import API
    class Response:
        status = 401
        def __enter__(self): return self
        def __exit__(self, *args): pass
    class Connection:
        def __init__(self, *args, **kwargs): pass
        def request(self, *args, **kwargs): pass
        def getresponse(self): return Response()
        def close(self): pass
    monkeypatch.setattr('http.client.HTTPConnection', Connection)
    api = API(1, 'test-only')
    routes = {'/session/{sessionID}': {'get': 'session.get', 'delete': 'session.delete'},
              '/session/{sessionID}/children': {'get': 'session.children'},
              '/session/status': {'get': 'session.status'}, '/project/current': {'get': 'project.current'}}
    spec = {'paths': {route: {method: {'operationId': op} for method, op in methods.items()}
                      for route, methods in routes.items()}}
    monkeypatch.setattr(api, 'request', lambda method, path: health if path == '/global/health' else spec)
    api.verify()
    health['healthy'] = False
    with pytest.raises(Unverifiable, match='健康'):
        api.verify()


def test_review_only_change_preserves_old_receipt_identity():
    from ecra.common import digest
    from ecra import review
    from ecra.review_session_cleanup import compatible_review_implementation
    names = ['review.py', 'review_contract.py', 'review_language.py', 'review_sources.py',
             'native_review_packet.py', 'review_hash.py', 'review_packet.py', 'evidence_mcp.py', 'review_summary.py']
    texts = [(Path(review.__file__).parent/name).read_text('utf-8') for name in names]
    previous = '51256eac8239371fdd17bfc302d1e180b8a248ac9521bf93764bdd1ba0a9a8aa'  # pre-lifecycle Portable
    assert compatible_review_implementation(digest(texts)) == compatible_review_implementation(previous)
    texts[1] += '\n# a different answer contract'
    assert compatible_review_implementation(digest(texts)) != compatible_review_implementation(previous)
