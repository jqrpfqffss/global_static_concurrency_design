"""在专用 INAV H743 副本中修改真实驱动，串行比较全量和差异；不运行模型。"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

TOOL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL))
from ecra.common import read_json, write_json
from ecra.config import load_config
from ecra.git_diff import variable_graph
from ecra.workflow import engine_digest, file_digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True, help='专用副本；会保留三处未提交测试修改')
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True, help='工程外、必须不存在的新证据目录')
    parser.add_argument('--ruby-bin', type=Path, required=True)
    args = parser.parse_args()
    root, evidence, config = args.project.resolve(), args.evidence.resolve(), args.config.resolve()
    if evidence.is_relative_to(root) or evidence.exists():
        parser.error('证据目录必须在工程外且尚未存在')
    def git(*argv):
        return subprocess.check_output(['git', *argv], cwd=root, text=True, encoding='utf-8').strip()
    cfg, _ = load_config(root, config)
    if (cfg['review']['enabled'] or cfg['review']['prepare_packets']
            or cfg['analysis']['cmake'].get('target') != 'MATEKH743.elf'
            or not cfg['analysis']['git_diff'].get('include_uncommitted')
            or any(cfg['analysis'].get(k) for k in ('include_dirs', 'exclude_dirs', 'exclude_files', 'exclude'))):
        parser.error('需要关闭复核、选择完整 H743 ELF 目标并启用工作区比较；不允许缩小变量范围')
    base = cfg['analysis']['git_diff']['target_ref']
    if git('status', '--porcelain') or git('rev-parse', base) != git('rev-parse', 'HEAD'):
        parser.error('需要专用副本的干净基准 HEAD；禁止覆盖已有修改')
    evidence.mkdir(parents=True)
    receipt = evidence/'acceptance.json'
    result = dict(complete=False, project=str(root), config=str(config), engine_digest=engine_digest(),
                  config_sha256=file_digest(config), base_sha=git('rev-parse', base),
                  review_executed=False, mutations=[], runs=[], comparisons=[])
    watched = [Path(__file__), TOOL/'scripts/benchmark_project_scan.py', TOOL/'scripts/validate_large_report.py']
    result['validation_scripts'] = {str(path):file_digest(path) for path in watched}
    write_json(receipt, result)
    env = dict(os.environ, PYTHONHASHSEED='0', PYTHONIOENCODING='utf-8',
               PATH=str(args.ruby_bin.resolve())+os.pathsep+os.environ.get('PATH', ''))
    def assert_frozen():
        if (engine_digest()!=result['engine_digest'] or file_digest(config)!=result['config_sha256']
                or git('rev-parse','HEAD')!=result['base_sha'] or git('rev-parse',base)!=result['base_sha']
                or any(file_digest(path)!=sha for path,sha in result['validation_scripts'].items())):
            raise RuntimeError('矩阵运行期间引擎、配置、验证脚本或 Git 基准变化，禁止混用不同输入结果')
    def scan(name, mode, reference=None):
        assert_frozen()
        folder = evidence/name
        command = [sys.executable, '-B', str(TOOL/'scripts/benchmark_project_scan.py'),
            '--project', str(root), '--config', str(config), '--evidence', str(folder), '--scan-mode', mode]
        if reference:
            command.extend(['--reference', str(reference)])
        print('开始真实工程验证：'+name, flush=True)
        proc = subprocess.run(command, cwd=TOOL, env=env)
        assert_frozen()
        if (folder/'execution.json').is_file():
            record = read_json(folder/'execution.json')
            record['name'] = name
            result['runs'].append(record)
        write_json(receipt, result)
        if proc.returncode or not result['runs'][-1].get('complete'):
            raise RuntimeError('验证未完成：'+name+'；保留日志和静态未知项，不能计为通过')
        if mode == 'diff':
            summary = read_json(folder/'summary.json')
            selected = set(read_json(folder/'selection.json'))
            uart_fields = [v for v in summary['variables'].values()
                           if v['symbol_id'] in selected and (v.get('name') or '').endswith('txBufferTail')]
            roots = [{summary['functions'].get(f, {}).get('name')
                      for f in variable_graph(summary, v).get('roots', [])} for v in uart_fields]
            record['known_uart_case'] = dict(selected_tail_fields=len(uart_fields),
                main_and_irq_evidence=any('main' in names and any(n and n.endswith('IRQHandler')
                                                               for n in names) for names in roots))
            if not uart_fields:
                write_json(receipt, result)
                raise RuntimeError('真实 UART 环形缓冲区变量没有进入差异集合')
            if not record['known_uart_case']['main_and_irq_evidence']:
                write_json(receipt, result)
                raise RuntimeError('真实 UART 变量未同时恢复 main 和 IRQ 完整入口证据，不能计为并发场景通过')
            del summary
        if reference:
            result['comparisons'].append(dict(name=name, reference=str(reference),
                semantic_mismatches=record['semantic_mismatches'], classification_mismatches=record['classification_mismatches']))
        write_json(receipt, result)
        return folder/'summary.json'
    def change(file, old, new):
        assert_frozen()
        path = root/file
        data, old_bytes, new_bytes = path.read_bytes(), old.encode('utf-8'), new.encode('utf-8')
        if data.count(old_bytes) != 1:
            raise RuntimeError('测试变更定位不唯一，禁止继续：'+file)
        path.write_bytes(data.replace(old_bytes, new_bytes))
        result['mutations'].append(dict(file=file, old=old, new=new, sha256=file_digest(path)))
        write_json(receipt, result)
    scan('full-base', 'full')
    change('src/main/drivers/serial_uart_stm32h7xx.c',
           's->port.txBufferTail = (s->port.txBufferTail + 1) % s->port.txBufferSize;',
           's->port.txBufferTail = (s->port.txBufferTail + 2) % s->port.txBufferSize;')
    current = scan('diff-first', 'diff')
    scan('diff-cached', 'diff', current)
    scan('full-head', 'full', current)
    change('src/main/drivers/serial_uart.h', '#define UART1_TX_BUFFER_SIZE    256', '#define UART1_TX_BUFFER_SIZE    512')
    current = scan('diff-header', 'diff')
    scan('full-header', 'full', current)
    change('src/main/drivers/serial_uart_stm32h7xx.c',
           'HAL_NVIC_SetPriority(uart->irq, NVIC_PRIO_SERIALUART, 0);',
           'HAL_NVIC_SetPriority(uart->irq, NVIC_PRIO_SERIALUART - 1, 0);')
    current = scan('diff-nvic', 'diff')
    scan('full-nvic', 'full', current)
    # Leave the final user-facing index in difference mode and check hot reuse.
    scan('diff-final', 'diff', current)
    result.update(complete=True, final_head_sha=git('rev-parse', 'HEAD'), final_worktree_diff=git('diff', '--stat'))
    write_json(receipt, result)
    print('真实 H743 差异矩阵完成；业务修改仅用于分析验证，没有烧录目标板。', flush=True)


if __name__ == '__main__':
    main()
