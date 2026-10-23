"""Controlled replay of real complete TU facts, never a full-scan acceptance.

Keeps the CLI's real merge/analysis preparation and Clang input verification.
Extraction alone is replaced by immutable, previously captured TU responses.
No successful safety report is published. psutil is needed only by the monitor.
"""
import argparse
import gc
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
from collections import Counter
sys.path.insert(0, str(Path(__file__).resolve().parent))
from commit_reserve import CommitReserve, python_reserve


def solver_runtime_sizes(solver):
    """Bounded-depth allocation census, without copying the IR or runtime graph.

    References shared by fields can be counted repeatedly. These are explanatory
    container sizes, not an alternative to measured process Private Bytes.
    """
    result = {}
    for name in ('points', 'unknown_points', 'slots_by_shape', 'descendant_slots',
                 'readers', 'load_cache', 'load_dependencies', 'offset_images',
                 'offset_prefixes', 'location_images', 'update_images',
                 'escape_closures', 'pending', 'enqueued'):
        value = getattr(solver, name)
        row = dict(type=type(value).__name__, count=len(value), shallow_bytes=sys.getsizeof(value))
        if isinstance(value, dict):
            row['key_reference_bytes'] = sum(sys.getsizeof(k) for k in value)
            row['value_reference_bytes'] = sum(sys.getsizeof(v) for v in value.values())
            row['nested_container_members'] = sum(len(v) for v in value.values()
                if isinstance(v, (set, tuple, list, dict)))
            nested_bytes = bitmap_bytes = bitmap_references = 0
            for item in value.values():
                members = item if isinstance(item, (tuple, list)) else (item,)
                for member in members:
                    if isinstance(member, (set, dict, tuple, list)):
                        nested_bytes += sys.getsizeof(member)
                    bits = getattr(member, 'bits', member)
                    if hasattr(bits, 'referenced_storage_bytes'):
                        bitmap_references += 1
                        bitmap_bytes += bits.referenced_storage_bytes()
            row.update(nested_container_reference_bytes=nested_bytes,
                       bitmap_references=bitmap_references, bitmap_reference_bytes=bitmap_bytes)
        result[name] = row
    return result


def dump(path, data):
    with path.open('w', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)


def frame_sizes(exc):
    """Shallow allocation evidence; referenced bitmap bytes may include aliases."""
    result, solver_fields = [], {}
    tb = exc.__traceback__
    while tb:
        frame = tb.tb_frame
        row = dict(file=frame.f_code.co_filename, function=frame.f_code.co_name, line=tb.tb_lineno, locals={})
        for name, value in frame.f_locals.items():
            if isinstance(value, (dict, list, set, tuple, int, str)):
                row['locals'][name] = dict(type=type(value).__name__, shallow_bytes=sys.getsizeof(value))
                if not isinstance(value, int):
                    row['locals'][name]['length'] = len(value)
            elif name == 'self' and hasattr(value, '__dict__'):
                if id(value) in solver_fields:
                    row['locals'][name] = solver_fields[id(value)]
                    continue
                fields = {}
                for key, item in vars(value).items():
                    field = dict(type=type(item).__name__, shallow_bytes=sys.getsizeof(item))
                    if isinstance(item, (dict, list, set, tuple)):
                        field['length'] = len(item)
                    if isinstance(item, dict):
                        count = total = largest = maximum_bits = 0
                        for member in item.values():
                            bits = getattr(member, 'bits', None)
                            if isinstance(bits, int) or hasattr(bits, 'referenced_storage_bytes'):
                                size = bits.referenced_storage_bytes() if hasattr(bits, 'referenced_storage_bytes') else sys.getsizeof(bits)
                                count += 1; total += size; largest = max(largest, size)
                                maximum_bits = max(maximum_bits, bits.bit_length())
                        if count:
                            field.update(target_sets=count, referenced_bitmap_bytes=total,
                                         max_bitmap_bytes=largest, max_bit_length=maximum_bits)
                    fields[key] = field
                if hasattr(value, 'load_dependencies') and hasattr(value, 'target_pool'):
                    try:
                        fields['_runtime_allocations'] = solver_runtime_sizes(value)
                    except MemoryError:
                        fields['_runtime_allocations'] = dict(incomplete=True,reason='Profiling allocation failed')
                row['locals'][name] = fields
                solver_fields[id(value)] = fields
        result.append(row)
        tb = tb.tb_next
    return result


