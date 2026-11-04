"""Actual authorized saved scan, supervised review stop/retry, real Chrome.

Uses an explicitly missing model executable: real launch failures, never model
reasoning or simulated SAFE. Copies the supplied scan; retains every failure.
No new native scan, large end-to-end review, second-PC or UAT claim.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

TOOL=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(TOOL))


def main():
    global TOOL
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--work',type=Path,required=True)
    parser.add_argument('--engine',type=Path,default=TOOL,help='Production program root, e.g. extracted Portable; test controller remains external')
    parser.add_argument('--python',type=Path,default=Path(sys.executable),help='Actual service/worker interpreter')
    args=parser.parse_args()
    TOOL=args.engine.resolve();sys.path.insert(0,str(TOOL))
    import yaml
    from ecra.common import read_json,write_json
    from ecra.config import configured_project_root
    from ecra.human_reviews import ReviewStore
    from ecra.report_package import sha256,export_report,import_report
    from ecra.scan_store import EvidenceProvider
    from ecra.scan_persistence import runtime
    from ecra.workspace import studio_data_root
    work=studio_data_root(args.work);root=configured_project_root(args.config)
    if work==root or work.is_relative_to(root) or root.is_relative_to(work):
        raise ValueError('验收目录须独立于原固件')
    work.mkdir(parents=True,exist_ok=False)
    def stamps(paths):
        return {str(p):(sha256(p),p.stat().st_size,p.stat().st_mtime_ns) for p in paths if p.is_file()}
    original=stamps([args.config,*root.rglob('*'),*args.source.rglob('*')])
    engine=stamps([Path(__file__),*(p for p in (TOOL/'ecra').rglob('*')
                  if p.is_file() and '__pycache__' not in p.parts)])
    data=work/'独立 数据';scan=data/'scans'/args.source.name
    shutil.copytree(args.source,scan)
    provider=EvidenceProvider(scan/'scan.db');binding=provider.metadata()
    human_before=ReviewStore(scan/'reviews.db',binding).history()
    static=sha256(scan/'scan.db')
    os.environ.update(ECRA_DATA_ROOT=str(data),LOCALAPPDATA=str(work/'private-user'),XDG_CONFIG_HOME=str(work/'private-user'))
    cfg=yaml.safe_load(args.config.read_text('utf-8'));cfg['analysis']['output']=dict(location='user')
    cfg['review'].update(enabled=False,command=['ECRA_MISSING_EXECUTABLE_DO_NOT_CONNECT'],workers=2,retries=0)
    result=dict(passed=False,scope=__doc__,engine_root=str(TOOL),service_python=str(args.python.resolve()),
        tests=[],screenshots=[],page_errors=[],external_requests=[])
    def save():write_json(work/'acceptance.json',result)
    save();server=log=playwright=browser=None
    try:
        log=(work/'server.log').open('wb');session=work/'session.json'
        server=subprocess.Popen([str(args.python),'-B','-X','utf8','-m','ecra.studio','--data-root',str(data),
            '--no-browser','--session-file',str(session)],cwd=TOOL,stdout=log,stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        end=time.monotonic()+60
        while not session.is_file():
            if server.poll() is not None or time.monotonic()>end:raise RuntimeError('Studio did not start')
            time.sleep(.1)
        info=read_json(session);base='http://'+info['authority']
        import psutil
        actual_python=Path(psutil.Process(server.pid).exe()).resolve()
        assert os.path.samefile(actual_python,args.python)
        result['actual_service_python']=str(actual_python)
        def api(path,body=None):
            request=urllib.request.Request(base+'/api'+path,data=None if body is None else json.dumps(body).encode(),
                headers={'X-ECRA-Session':info['token'],'Content-Type':'application/json','Origin':base})
            try:
                with urllib.request.urlopen(request,timeout=60) as response:return json.load(response)
            except urllib.error.HTTPError as exc:
                raise ValueError(f'{path}: HTTP {exc.code}: {exc.read().decode("utf-8")}') from exc
        while True:
            try:api('/bootstrap');break
            except OSError:
                if time.monotonic()>end:raise
                time.sleep(.1)
        profile=api('/profiles',dict(id=binding['profile_id'],yaml=yaml.safe_dump(cfg,allow_unicode=True)))
        assert profile['project_id']==binding['project_id']
        from playwright.sync_api import sync_playwright,expect
        playwright=sync_playwright().start();browser=playwright.chromium.launch(channel='chrome',headless=True)
        page=browser.new_page(viewport=dict(width=1366,height=768))
        page.on('pageerror',lambda error:result['page_errors'].append(str(error)))
        page.on('request',lambda req:result['external_requests'].append(req.url) if not req.url.startswith(base) else None)
        page.goto(info['url']);page.get_by_role('link',name='历史与对比',exact=True).click()
        page.get_by_label('归档 '+args.source.name,exact=True).get_by_role('button',name='打开结果',exact=True).click()
        expect(page.locator('.activity')).to_have_count(0,timeout=30000)
        page.get_by_role('link',name='OpenCode 复核',exact=True).click()
        expect(page.get_by_role('button',name='复核全部疑似与未知',exact=True)).to_be_enabled()
        assert api('/tasks')['items']==[],'Opening review must not start a task'
        page.get_by_role('button',name='复核全部疑似与未知',exact=True).click()
        expect(page.get_by_role('button',name='安全停止',exact=True)).to_be_enabled(timeout=30000)
        stopped=api('/tasks')['items'][0]
        page.get_by_role('button',name='安全停止',exact=True).click()
        def finished(ident):
            end=time.monotonic()+240
            while True:
                task=api('/tasks/'+ident)
                if task['state'] in {'COMPLETE','FAILED','INTERRUPTED'}:return task
                if time.monotonic()>end:raise TimeoutError('Supervised review did not finish')
                time.sleep(.2)
        stopped=finished(stopped['id']);assert stopped['state']=='INTERRUPTED',stopped
        assert stopped['progress_kind']=='AI_REVIEW' and 'tu_cache' not in stopped
        result['stopped_task']=stopped
        expect(page.get_by_role('button',name='重新核对输入并重试复核',exact=True)).to_be_enabled(timeout=30000)
        shot=work/'01-real-review-stop.png';page.screenshot(path=str(shot),full_page=True);result['screenshots'].append(str(shot))
        with page.expect_response(lambda response:response.url.endswith('/retry') and response.request.method=='POST') as submitted:
            page.get_by_role('button',name='重新核对输入并重试复核',exact=True).click()
        retry=submitted.value.json();assert retry['id']!=stopped['id']
        retry=finished(retry['id']);assert retry['state']=='COMPLETE',retry
        assert retry['progress_kind']=='AI_REVIEW' and 'tu_cache' not in retry
        queue=runtime(scan)['reviews'];assert len(queue)>0 and all(row['state']=='TECH_FAILED' for row in queue)
        assert retry['memory']['completed_units']==retry['memory']['total_units']==len(queue)
        expect(page.get_by_role('heading',name='复核执行已结束',exact=True)).to_be_visible(timeout=30000)
        expect(page.locator('.task-detail')).to_contain_text('复核项目已处理（含技术失败）',timeout=30000)
        expect(page.locator('.task-detail')).not_to_contain_text('TU 解析完成')
        page.locator('.task-detail p').filter(has_text='复核项目已处理（含技术失败）').scroll_into_view_if_needed()
        shot=work/'02-real-review-failures-count.png';page.screenshot(path=str(shot),full_page=True);result['screenshots'].append(str(shot))
        result['retry_task']=retry;result['tests'].append('REAL_SUPERVISED_CHROME_STOP_RETRY_INPUT_GATES_AND_EXACT_FAILURE_COUNTS');save()
        previous={row['finding_id']:len(row['attempts']) for row in queue}
        page.get_by_role('link',name='OpenCode 复核',exact=True).click()
        expect(page.get_by_role('button',name='仅重试技术失败',exact=True)).to_be_enabled(timeout=30000)
        with page.expect_response(lambda response:response.url.endswith('/api/tasks') and response.request.method=='POST') as submitted:
            page.get_by_role('button',name='仅重试技术失败',exact=True).click()
        failed=submitted.value.json();assert failed['mode']=='review-failed'
        failed=finished(failed['id']);assert failed['state']=='COMPLETE',failed
        queue=runtime(scan)['reviews'];assert all(row['state']=='TECH_FAILED' and len(row['attempts'])>previous[row['finding_id']] for row in queue)
        result['failed_only_task']=failed;result['tests'].append('REAL_MISSING_EXECUTABLE_TECH_FAILED_RETRY_WITH_HISTORY_NO_SAFE')
        page.get_by_role('link',name='OpenCode 复核',exact=True).click()
        expect(page.get_by_role('heading',name='原始状态与完整收据',exact=True)).to_be_visible()
        first=page.locator('.history-event').first;first.get_by_text('Packet / 提示词 / 原始响应',exact=True).click()
        artifact=queue[0]['packet_file'];first.get_by_role('button',name=artifact,exact=True).click()
        expect(page.get_by_role('heading',name='审计原件',exact=True)).to_be_visible()
        shot=work/'03-real-packet-archive.png';page.screenshot(path=str(shot),full_page=True);result['screenshots'].append(str(shot))
        assert sha256(scan/'scan.db')==static and ReviewStore(scan/'reviews.db',binding).history()==human_before
        archive=work/'review-failures.ecra-report';export_report(scan,archive)
        imported=import_report(archive,work/'offline');restored=work/'offline/scans'/imported['scan_id']
        assert runtime(restored)['reviews']==queue
        result['tests'].append('REAL_PACKET_UI_FULL_PACKAGE_ROUNDTRIP_STATIC_AND_HUMAN_UNCHANGED')
        differences=[path for path,value in original.items() if stamps([Path(path)]).get(path)!=value]
        changes=[path for path,value in engine.items() if stamps([Path(path)]).get(path)!=value]
        assert not differences and not changes,(differences,changes)
        result.update(passed=not result['page_errors'] and not result['external_requests'],static_sha256=static,
            source_files=len(original),original_differences=differences,engine_differences=changes,
            review_states={row['finding_id']:row['state'] for row in queue},package_sha256=sha256(archive),
            model_reasoning='NOT_VERIFIED',all_gates_passed=False)
    except BaseException:
        import traceback
        result['error']=traceback.format_exc();raise
    finally:
        if browser:browser.close()
        if playwright:playwright.stop()
        if server:server.terminate();server.wait(timeout=30)
        if log:log.close()
        save()
    print(json.dumps(result,ensure_ascii=True),flush=True)
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
