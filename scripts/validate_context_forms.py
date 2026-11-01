"""Real Chrome + local Studio: ordinary context forms and exact advanced roundtrip.

Uses an already authorized, read-only firmware path. No mock API, native scan,
network model, or physical second-machine/DPI/UAT claim is made by this script.
"""
import argparse
import copy
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
    before={str(p.relative_to(args.firmware)):(sha256(p),p.stat().st_size,p.stat().st_mtime_ns) for p in args.firmware.rglob('*') if p.is_file()}
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
        def field(name):return page.get_by_label(name,exact=True)
        def passed(name):receipt['tests'].append(dict(name=name,status='PASS',related=['U02','H2','H5']))
        def shot(name):
            expect(page.locator('.activity')).to_have_count(0)
            path=output/(name+'.png');page.screenshot(path=str(path),full_page=True);receipt['screenshots'].append(str(path))
        def check_save():
            button('检查配置与工具路径').click();expect(button('保存独立配置')).to_be_enabled()
            button('保存独立配置').click();expect(page.get_by_role('status').filter(has_text='配置已保存')).to_be_visible()
            expect(button('开始此配置扫描')).to_be_enabled()
        field('工程名称').fill('F030 入口配置')
        field('固件目录（绝对路径）').fill(str(args.firmware.resolve()));button('下一步').click()
        field('真实构建方式').select_option('database');field('编译数据库路径').fill(str(args.compile_database.resolve()))
        expect(field('编译器标准头文件')).to_have_value('default');field('编译器标准头文件').select_option('on')
        button('下一步').click();expect(field('入口ID 1')).to_have_value('main')
        for kind in ['ISR','TASK']:
            field('新增入口类型').select_option(kind);button('添加执行入口').click()
        field('入口ID 2').fill('systick');field('入口函数 2').fill('SysTick_Handler\nSysTick_Handler')
        field('入口ID 3').fill('control_task');field('入口函数 3').fill('ControlTask')
        button('下一步').click();editor=field('高级完整 YAML');first=editor.input_value();first_value=yaml.safe_load(first)
        assert first_value['analysis']['auto_system_includes'] is True
        assert first_value['contexts']==[dict(id='main',kind='MAIN',functions=['main']),dict(id='systick',kind='ISR',functions=['SysTick_Handler','SysTick_Handler']),dict(id='control_task',kind='TASK',functions=['ControlTask'])]
        passed('ordinary_main_isr_task_and_explicit_compiler_header_generation')
        # Complete advanced configuration, including comments, unknown fields,
        # duplicate functions and a shared advanced object outside editable fields.
        advanced=first.split('contexts:')[0].replace('analysis:\n','analysis:\n  allow_external_toolchain: true\n',1)+"""contexts:
  # 用户入口注释
  - id: main # 主入口注释
    kind: MAIN
    functions: [main, main] # 重复函数保留
    regex: ['^main$']
    future: &advanced {enabled: true, quoted: "on", values: [1, true, -0.0]}
  - id: systick
    kind: ISR
    functions: [SysTick_Handler]
    priority: 3 # 高级优先级保留
  - id: control_task
    kind: TASK
    functions: [ControlTask]
    reentrant: false
review: {enabled: false, future_review: 3}
future_alias: *advanced
"""
        editor.fill(advanced);check_save();profile_path=next((work/'data/projects').glob('*/profiles/*.yaml'))
        assert profile_path.read_bytes().decode()==advanced
        button('上一步').click();field('入口ID 1').fill('main_entry');field('入口函数 1').fill('main\nmain\nStart, Extra')
        field('入口类型 2').select_option('IRQ');field('入口函数 2').fill('SysTick_Handler\nTimer_Handler')
        button('下一步').click();merged=editor.input_value();expected=yaml.safe_load(advanced)
        expected['contexts'][0].update(id='main_entry',functions=['main','main','Start, Extra'])
        expected['contexts'][1].update(kind='IRQ',functions=['SysTick_Handler','Timer_Handler'])
        value=yaml.safe_load(merged);assert value==expected and value['future_alias'] is value['contexts'][0]['future']
        for marker in ['# 用户入口注释','# 主入口注释','# 重复函数保留','# 高级优先级保留',"'^main$'",'"on"']:assert marker in merged
        assert value['contexts'][0]['future']['values'][2].hex()=='-0x0.0p+0'
        expect(button('开始此配置扫描')).to_be_disabled();expect(button('保存独立配置')).to_be_disabled()
        backups=list((work/'data/settings/profile-drafts').glob('*.yaml'))
        assert any(p.read_bytes().decode()==advanced for p in backups)
        button('恢复同步前原文').click();expect(editor).to_have_value(advanced)
        expect(button('保存独立配置')).to_be_disabled();expect(button('开始此配置扫描')).to_be_disabled()
        passed('advanced_context_fields_comments_types_aliases_and_complete_restore')
        # Reapply using the restored row identities, then explicitly restore the
        # compiler setting to its absent engine default without changing context.
        button('上一步').click();field('入口ID 1').fill('main_entry');field('入口函数 1').fill('main\nmain\nStart, Extra')
        field('入口类型 2').select_option('IRQ');field('入口函数 2').fill('SysTick_Handler\nTimer_Handler')
        button('上一步').click();field('编译器标准头文件').select_option('default')
        button('下一步').click();button('下一步').click();expected['analysis'].pop('auto_system_includes')
        merged=editor.input_value();assert yaml.safe_load(merged)==expected;check_save()
        passed('explicit_return_to_engine_default_removes_only_selected_option')
        # IDs remain server-validated. A failed merge never overwrites the saved
        # profile or removes the user's field values in the ordinary form.
        button('上一步').click();field('入口ID 1').fill('systick');button('下一步').click()
        expect(page.get_by_role('alert')).to_contain_text('不能重复');expect(field('入口ID 1')).to_have_value('systick')
        assert profile_path.read_bytes().decode()==merged
        field('入口ID 1').fill('main_entry')
        passed('duplicate_context_identity_error_preserves_inputs_and_saved_profile')
        # Add enough real config rows to cross the visible eight-row page; all
        # rows must survive pagination, synchronization and a browser reload.
        for index in range(10):
            field('新增入口类型').select_option('TASK');button('添加执行入口').click()
        expect(page.get_by_text('第 2 / 2 页 · 共 13 项',exact=True)).to_be_visible()
        expect(field('入口ID 13')).to_be_visible();field('入口函数 13').fill('LastTask\nLastTask')
        button('上一页入口').click();expect(field('入口ID 1')).to_have_value('main_entry')
        expect(field('入口函数 1')).to_have_value('main\nmain\nStart, Extra')
        button('下一步').click();paged=editor.input_value();value=yaml.safe_load(paged)
        assert value['contexts'][:3]==expected['contexts'] and len(value['contexts'])==13
        assert value['contexts'][-1]['functions']==['LastTask','LastTask']
        assert len({row['id'] for row in value['contexts']})==13
        check_save();page.reload();button('F030 入口配置 · 打开完整 YAML').click();expect(editor).to_have_value(paged)
        button('上一步').click();button('下一页入口').click();expect(field('入口函数 13')).to_have_value('LastTask\nLastTask')
        passed('all_thirteen_entries_survive_pagination_save_and_reload')
        button('上一页入口').click();button('移除入口 2').click();button('下一步').click()
        removed=editor.input_value();wanted=yaml.safe_load(paged);wanted['contexts'].pop(1)
        assert yaml.safe_load(removed)==wanted
        assert '# 主入口注释' in removed and 'future_alias: *advanced' in removed
        backups=list((work/'data/settings/profile-drafts').glob('*.yaml'))
        assert any(p.read_bytes().decode()==paged for p in backups)
        check_save();merged=removed
        passed('explicit_row_removal_preserves_other_advanced_rows_and_full_predecessor')
        for width,height in [(1366,768),(1600,900)]:
            page.set_viewport_size(dict(width=width,height=height));button('上一步').click()
            page.evaluate('scrollTo(0,0)');assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            bounds=button('下一步').bounding_box();assert bounds and 0<=bounds['y'] and bounds['y']+bounds['height']<=height
            field('入口ID 1').scroll_into_view_if_needed();shot('01-contexts-'+str(width))
            button('下一步').click();bounds=button('开始此配置扫描').bounding_box()
            assert bounds and 0<=bounds['y'] and bounds['y']+bounds['height']<=height
            shot('02-saved-'+str(width))
        passed('context_and_saved_primary_actions_visible_at_1366_and_1600')
        # Shared controlled functions remain read-only while unrelated fields can
        # still round-trip. This is a real API refusal policy, not a mock screen.
        shared=first.split('contexts:')[0].replace('analysis:\n','analysis:\n  allow_external_toolchain: true\n',1)+"""contexts:
  - id: main
    kind: MAIN
    functions: &functions [main]
future_functions: *functions
review: {enabled: false}
"""
        editor.fill(shared);button('上一步').click()
        expect(page.get_by_role('note').filter(has_text='共享列表')).to_be_visible();expect(field('入口ID 1')).to_have_count(0)
        field('排除变量清单目录（每行一个，仍参与调用恢复）').fill('Drivers, HAL')
        button('下一步').click();value=yaml.safe_load(editor.input_value());wanted=yaml.safe_load(shared)
        wanted['analysis']['exclude_dirs']=['Drivers, HAL'];assert value==wanted
        assert value['contexts'][0]['functions'] is value['future_functions'];check_save();merged=editor.input_value()
        passed('shared_context_function_editor_disabled_without_losing_other_form_edits')
        backups=list((work/'data/settings/profile-drafts').glob('*.yaml'))
        assert before=={str(p.relative_to(args.firmware)):(sha256(p),p.stat().st_size,p.stat().st_mtime_ns) for p in args.firmware.rglob('*') if p.is_file()}
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
