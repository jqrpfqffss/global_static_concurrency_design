"""Resume reviews only against a verified, unchanged static scan."""
import copy
import hashlib
import json
from collections import OrderedDict
from functools import lru_cache
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from .common import digest, read_json, relative, write_json
from .config import load_config
from .html_report import REVIEW_PAGE, category, review_records, write_html
from .report import generate
from .review import review_all, verify_receipt
from .review_integrity import normalize_review_record, set_review_state


def file_digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


ENGINE_SCOPE = 'static-v1'
# These modules consume existing facts; they do not recover accesses, calls or
# static classifications. Unknown/new modules remain included by default.
REVIEW_REPORT_MODULES = frozenset({
    'case_library.py', 'decisions.py', 'html_report.py', 'report.py',
    'review.py', 'review_context.py', 'review_contract.py', 'review_integrity.py',
    'review_presentation.py', 'review_language.py', 'review_summary.py', 'workflow.py',
})


def engine_digest():
    package = Path(__file__).parent
    return digest({path.name: file_digest(path) for path in sorted(package.glob('*.py'))
                   if path.name not in REVIEW_REPORT_MODULES})


def analysis_config(cfg):
    return {k: v for k, v in cfg.items() if k != 'review'}


def read_saved_json(path, *, canonical_accesses=False):
    """Read a complete saved object without an all-file Unicode allocation.

    Equal immutable strings are shared. For facts, complete read-only access
    entities can also share storage, as they do before serialization. Array
    order, duplicate entries, scalar types and every field remain unchanged.
    """
    from .json_rows import RecordDicts, RowReader
    strings = lru_cache(maxsize=131072)(lambda value: value)
    records = RecordDicts()
    access_rows, access_count = OrderedDict(), 0
    def identical(first, second):
        if first is second:
            return True
        if type(first) is not type(second):
            return False
        if isinstance(first, dict):
            return (len(first) == len(second) and all(a == b for a, b in zip(first, second))
                    and all(identical(first[key], second[key]) for key in first))
        if isinstance(first, list):
            return len(first) == len(second) and all(identical(a, b) for a, b in zip(first, second))
        if isinstance(first, float):
            return first.hex() == second.hex()
        return first == second
    def share(value):
        if isinstance(value, str):
            return strings(value) if len(value) <= 1024 else value
        if isinstance(value, list):
            for index, item in enumerate(value):
                value[index] = share(item)
        return value
    def object_hook(value):
        nonlocal access_count
        source = value
        keys = tuple(strings(key) for key in source)
        value = records(keys)
        for key, item in zip(keys, source.values()):
            value[key] = share(item)
        if canonical_accesses and all(key in value for key in
                ('access_id', 'access_kind', 'symbol_id', 'function_id', 'file', 'offset')):
            key = value['access_id'], value['symbol_id'], value.get('access_path')
            try:
                bucket = access_rows.get(key, ())
            except TypeError:
                return value
            for previous in bucket:
                # Python's ordinary == would conflate True/1 and -0.0/0.0.
                # Exact JSON type/value/key-order equality is mandatory.
                if identical(previous, value):
                    access_rows.move_to_end(key)
                    return previous
            if not bucket:
                access_rows[key] = bucket = []
            bucket.append(value)
            access_count += 1
            access_rows.move_to_end(key)
            # This is a bounded index, not an evidence limit: evicted rows
            # remain in the returned arrays, and unmatched rows stay complete.
            while access_count > 1048576:
                _, evicted = access_rows.popitem(last=False)
                access_count -= len(evicted)
        return value
    result = {}
    with Path(path).open(encoding='utf-8-sig') as stream:
        reader = RowReader(stream, object_hook)
        reader.take('{')
        if reader.peek() != '}':
            while True:
                key = reader.value()
                if not isinstance(key, str) or key in result:
                    raise ValueError('Invalid or repeated saved JSON field')
                reader.take(':')
                if reader.peek() == '[':
                    reader.take('[')
                    result[key] = []
                    if reader.peek() != ']':
                        while True:
                            result[key].append(share(reader.value()))
                            if reader.peek() == ']':
                                break
                            reader.take(',')
                    reader.take(']')
                else:
                    result[key] = share(reader.value())
                if reader.peek() == '}':
                    break
                reader.take(',')
        reader.take('}')
        if reader.peek():
            raise ValueError('Trailing data in saved JSON')
    return result


