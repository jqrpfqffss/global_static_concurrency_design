"""Run one classifier revision on an already-built firmware closure.

This harness invokes the production prepare/extract/merge/analyze pipeline.
The baseline uses the identical target-only compile database, so measured
changes are classifier changes, not extra off-target source inventory.
"""
import argparse
import ast
import hashlib
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import faulthandler


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


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
    args = parser.parse_args()
    faulthandler.dump_traceback_later(60, repeat=True)
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
    provenance = dict(mode='FRESH_EXTRACTION',extraction_engine=str(engine),
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
            for job in as_completed(jobs):
                unit, part = job.result()
                parts.append(part)
                print(f"Clang {len(parts)}/{len(units)} {unit['parse_status']} {unit['source_file']}", flush=True)
        facts = merge(parts)
        parts.clear()
        jobs.clear()
        facts["translation_units"] = units
    write(output/'extraction-provenance.json',provenance)
    for unit in units:
        if unit["parse_status"] != "PARSED":
            facts["unknowns"].append(dict(kind="PARSE_FAILED", file=unit["source_file"], diagnostics=unit["diagnostics"]))
    parsed = sum(u["parse_status"] == "PARSED" for u in units)
    coverage = dict(translation_units_total=len(units), translation_units_parsed=parsed,
                    translation_units_failed=len(units)-parsed,
                    parse_coverage_percent=round(100*parsed/max(1,len(units)),2), **compilation)
    write(output / "raw-facts.json", facts)
    if args.extract_only:
        write(output / 'extraction-summary.json', dict(coverage=coverage,
            engine=str(engine),engine_hash=digest([p.read_text(encoding='utf-8') for p in sorted((engine/'ecra').glob('*.py'))]),
            functions=len(facts['functions']),calls=len(facts['calls']),variables=len(facts['variables']),
            accesses=len(facts['accesses']),duration_seconds=round(time.monotonic()-started,2)))
        faulthandler.cancel_dump_traceback_later()
        print('Extraction complete; classification deliberately not run',flush=True)
        return
    print("Classifying merged target evidence", flush=True)
    report = analyze(facts, cfg, coverage, root=root)
    # Small diagnostic index: all storage rows, exact access sites and local
    # blocker reasons, without repeating the complete call graph per row.
    # The full facts remain the authority for independent source audits.
    fields = ('symbol_id', 'qualified_name', 'name', 'kind', 'canonical_path', 'definition_file', 'definition_line',
              'static_classification', 'safe_reason_code', 'unknown_reason_codes', 'coverage', 'root_symbol_id',
              'array_root_symbol_id', 'field_path', 'safe_reason_codes')
    site_fields = ('kind', 'file', 'line', 'offset', 'function_id', 'target_function_id', 'reason',
                   'reason_code', 'relevance', 'access_path', 'access_kind', 'contexts', 'source_text')
    write(output / 'classification-index.json', [dict({k:v[k] for k in fields if k in v},
        accesses=[{k:a[k] for k in site_fields if k in a} for a in v.get('accesses', [])],
        blocking_evidence=[{k:b[k] for k in site_fields if k in b} for b in v.get('blocking_evidence', [])])
        for v in facts['variables']])
    write(output / "facts.json", facts)
    write(output / "report.json", report)
    variables = [v for v in facts["variables"] if v.get("static_classification") in {"SAFE", "SUSPECT", "UNKNOWN"}]
    counts = Counter(v["static_classification"] for v in variables)
    expected = coverage.get('static_classification', {})
    if expected:
        assert expected['total'] == len(variables), 'benchmark classification denominator differs from production accounting'
        assert all(expected.get(state.lower(),0) == counts[state] for state in ('SAFE','SUSPECT','UNKNOWN'))
    roots = {}
    for variable in variables:
        ident = variable.get('array_root_symbol_id') or variable.get('root_symbol_id') or variable['symbol_id']
        ident = ident.split('::element::',1)[0]
        state = variable['static_classification']
        roots[ident] = max(roots.get(ident,'SAFE'),state,key={'SAFE':0,'UNKNOWN':1,'SUSPECT':2}.get)
    summary = dict(total=len(variables), inventory_total=len(facts['variables']), classifications=dict(counts),
        root_storage_total=len(roots),root_classifications=dict(Counter(roots.values())),
        percentages={k: round(100*counts[k]/max(1,len(variables)),2) for k in ("SAFE","SUSPECT","UNKNOWN")},
        by_kind=dict(Counter(v.get("kind") for v in variables)),
        safe_reasons=dict(Counter(v.get("safe_reason_code",v.get("screening_reason")) for v in variables if v.get("static_classification")=="SAFE")),
        unknown_reasons=dict(Counter(code for v in variables if v.get("static_classification")=="UNKNOWN" for code in v.get("unknown_reason_codes",v.get("screening_blockers",[])))),
        review_queue=len({f["symbol_id"] for f in report["findings"] if f.get("symbol_id")}),
        parse_coverage_percent=coverage["parse_coverage_percent"],translation_units=len(units),
        duration_seconds=round(time.monotonic()-started,2),engine=str(engine),extraction_provenance=provenance,
        engine_hash=digest([p.read_text(encoding="utf-8") for p in sorted((engine/"ecra").glob("*.py"))]))
    write(output / "summary.json", summary)
    faulthandler.cancel_dump_traceback_later()
    print(json.dumps({k:v for k,v in summary.items() if k!='extraction_provenance'}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
