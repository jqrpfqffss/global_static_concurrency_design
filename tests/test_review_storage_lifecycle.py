from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import shutil
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest

from ecra import garbage_collection as gc, review_archive
from ecra.common import read_json, write_json
from ecra.human_reviews import ReviewStore
from ecra.report_package import export_report, import_report, sha256
from ecra.review import review_all, verify_receipt
from ecra.scan_persistence import append_runtime, runtime
from ecra.scan_store import EvidenceProvider, publish_scan
from tests.review_fixtures import mock_runtime
from tests.test_review_contract import answer_for


@pytest.fixture
def case(tmp_path):
    out = tmp_path/'data/scans/s'
    text = 'int shared;\nvoid IRQ(void){shared++;}\n'
    facts = dict(variables=[dict(symbol_id='shared', name='shared', static_classification='SUSPECT')])
    report = dict(findings=[dict(finding_id='F', variable_name='shared', static_classification='SUSPECT', accesses=[])])
    publish_scan(out/'scan.db', facts, report, scan_id='s', project_id='p',
                 provenance=dict(archived_sources=[dict(file='app.c', text=text, sha256=hashlib.sha256(text.encode()).hexdigest())]))
    provider = EvidenceProvider(out/'scan.db')
    human = ReviewStore(out/'reviews.db', provider.metadata())
    human.append('shared', provider.fingerprint('shared'), decision='NEED_MORE_EVIDENCE', reviewer='fixture')
    append_runtime(out, {}, [dict(finding_id='F', state='PENDING', static_classification='SUSPECT')])
    write_json(out/'manifest.json', dict(provider.metadata(), format='ECRA_LOCAL_SCAN', scan_sha256=sha256(out/'scan.db')))
    cfg = dict(review=dict(enabled=True, retries=0), analysis={})
    calls = []

    def model(argv, **options):
        calls.append(read_json(argv[argv.index('--file')+1])['finding_id'])
        return CompletedProcess(argv, 0, json.dumps(answer_for()), '')

    def run(**options):
        with mock_runtime(['synthetic-test-executor']), patch('ecra.review.execute', side_effect=model):
            return review_all(tmp_path, out, cfg, facts, report, 'scan', mode='review-resume', **options)
    return out, run, calls, human


@pytest.mark.parametrize('before_call', [False, True])
def test_cancelled_attempt_retires_on_its_own_retry_and_keeps_diagnostics(case, before_call):
    out, run, calls, _ = case
    from ecra.review import _sha

    def stop_on_input(path):
        if path.name.startswith('F.') and path.name.endswith('.input.json'):
            raise KeyboardInterrupt
        return _sha(path)

    stop = (patch('ecra.review._sha', side_effect=stop_on_input) if before_call
            else patch('ecra.review.parse_answer', side_effect=KeyboardInterrupt))
    with stop, pytest.raises(KeyboardInterrupt):
        run()
    folder = out/'review'
    paused = {path.name: sha256(path) for path in folder.glob('F.*')}
    assert any(name.endswith('.execution.json') for name in paused)
    row, = run()
    assert row['state'] == 'DONE' and calls == ['F'] * (1 if before_call else 2)
    assert row['interrupted_files'] == paused
    for name, hashed in paused.items():
        assert sha256(review_archive.archived_file(out, name, 'F')) == hashed
    assert not list(folder.glob('F.*'))


def test_out_of_space_after_intent_replays_without_model(case):
    out, run, calls, _ = case
    with patch.object(review_archive, 'archive_object', side_effect=OSError(28, 'disk full')):
        with pytest.raises(OSError, match='disk full'):
            run()
    row = read_json(out/'review/F.result.json')
    assert runtime(out)['reviews'][0]['state'] == 'PENDING'
    assert (out/'review'/row['execution']['stdout_file']).is_file()
    recovered, = run()
    assert recovered['state'] == 'DONE' and calls == ['F']
    assert not list((out/'review').glob('F.*'))


