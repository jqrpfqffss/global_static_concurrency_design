"""Actual Chrome on a verified publication-only F030 combination.

Requires the independently compared private case receipt. This is not a new
multicore native scan, physical second computer, Windows DPI or engineer UAT.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time
import traceback


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['case','engine','python','work','evidence']:parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--expected-existing-events',type=int,default=0)
    args=parser.parse_args();sys.path.insert(0,str(args.engine))
    from ecra.workspace import studio_data_root,no_links
    from ecra.scan_store import EvidenceProvider
    from ecra.report_package import sha256,import_report
    from ecra.human_reviews import ReviewStore
    from ecra.studio.process_budget import ProcessBudget
    from ecra.studio.write_guard import OwnedProcess
    case=json.loads((args.case/'acceptance.json').read_text('utf-8'));assert case['passed'] and case['all_inputs_unchanged']
    data=studio_data_root(args.case/'data');scan=no_links(case['publication']['scan_path'])
    assert scan.parent==data/'scans' and scan.is_dir()
    manifest=json.loads((scan/'manifest.json').read_text('utf-8'))
    assert manifest['derivation']=='LINKED_MULTICORE_COMBINATION' and manifest['source_reverification'] is False
    work=studio_data_root(args.work);work.mkdir(exist_ok=False,parents=True)
    output=no_links(args.evidence);output.mkdir(exist_ok=False,parents=True)
    (work/'controller.py').write_bytes(Path(__file__).read_bytes())
    runtime_files=[path for path in (args.engine/'ecra').rglob('*') if path.is_file()
                   and (path.suffix=='.py' or 'web' in path.relative_to(args.engine/'ecra').parts)]
    runtime_before={path.relative_to(args.engine).as_posix():sha256(path) for path in runtime_files}
    result=dict(passed=False,scope=__doc__,tests=[],screenshots=[],page_errors=[],external_requests=[],
        engine=str(args.engine),static_sha256=sha256(scan/'scan.db'),case_receipt_sha256=sha256(args.case/'acceptance.json'),
        source_package_snapshot_sha256=sha256(args.engine/'SOURCE-SNAPSHOT.json') if (args.engine/'SOURCE-SNAPSHOT.json').is_file() else None,
        all_gates_passed=False)
    provider=EvidenceProvider(scan/'scan.db');binding=provider.metadata();reviews=ReviewStore(scan/'reviews.db',binding)
    previous=reviews.history();assert len(previous)==args.expected_existing_events
    symbol=next(row['symbol_id'] for row in provider.symbols(limit=200)['items'] if row['static_classification'] in {'SUSPECT','UNKNOWN','SAFE_PROVEN'}
                and not reviews.current(row['symbol_id'],provider.fingerprint(row['symbol_id']))['heads'])
    result['existing_events']=len(previous)
    def save():(output/'acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n','utf-8')
    def passed(name):result['tests'].append(dict(name=name,status='PASS'));save()
    def shot(name):
        if name!='failed':expect(page.locator('.activity')).to_have_count(0,timeout=120000)
        target=output/(name+'.png');page.screenshot(path=str(target),full_page=True);result['screenshots'].append(str(target));save()
    process=budget=log=playwright=browser=context=page=None;start=time.monotonic();save()
    try:
        session=work/'session.json';log=(work/'server.log').open('xb');budget=ProcessBudget(2*1024**3)
        command=[str(args.python),'-B','-X','utf8','-m','ecra.studio','--data-root',str(data),'--no-browser','--session-file',str(session)]
        process=OwnedProcess(command,cwd=args.engine,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',LOCALAPPDATA=str(work/'user')),log=log)
        budget.assign(process);process.resume();deadline=time.monotonic()+90
        while not session.is_file():
            if process.poll() is not None or time.monotonic()>deadline:raise RuntimeError('Private real Studio service startup failed; log retained')
            time.sleep(.1)
        info=json.loads(session.read_text('utf-8'));origin='http://'+info['authority']
        from playwright.sync_api import sync_playwright,expect
        playwright=sync_playwright().start();browser=playwright.chromium.launch(channel='chrome',headless=True)
        context=browser.new_context(viewport=dict(width=1366,height=768),accept_downloads=True)
        context.tracing.start(screenshots=True,snapshots=True,sources=True);page=context.new_page()
        page.on('pageerror',lambda error:result['page_errors'].append(str(error)))
        page.on('request',lambda request:result['external_requests'].append(request.url) if request.url.startswith(('http:','https:')) and not request.url.startswith(origin+'/') else None)
        page.goto(info['url']);expect(page.locator('.activity')).to_have_count(0,timeout=120000)
        expect(page.get_by_role('note').filter(has_text='派生结果证据模式：')).to_be_visible(timeout=120000)
        page.get_by_role('link',name='变量与风险',exact=True).click()
        search=page.get_by_label('查找变量、文件或规范身份',exact=True);search.fill(symbol);search.press('Enter')
        expect(page.locator('.symbol')).to_have_count(1,timeout=120000);page.locator('.symbol').click()
        expect(page.locator('.detail-summary .identity')).to_have_text(symbol,timeout=120000)
        shot('01-derived-canonical-object-real-workbench');passed('real_published_derived_scan_and_exact_canonical_object_open')
        page.get_by_label('确认者',exact=True).fill('派生发布操作验收 · 用户声明')
        page.get_by_label('依据 / 修改或撤销理由',exact=True).fill('发布和人工记录链路验收；暂无法确认，不代表新的原生扫描或目标板结论。')
        page.get_by_role('button',name='暂无法确认',exact=True).click()
        expect(page.locator('.detail-summary')).to_contain_text('暂无法确认',timeout=120000)
        assert len(reviews.history())==len(previous)+1 and all(event in reviews.history() for event in previous)
        assert reviews.current(symbol,provider.fingerprint(symbol))['decision']=='NEED_MORE_EVIDENCE'
        shot('02-real-human-declaration');passed('real_button_commits_one_separate_human_event')
        page.reload();expect(page.locator('.activity')).to_have_count(0,timeout=120000)
        page.get_by_role('link',name='人工确认',exact=True).click()
        page.get_by_role('button',name='继续上次位置',exact=True).click()
        expect(page.locator('.detail-summary .identity')).to_have_text(symbol,timeout=120000)
        expect(page.locator('.detail-summary')).to_contain_text('暂无法确认',timeout=120000)
        assert not (scan/'scan_state.json').exists();passed('reload_restores_selection_and_human_state_without_source_reverification_capability')
        page.get_by_role('link',name='数据与共享',exact=True).click()
        with page.expect_download(timeout=180000) as operation:page.get_by_role('button',name='导出标准完整包',exact=True).click()
        download=operation.value;target=work/'browser-export.ecra-report';download.save_as(target)
        assert download.failure() is None and download.url.startswith(origin+'/export-download/')
        assert sha256(target)==sha256(data/'exports'/download.suggested_filename)
        restored=import_report(target,work/'independent-data');dest=work/'independent-data/scans'/restored['scan_id']
        assert EvidenceProvider(dest/'scan.db').metadata()==binding
        assert ReviewStore(dest/'reviews.db',binding).history()==reviews.history()
        result.update(archive_sha256=sha256(target),archive_bytes=target.stat().st_size,symbol_id=symbol)
        shot('03-actual-complete-browser-export');passed('native_browser_download_and_strict_complete_import_keep_full_roots_and_human_event')
        assert sha256(scan/'scan.db')==result['static_sha256'] and not result['page_errors'] and not result['external_requests']
        assert runtime_before=={path.relative_to(args.engine).as_posix():sha256(path) for path in runtime_files}
        result.update(passed=True,static_unchanged=True,runtime_files=len(runtime_before),runtime_files_unchanged=True,
                      runtime_hashes=runtime_before,seconds=time.monotonic()-start);save()
    except BaseException:
        result.update(error=traceback.format_exc(),seconds=time.monotonic()-start);save()
        if page is not None:
            try:shot('failed')
            except Exception:pass
        raise
    finally:
        if context is not None:
            try:context.tracing.stop(path=str(output/'trace.zip'))
            finally:context.close()
        if browser is not None:browser.close()
        if playwright is not None:playwright.stop()
        if budget is not None:budget.close()
        if process is not None:
            try:process.wait(timeout=30)
            finally:process.close()
        if log is not None:log.close()
    print(json.dumps(dict(passed=result['passed'],tests=len(result['tests']))),flush=True)


if __name__=='__main__':main()