def inside(args):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    sys.path.insert(0, str(args.engine))
    from ecra import cli, scan_diagnostics
    final_reserve = CommitReserve()
    final_python = python_reserve()
    start = time.monotonic()
    while not (args.evidence/'limit.json').is_file():
        if time.monotonic()-start > 30:
            raise RuntimeError('Explicit controlled limit was not applied')
        time.sleep(0.1)
    source_files = sorted(p for p in args.workers.glob('TU-*.response.json') if '.dependencies.' not in p.name)
    source = {p.name.split('.')[0]: p for p in source_files}
    replayed = []
    reached = False
    probe_reached = False
    analysis_facts = None
    solver_summaries = {}
    def capture_solver_stats(facts):
        for key in ('points_to_stats', 'context_points_to_stats'):
            data = facts.get(key, {}) if facts is not None else {}
            solver_summaries[key] = {field: data[field] for field in
                ('complete', 'equations', 'evaluations', 'locations', 'targets', 'iterations', 'reason')
                if field in data}
    class ReplayBoundary(Exception):
        pass
    def responses(root, units, cfg, worker_dir, env, tool_root, out):
        if len(source) != len(units):
            raise ValueError('Replay collection must contain the entire real target')
        for unit in units:
            path = source[unit['tu_id']]
            request = json.loads(path.with_name(unit['tu_id']+'.request.json').read_text(encoding='utf-8'))
            old = request['unit']
            for field in ('source', 'source_file', 'directory', 'arguments', 'original_arguments'):
                if old.get(field) != unit.get(field):
                    raise ValueError(f'Captured TU command differs: {unit["tu_id"]} {field}')
            metadata = Path(str(path)+'.metadata.json')
            if not metadata.is_file():
                raise ValueError('Complete metadata required for exact replay')
            replayed.append(dict(path=str(path), bytes=path.stat().st_size,
                metadata_sha256=hashlib.sha256(metadata.read_bytes()).hexdigest()))
            yield unit, path, metadata
    original_analyze = cli.analyze
    original_merge = cli.merge
    def merge(*a, **kw):
        if args.analysis_after_resource:
            waiting = time.monotonic()
            print('CONTROLLED RESOURCE WAIT: full captured facts retained; no analysis started.', flush=True)
            while True:
                try:
                    resource = json.loads(args.analysis_after_resource.read_text(encoding='utf-8-sig'))
                except (FileNotFoundError, json.JSONDecodeError):
                    resource = {}
                if resource.get('complete') is True:
                    break
                time.sleep(2)
            dump(args.evidence/'analysis-resource-wait.json', dict(
                complete=True,full_scan_acceptance=False,seconds=time.monotonic()-waiting,
                receipt=str(args.analysis_after_resource),reason='Serialize independent memory-intensive experiments'))
        reserve = CommitReserve()
        python_backup = python_reserve()
        try:
            if args.merged_cache_in:
                from ecra.fact_parts import FactParts
                from ecra.json_rows import rows
                from ecra.workflow import file_digest
                metadata = json.loads(args.merged_cache_in.with_suffix('.metadata.json').read_text(encoding='utf-8'))
                if (metadata.get('controlled_replay') is not True or metadata.get('full_scan_acceptance') is not False
                        or metadata.get('files') != replayed
                        or metadata.get('sha256') != file_digest(args.merged_cache_in)):
                    raise ValueError('Merged replay cache provenance or full content hash differs')
                facts = {key: [] for key in metadata['tables']}
                decoder = FactParts()
                for table, row, array in rows(args.merged_cache_in, decoder._object):
                    if not array or table not in facts:
                        raise ValueError('Unexpected replay cache schema')
                    facts[table].append(row)
                if {key: len(value) for key, value in facts.items()} != metadata['tables']:
                    raise ValueError('Merged replay cache table counts differ')
                dump(args.evidence/'merged-cache-loaded.json', dict(
                    controlled_replay=True, full_scan_acceptance=False,
                    path=str(args.merged_cache_in), sha256=metadata['sha256'],
                    tables=metadata['tables'], memory=scan_diagnostics.memory(),
                    record_schemas=decoder._records.cache_info()._asdict() if hasattr(decoder, '_records') else None))
            else:
                facts = original_merge(*a, **kw)
            if args.merged_cache_out:
                from ecra.common import write_json
                from ecra.workflow import file_digest
                write_json(args.merged_cache_out, facts, indent=None)
                dump(args.merged_cache_out.with_suffix('.metadata.json'), dict(
                    controlled_replay=True,full_scan_acceptance=False,
                    sha256=file_digest(args.merged_cache_out),tables={k:len(v) for k,v in facts.items()},files=replayed))
            return facts
        except MemoryError as exc:
            python_backup = None
            reserve.close()
            dump(args.evidence/'allocation-frames.json', frame_sizes(exc))
            raise
        finally:
            python_backup = None
            reserve.close()
    def measured(*a, **kw):
        nonlocal analysis_facts
        analysis_facts = a[0]
        reserve = CommitReserve()
        python_backup = python_reserve()
        try:
            return original_analyze(*a, **kw)
        except MemoryError as exc:
            python_backup = None
            reserve.close()
            dump(args.evidence/'allocation-frames.json', frame_sizes(exc))
            raise
        finally:
            python_backup = None
            reserve.close()
            capture_solver_stats(analysis_facts)
            analysis_facts = None
    original_stage = scan_diagnostics.start_stage
    from ecra.points_to import Solver
    original_init = Solver.__init__
    original_add_points = Solver.add_points
    initialized = 0
    next_sample = args.pointer_sample_step
    last_sample = time.monotonic()
    def indexed(self, *a, **kw):
        nonlocal initialized
        if args.solver_tracemalloc:
            import tracemalloc
            if not tracemalloc.is_tracing():
                tracemalloc.start(1)
        original_init(self, *a, **kw)
        initialized += 1
        # Only IDs are retained by this diagnostic, never another copy of IR.
        unique = {id(value) for value in self.storage_definitions.values()}
        dump(args.evidence/f'storage-index-{initialized}.json', dict(
            locations=len(self.storage_definitions), unique_layouts=len(unique),
            index_shallow_bytes=sys.getsizeof(self.storage_definitions),
            pointer_storage_rows=len(self.facts.get('pointer_storage', [])),
            memory=scan_diagnostics.memory()))
    def sampled_points(self, *a, **kw):
        nonlocal probe_reached, next_sample, last_sample
        result = original_add_points(self, *a, **kw)
        now = time.monotonic()
        stop_probe = args.pointer_probe_atoms and not probe_reached and len(self.target_pool.values) >= args.pointer_probe_atoms
        periodic_sample = next_sample and len(self.target_pool.values) >= next_sample
        timed_sample = args.solver_sample_seconds > 0 and now-last_sample >= args.solver_sample_seconds
        if stop_probe or periodic_sample or timed_sample:
            last_sample = now
            probe_reached = bool(stop_probe)
            structures = {}
            seen = set()
            unique_bytes = 0
            for name in ('points', 'unknown_points'):
                collection = getattr(self, name)
                histogram = Counter()
                references = sparse_bytes = 0
                for targets in collection.values():
                    bits = targets.bits
                    count = bits.bit_count()
                    bucket = str(count) if count <= 4 else '5-32' if count <= 32 else '33-128' if count <= 128 else '>128'
                    histogram[bucket] += 1
                    size = bits.referenced_storage_bytes() if hasattr(bits, 'referenced_storage_bytes') else sys.getsizeof(bits)
                    references += size
                    if count <= 128 and bits.bit_length() > 8192:
                        sparse_bytes += size
                    if id(bits) not in seen:
                        seen.add(id(bits)); unique_bytes += size
                structures[name] = dict(sets=len(collection), cardinalities=dict(histogram),
                    referenced_bitmap_bytes=references, sparse_wide_bitmap_bytes=sparse_bytes)
            name = ('pointer-cardinality-probe.json' if stop_probe else
                    f'pointer-sample-{next_sample:09d}.json' if periodic_sample else
                    f'solver-runtime-{initialized}-{int(now-start):010d}.json')
            dump(args.evidence/name, dict(
                controlled_replay=True,full_scan_acceptance=False,pointer_stages_complete=False,
                atoms=len(self.target_pool.values),structures=structures,
                runtime_allocations=solver_runtime_sizes(self),
                unique_referenced_bitmap_objects=len(seen),unique_bitmap_bytes=unique_bytes,
                bitmap_size_boundary='Referenced object/storage bytes; shared blocks may be counted more than once; OS Private Bytes is authoritative',
                memory=scan_diagnostics.memory()))
            if args.solver_tracemalloc:
                import tracemalloc
                traced = tracemalloc.get_traced_memory()
                snapshot = tracemalloc.take_snapshot()
                top = [dict(location=str(stat.traceback),bytes=stat.size,count=stat.count)
                       for stat in snapshot.statistics('lineno')[:80]]
                del snapshot
                dump(args.evidence/(name.removesuffix('.json')+'-tracemalloc.json'), dict(
                    controlled_replay=True,full_scan_acceptance=False,atoms=len(self.target_pool.values),
                    traced_current_bytes=traced[0],traced_peak_bytes=traced[1],
                    tracer_overhead_bytes=tracemalloc.get_tracemalloc_memory(),top_allocations=top,
                    memory=scan_diagnostics.memory()))
            if periodic_sample:
                next_sample = (len(self.target_pool.values) // args.pointer_sample_step + 1) * args.pointer_sample_step
            if stop_probe:
                raise ReplayBoundary('Controlled stop after bitmap cardinality measurement; no complete pointer solution or safety report')
        return result
    def stage(name, operation=None):
        nonlocal reached
        original_stage(name, operation)
        if args.stop_after_pointers and name == '结构体字段、数组与重叠存储分析':
            reached = True
            capture_solver_stats(analysis_facts)
            raise ReplayBoundary('Controlled stop after both complete pointer solvers; not a full scan')
    def stop_render(*a, **kw):
        nonlocal reached
        reached = True
        raise ReplayBoundary('Controlled stop after complete analysis; no safety report')
    cli.extraction_responses = responses
    cli.merge = merge
    cli.analyze = measured
    cli.generate = stop_render
    scan_diagnostics.start_stage = stage
    Solver.__init__ = indexed
    if args.pointer_probe_atoms or args.pointer_sample_step or args.solver_sample_seconds > 0:
        Solver.add_points = sampled_points
    if args.captured_dependencies:
        def dependencies(root, units, cfg, worker_dir, env, tool_root):
            for unit in units:
                metadata = json.loads(Path(str(source[unit['tu_id']])+'.metadata.json').read_text(encoding='utf-8'))
                yield unit, metadata['input_snapshot'], metadata.get('preprocessor_signature')
        cli.dependency_results = dependencies
    print('CONTROLLED REAL FACT REPLAY: no new TU extraction; not full-scan acceptance.', flush=True)
    escaped_error = None
    try:
        code = cli.run(args.project, args.config, no_review=True)
    except BaseException as exc:
        final_python = None
        final_reserve.close()
        escaped_error = dict(type=type(exc).__name__, traceback=traceback.format_exc())
        traceback.print_exception(type(exc), exc, exc.__traceback__)
        code = 130 if isinstance(exc, KeyboardInterrupt) else 3
    # A Solver can have collectible cache cycles after a failed experiment.
    # Release the explicit diagnostic reserve before recording this failure.
    final_python = None
    final_reserve.close()
    gc.collect()
    fixed_points_complete = all(solver_summaries.get(key, {}).get('complete') is True
        for key in ('points_to_stats', 'context_points_to_stats'))
    result = dict(controlled_replay=True, full_scan_acceptance=False, safety_report_valid=False,
        pointer_stages_reached=reached, solver_fixed_points_complete=fixed_points_complete,
        pointer_stages_complete=reached and fixed_points_complete,
        full_analysis_complete=reached and fixed_points_complete and not args.stop_after_pointers,
        solver_summaries=solver_summaries,
        pointer_cardinality_probe_complete=probe_reached,
        fresh_clang_dependency_discovery=not args.captured_dependencies,
        merged_ir_cache=str(args.merged_cache_in) if args.merged_cache_in else None,
        cli_exit_code=code, seconds=time.monotonic()-start, interpreter=sys.version, files=replayed)
    result['escaped_error'] = escaped_error
    result['diagnostic_reserve'] = 'Two explicit 8 MiB private commit reserves and Python size-class pools; controlled harness overhead only'
    dump(args.evidence/'replay-result.json', result)
    return 0 if (reached and fixed_points_complete) or probe_reached else code or 3


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('engine', 'python', 'project', 'config', 'workers', 'evidence'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--limit-gib', type=float, default=24)
    parser.add_argument('--stop-after-pointers', action='store_true')
    parser.add_argument('--captured-dependencies',action='store_true',
        help='IR replay only: validate captured dependency hashes without rediscovering includes; never full-scan acceptance')
    parser.add_argument('--merged-cache-out',type=Path,help='Persist complete merged IR for separately labelled replay')
    parser.add_argument('--merged-cache-in',type=Path,help='CONTROLLED IR replay only; verifies complete cache SHA and TU metadata, never native acceptance')
    parser.add_argument('--pointer-probe-atoms',type=int,default=0,help='CONTROLLED diagnostic stop at target-pool size; never a complete solver/scan')
    parser.add_argument('--pointer-sample-step',type=int,default=0,help='CONTROLLED cardinality samples at atom intervals; does not stop solving')
    parser.add_argument('--solver-tracemalloc',action='store_true',
        help='CONTROLLED replay profiling only: trace allocations after merged facts are prepared')
    parser.add_argument('--solver-sample-seconds',type=float,default=120,
        help='CONTROLLED runtime census interval: also captures growth with no new target atoms; 0 disables')
    parser.add_argument('--analysis-after-resource',type=Path,
        help='CONTROLLED resource scheduling only: wait before loading/merging IR; never a full-scan acceptance')
    parser.add_argument('--inside', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.pointer_sample_step < 0 or args.pointer_probe_atoms < 0 or args.solver_sample_seconds < 0:
        parser.error('Pointer sampling thresholds cannot be negative')
    if args.merged_cache_in and args.merged_cache_out:
        parser.error('Choose either merged-cache-in or merged-cache-out')
    if args.inside:
        return inside(args)
    import psutil
    import shutil
    from large_stm32_scan import monitor_sample
    args.evidence.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(__file__, args.evidence/'harness.py')
    helper_path = Path(__file__).with_name('commit_reserve.py')
    shutil.copyfile(helper_path, args.evidence/'commit_reserve.py')
    # Execute the archived source itself. Later edits to a test script must not
    # make traceback linecache show code that this process never executed.
    command = [str(args.python), '-u', str((args.evidence/'harness.py').resolve()), *sys.argv[1:], '--inside']
    peaks = {}; start = time.monotonic()
    with (args.evidence/'console.log').open('w', encoding='utf-8') as log, \
            (args.evidence/'memory.jsonl').open('w', encoding='utf-8') as memory:
        proc = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        root = psutil.Process(proc.pid)
        controller = subprocess.Popen([sys.executable, str(Path(__file__).with_name('windows_memory_limit.py')),
            '--pid', str(proc.pid), '--gib', str(args.limit_gib), '--evidence', str(args.evidence/'limit.json')],
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        dump(args.evidence/'execution-start.json', dict(pid=proc.pid,created_unix=root.create_time(),command=command,
            harness_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            reserve_helper_sha256=hashlib.sha256(helper_path.read_bytes()).hexdigest()))
        reserve = [bytearray(256*1024)]
        while proc.poll() is None:
            monitor_sample(root, start, peaks, memory, psutil, args.evidence/'monitor_errors.log', reserve=reserve)
            time.sleep(0.5)
    dump(args.evidence/'execution.json', dict(controlled_replay=True,full_scan_acceptance=False,
        pid=proc.pid,exit_code=proc.returncode,seconds=time.monotonic()-start,peaks=peaks))
    return proc.returncode


if __name__ == '__main__':
    raise SystemExit(main())
