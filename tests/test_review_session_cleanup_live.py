"""Opt-in real OpenCode + ECRA + Studio check with an isolated local model fixture."""
from collections import Counter
from contextlib import closing, contextmanager, redirect_stdout
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import re
import socket
from threading import Thread
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

from ecra.common import read_json, write_json
from ecra.review import validate_result_receipt
from ecra.review_opencode_sessions import API, Runtime, VERSION
from ecra.review_session_cleanup import Run
from ecra.scan_persistence import run_canonical, runtime
from tests import test_canonical_scan as fixtures
from tests.test_review_contract import answer_for


@contextmanager
def local_model():
    completed = []

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            messages = json.dumps(request['messages'], ensure_ascii=False)
            match = re.search(r'finding_id 必须原样返回：([\w.:-]+)', messages)
            variable = re.search(r'含变量名 (v\d+)、', messages)
            if self.path != '/v1/chat/completions' or not match or not variable:
                self.send_error(400, 'unexpected fixture model request')
                return
            fid = match[1]
            answer = answer_for('NEED_MORE_CONTEXT', fid=fid, variable=variable[1])
            answer['evidence'] = [dict(file='main.c', line=2, claim='中断入口中存在对被测变量的访问。')]
            answer['reason'] = '已核对归档源码。原始证据保留供复查。' * 4000
            content = json.dumps(answer, ensure_ascii=False)
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()
            chunks = [
                {'choices': [{'index': 0, 'delta': {'role': 'assistant', 'content': content},
                              'finish_reason': None}]},
                {'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}],
                 'usage': {'prompt_tokens': 240, 'completion_tokens': 100, 'total_tokens': 340}},
            ]
            for chunk in chunks:
                event = {'id': 'ecra-fixture', 'object': 'chat.completion.chunk', 'created': 1, 'model': 'fixture'}
                self.wfile.write(b'data: ' + json.dumps(dict(event, **chunk), ensure_ascii=False).encode() + b'\n\n')
            self.wfile.write(b'data: [DONE]\n\n')
            completed.append(fid)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Provider)
    thread = Thread(target=server.serve_forever, kwargs={'poll_interval': .05}, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}/v1', completed
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def create_manual(api, directory):
    with closing(http.client.HTTPConnection('127.0.0.1', api.port, timeout=10)) as conn:
        conn.request('POST', '/session?'+urlencode(dict(directory=str(directory))),
                     json.dumps(dict(title='Manual fixture session')),
                     {'Authorization': api.authorization, 'Content-Type': 'application/json'})
        with conn.getresponse() as response:
            body = json.loads(response.read())
            if response.status != 200:
                raise AssertionError(body)
            return body['id']


def storage_bytes(database):
    """Count allocated bytes for the actual OpenCode DB and any WAL sidecars."""
    paths = [database, database.with_name(database.name+'-wal'), database.with_name(database.name+'-shm')]
    if os.name != 'nt':
        return sum(path.stat().st_blocks * 512 for path in paths if path.is_file())
    import ctypes
    import msvcrt
    from ctypes import wintypes

    class FileStandardInfo(ctypes.Structure):
        _fields_ = [('allocation', ctypes.c_longlong), ('end', ctypes.c_longlong),
                    ('links', wintypes.DWORD), ('delete_pending', ctypes.c_byte), ('directory', ctypes.c_byte)]

    get_info = ctypes.WinDLL('kernel32', use_last_error=True).GetFileInformationByHandleEx
    get_info.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    get_info.restype = wintypes.BOOL
    total = 0
    for path in paths:
        if path.is_file():
            with path.open('rb') as stream:
                info = FileStandardInfo()
                if not get_info(msvcrt.get_osfhandle(stream.fileno()), 1, ctypes.byref(info), ctypes.sizeof(info)):
                    raise ctypes.WinError(ctypes.get_last_error())
                total += info.allocation
    return total


@contextmanager
def studio_api(data):
    import uvicorn
    from ecra.studio.server import create_app
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        host, port = listener.getsockname()
        authority = f'{host}:{port}'
        app = create_app(data, token='fixture-test', authority=authority)
        server = uvicorn.Server(uvicorn.Config(app, log_level='critical'))
        thread = Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(.02)
            if not server.started:
                raise AssertionError('Studio did not start')

            def get(path):
                with closing(http.client.HTTPConnection(host, port, timeout=10)) as conn:
                    conn.request('GET', path, headers={'X-ECRA-Session': 'fixture-test', 'Origin': 'http://'+authority})
                    with conn.getresponse() as response:
                        body = json.loads(response.read())
                        if response.status != 200:
                            raise AssertionError(body)
                        return body

            yield get
        finally:
            server.should_exit = True
            thread.join(timeout=10)


