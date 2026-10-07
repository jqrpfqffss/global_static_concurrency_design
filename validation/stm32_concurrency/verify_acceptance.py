"""Independent, fail-closed comparison of frozen expectations and real reports.

No production module imports this file or its ground truth. A matching warning
alone is insufficient: identity, access mode, execution root and every call edge
are checked, per variable and build variant.
"""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def read(path, default=None):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {} if default is None else default


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def hashes_valid(base, hashes):
    return bool(hashes) and all((base/p).is_file() and sha(base/p)==h for p,h in hashes.items())


def identify(expected, facts):
    candidates = [v for v in facts.get('variables', []) if v['name'] == expected['name']
                  and v['definition_file'] == expected['file'] and v['kind'] == expected['kind']]
    if expected.get('function'):
        candidates = [v for v in candidates if v['qualified_name'] == expected['function'] + '::' + expected['name']]
        candidates = sorted(candidates, key=lambda v: (v['definition_line'], v['symbol_id']))
        candidates = candidates[expected['ordinal']:expected['ordinal']+1]
    if expected.get('translation_unit'):
        candidates = [v for v in candidates if expected['translation_unit'] in v['translation_units']]
    return candidates[0] if len(candidates) == 1 else None


def chain_matches(expected, variable, facts):
    functions = {f['function_id']: f for f in facts['functions']}
    edges = {(c['caller_function_id'], c['callee_function_id']) for c in facts['calls']
             if c['call_kind'] != 'CONFIGURED'}
    roots = {b['function_id'] for b in facts.get('context_bindings', [])
             if b['context_id'] == expected['context'] and b['call_depth'] == 0}
    paths = [[f] for f in roots if functions[f]['name'] == expected['functions'][0]]
    for name in expected['functions'][1:]:
        paths = [p + [b] for p in paths for a, b in edges
                 if a == p[-1] and functions.get(b, {}).get('name') == name]
    for access in variable.get('accesses', []):
        if access['access_kind'] not in expected['modes'] or expected['context'] not in access.get('contexts', []):
            continue
        if any(p[-1] == access['function_id'] for p in paths):
            return dict(access_id=access['access_id'], kind=access['access_kind'], file=access['file'],
                        line=access['line'], context=expected['context'], chain=next(p for p in paths if p[-1] == access['function_id']))
    return None