def saved_report_digest(report):
    """Exactly common.digest's JSON bytes, emitted incrementally."""
    sha = hashlib.sha256()
    for chunk in json.JSONEncoder(sort_keys=True, ensure_ascii=False).iterencode(report):
        sha.update(chunk.encode('utf-8'))
    return sha.hexdigest()


def clean_report(report):
    # Only these dictionaries are edited. Nested static evidence is read-only;
    # copying it would duplicate gigabytes before validating a saved report.
    result = dict(report)
    result['findings'] = [dict(finding) for finding in report['findings']]
    for key in ('run_status', 'stale_reason', 'review_summary', 'review_integrity', 'review_records', 'matrix_review_summary', 'risk_summary', 'final_conclusion'):
        result.pop(key, None)
    for f in result['findings']:
        f.pop('review', None)
        f.pop('review_state', None)
        f.pop('review_status', None)
        f.pop('review_result', None)
        f.pop('effective_decision', None)
        f.pop('decision_label', None)
        f['status'] = 'NEED_OPENCODE_REVIEW'
    return result


def save_scan(root, out, cfg, config_file, report, *, initialize_queue=True):
    from .review_integrity import review_targets, assert_review_integrity
    queue = [set_review_state(dict(finding_id=f['finding_id'],
        static_classification=f.get('static_classification')), 'PENDING') for f in review_targets(report)]
    assert_review_integrity(report, queue)
    if initialize_queue:
        write_json(out/'review/queue.json', queue)
    else:
        assert_review_integrity(report, read_queue(out))
    write_json(out/'scan_state.json', dict(schema=1, project_root=str(root),
        config_file=relative(config_file, root), config_digest=digest(analysis_config(cfg)),
        engine_scope=ENGINE_SCOPE, engine_digest=engine_digest(), facts_sha256=file_digest(out/'facts.json'),
        manifest_sha256=file_digest(out/'input_manifest.json'),
        input_closure_sha256=file_digest(out/'input_closure.json') if (out/'input_closure.json').is_file() else None,
        report_digest=saved_report_digest(clean_report(report)), fingerprint=report['fingerprint']))


