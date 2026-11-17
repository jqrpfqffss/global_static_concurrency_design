"""Process-level synthetic CLI contract. This is never enterprise acceptance."""
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Timer

import pytest

from ecra.common import read_json
from ecra.review import review_all, ReviewExecutionError
from ecra.review_process import execute, ReviewStop
from ecra.review_session_cleanup import JOURNAL
from ecra.workflow import read_queue
from tests.test_review_contract import answer_for


@pytest.fixture
def cli(tmp_path):
    script = tmp_path/'CLI entry with spaces.py'
    log, mode, response = (tmp_path/name for name in ('argv.jsonl', 'mode', 'answer.json'))
    mode.write_text('ok')
    response.write_text(json.dumps(answer_for()), encoding='utf-8')
    script.write_text('''import json, sys, time, os
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')
log, mode, response = map(Path, sys.argv[1:4])
args = sys.argv[4:]
with log.open('a', encoding='utf-8') as out:
    out.write(json.dumps(args)+'\\n')
if not args or args[0] != 'run' or '--help' in args or '--version' in args or '-v' in args:
    raise SystemExit('FORBIDDEN PRECHECK: '+str(args))
behavior = mode.read_text()
if behavior == 'login':
    print('请输入域账号：', flush=True)
    time.sleep(20)
if behavior == 'timeout':
    time.sleep(20)
if behavior == 'nonzero':
    print('configured provider unavailable', file=sys.stderr)
    raise SystemExit(7)
if behavior == 'invalid':
    print('not a completed review')
    raise SystemExit(0)
packet = json.loads(Path(args[args.index('--file')+1]).read_text(encoding='utf-8'))
answer = json.loads(response.read_text(encoding='utf-8'))
answer['finding_id'] = packet['finding_id']
sid = 'ses_' + '0'*12 + 'A'*14
for kind, part in [('text', dict(type='text', text=json.dumps(answer,ensure_ascii=False))),
                   ('step_finish', dict(type='step-finish', reason='stop'))]:
    print(json.dumps(dict(type=kind, timestamp=1, sessionID=sid, part=dict(sessionID=sid, **part)),ensure_ascii=False))
''', encoding='utf-8')
    root = tmp_path/'firmware'
    root.mkdir()
    (root/'app.c').write_text('int shared;\nvoid IRQ(void){shared++;}\n', encoding='utf-8')
    command = [sys.executable, '-u', str(script), str(log), str(mode), str(response)]
    # Do not hash mutable controls as command inputs: directory indirection
    # lets the same installed entry be used for explicit failure retries.
    wrapper = tmp_path/'entry.py'
    wrapper.write_text('import runpy,sys\nsys.argv=[sys.argv[0],*[' +
                       ','.join(repr(str(p)) for p in (log, mode, response)) +
                       '],*sys.argv[1:]]\nrunpy.run_path('+repr(str(script))+',run_name="__main__")', encoding='utf-8')
    command = [sys.executable, '-u', str(wrapper)]
    cfg = {'review': dict(enabled=True, command=command, workers=1, retries=0, timeout_seconds=5,
                          session_cleanup={'enabled': False})}
    out = tmp_path/'archive'
    def review(count=1, mode='run'):
        findings = [dict(finding_id=f'F{i}', variable_name='shared', static_classification='SUSPECT') for i in range(count)]
        return review_all(root, out, cfg, dict(variables=[]), dict(findings=findings), 'static-test', mode=mode)
    return root, out, cfg, mode, log, review


@pytest.mark.parametrize('cleanup', [False, True])
def test_first_process_is_run_archive_resume_and_pending_identity(cli, cleanup):
    root, out, cfg, mode, log, review = cli
    cfg['review']['session_cleanup']['enabled'] = cleanup
    rows = review(2)
    assert [row['state'] for row in rows] == ['DONE', 'DONE']
    commands = [json.loads(line) for line in log.read_text().splitlines()]
    assert len(commands) == 2 and all(argv[0] == 'run' for argv in commands)
    assert not list(out.rglob('protocol.db'))
    before = [(out/'review'/f'F{i}.result.json').read_bytes() for i in range(2)]
    (out/'review/opencode-capabilities.json').unlink()
    assert [row['state'] for row in review(2, 'review-resume')] == ['DONE', 'DONE']
    assert before == [(out/'review'/f'F{i}.result.json').read_bytes() for i in range(2)]
    assert len(log.read_text().splitlines()) == 2
    assert [row['state'] for row in review(3, 'review-resume')] == ['DONE', 'DONE', 'DONE']
    assert before == [(out/'review'/f'F{i}.result.json').read_bytes() for i in range(2)]
    assert len(log.read_text().splitlines()) == 3
    if cleanup:
        import sqlite3
        from contextlib import closing
        with closing(sqlite3.connect(next(out.rglob(JOURNAL)))) as conn:
            assert json.loads(conn.execute('SELECT database_identity FROM run').fetchone()[0]) is None
            assert {r[0] for r in conn.execute('SELECT cleanup_state FROM calls')} == {'SKIPPED_UNVERIFIABLE'}


