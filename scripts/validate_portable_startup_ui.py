"""Actual ECRA.cmd Studio entry with Windows-only PATH and tool-owned workspace.

--no-browser suppresses desktop disruption but uses the actual Studio launcher
branch. Real Chrome is the external test controller; the service runs embedded
Python. Not a clean physical offline machine or literal desktop double-click.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
import urllib.request

TOOL=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(TOOL))
from ecra.studio.process_budget import ProcessBudget
from ecra.studio.write_guard import OwnedProcess
from ecra.workspace import no_links


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        while block:=stream.read(1024**2):h.update(block)
    return h.hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['bundle','work','evidence']:parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    if os.name!='nt':parser.error('Actual Windows ECRA.cmd required')
    bundle=no_links(args.bundle);work=no_links(args.work);output=no_links(args.evidence)
    if any(root==bundle or root.is_relative_to(bundle) or bundle.is_relative_to(root) for root in [work,output]):
        raise ValueError('Acceptance output cannot overlap the program')
    work.mkdir(parents=True,exist_ok=False);output.mkdir(parents=True,exist_ok=False)
    current=work/'unrelated cwd 中文';current.mkdir();local=work/'private localappdata 中文';local.mkdir()
    expected=bundle/'workspace';session=expected/'work/startup-ui-session.json'
    if expected.exists():
        raise ValueError('Use a fresh disposable bundle for startup acceptance')
    windows=Path(os.environ.get('SystemRoot','C:/Windows'))
    env=dict(os.environ,LOCALAPPDATA=str(local),PATH=os.pathsep.join(map(str,[windows/'System32',windows,windows/'System32/Wbem'])),PYTHONIOENCODING='utf-8')
    for name in ['PYTHONPATH','PYTHONHOME','ECRA_DATA_ROOT','ECRA_PORTABLE_ROOT','ECRA_CONFIG_HOME','ECRA_PATH_ALIAS_ROOT']:env.pop(name,None)
    files=[p for p in (bundle/'ecra').rglob('*') if p.is_file()]+[bundle/'ECRA.cmd',bundle/'run_ecra.py',bundle/'runtime/python.exe']
    before={p.relative_to(bundle).as_posix():(sha(p),p.stat().st_mtime_ns) for p in files}
    command=[str(windows/'System32/cmd.exe'),'/d','/c',str(bundle/'ECRA.cmd'),'--no-browser','--session-file',str(session)]
    receipt=dict(passed=False,scope=__doc__,command=command,cwd=str(current),restricted_path=env['PATH'],
                 tests=[],page_errors=[],external_requests=[],browser_downloads=[],physical_clean_offline_machine='NOT_VERIFIED',
                 literal_desktop_double_click='NOT_EXERCISED',native_windows_dpi='NOT_VERIFIED')
    process=browser=context=playwright=None;budget=ProcessBudget(512*1024**2)
    log=(work/'launcher.log').open('xb')
    def passed(name):receipt['tests'].append(dict(name=name,status='PASS',related=['U01','G8']))
    try:
        process=OwnedProcess(command,cwd=current,env=env,log=log);budget.assign(process);process.resume()
        deadline=time.monotonic()+45
        while not session.exists():
            if process.poll() is not None or time.monotonic()>deadline:raise RuntimeError('ECRA.cmd did not start Studio; see launcher.log')
            time.sleep(.1)
        info=json.loads(session.read_text('utf-8'));base='http://'+info['authority']
        while True:
            try:
                req=urllib.request.Request(base+'/api/bootstrap',headers={'X-ECRA-Session':info['token']})
                with urllib.request.urlopen(req,timeout=1) as response:bootstrap=json.load(response)
                break
            except OSError:
                if process.poll() is not None or time.monotonic()>deadline:raise
                time.sleep(.1)
        assert Path(bootstrap['data_root']).resolve()==expected.resolve()
        assert Path(bootstrap['tool_root']).resolve()==bundle
        assert not list(local.iterdir())
        assert bootstrap['sample']['available']
        import psutil
        descendants=psutil.Process(process.pid).children(recursive=True)
        executables=[p.exe() for p in descendants if p.name().lower()=='python.exe']
        assert len(executables)==1 and Path(executables[0]).resolve()==(bundle/'runtime/python.exe').resolve()
        receipt['service_python']=executables[0];passed('actual_cmd_uses_embedded_python_with_windows_only_path_and_private_default_data_root')
        from playwright.sync_api import sync_playwright,expect
        playwright=sync_playwright().start();browser=playwright.chromium.launch(channel='chrome',headless=True)
        context=browser.new_context(viewport=dict(width=1366,height=768));context.tracing.start(screenshots=True,snapshots=True,sources=True)
        page=context.new_page();page.on('pageerror',lambda error:receipt['page_errors'].append(str(error)))
        page.on('download',lambda item:receipt['browser_downloads'].append(item.suggested_filename))
        page.on('request',lambda request:receipt['external_requests'].append(request.url) if not request.url.startswith((base+'/','data:','blob:')) else None)
        page.goto(info['url'])
        for name in ['新建工程','导入历史结果','打开示例']:
            expect(page.get_by_role('button',name=name,exact=True)).to_be_in_viewport(ratio=1)
        page.screenshot(path=str(output/'01-actual-launcher-first-use.png'),full_page=True)
        passed('actual_launcher_page_has_all_three_real_first_use_actions_without_external_requests')
        page.get_by_role('button',name='打开示例',exact=True).click()
        expect(page.get_by_role('heading',name='先处理需要核实的变量',exact=True)).to_be_visible(timeout=30000)
        expect(page.get_by_text('教学示例 · 真实扫描归档 · 非用户工程',exact=False).first).to_be_visible(timeout=30000)
        expect(page.get_by_role('button',name='打开示例',exact=True)).to_be_visible()
        assert list((expected/'scans').glob('*/scan.db'))
        page.screenshot(path=str(output/'02-actual-launcher-real-sample.png'),full_page=True)
        passed('actual_launcher_imports_complete_builtin_native_archive_into_tool_workspace')
        page.get_by_role('link',name='设置与验收状态',exact=True).click()
        expect(page.get_by_role('heading',name='工具数据目录',exact=True)).to_be_visible()
        expect(page.get_by_role('button',name='打开数据目录',exact=True)).to_be_visible()
        expect(page.get_by_text(str(expected),exact=False).first).to_be_visible()
        passed('settings_shows_the_active_tool_directory_and_open_action')
        page.get_by_role('link',name='数据与共享',exact=True).click()
        page.get_by_role('combobox',name='完整包压缩').select_option('deflate')
        page.get_by_role('button',name='导出标准完整包',exact=True).click()
        expect(page.get_by_role('button',name='打开结果包所在目录',exact=False)).to_be_visible(timeout=45000)
        exports=list((expected/'exports').glob('*.ecra-report'))
        assert len(exports)==1 and exports[0].is_file()
        expect(page.get_by_text(str(exports[0]),exact=True)).to_be_visible()
        assert not receipt['browser_downloads']
        passed('complete_export_lands_in_tool_workspace_without_a_browser_download')
        assert before=={p.relative_to(bundle).as_posix():(sha(p),p.stat().st_mtime_ns) for p in files}
        assert not list((bundle/'ecra').rglob('__pycache__'))
        assert not receipt['page_errors'] and not receipt['external_requests']
        assert not list(local.iterdir())
        receipt.update(program_bytes_and_mtime_unchanged=True,data_root=str(expected),job=budget.sample())
        passed('launch_and_sample_leave_all_checked_program_assets_unchanged')
        receipt['passed']=True
    except BaseException:
        receipt['error']=traceback.format_exc()
        if context:
            try:context.pages[0].screenshot(path=str(output/'failure.png'),full_page=True)
            except Exception:pass
        raise
    finally:
        if context:context.tracing.stop(path=str(output/'trace.zip'));context.close()
        if browser:browser.close()
        if playwright:playwright.stop()
        budget.close()
        if process is not None:
            process.wait(timeout=30);process.close()
        log.close();(output/'acceptance.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),'utf-8')
        print(json.dumps(dict(passed=receipt['passed'],tests=len(receipt['tests']),evidence=str(output)),ensure_ascii=False),flush=True)
    return 0 if receipt['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
