"""Audit the committed serial diff corpus, including independent full scans.

No LLM verdict, flashing, resetting or serial-port operations are performed.
Case expectations are independent of scan output. A blanket diff selection
cannot satisfy the isolated-variable control or replace concrete risk evidence.
"""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

TOOL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL))
from ecra.common import read_json, write_json
from ecra.git_diff import summarize
from ecra.workflow import engine_digest, file_digest, read_saved_json
from scripts.prepare_serial_diff import FIXTURE, git


def audit_cases(facts, report, baseline, cases):
    delta = report['git_diff']
    selected = set(delta['selected_symbol_ids'])
    findings = {f['symbol_id']: f for f in report['findings']}
    results = []
    for case in cases:
        errors, rows = [], []
        for name in case['variables']:
            new = [v for v in facts['variables'] if v['qualified_name'] == name]
            old = [v for v in baseline['variables'] if v['qualified_name'] == name]
            if case.get('deleted'):
                if new or not old or not any(v['name'] == name for v in delta['deleted_variables']):
                    errors.append(name + ': deleted storage was not accounted for')
                continue
            if case.get('active_instances') is not None:
                count = sum(bool(v.get('contexts')) for v in new)
                expected = case['active_instances']
            else:
                count, expected = len(new), case.get('instances', 1)
            if count != expected:
                errors.append(f'{name}: expected {expected} instances, got {count}')
            if case.get('base') and (not old or any(v['static_classification'] != case['base'] for v in old)):
                errors.append(name + ': incorrect baseline classification')
            if case.get('absent_base') and old:
                errors.append(name + ': unexpectedly present in baseline')
            for v in new:
                sid, classification = v['symbol_id'], v['static_classification']
                accesses = v.get('accesses', [])
                paths = [p for a in accesses for routes in a.get('all_call_chains', {}).values() for p in routes]
                longest = max(map(len, paths), default=0)
                alias = any(a.get('via_alias') == 'interprocedural points-to' for a in accesses)
                hints = sorted({h['kind'] for h in v.get('concurrency_hints', [])})
                impact = delta['impacts'].get(sid, {})
                row = dict(name=name, symbol_id=sid, classification=classification,
                           contexts=v.get('contexts'), selected=sid in selected,
                           alias=alias, longest_chain=longest, hints=hints,
                           reasons=impact.get('reasons', []), conflict_pairs=len(v.get('conflict_pairs', [])))
                rows.append(row)
                if classification != case['head']:
                    errors.append(f'{name}: expected {case["head"]}, got {classification}')
                if case['id'].startswith(('D', 'H')) and sid not in selected:
                    errors.append(name + ': missing from diff selection')
                if classification == 'SUSPECT':
                    if not v.get('conflict_pairs') or sid not in findings or len(v.get('contexts', [])) < 2:
                        errors.append(name + ': concrete multi-context conflict evidence missing')
                    if not set(row['reasons']) - {'CANNOT_EXCLUDE_IMPACT', 'BUILD_SEMANTICS_CHANGED', 'SEMANTIC_IMPACT'}:
                        errors.append(name + ': blanket fallback cannot replace changed evidence')
                if classification == 'SAFE_PROVEN' and sid in findings:
                    errors.append(name + ': safe control unexpectedly queued as a finding')
                if case.get('alias') and not alias:
                    errors.append(name + ': alias access evidence missing')
                if case.get('hint') and case['hint'] not in hints:
                    errors.append(name + ': cross-function stale-writeback evidence missing')
                if case.get('access_kind') and not any(a['access_kind'] == case['access_kind'] for a in accesses):
                    errors.append(name + ': changed access kind missing')
                if case.get('min_chain', 0) > longest:
                    errors.append(name + ': deep call witness missing')
                if case.get('unchanged') and sid in selected:
                    errors.append(name + ': disconnected unchanged private storage was selected')
                if case.get('instances', case.get('active_instances', 1)) > 1 and len(v.get('contexts', [])) > 1:
                    errors.append(name + ': independent static instances were conflated')
        results.append(dict(id=case['id'], name=case['name'], passed=not errors, errors=errors, variables=rows))
    return dict(passed=all(row['passed'] for row in results), cases=results,
                total=len(results), passed_cases=sum(row['passed'] for row in results))