@pytest.mark.skipif(os.name != 'nt', reason='Requires Windows delete-sharing semantics')
def test_windows_open_reader_defers_only_its_file(case):
    out, run, calls, _ = case
    original = review_archive.archive_receipt
    messages = []
    with ExitStack() as stack:
        def lock_transcript(directory, path, row):
            original(directory, path, row)
            stack.enter_context((out/'review'/row['execution']['stdout_file']).open('rb'))
        with patch.object(review_archive, 'archive_receipt', side_effect=lock_transcript):
            row, = run(progress=messages.append)
        assert row['state'] == 'DONE'
        assert [p.name for p in (out/'review').glob('F.*')] == [row['execution']['stdout_file']]
        assert any('待补偿' in message for message in messages)
    assert run()[0] == row and calls == ['F']
    assert not list((out/'review').glob('F.*'))


def test_old_working_copies_gc_and_package_round_trip(case, tmp_path):
    out, run, _, human = case
    row, = run()
    before = human.history()
    folder = out/'review'
    name = row['execution']['stdout_file']
    obj = out/'evidence'/row['execution']['stdout_sha256']
    shutil.copyfile(obj, folder/name)
    shutil.copyfile(obj, folder/'unknown-name.jsonl')
    # Historical directory audits bind the object for life.
    index = json.dumps(dict(version=1, files={'review/'+name: row['archived_files'][name]})).encode()
    hashed = hashlib.sha256(index).hexdigest()
    (out/'evidence'/hashed).write_bytes(index)
    write_json(out/'manifest.json', dict(read_json(out/'manifest.json'), audit_indices=[hashed]))
    # Some old writers replaced the manifest root between two checkpoints.
    # Both the previous v1 index and its uniquely referenced payload survive.
    retired = b'earlier checkpoint'
    old_hash = hashlib.sha256(retired).hexdigest()
    (out/'evidence'/old_hash).write_bytes(retired)
    old_index = json.dumps(dict(version=1, files={'run.json': dict(sha256=old_hash,size=len(retired))})).encode()
    old_root = hashlib.sha256(old_index).hexdigest()
    (out/'evidence'/old_root).write_bytes(old_index)
    data = out.parent.parent
    plan = gc.preview(data)
    assert [(item['category'], Path(item['relative']).name) for item in plan['items']] == [('REVIEW_DUPLICATE',name)]
    gc.quarantine(data, plan['id'])
    gc.restore(data, plan['id'])
    assert (folder/name).read_bytes() == obj.read_bytes()
    plan = gc.preview(data)
    gc.quarantine(data, plan['id'])
    gc.purge(data, plan['id'])
    assert (out/'evidence'/old_hash).read_bytes() == retired and (out/'evidence'/old_root).read_bytes() == old_index
    assert (folder/'unknown-name.jsonl').exists() and not (folder/name).exists()
    assert human.history() == before and runtime(out)['reviews'] == [row]
    assert verify_receipt(tmp_path, folder, row) == row['answer']
    package = tmp_path/'complete.ecra-report'
    export_report(out, package)
    destination = tmp_path/'receiver'
    import_report(package, destination)
    imported = destination/'scans/s'
    assert runtime(imported)['reviews'] == [row]
    assert verify_receipt(tmp_path, imported/'review', row) == row['answer']
    assert ReviewStore(imported/'reviews.db', EvidenceProvider(imported/'scan.db').metadata()).history() == before


def test_batch_vendor_cache_is_retired_after_maintenance_only(tmp_path):
    from ecra.opencode_storage import ReviewStorage, retry_retired_runtime
    out = tmp_path/'data/scans/firmware'
    db = tmp_path/'unrelated-session.db'
    db.write_bytes(b'owned elsewhere')
    with ExitStack() as other:
        active = ReviewStorage(out, environment={'OPENCODE_DB': str(db)}, lifetime=other)
        running = active.work/'cache/example.bin'
        running.parent.mkdir()
        running.write_bytes(b'still used')
        with ExitStack() as batch:
            owned = ReviewStorage(out, environment={}, lifetime=batch)
            owned.database.write_bytes(b'private sessions')
            before = owned.work.stat()
            with patch('ecra.opencode_storage.shutil.rmtree', side_effect=PermissionError('in use')):
                batch.close()
            marker = read_json(owned.scope/'runtime-retired.json')
            assert marker['identity'] == [before.st_dev, before.st_ino]
        retry_retired_runtime(out, lambda _: None)
        assert not owned.work.exists()
        assert owned.database.read_bytes() == b'private sessions'
        assert running.read_bytes() == b'still used'
    assert not active.work.exists() and db.read_bytes() == b'owned elsewhere'