def verify_saved_input_closure(root, out, cfg, state, manifest, config_file):
    """Re-run only preprocessing, using checkpoint-bound compiler inputs.

    Existing file hashes cannot detect a new earlier search-path header or a
    negative __has_include probe. No build/configure or full facts load occurs.
    """
    import shutil
    import tempfile
    from .cli import dependency_results
    from .input_snapshot import file_record
    capsule_file = out/'input_closure.json'
    expected_hash = state.get('input_closure_sha256')
    if not isinstance(expected_hash, str) or not expected_hash:
        raise ValueError('旧扫描检查点缺少可重放输入闭包；请重新运行 run')
    if not capsule_file.is_file() or file_digest(capsule_file) != expected_hash:
        raise ValueError('扫描输入闭包已变化/损坏；请重新运行 run')
    capsule = read_json(capsule_file)
    units = capsule.get('units')
    dependencies = capsule.get('dependency_sets')
    signatures = capsule.get('preprocessor_signatures')
    if (capsule.get('schema') != 1 or not isinstance(units, list)
            or not isinstance(dependencies, dict) or not isinstance(signatures, dict)):
        raise ValueError('扫描输入闭包格式损坏；请重新运行 run')
    ids = [unit.get('tu_id') for unit in units if isinstance(unit, dict)]
    if (len(ids) != len(units) or len(set(ids)) != len(ids)
            or set(ids) != set(dependencies) or set(ids) != set(signatures)):
        raise ValueError('扫描输入闭包单元集合损坏；请重新运行 run')
    changes = []
    parent_selections = capsule.get('parent_selections',[])
    if not isinstance(parent_selections,list):
        raise ValueError('父进程输入选择记录损坏；请重新运行 run')
    for selection in parent_selections:
        if (not isinstance(selection,dict) or not isinstance(selection.get('directory'),str)
                or selection.get('pattern') != '*.map' or not isinstance(selection.get('files'),list)
                or any(not isinstance(name,str) for name in selection['files'])):
            raise ValueError('父进程输入选择记录损坏；请重新运行 run')
        current_files = sorted(relative(path,root) for path in Path(selection['directory']).glob(selection['pattern']))
        if current_files != selection['files']:
            changes.append(dict(file=relative(selection['directory'],root)+'/'+selection['pattern'],
                reason='PARENT_INPUT_SET_CHANGED',before=selection['files'],after=current_files))
    tool_root = Path(__file__).resolve().parent.parent
    env = os.environ.copy()
    env['PYTHONPATH'] = str(tool_root) + os.pathsep + env.get('PYTHONPATH', '')
    with tempfile.TemporaryDirectory(prefix='verify-inputs-', dir=out) as temp:
        work = Path(temp)/'workers'
        work.mkdir()
        try:
            for unit, inputs, signature in dependency_results(root, units, cfg, work, env, tool_root):
                tu_id = unit['tu_id']
                current = {relative(path, root): row for path, row in inputs.items()}
                expected = set(dependencies[tu_id])
                if signatures[tu_id] is not None and signature != signatures[tu_id]:
                    changes.append(dict(file=unit['source_file'], unit=tu_id,
                        reason='PREPROCESSOR_STATE_CHANGED', before=signatures[tu_id], after=signature))
                for path in sorted(expected | set(current)):
                    row = current.get(path)
                    if (path not in expected or row is None or row.get('status') != 'OK'
                            or row.get('sha256') != manifest.get(path)):
                        changes.append(dict(file=path, unit=tu_id, reason='DEPENDENCY_CHANGED',
                                            before=manifest.get(path), after=row))
        except BaseException:
            # Preserve worker diagnostics when a subprocess fails. Never turn
            # a failed verification into an apparently current checkpoint.
            try:
                shutil.copytree(Path(temp)/'diagnostics', out/'diagnostics/resume-input-error', dirs_exist_ok=True)
            except (OSError, MemoryError):
                pass
            raise
    ignored = {state['config_file'], relative(config_file, root)}
    for path, expected in manifest.items():
        if path in ignored:
            continue
        row = file_record(root/path)
        if row.get('status') != 'OK' or row.get('sha256') != expected:
            changes.append(dict(file=path, reason='INPUT_CHANGED_DURING_RESUME', before=expected, after=row))
    live_cfg, _ = load_config(root, config_file)
    live_digest = digest(analysis_config(live_cfg))
    if live_digest != state['config_digest']:
        changes.append(dict(file=relative(config_file, root), reason='ANALYSIS_CONFIGURATION_CHANGED',
                            before=state['config_digest'], after=live_digest))
    current_engine = engine_digest()
    if current_engine != state['engine_digest']:
        changes.append(dict(file=str(tool_root/'ecra'), reason='STATIC_ENGINE_CHANGED',
                            before=state['engine_digest'], after=current_engine))
    write_json(out/'diagnostics/resume_source_changes.json', dict(schema=1,
               status='INVALID' if changes else 'VERIFIED', changes=changes))
    if changes:
        paths = ', '.join(dict.fromkeys(row['file'] for row in changes))
        raise ValueError('源码/头文件/编译数据库已变化，需重新扫描：' + paths[:1500]
                         + '；详见 diagnostics/resume_source_changes.json')


def verify_saved_publication(root, out, cfg, state, config_file):
    """Validate the long render window before reporting a saved command done."""
    import traceback
    from .html_report import write_failure
    from .scan_diagnostics import memory
    reserve = bytearray(128 * 1024)
    try:
        if (file_digest(out/'input_manifest.json') != state['manifest_sha256']
                or file_digest(out/'facts.json') != state['facts_sha256']):
            raise ValueError('恢复发布期间事实或输入清单已变化；请重新运行 run')
        if state.get('input_closure_sha256') or (out/'diagnostics/source_changes.json').is_file():
            verify_saved_input_closure(root, out, cfg, state, read_json(out/'input_manifest.json'), config_file)
        else:
            # Legacy broad manifests retain their existing validation policy.
            live_cfg, _ = load_config(root, config_file)
            checked_scan(root, out, live_cfg, config_file, with_facts=False)
    except BaseException as exc:
        reserve = None
        trace = traceback.format_exc()
        (out/'scan_state.json').unlink(missing_ok=True)
        error = f'{type(exc).__name__}: {exc}'
        write_json(out/'result_validity.json', dict(analysis_valid=False, state='FAILED',
                   stage='saved_publication_inputs', error=error))
        diag = out/'diagnostics'
        diag.mkdir(exist_ok=True)
        (diag/'exception.log').write_text(trace, encoding='utf-8')
        detail = dict(stage='saved_publication_inputs', exception_type=type(exc).__name__,
                      error=str(exc), memory=memory(), analysis_valid=False)
        # Preserve the full generated evidence by a same-directory-tree rename,
        # rather than copying a multi-GB report just to invalidate its public URL.
        source = out/'reports/global_static_concurrency.json'
        target = diag/('invalid-publication-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.json')
        can_replace = True
        if source.is_file():
            try:
                if not all(p.resolve().is_relative_to(out.resolve()) for p in (source, target)):
                    raise OSError('Refusing report archive outside output directory')
                source.replace(target)
                detail['invalid_report_archive'] = str(target)
            except OSError as archive_error:
                can_replace = False
                detail['report_archive_error'] = str(archive_error)
        write_failure(out, write_report=can_replace)
        write_json(diag/'exception.json', detail)
        write_json(out/'resume.json', dict(state='FAILED', exit_code=3, error=error,
                   stage='saved_publication_inputs', finished=datetime.now(timezone.utc).isoformat()))
        raise


