"""用实际 Portable 工具在中文空格路径验证目标闭包、响应文件及差异模式；关闭复核。"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

TOOL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL))
from ecra.common import read_json, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True, help='必须不存在的新目录；建议含中文及空格')
    args = parser.parse_args()
    bundle, root = args.bundle.resolve(), args.work.resolve()
    if root.exists() or root.is_relative_to(bundle):
        parser.error('工作目录必须在 Portable 包外且尚未存在')
    os.environ['ECRA_PORTABLE_ROOT'] = str(bundle)
    from ecra.portable import tool_path
    git, compiler = tool_path('git'), tool_path('arm-none-eabi-gcc')
    python = bundle/'runtime/python.exe'
    env = dict(os.environ, PATH='C:/Windows/System32;C:/Windows', PYTHONIOENCODING='utf-8', PYTHONHASHSEED='0',
               GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='NUL')
    for key in ('CC', 'CXX', 'ASM', 'GCC_EXEC_PREFIX', 'COMPILER_PATH', 'LIBRARY_PATH', 'CPATH',
                'C_INCLUDE_PATH', 'CPLUS_INCLUDE_PATH'):
        env.pop(key, None)
    logs = root.with_name(root.name+'-logs')
    logs.mkdir(parents=True, exist_ok=False)
    root.mkdir()
    (root/'.gitignore').write_text('build/\n.ecra*/\n', encoding='utf-8')
    (root/'app.c').write_text('volatile unsigned g;\nstatic unsigned unrelated;\n'
        'void Task(void){g=1;}\nvoid Other(void){unrelated=1;}\n'
        'void TIM4_IRQHandler(void){g++;}\nint main(void){Task();return 0;}\n', encoding='utf-8')
    (root/'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.18)\n'
        'set(CMAKE_SYSTEM_NAME Generic)\nset(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)\n'
        f'set(CMAKE_C_COMPILER "{Path(compiler).as_posix()}")\nproject(portable_target C)\n'
        'add_executable(firmware.elf app.c)\n'
        'target_compile_options(firmware.elf PRIVATE -mcpu=cortex-m7 -mthumb -ffreestanding)\n'
        'target_link_options(firmware.elf PRIVATE -mcpu=cortex-m7 -mthumb -nostdlib -Wl,--entry=main)\n', encoding='utf-8')
    def command(*argv):
        p = subprocess.run([str(x) for x in argv], cwd=root, env=env, capture_output=True,
                           text=True, encoding='utf-8', errors='replace')
        if p.returncode:
            raise RuntimeError(p.stdout+p.stderr)
        return p.stdout.strip()
    command(git, 'init')
    command(git, 'add', '.')
    command(git, '-c', 'user.name=ECRA validation', '-c', 'user.email=ecra@example.invalid', 'commit', '-m', 'base')
    command(git, 'branch', 'base')
    cfg = dict(version=1, project=dict(root=str(root), chip='STM32H743XI', core='Cortex-M7',
                                     native_word_bits=32, nvic_priority_bits=4),
        analysis=dict(compile_database='auto', include_dirs=[], exclude_dirs=[], exclude_files=[],
            auto_system_includes=True, build_closure_only=True, extraction_workers=1,
            cmake=dict(build_dir='build/ecra', generator='Ninja', target='firmware.elf', build=True,
                       args=['-DCMAKE_NINJA_FORCE_RESPONSE_FILE=ON']),
            git_diff=dict(enabled=False, base_ref='base', cache_enabled=True,
                          verify_against_full=True)),
        contexts=[dict(id='main', kind='MAIN', functions=['main']),
                  dict(id='irq', kind='IRQ', functions=['TIM4_IRQHandler'], priority=1)],
        review=dict(enabled=False, prepare_packets=False))
    config = root.with_name(root.name+'-semantics.yaml')
    write_json(config, cfg)
    receipt = root.with_name(root.name+'-acceptance.json')
    result = dict(complete=False, bundle=str(bundle), project=str(root), review_executed=False, runs=[])
    write_json(receipt, result)
    def scan(name, mode):
        argv = [str(python), '-B', str(bundle/'run_ecra.py'), '--project', str(root), '--config', str(config),
                '--scan-mode', mode, '--no-review']
        started = time.monotonic()
        with (logs/(name+'.log')).open('w', encoding='utf-8') as stream:
            p = subprocess.run(argv, cwd=root, env=env, stdout=stream, stderr=subprocess.STDOUT)
        if p.returncode not in (0, 1, 2):
            raise RuntimeError('Portable 扫描失败：'+str(logs/(name+'.log')))
        out = root/'.ecra'
        validity = read_json(out/'result_validity.json')
        facts, report = read_json(out/'facts.json'), read_json(out/'reports/global_static_concurrency.json')
        delta = report.get('git_diff', {})
        record = dict(name=name, seconds=time.monotonic()-started, exit_code=p.returncode,
            valid=validity.get('analysis_valid'), tu_cache=delta.get('tu_cache'),
            baseline_summary_cache=delta.get('baseline_summary_cache'), verification=delta.get('full_verification'))
        if not record['valid'] or read_json(out/'run.json')['review_mode'] != 'disabled_by_cli':
            raise RuntimeError('Portable 结果有效性或禁用复核状态不符合要求')
        if mode == 'diff':
            selected = set(delta['selected_symbol_ids'])
            if selected != {'c:@g'} or (out/'diff_index.html').exists():
                raise RuntimeError('Portable 差异范围或报告文件不符合要求')
            g = next(v for v in facts['variables'] if v['symbol_id'] == 'c:@g')
            functions = {f['function_id']: f['name'] for f in facts['functions']}
            if not any(functions.get(a['function_id']) == 'TIM4_IRQHandler' for a in g['accesses']):
                raise RuntimeError('未修改 IRQ 路径没有保留在完整事实中')
            if delta['full_verification']['state'] != 'PASSED':
                raise RuntimeError('独立全量交叉验证未通过')
        result['runs'].append(record)
        write_json(receipt, result)
    scan('full', 'full')
    p = root/'app.c'
    p.write_bytes(p.read_bytes().replace(b'g=1;', b'g++;'))
    command(git, 'add', 'app.c')
    command(git, '-c', 'user.name=ECRA validation', '-c', 'user.email=ecra@example.invalid', 'commit', '-m', 'change')
    scan('diff-first', 'diff')
    scan('diff-cached', 'diff')
    result['complete'] = True
    write_json(receipt, result)
    print('Portable 目标、响应文件、中文空格路径及完整差异证据验证通过。', flush=True)


if __name__ == '__main__':
    main()
