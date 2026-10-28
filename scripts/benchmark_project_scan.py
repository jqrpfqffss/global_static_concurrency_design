"""对已有真实工程执行无复核扫描，记录耗时、内存及完整语义对照。"""
import argparse
from collections import Counter
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
    parser.add_argument('--reference', type=Path, help='同一源码快照的规范化 summary.json，用于完整语义对照')
    args = parser.parse_args()
    from ecra.config import load_config
    from ecra.common import read_json, write_json, digest
    from ecra.workflow import read_saved_json, file_digest, engine_digest
    from ecra.git_diff import summarize
    import psutil  # 仅测量脚本依赖，分析器和 Portable 不依赖此包。

    project, config = args.project.resolve(), args.config.resolve()
    cfg, _ = load_config(project, config)
    if cfg['review'].get('enabled') or cfg['review'].get('prepare_packets'):
        parser.error('实测配置必须关闭 review.enabled 和 review.prepare_packets')
    evidence = args.evidence.resolve()
    evidence.mkdir(parents=True, exist_ok=False)
    out = project / cfg['analysis'].get('output_dir', '.ecra')
    command = [sys.executable, '-B', str(TOOL/'run_ecra.py'), '--project', str(project),
               '--config', str(config), '--scan-mode', args.scan_mode, '--no-review']
    result = dict(complete=False, command=command, engine_digest=engine_digest(),
                  config_sha256=file_digest(config), scan_mode=args.scan_mode,
                  review_executed=False, memory_sampling_errors=0)
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
    if proc.returncode not in (0, 1, 2):
        raise RuntimeError('扫描失败，日志：' + str(evidence/'console.log'))
    validity = read_json(out/'result_validity.json')
    if not validity.get('analysis_valid') or engine_digest() != result['engine_digest']:
        raise RuntimeError('结果或分析实现无效，不能记录为验收通过')
    post_started = time.monotonic()
    facts = read_saved_json(out/'facts.json', canonical_accesses=True)
    report = read_saved_json(out/'reports/global_static_concurrency.json')
    summary = summarize(facts, report)
    write_json(evidence/'summary.json', summary, indent=None)
    delta = report.get('git_diff', {})
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
