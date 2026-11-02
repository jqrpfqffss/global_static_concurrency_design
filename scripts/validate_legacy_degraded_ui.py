"""Real Chrome: explicit unverified legacy archive, raw bytes and offline transfer.

An owned copy of the approved native legacy result loses facts.json deliberately.
Original firmware/results are never edited; no native/DPI/physical-second-PC claim.
"""
import argparse
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
from ecra.report_package import sha256
from ecra.scan_store import EvidenceProvider
from ecra.workspace import no_links,studio_data_root


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['source','work','evidence']:parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--engine',type=Path,default=TOOL);parser.add_argument('--python',type=Path,default=Path(sys.executable))
    args=parser.parse_args();original=no_links(args.source.resolve())
    work=studio_data_root(args.work.resolve());work.mkdir(parents=True,exist_ok=False)
    output=no_links(args.evidence.resolve());output.mkdir(parents=True,exist_ok=False)
    (work/'controller.py').write_bytes(Path(__file__).read_bytes())
    def inventory(folder):return {p.relative_to(folder).as_posix():(sha256(p),p.stat().st_size,p.stat().st_mtime_ns) for p in folder.rglob('*') if p.is_file()}
    original_before=inventory(original);source=work/'legacy-source';source.mkdir()
    for name in original_before:
        if name == 'facts.json': continue  # explicit incomplete owned fixture; original stays read-only
        target=source/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(original/name,target)
    root=json.loads((source/'scan_state.json').read_text('utf-8'))['project_root']
    note='000-untrusted-original.html';(source/note).write_text('<script>window.legacyInjected=true</script>\n'+'归档原字节，不能执行。'*2000,'utf-8')
    before=inventory(source);receipt=dict(passed=False,scope=__doc__,tests=[],screenshots=[],page_errors=[],external_requests=[],physical_second_computer='NOT_VERIFIED',native_dpi='NOT_VERIFIED')
    servers=[];browser=context=playwright=None
    def service(name):
        data=work/(name+'-data');session=work/(name+'-session.json');log=(work/(name+'-server.log')).open('wb')
        server=subprocess.Popen([str(args.python),'-B','-X','utf8','-m','ecra.studio','--no-browser','--data-root',str(data),'--session-file',str(session)],
            cwd=args.engine,env=dict(os.environ,PYTHONIOENCODING='utf-8'),stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        servers.append((server,log));deadline=time.monotonic()+60
        while not session.exists():
            if server.poll() is not None or time.monotonic()>deadline:raise RuntimeError('Studio startup failed')
            time.sleep(.1)
        info=json.loads(session.read_text('utf-8'));base='http://'+info['authority']
        while True:
            try:urllib.request.urlopen(urllib.request.Request(base+'/api/bootstrap',headers={'x-ecra-session':info['token']}),timeout=1).close();break
            except OSError:
                if time.monotonic()>deadline:raise
                time.sleep(.1)
        return data,info,base
    try:
        data,info,base=service('original');other,other_info,other_base=service('viewer')
        from playwright.sync_api import sync_playwright,expect
        playwright=sync_playwright().start();browser=playwright.chromium.launch(channel='chrome',headless=True)
        context=browser.new_context(viewport=dict(width=1366,height=768),record_video_dir=str(output/'video'))
        context.tracing.start(screenshots=True,snapshots=True,sources=True)
        def newpage(url,origin):
            page=context.new_page();page.on('pageerror',lambda e:receipt['page_errors'].append(str(e)))
            page.on('request',lambda r:receipt['external_requests'].append(r.url) if not r.url.startswith(origin) else None);page.goto(url);return page
        page=newpage(info['url'],base)
        def shot(name,p=page):
            f=output/(name+'.png');p.screenshot(path=str(f),full_page=True);receipt['screenshots'].append(str(f))
        def passed(name):
            receipt['tests'].append(dict(name=name,status='PASS',related=['U21','U19 subset','U24','H6']))
            (output/'progress.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),'utf-8');print('PASS '+name,flush=True)
        page.get_by_role('button',name='打开示例',exact=True).click();expect(page.get_by_role('heading',name='先处理需要核实的变量',exact=True)).to_be_visible(timeout=60000)
        existing=next(p for p in (data/'scans').iterdir() if (p/'scan.db').is_file());existing_sha=sha256(existing/'scan.db')
        page.get_by_role('link',name='数据与共享',exact=True).click();migration=page.get_by_role('region',name='旧结果只读迁移',exact=True)
        migration.get_by_label('旧结果目录（绝对路径）',exact=True).fill(str(source));migration.get_by_label('旧记录中的原工程目录',exact=True).fill(root)
        migration.get_by_role('button',name='检查旧目录与归属',exact=True).click();expect(migration.get_by_role('alert')).to_contain_text('缺少完整facts.json')
        assert len(list((data/'scans').iterdir()))==1
        passed('strict_default_rejects_missing_facts_and_preserves_existing_archive')
        migration.get_by_role('checkbox',name='证据不全时只保存原文件',exact=False).check()
        migration.get_by_role('button',name='检查旧目录与归属',exact=True).click();expect(migration.get_by_label('旧迁移计划',exact=True)).to_contain_text('未验证原件归档')
        expect(migration.get_by_label('旧迁移计划',exact=True)).to_contain_text('缺少完整facts.json');shot('01-explicit-degraded-plan')
        migration.get_by_role('button',name='开始只读迁移',exact=True).click();expect(migration.get_by_role('button',name='打开迁移结果',exact=True)).to_be_visible(timeout=120000)
        migration.get_by_role('button',name='打开迁移结果',exact=True).click();expect(page.get_by_role('heading',name='查看未验证的旧原件',exact=True)).to_be_visible()
        expect(page.get_by_role('heading',name='未恢复可信静态证据，零可核验对象不等于零风险',exact=True)).to_be_visible()
        expect(page.locator('.cards')).to_have_count(0);expect(page.get_by_role('button',name='继续人工确认',exact=True)).to_have_count(0)
        scan=next(p for p in (data/'scans').iterdir() if p!=existing);provider=EvidenceProvider(scan/'scan.db');binding=provider.validate(deep=True)
        assert binding['state']=='UNVERIFIED' and provider.counts()=={} and provider.load('facts')=={'legacy_archive_only':True}
        static=sha256(scan/'scan.db');passed('explicit_real_ui_migration_publishes_only_unverified_navigation_and_complete_original_bytes')
        archive=page.get_by_role('region',name='旧归档原文件与复核历史',exact=True)
        archive.locator('article').filter(has_text=note).get_by_role('button',name='查看归档片段',exact=True).click()
        expect(archive.locator('.legacy-preview')).to_contain_text('<script>window.legacyInjected=true</script>');assert page.evaluate('window.legacyInjected') is None
        archive.get_by_role('button',name='继续读取下一段',exact=True).click();assert page.evaluate('window.legacyInjected') is None
        shot('02-raw-html-text-only');passed('untrusted_original_html_is_segmented_text_and_never_executed')
        for route in ['变量与风险','人工确认','覆盖与诊断','OpenCode 复核']:
            page.get_by_role('link',name=route,exact=True).click();expect(page.get_by_role('heading',name='未恢复可信静态证据',exact=True)).to_be_visible()
            expect(page.get_by_role('button',name='确认无风险',exact=True)).to_have_count(0)
        denied=page.request.post(base+'/api/scans/'+scan.name+'/human',headers={'x-ecra-session':info['token'],'origin':base},data=dict(symbol_id='invented',reviewer='bad',decision='CONFIRMED_SAFE'))
        assert denied.status==400 and '未验证原件' in denied.json()['error']
        passed('all_static_review_routes_and_backend_reject_invented_safety_conclusions')
        page.get_by_role('link',name='数据与共享',exact=True).click()
        with page.expect_download() as pending:page.get_by_role('button',name='导出标准完整包',exact=True).click()
        package=work/'unverified.ecra-report';pending.value.save_as(package)
        viewer=newpage(other_info['url'],other_base);viewer.get_by_role('link',name='数据与共享',exact=True).click()
        viewer.get_by_label('选择 .ecra-report',exact=True).set_input_files(str(package))
        expect(viewer.get_by_role('status').filter(has_text='导入已提交')).to_be_visible(timeout=120000)
        viewer.get_by_role('link',name='项目概览',exact=True).click();expect(viewer.get_by_role('heading',name='查看未验证的旧原件',exact=True)).to_be_visible()
        imported=other/'scans'/scan.name;other_provider=EvidenceProvider(imported/'scan.db');assert other_provider.roots()==provider.roots()
        for p in (scan/'evidence').iterdir():assert (imported/'evidence'/p.name).read_bytes()==p.read_bytes()
        shot('03-independent-viewer-after-standard-package',viewer)
        passed('standard_package_roundtrip_to_independent_real_service_preserves_every_original_and_unverified_status')
        migration=page.get_by_role('region',name='旧结果只读迁移',exact=True)
        migration.get_by_label('旧结果目录（绝对路径）',exact=True).fill(str(source));migration.get_by_label('旧记录中的原工程目录',exact=True).fill(root)
        migration.get_by_role('checkbox',name='证据不全时只保存原文件',exact=False).check()
        migration.get_by_role('button',name='检查旧目录与归属',exact=True).click();expect(migration.get_by_label('旧迁移计划',exact=True)).to_be_visible()
        migration.get_by_role('button',name='开始只读迁移',exact=True).click();expect(migration.get_by_text('相同来源已导入：打开已有归档，原人工确认保留。',exact=True)).to_be_visible(timeout=120000)
        assert len(list((data/'scans').iterdir()))==2 and sha256(scan/'scan.db')==static and sha256(existing/'scan.db')==existing_sha
        assert before==inventory(source) and original_before==inventory(original)
        assert not receipt['page_errors'] and not receipt['external_requests']
        passed('repeated_degraded_migration_is_idempotent_and_all_originals_and_prior_authority_remain_unchanged')
        receipt.update(passed=True,scan_id=scan.name,original_files=len(original_before),captured_files=len(before),package_sha256=sha256(package),static_sha256=static)
    except BaseException:
        receipt['error']=traceback.format_exc()
        if context:
            try:context.pages[0].screenshot(path=str(output/'failure.png'),full_page=True)
            except Exception:pass
        raise
    finally:
        if context:context.tracing.stop(path=str(output/'trace.zip'));context.close()
        if browser:browser.close()
        if playwright:playwright.stop()
        for server,log in reversed(servers):server.terminate();server.wait(timeout=30);log.close()
        (output/'acceptance.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),'utf-8')
        print(json.dumps(dict(passed=receipt['passed'],tests=len(receipt['tests']),evidence=str(output)),ensure_ascii=False))


if __name__=='__main__':main()
