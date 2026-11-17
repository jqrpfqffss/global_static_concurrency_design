"""Real Chrome read/preflight check; explicitly NOT a model acceptance."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.request


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for key in ('engine', 'python', 'data', 'evidence'):
        p.add_argument('--'+key, type=Path, required=True)
    p.add_argument('--scan', required=True)
    p.add_argument('--config', type=Path, help='Explicitly save this profile through the production API before the UI check')
    args = p.parse_args()
    sys.path.insert(0,str(args.engine))
    from ecra.runtime_storage import initialize
    from ecra.workspace import managed_path
    from ecra.common import write_json
    initialize()
    evidence = managed_path(args.evidence)
    evidence.mkdir(parents=True,exist_ok=True)
    session = managed_path(args.data/'work/browser-session.json')
    session.unlink(missing_ok=True)
    env = dict(os.environ, PYTHONPATH=str(args.engine), PYTHONIOENCODING='utf-8')
    env.pop('ECRA_CONFIG_HOME',None)
    report = dict(passed=False, level='UI_AND_NO_MODEL_PREFLIGHT', model_calls=0)
    with (evidence/'server.log').open('wb') as log:
        server = subprocess.Popen([str(args.python),'-B','-m','ecra.studio','--data-root',str(args.data),
            '--no-browser','--session-file',str(session)],cwd=args.engine,env=env,stdout=log,
            stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            deadline = time.monotonic()+45
            while not session.exists():
                if server.poll() is not None or time.monotonic()>deadline: raise TimeoutError('Studio startup failed')
                time.sleep(.1)
            info = json.loads(session.read_text('utf-8'))
            base = 'http://'+info['authority']
            def api(path, body=None):
                request = urllib.request.Request(base+'/api'+path,
                    data=None if body is None else json.dumps(body).encode(),
                    headers={'X-ECRA-Session':info['token'], 'Content-Type':'application/json', 'Origin':base})
                with urllib.request.urlopen(request,timeout=30) as response:return json.load(response)
            while True:
                try:report['bootstrap']=api('/bootstrap');break
                except OSError:
                    if time.monotonic()>deadline:raise
                    time.sleep(.1)
            if args.config:
                from ecra.scan_store import EvidenceProvider
                binding = EvidenceProvider(args.data/'scans'/args.scan/'scan.db').metadata()
                profile = api('/profiles', dict(id=binding['profile_id'], yaml=args.config.read_text('utf-8-sig')))
                report['profile'] = {key:profile.get(key) for key in ('id','project_id','revision')}
            tasks_before=api('/tasks')
            from playwright.sync_api import sync_playwright, expect
            with sync_playwright() as pw:
                browser=pw.chromium.launch(channel='chrome',headless=True)
                page=browser.new_page(viewport={'width':1440,'height':1000})
                page.goto(info['url'])
                (evidence/'initial-page.txt').write_text(page.locator('body').inner_text(),encoding='utf-8')
                page.get_by_role('link',name='历史与对比',exact=True).click()
                page.get_by_label('归档 '+args.scan,exact=True).get_by_role('button',name='打开结果',exact=True).click()
                page.get_by_role('link',name='OpenCode 复核',exact=True).click()
                page.get_by_text('复核配置与执行说明',exact=True).click()
                expect(page.get_by_role('button',name='检查 OpenCode（不调用模型）',exact=True)).to_be_enabled()
                with page.expect_response(lambda r:r.url.endswith('/profiles/opencode-check'),timeout=90000) as response:
                    page.get_by_role('button',name='检查 OpenCode（不调用模型）',exact=True).click()
                report['preflight']=response.value.json()
                expect(page.get_by_role('button',name='检查 OpenCode（不调用模型）',exact=True)).to_be_enabled(timeout=90000)
                page.screenshot(path=str(evidence/'review.png'),full_page=True)
                (evidence/'review-page.txt').write_text(page.locator('body').inner_text(),encoding='utf-8')
                browser.close()
            assert tasks_before==api('/tasks'), 'Reading/checking must not dispatch review tasks'
            assert Path(report['bootstrap']['runtime']['module']).is_relative_to(args.engine)
            report['archive_api']=api('/scans/'+args.scan+'/ai')
            report['passed']=report['preflight']['ready']
        except BaseException as exc:
            report['error']=type(exc).__name__+': '+str(exc)
            raise
        finally:
            write_json(evidence/'result.json',report)
            server.terminate()
            server.wait(timeout=10)
            log.flush()
            raw = (evidence/'server.log').read_text('utf-8',errors='replace')
            log.seek(0);log.truncate()
            log.write(re.sub(r'(#session=)[A-Za-z0-9_-]+',r'\1<redacted>',raw).encode('utf-8'))
    return 0 if report['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
