"""Opt-in Windows REAL CLI + REAL MODEL + existing verified project checkpoint.

Uses Studio's production task API, input gates, archive reader and stop/resume.
No simulated answers, synthetic facts, altered firmware, or implicit DB switch.
The executable, model, engine, checkpoint and any shared DB must be explicit.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('engine', 'python', 'data', 'config', 'exe', 'evidence'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--scan', required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--count', type=int, default=5)
    parser.add_argument('--database', type=Path)
    parser.add_argument('--pause', action='store_true')
    args = parser.parse_args()
    sys.path.insert(0, str(args.engine))
    import yaml
    from ecra.common import read_json, write_json
    from ecra.workspace import managed_path
    from ecra.scan_persistence import runtime
    from ecra.scan_store import EvidenceProvider
    out = managed_path(args.data/'scans'/args.scan)
    evidence = managed_path(args.evidence)
    evidence.mkdir(parents=True, exist_ok=True)
    cfg = yaml.safe_load(args.config.read_text('utf-8-sig'))
    rows = runtime(out)['reviews']
    selected = [r['finding_id'] for r in rows if r['state'] == 'PENDING'][:args.count]
    if not selected:
        raise ValueError('No pending real candidates; this driver never silently re-reviews DONE items')
    binding = EvidenceProvider(out/'scan.db').metadata()
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    result = dict(level='REAL_CLI_REAL_MODEL', required_enterprise_acceptance=False, passed=False,
                  engine=str(args.engine), exe=str(args.exe), executable_sha256=sha(args.exe),
                  database=str(args.database) if args.database else 'ECRA_PRIVATE_DATABASE',
                  project=cfg['project']['root'], scan=args.scan, finding_ids=selected,
                  entire_project_candidates=len(rows), static_before=sha(out/'scan.db'), stages=[])
    def save():
        write_json(evidence/'result.json', result)
    save()
    env = dict(os.environ, PYTHONPATH=str(args.engine), PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1')
    env.pop('ECRA_PORTABLE_ROOT', None)
    env.pop('ECRA_CONFIG_HOME', None)
    if args.database:
        env['OPENCODE_DB'] = str(args.database.resolve())
    elif env.get('OPENCODE_DB'):
        raise ValueError('Inherited OPENCODE_DB must be acknowledged with --database; refusing implicit replacement')
    cfg['review'].update(enabled=True, command=[str(args.exe.resolve())], model=args.model, retries=0,
                         workers=1 if args.pause else 3, finding_ids=selected,
                         session_cleanup={'enabled': not args.pause})
    session = args.data/'work/opencode-acceptance-session.json'
    server = None
    log = None
    profile = None
    def start_server():
        nonlocal server, log, info, base
        session.unlink(missing_ok=True)
        log = (evidence/('studio-'+str(len(result['stages']))+'.log')).open('wb')
        server = subprocess.Popen([str(args.python), '-B', '-m', 'ecra.studio', '--no-browser',
            '--data-root', str(args.data), '--session-file', str(session)], cwd=args.engine, env=env,
            stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
        deadline = time.monotonic()+45
        while not session.is_file():
            if server.poll() is not None or time.monotonic()>deadline:
                raise RuntimeError('Studio did not start')
            time.sleep(.1)
        info = read_json(session)
        base = 'http://'+info['authority']
        while True:
            try:
                boot = api('/bootstrap')
                break
            except OSError:
                if time.monotonic()>deadline:
                    raise
                time.sleep(.1)
        result.setdefault('runtime', []).append(boot)
    def api(path, body=None):
        req = urllib.request.Request(base+'/api'+path, data=None if body is None else json.dumps(body).encode(),
            headers={'X-ECRA-Session': info['token'], 'Content-Type': 'application/json', 'Origin': base})
        with urllib.request.urlopen(req, timeout=90) as response:
            return json.load(response)
    def stop_server():
        nonlocal server, log
        if server:
            server.terminate()
            server.wait(timeout=10)
            server = None
        if log:
            log_path = Path(log.name)
            log.close()
            raw = log_path.read_text('utf-8',errors='replace')
            log_path.write_text(re.sub(r'(#session=)[A-Za-z0-9_-]+',r'\1<redacted>',raw),encoding='utf-8')
            log = None
    def profile_save():
        nonlocal profile
        payload = dict(id=profile['id'] if profile else binding['profile_id'], yaml=yaml.safe_dump(cfg, allow_unicode=True))
        if profile:
            payload['revision'] = profile['revision']
        profile = api('/profiles', payload)
    def task_start():
        task = api('/tasks', dict(project_id=profile['project_id'], profile_id=profile['id'],
            revision=profile['revision'], mode='review-resume', scan_id=args.scan))
        result['stages'].append(dict(task_id=task['id'], workers=cfg['review']['workers'], cleanup=cfg['review']['session_cleanup']['enabled']))
        save()
        return task
    def monitor(task, pause=False):
        deadline = time.monotonic()+1800
        requested = False
        while True:
            page = api('/scans/'+args.scan+'/ai')
            current = runtime(out)['reviews']
            done = [r for r in current if r['finding_id'] in selected and r['state']=='DONE']
            if pause and done and len(done)<len(selected) and not requested:
                api('/tasks/'+task['id']+'/stop', {})
                requested = True
                result['before_restart'] = {r['finding_id']:r['execution']['stdout_sha256'] for r in done}
                save()
            task = api('/tasks/'+task['id'])
            if task['state'] in {'COMPLETE','FAILED','INTERRUPTED'}:
                result['stages'][-1].update(state=task['state'], progress=page.get('progress'), error=task.get('error'))
                save()
                if pause and not requested:
                    raise RuntimeError('Task ended before a partial archive could be paused: '+str(task.get('error')))
                if task['state']=='FAILED':
                    raise RuntimeError('Production task failed: '+str(task.get('error')))
                return
            if time.monotonic()>deadline:
                api('/tasks/'+task['id']+'/stop', {})
                raise TimeoutError('Acceptance stopped its own task after 1800 seconds')
            time.sleep(1)
    info, base = {}, ''
    try:
        start_server()
        profile_save()
        result['preflight'] = api('/profiles/opencode-check', dict(project_id=profile['project_id'], profile_id=profile['id']))
        save()
        if not result['preflight']['ready']:
            raise RuntimeError(result['preflight'].get('error'))
        monitor(task_start(), args.pause)
        if args.pause:
            stop_server()
            start_server()
            cfg['review'].update(workers=3, session_cleanup={'enabled':True})
            profile_save()
            monitor(task_start())
        current = runtime(out)['reviews']
        chosen = [r for r in current if r['finding_id'] in selected]
        result['archived'] = sum(r['state']=='DONE' for r in chosen)
        result['cli_attempts'] = sum(len(r.get('attempts',[])) for r in chosen)
        result['states'] = {r['finding_id']:r['state'] for r in chosen}
        result['capabilities'] = api('/scans/'+args.scan+'/ai').get('opencode')
        for row in chosen:
            if row['state']!='DONE':
                result.setdefault('errors', []).append(row.get('error'))
                continue
            if row['finding_id'] in result.get('before_restart', {}):
                assert row['execution']['stdout_sha256']==result['before_restart'][row['finding_id']]
            for key in ('stdout','stderr','prompt','packet'):
                from urllib.parse import urlencode
                artifact = api('/scans/'+args.scan+'/ai-artifact?'+urlencode(dict(finding_id=row['finding_id'], name=row['execution'][key+'_file'])))
                assert 'text' in artifact
        result['static_after'] = sha(out/'scan.db')
        assert result['static_before']==result['static_after']
        from playwright.sync_api import sync_playwright
        with sync_playwright() as browser_runtime:
            browser = browser_runtime.chromium.launch(channel='chrome', headless=True)
            page = browser.new_page(viewport=dict(width=1440,height=1000))
            page.goto(info['url'])
            page.get_by_role('link',name='历史与对比',exact=True).click()
            page.get_by_label('归档 '+args.scan,exact=True).get_by_role('button',name='打开结果',exact=True).click()
            page.get_by_role('link',name='OpenCode 复核',exact=True).click()
            page.get_by_text('复核配置与执行说明',exact=True).click()
            page.screenshot(path=str(evidence/'studio-archive.png'),full_page=True)
            (evidence/'studio-text.txt').write_text(page.locator('body').inner_text(),encoding='utf-8')
            browser.close()
        result['passed'] = len(chosen)==len(selected) and result['archived']==len(selected)
        save()
        return 0 if result['passed'] else 1
    except BaseException as exc:
        result['error'] = type(exc).__name__+': '+str(exc)
        result['cli_invocations_observed'] = sum(len(list((out/'review').glob(fid+'.*.attempt*.jsonl'))) for fid in selected)
        result['final_states'] = {r['finding_id']:r['state'] for r in runtime(out)['reviews'] if r['finding_id'] in selected}
        save()
        raise
    finally:
        if server:
            try:
                for task in api('/tasks')['items']:
                    if task['state'] in {'RUNNING','STARTING','STOPPING'}:
                        api('/tasks/'+task['id']+'/stop', {})
            except Exception:
                pass
        stop_server()


if __name__=='__main__':
    raise SystemExit(main())
