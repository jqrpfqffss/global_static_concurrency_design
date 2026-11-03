"""Real imported INAV evidence in the shipped GUI; no synthetic analysis data.

Normally requires the verified standard-package import of the approved INAV
scan. An explicitly selected original-graph diagnostic remains separate.
Checks complete direct-edge pages and a marked main witness, not enumerated
all-path lists, target-board behavior, physical second-PC or Windows DPI.
"""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import time
import traceback
import urllib.parse
import urllib.request


def wait(fn,seconds=120):
    end=time.monotonic()+seconds
    while True:
        result=fn()
        if result:return result
        if time.monotonic()>end:raise TimeoutError('Actual viewer operation did not complete')
        time.sleep(.1)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['data-root','work','evidence','engine']:p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--input-kind',choices=['verified-native-package','original-native-graph-diagnostic'],default='verified-native-package')
    p.add_argument('--python',type=Path,help='Explicit source-engine diagnostic interpreter; never labelled Portable acceptance')
    p.add_argument('--scan',default='native-golden');args=p.parse_args()
    if os.name!='nt':p.error('Actual Windows launcher/Jobs/Chrome required')
    sys.path.insert(0,str(args.engine))
    from ecra.scan_store import EvidenceProvider,connect_readonly
    from ecra.report_package import sha256,IDENTITY
    from ecra.workspace import no_links,studio_data_root
    from ecra.studio.process_budget import ProcessBudget
    from ecra.studio.write_guard import OwnedProcess
    assert IDENTITY.fullmatch(args.scan)
    data=studio_data_root(args.data_root);scan=no_links(data/'scans'/args.scan);provider=EvidenceProvider(scan/'scan.db')
    work=studio_data_root(args.work);work.mkdir(parents=True,exist_ok=False)
    output=no_links(args.evidence);output.mkdir(parents=True,exist_ok=False);(work/'controller.py').write_bytes(Path(__file__).read_bytes())
    assert not work.is_relative_to(data) and not output.is_relative_to(data)
    symbol='tu::src/main/drivers/time.c::c:time.c@sysTickUptime';main_context='vector:slot:1';irq_context='vector:slot:15'
    process=budget=log=browser=context=playwright=page=None;info={}
    result=dict(passed=False,tests=[],screenshots=[],page_errors=[],external_requests=[],symbol_id=symbol,scan_id=args.scan,
                input_kind=args.input_kind,engine=str(args.engine),scope=__doc__,main_context=main_context,irq_context=irq_context,
                native_windows_dpi='NOT_VERIFIED',physical_second_computer='NOT_VERIFIED',engineer_uat='NOT_VERIFIED')
    def save():(output/'acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n','utf-8')
    def passed(name):result['tests'].append(dict(name=name,status='PASS'));save()
    def api(path):
        request=urllib.request.Request('http://'+info['authority']+'/api'+path,headers={'X-ECRA-Session':info['token']})
        with urllib.request.urlopen(request,timeout=120) as response:return json.load(response)
    def shot(name):
        path=output/(name+'.png');page.screenshot(path=str(path),full_page=True);result['screenshots'].append(str(path));save()
    save()
    try:
        manifest=json.loads((scan/'manifest.json').read_text('utf-8'));binding=provider.metadata()
        if args.input_kind=='verified-native-package':
            assert manifest['format']=='ECRA_REPORT' and re.fullmatch('[0-9a-f]{64}',manifest['import_origin'])
        else:
            assert manifest['format']=='ECRA_VALIDATION_NATIVE_GRAPH_COPY'
            assert binding['facts_hash']=='9da30821f449de364352f533134d80e731e031f44bbe69ec86d8f287ac12b6c2'
        assert binding['scan_id']==args.scan
        # Standard V1 packages bind these four keys. profile/state remain in
        # immutable scan.db, rather than being duplicated in the manifest.
        assert all(manifest[key]==binding[key] for key in ['scan_id','project_id','facts_hash','report_hash'])
        candidates=provider.symbols(search=symbol,limit=50)['items'];assert any(r['symbol_id']==symbol for r in candidates)
        accesses=provider.records('accesses',symbol_id=symbol,limit=200);assert accesses['next_offset'] is None
        assert any(r['summary']['access_kind']=='RMW' and r['function_id']=='c:@F@SysTick_Handler' for r in accesses['items'])
        bindings={f:provider.records('context_bindings',function_id=f,limit=200)['items'] for f in ['c:@F@main','c:@F@SysTick_Handler']}
        assert any(r['summary'].get('context_id')==main_context for r in bindings['c:@F@main'])
        assert any(r['summary'].get('context_id')==irq_context for r in bindings['c:@F@SysTick_Handler'])
        finding=provider.records('findings',dataset='report',symbol_id=symbol,limit=200)['items'][0]
        fields=provider.node(finding['node'],limit=200)['items'];pairs=next(x for x in fields if x['key']=='conflict_pairs')
        assert pairs['total']>10 and finding['summary']['protection_status']=='UNRESOLVED'
        micros=next(r for r in accesses['items'] if r['function_id']=='c:@F@micros')
        route=provider.load('facts',['accesses',micros['ordinal'],'call_chains',main_context]);assert route[0]=='c:@F@main' and route[-1]=='c:@F@micros'
        assert provider.load('facts',['context_call_graph','complete']) is True
        result['phase']='HASHING_STATIC_BEFORE';save();before_hash=sha256(scan/'scan.db')
        if args.input_kind=='verified-native-package':assert before_hash==manifest['files']['scan.db']['sha256']
        result.update(main_witness=route,static_sha256_before=before_hash,controller_sha256=sha256(work/'controller.py'),binding=binding)
        with closing(sqlite3.connect((scan/'reviews.db').resolve().as_uri()+'?mode=ro',uri=True)) as conn:
            events_before=conn.execute('SELECT count(*) FROM events').fetchone()[0]
        result['existing_human_events']=events_before;save()
        windows=Path(os.environ.get('SystemRoot','C:/Windows'));session=work/'session.json'
        env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',LOCALAPPDATA=str(work/'user'),PATH=str(windows/'System32')+os.pathsep+str(windows))
        command=[str(windows/'System32/cmd.exe'),'/d','/c',str(args.engine/'ECRA.cmd'),'--no-browser','--data-root',str(data),'--session-file',str(session)]
        result['runtime_kind']='ACTUAL_PORTABLE_LAUNCHER'
        if args.python:
            command=[str(args.python),'-B','-X','utf8','-m','ecra.studio','--no-browser','--data-root',str(data),'--session-file',str(session)]
            result['runtime_kind']='EXPLICIT_SOURCE_ENGINE_NOT_PORTABLE'
        result['command']=command;save();log=(work/'launcher.log').open('xb');budget=ProcessBudget(2*1024**3)
        process=OwnedProcess(command,cwd=args.engine if args.python else work,env=env,log=log);budget.assign(process);process.resume()
        def ready():
            if process.poll() is not None:raise RuntimeError('Actual Portable launcher exited; inspect private log')
            try:return json.loads(session.read_text('utf-8'))
            except (OSError,ValueError):return None
        info=wait(ready,60)
        def bound():
            try:return api('/bootstrap')
            except OSError:return None
        wait(bound,60)
        from playwright.sync_api import sync_playwright,expect
        playwright=sync_playwright().start();browser=playwright.chromium.launch(channel='chrome',headless=True)
        context=browser.new_context(viewport=dict(width=1366,height=768));context.tracing.start(screenshots=True,snapshots=True,sources=True)
        page=context.new_page();page.on('pageerror',lambda e:result['page_errors'].append(str(e)))
        page.on('request',lambda q:result['external_requests'].append(q.url) if q.url.startswith(('http:','https:')) and not q.url.startswith('http://'+info['authority']+'/') else None)
        page.goto(info['url']);expect(page.locator('.activity')).to_have_count(0,timeout=120000)
        page.get_by_role('link',name='变量与风险',exact=True).click();search=page.get_by_label('查找变量、文件或规范身份',exact=True)
        search.fill(symbol);search.press('Enter')
        expect(page.locator('.symbol')).to_have_count(1,timeout=120000);page.locator('.symbol').click()
        expect(page.locator('.detail-summary .identity')).to_have_text(symbol,timeout=120000)
        expect(page.locator('.access-row')).to_have_count(accesses['total'],timeout=120000)
        expect(page.locator('.detail-summary')).to_contain_text('目标板实测')
        shot('01-real-main-irq-identity-and-accesses');passed('native_canonical_identity_all_accesses_and_real_main_systick_context_bindings')
        panel=page.locator('.conflict-pairs');expect(panel).to_be_visible(timeout=120000);offset=0;seen=[];atomic_checked=False
        while offset<pairs['total']:
            expect(panel.get_by_text('正在读取关系…',exact=True)).to_have_count(0,timeout=120000)
            expected=provider.node(pairs['id'],offset=offset,limit=10);rows=panel.locator(':scope > article')
            expect(rows).to_have_count(len(expected['items']),timeout=120000)
            for index,item in enumerate(expected['items']):
                article=rows.nth(index);expect(article.locator(':scope > strong')).to_contain_text('关系 '+str(offset+index+1))
                details=article.locator(':scope > details.evidence-node');details.locator(':scope > summary').click()
                expect(details.locator(':scope > .node-content > .reference')).to_contain_text('#'+str(item['id'])+' ·',timeout=120000)
                details.locator(':scope > summary').click();seen.append(item['id'])
            if expected['next_offset'] is None:break
            offset=expected['next_offset']
            if not atomic_checked:
                next_first=provider.node(pairs['id'],offset=offset,limit=10)['items'][0];held=[]
                pattern=re.compile(r'/api/scans/'+re.escape(args.scan)+r'/nodes/'+str(next_first['id'])+r'\?limit=200$')
                def hold_real_response(route):held.append(route)
                page.route(pattern,hold_real_response)
                try:
                    panel.get_by_role('button',name='后10组关系',exact=True).click()
                    expect(panel.get_by_text('正在读取关系…',exact=True)).to_be_visible(timeout=120000)
                    deadline=time.monotonic()+30
                    while not held:
                        if time.monotonic()>deadline:raise TimeoutError('Real next-page request was not observed')
                        page.wait_for_timeout(50)  # Pump actual request events, never manufacture a response.
                    # The genuine second-page request is pending. The old
                    # page label and its old references must stay together.
                    expect(rows.first.locator(':scope > strong')).to_contain_text('关系 1 ·')
                    shot('02a-page-label-and-evidence-stay-atomic-during-real-pending-request')
                finally:
                    for pending_request in held:pending_request.continue_()
                    page.unroute(pattern,hold_real_response)
                atomic_checked=True
            else:panel.get_by_role('button',name='后10组关系',exact=True).click()
            expect(panel.get_by_text('正在读取关系…',exact=True)).to_have_count(0,timeout=120000)
            expect(rows.first.locator(':scope > strong')).to_contain_text('关系 '+str(offset+1),timeout=120000)
            result.update(phase='COMPLETE_CONFLICT_PAGES',conflict_pairs_read=len(seen));save()
        assert len(seen)==pairs['total'] and atomic_checked;result.update(conflict_pairs_read=len(seen),page_publication_atomic=True)
        shot('02-all-conflict-pages-no-top-n');passed('all_real_conflict_pairs_paged_with_original_evidence_references_and_model_disclaimer')
        page.get_by_role('tab',name='调用与保护',exact=True).click();tree=page.locator('.call-tree')
        functions=api('/scans/'+args.scan+'/symbol-functions?'+urllib.parse.urlencode(dict(symbol_id=symbol)))
        assert functions['next_offset'] is None;roots=tree.locator(':scope > div > .call-node');expect(roots).to_have_count(functions['total'],timeout=120000)
        checked=[]
        def root_button(node):return node.locator(':scope > button.call-function')
        def children(node):return node.locator(':scope > .call-children')
        for direction in ['upstream','downstream']:
            tree.get_by_label('调用查询方向',exact=True).select_option(direction)
            for index,function in enumerate(functions['items']):
                node=roots.nth(index);root_button(node).click();offset=0;ordinals=[]
                while True:
                    expected=provider.records('calls',offset=offset,limit=50,**{'target_id' if direction=='upstream' else 'source_id':function['function_id']})
                    body=children(node);expect(body.locator(':scope > p').first).to_contain_text(str(expected['total'])+' 条',timeout=120000)
                    articles=body.locator(':scope > article');expect(articles).to_have_count(len(expected['items']),timeout=120000)
                    for position,edge in enumerate(expected['items']):
                        article=articles.nth(position);expect(article.locator(':scope > p').first).to_contain_text(str(edge['summary'].get('file'))+':'+str(edge['summary'].get('line')))
                        detail=article.locator(':scope > details.evidence-node');detail.locator(':scope > summary').click()
                        expect(detail.locator(':scope > .node-content > .reference')).to_contain_text('#'+str(edge['node']),timeout=120000)
                        detail.locator(':scope > summary').click();ordinals.append(edge['ordinal'])
                    if expected['next_offset'] is None:break
                    offset=expected['next_offset'];body.locator(':scope > button').filter(has_text='继续完整调用边').click()
                    expect(body.locator(':scope > p').first).to_contain_text('显示 '+str(offset+1)+'–',timeout=120000)
                assert len(ordinals)==expected['total'];checked.append(dict(function_id=function['function_id'],direction=direction,total=len(ordinals),ordinals=ordinals))
                root_button(node).click()
        assert any(r['direction']=='upstream' and r['total']>50 for r in checked);result['all_direct_edge_pages']=checked
        # Check the complete related edge-index union as well as the user-visible
        # access-function pages. Only bounded responses are read; the oracle and
        # visited set live in this test's own SQLite file, never in scan.db.
        with closing(sqlite3.connect(work/'edge-oracle.db')) as oracle,closing(connect_readonly(scan/'scan.db')) as authority:
            oracle.execute('CREATE TABLE expected(ordinal INTEGER PRIMARY KEY,node INTEGER,source TEXT,target TEXT)')
            oracle.execute('CREATE TABLE seen(ordinal INTEGER PRIMARY KEY)')
            for function in functions['items']:
                indices=provider.resolve('facts',['call_graph_slices',function['function_id'],'call_edge_indices']);offset=0
                while True:
                    part=provider.node(indices,offset=offset,limit=200);ids=[row['value'] for row in part['items']]
                    if ids:
                        rows=authority.execute("SELECT ordinal,node,source_id,target_id FROM records WHERE dataset='facts' AND relation='calls' AND ordinal IN ("+','.join('?'*len(ids))+')',ids)
                        oracle.executemany('INSERT OR IGNORE INTO expected VALUES (?,?,?,?)',(tuple(row) for row in rows))
                    if part['next_offset'] is None:break
                    offset=part['next_offset']
            oracle.commit();response_peak=0;pages=0
            for (caller,) in oracle.execute('SELECT DISTINCT source FROM expected WHERE source IS NOT NULL ORDER BY source'):
                offset=0;expected_total=authority.execute("SELECT count(*) FROM records WHERE dataset='facts' AND relation='calls' AND source_id=?",(caller,)).fetchone()[0]
                while True:
                    part=api('/scans/'+args.scan+'/call-neighbors?'+urllib.parse.urlencode(dict(function_id=caller,direction='downstream',offset=offset,limit=50)))
                    assert part['total']==expected_total;response_peak=max(response_peak,len(json.dumps(part,ensure_ascii=True).encode()));pages+=1
                    for row in part['items']:
                        found=oracle.execute('SELECT node FROM expected WHERE ordinal=?',(row['ordinal'],)).fetchone()
                        if found:
                            assert found[0]==row['node'];oracle.execute('INSERT OR IGNORE INTO seen VALUES (?)',(row['ordinal'],))
                    if part['next_offset'] is None:break
                    offset=part['next_offset']
            expected_count=oracle.execute('SELECT count(*) FROM expected').fetchone()[0];seen_count=oracle.execute('SELECT count(*) FROM seen').fetchone()[0]
            assert expected_count==seen_count and expected_count>50
            result['complete_slice_API']=dict(expected_edges=expected_count,seen_edges=seen_count,pages=pages,max_response_bytes=response_peak)
        shot('03-all-bidirectional-edge-pages-checked');passed('every_related_function_all_direct_and_resolved_callsite_pages_keep_order_and_duplicates')
        tree.get_by_label('调用查询方向',exact=True).select_option('upstream');index=next(i for i,f in enumerate(functions['items']) if f['function_id']==route[-1]);node=roots.nth(index)
        root_button(node).click()
        for caller,callee in reversed(list(zip(route,route[1:]))):
            matches=provider.records('calls',source_id=caller,target_id=callee,limit=200);assert matches['next_offset'] is None
            valid=[]
            for edge in matches['items']:
                try:allowed=provider.load('facts',['calls',edge['ordinal'],'allowed_contexts'])
                except KeyError:allowed=None
                if allowed is None or main_context in allowed:valid.append(edge)
            assert valid;edge=valid[0]
            with closing(connect_readonly(scan/'scan.db')) as conn:
                rank=conn.execute("SELECT count(*) FROM records WHERE dataset='facts' AND relation='calls' AND target_id=? AND ordinal<?",(callee,edge['ordinal'])).fetchone()[0]
            body=children(node)
            # Expanding a real large archive can outlast Playwright's default
            # five-second assertion. Await the actual first page and row count
            # before selecting the SQL-ranked witness; never fabricate a page.
            expect(body.locator(':scope > p').first).to_contain_text('显示 1–',timeout=120000)
            for offset in range(50,(rank//50)*50+1,50):
                body.locator(':scope > button').filter(has_text='继续完整调用边').click();expect(body.locator(':scope > p').first).to_contain_text('显示 '+str(offset+1)+'–',timeout=120000)
            article=body.locator(':scope > article').nth(rank%50);node=article.locator(':scope > .call-node');expect(node).to_have_count(1,timeout=120000)
            root_button(node).click()
        expect(root_button(node)).to_contain_text('main');shot('04-real-main-witness-not-all-path-enumeration');passed('archived_main_witness_expands_real_context_allowed_edges_to_main')
        page.get_by_role('tab',name='时序与访问',exact=True).click();expect(page.locator('.finding-card')).to_contain_text(finding['summary']['protection_note'])
        expect(page.locator('.finding-card')).to_contain_text('无法恢复全部竞争 IRQ 优先级')
        shot('05-unresolved-nvic-and-protection-kept');passed('actual_unresolved_priority_and_protection_conditions_are_visible_without_invented_preemption')
        rmw=page.locator('.access-row').filter(has_text='c:@F@SysTick_Handler');rmw.get_by_role('button',name='定位此访问代码',exact=True).click()
        archived=provider.archived_source(next(r['summary']['file'] for r in accesses['items'] if r['function_id']=='c:@F@SysTick_Handler'))
        if args.input_kind=='original-native-graph-diagnostic' and not archived['available']:
            expect(page.get_by_role('region',name='带行号的归档源码')).to_contain_text('此归档未包含对应源码文本；原源码不可用。')
            expect(page.locator('.source-code')).to_have_count(0)
            result['archived_source']='UNAVAILABLE_IN_ORIGINAL_COMPARISON_ONLY_GRAPH'
            shot('06-diagnostic-graph-honestly-declares-source-unavailable');passed('comparison_only_graph_without_archived_text_does_not_read_or_invent_live_source')
        else:
            assert archived['available'];expect(page.locator('.source-code')).to_contain_text('sysTickUptime++',timeout=120000)
            result['archived_source']='ACTUAL_ARCHIVED_RMW_TEXT_VERIFIED'
            shot('06-real-archived-systick-rmw-code');passed('viewer_uses_real_archived_rmw_source_with_complete_text_navigation')
        with closing(sqlite3.connect((scan/'reviews.db').resolve().as_uri()+'?mode=ro',uri=True)) as conn:
            events_after=conn.execute('SELECT count(*) FROM events').fetchone()[0]
        result.update(static_sha256_after=sha256(scan/'scan.db'),binding=provider.metadata(),tasks_after_browsing=api('/tasks')['items'],human_events_after=events_after)
        result['passed']=len(result['tests'])==6 and result['static_sha256_after']==before_hash and events_after==events_before and not result['page_errors'] and not result['external_requests'] and not result['tasks_after_browsing']
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
