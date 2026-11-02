"""Actual launcher/Chrome policy persistence, native files and package roundtrip.

Approved F030 only; no large G4, physical clean-PC, DPI or engineer UAT claim.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time
import traceback
import urllib.request


def wait(predicate,seconds=240):
    end=time.monotonic()+seconds
    while True:
        value=predicate()
        if value:return value
        if time.monotonic()>end:raise TimeoutError('Actual native/UI operation has not completed')
        time.sleep(.1)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['config','work','evidence']:parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--engine',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--allow-external-toolchain',action='store_true');args=parser.parse_args()
    if os.name!='nt':parser.error('Actual Windows launcher/Jobs/NTFS/Chrome required')
    sys.path.insert(0,str(args.engine))
    from ecra.studio.process_budget import ProcessBudget
    from ecra.studio.write_guard import OwnedProcess
    from ecra.config import configured_project_root
    from ecra.report_package import sha256
    from ecra.scan_store import EvidenceProvider
    from ecra.workspace import studio_data_root,no_links
    import yaml
    work=studio_data_root(args.work);work.mkdir(parents=True,exist_ok=False)
    output=no_links(args.evidence);output.mkdir(parents=True,exist_ok=False)
    (work/'controller.py').write_bytes(Path(__file__).read_bytes())
    config=args.config.resolve();source=configured_project_root(config);cfg=yaml.safe_load(config.read_text('utf-8'))
    database=(source/cfg['analysis']['compile_database']).resolve()
    before={str(p):(sha256(p),p.stat().st_size,p.stat().st_mtime_ns) for p in [config,database,*source.rglob('*')] if p.is_file()}
    engine_before={str(p):sha256(p) for p in (args.engine/'ecra').rglob('*.py')}
    root=work/'data';viewer=work/'viewer';env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',LOCALAPPDATA=str(work/'user'),ECRA_DATA_ROOT=str(root))
    env.pop('ECRA_PORTABLE_ROOT',None)
    windows=Path(os.environ.get('SystemRoot','C:/Windows'));process=budget=log=browser=context=playwright=page=None;info={};generation=0;allowed=set()
    result=dict(passed=False,tests=[],commands=[],screenshots=[],page_errors=[],external_requests=[],source=str(source),engine=str(args.engine),scope=__doc__)
    def save():(output/'acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n','utf-8')
    def passed(name):result['tests'].append(dict(name=name,status='PASS'));save()
    def api(path,payload=None,method=None):
        request=urllib.request.Request('http://'+info['authority']+'/api'+path,data=None if payload is None else json.dumps(payload).encode(),
            headers={'X-ECRA-Session':info['token'],'Origin':'http://'+info['authority'],'Content-Type':'application/json'},method=method)
        with urllib.request.urlopen(request,timeout=240) as response:return json.load(response)
    def stop():
        nonlocal process,budget,log
        if budget:budget.close();budget=None
        if process:process.wait(timeout=30);process.close();process=None
        if log:log.close();log=None
    def start(data):
        nonlocal process,budget,log,info,generation
        generation+=1;session=work/('session-'+str(generation)+'.json')
        command=[str(windows/'System32/cmd.exe'),'/d','/c',str(args.engine/'ECRA.cmd'),'--data-root',str(data),'--no-browser','--session-file',str(session)]
        result['commands'].append(command);save();log=(work/('launcher-'+str(generation)+'.log')).open('xb');budget=ProcessBudget(2*1024**3)
        process=OwnedProcess(command,cwd=work,env=env,log=log);budget.assign(process);process.resume()
        def ready():
            if process.poll() is not None:raise RuntimeError('Actual launcher exited; inspect private launcher log')
            try:return json.loads(session.read_text('utf-8'))
            except (OSError,ValueError):return None
        info=wait(ready,60);allowed.add('http://'+info['authority']+'/')
        def bound():
            try:return api('/bootstrap')
            except OSError:return None
        wait(bound,60)
    save()
    try:
        start(root)
        from playwright.sync_api import sync_playwright,expect
        playwright=sync_playwright().start();browser=playwright.chromium.launch(channel='chrome',headless=True)
        context=browser.new_context(viewport=dict(width=1366,height=768),accept_downloads=True);context.tracing.start(screenshots=True,snapshots=True,sources=True)
        def open_page():
            value=context.new_page();value.on('pageerror',lambda e:result['page_errors'].append(str(e)))
            value.on('request',lambda q:result['external_requests'].append(q.url) if q.url.startswith(('http:','https:')) and not any(q.url.startswith(origin) for origin in allowed) else None)
            value.goto(info['url']);expect(value.locator('.activity')).to_have_count(0,timeout=30000);return value
        page=open_page()
        def button(name):return page.get_by_role('button',name=name,exact=True)
        def settings():
            page.get_by_role('link',name='设置与验收状态',exact=True).click()
            section=page.locator('.storage-policy-settings');expect(section.locator('summary')).to_contain_text('自动节省存储空间' if api('/storage/policy')['mode']=='auto' else '保持普通文件',timeout=30000)
            if section.get_attribute('open') is None:section.locator('summary').click()
            return section
        def shot(name):
            target=output/(name+'.png');page.screenshot(path=str(target),full_page=True);result['screenshots'].append(str(target));save()
        def choose(mode):
            section=settings();section.get_by_label('新扫描空间策略',exact=True).select_option(mode);section.get_by_role('button',name='保存空间策略',exact=True).click()
            expect(section.get_by_role('status').filter(has_text='应用于下一次扫描')).to_be_visible(timeout=30000);assert api('/storage/policy')['mode']==mode
        choose('off');shot('01-off-policy-saved');passed('actual_GUI_atomic_policy_save_and_readback')
        cfg.setdefault('analysis',{})['output']=dict(location='user')
        if args.allow_external_toolchain:cfg['analysis']['allow_external_toolchain']=True
        profile=api('/profiles',dict(id='storage-policy-f030',yaml=yaml.safe_dump(cfg,allow_unicode=True,sort_keys=False)))
        def launch_scan():
            before_ids={r['id'] for r in api('/tasks')['items']};page.get_by_role('link',name='扫描任务',exact=True).click()
            page.get_by_label('扫描工程配置',exact=True).select_option(profile['id']);button('检查并扫描').click()
            return wait(lambda:next((r for r in api('/tasks')['items'] if r['id'] not in before_ids),None),30)
        first=launch_scan();assert first['storage_policy']['mode']=='off';choose('auto')
        assert api('/tasks/'+first['id'])['storage_policy']['mode']=='off';shot('02-running-task-keeps-off-after-next-policy-auto')
        def finished(task):
            value=api('/tasks/'+task['id']);return value if value['state'] not in {'RUNNING','STOP_REQUESTED'} else None
        off=wait(lambda:finished(first),360);assert off['state']=='COMPLETE' and off['published'],off.get('error')
        off_dir=root/'scans'/off['scan_id'];off_rows=[json.loads(s) for s in (off_dir/'diagnostics/storage-compaction.jsonl').read_text('utf-8').splitlines()]
        assert off_rows and all(r['status']=='SKIPPED_POLICY_OFF' for r in off_rows);EvidenceProvider(off_dir/'scan.db').validate(deep=True)
        old_hash=sha256(off_dir/'scan.db');passed('actual_native_scan_keeps_startup_policy_after_GUI_changes_future_default')
        page.close();stop();start(root);page=open_page();settings();shot('03-reopened-auto-policy')
        assert api('/storage/policy')['mode']=='auto';passed('actual_launcher_restart_preserves_saved_policy')
        second=launch_scan();assert second['storage_policy']['mode']=='auto';auto=wait(lambda:finished(second),360)
        assert auto['state']=='COMPLETE' and auto['published'],auto.get('error');auto_dir=root/'scans'/auto['scan_id']
        rows=[json.loads(s) for s in (auto_dir/'diagnostics/storage-compaction.jsonl').read_text('utf-8').splitlines()]
        assert {r['kind'] for r in rows}=={'worker','cache','authority'} and all(r['status']=='COMPRESSED' and r['byte_verified'] for r in rows)
        EvidenceProvider(auto_dir/'scan.db').validate(deep=True);assert sha256(off_dir/'scan.db')==old_hash
        result['actual_native']=[dict(task=off['id'],scan=off['scan_id'],policy='off',rows=off_rows),dict(task=auto['id'],scan=auto['scan_id'],policy='auto',rows=rows)]
        expect(button('打开扫描结果')).to_be_visible(timeout=30000);button('打开扫描结果').click()
        expect(page.locator('.activity')).to_have_count(0,timeout=30000)
        shot('04-actual-auto-native-complete');passed('actual_next_native_scan_compresses_closed_worker_cache_authority_preserving_old_scan')
        page.get_by_role('link',name='数据与共享',exact=True).click();button('更新空间占用').click()
        expect(page.locator('.activity')).to_have_count(0,timeout=60000)
        table=page.get_by_role('table').filter(has=page.get_by_role('columnheader',name='实际文件分配',exact=True));expect(table).to_be_visible(timeout=60000)
        for name in ['扫描归档','工程与构建','共享缓存','工作与诊断','导出','设置']:expect(table.get_by_role('rowheader',name=name,exact=True)).to_be_visible()
        assert '未测量' not in table.inner_text();shot('05-real-logical-and-allocated-categories');passed('actual_GUI_complete_logical_and_allocated_category_measurement')
        with page.expect_download() as download:button('导出标准完整包').click()
        package=work/'compressed-F030.ecra-report';download.value.save_as(str(package));assert package.is_file()
        page.close();stop();start(viewer);page=open_page();page.get_by_role('link',name='数据与共享',exact=True).click()
        page.get_by_label('选择 .ecra-report',exact=True).set_input_files(str(package))
        imported=wait(lambda:next(iter(api('/scans')['items']),None),360);destination=viewer/'scans'/imported['scan_id']
        EvidenceProvider(destination/'scan.db').validate(deep=True)
        assert EvidenceProvider(destination/'scan.db').roots()==EvidenceProvider(auto_dir/'scan.db').roots()
        shot('06-independent-viewer-imports-compressed-source-package');passed('actual_GUI_standard_package_from_compressed_source_imports_all_typed_roots')
        page.close();stop();start(root);page=open_page();section=settings()
        # A real concurrent API writer changes the revision after the GUI read.
        current=api('/storage/policy');api('/storage/policy',dict(mode='off',revision=current['revision']))
        section.get_by_label('新扫描空间策略',exact=True).select_option('auto');section.get_by_role('button',name='保存空间策略',exact=True).click()
        expect(section.get_by_role('alert')).to_contain_text('其他窗口修改',timeout=30000);assert api('/storage/policy')['mode']=='off'
        shot('07-concurrent-revision-refused');passed('actual_GUI_stale_revision_refuses_to_overwrite_other_window')
        page.close();stop();settings_file=root/'settings/storage-policy.json';corrupt=b'broken owned policy for explicit GUI repair';settings_file.write_bytes(corrupt)
        start(root);page=open_page();page.get_by_role('link',name='设置与验收状态',exact=True).click();section=page.locator('.storage-policy-settings')
        expect(section.get_by_role('button',name='保存空间策略',exact=True)).to_be_disabled(timeout=30000)
        section.get_by_label('备份损坏空间设置后保存',exact=True).check();section.get_by_label('新扫描空间策略',exact=True).select_option('auto')
        section.get_by_role('button',name='保存空间策略',exact=True).click();expect(section.get_by_role('status').filter(has_text='应用于下一次扫描')).to_be_visible(timeout=30000)
        import hashlib
        backup=settings_file.parent/'storage-policy-backups'/(hashlib.sha256(corrupt).hexdigest()+'.json');assert backup.read_bytes()==corrupt
        shot('08-explicit-corrupt-policy-backup-and-repair');passed('actual_GUI_corrupt_policy_requires_explicit_backup_and_preserves_original_bytes')
        changes=[p for p,b in before.items() if (sha256(Path(p)),Path(p).stat().st_size,Path(p).stat().st_mtime_ns)!=b]
        engine_changes=[p for p,h in engine_before.items() if sha256(Path(p))!=h]
        result.update(original_files=len(before),original_changes=changes,engine_files=len(engine_before),engine_changes=engine_changes,
                      package_sha256=sha256(package),old_scan_sha256=old_hash)
        result['passed']=len(result['tests'])==8 and not changes and not engine_changes and not result['page_errors'] and not result['external_requests'];save()
        return 0 if result['passed'] else 1
    except BaseException:
        result['error']=traceback.format_exc()
        if page:
            try:page.screenshot(path=str(output/'failed.png'),full_page=True)
            except Exception:pass
        save();raise
    finally:
        if context:
            try:context.tracing.stop(path=str(output/'browser-trace.zip'))
            except Exception:pass
            context.close()
        if browser:browser.close()
        if playwright:playwright.stop()
        stop()


if __name__=='__main__':raise SystemExit(main())
