"""Authorized input copy: working bytes -> real Chrome -> native Diff/retry.

Explicit database only. No CMake equivalence, hardware, live model, second PC,
physical DPI or UAT claim. All edits are in a newly created private Git copy.
"""
import argparse
from contextlib import redirect_stdout
import copy
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import time
import traceback
import urllib.request

TOOL=Path(__file__).resolve().parents[1];sys.path.insert(0,str(TOOL))
OWNED_WORK=None


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--work',type=Path,required=True)
    parser.add_argument('--allow-partial',action='store_true',help='仅关闭独立全量对照；基准部分解析仍按原门禁拒绝Diff，不能据此宣称完整校验通过')
    parser.add_argument('--controlled-fixture',action='store_true',help='显式标注自建原生测试工程；所有结果不计G2真实工程验收')
    args=parser.parse_args()
    import yaml
    from ecra.common import read_json,write_json
    from ecra.config import configured_project_root,load_config
    from ecra.git_diff import relocate_paths,summarize,compare
    from ecra.report_package import sha256,export_report,import_report
    from ecra.scan_persistence import run_canonical
    from ecra.scan_store import EvidenceProvider
    from ecra.workflow import checked_scan,saved_run
    from ecra.workspace import studio_data_root
    from scripts.validate_studio_baseline import strict_difference
    work=studio_data_root(args.work);original=configured_project_root(args.config)
    if work==original or work.is_relative_to(original) or original.is_relative_to(work):
        raise ValueError('验收目录必须独立于获准原工程')
    work.mkdir(parents=True,exist_ok=False)
    global OWNED_WORK
    OWNED_WORK=work
    cfg,_=load_config(original,args.config)
    database=(original/cfg['analysis']['compile_database']).resolve()
    def stamps(paths):return {str(p):(sha256(p),p.stat().st_size,p.stat().st_mtime_ns) for p in paths if p.is_file()}
    originals=stamps([args.config,database,*original.rglob('*')])
    engine=stamps((TOOL/'ecra').rglob('*.py'))
    root=work/'独立固件 副本';shutil.copytree(original,root)
    if (root/'.git').exists():raise ValueError('请提供获准的无.git源快照；不接管既有仓库')
    for path in root.rglob('*'):
        if path.is_file():path.chmod(stat.S_IREAD|stat.S_IWRITE)
    data=work/'独立 数据';os.environ.update(ECRA_DATA_ROOT=str(data),LOCALAPPDATA=str(work/'private-user'),XDG_CONFIG_HOME=str(work/'private-user'))
    def git(*values):
        return subprocess.run(['git','-c','core.autocrlf=false','-C',str(root),*values],check=True,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=120,env=dict(os.environ,GIT_OPTIONAL_LOCKS='0')).stdout.decode('utf-8').strip()
    private_db=root/'compile_commands.json';write_json(private_db,relocate_paths(read_json(database),original,root))
    git('init','-q');git('config','user.name','ECRA private acceptance');git('config','user.email','acceptance@example.invalid');git('config','core.autocrlf','false')
    (root/'rename-before.txt').write_text('rename receipt\n','utf-8');(root/'delete-before.txt').write_text('delete receipt\n','utf-8')
    git('add','.');git('commit','-qm','Independent authorized baseline');git('branch','comparison-base')
    base=git('rev-parse','HEAD')
    main=root/'main.c';raw=main.read_bytes()
    header=root/'dirty_actual_input.h';header.write_text('#define ECRA_DIRTY_VALUE 1\n','utf-8')
    main.write_bytes(b'#include "dirty_actual_input.h"\nvolatile unsigned ecra_working_value=ECRA_DIRTY_VALUE;\n'+raw)
    git('add','main.c',header.name)
    header.write_text('#include "dirty_untracked.h"\n#define ECRA_DIRTY_VALUE 2\n','utf-8')
    untracked=root/'dirty_untracked.h';untracked.write_text('// consumed untracked header\n','utf-8')
    git('mv','rename-before.txt','rename-after.txt');(root/'delete-before.txt').unlink()
    private=stamps(root.rglob('*'))
    configured=relocate_paths(yaml.safe_load(args.config.read_text('utf-8')),original,root)
    configured['project']['root']=str(root);configured['analysis']['compile_database']='compile_commands.json'
    configured['analysis']['output']=dict(location='user');configured['review'].update(enabled=False,prepare_packets=False)
    ordinary=copy.deepcopy(configured);ordinary['analysis']['git_diff']=dict(enabled=False,include_uncommitted=False)
    ordinary_config=work/'ordinary.yaml';ordinary_config.write_text(yaml.safe_dump(ordinary,allow_unicode=True),'utf-8')
    configured['analysis']['git_diff']=dict(enabled=True,base_ref='comparison-base',current_ref='HEAD',include_uncommitted=True,cache_enabled=True,verify_against_full=not args.allow_partial)
    result=dict(passed=False,scope=__doc__,input_kind='CONTROLLED_NATIVE_FIXTURE_NOT_G2' if args.controlled_fixture else 'AUTHORIZED_SOURCE_COPY',tests=[],screenshots=[],page_errors=[],external_requests=[],base_sha=base,engine=str(TOOL),staged_header_sha256=__import__('hashlib').sha256(b'#define ECRA_DIRTY_VALUE 1\n').hexdigest(),working_header_sha256=sha256(header))
    def save():write_json(work/'acceptance.json',result)
    save();server=stream=browser=playwright=None;started=time.monotonic()
    try:
        with (work/'ordinary.log').open('w',encoding='utf-8') as log,redirect_stdout(log):
            code=run_canonical(root,ordinary_config,no_review=True,scan_id='ordinary')
        assert code in {0,1,2};prior=sha256(data/'scans/ordinary/scan.db')
        session=work/'session.json';stream=(work/'server.log').open('wb')
        server=subprocess.Popen([sys.executable,'-B','-X','utf8','-m','ecra.studio','--data-root',str(data),'--no-browser','--session-file',str(session)],
            cwd=TOOL,stdout=stream,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        deadline=time.monotonic()+60
        while not session.exists():
            if server.poll() is not None or time.monotonic()>deadline:raise RuntimeError('Studio did not start')
            time.sleep(.1)
        info=read_json(session);base_url='http://'+info['authority']
        def api(path,payload=None):
            request=urllib.request.Request(base_url+'/api'+path,data=None if payload is None else json.dumps(payload).encode(),
                headers={'X-ECRA-Session':info['token'],'Content-Type':'application/json','Origin':base_url})
            with urllib.request.urlopen(request,timeout=60) as response:return json.load(response)
        while True:
            try:api('/bootstrap');break
            except OSError:
                if time.monotonic()>deadline:raise
                time.sleep(.1)
        from playwright.sync_api import sync_playwright,expect
        playwright=sync_playwright().start();browser=playwright.chromium.launch(channel='chrome',headless=True)
        page=browser.new_page(viewport=dict(width=1366,height=768))
        page.on('pageerror',lambda error:result['page_errors'].append(str(error)))
        page.on('request',lambda req:result['external_requests'].append(req.url) if not req.url.startswith(base_url) else None)
        page.goto(info['url']);page.get_by_role('link',name='工程配置',exact=True).click();page.get_by_role('button',name='新建工程配置',exact=True).click()
        page.get_by_label('工程名称',exact=True).fill('工作区实际字节验收'+(' · 自建测试工程' if args.controlled_fixture else ''));page.get_by_label('固件目录（绝对路径）',exact=True).fill(str(root))
        page.get_by_role('button',name='下一步',exact=True).click();page.get_by_label('真实构建方式',exact=True).select_option('database')
        page.get_by_label('编译数据库路径',exact=True).fill('compile_commands.json');page.get_by_role('button',name='下一步',exact=True).click()
        page.get_by_label('Diff 基准 ref（空表示全量）',exact=True).fill('comparison-base')
        page.get_by_label('纳入当前工作区未提交输入',exact=True).check();page.get_by_role('button',name='读取并核对本地 Git 版本',exact=True).click()
        expect(page.get_by_label('Git 版本选择',exact=True)).to_contain_text(base,timeout=30000)
        expect(page.get_by_label('Git 版本选择',exact=True)).to_contain_text('不是只扫描暂存区')
        shot=work/'01-real-git-working-preview.png';page.screenshot(path=str(shot),full_page=True);result['screenshots'].append(str(shot))
        page.get_by_role('button',name='下一步',exact=True).click()
        # Load the approved complete semantic configuration through the existing
        # advanced editor; do not replace contexts with wizard defaults.
        page.get_by_label('高级完整 YAML',exact=True).fill(yaml.safe_dump(configured,allow_unicode=True))
        page.get_by_role('button',name='检查配置与工具路径',exact=True).click()
        expect(page.locator('.profile-check')).to_be_visible(timeout=30000)
        page.get_by_role('button',name='保存独立配置',exact=True).click()
        expect(page.locator('.activity')).to_have_count(0,timeout=30000)
        profiles=api('/profiles')['items'];assert len(profiles)==1,profiles
        result['profile']=profiles[0];result['tests'].append('REAL_CHROME_FOUR_STEP_DATABASE_DIRTY_REF_PREVIEW_SAVE');save()
        page.get_by_role('link',name='扫描任务',exact=True).click();page.get_by_role('button',name='检查并扫描',exact=True).click()
        deadline=time.monotonic()+120
        while True:
            tasks=api('/tasks')['items']
            if tasks:
                stopped=tasks[0];detail=api('/tasks/'+stopped['id'])
                if detail.get('progress_kind')=='WORKING_INPUT_INVENTORY' and detail.get('stages'):break
            if time.monotonic()>deadline:raise TimeoutError('Capture stage unavailable')
            page.wait_for_timeout(200)
        page.get_by_role('button',name='安全停止',exact=True).click()
        while True:
            detail=api('/tasks/'+stopped['id'])
            if detail['state'] in {'COMPLETE','FAILED','INTERRUPTED'}:break
            if time.monotonic()>deadline:raise TimeoutError('Capture did not stop')
            page.wait_for_timeout(200)
        assert detail['state']=='INTERRUPTED',detail
        assert sha256(data/'scans/ordinary/scan.db')==prior
        result['stopped_task']=detail['id'];result['tests'].append('REAL_CHROME_STOP_DURING_CAPTURE_PRIOR_RESULT_UNCHANGED');save()
        page.get_by_role('button',name='从已验证 TU 恢复 / 重试',exact=True).click()
        deadline=time.monotonic()+7200;running=None;shot_saved=False
        while True:
            items=api('/tasks')['items'];running=next((item for item in items if item['id']!=stopped['id']),None)
            if running:
                detail=api('/tasks/'+running['id'])
                if not shot_saved and detail.get('stages'):
                    page.wait_for_timeout(1100);shot=work/'02-real-capture-progress.png';page.screenshot(path=str(shot),full_page=True);result['screenshots'].append(str(shot));shot_saved=True
                if detail['state'] in {'COMPLETE','FAILED','INTERRUPTED'}:break
                result['running']=dict(id=detail['id'],stage=detail.get('progress',{}).get('stage'),state=detail['state']);save()
            if time.monotonic()>deadline:raise TimeoutError('Native dirty Diff timed out')
            page.wait_for_timeout(1000)
        assert detail['state']=='COMPLETE',dict(id=detail['id'],error=detail.get('error'),failure=detail.get('failure'))
        out=data/'scans'/detail['scan_id'];provider=EvidenceProvider(out/'scan.db');provider.validate(deep=True)
        facts=provider.load('facts');report=provider.load('report');diff=report['git_diff']
        verification=diff.get('full_verification',dict(state='NOT_REQUESTED_PARTIAL_INPUT'))
        if args.allow_partial:
            assert read_json(out/'diagnostics/completion.json')['partial']>0
            assert read_json(out/'diagnostics/completion.json')['static_analysis_status']=='INCOMPLETE'
            assert 'full_verification' not in diff
        else:assert verification['state']=='PASSED',verification
        assert diff['pin']['include_uncommitted'] and diff['pin']['base_sha']==base
        identity=read_json(out/'input_closure.json')['frozen_view'];descriptor={key:identity[key] for key in ('file','sha256')}
        plan=read_json(data/'work/tasks'/running['id']/'fixed-inputs/capture-plan.json')
        assert plan['compiler_view']==descriptor
        assert read_json(data/'work/tasks'/running['id']/'preflight/preflight.json')['frozen_working_inputs']==descriptor
        requests=list((out/'workers/full-verification').glob('*.request.json'))
        assert len(requests)==(0 if args.allow_partial else 4) and all(read_json(p)['compiler_view']==descriptor for p in requests)
        ref=provider.archived_source(header.name);assert ref['sha256']==sha256(header) and ref['sha256']!=result['staged_header_sha256']
        assert provider.archived_source(untracked.name)['sha256']==sha256(untracked)
        baseline=read_json(Path(diff['pin']['base_summary_path']));calculated=compare(baseline,summarize(facts,report),diff['pin'])
        actual={key:value for key,value in diff.items() if key not in {'baseline_summary_cache','tu_cache','full_verification'}}
        assert strict_difference(calculated,actual) is None
        independent=EvidenceProvider(data/'scans/ordinary/scan.db').load('facts')
        for var in independent['variables']:
            if var['symbol_id'] in diff['impacts']:var['impact']=copy.deepcopy(diff['impacts'][var['symbol_id']])
        difference=strict_difference(facts,independent);assert difference is None,difference
        result['tests'].append('REAL_NATIVE_DIRTY_DIFF_INDEPENDENT_FULL_ZERO_FIELD_DIFF_'+('PARTIAL_PRESERVED' if args.allow_partial else 'AND_UNCACHED_FULL_VERIFICATION'))
        result.update(scan_id=detail['scan_id'],units=read_json(out/'diagnostics/completion.json')['translation_units_total'],completion=read_json(out/'diagnostics/completion.json'),full_verification=verification,frozen_view=identity,independent_facts_difference=difference);save()
        config=data/'work/tasks'/running['id']/'semantics.yaml';effective,_=load_config(root,config)
        checked_scan(root,out,effective,config,with_facts=False,_report_projection=True)
        with (work/'saved-report.log').open('w',encoding='utf-8') as log,redirect_stdout(log):
            assert saved_run(root,config,render_only=True,_out=out) in {0,1,2}
        page.get_by_role('button',name='打开扫描结果',exact=True).click();page.get_by_role('link',name='变量与风险',exact=True).click()
        expect(page.locator('.banner').filter(has_text='Git 差异：')).to_be_visible(timeout=30000)
        expect(page.locator('.activity')).to_have_count(0,timeout=30000)
        expect(page.locator('.symbol').first).to_be_visible(timeout=30000)
        page.locator('.symbol').first.click();expect(page.locator('.conclusion')).to_be_visible(timeout=30000)
        expect(page.locator('.activity')).to_have_count(0,timeout=30000)
        shot=work/'03-real-diff-workbench.png';page.screenshot(path=str(shot),full_page=True);result['screenshots'].append(str(shot))
        package=work/'dirty-complete.ecra-report';export_report(out,package);imported=import_report(package,work/'independent-viewer')
        restored=EvidenceProvider(work/'independent-viewer/scans'/imported['scan_id']/'scan.db')
        assert restored.metadata()['facts_hash']==provider.metadata()['facts_hash']
        assert restored.archived_source(header.name)['sha256']==sha256(header)
        result['tests'].append('REAL_CHECKPOINT_SAVED_REPORT_AND_FULL_PACKAGE_ARCHIVED_WORKING_HEADERS')
        for name,before in [('approved_original',originals),('private_git',private),('engine',engine)]:
            differences=[path for path,value in before.items() if not Path(path).is_file() or (sha256(path),Path(path).stat().st_size,Path(path).stat().st_mtime_ns)!=value]
            result[name+'_differences']=differences;assert not differences,(name,differences)
        assert set(private)==set(stamps(root.rglob('*')))
        result.update(passed=not result['page_errors'] and not result['external_requests'],seconds=time.monotonic()-started,all_gates_passed=False)
    except BaseException:
        result.update(error=traceback.format_exc(),seconds=time.monotonic()-started);raise
    finally:
        if browser:browser.close()
        if playwright:playwright.stop()
        if server:server.terminate();server.wait(timeout=30)
        if stream:stream.close()
        save()
    print(json.dumps(dict(passed=result['passed'],seconds=result['seconds'],receipt=str(work/'acceptance.json'))),flush=True)


if __name__=='__main__':
    try:main()
    except BaseException:
        if OWNED_WORK is not None and not (OWNED_WORK/'acceptance.json').exists():
            with (OWNED_WORK/'preparation-failure.json').open('x',encoding='utf-8') as stream:
                json.dump(dict(passed=False,stage='CONTROLLER_PREPARATION',error=traceback.format_exc()),stream,ensure_ascii=True,indent=2)
        raise
