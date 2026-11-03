"""Real Chrome catalog operations using existing approved native scan archives.

No invented scan identities, dates, analysis fields or human events. Copies of
previously completed native archives are isolated from the originals. One
explicit corrupt database is a negative fixture, not a simulated scan result.
This is not new native/G1/G2/physical second-PC/DPI/UAT acceptance.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time
import traceback
import urllib.request
import urllib.parse
import zipfile


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['archive-list','work','evidence']:parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--engine',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--python',type=Path,default=Path(sys.executable))
    parser.add_argument('--comparison-acceptance',action='store_true',help='Also exercise real archived canonical-object comparison and both evidence entries')
    args=parser.parse_args()
    sys.path.insert(0,str(args.engine))
    from ecra.report_package import sha256, snapshot, import_report, import_delta
    from ecra.scan_store import EvidenceProvider
    from ecra.scan_identity import query
    from ecra.workspace import no_links, studio_data_root
    engine_files=[p for p in (args.engine/'ecra').rglob('*') if p.is_file() and p.suffix!='.pyc' and '__pycache__' not in p.parts]
    engine_hashes={p:sha256(p) for p in engine_files}
    work=studio_data_root(args.work);work.mkdir(parents=True,exist_ok=False)
    output=no_links(args.evidence);output.mkdir(parents=True,exist_ok=False)
    (work/'controller.py').write_bytes(Path(__file__).read_bytes())
    archives=json.loads(args.archive_list.read_text('utf-8'))['directories']
    assert len(archives)>20 and len(archives)==len(set(archives))
    data=work/'data';originals={};bindings={};identities={};dates={};source_rows=[]
    def archived_files(folder):
        files=[no_links(folder/name) for name in ['scan.db','reviews.db','manifest.json']]
        objects=no_links(folder/'evidence')
        if objects.exists():files.extend(no_links(p) for p in objects.iterdir() if p.is_file())
        return files
    def events(folder):
        with closing(sqlite3.connect((folder/'reviews.db').resolve().as_uri()+'?mode=ro',uri=True)) as conn:
            return list(conn.execute('SELECT event_id,payload FROM events ORDER BY event_id'))
    for value in archives:
        source=no_links(value);manifest=json.loads((source/'manifest.json').read_text('utf-8'))
        assert manifest['format']=='ECRA_LOCAL_SCAN' and manifest['state']=='STATIC_VALIDATED'
        provider=EvidenceProvider(source/'scan.db');binding=provider.metadata();sid=binding['scan_id']
        assert source.name==sid and sid not in bindings
        bindings[sid]=binding;identities[sid]=query(provider)
        dates[sid]=datetime.fromisoformat(manifest['completed_at']).astimezone(timezone.utc).date().isoformat()
        files=archived_files(source);originals.update({p:(sha256(p),p.stat().st_size,p.stat().st_mtime_ns) for p in files})
        target=no_links(data/'scans'/sid);target.mkdir(parents=True)
        shutil.copyfile(source/'scan.db',target/'scan.db')
        snapshot(source/'reviews.db',target/'reviews.db')
        shutil.copyfile(source/'manifest.json',target/'manifest.json')
        if (source/'evidence').exists():shutil.copytree(source/'evidence',target/'evidence')
        assert events(source)==events(target) and sha256(source/'scan.db')==sha256(target/'scan.db')
        source_rows.append(dict(source=str(source),scan_id=sid,scan_sha256=sha256(source/'scan.db'),events=len(events(source))))
    immutable={p:sha256(p) for p in data.glob('scans/*/scan.db')}
    session=work/'session.json';log=(work/'server.log').open('xb')
    server=subprocess.Popen([str(args.python),'-B','-X','utf8','-m','ecra.studio','--data-root',str(data),'--no-browser','--session-file',str(session)],
        cwd=args.engine,env=dict(os.environ,PYTHONIOENCODING='utf-8'),stdout=log,stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    result=dict(passed=False,scope=__doc__,engine=str(args.engine),python=str(args.python),tests=[],screenshots=[],page_errors=[],external_requests=[],
                source_archives=source_rows,native_DPI='NOT_VERIFIED',engineer_UAT='NOT_VERIFIED',physical_second_PC='NOT_VERIFIED')
    def save():(output/'acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n','utf-8')
    browser=context=playwright=None
    try:
        deadline=time.monotonic()+60
        while not session.exists():
            if server.poll() is not None or time.monotonic()>deadline:raise RuntimeError('Actual service failed before session startup')
            time.sleep(.05)
        info=json.loads(session.read_text('utf-8'));base='http://'+info['authority']
        def api(path):
            req=urllib.request.Request(base+'/api'+path,headers={'X-ECRA-Session':info['token']})
            with urllib.request.urlopen(req,timeout=30) as response:return json.load(response)
        while True:
            try:api('/bootstrap');break
            except OSError:
                if time.monotonic()>deadline:raise
                time.sleep(.05)
        from playwright.sync_api import sync_playwright,expect
        playwright=sync_playwright().start();browser=playwright.chromium.launch(channel='chrome',headless=True)
        context=browser.new_context(viewport=dict(width=1600,height=900),accept_downloads=True)
        context.tracing.start(screenshots=True,snapshots=True,sources=True);page=context.new_page()
        page.on('pageerror',lambda e:result['page_errors'].append(str(e)))
        page.on('request',lambda r:result['external_requests'].append(r.url) if r.url.startswith(('http:','https:')) and not r.url.startswith(base+'/') else None)
        def passed(name):result['tests'].append(dict(name=name,status='PASS'));save()
        def shot(name):
            photo=output/(name+'.png');page.screenshot(path=str(photo),full_page=True);result['screenshots'].append(str(photo));save()
        def button(name):return page.get_by_role('button',name=name,exact=True)
        def ready():expect(button('查询历史')).to_be_enabled(timeout=30000)
        def advanced():
            details=page.locator('.history-advanced')
            if details.get_attribute('open') is None:details.locator('summary').click()
        def count(total,rows):
            expect(page.locator('.history-count')).to_contain_text('匹配 '+str(total)+' 个归档',timeout=30000)
            expect(page.locator('.history-row')).to_have_count(rows)
        page.goto(info['url']);expect(page.locator('.activity')).to_have_count(0,timeout=30000)
        broken=data/'scans/zz-invalid-history';broken.mkdir();(broken/'scan.db').write_bytes(b'explicit corrupt negative fixture')
        page.get_by_role('link',name='历史与对比',exact=True).click();count(24,20);ready()
        page_ids=[row.get_attribute('aria-label').removeprefix('归档 ') for row in page.locator('.history-row').all()]
        actual=api('/history?limit=100');assert {i['scan_id'] for i in actual['items']}==set(bindings)|{'zz-invalid-history'}
        assert all(i['mode']=='LOCAL_SNAPSHOT' for i in actual['items'] if i['can_open'])
        shot('01-real-native-archives-page-one');passed('actual23_native_archive_identity_set_and_server_pagination')
        button('下一页').click();count(24,4);ready();page.reload();count(24,4);ready()
        assert page.locator('.history-count').inner_text().find('显示 21–24')>=0
        shot('02-reopened-page-two');passed('page_offset_survives_actual_browser_reload_during_parent_bootstrap')
        button('清空筛选').click();count(24,20);ready()
        chosen=next(sid for sid in page_ids if sid not in page.locator('.header-scan').inner_text())
        project=bindings[chosen]['project_id'];profile=bindings[chosen]['profile_id'];day=dates[chosen]
        page.get_by_label('工程名称 / ID',exact=True).fill(project)
        page.get_by_label('配置 / 目标 / 变体',exact=True).fill(profile)
        advanced()
        page.get_by_label('历史扫描模式',exact=True).select_option('FULL')
        page.get_by_label('归档发布状态',exact=True).select_option('STATIC_VALIDATED')
        page.get_by_label('开始日期（UTC）',exact=True).fill(day);page.get_by_label('结束日期（UTC）',exact=True).fill(day)
        expected={sid for sid,b in bindings.items() if project in b['project_id'] and profile in '\n'.join(str(x or '') for x in [b['profile_id'],identities[sid]['configured_target'],identities[sid]['build_variant']]) and dates[sid]==day}
        button('查询历史').click();count(len(expected),min(len(expected),20));ready();assert chosen in expected
        page.reload();count(len(expected),min(len(expected),20));ready();expect(page.get_by_label('配置 / 目标 / 变体',exact=True)).to_have_value(profile)
        shot('03-composite-query-keeps-archived-identity');passed('real_project_profile_fullmode_publishstate_UTC_day_and_filter_reopen')
        page.get_by_label('核心声明',exact=True).fill('此原配置没有此核心声明');button('查询历史').click();count(0,0);ready()
        expect(page.get_by_text('没有匹配归档。',exact=False)).to_be_visible();shot('04-empty-explicit-no-safety-claim')
        passed('missing_core_is_not_invented_and_empty_filter_has_recovery_action')
        button('清空筛选').click();count(24,20);ready()
        row=page.get_by_role('article',name='归档 '+chosen,exact=True)
        with page.expect_download() as transfer:row.get_by_role('button',name='导出标准完整包',exact=True).click()
        package=output/'selected-archive.ecra-report';transfer.value.save_as(str(package));ready()
        with zipfile.ZipFile(package) as z:assert json.loads(z.read('manifest.json'))['scan_id']==chosen
        imported=import_report(package,work/'roundtrip');assert imported['scan_id']==chosen
        assert EvidenceProvider(work/'roundtrip/scans'/chosen/'scan.db').metadata()==bindings[chosen]
        assert events(data/'scans'/chosen)==events(work/'roundtrip/scans'/chosen)
        with page.expect_download() as transfer:row.get_by_role('button',name='导出人工确认增量',exact=True).click()
        delta=output/'selected-confirmations.ecra-review-delta';transfer.value.save_as(str(delta));ready()
        assert json.loads(delta.read_text('utf-8'))['binding']['scan_id']==chosen
        import_delta(delta,work/'roundtrip/scans'/chosen)
        assert events(data/'scans'/chosen)==events(work/'roundtrip/scans'/chosen)
        shot('05-row-specific-export-preserves-current-other-header');passed('row_specific_complete_and_delta_exports_roundtrip_exact_binding_and_all_events')
        row.get_by_role('button',name='继续人工确认',exact=True).click()
        expect(page.get_by_role('heading',name='人工确认工作台',exact=True)).to_be_visible(timeout=30000)
        expect(page.locator('.header-scan')).to_contain_text(chosen);expect(page.locator('.activity')).to_have_count(0,timeout=30000)
        shot('06-row-specific-continue-confirmation');passed('continue_action_opens_selected_history_not_previous_header_scan')
        page.get_by_role('link',name='历史与对比',exact=True).click();count(24,20);ready()
        advanced()
        page.get_by_label('归档发布状态',exact=True).select_option('FAILED');button('查询历史').click();count(1,1);ready()
        broken_row=page.get_by_role('article',name='归档 zz-invalid-history',exact=True)
        expect(broken_row).to_contain_text('读取失败');expect(broken_row.get_by_role('button',name='打开结果',exact=True)).to_be_disabled()
        expect(broken_row.get_by_role('button',name='导出标准完整包',exact=True)).to_be_disabled()
        shot('07-corrupt-archive-kept-with-diagnostic');passed('one_corrupt_archive_visible_and_does_not_hide23_valid_archives')
        button('清空筛选').click();count(24,20);ready();page.set_viewport_size(dict(width=1366,height=768))
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        expect(button('查询历史')).to_be_in_viewport();expect(page.get_by_label('工程名称 / ID',exact=True)).to_be_in_viewport()
        expect(button('下一页')).to_be_in_viewport()
        assert page.locator('.history-records').evaluate('(e)=>e.scrollHeight>e.clientHeight')
        shot('08-history-1366-controls');passed('1366_real_browser_query_controls_and_no_horizontal_overflow')
        if args.comparison_acceptance:
            from collections import defaultdict
            grouped=defaultdict(list)
            for sid,binding in bindings.items():grouped[binding['project_id']].append(sid)
            pair=next(values[:2] for values in grouped.values() if len(values)>1)
            base_id,current_id=pair
            def archived_symbols(sid):
                with closing(sqlite3.connect((data/'scans'/sid/'scan.db').resolve().as_uri()+'?mode=ro',uri=True)) as conn:
                    return {sid:(name,digest,classification) for sid,name,digest,classification in conn.execute('SELECT s.symbol_id,s.name,n.hash,s.static_classification FROM symbols s JOIN nodes n ON n.id=s.node')}
            base_symbols,current_symbols=archived_symbols(base_id),archived_symbols(current_id)
            common_ids=base_symbols.keys()&current_symbols.keys();assert common_ids
            same_roots=all(bindings[base_id][key]==bindings[current_id][key] for key in ['facts_hash','report_hash'])
            expected_counts=defaultdict(int)
            for sid in base_symbols.keys()|current_symbols.keys():
                kind='ADDED' if sid not in base_symbols else 'NOT_OBSERVED' if sid not in current_symbols else 'EVIDENCE_IDENTICAL' if same_roots and base_symbols[sid][1]==current_symbols[sid][1] else 'EVIDENCE_CHANGED'
                expected_counts[kind]+=1
            def find_history(sid):
                ready();button('清空筛选').click();count(24,20);ready()
                for index in range(2):
                    found=page.get_by_role('article',name='归档 '+sid,exact=True)
                    if found.count():return found
                    button('下一页').click();ready()
                raise AssertionError('Real archive absent from history pages')
            find_history(base_id).get_by_role('button',name='设为对比基准',exact=True).click()
            find_history(current_id).get_by_role('button',name='与基准对比',exact=True).click()
            comparison=page.get_by_role('region',name='历史对象对比',exact=True)
            expect(comparison.locator('.comparison-rows')).to_be_visible(timeout=30000)
            actual=api('/history/compare?'+urllib.parse.urlencode(dict(base=base_id,current=current_id,limit=100)))
            assert actual['counts']==dict(expected_counts) and actual['total']==len(base_symbols.keys()|current_symbols.keys())
            expect(comparison).to_contain_text(base_id);expect(comparison).to_contain_text(current_id)
            expect(comparison).to_contain_text('本轮未观察到不等于已修复')
            shot('09-real-archive-comparison-direction-and-counts');passed('two_real_native_archives_compare_exact_canonical_union_and_conservative_full_fingerprints')
            first_rows=[row.get_attribute('aria-label') for row in comparison.locator('.comparison-row').all()]
            if actual['total']>50:
                pending=[]
                def hold(route):pending.append(route)
                page.route('**/api/history/compare?**offset=50**',hold)
                comparison.get_by_role('button',name='下一页',exact=True).click()
                deadline=time.monotonic()+10
                while not pending:
                    page.wait_for_timeout(50)
                    assert time.monotonic()<deadline
                expect(comparison).to_contain_text('显示 1–50')
                assert [row.get_attribute('aria-label') for row in comparison.locator('.comparison-row').all()]==first_rows
                pending[0].continue_();page.unroute('**/api/history/compare?**offset=50**',hold)
                expect(comparison).to_contain_text('显示 51–',timeout=30000)
                comparison.get_by_role('button',name='上一页',exact=True).click()
                expect(comparison).to_contain_text('显示 1–50',timeout=30000)
            else:
                expect(comparison.get_by_role('button',name='下一页',exact=True)).to_be_disabled()
            result['comparison_pagination_scope']='ACTUAL_MULTI_PAGE_PENDING_REQUEST_HELD' if actual['total']>50 else 'ACTUAL15_OR_FEWER_ONE_PAGE_END;20007_BOUNDED_PAGINATION_IS_SEPARATE_DECLARED_UNIT_FIXTURE'
            passed('actual_comparison_pagination_keeps_previous_rows_and_range_atomic_or_explicit_last_page')
            def accessed_ids(sid):
                with closing(sqlite3.connect((data/'scans'/sid/'scan.db').resolve().as_uri()+'?mode=ro',uri=True)) as conn:
                    return {row[0] for row in conn.execute("SELECT DISTINCT symbol_id FROM records WHERE dataset='facts' AND relation='accesses' AND symbol_id IS NOT NULL")}
            accessed=common_ids&accessed_ids(base_id)&accessed_ids(current_id)
            selected=sorted(accessed or common_ids)[0]
            result['comparison_selected_evidence']=dict(symbol_id=selected,has_real_accesses_in_both_archives=bool(accessed))
            page.get_by_label('对比变量 / canonical 身份',exact=True).fill(selected)
            page.get_by_role('button',name='查询对比',exact=True).click()
            object_row=page.get_by_role('article',name='对比对象 '+selected,exact=True)
            expect(object_row).to_be_visible(timeout=30000)
            selected_before=events(data/'scans'/base_id);selected_after=events(data/'scans'/current_id)
            for side,sid in [('基准',base_id),('当前',current_id)]:
                page.get_by_role('article',name='对比对象 '+selected,exact=True).get_by_role('button',name='查看'+side+'证据',exact=True).click()
                expect(page.locator('.header-scan')).to_contain_text(sid,timeout=30000)
                expect(page.locator('.detail-panel')).to_contain_text(selected,timeout=30000)
                expect(page.get_by_role('heading',name='访问证据',exact=False)).to_be_visible(timeout=30000)
                page.get_by_role('link',name='历史与对比',exact=True).click()
                expect(page.get_by_role('region',name='历史对象对比',exact=True).locator('.comparison-rows')).to_be_visible(timeout=30000)
                page.get_by_label('对比变量 / canonical 身份',exact=True).fill(selected);page.get_by_role('button',name='查询对比',exact=True).click()
                expect(page.get_by_role('article',name='对比对象 '+selected,exact=True)).to_be_visible(timeout=30000)
            assert events(data/'scans'/base_id)==selected_before and events(data/'scans'/current_id)==selected_after
            shot('10-both-evidence-entries-preserve-original-human-history');passed('both_comparison_evidence_buttons_open_correct_scan_and_canonical_object_without_inheriting_decisions')
            page.reload();expect(page.get_by_role('region',name='历史对象对比',exact=True).locator('.comparison-rows')).to_be_visible(timeout=30000)
            expect(page.get_by_role('region',name='历史对象对比',exact=True)).to_contain_text(base_id)
            shot('11-comparison-reopen-1366');assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            expect(page.get_by_role('button',name='返回历史检索',exact=True)).to_be_in_viewport()
            expect(page.get_by_label('对比变量 / canonical 身份',exact=True)).to_be_in_viewport()
            passed('comparison_direction_survives_real_reload_and_1366_controls_remain_visible')
            page.get_by_role('button',name='返回历史检索',exact=True).click();ready()
            expect(page.get_by_text('当前对比基准：',exact=False)).to_contain_text(base_id)
            find_history(current_id).get_by_role('button',name='设为对比基准',exact=True).click()
            find_history(base_id).get_by_role('button',name='与基准对比',exact=True).click()
            expect(page.get_by_role('region',name='历史对象对比',exact=True).locator('.comparison-rows')).to_be_visible(timeout=30000)
            reversed_value=api('/history/compare?'+urllib.parse.urlencode(dict(base=current_id,current=base_id,limit=100)))
            assert reversed_value['counts'].get('ADDED',0)==expected_counts.get('NOT_OBSERVED',0)
            assert reversed_value['counts'].get('NOT_OBSERVED',0)==expected_counts.get('ADDED',0)
            passed('return_keeps_history_query_and_changing_baseline_reverses_real_canonical_direction')
            foreign=next((sid for sid,b in bindings.items() if b['project_id']!=bindings[base_id]['project_id']),None)
            if foreign:
                result['comparison_invalid_pair']='DIFFERENT_PROJECT_ACTUAL_GUI'
                page.get_by_role('button',name='返回历史检索',exact=True).click();ready()
                find_history(foreign).get_by_role('button',name='与基准对比',exact=True).click()
                expect(page.get_by_role('alert')).to_contain_text('工程身份不同',timeout=30000)
                expect(page.get_by_role('button',name='重试对比',exact=True)).to_be_visible()
            else:
                result['comparison_invalid_pair']='SAME_SCAN_ACTUAL_AUTHENTICATED_HTTP;OTHER_PROJECT_UNIT_CASE_SEPARATE'
                invalid=page.request.get(base+'/api/history/compare?base='+base_id+'&current='+base_id,headers={'X-ECRA-Session':info['token']})
                assert invalid.status==400 and '两个不同扫描批次' in invalid.json()['error']
            passed('invalid_pair_is_rejected_with_explicit_recovery_and_no_original_data_changes')
            result['comparison_acceptance']=dict(before=base_id,after=current_id,counts=dict(expected_counts),canonical_objects=actual['total'],physical_DPI='NOT_VERIFIED')
        assert all(sha256(p)==digest for p,digest in immutable.items())
        assert all((sha256(p),p.stat().st_size,p.stat().st_mtime_ns)==record for p,record in originals.items())
        assert all(p.is_file() and sha256(p)==digest for p,digest in engine_hashes.items())
        assert not result['page_errors'] and not result['external_requests']
        context.tracing.stop(path=str(output/'trace.zip'))
        result.update(passed=True,original_files_unchanged=len(originals),private_static_databases_unchanged=len(immutable),selected_scan_id=chosen,tests_count=len(result['tests']),engine_files_unchanged=len(engine_hashes),engine_sha256={p.relative_to(args.engine).as_posix():v for p,v in engine_hashes.items()});save()
    except BaseException:
        result.update(error=traceback.format_exc());save()
        if context:
            try:
                if context.pages:context.pages[-1].screenshot(path=str(output/'failure.png'),full_page=True)
                context.tracing.stop(path=str(output/'failure-trace.zip'))
            except Exception:pass
        raise
    finally:
        if context:context.close()
        if browser:browser.close()
        if playwright:playwright.stop()
        if server.poll() is None:server.terminate();server.wait(timeout=30)
        log.close()
    return 0


if __name__=='__main__':raise SystemExit(main())
