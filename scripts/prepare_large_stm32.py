"""Prepare the pinned real Prusa MINI target without editing firmware sources.

Reuses the checkout/build on subsequent invocations. Install its three Python
build dependencies explicitly beforehand; ECRA itself needs no new packages.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

REPOSITORY = 'https://github.com/prusa3d/Prusa-Firmware-Buddy.git'
COMMIT = '570e86d56f6ca5ad36f5df984e52f2f20d542907'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--arm-toolchain', type=Path, required=True)
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    workspace.mkdir(parents=True,exist_ok=True)
    root = workspace/'Prusa-Firmware-Buddy'
    logs = workspace/'preparation'
    logs.mkdir(exist_ok=True)
    def execute(argv, cwd=workspace, label='command'):
        proc = subprocess.run([str(a) for a in argv],cwd=cwd,capture_output=True,text=True,encoding='utf-8',errors='replace')
        (logs/(label+'.log')).write_text(json.dumps([str(a) for a in argv])+'\n'+proc.stdout+proc.stderr,encoding='utf-8')
        if proc.returncode:
            raise RuntimeError(f'{label} failed: {proc.returncode}; see {logs}')
        return proc.stdout.strip()
    created = not root.exists()
    if created:
        execute(['git','clone','--no-checkout',REPOSITORY,root],label='clone')
    revision = execute(['git','rev-parse','HEAD'],root,label='revision')
    if revision != COMMIT:
        # Never reset an existing firmware checkout containing user changes.
        if not created and execute(['git','status','--porcelain','--untracked-files=no'],root,label='status'):
            raise ValueError('Tracked firmware modifications exist; preserve them and select another workspace')
        execute(['git','fetch','--depth','1','origin',COMMIT],root,label='fetch')
        execute(['git','checkout','--detach',COMMIT],root,label='checkout')
    version = execute([args.arm_toolchain/'bin/arm-none-eabi-gcc.exe','--version'],label='compiler')
    if '10.3.1 20210824' not in version:
        raise ValueError('Pinned target requires the documented ARM GCC 10.3-2021.10 toolchain')
    boot = root/'.dependencies/bootloader-mini-2.0.2/bootloader.bin'
    if not boot.is_file():
        execute([sys.executable,'-c',"import sys;sys.path.insert(0,'utils');import bootstrap;bootstrap.install_dependency('bootloader-mini')"],root,label='bootloader')
    build = root/'build/ecra-mini'
    execute(['cmake','-S',root,'-B',build,'-G','Ninja',
             '-DCMAKE_TOOLCHAIN_FILE='+str(root/'cmake/AnyGccArmNoneEabi.cmake'),
             '-DARM_TOOLCHAIN_DIR='+str(args.arm_toolchain.resolve()),
             '-DPython3_EXECUTABLE='+sys.executable,'-DCMAKE_MAKE_PROGRAM='+str(shutil.which('ninja')),
             '-DPRINTER=MINI','-DBOARD=BUDDY','-DMCU=STM32F407VG','-DBOOTLOADER=NO',
             '-DCMAKE_BUILD_TYPE=Release','-DCMAKE_EXPORT_COMPILE_COMMANDS=ON',
             '-DPRESET_COMPILE_OPTIONS=-D_DEFAULT_SOURCE'],root,label='configure')
    execute(['cmake','--build',build,'--parallel',str(args.workers)],root,label='build')
    entries = json.loads((build/'compile_commands.json').read_text(encoding='utf-8'))
    count = sum(Path(e['file']).suffix.lower() in {'.c','.cpp','.cc','.cxx'} for e in entries)
    if count < 226:
        raise ValueError(f'Insufficient real translation units: {count}')
    cfg = dict(version=1,project=dict(root=str(root),chip='STM32F407VG',core='Cortex-M4',native_word_bits=32),
        analysis=dict(compile_database='build/ecra-mini/compile_commands.json',auto_system_includes=True,
            include_dirs=[],exclude_dirs=[],exclude_files=[],exclude=[],build_closure_only=True,
            parse_timeout_seconds=600,extraction_workers=args.workers,output_dir='.ecra-full'),
        contexts=[dict(id='main',kind='MAIN',functions=['main'])],review=dict(enabled=False,prepare_packets=False))
    (workspace/'semantics-full.yaml').write_text(json.dumps(cfg,indent=2),encoding='utf-8')
    execute(['ninja','-C',build,'-t','query','firmware'],root,label='link-inputs')
    print(json.dumps(dict(commit=COMMIT,root=str(root),translation_units=count,config=str(workspace/'semantics-full.yaml'))))


if __name__ == '__main__':
    main()
