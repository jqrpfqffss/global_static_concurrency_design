"""Actual two-origin Chrome collaboration on two isolated local data roots.

Uses a real existing native archive and real packaged servers. All mutations
use visible GUI controls; database reads independently check immutable events.
This is one physical host, not second-machine/offline-environment acceptance.
"""
import argparse
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback
import urllib.parse
import urllib.request

TOOL=Path(__file__).resolve().parents[1];sys.path.insert(0,str(TOOL))
from ecra.report_package import export_report,sha256
from ecra.scan_store import EvidenceProvider
from ecra.human_reviews import ReviewStore


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['scan','engine','python','work','evidence']:parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();work=args.work.resolve();work.mkdir(parents=True,exist_ok=False)
    output=args.evidence.resolve();output.mkdir(parents=True,exist_ok=False)
    source=args.scan.resolve();before={p.relative_to(source).as_posix():sha256(p) for p in source.rglob('*') if p.is_file()}
    staging=work/'input-copy';shutil.copytree(source,staging)
    provider=EvidenceProvider(staging/'scan.db');binding=provider.metadata();scan_id=binding['scan_id']
    assert ReviewStore(staging/'reviews.db',binding).history()==[],'Use a native archive without existing human decisions'
    item=provider.symbols(search='HCLK',limit=50)['items'];assert len(item)==1
    symbol=item[0]['symbol_id'];fingerprint=provider.fingerprint(symbol);static_sha=sha256(staging/'scan.db')
    initial=work/'base.ecra-report';export_report(staging,initial)
    receipt=dict(passed=False,scope=__doc__,tests=[],page_errors=[],external_requests=[],screenshots=[],
        engine=str(args.engine.resolve()),server_python=str(args.python.resolve()),scan_id=scan_id,symbol_id=symbol,
        physical_second_computer='NOT_VERIFIED',clean_offline_machine='NOT_VERIFIED',independent_engineer_uat='NOT_VERIFIED')
    servers=[];logs=[];contexts=[];pages=[];browser=None
    try:
        for device in ['A','B']:
            folder=work/device;folder.mkdir();session=folder/'session.json';log=(folder/'server.log').open('w',encoding='utf-8');logs.append(log)
            server=subprocess.Popen([str(args.python.resolve()),'-B','-m','ecra.studio','--data-root',str(folder/'data'),
                '--no-browser','--session-file',str(session)],cwd=args.engine.resolve(),stdout=log,stderr=subprocess.STDOUT,
                env=dict(os.environ,PYTHONIOENCODING='utf-8'),creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            servers.append(server);deadline=time.monotonic()+60
            while not session.exists():
                if server.poll() is not None or time.monotonic()>deadline:raise RuntimeError('Server '+device+' did not start')
                time.sleep(.1)
            info=json.loads(session.read_text(encoding='utf-8'))
            while True:
                try:
                    urllib.request.urlopen(urllib.request.Request('http://'+info['authority']+'/api/bootstrap',headers={'X-ECRA-Session':info['token']}),timeout=1).close();break
                except OSError:
                    if server.poll() is not None or time.monotonic()>deadline:raise
                    time.sleep(.1)
        from playwright.sync_api import sync_playwright,expect
        with sync_playwright() as pw:
            browser=pw.chromium.launch(channel='chrome',headless=True)
            for device in ['A','B']:
                info=json.loads((work/device/'session.json').read_text(encoding='utf-8'))
                context=browser.new_context(viewport=dict(width=1600,height=900),record_video_dir=str(output/device/'video'))
                contexts.append(context);context.tracing.start(screenshots=True,snapshots=True,sources=True)
                page=context.new_page();pages.append(page);page.on('pageerror',lambda error:receipt['page_errors'].append(str(error)))
                page.on('request',lambda request:receipt['external_requests'].append(request.url) if urllib.parse.urlsplit(request.url).scheme in {'http','https'} and urllib.parse.urlsplit(request.url).hostname not in {'127.0.0.1','localhost'} else None)
                page.goto(info['url'])
                expect(page.get_by_role('heading',name='开始使用 ECRA Studio',exact=True)).to_be_visible()
            a,b=pages
            def imported(page,path,delta=False):
                device=['A','B'][pages.index(page)]
                old=len(store(device).history()) if (work/device/'data/scans'/scan_id/'reviews.db').is_file() else 0
                page.get_by_role('link',name='数据与共享',exact=True).click()
                control=page.get_by_label('选择 .ecra-review-delta' if delta else '选择 .ecra-report',exact=True)
                with page.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/delta/import' if delta else '/api/import'),timeout=120000) as response:
                    control.set_input_files(str(path))
                assert response.value.status==200,response.value.status
                expect(page.locator('.activity')).to_have_count(0,timeout=120000)
                notice=page.get_by_role('status').filter(has_text='导入已提交')
                expect(notice).to_be_visible(timeout=120000)
                count=int(re.search(r'新增人工事件 (\d+)',notice.inner_text()).group(1))
                assert len(store(device).history())-old==count
                return dict(imported_events=count)
            def opened(page):
                page.get_by_role('link',name='变量与风险',exact=True).click()
                page.get_by_label('查找变量、文件或规范身份',exact=True).fill(symbol)
                page.get_by_role('button',name='搜索',exact=True).click()
                expect(page.locator('.symbol')).to_have_count(1);page.locator('.symbol').click()
                expect(page.locator('.detail-heading h2')).to_have_text('HCLK')
            def saved(page,reviewer,comment,button):
                page.get_by_label('确认者',exact=True).fill(reviewer)
                page.get_by_label('依据 / 修改或撤销理由',exact=True).fill(comment)
                with page.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/human')) as response:
                    page.get_by_role('button',name=button,exact=True).click()
                assert response.value.status==200,response.value.text()
                expect(page.get_by_role('status').filter(has_text='已保存')).to_be_visible()
            def downloaded(page,name,filename):
                page.get_by_role('link',name='数据与共享',exact=True).click()
                with page.expect_download(timeout=120000) as download:page.get_by_role('button',name=name,exact=True).click()
                target=work/filename;download.value.save_as(str(target));assert target.is_file();return target
            def store(device):return ReviewStore(work/device/'data/scans'/scan_id/'reviews.db',binding)
            def shot(page,name):
                path=output/(name+'.png');page.screenshot(path=str(path),full_page=True);receipt['screenshots'].append(str(path))
            static_copies={}
            for device,page in zip(['A','B'],pages):
                imported(page,initial);opened(page)
                static_copies[device]=sha256(work/device/'data/scans'/scan_id/'scan.db')
            receipt['tests'].append(dict(name='two_real_servers_import_same_native_archive',status='PASS',related=['U19','U20'],limitation='Two isolated roots/origins on one physical host'))
            saved(a,'电脑A工程师','初始归档核对；仅用于协作流程验收','确认有风险')
            delta0=downloaded(a,'导出人工确认增量','initial.ecra-review-delta')
            assert imported(b,delta0,True)['imported_events']==1
            assert imported(b,delta0,True)['imported_events']==0
            opened(a);opened(b)
            receipt['tests'].append(dict(name='gui_delta_propagation_and_repeat_import_are_idempotent',status='PASS',related=['U20']))
            saved(a,'电脑A工程师','电脑A：核对归档路径后提出无风险结论；协议测试','确认无风险')
            saved(b,'电脑B工程师','电脑B：NVIC 证据仍缺失，要求继续核实；协议测试','暂无法确认')
            delta_b=downloaded(b,'导出人工确认增量','B.ecra-review-delta')
            assert imported(a,delta_b,True)['imported_events']==1
            opened(a);state=store('A').current(symbol,fingerprint);assert state['conflict'] and len(state['heads'])==2
            assert len(store('A').history())==3
            expect(a.locator('.review-controls')).to_contain_text('离线并行确认冲突')
            a.get_by_role('tab',name='人工历史',exact=True).click()
            history=a.locator('.history-event');expect(history).to_have_count(3)
            expect(a.locator('.detail-group').filter(has=history.first)).to_contain_text('电脑A：核对归档路径')
            expect(a.locator('.detail-group').filter(has=history.first)).to_contain_text('电脑B：NVIC 证据仍缺失')
            assert len({row['device'] for row in state['heads']})==2
            shot(a,'01-both-device-conflicts-visible')
            receipt['tests'].append(dict(name='parallel_gui_decisions_keep_both_branch_sources_and_history',status='PASS',related=['U20']))
            a.get_by_label('依据 / 修改或撤销理由',exact=True).fill('')
            with a.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/human')) as rejected:
                a.get_by_role('button',name='确认有风险',exact=True).click()
            assert rejected.value.status==400,rejected.value.text()
            expect(a.get_by_role('alert')).to_contain_text('解决冲突必须填写依据')
            assert len(store('A').history())==3 and store('A').current(symbol,fingerprint)['conflict']
            receipt['tests'].append(dict(name='missing_resolution_reason_is_rejected_without_changing_heads',status='PASS',related=['U20','H4']))
            old_heads={row['event_id'] for row in state['heads']}
            saved(a,'联合核对声明工程师','已核对两台电脑的原始事件、来源与归档证据；保留待补实测依据','暂无法确认')
            merged=store('A').current(symbol,fingerprint)
            assert not merged['conflict'] and set(merged['heads'][0]['parents'])==old_heads
            assert len(store('A').history())==4
            shot(a,'02-explicit-resolution-retains-history')
            receipt['tests'].append(dict(name='explicit_gui_resolution_adds_event_with_every_branch_parent',status='PASS',related=['U20']))
            full=downloaded(a,'导出标准完整包','resolved.ecra-report')
            assert imported(b,full)['imported_events']==2
            opened(b);expect(b.locator('.conclusion')).to_contain_text('暂无法确认')
            events=lambda device:{row['event_id']:row for row in store(device).history()}
            assert events('A')==events('B') and len(events('B'))==4
            b.reload();expect(b.get_by_role('heading',name='变量与风险',exact=True)).to_be_visible();opened(b)
            b.get_by_role('tab',name='人工历史',exact=True).click();expect(b.locator('.history-event')).to_have_count(4)
            shot(b,'03-imported-full-package-history-after-reopen')
            receipt['tests'].append(dict(name='resolved_full_package_merges_existing_archive_and_survives_reopen',status='PASS',related=['U19','U20']))
            delta_final=downloaded(b,'导出人工确认增量','final.ecra-review-delta')
            assert imported(a,delta_final,True)['imported_events']==0
            for device in ['A','B']:
                db=work/device/'data/scans'/scan_id/'scan.db';EvidenceProvider(db).validate(deep=True)
                assert EvidenceProvider(db).metadata()==binding
                assert sha256(db)==static_copies[device]
            assert before=={p.relative_to(source).as_posix():sha256(p) for p in source.rglob('*') if p.is_file()}
            assert not receipt['page_errors'] and not receipt['external_requests']
            receipt['tests'].append(dict(name='final_delta_idempotent_static_and_original_bytes_unchanged_no_external_requests',status='PASS',related=['U20','H1','H4','H6']))
            receipt.update(passed=True,events=events('A'),source_static_sha256=static_sha,
                imported_static_sha256=static_copies,original_unchanged=True,
                snapshot_scope='SQLite Backup may change physical database header bytes; each imported immutable copy must retain its own initial SHA, full graph validation and exact source binding')
            for device,context in zip(['A','B'],contexts):context.tracing.stop(path=str(output/device/'trace.zip'));context.close()
            contexts=[];browser.close();browser=None
    except BaseException as exc:
        receipt.update(error=str(exc),traceback=traceback.format_exc())
        for index,page in enumerate(pages):
            try:page.screenshot(path=str(output/('failure-'+str(index)+'.png')),full_page=True)
            except Exception:pass
        raise
    finally:
        (output/'acceptance.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
        for server in servers:
            if server.poll() is None:server.terminate();server.wait(timeout=30)
        for log in logs:log.close()
    print(json.dumps(dict(passed=receipt['passed'],tests=len(receipt['tests']))))


if __name__=='__main__':main()
