"""Select stratified SAFE audit candidates; never assert audit completion."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path

from preopencode_benchmark_summary import records


def compact(variable, evidence_file='facts.json'):
    keys = ("symbol_id", "root_symbol_id", "array_root_symbol_id", "name", "qualified_name", "kind",
            "definition_file", "definition_line", "type", "linkage", "storage_class", "field_path",
            "static_classification", "safe_reason_code", "safe_evidence", "shared_reason_code", "shared_evidence",
            "screening_reason", "coverage",
            "coverage_reasons", "analysis_coverage", "translation_units", "canonical_path",
            "address_taken", "address_escape", "initialization_proof", "safe_reason_codes")
    result = {k:variable[k] for k in keys if k in variable}
    accesses = variable.get("accesses", [])
    access_keys = ("access_id", "file", "line", "column", "access_kind", "function_id", "function_name",
                   "field_path", "contexts", "context_ids", "context_paths", "physical_contexts", "phase",
                   "alias_resolution", "source_text", "protection", "address_taken", "via_alias", "access_path",
                   "call_chains", "call_graph_slice", "allowed_contexts", "mask_states", "inherited_from_access_id")
    result["access_count"] = len(accesses)
    result["accesses"] = [{k:a[k] for k in access_keys if k in a} for a in accesses]
    result["audit_status"] = "PENDING_INDEPENDENT_SOURCE_REVIEW"
    result['full_evidence_reference'] = dict(file=evidence_file,symbol_id=variable['symbol_id'],
        fields=['variable_evidence_slice','call_graph_slices','functions','calls','control_flow','pointer_constraints'])
    result["audit_questions"] = [
        "Do source references and resolved aliases account for all runtime accesses?",
        "Are main, IRQ, callback and DMA execution entries mapped correctly?",
        "Does any address escape or whole-object operation invalidate the proof?",
        "Does the stated SAFE_PROVEN or SHARED_NO_REVIEW proof hold for this canonical storage object?",
    ]
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", type=Path)
    parser.add_argument("--count",type=int,default=30)
    args = parser.parse_args()
    # Retain only count records per stratum; no giant facts file in memory.
    buckets = defaultdict(list)
    totals = Counter()
    source = args.folder/'facts.json'
    sampled_snapshot = not source.exists()
    if source.exists():
        variables = records(source)
        evidence_file = 'facts.json'
    else:
        sample_file = args.folder/'audit-sample-evidence.json'
        variables = iter(json.loads(sample_file.read_text(encoding='utf-8')))
        evidence_file = sample_file.name
    for variable in variables:
        state = 'SAFE_PROVEN' if variable.get('static_classification') == 'SAFE' else variable.get('static_classification')
        if state not in {'SAFE_PROVEN', 'SHARED_NO_REVIEW'}:
            continue
        key = (state, variable.get("kind", "?"), variable.get("safe_reason_code")
               or variable.get('shared_reason_code') or variable.get("screening_reason"))
        totals[key] += 1
        if len(buckets[key]) < args.count:
            buckets[key].append(compact(variable, evidence_file))
    if sampled_snapshot and (args.folder/'classification-index.json').exists():
        totals.clear()
        for variable in json.loads((args.folder/'classification-index.json').read_text(encoding='utf-8')):
            state = variable.get('static_classification')
            if state in {'SAFE_PROVEN', 'SHARED_NO_REVIEW'}:
                totals[(state, variable.get('kind', '?'), variable.get('safe_reason_code')
                        or variable.get('shared_reason_code'))] += 1
    for state, filename in (('SAFE_PROVEN', 'safe-proven-audit-candidates.json'),
                            ('SHARED_NO_REVIEW', 'shared-no-review-audit-candidates.json')):
        if sampled_snapshot:
            selected = [compact(variable, evidence_file) for variable in
                        json.loads((args.folder/'audit-sample-evidence.json').read_text(encoding='utf-8'))
                        if variable.get('static_classification') == state][:args.count]
        else:
            selected = []
            keys = sorted((key for key in buckets if key[0] == state), key=str)
            while len(selected) < args.count and any(buckets[key] for key in keys):
                for key in keys:
                    if buckets[key] and len(selected) < args.count:
                        selected.append(buckets[key].pop(0))
        result = dict(classification=state, requested=args.count, selected=len(selected),
            total_available=sum(value for key,value in totals.items() if key[0] == state),
            selection=("Seeded random draw per storage-kind/proof stratum in audit-sample-selection.json; no audit verdict inferred"
                       if sampled_snapshot else "Deterministic round robin over storage kind and proof code; no audit verdict inferred"),
            available_strata=[dict(kind=k[1],reason=k[2],count=v)
                              for k,v in sorted(totals.items(),key=str) if k[0] == state], samples=selected)
        output = args.folder/filename
        output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
        print(str(output), "selected", len(selected), "of", result["total_available"])


if __name__ == "__main__":
    main()
