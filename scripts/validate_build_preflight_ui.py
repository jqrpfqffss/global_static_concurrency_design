"""Real Chrome U02/U05 subset: build gate, full commands, repair and native scan.

Uses only explicitly supplied firmware/config and repository teaching sources.
No mock API, online model, physical32GB, native DPI or engineer UAT claim.
"""
import argparse
from contextlib import closing
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback
import urllib.parse
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
    parser.add_argument('--identity-acceptance',action='store_true',help='Also verify archived identity, four-card drilldown, human undo and real CMake scan identity')
    parser.add_argument('--inheritance-acceptance',action='store_true',help='Also rescan only the private teaching copy after real build/source changes and verify prior human SAFE is RECHECK_REQUIRED')
    parser.add_argument('--review-write-pressure',action='store_true',help='Hold a real private reviews.db write lock and check fields remain disabled until commit')
    args=parser.parse_args()
    if args.inheritance_acceptance and not (args.identity_acceptance and args.cmake_example):
        parser.error('--inheritance-acceptance requires --identity-acceptance and --cmake-example')
    if args.review_write_pressure and not args.identity_acceptance:parser.error('--review-write-pressure requires --identity-acceptance')
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
    if args.identity_acceptance:cfg['project']['name']='F030真实控制板 · 中文工程与长构建身份逐项验收'
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
            # Reopening a saved revision asynchronously restores historical
            # tasks and changes this same button's label. Keep one live locator.
            control=panel.get_by_role('button',name=re.compile(r'^(?:重新)?检查真实构建$'))
            expect(control).to_be_enabled()
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
        if args.identity_acceptance:
            button('打开扫描结果').click()
            expect(page.get_by_role('heading',name='先处理需要核实的变量',exact=True)).to_be_visible()
            expected_name=cfg['project']['name'];binding=get('/scans/'+completed['scan_id']+'/summary')
            assert binding['identity']['project_name']==expected_name
            # The input-bound config is a separately saved profile, not the original input YAML.
            profile=next(p for p in get('/profiles')['items'] if p['id']==binding['binding']['profile_id'])
            import hashlib
            assert binding['identity']['config_sha256']==hashlib.sha256(profile['yaml'].encode('utf-8')).hexdigest()
            for width,height in ((1366,768),(1600,900),(1920,1080)):
                page.set_viewport_size(dict(width=width,height=height))
                identity_button=button('查看当前工程与构建身份');expect(identity_button).to_contain_text(expected_name)
                box=page.locator('header').bounding_box();assert box and box['height']==60
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                identity_button.click();dialog=page.get_by_role('dialog',name='当前工程与构建身份',exact=True)
                expect(dialog).to_contain_text(str(root));expect(dialog).to_contain_text(binding['identity']['config_sha256'])
                for key in ['chip','core']:
                    if cfg['project'].get(key):expect(dialog).to_contain_text(cfg['project'][key])
                expect(dialog).to_contain_text('部分覆盖（INCOMPLETE）');shot('06-identity-'+str(width))
                page.keyboard.press('Escape');expect(dialog).not_to_be_visible();expect(identity_button).to_be_focused()
            passed('native_identity_uses_snapshot_config_and_fits_three_viewports_with_escape_focus_return')
            for state,title in [('SUSPECT','静态疑似'),('UNKNOWN','无法判断'),('SAFE_PROVEN','当前构建已证明安全'),('PENDING','人工待确认')]:
                page.get_by_role('link',name='项目概览',exact=True).click()
                expected=binding['human_counts'].get('PENDING',0) if state=='PENDING' else binding['static_counts'].get(state,0)
                with page.expect_response(lambda r:'/symbols?' in r.url and 'limit=50' in r.url and
                    ('human_decision=PENDING' in r.url if state=='PENDING' else 'classification='+state+'&' in r.url)) as response:
                    button(title+' '+str(expected)).click()
                assert response.value.json()['total']==expected
                expect(page.locator('.symbol')).to_have_count(min(50,expected))
            passed('all_four_overview_cards_drill_into_exact_same_persisted_denominators')
            page.get_by_label('静态分类',exact=True).select_option('')
            page.get_by_label('人工状态',exact=True).select_option('')
            page.get_by_label('查找变量、文件或规范身份',exact=True).fill('HCLK');button('搜索').click()
            expect(page.locator('.symbol')).to_have_count(1);page.locator('.symbol').click()
            symbol=EvidenceProvider(native/'scan.db').symbols(search='HCLK')['items'][0]['symbol_id']
            from ecra.human_reviews import ReviewStore
            store=ReviewStore(native/'reviews.db',EvidenceProvider(native/'scan.db').metadata());events_before=store.history(symbol)
            page.get_by_label('确认者',exact=True).fill('U17自动化撤销验收声明')
            reason=page.get_by_label('依据 / 修改或撤销理由',exact=True);reason.fill('临时风险决定，用于验证撤销审计，不作为安全证明')
            if args.review_write_pressure:
                import sqlite3
                lock=sqlite3.connect(native/'reviews.db');lock.execute('BEGIN IMMEDIATE')
                try:
                    button('确认有风险').click()
                    for control in [reason,page.get_by_label('确认者',exact=True),page.get_by_label('独立处理状态',exact=True)]:expect(control).to_be_disabled()
                    with closing(sqlite3.connect((native/'reviews.db').resolve().as_uri()+'?mode=ro',uri=True)) as reader:
                        assert reader.execute('SELECT count(*) FROM events WHERE symbol_id=?',(symbol,)).fetchone()[0]==len(events_before)
                    page.keyboard.press('Escape');expect(page.locator('.detail-heading h2')).to_have_count(0)
                finally:lock.rollback();lock.close()
                expect(page.get_by_role('status').filter(has_text='已保存')).to_be_visible()
                page.locator('.symbol').click();expect(page.locator('.detail-heading h2')).to_have_text('HCLK')
                expect(reason).to_be_enabled()
                passed('actual_sqlite_write_lock_disables_fields_and_commit_survives_escape_before_receipt')
            else:button('确认有风险').click()
            expect(page.locator('.conclusion')).to_contain_text('人工确认有风险')
            reason.fill('复核后撤销临时测试决定，保留原始理由');button('撤销上次确认').click()
            expect(page.locator('.conclusion')).to_contain_text('待确认')
            events=store.history(symbol);assert len(events)==len(events_before)+2
            assert events[-2]['decision']=='CONFIRMED_RISK' and events[-1]['decision']=='PENDING'
            assert events[-2]['comment']=='临时风险决定，用于验证撤销审计，不作为安全证明'
            assert events[-1]['comment']=='撤销 '+events[-2]['event_id']+'：复核后撤销临时测试决定，保留原始理由'
            assert sha256(native/'scan.db')==receipt['native_scan']['sha256']
            shot('07-human-undo-retains-original-event');passed('actual_human_undo_appends_event_and_preserves_original_reason_and_static_database')
            page.get_by_role('link',name='工程配置',exact=True).click()
            page.locator('button.profile').filter(has_text=profile['name']).click()
            changed=json.loads(profile['yaml']);changed['project']['name']='当前已保存配置已改名，不能覆盖旧批次'
            save(json.dumps(changed,ensure_ascii=False))
            page.get_by_role('link',name='历史与对比',exact=True).click()
            page.locator('.history-row').filter(has_text=completed['scan_id']).get_by_role('button',name='打开结果',exact=True).click()
            expect(button('查看当前工程与构建身份')).to_contain_text(expected_name)
            assert get('/scans/'+completed['scan_id']+'/summary')['identity']==binding['identity']
            assert sha256(native/'scan.db')==receipt['native_scan']['sha256']
            passed('editing_current_profile_cannot_relabel_archived_scan_identity')
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
            if args.identity_acceptance:
                start.click();expect(button('打开扫描结果')).to_be_visible(timeout=240000)
                cmake_task=next(t for t in get('/tasks')['items'] if t['mode']=='scan' and t['project_root']==str(demo) and t['state']=='COMPLETE')
                identity=get('/scans/'+cmake_task['scan_id']+'/summary')['identity']
                assert identity['configured_target']=='demo' and identity['build_variant']=='Release'
                assert identity['project_name']=='真实ARM教学对象构建'
                button('打开扫描结果').click();button('查看当前工程与构建身份').click()
                expect(page.get_by_role('dialog',name='当前工程与构建身份',exact=True)).to_contain_text('Release')
                shot('08-real-cmake-native-build-identity');page.keyboard.press('Escape')
                assert demo_before=={p.name:(sha256(p),p.stat().st_mtime_ns) for p in demo.iterdir()}
                passed('actual_native_cmake_target_and_cache_variant_are_archived_and_visible')
                if args.inheritance_acceptance:
                    import yaml
                    original_teaching={name:sha256(TOOL/'examples/stm32_demo'/name) for name in demo_before}
                    receipt['inheritance_scans']=[]
                    def selected_demo(task):
                        page.get_by_role('link',name='变量与风险',exact=True).click()
                        page.get_by_label('查找变量、文件或规范身份',exact=True).fill('g_counter');button('搜索').click()
                        expect(page.locator('.symbol')).to_have_count(1);page.locator('.symbol').click()
                        database=work/'data/scans'/task['scan_id']/'scan.db'
                        provider=EvidenceProvider(database);item=provider.symbols(search='g_counter')['items'][0]
                        store=ReviewStore(database.parent/'reviews.db',provider.metadata())
                        return database,provider,item['symbol_id'],store
                    def human_state(task,symbol):
                        return get('/scans/'+task['scan_id']+'/human?symbol_id='+urllib.parse.quote(symbol,safe=''))
                    def test_safe_decision():
                        page.get_by_label('确认者',exact=True).fill('U18隔离教学档案自动化验收声明')
                        page.get_by_label('依据 / 修改或撤销理由',exact=True).fill('只测试安全确认不会跨变化继承；此隔离教学决定不是固件安全证明或工程师UAT')
                        button('确认无风险').click();expect(page.locator('.conclusion')).to_contain_text('人工确认无风险')
                    def rescan_demo(variant=None):
                        existing={t['id'] for t in get('/tasks')['items']}
                        page.get_by_role('link',name='工程配置',exact=True).click()
                        profile=next(p for p in get('/profiles')['items'] if p['project_root']==str(demo))
                        page.locator('button.profile').filter(has_text=profile['name']).click()
                        raw=profile['yaml']
                        if variant:
                            changed=yaml.safe_load(raw);changed['analysis']['cmake']['build_type']=variant;raw=json.dumps(changed,ensure_ascii=False)
                        save(raw);check();expect(start).to_be_enabled(timeout=180000);start.click()
                        expect(button('打开扫描结果')).to_be_visible(timeout=240000)
                        task=next(t for t in get('/tasks')['items'] if t['id'] not in existing and t['mode']=='scan' and t['state']=='COMPLETE')
                        button('打开扫描结果').click()
                        expect(page.get_by_role('heading',name='先处理需要核实的变量',exact=True)).to_be_visible()
                        return task
                    prior_db,prior_provider,symbol,prior_store=selected_demo(cmake_task)
                    test_safe_decision();old_event=prior_store.history(symbol)[-1];old_sha=sha256(prior_db)
                    debug_task=rescan_demo('Debug')
                    debug_db,debug_provider,new_symbol,debug_store=selected_demo(debug_task);assert new_symbol==symbol
                    expect(page.locator('.conclusion')).to_contain_text('需重新确认')
                    state=human_state(debug_task,symbol);assert state['decision']=='RECHECK_REQUIRED' and state['heads']==[]
                    assert any(old_event in row['events'] for row in state['prior_reviews'])
                    assert sha256(prior_db)==old_sha and prior_store.history(symbol)==[old_event]
                    assert get('/scans/'+debug_task['scan_id']+'/summary')['identity']['build_variant']=='Debug'
                    receipt['inheritance_scans'].append(dict(change='Release_to_Debug',before=cmake_task['scan_id'],after=debug_task['scan_id'],decision=state['decision']))
                    shot('09-build-change-requires-confirmation');passed('actual_build_variant_change_keeps_prior_safe_event_as_history_and_requires_new_confirmation')
                    test_safe_decision();debug_event=debug_store.history(symbol)[-1];debug_sha=sha256(debug_db)
                    changed_file=demo/'main.c';raw=changed_file.read_text('utf-8');assert 'g_counter = g_counter + 1;' in raw
                    changed_file.write_text(raw.replace('g_counter = g_counter + 1;','g_counter = g_counter + 3;',1),'utf-8')
                    source_task=rescan_demo()
                    source_db,source_provider,new_symbol,source_store=selected_demo(source_task);assert new_symbol==symbol
                    expect(page.locator('.conclusion')).to_contain_text('需重新确认')
                    state=human_state(source_task,symbol);assert state['decision']=='RECHECK_REQUIRED' and state['heads']==[]
                    assert any(debug_event in row['events'] for row in state['prior_reviews'])
                    assert any(old_event in row['events'] for row in state['prior_reviews'])
                    assert sha256(prior_db)==old_sha and sha256(debug_db)==debug_sha
                    assert original_teaching=={name:sha256(TOOL/'examples/stm32_demo'/name) for name in demo_before}
                    receipt['inheritance_scans'].append(dict(change='private_teaching_source_RMW_expression',before=debug_task['scan_id'],after=source_task['scan_id'],decision=state['decision'],original_repository_sources_unchanged=True))
                    shot('10-source-change-keeps-two-generations');passed('actual_private_source_change_keeps_two_generations_of_prior_events_without_inheriting_safe')
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
