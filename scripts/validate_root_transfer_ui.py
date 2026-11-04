"""Approved native F030 -> Chrome whole-root copy -> old root offline -> resume/rescan.

All working data and user preferences are private. Optional --target permits
an actual second volume. No physical second-PC, clean Portable or UAT claim.
"""
import argparse
from contextlib import redirect_stdout
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

TOOL=Path(__file__).resolve().parents[1];sys.path.insert(0,str(TOOL))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--work',type=Path,required=True)
    parser.add_argument('--target',type=Path)
    args=parser.parse_args()
    import yaml
    from ecra.common import write_json
    from ecra.config import configured_project_root,load_config
    from ecra.report_package import sha256,export_report,import_report
    from ecra.human_reviews import ReviewStore
    from ecra.scan_persistence import run_canonical
    from ecra.scan_store import EvidenceProvider
    from ecra.workspace import WorkspaceResolver,studio_data_root
    from ecra.workflow import status,checked_scan
    work=studio_data_root(args.work);work.mkdir(parents=True,exist_ok=False)
    source=work/'原始 完整数据';target=studio_data_root(args.target or work/'恢复 完整副本')
    assert not target.exists();parked=work/'原目录 离线保留'
    cfg=yaml.safe_load(args.config.read_text('utf-8'));root=configured_project_root(args.config)
    originals={p:(sha256(p),p.stat().st_size,p.stat().st_mtime_ns) for p in [args.config,*root.rglob('*')] if p.is_file()}
    engine={p:sha256(p) for p in (TOOL/'ecra').rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    cfg['analysis']['output']=dict(location='custom',custom_dir=str(source));cfg['review'].update(enabled=False,prepare_packets=False)
    os.environ.update(ECRA_DATA_ROOT=str(source),LOCALAPPDATA=str(work/'private-user'),XDG_CONFIG_HOME=str(work/'private-user'))
    project=WorkspaceResolver.resolve(root,cfg['analysis']).project_id
    profile=source/'projects'/project/'profiles/main.yaml';profile.parent.mkdir(parents=True)
    profile.write_text('# 完整搬迁验收：保留注释\n'+yaml.safe_dump(cfg,allow_unicode=True),'utf-8')
    result=dict(passed=False,scope=__doc__,source=str(source),target=str(target),tests=[],screenshots=[],page_errors=[],external_requests=[])
    def save():write_json(work/'acceptance.json',result)
    save();server=stream=browser=playwright=None;generation=0
    def stop():
        nonlocal server,stream
        if server:server.terminate();server.wait(timeout=30);server=None
        if stream:stream.close();stream=None
    def start(data):
        nonlocal server,stream,generation
        generation+=1;session=work/('session-'+str(generation)+'.json');stream=(work/('server-'+str(generation)+'.log')).open('wb')
        server=subprocess.Popen([sys.executable,'-B','-X','utf8','-m','ecra.studio','--data-root',str(data),
            '--no-browser','--session-file',str(session)],cwd=TOOL,stdout=stream,stderr=subprocess.STDOUT,
            env=dict(os.environ,ECRA_DATA_ROOT=str(data)),creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        end=time.monotonic()+60
        while not session.exists():
            if server.poll() is not None or time.monotonic()>end:raise RuntimeError('Studio failed to start')
            time.sleep(.1)
        value=json.loads(session.read_text('utf-8'));base='http://'+value['authority']
        while True:
            try:urllib.request.urlopen(urllib.request.Request(base+'/api/bootstrap',headers={'X-ECRA-Session':value['token']}),timeout=2).close();break
            except OSError:
                if time.monotonic()>end:raise
                time.sleep(.1)
        return value,base
    try:
        with (work/'native.log').open('w',encoding='utf-8') as log,redirect_stdout(log):
            code=run_canonical(root,profile,no_review=True,scan_id='before-transfer',profile_id='main')
        assert code in {0,1,2}
        scan=source/'scans/before-transfer';provider=EvidenceProvider(scan/'scan.db');provider.validate(deep=True)
        binding=provider.metadata()
        sid=provider.symbols(search='HCLK')['items'][0]['symbol_id']
        old=ReviewStore(scan/'reviews.db',provider.metadata())
        event=old.append(sid,provider.fingerprint(sid),reviewer='搬迁自动化声明',decision='CONFIRMED_RISK',comment='功能测试声明，非硬件复现结论')
        static=sha256(scan/'scan.db');profile_bytes=profile.read_bytes()
        from playwright.sync_api import sync_playwright,expect
        playwright=sync_playwright().start();browser=playwright.chromium.launch(channel='chrome',headless=True)
        context=browser.new_context(viewport=dict(width=1366,height=768))
        info,base=start(source);page=context.new_page()
        def api(path,body=None):
            request=urllib.request.Request(base+'/api'+path,data=None if body is None else json.dumps(body).encode(),
                headers={'X-ECRA-Session':info['token'],'Origin':base,'Content-Type':'application/json'})
            with urllib.request.urlopen(request,timeout=30) as response:return json.load(response)
        actual=api('/tasks',dict(project_id=project,profile_id='main',revision=sha256(profile),
            resources=dict(preset='manual',peak_gib=4,workers=1)))
        stopped_id=actual['id'];api('/tasks/'+stopped_id+'/stop',{})
        end=time.monotonic()+180
        while True:
            task=api('/tasks/'+stopped_id)
            if task['state'] in {'COMPLETE','FAILED','INTERRUPTED'}:break
            if time.monotonic()>end:raise TimeoutError('Real safe stop did not finish')
            time.sleep(.2)
        assert task['state'] in {'INTERRUPTED','FAILED'},task
        result['stopped_task']=dict(id=stopped_id,state=task['state'],exit_code=task.get('exit_code'))
        def events(p,b):
            p.on('pageerror',lambda e:result['page_errors'].append(str(e)))
            p.on('request',lambda r:result['external_requests'].append(r.url) if not r.url.startswith(b) else None)
        events(page,base);page.goto(info['url']);page.get_by_role('link',name='设置与验收状态',exact=True).click()
        page.get_by_label('整套复制的目标空目录',exact=True).fill(str(target))
        page.get_by_role('button',name='检查整套复制计划',exact=True).click()
        page.get_by_role('button',name='开始完整复制并校验',exact=True).click()
        expect(page.get_by_role('heading',name='复制完成',exact=True)).to_be_visible(timeout=180000)
        page.locator('.root-transfer').scroll_into_view_if_needed();shot=work/'01-complete-copy.png';page.screenshot(path=str(shot),full_page=True);result['screenshots'].append(str(shot))
        assert sha256(scan/'scan.db')==static and old.history()==[event] and profile.read_bytes()==profile_bytes
        result['tests'].append('REAL_CHROME_COMPLETE_COPY_ORIGINAL_STATIC_PROFILE_EVENTS_UNCHANGED');save()
        page.close();stop()
        assert source.resolve().is_relative_to(work.resolve()) and parked.resolve().is_relative_to(work.resolve())
        source.rename(parked);assert not source.exists()
        os.environ['ECRA_DATA_ROOT']=str(target)
        moved_profile=target/profile.relative_to(source);moved_scan=target/'scans/before-transfer'
        assert '# 完整搬迁验收：保留注释' in moved_profile.read_text('utf-8')
        assert yaml.safe_load(moved_profile.read_text('utf-8'))['analysis']['output']==dict(location='user')
        assert sha256(moved_scan/'scan.db')==static
        moved_cfg,_=load_config(root,moved_profile)
        _,_,state=checked_scan(root,moved_scan,moved_cfg,moved_profile,with_facts=False,_report_projection=True)
        assert state['fingerprint']
        assert status(root,moved_profile)['resumable'] is True
        result['tests'].append('OLD_ROOT_OFFLINE_REAL_CHECKPOINT_AND_CLI_STATUS_INPUTS_REVERIFIED');save()
        info,base=start(target);page=context.new_page();events(page,base);page.goto(info['url'])
        page.get_by_role('link',name='变量与风险',exact=True).click()
        page.get_by_label('查找变量、文件或规范身份',exact=True).fill('HCLK');page.get_by_role('button',name='搜索',exact=True).click()
        expect(page.locator('.symbol')).to_have_count(1);page.locator('.symbol').click()
        expect(page.locator('.conclusion')).to_contain_text('人工确认有风险')
        page.get_by_label('确认者',exact=True).fill('搬迁后声明')
        page.get_by_label('依据 / 修改或撤销理由',exact=True).fill('复制后继续确认，原事件保留')
        page.get_by_role('button',name='暂无法确认',exact=True).click()
        expect(page.locator('.conclusion')).to_contain_text('暂无法确认',timeout=30000)
        shot=work/'02-new-root-review.png';page.screenshot(path=str(shot),full_page=True);result['screenshots'].append(str(shot))
        archive=work/'after-copy.ecra-report';export_report(moved_scan,archive)
        imported=import_report(archive,work/'independent-viewer')
        restored=ReviewStore(work/'independent-viewer/scans'/imported['scan_id']/'reviews.db',binding)
        assert len(restored.history(sid))==2
        result['tests'].append('REAL_CHROME_NEW_ROOT_CONFIRM_AND_FULL_PACKAGE_ROUNDTRIP');save()
        # Retry through the real supervised task API, using the preserved stopped
        # task config. The derived config only rebinds output; every input is checked.
        started=api('/tasks/'+stopped_id+'/retry',{});end=time.monotonic()+240
        while True:
            item=api('/tasks/'+started['id'])
            if item['state'] in {'COMPLETE','FAILED','INTERRUPTED'}:break
            if time.monotonic()>end:raise TimeoutError('Native retry did not finish')
            time.sleep(.2)
        assert item['state']=='COMPLETE',item
        assert item['data_relocation']['source_sha256']==sha256(target/'work/tasks'/stopped_id/'semantics.yaml')
        after=EvidenceProvider(target/'scans'/item['scan_id']/'scan.db');after.validate(deep=True)
        assert after.metadata()['facts_hash']==binding['facts_hash']
        result['tests'].append('OLD_ROOT_OFFLINE_REAL_SUPERVISED_RETRY_NATIVE_FACTS_EQUAL');save()
        assert not [str(p) for p,v in originals.items() if (sha256(p),p.stat().st_size,p.stat().st_mtime_ns)!=v]
        assert not [str(p) for p,h in engine.items() if sha256(p)!=h]
        parked_provider=EvidenceProvider(parked/'scans/before-transfer/scan.db')
        parked_store=ReviewStore(parked/'scans/before-transfer/reviews.db',parked_provider.metadata())
        assert sha256(parked_provider.path)==static and parked_store.history()==[event]
        result.update(passed=not result['page_errors'] and not result['external_requests'],original_firmware_unchanged=True,
            original_events_unchanged=True,original_scan_sha256=static,facts_hash=after.metadata()['facts_hash'],
            cross_volume=source.anchor.casefold()!=target.anchor.casefold(),engine_unchanged=True)
    except BaseException:
        import traceback
        result['error']=traceback.format_exc();raise
    finally:
        if browser:browser.close()
        if playwright:playwright.stop()
        stop()
        if parked.exists() and not source.exists():parked.rename(source)
        save()
    print(json.dumps(result,ensure_ascii=True),flush=True)
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
