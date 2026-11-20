"""Exercise the built Studio in Chrome with real SQLite commits and one-shot HTTP faults."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import zipfile
import json
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlsplit, parse_qs
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tests')]
from playwright.sync_api import expect, sync_playwright
from projection_fixture import create_checkpoint, finish_checkpoint, publish
from ecra.workspace import managed_root


def check_draft_and_answer(page, info):
    """A newly opened AI tab can retry without a result commit; a stale draft cannot sign new heads."""
    failures=[]
    def first(route):
        if not failures:
            failures.append(time.monotonic())
            route.fulfill(status=503,json=dict(error='单次 AI 答复故障'))
        else:route.continue_()
    page.route('**/symbol-ai?*',first)
    page.get_by_role('tab',name='OpenCode结论',exact=True).click()
    answers=page.get_by_label('当前对象的OpenCode结论')
    expect(answers).to_contain_text('待同步')
    expect(answers).to_contain_text('测试夹具 b1 FALSE_POSITIVE',timeout=8000)
    elapsed=round(time.monotonic()-failures[0],3)
    url='http://'+info['authority']+'/api/scans/fixture/human'
    headers={'X-ECRA-Session':info['token'],'Origin':'http://'+info['authority']}
    review=page.request.get(url+'?symbol_id=B',headers=headers).json()
    signed=page.request.post(url,headers=headers,data=dict(symbol_id='B',fingerprint=review['fingerprint'],
        reviewer='第二窗口测试',decision='CONFIRMED_RISK',comment='受控记录',expected_heads=[]))
    assert signed.json()['saved']
    expect(page.locator('.review-content')).to_contain_text('原提交依据已保留',timeout=8000)
    page.get_by_label('确认者',exact=True).fill('第一窗口测试')
    page.get_by_role('button',name='确认无风险',exact=True).click()
    expect(page.locator('.banner.error').filter(has_text='已有其他确认')).to_be_visible()
    expect(page.locator('.review-content textarea')).to_have_value('保留此测试草稿')
    after=page.request.get(url+'?symbol_id=B',headers=headers).json()
    assert len(after['history'])==1 and after['decision']=='CONFIRMED_RISK'
    return dict(symbol_ai_retry_seconds=elapsed,original_draft_heads_rejected=True)


def check_navigation(context, info, out, output):
    """Exercise late reads, last-page removal, visibility and manual history."""
    page=context.new_page()
    errors=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    tried=[]
    def first_summary(route):
        if not tried:
            tried.append(True)
            route.fulfill(status=503,json=dict(error='一次初始化故障'))
        else:
            route.continue_()
    page.route('**/summary',first_summary)
    page.goto(info['url'])
    expect(page.get_by_role('alert').filter(has_text='汇总更新失败')).to_be_visible()
    expect(page.locator('.cards')).to_be_visible(timeout=8000)
    assert tried
    # Capture a genuine old response, but delay delivery through a change of query.
    page.get_by_role('link',name='变量与风险',exact=True).click()
    footer=page.locator('.page-controls')
    expect(footer).to_contain_text('匹配 6 项')
    delayed=[]
    def hold(route):
        if not delayed and parse_qs(urlsplit(route.request.url).query).get('limit')==['50']:
            delayed.append((route,route.fetch()))
        else:
            route.continue_()
    page.route('**/symbols?*',hold)
    page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    for _ in range(100):
        if delayed:break
        page.wait_for_timeout(40)
    assert delayed, 'No outstanding list request'
    page.locator('#variable-search').fill('B')
    page.get_by_role('button',name='搜索',exact=True).click()
    expect(footer).to_contain_text('匹配 1 项')
    delayed[0][0].fulfill(response=delayed[0][1])
    page.wait_for_timeout(250)
    expect(page.locator('.symbol strong')).to_have_text(['B'])
    expect(footer).to_contain_text('匹配 1 项')
    page.unroute('**/symbols?*',hold)

    def switch(sid):
        page.get_by_role('link',name='历史与对比',exact=True).click()
        page.get_by_label('归档 '+sid,exact=True).get_by_role('button',name='打开结果').click()
        expect(page.locator('.header-scan')).to_have_text('批次 '+sid)
        expect(page.locator('.cards')).to_be_visible()

    # Hold another response across A -> B -> A. The same scan ID alone is insufficient.
    delayed.clear()
    page.route('**/symbols?*',hold)
    page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    for _ in range(100):
        if delayed:break
        page.wait_for_timeout(40)
    assert delayed
    switch('paged')
    page.get_by_role('link',name='人工确认',exact=True).click()
    expect(footer).to_contain_text('匹配 51 项')
    viewport=page.locator('.symbol-list')
    before_scroll=viewport.evaluate('el => { el.scrollTop = 320; return el.scrollTop }')
    assert before_scroll==320
    with page.expect_response(lambda res: '/paged/symbols?' in res.url, timeout=10000) as refresh:
        publish(out.parent/'paged','gap1','NEED_MORE_CONTEXT')
    assert refresh.value.json()['total']==51
    page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
    assert viewport.evaluate('el => el.scrollTop')==before_scroll
    page.get_by_role('button',name='下一页',exact=True).click()
    expect(footer).to_contain_text('51–51')
    page.locator('.symbol').click()
    page.get_by_role('button',name='填写人工确认',exact=True).click()
    page.get_by_label('确认者',exact=True).fill('协议测试')
    page.locator('.review-content textarea').fill('末页测试依据')
    page.get_by_role('button',name='确认无风险',exact=True).click()
    expect(footer).to_contain_text('匹配 50 项 · 1–50',timeout=12000)
    expect(page.locator('.symbol')).to_have_count(50)
    expect(page.get_by_role('button',name='下一页',exact=True)).to_be_disabled()
    expect(page.locator('.conclusion')).to_contain_text('人工确认无风险')
    page.screenshot(path=output/'last-pending-page.png')
    switch('fixture')
    page.get_by_role('link',name='变量与风险',exact=True).click()
    page.get_by_role('button',name='清空',exact=True).click()
    expect(footer).to_contain_text('匹配 6 项')
    delayed[0][0].fulfill(response=delayed[0][1])
    page.wait_for_timeout(300)
    expect(footer).to_contain_text('匹配 6 项')
    expect(page.locator('.symbol')).to_have_count(6)
    page.unroute('**/symbols?*',hold)

    switch('scoped')
    cards=page.locator('.cards strong')
    expect(cards).to_have_text(['2','0','0','2'])
    page.locator('.cards button').first.click()
    expect(footer).to_contain_text('匹配 2 项')
    expect(page.locator('.symbol strong')).to_have_text(['C','B'])
    cdp=context.new_cdp_session(page)
    cdp.send('Page.setWebLifecycleState',dict(state='frozen'))
    publish(out.parent/'scoped','b1','FALSE_POSITIVE')
    cdp.send('Page.setWebLifecycleState',dict(state='active'))
    expect(footer).to_contain_text('匹配 1 项')
    expect(page.locator('.symbol strong')).to_have_text(['C'])
    page.get_by_role('link',name='项目概览',exact=True).click()
    expect(cards).to_have_text(['1','0','1','1'])
    page.screenshot(path=output/'diff-scope.png')
    page.get_by_role('link',name='覆盖与诊断',exact=True).click()
    expect(page.get_by_role('heading',name='覆盖与诊断',exact=True)).to_be_visible()
    page.get_by_role('link',name='数据与共享',exact=True).click()
    page.get_by_role('button',name='导出标准完整包').click()
    expect(page.locator('.export-progress')).to_contain_text('完整结果包已就绪',timeout=60000)
    package,=(out.parent.parent/'exports').glob('*.ecra-report')
    with zipfile.ZipFile(package) as archive:
        manifest=json.loads(archive.read('manifest.json'))
    headers={'X-ECRA-Session':info['token']}
    revision=page.request.get('http://'+info['authority']+'/api/scans/scoped/result-revision',headers=headers).json()
    assert manifest['result_revision']==revision['result_revision'] and manifest['generated_at']
    page.screenshot(path=output/'export.png')
    page.get_by_role('link',name='历史与对比',exact=True).click()
    expect(page.locator('.history-count')).to_contain_text('3 个归档')
    page.get_by_role('link',name='项目概览',exact=True).click()
    expect(cards).to_have_text(['1','0','1','1'])
    # Only this test's private archive is damaged. A confirmed integrity failure
    # must clear the previously visible cards and refuse to present stale counts.
    (out.parent/'scoped'/'manifest.json').write_text('{','utf8')
    page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    unavailable=page.get_by_role('heading',name='当前结果未能读取')
    expect(unavailable).to_be_visible()
    expect(cards).to_have_count(0)
    url='http://'+info['authority']+'/api/scans/'
    broken=page.request.get(url+'scoped/summary',headers=headers)
    assert broken.json()['code']=='INVALID_SCAN'
    page.evaluate("localStorage.setItem('ecra-scan','absent-fixture')")
    page.reload()
    expect(unavailable).to_be_visible()
    expect(cards).to_have_count(0)
    missing=page.request.get(url+'absent-fixture/summary',headers=headers)
    assert (missing.status,missing.json()['code'])==(404,'SCAN_MISSING')
    page.screenshot(path=output/'missing.png')
    assert not errors,errors
    return dict(initial_summary_recovered=True,delayed_filter_total=1,returned_batch_total=6,
                list_scroll_px=before_scroll,invalid_archive_hidden=True,missing_archive_hidden=True,pending_last_page=[51,50],export=str(package),exported_revision=manifest['result_revision'],diff_before=[2,0,0,2],diff_after=[1,0,1,1],page_errors=errors)


def check_concurrent_results(context, info, data, output):
    from ecra.scan_persistence import commit_review_result, review_writer

    archive = data/'scans'/'parallel'
    sample = create_checkpoint(archive)
    overview = context.new_page()
    overview.goto(info['url'])
    overview.evaluate("localStorage.setItem('ecra-scan','parallel')")
    overview.reload()
    cards = overview.locator('.cards strong')
    expect(cards).to_have_text(['2','2','1','4'])
    second_browser = context.browser.browser_type.launch(channel='chrome')
    try:
        review = second_browser.new_page(viewport=dict(width=1440, height=960))
        review.goto(info['url'])
        expect(review.get_by_role('link', name='项目概览', exact=True)).to_be_visible()
        review.evaluate("localStorage.setItem('ecra-scan','parallel')")
        review.reload()
        review.get_by_role('link', name='OpenCode 复核', exact=True).click()
        progress = review.locator('.ai-progress')
        expect(progress).to_contain_text('总复核对象 7 · 已完成 0')
        outcomes = [('a1','REVIEWED_SAFE'), ('a2','REVIEWED_SAFE'), ('b1','FALSE_POSITIVE'),
                    ('c1','CONFIRMED'), ('d1','NEED_MORE_CONTEXT'), (sample,'REVIEWED_SAFE'),
                    ('gap1','NEED_MORE_CONTEXT')]
        with ThreadPoolExecutor(max_workers=3) as workers:
            submissions = [workers.submit(publish, archive, fid, verdict) for fid, verdict in outcomes]
            receipts = [submission.result() for submission in submissions]
        with review_writer(archive) as writer:
            commit_review_result(writer, *receipts[0])
        expect(cards).to_have_text(['1','1','3','2'],timeout=10000)
        expect(progress).to_contain_text('总复核对象 7 · 已完成 7 · 技术失败 0 · 待复核 0')
        review.screenshot(path=output/'parallel.png')
    finally:
        second_browser.close()
    return dict(browser_processes=2, workers=3, objects=7, done=7, duplicate=1, cards=[1,1,3,2])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    data = managed_root()/'data-roots'/('sync-ui-'+uuid4().hex[:8])
    out = data/'scans/fixture'
    sample = create_checkpoint(out)
    finish_checkpoint(out, sample)
    if not args.baseline:
        for name,config in [('paged',dict(extra_pending=48)),('scoped',dict(diff=True))]:
            other=data/'scans'/name
            finish_checkpoint(other,create_checkpoint(other,**config))
    session = data/'work/session.json'
    args.output.mkdir(parents=True, exist_ok=True)
    # ECRA.cmd uses this module in both source and Portable installations.
    server = subprocess.Popen([sys.executable, '-B', '-m', 'ecra.studio', '--no-browser', '--data-root',
                               str(data), '--session-file', str(session)], cwd=ROOT, stdout=subprocess.DEVNULL)
    try:
        until = time.monotonic()+35
        while not session.is_file():
            if server.poll() is not None or time.monotonic()>until:
                raise RuntimeError('Studio startup failed')
            time.sleep(.1)
        info = json.loads(session.read_text('utf8'))
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel='chrome')
            context = browser.new_context(viewport=dict(width=1440, height=960))
            faults, pages, observations = {}, {}, {}
            def open_page(key, route):
                page = context.new_page()
                page.goto(info['url'])
                expect(page.locator('.cards')).to_be_visible()
                if route:
                    page.get_by_role('link', name=route, exact=True).click()
                pages[key] = page
                return page
            def once(page, key, pattern, match=lambda q: True):
                def intercept(route):
                    if key in faults and match(parse_qs(urlsplit(route.request.url).query)):
                        faults[key] = False
                        if key not in observations:
                            observations[key] = dict(failed=round(time.monotonic()-start,3))
                            route.fulfill(status=503, json=dict(error='受控单次读取故障'))
                            return
                    route.continue_()
                page.route(pattern, intercept)
            overview = open_page('summary','')
            listing = open_page('list','变量与风险')
            detail = open_page('detail','变量与风险')
            detail.locator('.symbol').filter(has=detail.get_by_text('B',exact=True)).click()
            detail.get_by_role('button', name='填写人工确认', exact=True).click()
            draft = detail.locator('.review-content textarea')
            draft.fill('保留此测试草稿')
            ai = open_page('ai', 'OpenCode 复核')
            ai.get_by_role('button', name='待复核 / 无法判断 3').click()
            ai.get_by_role('button', name='B', exact=True).click()
            expect(ai.locator('.inspector-detail')).to_contain_text('技术失败')
            manual = open_page('manual','人工确认')
            expect(manual.locator('.page-controls')).to_contain_text('匹配 3 项')
            once(overview, 'summary', '**/summary')
            once(listing, 'list', '**/symbols?*', lambda q:q.get('limit')==['50'])
            once(detail, 'detail', '**/symbol?*')
            once(ai, 'ai', '**/ai?*', lambda q:'finding_id' in q)
            for key in ('summary','list','detail','ai'):
                faults[key] = True
            publish(out,'b1','FALSE_POSITIVE')
            start = time.monotonic()
            checks = {
                'summary': (overview.locator('.cards button').filter(has_text='安全（'), '3'),
                'list': (listing.locator('.symbol').filter(has=listing.get_by_text('B',exact=True)), '无需人工'),
                'detail': (detail.locator('.conclusion'), '无需人工'),
                'ai': (ai.locator('.inspector-detail'), 'OpenCode确认静态误报'),
                'manual': (manual.locator('.page-controls'), '匹配 2 项'),
            }
            while time.monotonic()-start < 10:
                overview.wait_for_timeout(100)
                for key,(loc,needle) in checks.items():
                    if key in observations and 'applied' in observations[key]:
                        continue
                    if any(needle in text for text in loc.all_inner_texts()):
                        observations.setdefault(key,{})['applied'] = round(time.monotonic()-start,3)
                if all('applied' in observations.get(key,{}) for key in checks):
                    break
            for key,(loc,_) in checks.items():
                observations.setdefault(key,{})['display'] = loc.all_inner_texts()
            observations['draft'] = draft.input_value() if draft.count() else None
            observations['asset'] = overview.locator('script[src]').first.get_attribute('src')
            asset=urlsplit(overview.url).scheme+'://'+info['authority']+'/'+observations['asset'].removeprefix('./')
            content=overview.request.get(asset).body()
            assert content==(ROOT/'ecra/studio/web'/observations['asset']).read_bytes()
            observations['asset_sha256']=hashlib.sha256(content).hexdigest()
            print(json.dumps(observations,ensure_ascii=False), flush=True)
            (args.output/'observations.json').write_text(json.dumps(observations,ensure_ascii=False,indent=2),'utf8')
            overview.screenshot(path=str(args.output/'overview.png'))
            detail.screenshot(path=str(args.output/'detail.png'))
            assert all('failed' in observations[key] for key in faults)
            if args.baseline:
                assert all('applied' not in observations[key] for key in faults)
            else:
                assert all('applied' in observations[key] for key in checks)
                assert observations['draft']=='保留此测试草稿'
                publish(out,'gap1','NEED_MORE_CONTEXT')
                expect(ai.locator('.ai-progress')).to_contain_text('已完成 7')
                ai.reload()
                expect(ai.locator('.ai-progress')).to_contain_text('总复核对象 7 · 已完成 7 · 技术失败 0 · 待复核 0')
                expect(manual.locator('.page-controls')).to_contain_text('匹配 2 项')
                ai.screenshot(path=str(args.output/'last-item.png'))
                # Failure after changing a query must not send the old query's conditional revision.
                missed=[]
                def search_fault(route):
                    if not missed and parse_qs(urlsplit(route.request.url).query).get('search')==['C']:
                        missed.append(True)
                        route.fulfill(status=503,json=dict(error='首次搜索失败'))
                    else:route.continue_()
                ai.route('**/ai?*',search_fault)
                ai.locator('#ai-search').fill('C')
                ai.get_by_role('button',name='搜索复核结果').click()
                expect(ai.locator('.page-controls')).to_contain_text('1–1 / 1',timeout=8000)
                expect(ai.locator('.ai-table tbody button')).to_have_text(['C'])
                assert missed
                more=check_draft_and_answer(detail,info)
                more.update(check_navigation(context, info, out, args.output))
                more['concurrent'] = check_concurrent_results(context, info, data, args.output)
                (args.output/'navigation.json').write_text(json.dumps(more,indent=2),'utf8')
            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=10)


if __name__=='__main__':
    main()
