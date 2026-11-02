"""Real Chrome U02/U05 subset: build gate, full commands, repair and native scan.

Uses only explicitly supplied firmware/config and repository teaching sources.
No mock API, online model, physical32GB, native DPI or engineer UAT claim.
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

TOOL=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(TOOL))
from ecra.report_package import sha256


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('config','work','evidence'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--engine',type=Path,default=TOOL)
    parser.add_argument('--python',type=Path,default=Path(sys.executable))
    parser.add_argument('--cmake-example',action='store_true',help='Also actually build the repository teaching ARM object target in an independent source copy')
    parser.add_argument('--allow-external-toolchain',action='store_true',help='Explicitly allow the approved frozen database compiler; never substitute its arguments')
    args=parser.parse_args()
    from ecra.config import configured_project_root,read_yaml
    from ecra.workspace import no_links,studio_data_root
    config=no_links(args.config.resolve());root=configured_project_root(config)
    work=studio_data_root(args.work.resolve());work.mkdir(parents=True,exist_ok=False)
    output=no_links(args.evidence.resolve());output.mkdir(parents=True,exist_ok=True)
    (work/'controller.py').write_bytes(Path(__file__).read_bytes())
    cfg=read_yaml(config);database=(root/cfg['analysis']['compile_database']).resolve()
    before={str(p.relative_to(root)):(sha256(p),p.stat().st_size,p.stat().st_mtime_ns) for p in root.rglob('*') if p.is_file()}
    database_before=(sha256(database),database.stat().st_mtime_ns)
    original_cfg_sha=sha256(config)
    cfg['analysis']['output']=dict(location='user')
    if args.allow_external_toolchain:cfg['analysis']['allow_external_toolchain']=True
    raw=json.dumps(cfg,ensure_ascii=False,indent=2)
    receipt=dict(passed=False,tests=[],screenshots=[],page_errors=[],external_requests=[],scope=__doc__,
                 firmware=str(root),source_config=str(config),native_dpi='NOT_VERIFIED',engineer_uat='NOT_VERIFIED')
    flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
    log=(work/'server.log').open('wb');session=work/'session.json'
    server=subprocess.Popen([str(args.python),'-B','-X','utf8','-m','ecra.studio','--data-root',str(work/'data'),
        '--no-browser','--session-file',str(session)],cwd=args.engine,env=dict(os.environ,PYTHONIOENCODING='utf-8'),stdout=log,stderr=subprocess.STDOUT,creationflags=flags)
    browser=context=playwright=None
    try:
        deadline=time.monotonic()+60
        while not session.is_file():
            if server.poll() is not None or time.monotonic()>deadline:raise RuntimeError('Studio startup failed; see server.log')
            time.sleep(.1)
        info=json.loads(session.read_text('utf-8'));base='http://'+info['authority']
        def get(path):
            with urllib.request.urlopen(urllib.request.Request(base+'/api'+path,headers={'X-ECRA-Session':info['token']}),timeout=30) as r:return json.load(r)
        while True:
            try:get('/bootstrap');break
            except OSError:
                if time.monotonic()>deadline:raise
                time.sleep(.1)
        from playwright.sync_api import sync_playwright,expect
        playwright=sync_playwright().start();browser=playwright.chromium.launch(channel='chrome',headless=True)
        context=browser.new_context(viewport=dict(width=1600,height=900),record_video_dir=str(output/'video'))
        context.tracing.start(screenshots=True,snapshots=True,sources=True);page=context.new_page()
        page.on('pageerror',lambda e:receipt['page_errors'].append(str(e)))
        page.on('request',lambda r:receipt['external_requests'].append(r.url) if not r.url.startswith(base) else None)
        def button(name):return page.get_by_role('button',name=name,exact=True)
        def passed(name):
            receipt['tests'].append(dict(name=name,status='PASS',related=['U02','U05','U06','H2','H5']))
            (output/'progress.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),'utf-8')
            print('PASS '+name,flush=True)
        def shot(name):
            path=output/(name+'.png');page.screenshot(path=str(path),full_page=True);receipt['screenshots'].append(str(path))
        def save(value):
            editor.fill(value);button('检查配置与工具路径').click();expect(button('保存独立配置')).to_be_enabled()
            button('保存独立配置').click();expect(page.locator('.activity')).to_have_count(0)
        def check():
            panel=page.get_by_role('region',name='真实构建预检查')
            control=panel.get_by_role('button',name='重新检查真实构建',exact=True)
            if not control.count():control=panel.get_by_role('button',name='检查真实构建',exact=True)
            control.click()
            return panel
        page.goto(info['url']);button('打开示例').click()
        expect(page.get_by_role('heading',name='先处理需要核实的变量',exact=True)).to_be_visible(timeout=60000)
        sample=next(p for p in (work/'data/scans').iterdir() if (p/'scan.db').is_file());sample_sha=sha256(sample/'scan.db')
        page.get_by_role('link',name='工程配置',exact=True).click()
        page.get_by_label('工程名称',exact=True).fill('F030 编译检查')
        page.get_by_label('固件目录（绝对路径）',exact=True).fill(str(root));button('下一步').click()
        page.get_by_label('真实构建方式',exact=True).select_option('database')
        page.get_by_label('编译数据库路径',exact=True).fill(str(database));button('下一步').click()
        button('上一步').click();expect(page.get_by_label('编译数据库路径',exact=True)).to_have_value(str(database))
        button('下一步').click();button('下一步').click()
        editor=page.get_by_label('高级完整 YAML',exact=True);start=button('开始此配置扫描')
        expect(start).to_be_disabled();save(raw);expect(start).to_be_disabled()
        passed('four_steps_preserve_database_and_saved_configuration_alone_cannot_enable_scan')
        panel=check();expect(start).to_be_disabled();expect(start).to_be_enabled(timeout=180000)
        expect(panel).to_contain_text('真实构建与编译输入检查通过')
        tasks=get('/tasks')['items'];good=next(t for t in tasks if t['mode']=='precheck' and t['state']=='COMPLETE')
        plan=get('/tasks/'+good['id']+'/plan?limit=1');rows=json.loads(database.read_text('utf-8'))
        assert plan['check']['passed'] and plan['total']==len(rows)
        original=rows[0].get('arguments')
        if original:assert plan['items'][0]['original_arguments']==original
        ordinals=[];cursor=0
        while True:
            chunk=get('/tasks/'+good['id']+'/plan?limit=1&offset='+str(cursor));ordinals.extend(r['ordinal'] for r in chunk['items'])
            if chunk['next_offset'] is None:break
            cursor=chunk['next_offset']
        assert ordinals==list(range(len(rows)))
        passed('real_all_tu_compiler_and_input_checks_are_persisted_and_every_command_pages_without_truncation')
        for width,height in ((1366,768),(1600,900)):
            page.set_viewport_size(dict(width=width,height=height));page.evaluate('scrollTo(0,0)')
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            bounds=start.bounding_box();assert bounds and bounds['y']>=0 and bounds['y']+bounds['height']<=height
            shot('01-build-plan-'+str(width))
        passed('checked_plan_and_wizard_scan_action_fit_1366_and_1600')
        page.set_viewport_size(dict(width=1600,height=900))
        saved=editor.input_value();editor.fill(saved+'\n# changed after check\n');expect(start).to_be_disabled()
        editor.fill(saved);expect(start).to_be_disabled()
        passed('any_unsaved_yaml_change_revokes_wizard_start_even_when_text_is_restored')
        contract=work/'input-contract';contract.mkdir()
        bad_db=contract/'compile_commands.json';bad_rows=json.loads(database.read_text('utf-8'))
        from ecra.compilation import split_command
        for row in bad_rows:
            values=row.get('arguments') or split_command(row['command']);values[0]=str(contract/'missing-arm-none-eabi-gcc.exe')
            row['arguments']=values;row.pop('command',None)
        bad_db.write_text(json.dumps(bad_rows),'utf-8');bad=json.loads(raw)
        bad['analysis']['compile_database']=str(bad_db);bad['analysis']['auto_system_includes']=False
        save(json.dumps(bad,ensure_ascii=False));panel=check()
        expect(panel.get_by_role('alert').filter(has_text='检查未通过')).to_be_visible(timeout=90000)
        expect(panel).to_contain_text('missing-arm-none-eabi-gcc.exe');expect(start).to_be_disabled()
        assert not [t for t in get('/tasks')['items'] if t['mode']=='scan']
        assert sha256(sample/'scan.db')==sample_sha
        shot('02-missing-compiler-blocked');passed('actual_missing_compiler_blocks_gate_with_path_and_repair_and_preserves_previous_archive')
        save(raw);panel=check();expect(start).to_be_enabled(timeout=180000)
        start.click();expect(page.get_by_role('heading',name='扫描任务中心',exact=True)).to_be_visible()
        expect(button('打开扫描结果')).to_be_visible(timeout=240000)
        completed=next(t for t in get('/tasks')['items'] if t['mode']=='scan' and t['state']=='COMPLETE')
        taskdir=work/'data/work/tasks'/completed['id']
        assert read_json(taskdir/'preflight/preflight.json')['passed']
        native=work/'data/scans'/completed['scan_id']
        from ecra.scan_store import EvidenceProvider
        EvidenceProvider(native/'scan.db').validate(deep=True)
        assert all(not (native/n).exists() for n in ('facts.json','facts.db','index.html','reports','inventory'))
        receipt['native_scan']=dict(task=completed['id'],database=str(native/'scan.db'),sha256=sha256(native/'scan.db'))
        shot('03-precheck-then-native-publication');passed('repair_recheck_then_actual_wizard_scan_publishes_only_valid_authority_database')
        if args.cmake_example:
            demo=work/'teaching-source';demo.mkdir()
            for name in ('main.c','other.c','shared.h','CMakeLists.txt'):
                shutil.copy2(TOOL/'examples/stm32_demo'/name,demo/name)
            demo_before={p.name:(sha256(p),p.stat().st_mtime_ns) for p in demo.iterdir()}
            original_args=rows[0].get('arguments') or split_command(rows[0]['command'])
            from ecra.portable import resolved_executable
            compiler=resolved_executable(original_args[0],rows[0].get('directory',root))
            tools_bundle=args.engine if (args.engine/'portable-lock.json').is_file() else Path(os.environ.get('ECRA_PORTABLE_ROOT',''))
            if (tools_bundle/'portable-lock.json').is_file():
                compiler=tools_bundle/'tools/arm-gcc/bin/arm-none-eabi-gcc.exe'
            toolchain=contract/'arm-toolchain.cmake'
            toolchain.write_text('set(CMAKE_SYSTEM_NAME Generic)\nset(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)\nset(CMAKE_C_COMPILER "'+compiler.as_posix()+'")\n','utf-8')
            page.get_by_role('link',name='工程配置',exact=True).click();button('新建工程配置').click()
            page.get_by_label('工程名称',exact=True).fill('真实ARM教学对象构建')
            page.get_by_label('固件目录（绝对路径）',exact=True).fill(str(demo));button('下一步').click()
            page.get_by_label('目标名称',exact=True).fill('demo')
            page.get_by_label('Toolchain 文件',exact=True).fill(str(contract/'missing-toolchain.cmake'))
            page.get_by_label('构建变体',exact=True).fill('Release')
            button('下一步').click();button('下一步').click();editor=page.get_by_label('高级完整 YAML',exact=True);start=button('开始此配置扫描')
            save(editor.input_value());panel=check()
            expect(panel.get_by_role('alert').filter(has_text='检查未通过')).to_be_visible(timeout=90000)
            expect(panel).to_contain_text('missing-toolchain.cmake');expect(start).to_be_disabled()
            shot('04-cmake-toolchain-blocked');passed('actual_cmake_missing_toolchain_is_visible_and_blocks_wizard_scan')
            button('上一步').click();button('上一步').click()
            expect(page.get_by_label('目标名称',exact=True)).to_have_value('demo')
            expect(page.get_by_label('构建变体',exact=True)).to_have_value('Release')
            page.get_by_label('Toolchain 文件',exact=True).fill(str(toolchain))
            button('下一步').click();button('下一步').click();save(editor.input_value());panel=check()
            expect(start).to_be_enabled(timeout=180000)
            expect(panel).to_contain_text('demo');expect(panel).to_contain_text('Release')
            candidates=[t for t in get('/tasks')['items'] if t['mode']=='precheck' and t['project_root']==str(demo) and t['state']=='COMPLETE']
            cmake_plan=get('/tasks/'+candidates[0]['id']+'/plan');build=Path(cmake_plan['check']['build_root'])
            assert build.is_relative_to(work/'data') and cmake_plan['total']==2
            objects=list(build.rglob('*.obj'));assert len(objects)==2
            for obj in objects:
                data=obj.read_bytes();assert data[:4]==b'\x7fELF' and int.from_bytes(data[18:20],'little')==40
            assert demo_before=={p.name:(sha256(p),p.stat().st_mtime_ns) for p in demo.iterdir()}
            shot('05-cmake-target-release-checked');receipt['cmake_plan']=cmake_plan['check']
            passed('real_cmake_arm_target_release_build_after_form_repair_preserves_source_and_shows_all_commands')
        assert sha256(sample/'scan.db')==sample_sha
        assert before=={str(p.relative_to(root)):(sha256(p),p.stat().st_size,p.stat().st_mtime_ns) for p in root.rglob('*') if p.is_file()}
        assert database_before==(sha256(database),database.stat().st_mtime_ns) and original_cfg_sha==sha256(config)
        receipt.update(firmware_unchanged_files=len(before),original_database_unchanged=True,original_config_unchanged=True)
        assert not receipt['page_errors'] and not receipt['external_requests']
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
        server.terminate();server.wait(timeout=30);log.close()
        (output/'acceptance.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),'utf-8')
        print(json.dumps(dict(passed=receipt['passed'],tests=len(receipt['tests']),evidence=str(output)),ensure_ascii=False))


from ecra.common import read_json
if __name__=='__main__':main()
