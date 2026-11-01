"""Actual ARM/CMake/Clang compatibility of the unintegrated Windows write guard.

Uses the explicitly selected frozen public F030 input. This is not a production
dirty snapshot, private Git metadata isolation, or full H2/G8 acceptance.
"""
import argparse
import json
import os
from pathlib import Path
import sys

TOOL=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(TOOL))
from ecra.report_package import sha256
from ecra.studio.process_budget import ProcessBudget
from ecra.studio.write_guard import GuardedProcess,create_private_directory


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--firmware',type=Path,required=True);parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--work',type=Path,required=True);parser.add_argument('--private-root',type=Path,required=True)
    args=parser.parse_args()
    work=args.work.resolve()
    private=args.private_root.resolve();source=args.firmware.resolve()
    if private==source or private.is_relative_to(source) or source.is_relative_to(private):raise ValueError('Private root overlaps source')
    if private==TOOL or private.is_relative_to(TOOL):raise ValueError('Use an external private root')
    if work==source or work.is_relative_to(source) or work==TOOL or work.is_relative_to(TOOL):raise ValueError('Observer evidence must stay outside source and installation')
    work.mkdir(parents=True,exist_ok=False)
    before={p.relative_to(source).as_posix():sha256(p) for p in source.rglob('*') if p.is_file()}
    private=create_private_directory(private,source_root=source)
    code=r'''import ctypes,json,subprocess,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from ecra.studio.write_guard import Windows
from ecra.config import load_config
from ecra.compilation import prepare
from ecra.extract import Extractor
source,config,private=map(Path,sys.argv[2:5]);cfg,_=load_config(source,config)
units,coverage=prepare(source,cfg,build_firmware=False)
compiler=units[0]['original_arguments'][0]
import shutil
cmake=shutil.which('cmake');ninja=shutil.which('ninja');assert cmake and ninja
project=private/'project';project.mkdir()
q=lambda path:json.dumps(Path(path).as_posix())
text='cmake_minimum_required(VERSION 3.20)\nset(CMAKE_SYSTEM_NAME Generic)\nset(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)\nset(CMAKE_C_COMPILER '+q(compiler)+')\nproject(guard_f030 C)\n'
text+='add_executable(guard.elf '+ ' '.join(q(source/name) for name in ['startup.c','main.c','peripheral.c','utils.c'])+')\n'
text+='target_compile_options(guard.elf PRIVATE -mcpu=cortex-m0 -mthumb -Wall -g --specs=nosys.specs)\n'
text+='target_link_options(guard.elf PRIVATE -mcpu=cortex-m0 -mthumb --specs=nosys.specs -nostartfiles -Wl,-T,'+(source/'linker.ld').as_posix()+' -Wl,-gc-sections)\n'
(project/'CMakeLists.txt').write_text(text,encoding='utf-8')
commands=[[cmake,'-S',str(project),'-B',str(private/'build'),'-G','Ninja','-DCMAKE_MAKE_PROGRAM='+ninja],[cmake,'--build',str(private/'build'),'--parallel','2']]
records=[]
for command in commands:
 result=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',errors='replace')
 records.append(dict(command=command,returncode=result.returncode,stdout=result.stdout,stderr=result.stderr))
 if result.returncode:
  (private/'compatibility.json').write_text(json.dumps(dict(passed=False,commands=records),ensure_ascii=True,indent=2),encoding='utf-8');raise SystemExit(result.returncode)
unit=next(u for u in units if u['source_file']=='peripheral.c')
part=Extractor(dict(root=str(source),unit=unit,config=cfg)).run()
api=Windows();token=ctypes.wintypes.HANDLE();api.check(api.adv.OpenProcessToken(api.kernel.GetCurrentProcess(),8,ctypes.byref(token)))
try:integrity=api.integrity(token)
finally:api.kernel.CloseHandle(token)
receipt=dict(passed=integrity==0x1000 and part['parse_status'] in ['PARSED','PARTIAL'],integrity_rid=integrity,commands=records,
 native_elf=str(private/'build/guard.elf'),clang_tu=unit['source_file'],parse_status=part['parse_status'],
 diagnostics=part.get('diagnostics',[]),variables=len(part['variables']),accesses=len(part['accesses']))
(private/'compatibility.json').write_text(json.dumps(receipt,ensure_ascii=True,indent=2),encoding='utf-8')
print(json.dumps(receipt,ensure_ascii=True),flush=True)
raise SystemExit(0 if receipt['passed'] else 1)
'''
    process=None;budget=ProcessBudget(1024**3);result=dict(passed=False,scope=__doc__,
        config=str(args.config.resolve()),config_sha256=sha256(args.config.resolve()),
        python=sys.executable,source=str(source),private_root=str(private))
    try:
        with (work/'child.log').open('wb') as log:
            process=GuardedProcess([sys.executable,'-B','-c',code,str(TOOL),str(source),str(args.config.resolve()),str(private)],
                cwd=private,env=dict(os.environ,PYTHONIOENCODING='utf-8',TEMP=str(private),TMP=str(private),GIT_OPTIONAL_LOCKS='0'),log=log)
            budget.assign(process);process.resume();exit_code=process.wait(timeout=180)
        if (private/'compatibility.json').is_file():result.update(json.loads((private/'compatibility.json').read_text(encoding='utf-8')))
        result.update(exit_code=exit_code,resources=budget.sample(),source_unchanged=before=={p.relative_to(source).as_posix():sha256(p) for p in source.rglob('*') if p.is_file()})
        result['passed']=bool(result['passed'] and exit_code==0 and result['source_unchanged'])
        (work/'acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(dict(passed=result['passed'],parse_status=result.get('parse_status'),exit_code=exit_code)))
        return 0 if result['passed'] else 1
    finally:
        budget.close()
        if process:
            if process.poll() is None:process.terminate();process.wait(timeout=10)
            process.close()


if __name__=='__main__':raise SystemExit(main())
