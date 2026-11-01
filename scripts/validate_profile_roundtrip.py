"""Real Chrome + local Studio: advanced YAML/form edits, backup, save and reopen.

Uses an already authorized, read-only firmware path. No mock API, native scan,
network model, or physical second-machine/DPI/UAT claim is made by this script.
"""
import argparse
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
        def check_save():
            button('检查配置与工具路径').click();expect(button('保存独立配置')).to_be_enabled()
            button('保存独立配置').click();expect(page.get_by_role('status').filter(has_text='配置已保存')).to_be_visible()
            expect(button('开始此配置扫描')).to_be_enabled()
        def shot(name):
            expect(page.locator('.activity')).to_have_count(0)
            path=output/(name+'.png');page.screenshot(path=str(path),full_page=True);receipt['screenshots'].append(str(path))
        def passed(name):receipt['tests'].append(dict(name=name,status='PASS',related=['U02','H2','H5']))
        page.get_by_label('工程名称',exact=True).fill('F030 日常配置')
        page.get_by_label('固件目录（绝对路径）',exact=True).fill(str(args.firmware.resolve()))
        button('下一步').click();page.get_by_label('真实构建方式',exact=True).select_option('database')
        expect(page.get_by_label('构建变体',exact=True)).to_have_count(0)
        page.get_by_label('编译数据库路径',exact=True).fill(str(args.compile_database.resolve()))
        button('下一步').click();page.get_by_label('变量定义纳入目录（每行一个，空表示全部）',exact=True).fill('Src,用户目录\n Path with spaces ')
        button('下一步').click();editor=page.get_by_label('高级完整 YAML',exact=True)
        first=editor.input_value();value=yaml.safe_load(first)
        assert value['project']['name']=='F030 日常配置'
        assert value['analysis']['include_dirs']==['Src,用户目录',' Path with spaces ']
        passed('four_step_generation_preserves_comma_space_paths_and_names')
        advanced=first.replace('analysis:\n','analysis:\n  allow_external_toolchain: true\n',1)+'\n# 用户高级字段与类型\ncustom: {quoted: "on", integer: 12, enabled: true, values: [a, b]}\n'
        editor.fill(advanced);check_save();profile_path=next((work/'data/projects').glob('*/profiles/*.yaml'))
        assert profile_path.read_bytes().decode()==advanced
        button('上一步').click();expect(page.get_by_label('变量定义纳入目录（每行一个，空表示全部）',exact=True)).to_have_value('Src,用户目录\n Path with spaces ')
        page.get_by_label('排除变量清单目录（每行一个，仍参与调用恢复）',exact=True).fill('Drivers,HAL\nLibs with spaces')
        button('下一步').click();expect(page.get_by_role('status').filter(has_text='已同步所改字段')).to_be_visible()
        merged=editor.input_value();expected=yaml.safe_load(advanced);expected['analysis']['exclude_dirs']=['Drivers,HAL','Libs with spaces']
        assert yaml.safe_load(merged)==expected and '# 用户高级字段与类型' in merged and '"on"' in merged
        expect(button('开始此配置扫描')).to_be_disabled();expect(button('保存独立配置')).to_be_disabled()
        passed('advanced_edit_back_modify_forward_changes_only_requested_paths')
        backups=list((work/'data/settings/profile-drafts').glob('*.yaml'))
        assert len(backups)==1 and backups[0].read_bytes().decode()==advanced
        button('恢复同步前原文').click();expect(editor).to_have_value(advanced)
        expect(button('开始此配置扫描')).to_be_disabled();expect(button('保存独立配置')).to_be_disabled()
        passed('immutable_original_backup_and_restore_require_recheck_save')
        button('上一步').click();page.get_by_label('排除变量清单目录（每行一个，仍参与调用恢复）',exact=True).fill('Drivers,HAL\nLibs with spaces')
        button('下一步').click();check_save();merged=editor.input_value()
        assert profile_path.read_bytes().decode()==merged
        button('F030 日常配置 · 打开完整 YAML').click();expect(editor).to_have_value(merged)
        passed('synchronized_saved_profile_reopens_byte_exact_with_descriptive_name')
        shot('01-roundtrip-saved-1600')
        # A temporary build-mode switch must retain all unrelated advanced data,
        # expose the changed branch and allow restoring its complete predecessor.
        button('上一步').click();button('上一步').click()
        page.get_by_label('真实构建方式',exact=True).select_option('cmake')
        page.get_by_label('目标名称',exact=True).fill('firmware')
        page.get_by_label('构建变体',exact=True).fill('Release')
        button('下一步').click();button('下一步').click()
        expect(page.get_by_role('status').filter(has_text='旧构建分支已保存到原文备份')).to_be_visible()
        switched=yaml.safe_load(editor.input_value());old=yaml.safe_load(merged)
        assert 'compile_database' not in switched['analysis'] and switched['analysis']['cmake']['build_type']=='Release'
        assert switched['custom']==old['custom'] and switched['contexts']==old['contexts']
        button('恢复同步前原文').click();expect(editor).to_have_value(merged)
        passed('build_mode_switch_declared_backed_up_and_reversible')
        # Shared controlled mappings are deliberately left in the raw editor;
        # refusal cannot alter the editor or saved profile.
        ambiguous='shared: &project\n  name: same\n  root: '+json.dumps(str(args.firmware.resolve()))+'\nproject: *project\nanalysis: {output: {location: user}, compile_database: auto}\n'
        editor.fill(ambiguous);button('上一步').click()
        expect(page.get_by_role('alert')).to_contain_text('共享映射')
        expect(editor).to_have_value(ambiguous);assert profile_path.read_bytes().decode()==merged
        passed('ambiguous_alias_controlled_mapping_refuses_without_overwrite')
        editor.fill(merged);check_save()
        for width,height in [(1366,768),(1600,900)]:
            page.set_viewport_size(dict(width=width,height=height));page.evaluate('scrollTo(0,0)')
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),'horizontal overflow'
            bounds=button('开始此配置扫描').bounding_box()
            assert bounds and 0<=bounds['y'] and bounds['y']+bounds['height']<=height,'primary action outside first viewport'
            shot('02-profile-saved-'+str(width))
        # Reload is independent of the editor's in-memory form and backup state.
        page.reload();button('F030 日常配置 · 打开完整 YAML').click()
        expect(page.get_by_label('高级完整 YAML',exact=True)).to_have_value(merged)
        button('新建工程配置').click();expect(page.get_by_label('工程名称',exact=True)).to_have_value('')
        assert profile_path.read_bytes().decode()==merged
        passed('browser_reload_and_new_profile_keep_existing_profile')
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
