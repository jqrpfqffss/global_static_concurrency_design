"""Real browser pagination capacity, with explicit synthetic storage fixtures.

This is not a native firmware scan, semantic golden, G2, G3 or G4 result.
Every operation uses the production server, database and human-review APIs.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

TOOL=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(TOOL))
from ecra.scan_store import publish_scan,EvidenceProvider
from ecra.human_reviews import ReviewStore
from ecra.report_package import sha256


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work',type=Path,required=True)
    parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--engine',type=Path,default=TOOL)
    parser.add_argument('--python',type=Path,default=Path(sys.executable))
    args=parser.parse_args()
    work=args.work.resolve();work.mkdir(parents=True,exist_ok=False)
    output=args.evidence.resolve();output.mkdir(parents=True,exist_ok=False)
    scan=work/'data/scans/capacity-fixture';scan.mkdir(parents=True)
    count=20007
    facts=dict(variables=[dict(symbol_id='CAPACITY-'+str(i),name='capacity_counter_'+str(i),
        static_classification='UNKNOWN',definition_file='CAPACITY_TEST_ONLY.c',definition_line=i+1,
        analysis_coverage='UNKNOWN') for i in range(count)])
    publish_scan(scan/'scan.db',facts,dict(findings=[]),scan_id=scan.name,project_id='SYNTHETIC_CAPACITY_TEST_ONLY',
                 provenance=dict(scope='Synthetic capacity fixture, no native extraction or risk classification.'))
    provider=EvidenceProvider(scan/'scan.db');store=ReviewStore(scan/'reviews.db',provider.metadata())
    original=sha256(scan/'scan.db');del facts
    session=work/'session.json'
    log=(work/'server.log').open('w',encoding='utf-8')
    receipt=dict(passed=False,scope=__doc__,rows=count,engine=str(args.engine),tests=[],page_errors=[],external_requests=[])
    server=subprocess.Popen([str(args.python),'-B','-m','ecra.studio','--data-root',str(work/'data'),
        '--no-browser','--session-file',str(session)],cwd=args.engine,stdout=log,stderr=subprocess.STDOUT,
        env=dict(os.environ,PYTHONIOENCODING='utf-8'),creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    try:
        deadline=time.monotonic()+40
        while not session.is_file():
            if server.poll() is not None or time.monotonic()>deadline:raise RuntimeError('Studio startup failed; see server.log')
            time.sleep(.1)
        info=json.loads(session.read_text(encoding='utf-8'));base='http://'+info['authority']
        from playwright.sync_api import sync_playwright,expect
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='chrome',headless=True)
            context=browser.new_context(viewport=dict(width=1366,height=768),record_video_dir=str(output/'video'))
            context.tracing.start(screenshots=True,snapshots=True,sources=True)
            page=context.new_page();responses=[]
            page.on('pageerror',lambda e:receipt['page_errors'].append(str(e)))
            page.on('response',lambda r:responses.append(r) if r.url.startswith(base+'/api/') else None)
            page.on('request',lambda r:receipt['external_requests'].append(r.url) if not r.url.startswith(base) else None)
            try:
                started=time.monotonic();page.goto(info['url'])
                expect(page.get_by_role('heading',name='先处理需要核实的变量',exact=True)).to_be_visible(timeout=30000)
                receipt['overview_seconds']=time.monotonic()-started
                page.get_by_role('button',name='无法判断 20007',exact=True).click()
                expect(page.locator('.symbol')).to_have_count(50)
                expect(page.get_by_text('匹配 20007 项；显示 1–50',exact=True)).to_be_visible()
                for expected in ('51–100','101–150'):
                    page.get_by_role('button',name='下一页',exact=True).click()
                    expect(page.get_by_text('匹配 20007 项；显示 '+expected,exact=True)).to_be_visible()
                    expect(page.locator('.symbol')).to_have_count(50)
                started=time.monotonic()
                page.get_by_label('查找变量、文件或规范身份',exact=True).fill('capacity_counter_20006')
                page.get_by_role('button',name='搜索',exact=True).click()
                expect(page.locator('.symbol')).to_have_count(1)
                page.locator('.symbol').click()
                expect(page.locator('.detail-heading h2')).to_have_text('capacity_counter_20006')
                receipt['last_identity_lookup_seconds']=time.monotonic()-started
                page.get_by_label('确认者',exact=True).fill('容量测试自动化声明')
                page.get_by_label('依据 / 修改或撤销理由',exact=True).fill('仅验证20007行容量及持久化；不作为任何固件风险判断')
                page.get_by_role('button',name='暂无法确认',exact=True).click()
                expect(page.locator('.conclusion')).to_contain_text('暂无法确认')
                page.reload()
                page.get_by_role('link',name='人工确认',exact=True).click()
                page.get_by_role('button',name='继续上次位置',exact=True).click()
                expect(page.locator('.detail-heading h2')).to_have_text('capacity_counter_20006')
                expect(page.locator('.conclusion')).to_contain_text('暂无法确认')
                assert store.current('CAPACITY-20006',provider.fingerprint('CAPACITY-20006'))['decision']=='NEED_MORE_EVIDENCE'
                assert sha256(scan/'scan.db')==original
                payloads=[]
                for response in responses:
                    raw=response.body();payloads.append(dict(path=response.url[len(base):],bytes=len(raw)))
                    if '/symbols?' in response.url:assert len(json.loads(raw)['items'])<=50
                receipt['max_api_response_bytes']=max(row['bytes'] for row in payloads)
                assert receipt['max_api_response_bytes']<512*1024
                assert not receipt['page_errors'] and not receipt['external_requests']
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.screenshot(path=str(output/'20007-real-server-pagination.png'),full_page=True)
                receipt.update(passed=True,tests=['20007_rows_real_server_pages','exact_last_identity_search',
                    'human_commit_and_reopen_position','bounded_api_responses','immutable_static_hash'],api_payloads=payloads,static_sha256=original)
            except BaseException:
                page.screenshot(path=str(output/'failure.png'),full_page=True);raise
            finally:
                context.tracing.stop(path=str(output/'trace.zip'));context.close();browser.close()
    except BaseException as exc:
        receipt.update(error=str(exc),traceback=traceback.format_exc());raise
    finally:
        server.terminate();server.wait(timeout=20);log.close()
        (output/'acceptance.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({key:receipt[key] for key in ('passed','rows','max_api_response_bytes','overview_seconds','last_identity_lookup_seconds')}))


if __name__=='__main__':main()
