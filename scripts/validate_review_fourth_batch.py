"""Actual packaged Chrome:1000 additional NEED_MORE_EVIDENCE declarations.

Only the explicitly marked private copy of the approved original INAV graph,
with all3000 known prior events, is accepted. Eligible canonical objects are
SUSPECT/UNKNOWN/SAFE_PROVEN with PENDING human state. No safe declarations, no
new native scan/G2/physical second-PC/DPI/UAT claim. Original root is preserved.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import traceback
import urllib.parse
import urllib.request
from contextlib import closing

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ecra.common import write_json
from ecra.scan_store import EvidenceProvider
from ecra.workspace import no_links,studio_data_root


def file_hash(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for part in iter(lambda:stream.read(4*1024**2),b''):h.update(part)
    return h.hexdigest()


def events(path):
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as c:
        return [json.loads(r[0]) for r in c.execute('SELECT payload FROM events ORDER BY revision,event_id')]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['data','engine','python','work','evidence']:p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--expected-existing-events',type=int,default=3000);p.add_argument('--count',type=int,default=1000)
    args=p.parse_args()
    if args.count!=1000 or args.expected_existing_events!=3000:p.error('This continuation contract is exactly3000 existing +1000 new events')
    data=studio_data_root(args.data.resolve());work=studio_data_root(args.work.resolve());output=no_links(args.evidence.resolve())
    if work.is_relative_to(data) or data.is_relative_to(work):raise ValueError('Keep diagnostic receipts separate from the existing data root')
    scan_id='original-native-comparison-only';scan=no_links(data/'scans'/scan_id)
    manifest=json.loads((scan/'manifest.json').read_text('utf-8'))
    if manifest.get('format')!='ECRA_VALIDATION_NATIVE_GRAPH_COPY':raise ValueError('Only the existing explicitly marked U16 validation archive is authorized')
    graph=no_links(scan/'scan.db');reviews=no_links(scan/'reviews.db');provider=EvidenceProvider(graph);binding=provider.metadata()
    if binding['facts_hash']!='9da30821f449de364352f533134d80e731e031f44bbe69ec86d8f287ac12b6c2':raise ValueError('Unexpected native graph')
    old=events(reviews)
    if (len(old)!=3000 or any(e['decision']!='NEED_MORE_EVIDENCE' for e in old)
        or sum(e['reviewer']=='U16自动化容量验收声明' for e in old)!=1000
        or sum(e['reviewer']=='U16升级后第二批自动化验收声明' for e in old)!=1000
        or sum(e['reviewer']=='U16v23第三批自动化验收声明' for e in old)!=1000):raise ValueError('Existing decisions differ from the known isolated validation batch; no mutations made')
    marker=json.loads((data/'U16-PRIVATE-COPY.json').read_text('utf-8'))
    old_events_hash=hashlib.sha256(json.dumps(old,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest()
    assert marker['format']=='ECRA_U16_PRIVATE_UPGRADE_COPY_V1' and marker['source_events']==3000 and marker['source_events_sha256']==old_events_hash
    assert marker['source_graph_sha256']=='660dffb23a520fdb279f062965267cb5e7710fd59da3a4ede403386792c2c606'
    old_ids={e['event_id'] for e in old};old_symbols={e['symbol_id'] for e in old}
    assert len(old_ids)==len(old_symbols)==3000 and provider.counts()['UNKNOWN']==3366
    work.mkdir(parents=True,exist_ok=False);output.mkdir(parents=True,exist_ok=False);(work/'controller.py').write_bytes(Path(__file__).read_bytes())
    before=(graph.stat().st_size,graph.stat().st_mtime_ns);expected_sha='660dffb23a520fdb279f062965267cb5e7710fd59da3a4ede403386792c2c606'
    receipt=dict(passed=False,state='VERIFYING_EXISTING_GRAPH',scope=__doc__,existing_events=3000,requested=1000,completed=0,
        data_root=str(data),engine=str(args.engine.resolve()),server_python=str(args.python.resolve()),tests=[],screenshots=[],
        source_snapshot_head=json.loads((args.engine/'SOURCE-SNAPSHOT.json').read_text('utf-8'))['head'],private_copy=marker,eligible_classes=['SUSPECT','UNKNOWN','SAFE_PROVEN'],page_errors=[],external_requests=[],native_scan='NOT_EXERCISED',physical_second_computer='NOT_VERIFIED',windows_dpi='NOT_VERIFIED',engineer_uat='NOT_VERIFIED')
    def save():write_json(output/'acceptance.json',receipt)
    save();start=time.monotonic();server=log=browser=context=playwright=None;latencies=[];seen=set();port_count=0;initial_pending=None;expected_position=None
    try:
        assert file_hash(graph)==expected_sha
        receipt.update(state='BROWSER',static_sha256=expected_sha,static_bytes=before[0]);save()
        from playwright.sync_api import sync_playwright,expect
        playwright=sync_playwright().start();browser=playwright.chromium.launch(channel='chrome',headless=True)
        context=browser.new_context(viewport=dict(width=1366,height=768));context.tracing.start(screenshots=False,snapshots=True,sources=True)
        def open_service(expected_new):
            nonlocal server,log,port_count,initial_pending,expected_position
            port_count+=1;session=work/('session-'+str(port_count)+'.json');log=(work/('server-'+str(port_count)+'.log')).open('wb')
            server=subprocess.Popen([str(args.python),'-B','-X','utf8','-m','ecra.studio','--data-root',str(data),'--no-browser','--session-file',str(session)],
                cwd=args.engine,env=dict(os.environ,PYTHONIOENCODING='utf-8'),stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            deadline=time.monotonic()+60
            while True:
                if server.poll() is not None or time.monotonic()>deadline:raise RuntimeError('Actual packaged Studio did not publish a complete session')
                try:info=json.loads(session.read_text('utf-8'));break
                except (FileNotFoundError,PermissionError,json.JSONDecodeError):time.sleep(.05)
            base='http://'+info['authority']
            def get(path):
                with urllib.request.urlopen(urllib.request.Request(base+'/api'+path,headers={'X-ECRA-Session':info['token']}),timeout=30) as response:return json.load(response)
            while True:
                try:get('/bootstrap');break
                except OSError:
                    if time.monotonic()>deadline:raise
                    time.sleep(.1)
            if expected_position is not None:assert get('/scans/'+scan_id+'/position')==expected_position
            def eligible_counts():
                return {state:get('/scans/'+scan_id+'/symbols?classification='+state+'&human_decision=PENDING&limit=1')['total'] for state in ['SUSPECT','UNKNOWN','SAFE_PROVEN']}
            pending=eligible_counts()
            if initial_pending is None:initial_pending=sum(pending.values());assert initial_pending>=1000
            assert sum(pending.values())==initial_pending-expected_new
            receipt['initial_eligible_pending']=initial_pending
            prior_position=get('/scans/'+scan_id+'/position')
            page=context.new_page();page.on('pageerror',lambda e:receipt['page_errors'].append(str(e)))
            page.on('request',lambda r:receipt['external_requests'].append(r.url) if urllib.parse.urlsplit(r.url).scheme in {'http','https'} and urllib.parse.urlsplit(r.url).hostname!='127.0.0.1' else None)
            page.goto(info['url']);expect(page.get_by_role('heading',name='先处理需要核实的变量',exact=True)).to_be_visible(timeout=30000)
            page.get_by_role('button',name='继续人工确认',exact=True).click()
            expect(page.locator('.activity')).to_have_count(0,timeout=30000)
            if expected_position is not None:
                expect(page.get_by_label('人工状态',exact=True)).to_have_value('PENDING')
                expect(page.get_by_label('静态分类',exact=True)).to_have_value(expected_position['classification'])
                expect(page.get_by_label('查找变量、文件或规范身份',exact=True)).to_have_value(expected_position.get('search',''))
            else:
                # The real source history may retain a previous evidence
                # search. Preserve that state, then deliberately widen the
                # capacity-test scope through visible controls, never SQL.
                receipt['initial_saved_position']=prior_position
                if prior_position:
                    expect(page.get_by_label('查找变量、文件或规范身份',exact=True)).to_have_value(prior_position.get('search',''))
                    old_extra=prior_position.get('extra') or {}
                    assert not any(old_extra.get(key) for key in ['file','function','context','coverage','ai_state','diff','handling_status'])
                exact=page.get_by_role('button',name='清除精确定位',exact=True)
                if exact.count():exact.click();expect(page.locator('.activity')).to_have_count(0)
                page.get_by_label('查找变量、文件或规范身份',exact=True).fill('')
                receipt['initial_scope_widened_via_visible_UI']=True
            chosen=next(state for state,count in pending.items() if count>0)
            page.get_by_label('静态分类',exact=True).select_option(chosen);page.get_by_label('人工状态',exact=True).select_option('PENDING')
            page.get_by_role('button',name='搜索',exact=True).click();expect(page.locator('.activity')).to_have_count(0)
            assert len(events(reviews))==3000+expected_new
            page.get_by_label('确认者',exact=True).fill('U16v32第四批自动化验收声明')
            return page,get
        page,get=open_service(0);receipt['tests'].append(dict(name='v32_private_copy_opens3000_prior_events_without_reset',status='PASS',old_events=3000));save()
        for index in range(1000):
            if page.locator('.symbol').count()==0:
                pending={state:get('/scans/'+scan_id+'/symbols?classification='+state+'&human_decision=PENDING&limit=1')['total'] for state in ['SUSPECT','UNKNOWN','SAFE_PROVEN']}
                chosen=next(state for state,count in pending.items() if count>0)
                page.get_by_label('静态分类',exact=True).select_option(chosen);page.get_by_role('button',name='搜索',exact=True).click();expect(page.locator('.activity')).to_have_count(0)
            page.locator('.symbol').first.click();expect(page.locator('.activity')).to_have_count(0)
            position=get('/scans/'+scan_id+'/position');symbol=position['symbol_id']
            assert symbol not in seen and symbol not in old_symbols;seen.add(symbol)
            page.get_by_label('依据 / 修改或撤销理由',exact=True).fill('v32第四批容量验收：完整保留原3000事件并继续，暂无法确认，不作风险或安全证明')
            moment=time.monotonic();page.get_by_role('button',name='暂无法确认',exact=True).click()
            expect(page.get_by_role('status').filter(has_text='已保存')).to_be_visible(timeout=30000)
            expect(page.locator('.activity')).to_have_count(0);latencies.append(time.monotonic()-moment)
            with closing(sqlite3.connect(reviews.resolve().as_uri()+'?mode=ro',uri=True)) as c:assert c.execute('SELECT count(*) FROM events').fetchone()[0]==3001+index
            receipt.update(completed=index+1,seconds=time.monotonic()-start);save()
            if (index+1)%50==0:print('New batch committed '+str(index+1)+'; total events '+str(3001+index),flush=True)
            if index+1 in {350,700,1000}:
                path=output/('upgrade-batch-'+str(index+1)+'.png');page.screenshot(path=str(path),full_page=True);receipt['screenshots'].append(str(path))
                context.tracing.stop(path=str(output/('trace-'+str(index+1)+'.zip')));context.tracing.start(screenshots=False,snapshots=True,sources=True)
                expected_position=get('/scans/'+scan_id+'/position')
                page.close();server.terminate();server.wait(timeout=30);log.close();server=log=None
                page,get=open_service(index+1);receipt['tests'].append(dict(name='restart_after_new_'+str(index+1),status='PASS',total_events=3001+index));save()
        after=events(reviews);assert len(after)==4000 and [e for e in after if e['event_id'] in old_ids]==old
        new=[e for e in after if e['event_id'] not in old_ids];assert len(new)==1000 and all(e['decision']=='NEED_MORE_EVIDENCE' for e in new)
        assert {e['symbol_id'] for e in new}==seen
        receipt.update(state='VERIFYING_STATIC_GRAPH_AND_HISTORY');save()
        assert before==(graph.stat().st_size,graph.stat().st_mtime_ns) and file_hash(graph)==expected_sha
        assert not receipt['page_errors'] and not receipt['external_requests']
        ordered=sorted(latencies)
        receipt.update(passed=True,state='COMPLETE',events=4000,old_events_preserved=3000,new_distinct_symbols=1000,static_unchanged=True,
            save_seconds=dict(median=ordered[499],p95=ordered[949],maximum=ordered[-1]),seconds=time.monotonic()-start)
    except BaseException:
        receipt.update(state='FAILED',error=traceback.format_exc())
        if context and context.pages:
            try:context.pages[-1].screenshot(path=str(output/'failure.png'),full_page=True)
            except Exception:pass
        raise
    finally:
        if context:
            try:context.tracing.stop(path=str(output/'final-trace.zip'))
            finally:context.close()
        if browser:browser.close()
        if playwright:playwright.stop()
        if server:server.terminate();server.wait(timeout=30)
        if log:log.close()
        save();print(json.dumps(dict(passed=receipt['passed'],state=receipt['state'],completed=receipt['completed'])),flush=True)
    return 0 if receipt['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
