"""Actual owned-worker/service crash and GUI retry against approved F030 inputs.

No mocked API/process result. Each run needs a fresh private root. Existing native
archives, human declarations and input bytes must survive both injected crashes.
This is not a power-loss/system-reboot, large-native or full G5 certification.
"""
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import traceback
import urllib.request


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024**2),b''):h.update(block)
    return h.hexdigest()


def wait(predicate, seconds=180):
    deadline=time.monotonic()+seconds
    while True:
        result=predicate()
        if result:return result
        if time.monotonic()>deadline:raise TimeoutError('Actual operation did not reach its required state')
        time.sleep(.03)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['engine','python','config','work','evidence']:p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--allow-external-toolchain',action='store_true',help='明确允许黄金编译数据库的原外部工具链，不替换编译器/宏')
    args=p.parse_args()
    if os.name!='nt':p.error('Actual Windows Job ownership is required')
    # Host-only browser/observer dependencies are not a runtime requirement.
    import psutil,yaml
    from playwright.sync_api import sync_playwright,expect
    sys.path.insert(0,str(args.engine.resolve()))
    from ecra.scan_store import EvidenceProvider
    from ecra.workspace import studio_data_root,no_links
    work=studio_data_root(args.work.resolve());work.mkdir(parents=True,exist_ok=False)
    output=no_links(args.evidence.resolve());output.mkdir(parents=True,exist_ok=False)
    (work/'controller.py').write_bytes(Path(__file__).read_bytes())
    cfg=yaml.safe_load(args.config.read_text('utf-8'));source=Path(cfg['project']['root'])
    before={str(f.relative_to(source)):sha(f) for f in source.rglob('*') if f.is_file()}
    original_config_sha=sha(args.config)
    cfg.setdefault('analysis',{})['output']=dict(location='user')
    if args.allow_external_toolchain:cfg['analysis']['allow_external_toolchain']=True
    raw=yaml.safe_dump(cfg,allow_unicode=True,sort_keys=False)
    data=work/'data';server=log=browser=context=playwright=None;generation=0;info=None
    r=dict(passed=False,status='STARTING',scope=__doc__,tests=[],screenshots=[],page_errors=[],external_requests=[],
           engine=str(args.engine),python=str(args.python),source=str(source),original_config_sha256=original_config_sha,
           physical32GB='NOT_VERIFIED',power_loss='NOT_VERIFIED',full_G5='NOT_CLOSED',engineer_UAT='NOT_VERIFIED')
    def save():(output/'acceptance.json').write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n','utf-8')
    def events(scan):
        with closing(sqlite3.connect((data/'scans'/scan/'reviews.db').resolve().as_uri()+'?mode=ro',uri=True)) as c:
            return list(c.execute('SELECT event_id,payload FROM events ORDER BY revision,event_id'))
    def api(path,payload=None):
        request=urllib.request.Request('http://'+info['authority']+'/api'+path,
            data=None if payload is None else json.dumps(payload).encode(),
            headers={'X-ECRA-Session':info['token'],'Content-Type':'application/json','Origin':'http://'+info['authority']})
        with urllib.request.urlopen(request,timeout=30) as response:return json.load(response)
    def start_service():
        nonlocal server,log,generation,info
        generation+=1;session=work/('session-'+str(generation)+'.json')
        log=(work/('server-'+str(generation)+'.log')).open('xb')
        server=subprocess.Popen([str(args.python),'-B','-X','utf8','-m','ecra.studio','--data-root',str(data),
            '--no-browser','--session-file',str(session)],cwd=args.engine,
            env=dict(os.environ,PYTHONIOENCODING='utf-8'),stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
        def session_ready():
            if server.poll() is not None:raise RuntimeError('Actual Studio exited before session startup')
            try:return json.loads(session.read_text('utf-8'))
            except (OSError,ValueError):return None
        info=wait(session_ready,60)
        def ready():
            try:return api('/bootstrap')
            except OSError:return None
        wait(ready,60)
    def screenshot(page,name):
        expect(page.locator('.activity')).to_have_count(0,timeout=30000)
        path=output/(name+'.png');page.screenshot(path=str(path),full_page=True);r['screenshots'].append(str(path));save()
    def task_page():
        page=context.new_page();page.on('pageerror',lambda e:r['page_errors'].append(str(e)))
        page.on('request',lambda q:r['external_requests'].append(q.url) if q.url.startswith(('http:','https:')) and not q.url.startswith('http://'+info['authority']+'/') else None)
        page.goto(info['url']);page.get_by_role('link',name='扫描任务',exact=True).click()
        expect(page.get_by_role('heading',name='扫描任务中心',exact=True)).to_be_visible();return page
    def launch(page,known):
        page.get_by_role('button',name='检查并扫描',exact=True).click()
        return wait(lambda:next((t for t in api('/tasks')['items'] if t['id'] not in known),None),30)
    def completed(page,task):
        def terminal():
            value=api('/tasks/'+task['id'])
            return value if value['state'] not in {'RUNNING','STOP_REQUESTED'} else None
        value=wait(terminal);assert value['state']=='COMPLETE' and value['published'],value.get('error',value['state'])
        expect(page.get_by_role('button',name='打开扫描结果',exact=True)).to_be_visible(timeout=30000)
        EvidenceProvider(data/'scans'/value['scan_id']/'scan.db').validate(deep=True);return value
    def actual_worker(task):
        out=data/'scans'/task['scan_id']
        def native_worker():
            if not (out/'storage.json').is_file():return None
            for child in psutil.Process(server.pid).children(recursive=True):
                try:
                    command=child.cmdline()
                    if 'ecra.studio.task_worker' in command and str(data/'work/tasks'/task['id']/'semantics.yaml') in command:
                        return child
                except psutil.NoSuchProcess:pass
            return None
        return wait(native_worker)
    def identity(process):return dict(pid=process.pid,created=process.create_time(),command=process.cmdline())
    def original_survives(scan,digest,history,pointer):
        assert sha(data/'scans'/scan/'scan.db')==digest
        assert events(scan)==history
        assert pointer.read_bytes()==pointer_before
    save()
    try:
        start_service();profile=api('/profiles',dict(yaml=raw,id='crash-recovery-f030'))
        playwright=sync_playwright().start()
        browser=playwright.chromium.launch(channel='chrome',headless=True);context=browser.new_context(viewport=dict(width=1366,height=768))
        context.tracing.start(screenshots=True,snapshots=True,sources=True)
        r['status']='FIRST_NATIVE';save()
        page=task_page();first=completed(page,launch(page,set()))
        page.get_by_role('button',name='打开扫描结果',exact=True).click()
        page.get_by_role('link',name='变量与风险',exact=True).click()
        page.get_by_label('查找变量、文件或规范身份',exact=True).fill('HCLK');page.get_by_role('button',name='搜索',exact=True).click()
        expect(page.locator('.symbol')).to_have_count(1);page.locator('.symbol').click()
        page.get_by_label('确认者',exact=True).fill('U08异常退出自动化验收声明')
        page.get_by_label('依据 / 修改或撤销理由',exact=True).fill('暂无法确认；仅验证独立验收数据的故障恢复，不作固件安全证明')
        page.get_by_role('button',name='暂无法确认',exact=True).click()
        expect(page.get_by_role('status').filter(has_text='已保存')).to_be_visible(timeout=30000)
        first_id=first['scan_id'];first_sha=sha(data/'scans'/first_id/'scan.db');first_events=events(first_id);assert len(first_events)==1
        pointer=next((data/'projects').glob('*/latest-scan-crash-recovery-f030.json'));pointer_before=pointer.read_bytes()
        screenshot(page,'01-valid-scan-and-declaration');r['tests'].append(dict(name='actual_native_valid_scan_and_declared_pending_event',status='PASS'));r['status']='WORKER_CRASH';save()
        page.get_by_role('link',name='扫描任务',exact=True).click()
        crashed=launch(page,{t['id'] for t in api('/tasks')['items']});worker=actual_worker(crashed);declared=identity(worker)
        assert worker.create_time()==declared['created'];worker.terminate();worker.wait(timeout=15)
        expect(page.get_by_role('heading',name='扫描失败',exact=True)).to_be_visible(timeout=30000)
        value=api('/tasks/'+crashed['id']);assert value['state']=='FAILED' and not value['published']
        expect(page.get_by_role('button',name='打开扫描结果',exact=True)).to_have_count(0)
        original_survives(first_id,first_sha,first_events,pointer);screenshot(page,'02-worker-crash-old-scan-retained')
        r['tests'].append(dict(name='actual_owned_worker_crash_preserves_valid_scan_pointer_and_events',status='PASS',injected_process=declared));save()
        known={t['id'] for t in api('/tasks')['items']};page.get_by_role('button',name='从已验证 TU 恢复 / 重试',exact=True).click()
        retry=wait(lambda:next((t for t in api('/tasks')['items'] if t['id'] not in known),None),30)
        recovered=completed(page,retry);assert recovered['tu_cache']['hits']>0,recovered.get('tu_cache')
        assert sha(data/'scans'/first_id/'scan.db')==first_sha and events(first_id)==first_events
        screenshot(page,'03-worker-crash-retry-cache-verified')
        r['tests'].append(dict(name='actual_gui_retry_after_worker_crash_revalidates_inputs_and_reuses_tu',status='PASS',task=recovered));save()
        stable_id=recovered['scan_id'];stable_sha=sha(data/'scans'/stable_id/'scan.db');stable_events=events(stable_id);pointer_before=pointer.read_bytes()
        r['status']='SERVICE_CRASH';save()
        pending=launch(page,{t['id'] for t in api('/tasks')['items']});worker=actual_worker(pending)
        parent=psutil.Process(server.pid);owned=[identity(c) for c in parent.children(recursive=True)];parent_id=identity(parent)
        assert parent.create_time()==parent_id['created'] and '--data-root' in parent_id['command'] and str(data) in parent_id['command']
        server.terminate();server.wait(timeout=20);log.close();log=None
        def owned_gone():
            for row in owned:
                try:
                    if psutil.Process(row['pid']).create_time()==row['created']:return False
                except psutil.NoSuchProcess:pass
            return True
        assert wait(owned_gone,20)
        original_survives(stable_id,stable_sha,stable_events,pointer)
        page.close();start_service();page=task_page()
        interrupted=api('/tasks/'+pending['id']);assert interrupted['state']=='INTERRUPTED' and not interrupted.get('published',False)
        expect(page.get_by_role('heading',name='已停止 / 上次中断',exact=True)).to_be_visible(timeout=30000)
        expect(page.get_by_role('button',name='打开扫描结果',exact=True)).to_have_count(0)
        original_survives(stable_id,stable_sha,stable_events,pointer);screenshot(page,'04-service-reopened-interrupted')
        r['tests'].append(dict(name='actual_server_crash_kills_owned_descendants_and_reopen_keeps_valid_history',status='PASS',injected_server=parent_id,owned_descendants=owned));save()
        known={t['id'] for t in api('/tasks')['items']};page.get_by_role('button',name='从已验证 TU 恢复 / 重试',exact=True).click()
        retried=wait(lambda:next((t for t in api('/tasks')['items'] if t['id'] not in known),None),30)
        final=completed(page,retried);assert final['tu_cache']['hits']>0
        assert sha(data/'scans'/first_id/'scan.db')==first_sha and events(first_id)==first_events
        assert sha(data/'scans'/stable_id/'scan.db')==stable_sha and events(stable_id)==stable_events
        screenshot(page,'05-service-reopen-retry-cache-verified');r['tests'].append(dict(name='actual_gui_retry_after_restart_preserves_both_prior_valid_scans',status='PASS',task=final))
        assert before=={str(f.relative_to(source)):sha(f) for f in source.rglob('*') if f.is_file()}
        assert sha(args.config)==original_config_sha and not r['page_errors'] and not r['external_requests']
        context.tracing.stop(path=str(output/'trace.zip'));r.update(passed=True,status='COMPLETE',input_files_unchanged=len(before),original_config_unchanged=True,valid_scans_preserved=[first_id,stable_id]);save()
        context.close();context=None;browser.close();browser=None
    except BaseException:
        r.update(status='FAILED',error=traceback.format_exc());save()
        if context:
            try:
                if context.pages:context.pages[-1].screenshot(path=str(output/'failure.png'),full_page=True)
                context.tracing.stop(path=str(output/'failure-trace.zip'))
            except Exception:pass
        raise
    finally:
        if server is not None and server.poll() is None:server.terminate();server.wait(timeout=30)
        if log:log.close()
        if context:context.close()
        if browser:browser.close()
        if playwright:playwright.stop()
    return 0


if __name__=='__main__':raise SystemExit(main())
