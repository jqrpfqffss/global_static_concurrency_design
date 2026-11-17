"""Fake OpenCode sessions and real ECRA archives; no user's OpenCode store is used."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Barrier, Event, Lock, Thread
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from ecra.common import read_json, write_json
from ecra.config import load_config
from ecra.review import parse_answer, review_all, validate_result_receipt
from ecra.review_contract import NVICFactConflictError, StaleWritebackSafetyError
from ecra.review_opencode_sessions import API, VERSION, Unverifiable, file_identity, session_from_jsonl
from ecra.review_session_cleanup import JOURNAL
from ecra.scan_persistence import runtime
from ecra.workflow import saved_run
from ecra.workspace import canonical
from tests import test_canonical_scan as fixtures
from tests.test_review_contract import answer_for


def session_id(number):
    return 'ses_' + f'{number:012x}' + 'A'*14


def envelope(sid, text, kind='text', **part):
    return json.dumps(dict(type=kind, timestamp=1, sessionID=sid,
                           part=dict(type={'text': 'text', 'tool_use': 'tool'}[kind],
                                     sessionID=sid, text=text, **part)), ensure_ascii=False)


class FakeOpenCode:
    """A fake CLI transport and per-store loopback service with the v1 routes."""
    def __init__(self):
        self.lock = Lock()
        self.serial = 0
        self.stores = {}
        self.spawned = []
        self.deleted = []
        self.requests = []
        self.maintenance_commands = []
        self.on_delete = None
        self.delete_failure = None
        self.unsupported = False
        self.active = set()
        self.max_active = 0
        self.manual = Path('unmanaged-manual-store')

    def add_session(self, store, title='manual', cwd='.', *, parent=None, sid=None):
        with self.lock:
            self.serial += 1
            sid = sid or session_id(self.serial)
            info = dict(id=sid, title=title, directory=str(Path(cwd).resolve()), projectID='global', version=VERSION)
            if parent:
                info['parentID'] = parent
            self.stores.setdefault(store, {})[sid] = info
            return sid

    def model(self, argv, *, cwd, env, stdout_path, answer=None, during=None, raw=None,
              transport_error=False, child=False, bind_session=None, **options):
        fid = stdout_path.name.split('.', 1)[0]
        stage = stdout_path.name.rsplit('.', 2)[1]
        if '--file' in argv:
            packet = read_json(Path(argv[argv.index('--file')+1]))
            fid = packet['finding_id']
        title = argv[argv.index('--title')+1] if '--title' in argv else 'unmanaged'
        store = Path(env['OPENCODE_DB']) if 'OPENCODE_DB' in env else self.manual
        sid = self.add_session(store, title, cwd, sid=bind_session)
        if child:
            self.add_session(store, parent=sid, cwd=cwd)
        with self.lock:
            self.spawned.append((store, fid, stage, sid))
            self.active.add((store, sid))
            self.max_active = max(self.max_active, len(self.active))
        try:
            if during:
                during(fid, sid)
            if answer is None:
                answer = answer_for(fid=fid)
            if callable(answer):
                answer = answer(fid)
            given = answer if isinstance(answer, str) else json.dumps(answer, ensure_ascii=False)
            if transport_error:
                raise subprocess.TimeoutExpired(argv, .01)
            return subprocess.CompletedProcess(argv, 0, raw(sid, given) if raw else envelope(sid, given), '')
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            stdout_path.write_text(envelope(sid, ''), encoding='utf-8')
            if 'on_exit' in options:
                options['on_exit']()
            raise
        finally:
            with self.lock:
                self.active.discard((store, sid))

    def runtime(self, _command, **options):
        fake = self

        class Runtime:
            exe = Path(sys.executable)
            hash = 'fake-binary'
            command = list(_command)
            product, version = 'SYNTHETIC_TEST_ONLY', VERSION

            def report(self):
                return {'test_only': True}

            def validate_run(self, raw):
                pass

            def check_exe(self):
                pass

            @contextmanager
            def maintenance(self, database, *, workdir, shared=False, environment=None, **context):
                yield Maintenance(database, shared)

        class Maintenance:
            def __init__(self, database, shared):
                self.store = database
                self.shared = shared

            def verify(self):
                if fake.unsupported:
                    raise Unverifiable('unsupported test version')

            def prepare(self):
                # This flag describes optional cleanup, not basic admission.
                self.store.touch()
                if not self.shared:
                    self.checkpoint()
                return file_identity(self.store)

            def checkpoint(self):
                fake.maintenance_commands.append(('checkpoint', self.store))

            def compact(self):
                fake.maintenance_commands.append(('compact', self.store))

            @contextmanager
            def server(self):
                self.verify()
                with fake.server(self.store) as api:
                    yield api

        return Runtime()

    @contextmanager
    def server(self, store):
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                path = urlsplit(self.path).path
                with fake.lock:
                    sessions = fake.stores.setdefault(store, {})
                    if path == '/session/status':
                        value = {sid: {'type': 'busy'} for source, sid in fake.active if source == store}
                    elif path == '/project/current':
                        value = {'id': 'global'}
                    elif path.endswith('/children'):
                        sid = path.split('/')[2]
                        value = [item for item in sessions.values() if item.get('parentID') == sid]
                    else:
                        value = sessions.get(path.split('/')[-1])
                if value is None:
                    self.respond(404, {'name': 'NotFoundError'})
                else:
                    self.respond(200, value)

            def do_DELETE(self):
                sid = self.path.split('/')[-1]
                with fake.lock:
                    fake.requests.append((store, sid))
                try:
                    if fake.delete_failure:
                        failure = fake.delete_failure(store, sid)
                        if failure:
                            self.respond(failure, {'error': 'injected'})
                            return
                    if fake.on_delete:
                        fake.on_delete(store, sid)
                    with fake.lock:
                        self.assert_idle(sid)
                        fake.stores[store].pop(sid)
                        fake.deleted.append((store, sid))
                    self.respond(200, True)
                except Exception:
                    self.respond(500, {'error': 'failed fake safety assertion'})

            def assert_idle(self, sid):
                assert (store, sid) not in fake.active, 'active session was deleted'
                assert not any(s.get('parentID') == sid for s in fake.stores[store].values())

            def respond(self, code, body):
                raw = json.dumps(body).encode()
                self.send_response(code)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                try:
                    self.wfile.write(raw)
                except OSError:  # The timeout test may have already disconnected.
                    pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = Thread(target=server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        thread.start()
        try:
            yield API(server.server_port, 'fake-only')
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


def records(out):
    entries = []
    for journal in (out/'opencode-session-cleanup').glob('*/'+JOURNAL):
        with closing(sqlite3.connect(journal)) as conn:
            conn.row_factory = sqlite3.Row
            entries.extend(dict(row) for row in conn.execute('SELECT * FROM calls'))
    return entries


class CleanupTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory(prefix='ecra cleanup 中文 ')
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        (self.root/'app.c').write_text('int shared;\nvoid IRQ(void){shared++;}\n', encoding='utf-8')
        self.out = self.root/'archive'
        self.fake = FakeOpenCode()
        self.logs = []
        self.cfg = {'review': {'enabled': True, 'retries': 0, 'workers': 1,
                               'session_cleanup': {'enabled': True}}}
        for target, args in (
            ('ecra.review.resolve_command', dict(return_value=[sys.executable])),
            ('ecra.review_opencode_sessions.Runtime', dict(side_effect=self.fake.runtime)),
            ('ecra.review_session_cleanup.Runtime', dict(side_effect=self.fake.runtime)),
            ('ecra.review.execute', dict(side_effect=self.fake.model)),
        ):
            manager = patch(target, **args)
            manager.start()
            self.addCleanup(manager.stop)

    def review(self, count=1, *, out=None, mode='run', respond=None, on_result=None):
        findings = [dict(finding_id=f'F{i}', variable_name='shared', static_classification='SUSPECT')
                    for i in range(count)]
        with patch('ecra.review.execute', side_effect=respond or self.fake.model):
            return review_all(self.root, out or self.out, self.cfg, dict(variables=[]), dict(findings=findings),
                              'static-fingerprint', self.logs.append, mode=mode, on_result=on_result)

    def deleted(self):
        return Counter(self.fake.deleted)

    def test_insufficient_balance_stops_retry_and_preserves_pending(self):
        from ecra.review import ReviewExecutionError
        from ecra.workflow import read_queue
        self.cfg['review']['retries'] = 2
        calls = []
        def quota(argv, **kw):
            calls.append(argv)
            error = dict(type='error', error=dict(name='APIError',
                data=dict(statusCode=429, message='account is suspended due to insufficient balance')))
            return subprocess.CompletedProcess(argv, 1, json.dumps(error), '')
        with self.assertRaises(ReviewExecutionError):
            self.review(4, respond=quota)
        self.assertEqual(len(calls), 1)
        self.assertEqual([r['state'] for r in read_queue(self.out)], ['TECH_FAILED','PENDING','PENDING','PENDING'])

    def test_explicit_batch_keeps_unselected_candidates_pending(self):
        self.cfg['review']['finding_ids'] = ['F1', 'F3']
        rows = self.review(5)
        self.assertEqual([r['state'] for r in rows], ['PENDING','DONE','PENDING','DONE','PENDING'])
        count = len(self.fake.spawned)
        self.review(5, mode='review-resume')
        self.assertEqual(len(self.fake.spawned), count)

    def test_common_initialization_failure_is_one_task_error_and_resumes(self):
        from ecra.review import ReviewInitializationError
        from ecra.review_opencode_sessions import Unavailable
        from ecra.workflow import read_queue
        done = self.review(count=1)[0]
        calls = len(self.fake.spawned)
        with patch.dict(os.environ, OPENCODE_DB=str(self.root/'shared.db')), \
                patch('ecra.opencode_storage.ReviewStorage.prepare', side_effect=Unavailable('db path timeout')):
            with self.assertRaisesRegex(ReviewInitializationError, '初始化失败，复核尚未启动'):
                self.review(count=5, mode='review-resume')
        rows = read_queue(self.out)
        self.assertEqual(Counter(r['state'] for r in rows), {'DONE': 1, 'PENDING': 4})
        self.assertEqual(rows[0], done)
        self.assertEqual(len(self.fake.spawned), calls)
        self.assertTrue(all(not r.get('attempts') for r in rows[1:]))
        self.assertEqual(read_json(self.out/'review/initialization-error.json')['model_calls'], 0)
        rows = self.review(count=5, mode='review-resume')
        self.assertTrue(all(r['state'] == 'DONE' for r in rows))
        self.assertEqual(rows[0], done)
        self.assertEqual(len(self.fake.spawned), calls+4)

    def test_discovered_invalid_configuration_stops_dispatch_without_fake_attempts(self):
        from ecra.review import ReviewExecutionError
        from ecra.workflow import read_queue
        calls = []
        def invalid(argv, **kwargs):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 1, '', 'Configuration is invalid at test-config')
        with self.assertRaisesRegex(ReviewExecutionError, '已停止派发'):
            self.review(count=5, respond=invalid)
        rows = read_queue(self.out)
        self.assertEqual(len(calls), 1)
        self.assertEqual(Counter(r['state'] for r in rows), {'TECH_FAILED': 1, 'PENDING': 4})
        self.assertTrue(all(not row.get('attempts') for row in rows[1:]))
        self.assertTrue(all(r['state'] == 'DONE' for r in self.review(count=5, mode='review-resume')))

    def test_legacy_launch_failure_is_retried_by_failed_only_entry(self):
        from ecra.review_integrity import set_review_state
        row = self.review()[0]
        legacy = set_review_state(dict(row), 'TECH_FAILED')
        legacy.pop('answer', None)
        legacy.update(failure_stage='launch', error='Unavailable: OpenCode 维护命令超时',
                      attempt_count=0, attempts=[])
        write_json(self.out/'review/queue.json', [legacy])
        write_json(self.out/'review/F0.result.json', legacy)
        count = len(self.fake.spawned)
        recovered = self.review(mode='review-failed')[0]
        self.assertEqual(recovered['state'], 'DONE')
        self.assertEqual(len(self.fake.spawned), count+1)

    def expected(self, spawned=None):
        return Counter((store, sid) for store, _, _, sid in (self.fake.spawned if spawned is None else spawned))

    def test_strict_config_default_and_excluded_from_static_identity(self):
        from ecra.workflow import analysis_config
        path = self.root/'semantics.yaml'
        path.write_text('version: 1\n', encoding='utf-8')
        default, _ = load_config(self.root, path)
        self.assertIs(default['review']['session_cleanup']['enabled'], False)
        path.write_text('version: 1\nreview: {session_cleanup: {enabled: true}}\n', encoding='utf-8')
        on, _ = load_config(self.root, path)
        self.assertIs(on['review']['session_cleanup']['enabled'], True)
        self.assertEqual(analysis_config(on), analysis_config(default))
        for value in ('"true"', '1', '0', 'null', '[]', '{}'):
            with self.subTest(value=value):
                path.write_text(f'version: 1\nreview: {{session_cleanup: {{enabled: {value}}}}}\n', encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'review.session_cleanup.enabled'):
                    load_config(self.root, path)

    def test_disabled_then_cache_hit_do_not_adopt_any_session(self):
        self.cfg['review']['session_cleanup']['enabled'] = False
        row, = self.review()
        self.assertEqual(row['state'], 'DONE')
        self.assertFalse((self.out/'opencode-session-cleanup').exists())
        self.assertFalse(self.fake.requests)
        self.cfg['review']['session_cleanup']['enabled'] = True
        cached, = self.review()
        self.assertTrue(cached['cached'])
        self.assertEqual(cached['cache_key'], row['cache_key'])
        self.assertNotIn('session_cleanup', read_json(self.out/'review/project-evidence.json')['config']['review'])
        self.assertEqual(len(self.fake.spawned), 1)
        self.assertFalse(self.fake.requests)
        self.assertFalse(records(self.out))

    def test_single_variable_cleans_only_after_durable_receipt_and_keeps_manual_session(self):
        external = self.fake.add_session(self.fake.manual)

        def committed(_store, _sid):
            self.assertEqual(read_json(self.out/'review/F0.result.json')['state'], 'DONE')
            self.assertEqual(read_json(self.out/'review/queue.json')[0]['state'], 'DONE')

        self.fake.on_delete = committed
        row, = self.review()
        self.assertEqual(self.deleted(), self.expected())
        self.assertIn(external, self.fake.stores[self.fake.manual])
        validate_result_receipt(self.root, self.out/'review', row, 'F0', 'static-fingerprint', 'SUSPECT')
        self.assertEqual(row['answer']['status'], 'CONFIRMED')

    def test_multiple_stages_and_technical_retries_have_distinct_claims(self):
        self.cfg['review']['retries'] = 1
        stages = Counter()

        def respond(argv, **kwargs):
            stage = kwargs['stdout_path'].name.rsplit('.', 2)[1]
            stages[stage] += 1
            answer = answer_for(fid='F0')
            if stage == 'ANALYZE':
                return self.fake.model(argv, **kwargs, answer='{}', transport_error=stages[stage] == 1)
            if stage == 'FORMAT_FIX':
                answer.update(reason='The IRQ can overwrite the old value.', summary='bad')
            elif stage == 'LANGUAGE_FIX':
                answer.update(reason='IRQ 可以覆盖旧值。', summary='bad')
            else:
                answer = {'summary': answer['summary']}
            return self.fake.model(argv, **kwargs, answer=answer)

        row, = self.review(respond=respond)
        self.assertEqual(row['state'], 'DONE', row.get('error'))
        self.assertEqual(stages, Counter(ANALYZE=2, FORMAT_FIX=1, LANGUAGE_FIX=1, SUMMARY_FIX=1))
        self.assertEqual(self.deleted(), self.expected())
        self.assertEqual({r['review_request'] for r in records(self.out)}, {row['review_request']})
        self.assertEqual({r['process_state'] for r in records(self.out)}, {'EXITED'})

    def test_semantic_challenges_use_the_same_post_archive_boundary(self):
        # Exercise the two invoke call sites without inventing static NVIC
        # facts or changing the existing validators' tested semantics.
        checks = [NVICFactConflictError('missing fact'), None, None, None, None]
        with patch('ecra.review.validate_nvic_missing_facts', side_effect=checks), \
                patch('ecra.review.parse_answer') as parse:
            count = 0

            def challenge(*args, **kwargs):
                nonlocal count
                count += 1
                if count == 2:
                    raise StaleWritebackSafetyError('blocking proof missing')
                return parse_answer(*args, **kwargs)

            parse.side_effect = challenge
            row, = self.review()
        self.assertEqual(row['state'], 'DONE', row.get('error'))
        self.assertEqual({stage for _, _, stage, _ in self.fake.spawned},
                         {'ANALYZE', 'NVIC_FACT_CHALLENGE', 'STALE_WRITEBACK_CHALLENGE'})
        self.assertEqual(self.deleted(), self.expected())

    def test_three_workers_delete_only_the_committed_variable_while_others_are_active(self):
        self.cfg['review']['workers'] = 3
        all_started, release = Barrier(3), Event()
        observations = []
        shared_db = self.root/'历史 会话.db'
        manual = self.fake.add_session(shared_db)

        def during(fid, _sid):
            all_started.wait(timeout=10)
            if fid != 'F1':
                self.assertTrue(release.wait(10))

        def deleted(store, sid):
            observations.append((sid, {value for path, value in self.fake.active if path == store}))
            release.set()

        self.fake.on_delete = deleted
        with patch.dict(os.environ, OPENCODE_DB=str(shared_db)):
            self.review(3, respond=lambda *args, **kwargs: self.fake.model(*args, **kwargs, during=during))
        by_fid = {fid: sid for _, fid, _, sid in self.fake.spawned}
        self.assertEqual(observations[0], (by_fid['F1'], {by_fid['F0'], by_fid['F2']}))
        self.assertEqual(self.deleted(), self.expected())
        self.assertEqual(set(self.fake.stores[shared_db]), {manual})
        self.assertFalse(self.fake.maintenance_commands)

    def test_two_tasks_eight_workers_each_with_100_variables_and_manual_sessions(self):
        self.cfg['review']['workers'] = 8
        other = self.root/'other task'
        auth_home = self.root/'fixture-credentials'
        write_json(auth_home/'opencode/auth.json', {'fixture': {'type': 'api', 'key': 'fixture-key'}})
        manuals = {self.fake.add_session(self.fake.manual) for _ in range(8)}
        tasks, workers = Barrier(2), Barrier(16)
        unchecked = set()

        def during(fid, _sid):
            # Reversed completion order, eight slots in use per task.
            if int(fid[1:]) < 8:
                workers.wait(timeout=45)
            time.sleep((8-int(fid[1:]) % 8)*.001)

        def deleted(store, sid):
            fid, = [fid for key, fid, _, candidate in self.fake.spawned if (key, candidate) == (store, sid)]
            out = store.parents[2]
            if read_json(out/'review'/(fid+'.result.json'))['state'] != 'DONE':
                unchecked.add((store, sid))

        def work(out, count):
            tasks.wait(timeout=5)
            return review_all(self.root, out, self.cfg, dict(variables=[]),
                              dict(findings=[dict(finding_id=f'F{i}', variable_name='shared',
                                   static_classification='SUSPECT') for i in range(count)]),
                              'static-fingerprint', self.logs.append)

        self.fake.on_delete = deleted
        with patch.dict(os.environ, XDG_DATA_HOME=str(auth_home)), \
             patch('ecra.review.execute', side_effect=lambda *args, **kw: self.fake.model(*args, **kw, during=during)):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(work, self.out, 100), pool.submit(work, other, 12)]
                errors = [(row['finding_id'], row.get('error')) for future in futures
                          for row in future.result(timeout=300) if row['state'] != 'DONE']
                self.assertEqual(len(errors), 0, errors[:5])
        self.assertFalse(unchecked)
        self.assertEqual(self.fake.max_active, 16)
        pending = [(row['finding_id'], row['cleanup_state'], row['reason'])
                   for out in (self.out, other) for row in records(out) if row['cleanup_state'] != 'DELETED']
        self.assertFalse(pending, (pending[:8], self.logs[-5:]))
        self.assertFalse(self.expected() - self.deleted(), self.logs[-5:])
        self.assertEqual(self.deleted(), self.expected())
        self.assertEqual(Counter(self.fake.requests), self.expected())
        self.assertEqual(set(self.fake.stores[self.fake.manual]), manuals)
        self.assertEqual(len({store for store, *_ in self.fake.spawned}), 2)

    def test_missing_conflicting_illegal_and_nested_ids_do_not_grant_ownership(self):
        plain = json.dumps(answer_for(fid='F0'))
        one, two = session_id(999), session_id(1000)
        self.assertEqual(session_from_jsonl(envelope(one, envelope(two, '<fake>'))),
                         (one, {one}, ''))
        self.assertEqual(session_from_jsonl(envelope(one, '', kind='tool_use', state={'output': envelope(two, '')})),
                         (one, {one}, ''))
        for label, raw in dict(missing=lambda a, b: b, illegal=lambda a, b: envelope('../oops', b),
                               conflict=lambda a, b: envelope(a, b)+'\n'+envelope(two, '')).items():
            with self.subTest(label=label):
                out = self.root/label
                row, = self.review(out=out, respond=lambda *a, **kw: self.fake.model(*a, **kw, raw=raw))
                self.assertEqual(row['state'], 'DONE')
                entry, = records(out)
                self.assertEqual(entry['cleanup_state'], 'SKIPPED_UNVERIFIABLE')
                self.assertTrue(entry['reason'])
        self.assertIsNone(session_from_jsonl(plain)[0])
        self.assertFalse(self.fake.requests)

    def test_multiple_claimants_and_unknown_children_are_protected(self):
        sid = session_id(2000)

        def duplicate(argv, **kw):
            stage = kw['stdout_path'].name.rsplit('.', 2)[1]
            return self.fake.model(argv, **kw, bind_session=sid,
                                   answer='{}' if stage == 'ANALYZE' else None)

        row, = self.review(respond=duplicate)
        self.assertEqual(row['state'], 'DONE')
        self.assertTrue(all('多个调用' in row['reason'] for row in records(self.out)))
        self.review(out=self.root/'child', respond=lambda *a, **kw: self.fake.model(*a, **kw, child=True))
        self.assertIn('子会话', records(self.root/'child')[0]['reason'])
        self.assertFalse(self.fake.requests)

    def test_delete_failure_is_done_and_resume_retries_without_model(self):
        self.fake.delete_failure = lambda *_: 503
        row, = self.review()
        self.assertEqual(row['state'], 'DONE')
        self.assertEqual(records(self.out)[0]['cleanup_state'], 'DELETE_FAILED')
        self.fake.delete_failure = None
        recovered, = self.review(mode='review-resume')
        self.assertEqual(recovered, row)
        self.assertEqual(self.deleted(), self.expected())
        self.assertEqual(len(self.fake.spawned), 1)
        self.assertEqual(Counter(self.fake.requests), self.expected() + self.expected())

    def test_delete_timeout_preserves_done_and_does_not_block_next_model(self):
        timeout_waiting, next_completed = Event(), Event()

        def timeout(*_):
            timeout_waiting.set()
            next_completed.wait(2)
            time.sleep(.2)
            return 503

        def model(argv, **kw):
            if 'F1.' in kw['stdout_path'].name:
                self.assertTrue(timeout_waiting.wait(5))
                next_completed.set()
            return self.fake.model(argv, **kw)

        self.fake.delete_failure = timeout
        with patch('ecra.review_opencode_sessions.REQUEST_TIMEOUT', .10):
            rows = self.review(2, respond=model)
        self.assertEqual([row['state'] for row in rows], ['DONE', 'DONE'])
        self.assertEqual({row['cleanup_state'] for row in records(self.out)}, {'DELETE_FAILED'})
        self.assertFalse(self.fake.deleted)
        self.assertEqual(len(self.fake.requests), 1)

    def test_unsupported_cleanup_does_not_change_review_transport(self):
        self.fake.unsupported = True
        manual = self.fake.add_session(self.fake.manual)
        row, = self.review()
        self.assertEqual(row['state'], 'DONE')
        self.assertFalse(self.fake.requests)
        self.assertTrue(self.fake.spawned[0][0].is_relative_to(self.out/'opencode'))
        self.assertEqual(set(self.fake.stores[self.fake.manual]), {manual})
        capability = read_json(self.out/'review/opencode-capabilities.json')
        self.assertIn('unsupported test version', capability['cleanup_error'])
        self.assertEqual(records(self.out)[0]['cleanup_state'], 'SKIPPED_UNVERIFIABLE')

    def test_failed_and_interrupted_calls_are_retained_on_resume_and_retry(self):
        row, = self.review(respond=lambda *a, **kw: self.fake.model(*a, **kw, transport_error=True))
        self.assertEqual(row['state'], 'TECH_FAILED')
        failed = self.fake.spawned[0]
        self.assertEqual(records(self.out)[0]['cleanup_state'], 'RETAINED')
        row, = self.review(mode='review-failed')
        self.assertEqual(row['state'], 'DONE')
        self.assertEqual(self.deleted(), self.expected(self.fake.spawned[1:]))
        self.assertIn(failed[3], self.fake.stores[failed[0]])

        def pause(argv, **kwargs):
            def interrupt(fid, _sid):
                if fid == 'F1':
                    raise KeyboardInterrupt()
            return self.fake.model(argv, **kwargs, during=interrupt)

        other = self.root/'paused'
        with self.assertRaises(KeyboardInterrupt):
            self.review(3, out=other, respond=pause)
        _, inactive = self.fake.spawned[-2:]
        self.assertIn(inactive[3], self.fake.stores[inactive[0]])
        rows = self.review(3, out=other, mode='review-resume')
        self.assertTrue(all(row['state'] == 'DONE' for row in rows))
        self.assertEqual(self.deleted(), self.expected([x for x in self.fake.spawned if x not in (failed, inactive)]))

    def test_explicit_rereview_leaves_previous_failed_deletion_alone(self):
        self.fake.delete_failure = lambda *_: 500
        old, = self.review()
        first = self.fake.spawned[0]
        self.fake.delete_failure = None
        new, = self.review(mode='review')
        self.assertNotEqual(old['review_request'], new['review_request'])
        self.assertEqual(self.deleted(), self.expected(self.fake.spawned[1:]))
        self.assertIn(first[3], self.fake.stores[first[0]])

    def test_replaced_store_is_not_adopted_on_resume(self):
        self.fake.delete_failure = lambda *_: 503
        store = self.root/'shared.db'
        with patch.dict(os.environ, OPENCODE_DB=str(store)):
            self.review()
            sid = self.fake.spawned[0][3]
            store.rename(store.with_suffix('.previous'))
            store.touch()
            self.fake.delete_failure = None
            self.review(mode='review-resume')
        self.assertEqual(self.fake.requests, [(store, sid)])
        self.assertFalse(self.fake.deleted)

    def test_resume_uses_original_shared_store_when_override_changes(self):
        store, other = self.root/'first.db', self.root/'second.db'
        self.fake.delete_failure = lambda *_: 503
        with patch.dict(os.environ, OPENCODE_DB=str(store)):
            row, = self.review()
        sid = self.fake.spawned[0][3]
        other.touch()
        self.fake.stores[other] = {sid: dict(self.fake.stores[store][sid])}
        self.fake.delete_failure = None
        with patch.dict(os.environ, OPENCODE_DB=str(other)):
            resumed, = self.review(mode='review-resume')
        self.assertEqual(resumed, row)
        self.assertEqual(self.fake.deleted, [(store, sid)])
        self.assertIn(sid, self.fake.stores[other])
        self.assertEqual(len(self.fake.spawned), 1)
        self.assertFalse(self.fake.maintenance_commands)

    def test_resume_recovers_legacy_managed_database_in_journal_directory(self):
        from ecra.review_session_cleanup import SessionCleanup

        self.fake.delete_failure = lambda *_: 503
        row, = self.review()
        store, _, _, sid = self.fake.spawned[0]
        journal, = (self.out/'opencode-session-cleanup').glob('*/'+JOURNAL)
        legacy_store = journal.parent/'sessions.db'
        store.rename(legacy_store)
        self.fake.stores[legacy_store] = self.fake.stores.pop(store)
        with closing(sqlite3.connect(journal)) as conn, conn:
            recorded = json.loads(conn.execute('SELECT binding FROM run').fetchone()[0])
            del recorded['database'], recorded['shared']
            recorded['schema'] = 1
            cleanup = SessionCleanup(self.root, self.out, 'static-fingerprint', self.logs.append)
            recorded['environment'] = cleanup.environment_binding(legacy=True)
            conn.execute('UPDATE run SET binding=?', (json.dumps(recorded),))
        self.fake.delete_failure = None
        resumed, = self.review(mode='review-resume')
        self.assertEqual(resumed, row)
        self.assertEqual(self.fake.deleted, [(legacy_store, sid)])

    def test_same_id_in_other_stores_cannot_be_deleted(self):
        sid = session_id(9000)
        self.fake.add_session(self.fake.manual, sid=sid)
        other = self.root/'failed-task'
        self.review(out=other, respond=lambda *a, **kw:
                    self.fake.model(*a, **kw, bind_session=sid, transport_error=True))
        self.review(respond=lambda *a, **kw: self.fake.model(*a, **kw, bind_session=sid))
        first, second = self.fake.spawned
        self.assertEqual(self.fake.requests, [(second[0], sid)])
        self.assertIn(sid, self.fake.stores[first[0]])
        self.assertIn(sid, self.fake.stores[self.fake.manual])

    def test_lost_delete_ack_recovery_does_not_send_a_second_delete(self):
        from ecra.review_session_cleanup import Run
        update = Run.state

        def lost(run, call, state, reason=''):
            if state == 'DELETED':
                raise OSError('lost after DELETE')
            return update(run, call, state, reason)

        with patch.object(Run, 'state', lost):
            self.review()
        self.assertEqual(records(self.out)[0]['cleanup_state'], 'READY_TO_DELETE')
        self.review(mode='review-resume')
        self.assertEqual(records(self.out)[0]['cleanup_state'], 'DELETED')
        self.assertEqual(Counter(self.fake.requests), self.expected())

    def test_live_run_lease_excludes_another_process(self):
        def probe(_store, _sid):
            # Separate Python process, same run folder. It must not be able
            # to adopt/recover or compact a store still used by its owner.
            journal, = (self.out/'opencode-session-cleanup').glob('*/'+JOURNAL)
            result = subprocess.run([sys.executable, '-c',
                'from ecra.storage_activity import DataActivity, DataBusy\n'
                'import sys\n'
                'try:\n with DataActivity(sys.argv[1], exclusive=True): sys.exit(8)\n'
                'except DataBusy: sys.exit(0)\n',
                str(journal.parent)], capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)

        self.fake.on_delete = probe
        self.review()
        self.assertEqual(self.deleted(), self.expected())

    def test_interrupt_during_cleanup_join_does_not_release_lease_early(self):
        from ecra.storage_activity import DataActivity, DataBusy
        deleting, release = Event(), Event()
        shutdown = ThreadPoolExecutor.shutdown

        def pause_delete(*_):
            deleting.set()
            self.assertTrue(release.wait(10))

        def interrupt(pool, *args, **kwargs):
            if pool._thread_name_prefix == 'opencode-cleanup':
                self.assertTrue(deleting.wait(5))
                shutdown(pool, wait=False)
                raise KeyboardInterrupt()
            return shutdown(pool, *args, **kwargs)

        self.fake.on_delete = pause_delete
        try:
            with patch.object(ThreadPoolExecutor, 'shutdown', interrupt), self.assertRaises(KeyboardInterrupt):
                self.review()
            journal, = (self.out/'opencode-session-cleanup').glob('*/'+JOURNAL)
            with self.assertRaises(DataBusy):
                with DataActivity(journal.parent, exclusive=True):
                    pass
        finally:
            release.set()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                with DataActivity(journal.parent, exclusive=True):
                    break
            except DataBusy:
                time.sleep(.02)
        else:
            self.fail('cleanup worker did not release its run')
        self.assertEqual(self.deleted(), self.expected())


class NativeCleanupTests(unittest.TestCase):
    def setUp(self):
        case = fixtures.CanonicalScanTests(methodName='runTest')
        case.setUp()
        self.addCleanup(case.doCleanups)
        self.case = case
        self.out, _ = case.run_scan()
        self.cfg = read_json(case.config)
        self.cfg['review']['session_cleanup'] = {'enabled': True}
        self.cfg['review']['retries'] = 0
        write_json(case.config, self.cfg)
        self.fake = FakeOpenCode()
        self.client_address = 'http://127.0.0.1:12345'
        self.logs = io.StringIO()
        for manager in (
            patch('ecra.review.resolve_command', return_value=[sys.executable]),
            patch('ecra.review_opencode_sessions.Runtime', side_effect=self.fake.runtime),
            patch('ecra.review_session_cleanup.Runtime', side_effect=self.fake.runtime),
            patch('ecra.review.execute', side_effect=self.model),
            redirect_stdout(self.logs),
        ):
            manager.__enter__()
            self.addCleanup(manager.__exit__, None, None, None)

    def model(self, argv, **kw):
        def answer(fid):
            result = answer_for('NEED_MORE_CONTEXT', fid=fid)
            result['evidence'] = [dict(file='main.c', line=1, claim='中断入口的已归档访问。')]
            return result
        return self.fake.model(argv, **kw, answer=answer)

    def resume(self):
        return saved_run(self.case.root, self.case.config, resume=True, _out=self.out)

    def test_commit_failure_then_reconciled_orphan_recovers_without_rerunning_model(self):
        with patch('ecra.scan_persistence.commit_review_result', side_effect=OSError('lost before commit')):
            with self.assertRaisesRegex(OSError, 'lost before commit'):
                self.resume()
        self.assertFalse(self.fake.requests)
        self.assertEqual(runtime(self.out)['reviews'][0]['state'], 'PENDING')
        self.assertIn(self.resume(), (0, 1, 2))
        self.assertEqual(runtime(self.out)['reviews'][0]['state'], 'DONE')
        self.assertEqual(len(self.fake.spawned), 1)
        self.assertEqual(self.fake.deleted, [(self.fake.spawned[0][0], self.fake.spawned[0][3])])

    def test_post_commit_crash_retries_and_preserves_studio_evidence(self):
        # Lose the notification at the exact boundary after SQLite commits;
        # the durable call must still be discoverable from a new review run.
        with patch('ecra.review_session_cleanup.SessionCleanup.after_archive', side_effect=KeyboardInterrupt()):
            self.assertEqual(self.resume(), 130)
        before, = runtime(self.out)['reviews']
        self.assertEqual(before['state'], 'DONE')
        self.assertFalse(self.fake.requests)
        self.assertEqual(records(self.out)[0]['cleanup_state'], 'WAITING_FOR_ARCHIVE')
        self.assertIn(self.resume(), (0, 1, 2))
        self.assertEqual(runtime(self.out)['reviews'], [before])
        self.assertEqual(len(self.fake.spawned), 1)
        self.assertEqual(self.fake.deleted, [(self.fake.spawned[0][0], self.fake.spawned[0][3])])

        from fastapi.testclient import TestClient
        from ecra.studio.server import create_app
        with TestClient(create_app(self.case.data, token='cleanup-test', authority=self.client_address[7:]),
                        base_url=self.client_address,
                        headers={'x-ecra-session': 'cleanup-test', 'origin': self.client_address}) as client:
            url = f'/api/scans/{self.out.name}'
            fid = before['finding_id']
            result = client.get(url+'/ai', params=dict(finding_id=fid))
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json()['items'][0]['status'], 'NEED_MORE_CONTEXT')
            for stream in ('stdout', 'stderr', 'prompt', 'packet'):
                content = client.get(url+'/ai-artifact', params=dict(finding_id=fid,
                                     name=before['execution'][stream+'_file']))
                self.assertEqual(content.status_code, 200, content.text)
                if stream == 'stdout':
                    self.assertIn(fid, content.json()['text'])

    def test_damaged_evidence_never_deletes(self):
        from ecra.scan_persistence import commit_review_result

        def corrupt(*args, **kwargs):
            commit_review_result(*args, **kwargs)
            row = args[2]
            object_path = self.out/'evidence'/row['execution']['stderr_sha256']
            object_path.write_bytes(b'tampered')

        with patch('ecra.scan_persistence.commit_review_result', side_effect=corrupt):
            with self.assertRaisesRegex(ValueError, '审计对象损坏'):
                self.resume()
        self.assertFalse(self.fake.requests)
        self.assertIn('摘要', records(self.out)[0]['reason'])


if __name__ == '__main__':
    unittest.main()
