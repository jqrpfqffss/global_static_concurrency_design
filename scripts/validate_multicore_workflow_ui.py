"""Actual GUI selection/upload/owned merge using two approved F030 aliases.

Inputs are separately scanned from the same approved single-core firmware.
This verifies the user workflow, not an independent dual-core G2 project.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
import urllib.parse
import urllib.request

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ecra.report_package import sha256,import_report
from ecra.scan_store import EvidenceProvider
from ecra.human_reviews import ReviewStore


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['case','work','evidence']:parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--engine',type=Path,default=ROOT)
    parser.add_argument('--python',type=Path,default=Path(sys.executable))
    args=parser.parse_args();case=json.loads((args.case/'acceptance.json').read_text('utf-8'))
    assert case['passed'] and len(case['inputs'])==2 and not case['original_differences'] and not case['engine_differences']
    work=args.work.resolve();work.mkdir(parents=True,exist_ok=False)
    output=args.evidence.resolve();output.mkdir(parents=True,exist_ok=False)
    data=Path(case['data_root']);root=Path(case['project_root']);elf=Path(case['elf'])
    originals={str(p):(sha256(p),p.stat().st_size,p.stat().st_mtime_ns) for p in root.rglob('*') if p.is_file()}
    source_files=[p for row in case['inputs'] for p in (data/'scans'/row['scan_id']).rglob('*') if p.is_file()]
    source_before={str(p):sha256(p) for p in source_files}
    runtime=[p for p in (args.engine/'ecra').rglob('*') if p.is_file() and p.suffix!='.pyc']
    runtime_before={p.relative_to(args.engine).as_posix():sha256(p) for p in runtime}
    receipt=dict(passed=False,scope=__doc__,tests=[],page_errors=[],external_requests=[],screenshots=[],
                 engine=str(args.engine),actual_python=str(args.python),data_root=str(data),
                 native_case_sha256=sha256(args.case/'acceptance.json'),source_firmware=str(root),
                 controller_sha256=sha256(Path(__file__)),all_gates_passed=False)
    def save():(output/'acceptance.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n','utf-8')
    def passed(name):receipt['tests'].append(dict(name=name,status='PASS'));save()
    save();started=time.monotonic();session=work/'session.json';log=(work/'server.log').open('xb')
    server=subprocess.Popen([str(args.python),'-B','-X','utf8','-m','ecra.studio','--data-root',str(data),
        '--no-browser','--session-file',str(session)],cwd=args.engine,stdout=log,stderr=subprocess.STDOUT,
        env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONIOENCODING='utf-8'),
        creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    browser=context=playwright=page=None;info={}
    def api(path):
        with urllib.request.urlopen(urllib.request.Request('http://'+info['authority']+'/api'+path,
                headers={'X-ECRA-Session':info['token']}),timeout=120) as response:return json.load(response)
    try:
        deadline=time.monotonic()+60
        while True:
            if server.poll() is not None or time.monotonic()>deadline:raise RuntimeError('Actual Studio did not publish a complete session')
            try:
                info=json.loads(session.read_text('utf-8'));api('/bootstrap');break
            except (OSError,ValueError):time.sleep(.05)
        base='http://'+info['authority']
        from playwright.sync_api import sync_playwright,expect
        playwright=sync_playwright().start();browser=playwright.chromium.launch(channel='chrome',headless=True)
        context=browser.new_context(viewport=dict(width=1366,height=768),accept_downloads=True)
        context.tracing.start(screenshots=True,snapshots=True,sources=True)
        page=context.new_page();page.on('pageerror',lambda error:receipt['page_errors'].append(str(error)))
        page.on('request',lambda request:receipt['external_requests'].append(request.url)
                if urllib.parse.urlsplit(request.url).scheme in {'http','https'} and not request.url.startswith(base) else None)
        def idle():expect(page.locator('.activity')).to_have_count(0,timeout=120000)
        def shot(name):
            idle();page.screenshot(path=str(output/(name+'.png')),full_page=True)
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            receipt['screenshots'].append(name+'.png');save()
        page.goto(info['url']);expect(page.get_by_role('heading',name='先处理需要核实的变量')).to_be_visible(timeout=30000)
        page.get_by_role('link',name='数据与共享',exact=True).click()
        panel=page.get_by_role('region',name='多核已有结果合并',exact=True)
        page.get_by_role('button',name='合并已有多核结果',exact=True).click()
        for i,row in enumerate(case['inputs'],1):
            panel.get_by_label('核心别名 '+str(i),exact=True).fill(row['variant'])
            panel.get_by_label('多核扫描 '+str(i),exact=True).select_option(row['scan_id'])
            panel.get_by_label('多核ELF '+str(i),exact=True).set_input_files(elf)
            expect(panel.get_by_role('status').filter(has_text='正在处理真实多核输入')).to_have_count(0,timeout=120000)
            expect(panel.get_by_text('已上传：'+elf.name,exact=True)).to_have_count(i)
        panel.get_by_role('button',name='下一步：共享区域',exact=True).click()
        panel.get_by_role('button',name='检查多核输入',exact=True).click()
        expect(panel.get_by_role('alert')).to_contain_text('共享RAM')
        assert not api('/tasks')['items']
        passed('actual_scan_choices_and_streamed_ELF_uploads_missing_region_rejected_before_task')
        for i,region in enumerate(case['regions'],1):
            if i>1:panel.get_by_role('button',name='添加共享区域',exact=True).click()
            panel.get_by_label('共享RAM起始地址 '+str(i),exact=True).fill(region['start'])
            panel.get_by_label('共享RAM长度 '+str(i),exact=True).fill(region['size'])
        panel.get_by_label('多核资源预设',exact=True).select_option('low')
        panel.get_by_role('button',name='检查多核输入',exact=True).click()
        expect(panel.get_by_role('region',name='多核输入检查计划')).to_be_visible(timeout=120000)
        for row in case['inputs']:
            expect(panel.get_by_role('region',name='多核输入检查计划')).to_contain_text(row['scan_id'])
        receipt['primary_action_bounds']=[]
        for width,height in [(1366,768),(1600,900)]:
            page.set_viewport_size(dict(width=width,height=height))
            panel.evaluate("element=>element.scrollIntoView({block:'start'})")
            box=panel.get_by_role('button',name='开始派生合并',exact=True).bounding_box()
            assert box and box['y']>=0 and box['y']+box['height']<=height,box
            receipt['primary_action_bounds'].append(dict(width=width,height=height,button=box))
        page.set_viewport_size(dict(width=1366,height=768))
        shot('01-real-archived-config-and-explicit-scan-plan')
        panel.get_by_text('查看归档配置来源指纹',exact=True).click()
        panel.get_by_text('扫描时完整配置原文',exact=True).first.click()
        expect(panel.locator('.evidence-node .node-content').first).to_contain_text('Cortex-M0',timeout=120000)
        expect(panel.locator('.evidence-node pre').first).to_have_text(Path(case['inputs'][0]['config']).read_text('utf-8'))
        panel.get_by_text('查看归档配置来源指纹',exact=True).click()
        passed('real_precheck_uses_archived_config_and_explicit_scan_bindings_with_truthful_capability')
        bad=work/'invalid-upload.elf';bad.write_bytes(b'explicit invalid ELF upload fixture')
        panel.get_by_role('button',name='返回共享区域',exact=True).click()
        panel.get_by_role('button',name='返回核心输入',exact=True).click()
        panel.get_by_label('多核ELF 2',exact=True).set_input_files(bad)
        expect(panel.get_by_role('alert')).to_contain_text('ELF32',timeout=120000)
        expect(panel.get_by_role('button',name='下一步：共享区域',exact=True)).to_be_disabled()
        expect(panel.get_by_role('button',name='开始派生合并',exact=True)).to_have_count(0)
        shot('02-invalid-new-ELF-clears-prior-selection-and-plan')
        panel.get_by_label('多核ELF 2',exact=True).set_input_files(elf)
        expect(panel.get_by_role('status').filter(has_text='正在处理真实多核输入')).to_have_count(0,timeout=120000)
        panel.get_by_role('button',name='下一步：共享区域',exact=True).click()
        expect(panel.get_by_label('多核资源预设',exact=True)).to_have_value('low')
        for i,region in enumerate(case['regions'],1):
            expect(panel.get_by_label('共享RAM起始地址 '+str(i),exact=True)).to_have_value(region['start'])
            expect(panel.get_by_label('共享RAM长度 '+str(i),exact=True)).to_have_value(region['size'])
        panel.get_by_role('button',name='检查多核输入',exact=True).click()
        expect(panel.get_by_role('button',name='开始派生合并',exact=True)).to_be_visible(timeout=120000)
        passed('invalid_new_file_cannot_reuse_previous_ELF_token_or_stale_plan')
        panel.get_by_role('button',name='开始派生合并',exact=True).click()
        expect(page.get_by_role('heading',name='扫描任务中心',exact=True)).to_be_visible(timeout=30000)
        deadline=time.monotonic()+180
        while True:
            jobs=api('/tasks')['items'];assert len(jobs)==1
            task=jobs[0]
            if task['state'] not in {'RUNNING','STOP_REQUESTED'}:break
            if time.monotonic()>deadline:raise TimeoutError('Owned native-data multicore operation did not finish')
            page.wait_for_timeout(100)
        assert task['state']=='COMPLETE' and task['mode']=='multicore' and task['budget_bytes']==8*1024**3,task
        assert task['checkpoint_mode']=='RETRY_DERIVATION_FROM_FIXED_INPUTS' and task['resources']['peak_job_commit_bytes']>0
        receipt['task_id']=task['id'];receipt['task_resources']=task['resources'];receipt['task_budget_bytes']=task['budget_bytes']
        expect(page.get_by_role('heading',name='派生结果已发布',exact=True)).to_be_visible(timeout=30000)
        shot('03-real_owned_task_and_resource_budget')
        out=data/'scans'/task['scan_id'];provider=EvidenceProvider(out/'scan.db');binding=provider.validate(deep=True)
        components=provider.load('provenance')['components']
        assert [row['binding']['scan_id'] for row in components]==[row['scan_id'] for row in case['inputs']]
        assert all(row['selection_mode']=='EXPLICIT_SCAN' for row in components)
        assert all(Path(component['facts']['path']).parent==data/'scans'/row['scan_id'] for component,row in zip(components,case['inputs']))
        receipt.update(scan_id=task['scan_id'],binding=binding,static_sha256=sha256(out/'scan.db'))
        passed('actual_owned_worker_publishes_exact_selected_archives_despite_mutable_latest_pointer')
        page.get_by_role('button',name='打开扫描结果',exact=True).click();idle()
        expect(page.get_by_role('note').filter(has_text='链接地址派生合并')).to_be_visible(timeout=30000)
        summary=api('/scans/'+out.name+'/summary');assert summary['can_confirm'] and not summary['can_review']
        candidates=provider.symbols(limit=200)['items']
        target=next(row for row in candidates if provider.symbols(search=row['symbol_id'],limit=1)['total']==1
                    and provider.records('accesses',symbol_id=row['symbol_id'],limit=1)['total']>0)
        page.locator('.cards button').last.click();idle()
        page.get_by_label('人工状态',exact=True).select_option('');idle()
        page.get_by_label('查找变量、文件或规范身份',exact=True).fill(target['symbol_id'])
        page.get_by_role('button',name='搜索',exact=True).click();expect(page.locator('.symbol')).to_have_count(1)
        page.locator('.symbol').click();idle()
        expect(page.locator('.detail-heading h2')).to_have_text(target['name'])
        shot('04-actual_derived_object_and_evidence_workbench')
        passed('actual_canonical_workbench_and_archive_only_capability_without_false_native_claim')
        page.get_by_label('确认者',exact=True).fill('多核流程自动化验收声明')
        page.get_by_label('依据 / 修改或撤销理由',exact=True).fill('获准F030同源别名流程验收；仅验证确认记录保持，不作硬件结论')
        page.get_by_role('button',name='暂无法确认',exact=True).click()
        expect(page.locator('.detail-summary')).to_contain_text('暂无法确认',timeout=120000)
        reviews=ReviewStore(out/'reviews.db',binding)
        assert len(reviews.history())==1
        page.reload();idle();page.get_by_role('link',name='人工确认',exact=True).click()
        page.get_by_role('button',name='继续上次位置',exact=True).click();idle()
        expect(page.locator('.detail-summary .identity')).to_have_text(target['symbol_id'])
        expect(page.locator('.detail-summary')).to_contain_text('暂无法确认')
        shot('05-real_human_event_and_reopened_position')
        passed('actual_human_commit_and_reopened_selection_keep_one_immutable_event')
        page.get_by_role('link',name='数据与共享',exact=True).click()
        with page.expect_download(timeout=180000) as operation:
            page.get_by_role('button',name='导出标准完整包',exact=True).click()
        download=operation.value;archive=work/'complete-derived-result.ecra-report';download.save_as(archive)
        assert download.failure() is None and download.url.startswith(base+'/export-download/')
        restored=import_report(archive,work/'independent-viewer')
        imported=work/'independent-viewer/scans'/restored['scan_id']
        assert EvidenceProvider(imported/'scan.db').metadata()==binding
        assert ReviewStore(imported/'reviews.db',binding).history()==reviews.history()
        receipt.update(archive_bytes=archive.stat().st_size,archive_sha256=sha256(archive))
        shot('06-real_native_download_and_complete_independent_import')
        passed('actual_browser_complete_export_strict_import_preserve_full_roots_and_human_event')
        assert {str(p):sha256(p) for p in source_files}==source_before
        assert originals=={str(p):(sha256(p),p.stat().st_size,p.stat().st_mtime_ns) for p in root.rglob('*') if p.is_file()}
        assert sha256(elf)==case['original_elf_sha256']
        assert sha256(out/'scan.db')==receipt['static_sha256']
        assert runtime_before=={p.relative_to(args.engine).as_posix():sha256(p) for p in runtime}
        assert not receipt['page_errors'] and not receipt['external_requests']
        assert sha256(Path(__file__))==receipt['controller_sha256']
        receipt.update(passed=True,seconds=time.monotonic()-started,source_input_files_unchanged=True,
                       firmware_unchanged=True,runtime_files=len(runtime),runtime_files_unchanged=True)
        passed('source_scans_human_history_firmware_ELF_and_runtime_bytes_unchanged_offline_UI')
    except BaseException:
        receipt.update(error=traceback.format_exc(),seconds=time.monotonic()-started);save()
        if page is not None:
            try:page.screenshot(path=str(output/'failure.png'),full_page=True)
            except Exception:pass
        raise
    finally:
        if context is not None:
            try:context.tracing.stop(path=str(output/'trace.zip'))
            finally:context.close()
        if browser is not None:browser.close()
        if playwright is not None:playwright.stop()
        server.terminate();server.wait(timeout=30);log.close()
    print(json.dumps(dict(passed=receipt['passed'],tests=len(receipt['tests']),seconds=receipt['seconds'])),flush=True)


if __name__=='__main__':main()
