"""Real F030 TU selection while an older evidence request is held in Chrome.

Uses the production archive, server and UI. Network requests may be held or
aborted, never fulfilled with fabricated evidence. Not full U14/U22 or UAT.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ecra.report_package import import_report, sha256
from ecra.scan_store import EvidenceProvider
from ecra.studio.coverage import CoverageService


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('package', 'work', 'evidence'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--engine', type=Path, default=ROOT)
    parser.add_argument('--python', type=Path, default=Path(sys.executable))
    args = parser.parse_args()
    work, output = args.work.resolve(), args.evidence.resolve()
    work.mkdir(parents=True, exist_ok=False); output.mkdir(parents=True, exist_ok=False)
    imported = import_report(args.package.resolve(), work/'data')
    scan = work/'data/scans'/imported['scan_id']
    provider = EvidenceProvider(scan/'scan.db')
    rows = CoverageService(scan/'scan.db').translation_units()['items']
    pair = next((a, b) for a in rows for b in rows
                if a['fields'].get('original_arguments') and b['fields'].get('original_arguments')
                and a['fields']['original_arguments']['id'] != b['fields']['original_arguments']['id'])
    first, second = pair
    nodes = [item['fields']['original_arguments']['id'] for item in pair]
    expected = [provider.node(node) for node in nodes]
    assert all(item['kind'] == 'list' and item['items'] for item in expected)
    original = sha256(scan/'scan.db')
    state = dict(passed=False, scope=__doc__, tests=[], page_errors=[], external_requests=[],
                 engine=str(args.engine.resolve()), actual_python=str(args.python.resolve()),
                 scan_id=scan.name, package_sha256=sha256(args.package),
                 static_sha256=original, controller_sha256=sha256(Path(__file__)),
                 source_files=[item['summary']['source_file'] for item in pair],
                 evidence_nodes=nodes, expected_hashes=[item['hash'] for item in expected])
    def save():
        (output/'acceptance.json').write_text(json.dumps(state, ensure_ascii=False, indent=2)+'\n', 'utf-8')
    save()
    session = work/'session.json'
    with (work/'server.log').open('xb') as log:
        server = subprocess.Popen([str(args.python), '-B', '-X', 'utf8', '-m', 'ecra.studio',
            '--data-root', str(work/'data'), '--no-browser', '--session-file', str(session)],
            cwd=args.engine, env=dict(os.environ, PYTHONIOENCODING='utf-8'),
            stdout=log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        try:
            deadline = time.monotonic()+60
            while True:
                if server.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError('Actual Studio did not start; private log preserved')
                try:
                    info = json.loads(session.read_text('utf-8'))
                    base = 'http://'+info['authority']
                    with urllib.request.urlopen(urllib.request.Request(base+'/api/bootstrap',
                            headers={'X-ECRA-Session': info['token']}), timeout=5):
                        break
                except (OSError, ValueError):
                    time.sleep(.05)
            from playwright.sync_api import sync_playwright, expect
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel='chrome', headless=True)
                context = browser.new_context(viewport=dict(width=1600, height=900))
                context.tracing.start(screenshots=True, snapshots=True, sources=True)
                page = context.new_page(); held = []
                page.on('pageerror', lambda error: state['page_errors'].append(str(error)))
                page.on('request', lambda request: state['external_requests'].append(request.url)
                        if not request.url.startswith(base) else None)
                pattern = base+'/api/scans/'+scan.name+'/nodes/'+str(nodes[0])+'?**'
                def hold(route):
                    held.append(route)
                def choose(item):
                    row = page.locator('.coverage-table tbody tr').filter(has_text=item['summary']['source_file'])
                    expect(row).to_have_count(1)
                    row.get_by_role('button', name='查看完整证据', exact=True).click()
                    expect(page.get_by_text('正在读取覆盖证据…', exact=True)).to_have_count(0)
                def reference(node, hashed):
                    expect(evidence.locator(':scope > .node-content > .reference')).to_have_text(
                        '证据引用 #'+str(node)+' · SHA-256 '+hashed, timeout=15000)
                def shot(name):
                    evidence.scroll_into_view_if_needed()
                    page.screenshot(path=str(output/(name+'.png')), full_page=True)
                try:
                    page.goto(info['url'])
                    expect(page.get_by_role('heading', name='先处理需要核实的变量')).to_be_visible(timeout=30000)
                    page.get_by_role('link', name='覆盖与诊断', exact=True).click()
                    page.get_by_role('tab', name='编译单元', exact=True).click()
                    expect(page.locator('.coverage-table tbody tr')).to_have_count(len(rows))
                    choose(first)
                    current = page.get_by_role('region', name='当前覆盖证据')
                    evidence = current.locator(':scope > details.evidence-node').filter(
                        has=page.locator('summary', has_text='原始真实编译命令'))
                    expect(evidence).to_have_count(1)
                    page.route(pattern, hold)
                    evidence.locator(':scope > summary').click()
                    expect(evidence.get_by_role('status')).to_have_text('正在读取证据…')
                    end = time.monotonic()+15
                    while not held:
                        if time.monotonic() > end: raise TimeoutError('Real first-TU request not observed')
                        page.wait_for_timeout(20)
                    state['tests'].append('real_first_TU_request_held_with_actual_loading_state');save()
                    choose(second)
                    # The same expanded detail-field component receives a new
                    # actual node. Release the older genuine request last.
                    with page.expect_response(lambda response: '/nodes/'+str(nodes[0])+'?' in response.url):
                        for route in held: route.continue_()
                    held.clear(); page.unroute(pattern, hold)
                    expect(evidence.get_by_role('status')).to_have_count(0, timeout=15000)
                    state['observed_reference_after_late_response'] = evidence.locator(
                        ':scope > .node-content > .reference').all_text_contents();save()
                    reference(nodes[1], expected[1]['hash'])
                    visible = evidence.locator(':scope > .node-content > .fact-line > span').all_text_contents()
                    assert visible == [str(item['value']) for item in expected[1]['items']]
                    shot('01-second-TU-keeps-its-real-command-after-old-response')
                    state['tests'].append('new_TU_auto_loads_and_late_old_response_cannot_replace_current_evidence');save()
                    def abort(route): route.abort('connectionfailed')
                    page.route(pattern, abort)
                    choose(first)
                    expect(evidence.get_by_role('alert')).to_contain_text('证据读取失败', timeout=15000)
                    retry = evidence.get_by_role('button', name='重试读取证据', exact=True)
                    expect(retry).to_be_visible();shot('02-real-network-failure-with-evidence-retry')
                    page.unroute(pattern, abort); retry.click()
                    reference(nodes[0], expected[0]['hash'])
                    expect(evidence.get_by_role('alert')).to_have_count(0)
                    shot('03-retry-reads-the-current-TU-from-real-backend')
                    state['tests'].append('actual_network_failure_and_retry_restore_current_TU_node')
                    assert sha256(scan/'scan.db') == original
                    assert not state['page_errors'] and not state['external_requests']
                    assert sha256(Path(__file__)) == state['controller_sha256']
                    state['tests'].append('static_bytes_controller_and_offline_UI_unchanged')
                    state['passed'] = True;save()
                except BaseException:
                    page.screenshot(path=str(output/'failure.png'), full_page=True);raise
                finally:
                    for route in held:
                        try: route.continue_()
                        except Exception: pass
                    context.tracing.stop(path=str(output/'trace.zip'));context.close();browser.close()
        except BaseException as exc:
            state.update(error=str(exc), traceback=traceback.format_exc());save();raise
        finally:
            server.terminate();server.wait(timeout=20)
    print(json.dumps(dict(passed=state['passed'], tests=len(state['tests']))))


if __name__ == '__main__':
    main()
