"""Real Chrome legacy migration with immutable DB and persisted decision checks.

Uses a byte copy of an existing native result. It does not run a new firmware
scan or substitute this conversion for the full U21/large-project gates.
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
from ecra.human_reviews import ReviewStore


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--work',type=Path,required=True)
    parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--engine',type=Path,default=TOOL)
    parser.add_argument('--python',type=Path,default=Path(sys.executable))
    args=parser.parse_args()
    work=args.work.resolve();work.mkdir(parents=True,exist_ok=False)
    output=args.evidence.resolve();output.mkdir(parents=True,exist_ok=False)
    source=work/'legacy-source';source.mkdir()
    original=args.source.resolve()
    old_hashes={str(file.relative_to(original)):sha256(file) for file in original.rglob('*') if file.is_file()}
    for name in old_hashes:
        target=source/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(original/name,target)
    # Deliberate untrusted-content fixture in the owned byte copy only.
    note='000-历史复核说明.txt'
    (source/note).write_text('历史说明 <script>window.legacyInjected=true</script>\n'+'仅查看原字节，不能执行。'*1500,encoding='utf-8')
    root=json.loads((source/'scan_state.json').read_text(encoding='utf-8'))['project_root']
    source_hashes={str(file.relative_to(source)):sha256(file) for file in source.rglob('*') if file.is_file()}
    session=work/'session.json';log=(work/'server.log').open('w',encoding='utf-8')
    receipt=dict(passed=False,scope=__doc__,engine=str(args.engine.resolve()),python=str(args.python.resolve()),
        tests=[],page_errors=[],external_requests=[],native_windows_dpi='NOT_VERIFIED')
    server=subprocess.Popen([str(args.python),'-X','utf8','-B','-m','ecra.studio','--no-browser','--data-root',str(work/'data'),
        '--session-file',str(session)],cwd=args.engine,env=dict(os.environ,PYTHONIOENCODING='utf-8'),
        stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    try:
        deadline=time.monotonic()+40
        while not session.exists():
            if server.poll() is not None or time.monotonic()>deadline:raise RuntimeError('Studio startup failed')
            time.sleep(.1)
        info=json.loads(session.read_text(encoding='utf-8'));base='http://'+info['authority']
        while True:
            try:
                urllib.request.urlopen(urllib.request.Request(base+'/api/bootstrap',headers={'X-ECRA-Session':info['token']}),timeout=1).close();break
            except OSError:
                if time.monotonic()>deadline:raise
                time.sleep(.1)
        from playwright.sync_api import sync_playwright,expect
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='chrome',headless=True)
            context=browser.new_context(viewport=dict(width=1366,height=768),record_video_dir=str(output/'video'))
            context.tracing.start(screenshots=True,snapshots=True,sources=True)
            page=context.new_page()
            page.on('pageerror',lambda e:receipt['page_errors'].append(str(e)))
            page.on('request',lambda r:receipt['external_requests'].append(r.url) if not r.url.startswith(base) else None)
            def shot(name):page.screenshot(path=str(output/(name+'.png')),full_page=True)
            try:
                page.goto(info['url']);expect(page.get_by_role('heading',name='开始使用 ECRA Studio')).to_be_visible()
                page.get_by_role('link',name='数据与共享',exact=True).click()
                migration=page.locator('section[aria-label="旧结果只读迁移"]')
                migration.get_by_label('旧结果目录（绝对路径）',exact=True).fill(str(source))
                migration.get_by_label('旧记录中的原工程目录',exact=True).fill(str(work))
                migration.get_by_role('button',name='检查旧目录与归属',exact=True).click()
                expect(migration.get_by_role('alert')).to_contain_text('归属与所选原工程不一致')
                assert not (work/'data/scans').exists()
                receipt['tests'].append('wrong_owner_is_rejected_without_scan_publication')
                migration.get_by_label('旧记录中的原工程目录',exact=True).fill(root)
                migration.get_by_role('button',name='检查旧目录与归属',exact=True).click()
                expect(migration.get_by_label('旧迁移计划',exact=True)).to_contain_text('归属匹配')
                shot('01-legacy-owner-and-plan')
                migration.get_by_role('button',name='开始只读迁移',exact=True).click()
                expect(migration.get_by_role('button',name='打开迁移结果',exact=True)).to_be_visible(timeout=120000)
                shot('02-legacy-real-conversion-complete')
                migration.get_by_role('button',name='打开迁移结果',exact=True).click()
                expect(page.get_by_role('heading',name='先处理需要核实的变量',exact=True)).to_be_visible()
                expect(page.get_by_role('note')).to_contain_text('旧归档证据模式')
                scans=list((work/'data/scans').iterdir());assert len(scans)==1
                scan=scans[0];provider=EvidenceProvider(scan/'scan.db');store=ReviewStore(scan/'reviews.db',provider.metadata())
                static_hash=sha256(scan/'scan.db')
                receipt['tests'].append('native_legacy_copy_converts_through_real_ui_job')
                page.get_by_role('button',name='无法判断 '+str(provider.counts()['UNKNOWN']),exact=True).click()
                page.get_by_label('查找变量、文件或规范身份',exact=True).fill('HCLK')
                page.get_by_role('button',name='搜索',exact=True).click()
                expect(page.locator('.symbol')).to_have_count(1);page.locator('.symbol').click()
                expect(page.locator('.detail-heading h2')).to_have_text('HCLK')
                page.get_by_label('确认者',exact=True).fill('迁移验收声明')
                page.get_by_label('依据 / 修改或撤销理由',exact=True).fill('验证旧归档中的新人工事件持久化，不作为原生安全结论')
                page.get_by_role('button',name='暂无法确认',exact=True).click()
                expect(page.locator('.conclusion')).to_contain_text('暂无法确认')
                symbol=provider.symbols(search='HCLK')['items'][0]['symbol_id']
                assert store.current(symbol,provider.fingerprint(symbol))['decision']=='NEED_MORE_EVIDENCE'
                page.reload();page.get_by_role('link',name='人工确认',exact=True).click()
                page.get_by_role('button',name='继续上次位置',exact=True).click()
                expect(page.locator('.detail-heading h2')).to_have_text('HCLK')
                expect(page.locator('.conclusion')).to_contain_text('暂无法确认')
                shot('03-legacy-confirmation-reopened')
                receipt['tests'].append('converted_archive_decision_and_position_survive_reopen')
                page.get_by_role('link',name='数据与共享',exact=True).click()
                archive=page.locator('section[aria-label="旧归档原文件与复核历史"]')
                archive.locator('article').filter(has_text=note).get_by_role('button',name='查看归档片段',exact=True).click()
                expect(archive.locator('.legacy-preview')).to_contain_text('<script>window.legacyInjected=true</script>')
                assert page.evaluate('window.legacyInjected') is None
                archive.get_by_role('button',name='继续读取下一段',exact=True).click()
                expect(archive.get_by_text('UTF-8文本',exact=False)).to_be_visible()
                assert page.evaluate('window.legacyInjected') is None
                shot('04-legacy-opaque-audit-segments')
                receipt['tests'].append('opaque_original_audits_paginate_without_script_execution')
                migration.get_by_label('旧结果目录（绝对路径）',exact=True).fill(str(source))
                migration.get_by_label('旧记录中的原工程目录',exact=True).fill(root)
                migration.get_by_role('button',name='检查旧目录与归属',exact=True).click()
                expect(migration.get_by_label('旧迁移计划',exact=True)).to_be_visible()
                migration.get_by_role('button',name='开始只读迁移',exact=True).click()
                expect(migration.get_by_text('相同来源已导入：打开已有归档，原人工确认保留。',exact=True)).to_be_visible(timeout=120000)
                assert len(list((work/'data/scans').iterdir()))==1
                assert len(store.history(symbol))==1 and sha256(scan/'scan.db')==static_hash
                assert source_hashes=={str(f.relative_to(source)):sha256(f) for f in source.rglob('*') if f.is_file()}
                receipt['tests'].append('repeat_ui_migration_retains_static_db_and_existing_human_event')
                # A damaged private source is a real conversion failure; the
                # previously published archive must remain readable unchanged.
                (source/'facts.json').write_text('{"variables":[',encoding='utf-8')
                migration.get_by_role('button',name='检查旧目录与归属',exact=True).click()
                expect(migration.get_by_label('旧迁移计划',exact=True)).to_be_visible()
                migration.get_by_role('button',name='开始只读迁移',exact=True).click()
                expect(migration.get_by_role('alert')).to_be_visible(timeout=120000)
                expect(migration.get_by_label('旧迁移执行状态',exact=True)).to_contain_text('迁移失败')
                assert len(list((work/'data/scans').iterdir()))==1
                assert sha256(scan/'scan.db')==static_hash and len(store.history(symbol))==1
                shot('05-legacy-damaged-input-preserves-valid-result')
                receipt['tests'].append('failed_conversion_does_not_damage_valid_result_or_human_history')
                assert old_hashes=={str(f.relative_to(original)):sha256(f) for f in original.rglob('*') if f.is_file()}
                assert not receipt['page_errors'] and not receipt['external_requests']
                receipt.update(passed=True,scan_id=scan.name,static_sha256=static_hash,original_preserved=True,
                    human_events=len(store.history(symbol)),related_scenarios=['U21 partial','U16 partial','U24 partial'])
            except BaseException:
                shot('failure');raise
            finally:
                context.tracing.stop(path=str(output/'trace.zip'));context.close();browser.close()
    except BaseException as exc:
        receipt.update(error=str(exc),traceback=traceback.format_exc());raise
    finally:
        server.terminate();server.wait(timeout=20);log.close()
        (output/'acceptance.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(passed=receipt['passed'],tests=receipt['tests'],scan_id=receipt['scan_id']),ensure_ascii=False))


if __name__=='__main__':main()
