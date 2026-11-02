"""Actual ECRA.cmd / Chrome saved-root restart with existing native archives.

Private LOCALAPPDATA only; original approved F030 files and archive events stay
unchanged. The additional native scan proves current-window output stays bound
after saving a different future default. No data-root migration, physical
second-PC, clean offline-PC, Windows DPI, large-native/G1/G3 or UAT claim.
"""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import time
import traceback
import urllib.request


def wait(predicate, seconds=180):
    end=time.monotonic()+seconds
    while True:
        value=predicate()
        if value:return value
        if time.monotonic()>end:raise TimeoutError('Actual root/scan operation did not complete')
        time.sleep(.05)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['archive-list','config','work','evidence']:p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--engine',type=Path,default=Path(__file__).resolve().parents[1])
    p.add_argument('--allow-external-toolchain',action='store_true')
    args=p.parse_args()
    if os.name!='nt':p.error('Actual Windows launcher and owned Job required')
    sys.path.insert(0,str(args.engine))
    from ecra.studio.process_budget import ProcessBudget
    from ecra.studio.write_guard import OwnedProcess
    from ecra.report_package import sha256,snapshot
    from ecra.scan_store import EvidenceProvider
    from ecra.workspace import no_links,studio_data_root
    import yaml
    work=studio_data_root(args.work);work.mkdir(parents=True,exist_ok=False)
    output=no_links(args.evidence);output.mkdir(parents=True,exist_ok=False)
    (work/'controller.py').write_bytes(Path(__file__).read_bytes())
    def events(folder):
        with closing(sqlite3.connect((folder/'reviews.db').resolve().as_uri()+'?mode=ro',uri=True)) as conn:
            return list(conn.execute('SELECT event_id,payload FROM events ORDER BY event_id'))
    candidates=[no_links(s) for s in json.loads(args.archive_list.read_text('utf-8'))['directories']]
    originals=[s for s in candidates if events(s)][:2];assert len(originals)==2
    original_hashes={}
    local=work/'私有 用户设置';root_a=local/'ECRAStudio/data';root_b=work/'独立 中文数据 B'
    for source,root in zip(originals,[root_a,root_b]):
        target=root/'scans'/source.name;target.mkdir(parents=True)
        files=[source/'scan.db',source/'reviews.db',source/'manifest.json',*(source/'evidence').iterdir()]
        original_hashes.update({f:(sha256(f),f.stat().st_size,f.stat().st_mtime_ns) for f in files if f.is_file()})
        shutil.copyfile(source/'scan.db',target/'scan.db');snapshot(source/'reviews.db',target/'reviews.db')
        shutil.copyfile(source/'manifest.json',target/'manifest.json');shutil.copytree(source/'evidence',target/'evidence')
        assert events(target)==events(source)
    cfg=yaml.safe_load(args.config.read_text('utf-8'));firmware=Path(cfg['project']['root'])
    firmware_hashes={f:(sha256(f),f.stat().st_size,f.stat().st_mtime_ns) for f in firmware.rglob('*') if f.is_file()}
    config_sha=sha256(args.config)
    engine_hashes={f:sha256(f) for f in (args.engine/'ecra').rglob('*') if f.is_file() and f.suffix!='.pyc' and '__pycache__' not in f.parts}
    before_static={root/'scans'/source.name/'scan.db':sha256(source/'scan.db') for source,root in zip(originals,[root_a,root_b])}
    before_events={root/'scans'/source.name:events(source) for source,root in zip(originals,[root_a,root_b])}
    env=dict(os.environ,LOCALAPPDATA=str(local),PYTHONIOENCODING='utf-8')
    for key in ['ECRA_DATA_ROOT','ECRA_PORTABLE_ROOT','ECRA_CONFIG_HOME','PYTHONHOME','PYTHONPATH']:env.pop(key,None)
    windows=Path(os.environ.get('SystemRoot','C:/Windows'))
    process=budget=log=browser=context=playwright=None;info=None;generation=0;allowed=set()
    r=dict(passed=False,scope=__doc__,tests=[],screenshots=[],page_errors=[],external_requests=[],
           engine=str(args.engine),original_archives=[str(s) for s in originals],root_a=str(root_a),root_b=str(root_b),commands=[])
    def save():(output/'acceptance.json').write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n','utf-8')
    def passed(name):r['tests'].append(dict(name=name,status='PASS'));save()
    def api(path,payload=None,method=None):
        request=urllib.request.Request('http://'+info['authority']+'/api'+path,
            data=None if payload is None else json.dumps(payload).encode(),
            headers={'X-ECRA-Session':info['token'],'Origin':'http://'+info['authority'],'Content-Type':'application/json'},method=method)
        with urllib.request.urlopen(request,timeout=30) as response:return json.load(response)
    def stop():
        nonlocal process,budget,log
        if budget:budget.close();budget=None
        if process:process.wait(timeout=30);process.close();process=None
        if log:log.close();log=None
    def start(explicit=None):
        nonlocal info,process,budget,log,generation
        generation+=1;session=work/('session-'+str(generation)+'.json')
        command=[str(windows/'System32/cmd.exe'),'/d','/c',str(args.engine/'ECRA.cmd'),'--no-browser','--session-file',str(session)]
        if explicit is not None:command.extend(['--data-root',str(explicit)])
        r['commands'].append(command);save()
        log=(work/('launcher-'+str(generation)+'.log')).open('xb');budget=ProcessBudget(2*1024**3)
        process=OwnedProcess(command,cwd=work,env=env,log=log);budget.assign(process);process.resume()
        def ready_session():
            if process.poll() is not None:raise RuntimeError('Actual launcher exited; inspect private launcher log')
            try:return json.loads(session.read_text('utf-8'))
            except (ValueError,OSError):return None
        info=wait(ready_session,60);allowed.add('http://'+info['authority']+'/')
        def ready():
            try:return api('/bootstrap')
            except OSError:return None
        return wait(ready,60)
    save()
    try:
        start(root_b);stop()  # real application creates the existing-root marker
        boot=start();assert Path(boot['data_root']).resolve()==root_a.resolve() and boot['data_root_source']=='SYSTEM_DEFAULT'
        from playwright.sync_api import sync_playwright,expect
        playwright=sync_playwright().start();browser=playwright.chromium.launch(channel='chrome',headless=True)
        context=browser.new_context(viewport=dict(width=1366,height=768));context.tracing.start(screenshots=True,snapshots=True,sources=True)
        def page_for_service():
            page=context.new_page()
            page.on('pageerror',lambda e:r['page_errors'].append(str(e)))
            page.on('request',lambda q:r['external_requests'].append(q.url) if q.url.startswith(('http:','https:')) and not any(q.url.startswith(origin) for origin in allowed) else None)
            page.goto(info['url']);expect(page.locator('.activity')).to_have_count(0,timeout=30000);return page
        page=page_for_service()
        def button(name):return page.get_by_role('button',name=name,exact=True)
        def settings():
            page.get_by_role('link',name='设置与验收状态',exact=True).click()
            expect(button('检查数据目录')).to_be_enabled(timeout=30000)
        def shot(name):
            photo=output/(name+'.png');page.screenshot(path=str(photo),full_page=True);r['screenshots'].append(str(photo));save()
        settings();shot('01-current-system-default')
        button('浏览数据目录').click();dialog=page.get_by_role('dialog',name='选择下次启动数据目录',exact=True)
        dialog.get_by_label('要浏览的绝对目录',exact=True).fill(str(root_b));dialog.get_by_role('button',name='打开目录',exact=True).click()
        expect(dialog.get_by_role('button',name='使用此目录',exact=True)).to_be_enabled()
        dialog.get_by_role('button',name='使用此目录',exact=True).click()
        button('检查数据目录').click();expect(button('保存为下次启动目录')).to_be_enabled()
        shot('02-checked-existing-root-with-events');button('保存为下次启动目录').click()
        expect(page.get_by_role('status').filter(has_text='再次双击ECRA.cmd')).to_be_visible(timeout=30000)
        assert Path(api('/bootstrap')['data_root']).resolve()==root_a.resolve()
        preference=local/'ECRAStudio/preferences.json';assert Path(json.loads(preference.read_text('utf-8'))['data_root']).resolve()==root_b.resolve()
        shot('03-saved-next-launch-current-root-retained');passed('actual_GUI_directory_browser_preview_and_atomic_future_default_preserve_current_root')
        cfg.setdefault('analysis',{})['output']=dict(location='user')
        if args.allow_external_toolchain:cfg['analysis']['allow_external_toolchain']=True
        profile=api('/profiles',dict(id='root-binding-f030',yaml=yaml.safe_dump(cfg,allow_unicode=True,sort_keys=False)))
        page.get_by_role('link',name='扫描任务',exact=True).click()
        page.get_by_label('扫描工程配置',exact=True).select_option(profile['id'])
        button('检查并扫描').click()
        task=wait(lambda:next(iter(api('/tasks')['items']),None),30)
        def terminal():
            row=api('/tasks/'+task['id'])
            return row if row['state'] not in {'RUNNING','STOP_REQUESTED'} else None
        finished=wait(terminal,240);assert finished['state']=='COMPLETE' and finished['published'],finished.get('error',finished['state'])
        EvidenceProvider(root_a/'scans'/finished['scan_id']/'scan.db').validate(deep=True)
        assert not (root_b/'scans'/finished['scan_id']).exists() and not list((root_b/'work/tasks').iterdir())
        expect(button('打开扫描结果')).to_be_visible(timeout=30000);shot('04-native-scan-stays-in-current-root')
        r['native_task']=finished;passed('actual_F030_native_after_preference_change_remains_in_original_service_root_not_future_root')
        page.close();stop();boot=start()
        assert boot['data_root_source']=='GUI_DEFAULT' and Path(boot['data_root']).resolve()==root_b.resolve()
        page=page_for_service();settings();expect(page.get_by_text('来源：GUI保存的默认目录',exact=False)).to_be_visible()
        for folder,old in before_events.items():assert events(folder)==old
        shot('05-actual-cmd-reopen-saved-root-with-human-events');passed('actual_default_ECRA_cmd_restart_reads_selected_existing_root_and_preserves_all_original_human_events')
        field=page.get_by_label('下次启动数据目录（绝对路径）',exact=True);field.fill(str(firmware));button('检查数据目录').click()
        expect(page.get_by_role('alert').filter(has_text='数据目录未保存')).to_be_visible()
        expect(button('保存为下次启动目录')).to_have_count(0)
        assert Path(json.loads(preference.read_text('utf-8'))['data_root']).resolve()==root_b.resolve()
        shot('06-firmware-path-rejected-default-retained');passed('actual_GUI_rejects_firmware_directory_without_writing_source_or_overwriting_default')
        page.close();stop();bad=b'{controlled broken startup preference\n';preference.write_bytes(bad)
        boot=start();assert boot['data_root_source']=='RECOVERY_DEFAULT' and boot['preference_warning']
        page=page_for_service();expect(page.get_by_role('alert').filter(has_text='恢复设置').first).to_be_visible()
        settings();field=page.get_by_label('下次启动数据目录（绝对路径）',exact=True);field.fill(str(root_b));button('检查数据目录').click()
        expect(button('保存为下次启动目录')).to_be_disabled()
        page.get_by_label('备份损坏启动设置后保存新目录',exact=True).check();button('保存为下次启动目录').click()
        expect(page.get_by_role('status').filter(has_text='再次双击ECRA.cmd')).to_be_visible(timeout=30000)
        import hashlib
        backup=preference.parent/'preferences-backups'/(hashlib.sha256(bad).hexdigest()+'.json');assert backup.read_bytes()==bad
        shot('07-explicit-recovery-with-immutable-original-settings-backup')
        page.close();stop();boot=start();assert boot['data_root_source']=='GUI_DEFAULT' and Path(boot['data_root']).resolve()==root_b.resolve()
        passed('actual_corrupt_preference_restart_recovery_and_explicit_backup_repair_then_reopen_correct_root')
        for db,digest in before_static.items():assert sha256(db)==digest
        for folder,old in before_events.items():assert events(folder)==old
        assert all((sha256(f),f.stat().st_size,f.stat().st_mtime_ns)==record for f,record in original_hashes.items())
        assert all((sha256(f),f.stat().st_size,f.stat().st_mtime_ns)==record for f,record in firmware_hashes.items())
        assert sha256(args.config)==config_sha and all(sha256(f)==digest for f,digest in engine_hashes.items())
        assert not r['page_errors'] and not r['external_requests']
        passed('all_original_archive_components_firmware_config_and_engine_bytes_unchanged')
        context.tracing.stop(path=str(output/'trace.zip'));r.update(passed=True,tests_count=len(r['tests']),original_archive_files_unchanged=len(original_hashes),firmware_files_unchanged=len(firmware_hashes),engine_files_unchanged=len(engine_hashes));save()
    except BaseException:
        r['error']=traceback.format_exc();save()
        if context:
            try:
                if context.pages:context.pages[-1].screenshot(path=str(output/'failure.png'),full_page=True)
                context.tracing.stop(path=str(output/'failure-trace.zip'))
            except Exception:pass
        raise
    finally:
        if context:context.close()
        if browser:browser.close()
        if playwright:playwright.stop()
        stop()
    return 0


if __name__=='__main__':raise SystemExit(main())