@pytest.mark.skipif(os.name != 'nt', reason='Requires Windows delete-sharing semantics')
def test_worker_cleanup_retries_only_the_retired_inode(case):
    from ecra.fact_parts import discard_worker_files, retry_worker_cleanup
    out, _, _, _ = case
    worker = out/'workers/TU-123.response.json'
    other = out/'workers/TU-234.response.json'
    worker.parent.mkdir()
    worker.write_bytes(b'retired scan cache')
    other.write_bytes(b'unrelated worker')
    with worker.open('rb'):
        discard_worker_files(worker)
    retry_worker_cleanup(out)
    assert not worker.exists() and other.read_bytes() == b'unrelated worker'
    worker.write_bytes(b'second slot')
    with worker.open('rb'):
        discard_worker_files(worker)
    replacement = worker.with_suffix('.new')
    replacement.write_bytes(b'new owner')
    replacement.replace(worker)
    retry_worker_cleanup(out)
    assert worker.read_bytes() == b'new owner'


@pytest.mark.parametrize('complete', [False, True])
def test_interrupted_object_copy_recovers_only_the_abandoned_writer(tmp_path, complete):
    import subprocess
    import sys
    import uuid

    source = tmp_path/'source'
    source.write_bytes(b'archive bytes repeated' * 1000)
    expected = sha256(source)
    driver = """
import os, sys
from pathlib import Path
from ecra import review_archive
def interrupt(original, stream):
    stream.write(original.read(-1 if sys.argv[2] == 'True' else 512))
    stream.flush()
    os.fsync(stream.fileno())
    os._exit(42)
review_archive.shutil.copyfileobj = interrupt
folder = Path(sys.argv[1])
review_archive.archive_object(folder, folder/'source')
"""
    process = subprocess.run([sys.executable, '-c', driver, str(tmp_path), str(complete)])
    assert process.returncode == 42
    stage = tmp_path/'.ecra-object-copies'
    interrupted, = stage.iterdir()
    live = stage/f'{expected}.{os.getpid()}.{review_archive._writer_birth(os.getpid())}.{uuid.uuid4().hex}.part'
    live.write_bytes(source.read_bytes()[:64])
    if complete:
        source.unlink()  # The finished copy alone can restore this expected object.
    else:
        review_archive.recover_object_copies(tmp_path)
        assert interrupted.is_file()  # No authoritative object yet.
    review_archive.archive_object(tmp_path, source, expected)
    assert sha256(tmp_path/'evidence'/expected) == expected
    assert not interrupted.exists()
    assert live.is_file()


@pytest.mark.skipif(os.name != 'nt', reason='Requires Windows delete-sharing semantics')
def test_completed_shared_cleanup_preserves_navigation_with_an_unrecognized_field(tmp_path):
    from ecra.common import write_json
    from ecra.review_archive import navigation_record, release_saved_shared
    out = tmp_path/'scan'
    folder = out/'review'
    folder.mkdir(parents=True)
    write_json(folder/'facts-navigation.json', navigation_record(out, 'facts'))
    changed = dict(navigation_record(out, 'report'), annotation='keep historical note')
    path = folder/'report-navigation.json'
    write_json(path, changed)
    original = path.read_bytes()
    rows = [dict(state='DONE', archived_files={'project-evidence.json': dict(sha256='a'*64)})]
    release_saved_shared(out, rows, lambda _: None)
    assert not (folder/'facts-navigation.json').exists()
    assert path.read_bytes() == original