def checked_scan(root, out, cfg, config_file, *, with_facts=True):
    from .cli import file_hashes
    if not (out/'scan_state.json').is_file():
        raise ValueError('没有可恢复的扫描检查点；请先运行 run（旧版报告需要重新扫描一次）')
    state = read_json(out/'scan_state.json')
    required=('project_root','config_file','config_digest','engine_digest','facts_sha256','manifest_sha256','report_digest','fingerprint')
    if not isinstance(state,dict) or any(not isinstance(state.get(k),str) for k in required):
        raise ValueError('扫描检查点损坏；请重新运行 run')
    if state.get('schema') != 1 or state.get('project_root') != str(root):
        raise ValueError('扫描检查点不属于当前工程；请重新运行 run')
    rescan = '请先执行 py -3.10 run_ecra.py --no-review 刷新静态扫描，再执行复核命令'
    if state['config_digest'] != digest(analysis_config(cfg)):
        raise ValueError('分析配置已变化，不能复用旧调用链；' + rescan)
    if state.get('engine_scope') != ENGINE_SCOPE:
        # The old aggregate digest cannot establish which modules changed.
        # Refresh once rather than bless unknown old facts by replacing a hash.
        raise ValueError('旧扫描检查点使用全程序指纹，需一次性更新为静态分析指纹；' + rescan)
    if state['engine_digest'] != engine_digest():
        raise ValueError('静态分析实现已变化，不能复用旧调用链；' + rescan)
    if (state['facts_sha256'] != file_digest(out/'facts.json') or
            state['manifest_sha256'] != file_digest(out/'input_manifest.json')):
        raise ValueError('扫描事实或输入清单已变化/损坏；请重新运行 run')
    report = read_saved_json(out/'reports/global_static_concurrency.json')
    if not isinstance(report,dict) or not isinstance(report.get('findings'),list):
        raise ValueError('静态报告格式损坏；请重新运行 run')
    if saved_report_digest(clean_report(report)) != state['report_digest']:
        raise ValueError('静态报告已变化/损坏；请重新运行 run')
    manifest = read_json(out/'input_manifest.json')
    from .scope import AuditScope
    # Current scans bind the actual compiler closure. Legacy scans retain the
    # old broad manifest behavior until refreshed.
    precise = bool(state.get('input_closure_sha256')) or (out / 'diagnostics/source_changes.json').is_file()
    current = file_hashes(root, out, [config_file, *(root/p for p in manifest)],
                          AuditScope(root, cfg['analysis']).includes if not precise else (), exact=precise)
    # Model/time/retry settings can change without re-parsing the firmware.
    ignored = {state['config_file'], relative(config_file, root)}
    changed = sorted(p for p in set(current) | set(manifest)
                     if p not in ignored and current.get(p) != manifest.get(p))
    if changed:
        raise ValueError('源码/头文件/编译数据库已变化，需重新扫描：' + ', '.join(changed[:8]))
    if precise:
        verify_saved_input_closure(root, out, cfg, state, manifest, config_file)
    return (read_saved_json(out/'facts.json', canonical_accesses=True) if with_facts else None), clean_report(report), state


def output_path(root, cfg):
    out = (root/cfg['analysis'].get('output_dir', '.ecra')).resolve()
    if out == root or not out.is_relative_to(root):
        raise ValueError('analysis.output_dir 必须是工程根目录下的独立子目录')
    return out


