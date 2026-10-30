"""准备真实 INAV STM32H743 固件的隔离副本；不修改原仓库。"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

COMMIT = 'ed7fb3bb3216f8215150b42b52cb7b724e1dfae8'
REPOSITORY = 'https://github.com/iNavFlight/inav.git'


def windows_settings(text):
    # Only build glue: keep the official Ruby settings generator and flags.
    lines = text.splitlines()
    if sum(' -E env ' in line for line in lines) != 1:
        raise ValueError('上游设置生成器结构变化，禁止继续应用适配')
    lines = ['            ${CMAKE_COMMAND} -E env "CFLAGS=${settings_cflags}" "TARGET=${name}" "SETTINGS_CXX=${args_SETTINGS_CXX}"'
             if ' -E env ' in line else line for line in lines]
    text = '\n'.join(lines) + '\n'
    return text.replace('    set(output ${dir}/${SETTINGS_GENERATED_H} ${dir}/${SETTINGS_GENERATED_C})',
        '    if(NOT args_SETTINGS_CXX)\n        set(args_SETTINGS_CXX arm-none-eabi-g++)\n    endif()\n'
        '    string(JOIN " " settings_cflags ${cflags})\n'
        '    set(output ${dir}/${SETTINGS_GENERATED_H} ${dir}/${SETTINGS_GENERATED_C})').replace(
        '        DEPENDS ${SETTINGS_GENERATOR} ${SETTINGS_FILE}',
        '        VERBATIM\n        DEPENDS ${SETTINGS_GENERATOR} ${SETTINGS_FILE}')


def configuration(root, ruby):
    return dict(version=1, project=dict(root=str(root), chip='STM32H743XI', core='Cortex-M7', native_word_bits=32),
        analysis=dict(compile_database='auto', auto_system_includes=True, build_closure_only=True,
            include_dirs=[], exclude_dirs=[], exclude_files=[], exclude=[], extraction_workers=8,
            parse_timeout_seconds=600, output_dir='.ecra',
            cmake=dict(build_dir='build/ecra', generator='Ninja', target='MATEKH743.elf', build_type='Release',
                       build=True, build_args=['--parallel', '6'], timeout_seconds=1200,
                       args=['-DRUBY_EXECUTABLE='+ruby.as_posix()]),
            build_closure=dict(elf='build/ecra/bin/MATEKH743.elf', map='build/ecra/bin/MATEKH743.elf.map'),
            git_diff=dict(enabled=False, base_ref='ecra-validation-base',
                          include_uncommitted=True, cache_enabled=True, verify_against_full=False)),
        contexts=[dict(id='main', kind='MAIN', functions=['main'])],
        review=dict(enabled=False, prepare_packets=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', default=REPOSITORY, help='官方仓库 URL 或已有的同提交干净仓库')
    parser.add_argument('--work', type=Path, required=True, help='必须不存在的新目录')
    parser.add_argument('--ruby', type=Path, required=True, help='实际 ruby.exe，需具备标准库')
    parser.add_argument('--compiler-bin', type=Path, required=True, help='ARM GCC 10.3-2021.10 的 bin 目录')
    args = parser.parse_args()
    root, ruby, compiler = args.work.resolve(), args.ruby.resolve(), args.compiler_bin.resolve()
    if root.exists():
        parser.error('工作副本已存在，禁止覆盖')
    if not ruby.is_file() or not (compiler/'arm-none-eabi-gcc.exe').is_file():
        parser.error('Ruby 或 ARM GCC 不存在')
    evidence = root.with_name(root.name+'-preparation')
    evidence.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ, PATH=str(compiler)+os.pathsep+str(ruby.parent)+os.pathsep+os.environ.get('PATH', ''))
    result = dict(complete=False, upstream=REPOSITORY, upstream_commit=COMMIT, project=str(root), commands=[])
    receipt = evidence/'preparation.json'
    def save():
        receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    def run(label, argv, cwd=None):
        started = time.monotonic()
        with (evidence/(label+'.log')).open('w', encoding='utf-8') as log:
            p = subprocess.run([str(a) for a in argv], cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT)
        result['commands'].append(dict(label=label, argv=[str(a) for a in argv], exit_code=p.returncode,
                                       seconds=time.monotonic()-started))
        save()
        if p.returncode:
            raise RuntimeError('工程准备失败：'+label+'；详见 '+str(evidence))
    save()
    run('init', ['git', 'init', root])
    run('origin', ['git', 'remote', 'add', 'origin', args.source], root)
    run('fetch-pin', ['git', 'fetch', '--depth', '1', 'origin', COMMIT], root)
    run('select-new-snapshot', ['git', 'switch', '--detach', COMMIT], root)
    actual = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    if actual != COMMIT:
        raise RuntimeError('上游提交不符合固定版本，禁止继续')
    path = root/'cmake/settings.cmake'
    path.write_text(windows_settings(path.read_text(encoding='utf-8')), encoding='utf-8')
    with (root/'.gitignore').open('a', encoding='utf-8') as stream:
        stream.write('\n# ECRA isolated validation artifacts\n.ecra*/\n')
    run('stage-build-adapter', ['git', 'add', 'cmake/settings.cmake', '.gitignore'], root)
    run('commit-build-adapter', ['git', '-c', 'user.name=ECRA validation', '-c', 'user.email=ecra@example.invalid',
                                'commit', '-m', 'build: adapt settings generator argument passing for Windows'], root)
    run('pin-base', ['git', 'branch', 'ecra-validation-base'], root)
    build = root/'build/ecra'
    run('configure', ['cmake', '-S', root, '-B', build, '-G', 'Ninja', '-DCMAKE_BUILD_TYPE=Release',
                     '-DCMAKE_EXPORT_COMPILE_COMMANDS=ON', '-DRUBY_EXECUTABLE='+ruby.as_posix()])
    run('build-elf', ['cmake', '--build', build, '--target', 'MATEKH743.elf', '--parallel', '6'])
    cfg = configuration(root, ruby)
    config = root.with_name(root.name+'-semantics.yaml')
    config.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')
    result.update(complete=True, config=str(config), base_sha=subprocess.check_output(
        ['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip(),
        build_adapter='仅修正 Windows 环境参数、显式设置生成器编译器；没有修改固件业务逻辑')
    save()
    print('真实 H743 ELF 构建完成：'+str(config), flush=True)


if __name__ == '__main__':
    main()
