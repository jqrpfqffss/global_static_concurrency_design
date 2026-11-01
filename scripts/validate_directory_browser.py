"""Real Chrome + local Studio: read-only directory selection and bound scope pages.

Uses an already authorized, read-only firmware path. No mock API, native scan,
network model, or physical second-machine/DPI/UAT claim is made by this script.
"""
import argparse
import shutil
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
from ecra.report_package import sha256
import yaml


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['firmware','compile-database','work','evidence']:parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--engine',type=Path,default=TOOL)
    parser.add_argument('--python',type=Path,default=Path(sys.executable))
    args=parser.parse_args()
    work=args.work.resolve();work.mkdir(parents=True,exist_ok=False)
    output=args.evidence.resolve();output.mkdir(parents=True,exist_ok=True)
    receipt=dict(passed=False,tests=[],screenshots=[],page_errors=[],external_requests=[],
        scope=__doc__,firmware=str(args.firmware.resolve()),compile_database=str(args.compile_database.resolve()),
        native_windows_dpi='NOT_VERIFIED',engineer_uat='NOT_VERIFIED',native_scan='NOT_EXERCISED')
    before={str(p.relative_to(args.firmware)):sha256(p) for p in args.firmware.rglob('*') if p.is_file()}
    database_before=sha256(args.compile_database)
    fixture=work/'固件, 目录选择';shutil.copytree(args.firmware,fixture)
    for index in range(137):(fixture/f'范围, {index:03d}').mkdir()
    (fixture/'范围, 005'/'子目录 中文').mkdir();outside=work/'工程外目录';outside.mkdir()
    from ecra.git_diff import relocate_paths
    commands=relocate_paths(json.loads(args.compile_database.read_text('utf-8')),args.firmware.resolve(),fixture)
    local_db=work/'fixture-compile_commands.json';local_db.write_text(json.dumps(commands,ensure_ascii=False),'utf-8')
    def inventory(root):
        return {p.relative_to(root).as_posix():(sha256(p) if p.is_file() else None,p.stat().st_size if p.is_file() else None,p.stat().st_mtime_ns) for p in [root,*root.rglob('*')]}
    original_inventory=inventory(args.firmware);fixture_before=inventory(fixture)
    log=(work/'server.log').open('w',encoding='utf-8');session=work/'session.json'
    flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
    server=subprocess.Popen([str(args.python),'-B','-X','utf8','-m','ecra.studio','--data-root',str(work/'data'),
        '--no-browser','--session-file',str(session)],cwd=args.engine,env=dict(os.environ,PYTHONIOENCODING='utf-8'),
        stdout=log,stderr=subprocess.STDOUT,creationflags=flags)
    browser=context=playwright=None
    try:
        deadline=time.monotonic()+60
        while not session.exists():
            if server.poll() is not None or time.monotonic()>deadline:raise RuntimeError('Studio failed to start; see server.log')
            time.sleep(.1)
        info=json.loads(session.read_text(encoding='utf-8'));base='http://'+info['authority']
        while True:
            try:
                urllib.request.urlopen(urllib.request.Request(base+'/api/bootstrap',headers={'X-ECRA-Session':info['token']}),timeout=1).close();break
            except OSError:
                if time.monotonic()>deadline:raise
                time.sleep(.1)
        from playwright.sync_api import sync_playwright,expect
        playwright=sync_playwright().start();browser=playwright.chromium.launch(channel='chrome',headless=True)
        context=browser.new_context(viewport=dict(width=1600,height=900),record_video_dir=str(output/'video'))
        context.tracing.start(screenshots=True,snapshots=True,sources=True);page=context.new_page()
        page.on('pageerror',lambda exc:receipt['page_errors'].append(str(exc)))
        page.on('request',lambda request:receipt['external_requests'].append(request.url) if not request.url.startswith(base) else None)
        page.goto(info['url']);page.get_by_role('link',name='工程配置',exact=True).click()
        def button(name):return page.get_by_role('button',name=name,exact=True)
        def field(name):return page.get_by_label(name,exact=True)
        def passed(name):receipt['tests'].append(dict(name=name,status='PASS',related=['U02','H2','H5']))
        def dialog(title):return page.get_by_role('dialog',name=title,exact=True)
        def open_dialog(title,trigger):
            button(trigger).click();view=dialog(title);expect(view).to_be_visible();expect(view.get_by_role('button',name='使用此目录',exact=True)).to_be_enabled();return view
        def wait_path(view,path):expect(view.get_by_label('要浏览的绝对目录',exact=True)).to_have_value(str(path))
        def navigate(view,path):
            view.get_by_label('要浏览的绝对目录',exact=True).fill(str(path));view.get_by_role('button',name='打开目录',exact=True).click()
            wait_path(view,path);expect(view.get_by_role('button',name='使用此目录',exact=True)).to_be_enabled()
        def shot(name):
            path=output/(name+'.png');page.screenshot(path=str(path),full_page=True);receipt['screenshots'].append(str(path))
        field('工程名称').fill('F030 目录选择');field('固件目录（绝对路径）').fill(str(args.firmware.resolve()))
        view=open_dialog('选择固件目录','选择固件目录');navigate(view,fixture)
        page.keyboard.press('Escape');expect(view).to_have_count(0);expect(field('固件目录（绝对路径）')).to_have_value(str(args.firmware.resolve()))
        passed('escape_cancels_real_directory_navigation_without_changing_project')
        view=open_dialog('选择固件目录','选择固件目录');navigate(view,fixture)
        view.get_by_role('button',name='使用此目录',exact=True).click();expect(field('固件目录（绝对路径）')).to_have_value(str(fixture))
        button('下一步').click();field('真实构建方式').select_option('database');field('编译数据库路径').fill(str(local_db));button('下一步').click()
        field('变量定义纳入目录（每行一个，空表示全部）').fill('Keep, manual')
        field('排除变量清单目录（每行一个，仍参与调用恢复）').fill('Vendor First')
        passed('actual_project_folder_selection_only_registers_selected_path')
        view=open_dialog('选择变量纳入目录','从目录树纳入')
        view.get_by_label('要浏览的绝对目录',exact=True).fill(str(outside));view.get_by_role('button',name='打开目录',exact=True).click()
        expect(view.get_by_role('alert')).to_contain_text('不能超出');expect(view.get_by_role('button',name='使用此目录',exact=True)).to_be_disabled()
        view.get_by_role('button',name='返回工程根目录',exact=True).click();wait_path(view,fixture)
        expect(view.get_by_role('button',name='使用此目录',exact=True)).to_be_enabled()
        passed('scope_escape_reports_real_error_and_disables_stale_directory_selection')
        view.get_by_label('筛选当前层目录',exact=True).fill('范围, ')
        pages=[]
        with page.expect_response(lambda r:'/profiles/directories' in r.url) as pending:view.get_by_role('button',name='筛选目录',exact=True).click()
        data=pending.value.json();assert data['total']==137 and len(data['items'])==50
        pages.extend(row['name'] for row in data['items'])
        while data['next_after'] is not None:
            with page.expect_response(lambda r:'/profiles/directories' in r.url) as pending:view.get_by_role('button',name='下一页目录',exact=True).click()
            data=pending.value.json();pages.extend(row['name'] for row in data['items'])
        assert pages==[f'范围, {i:03d}' for i in range(137)]
        expect(view.get_by_role('button',name='下一页目录',exact=True)).to_be_disabled()
        for _ in range(2):view.get_by_role('button',name='上一页目录',exact=True).click();expect(view.get_by_role('button',name='使用此目录',exact=True)).to_be_enabled()
        view.get_by_role('button',name='进入 范围, 005',exact=True).click();expect(view.get_by_role('button',name='进入 子目录 中文',exact=True)).to_be_visible()
        view.get_by_role('button',name='进入 子目录 中文',exact=True).click();expect(view.get_by_role('button',name='使用此目录',exact=True)).to_be_enabled()
        view.get_by_role('button',name='使用此目录',exact=True).click()
        included=str(Path('范围, 005')/'子目录 中文')
        expect(field('变量定义纳入目录（每行一个，空表示全部）')).to_have_value('Keep, manual\n'+included)
        passed('all_137_real_directories_and_nested_relative_selection_without_lost_pages')
        view=open_dialog('选择变量排除目录','从目录树排除');view.get_by_role('button',name='取消选择',exact=True).click()
        expect(field('排除变量清单目录（每行一个，仍参与调用恢复）')).to_have_value('Vendor First')
        view=open_dialog('选择变量排除目录','从目录树排除');view.get_by_label('筛选当前层目录',exact=True).fill('范围, ')
        view.get_by_role('button',name='筛选目录',exact=True).click();expect(view.get_by_role('button',name='下一页目录',exact=True)).to_be_enabled()
        view.get_by_role('button',name='下一页目录',exact=True).click();expect(view.get_by_role('button',name='进入 范围, 099',exact=True)).to_be_visible()
        view.get_by_role('button',name='进入 范围, 099',exact=True).click();expect(view.get_by_role('button',name='使用此目录',exact=True)).to_be_enabled()
        view.get_by_role('button',name='使用此目录',exact=True).click()
        expect(field('排除变量清单目录（每行一个，仍参与调用恢复）')).to_have_value('Vendor First\n范围, 099')
        passed('exclude_cancel_and_paged_selection_keep_existing_literal_entries')
        for width,height in [(1366,768),(1600,900)]:
            page.set_viewport_size(dict(width=width,height=height));view=open_dialog('选择变量纳入目录','从目录树纳入')
            for name in ['使用此目录','取消选择']:
                bounds=view.get_by_role('button',name=name,exact=True).bounding_box();assert bounds and 0<=bounds['y'] and bounds['y']+bounds['height']<=height
            bounds=view.get_by_label('要浏览的绝对目录',exact=True).bounding_box();assert bounds and bounds['y']>=0 and bounds['y']+bounds['height']<=height
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth');shot('01-directory-dialog-'+str(width))
            view.get_by_role('button',name='取消选择',exact=True).click()
        passed('real_directory_dialog_actions_and_path_visible_at_1366_and_1600')
        button('下一步').click();editor=field('高级完整 YAML');raw=editor.input_value();value=yaml.safe_load(raw)
        assert value['project']['root']==str(fixture)
        assert value['analysis']['include_dirs']==['Keep, manual',included] and value['analysis']['exclude_dirs']==['Vendor First','范围, 099']
        raw=raw.replace('analysis:\n','analysis:\n  allow_external_toolchain: true\n',1)+'\n# 保留用户原文\nfuture: {enabled: true, label: "on"}\n'
        editor.fill(raw);button('检查配置与工具路径').click();expect(button('保存独立配置')).to_be_enabled()
        button('保存独立配置').click();expect(page.get_by_role('status').filter(has_text='配置已保存')).to_be_visible()
        profile_path=next((work/'data/projects').glob('*/profiles/*.yaml'));assert profile_path.read_bytes().decode()==raw
        page.reload();button('F030 目录选择 · 打开完整 YAML').click();expect(editor).to_have_value(raw)
        button('上一步').click();expect(field('变量定义纳入目录（每行一个，空表示全部）')).to_have_value('Keep, manual\n'+included)
        button('下一步').click();expect(editor).to_have_value(raw)
        passed('selected_relative_scope_survives_save_reload_and_no_change_roundtrip')
        assert original_inventory==inventory(args.firmware) and fixture_before==inventory(fixture)
        receipt.update(fixture_tree_entries_unchanged=len(fixture_before),fixture=str(fixture),fixture_note='ApprovedF030 copy plus137 empty directory UI fixtures, not another nativeG2 project')
        backups=[]
        assert before=={str(p.relative_to(args.firmware)):sha256(p) for p in args.firmware.rglob('*') if p.is_file()}
        assert sha256(args.compile_database)==database_before
        receipt.update(firmware_files_unchanged=len(before),compile_database_unchanged=True,backup_files=len(backups),
            saved_profile=str(profile_path),profile_sha256=sha256(profile_path))
        assert not receipt['page_errors'] and not receipt['external_requests']
        receipt['passed']=True
    except BaseException:
        receipt['error']=traceback.format_exc()
        if context:
            try:context.pages[0].screenshot(path=str(output/'failure.png'),full_page=True)
            except Exception:pass
        raise
    finally:
        if context:
            context.tracing.stop(path=str(output/'trace.zip'));context.close()
        if browser:browser.close()
        if playwright:playwright.stop()
        server.terminate();server.wait(timeout=30);log.close()
        (output/'acceptance.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(dict(passed=receipt['passed'],tests=len(receipt['tests']),evidence=str(output)),ensure_ascii=False))


if __name__=='__main__':main()