def checked_reviews(root, out, reviews, fingerprint):
    import json
    verified=[]
    for original in reviews:
        r=normalize_review_record(copy.deepcopy(original))
        if r.get('state')=='DONE':
            try:
                cached=read_json(out/'review'/(r['finding_id']+'.result.json'))
                if (r.get('scan_fingerprint')!=fingerprint or cached.get('cache_key')!=r.get('cache_key')
                        or cached.get('answer')!=r.get('answer')):
                    raise ValueError('复核收据与当前扫描/缓存不匹配')
                answer=verify_receipt(root, out/'review', r)
                if answer['status']!=r.get('status'):
                    raise ValueError('复核状态与答案不一致')
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
                from .review_integrity import mark_review_stale
                mark_review_stale(out/'review', r, exc)
        verified.append(r)
    return verified


def read_queue(out):
    try:
        rows=read_json(out/'review/queue.json')
        if not isinstance(rows,list):
            return []
        return [r for r in rows if isinstance(r,dict) and isinstance(r.get('finding_id'),str)]
    except (OSError,ValueError):
        # Per-item caches can still be recovered by review_all. A broken queue
        # never means that the corresponding findings have been reviewed.
        return []


def status(root, config_path=None):
    cfg, config_file = load_config(root, config_path)
    out = output_path(root, cfg)
    info = dict(project=str(root), output=str(out), scan_lock=(out/'scan.lock').exists())
    if not (out/'reports/global_static_concurrency.json').exists():
        info.update(state='NOT_SCANNED', next_action='运行 run，生成变量清单和复核队列')
    else:
        report = read_saved_json(out/'reports/global_static_concurrency.json')
        queue = read_queue(out)
        records = review_records(report, queue)
        from .review_integrity import review_integrity
        integrity = review_integrity(report, queue)
        info.update(state=report.get('run_status', 'SCANNED'), analysis_status=report['analysis_status'],
                    variables=report['coverage'].get('variables_total'), findings=len(records),
                    unresolved=sum(category(r)=='unresolved' for r in records),
                    review_integrity=integrity, review_complete=integrity['all_done'],
                    inventory_html=str(out/'index.html'), review_html=str(out/REVIEW_PAGE))
        if info['scan_lock']:
            info.update(resumable=False, next_action='存在运行锁：等待扫描/复核结束；若进程已退出，确认后移除过期 scan.lock。当前数量来自已保存的结果。')
            return info
        try:
            checked_scan(root, out, cfg, config_file, with_facts=False)
            # A DONE label in queue.json is not enough to claim completion.
            # Check the immutable prompt, transcript, answer and cited source
            # before reporting a review as finished, without changing files.
            receipt_errors = []
            verified_queue = copy.deepcopy(queue)
            for row in verified_queue:
                if row.get('state') != 'DONE':
                    continue
                try:
                    verify_receipt(root, out/'review', row)
                except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
                    receipt_errors.append(dict(finding_id=row['finding_id'], error=str(exc)))
                    set_review_state(row, 'TECH_FAILED')
                    row.update(error=str(exc))
                    row.pop('answer', None)
            if receipt_errors:
                integrity = review_integrity(report, verified_queue)
                records = review_records(report, verified_queue)
                info.update(review_integrity=integrity, review_complete=False,
                            unresolved=sum(category(r) == 'unresolved' for r in records),
                            review_receipt_errors=receipt_errors)
            disabled = not cfg.get('review', {}).get('enabled', True)
            if receipt_errors:
                action = f"{len(receipt_errors)} 项复核收据未通过校验；运行 review 重建对应结果。"
            elif integrity['all_done']:
                if info['unresolved']:
                    action = f"全部模型复核已有答复，但 {info['unresolved']} 项仍缺证据；查看逐项复核并补充上下文。"
                elif report['analysis_status'] == 'INCOMPLETE':
                    action = '逐项复核已完成；静态分析仍有覆盖缺口，请查看报告的覆盖证据与未知事实。'
                else:
                    action = '逐项复核已完成；查看报告并核对固件构建配置。'
            elif disabled:
                action = '当前未启用模型：可按 HTML 人工排查；运行原命令重新扫描；运行 report 仅刷新结果。'
            else:
                action = '运行 review 重新复核全部疑似/未知；review-failed 只重跑技术失败；report 仅刷新结果'
            info.update(resumable=True, review_enabled=not disabled,
                        next_action=action)
        except (OSError, ValueError, KeyError) as exc:
            info.update(resumable=False, review_complete=False, next_action=str(exc))
    return info


