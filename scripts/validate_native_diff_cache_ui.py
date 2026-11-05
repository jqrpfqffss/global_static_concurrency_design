"""Real Chrome/Playwright CLI, two native Diff runs and independent archives.

Developer acceptance only: creates its own two-TU ARM Git fixture, not G2.
Requires installed Chrome, npx and a cached @playwright/cli; never downloads.
The profile is prepared through the actual API. Scan/result/evidence actions
use fresh accessibility snapshots and real UI clicks. No model or firmware
repository is accessed. Does not establish UAT, physical DPI or Portable gates.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import traceback
import urllib.request
import uuid


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine',type=Path,required=True)
    parser.add_argument('--work',type=Path,required=True)
    args=parser.parse_args();engine=args.engine.resolve();work=args.work.resolve()
    if work==engine or work.is_relative_to(engine) or engine.is_relative_to(work):
        raise ValueError('Acceptance work must be independent of the frozen engine')
    npx=shutil.which('npx.cmd' if os.name=='nt' else 'npx')
    if not npx:raise ValueError('npx and an already cached @playwright/cli are required')
    sys.path.insert(0,str(engine))
    from ecra.common import read_json,write_json
    from ecra.report_package import sha256,export_report,import_report
    from ecra.scan_store import EvidenceProvider
    from ecra.workspace import no_links,studio_data_root
    work=studio_data_root(work);work.mkdir(parents=True,exist_ok=False)
    root=work/'firmware';root.mkdir();data=work/'data'
    result=dict(passed=False,scope=__doc__,engine=str(engine),tests=[],all_gates_passed=False)
    server=log=None;browser_open=False;sequence=0;session='ecra-diff-'+uuid.uuid4().hex[:12]
    started=time.monotonic()
    def save():write_json(work/'acceptance.json',result)
    def stamps():
        return {p.relative_to(root).as_posix():dict(sha256=sha256(p),size=p.stat().st_size,mtime_ns=p.stat().st_mtime_ns)
                for p in root.rglob('*') if p.is_file()}
    def cli(*arguments):
        nonlocal sequence
        sequence+=1
        process=subprocess.run([npx,'--offline','--package','@playwright/cli','playwright-cli','-s='+session,*arguments],
            cwd=work,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',timeout=60)
        (work/('%03d-cli.log'%sequence)).write_text(process.stdout,'utf-8')
        if process.returncode:raise RuntimeError('Playwright CLI failed: '+str(arguments)+'\n'+process.stdout)
        return process.stdout
    def click(role,name):
        # No stale IDs or direct DOM interaction: every action re-snapshots.
        deadline=time.monotonic()+30
        while True:
            tree=cli('snapshot')
            matches=re.findall(r'^\s*- '+re.escape(role)+' "'+re.escape(name)+r'" \[ref=(e\d+)\]',tree,re.M)
            if len(matches)==1:return cli('click',matches[0])
            if time.monotonic()>deadline:raise ValueError('Missing/ambiguous enabled UI action: '+name)
            time.sleep(.5)
    save()
    try:
        (root/'main.c').write_text('int shared;void Task(void){shared=1;}void ISR(void){shared++;}\n','utf-8')
        (root/'other.c').write_text('static int other;void Other(void){other++;}\n','utf-8')
        write_json(root/'compile_commands.json',[dict(directory=str(root),file=n,
            arguments=['arm-none-eabi-gcc','-mcpu=cortex-m7','-mthumb','-c',n]) for n in ['main.c','other.c']])
        def git(*arguments):
            return subprocess.check_output(['git','-C',str(root),'-c','commit.gpgSign=false',*arguments],
                stderr=subprocess.DEVNULL,env=dict(os.environ,GIT_OPTIONAL_LOCKS='0',GIT_CONFIG_NOSYSTEM='1',
                    GIT_CONFIG_GLOBAL='NUL' if os.name=='nt' else '/dev/null')).decode().strip()
        git('init');git('config','user.name','ECRA UI acceptance');git('config','user.email','acceptance@example.invalid')
        git('add','.');git('commit','-m','controlled baseline');base=git('rev-parse','HEAD')
        (root/'main.c').write_text('int shared;void Task(void){shared=2;}void ISR(void){shared++;}\n','utf-8')
        git('commit','-am','controlled current');before=stamps();write_json(work/'source-before.json',before)
        sources={p.relative_to(engine).as_posix():sha256(p) for p in (engine/'ecra').rglob('*.py')}
        cfg=dict(version=1,project=dict(root=str(root),name='原生 Diff 连续扫描 · 自建测试工程'),
            analysis=dict(compile_database='compile_commands.json',output=dict(location='custom',custom_dir=str(data)),
                          git_diff=dict(enabled=True,base_ref=base)),
            contexts=[dict(id='task',kind='TASK',functions=['Task']),dict(id='irq',kind='ISR',functions=['ISR'])],
            review=dict(enabled=False,prepare_packets=False))
        session_file=work/'session.json';log=(work/'server.log').open('wb')
        server=subprocess.Popen([sys.executable,'-B','-X','utf8','-m','ecra.studio','--data-root',str(data),
            '--no-browser','--session-file',str(session_file)],cwd=engine,stdout=log,stderr=subprocess.STDOUT,
            env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'),creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        deadline=time.monotonic()+60
        while not session_file.is_file():
            if server.poll() is not None or time.monotonic()>deadline:raise RuntimeError('Studio did not start')
            time.sleep(.1)
        info=read_json(session_file);url='http://'+info['authority']
        def api(path,payload=None):
            request=urllib.request.Request(url+'/api'+path,data=None if payload is None else json.dumps(payload).encode(),
                headers={'X-ECRA-Session':info['token'],'Content-Type':'application/json','Origin':url})
            with urllib.request.urlopen(request,timeout=60) as response:return json.load(response)
        api('/profiles',dict(yaml=json.dumps(cfg,ensure_ascii=False)))
        cli('open',info['url'],'--browser=chrome');browser_open=True;cli('resize','1366','768')
        click('link','扫描任务');seen=set();tasks=[];archives=[];reports=[]
        for ordinal in [1,2]:
            click('button','检查并扫描');deadline=time.monotonic()+600
            while True:
                candidates=[t for t in api('/tasks')['items'] if t['id'] not in seen]
                if candidates:
                    if len(candidates)!=1:raise ValueError('Unexpected parallel UI task')
                    task=candidates[0]
                    if task['state'] in {'COMPLETE','FAILED','INTERRUPTED'}:break
                if time.monotonic()>deadline:raise TimeoutError('Native UI Diff did not complete')
                time.sleep(.5)
            if task['state']!='COMPLETE':raise ValueError('Real native task failed: '+str(task))
            seen.add(task['id']);tasks.append(task)
            out=data/'scans'/task['scan_id'];EvidenceProvider(out/'scan.db').validate(deep=True)
            report=read_json(out/'reports/global_static_concurrency.json');reports.append(report)
            expected=dict(hit=ordinal==2,corrupt=False)
            if report['git_diff']['baseline_summary_cache']!=expected:raise ValueError('Wrong baseline cache result')
            archived=no_links(report['git_diff']['pin']['base_summary_path']);archives.append(archived)
            if ordinal==1:
                first_db=sha256(out/'scan.db');summary_sha=sha256(archived)
            cli('screenshot','--filename=%02d-published.png'%ordinal)
        result['tests']+=['REAL_CHROME_TWO_NATIVE_DIFF_STARTS','SECOND_RUN_VALIDATED_SUMMARY_HIT_DISTINCT_ARCHIVES']
        if archives[0]==archives[1] or os.path.samefile(*archives) or any(sha256(p)!=summary_sha for p in archives):
            raise ValueError('Native scan pins must be independent identical archives')
        if sha256(data/'scans'/tasks[0]['scan_id']/'scan.db')!=first_db or stamps()!=before:
            raise ValueError('First authority or original source changed')
        result['tests'].append('FIRST_AUTHORITY_AND_ALL_SOURCE_BYTES_SIZE_MTIME_UNCHANGED')
        click('button','打开扫描结果');click('link','变量与风险');click('button','shared 静态疑似 待确认 main.c:1')
        tree=cli('snapshot')
        if not all(value in tree for value in ['Git 差异：','c:@F@ISR','c:@F@Task']):
            raise ValueError('Actual Diff/access evidence is absent from the workbench')
        cli('screenshot','--filename=03-shared-evidence.png');result['tests'].append('REAL_CHROME_OPEN_RESULT_SHARED_ACCESS_EVIDENCE')
        package=work/'complete.ecra-report';export_report(out,package);imported=import_report(package,work/'viewer')
        restored=work/'viewer/scans'/imported['scan_id'];left=EvidenceProvider(out/'scan.db');right=EvidenceProvider(restored/'scan.db')
        right.validate(deep=True)
        if any(left.metadata()[k]!=right.metadata()[k] for k in ['facts_hash','report_hash']):raise ValueError('Imported graph differs')
        if sha256(restored/'evidence'/summary_sha)!=summary_sha:raise ValueError('Imported baseline summary missing')
        result['tests'].append('COMPLETE_EXPORT_IMPORT_FACTS_REPORT_ROOTS_AND_BASE_SUMMARY_CAS_MATCH')
        requests=cli('requests','--all','--static');urls=re.findall(r'https?://[^\s]+',requests)
        if not urls or any(not u.startswith(url+'/') for u in urls):raise ValueError('Recorded external network request')
        console=cli('console')
        if 'Errors: 0, Warnings: 0' not in console:raise ValueError('Browser console diagnostics: '+console)
        if any(sha256(engine/p)!=hashed for p,hashed in sources.items()):raise ValueError('Engine source changed')
        result.update(passed=True,tasks=[{k:t[k] for k in ['id','state','started','finished']} for t in tasks],
            source_files=len(before),source_differences=[],engine_files=len(sources),engine_differences=[],
            cache=[r['git_diff']['baseline_summary_cache'] for r in reports],analysis_status=[r['analysis_status'] for r in reports],
            summary_sha256=summary_sha,package_sha256=sha256(package),package_bytes=package.stat().st_size,
            recorded_network_requests=len(urls),recorded_external_requests=[],browser_console_errors=0,browser_console_warnings=0,
            screenshots={p.name:sha256(p) for p in work.glob('*.png')},validator_sha256=sha256(Path(__file__)))
    except BaseException:
        result['error']=traceback.format_exc();raise
    finally:
        if browser_open:
            try:cli('close')
            except Exception:result['browser_cleanup_error']=traceback.format_exc()
        if server:
            server.terminate();server.wait(timeout=30)
        if log:log.close()
        result['seconds']=time.monotonic()-started;save()
    print(json.dumps(dict(passed=result['passed'],receipt=str(work/'acceptance.json'))),flush=True)


if __name__=='__main__':main()
