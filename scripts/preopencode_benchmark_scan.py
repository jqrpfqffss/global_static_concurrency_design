"""Run one classifier revision on an already-built firmware closure.

This harness invokes the production prepare/extract/merge/analyze pipeline.
The baseline uses the identical target-only compile database, so measured
changes are classifier changes, not extra off-target source inventory.
"""
import argparse
import ast
import hashlib
from collections import Counter, defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import random
from pathlib import Path
import shutil
import subprocess
import sys
import time
import faulthandler


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def write_json_array(path, rows):
    """Write an audit index one row at a time to bound serialization memory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as stream:
        stream.write('[')
        count = 0
        for number, row in enumerate(rows):
            stream.write(',\n' if number else '\n')
            encoded = json.dumps(row, ensure_ascii=False, indent=2)
            stream.write('\n'.join('  ' + line for line in encoded.splitlines()))
            count += 1
        stream.write('\n]' if count else ']')


def extraction_signature(engine):
    """Include the whole parser pipeline and only merge/linkage from analysis."""
    sources = {name: (engine/'ecra'/(name+'.py')).read_text(encoding='utf-8') for name in
               ('extract','pointer_extract','controlflow','common','config','compilation')}
    for module, name in (('analysis','merge'),('points_to','resolve_linkage')):
        source = (engine/'ecra'/(module+'.py')).read_text(encoding='utf-8')
        node = next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name==name)
        sources[module+'.'+name] = ast.get_source_segment(source,node)
    return hashlib.sha256(json.dumps(sources,sort_keys=True).encode()).hexdigest()


def sha256_file(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def compact_conflict_scenarios(pairs):
    """Keep complete access coverage without serialising the pair product.

    Conflict generation compares concrete access instances, so a variable with
    many reads and writes can legitimately have O(n²) pairs.  The benchmark
    index is an audit aid, not the classifier's authority: group equivalent
    context/access-kind scenarios, retain every participating access id, one
    source witness and the exact number of represented pairs/path products.
    """
    groups = {}
    participant_fields = ('access_id', 'access_kind', 'context_id', 'function_id',
                          'file', 'line', 'canonical_path', 'access_scope')
    for pair in pairs:
        left, right = pair['participant_a'], pair['participant_b']
        relation = pair.get('relation', {})
        key = (left.get('context_id'), right.get('context_id'),
               left.get('access_kind'), right.get('access_kind'),
               relation.get('relation'), pair.get('mhp'),
               pair.get('has_write_conflict'), pair.get('protection_status'))
        row = groups.get(key)
        if row is None:
            row = groups[key] = dict(
                contexts=[left.get('context_id'), right.get('context_id')],
                access_kinds=[left.get('access_kind'), right.get('access_kind')],
                relation=relation, mhp=pair.get('mhp'),
                may_concurrent=pair.get('may_concurrent'),
                has_write_conflict=pair.get('has_write_conflict'),
                protection_status=pair.get('protection_status'),
                pair_count=0, path_combination_count=0,
                participant_a_access_ids=set(), participant_b_access_ids=set(),
                witness=dict(
                    participant_a={k:left[k] for k in participant_fields if k in left},
                    participant_b={k:right[k] for k in participant_fields if k in right}))
        row['pair_count'] += pair.get('pair_count', 1)
        row['path_combination_count'] += pair.get('path_combination_count', 0)
        if pair.get('representation') == 'CONTEXT_ACCESS_PRODUCT':
            row['participant_a_access_ids'].update(
                pair.get('participant_a_read_access_ids', ()) + pair.get('participant_a_write_access_ids', ()))
            row['participant_b_access_ids'].update(
                pair.get('participant_b_read_access_ids', ()) + pair.get('participant_b_write_access_ids', ()))
            row['pair_rule'] = pair['pair_rule']
        else:
            row['participant_a_access_ids'].add(left.get('access_id'))
            row['participant_b_access_ids'].add(right.get('access_id'))
    result = []
    for row in groups.values():
        row['participant_a_access_ids'] = sorted(row['participant_a_access_ids'] - {None})
        row['participant_b_access_ids'] = sorted(row['participant_b_access_ids'] - {None})
        result.append(row)
    return sorted(result, key=lambda row: (
        not row['may_concurrent'], not row['has_write_conflict'],
        tuple(value or '' for value in row['contexts']), tuple(row['access_kinds'])))


def stratified_audit_sample(variables, state, count=60, seed='ecra-source-audit-v1',
                            minimum_per_proof=10):
    """Reproducible draw with a floor for each available proof reason."""
    buckets = defaultdict(deque)
    for variable in sorted(variables, key=lambda row: row['symbol_id']):
        if variable.get('static_classification') != state:
            continue
        reason = (variable.get('safe_reason_code') if state == 'SAFE_PROVEN'
                  else variable.get('shared_reason_code'))
        buckets[(variable.get('kind'), reason)].append(variable)
    keys = sorted(buckets, key=lambda key: (key[0] or '', key[1] or ''))
    rng = random.Random(seed + ':' + state)
    for key in keys:
        rows = list(buckets[key])
        rng.shuffle(rows)
        buckets[key] = deque(rows)
    selected = []
    proof_counts = Counter()
    available = Counter({reason: sum(len(buckets[key]) for key in keys if key[1] == reason)
                         for reason in {key[1] for key in keys}})
    target = max(count, sum(min(minimum_per_proof, total) for total in available.values()))
    for reason in sorted(available, key=lambda value: value or ''):
        reason_keys = [key for key in keys if key[1] == reason]
        floor = min(minimum_per_proof, available[reason])
        while proof_counts[reason] < floor:
            for key in reason_keys:
                if buckets[key] and proof_counts[reason] < floor:
                    selected.append(buckets[key].popleft())
                    proof_counts[reason] += 1
    while len(selected) < target and any(buckets.values()):
        for key in keys:
            if buckets[key] and len(selected) < target:
                selected.append(buckets[key].popleft())
    return selected


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--reuse-workers", action="store_true")
    parser.add_argument("--extract-only", action="store_true", help="Persist raw merged evidence, without classification")
    parser.add_argument("--classify-raw", help="Debug/reclassify a saved merged extraction without reparsing")
    parser.add_argument("--extraction-engine", help="Frozen engine that produced --classify-raw; verify parser compatibility")
    parser.add_argument("--write-full-output", action="store_true",
                        help="Also write full facts/report JSON; large firmware may require many GB")
    parser.add_argument("--traceback-interval", type=int, default=0,
                        help="Opt in to periodic stack dumps during long benchmarks")
    parser.add_argument("--trace-variables", type=int, default=0,
                        help="Print every Nth variable entering evidence construction")
    parser.add_argument("--trace-memory-limit-mb", type=int, default=0,
                        help="Abort traced classification when Windows working set exceeds this limit")
    parser.add_argument("--trace-index-only", action="store_true",
                        help="Stop after reporting evidence-index size")
    args = parser.parse_args()
    if args.traceback_interval > 0:
        faulthandler.dump_traceback_later(args.traceback_interval, repeat=True)
    engine = Path(args.engine).resolve()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(engine))
    from ecra.config import load_config, configured_project_root
    from ecra.compilation import prepare
    from ecra.analysis import merge, analyze
    from ecra.common import digest
    root = configured_project_root(Path(args.config).resolve())
    cfg, _ = load_config(root, Path(args.config).resolve())
    units, compilation = prepare(root, cfg, progress=lambda s: print(s, flush=True), build_firmware=False)
    # Every input DB is materialized from successful compilation plus the actual
    # link graph. Off-target files are not part of either revision's input.
    compilation["excluded_from_build"] = compilation.get("excluded_from_build", compilation.get("unlisted_sources", []))
    compilation["unlisted_sources"] = []
    cfg["analysis"]["build_closure_only"] = True
    env = dict(os.environ, PYTHONPATH=str(engine))

    def extract(unit):
        req = output / "workers" / (unit["tu_id"] + ".request.json")
        res = output / "workers" / (unit["tu_id"] + ".response.json")
        write(req, dict(root=str(root), unit=unit, config=cfg))
        try:
            if not (args.reuse_workers and res.exists()):
                proc = subprocess.run([sys.executable, "-m", "ecra.extract", str(req), str(res)],
                    cwd=engine, env=env, capture_output=True, timeout=600)
                if proc.returncode:
                    raise RuntimeError(proc.stderr.decode(errors="replace")[-4000:])
            part = json.loads(res.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            part = dict(parse_status="FAILED", diagnostics=[dict(severity=4, message=str(exc))])
        unit.update(parse_status=part["parse_status"], diagnostics=part.get("diagnostics", []), includes=part.get("includes", []))
        for variable in part.get("variables", []):
            variable["parse_status"] = part["parse_status"]
        return unit, part

    started = time.monotonic()
    provenance = dict(mode='REUSED_WORKER_EXTRACTION' if args.reuse_workers else 'FRESH_EXTRACTION',
                      extraction_engine=str(engine),
                      extraction_signature=extraction_signature(engine))
    parts = []
    if args.classify_raw:
        raw_path = Path(args.classify_raw).resolve()
        provenance.update(mode='SAVED_EXTRACTION_UNVERIFIED',raw_path=str(raw_path),raw_sha256=sha256_file(raw_path))
        if args.extraction_engine:
            origin = Path(args.extraction_engine).resolve()
            signature = extraction_signature(origin)
            if signature != provenance['extraction_signature']:
                raise ValueError('Saved extraction parser/merge signature differs; rerun extraction with the selected engine')
            provenance.update(mode='SAVED_EXTRACTION_IDENTICAL_PARSER',extraction_engine=str(origin))
            # Check the saved requests against this target/profile, including
            # every compile argument; a different build closure is not a cache hit.
            requests = [json.loads(p.read_text(encoding='utf-8')) for p in (raw_path.parent/'workers').glob('*.request.json')]
            saved = {r['unit']['tu_id']:r for r in requests}
            if len(saved)!=len(units) or any(u['tu_id'] not in saved or
                saved[u['tu_id']]['unit']['arguments']!=u['arguments'] or saved[u['tu_id']]['config']!=cfg for u in units):
                raise ValueError('Saved extraction does not match the current compile closure/configuration')
        facts = json.loads(raw_path.read_text(encoding='utf-8'))
        units = facts['translation_units']
        if args.extraction_engine:
            inputs = {Path(u['source']) for u in units} | {Path(p) for u in units for p in u.get('includes',[])}
            inputs.update(root/p for p in compilation.get('assembly_sources', []))
            if any(not p.exists() or p.stat().st_mtime_ns>raw_path.stat().st_mtime_ns for p in inputs):
                raise ValueError('A source/header changed after the saved extraction; rerun extraction')
            provenance['source_input_sha256'] = {str(p):sha256_file(p) for p in sorted(inputs)}
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            jobs = [pool.submit(extract, unit) for unit in units]
            completed = []
            for job in as_completed(jobs):
                unit, part = job.result()
                completed.append((unit, part))
                print(f"Clang {len(completed)}/{len(units)} {unit['parse_status']} {unit['source_file']}", flush=True)
        parts = [part for unit, part in sorted(completed,
                 key=lambda item: (item[0]['source_file'], item[0]['tu_id']))]
        facts = merge(parts)
        parts.clear()
        jobs.clear()
        facts["translation_units"] = units
    write(output/'extraction-provenance.json',provenance)
    failed_rows = {(issue.get('file'), issue.get('kind')) for issue in facts['unknowns']
                   if issue.get('kind') == 'PARSE_FAILED'}
    for unit in units:
        if unit["parse_status"] != "PARSED":
            key = (unit['source_file'], 'PARSE_FAILED')
            if key not in failed_rows:
                facts["unknowns"].append(dict(kind="PARSE_FAILED", file=unit["source_file"],
                                              diagnostics=unit["diagnostics"]))
                failed_rows.add(key)
    parsed = sum(u["parse_status"] == "PARSED" for u in units)
    coverage = dict(translation_units_total=len(units), translation_units_parsed=parsed,
                    translation_units_failed=len(units)-parsed,
                    parse_coverage_percent=round(100*parsed/max(1,len(units)),2), **compilation)
    if args.classify_raw:
        # A saved extraction is immutable input. Re-serializing it after adding
        # analysis-only PARSE_FAILED markers changes the next replay's evidence.
        destination = (output / 'raw-facts.json').resolve()
        if destination != raw_path:
            shutil.copyfile(raw_path, destination)
    else:
        write(output / "raw-facts.json", facts)
    if args.extract_only:
        write(output / 'extraction-summary.json', dict(coverage=coverage,
            engine=str(engine),engine_hash=digest([p.read_text(encoding='utf-8') for p in sorted((engine/'ecra').glob('*.py'))]),
            functions=len(facts['functions']),calls=len(facts['calls']),variables=len(facts['variables']),
            accesses=len(facts['accesses']),duration_seconds=round(time.monotonic()-started,2)))
        if args.traceback_interval > 0:
            faulthandler.cancel_dump_traceback_later()
        print('Extraction complete; classification deliberately not run',flush=True)
        return
    print("Classifying merged target evidence", flush=True)
    if args.trace_variables > 0:
        from ecra.evidence import EvidenceIndex
        if os.name == 'nt':
            import ctypes
            from ctypes import wintypes
            class ProcessMemoryCounters(ctypes.Structure):
                _fields_ = [('cb', wintypes.DWORD), ('page_faults', wintypes.DWORD),
                    ('peak_working_set', ctypes.c_size_t), ('working_set', ctypes.c_size_t),
                    ('peak_paged_pool', ctypes.c_size_t), ('paged_pool', ctypes.c_size_t),
                    ('peak_nonpaged_pool', ctypes.c_size_t), ('nonpaged_pool', ctypes.c_size_t),
                    ('pagefile', ctypes.c_size_t), ('peak_pagefile', ctypes.c_size_t)]
            ctypes.windll.kernel32.GetCurrentProcess.restype = ctypes.c_void_p
            ctypes.windll.psapi.GetProcessMemoryInfo.argtypes = [
                ctypes.c_void_p, ctypes.POINTER(ProcessMemoryCounters), wintypes.DWORD]
            def working_set_mb():
                counters = ProcessMemoryCounters()
                counters.cb = ctypes.sizeof(counters)
                if not ctypes.windll.psapi.GetProcessMemoryInfo(
                        ctypes.windll.kernel32.GetCurrentProcess(),
                        ctypes.byref(counters), counters.cb):
                    return 0
                return round(counters.working_set / (1024 * 1024))
        else:
            def working_set_mb():
                return 0
        original_build = EvidenceIndex.build
        original_index_init = EvidenceIndex.__init__
        def trace_index_init(index, facts, coverage, cfg, unreachable):
            original_index_init(index, facts, coverage, cfg, unreachable)
            kinds = Counter(issue['kind'] for issues in index.entries.values() for issue in issues)
            print(f"Evidence index entries={sum(map(len, index.entries.values()))} "
                  f"targets={len(index.entries)} kinds={dict(kinds.most_common(8))} "
                  f"memory_mb={working_set_mb()}", flush=True)
            if args.trace_index_only:
                raise SystemExit(0)
        EvidenceIndex.__init__ = trace_index_init
        import ecra.analysis as analysis_module
        original_conflicts = analysis_module.conflict_pairs
        conflicts_processed = 0
        def trace_conflicts(accesses, relations, contexts):
            nonlocal conflicts_processed
            conflicts_processed += 1
            before = working_set_mb()
            result = original_conflicts(accesses, relations, contexts)
            after = working_set_mb()
            if conflicts_processed % args.trace_variables == 0 or after - before >= 100:
                symbol = accesses[0].get('symbol_id') if accesses else '?'
                print(f"Conflicts {conflicts_processed} {symbol} accesses={len(accesses)} "
                      f"pairs={len(result)} memory_mb={before}->{after}", flush=True)
            if args.trace_memory_limit_mb and after > args.trace_memory_limit_mb:
                raise MemoryError(f"Benchmark memory limit reached after conflicts: {after} MB")
            return result
        analysis_module.conflict_pairs = trace_conflicts
        processed = 0
        def trace_build(index, variable, accesses, contexts, protection):
            nonlocal processed
            processed += 1
            before = working_set_mb()
            result = original_build(index, variable, accesses, contexts, protection)
            after = working_set_mb()
            if processed % args.trace_variables == 0 or after - before >= 100:
                print(f"Evidence {processed} {variable['symbol_id']} "
                      f"accesses={len(accesses)} issues={len(index.by_symbol[variable['symbol_id']])} "
                      f"gaps={len(result.critical_gaps)} memory_mb={before}->{after}", flush=True)
            if args.trace_memory_limit_mb and after > args.trace_memory_limit_mb:
                raise MemoryError(f"Benchmark memory limit reached at {variable['symbol_id']}: {after} MB")
            return result
        EvidenceIndex.build = trace_build
    report = analyze(facts, cfg, coverage, root=root)
    write(output / 'failed-tu-preprocessing.json', facts.get('failed_tu_preprocessing', []))
    if args.trace_variables > 0:
        print(f"Analyze complete memory_mb={working_set_mb()}", flush=True)
    from ecra.diagnostics import root_causes
    diagnostic = root_causes(facts['variables'], report['coverage']['review_rates'])
    if args.trace_variables > 0:
        print(f"Root causes complete memory_mb={working_set_mb()}", flush=True)
    write(output / 'root_cause_v2.json', diagnostic)
    # Small diagnostic index: all storage rows, exact access sites and local
    # blocker reasons, without repeating the complete call graph per row.
    # The full facts remain the authority for independent source audits.
    fields = ('symbol_id', 'qualified_name', 'name', 'kind', 'canonical_path', 'definition_file', 'definition_line',
              'static_classification', 'safe_reason_code', 'shared_reason_code', 'shared_evidence',
              'shared_no_review_rejections', 'unknown_reason_codes', 'coverage', 'analysis_coverage',
              'coverage_reasons', 'root_symbol_id', 'array_root_symbol_id', 'field_path', 'safe_reason_codes',
              'size_bytes', 'alignment_bytes', 'declared_alignment_bytes', 'root_alignment_bytes',
              'offset_bits', 'type', 'is_volatile', 'is_atomic', 'is_pointer', 'is_union',
              'is_bitfield_container', 'overlap_groups', 'initialization_proof', 'multi_field_coherence')
    site_fields = ('kind', 'file', 'line', 'offset', 'function_id', 'target_function_id', 'reason',
                   'reason_code', 'relevance', 'access_path', 'access_kind', 'contexts', 'source_text',
                   'access_id', 'access_scope', 'via_alias', 'conditional_ancestor', 'context_exclusions')
    write_json_array(output / 'classification-index.json', (dict({k:v[k] for k in fields if k in v},
        accesses=[{k:a[k] for k in site_fields if k in a} for a in v.get('accesses', [])],
        blocking_evidence=[{k:b[k] for k in site_fields if k in b} for b in v.get('blocking_evidence', [])],
        physical_contexts=v.get('variable_evidence_slice', {}).get('physical_contexts', []),
        conflict_scenarios=compact_conflict_scenarios(v.get('conflict_pairs', [])))
        for v in facts['variables']))
    sample_evidence = [candidate for state in ('SAFE_PROVEN', 'SHARED_NO_REVIEW')
                       for candidate in stratified_audit_sample(facts['variables'], state)]
    write(output / 'audit-sample-evidence.json', sample_evidence)
    write(output / 'audit-sample-selection.json', dict(
        method='seeded random within storage-kind and proof-reason strata, round-robin across strata',
        seed='ecra-source-audit-v1', requested_per_state=60, minimum_per_proof=10,
        selected=[dict(symbol_id=v['symbol_id'], classification=v['static_classification'],
                       kind=v.get('kind'), proof_reason=v.get('safe_reason_code') or v.get('shared_reason_code'))
                  for v in sample_evidence]))
    if args.write_full_output:
        write(output / "facts.json", facts)
        write(output / "report.json", report)
    variables = [v for v in facts["variables"]
                 if v.get("static_classification") in {"SAFE_PROVEN", "SHARED_NO_REVIEW", "SUSPECT", "UNKNOWN"}]
    counts = Counter(v["static_classification"] for v in variables)
    expected = coverage.get('static_classification', {})
    if expected:
        assert expected['total'] == len(variables), 'benchmark classification denominator differs from production accounting'
        assert expected.get('safe_proven',0) == counts['SAFE_PROVEN']
        assert expected.get('shared_no_review',0) == counts['SHARED_NO_REVIEW']
        assert all(expected.get(state.lower(),0) == counts[state] for state in ('SUSPECT','UNKNOWN'))
    roots = {}
    for variable in variables:
        ident = variable.get('array_root_symbol_id') or variable.get('root_symbol_id') or variable['symbol_id']
        ident = ident.split('::element::',1)[0]
        state = variable['static_classification']
        roots[ident] = max(roots.get(ident,'SAFE_PROVEN'),state,
                           key={'SAFE_PROVEN':0,'SHARED_NO_REVIEW':1,'UNKNOWN':2,'SUSPECT':3}.get)
    summary = dict(total=len(variables), inventory_total=len(facts['variables']), classifications=dict(counts),
        root_storage_total=len(roots),root_classifications=dict(Counter(roots.values())),
        percentages={k: round(100*counts[k]/max(1,len(variables)),2)
                     for k in ("SAFE_PROVEN","SHARED_NO_REVIEW","SUSPECT","UNKNOWN")},
        by_kind=dict(Counter(v.get("kind") for v in variables)),
        safe_reasons=dict(Counter(v.get("safe_reason_code",v.get("screening_reason")) for v in variables
                                  if v.get("static_classification")=="SAFE_PROVEN")),
        shared_reasons=dict(Counter(v.get('shared_reason_code') for v in variables
                                    if v.get('static_classification')=='SHARED_NO_REVIEW')),
        unknown_reasons=dict(Counter(code for v in variables if v.get("static_classification")=="UNKNOWN" for code in v.get("unknown_reason_codes",v.get("screening_blockers",[])))),
        review_rates=report['coverage']['review_rates'],
        root_cause_reason_counts=diagnostic['reason_counts'],
        counterfactual_upper_bounds=diagnostic['counterfactual_upper_bounds'],
        review_queue=len({f["symbol_id"] for f in report["findings"] if f.get("symbol_id")}),
        pointer_solver_pruning={key: value for key, value in facts.get('pointer_solver_pruning', {}).items()
                                if key != 'pruned_function_ids'},
        points_to_stats=facts.get('points_to_stats', {}),
        context_points_to_stats=facts.get('context_points_to_stats', {}),
        parse_coverage_percent=coverage["parse_coverage_percent"],translation_units=len(units),
        duration_seconds=round(time.monotonic()-started,2),engine=str(engine),extraction_provenance=provenance,
        full_output_written=args.write_full_output,
        engine_hash=digest([p.read_text(encoding="utf-8") for p in sorted((engine/"ecra").glob("*.py"))]))
    write(output / "summary.json", summary)
    worker_dir = (raw_path.parent if args.classify_raw else output) / 'workers'
    worker_hashes = {}
    for unit in sorted(units, key=lambda item: item['tu_id']):
        response = worker_dir / (unit['tu_id'] + '.response.json')
        if response.is_file():
            worker_hashes[unit['tu_id']] = sha256_file(response)
    write(output / 'input-manifest.json', dict(
        config_sha256=sha256_file(Path(args.config).resolve()),
        compile_database_sha256=sha256_file(Path(compilation['compile_database'])),
        raw_facts_sha256=sha256_file(output / 'raw-facts.json'),
        worker_response_sha256=worker_hashes,
        worker_response_count=len(worker_hashes),
        expected_worker_count=len(units),
        extraction_signature=provenance['extraction_signature'],
        engine_hash=summary['engine_hash'],
        failed_tu_preprocessing_sha256=sha256_file(output / 'failed-tu-preprocessing.json'),
        classification_index_sha256=sha256_file(output / 'classification-index.json'),
        root_cause_sha256=sha256_file(output / 'root_cause_v2.json')))
    if args.traceback_interval > 0:
        faulthandler.cancel_dump_traceback_later()
    print(json.dumps({k:v for k,v in summary.items() if k!='extraction_provenance'}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
