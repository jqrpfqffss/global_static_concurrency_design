"""Real archived F030 coverage UI; not full U14/UAT or large-project certification."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

TOOL=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(TOOL))
from ecra.report_package import import_report,sha256
from ecra.studio.coverage import CoverageService
from ecra.human_reviews import ReviewStore
from ecra.scan_store import EvidenceProvider


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package',type=Path,required=True)
    parser.add_argument('--work',type=Path,required=True)
    parser.add_argument('--evidence',type=Path,required=True)
    args=parser.parse_args()
    work=args.work.resolve();work.mkdir(parents=True,exist_ok=False)
    output=args.evidence.resolve();output.mkdir(parents=True,exist_ok=False)
    imported=import_report(args.package.resolve(),work/'data')
    scan_id=imported['scan_id'];scan=work/'data/scans'/scan_id
    provider=EvidenceProvider(scan/'scan.db');query=CoverageService(scan/'scan.db')
    stats=query.summary();original=sha256(scan/'scan.db')
    receipt=dict(passed=False,scope=__doc__,tests=[],page_errors=[],external_requests=[],scan_id=scan_id,
        static_sha256=original,package_sha256=sha256(args.package),archived_status=stats,
        physical_second_machine='NOT_VERIFIED',native_windows_dpi='NOT_VERIFIED',independent_engineer_uat='NOT_VERIFIED')
    session=work/'session.json';log=(work/'server.log').open('w',encoding='utf-8')
    server=subprocess.Popen([sys.executable,'-B','-m','ecra.studio','--data-root',str(work/'data'),
        '--no-browser','--session-file',str(session)],cwd=TOOL,stdout=log,stderr=subprocess.STDOUT,
        env=dict(os.environ,PYTHONIOENCODING='utf-8'),creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    try:
        deadline=time.monotonic()+40
        while not session.exists():
            if server.poll() is not None or time.monotonic()>deadline:raise RuntimeError('Studio startup failed; see server.log')
            time.sleep(.1)
        info=json.loads(session.read_text(encoding='utf-8'));base='http://'+info['authority']
        from playwright.sync_api import sync_playwright,expect
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='chrome',headless=True)
            context=browser.new_context(viewport=dict(width=1600,height=900),record_video_dir=str(output/'video'))
            context.tracing.start(screenshots=True,snapshots=True,sources=True)
            page=context.new_page();responses=[]
            page.on('pageerror',lambda e:receipt['page_errors'].append(str(e)))
            page.on('request',lambda r:receipt['external_requests'].append(r.url) if not r.url.startswith(base) else None)
            page.on('response',lambda r:responses.append(r) if r.url.startswith(base+'/api/') else None)
            def idle():
                expect(page.get_by_text('正在读取覆盖证据…',exact=True)).to_have_count(0)
                expect(page.locator('.activity')).to_have_count(0)
                expect(page.get_by_role('alert')).to_have_count(0)
            def shot(name):
                idle();page.screenshot(path=str(output/(name+'.png')),full_page=True)
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            try:
                page.goto(info['url']);expect(page.get_by_role('heading',name='先处理需要核实的变量')).to_be_visible()
                page.get_by_role('link',name='覆盖与诊断',exact=True).click()
                expect(page.get_by_role('heading',name='本次归档的覆盖状态')).to_be_visible();idle()
                status=page.get_by_role('region',name='覆盖状态')
                expect(status).to_contain_text('TU记录 '+str(stats['tu_records']))
                expect(status).to_contain_text('缺口记录 '+str(stats['unknown_records']))
                expect(page.locator('.coverage-table tbody tr')).to_have_count(query.blockers()['total'])
                assert {r['raw']:r['count'] for r in stats['tu_statuses']}==dict(PARSED=2,PARTIAL=2), 'This acceptance expects the frozen parsed F030 golden'
                receipt['tests'].append('native_archive_counts_and_partial_status_match_sql')
                page.locator('.coverage-table tbody tr').first.get_by_role('button',name='查看完整证据').click()
                current=page.get_by_role('region',name='当前覆盖证据')
                expect(current.get_by_role('heading',name='归档关联身份（5）')).to_be_visible();idle()
                target=query.related(query.blockers()['items'][0]['node'])['items'][0]
                assert target['available']
                current.get_by_role('button',name='打开关联变量').first.click()
                expect(page.locator('.detail-heading h2')).to_have_text(target['symbol']['name']);idle()
                expect(page.locator('.symbol')).to_have_count(1)
                expect(page.get_by_text('精确定位：'+target['symbol_id'],exact=False)).to_be_visible()
                position=ReviewStore(scan/'reviews.db',provider.metadata()).position('workbench')
                assert position['symbol_id']==target['symbol_id'] and position['extra']['symbol_id']==target['symbol_id']
                page.get_by_role('button',name='返回覆盖诊断',exact=True).click()
                expect(page.get_by_role('region',name='当前覆盖证据')).to_be_visible();idle()
                page.reload();expect(page.get_by_role('region',name='当前覆盖证据')).to_be_visible();idle()
                shot('01-blocker-return-and-reopen')
                receipt['tests'].append('canonical_identity_drill_return_and_reopen_selected_evidence')
                page.get_by_role('tab',name='解析/别名/硬件记录',exact=True).click();idle()
                page.get_by_role('button',name='指针解引用 · 58条 / 0个直接对象 / 58条无匹配身份',exact=True).click();idle()
                expect(page.locator('.coverage-table tbody tr')).to_have_count(50)
                page.get_by_role('button',name='下一页记录',exact=True).click();idle()
                expect(page.locator('.coverage-table tbody tr')).to_have_count(8)
                expect(page.get_by_text('匹配 58 项；显示 51–58。空列表不构成安全证明。',exact=True)).to_be_visible()
                page.reload();expect(page.locator('.coverage-table tbody tr')).to_have_count(8);idle()
                assert ReviewStore(scan/'reviews.db',provider.metadata()).position('coverage')['offsets']['issues']==50
                page.locator('.coverage-table tbody tr').first.get_by_role('button',name='查看完整证据').click();idle()
                expect(page.get_by_text('该记录未提供关联身份；不能解释为无影响。',exact=True)).to_be_visible()
                shot('02-unknown-group-page-and-unbound-record')
                receipt['tests'].append('group_counts_server_paging_and_reopened_offset_no_zero_impact_inference')
                page.get_by_role('tab',name='编译单元',exact=True).click();idle()
                expect(page.locator('.coverage-table tbody tr')).to_have_count(4)
                parsed=next(r for r in stats['tu_statuses'] if r['raw']=='PARSED')
                page.get_by_label('TU解析状态',exact=True).select_option(str(parsed['node']));idle()
                expect(page.locator('.coverage-table tbody tr')).to_have_count(2)
                page.get_by_label('源文件包含',exact=True).fill('utils.c')
                page.get_by_role('button',name='筛选编译单元',exact=True).click();idle()
                expect(page.locator('.coverage-table tbody tr')).to_have_count(1)
                page.get_by_label('仅零归档关联对象TU',exact=True).check();idle()
                expect(page.locator('.coverage-table tbody tr')).to_have_count(1)
                page.locator('.coverage-table tbody tr').first.get_by_role('button',name='查看完整证据').click();idle()
                current=page.get_by_role('region',name='当前覆盖证据')
                current.get_by_role('button',name='查看归档位置代码',exact=True).click()
                expect(current.locator('.source-code code').first).not_to_be_empty()
                original_command=current.locator('details.evidence-node').filter(has=page.locator('summary',has_text='原始真实编译命令')).first
                original_command.locator(':scope > summary').click();expect(original_command).to_contain_text('arm-none-eabi-gcc')
                raw=current.locator('details.evidence-node').filter(has=page.locator('summary',has_text='当前记录的全部字段与证明')).first
                raw.locator(':scope > summary').click();expect(raw).to_contain_text('utils.c')
                shot('03-tu-filter-and-original-command-evidence')
                receipt['tests'].append('all_tus_parsed_file_zero_object_filters_original_commands_and_archived_source')
                page.get_by_role('tab',name='构建与范围',exact=True).click();idle()
                closure=page.locator('details.evidence-node').filter(has=page.locator('summary',has_text='真实构建闭包')).first
                closure.locator(':scope > summary').click();expect(closure).to_contain_text('compile_database')
                shot('04-real-build-closure')
                receipt['tests'].append('real_build_scope_evidence_available_without_full_fact_restore')
                for width,height,name in [(1366,768,'05-layout-1366'),(960,640,'06-layout-960')]:
                    page.set_viewport_size(dict(width=width,height=height));shot(name)
                receipt['tests'].append('three_viewports_no_horizontal_page_overflow_not_windows_dpi')
                assert sha256(scan/'scan.db')==original
                payloads=[dict(path=r.url[len(base):],bytes=len(r.body())) for r in responses]
                receipt['max_api_response_bytes']=max(row['bytes'] for row in payloads)
                assert receipt['max_api_response_bytes']<512*1024
                assert not receipt['page_errors'] and not receipt['external_requests']
                receipt.update(passed=True,api_payloads=payloads)
                receipt['tests']+=['immutable_static_database_hash','bounded_real_api_no_page_errors_or_external_requests']
            except BaseException:
                page.screenshot(path=str(output/'failure.png'),full_page=True);raise
            finally:
                context.tracing.stop(path=str(output/'trace.zip'));context.close();browser.close()
    except BaseException as exc:
        receipt.update(error=str(exc),traceback=traceback.format_exc());raise
    finally:
        server.terminate();server.wait(timeout=20);log.close()
        (output/'acceptance.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(passed=receipt['passed'],tests=len(receipt['tests']),max_api_response_bytes=receipt['max_api_response_bytes'])))


if __name__=='__main__':main()
