"""Real Chrome, guarded ARM CMake, staged/working/generated inputs and native Diff.

Developer acceptance in a new private three-TU Git fixture, not G2 or UAT.
Profiles are saved through the real API; task/result/evidence operations use
fresh accessibility snapshots and real clicks. Requires Chrome and an already
cached Playwright CLI. No downloads, customer repositories or live model.
"""
import argparse
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
    parser.add_argument('--exercise-retry',action='store_true',help='安全停止已固定CMake输入的任务，真实UI恢复且验证没有重新构建')
    args=parser.parse_args();engine=args.engine.resolve();sys.path.insert(0,str(engine))
    from ecra.common import read_json,write_json
    from ecra.report_package import sha256,export_report,import_report
    from ecra.scan_store import EvidenceProvider
    from ecra.workspace import studio_data_root
    work=studio_data_root(args.work)
    if work==engine or work.is_relative_to(engine) or engine.is_relative_to(work):
        raise ValueError('验收输出须在冻结引擎之外')
    npx=shutil.which('npx.cmd' if os.name=='nt' else 'npx')
    if not npx:raise ValueError('需要npx及已缓存的Playwright CLI；本脚本不下载')
    work.mkdir(parents=True,exist_ok=False);root=work/'未提交 固件';root.mkdir();data=work/'data'
    result=dict(passed=False,scope=__doc__,tests=[],engine=str(engine),all_gates_passed=False)
    session='ecra-working-cmake-'+uuid.uuid4().hex[:10];sequence=0
    server=log=None;opened=tracing=False;started=time.monotonic()
    def save():write_json(work/'acceptance.json',result)
    def stamps():
        return {p.relative_to(root).as_posix():[sha256(p),p.stat().st_size,p.stat().st_mtime_ns]
                for p in root.rglob('*') if p.is_file()}
    def cli(*values):
        nonlocal sequence
        sequence+=1
        process=subprocess.run([npx,'--offline','--package','@playwright/cli','playwright-cli','-s='+session,*values],
            cwd=work,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',timeout=60)
        (work/('%03d-cli.log'%sequence)).write_text(process.stdout,'utf-8')
        if process.returncode:raise RuntimeError('Playwright CLI失败：'+str(values)+'\n'+process.stdout)
        return process.stdout
    def click(role,name,*,prefix=False):
        deadline=time.monotonic()+30
        while True:
            tree=cli('snapshot')
            pattern=r'^\s*- '+re.escape(role)+r' "('+re.escape(name)+(r'[^"\n]*' if prefix else '')+r')" \[ref=([A-Za-z0-9_-]+)\]'
            matches=re.findall(pattern,tree,re.M)
            if len(matches)==1:return cli('click',matches[0][1])
            if time.monotonic()>deadline:raise ValueError('缺少或歧义操作：'+name)
            time.sleep(.5)
    save()
    try:
        cmake=('cmake_minimum_required(VERSION 3.20)\nproject(working_cmake C)\nset(WIDTH 1)\n'
            'configure_file(generated.h.in generated.h @ONLY)\nconfigure_file(generated.c.in generated.c @ONLY)\n'
            'add_library(firmware STATIC main.c other.c ${CMAKE_CURRENT_BINARY_DIR}/generated.c)\n'
            'target_include_directories(firmware PRIVATE ${CMAKE_CURRENT_BINARY_DIR})\n'
            'target_compile_options(firmware PRIVATE -mcpu=cortex-m7 -mthumb)\n')
        (root/'CMakeLists.txt').write_text(cmake,'utf-8')
        (root/'generated.h.in').write_text('#define BUILD_WIDTH @WIDTH@\n','utf-8')
        (root/'generated.c.in').write_text('int generated_value=@WIDTH@;\n','utf-8')
        (root/'main.c').write_text('#include "generated.h"\nint marker[BUILD_WIDTH];int shared;'
            'void Task(void){shared=1;}void ISR(void){shared++;}\n','utf-8')
        (root/'other.c').write_text('static int other;void Other(void){other++;}\n','utf-8')
        (root/'rename-before.txt').write_text('rename proof\n','utf-8');(root/'delete-before.txt').write_text('delete proof\n','utf-8')
        def git(*values):
            return subprocess.check_output(['git','-C',str(root),'-c','commit.gpgSign=false',*values],
                stderr=subprocess.DEVNULL,env=dict(os.environ,GIT_OPTIONAL_LOCKS='0',GIT_CONFIG_NOSYSTEM='1',
                GIT_CONFIG_GLOBAL='NUL' if os.name=='nt' else '/dev/null')).decode().strip()
        git('init');git('config','user.name','ECRA private acceptance');git('config','user.email','acceptance@example.invalid')
        git('add','.');git('commit','-m','actual CMake baseline');base=git('rev-parse','HEAD')
        (root/'CMakeLists.txt').write_text(cmake.replace('WIDTH 1','WIDTH 2'),'utf-8');git('add','CMakeLists.txt')
        (root/'CMakeLists.txt').write_text(cmake.replace('WIDTH 1','WIDTH 3'),'utf-8')
        main=root/'main.c';main.write_text('#include "working-only.h"\n'+main.read_text('utf-8'),'utf-8')
        (root/'working-only.h').write_text('extern int shared;\n','utf-8')
        git('mv','rename-before.txt','rename-after.txt');(root/'delete-before.txt').unlink()
        before=stamps();write_json(work/'source-before.json',before)
        engine_files={p.relative_to(engine).as_posix():sha256(p) for p in (engine/'ecra').rglob('*.py')}
        cfg=dict(version=1,project=dict(root=str(root),name='CMake 工作字节 · 自建验收工程'),
            analysis=dict(compile_database='auto',output=dict(location='custom',custom_dir=str(data)),
                cmake=dict(build_dir='build/ecra',generator='Ninja',build=True,clean_before_configure=False,
                    args=['-DCMAKE_SYSTEM_NAME=Generic','-DCMAKE_C_COMPILER=arm-none-eabi-gcc','-DCMAKE_TRY_COMPILE_TARGET_TYPE=STATIC_LIBRARY']),
                git_diff=dict(enabled=True,base_ref=base,current_ref='HEAD',include_uncommitted=True,verify_against_full=True)),
            contexts=[dict(id='task',kind='TASK',functions=['Task']),dict(id='irq',kind='ISR',functions=['ISR'])],
            review=dict(enabled=False,prepare_packets=False))
        session_file=work/'session.json';log=(work/'server.log').open('wb')
        server=subprocess.Popen([sys.executable,'-B','-X','utf8','-m','ecra.studio','--data-root',str(data),
            '--no-browser','--session-file',str(session_file)],cwd=engine,stdout=log,stderr=subprocess.STDOUT,
            env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'),creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        deadline=time.monotonic()+60
        while not session_file.is_file():
            if server.poll() is not None or time.monotonic()>deadline:raise RuntimeError('Studio启动失败')
            time.sleep(.1)
        info=read_json(session_file);url='http://'+info['authority']
        def api(path,payload=None):
            request=urllib.request.Request(url+'/api'+path,data=None if payload is None else json.dumps(payload).encode(),
                headers={'X-ECRA-Session':info['token'],'Content-Type':'application/json','Origin':url})
            with urllib.request.urlopen(request,timeout=60) as response:return json.load(response)
        profile=api('/profiles',dict(yaml=json.dumps(cfg,ensure_ascii=False)));result['profile_id']=profile['id'];save()
        cli('open',info['url'],'--browser=chrome');opened=True;cli('tracing-start');tracing=True;cli('resize','1366','768')
        click('link','扫描任务');click('button','检查并扫描');deadline=time.monotonic()+3600
        stopped=None
        if args.exercise_retry:
            while True:
                tasks=api('/tasks')['items']
                if tasks:
                    stopped=tasks[0]
                    if stopped['state'] in {'FAILED','COMPLETE','INTERRUPTED'}:raise ValueError('固定输入前任务已结束：'+stopped['state'])
                    if (data/'work/tasks'/stopped['id']/'fixed-inputs/capture-plan.json').is_file():break
                if time.monotonic()>deadline:raise TimeoutError('未形成完整CMake固定输入')
                time.sleep(.2)
            click('button','安全停止')
            while True:
                stopped=api('/tasks/'+stopped['id'])
                if stopped['state'] in {'FAILED','COMPLETE','INTERRUPTED'}:break
                if time.monotonic()>deadline:raise TimeoutError('安全停止未结束')
                time.sleep(.2)
            assert stopped['state']=='INTERRUPTED',stopped['state']
            assert not (data/'scans'/stopped['scan_id']/'manifest.json').exists()
            def builds():
                return {str(p):sha256(p/'.ecra-write-guard') for p in (data/'projects').glob('*/builds/working-cmake-*')
                    if re.fullmatch(r'working-cmake-[0-9a-f]{32}',p.name)}
            before_builds=builds();assert len(before_builds)==2
            cli('screenshot','--filename=00-safe-stopped.png');click('button','从已验证 TU 恢复 / 重试')
            result['tests'].append('REAL_CHROME_STOP_AFTER_COMPLETE_FIXED_INPUTS_AND_RETRY');save()
        while True:
            tasks=[t for t in api('/tasks')['items'] if stopped is None or t['id']!=stopped['id']]
            if tasks:
                if len(tasks)!=1:raise ValueError('出现非本轮任务')
                task=tasks[0]
                if task['state'] in {'COMPLETE','FAILED','INTERRUPTED'}:break
            if time.monotonic()>deadline:raise TimeoutError('未提交CMake真实任务超时')
            time.sleep(1)
        if task['state']!='COMPLETE':
            detail=api('/tasks/'+task['id']);write_json(work/'failed-task.json',detail)
            raise ValueError('真实任务失败：'+str(detail.get('error') or detail.get('failure',{}).get('message')))
        if stopped is not None:
            detail=api('/tasks/'+task['id']);assert detail['reused_working_inputs']['source_task']==stopped['id']
            assert builds()==before_builds
            reused=read_json(data/'work/tasks'/task['id']/'reused-working-inputs.json')
            assert reused['config']==str(data/'work/tasks'/stopped['id']/'semantics.yaml')
            result['tests'].append('RETRY_REUSES_ORIGINAL_BUILD_GENERATED_INPUTS_AND_CONFIG_WITHOUT_CMAKE')
        result['tests'].append('REAL_CHROME_CMAKE_WORKING_NATIVE_TASK_COMMITTED');cli('screenshot','--filename=01-task-complete.png');save()
        out=data/'scans'/task['scan_id'];provider=EvidenceProvider(out/'scan.db');provider.validate(deep=True)
        facts,report=provider.load('facts'),provider.load('report');diff=report['git_diff']
        baseline=EvidenceProvider(diff['pin']['base_facts_path']).load('facts')
        def width(values):return next(v['size_bytes'] for v in values['variables'] if v['name']=='marker')
        assert (width(baseline),width(facts))==(4,12)
        assert len(facts['translation_units'])==3 and diff['full_verification']['state']=='PASSED'
        closure=read_json(out/'input_closure.json');assert closure['frozen_view']['proof_scope']=='COMPLETE_GUARDED_CMAKE_INPUTS_V1'
        assert not (root/'build').exists() and not (out/'facts.json').exists() and stamps()==before
        result['tests']+=['ACTUAL_STAGED2_WORKING3_BASE1_GENERATED_HEADER_AND_C_TU',
            'INDEPENDENT_UNCACHED_FULL_VERIFICATION_PASSED','SOURCE_GIT_INDEX_BYTES_SIZE_MTIME_UNCHANGED']
        click('button','打开扫描结果');click('link','变量与风险');click('button','shared ',prefix=True)
        tree=cli('snapshot')
        if not all(v in tree for v in ['Git 差异：','c:@F@ISR','c:@F@Task']):raise ValueError('详情缺少实际Diff和访问证据')
        cli('screenshot','--filename=02-working-diff-evidence-1366.png');cli('resize','1600','900')
        cli('screenshot','--filename=03-working-diff-evidence-1600.png');result['tests'].append('REAL_CHROME_WORKING_DIFF_ACCESS_EVIDENCE')
        package=work/'working-cmake.ecra-report';export_report(out,package)
        imported=import_report(package,work/'viewer');restored=EvidenceProvider(work/'viewer/scans'/imported['scan_id']/'scan.db')
        restored.validate(deep=True)
        assert all(provider.metadata()[k]==restored.metadata()[k] for k in ['facts_hash','report_hash'])
        result['tests'].append('COMPLETE_PACKAGE_IMPORT_FACTS_REPORT_HASHES_IDENTICAL')
        requests=cli('requests','--all','--static');urls=re.findall(r'https?://[^\s]+',requests)
        assert urls and all(u.startswith(url+'/') for u in urls)
        console=cli('console');assert 'Errors: 0, Warnings: 0' in console,console
        assert stamps()==before and all(sha256(engine/p)==value for p,value in engine_files.items())
        result.update(passed=True,task_id=task['id'],scan_id=task['scan_id'],source_files=len(before),source_differences=[],
            engine_files=len(engine_files),engine_differences=[],width_bytes=dict(base=4,current=12),
            full_verification=diff['full_verification'],source_authority_sha256=sha256(out/'scan.db'),
            package_sha256=sha256(package),package_bytes=package.stat().st_size,
            external_requests=[],browser_errors=0,screenshots={p.name:sha256(p) for p in work.glob('*.png')},
            validator_sha256=sha256(Path(__file__)))
    except BaseException:
        result['error']=traceback.format_exc()
        if opened:
            try:cli('snapshot');cli('screenshot','--filename=99-failure.png')
            except Exception:result['failure_capture_error']=traceback.format_exc()
        raise
    finally:
        if opened:
            if tracing:
                try:cli('tracing-stop')
                except Exception:result['trace_cleanup_error']=traceback.format_exc()
            try:cli('close')
            except Exception:result['browser_cleanup_error']=traceback.format_exc()
        if server:
            server.terminate();server.wait(timeout=30)
        if log:log.close()
        result['seconds']=time.monotonic()-started
        trace_root=work/'.playwright-cli/traces'
        result['traces']={str(p.relative_to(work)):sha256(p) for p in trace_root.rglob('*') if p.is_file()}
        save()
    print(json.dumps(dict(passed=result['passed'],receipt=str(work/'acceptance.json'))),flush=True)


if __name__=='__main__':main()
