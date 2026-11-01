"""Build a real, independently compared Studio teaching archive from repo demo.

Never runs setup_demo.py or writes the original demo/user configuration. All
build/scan products use explicitly selected fresh external directories. This
two-TU object target is not a linked STM32 firmware or an additional G2 project.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

TOOL=Path(__file__).resolve().parents[1]


def sha(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024**2),b''):value.update(block)
    return value.hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['engine','original-engine','source-copy','build','data','old-data','work','cmake','ninja','compiler']:
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();sys.path.insert(0,str(args.engine.resolve()))
    from ecra.workspace import no_links
    from ecra.report_package import export_report,import_report
    from ecra.scan_store import EvidenceProvider
    import yaml
    work=no_links(args.work)
    roots=[no_links(getattr(args,name)) for name in ['source_copy','build','data','old_data','work']]
    for i,root in enumerate(roots):
        for protected in [TOOL,args.engine.resolve(),args.original_engine.resolve()]:
            if root==protected or root.is_relative_to(protected) or protected.is_relative_to(root):raise ValueError('Use external fresh recipe/build/scan roots')
        if any(root==other or root.is_relative_to(other) or other.is_relative_to(root) for other in roots[:i]):raise ValueError('Recipe roots must not overlap')
    source,build,data,old_data,_=roots
    for root in [source,build,data,old_data,work]:
        if root.exists():raise FileExistsError(str(root))
    work.mkdir(parents=True)
    (work/'builder.py').write_bytes(Path(__file__).read_bytes())
    source.mkdir(parents=True);build.mkdir(parents=True)
    origin=TOOL/'examples/stm32_demo';names=['main.c','other.c','shared.h','CMakeLists.txt','semantics.yaml']
    original={name:dict(sha256=sha(origin/name),mtime_ns=(origin/name).stat().st_mtime_ns,size=(origin/name).stat().st_size) for name in names}
    for name in names:shutil.copy2(origin/name,source/name)
    copied={name:dict(sha256=sha(source/name),mtime_ns=(source/name).stat().st_mtime_ns,size=(source/name).stat().st_size) for name in names}
    toolchain=work/'arm-toolchain.cmake'
    toolchain.write_text('set(CMAKE_SYSTEM_NAME Generic)\nset(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)\nset(CMAKE_C_COMPILER '+json.dumps(args.compiler.resolve().as_posix())+')\nset(CMAKE_C_FLAGS_INIT "-mcpu=cortex-m7 -mthumb -std=c11")\n','utf-8')
    commands=[]
    def command(label,argv,cwd=TOOL):
        log=work/(label+'.log');start=time.monotonic()
        with log.open('xb') as output:code=subprocess.call(list(map(str,argv)),cwd=cwd,stdout=output,stderr=subprocess.STDOUT)
        commands.append(dict(label=label,argv=list(map(str,argv)),exit_code=code,seconds=time.monotonic()-start,log=str(log),log_sha256=sha(log)))
        if code:raise RuntimeError(label+' failed; see '+str(log))
    command('cmake-configure',[args.cmake,'-S',source,'-B',build,'-G','Ninja','-DCMAKE_MAKE_PROGRAM='+str(args.ninja.resolve()),'-DCMAKE_TOOLCHAIN_FILE='+str(toolchain)])
    command('arm-object-build',[args.cmake,'--build',build,'--target','demo','--parallel','2'])
    database=build/'compile_commands.json';units=json.loads(database.read_text('utf-8'));assert len(units)==2
    cfg=yaml.safe_load((origin/'semantics.yaml').read_text('utf-8'))
    cfg['project'].update(root=str(source),name='内置教学示例 · STM32对象目标')
    cfg['analysis'].pop('output_dir',None)
    # Explicit custom is supported by both the original e69 and formal Studio;
    # the original engine predates the new user location enum.
    cfg['analysis'].update(output=dict(location='custom',custom_dir=str(old_data)),compile_database=str(database),auto_system_includes=True,allow_external_toolchain=True)
    config=work/'semantics.yaml';config.write_text(yaml.safe_dump(cfg,allow_unicode=True,sort_keys=False),'utf-8')
    # The original supports custom output; the canonical observer explicitly
    # injects a second fresh WorkspaceResolver instance without editing config.
    # Both runs therefore consume the very same config path and bytes.
    command('original-native',[sys.executable,'-B','-X','utf8',TOOL/'scripts/measure_native_golden.py','--engine',args.original_engine,'--config',config,'--data-root',old_data,'--work',work/'original-native','--mode','legacy','--limit-gib','2'])
    old_manifest={p.relative_to(old_data).as_posix():sha(p) for p in old_data.rglob('*') if p.is_file()}
    sample_id='builtin-stm32-demo-v1'
    command('new-native',[sys.executable,'-B','-X','utf8',TOOL/'scripts/measure_native_golden.py','--engine',args.engine,'--config',config,'--data-root',data,'--work',work/'new-native','--mode','canonical','--limit-gib','2','--scan-id',sample_id,'--profile-id','builtin-stm32-demo'])
    assert old_manifest=={p.relative_to(old_data).as_posix():sha(p) for p in old_data.rglob('*') if p.is_file()}
    command('original-graph',[sys.executable,'-B','-X','utf8',TOOL/'scripts/measure_baseline_graph.py','--execution',work/'original-native/execution.json','--engine',args.engine,'--work',work/'original-graph','--limit-gib','2'])
    out=data/'scans'/sample_id
    command('full-semantic-comparison',[sys.executable,'-B','-X','utf8',TOOL/'scripts/compare_native_graphs.py','--before',work/'original-graph/original-graph.db','--after',out/'scan.db','--receipt',work/'semantic-comparison.json','--envelope',work/'runtime-envelope.jsonl'])
    provider=EvidenceProvider(out/'scan.db');binding=provider.validate(deep=True)
    from ecra.scan_persistence import archive_audit
    audit=archive_audit(out)
    (out/'manifest.json').write_text(json.dumps(dict(binding,format='ECRA_LOCAL_SCAN',version=1,state='STATIC_VALIDATED',source_reverification=True,scan_sha256=sha(out/'scan.db'),**audit),ensure_ascii=False,indent=2),'utf-8')
    destination=work/'package';destination.mkdir();package=destination/'stm32-demo.ecra-report'
    export_report(out,package)
    imported=import_report(package,work/'viewer-check');assert imported['scan_id']==sample_id
    assert provider.roots()==EvidenceProvider(work/'viewer-check/scans'/sample_id/'scan.db').roots()
    for name in names:
        for root,expected in [(origin,original),(source,copied)]:
            p=root/name;assert dict(sha256=sha(p),mtime_ns=p.stat().st_mtime_ns,size=p.stat().st_size)==expected[name]
    metadata=dict(format='ECRA_BUILTIN_SAMPLE_V1',filename=package.name,sha256=sha(package),bytes=package.stat().st_size,
                  scan_id=binding['scan_id'],project_id=binding['project_id'],facts_hash=binding['facts_hash'],report_hash=binding['report_hash'],
                  title='STM32并发访问教学示例',notice='教学示例 · 真实扫描归档 · 非用户工程。2个TU实际ARM对象编译/Clang分析，未链接固件、无硬件验证；未知与覆盖缺口按实保存。',
                  sources=original,license='Repository project terms; no standalone LICENSE file declared in this checkout',native_tus=2,linked_firmware=False,hardware_verified=False)
    (destination/'sample.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n','utf-8')
    receipt=dict(passed=True,scope=__doc__,engine=str(args.engine),original_engine=str(args.original_engine),commands=commands,builder_sha256=sha(work/'builder.py'),
                 original_files_unchanged=True,copied_files_unchanged=True,original_native_bytes_unchanged_after_new=True,
                 measurement_scope='Independent native CLI bodies under separate fresh external roots; same config and compile DB; no G2/physical32GB/hardware claim',
                 native_receipts={name:dict(path=str(work/name/'execution.json'),sha256=sha(work/name/'execution.json')) for name in ['original-native','new-native']},
                 semantic_comparison=json.loads((work/'semantic-comparison.json').read_text('utf-8')),
                 tools={name:dict(path=str(getattr(args,name).resolve()),sha256=sha(getattr(args,name))) for name in ['cmake','ninja','compiler']},sample=metadata)
    (work/'acceptance.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n','utf-8')
    print(json.dumps(dict(passed=True,package=str(package),bytes=metadata['bytes'],sha256=metadata['sha256'])),flush=True)


if __name__=='__main__':main()