def read_and_audit(root, out):
    facts = read_saved_json(out/'facts.json', canonical_accesses=True)
    report = read_saved_json(out/'reports/global_static_concurrency.json')
    pin = report['git_diff']['pin']
    if (file_digest(pin['base_facts_path']) != pin['base_facts_sha256']
            or file_digest(pin['base_summary_path']) != pin['base_summary_sha256']):
        raise RuntimeError('Pinned baseline evidence integrity check failed')
    baseline = read_saved_json(pin['base_facts_path'], canonical_accesses=True)
    cases = read_json(FIXTURE/'expectations.json')['cases']
    result = audit_cases(facts, report, baseline, cases)
    selected = set(report['git_diff']['selected_symbol_ids'])
    unrelated = [v['qualified_name'] for v in facts['variables'] if v['symbol_id'] in selected
                 and 'ecra_diff_' not in (v.get('definition_file') or '')]
    result['focus'] = dict(passed=not unrelated, unrelated_selected=unrelated,
                           potential_impact=len(report['git_diff'].get('conservative_symbol_ids', [])))
    result['passed'] = result['passed'] and result['focus']['passed']
    result.update(inventory=sum('static_classification' in v for v in facts['variables']), selected=len(report['git_diff']['selected_symbol_ids']),
                  classifications=dict(Counter(v['static_classification'] for v in facts['variables'] if 'static_classification' in v)),
                  fallback=report['git_diff']['fallback_reasons'],
                  baseline_sha=pin['base_sha'], current_sha=pin['head_sha'],
                  cache=report['git_diff']['tu_cache'])
    if git(root, 'rev-parse', 'HEAD') != pin['head_sha']:
        raise RuntimeError('Firmware HEAD differs from audited report')
    return result, facts, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--config', type=Path, default=TOOL/'config/semantics.yaml')
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--audit-existing', action='store_true', help='Audit existing diff without rerunning; never counts as a full matrix')
    args = parser.parse_args()
    root, evidence, config = args.project.resolve(), args.evidence.resolve(), args.config.resolve()
    from ecra.config import load_config
    cfg, _ = load_config(root, config)
    out = root/cfg['analysis']['output_dir']
    evidence.mkdir(parents=True, exist_ok=False)
    if args.audit_existing:
        result, _, _ = read_and_audit(root, out)
        write_json(evidence/'cases.json', result)
        print(json.dumps(dict(passed=result['passed'], passed_cases=result['passed_cases'], total=result['total']), ensure_ascii=False))
        return 0 if result['passed'] else 1
    if git(root, 'status', '--porcelain') or cfg['review']['enabled']:
        raise ValueError('Requires clean committed firmware and disabled external review')
    identity = dict(engine_digest=engine_digest(), config_sha256=file_digest(config),
                    head=git(root, 'rev-parse', 'HEAD'),
                    base=git(root, 'rev-parse', cfg['analysis']['git_diff']['base_ref']),
                    scripts={str(p): file_digest(p) for p in (Path(__file__), FIXTURE/'expectations.json')})
    receipt = dict(identity, complete=False, review_executed=False, hardware_executed=False, runs=[])
    write_json(evidence/'acceptance.json', receipt)

    def assert_frozen():
        if (identity['engine_digest'] != engine_digest() or identity['config_sha256'] != file_digest(config)
                or identity['head'] != git(root, 'rev-parse', 'HEAD')
                or identity['base'] != git(root, 'rev-parse', cfg['analysis']['git_diff']['base_ref'])
                or any(file_digest(p) != sha for p, sha in identity['scripts'].items())):
            raise RuntimeError('Inputs or engine changed during validation')

    summaries = {}
    for name, mode in [('diff-first', 'diff'), ('full-independent', 'full'), ('diff-cached', 'diff')]:
        assert_frozen()
        folder = evidence/name
        folder.mkdir()
        start = time.monotonic()
        print('Running ' + name, flush=True)
        with (folder/'console.log').open('w', encoding='utf-8') as stream:
            proc = subprocess.run([sys.executable, '-B', str(TOOL/'run_ecra.py'), '--project', str(root),
                '--config', str(config), '--scan-mode', mode, '--no-review'], cwd=TOOL,
                env=dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONHASHSEED='0'), stdout=stream, stderr=subprocess.STDOUT)
        assert_frozen()
        validity = read_json(out/'result_validity.json')
        if proc.returncode not in (0, 1, 2) or not validity.get('analysis_valid'):
            raise RuntimeError('Invalid scan: ' + str(folder/'console.log'))
        facts = read_saved_json(out/'facts.json', canonical_accesses=True)
        report = read_saved_json(out/'reports/global_static_concurrency.json')
        summaries[name] = summarize(facts, report)
        write_json(folder/'summary.json', summaries[name], indent=None)
        record = dict(name=name, exit_code=proc.returncode, seconds=time.monotonic()-start,
                      validity=validity, tus=len(facts['translation_units']),
                      parse_statuses=dict(Counter(u['parse_status'] for u in facts['translation_units'])),
                      classifications=dict(Counter(v['static_classification'] for v in facts['variables'] if 'static_classification' in v)))
        if mode == 'diff':
            result, _, _ = read_and_audit(root, out)
            write_json(folder/'cases.json', result)
            record.update(case_audit_passed=result['passed'], passed_cases=result['passed_cases'],
                          cache=result['cache'], fallback=result['fallback'], selected=result['selected'])
            if not result['passed']:
                receipt['runs'].append(record)
                write_json(evidence/'acceptance.json', receipt)
                raise RuntimeError('Case audit failed: ' + str(folder/'cases.json'))
        # Resolve shared storage before archiving, so the evidence directory
        # remains readable after a later scan replaces the live output.
        write_json(folder/'facts.json', facts, indent=None)
        write_json(folder/'reports/global_static_concurrency.json', report, indent=None)
        for source in ('result_validity.json', 'run.json', 'diagnostics/scan_stages.json'):
            destination = folder/source
            destination.parent.mkdir(exist_ok=True, parents=True)
            shutil.copyfile(out/source, destination)
        receipt['runs'].append(record)
        write_json(evidence/'acceptance.json', receipt)
    receipt['full_vs_diff_equal'] = summaries['full-independent'] == summaries['diff-first'] == summaries['diff-cached']
    receipt['complete'] = receipt['full_vs_diff_equal']
    write_json(evidence/'acceptance.json', receipt)
    if not receipt['complete']:
        raise RuntimeError('Independent full and diff facts differ')
    print('All cases and independent full/diff comparisons passed', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