def test_preflight_restart_retires_only_its_committed_work_copy(tmp_path):
    from ecra.studio.preflight import _closure_copy, release_preflight_work
    from ecra.studio.tasks import TaskManager

    data = tmp_path/'data'
    task = data/'work/tasks/check'
    folder = task/'preflight'
    folder.mkdir(parents=True)
    plan = folder/'plan.db'
    plan.write_bytes(b'committed plan')
    closure = folder/'input_closure.json'
    closure.write_bytes(b'checked inputs')
    write_json(task/'task.json', dict(id='check', mode='precheck', scan_id='s', state='COMPLETE', started='now'))
    record = dict(state='PRECHECK_READY', passed=True, plan_sha256=sha256(plan), closure_copy=_closure_copy(closure))
    write_json(folder/'preflight.json', record)
    with closure.open('rb'):
        release_preflight_work(folder)
        assert closure.exists()
    TaskManager(data)
    assert not closure.exists()
    closure.write_bytes(b'another run')
    TaskManager(data)
    assert closure.read_bytes() == b'another run'


def test_export_supplies_old_portable_with_exact_queue_projection(case, tmp_path):
    import zipfile
    from ecra.scan_persistence import _encode

    out, run, _, _ = case
    terminal, = run()
    pending = dict(terminal, state='PENDING', review_state='PENDING', review_retry_mode='review')
    append_runtime(out, {}, [pending])
    hashed, raw = _encode(pending)
    assert not (out/'evidence'/hashed).exists()
    package = tmp_path/'paused.ecra-report'
    export_report(out, package)
    with zipfile.ZipFile(package) as archive:
        assert archive.read('evidence/'+hashed) == raw.encode()
    assert not (out/'evidence'/hashed).exists()
    destination = tmp_path/'receiver'
    import_report(package, destination)
    assert runtime(destination/'scans/s')['reviews'] == [pending]


def test_replaced_manual_inputs_remain_verifiable_and_retire_per_variable(case, tmp_path):
    out, run, _, _ = case
    facts = EvidenceProvider(out/'scan.db').load('facts')
    report = EvidenceProvider(out/'scan.db').load('report')
    config = dict(analysis={}, review=dict(enabled=False, prepare_packets=True))
    context = tmp_path/'review-context.md'

    def prepare(text):
        context.write_text(text, 'utf8')
        return review_all(tmp_path, out, config, facts, report, 'scan', review_context_path=context)[0]

    first = prepare('first manual context')
    second = prepare('second manual context')
    assert first['prompt_sha256'] != second['prompt_sha256']
    assert sha256(out/'evidence'/first['prompt_sha256']) == first['prompt_sha256']
    assert not (out/'evidence'/second['prompt_sha256']).exists()
    terminal, = run()
    assert terminal['state'] == 'DONE'
    for name, entry in second['manual_exports'].items():
        assert not (out/'review'/name).exists()
        assert sha256(out/'evidence'/entry['sha256']) == entry['sha256']


def test_full_disk_after_commit_recovers_without_a_cleanup_marker(case):
    import errno

    out, run, calls, _ = case
    unlink = Path.unlink
    write = review_archive.write_receipt

    def locked(path, *args, **kwargs):
        if path.parent == out/'review' and path.name == 'F.result.json' and path.exists():
            raise OSError(errno.ENOSPC, 'full while unlinking')
        return unlink(path, *args, **kwargs)

    def no_marker(path, row, **kwargs):
        if path.parent == out/'diagnostics/review-cleanup':
            raise OSError(errno.ENOSPC, 'full while recording cleanup')
        return write(path, row, **kwargs)

    with patch.object(Path, 'unlink', locked), patch.object(review_archive, 'write_receipt', no_marker):
        row, = run()
    assert row['state'] == 'DONE' and (out/'review/F.result.json').is_file()
    assert not list((out/'diagnostics/review-cleanup').glob('*.json'))
    recovered, = run()
    assert recovered['answer'] == row['answer'] and calls == ['F']
    assert not (out/'review/F.result.json').exists()
