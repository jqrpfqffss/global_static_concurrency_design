"""用实际 Portable 工具在中文空格路径验证目标闭包、响应文件及差异模式；关闭复核。"""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True, help='必须不存在的新目录；建议含中文及空格')
    parser.add_argument('--check-working-inputs', action='store_true')
    args = parser.parse_args()
    bundle, root = args.bundle.resolve(), args.work.resolve()
    if root.exists() or root.is_relative_to(bundle):
        parser.error('工作目录必须在 Portable 包外且尚未存在')
    python = bundle/'runtime/python.exe'
    if Path(sys.executable).resolve() != python:
        parser.error('请用被验收包的 runtime/python.exe 启动')
    sys.path.insert(0, str(bundle))
    os.environ['ECRA_PORTABLE_ROOT'] = str(bundle)
    os.environ.pop('ECRA_DATA_ROOT', None)
    from ecra.config import TOOL_ROOT, load_config
    from ecra.common import read_json, write_json
    from ecra.workflow import output_path, file_digest
    from ecra.scan_store import EvidenceProvider
    from ecra.portable import bundle_root, tool_path
    if TOOL_ROOT.resolve() != bundle or bundle_root() != bundle:
        parser.error('导入的 ECRA 与被验收工具根不一致')
    git, compiler = tool_path('git'), tool_path('arm-none-eabi-gcc')
    windows = Path(os.environ['SystemRoot'])
    env = dict(os.environ, PATH=os.pathsep.join(map(str, (windows/'System32', windows))), PYTHONIOENCODING='utf-8', PYTHONHASHSEED='0',
               GIT_CONFIG_GLOBAL='NUL', GIT_TERMINAL_PROMPT='0')
    for key in ('CC', 'CXX', 'ASM', 'GCC_EXEC_PREFIX', 'COMPILER_PATH', 'LIBRARY_PATH', 'CPATH',
                'C_INCLUDE_PATH', 'CPLUS_INCLUDE_PATH'):
        env.pop(key, None)
    logs = root.with_name(root.name+'-logs')
    logs.mkdir(parents=True, exist_ok=False)
    root.mkdir()
    data = bundle/'workspace'
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
    if args.check_working_inputs:
        write_json(root/'compile_commands.json', [dict(directory='.', file='app.c',
            arguments=[compiler, '-mcpu=cortex-m7', '-mthumb', '-ffreestanding', '-c', 'app.c'])])
    command(git, 'add', '.')
    command(git, '-c', 'user.name=ECRA validation', '-c', 'user.email=ecra@example.invalid', 'commit', '-m', 'base')
    command(git, 'branch', 'base')
    cfg = dict(version=1, project=dict(root=str(root), chip='STM32H743XI', core='Cortex-M7',
                                     native_word_bits=32, nvic_priority_bits=4),
        analysis=dict(compile_database='auto', include_dirs=[], exclude_dirs=[], exclude_files=[],
            output=dict(location='tool'),
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
    base = command(git, 'rev-parse', 'HEAD')
    receipt = root.with_name(root.name+'-acceptance.json')
    result = dict(complete=False, bundle=str(bundle), project=str(root), review_executed=False, python=str(python), git=git,
                  git_version=command(git, '--version'), data=str(data), runs=[])
    write_json(receipt, result)
    def scan(name, mode):
        argv = [str(python), '-B', str(bundle/'run_ecra.py'), '--project', str(root), '--config', str(config),
                '--scan-mode', mode, '--no-review']
        existing = set((data/'scans').glob('*'))
        started = time.monotonic()
        with (logs/(name+'.log')).open('w', encoding='utf-8') as stream:
            p = subprocess.run(argv, cwd=root, env=env, stdout=stream, stderr=subprocess.STDOUT)
        if p.returncode not in (0, 1, 2):
            raise RuntimeError('Portable 扫描失败：'+str(logs/(name+'.log')))
        out = output_path(root, load_config(root, config)[0])
        if out in existing or out.parent != data/'scans':
            raise RuntimeError(f'未找到本次正式扫描的新结果：{out}')
        validity = read_json(out/'result_validity.json')
        provider = EvidenceProvider(out/'scan.db')
        provider.validate(deep=True)
        facts, report = provider.load('facts'), provider.load('report')
        delta = report.get('git_diff', {})
        record = dict(name=name, seconds=time.monotonic()-started, exit_code=p.returncode,
            valid=validity.get('analysis_valid'), tu_cache=delta.get('tu_cache'),
            baseline_summary_cache=delta.get('baseline_summary_cache'), verification=delta.get('full_verification'))
        record.update(output=str(out), command=argv, log=str(logs/(name+'.log')))
        if not any(v['name'] == 'unrelated' for v in facts['variables']):
            raise RuntimeError('完整事实缺少对照变量')
        if mode == 'full' and delta:
            raise RuntimeError('全量对照实际执行了差异扫描')
        if not record['valid'] or read_json(out/'run.json')['review_mode'] != 'disabled_by_cli':
            raise RuntimeError('Portable 结果有效性或禁用复核状态不符合要求')
        if mode == 'diff':
            selected = set(delta['selected_symbol_ids'])
            pin = delta['pin']
            record.update(base_sha=pin['base_sha'], head_sha=pin['head_sha'], selected=sorted(selected))
            if (pin['base_sha'] != base or pin['head_sha'] != command(git, 'rev-parse', 'HEAD')
                    or selected != {'c:@g'} or (out/'diff_index.html').exists()):
                raise RuntimeError('Portable 差异范围或报告文件不符合要求')
            g = next(v for v in facts['variables'] if v['symbol_id'] == 'c:@g')
            functions = {f['function_id']: f['name'] for f in facts['functions']}
            record['accesses'] = sorted((functions.get(a['function_id']), a['access_kind']) for a in g['accesses'])
            if not any(name == 'TIM4_IRQHandler' for name, kind in record['accesses']):
                raise RuntimeError('未修改 IRQ 路径没有保留在完整事实中')
            record['classifications'] = {v['name']: v['static_classification'] for v in facts['variables']}
            record['fallback_level'] = delta['fallback_level']
            check = record['verification']
            if (check['state'] != 'PASSED' or check['reextracted_units'] < 1
                    or check['classification_mismatches'] or check['semantic_mismatches']):
                raise RuntimeError('独立全量交叉验证未通过')
            if name in ('diff-first', 'diff-cached') and record['fallback_level'] != 'L0':
                raise RuntimeError('标准双提交用例出现差异范围回退')
        result['runs'].append(record)
        write_json(receipt, result)
    scan('full', 'full')
    p = root/'app.c'
    p.write_bytes(p.read_bytes().replace(b'g=1;', b'g++;'))
    command(git, 'add', 'app.c')
    command(git, '-c', 'user.name=ECRA validation', '-c', 'user.email=ecra@example.invalid', 'commit', '-m', 'change')
    scan('diff-first', 'diff')
    scan('diff-cached', 'diff')
    first, repeated = result['runs'][1:3]
    for field in ('base_sha', 'head_sha', 'selected', 'accesses', 'classifications', 'fallback_level', 'exit_code'):
        if first[field] != repeated[field]:
            raise RuntimeError(f'重复差异结果不一致：{field}')
    if args.check_working_inputs:
        p.write_bytes(p.read_bytes().replace(b'g++;', b'g+=2;', 1))
        command(git, 'add', 'app.c')
        p.write_bytes(p.read_bytes().replace(b'g+=2;', b'g+=3;', 1))
        # Exercise the supported versioned database capture independently of the CMake builds above.
        del cfg['analysis']['cmake']
        cfg['analysis']['compile_database'] = 'compile_commands.json'
        cfg['analysis']['git_diff']['include_uncommitted'] = True
        write_json(config, cfg)
        def original():
            return {str(file.relative_to(root)): file_digest(file) for file in root.rglob('*') if file.is_file()}
        before = original()
        for mode in ('full', 'diff'):
            scan('working-'+mode, mode)
            out = Path(result['runs'][-1]['output'])
            view = read_json(out/'input_closure.json')['frozen_view']
            capture = read_json(Path(view['file']))['capture']
            frozen = Path(capture['source_root'])
            if (file_digest(view['file']) != view['sha256'] or (frozen/'app.c').read_bytes() != p.read_bytes()
                    or command(git, '-C', frozen, 'show', ':app.c') != command(git, 'show', ':app.c')
                    or original() != before):
                raise RuntimeError('固定输入或原仓库保全校验失败')
    result['complete'] = True
    write_json(receipt, result)
    print('Portable 目标、响应文件、中文空格路径及完整差异证据验证通过。', flush=True)


if __name__ == '__main__':
    main()
