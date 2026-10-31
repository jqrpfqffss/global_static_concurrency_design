"""对已有真实工程执行无复核扫描，记录耗时、内存及完整语义对照。"""
import argparse
from collections import Counter
import math
import os
from pathlib import Path
import subprocess
import sys
import time

TOOL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL))


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--scan-mode', choices=('full', 'diff'), required=True)
    parser.add_argument('--legacy-output', action='store_true', help='显式测量旧版产物，供冻结基线/兼容回归；不作为新格式收益')
    parser.add_argument('--reference', type=Path, help='同一源码快照的规范化 summary.json，用于完整语义对照')
    parser.add_argument('--audit-baseline', action='store_true',
                        help='额外独立审计首次差异内建的完整基准；不替代当前版本全量对照')
    parser.add_argument('--audit-saved', action='store_true',
                        help='仅恢复同一输入、引擎和命令的未完成产物审计，不重新执行扫描或改写原 CLI 测量')
    args = parser.parse_args()
    if args.audit_baseline and args.scan_mode != 'diff':
        parser.error('--audit-baseline 仅用于差异扫描')
    from ecra.config import load_config
    from ecra.common import read_json, write_json, digest
    from ecra.workflow import read_saved_json, file_digest, engine_digest, checked_scan
    from ecra.git_diff import summarize
    import psutil  # 仅测量脚本依赖，分析器和 Portable 不依赖此包。

    project, config = args.project.resolve(), args.config.resolve()
    cfg, _ = load_config(project, config)
    if cfg['review'].get('enabled') or cfg['review'].get('prepare_packets'):
        parser.error('实测配置必须关闭 review.enabled 和 review.prepare_packets')
    evidence = args.evidence.resolve()
    if not args.audit_saved:
        evidence.mkdir(parents=True, exist_ok=False)
    from ecra.workflow import output_path
    from ecra.workspace import lock_path
    out = output_path(project, cfg)
    command = [sys.executable, '-B', str(TOOL/'run_ecra.py'), '--project', str(project),
               '--config', str(config), '--scan-mode', args.scan_mode, '--no-review']
    if args.legacy_output:
        command.append('--legacy-output')
    identity = dict(command=command, engine_digest=engine_digest(),
                  config_sha256=file_digest(config), scan_mode=args.scan_mode,
                  review_executed=False, audit_baseline=args.audit_baseline,
                  reference=dict(path=str(args.reference.resolve()), sha256=file_digest(args.reference))
                            if args.reference else None)
    if args.audit_saved:
        result = read_json(evidence/'execution.json')
        if (result.get('complete') is not False or any(result.get(k) != v for k, v in identity.items())
                or result.get('exit_code') not in (0, 1, 2)
                or type(result.get('seconds')) not in (int, float) or not math.isfinite(result['seconds']) or result['seconds'] <= 0
                or type(result.get('peak_tree_rss_bytes')) is not int or result['peak_tree_rss_bytes'] < 0):
            raise RuntimeError('保存测量不属于同一未完成扫描；禁止恢复或改写验收结果')
        if result.get('output'):
            out=Path(result['output'])
        if lock_path(project, cfg['analysis']).exists():
            raise RuntimeError('扫描仍有锁，不能与发布并行恢复审计')
        _, saved_report, state = checked_scan(project, out, cfg, config, with_facts=False)
        del saved_report
        if state.get('scan_mode', 'full') != args.scan_mode:
            raise RuntimeError('保存扫描模式与本轮审计不一致')
        from datetime import datetime, timezone
        result.setdefault('audit_resumptions', []).append(dict(
            started_utc=datetime.now(timezone.utc).isoformat(), snapshot_fingerprint=state['fingerprint'],
            ast_extraction_executed=False, review_executed=False))
        write_json(evidence/'execution.json', result)
        peak = result['peak_tree_rss_bytes']
    else:
        result = dict(identity, complete=False, memory_sampling_errors=0)
        write_json(evidence/'execution.json', result)
        started, peak = time.monotonic(), 0
        with (evidence/'console.log').open('w', encoding='utf-8') as stream:
            proc = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT,
                                    env=dict(os.environ, PYTHONIOENCODING='utf-8'))
            while proc.poll() is None:
                try:
                    parent = psutil.Process(proc.pid)
                    peak = max(peak, sum(p.memory_info().rss for p in [parent, *parent.children(recursive=True)]
                                         if p.is_running()))
                except psutil.NoSuchProcess:
                    pass
                except psutil.Error:
                    result['memory_sampling_errors'] += 1
                time.sleep(.2)
        result.update(seconds=time.monotonic()-started, peak_tree_rss_bytes=peak, exit_code=proc.returncode)
        write_json(evidence/'execution.json', result)
    if result['exit_code'] not in (0, 1, 2):
        raise RuntimeError('扫描失败，日志：' + str(evidence/'console.log'))
    if not args.audit_saved and not args.legacy_output:
        out=output_path(project,cfg)  # resolve the newly published scan, not the pre-run pointer
    result['output']=str(out)
    write_json(evidence/'execution.json',result)
    validity = read_json(out/'result_validity.json')
    if not validity.get('analysis_valid') or engine_digest() != result['engine_digest']:
        raise RuntimeError('结果或分析实现无效，不能记录为验收通过')
    post_started = time.monotonic()
    facts = read_saved_json(out/'facts.json', canonical_accesses=True)
    report = read_saved_json(out/'reports/global_static_concurrency.json')
    summary = summarize(facts, report)
    write_json(evidence/'summary.json', summary, indent=None)
    delta = report.get('git_diff', {})
    baseline_audit = None
    if args.audit_baseline:
        pinned = delta['pin']
        from ecra.workspace import context
        base_out = Path(context(project, cfg['analysis']).git_diff_root)/'artifacts'/('base-' + pinned['base_sha'])
        if not base_out.resolve().is_relative_to((out/'git_diff').resolve()):
            raise RuntimeError('基准审计路径不属于本轮隔离工作树')
        if (file_digest(base_out/'facts.json') != pinned['base_facts_sha256']
                or file_digest(pinned['base_facts_path']) != pinned['base_facts_sha256']
                or file_digest(pinned['base_summary_path']) != pinned['base_summary_sha256']):
            raise RuntimeError('完整基准事实或摘要与本轮引用不一致')
        baseline_audit = dict(output_dir=str(base_out), base_sha=pinned['base_sha'],
            facts_sha256=pinned['base_facts_sha256'], summary_sha256=pinned['base_summary_sha256'],
            engine_digest=result['engine_digest'])
    selected = set(delta.get('selected_symbol_ids', []))
    write_json(evidence/'selection.json', sorted(selected), indent=None)
    result.update(validity=validity, translation_units=len(facts['translation_units']),
                  parse_status_counts=dict(Counter(u.get('parse_status') for u in facts['translation_units'])),
                  functions=len(facts['functions']), inventory_rows=len(facts['variables']),
                  classifications=dict(Counter(v.get('static_classification') for v in facts['variables'])),
                  variable_accountability=report['coverage'].get('variable_accountability'),
                  selected_variables=len(delta.get('selected_symbol_ids', [])), tu_cache=delta.get('tu_cache'),
                  baseline_summary_cache=delta.get('baseline_summary_cache'),
                  fallback_reasons=delta.get('fallback_reasons'), verification=delta.get('full_verification'),
                  static_status=report['analysis_status'], review_candidates=report['review_integrity']['targets'],
                  selected_classifications=dict(Counter(v.get('static_classification') for v in facts['variables'] if v['symbol_id'] in selected)),
                  impact_reason_counts=dict(Counter(reason for item in delta.get('impacts', {}).values() for reason in item['reasons'])),
                  modified_functions=len(delta.get('modified_function_ids', [])),
                  unknown_kinds=dict(Counter(item['kind'] for item in facts.get('unknowns', []))),
                  points_to_stats=facts.get('points_to_stats'), context_points_to_stats=facts.get('context_points_to_stats'),
                  contexts=len(facts.get('contexts', [])), accesses=len(facts.get('accesses', [])), calls=len(facts.get('calls', [])),
                  summary_graphs=len(summary.get('graphs', {})),
                  selection_sha256=file_digest(evidence/'selection.json'),
                  stage_timings=read_json(out/'diagnostics/scan_stages.json'),
                  facts_sha256=file_digest(out/'facts.json'), summary_sha256=file_digest(evidence/'summary.json'))
    # Disabled scans still save PENDING queue records for later resumption.
    # Those are not model executions; check the persisted execution mode.
    if read_json(out/'run.json').get('review_mode') != 'disabled_by_cli':
        raise RuntimeError('本轮扫描没有保存预期的禁用复核执行模式')
    if args.reference:
        reference = read_json(args.reference)
        keys = reference.keys() | summary.keys()
        result['semantic_mismatches'] = sorted(k for k in keys if digest(reference.get(k)) != digest(summary.get(k)))
        old, new = reference['variables'], summary['variables']
        result['classification_mismatches'] = sorted(sid for sid in old.keys() | new.keys()
            if old.get(sid, {}).get('dimensions', {}).get('classification') !=
               new.get(sid, {}).get('dimensions', {}).get('classification'))
        if result['semantic_mismatches']:
            write_json(evidence/'execution.json', result)
            raise RuntimeError('完整语义对照不一致：' + '、'.join(result['semantic_mismatches']))
    # The next matrix scan replaces the published report. Audit this exact
    # snapshot now, after releasing the complete analysis objects.
    del facts, report, delta
    import gc
    import shutil
    gc.collect()
    from scripts.validate_large_report import audit
    if baseline_audit:
        artifact = audit(Path(baseline_audit['output_dir']), node=shutil.which('node'))
        write_json(evidence/'baseline-artifact-audit.json', artifact)
        result['baseline_artifact_audit'] = dict(baseline_audit, passed=artifact['passed'],
                                                checks=artifact['checks'], seconds=artifact['seconds'])
        if not artifact['passed']:
            write_json(evidence/'execution.json', result)
            raise RuntimeError('完整基准产物审计失败，禁止将首次差异记为通过')
    artifact = audit(out, node=shutil.which('node'))
    write_json(evidence/'artifact-audit.json', artifact)
    result['artifact_audit'] = dict(passed=artifact['passed'], checks=artifact['checks'],
                                  seconds=artifact['seconds'])
    if not artifact['passed']:
        write_json(evidence/'execution.json', result)
        raise RuntimeError('本轮产物审计失败，禁止继续矩阵：'+str(evidence/'artifact-audit.json'))
    result.update(complete=True, postprocessing_seconds=time.monotonic()-post_started)
    write_json(evidence/'execution.json', result)
    print(f"已完成：{result['seconds']:.3f} 秒，进程树 RSS 峰值 {peak / 1024**2:.1f} MiB；未执行复核。")


if __name__ == '__main__':
    main()
