"""Real approved firmware, repeat native scan, Chrome inheritance/undo/restart.

Requires an explicitly supplied authorized config. Uses private data only;
does not claim physical second-PC, Windows DPI, UAT or full G1-G8 acceptance.
"""
import argparse
import contextlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

TOOL=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(TOOL))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--work',type=Path,required=True)
    parser.add_argument('--reuse-fixture',type=Path,help='只重验界面；复制之前实际完成的两次原生扫描，保留其失败收据')
    args=parser.parse_args()
    from ecra.common import write_json
    from ecra.config import configured_project_root
    from ecra.human_reviews import ReviewStore
    from ecra.report_package import sha256,export_report,import_report,export_delta,import_delta
    from ecra.scan_persistence import run_canonical
    from ecra.scan_store import EvidenceProvider
    import yaml
    work=args.work.resolve();work.mkdir(parents=True,exist_ok=False)
    root=configured_project_root(args.config)
    originals={p:(sha256(p),p.stat().st_size,p.stat().st_mtime_ns)
        for p in [args.config,*root.rglob('*')] if p.is_file()}
    engine={p:sha256(p) for p in (TOOL/'ecra').rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    cfg=yaml.safe_load(args.config.read_text('utf-8'));cfg['analysis']['output']=dict(location='user')
    cfg['review'].update(enabled=False,prepare_packets=False)
    config=work/'semantics.yaml';config.write_text(yaml.safe_dump(cfg,allow_unicode=True),'utf-8')
    data=work/'data';os.environ['ECRA_DATA_ROOT']=str(data)
    result=dict(passed=False,scope=__doc__,tests=[],page_errors=[],external_requests=[],screenshots=[])
    receipt=work/'acceptance.json'
    def save():write_json(receipt,result)
    save()
    server=log=browser=playwright=None
    try:
        if args.reuse_fixture:
            import shutil
            shutil.copytree(args.reuse_fixture/'data',data)
            result['fixture_origin']=str(args.reuse_fixture.resolve())
        for name in ['first','second']:
            if not args.reuse_fixture:
                with (work/(name+'.log')).open('w',encoding='utf-8') as stream,contextlib.redirect_stdout(stream):
                    code=run_canonical(root,config,no_review=True,scan_id=name)
                assert code in {0,1,2},code
            provider=EvidenceProvider(data/'scans'/name/'scan.db');provider.validate(deep=True)
            if name=='first':
                original_provider=provider
                sid=provider.symbols(search='HCLK')['items'][0]['symbol_id']
                old=ReviewStore(provider.path.parent/'reviews.db',provider.metadata())
                event=old.history(sid)[0] if args.reuse_fixture else old.append(sid,provider.fingerprint(sid),reviewer='F030继承自动化验收声明',
                    decision='CONFIRMED_SAFE',comment='仅测试继承与撤销，不是固件安全结论')
                old_static=sha256(provider.path)
        current=ReviewStore(provider.path.parent/'reviews.db',provider.metadata())
        assert original_provider.metadata()['facts_hash']==provider.metadata()['facts_hash']
        assert current.current(sid,provider.fingerprint(sid))['inherited']
        assert current.history()==[]
        result['tests'].append('REAL_F030_REPEAT_NATIVE_FULL_FACTS_EQUAL_AND_INHERITED')
        archive=work/'before.ecra-report';export_report(provider.path.parent,archive)
        imported=import_report(archive,work/'offline')
        offline=work/'offline/scans'/imported['scan_id']
        session=work/'session.json';log=(work/'server.log').open('wb')
        server=subprocess.Popen([sys.executable,'-B','-X','utf8','-m','ecra.studio','--data-root',str(data),
            '--no-browser','--session-file',str(session)],cwd=TOOL,stdout=log,stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        deadline=time.monotonic()+60
        while not session.exists():
            if server.poll() is not None or time.monotonic()>deadline:raise RuntimeError('Studio failed to start')
            time.sleep(.1)
        info=json.loads(session.read_text('utf-8'));base='http://'+info['authority']
        while True:
            try:
                urllib.request.urlopen(urllib.request.Request(base+'/api/bootstrap',headers={'X-ECRA-Session':info['token']}),timeout=2).close();break
            except OSError:
                if time.monotonic()>deadline:raise
                time.sleep(.1)
        from playwright.sync_api import sync_playwright,expect
        playwright=sync_playwright().start();browser=playwright.chromium.launch(channel='chrome',headless=True)
        page=browser.new_page(viewport=dict(width=1366,height=768))
        page.on('pageerror',lambda e:result['page_errors'].append(str(e)))
        page.on('request',lambda r:result['external_requests'].append(r.url) if not r.url.startswith(base) else None)
        page.goto(info['url']);page.get_by_role('link',name='历史与对比',exact=True).click()
        page.get_by_label('归档 second',exact=True).get_by_role('button',name='继续人工确认',exact=True).click()
        expect(page.locator('.activity')).to_have_count(0,timeout=30000)
        page.get_by_label('人工状态',exact=True).select_option('')
        page.get_by_label('查找变量、文件或规范身份',exact=True).fill('HCLK')
        page.get_by_role('button',name='搜索',exact=True).click()
        expect(page.locator('.symbol')).to_have_count(1,timeout=30000)
        page.locator('.symbol').click()
        expect(page.locator('.review-controls')).to_contain_text('沿用：人工确认无风险')
        expect(page.locator('.review-controls')).to_contain_text('F030继承自动化验收声明')
        page.get_by_role('tab',name='人工历史',exact=True).click()
        expect(page.get_by_role('heading',name='不可变确认历史 · 0 个本轮事件',exact=True)).to_be_visible()
        shot=work/'01-inherited-source.png';page.screenshot(path=str(shot),full_page=True);result['screenshots'].append(str(shot))
        page.get_by_label('确认者',exact=True).fill('撤销自动化验收声明')
        page.get_by_label('依据 / 修改或撤销理由',exact=True).fill('撤回测试依据，保留原历史')
        page.get_by_role('button',name='撤销上次确认',exact=True).click()
        expect(page.locator('.conclusion')).to_contain_text('需重新确认',timeout=30000)
        page.reload();expect(page.locator('.activity')).to_have_count(0,timeout=30000)
        page.locator('.symbol').click()
        expect(page.locator('.conclusion')).to_contain_text('需重新确认',timeout=30000)
        shot=work/'02-undo-reloaded.png';page.screenshot(path=str(shot),full_page=True);result['screenshots'].append(str(shot))
        result['tests'].append('REAL_CHROME_SOURCE_AND_ZERO_CURRENT_EVENTS_UNDO_RELOAD')
        delta=work/'undo.ecra-review-delta';export_delta(provider.path.parent,delta)
        assert import_delta(delta,offline)['imported_events']==1
        assert import_delta(delta,offline)['imported_events']==0
        restored=ReviewStore(offline/'reviews.db',provider.metadata())
        assert restored.current(sid,provider.fingerprint(sid))['decision']=='RECHECK_REQUIRED'
        result['tests'].append('INDEPENDENT_FULL_IMPORT_AND_UNDO_DELTA_IDEMPOTENT')
        assert old.history()==[event] and sha256(original_provider.path)==old_static
        assert not [str(p) for p,v in originals.items() if (sha256(p),p.stat().st_size,p.stat().st_mtime_ns)!=v]
        assert not [str(p) for p,h in engine.items() if sha256(p)!=h]
        result.update(passed=not result['page_errors'] and not result['external_requests'],
            original_files_unchanged=True,engine_unchanged=True,native_facts_hash=provider.metadata()['facts_hash'],
            source_events_unchanged=True,current_events=len(current.history()),firmware_files=len(originals))
    except BaseException:
        import traceback
        result['error']=traceback.format_exc();raise
    finally:
        if browser:browser.close()
        if playwright:playwright.stop()
        if server:
            server.terminate();server.wait(timeout=30)
        if log:log.close()
        save()
    print(json.dumps(result,ensure_ascii=True),flush=True)
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
