from tests.review_fixtures import mock_runtime
"""Exercise the committed AI ledger through a real static scan and Studio API."""
import contextlib
from collections import Counter
import io
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch

from ecra.common import read_json, write_json
from ecra.scan_persistence import run_canonical, runtime, snapshot_head
from ecra.workflow import saved_run
from tests import test_canonical_scan as fixtures
from tests.test_review_contract import answer_for


class ReviewResumeTests(unittest.TestCase):
    def setUp(self):
        case = fixtures.CanonicalScanTests(methodName='runTest')
        case.setUp()
        self.addCleanup(case.doCleanups)
        self.case = case
        self.out = case.data/'scans'/'review-test'
        self.stop = case.base/'stop'
        names = [f'v{i}' for i in range(10)]
        increments = ' '.join(f'{name}++;' for name in names)
        (case.root/'main.c').write_text('int '+','.join(names)+';\nvoid ISR(void){'+increments+
                                      '}\nint main(void){'+increments+'return v0;}\n', encoding='utf-8')
        raw = read_json(case.config)
        raw['review'].update(enabled=True, workers=1, retries=0)
        write_json(case.config, raw)
        self.calls = []

    def response(self, argv, **kwargs):
        packet = read_json(Path(argv[argv.index('--file')+1]))
        fid = packet['finding_id']
        self.calls.append(fid)
        value = answer_for(status='NEED_MORE_CONTEXT', fid=fid, variable=packet['variable']['qualified_name'])
        value['evidence'] = [dict(file='main.c', line=2, claim='源码中断入口的测试访问。')]
        return subprocess.CompletedProcess(argv, 0, json.dumps(value, ensure_ascii=False), '')

    def model(self, respond=None):
        stack = contextlib.ExitStack()
        stack.enter_context(mock_runtime(['synthetic-review-transport']))
        stack.enter_context(patch('ecra.review.execute', side_effect=respond or self.response))
        stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        return stack

    def scan(self):
        return run_canonical(self.case.root, self.case.config, scan_id=self.out.name)

    def client(self):
        from fastapi.testclient import TestClient
        from ecra.studio.server import create_app
        address = 'http://127.0.0.1:12345'
        return TestClient(create_app(self.case.data, token='review-test', authority=address[7:]),
                          base_url=address, headers={'x-ecra-session': 'review-test', 'origin': address})

    @unittest.skipUnless(importlib.util.find_spec('httpx') or importlib.util.find_spec('httpx2'),
                         'Studio TestClient requires the optional HTTP test dependency')
    def test_first_scan_is_openable_in_studio_during_review(self):
        errors = []
        with self.client() as client:
            observed = []

            def respond(argv, **kwargs):
                done = len(self.calls)
                try:
                    if done == 1:
                        self.assertEqual([i['scan_id'] for i in client.get('/api/scans').json()['items']], [self.out.name])
                    self.assert_progress(client, done)
                    if done:
                        self.assert_receipt(client, self.calls[-1])
                    observed.append(done)
                except Exception as exc:
                    errors.append(exc)
                return self.response(argv, **kwargs)

            with self.model(respond):
                self.assertIn(self.scan(), (0, 1, 2))
            self.assert_progress(client, 10)
            self.assert_receipt(client, self.calls[-1])
        self.assertFalse(errors, errors)
        self.assertEqual(observed, list(range(10)))
        manifest = read_json(self.out/'manifest.json')
        final_audit = read_json(self.out/'evidence'/manifest['audit_index'])['files']
        self.assertIn('diagnostics/completion.json', final_audit)
        archived_run = read_json(self.out/'evidence'/final_audit['run.json']['sha256'])
        self.assertEqual(archived_run['state'], manifest['run_state'])

    def assert_progress(self, client, done):
        response = client.get(f'/api/scans/{self.out.name}/ai', params=dict(limit=1))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['progress'], dict(total=10, done=done, tech_failed=0, pending=10-done))

    def assert_receipt(self, client, fid):
        receipt = read_json(self.out/'review'/(fid+'.result.json'))
        with contextlib.closing(sqlite3.connect(self.out/'reviews.db')) as conn:
            meta = snapshot_head(conn)
            sequence, hashed, raw = conn.execute('SELECT sequence,hash,payload FROM ai_events WHERE finding_id=? ORDER BY sequence DESC', (fid,)).fetchone()
        self.assertEqual(meta['watermark'], sequence)
        self.assertEqual(receipt, json.loads(raw))
        self.assertEqual((self.out/'evidence'/hashed).read_text(encoding='utf-8'), raw)
        execution = receipt['execution']
        for stream in ('prompt', 'packet', 'stderr', 'stdout'):
            self.assertTrue((self.out/'evidence'/execution[stream+'_sha256']).is_file())
        page = client.get(f'/api/scans/{self.out.name}/ai', params=dict(finding_id=fid)).json()
        self.assertEqual(page['items'][0]['state'], 'DONE')
        self.assertEqual(page['items'][0]['status'], 'NEED_MORE_CONTEXT')
        self.assertEqual(page['groups']['safe'], 0)
        original = client.get(f'/api/scans/{self.out.name}/ai-artifact',
                              params=dict(name=execution['stdout_file'], finding_id=fid))
        self.assertEqual(original.status_code, 200, original.text)
        self.assertIn(fid, original.json()['text'])

    def test_three_commits_survive_safe_stop_and_resume_calls_only_remaining_seven(self):
        def respond(argv, **kwargs):
            if len(self.calls) == 2:
                self.stop.touch()
            return self.response(argv, **kwargs)

        with patch.dict(os.environ, ECRA_JOB_STOP_FILE=str(self.stop)), self.model(respond):
            code = self.scan()
        self.assertEqual(code, 130)
        self.assertTrue((self.out/'scan_state.json').is_file())
        self.assertEqual(len(self.calls), 3)
        completed = set(self.calls)
        old = {fid: (self.out/'review'/(fid+'.result.json')).read_bytes() for fid in completed}
        with self.model():
            self.assertIn(saved_run(self.case.root, self.case.config, resume=True), (0, 1, 2))
        self.assertEqual(len(self.calls[3:]), 7)
        self.assertFalse(completed.intersection(self.calls[3:]))
        self.assertEqual(len(set(self.calls)), 10)
        self.assertEqual({r['state'] for r in runtime(self.out)['reviews']}, {'DONE'})
        for fid, receipt in old.items():
            self.assertEqual((self.out/'review'/(fid+'.result.json')).read_bytes(), receipt)

    def test_parallel_workers_commit_without_waiting_for_first_item(self):
        from ecra.native_consumers import runtime_inputs
        from ecra.review import review_all
        from ecra.scan_persistence import append_runtime
        from ecra.config import load_config

        self.out, _ = self.case.run_scan()
        facts, report = runtime_inputs(self.out)
        initial = runtime(self.out)['reviews']
        fingerprint = read_json(self.out/'scan_state.json')['fingerprint']
        cfg, _ = load_config(self.case.root, self.case.config)
        for workers in (1, 2, 4, 8):
            with self.subTest(workers=workers):
                append_runtime(self.out, {}, initial)
                cfg['review']['workers'] = workers
                self.calls.clear()
                first, released = threading.Event(), threading.Event()
                first_id = initial[0]['finding_id']
                checkpoints = []
                errors = []

                def respond(argv, **kwargs):
                    packet = read_json(Path(argv[argv.index('--file')+1]))
                    if workers > 1 and packet['finding_id'] == first_id:
                        first.set()
                        if not released.wait(15):
                            errors.append('首项复核阻塞了其他提交')
                    return self.response(argv, **kwargs)

                def committed(_):
                    rows = runtime(self.out)['reviews']
                    done = {row['finding_id'] for row in rows if row['state'] == 'DONE'}
                    if not checkpoints and workers > 1:
                        try:
                            self.assertTrue(first.wait(5))
                            self.assertNotIn(first_id, done)
                        finally:
                            released.set()
                    checkpoints.append(len(done))

                with self.model(respond):
                    review_all(self.case.root, self.out, cfg, facts, report, fingerprint, on_result=committed, mode='review')
                self.assertFalse(errors, errors)
                self.assertEqual(checkpoints, list(range(1, 11)))
                self.assertEqual(set(Counter(self.calls).values()), {1})

    def test_technical_failures_are_retried_without_losing_valid_receipts(self):
        self.out, _ = self.case.run_scan()

        def respond(argv, **kwargs):
            if '--file' not in argv:
                return subprocess.CompletedProcess(argv, 0, '{broken', '')
            packet = read_json(Path(argv[argv.index('--file')+1]))
            name = packet['variable']['qualified_name']
            if name == 'v3':
                raise subprocess.TimeoutExpired(argv, 1)
            if name == 'v4':
                return subprocess.CompletedProcess(argv, 0, '{broken', '')
            response = self.response(argv, **kwargs)
            if name != 'v5':
                return response
            invalid = json.loads(response.stdout)
            invalid['evidence'][0]['file'] = 'missing.c'
            return subprocess.CompletedProcess(argv, 0, json.dumps(invalid), '')

        with self.model(respond):
            self.assertIn(saved_run(self.case.root, self.case.config, resume=True), (0, 1, 2))
        rows = runtime(self.out)['reviews']
        failures = {r['finding_id'] for r in rows if r['state'] == 'TECH_FAILED'}
        self.assertEqual(len(failures), 3, [(r['finding_id'], r.get('error')) for r in rows if r['state'] == 'TECH_FAILED'])
        self.assertTrue(all(not r.get('answer') for r in rows if r['finding_id'] in failures))
        self.calls.clear()
        with self.model():
            self.assertIn(saved_run(self.case.root, self.case.config, failed_only=True), (0, 1, 2))
        self.assertEqual(set(self.calls), failures)
        self.assertEqual(len(self.calls), 3)

    def test_resume_revalidates_only_damaged_receipt_and_refuses_changed_inputs(self):
        self.out, _ = self.case.run_scan()
        with self.model():
            self.assertIn(saved_run(self.case.root, self.case.config, resume=True), (0, 1, 2))
        fid = self.calls[0]
        cache = self.out/'review'/(fid+'.result.json')
        cache.write_text('{damaged', encoding='utf-8')
        self.calls.clear()
        with self.model():
            self.assertIn(saved_run(self.case.root, self.case.config, resume=True), (0, 1, 2))
        self.assertEqual(self.calls, [fid])
        self.assertTrue(list((self.out/'diagnostics'/'review-recovery').glob(fid+'*')))
        self.calls.clear()
        with (self.case.root/'main.c').open('a', encoding='utf-8') as stream:
            stream.write('// 输入变更\n')
        with self.model():
            self.assertEqual(saved_run(self.case.root, self.case.config, resume=True), 2)
        self.assertEqual(self.calls, [])
        self.assertNotIn('DONE', {r['state'] for r in runtime(self.out)['reviews']})

    def test_interrupted_failed_only_resumes_its_pending_retries(self):
        self.out, _ = self.case.run_scan()

        def fail(argv, **kwargs):
            packet = read_json(Path(argv[argv.index('--file')+1]))
            if packet['variable']['qualified_name'] in {'v3','v4'}:
                return subprocess.CompletedProcess(argv, 1, '', 'synthetic transport error')
            return self.response(argv, **kwargs)

        with self.model(fail):
            self.assertIn(saved_run(self.case.root, self.case.config, resume=True), (0, 1, 2))
        initial = {r['finding_id'] for r in runtime(self.out)['reviews'] if r['state'] == 'TECH_FAILED'}
        self.calls.clear()

        def stop(argv, **kwargs):
            self.stop.touch()
            return self.response(argv, **kwargs)

        with patch.dict(os.environ, ECRA_JOB_STOP_FILE=str(self.stop)), self.model(stop):
            self.assertEqual(saved_run(self.case.root, self.case.config, failed_only=True), 130)
        with self.model():
            self.assertIn(saved_run(self.case.root, self.case.config, failed_only=True), (0, 1, 2))
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(set(self.calls), initial)

    def test_hard_exit_recovers_only_valid_receipts_and_releases_scan_lock(self):
        self.out, _ = self.case.run_scan()
        from ecra.scan_persistence import append_runtime
        initial = runtime(self.out)['reviews']
        driver = Path(__file__).resolve()
        journal = self.case.base/'children.jsonl'
        for stage in ('before-answer', 'before-validation', 'before-commit', 'after-commit', 'parallel'):
            with self.subTest(stage=stage):
                append_runtime(self.out, {}, initial)
                raw = read_json(self.case.config)
                raw['review']['workers'] = 4 if stage == 'parallel' else 1
                write_json(self.case.config, raw)
                result = subprocess.run([sys.executable, '-m', 'tests.test_review_resume', stage,
                    str(self.case.config), str(journal)], capture_output=True, text=True, encoding='utf-8', timeout=90,
                    cwd=driver.parents[1], env={**os.environ, 'PYTHONIOENCODING':'utf-8'})
                self.assertEqual(result.returncode, 42, result.stdout+result.stderr)
                before = runtime(self.out)['reviews']
                self.assertEqual(sum(r['state'] == 'DONE' for r in before), int(stage in {'after-commit', 'parallel'}))
                self.calls.clear()
                with self.model():
                    self.assertIn(saved_run(self.case.root, self.case.config, resume=True), (0, 1, 2))
                self.assertEqual(len(self.calls), 9 if stage in {'before-commit', 'after-commit', 'parallel'} else 10)
                self.assertEqual(len(set(self.calls)), len(self.calls))

    @unittest.skipUnless(os.name == 'nt', 'Windows process tree ownership')
    def test_safe_stop_ends_only_its_owned_opencode_tree_and_preserves_transcript(self):
        from ecra.review_process import ReviewStop, execute
        from ecra.lock_owner import process_identity
        root = self.case.base
        ready = root/'child.pid'
        program = ('import pathlib,subprocess,sys,time; '
                   'child=subprocess.Popen([sys.executable,"-c","import time; time.sleep(60)"]); '
                   'print("partial OpenCode transcript",flush=True); '
                   'pathlib.Path(sys.argv[1]).write_text(str(child.pid)); time.sleep(60)')
        unowned = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
        self.addCleanup(unowned.wait, timeout=3)
        self.addCleanup(unowned.kill)
        with patch.dict(os.environ, ECRA_JOB_STOP_FILE=str(self.stop)):
            stop = ReviewStop()
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(execute, [sys.executable,'-c',program,str(ready)], cwd=root, env=os.environ.copy(),
                timeout=15, stop=stop, stdout_path=root/'stdout', stderr_path=root/'stderr')
            import time
            deadline = time.monotonic()+10
            while not ready.is_file() and time.monotonic() < deadline and not future.done():
                time.sleep(.05)
            self.stop.touch()
            with self.assertRaises(KeyboardInterrupt):
                future.result(timeout=4)
        pid = int(ready.read_text())
        deadline = time.monotonic()+3
        while process_identity(pid) is not False and time.monotonic() < deadline:
            time.sleep(.05)
        self.assertIs(process_identity(pid), False)
        self.assertIsNone(unowned.poll())
        self.assertIn(b'partial OpenCode transcript', (root/'stdout').read_bytes())

    def test_incremental_commit_is_idempotent_and_rejects_two_stale_workers(self):
        from ecra.scan_persistence import append_runtime, commit_review_result, review_head, review_writer

        out = self.case.base
        first = dict(finding_id='F1', state='PENDING', review_request='first')
        append_runtime(out, {}, [first])
        with review_writer(out) as writer:
            initial = snapshot_head(writer)['watermark']
            row = dict(first, state='DONE', review_base_sequence=initial)
            commit_review_result(writer, 0, row)
            committed = snapshot_head(writer)
            commit_review_result(writer, 0, row)
            self.assertEqual(snapshot_head(writer), committed)
            append_runtime(out, {}, [dict(first, review_request='second')])
            head = snapshot_head(writer)
            self.assertEqual(review_head(writer, 'F1', head['watermark'])[2], 'PENDING')
            with self.assertRaisesRegex(ValueError, '当前事件已变化'):
                commit_review_result(writer, 0, row)
            with self.assertRaisesRegex(ValueError, '分发身份不一致'):
                commit_review_result(writer, 0, dict(row, review_base_sequence=head['watermark']))
            self.assertEqual(snapshot_head(writer), head)

    def test_live_reader_does_not_block_or_expose_partial_commit(self):
        from ecra.scan_persistence import append_runtime, commit_review_result, review_writer

        out = self.case.base
        append_runtime(out, {}, [dict(finding_id='F1', state='PENDING')])
        uri = (out/'reviews.db').as_uri()+'?mode=ro'
        with contextlib.closing(sqlite3.connect(uri, uri=True)) as reader, review_writer(out) as writer:
            reader.execute('BEGIN')
            before = snapshot_head(reader)
            row = dict(finding_id='F1', state='DONE', review_base_sequence=before['watermark'])
            commit_review_result(writer, 0, row)
            self.assertEqual(snapshot_head(reader), before)
            reader.commit()
            self.assertGreater(snapshot_head(reader)['watermark'], before['watermark'])

    def test_interrupted_task_retry_routes_only_its_review_scope(self):
        from ecra.studio.tasks import TaskManager

        for mode, published, expected in (
                ('scan', False, 'scan'), ('scan', True, 'review-resume'),
                ('review', True, 'review-resume'), ('review-resume', True, 'review-resume'),
                ('review-failed', True, 'review-failed')):
            with self.subTest(mode=mode, published=published):
                self.assertEqual(TaskManager.retry_mode(dict(mode=mode, review_resumable=published)), expected)


