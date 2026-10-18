"""Reproducible, ground-truth-blind OpenCode benchmark on ST's CDC firmware.

The upstream is pinned; each scenario gets a separately linked firmware image.
Expectations stay outside every model-readable project. No board is flashed.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ecra.common import read_json, write_json
from ecra.config import load_config
from ecra.cli import safe_review_samples
from ecra.review import review_all, verify_receipt
from ecra.compilation import prepare as compilation_prepare
from ecra.extract import Extractor

FIXTURES = ROOT / 'tests/fixtures/stm32_cdc'
PIN = '94cae6e83f00e276a11957e7833c01ac3d0bd7af'
APP = Path('Projects/STM324xG_EVAL/Applications/USB_Device/CDC_Standalone')
SUBMODULES = ['Drivers/CMSIS/Device/ST/STM32F4xx', 'Drivers/STM32F4xx_HAL_Driver',
              'Drivers/BSP/STM324xG_EVAL', 'Drivers/BSP/Components/Common',
              'Drivers/BSP/Components/stmpe811']


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def command(argv, cwd, log, timeout=300, accepted=(0,)):
    result = subprocess.run([str(v) for v in argv], cwd=cwd, capture_output=True,
                            encoding='utf-8', errors='replace', timeout=timeout)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(result.stdout + result.stderr, encoding='utf-8')
    if result.returncode not in accepted:
        raise RuntimeError(f'Command exit {result.returncode}; see {log}')
    return result


def upstream(base):
    source = base/'upstream'
    if not (source/'.git').exists():
        command(['git', 'clone', '--depth', '1', '--filter=blob:none', '--sparse',
                 '--branch', 'v1.28.3', 'https://github.com/STMicroelectronics/STM32CubeF4.git', source],
                ROOT, base/'logs/clone.txt')
    actual = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, text=True).strip()
    if actual != PIN:
        raise ValueError(f'Wrong upstream commit: {actual}')
    command(['git', 'sparse-checkout', 'set', '--skip-checks', APP.as_posix(),
             'Drivers/CMSIS', *SUBMODULES[1:], 'Middlewares/ST/STM32_USB_Device_Library'],
            source, base/'logs/sparse.txt')
    command(['git', 'submodule', 'update', '--init', '--depth', '1', '--', *SUBMODULES],
            source, base/'logs/submodules.txt')
    revisions = {p: subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source/p,
                 text=True).strip() for p in SUBMODULES}
    write_json(base/'provenance.json', dict(repository='STMicroelectronics/STM32CubeF4',
        tag='v1.28.3', commit=actual, submodules=revisions, application=APP.as_posix(),
        board='STM324xG-EVAL', chip='STM32F407IG', rtos=False, flashed=False))
    return source


def copy_tree(source, target, *, links=False):
    def copier(src, dst):
        if links and not Path(dst).exists():
            try:
                os.link(src, dst)
                return dst
            except OSError:
                pass
        # Never modify a hard-linked upstream inode by overwriting it.
        if Path(dst).exists():
            if Path(src).read_bytes() == Path(dst).read_bytes():
                return dst
            Path(dst).unlink()
        return shutil.copy2(src, dst)
    shutil.copytree(source, target, dirs_exist_ok=True, copy_function=copier,
                    ignore=shutil.ignore_patterns('.git', '*.o', '*.a', '__pycache__'))


def prepare(base, cases):
    source = upstream(base)
    project = ET.parse(source/APP/'MDK-ARM/Project.uvprojx').getroot().find('./Targets/Target')
    mdk = source/APP/'MDK-ARM'
    files = [(mdk/p.text.replace('\\', '/')).resolve() for p in project.findall('.//FilePath')
             if p.text.lower().endswith('.c')]
    includes = [(mdk/p.replace('\\', '/')).resolve() for p in
                project.findtext('.//Cads/VariousControls/IncludePath').split(';')]
    # CMSIS core include is toolchain-injected in Keil, explicit for GCC.
    includes.append(source/'Drivers/CMSIS/Include')

    def relative(p):
        return (Path('Application')/p.relative_to(source/APP) if p.is_relative_to(source/APP)
                else p.relative_to(source)).as_posix()

    for case in cases:
        root = base/'projects'/case['id']
        root.mkdir(parents=True, exist_ok=True)
        copy_tree(source/APP, root/'Application')
        for directory in ['Drivers/CMSIS/Include', 'Drivers/CMSIS/Device/ST/STM32F4xx',
                          *SUBMODULES[1:], 'Middlewares/ST/STM32_USB_Device_Library']:
            copy_tree(source/directory, root/directory, links=True)
        app = root/'App'
        app.mkdir(exist_ok=True)
        for name in ('lab.h', 'board.c'):
            shutil.copy2(FIXTURES/name, app/name)
        text = (FIXTURES/(case['id']+'.c')).read_text(encoding='utf-8')
        if 'void Lab_OnTick(' not in text:
            text += '\nvoid Lab_OnTick(void) {}\n'
        (app/'lab.c').write_text(text, encoding='utf-8')
        main = root/'Application/Src/main.c'
        body = main.read_text(encoding='utf-8', errors='replace')
        body = body.replace('#include "main.h"', '#include "main.h"\n#include "lab.h"')
        body = body.replace('  USBD_Start(&USBD_Device);', '  USBD_Start(&USBD_Device);\n  Lab_Init();')
        body = body.replace('  while (1)\n  {\n  }', '  while (1)\n  {\n    Lab_Poll();\n  }', 1)
        main.write_text(body, encoding='utf-8')
        irq = root/'Application/Src/stm32f4xx_it.c'
        body = irq.read_text(encoding='utf-8').replace('#include "stm32f4xx_it.h"',
                                                    '#include "stm32f4xx_it.h"\n#include "lab.h"')
        if '#include "lab.h"' not in body:
            body = '#include "lab.h"\n'+body
        irq.write_text(body.replace('  HAL_IncTick();', '  HAL_IncTick();\n  Lab_OnTick();'), encoding='utf-8')
        linker = root/'Application/STM32CubeIDE/STM32F407IGHX_FLASH.ld'
        # CubeIDE's READONLY section annotation needs newer binutils; section
        # contents already carry read-only ELF flags in the GCC 10.3 toolchain.
        linker.write_text(linker.read_text(encoding='utf-8').replace('(READONLY)', ''), encoding='utf-8')
        (root/'cmake').mkdir(exist_ok=True)
        (root/'cmake/arm.cmake').write_text('''set(CMAKE_SYSTEM_NAME Generic)
set(CMAKE_SYSTEM_PROCESSOR arm)
set(CMAKE_C_COMPILER arm-none-eabi-gcc)
set(CMAKE_ASM_COMPILER arm-none-eabi-gcc)
set(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)
''', encoding='utf-8')
        all_files = [relative(p) for p in files] + ['App/board.c', 'App/lab.c',
            'Application/STM32CubeIDE/Application/User/syscalls.c',
            'Application/STM32CubeIDE/Application/User/sysmem.c',
            'Application/STM32CubeIDE/Application/Startup/startup_stm32f407ighx.s']
        cmake = '''cmake_minimum_required(VERSION 3.20)
project(st_cdc_benchmark C ASM)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
add_executable(firmware
''' + '\n'.join('  '+v for v in all_files) + ''')
target_include_directories(firmware PRIVATE App
''' + '\n'.join('  '+relative(p) for p in includes) + ''')
target_compile_definitions(firmware PRIVATE USE_HAL_DRIVER STM32F407xx USE_STM324xG_EVAL USE_USB_FS)
target_compile_options(firmware PRIVATE -mcpu=cortex-m4 -mthumb -mfpu=fpv4-sp-d16 -mfloat-abi=hard -Og -fno-inline -g3 -ffunction-sections -fdata-sections)
target_link_options(firmware PRIVATE -mcpu=cortex-m4 -mthumb -mfpu=fpv4-sp-d16 -mfloat-abi=hard --specs=nano.specs --specs=nosys.specs -Wl,--gc-sections -Wl,-Map=firmware.map "-T${CMAKE_CURRENT_SOURCE_DIR}/Application/STM32CubeIDE/STM32F407IGHX_FLASH.ld")
set_target_properties(firmware PROPERTIES SUFFIX .elf)
'''
        # A commercial-style binary-only board policy is intentionally opaque
        # to source review. Its authoring source/ground truth stay outside root.
        if case['id'] in {'p17', 'p18'}:
            (root/'BoardBinary').mkdir(exist_ok=True)
            board_source = FIXTURES/'private_board.c'
            command(['arm-none-eabi-gcc', '-mcpu=cortex-m4', '-mthumb', '-mfpu=fpv4-sp-d16', '-mfloat-abi=hard', '-c', board_source,
                     '-o', root/'BoardBinary/policy.o'], ROOT, root/'build-policy.txt')
            cmake += 'target_link_libraries(firmware PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/BoardBinary/policy.o")\n'
        (root/'CMakeLists.txt').write_text(cmake, encoding='utf-8')
        command(['cmake', '-S', root, '-B', root/'build', '-G', 'Ninja',
                 '-DCMAKE_TOOLCHAIN_FILE=cmake/arm.cmake'], ROOT, root/'configure.txt')
        command(['cmake', '--build', root/'build', '-j', '6'], ROOT, root/'build.txt')
        elf = root/'build/firmware.elf'
        symbols = subprocess.check_output(['arm-none-eabi-nm', '-S', elf], text=True)
        (root/'symbols.txt').write_text(symbols, encoding='utf-8')
        cfg = dict(version=1, project=dict(root=str(root), chip='STM32F407IG', core='Cortex-M4',
            native_word_bits=32, nvic_priority_bits=4), analysis=dict(
            compile_database='build/compile_commands.json', include_dirs=['Application/Src','App'],
            exclude_dirs=['Drivers','Middlewares','build','.ecra'],
            exclude_files=['Application/Src/system_stm32f4xx.c'], auto_system_includes=True,
            output_dir='.ecra', open_report=False, expected_defines=['STM32F407xx','USE_USB_FS']),
            contexts=[dict(id='main',kind='MAIN',functions=['main'])],
            review=dict(enabled=False, command=['opencode'], timeout_seconds=360, retries=0,workers=1))
        config = root/'config'
        config.mkdir(exist_ok=True)
        write_json(config/'semantics.yaml',cfg)
        shutil.copy2(ROOT/'config/concurrency_cases.md',config/'concurrency_cases.md')
        write_json(root/'build-evidence.json',dict(elf_sha256=sha(elf), elf_size=elf.stat().st_size,
            translation_units=len(read_json(root/'build/compile_commands.json')), main_sha256=sha(main),
            lab_sha256=sha(app/'lab.c'), expectation_sha256=sha(FIXTURES/'expectations.json')))
        print('BUILD',case['id'],elf.stat().st_size,flush=True)


def scan(base,cases,cache_only=False):
    """Use the normal CLI pipeline with audited immutable-TU transport caching.

    This only reuses real Clang responses, never analysis verdicts/model answers.
    Every source/header hash and normalized compile request must match. The
    scenario TU differs between variants and is parsed for its own source hash.
    """
    from ecra.cli import run
    from ecra.common import execute
    cache=base/'extract-cache'
    cache.mkdir(exist_ok=True)
    engine_hash=hashlib.sha256(''.join(sha(p) for p in sorted((ROOT/'ecra').glob('*.py'))).encode()).hexdigest()
    # Initialize the libclang binding before concurrent, independent TU parses.
    from clang.cindex import Index
    Index.create()
    for case in cases:
        root=base/'projects'/case['id']
        cfg,_=load_config(root,root/'config/semantics.yaml')
        units,_=compilation_prepare(root,cfg)

        def relocate(value,old,new):
            if isinstance(value,str):return value.replace(str(old),str(new)).replace(old.as_posix(),new.as_posix())
            if isinstance(value,list):return [relocate(v,old,new) for v in value]
            if isinstance(value,dict):return {relocate(k,old,new):relocate(v,old,new) for k,v in value.items()}
            return value

        def warm(unit):
            request=dict(root=str(root),unit=unit,config=cfg)
            normalized=relocate(request,root,Path('PROJECT_ROOT'))
            # Include source content in the key so independently scanned
            # scenarios never overwrite each other's cache entries.
            key=hashlib.sha256((engine_hash+sha(unit['source'])+json.dumps(normalized,sort_keys=True)).encode()).hexdigest()
            meta=cache/(key+'.json')
            body=cache/(key+'.response.json')
            if meta.exists() and body.exists():
                old=read_json(meta)
                origin=Path(old['root'])
                valid=all(Path(relocate(p,origin,root)).is_file() and
                          sha(Path(relocate(p,origin,root)))==h for p,h in old['inputs'].items())
                valid=valid and old['response_sha256']==sha(body)
                if valid:return unit['tu_id'],(meta,body,True)
            existing=root/'.ecra/workers'/(unit['tu_id']+'.response.json')
            existing_request=existing.with_name(unit['tu_id']+'.request.json')
            if existing.exists() and existing_request.exists() and read_json(existing_request)==request:
                part=read_json(existing)
                inputs=[Path(unit['source']),*[Path(p) for p in part.get('includes',[])]]
                if any(p.is_file() and p.stat().st_mtime_ns>existing.stat().st_mtime_ns for p in inputs):
                    part=Extractor(request).run()
            else:
                part=Extractor(request).run()
            inputs=[Path(unit['source']),*[Path(p) for p in part.get('includes',[])]]
            hashes={str(p):sha(p) for p in inputs if p.is_file()}
            write_json(body,part)
            write_json(meta,dict(root=str(root),inputs=hashes,response_sha256=sha(body)))
            return unit['tu_id'],(meta,body,False)

        # libclang handles separate translation units. A short-lived child
        # per TU is unnecessary here; the ordinary scanner still receives the
        # same serialized responses at its existing extraction boundary.
        with ThreadPoolExecutor(max_workers=4) as pool:
            prepared=dict(pool.map(warm,units))
        stats=dict(reused=sum(v[2] for v in prepared.values()),extracted=sum(not v[2] for v in prepared.values()))
        print('EXTRACTION',case['id'],stats,flush=True)
        if cache_only:
            continue

        def transport(argv,**kwargs):
            if len(argv)>3 and argv[1:3]==['-m','ecra.extract']:
                request=read_json(Path(argv[3]))
                meta,body,_=prepared[request['unit']['tu_id']]
                origin=Path(read_json(meta)['root'])
                write_json(Path(argv[4]),relocate(read_json(body),origin,root))
                return subprocess.CompletedProcess(argv,0,'','')
            return execute(argv,**kwargs)
        with patch('ecra.cli.execute',side_effect=transport):
            # run() is otherwise unchanged: merge, external-call gaps,
            # analyze, report, queue and scan checkpoint all run normally.
            code=run(root,str(root/'config/semantics.yaml'),no_review=True)
        if code not in (0,1,2):raise ValueError('Unexpected scanner exit')
        facts=read_json(root/'.ecra/facts.json')
        write_json(root/'scan-evidence.json',dict(variables=len(facts['variables']),
            extraction_cache=stats,
            units=len(facts.get('translation_units',[])),parse_statuses={
                s:sum(u.get('parse_status')==s for u in facts.get('translation_units',[]))
                for s in {u.get('parse_status') for u in facts.get('translation_units',[])}}))
        print('SCAN',case['id'],len(facts['variables']),flush=True)


def review_one(base,case,args):
    root=base/'projects'/case['id']
    if args.wait_for_scan:
        deadline=time.monotonic()+1800
        while not (root/'scan-evidence.json').exists():
            if time.monotonic()>deadline:raise TimeoutError(f"{case['id']}: scan did not finish")
            time.sleep(2)
    if args.after_round:
        deadline=time.monotonic()+1800
        while not (base/'results'/args.after_round/(case['id']+'.json')).exists():
            if time.monotonic()>deadline:raise TimeoutError(f"{case['id']}: previous review did not finish")
            time.sleep(2)
    if args.refresh_library:
        shutil.copy2(ROOT/'config/concurrency_cases.md',root/'config/concurrency_cases.md')
    cfg,_=load_config(root,root/'config/semantics.yaml')
    cfg['review'].update(enabled=True,model=args.model,workers=1,facts_path=str(root/'.ecra/facts.json'),
                         timeout_seconds=args.timeout)
    facts=read_json(root/'.ecra/facts.json')
    full=read_json(root/'.ecra/reports/global_static_concurrency.json')
    selected=[]
    target_by_id={}
    for name in case['targets']:
        variable=next(v for v in facts['variables'] if v.get('canonical_path',v['qualified_name'])==name)
        finding=next((f for f in full['findings'] if f.get('symbol_id')==variable['symbol_id']),None)
        if finding is None:
            finding=next(f for f in safe_review_samples(facts,len(facts['variables']),len(facts['variables']))
                         if f['symbol_id']==variable['symbol_id'])
        selected.append(finding)
        target_by_id[finding['finding_id']]=name
    report=copy.deepcopy(full)
    report['findings']=selected
    report.pop('review_safe_samples',None)
    out=root/'.ecra'/args.round
    start=time.monotonic()
    # Explicitly audit the chosen SAFE samples too. Ordinary `review` mode
    # intentionally selects only SUSPECT/UNKNOWN; the full scan stays intact.
    if args.phase=='collect':
        rows=read_json(out/'review/queue.json')
    else:
        rows=review_all(root,out,cfg,facts,report,full['fingerprint'],mode='run',
            case_library_path=root/'config/concurrency_cases.md',review_context_path=root/'config/review_context.md',
            progress=lambda s:print(case['id'],s,flush=True))
    observations=[]
    for row in rows:
        target=target_by_id[row['finding_id']]
        if row['state']=='DONE': verify_receipt(root,out/'review',row)
        packet=read_json(out/'review'/row['packet_file']) if row.get('packet_file') else {}
        reads=[]
        current_attempts=row.get('attempts',[])[row.get('attempt_start',0):]
        elapsed=sum((datetime.fromisoformat(a['finished'])-datetime.fromisoformat(a['started'])).total_seconds()
                    for a in current_attempts if a.get('started') and a.get('finished'))
        for attempt in current_attempts:
            for line in (out/'review'/attempt['stdout_file']).read_text(encoding='utf-8').splitlines():
                try: event=json.loads(line)
                except json.JSONDecodeError:continue
                part=event.get('part') or {}; state=part.get('state') or {}
                if event.get('type')=='tool_use' and part.get('tool')=='read' and state.get('status')=='completed':
                    reads.append(state.get('input') or {})
        observations.append(dict(case=case['id'],target=target,category=case['category'],finding_id=row['finding_id'],
            review_directory=str(out/'review'),packet_file=row.get('packet_file'),
            state=row['state'],status=row.get('status'),error=row.get('error'),answer=row.get('answer'),
            static_classification=packet.get('static_classification',row.get('static_classification')),expected=case['allowed'],
            meets_expected=row['state']=='DONE' and (not case['allowed'] or row.get('status') in case['allowed']),
            source_reads=[r for r in reads if r.get('filePath','').endswith(('.c','.h'))],
            case_reads=[r for r in reads if 'case-library' in r.get('filePath','')],
            seconds=round(elapsed,2),receipt_verified=row['state']=='DONE',
            prompt_chars=len((out/'review'/row['prompt_file']).read_text(encoding='utf-8')) if row.get('prompt_file') else 0,
            attempts=row.get('attempt_count',0),stages=[a['stage'] for a in row.get('attempts',[])[row.get('attempt_start',0):]]))
    write_json(base/'results'/args.round/(case['id']+'.json'),observations)
    return observations


def export(base):
    """Publish small, inspectable observations without shipping vendor trees."""
    cases=read_json(FIXTURES/'expectations.json')['cases']
    builds=[]
    for case in cases:
        root=base/'projects'/case['id']
        evidence=read_json(root/'build-evidence.json')
        evidence.update(case=case['id'],scan=read_json(root/'scan-evidence.json'))
        if evidence['scan']['parse_statuses']!={'PARSED':39}:raise ValueError('Incomplete TU extraction')
        builds.append(evidence)
    rounds={}
    for folder in sorted((base/'results').iterdir()):
        if not folder.is_dir():continue
        rows=[r for f in sorted(folder.glob('p*.json')) for r in read_json(f)]
        for row in rows:
            root=base/'projects'/row['case']
            review=root/'.ecra'/folder.name/'review'
            queue=read_json(review/'queue.json')
            receipt=next(r for r in queue if (r.get('answer') or {}).get('finding_id')==row.get('answer',{}).get('finding_id')) if row.get('answer') else None
            if receipt:
                verify_receipt(root,review,receipt)
                row['finding_id']=receipt['finding_id']
                row['artifacts']=dict(directory=str(review.relative_to(ROOT)),
                    packet=receipt['packet_file'],packet_sha256=receipt['packet_sha256'],
                    prompt=receipt['prompt_file'],prompt_sha256=receipt['prompt_sha256'],
                    receipt_sha256=sha(review/(receipt['finding_id']+'.result.json')),
                    executions=[{k:a[k] for k in ('model','stage','started','finished','stdout_file','stdout_sha256') if k in a}
                                for a in receipt['attempts'][receipt.get('attempt_start',0):]])
        rounds[folder.name]=rows
    initial=[r for r in rounds.get('round1',[]) if r['category']!='baseline']
    if len(initial)!=20 or len({r['case'] for r in initial})!=20:raise ValueError('All 20 independent cases required')
    host=read_json(base/'host-replays/results.json')
    models=sorted({a['model'] for rows in rounds.values() for r in rows
                   for a in r.get('artifacts',{}).get('executions',[]) if a.get('model')})
    result=dict(date='2026-10-18',models=models,provenance=read_json(base/'provenance.json'),
        tools=read_json(base/'tool-versions.json'),expectations=cases,builds=builds,
        cache_audit=read_json(base/'cache-audit.json'),host_replays=host,rounds=rounds,
        scored_initial=dict(total=20,done=sum(r['state']=='DONE' for r in initial),
                            status_agrees=sum(r['meets_expected'] for r in initial)),
        provider_stop=read_json(base/'provider-stop.json') if (base/'provider-stop.json').exists() else None,
        final_verification=read_json(base/'final-verification.json') if (base/'final-verification.json').exists() else None,
        limitation='Source-level controlled matrix and selected native variables only; no board flash or physical timing validation.')
    # Preserve relative project paths in the durable, tracked report.
    def relative_paths(value):
        if isinstance(value,str):return value.replace(str(ROOT)+'\\','').replace(ROOT.as_posix()+'/','')
        if isinstance(value,list):return [relative_paths(v) for v in value]
        if isinstance(value,dict):return {k:relative_paths(v) for k,v in value.items()}
        return value
    write_json(ROOT/'docs/stm32_cube_cdc_validation_results.json',relative_paths(result))
    print('EXPORTED',result['scored_initial'])


def binary_context(base):
    """Attach reproducible compiler observations, without a suggested verdict."""
    root=base/'projects/p00'
    elf=root/'build/firmware.elf'
    assembly=subprocess.check_output(['arm-none-eabi-objdump','-d',
        '--disassemble=HAL_TIM_PeriodElapsedCallback',str(elf)],text=True)
    symbols=subprocess.check_output(['arm-none-eabi-nm','-S',str(elf)],text=True)
    relevant='\n'.join(s for s in symbols.splitlines() if s.endswith((' UserTxBufPtrIn',' UserTxBufPtrOut')))
    (base/'native-callback-disassembly.txt').write_text(assembly,encoding='utf-8')
    text=('当前GNU ARM构建的补充观测，仅为事实数据，不是安全结论。请与源码及Packet共同评估。\n'
          f'ELF SHA256: {sha(elf)}\nflags: -Og -fno-inline, Cortex-M4, GCC 10.3.1\n'
          f'nm -S:\n{relevant}\nobjdump:\n~~~asm\n{assembly}\n~~~\n'
          '不可将此构建的指令序列推广到其他优化级别或不同源码。\n')
    (root/'config/review_context.md').write_text(text,encoding='utf-8')
    print('BUILD_CONTEXT',sha(elf),len(text),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase',choices=['prepare','cache','scan','review','collect','summary','export','binary-context'])
    p.add_argument('--base',type=Path,default=ROOT/'validation/stm32_cube_cdc_20261018')
    p.add_argument('--cases',default='')
    p.add_argument('--round',default='round1')
    p.add_argument('--model',default='kimi/kimi-k2.7-code')
    p.add_argument('--workers',type=int,default=3)
    p.add_argument('--targets',default='',help='Optional exact variable names, comma separated')
    p.add_argument('--timeout',type=int,default=360)
    p.add_argument('--wait-for-scan',action='store_true')
    p.add_argument('--after-round',default='',help='Wait for that case in an earlier round before review')
    p.add_argument('--refresh-library',action='store_true',help='Copy the current library before this case review')
    args=p.parse_args();args.base=args.base.resolve()
    cases=read_json(FIXTURES/'expectations.json')['cases']
    if args.cases: cases=[c for c in cases if c['id'] in args.cases.split(',')]
    if args.targets:
        cases=[dict(c,targets=[n for n in c['targets'] if n in args.targets.split(',')]) for c in cases]
        cases=[c for c in cases if c['targets']]
    if not cases:raise ValueError('No cases selected')
    args.base.mkdir(parents=True,exist_ok=True)
    original=sha(ROOT/'config/semantics.yaml')
    if args.phase=='prepare':prepare(args.base,cases)
    elif args.phase in ('cache','scan'):scan(args.base,cases,cache_only=args.phase=='cache')
    elif args.phase in ('review','collect'):
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for future in as_completed([pool.submit(review_one,args.base,c,args) for c in cases]):
                for item in future.result():print('RESULT',item['case'],item['target'],item['status'],item['meets_expected'],flush=True)
    elif args.phase=='export':export(args.base)
    elif args.phase=='binary-context':binary_context(args.base)
    else:
        rows=[r for f in sorted((args.base/'results'/args.round).glob('p*.json')) for r in read_json(f)]
        write_json(args.base/'results'/args.round/'summary.json',rows)
        print(json.dumps([dict(case=r['case'],target=r['target'],status=r['status'],pass_=r['meets_expected']) for r in rows],ensure_ascii=False,indent=2))
    if original!=sha(ROOT/'config/semantics.yaml'):raise ValueError('User central config unexpectedly changed')


if __name__=='__main__': main()
