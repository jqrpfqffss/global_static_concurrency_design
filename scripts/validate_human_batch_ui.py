"""Real Chrome 1000-item review/resume on a byte copy of a real native graph.

The approved original INAV comparison graph is never modified. This is a UI
capacity/restart check, not a new native scan, candidate G1, physical-PC or UAT.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback
import urllib.request

TOOL=Path(__file__).resolve().parents[1];sys.path.insert(0,str(TOOL))
from ecra.common import write_json
from ecra.scan_store import EvidenceProvider
from ecra.human_reviews import ReviewStore
from ecra.workspace import no_links,studio_data_root


def file_hash(path):
    h=hashlib.sha256()
    with path.open('rb') as s:
        for part in iter(lambda:s.read(1024**2),b''):h.update(part)
    return h.hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['graph','work','evidence','engine','python']:parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--count',type=int,default=1000)
    args=parser.parse_args()
    if args.count<1000:parser.error('U16 requires at least1000 distinct native objects')
    graph=no_links(args.graph.resolve());work=studio_data_root(args.work.resolve());output=no_links(args.evidence.resolve())
    if work==graph.parent or work.is_relative_to(graph.parent) or graph.is_relative_to(work):raise ValueError('Validation cannot overlap the original graph')
    work.mkdir(parents=True,exist_ok=False);output.mkdir(parents=True,exist_ok=False)
    (work/'controller.py').write_bytes(Path(__file__).read_bytes())
    receipt=dict(passed=False,scope=__doc__,requested=args.count,completed=0,tests=[],screenshots=[],page_errors=[],external_requests=[],native_dpi='NOT_VERIFIED',engineer_uat='NOT_VERIFIED',physical_second_computer='NOT_VERIFIED',source=str(graph),state='COPYING')
    def save():write_json(output/'acceptance.json',receipt)
    save();server=log=browser=context=playwright=None
    source_before=(graph.stat().st_size,graph.stat().st_mtime_ns)
    binding=EvidenceProvider(graph).metadata()
    if binding['facts_hash']!='9da30821f449de364352f533134d80e731e031f44bbe69ec86d8f287ac12b6c2':raise ValueError('Requires the approved complete original INAV graph')
    if shutil.disk_usage(work).free<source_before[0]+32*1024**3:raise OSError('Need graph copy plus32GiB safety space')
    data=work/'data';scan=data/'scans'/binding['scan_id'];scan.mkdir(parents=True)
    write_json(scan/'storage.json',dict(version=1,scan_id=binding['scan_id'],project_id=binding['project_id'],profile_id=binding['profile_id']))
    target=scan/'scan.db';copied=0;digest=hashlib.sha256();start=time.monotonic()
    try:
        with graph.open('rb') as src,target.open('xb') as dst:
            for part in iter(lambda:src.read(1024**2),b''):
                dst.write(part);digest.update(part);copied+=len(part)
                if copied%(1024**3)==0:
                    receipt.update(copied_bytes=copied,seconds=time.monotonic()-start);save();print('Copied '+str(copied)+' bytes',flush=True)
            dst.flush();os.fsync(dst.fileno())
        assert source_before==(graph.stat().st_size,graph.stat().st_mtime_ns)
        copied_hash=digest.hexdigest();assert file_hash(target)==copied_hash
        provider=EvidenceProvider(target);assert provider.metadata()==binding
        store=ReviewStore(scan/'reviews.db',binding)
        assert store.history()==[]
        write_json(scan/'manifest.json',dict(format='ECRA_VALIDATION_NATIVE_GRAPH_COPY',version=1,**binding,
            warning='Independent byte copy of approved original INAV graph for U16 UI validation; not a standard imported package or new candidate scan'))
        counts=provider.counts();chosen=max(['UNKNOWN','SUSPECT'],key=lambda k:counts.get(k,0))
        if counts.get(chosen,0)<args.count:raise ValueError('Approved native graph lacks1000 targets in one risk class')
        receipt.update(state='BROWSER',static_sha256=copied_hash,native_counts=counts,classification=chosen,graph_bytes=copied,source_copy_verified=True);save()
        from playwright.sync_api import sync_playwright,expect
        playwright=sync_playwright().start();browser=playwright.chromium.launch(channel='chrome',headless=True)
        context=browser.new_context(viewport=dict(width=1366,height=768));context.tracing.start(screenshots=False,snapshots=True,sources=True)
        port_count=0
        def open_service():
            nonlocal server,log,port_count
            port_count+=1;session=work/('session-'+str(port_count)+'.json');log=(work/('server-'+str(port_count)+'.log')).open('wb')
            server=subprocess.Popen([str(args.python),'-B','-X','utf8','-m','ecra.studio','--data-root',str(data),'--no-browser','--session-file',str(session)],cwd=args.engine,env=dict(os.environ,PYTHONIOENCODING='utf-8'),stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            deadline=time.monotonic()+60
            while not session.exists():
                if server.poll() is not None or time.monotonic()>deadline:raise RuntimeError('Studio did not start')
                time.sleep(.1)
            info=json.loads(session.read_text('utf-8'));base='http://'+info['authority']
            while True:
                try:urllib.request.urlopen(urllib.request.Request(base+'/api/bootstrap',headers={'x-ecra-session':info['token']}),timeout=2).close();break
                except OSError:
                    if time.monotonic()>deadline:raise
                    time.sleep(.1)
            page=context.new_page();page.on('pageerror',lambda e:receipt['page_errors'].append(str(e)))
            page.on('request',lambda r:receipt['external_requests'].append(r.url) if not r.url.startswith(base) else None)
            page.goto(info['url']);page.get_by_role('link',name='人工确认',exact=True).click()
            page.get_by_role('button',name='继续上次位置',exact=True).click()
            expect(page.locator('.activity')).to_have_count(0,timeout=60000)
            page.get_by_label('静态分类',exact=True).select_option(chosen)
            page.get_by_label('人工状态',exact=True).select_option('PENDING')
            expect(page.locator('.activity')).to_have_count(0)
            return page
        page=open_service();saved=set()
        for i in range(args.count):
            page.locator('.symbol').first.click();expect(page.locator('.activity')).to_have_count(0,timeout=30000)
            symbol=page.locator('.detail-summary>.identity').inner_text().strip()
            assert symbol and symbol not in saved
            page.get_by_label('确认者',exact=True).fill('U16自动化容量验收声明')
            page.get_by_label('依据 / 修改或撤销理由',exact=True).fill('原生归档第'+str(i+1)+'项容量与重启验证；仅暂无法确认，不作安全证明。')
            page.get_by_role('button',name='暂无法确认',exact=True).click()
            expect(page.locator('.conclusion')).to_contain_text('暂无法确认',timeout=30000)
            expect(page.locator('.activity')).to_have_count(0,timeout=30000)
            saved.add(symbol);receipt['completed']=i+1
            if (i+1)%50==0:
                assert len(store.history())==i+1
                save();print('Confirmed '+str(i+1)+' distinct native objects',flush=True)
            if i+1 in {350,700,args.count}:
                image=output/('batch-'+str(i+1)+'.png');page.screenshot(path=str(image),full_page=True);receipt['screenshots'].append(str(image))
                context.tracing.stop(path=str(output/('trace-'+str(i+1)+'.zip')));context.tracing.start(screenshots=False,snapshots=True,sources=True)
                page.close();server.terminate();server.wait(timeout=30);log.close();server=log=None
                page=open_service();assert len(store.history())==i+1
                receipt['tests'].append(dict(name='actual_service_restart_after_'+str(i+1),status='PASS',events=i+1))
        events=store.history();assert len(events)==args.count and len({e['symbol_id'] for e in events})==args.count
        assert all(e['decision']=='NEED_MORE_EVIDENCE' for e in events)
        receipt.update(state='VERIFYING_ORIGINALS');save()
        assert source_before==(graph.stat().st_size,graph.stat().st_mtime_ns)
        assert file_hash(graph)==copied_hash and file_hash(target)==copied_hash
        assert not receipt['page_errors'] and not receipt['external_requests']
        receipt.update(passed=True,state='COMPLETE',original_unchanged=True,static_unchanged=True,events=len(events),distinct_native_symbols=len(saved),seconds=time.monotonic()-start)
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


if __name__=='__main__':main()