def crash_driver(stage, config, journal):
    from ecra.config import configured_project_root
    from ecra.scan_persistence import commit_review_result
    from ecra.review import parse_answer

    root = configured_project_root(config)
    gate = threading.Barrier(4, timeout=20)

    def invoke(argv, **_):
        packet = read_json(Path(argv[argv.index('--file')+1]))
        fid = packet['finding_id']
        if stage == 'before-answer':
            os._exit(42)
        if stage == 'parallel':
            index = gate.wait()
            if index:
                threading.Event().wait(25)
        with Path(journal).open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(dict(stage=stage, finding_id=fid))+'\n')
        value = answer_for(status='NEED_MORE_CONTEXT', fid=fid, variable=packet['variable']['qualified_name'])
        value['evidence'] = [dict(file='main.c', line=2, claim='断点续跑测试的源码访问。')]
        return subprocess.CompletedProcess(argv, 0, json.dumps(value, ensure_ascii=False), '')

    def validate(*args, **kwargs):
        if stage == 'before-validation':
            os._exit(42)
        return parse_answer(*args, **kwargs)

    def commit(*args, **kwargs):
        if stage == 'before-commit':
            os._exit(42)
        commit_review_result(*args, **kwargs)
        if stage in {'after-commit', 'parallel'}:
            os._exit(42)

    with (mock_runtime(['synthetic-review-transport']),
          patch('ecra.review.execute', side_effect=invoke), patch('ecra.review.parse_answer', side_effect=validate),
          patch('ecra.scan_persistence.commit_review_result', side_effect=commit)):
        saved_run(root, config)


if __name__ == '__main__':
    crash_driver(*sys.argv[1:])
