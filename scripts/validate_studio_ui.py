"""Real Chromium operations + authoritative SQLite assertions, no mocked API.

This is a bounded preview acceptance script, not full U01–U24 certification.
Browser density emulation is explicitly not native Windows DPI testing.
"""
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
import zipfile

TOOL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL))
from ecra.scan_store import EvidenceProvider
from ecra.human_reviews import ReviewStore


def main():
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):
            stream.reconfigure(encoding='utf-8',errors='replace')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--firmware', type=Path)
    parser.add_argument('--compile-database', type=Path)
    parser.add_argument('--native-scan', action='store_true', help='通过真实任务按钮停止并恢复扫描；需固件与真实数据库')
    parser.add_argument('--ai-failure', action='store_true', help='注入缺失复核工具的真实故障；不调用网络模型')
    parser.add_argument('--allow-external-toolchain',action='store_true',help='明确允许已冻结编译数据库中的外部黄金工具链；不改写编译器路径')
    parser.add_argument('--engine', type=Path, default=TOOL)
    parser.add_argument('--python', type=Path, default=Path(sys.executable))
    args = parser.parse_args()
    work = args.work.resolve(); work.mkdir(parents=True,exist_ok=False)
    output = args.evidence.resolve(); output.mkdir(parents=True,exist_ok=True)
    receipt = dict(passed=False, tests=[], screenshots=[], page_errors=[], external_requests=[],
        scope='Real Chromium preview archive/profile/decision workflows on one host; not full U01–U24',
        native_windows_dpi='NOT_VERIFIED', independent_engineer_uat='NOT_VERIFIED',
        native_scan_pipeline='NOT_EXERCISED', physical_second_computer='NOT_VERIFIED')
    session_file = work/'session.json'
    environment = dict(os.environ, PYTHONIOENCODING='utf-8')
    log = (work/'server.log').open('w',encoding='utf-8')
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    server = subprocess.Popen([str(args.python),'-B','-m','ecra.studio','--data-root',str(work/'data'),
        '--no-browser','--session-file',str(session_file)], cwd=args.engine, env=environment,
        stdout=log,stderr=subprocess.STDOUT,creationflags=flags)
    context = browser = playwright = None
    try:
        deadline = time.monotonic()+40
        while not session_file.exists():
            if server.poll() is not None or time.monotonic()>deadline:
                raise RuntimeError('Studio server did not start; see '+str(work/'server.log'))
            time.sleep(.1)
        info = json.loads(session_file.read_text(encoding='utf-8'))
        base = 'http://'+info['authority']
        while True:
            try:
                urllib.request.urlopen(urllib.request.Request(base+'/api/bootstrap',headers={'X-ECRA-Session':info['token']}),timeout=1).close()
                break
            except OSError:
                if time.monotonic()>deadline:
                    raise
                time.sleep(.1)
        from playwright.sync_api import sync_playwright, expect
        playwright = sync_playwright().start()
        if True:
            browser = playwright.chromium.launch(channel='chrome',headless=True)
            context = browser.new_context(viewport=dict(width=1600,height=900),record_video_dir=str(output/'video'))
            context.tracing.start(screenshots=True,snapshots=True,sources=True)
            page = context.new_page()
            page.on('pageerror', lambda error: receipt['page_errors'].append(str(error)))
            page.on('request', lambda request: receipt['external_requests'].append(request.url) if not request.url.startswith(base) else None)
            page.goto(info['url'])
            expect(page.get_by_role('heading',name='开始使用 ECRA Studio')).to_be_visible()
            expect(page.get_by_role('button',name='添加工程',exact=True)).to_be_visible()
            receipt['tests'].append(dict(name='preview_empty_next_step',status='PASS',related=['U01'],limitation='No sample or native scan entry; U01 remains incomplete'))
            page.get_by_role('link',name='数据与共享',exact=True).click()
            page.get_by_label('选择 .ecra-report',exact=True).set_input_files(str(args.package.resolve()))
            expect(page.get_by_role('status').filter(has_text='导入已提交')).to_be_visible(timeout=60000)
            provider = EvidenceProvider(work/'data/scans/golden-f030/scan.db')
            provider.validate(deep=True)
            reviews = ReviewStore(work/'data/scans/golden-f030/reviews.db',provider.metadata())
            assert len(reviews.history()) == 0, 'Golden package must have no test human decisions'
            receipt['tests'].append(dict(name='preview_package_ui_import',status='PASS',related=['U19','U24'],limitation='Same host, no clean-machine claim'))
            def shot(name):
                expect(page.locator('.activity')).to_have_count(0)
                expect(page.get_by_text('正在加载…',exact=True)).to_have_count(0)
                path = output/(name+'.png'); page.screenshot(path=str(path),full_page=True)
                receipt['screenshots'].append(str(path))
            shot('06-import-validated')
            page.get_by_role('link',name='项目概览',exact=True).click()
            expected_unknown = provider.counts()['UNKNOWN']
            page.get_by_role('button',name=f'无法判断 {expected_unknown}',exact=True).click()
            expect(page.get_by_text(re.compile(rf'^匹配 {expected_unknown} 项'))).to_be_visible()
            receipt['tests'].append(dict(name='preview_static_card_matches_sql_filter',status='PASS',related=['U09']))
            page.get_by_label('查找变量、文件或规范身份',exact=True).fill('HCLK')
            page.get_by_role('button',name='搜索',exact=True).click()
            expect(page.locator('.symbol')).to_have_count(1)
            page.locator('.symbol').click()
            expect(page.locator('.detail-heading h2')).to_have_text('HCLK')
            symbol = provider.symbols(search='HCLK')['items'][0]['symbol_id']
            fingerprint = provider.fingerprint(symbol)
            expect(page.locator('.finding-reason').first).to_contain_text('物理执行上下文')
            page.get_by_role('tab',name='调用与保护',exact=True).click()
            expect(page.get_by_role('heading',name='从真实访问函数展开调用关系',exact=True)).to_be_visible()
            page.locator('.call-function').first.click()
            access=provider.records('accesses',symbol_id=symbol,limit=1)['items'][0]
            upstream=provider.records('calls',target_id=access['function_id'])['total']
            expect(page.locator('.call-children').first).to_contain_text('调用此函数的边：'+str(upstream)+' 条')
            page.get_by_label('调用查询方向',exact=True).select_option('downstream')
            page.locator('.call-function').first.click()
            downstream=provider.records('calls',source_id=access['function_id'])['total']
            expect(page.locator('.call-children').first).to_contain_text('此函数调用的边：'+str(downstream)+' 条')
            receipt['tests'].append(dict(name='real_call_tree_queries_both_directions_without_edge_loss',status='PASS',related=['U12'],limitation='Real F030 call sites; not TMFC/INAV large graph acceptance'))
            page.locator('.compound-filters summary').click()
            for field,value in [('定义文件包含','main.c'),('访问函数身份包含',access['function_id'])]:
                control=page.get_by_label(field,exact=True);control.fill(value)
                with page.expect_response(lambda r:'/symbols?' in r.url):control.press('Tab')
                expect(page.locator('.symbol')).to_have_count(1)
            page.get_by_label('AI 复核状态',exact=True).select_option('PENDING')
            expect(page.locator('.symbol')).to_have_count(1)
            divider=page.get_by_role('separator',name='调整列表与证据宽度',exact=True)
            initial=int(divider.get_attribute('aria-valuenow'));divider.focus();page.keyboard.press('ArrowRight')
            expect(divider).to_have_attribute('aria-valuenow',str(initial+1));page.keyboard.press('ArrowLeft')
            receipt['tests'].append(dict(name='real_combined_filter_and_keyboard_splitter',status='PASS',related=['U10','U22'],limitation='Real archive filtering; >20,000-row browser capacity remains separate'))
            page.get_by_label('确认者',exact=True).fill('浏览器验收声明工程师')
            expect(page.get_by_role('button',name='确认无风险',exact=True)).to_be_disabled()
            page.get_by_label('依据 / 修改或撤销理由',exact=True).fill('自动化操作验证；不是硬件风险判定。归档引用 #'+str(provider.symbols(search='HCLK')['items'][0]['node']))
            with page.expect_response(lambda r: r.request.method=='POST' and r.url.endswith('/human')) as response:
                page.get_by_role('button',name='确认有风险',exact=True).click()
            assert response.value.status == 200
            expect(page.locator('.conclusion')).to_contain_text('人工确认有风险')
            assert reviews.current(symbol,fingerprint)['decision']=='CONFIRMED_RISK'
            assert provider.counts()['UNKNOWN']==expected_unknown
            page.get_by_role('tab',name='归档源码',exact=True).click()
            expect(page.locator('.source-code')).to_contain_text('HCLK')
            expect(page.locator('.source-code .highlight .source-line')).to_contain_text('22')
            page.get_by_label('定位源码行',exact=True).fill('163')
            page.get_by_role('button',name='跳转行',exact=True).click()
            expect(page.locator('.source-code .highlight')).to_contain_text('HCLK = SYSCLK;')
            expect(page.get_by_role('link',name='在本机 VS Code 打开',exact=True)).to_have_count(0)
            receipt['tests'].append(dict(name='preview_archived_source_text',status='PASS',related=['U11','U19'],limitation='Archive protocol check on one host, not physical second-machine UAT'))
            shot('07-archived-source')
            page.reload(); expect(page.get_by_role('heading',name='变量与风险',exact=True)).to_be_visible()
            page.get_by_role('link',name='人工确认',exact=True).click()
            page.get_by_role('button',name='继续上次位置',exact=True).click()
            expect(page.locator('.conclusion')).to_contain_text('人工确认有风险')
            receipt['tests'].append(dict(name='preview_decision_commit_reopen_and_position',status='PASS',related=['U16'],limitation='One browser item; 1000-event persistence separately unit-tested'))
            page.get_by_label('依据 / 修改或撤销理由',exact=True).fill('误确认撤销，保留原事件')
            with page.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/human')) as response:
                page.get_by_role('button',name='撤销上次确认',exact=True).click()
            assert response.value.status==200
            expect(page.locator('.conclusion')).to_contain_text('待确认')
            assert len(reviews.history(symbol))==2
            receipt['tests'].append(dict(name='preview_undo_preserves_history',status='PASS',related=['U17']))
            page.get_by_role('tab',name='人工历史',exact=True).click()
            shot('05-human-history')
            # Malformed import is exercised via the real file input and API.
            malicious = work/'invalid.ecra-report'
            with zipfile.ZipFile(malicious,'w') as zipped:
                zipped.writestr('../escape.txt','must not be extracted')
            page.get_by_role('link',name='数据与共享',exact=True).click()
            page.get_by_label('选择 .ecra-report',exact=True).set_input_files(str(malicious))
            expect(page.get_by_role('alert')).to_contain_text('不允许的路径')
            assert len(reviews.history(symbol))==2 and not (work/'escape.txt').exists()
            receipt['tests'].append(dict(name='preview_malicious_package_preserves_prior_scan',status='PASS',related=['U24']))
            # UI cleanup runs against a real, explicitly unreferenced CAS object.
            # This small lifecycle test is separate from the 50-GiB disk test.
            import hashlib
            from ecra.report_package import sha256
            evidence=work/'data/scans/golden-f030/evidence';evidence.mkdir(exist_ok=True)
            unused=evidence/hashlib.sha256(b'UI cleanup unused object').hexdigest();unused.write_bytes(b'UI cleanup unused object')
            before=sha256(provider.path);history=reviews.history()
            cleanup=page.get_by_role('region',name='安全空间整理',exact=True)
            cleanup.get_by_role('button',name='生成回收预览',exact=True).click()
            expect(cleanup.get_by_role('heading',name='预览完成，尚未移动文件',exact=True)).to_be_visible(timeout=60000)
            assert unused.is_file()
            expect(cleanup.get_by_role('button',name='确认隔离暂存',exact=True)).to_be_disabled()
            cleanup.locator('input[type=checkbox]').check();cleanup.get_by_role('button',name='确认隔离暂存',exact=True).click()
            expect(cleanup.get_by_role('heading',name='已隔离，可以恢复或永久释放',exact=True)).to_be_visible(timeout=60000)
            assert not unused.exists()
            cleanup.get_by_role('button',name='恢复原路径',exact=True).click()
            expect(cleanup.get_by_role('heading',name='已恢复',exact=True)).to_be_visible(timeout=60000)
            assert unused.is_file()
            cleanup.get_by_role('button',name='生成回收预览',exact=True).click()
            expect(cleanup.get_by_role('heading',name='预览完成，尚未移动文件',exact=True)).to_be_visible(timeout=60000)
            cleanup.locator('input[type=checkbox]').check();cleanup.get_by_role('button',name='确认隔离暂存',exact=True).click()
            expect(cleanup.get_by_role('heading',name='已隔离，可以恢复或永久释放',exact=True)).to_be_visible(timeout=60000)
            expect(cleanup.get_by_role('button',name='确认永久释放',exact=True)).to_be_disabled()
            cleanup.locator('input[type=checkbox]').check();cleanup.get_by_role('button',name='确认永久释放',exact=True).click()
            expect(cleanup.get_by_role('heading',name='释放结束',exact=True)).to_be_visible(timeout=60000)
            assert not unused.exists() and sha256(provider.path)==before and reviews.history()==history
            provider.validate(deep=True);shot('09-cleanup-recovered-and-purged')
            receipt['tests'].append(dict(name='real_cleanup_preview_restore_second_confirmation_purge',status='PASS',related=['U23'],limitation='Small UI lifecycle; 50-GiB physical-free receipt separate'))
            if args.firmware and args.compile_database:
                page.get_by_role('link',name='工程配置',exact=True).click()
                page.get_by_label('工程名称',exact=True).fill('公开 STM32F030 配置验收')
                page.get_by_label('固件目录（绝对路径）',exact=True).fill(str(args.firmware.resolve()))
                page.get_by_role('button',name='下一步',exact=True).click()
                page.get_by_label('真实构建方式',exact=True).select_option('database')
                page.get_by_label('编译数据库路径',exact=True).fill(str(args.compile_database.resolve()))
                page.get_by_role('button',name='上一步',exact=True).click()
                expect(page.get_by_label('工程名称',exact=True)).to_have_value('公开 STM32F030 配置验收')
                page.get_by_role('button',name='下一步',exact=True).click()
                page.get_by_role('button',name='下一步',exact=True).click()
                page.get_by_role('button',name='下一步',exact=True).click()
                if args.allow_external_toolchain:
                    editor=page.get_by_label('高级完整 YAML',exact=True)
                    editor.fill(editor.input_value().replace('analysis:\n','analysis:\n  allow_external_toolchain: true\n',1))
                    receipt['toolchain_scope']='Explicitly authorized external frozen golden compiler; packaged toolchain separately tested by validate_portable.py'
                if args.ai_failure:
                    editor=page.get_by_label('高级完整 YAML',exact=True)
                    raw=editor.input_value()
                    editor.fill(raw.replace('review:\n  enabled: false','review:\n  enabled: false\n  command: [ecra-acceptance-missing-tool]'))
                page.get_by_role('button',name='检查配置与工具路径',exact=True).click()
                expect(page.get_by_role('button',name='保存独立配置',exact=True)).to_be_enabled()
                page.get_by_role('button',name='保存独立配置',exact=True).click()
                expect(page.get_by_role('status').filter(has_text='配置已保存')).to_be_visible()
                assert len(list((work/'data/projects').glob('*/profiles/*.yaml')))==1
                receipt['tests'].append(dict(name='preview_four_step_profile_save_retains_input',status='PASS',related=['U02'],limitation='Path/configuration check only; native build and scan NOT_IMPLEMENTED'))
                shot('02-project-wizard')
                if args.native_scan:
                    from ecra.report_package import sha256
                    source_before={str(path.relative_to(args.firmware)):sha256(path) for path in args.firmware.rglob('*') if path.is_file()}
                    page.get_by_role('link',name='扫描任务',exact=True).click()
                    page.get_by_role('button',name='开始扫描',exact=True).click()
                    stop=page.get_by_role('button',name='安全停止',exact=True)
                    expect(stop).to_be_enabled(timeout=20000)
                    stop.click()
                    expect(page.get_by_role('heading',name='已停止 / 上次中断',exact=True)).to_be_visible(timeout=120000)
                    shot('04-scan-stopped')
                    page.get_by_role('button',name='从已验证 TU 恢复 / 重试',exact=True).click()
                    expect(page.get_by_role('button',name='打开扫描结果',exact=True)).to_be_visible(timeout=180000)
                    for width,height in ((1366,768),(1600,900)):
                        page.set_viewport_size(dict(width=width,height=height));page.evaluate('scrollTo(0,0)')
                        bounds=page.get_by_role('button',name='打开扫描结果',exact=True).bounding_box()
                        assert bounds and bounds['y']>=0 and bounds['y']+bounds['height']<=height,'scan action outside first viewport'
                    page.set_viewport_size(dict(width=1600,height=900))
                    shot('04-scan-published')
                    tasks=[json.loads(path.read_text(encoding='utf-8')) for path in (work/'data/work/tasks').glob('*/task.json')]
                    completed=next(item for item in tasks if item['state']=='COMPLETE')
                    assert any(item['state']=='INTERRUPTED' for item in tasks)
                    assert completed['resources']['available'] and completed['resources']['peak_job_commit_bytes']>0
                    native=work/'data/scans'/completed['scan_id']
                    EvidenceProvider(native/'scan.db').validate(deep=True)
                    for name in ['facts.json','facts.db','index.html','reports','inventory']:
                        assert not (native/name).exists(),name+' must not be generated by a formal scan'
                    assert source_before=={str(path.relative_to(args.firmware)):sha256(path) for path in args.firmware.rglob('*') if path.is_file()}
                    receipt['native_scan_pipeline']='REAL_SCAN_STOP_RECOVER_PASS'
                    receipt['native_task']=completed
                    receipt['tests'].append(dict(name='native_scan_safe_stop_recovery_and_publication',status='PASS',related=['U03','U06','U08'],
                        limitation='Real 4-TU input; no large-resource or complete fault-matrix claim'))
                    page.get_by_role('button',name='打开扫描结果',exact=True).click()
                    expect(page.get_by_role('heading',name='先处理需要核实的变量',exact=True)).to_be_visible()
                    if args.ai_failure:
                        static_hash=sha256(native/'scan.db')
                        page.get_by_role('link',name='OpenCode 复核',exact=True).click()
                        page.get_by_role('button',name='复核全部疑似与未知',exact=True).click()
                        expect(page.get_by_role('heading',name='扫描任务中心',exact=True)).to_be_visible(timeout=20000)
                        expect(page.get_by_role('heading',name='复核执行已结束',exact=True)).to_be_visible(timeout=120000)
                        expect(page.get_by_role('button',name='打开扫描结果',exact=True)).to_be_visible(timeout=120000)
                        page.get_by_role('link',name='OpenCode 复核',exact=True).click()
                        expect(page.get_by_text(re.compile(r'^技术失败：\d+$'))).to_be_visible(timeout=20000)
                        expect(page.get_by_role('button',name='仅重试技术失败',exact=True)).to_be_enabled()
                        from ecra.scan_persistence import ai_page
                        ai=ai_page(native)
                        assert ai['states'].get('TECH_FAILED')==ai['total'] and ai['total']>0
                        assert sha256(native/'scan.db')==static_hash
                        shot('08-opencode-technical-failure')
                        receipt['tests'].append(dict(name='real_missing_review_tool_failure_keeps_static_database',status='PASS',related=['U15'],
                            limitation='Missing-command fault, no network model invocation or verdict accuracy claim'))
            # Four frozen core pages, plus human/import screenshots. Native
            # scan task page must truthfully show its gate, not mock progress.
            for route,name in [('项目概览','01-overview'),('扫描任务','04-scan-task-gate'),('变量与风险','03-evidence-workbench')]:
                page.get_by_role('link',name=route,exact=True).click()
                if route=='变量与风险':
                    page.locator('.symbol').first.click()
                    expect(page.locator('.detail-heading h2')).to_be_visible()
                    page.get_by_role('tab',name='时序与访问',exact=True).click()
                shot(name)
            page.keyboard.press('Control+f')
            expect(page.get_by_label('查找变量、文件或规范身份',exact=True)).to_be_focused()
            for width,height in [(1366,768),(1600,900),(1920,1080)]:
                page.set_viewport_size(dict(width=width,height=height))
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'unexpected horizontal scrolling'
                expect(page.get_by_label('查找变量、文件或规范身份',exact=True)).to_be_visible()
                shot(f'layout-{width}x{height}')
            devtools=context.new_cdp_session(page)
            for density in (1.25,1.5,2):
                devtools.send('Emulation.setDeviceMetricsOverride',dict(width=1366,height=768,deviceScaleFactor=density,mobile=False))
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                expect(page.get_by_label('查找变量、文件或规范身份',exact=True)).to_be_visible()
                shot('browser-density-'+str(density))
            devtools.send('Emulation.clearDeviceMetricsOverride')
            receipt['tests'].append(dict(name='preview_three_viewports_and_ctrl_f',status='PASS',related=['U22'],limitation='Native Windows 125/150/200% DPI and full keyboard matrix NOT_VERIFIED'))
            assert not receipt['page_errors'], receipt['page_errors']
            assert not receipt['external_requests'], receipt['external_requests']
            receipt['passed']=True
            context.tracing.stop(path=str(output/'trace.zip'))
            context.close(); context=None; browser.close(); browser=None
    except BaseException as exc:
        receipt['error']=str(exc); receipt['traceback']=traceback.format_exc()
        if context:
            try:
                if context.pages:
                    context.pages[0].screenshot(path=str(output/'failure.png'),full_page=True)
                context.tracing.stop(path=str(output/'failure-trace.zip'))
            except Exception:
                pass
        raise
    finally:
        if context:
            context.close()
        if browser:
            browser.close()
        if playwright:
            playwright.stop()
        server.terminate()
        server.wait(timeout=20)
        log.close()
        (output/'acceptance.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(passed=receipt['passed'],tests=len(receipt['tests']),evidence=str(output)),ensure_ascii=False))


if __name__=='__main__':
    main()
