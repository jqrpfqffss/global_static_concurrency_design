"""Frozen original5e622b9 merge; only source line endings are normalized.
Original function SHA256: e5ef68bd270d53bd04304cd4b6e9632aa18c0a162a0235136d1a119e45682db1
"""
from collections import defaultdict
from .common import digest
TABLES = ('variables', 'functions', 'accesses', 'calls', 'unknowns', 'protection_events', 'registrations', 'snapshots', 'pointer_constraints', 'semantic_calls', 'indirect_accesses', 'irq_priority_events', 'control_flow', 'pointer_storage', 'constant_regions', 'nvic_programs', 'nvic_globals', 'nvic_irq_definitions')

def merge(parts):
    from .points_to import resolve_linkage
    parts = resolve_linkage(parts)
    facts = {t: [] for t in TABLES}
    variables, functions = {}, {}
    unique_rows = {t: {} for t in TABLES[2:]}
    for part in parts:
        if part.get('parse_status') == 'FAILED':
            failed_sources = {tu for v in part.get('variables', []) for tu in v.get('translation_units', [])}
            failed_sources.update(f.get('translation_unit') or f.get('file') for f in part.get('functions', []))
            for source in sorted(failed_sources - {None}):
                issue = dict(kind='PARSE_FAILED', file=source, diagnostics=part.get('diagnostics', []))
                unique_rows['unknowns'][digest(issue)] = issue
        for v in part.get("variables", []):
            if part.get('parse_status') == 'FAILED':
                v['parse_status'] = 'FAILED'
            sid = v["symbol_id"]
            if sid not in variables:
                variables[sid] = v
            else:
                old = variables[sid]
                previous_type = old['type']
                compatible_array_declaration = (old.get('is_array') and v.get('is_array')
                    and old.get('array_element_type') == v.get('array_element_type')
                    and (old.get('array_size') is None or v.get('array_size') is None))
                if v.get("parse_status") == "FAILED":
                    old["parse_status"] = "FAILED"
                for field in ("declarations", "definitions", "translation_units"):
                    for item in v[field]:
                        if item not in old[field]:
                            old[field].append(item)
                if not old["definition_file"] and v["definition_file"]:
                    for field, value in v.items():
                        if field not in {'declarations', 'definitions', 'translation_units', 'parse_status'}:
                            old[field] = value
                if previous_type != v["type"] and not compatible_array_declaration:
                    issue = dict(kind="TYPE_VARIANT", symbol_id=sid, types=[previous_type, v["type"]])
                    unique_rows['unknowns'][digest(issue)] = issue
        for f in part.get("functions", []):
            functions[f["function_id"]] = f
        for t in ([part['_table']] if part.get('_table') in TABLES[2:] else
                  () if part.get('_table') else TABLES[2:]):
            for row in part.get(t, []):
                unique_rows[t][digest(row)] = row
    facts["variables"] = sorted(variables.values(), key=lambda x: x["symbol_id"])
    facts["functions"] = sorted(functions.values(), key=lambda x: x["function_id"])
    for t in TABLES[2:]:
        facts[t] = list(unique_rows.pop(t).values())
    regions = defaultdict(list)
    for row in facts['constant_regions']:
        regions[(row['function_id'], row['file'])].append(row)
    facts['constant_pruned_evidence'] = []
    for table in ('accesses', 'calls', 'unknowns', 'protection_events', 'registrations',
                  'pointer_constraints', 'semantic_calls', 'indirect_accesses', 'irq_priority_events'):
        kept = []
        for row in facts[table]:
            owner = row.get('function_id') or row.get('caller_function_id') or row.get('registered_by')
            proof = next((r for r in regions.get((owner, row.get('file')), ())
                          if r['offset'] <= row.get('offset', -1) < r['end_offset']), None)
            if proof is None:
                kept.append(row)
            else:
                facts['constant_pruned_evidence'].append(dict(table=table, evidence=row, proof=proof))
        facts[table] = kept
    return facts
