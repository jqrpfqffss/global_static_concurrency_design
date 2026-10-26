"""复制已有 ST CDC 实工程，验证真实业务代码差异；始终关闭模型复核。"""
import argparse
from pathlib import Path
import shutil
import sys

from validate_git_diff_stm32 import command, scan

TOOL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL))
from ecra.common import read_json, write_json
from ecra.workflow import engine_digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True,
                        help='已准备的 STM32CubeF4 CDC 工程，例如 validate_stm32_cdc.py 生成的 p00')
    parser.add_argument('--work', type=Path, required=True, help='必须不存在的新副本目录')
    args = parser.parse_args()
    source, root = args.source.resolve(), args.work.resolve()
    if root.exists():
        parser.error('验证副本目录必须不存在，禁止覆盖已有工程')
    required = ['App', 'Application', 'Drivers', 'Middlewares', 'cmake', 'CMakeLists.txt']
    if not all((source/name).exists() for name in required):
        parser.error('源目录不是完整的 ST CDC 构建工程')
    if root.is_relative_to(source):
        parser.error('验证副本不能位于原工程内')
    root.mkdir(parents=True)
    for name in required:
        path = source/name
        if path.is_dir():
            shutil.copytree(path, root/name, ignore=shutil.ignore_patterns('.git', '.ecra*', 'build', '__pycache__'))
        else:
            shutil.copy2(path, root/name)
    (root/'.gitignore').write_text('build/\n.ecra*/\n', encoding='utf-8')
    command(root, 'git', 'init')
    command(root, 'git', 'config', 'user.name', 'ECRA validation')
    command(root, 'git', 'config', 'user.email', 'ecra@example.invalid')
    command(root, 'git', 'add', '.')
    command(root, 'git', 'commit', '-m', 'ST CDC actual application baseline')
    command(root, 'git', 'branch', 'base')
    base_sha = command(root, 'git', 'rev-parse', 'HEAD')
    cfg = read_json(source/'config/semantics.yaml')
    cfg['project']['root'] = str(root)
    cfg['analysis'].pop('compile_database', None)
    cfg['analysis']['cmake'] = dict(build_dir='build/ecra', generator='Ninja',
        toolchain_file='cmake/arm.cmake', build=True, clean_before_configure=False)
    cfg['analysis']['extraction_workers'] = 8
    cfg['analysis']['git_diff'] = dict(enabled=False, target_ref='base', compare_mode='direct')
    cfg['review'].update(enabled=False, prepare_packets=False)
    config = root.parent/(root.name+'-semantics.yaml')
    write_json(config, cfg)
    result = dict(complete=False, source=str(source), project=str(root), base_sha=base_sha,
                  engine_digest=engine_digest(), review_executed=False, runs=[])
    receipt = root.parent/(root.name+'-acceptance.json')
    write_json(receipt, result)

    def execute(name, mode, reference=None):
        record, summary = scan(root, config, name, mode)
        result['runs'].append(record)
        if reference is not None and summary != reference:
            write_json(receipt, result)
            raise RuntimeError('当前完整语义不一致：' + name)
        write_json(receipt, result)
        return summary

    def change(file, old, new, title):
        path = root/file
        text = path.read_text(encoding='utf-8')
        if text.count(old) != 1:
            raise RuntimeError('变更定位不唯一：' + file)
        path.write_text(text.replace(old, new), encoding='utf-8')
        command(root, 'git', 'add', file)
        command(root, 'git', 'commit', '-m', title)

    execute('full-base', 'full')
    change('Application/Src/usbd_cdc_interface.c', 'UserTxBufPtrIn++;', 'UserTxBufPtrIn += 2;',
           'change actual UART receive buffer index update')
    current = execute('diff-first', 'diff')
    report = read_json(root/'.ecra/reports/global_static_concurrency.json')
    if 'c:@UserTxBufPtrIn' not in report['git_diff']['selected_symbol_ids']:
        raise RuntimeError('真实 UART 缓冲区索引变更没有纳入影响集合')
    execute('diff-cached', 'diff', current)
    execute('full-head', 'full', current)
    change('Application/Inc/usbd_cdc_interface.h', 'DMA_CHANNEL_4', 'DMA_CHANNEL_5',
           'change actual UART DMA channel macro')
    execute('diff-header', 'diff')
    change('Application/Src/stm32f4xx_hal_msp.c', 'USARTx_IRQn, 5, 0', 'USARTx_IRQn, 4, 0',
           'change actual UART interrupt priority')
    current = execute('diff-nvic', 'diff')
    execute('full-nvic', 'full', current)
    result.update(complete=True, head_sha=command(root, 'git', 'rev-parse', 'HEAD'),
                  classification_mismatches=0, semantic_mismatches=0,
                  scope='ST STM32CubeF4 CDC/USART/DMA 实应用隔离副本；修改真实业务源码；未烧录目标板')
    write_json(receipt, result)
    print('真实 CDC 工程差异矩阵已完成；未执行模型复核。', flush=True)


if __name__ == '__main__':
    main()
