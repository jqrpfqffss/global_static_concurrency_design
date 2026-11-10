"""Exercise the scan handoff through the Python-served Studio and real workers."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import traceback
import urllib.request

import yaml
from playwright.sync_api import expect, sync_playwright

TOOL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL))
from ecra.report_package import sha256
from ecra.scan_store import EvidenceProvider

TERMINAL = {'COMPLETE', 'FAILED', 'INTERRUPTED'}


def wait_for(read, timeout=240):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = read()
        if value:
            return value
        time.sleep(.2)
    raise AssertionError(f'Timed out after {timeout}s: {read}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True, help='Real firmware, with time for browser actions during preflight')
    parser.add_argument('--quick-config', type=Path, required=True, help='Smaller valid firmware for fault and repeat cases')
    parser.add_argument('--work', type=Path, required=True, help='Fresh directory outside the repository')
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    work, output = args.work.resolve(), args.evidence.resolve()
    work.mkdir(parents=True, exist_ok=False)
    output.mkdir(parents=True, exist_ok=False)
    data, session = work/'data', work/'session.json'
    receipt = dict(passed=False, work=str(work), config=str(args.config.resolve()),
                   quick_config=str(args.quick_config.resolve()), cases={}, posts=[], page_errors=[])

    def save_receipt():
        (output/'acceptance.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), 'utf-8')

    def config(path):
        value = yaml.safe_load(path.read_text('utf-8-sig'))
        value['analysis']['output'] = {'location': 'user'}
        return value

    primary, quick = config(args.config), config(args.quick_config)
    with (output/'server.log').open('wb') as log:
        server = subprocess.Popen([sys.executable, '-B', '-X', 'utf8', '-m', 'ecra.studio',
                                   '--data-root', str(data), '--session-file', str(session), '--no-browser'],
                                  cwd=TOOL, stdout=log, stderr=subprocess.STDOUT)
        try:
            def started():
                if server.poll() is not None:
                    raise RuntimeError('Studio exited, see server.log')
                return session.is_file()

            wait_for(started, 60)
            info = json.loads(session.read_text('utf-8'))
            base = 'http://' + info['authority']

            def get(path):
                request = urllib.request.Request(base + '/api' + path, headers={'X-ECRA-Session': info['token']})
                with urllib.request.urlopen(request, timeout=20) as response:
                    return json.load(response)

            def tasks():
                return get('/tasks')['items']

            def detail(ident):
                return get('/tasks/' + ident)

            def record(task):
                folder = data/'work/tasks'/task['id']
                result = json.loads((folder/'worker-result.json').read_text('utf-8'))
                checked = task.get('preflight', {})
                return dict(id=task['id'], scan_id=task['scan_id'], mode=task['mode'], state=task['state'],
                            published=task['published'], exit_code=task['exit_code'], error=task.get('error'),
                            worker_result=result, preflight_passed=checked.get('passed'),
                            translation_units=checked.get('translation_units'),
                            target=checked.get('target'), variant=checked.get('variant'),
                            stages=[stage['stage'] for stage in task.get('stages', [])],
                            resources=task['resource_policy'], profile_revision=task['profile_revision'],
                            diagnostics=str(folder))

            def completed(ident, state, published):
                def terminal():
                    task = detail(ident)
                    return task if task['state'] in TERMINAL else None
                task = wait_for(terminal, 900)
                assert task['state'] == state and task['published'] == published, record(task)
                return task

            def one_new(before, mode, post_index):
                new = [task for task in tasks() if task['id'] not in before]
                posts = receipt['posts'][post_index:]
                assert len(new) == len(posts) == 1, (new, posts)
                task, spec = new[0], posts[0]
                assert task['mode'] == spec['mode'] == mode, (task, spec)
                assert (task['project_id'], task['profile_id'], task['profile_revision'], task['request_id']) == (
                    spec['project_id'], spec['profile_id'], spec['revision'], spec['request_id'])
                frozen = data/'work/tasks'/task['id']/'semantics.yaml'
                assert sha256(frozen) == spec['revision']
                return task['id']

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel='chrome', headless=True)
                context = browser.new_context(viewport={'width': 1500, 'height': 900})
                context.tracing.start(screenshots=True, snapshots=True, sources=True)

                def open_page():
                    page = context.new_page()
                    page.on('pageerror', lambda error: receipt['page_errors'].append(str(error)))
                    def track(request):
                        if request.url == base + '/api/tasks' and request.method == 'POST':
                            receipt['posts'].append(request.post_data_json)
                    page.on('request', track)
                    page.goto(info['url'])
                    return page

                def button(name):
                    return page.get_by_role('button', name=name, exact=True)

                def navigate(name):
                    page.get_by_role('link', name=name, exact=True).click()

                def import_config(cfg):
                    navigate('工程配置')
                    page.locator('input[type=file]').set_input_files({
                        'name': 'handoff.yaml', 'mimeType': 'text/yaml',
                        'buffer': json.dumps(cfg, ensure_ascii=False).encode('utf-8')})
                    expect(button('开始此配置扫描')).to_be_enabled()

                def wizard():
                    return button('开始此配置扫描')

                def focused(ident):
                    expect(page.locator('.task-detail .identity')).to_contain_text(ident)

                def preflight_running(ident):
                    task = detail(ident)
                    assert task['state'] == 'RUNNING' and task.get('preflight', {}).get('passed') is False, task
                    return task.get('progress', {}).get('stage')

                def capture(name, cases, evidence):
                    page.screenshot(path=str(output/(name+'.png')))
                    for case in cases.split():
                        receipt['cases'][case] = dict(evidence, screenshot=name+'.png')
                    save_receipt()
                    print('PASS ' + cases, flush=True)

                page = open_page()
                try:
                    import_config(primary)
                    assets = page.evaluate("performance.getEntriesByType('resource').map(r => r.name)")
                    html = (TOOL/'ecra/studio/web/index.html').read_text('utf-8')
                    receipt['assets'] = {}
                    for name in re.findall(r'[.]/(assets/index-[^"\']+\.(?:js|css))', html):
                        url = base + '/' + name
                        assert url in assets, (url, assets)
                        with urllib.request.urlopen(url, timeout=20) as response:
                            on_disk = (TOOL/'ecra/studio/web'/name)
                            assert response.read() == on_disk.read_bytes()
                        receipt['assets'][name] = sha256(on_disk)
                    assert len(receipt['assets']) == 2
                    before, start = {task['id'] for task in tasks()}, len(receipt['posts'])
                    wizard().dblclick()
                    expect(page.get_by_role('heading', name='扫描任务中心')).to_be_visible()
                    scan = one_new(before, 'scan', start)
                    assert receipt['posts'][start]['resources'] == {'preset': 'auto'}
                    focused(scan)
                    expect(page.locator('.task-stages')).to_contain_text('预检查：', timeout=15000)
                    assert not button('打开扫描结果').is_visible()
                    page.get_by_label('检索任务日志').fill('预检查')
                    expect(page.locator('.task-log')).to_contain_text('预检查')
                    capture('01-preflight-logs', 'U02', dict(id=scan, stage=preflight_running(scan)))
                    navigate('工程配置')
                    preflight_running(scan)
                    navigate('扫描任务')
                    focused(scan)
                    capture('02-navigate-back', 'U03', dict(id=scan, stage=preflight_running(scan)))
                    page.reload()
                    focused(scan)
                    capture('03-reload', 'U04', dict(id=scan, stage=preflight_running(scan)))
                    failed_reads = []
                    def fail_once(route):
                        if not failed_reads:
                            failed_reads.append(route.request.url)
                            route.abort()
                        else:
                            route.continue_()
                    page.route(re.compile('/api/tasks/'+scan+r'\?offset=0$'), fail_once)
                    warning = page.get_by_text('任务状态暂时无法读取，正在重试；保留上次真实详情。', exact=True)
                    expect(warning).to_be_visible(timeout=8000)
                    focused(scan)
                    expect(page.locator('.task-detail > h3')).to_contain_text('完整扫描 · 执行中')
                    page.screenshot(path=str(output/'04-status-read-warning.png'))
                    expect(warning).to_have_count(0, timeout=8000)
                    assert len(failed_reads) == 1
                    capture('05-status-recovered', 'U06', dict(id=scan, stage=preflight_running(scan),
                            failed_reads=1, warning='04-status-read-warning.png'))

                    stage_at_close = preflight_running(scan)
                    page.close()
                    assert not context.pages and server.poll() is None
                    def progressed():
                        value = detail(scan)
                        assert value['state'] not in {'FAILED', 'INTERRUPTED'}, value.get('error')
                        return value.get('preflight', {}).get('passed') and value['progress_kind'] == 'TU_EXTRACTION' and any(
                            not stage['stage'].startswith('预检查：') for stage in value.get('stages', []))
                    wait_for(progressed, 480)
                    page = open_page()
                    navigate('扫描任务')
                    focused(scan)
                    expect(page.get_by_text('预检查通过，已进入正式扫描。', exact=True)).to_be_visible()
                    capture('06-reopen', 'U05', dict(id=scan, stage_at_close=stage_at_close, native_entered_while_closed=True))
                    task = completed(scan, 'COMPLETE', True)
                    assert task['preflight']['passed'] and task['progress_kind'] == 'TU_EXTRACTION'
                    assert len(task['stages']) > 4 and any(not s['stage'].startswith('预检查：') for s in task['stages'])
                    assert one_new(before, 'scan', start) == scan
                    expect(button('打开扫描结果')).to_be_visible(timeout=15000)
                    database = data/'scans'/scan/'scan.db'
                    EvidenceProvider(database).validate(deep=True)
                    digest = sha256(database)
                    capture('07-scan-published', 'U01 U08', {**record(task), 'task_posts': 1, 'database_sha256': digest})
                    button('打开扫描结果').click()
                    expect(page.get_by_role('heading', name='先处理需要核实的变量')).to_be_visible()

                    import_config(quick)
                    button('检查配置与工具路径').click()
                    button('保存独立配置').click()
                    panel = page.get_by_role('region', name='真实构建预检查')
                    before, start = {task['id'] for task in tasks()}, len(receipt['posts'])
                    status_path = re.compile(r'/api/tasks/[a-f0-9]{32}$')
                    precheck_reads = []
                    def fail_precheck_status(route):
                        if not precheck_reads:
                            precheck_reads.append(route.request.url)
                            route.abort()
                        else:
                            route.continue_()
                    page.route(status_path, fail_precheck_status)
                    failed_plans = []
                    plan_path = re.compile(r'/api/tasks/[a-f0-9]{32}/plan\?offset=0$')
                    def fail_plan(route):
                        failed_plans.append(route.request.url)
                        route.abort()
                    page.route(plan_path, fail_plan)
                    panel.get_by_role('button', name='检查真实构建', exact=True).click()
                    precheck_warning = panel.get_by_text('任务状态暂时无法读取，正在重试。', exact=False)
                    expect(precheck_warning).to_be_visible()
                    expect(panel.get_by_text('真实构建与编译输入检查通过，尚未开始扫描。', exact=True)).to_be_visible(timeout=180000)
                    expect(precheck_warning).to_have_count(0)
                    expect(panel.get_by_text('检查已通过，编译计划暂时无法读取。', exact=False)).to_be_visible()
                    precheck = one_new(before, 'precheck', start)
                    task = completed(precheck, 'COMPLETE', False)
                    assert len(failed_plans) == len(precheck_reads) == 1 and task['preflight']['passed']
                    assert not (data/'scans'/precheck/'diagnostics').exists()
                    capture('08-plan-unavailable', 'U07 U12', {**record(task), 'task_posts': 1, 'failed_plan_reads': 1})
                    page.unroute(plan_path)
                    page.unroute(status_path)
                    button('重试读取编译计划').click()
                    button('查看完整构建计划与逐 TU 参数').click()
                    plan = page.get_by_role('dialog', name='真实构建计划与完整编译参数')
                    expect(plan).to_contain_text(f"全部 {task['preflight']['translation_units']} TU")
                    page.screenshot(path=str(output/'08b-plan-retry-succeeded.png'))
                    receipt['cases']['U07']['successful_retry'] = '08b-plan-retry-succeeded.png'
                    page.keyboard.press('Escape')
                    button('查看检查日志与资源').click()
                    focused(precheck)
                    expect(page.locator('.task-detail > h3')).to_contain_text('仅预检查 · 检查通过，尚未开始扫描')
                    assert one_new(before, 'precheck', start) == precheck

                    # A real POST is accepted by Studio, then its browser response is discarded.
                    before, start = {task['id'] for task in tasks()}, len(receipt['posts'])
                    lost = []
                    def lose_response(route):
                        if route.request.method != 'POST':
                            return route.continue_()
                        response = route.fetch()
                        assert response.ok, response.text()
                        lost.append(response.json()['id'])
                        route.abort()
                    page.route(base+'/api/tasks', lose_response)
                    page.get_by_text('扫描配置与资源预算', exact=False).click()
                    page.get_by_label('资源预设').select_option('manual')
                    page.get_by_label('进程树峰值提交预算（GiB）').fill('5')
                    page.get_by_label('最大 TU 并行数').fill('2')
                    button('检查并扫描').click()
                    expect(button('打开扫描结果')).to_be_visible(timeout=240000)
                    repeated = one_new(before, 'scan', start)
                    assert lost == [repeated]
                    focused(repeated)
                    task = completed(repeated, 'COMPLETE', True)
                    assert task['resource_policy']['peak_bytes'] == 5*1024**3 and task['resource_policy']['workers'] == 2
                    capture('09-response-loss', 'U09 U13', {**record(task), 'task_posts': 1, 'dropped_success_response': True})
                    page.unroute(base+'/api/tasks')
                    existing, post_count = {row['id'] for row in tasks()}, len(receipt['posts'])
                    page.route(base+'/api/tasks', lambda route: route.abort() if route.request.method == 'POST' else route.continue_())
                    button('检查并扫描').click()
                    expect(page.get_by_text('任务提交结果待确认。请先到扫描任务中心核对', exact=False)).to_be_visible()
                    focused(repeated)
                    assert {row['id'] for row in tasks()} == existing and len(receipt['posts']) == post_count + 1
                    page.screenshot(path=str(output/'09b-submission-unconfirmed.png'))
                    receipt['cases']['U09']['unconfirmed_screenshot'] = '09b-submission-unconfirmed.png'
                    page.unroute(base+'/api/tasks')
                    button('打开扫描结果').click()
                    expect(page.get_by_role('heading', name='先处理需要核实的变量')).to_be_visible()
                    assert get('/scans/'+repeated+'/summary')['binding']['scan_id'] == repeated
                    navigate('历史与对比')
                    page.get_by_role('row', name='归档 '+scan, exact=True).get_by_role('button', name='打开结果', exact=True).click()
                    expect(page.get_by_role('heading', name='先处理需要核实的变量')).to_be_visible()
                    assert get('/scans/'+scan+'/summary')['binding']['scan_id'] == scan and sha256(database) == digest
                    capture('10-old-result', 'U14', dict(new_scan_id=repeated, prior_scan_id=scan, prior_database_sha256=digest))

                    broken = json.loads(json.dumps(quick))
                    broken['analysis']['expected_defines'] = ['ECRA_HANDOFF_EXPECTED_DEFINE_MISSING']
                    import_config(broken)
                    before, start = {task['id'] for task in tasks()}, len(receipt['posts'])
                    wizard().click()
                    expect(page.locator('.task-detail > h3')).to_contain_text('完整扫描 · 失败', timeout=120000)
                    bad = one_new(before, 'scan', start)
                    task = completed(bad, 'FAILED', False)
                    expect(page.locator('.task-detail')).to_contain_text('ECRA_HANDOFF_EXPECTED_DEFINE_MISSING')
                    assert not task['preflight']['passed'] and not (data/'scans'/bad/'diagnostics').exists()
                    assert not button('打开扫描结果').is_visible()
                    capture('11-gate-failed', 'U10', record(task))

                    import_config(primary)
                    before, start = {task['id'] for task in tasks()}, len(receipt['posts'])
                    wizard().click()
                    expect(page.locator('.task-stages')).to_contain_text('预检查：', timeout=15000)
                    stopped = one_new(before, 'scan', start)
                    preflight_running(stopped)
                    button('安全停止').click()
                    expect(page.locator('.task-detail > h3')).to_contain_text('已停止', timeout=120000)
                    task = completed(stopped, 'INTERRUPTED', False)
                    assert task['exit_code'] == 130 and not (data/'scans'/stopped/'diagnostics').exists()
                    assert sha256(database) == digest
                    capture('12-stopped', 'U11', record(task))
                    assert set(receipt['cases']) == {f'U{n:02d}' for n in range(1, 15)}
                    assert not receipt['page_errors'], receipt['page_errors']
                    receipt['passed'] = True
                finally:
                    if not receipt['passed'] and not page.is_closed():
                        page.screenshot(path=str(output/'failure.png'))
                    context.tracing.stop(path=str(output/'trace.zip'))
                    browser.close()
        except BaseException:
            receipt['error'] = traceback.format_exc()
            raise
        finally:
            server.terminate()
            server.wait(timeout=30)
            save_receipt()


if __name__ == '__main__':
    main()
