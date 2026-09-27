"""Run one classifier revision on an already-built firmware closure.

This harness invokes the production prepare/extract/merge/analyze pipeline.
The baseline uses the identical target-only compile database, so measured
changes are classifier changes, not extra off-target source inventory.
"""
import argparse
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
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--reuse-workers", action="store_true")
    parser.add_argument("--classify-raw", help="Debug/reclassify a saved merged extraction without reparsing")
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
    parts = []
    if args.classify_raw:
        facts = json.loads(Path(args.classify_raw).read_text(encoding='utf-8'))
        units = facts['translation_units']
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            jobs = [pool.submit(extract, unit) for unit in units]
            for job in as_completed(jobs):
                unit, part = job.result()
                parts.append(part)
                print(f"Clang {len(parts)}/{len(units)} {unit['parse_status']} {unit['source_file']}", flush=True)
        facts = merge(parts)
        facts["translation_units"] = units
    for unit in units:
        if unit["parse_status"] != "PARSED":
            facts["unknowns"].append(dict(kind="PARSE_FAILED", file=unit["source_file"], diagnostics=unit["diagnostics"]))
    parsed = sum(u["parse_status"] == "PARSED" for u in units)
    coverage = dict(translation_units_total=len(units), translation_units_parsed=parsed,
                    translation_units_failed=len(units)-parsed,
                    parse_coverage_percent=round(100*parsed/max(1,len(units)),2), **compilation)
    write(output / "raw-facts.json", facts)
    print("Classifying merged target evidence", flush=True)
    report = analyze(facts, cfg, coverage, root=root)
    write(output / "facts.json", facts)
    write(output / "report.json", report)
    variables = [v for v in facts["variables"] if v.get("static_classification") not in {"CONTAINER", "OUT_OF_BUILD"}]
    counts = Counter(v.get("static_classification", "UNKNOWN") for v in variables)
    summary = dict(total=len(variables), classifications=dict(counts),
        percentages={k: round(100*counts[k]/max(1,len(variables)),2) for k in ("SAFE","SUSPECT","UNKNOWN")},
        by_kind=dict(Counter(v.get("kind") for v in variables)),
        safe_reasons=dict(Counter(v.get("safe_reason_code",v.get("screening_reason")) for v in variables if v.get("static_classification")=="SAFE")),
        unknown_reasons=dict(Counter(code for v in variables if v.get("static_classification")=="UNKNOWN" for code in v.get("unknown_reason_codes",v.get("screening_blockers",[])))),
        review_queue=len({f["symbol_id"] for f in report["findings"] if f.get("symbol_id")}),
        parse_coverage_percent=coverage["parse_coverage_percent"],translation_units=len(units),
        duration_seconds=round(time.monotonic()-started,2),engine=str(engine),engine_hash=digest([p.read_text(encoding="utf-8") for p in sorted((engine/"ecra").glob("*.py"))]))
    write(output / "summary.json", summary)
    faulthandler.cancel_dump_traceback_later()
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
