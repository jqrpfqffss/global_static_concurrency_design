"""Real Chrome fault injection: missing CMake/Ninja/Git in private tool roots.

Uses current source with intentionally incomplete private Portable asset roots.
Ninja case copies the actual CMake distribution; no API/tool process is mocked.
Neither an installed package nor original firmware is edited. Not G8 clean-PC QA.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback
import urllib.request

TOOL=Path(__file__).resolve().parents[1];sys.path.insert(0,str(TOOL))
from ecra.report_package import sha256
from ecra.config import read_yaml,configured_project_root
from ecra.workspace import studio_data_root,no_links


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['config','tool-bundle','work','evidence']:parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();work=studio_data_root(args.work.resolve());work.mkdir(parents=True,exist_ok=False)
    output=no_links(args.evidence.resolve());output.mkdir(parents=True,exist_ok=False)
    root=configured_project_root(args.config)
    before={p:(sha256(p),p.stat().st_mtime_ns) for p in root.rglob('*') if p.is_file()}
    receipt=dict(passed=False,scope=__doc__,tests=[],page_errors=[],external_requests=[],screenshots=[])
    from playwright.sync_api import sync_playwright,expect
    try:
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch(channel='chrome',headless=True)
            for kind,field in [('cmake','analysis.cmake'),('ninja','analysis.cmake.generator'),('git','analysis.git_diff')]:
                case=work/kind;case.mkdir();tools=case/'deliberately-incomplete-assets';tools.mkdir()
                (tools/'portable-lock.json').write_text('{"versions":{},"version_patterns":{}}','utf-8')
                if kind=='ninja':
                    shutil.copytree(args.tool_bundle/'tools/cmake',tools/'tools/cmake')
                cfg=read_yaml(args.config);cfg['analysis']['output']=dict(location='user')
                if kind!='git':
                    cfg['analysis'].pop('compile_database',None);cfg['analysis']['cmake']=dict(generator='Ninja',build=True,location='workspace')
                else:cfg['analysis']['git_diff']=dict(enabled=True,base_ref='HEAD^',current_ref='HEAD',include_uncommitted=False)
                session=case/'session.json';log=(case/'server.log').open('wb')
                env=dict(os.environ,ECRA_PORTABLE_ROOT=str(tools),PYTHONIOENCODING='utf-8')
                server=subprocess.Popen([sys.executable,'-B','-X','utf8','-m','ecra.studio','--no-browser','--data-root',str(case/'data'),'--session-file',str(session)],cwd=TOOL,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                context=None
                try:
                    deadline=time.monotonic()+45
                    while not session.exists():
                        if server.poll() is not None or time.monotonic()>deadline:raise RuntimeError('Fault-injection Studio did not start')
                        time.sleep(.1)
                    info=json.loads(session.read_text('utf-8'));base='http://'+info['authority']
                    while True:
                        try:urllib.request.urlopen(urllib.request.Request(base+'/api/bootstrap',headers={'x-ecra-session':info['token']}),timeout=1).close();break
                        except OSError:
                            if time.monotonic()>deadline:raise
                            time.sleep(.1)
                    context=browser.new_context(viewport=dict(width=1366,height=768),record_video_dir=str(output/(kind+'-video')))
                    context.tracing.start(screenshots=True,snapshots=True,sources=True);page=context.new_page()
                    page.on('pageerror',lambda e:receipt['page_errors'].append(str(e)))
                    page.on('request',lambda r:receipt['external_requests'].append(r.url) if not r.url.startswith(base) else None)
                    page.goto(info['url']);page.get_by_role('link',name='工程配置',exact=True).click()
                    page.get_by_label('工程名称',exact=True).fill('缺工具故障验收');page.get_by_label('固件目录（绝对路径）',exact=True).fill(str(root))
                    for _ in range(3):page.get_by_role('button',name='下一步',exact=True).click()
                    page.get_by_label('高级完整 YAML',exact=True).fill(json.dumps(cfg,ensure_ascii=False))
                    page.get_by_role('button',name='检查配置与工具路径',exact=True).click();expect(page.get_by_role('button',name='保存独立配置',exact=True)).to_be_enabled()
                    page.get_by_role('button',name='保存独立配置',exact=True).click()
                    panel=page.get_by_role('region',name='真实构建预检查')
                    panel.get_by_role('button',name='检查真实构建',exact=True).click()
                    alert=panel.get_by_role('alert').filter(has_text='检查未通过');expect(alert).to_be_visible(timeout=60000)
                    expect(alert).to_contain_text(field);expect(alert).to_contain_text(kind);expect(alert).to_contain_text('修复')
                    expect(page.get_by_role('button',name='开始此配置扫描',exact=True)).to_be_disabled()
                    assert not (case/'data/scans').exists()
                    path=output/(kind+'-missing.png');page.screenshot(path=str(path),full_page=True);receipt['screenshots'].append(str(path))
                    receipt['tests'].append(dict(name='actual_missing_'+kind+'_blocks_before_native_data',status='PASS',required_field=field,asset_root=str(tools)))
                    print('PASS missing '+kind,flush=True)
                finally:
                    if context:context.tracing.stop(path=str(output/(kind+'-trace.zip')));context.close()
                    server.terminate();server.wait(timeout=30);log.close()
            browser.close()
        assert before=={p:(sha256(p),p.stat().st_mtime_ns) for p in root.rglob('*') if p.is_file()}
        assert not receipt['page_errors'] and not receipt['external_requests']
        receipt.update(passed=True,original_files_unchanged=len(before))
    except BaseException:
        receipt['error']=traceback.format_exc();raise
    finally:
        (output/'acceptance.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),'utf-8')
        print(json.dumps(dict(passed=receipt['passed'],tests=len(receipt['tests']),evidence=str(output)),ensure_ascii=False))


if __name__=='__main__':main()
