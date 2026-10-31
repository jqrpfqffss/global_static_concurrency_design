"""Compare frozen pre-refactor and current engines on one real ARM/Git fixture.

Creates a new fixture only; never accepts or edits an existing firmware project.
No OpenCode calls. Keeps source, logs, full facts, timings and migration receipts.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

TOOL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL))
from ecra.common import read_json, write_json, digest
from ecra.workflow import output_path, read_saved_json
from ecra.config import load_config
from ecra.git_diff import summarize


SOURCE = '''typedef unsigned short uint16_t;
struct State { unsigned raw,filtered; }; struct State state;
static volatile uint16_t g_msgSp;
static int file_static;
void __disable_irq(void); void __enable_irq(void);
void INF_SetPointFP(void){g_msgSp++;state.raw++;}
static void Filter(void){static unsigned history;history+=state.raw;state.filtered=history;file_static++;}
void Old(void){INF_SetPointFP();}
void ECAT_IRQHandler(void){Old();}
void TIM4_IRQHandler(void){INF_SetPointFP();}
void ECAT_Task(void){uint16_t snapshot=g_msgSp;g_msgSp=snapshot;Filter();}
void Task(void){__disable_irq();ECAT_Task();__enable_irq();}
'''


def size(path):
    return sum(p.stat().st_size for p in Path(path).rglob('*') if p.is_file()) if Path(path).exists() else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-tool', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    args = parser.parse_args()
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=False)
    root = work/'固件 ECAT SP'
    root.mkdir()
    (root/'a.c').write_text(SOURCE, encoding='utf-8')
    (root/'.gitignore').write_text('build/\n.ecra/\n', encoding='utf-8')
    (root/'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.20)\nproject(firmware C)\n'
        'add_library(firmware STATIC a.c)\ntarget_compile_options(firmware PRIVATE -mcpu=cortex-m7 -mthumb)\n')
    def git(*args):
        return subprocess.check_output(['git', '-C', str(root), '-c', 'user.name=ECRA',
            '-c', 'user.email=ecra@example.invalid', *args], stderr=subprocess.STDOUT).decode('utf-8').strip()
    git('init')
    git('add', '.')
    git('commit', '-m', 'ECAT SP regression baseline')
    git('branch', 'base')
    (root/'a.c').write_text(SOURCE.replace('ECAT_IRQHandler(void){Old();}', 'ECAT_IRQHandler(void){INF_SetPointFP();}'))
    git('add', 'a.c')
    git('commit', '-m', 'ECAT SP call-chain change')
    cfg = dict(version=1, project=dict(root=str(root)), analysis=dict(output_dir='.ecra',
        cmake=dict(build_dir='build/ecra', generator='Ninja', build=True, args=[
            '-DCMAKE_SYSTEM_NAME=Generic', '-DCMAKE_C_COMPILER=arm-none-eabi-gcc',
            '-DCMAKE_TRY_COMPILE_TARGET_TYPE=STATIC_LIBRARY']), git_diff=dict(base_ref='base')),
        contexts=[dict(id='task', kind='TASK', functions=['Task']),
            dict(id='ecat', kind='ISR', functions=['ECAT_IRQHandler']),
            dict(id='tim4', kind='ISR', functions=['TIM4_IRQHandler'])],
        review=dict(enabled=False, prepare_packets=False))
    config = work/'semantics.yaml'
    write_json(config, cfg)
    records = []
    def scan(tool, name, mode):
        begin = time.monotonic()
        log = work/(name+'.log')
        cmd = [sys.executable, str(tool/'run_ecra.py'), '--config', str(config), '--no-review', '--scan-mode', mode]
        with log.open('w', encoding='utf-8') as stream:
            proc = subprocess.run(cmd, stdout=stream, stderr=subprocess.STDOUT,
                                  env=dict(os.environ, PYTHONIOENCODING='utf-8'))
        out = root/'.ecra' if tool == args.baseline_tool.resolve() else output_path(root, load_config(root, config)[0])
        validity = read_json(out/'result_validity.json')
        if proc.returncode not in (0, 1, 2) or not validity.get('analysis_valid'):
            raise RuntimeError(f'Invalid scan {name}: {log}')
        facts = read_saved_json(out/'facts.json', canonical_accesses=True)
        report = read_saved_json(out/'reports/global_static_concurrency.json')
        summary = summarize(facts, report)
        write_json(work/(name+'-summary.json'), summary)
        pin = report.get('git_diff', {}).get('pin', {})
        trees = out/'git_diff' if tool == args.baseline_tool.resolve() else out.parent/'trees'
        if tool == args.baseline_tool.resolve():
            # Include the old baseline's in-worktree CMake tree too. Counting
            # only the original workspace build would understate old diff use.
            build_roots = [root/'build']
            if trees.exists():
                for cache in sorted(trees.rglob('CMakeCache.txt'), key=lambda p: len(p.parts)):
                    if not any(cache.parent.is_relative_to(folder) for folder in build_roots):
                        build_roots.append(cache.parent)
        else:
            build_roots = [out.parent/'builds']
        records.append(dict(name=name, command=cmd, exit_code=proc.returncode, seconds=time.monotonic()-begin,
            results=str(out), variables=len(facts['variables']), findings=len(report['findings']),
            facts_json_bytes=(out/'facts.json').stat().st_size, facts_db_bytes=(out/'facts.db').stat().st_size,
            report_bytes=size(out/'reports')+(out/'index.html').stat().st_size,
            build_bytes=sum(size(folder) for folder in build_roots), build_roots=list(map(str,build_roots)),
            worktrees=len(git('worktree', 'list', '--porcelain').split('worktree '))-1,
            managed_worktrees=sum(p.is_dir() and (p/'.git').is_file() for p in trees.iterdir()) if trees.exists() else 0,
            workspace_logical_bytes=size(out) + size(root/'build') if tool == args.baseline_tool.resolve() else size(out.parent),
            history_logical_bytes=size(out/'snapshots'),
            cache=report.get('git_diff', {}).get('tu_cache'), selected=report.get('git_diff', {}).get('selected_symbol_ids'),
            baseline_summary_cache=report.get('git_diff', {}).get('baseline_summary_cache'),
            workspace_digest=pin.get('workspace_digest'), git_status=git('status', '--porcelain=v1', '-uall')))
        write_json(work/'runs.json', records)
        return summary, facts, report
    before, bf, br = scan(args.baseline_tool.resolve(), 'before-full', 'full')
    before_repeat, _, _ = scan(args.baseline_tool.resolve(), 'before-full-repeat', 'full')
    if before_repeat != before:
        raise RuntimeError('Baseline repeated full scan changed complete semantics')
    for name in ('before-diff-first', 'before-diff-cached'):
        old_diff, _, _ = scan(args.baseline_tool.resolve(), name, 'diff')
        if old_diff != before:
            raise RuntimeError('Baseline diff/full complete semantic mismatch')
    legacy_hashes = {str(p.relative_to(root/'.ecra')): __import__('ecra.workspace', fromlist=['file_hash']).file_hash(p)
                     for p in (root/'.ecra').rglob('*') if p.is_file()}
    after, af, ar = scan(TOOL, 'after-full', 'full')
    after_repeat, _, _ = scan(TOOL, 'after-full-repeat', 'full')
    if after_repeat != after:
        raise RuntimeError('Repeated full scan changed complete semantics')
    if before != after:
        raise RuntimeError('Complete normalized evidence mismatch; inspect before-full-summary.json and after-full-summary.json')
    # Compare complete static table data, omitting only raw path/build metadata.
    ignored = {'root', 'translation_units', 'inventory_policy', 'scan_diagnostics'}
    old_tables = {k: v for k, v in bf.items() if k not in ignored}
    new_tables = {k: v for k, v in af.items() if k not in ignored}
    write_json(work/'full-facts-comparison.json', dict(equal=old_tables == new_tables,
        before_digest=digest(old_tables), after_digest=digest(new_tables), excluded_metadata=sorted(ignored)))
    if old_tables != new_tables:
        raise RuntimeError('Full static facts mismatch beyond permitted path/build metadata')
    for rel, expected in legacy_hashes.items():
        from ecra.workspace import file_hash
        if file_hash(root/'.ecra'/rel) != expected:
            raise RuntimeError('Legacy history changed during migration: '+rel)
    first, facts, report = scan(TOOL, 'after-diff-first', 'diff')
    second, _, cached = scan(TOOL, 'after-diff-cached', 'diff')
    full, _, _ = scan(TOOL, 'after-head-full', 'full')
    if first != second or second != full:
        raise RuntimeError('Diff/cached/full complete semantic summaries differ')
    sid = next(v['symbol_id'] for v in facts['variables'] if v['name'] == 'g_msgSp')
    if sid not in report['git_diff']['selected_symbol_ids']:
        raise RuntimeError('ECAT SP call-chain impact was lost')
    from ecra.review import build_variable_review_packet
    finding = next(f for f in report['findings'] if f.get('symbol_id') == sid)
    packet = build_variable_review_packet(Path(report['git_diff']['pin']['current_source_root']), facts, finding,
        facts_path='facts.json', shared_path='shared.json', report_path='report.json')
    if not any(f['name'] == 'TIM4_IRQHandler' for f in packet['functions']):
        raise RuntimeError('TIM4 evidence lost from ECAT SP review scope')
    write_json(work/'acceptance.json', dict(complete=True, before_after_full_facts_equal=True,
        before_after_summary_equal=True, diff_cached_full_equal=True, legacy_preserved=True,
        ecat_sp=dict(symbol_id=sid, selected=True, tim4_review_evidence=True), runs=records,
        hardware_test=False, model_review_executed=False))
    print(json.dumps(dict(complete=True, evidence=str(work)), ensure_ascii=False))


if __name__ == '__main__':
    main()
