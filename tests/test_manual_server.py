"""Real scan/checkpoint + HTTP + SQLite integration; model replies are synthetic."""
import copy
import http.client
import json
import threading
import unittest
from contextlib import closing
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from ecra.cli import run
from ecra.common import read_json
from ecra.manual_server import make_server
from ecra.workflow import saved_run, checked_scan, load_config
from ecra.manual_review import catalog


SOURCE = '''int value;
struct State {int a; int b;} state;
void ISR(void) { value++; state.a++; state.b++; }
void Task(void) { value++; state.a++; state.b++; }
void Unrelated(void) { int private_value = 1; (void)private_value; }
'''


class ServerTests(unittest.TestCase):
    from tests.test_ecra import ProjectTest as _fixture
    setUp = _fixture.setUp
    project = _fixture.project

    def scan(self, source=SOURCE):
        self.project({'app.c': source}, review=dict(enabled=False))
        self.assertIn(run(self.root, no_review=True), (0, 1, 2))
        self.out = self.root / '.ecra'
        self.server = make_server(self.root)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop, self.server, self.thread)
        return self.state()

    @staticmethod
    def stop(server, thread):
        server.shutdown()
        server.server_close()
        thread.join(3)

    def http(self, path, body=None, headers=None, method=None):
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=30)
        hdr = dict(Origin='http://' + self.server.authority)
        if body is not None:
            hdr.update({'Content-Type':'application/json', 'X-ECRA-Token':self.server.app.token})
        hdr.update(headers or {})
        data = json.dumps(body).encode() if body is not None else None
        connection.request(method or ('POST' if body is not None else 'GET'), path, data, hdr)
        response = connection.getresponse()
        result = response.read()
        code = response.status
        connection.close()
        try: result = json.loads(result)
        except (ValueError, UnicodeError): pass
        return code, result

    def state(self):
        code, result = self.http('/api/state')
        self.assertEqual(code, 200, result)
        return result

    def submit(self, state, row=None, **changes):
        row = row or state['rows'][0]
        request = dict(row, report_fingerprint=state['report_fingerprint'], decision='CONFIRMED_SAFE',
                       reason='人工核对串行访问，测试数据', reviewer='测试工程师')
        request.update(changes)
        return self.http('/api/decision', request)

    def test_real_scan_confirm_reopen_report_rescan_and_source_invalidation(self):
        state = self.scan()
        self.assertTrue(state['valid'])
        self.assertEqual(len(state['rows']), 3)  # two fields plus value, never container
        original = read_json(self.out / 'reports/global_static_concurrency.json')
        code, confirmed = self.submit(state)
        self.assertEqual(code, 200, confirmed)
        self.assertEqual(confirmed['progress']['percent'], 33.33)
        self.assertEqual(self.submit(state)[0], 409)  # second browser's old revision
        self.assertEqual(read_json(self.out / 'reports/global_static_concurrency.json'), original)
        self.assertEqual(self.state()['rows'][0]['decision'], 'CONFIRMED_SAFE')
        with patch('ecra.review.review_all', side_effect=AssertionError('report must not review')):
            self.assertIn(saved_run(self.root, render_only=True), (1, 2))
        self.assertEqual(self.state()['rows'][0]['decision'], 'CONFIRMED_SAFE')
        # Recreate server, equivalent to restarting the CLI/browser.
        new = make_server(self.root)
        self.addCleanup(new.server_close)
        self.assertEqual(new.app.refresh()[0]['decision'], 'CONFIRMED_SAFE')
        # Fresh scan with identical inputs inherits the decision.
        self.assertIn(run(self.root, no_review=True), (1, 2))
        self.assertEqual(self.state()['rows'][0]['decision'], 'CONFIRMED_SAFE')
        self.assertTrue(list((self.out / 'snapshots').iterdir()))
        self.assertTrue(list((self.out / 'snapshots').glob('*/manual_review/manual_review.sqlite3')))
        # Source changes before scanning: old safe decision immediately invalid.
        (self.root / 'app.c').write_text(SOURCE.replace('value++;', 'value += 2;'), encoding='utf-8')
        stale = self.state()
        self.assertFalse(stale['valid'])
        self.assertEqual(stale['rows'][0]['decision'], 'NEEDS_RECHECK')
        self.assertEqual(self.submit(stale)[0], 409)
        self.assertIn(run(self.root, no_review=True), (1, 2))
        self.assertEqual(self.state()['rows'][0]['decision'], 'NEEDS_RECHECK')
        self.assertTrue(self.http('/api/history')[1]['history'])

    def test_unrelated_function_change_inherits_but_access_change_invalidates(self):
        state = self.scan()
        self.assertEqual(self.submit(state)[0], 200)
        before = self.state()['rows'][0]['evidence_digest']
        (self.root / 'app.c').write_text(SOURCE.replace('private_value = 1', 'private_value = 2'), encoding='utf-8')
        self.assertIn(run(self.root, no_review=True), (1, 2))
        after = self.state()
        self.assertEqual(after['rows'][0]['evidence_digest'], before)
        self.assertEqual(after['rows'][0]['decision'], 'CONFIRMED_SAFE')
        (self.root / 'app.c').write_text(SOURCE.replace('value++;', 'value += 2;'), encoding='utf-8')
        self.assertIn(run(self.root, no_review=True), (1, 2))
        self.assertEqual(self.state()['rows'][0]['decision'], 'NEEDS_RECHECK')

    def test_local_service_host_origin_csrf_traversal_and_validation(self):
        state = self.scan()
        for headers in [{'Host':'evil.test'}, {'Origin':'http://evil.test'}, {'Sec-Fetch-Site':'cross-site'}]:
            with self.subTest(headers=headers):
                self.assertEqual(self.http('/api/state', headers=headers)[0], 403)
        request = dict(state['rows'][0], decision='CONFIRMED_SAFE', reason='人工依据',
                       report_fingerprint=state['report_fingerprint'])
        self.assertEqual(self.http('/api/decision', request, {'X-ECRA-Token':'wrong'})[0], 403)
        self.assertEqual(self.http('/api/decision', request, {'Origin':'null'})[0], 403)
        self.assertEqual(self.http('/api/decision', request, {'Content-Type':'text/plain'})[0], 400)
        for path in ['/../facts.json', '/%2e%2e/secret', '/facts.json', '/manual_review/manual_review.sqlite3', '/api/unknown']:
            self.assertEqual(self.http(path)[0], 404)
        self.assertEqual(self.submit(state, variable_id='foreign')[0], 400)
        self.assertEqual(self.submit(state, evidence_digest='old')[0], 409)
        self.assertEqual(self.submit(state, report_fingerprint='old')[0], 409)
        self.assertEqual(self.submit(state, reason='  ')[0], 400)
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=10)
        connection.request('POST', '/api/decision', headers={'Origin':'http://' + self.server.authority,
            'X-ECRA-Token':self.server.app.token, 'Content-Type':'application/json', 'Content-Length':str(9*1024*1024)})
        self.assertEqual(connection.getresponse().status, 413)
        connection.close()
        self.assertEqual(self.http('/index.html')[0], 200)
        self.assertEqual(self.http('/reports/global_static_concurrency.json')[0], 200)
        self.assertEqual(self.http('/review/queue.json')[0], 200)
        self.assertEqual(self.http('/review/arbitrary.txt')[0], 404)
        self.assertEqual(self.http('/api/history')[1]['history'], [])

    def test_html_is_offline_safe_and_notes_are_data(self):
        state = self.scan()
        text = self.http('/index.html')[1].decode()
        self.assertIn('离线报告仅供查看', text)
        self.assertIn('data-manual-edit=', text)
        self.assertIn('disabled>确认有风险', text)
        self.assertIn('textContent=', text)
        self.assertNotIn('innerHTML=', text[text.index('const manualConfig='):])
        malicious = '<img src=x onerror="globalThis.PWNED=1">'
        code, saved = self.submit(state, reason=malicious)
        self.assertEqual(code, 200)
        self.assertEqual(saved['rows'][0]['reason'], malicious)
        self.assertNotIn(malicious, self.http('/index.html')[1].decode())

    def test_identity_static_scopes_members_and_multiple_findings(self):
        state = self.scan('''static int state;
void F(void){static int state;state++;}
void G(void){static int state;state++;}
void ISR(void){state++;F();G();}
void Task(void){state++;F();G();}
''')
        rows = state['rows']
        self.assertEqual(len(rows), 3)
        self.assertEqual(len({r['variable_id'] for r in rows}), 3)
        self.assertEqual(self.submit(state, rows[1])[0], 200)
        self.assertEqual([r['decision'] for r in self.state()['rows']].count('CONFIRMED_SAFE'), 1)

    def test_real_review_pipeline_preserves_ledger_and_changed_verdict_invalidates(self):
        state = self.scan()

        verdict = ['FALSE_POSITIVE']

        def respond(argv, **kwargs):
            packet = read_json(argv[argv.index('--file') + 1])
            answer = dict(finding_id=packet['finding_id'], status=verdict[0], reason='模拟复核协议测试。',
                summary='已确认静态误报：' + packet.get('variable', {}).get('qualified_name', 'value state.a state.b') + ' 模拟互斥访问条件已核实，仅用于协议测试。',
                evidence=[dict(file='app.c', line=1, claim='测试源码位置。')])
            return CompletedProcess(argv, 0, json.dumps(answer), '')

        with patch('ecra.review.resolve_command', return_value=['synthetic-cli']), patch('ecra.review.execute', side_effect=respond):
            self.assertIn(saved_run(self.root), (1, 2))
            reviewed = self.state()
            self.assertTrue(all(r['state'] == 'DONE' for r in read_json(self.out/'review/queue.json')))
            self.assertEqual(self.submit(reviewed)[0], 200)
            self.assertIn(saved_run(self.root, failed_only=True), (1, 2))
            self.assertEqual(self.state()['rows'][0]['decision'], 'CONFIRMED_SAFE')
            self.assertIn(saved_run(self.root), (1, 2))
            self.assertEqual(self.state()['rows'][0]['decision'], 'CONFIRMED_SAFE')
            verdict[0] = 'REVIEWED_SAFE'
            self.assertIn(saved_run(self.root), (1, 2))
            self.assertEqual(self.state()['rows'][0]['decision'], 'NEEDS_RECHECK')

    def test_scan_lock_suspends_without_permanently_invalidating(self):
        state = self.scan()
        self.assertEqual(self.submit(state)[0], 200)
        lock = self.out / 'scan.lock'
        lock.write_text('running scanner')
        busy = self.state()
        self.assertFalse(busy['valid'])
        self.assertEqual(busy['progress']['counts']['CONFIRMED_SAFE'], 0)
        self.assertEqual(self.submit(state)[0], 409)
        lock.unlink()
        self.assertEqual(self.state()['rows'][0]['decision'], 'CONFIRMED_SAFE')

    def test_database_failure_is_reported_without_false_success(self):
        state = self.scan()
        with closing(self.server.app.ledger.connect()) as db, db:
            db.execute("CREATE TRIGGER fail_write BEFORE INSERT ON current_review BEGIN SELECT RAISE(ABORT,'disk fault'); END")
        code, result = self.submit(state)
        self.assertEqual(code, 503)
        self.assertIn('保存失败', result['error'])
        self.assertEqual(self.http('/api/history')[1]['history'], [])
        self.assertEqual(self.state()['progress']['counts']['CONFIRMED_SAFE'], 0)
        self.assertFalse((self.out/'scan.lock').exists())

    def test_removed_variable_and_failed_scan_preserve_ledger(self):
        state = self.scan()
        self.assertEqual(self.submit(state)[0], 200)
        changed = SOURCE.replace('state.a++;', '').replace('state.b++;', '')
        (self.root / 'app.c').write_text(changed, encoding='utf-8')
        self.assertIn(run(self.root, no_review=True), (1, 2))
        current = self.state()
        self.assertNotIn(state['rows'][0]['variable_id'], {r['variable_id'] for r in current['rows']})
        exported = self.http('/api/export')[1]
        self.assertEqual(len(exported['records']), 1)
        # Aborted scan removes its checkpoint; the audit ledger remains intact.
        with patch('ecra.cli.prepare', side_effect=ValueError('simulated build failure')):
            self.assertNotEqual(run(self.root, no_review=True), 0)
        self.assertFalse(self.state()['valid'])
        self.assertEqual(self.http('/api/export')[1], exported)

    def test_canonical_digest_ignores_fact_collection_order(self):
        self.scan()
        cfg, config = load_config(self.root)
        facts, report, state = checked_scan(self.root, self.out, cfg, config)
        original = catalog(self.root, self.out, cfg, facts, report)
        facts['variables'].reverse()
        facts['calls'].reverse()
        facts['contexts'].reverse()
        for v in facts['variables']:
            v.get('accesses', []).reverse()
        report['findings'].reverse()
        self.assertEqual(catalog(self.root, self.out, cfg, facts, report), original)

    def test_scope_and_priority_changes_invalidate(self):
        state = self.scan()
        self.assertEqual(self.submit(state)[0], 200)
        config = self.root / '.ecra/semantics.yaml'
        cfg = read_json(config)
        cfg['contexts'][0]['priority'] = 7
        config.write_text(json.dumps(cfg), encoding='utf-8')
        invalid = self.state()
        self.assertFalse(invalid['valid'])
        self.assertEqual(invalid['rows'][0]['decision'], 'NEEDS_RECHECK')

    def test_multi_tu_header_static_instances_do_not_share_decisions(self):
        self.project({'state.h': 'static int state; static inline void H(void){state++;}\n',
                      'a.c': '#include "state.h"\nvoid ISR(void){H();}\nvoid Task(void){H();}\n',
                      'b.c': '#include "state.h"\nvoid Other(void){H();}\n'},
                     contexts=[dict(id='isr',kind='ISR',functions=['ISR']),
                               dict(id='task',kind='TASK',functions=['Task']),
                               dict(id='other',kind='ISR',functions=['Other'])])
        self.assertIn(run(self.root, no_review=True), (0, 1, 2))
        server = make_server(self.root)
        self.addCleanup(server.server_close)
        state = server.app.state(server.app.refresh())
        facts = read_json(self.root / '.ecra/facts.json')
        instances = [v for v in facts['variables'] if v['name'] == 'state']
        self.assertEqual(len(instances), 2)
        self.assertEqual(len({v['symbol_id'] for v in instances}), 2)
        self.assertEqual(len({r['variable_id'] for r in state['rows']}), len(state['rows']))


if __name__ == '__main__':
    unittest.main()