@unittest.skipUnless(os.getenv('ECRA_TEST_OPENCODE_EXE'), 'opt in with ECRA_TEST_OPENCODE_EXE=absolute executable')
class RealOpenCodeCleanupTest(unittest.TestCase):
    def test_real_opencode_live_disk_and_studio(self):
        case = fixtures.CanonicalScanTests(methodName='runTest')
        case.setUp()
        self.addCleanup(case.doCleanups)
        exe = str(Path(os.environ['ECRA_TEST_OPENCODE_EXE']).resolve(strict=True))
        fake_home = case.base/'opencode-fixture'
        fake_home.mkdir()
        env = {k: v for k, v in os.environ.items()
               if not k.upper().startswith(('OPENCODE_', 'OPENAI_')) and 'PROXY' not in k.upper()}
        for area in ('DATA', 'CONFIG', 'CACHE', 'STATE'):
            env[f'XDG_{area}_HOME'] = str(fake_home/area.lower())
            (fake_home/area.lower()).mkdir()
        tmp = fake_home/'temp'
        tmp.mkdir()
        manual_db = fake_home/'manual-test.db'
        env.update(OPENCODE_TEST_HOME=str(fake_home), OPENCODE_DB=str(manual_db),
                   OPENCODE_DISABLE_AUTOUPDATE='true', OPENCODE_DISABLE_MODELS_FETCH='true',
                   OPENCODE_DISABLE_DEFAULT_PLUGINS='true', TEMP=str(tmp), TMP=str(tmp), TMPDIR=str(tmp))

        names = [f'v{i}' for i in range(4)]
        access = ' '.join(f'{name}++;' for name in names)
        (case.root/'main.c').write_text('int '+','.join(names)+';\nvoid ISR(void){'+access+
                                       '}\nint main(void){'+access+'return v0;}\n', encoding='utf-8')
        cfg = read_json(case.config)
        cfg['review'].update(enabled=True, command=[exe], workers=3, retries=0, timeout_seconds=90,
                             model='ecra-fixture/fixture', session_cleanup={'enabled': True})
        write_json(case.config, cfg)
        out = case.data/'scans'/'opencode-cleanup-live'
        sizes, deleted = [], []
        request, compact = API.request, Run.compact

        def observe_request(api, method, route, *args, **kwargs):
            result = request(api, method, route, *args, **kwargs)
            if method == 'DELETE':
                self.assertIs(result, True)
                deleted.append(route.rsplit('/', 1)[-1])
            return result

        def observe_compact(run):
            before = storage_bytes(run.database)
            compact(run)
            sizes.append((before, storage_bytes(run.database)))

        with patch.dict(os.environ, env, clear=True), local_model() as (base_url, model_calls):
            write_json(fake_home/'config/opencode/opencode.json', dict(autoupdate=False,
                enabled_providers=['ecra-fixture'], provider={'ecra-fixture': dict(
                    npm='@ai-sdk/openai-compatible', name='Local replay fixture',
                    options=dict(baseURL=base_url, apiKey='fixture-no-credentials'),
                    models={'fixture': dict(name='fixture', limit=dict(context=200000, output=100000))})}))
            opencode = Runtime([exe])
            with opencode.maintenance(manual_db) as maintenance:
                maintenance.verify()
                maintenance.compact()
                with maintenance.server() as api:
                    manual_id = create_manual(api, case.root)
                    original = api.request('GET', '/session/'+manual_id)
                    log = io.StringIO()
                    with patch.object(API, 'request', observe_request), patch.object(Run, 'compact', observe_compact), \
                            redirect_stdout(log):
                        result = run_canonical(case.root, case.config, scan_id=out.name)
                    self.assertIn(result, (0, 1, 2), log.getvalue())
                    self.assertEqual(api.request('GET', '/session/'+manual_id), original)

        rows = runtime(out)['reviews']
        self.assertEqual(len(rows), len(names), log.getvalue())
        self.assertEqual({row['state'] for row in rows}, {'DONE'}, log.getvalue() + repr([
            (row['finding_id'], row.get('error')) for row in rows]))
        self.assertEqual(Counter(model_calls), Counter(row['finding_id'] for row in rows))
        from ecra.review_opencode_sessions import session_from_jsonl
        archived_ids = []
        for row in rows:
            validate_result_receipt(case.root, out/'review', row, row['finding_id'],
                                    row['scan_fingerprint'], row['static_classification'])
            evidence = out/'evidence'/row['execution']['stdout_sha256']
            sid = session_from_jsonl(evidence.read_text('utf-8'))[0]
            self.assertIsNotNone(sid)
            archived_ids.append(sid)
        self.assertEqual(Counter(deleted), Counter(archived_ids), log.getvalue())
        self.assertNotIn(manual_id, deleted)
        self.assertEqual(len(sizes), 1, log.getvalue())
        before, after = sizes[0]
        self.assertGreater(before, after, log.getvalue())

        with studio_api(case.data) as studio:
            path = f'/api/scans/{out.name}'
            self.assertEqual(studio(path+'/ai')['progress']['done'], len(names))
            row = rows[0]
            for stream in ('stdout', 'stderr', 'prompt', 'packet'):
                query = urlencode(dict(finding_id=row['finding_id'], name=row['execution'][stream+'_file']))
                self.assertIn('text', studio(path+'/ai-artifact?'+query))
        print(json.dumps(dict(opencode=VERSION, variables=len(rows), workers=3, precise_deletes=len(deleted),
                              manual_retained=1, disk_before_compaction=before, disk_after_compaction=after,
                              bytes_reclaimed=before-after, studio_evidence='verified'), ensure_ascii=False))


if __name__ == '__main__':
    unittest.main()
