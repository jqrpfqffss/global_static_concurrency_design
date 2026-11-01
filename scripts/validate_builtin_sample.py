"""Real Chrome + local Studio: three first-use entries and a real native-built archive.

No firmware path or toolchain is passed to the viewer. No mock API, native scan,
network model, or physical second-machine/DPI/UAT claim is made by this script.
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

TOOL=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(TOOL))
from ecra.report_package import sha256
import yaml


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['work','evidence']:parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--engine',type=Path,default=TOOL)
    parser.add_argument('--python',type=Path,default=Path(sys.executable))
    args=parser.parse_args()
    work=args.work.resolve();work.mkdir(parents=True,exist_ok=False)
    output=args.evidence.resolve();output.mkdir(parents=True,exist_ok=True)
    receipt=dict(passed=False,tests=[],screenshots=[],page_errors=[],external_requests=[],
        scope=__doc__,engine=str(args.engine.resolve()),server_python=str(args.python.resolve()),
        native_windows_dpi='NOT_VERIFIED',engineer_uat='NOT_VERIFIED',native_scan='NOT_EXERCISED')
    assets=args.engine.resolve()/'ecra/studio/sample_assets'
    before={p.name:(sha256(p),p.stat().st_mtime_ns) for p in assets.iterdir() if p.is_file()}
    metadata=json.loads((assets/'sample.json').read_text('utf-8'))
    log=(work/'server.log').open('w',encoding='utf-8');session=work/'session.json'
    flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
    server=subprocess.Popen([str(args.python),'-B','-X','utf8','-m','ecra.studio','--data-root',str(work/'data'),
        '--no-browser','--session-file',str(session)],cwd=args.engine,env=dict(os.environ,PYTHONIOENCODING='utf-8'),
        stdout=log,stderr=subprocess.STDOUT,creationflags=flags)
    browser=context=playwright=None
    try:
        deadline=time.monotonic()+60
        while not session.exists():
            if server.poll() is not None or time.monotonic()>deadline:raise RuntimeError('Studio failed to start; see server.log')
            time.sleep(.1)
        info=json.loads(session.read_text(encoding='utf-8'));base='http://'+info['authority']
        while True:
            try:
                urllib.request.urlopen(urllib.request.Request(base+'/api/bootstrap',headers={'X-ECRA-Session':info['token']}),timeout=1).close();break
            except OSError:
                if time.monotonic()>deadline:raise
                time.sleep(.1)
        from playwright.sync_api import sync_playwright,expect
        playwright=sync_playwright().start();browser=playwright.chromium.launch(channel='chrome',headless=True)
        context=browser.new_context(viewport=dict(width=1600,height=900),record_video_dir=str(output/'video'))
        context.tracing.start(screenshots=True,snapshots=True,sources=True);page=context.new_page()
        page.on('pageerror',lambda exc:receipt['page_errors'].append(str(exc)))
        page.on('request',lambda request:receipt['external_requests'].append(request.url) if not request.url.startswith(base) else None)
        page.goto(info['url'])
        def button(name):return page.get_by_role('button',name=name,exact=True)
        def field(name):return page.get_by_label(name,exact=True)
        def passed(name):receipt['tests'].append(dict(name=name,status='PASS',related=['U01','U09','U16','U19','H5']))
        def shot(name):
            expect(page.locator('.activity')).to_have_count(0)
            path=output/(name+'.png');page.screenshot(path=str(path),full_page=True);receipt['screenshots'].append(str(path))
        for width,height in [(1366,768),(1600,900)]:
            page.set_viewport_size(dict(width=width,height=height))
            for name in ['新建工程','导入历史结果','打开示例']:
                expect(button(name)).to_be_visible();bounds=button(name).bounding_box()
                assert bounds and bounds['y']>=0 and bounds['y']+bounds['height']<=height
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth');shot('01-first-use-'+str(width))
        button('新建工程').click();expect(field('工程名称')).to_have_value('')
        page.get_by_role('link',name='项目概览',exact=True).click();button('导入历史结果').click()
        expect(field('选择 .ecra-report')).to_be_visible();page.get_by_role('link',name='项目概览',exact=True).click()
        passed('three_first_use_entries_have_real_routes_and_visible_actions')
        with page.expect_response(lambda r:'/api/sample/open' in r.url) as pending:button('打开示例').click()
        opened=pending.value.json();assert opened['scan_id']==metadata['scan_id']
        expect(page.get_by_role('note').filter(has_text='教学示例')).to_be_visible()
        expect(page.get_by_role('heading',name='先处理需要核实的变量',exact=True)).to_be_visible()
        from ecra.scan_store import EvidenceProvider
        from ecra.human_reviews import ReviewStore
        from ecra.report_package import import_report
        out=work/'data/scans'/opened['scan_id'];provider=EvidenceProvider(out/'scan.db');binding=provider.validate(deep=True)
        assert binding['facts_hash']==metadata['facts_hash'] and binding['report_hash']==metadata['report_hash']
        assert binding['profile_id']=='builtin-stm32-demo'
        static_sha=sha256(out/'scan.db');shot('02-real-sample-overview')
        passed('sample_opens_actual_native_archive_with_explicit_teaching_identity')
        for destination in ['工程配置','扫描任务']:
            page.get_by_role('link',name=destination,exact=True).click()
            expect(page.get_by_role('note').filter(has_text='教学示例')).to_have_count(0)
        page.get_by_role('link',name='项目概览',exact=True).click()
        expect(page.get_by_role('note').filter(has_text='教学示例')).to_be_visible()
        passed('teaching_label_does_not_misidentify_project_configuration_or_real_task_pages')
        counts=provider.counts();unknown=counts.get('UNKNOWN',0)
        button('无法判断 '+str(unknown)).click();expect(page.get_by_text('匹配 '+str(unknown)+' 项',exact=False)).to_be_visible()
        page.get_by_role('link',name='项目概览',exact=True).click()
        page.locator('.cards button').last.click()
        field('查找变量、文件或规范身份').fill('g_counter');button('搜索').click()
        expect(page.locator('.symbol')).to_have_count(1);page.locator('.symbol').click()
        symbol=provider.symbols(search='g_counter',limit=1)['items'][0]['symbol_id']
        expect(page.locator('.detail-heading h2')).to_have_text('g_counter')
        passed('real_unknown_card_drills_to_same_count_and_actual_canonical_variable')
        page.get_by_role('tab',name='归档源码',exact=True).click()
        expect(page.locator('.source-code')).to_contain_text('g_counter')
        assert sha256(out/'scan.db')==static_sha;shot('03-archived-demo-code')
        passed('archived_real_source_is_available_without_a_firmware_parameter')
        field('确认者').fill('示例验收');field('依据 / 修改或撤销理由').fill('教学确认，仅用于验证示例工作流')
        button('确认有风险').click();expect(page.get_by_role('status').filter(has_text='已保存')).to_be_visible()
        fingerprint=provider.fingerprint(symbol);reviews=ReviewStore(out/'reviews.db',binding)
        event=reviews.history(symbol)[0];assert reviews.current(symbol,fingerprint)['decision']=='CONFIRMED_RISK'
        page.reload();expect(page.get_by_role('note').filter(has_text='教学示例')).to_be_visible()
        page.get_by_role('link',name='项目概览',exact=True).click();button('继续人工确认').click()
        field('人工状态').select_option('');field('查找变量、文件或规范身份').fill('g_counter');button('搜索').click()
        expect(page.locator('.symbol')).to_have_count(1);page.locator('.symbol').click()
        page.get_by_role('tab',name='人工历史',exact=True).click();expect(page.get_by_text('示例验收',exact=False)).to_be_visible()
        passed('human_confirmation_and_teaching_label_survive_browser_reload')
        page.get_by_role('link',name='项目概览',exact=True).click()
        expect(button('打开示例')).to_be_visible()
        with page.expect_response(lambda r:'/api/sample/open' in r.url) as pending:button('打开示例').click()
        repeated=pending.value.json();assert repeated['repeated'] is True
        expect(page.get_by_role('note').filter(has_text='教学示例')).to_be_visible()
        assert [row['event_id'] for row in reviews.history(symbol)]==[event['event_id']]
        assert reviews.current(symbol,fingerprint)['decision']=='CONFIRMED_RISK' and sha256(out/'scan.db')==static_sha
        passed('reopening_existing_sample_is_idempotent_and_preserves_confirmation')
        page.get_by_role('link',name='数据与共享',exact=True).click()
        with page.expect_download() as pending:button('导出标准完整包').click()
        package=output/'confirmed-demo.ecra-report';pending.value.save_as(package)
        imported=import_report(package,work/'transferred-data')
        transferred=work/'transferred-data/scans'/imported['scan_id'];other=EvidenceProvider(transferred/'scan.db')
        assert other.roots()==provider.roots()
        assert ReviewStore(transferred/'reviews.db',other.metadata()).current(symbol,other.fingerprint(symbol))['decision']=='CONFIRMED_RISK'
        passed('standard_export_retains_complete_real_graph_and_human_event')
        # Stop the real service and reopen the same data root on a new port.
        # This crosses a process boundary, beyond a browser reload.
        page.close();old_pid=server.pid;server.terminate();server.wait(timeout=30);session.unlink()
        server=subprocess.Popen([str(args.python),'-B','-X','utf8','-m','ecra.studio','--data-root',str(work/'data'),
            '--no-browser','--session-file',str(session)],cwd=args.engine,env=dict(os.environ,PYTHONIOENCODING='utf-8'),
            stdout=log,stderr=subprocess.STDOUT,creationflags=flags)
        deadline=time.monotonic()+60
        while not session.exists():
            if server.poll() is not None or time.monotonic()>deadline:raise RuntimeError('Studio restart failed')
            time.sleep(.1)
        info=json.loads(session.read_text('utf-8'));base='http://'+info['authority']
        while True:
            try:
                urllib.request.urlopen(urllib.request.Request(base+'/api/bootstrap',headers={'X-ECRA-Session':info['token']}),timeout=1).close();break
            except OSError:
                if time.monotonic()>deadline:raise
                time.sleep(.1)
        page=context.new_page();page.on('pageerror',lambda exc:receipt['page_errors'].append(str(exc)))
        page.on('request',lambda request:receipt['external_requests'].append(request.url) if not request.url.startswith(base) else None)
        page.goto(info['url']);expect(page.get_by_role('note').filter(has_text='教学示例')).to_be_visible()
        page.get_by_role('link',name='人工确认',exact=True).click();field('人工状态').select_option('')
        field('查找变量、文件或规范身份').fill('g_counter');button('搜索').click()
        expect(page.locator('.symbol')).to_have_count(1);page.locator('.symbol').click()
        page.get_by_role('tab',name='人工历史',exact=True).click();expect(page.get_by_text('示例验收',exact=False)).to_be_visible()
        assert sha256(out/'scan.db')==static_sha;shot('04-real-service-reopened-confirmation')
        receipt.update(service_restarted=True,service_process_ids=[old_pid,server.pid])
        passed('actual_service_restart_keeps_sample_identity_and_committed_confirmation')
        receipt['workbench_action_bounds']=[]
        for width,height in [(1366,768),(1600,900)]:
            page.set_viewport_size(dict(width=width,height=height));page.evaluate('scrollTo(0,0)')
            for name in ['确认有风险','确认无风险','暂无法确认','撤销上次确认']:
                bounds=button(name).bounding_box();receipt['workbench_action_bounds'].append(dict(width=width,height=height,action=name,bounds=bounds))
                assert bounds and 0<=bounds['y'] and bounds['y']+bounds['height']<=height,'Review action below first viewport: '+str(receipt['workbench_action_bounds'][-1])
            expect(page.locator('.symbol').first).to_be_in_viewport(ratio=1)
            for tab in ['时序与访问','调用与保护','归档源码','人工历史']:expect(page.get_by_role('tab',name=tab,exact=True)).to_be_in_viewport(ratio=1)
            expect(field('依据 / 修改或撤销理由')).to_be_in_viewport(ratio=1)
            bounds=field('查找变量、文件或规范身份').bounding_box()
            assert bounds and bounds['y']>=0 and bounds['y']+bounds['height']<=height
            shot('05-workbench-actions-'+str(width))
        passed('review_search_and_all_decision_actions_fit_first_viewport_with_sample_banner')
        assert before=={p.name:(sha256(p),p.stat().st_mtime_ns) for p in assets.iterdir() if p.is_file()}
        assert not list((work/'data/work/tasks').glob('*/task.json'))
        receipt.update(scan_id=opened['scan_id'],facts_hash=binding['facts_hash'],report_hash=binding['report_hash'],static_database_unchanged=True,
                       program_assets_unchanged=True,native_tasks_created=0,human_event=event['event_id'],exported_package_sha256=sha256(package))
        assert not receipt['page_errors'] and not receipt['external_requests']
        receipt['passed']=True
    except BaseException:
        receipt['error']=traceback.format_exc()
        if context:
            try:context.pages[0].screenshot(path=str(output/'failure.png'),full_page=True)
            except Exception:pass
        raise
    finally:
        if context:
            context.tracing.stop(path=str(output/'trace.zip'));context.close()
        if browser:browser.close()
        if playwright:playwright.stop()
        server.terminate();server.wait(timeout=30);log.close()
        (output/'acceptance.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(dict(passed=receipt['passed'],tests=len(receipt['tests']),evidence=str(output)),ensure_ascii=False))


if __name__=='__main__':main()
