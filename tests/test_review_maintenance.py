"""Real owned processes, no network or user's database for fault injection."""
import json
from contextlib import contextmanager
import os
from pathlib import Path
import sys
from threading import Timer

import pytest

from ecra.review_opencode_sessions import Runtime, Unavailable
from ecra.review_process import ReviewStop


@contextmanager
def invocation(tmp_path, *, timeout, script, monkeypatch, stop=None):
    runtime = Runtime([sys.executable], timeout=timeout, stop=stop)
    with runtime.maintenance(tmp_path/'test.db', workdir=tmp_path) as maintenance:
        monkeypatch.setattr(maintenance, '_argv', lambda *args: [sys.executable, '-u', '-c', script])
        yield maintenance


def record(tmp_path):
    paths = list(tmp_path.glob('maintenance-logs/*/*/invocation.json'))
    assert len(paths) == 1
    return paths[0], json.loads(paths[0].read_text('utf-8'))


def test_slow_command_survives_old_ten_second_limit(tmp_path, monkeypatch):
    with invocation(tmp_path, timeout=20, monkeypatch=monkeypatch,
        script="import time; print('started',flush=True); time.sleep(10.3); print('finished')") as maintenance:
        assert maintenance.cli('db', 'path') == 'started\nfinished'
    path, result = record(tmp_path)
    assert result['elapsed_seconds'] > 10
    assert result['returncode'] == 0 and result['process_exited']
    assert result['first_output_seconds'] < result['elapsed_seconds']
    assert (path.parent/'stdout.log').read_text().endswith('finished\n')


@pytest.mark.parametrize('cancel', [False, True])
def test_timeout_or_cancel_preserves_redacted_output_and_kills_owned_tree(tmp_path, monkeypatch, cancel):
    stop = ReviewStop()
    marker = tmp_path/'child-survived'
    script = ("import subprocess,sys,time,os; "
              f"subprocess.Popen([sys.executable,'-c', {('import time; from pathlib import Path; time.sleep(2); Path('+repr(str(marker))+').touch()')!r}]); "
              "print(os.environ['API_KEY'], flush=True); print('https://user:password@example.test',flush=True); "
              "time.sleep(60)")
    monkeypatch.setenv('API_KEY', 'unique-test-secret-92345')
    manager = invocation(tmp_path, timeout=10 if cancel else .5,
        monkeypatch=monkeypatch, stop=stop, script=script)
    timer = Timer(.5, stop.cancelled.set) if cancel else None
    if timer:
        timer.start()
    try:
        with manager as maintenance, pytest.raises(KeyboardInterrupt if cancel else Unavailable) as error:
            maintenance.cli('db', '--format', 'json', 'PRAGMA database_list')
        if not cancel:
            assert 'PRAGMA database_list' in str(error.value)
            assert '详细日志' in str(error.value)
        path, result = record(tmp_path)
        assert result['outcome'] == ('cancelled' if cancel else 'timeout')
        assert result['process_exited'] and result['returncode'] is not None
        text = (path.parent/'stdout.log').read_text()
        assert '<redacted>' in text and 'unique-test-secret' not in text and 'user:password' not in text
        import time
        time.sleep(2.2)
        assert not marker.exists()
    finally:
        if timer:
            timer.cancel()


def test_maintenance_budget_is_validated_and_exposed_in_studio(tmp_path):
    from ecra.config import load_config
    from ecra.studio.profile_options import validate, state
    path = tmp_path/'semantics.yaml'
    path.write_text('version: 1\nreview:\n  maintenance_timeout_seconds: 17\n')
    cfg, _ = load_config(tmp_path, path)
    assert cfg['review']['maintenance_timeout_seconds'] == 17
    assert state(cfg)['review.maintenance_timeout_seconds'] == 17
    for value in [0, -1, float('inf'), True]:
        with pytest.raises(ValueError):
            validate('review.maintenance_timeout_seconds', value)
        with pytest.raises(ValueError):
            Runtime([sys.executable], timeout=value)


def test_review_only_upgrade_accepts_original_scan_but_not_changed_static_engine(monkeypatch):
    import ecra.workflow as workflow
    original = workflow._config_engine_hash
    upgrades = {
        '6352e018cec582589236685c52402ad514842e35e9134179048e3938c8505d65':
            '86cd56ed3cdc1916e3ea201b442917273c33d729d2b1c0270785fd42005b2bd2',
        '5d23965cdb19132dc10b04a08d2425b13ccc272e4ecb1977e6b1a1dfd569b3ba':
            '88d6861cbf63e0d6815e92c1e36884fe2f89d7eabc7c748f8604048146021e5d',
    }
    with monkeypatch.context() as before:
        before.setattr(workflow, '_config_engine_hash', lambda value: original(upgrades.get(value, value)))
        previous = workflow.engine_digest()
    assert workflow.matches_static_engine(previous)
    assert not workflow.matches_static_engine('0'*64)