@pytest.mark.parametrize('failure', ['login', 'nonzero', 'timeout', 'invalid'])
def test_real_run_failure_not_initialization_or_zero_model_calls(cli, failure):
    root, out, cfg, mode, log, review = cli
    mode.write_text(failure)
    if failure == 'timeout':
        cfg['review']['timeout_seconds'] = .3
    try:
        review()
    except ReviewExecutionError:
        pass  # A shared auth/protocol failure also stops the outer batch.
    row, = read_queue(out)
    assert row['state'] == 'TECH_FAILED'
    assert not (out/'review/initialization-error.json').exists()
    record = row['attempts'][0]
    assert record['operation_stage'] == 'run'
    assert record['cli_launch_attempts'] == 1 and record['model_calls'] is None
    assert record['model_requests_observed'] is False
    assert len(log.read_text().splitlines()) == 1
    if failure == 'timeout':
        assert record['outcome'] == 'timeout' and record['returncode_before_reap'] is None
    if failure == 'login':
        assert record['error_code'] == 'authentication_required'
    mode.write_text('ok')
    cfg['review']['timeout_seconds'] = 5
    assert review(mode='review-failed')[0]['state'] == 'DONE'
    assert len(log.read_text().splitlines()) == 2


def test_cli_and_studio_check_never_start_entry(cli, tmp_path):
    root, out, cfg, mode, log, review = cli
    # A packaged engine nested in the checkout must not inherit its outer Git
    # repository as this synthetic firmware's ownership boundary.
    (root/'.git').mkdir()
    from ecra.cli import main
    from ecra.studio.server import create_app
    from fastapi.testclient import TestClient
    config = tmp_path/'config.json'
    config.write_text(json.dumps(dict(version=1, project={'root':str(root)}, **cfg)), encoding='utf-8')
    assert main(['opencode-check', '--config', str(config), '--json']) == 0
    data = tmp_path/'studio'
    app = create_app(data, token='test-only', authority='testserver')
    with TestClient(app, headers={'X-ECRA-Session':'test-only', 'Origin':'http://testserver'}) as client:
        response = client.post('/api/profiles', json={'yaml':config.read_text('utf-8')})
        assert response.status_code == 200, response.text
        profile = response.json()
        response = client.post('/api/profiles/opencode-check', json=dict(project_id=profile['project_id'], profile_id=profile['id']))
        assert response.status_code == 200, response.text
        assert response.json()['ready'] and response.json()['model_calls'] == 0
    assert not log.exists()


def test_actual_run_cancel_keeps_original_outcome_and_reaps(tmp_path):
    stop = ReviewStop()
    record = {}
    timer = Timer(.3, stop.cancelled.set)
    timer.start()
    try:
        with pytest.raises(KeyboardInterrupt):
            execute([sys.executable, '-c', 'import time;time.sleep(20)'], cwd=tmp_path,
                    env=dict(os.environ, TEMP=str(tmp_path)), timeout=10, stop=stop,
                    stdout_path=tmp_path/'out', stderr_path=tmp_path/'err', diagnostic=record)
    finally:
        timer.cancel()
    assert record['outcome'] == 'cancelled' and record['ecra_requested_reap']
    assert record['returncode_before_reap'] is None and record['returncode_after_reap'] is not None
    assert record['model_calls'] is None


def test_reap_failure_cannot_replace_timeout_and_start_event_is_not_model_evidence(tmp_path, monkeypatch):
    from contextlib import contextmanager
    class Process:
        pid, returncode = 1, None
        def poll(self): return None
        def wait(self, timeout): raise subprocess.TimeoutExpired('test', timeout)
    @contextmanager
    def process(*args, **kwargs):
        kwargs['stdout'].write(b'{"type":"step_start"}\n')
        kwargs['stdout'].flush()
        try:
            yield Process()
        finally:
            raise OSError('synthetic reap failure')
    monkeypatch.setattr('ecra.review_process.owned_process', process)
    record = {}
    with pytest.raises(subprocess.TimeoutExpired):
        execute(['fixture'], cwd=tmp_path, env=dict(os.environ), timeout=.01, stop=ReviewStop(),
                stdout_path=tmp_path/'out', stderr_path=tmp_path/'err', diagnostic=record)
    assert record['outcome'] == 'timeout' and record['reap_error'] == 'synthetic reap failure'
    assert record['model_requests_observed'] is False and record['model_calls'] is None
