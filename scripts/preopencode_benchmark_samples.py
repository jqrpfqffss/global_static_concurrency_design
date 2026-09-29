"""Select stratified SAFE audit candidates; never assert audit completion."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path

from preopencode_benchmark_summary import records


def compact(variable):
    keys = ("symbol_id", "root_symbol_id", "array_root_symbol_id", "name", "qualified_name", "kind",
            "definition_file", "definition_line", "type", "linkage", "storage_class", "field_path",
            "static_classification", "safe_reason_code", "safe_evidence", "screening_reason", "coverage",
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
    result['full_evidence_reference'] = dict(file='facts.json',symbol_id=variable['symbol_id'],
        fields=['variable_evidence_slice','call_graph_slices','functions','calls','control_flow','pointer_constraints'])
    result["audit_questions"] = [
        "Do source references and resolved aliases account for all runtime accesses?",
        "Are main, IRQ, callback and DMA execution entries mapped correctly?",
        "Does any address escape or whole-object operation invalidate the proof?",
        "Does the stated SAFE proof hold for this canonical storage object?",
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
    for variable in records(args.folder/"facts.json"):
        if variable.get("static_classification") != "SAFE":
            continue
        key = (variable.get("kind", "?"),variable.get("safe_reason_code") or variable.get("screening_reason"))
        totals[key] += 1
        if len(buckets[key]) < args.count:
            buckets[key].append(compact(variable))
    selected = []
    keys = sorted(buckets,key=str)
    while len(selected) < args.count and any(buckets.values()):
        for key in keys:
            if buckets[key] and len(selected) < args.count:
                selected.append(buckets[key].pop(0))
    result = dict(requested=args.count,selected=len(selected),total_safe=sum(totals.values()),
        selection="Deterministic round robin over storage kind and SAFE proof code; no audit verdict inferred",
        available_strata=[dict(kind=k[0],reason=k[1],count=v) for k,v in sorted(totals.items(),key=str)],
        samples=selected)
    output = args.folder/"safe-audit-candidates.json"
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(str(output), "selected", len(selected), "of", result["total_safe"])


if __name__ == "__main__":
    main()