def saved_run(root, config_path=None, render_only=False, failed_only=False):
    cfg, config_file = load_config(root, config_path)
    out = output_path(root, cfg)
    if not out.is_dir():
        raise ValueError('还没有扫描结果；请先运行 run')
    lock = out/'scan.lock'
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise ValueError(f'已有扫描锁 {lock}；请先确认当前运行状态') from exc
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)
    try:
        try:
            facts, report, state = checked_scan(root, out, cfg, config_file)
        except ValueError as exc:
            if '源码/头文件/编译数据库已变化' not in str(exc):
                raise
            # The old scan cannot be reviewed against changed source. Keep every
            # ID visible as STALE until a fresh run creates a new fingerprint.
            facts = read_saved_json(out/'facts.json', canonical_accesses=True)
            report = clean_report(read_saved_json(out/'reports/global_static_concurrency.json'))
            from .review_integrity import review_targets, mark_review_stale
            saved = {r['finding_id']:r for r in read_queue(out)}
            reviews = [saved.get(f['finding_id'], dict(finding_id=f['finding_id'], state='PENDING'))
                       for f in review_targets(report)]
            for row in reviews:
                mark_review_stale(out/'review', row, exc)
                row['error_type'] = 'SourceChanged'
                row['failure_stage'] = 'source_validation'
                write_json(out/'review'/(row['finding_id']+'.result.json'), row)
            report['run_status'] = 'INCOMPLETE'
            report['stale_reason'] = str(exc)
            generate(out, facts, report, reviews)
            write_json(out/'review/queue.json', reviews)
            write_json(out/'resume.json', dict(command='run', state='INCOMPLETE', exit_code=2,
                review_integrity=report['review_integrity'], finished=datetime.now(timezone.utc).isoformat()))
            return 2
        queue_file = out/'review/queue.json'
        reviews = read_queue(out)
        reviews = checked_reviews(root, out, reviews, state['fingerprint'])
        write_json(queue_file, reviews)
        if not render_only:
            cfg['review']['enabled'] = True
            last = time.monotonic()

            def checkpoint(current):
                nonlocal last
                if time.monotonic()-last >= 30:
                    report['run_status']='REVIEW_RUNNING'
                    write_html(out, facts, report, current)
                    last=time.monotonic()

            try:
                reviews = review_all(root, out, cfg, facts, report, state['fingerprint'], on_result=checkpoint,
                                     review_context_path=config_file.parent/'review_context.md',
                                     case_library_path=config_file.parent/'concurrency_cases.md',
                                     mode='review-failed' if failed_only else 'review')
            except KeyboardInterrupt:
                reviews = read_queue(out)
                report['run_status']='INTERRUPTED'
                generate(out, facts, report, reviews)
                print('复核已中断，队列已保留；review 重跑全部疑似/未知，review-failed 只重跑技术失败。', flush=True)
                return 130
        inputs_current = True
        try:
            checked_scan(root, out, cfg, config_file, with_facts=False)
        except (OSError, ValueError, KeyError):
            inputs_current = False
            from .review_integrity import mark_review_stale
            for r in reviews:
                mark_review_stale(out/'review', r, '恢复期间输入发生变化；请重新扫描。')
            report['analysis_status']='INCOMPLETE'
            report['limitations'].append('恢复期间输入发生变化；请重新扫描。')
        records = review_records(report, reviews)
        from .review_integrity import review_integrity
        integrity = review_integrity(report, reviews, require_terminal=True)
        report['run_status'] = 'INCOMPLETE' if (report['analysis_status']=='INCOMPLETE' or
            not integrity['complete'] or any(category(r) in {'unresolved', 'likely'} for r in records)) else 'REVIEW_COMPLETE'
        mapping={r['finding_id']:r for r in records}
        for f in report['findings']:
            r=mapping[f['finding_id']]
            f['review_state']=r['state']
            f['review_status']=r.get('status')
            f['review_result']=r
            if r['state']=='DONE':
                f['status']=r['status']; f['review']=r['answer']
        generate(out, facts, report, reviews)
        write_json(queue_file, reviews)
        if inputs_current:
            verify_saved_publication(root, out, cfg, state, config_file)
        code=2 if report['run_status']=='INCOMPLETE' else (1 if report['findings'] else 0)
        write_json(out/'resume.json', dict(command='report' if render_only else ('review-failed' if failed_only else 'review'), state=report['run_status'],
                                         finished=datetime.now(timezone.utc).isoformat(), exit_code=code,
                                         review_integrity=integrity))
        print(f"{report['run_status']}：{out/'index.html'}\nOpenCode：{out/REVIEW_PAGE}", flush=True)
        return code
    finally:
        lock.unlink(missing_ok=True)
