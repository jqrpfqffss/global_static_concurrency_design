"""Real Chrome native downloads, complete archives and human-event round trips.

Uses the approved F030 archive plus a clearly declared64MiB unreferenced CAS
transport fixture. This is not an additional native firmware scan, INAV/G4,
physical second-PC, native Windows DPI or a multi-GiB transport measurement.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import traceback
import zipfile
import urllib.parse
import urllib.request


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['engine','python','package','work','evidence']:p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--compression-acceptance',action='store_true')
    args=p.parse_args();sys.path.insert(0,str(args.engine))
    from ecra.workspace import no_links,studio_data_root
    from ecra.report_package import import_report,import_delta,sha256
    from ecra.scan_store import EvidenceProvider
    from ecra.human_reviews import ReviewStore
    from ecra.studio.process_budget import ProcessBudget
    from ecra.studio.write_guard import OwnedProcess
    work=studio_data_root(args.work);work.mkdir(parents=True,exist_ok=False)
    output=no_links(args.evidence);output.mkdir(parents=True,exist_ok=False)
    (work/'controller.py').write_bytes(Path(__file__).read_bytes())
    result=dict(passed=False,tests=[],screenshots=[],page_errors=[],external_requests=[],scope=__doc__,
        native_windows_dpi='NOT_VERIFIED',physical_second_computer='NOT_VERIFIED',engineer_uat='NOT_VERIFIED',
        large_INAV_package='NOT_VERIFIED',native_download_requests=0,native_download_events=0,ticket_requests=0)
    def save():(output/'acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n','utf-8')
    def passed(name):result['tests'].append(dict(name=name,status='PASS'));save()
    save();process=budget=log=playwright=browser=context=page=None
    try:
        package_before=sha256(args.package);data=work/'data';imported=import_report(args.package,data)
        scan=data/'scans'/imported['scan_id'];provider=EvidenceProvider(scan/'scan.db');binding=provider.metadata()
        static_before=sha256(scan/'scan.db');reviews=ReviewStore(scan/'reviews.db',binding)
        previous=reviews.history();symbol=next(row['symbol_id'] for row in provider.symbols(limit=200)['items']
            if not reviews.current(row['symbol_id'],provider.fingerprint(row['symbol_id']))['heads'])
        # No analysis fact is altered. An unreachable, valid CAS object grows
        # transport bytes only; its artificial purpose is recorded explicitly.
        payload=work/'transport-payload';digest=hashlib.sha256();block=os.urandom(1024**2)
        with payload.open('xb') as stream:
            for _ in range(64):stream.write(block);digest.update(block)
            stream.flush();os.fsync(stream.fileno())
        payload_hash=digest.hexdigest();cas=scan/'evidence'/payload_hash;cas.parent.mkdir(exist_ok=True);os.rename(payload,cas)
        result.update(scan_id=imported['scan_id'],symbol_id=symbol,binding=binding,source_package_sha256=package_before,
            static_sha256_before=static_before,transport_fixture=dict(bytes=64*1024**2,sha256=payload_hash,kind='DECLARED_UNREFERENCED_RANDOM_CAS_NOT_FIRMWARE_EVIDENCE'))
        save();session=work/'session.json';windows=Path(os.environ.get('SystemRoot','C:/Windows'))
        env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',LOCALAPPDATA=str(work/'user'),PATH=str(windows/'System32')+os.pathsep+str(windows))
        command=[str(args.python),'-B','-X','utf8','-m','ecra.studio','--data-root',str(data),'--no-browser','--session-file',str(session)]
        result['command']=command;save();log=(work/'server.log').open('xb');budget=ProcessBudget(2*1024**3)
        process=OwnedProcess(command,cwd=args.engine,env=env,log=log);budget.assign(process);process.resume()
        deadline=time.monotonic()+60
        while not session.is_file():
            if process.poll() is not None or time.monotonic()>deadline:raise RuntimeError('Real local service did not start; private log retained')
            time.sleep(.1)
        info=json.loads(session.read_text('utf-8'));origin='http://'+info['authority']
        def api(path):
            request=urllib.request.Request(origin+'/api'+path,headers={'X-ECRA-Session':info['token']})
            with urllib.request.urlopen(request,timeout=120) as response:return json.load(response)
        while True:
            try:api('/bootstrap');break
            except OSError:
                if time.monotonic()>deadline:raise
                time.sleep(.1)
        from playwright.sync_api import sync_playwright,expect
        playwright=sync_playwright().start();browser=playwright.chromium.launch(channel='chrome',headless=True)
        context=browser.new_context(viewport=dict(width=1600,height=900),accept_downloads=True)
        context.add_init_script("""window.__wholeFileBlobCalls=0;
          Response.prototype.blob=function(){window.__wholeFileBlobCalls++;throw Error('Whole-file Response.blob is forbidden in this acceptance');};
          URL.createObjectURL=function(){window.__wholeFileBlobCalls++;throw Error('Whole-file object URL is forbidden in this acceptance');};""")
        context.tracing.start(screenshots=True,snapshots=True,sources=True);page=context.new_page()
        page.on('pageerror',lambda error:result['page_errors'].append(str(error)))
        def request_seen(request):
            if request.url.startswith(('http:','https:')) and not request.url.startswith(origin+'/'):result['external_requests'].append(request.url)
            path=urllib.parse.urlsplit(request.url).path
            if path.startswith('/export-download/'):result['native_download_requests']+=1
            if path.startswith('/api/download/') and path.endswith('/ticket'):result['ticket_requests']+=1
        page.on('request',request_seen)
        def shot(name):
            file=output/(name+'.png');page.screenshot(path=str(file),full_page=True);result['screenshots'].append(str(file));save()
        page.goto(info['url']);expect(page.locator('.activity')).to_have_count(0,timeout=120000)
        page.get_by_role('link',name='变量与风险',exact=True).click()
        search=page.get_by_label('查找变量、文件或规范身份',exact=True);search.fill(symbol);search.press('Enter')
        expect(page.locator('.symbol')).to_have_count(1,timeout=120000);page.locator('.symbol').click()
        expect(page.locator('.detail-summary .identity')).to_have_text(symbol,timeout=120000)
        page.get_by_label('确认者',exact=True).fill('原生下载验收 · 用户声明')
        page.get_by_label('依据 / 修改或撤销理由',exact=True).fill('实际浏览器保存，核对下载完整包与增量事件；不是新的硬件结论。')
        page.get_by_role('button',name='确认有风险',exact=True).click()
        expect(page.locator('.detail-summary')).to_contain_text('人工确认有风险',timeout=120000)
        events=reviews.history();assert len(events)==len(previous)+1
        assert all(event in events for event in previous);event=reviews.current(symbol,provider.fingerprint(symbol))['heads'][0]
        passed('real_gui_human_event_saved_without_changing_static_authority')
        page.get_by_role('link',name='数据与共享',exact=True).click();expect(page.locator('.activity')).to_have_count(0,timeout=120000)
        if args.compression_acceptance:
            page.get_by_label('完整包压缩',exact=True).select_option('compact')
        with page.expect_download(timeout=180000) as operation:page.get_by_role('button',name='导出标准完整包',exact=True).click()
        downloaded=operation.value;target=work/'downloaded-full.ecra-report';downloaded.save_as(target)
        assert downloaded.failure() is None
        assert downloaded.url.startswith(origin+'/export-download/')
        result['native_download_events']+=1
        exported=data/'exports'/downloaded.suggested_filename
        assert target.stat().st_size>64*1024**2 and sha256(target)==sha256(exported)
        assert page.evaluate('window.__wholeFileBlobCalls')==0 and result['native_download_events']==result['ticket_requests']==1
        result.update(full_archive_bytes=target.stat().st_size,full_archive_sha256=sha256(target),browser_blob_calls=0)
        shot('01-real-complete-native-browser-download');passed('real64MiB_complete_archive_native_download_matches_server_bytes_without_blob_or_object_url')
        destination=work/'independent-viewer-data';restored=import_report(target,destination)
        restored_scan=destination/'scans'/restored['scan_id'];restored_provider=EvidenceProvider(restored_scan/'scan.db')
        assert restored_provider.metadata()==binding and sha256(restored_scan/'evidence'/payload_hash)==payload_hash
        assert ReviewStore(restored_scan/'reviews.db',binding).history()==events
        passed('complete_download_strictly_imports_same_authority_all_cas_bytes_and_human_events_into_independent_root')
        if args.compression_acceptance:
            def complete_payload_hashes(path):
                hashes={}
                with zipfile.ZipFile(path) as zipped:
                    for entry in zipped.infolist():
                        digest=hashlib.sha256()
                        with zipped.open(entry) as stream:
                            while chunk:=stream.read(1024**2):digest.update(chunk)
                        hashes[entry.filename]=digest.hexdigest()
                return hashes
            with zipfile.ZipFile(target) as zipped:assert zipped.getinfo('scan.db').compress_type==zipfile.ZIP_BZIP2
            page.get_by_label('完整包压缩',exact=True).select_option('deflate')
            with page.expect_download(timeout=180000) as operation:page.get_by_role('button',name='导出标准完整包',exact=True).click()
            fast_download=operation.value;fast=work/'downloaded-fast.ecra-report';fast_download.save_as(fast)
            assert fast_download.failure() is None and fast_download.url.startswith(origin+'/export-download/')
            assert sha256(fast)==sha256(data/'exports'/fast_download.suggested_filename)
            result['native_download_events']+=1
            with zipfile.ZipFile(fast) as zipped:assert zipped.getinfo('scan.db').compress_type==zipfile.ZIP_DEFLATED
            assert complete_payload_hashes(target)==complete_payload_hashes(fast)
            fast_root=work/'fast-independent-viewer-data';fast_import=import_report(fast,fast_root)
            fast_scan=fast_root/'scans'/fast_import['scan_id']
            assert EvidenceProvider(fast_scan/'scan.db').metadata()==binding and ReviewStore(fast_scan/'reviews.db',binding).history()==events
            result['complete_archive_encodings']=dict(compact_bytes=target.stat().st_size,fast_bytes=fast.stat().st_size,
                fast_sha256=sha256(fast),all_uncompressed_payloads_identical=True)
            shot('01b-real-full-package-compression-choice');passed('real_gui_compact_and_fast_keep_every_complete_payload_and_human_event')
        with page.expect_download(timeout=120000) as operation:page.get_by_role('button',name='导出人工确认增量',exact=True).click()
        downloaded=operation.value;delta=work/'downloaded.ecra-review-delta';downloaded.save_as(delta)
        assert downloaded.failure() is None and sha256(delta)==sha256(data/'exports'/downloaded.suggested_filename)
        assert downloaded.url.startswith(origin+'/export-download/');result['native_download_events']+=1
        assert import_delta(delta,restored_scan)['imported_events']==0
        assert page.evaluate('window.__wholeFileBlobCalls')==0 and result['native_download_events']==result['ticket_requests']==(3 if args.compression_acceptance else 2)
        shot('02-real-review-delta-native-download');passed('review_delta_native_download_is_byte_exact_and_reimport_remains_idempotent')
        result.update(static_sha256_after=sha256(scan/'scan.db'),source_package_sha256_after=sha256(args.package),human_events_after=len(reviews.history()))
        result['passed']=len(result['tests'])==(5 if args.compression_acceptance else 4) and result['static_sha256_after']==static_before and result['source_package_sha256_after']==package_before and not result['external_requests'] and not result['page_errors']
        save();return 0 if result['passed'] else 1
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
        if budget:budget.close()
        if process:process.wait(timeout=30);process.close()
        if log:log.close()


if __name__=='__main__':raise SystemExit(main())