def compare(result_base=None):
    truth = read(ROOT / 'ground_truth.json')
    facts = {v: read((result_base or ROOT / 'results') / v / 'facts.json') for v in truth['variants']}
    reports = {v: read((result_base or ROOT / 'results') / v / 'reports/global_static_concurrency.json') for v in truth['variants']}
    multicore_facts = read((result_base or ROOT / 'results') / 'multicore/facts.json')
    multicore_report = read((result_base or ROOT / 'results') / 'multicore/reports/global_static_concurrency.json')
    missing_variables, matched, identities = [], [], {}
    for expected in truth['variables']:
        for variant in expected['variants']:
            identity = identify(expected, facts[variant])
            key = variant + ':' + expected['id']
            if identity:
                identities[key] = identity
                matched.append(key)
            else:
                missing_variables.append(key)
    # Different source/TU/block declarations must never match the same identity.
    collisions = []
    seen = {}
    for key, obj in identities.items():
        variant = key.split(':', 1)[0]
        identity = (variant, obj['symbol_id'])
        if identity in seen:
            collisions.append([seen[identity], key])
        seen[identity] = key
    cases, missing_cases = [], []
    for case in truth['cases']:
        evidence, deficits, review_results = [], [], []
        for vid in case['variables']:
            for chain in case.get('variable_chains', {}).get(vid, case['expected_chains']):
                candidates = []
                for variant in case['variants']:
                    obj = identities.get(variant + ':' + vid)
                    if obj:
                        hit = chain_matches(chain, obj, facts[variant])
                        if hit:
                            candidates.append(dict(hit, variant=variant, symbol_id=obj['symbol_id']))
                if not candidates:
                    deficits.append(dict(variable=vid, missing_chain=chain))
                evidence.extend(candidates)
            # Require each risky object to have its scenario-specific rule.
            found = []
            for variant in case['variants']:
                obj = identities.get(variant + ':' + vid)
                if obj:
                    found += [(variant, f) for f in reports[variant].get('findings', []) if f.get('symbol_id') == obj['symbol_id']]
            if len(case['variants']) > 1:
                merged_findings = []
                original_ids = {(v, identities[v + ':' + vid]['symbol_id']) for v in case['variants'] if v + ':' + vid in identities}
                for merged in multicore_facts.get('variables', []):
                    core_ids = {(x['variant'], x['symbol_id']) for x in merged.get('core_instances', [])}
                    if original_ids and original_ids <= core_ids:
                        merged_findings += [('multicore', f) for f in multicore_report.get('findings', []) if f.get('symbol_id') == merged['symbol_id']]
                found = merged_findings
            if not case['safe'] and not any(set(case['required_rules']) <= set(f['rules']) for _, f in found):
                deficits.append(dict(variable=vid, missing_rules=case['required_rules']))
            review_results += [dict(variant=v, finding_id=f['finding_id'], state=f.get('review_state'), status=f['status'], rules=f['rules']) for v, f in found]
        row = dict(id=case['id'], safe=case['safe'], passed=not deficits, deficits=deficits,
                   evidence=evidence, reviews=review_results)
        cases.append(row)
        if deficits and not case['safe']:
            missing_cases.append(row)
    build_record = read(ROOT / 'build_evidence.json')
    builds = build_record.get('builds', [])
    build_passed = len(builds) == len(truth['variants']) and hashes_valid(ROOT,build_record.get('source_hashes',{}))
    firmware = []
    for build in builds:
        elf = ROOT / build.get('elf', '__missing__')
        raw = elf.read_bytes() if elf.is_file() else b''
        okay = bool(build.get('passed') and len(raw) > 20 and raw[:4] == b'\x7fELF'
                    and raw[18:20] == b'\x28\x00' and sha(elf) == build.get('sha256'))
        build_passed &= okay
        if okay:
            firmware.append(build['elf'])
    unresolved = [c['id'] for c in cases if not c['reviews'] or any(r['state'] != 'DONE' or
                   r['status'] not in ({'REVIEWED_SAFE','FALSE_POSITIVE'} if c['safe'] else {'CONFIRMED','LIKELY'}) for r in c['reviews'])]
    false_confirmations = [c['id'] for c in cases if c['safe'] and any(r['status'] in {'CONFIRMED', 'LIKELY'} for r in c['reviews'])]
    reg = read(ROOT / 'regression.json')
    regression = bool(reg.get('passed') and reg.get('exit_code') == 0 and
        hashes_valid(ROOT.parents[1],reg.get('input_hashes',{})) and
        (ROOT/reg.get('log','__missing__')).is_file() and sha(ROOT/reg['log'])==reg.get('log_sha256'))
    host = read(ROOT / 'host_interleavings.json')
    host_cases = {c['id']:c for c in host.get('cases',[])}
    harness = bool(host.get('passed') and hashes_valid(ROOT,host.get('source_hashes',{})) and
        host.get('model_sha256')==sha(ROOT/'host_interleavings.py') and
        set(host_cases)=={c['id'] for c in truth['cases']} and
        all(c.get('schedules',0)>0 and ((c.get('violating_schedules')==0) if c['safe'] else
            (c.get('violating_schedules',0)>0 and bool(c.get('witness',{}).get('trace')))) for c in host_cases.values()))
    negative = read(ROOT / 'negative_tests.json')
    negatives_ok = all(negative.get(n['id'], {}).get('passed', False) for n in truth['negative_tests'])
    vendor_ok = read(ROOT / 'vendor_inventory_comparison.json').get('passed', False)
    truth_ok = sha(ROOT / 'ground_truth.json') == (ROOT / 'ground_truth.sha256').read_text().strip()
    coverage_ok = all(facts[v] and reports[v].get('coverage', {}).get('translation_units_failed') == 0
                      and not reports[v].get('coverage', {}).get('unlisted_sources') for v in truth['variants'])
    scan_inputs_current = all(hashes_valid(ROOT,read(ROOT/'results'/v/'input_manifest.json')) for v in truth['variants'])
    receipts = {(r['variant'],r['finding_id']):r for r in read(ROOT/'opencode_matrix_reviews.json',[])}
    review_evidence_errors=[]
    for case in cases:
        for result in case['reviews']:
            key=(result['variant'],result['finding_id'])
            receipt=receipts.get(key,{})
            raw_files=list((ROOT/receipt.get('folder','__missing__')/'review').glob('*.attempt*.jsonl'))
            if receipt.get('state')!='DONE' or receipt.get('status')!=result['status'] or not raw_files:
                review_evidence_errors.append(dict(case=case['id'],variant=key[0],finding_id=key[1],reason='Missing matching real review receipt/log'))
                continue
            for raw in raw_files:
                for line in raw.read_text(encoding='utf-8').splitlines():
                    try: event=json.loads(line)
                    except ValueError: continue
                    part=event.get('part',{}); state=part.get('state',{})
                    if event.get('type')=='tool_use' and state.get('status')=='completed':
                        target=str(state.get('input',{}).get('filePath','')).lower()
                        if part.get('tool')=='grep' or 'ground_truth' in target or 'ground-truth' in target or 'acceptance.json' in target:
                            review_evidence_errors.append(dict(case=case['id'],reason='Reviewer accessed independent oracle or unrestricted grep',log=str(raw)))
    # Independent source review can dispute a matrix assumption even when a
    # provider emits LIKELY. Never turn that label into proof of an actual run.
    disputes = [d for d in read(ROOT/'review_disputes.json', []) if d.get('state') != 'RESOLVED']
    unresolved = sorted(set(unresolved) | {d['case'] for d in disputes})
    safe_ok = all(c['passed'] for c in cases if c['safe']) and not false_confirmations
    passed = all([not missing_variables, not collisions, not missing_cases, not unresolved, safe_ok,
                  build_passed, regression, harness, negatives_ok, vendor_ok, truth_ok, coverage_ok, scan_inputs_current, not review_evidence_errors])
    return dict(status='PASS' if passed else 'FAIL', expected_variables=len(matched)+len(missing_variables),
                matched_variables=len(matched), expected_declarations=len(truth['variables']),
                expected_risk_cases=sum(not c['safe'] for c in cases),
                matched_risk_cases=sum(not c['safe'] and c['passed'] for c in cases),
                missing_variables=missing_variables, identity_collisions=collisions,
                missing_risk_cases=missing_cases, unresolved_reviews=unresolved,
                build_passed=build_passed, firmware_artifacts=firmware, regression_passed=regression,
                host_interleavings_passed=harness, negative_tests_passed=negatives_ok,
                vendor_inventory_passed=vendor_ok, truth_hash_valid=truth_ok, coverage_passed=bool(coverage_ok),
                scan_inputs_current=scan_inputs_current,
                safe_control_false_confirmations=false_confirmations,
                review_evidence_errors=review_evidence_errors, manual_review_disputes=disputes,
                safe_control_candidate_count=sum(c['safe'] and any(r['rules']!=['INVENTORY-AUDIT'] for r in c['reviews']) for c in cases), cases=cases)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='acceptance.json')
    args = parser.parse_args()
    result = compare()
    (ROOT / args.output).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k not in {'cases', 'missing_risk_cases', 'missing_variables'}}, ensure_ascii=False))
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
