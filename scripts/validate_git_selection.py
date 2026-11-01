"""Real Chrome/Git wizard selection, SHA preview, persistence and read-only proof.

Uses an isolated copy of the approved F030 input; its extra refs/dirty files are
explicit UI fixtures. Does not claim a new native G2 project or full U04/UAT.
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


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['firmware','compile-database','work','evidence']:parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--engine',type=Path,default=TOOL)
    parser.add_argument('--python',type=Path,default=Path(sys.executable))
    args=parser.parse_args();work=args.work.resolve();work.mkdir(parents=True,exist_ok=False)
    output=args.evidence.resolve();output.mkdir(parents=True,exist_ok=True)
    source_before={str(p.relative_to(args.firmware)):sha256(p) for p in args.firmware.rglob('*') if p.is_file()}
    database_before=sha256(args.compile_database)
    repo=work/'版本选择固件';shutil.copytree(args.firmware,repo)
    def git(*parts,input=None):
        env=dict(os.environ,GIT_CONFIG_GLOBAL='NUL' if os.name=='nt' else '/dev/null',GIT_CONFIG_NOSYSTEM='1',GIT_OPTIONAL_LOCKS='0')
        return subprocess.check_output(['git','-c','commit.gpgSign=false','-C',str(repo),*parts],input=input,env=env,stderr=subprocess.DEVNULL).decode('utf-8').strip()
    # The original compile database is only read. Versioned commands refer to
    # this isolated copy, retaining the actual compiler and argument ordering.
    from ecra.git_diff import relocate_paths
    commands=json.loads(args.compile_database.read_text(encoding='utf-8-sig'))
    (repo/'compile_commands.json').write_text(json.dumps(relocate_paths(commands,args.firmware.resolve(),repo),ensure_ascii=False),encoding='utf-8')
    git('init');git('config','user.name','ECRA UI acceptance');git('config','user.email','test@example.invalid');git('config','core.autocrlf','false')
    git('add','.');git('commit','-m','approved F030 copy for UI only');base=git('rev-parse','HEAD');git('tag','golden-base')
    (repo/'fixture-version.txt').write_text('Second committed UI version\n',encoding='utf-8')
    git('add','.');git('commit','-m','second UI version');head=git('rev-parse','HEAD')
    git('update-ref','--stdin',input=''.join(f'update refs/heads/feature/{i:03d} {head}\n' for i in range(120)).encode())
    (repo/'fixture-version.txt').write_text('staged UI difference\n',encoding='utf-8');git('add','fixture-version.txt')
    (repo/'fixture-version.txt').write_text('later working UI difference\n',encoding='utf-8')
    (repo/'未跟踪记录.txt').write_text('not covered\n',encoding='utf-8')
    def identity():return {str(p.relative_to(repo)):(sha256(p),p.stat().st_mtime_ns) for p in repo.rglob('*') if p.is_file()}
    original=identity();receipt=dict(passed=False,scope=__doc__,tests=[],screenshots=[],external_requests=[],page_errors=[],
        native_scan='NOT_EXERCISED',native_windows_dpi='NOT_VERIFIED',engineer_uat='NOT_VERIFIED',base_sha=base,current_sha=head)
    log=(work/'server.log').open('w',encoding='utf-8');session=work/'session.json'
    server=subprocess.Popen([str(args.python),'-B','-X','utf8','-m','ecra.studio','--data-root',str(work/'data'),
        '--no-browser','--session-file',str(session)],cwd=args.engine,stdout=log,stderr=subprocess.STDOUT,
        env=dict(os.environ,PYTHONIOENCODING='utf-8'),creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    playwright=browser=context=None
    try:
        deadline=time.monotonic()+60
        while not session.exists():
            if server.poll() is not None or time.monotonic()>deadline:raise RuntimeError('Studio startup failed; see server.log')
            time.sleep(.1)
        info=json.loads(session.read_text());origin='http://'+info['authority']
        while True:
            try:urllib.request.urlopen(urllib.request.Request(origin+'/api/bootstrap',headers={'X-ECRA-Session':info['token']}),timeout=1).close();break
            except OSError:
                if time.monotonic()>deadline:raise
                time.sleep(.1)
        from playwright.sync_api import sync_playwright,expect
        import yaml
        playwright=sync_playwright().start();browser=playwright.chromium.launch(channel='chrome',headless=True)
        context=browser.new_context(viewport=dict(width=1600,height=900),record_video_dir=str(output/'video'))
        context.tracing.start(screenshots=True,snapshots=True,sources=True);page=context.new_page()
        page.on('pageerror',lambda error:receipt['page_errors'].append(str(error)))
        page.on('request',lambda request:receipt['external_requests'].append(request.url) if not request.url.startswith(origin) else None)
        def button(name):return page.get_by_role('button',name=name,exact=True)
        def done(name):receipt['tests'].append(dict(name=name,status='PASS',related=['U04','H2','H5']))
        def shot(name):
            path=output/(name+'.png');page.screenshot(path=str(path),full_page=True);receipt['screenshots'].append(str(path))
        def read():
            button('读取并核对本地 Git 版本').click();expect(button('正在读取本地 Git…')).to_have_count(0)
        def configure(root,database):
            page.get_by_label('工程名称',exact=True).fill('版本选择日常配置')
            page.get_by_label('固件目录（绝对路径）',exact=True).fill(str(root));button('下一步').click()
            page.get_by_label('真实构建方式',exact=True).select_option('database')
            page.get_by_label('编译数据库路径',exact=True).fill(str(database));button('下一步').click()
        page.goto(info['url']);page.get_by_role('link',name='工程配置',exact=True).click()
        configure(repo,repo/'compile_commands.json');read();picker=page.get_by_role('region',name='Git 版本选择',exact=True)
        expect(picker).to_contain_text(head);expect(picker).to_contain_text('已暂存 1 · 工作区修改 1 · 未跟踪 1 · 冲突 0')
        expect(picker).to_contain_text('固定提交比较不包含这些未提交修改')
        done('real_git_head_dirty_coverage_and_read_only_preview')
        first=page.get_by_label('选择当前分支或标签',exact=True).locator('option').all_text_contents()
        assert 50<=len(first)<=52
        button('下一批版本').click();expect(picker).to_contain_text('本页 50 项')
        expect(page.get_by_label('选择当前分支或标签',exact=True).locator('option').first).to_have_text('HEAD')
        expect(button('正在读取本地 Git…')).to_have_count(0)
        second=page.get_by_label('选择当前分支或标签',exact=True).locator('option').all_text_contents()
        assert first!=second and len(second)<=52
        page.get_by_label('筛选分支或标签',exact=True).fill('golden-base');button('检索版本').click()
        expect(picker).to_contain_text('匹配 1 个真实引用')
        page.get_by_label('选择基准分支或标签',exact=True).select_option('refs/tags/golden-base')
        page.get_by_label('筛选分支或标签',exact=True).fill('feature/119');button('检索版本').click()
        expect(picker).to_contain_text('匹配 1 个真实引用')
        page.get_by_label('选择当前分支或标签',exact=True).select_option('refs/heads/feature/119')
        expect(picker.get_by_role('status')).to_contain_text('所选引用已变更')
        read();expect(picker).to_contain_text('基准提交：'+base);expect(picker).to_contain_text('当前提交：'+head)
        done('paged_real_ref_selection_search_and_commit_resolution')
        page.get_by_label('Diff 基准 ref（空表示全量）',exact=True).fill('missing-ref');read()
        expect(picker.get_by_role('alert')).to_contain_text('不能解析为提交')
        expect(picker.get_by_text('基准提交：'+base)).to_have_count(0)
        page.get_by_label('Diff 基准 ref（空表示全量）',exact=True).fill('refs/tags/golden-base');read()
        expect(picker).to_contain_text('基准提交：'+base);done('invalid_ref_keeps_input_and_removes_stale_commit_preview')
        for width,height in [(1366,768),(1600,900)]:
            page.set_viewport_size(dict(width=width,height=height));page.evaluate('scrollTo(0,0)')
            box=button('下一步').bounding_box();assert box and 0<=box['y'] and box['y']+box['height']<=height
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth');shot('01-real-git-selection-'+str(width))
        button('下一步').click();editor=page.get_by_label('高级完整 YAML',exact=True)
        value=yaml.safe_load(editor.input_value());g=value['analysis']['git_diff']
        assert g['base_ref']=='refs/tags/golden-base' and g['current_ref']=='refs/heads/feature/119' and not g['include_uncommitted']
        button('检查配置与工具路径').click();expect(button('保存独立配置')).to_be_enabled();button('保存独立配置').click()
        expect(page.get_by_role('status').filter(has_text='配置已保存')).to_be_visible()
        profile=next((work/'data/projects').glob('*/profiles/*.yaml'));raw=profile.read_bytes();assert yaml.safe_load(raw)['analysis']['git_diff']==g
        shot('02-selected-refs-saved');done('chosen_refs_generate_real_saved_profile_without_uncommitted_coverage')
        button('上一步').click();expect(page.get_by_label('当前 ref',exact=True)).to_have_value('refs/heads/feature/119')
        read();expect(picker).to_contain_text('基准提交：'+base)
        page.reload();button('版本选择日常配置 · 打开完整 YAML').click()
        expect(page.get_by_label('高级完整 YAML',exact=True)).to_have_value(raw.decode())
        assert profile.read_bytes()==raw;done('back_reload_reopen_retains_selected_refs_and_saved_bytes')
        button('新建工程配置').click();configure(args.firmware.resolve(),args.compile_database.resolve());read()
        expect(page.get_by_role('status').filter(has_text='此目录不是 Git 工程')).to_be_visible()
        expect(page.get_by_label('选择当前分支或标签',exact=True)).to_have_count(0)
        assert profile.read_bytes()==raw;done('new_non_git_project_clears_old_git_state_and_preserves_previous_profile')
        assert identity()==original,'Original fixture Git/source bytes or mtimes changed'
        assert source_before=={str(p.relative_to(args.firmware)):sha256(p) for p in args.firmware.rglob('*') if p.is_file()}
        assert sha256(args.compile_database)==database_before
        assert not receipt['external_requests'] and not receipt['page_errors']
        receipt.update(passed=True,source_files_unchanged=len(source_before),fixture_files_and_mtimes_unchanged=len(original),saved_profile=str(profile),profile_sha256=sha256(profile))
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
        server.terminate();server.wait(timeout=30);log.close()
        (output/'acceptance.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(dict(passed=receipt['passed'],tests=len(receipt['tests']),evidence=str(output)),ensure_ascii=False))


if __name__=='__main__':main()
