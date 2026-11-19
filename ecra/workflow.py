"""Resume reviews only against a verified, unchanged static scan."""
import copy
import hashlib
import json
from collections import OrderedDict
from functools import lru_cache
import os
from datetime import datetime, timezone
from pathlib import Path

from .common import digest, read_json, relative, write_json
from .config import load_config
from .html_report import REVIEW_PAGE, category, review_records
from .report import generate
from .review import review_all
from .review_integrity import set_review_state


def file_digest(path):
    from .scan_persistence import artifact
    mapped = artifact(path)
    if mapped is not None:
        path = mapped[0]
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


ENGINE_SCOPE = 'static-v1'
# c96308d, the last engine before the workspace change. A sealed result may
# resume archival review even when that engine's live build paths retired.
_PRE_WORKSPACE_ENGINES = frozenset({
    '3a1c30a68e917a2eb34cde42286c93e34bd2fdb48aef39c2c2ba5e0c4943190c',
    'd5309f7d9f2520844b2dbf5611b142fe28c91cc21dee9c00f0f1adfdad6f6937',
})
# These modules consume existing facts; they do not recover accesses, calls or
# static classifications. Unknown/new modules remain included by default.
REVIEW_REPORT_MODULES = frozenset({
    'case_library.py', 'decisions.py', 'html_report.py', 'report.py',
    'review.py', 'review_context.py', 'review_contract.py', 'review_integrity.py',
    'review_presentation.py', 'review_language.py', 'review_summary.py', 'workflow.py',
    'native_consumers.py', 'review_inheritance.py', 'review_sources.py', 'native_review_packet.py', 'review_hash.py', 'review_packet.py',
    'review_archive.py', 'review_process.py', 'review_session_cleanup.py', 'review_opencode_sessions.py',
    'opencode_storage.py', 'opencode_protocol.py', 'opencode_command.py', 'opencode_check.py',
})


_CLEANUP_CONFIG_UPGRADE = {
    # Only templates and review-only validation changed; retain static scan
    # and TU cache identities of both existing checkout line endings.
    '2cc053b945906dd2004889bbff6cf96e1892344f05883aae61a6c02e8502a883':
        'dcf410fed1f7cc3d01feb4a741ccc37dff8f8c3af90c26fe0d8c3e4afd90cd92',
    '0ce816b7a38da890e1bd73086a684802bdc59840eece4f683c6d32481d56f294':
        '54281c250ca8663f3e781ab389c94870738f33293702fda58ee57ec49d4f446e',
}


def _config_engine_hash(hashed):
    return _CLEANUP_CONFIG_UPGRADE.get(hashed, hashed)


# Exact review-only configuration/CLI upgrade; all static code still hashes normally.
_OPENCODE_RUNTIME_UPGRADE = {'config.py': {'c6078d9845b98cffc04aaad28645a5b8a09ec417c2df1e9c4b037753eb8c4311': '5d23965cdb19132dc10b04a08d2425b13ccc272e4ecb1977e6b1a1dfd569b3ba', '22d80b1c791cb093dd389ae94c5b8170e5c827a2431f99c47a1b609f83648070': '6352e018cec582589236685c52402ad514842e35e9134179048e3938c8505d65'}, 'cli.py': {'47d8615ad5fad1bd7a5b9c12b7048b90f4e0e10226e5f9ce6e35f7fbedc78508': '7beb189aab8dd9a5631b1ed850153bd070c26bb240458716c61eedf46b62c0e7', '23ef00da6290812ff063631d269deefe3bf04e00a5d83402765584931db5a48b': '6609c549543f4922fe18e2b5ad172a6a4b4ae0fb64a2c562a854ac9420231e46'}}


def _engine_files():
    package = Path(__file__).parent
    files = {path.name: file_digest(path) for path in sorted(package.glob('*.py'))
             if path.name not in REVIEW_REPORT_MODULES}
    for name, upgrades in _OPENCODE_RUNTIME_UPGRADE.items():
        if name in files:
            files[name] = upgrades.get(files[name], files[name])
    if 'config.py' in files:
        files['config.py'] = _config_engine_hash(files['config.py'])
    return files


_REVIEW_PUBLICATION_UPGRADE = {
    'cli.py': ('c9eda82f34af059f6f39861504f5b9caf3c551c23d747a61fa808d0e394e15fb',
               '2c66dd1233ad53670e1e16f485a7a518e7adc511c0b3ea51e24d265feb052721'),
    'scan_persistence.py': ('9945ba5d6bcefaca57508577e7240b4a1e1da1499a1a72e3d22d1cbf3af263a5',
                            'a4677b8ecad386c7e1154ecc26569441d3c48dd82399b0765f88eb0f54e55446'),
    'report_package.py': ('5c1137b1d54ae086ecdbd2951a6ae2e16e1bd7e7cf5ba3765c8f117c9c52a53b',
                          '028e7b9bf2d94c4a412b33a14781d3b13963677730655b020071d4925d04bd84'),
    'garbage_collection.py': ('2959f70ea45b3c0c9e40618580be203557663c9d952706070953fff9b6596b7e',
                              '5eaebb730d024e60fa60310092dfcd23e775c817f3f5e28655fb4192900db265'),
}


def engine_digest():
    files = _engine_files()
    # Each pair proves this review-only upgrade from 585df98. Future edits to
    # these files use their own byte digest, as do all other static modules.
    package = Path(__file__).parent
    for name, (after, before) in _REVIEW_PUBLICATION_UPGRADE.items():
        if name in files and hashlib.sha256((package/name).read_bytes().replace(b'\r\n', b'\n')).hexdigest() == after:
            files[name] = before
    return digest(files)


def matches_static_engine(expected, current=None):
    if expected == (current if current is not None else engine_digest()):
        return True
    # 3a12408 -> maintenance diagnostics: only review defaults/validation in
    # config.py changed. Admit that exact predecessor, not arbitrary engines.
    files = _engine_files()
    config_upgrade = {
        '5d23965cdb19132dc10b04a08d2425b13ccc272e4ecb1977e6b1a1dfd569b3ba':
            '88d6861cbf63e0d6815e92c1e36884fe2f89d7eabc7c748f8604048146021e5d',
        '6352e018cec582589236685c52402ad514842e35e9134179048e3938c8505d65':
            '86cd56ed3cdc1916e3ea201b442917273c33d729d2b1c0270785fd42005b2bd2',
    }
    predecessor = config_upgrade.get(files['config.py'])
    if predecessor:
        compatible = dict(files, **{'config.py': predecessor})
        for name, (after, before) in _REVIEW_PUBLICATION_UPGRADE.items():
            if name in compatible and hashlib.sha256(
                    (Path(__file__).parent/name).read_bytes().replace(b'\r\n', b'\n')).hexdigest() == after:
                compatible[name] = before
        if expected == digest(compatible):
            return True
    # Legacy checkouts also hashed CRLF working copies of these four files.
    from itertools import product
    previous = {
        'cli.py': ('2c66dd1233ad53670e1e16f485a7a518e7adc511c0b3ea51e24d265feb052721',
                   '06405dc61d90a81dcd48989a5aff1d7a9d7fd4e91d3c530f42cf4e30d6d81d1b'),
        'scan_persistence.py': ('a4677b8ecad386c7e1154ecc26569441d3c48dd82399b0765f88eb0f54e55446',
                                'dc0bb6767c5e450994aa7dbcadba1bbf72d9dfcd7ba328b255cd69973c08071d'),
        'report_package.py': ('028e7b9bf2d94c4a412b33a14781d3b13963677730655b020071d4925d04bd84',
                              '0f80028592321fa90a20bede8ba9c18ff3c159eae30f10c4b0dfb50ba33a3ed9'),
        'garbage_collection.py': ('5eaebb730d024e60fa60310092dfcd23e775c817f3f5e28655fb4192900db265',
                                  'ab1d558b0847b6dd2e8777bc00be774a453ee257ae3a659207defdf25e9b7122'),
    }
    package = Path(__file__).parent
    if any(hashlib.sha256((package/name).read_bytes().replace(b'\r\n', b'\n')).hexdigest() != hashed
           for name, (hashed, _) in _REVIEW_PUBLICATION_UPGRADE.items()):
        return False
    files = _engine_files()
    lf, crlf = {}, {}
    for name in files:
        raw = (package/name).read_bytes().replace(b'\r\n', b'\n')
        lf[name] = hashlib.sha256(raw).hexdigest()
        crlf[name] = hashlib.sha256(raw.replace(b'\n', b'\r\n')).hexdigest()
    for variant in (lf, crlf):
        variant['config.py'] = _config_engine_hash(variant['config.py'])
    for hashes in product(*previous.values()):
        prior = dict(zip(previous, hashes))
        if any(expected == digest({**variant, **prior}) for variant in (files, lf, crlf)):
            return True
    return False


def analysis_config(cfg):
    result = {k: v for k, v in cfg.items() if k != 'review'}
    result['analysis'] = {k: v for k, v in cfg.get('analysis', {}).items()
                          if k not in {'_workspace', 'output', 'output_dir'}}
    return result


def read_saved_json(path, *, canonical_accesses=False):
    """Read a complete saved object without an all-file Unicode allocation.

    Equal immutable strings are shared. For facts, complete read-only access
    entities can also share storage, as they do before serialization. Array
    order, duplicate entries, scalar types and every field remain unchanged.
    """
    from .scan_persistence import artifact, read
    if artifact(path) is not None:
        return read(path)
    from .json_rows import RecordDicts, RowReader
    strings = lru_cache(maxsize=131072)(lambda value: value)
    records = RecordDicts()
    access_rows, access_count = OrderedDict(), 0
    shared_ids = set()
    scalar_lists, scalar_list_bytes = OrderedDict(), 0
    coherence_rows = OrderedDict()
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
        nonlocal scalar_list_bytes
        if id(value) in shared_ids:
            return value
        if isinstance(value, str):
            return strings(value) if len(value) <= 1024 else value
        if isinstance(value, list):
            for index, item in enumerate(value):
                value[index] = share(item)
            if len(value) >= 8 and (all(type(item) is str for item in value)
                                   or all(type(item) is int for item in value)):
                import sys
                key = type(value[0]), tuple(value)
                previous = scalar_lists.get(key)
                if previous is not None:
                    scalar_lists.move_to_end(key)
                    return previous
                weight = sys.getsizeof(key[1]) + sys.getsizeof(value)
                scalar_lists[key] = value
                scalar_list_bytes += weight
                # Only the acceleration index is bounded. Evicted complete
                # lists remain in their original result locations.
                while scalar_list_bytes > 64*1024*1024 and scalar_lists:
                    expired, values = scalar_lists.popitem(last=False)
                    scalar_list_bytes -= sys.getsizeof(expired[1]) + sys.getsizeof(values)
        return value
    def object_hook(value):
        nonlocal access_count
        source = value
        keys = tuple(strings(key) for key in source)
        value = records(keys)
        for key, item in zip(keys, source.values()):
            value[key] = share(item)
        if isinstance(value.get('coherence_id'), str) and 'member_symbol_ids' in value:
            key = value['coherence_id'], keys
            bucket = coherence_rows.get(key, ())
            for previous in bucket:
                if identical(previous, value):
                    coherence_rows.move_to_end(key)
                    return previous
            if not bucket:
                coherence_rows[key] = bucket = []
            bucket.append(value)
            coherence_rows.move_to_end(key)
            while len(coherence_rows) > 200000:
                coherence_rows.popitem(last=False)
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
    from .shared_json import encoded_stream, read_stream
    result = {}
    with Path(path).open(encoding='utf-8-sig') as stream:
        if encoded_stream(stream):
            return read_stream(stream, object_hook, shared_ids=shared_ids, normalize=share)
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


def saved_report_digest(report, *, encoding='LEGACY_JSON_V1'):
    """Hash all static values without re-expanding shared evidence billions of times."""
    if encoding == 'ECRA_MERKLE_V1':
        from .shared_json import logical_digest
        return logical_digest(report)
    if encoding != 'LEGACY_JSON_V1':
        raise ValueError('不支持的完整证据摘要版本')
    sha = hashlib.sha256()
    for chunk in json.JSONEncoder(sort_keys=True, ensure_ascii=False).iterencode(report):
        sha.update(chunk.encode('utf-8'))
    return sha.hexdigest()


def clean_report(report):
    # Only these dictionaries are edited. Nested static evidence is read-only;
    # copying it would duplicate gigabytes before validating a saved report.
    result = dict(report)
    result['findings'] = [dict(finding) for finding in report['findings']]
    from .scan_persistence import RUNTIME_KEYS
    for key in RUNTIME_KEYS:
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
    from .review_archive import write_receipt
    queue = [set_review_state(dict(finding_id=f['finding_id'],
        static_classification=f.get('static_classification')), 'PENDING') for f in review_targets(report)]
    assert_review_integrity(report, queue)
    if initialize_queue:
        write_json(out/'review/queue.json', queue)
    else:
        assert_review_integrity(report, read_queue(out))
    write_receipt(out/'scan_state.json', dict(schema=1, project_root=str(root),
        config_file=relative(config_file, root), config_digest=digest(analysis_config(cfg)),
        engine_scope=ENGINE_SCOPE, engine_digest=engine_digest(), facts_sha256=file_digest(out/'facts.json'),
        manifest_sha256=file_digest(out/'input_manifest.json'),
        input_closure_sha256=file_digest(out/'input_closure.json') if (out/'input_closure.json').is_file() else None,
        report_digest=saved_report_digest(clean_report(report), encoding='ECRA_MERKLE_V1'),
        report_digest_encoding='ECRA_MERKLE_V1', fingerprint=report['fingerprint'],
        scan_mode='diff' if report.get('git_diff') else 'full', git_diff_pin=(report.get('git_diff') or {}).get('pin')))


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
    from .frozen_scan import replay_files
    with replay_files(capsule,root,cfg,config_path=Path(root)/state.get('config_file','')) as view:
        return _verify_saved_closure(root,out,cfg,state,manifest,config_file,capsule,file_view=view)


def _verify_saved_closure(root,out,cfg,state,manifest,config_file,capsule,*,file_view=None):
    if (state.get('git_diff_pin') or {}).get('schema') == 3:
        config_file = Path(state['git_diff_pin']['config_path'])
    import shutil
    import tempfile
    from .cli import dependency_results
    from .input_snapshot import file_record
    from .input_snapshot import runtime_environment
    if capsule.get('environment') != runtime_environment():
        raise ValueError('构建/Clang 运行环境已变化或旧检查点缺少环境绑定；请重新扫描，不能复用旧事实')
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
        if file_view is not None:
            fixed=sorted(relative(path,root) for path in file_view.select_files(selection['directory'],selection['pattern']))
            if fixed!=selection['files']:
                changes.append(dict(file=selection['directory'],reason='FROZEN_PARENT_INPUT_SET_CHANGED',
                    before=selection['files'],after=fixed))
    tool_root = Path(__file__).resolve().parent.parent
    env = os.environ.copy()
    env['PYTHONPATH'] = str(tool_root) + os.pathsep + env.get('PYTHONPATH', '')
    with tempfile.TemporaryDirectory(prefix='verify-inputs-', dir=out) as temp:
        work = Path(temp)/'workers'
        work.mkdir()
        try:
            frozen={} if file_view is None else dict(compiler_view={key:file_view.identity[key] for key in ('file','sha256')})
            for unit, inputs, signature in dependency_results(root, units, cfg, work, env, tool_root,**frozen):
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
        if file_view is not None:
            fixed=file_view.file_record(root/path)
            if fixed.get('status')!='OK' or fixed.get('sha256')!=expected:
                changes.append(dict(file=path,reason='FROZEN_INPUT_CHANGED_DURING_RESUME',before=expected,after=fixed))
    live_cfg, _ = load_config(root, config_file)
    from .git_diff import current_context
    _, live_cfg = current_context(root, live_cfg, state.get('git_diff_pin'))
    if state.get('scan_mode'):
        live_cfg['analysis']['git_diff']['enabled'] = state['scan_mode'] == 'diff'
    live_digest = digest(analysis_config(live_cfg))
    if live_digest != state['config_digest']:
        changes.append(dict(file=relative(config_file, root), reason='ANALYSIS_CONFIGURATION_CHANGED',
                            before=state['config_digest'], after=live_digest))
    current_engine = engine_digest()
    if not matches_static_engine(state['engine_digest'], current_engine):
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
        if state.get('git_diff_pin'):
            from .git_diff import assert_pin
            assert_pin(root, cfg, state['git_diff_pin'])
        if (file_digest(out/'input_manifest.json') != state['manifest_sha256']
                or file_digest(out/'facts.json') != state['facts_sha256']):
            raise ValueError('恢复发布期间事实或输入清单已变化；请重新运行 run')
        if state.get('input_closure_sha256') or (out/'diagnostics/source_changes.json').is_file():
            verify_saved_input_closure(root, out, cfg, state, read_json(out/'input_manifest.json'), config_file)
        else:
            # Legacy broad manifests retain their existing validation policy.
            live_cfg, _ = load_config(root, config_file)
            checked_scan(root, out, live_cfg, config_file, with_facts=False, _report_projection=True)
    except KeyboardInterrupt:
        raise
    except Exception as exc:
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


def checked_scan(root, out, cfg, config_file, *, with_facts=True, _report_projection=False):
    from .cli import file_hashes
    if not (out/'scan_state.json').is_file():
        raise ValueError('没有可恢复的扫描检查点；请先运行 run（旧版报告需要重新扫描一次）')
    state = read_json(out/'scan_state.json')
    required=('project_root','config_file','config_digest','engine_digest','facts_sha256','manifest_sha256','report_digest','fingerprint')
    if not isinstance(state,dict) or any(not isinstance(state.get(k),str) for k in required):
        raise ValueError('扫描检查点损坏；请重新运行 run')
    if (state.get('git_diff_pin') or {}).get('schema') == 3:
        config_file = Path(state['git_diff_pin']['config_path'])
    from .git_diff import current_context
    root, cfg = current_context(root, cfg, state.get('git_diff_pin'))
    if state.get('schema') != 1 or state.get('project_root') != str(root):
        raise ValueError('扫描检查点不属于当前工程；请重新运行 run')
    rescan = '请先执行 py -3.10 run_ecra.py --no-review 刷新静态扫描，再执行复核命令'
    if state.get('scan_mode'):
        cfg['analysis']['git_diff']['enabled'] = state['scan_mode'] == 'diff'
    if state.get('git_diff_pin'):
        from .git_diff import assert_pin
        assert_pin(root, cfg, state['git_diff_pin'])
    if state['config_digest'] != digest(analysis_config(cfg)):
        raise ValueError('分析配置已变化，不能复用旧调用链；' + rescan)
    if state.get('engine_scope') != ENGINE_SCOPE:
        # The old aggregate digest cannot establish which modules changed.
        # Refresh once rather than bless unknown old facts by replacing a hash.
        raise ValueError('旧扫描检查点使用全程序指纹，需一次性更新为静态分析指纹；' + rescan)
    if not matches_static_engine(state['engine_digest']):
        raise ValueError('静态分析实现已变化，不能复用旧调用链；' + rescan)
    if (state['facts_sha256'] != file_digest(out/'facts.json') or
            state['manifest_sha256'] != file_digest(out/'input_manifest.json')):
        raise ValueError('扫描事实或输入清单已变化/损坏；请重新运行 run')
    from .scan_persistence import is_canonical
    bounded=_report_projection and is_canonical(out)
    if bounded and with_facts:raise ValueError('状态投影不能用于恢复完整分析事实')
    if bounded:
        from .native_consumers import status_report,clean_report_digest
        report=status_report(out)
    else:
        report = read_saved_json(out/'reports/global_static_concurrency.json')
    if not isinstance(report,dict) or not isinstance(report.get('findings'),list):
        raise ValueError('静态报告格式损坏；请重新运行 run')
    if bounded:
        from .scan_store import EvidenceProvider
        from .scan_persistence import validate_review_binding
        provider = EvidenceProvider(out/'scan.db')
        validate_review_binding(out, provider)
        fingerprint = provider.node(provider.resolve('report', ['fingerprint'])).get('value')
    else:
        fingerprint = report.get('fingerprint')
    if state['fingerprint'] != fingerprint:
        raise ValueError('检查点与静态报告的扫描指纹不一致；请重新运行 run')
    if state.get('report_digest_encoding') != 'ECRA_MERKLE_V1':
        raise ValueError('旧扫描缺少完整共享证据摘要版本，请重新运行 run')
    actual_digest=(clean_report_digest(out/'scan.db',work=out/'diagnostics') if bounded else
                   saved_report_digest(clean_report(report), encoding=state['report_digest_encoding']))
    if actual_digest != state['report_digest']:
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
    from .workspace import context
    workspace = context(root, cfg['analysis'])
    workspace.bind(cfg['analysis'])
    pointer = Path(workspace.project_workspace)/'latest-scan.json'
    if pointer.is_file():
        saved = read_json(pointer)
        from .report_package import IDENTITY
        if saved.get('project_id') != workspace.project_id or not IDENTITY.fullmatch(saved.get('scan_id', '')):
            raise ValueError('当前扫描指针身份不符')
        from dataclasses import replace
        result = Path(workspace.workspace_root)/'scans'/saved['scan_id']
        replace(workspace, results_root=str(result)).bind(cfg['analysis'])
        return result
    return Path(workspace.results_root)


def read_queue(out):
    from .scan_persistence import runtime
    saved = runtime(out)
    if saved:
        return saved['reviews']
    try:
        rows=read_json(out/'review/queue.json')
        if not isinstance(rows,list):
            return []
        return [r for r in rows if isinstance(r,dict) and isinstance(r.get('finding_id'),str)]
    except (OSError,ValueError):
        if (out/'scan.db').is_file():
            raise
        # Per-item caches can still be recovered by review_all. A broken queue
        # never means that the corresponding findings have been reviewed.
        return []


def status(root, config_path=None):
    from .git_diff import selected_findings
    cfg, config_file = load_config(root, config_path)
    out = output_path(root, cfg)
    from .workspace import lock_path
    info = dict(project=str(root), output=str(out), scan_lock=lock_path(root, cfg['analysis']).exists())
    from .scan_persistence import exists, is_canonical
    if not exists(out/'reports/global_static_concurrency.json'):
        info.update(state='NOT_SCANNED', next_action='运行 run，生成变量清单和复核队列')
        legacy = Path(root)/'.ecra'
        if legacy != out and legacy.is_dir():
            from .workspace import legacy_files
            try:
                legacy_files(root, legacy)
                info.update(state='LEGACY_HISTORY_FOUND', legacy_history=str(legacy),
                    next_action='检测到已验证归属的旧版扫描历史；运行 run 复制迁移并刷新当前引擎结果，然后继续 report/review。原数据保留。')
            except (OSError, ValueError, KeyError, TypeError) as exc:
                info['legacy_directory'] = dict(path=str(legacy), owner_verified=False, diagnostic=str(exc))
    else:
        if is_canonical(out):
            from .workspace import formal_workspace
            try:
                formal_workspace(root,cfg['analysis'])
            except ValueError as exc:
                # SQLite readers may need WAL shared-memory sidecars. Never
                # even open runtime/queue files in a retired firmware/tool
                # output root; the existing migration workflow copies them.
                info.update(state='LEGACY_READ_ONLY',resumable=False,review_complete=False,
                            scan_database=str(out/'scan.db'),next_action=str(exc))
                return info
        if is_canonical(out):
            from .native_consumers import status_report
            report=status_report(out)
        else:
            report = read_saved_json(out/'reports/global_static_concurrency.json')
        queue = read_queue(out)
        records = review_records(dict(findings=selected_findings(report)), queue)
        from .review_integrity import review_integrity
        integrity = review_integrity(report, queue)
        info.update(state=report.get('run_status', 'SCANNED'), analysis_status=report['analysis_status'],
                    variables=report['coverage'].get('variables_total'), findings=len(records),
                    unresolved=sum(category(r)=='unresolved' for r in records),
                    review_integrity=integrity, review_complete=integrity['all_done'],
                    **(dict(scan_database=str(out/'scan.db'), viewer_command='ecra ui') if is_canonical(out) else
                       dict(inventory_html=str(out/'index.html'), review_html=str(out/REVIEW_PAGE))))
        if report.get('git_diff'):
            info['variables'] = report.get('risk_summary', {}).get('total_variables', len(report['git_diff']['selected_symbol_ids']))
        if info['scan_lock']:
            info.update(resumable=False, next_action='存在运行锁：等待扫描/复核结束；若进程已退出，确认后移除过期 scan.lock。当前数量来自已保存的结果。')
            return info
        try:
            from .workspace import context
            ws = context(root, cfg['analysis'])
            relocated = _archived_checkpoint(Path(ws.workspace_root), out, ws)
            if relocated:
                state = relocated[0]
            else:
                _, _, state = checked_scan(root, out, cfg, config_file, with_facts=False, _report_projection=True)
                from .git_diff import current_context
                root, cfg = current_context(root, cfg, state.get('git_diff_pin'))
            # A DONE label in queue.json is not enough to claim completion.
            # Check the immutable prompt, transcript, answer and cited source
            # before reporting a review as finished, without changing files.
            receipt_errors = []
            verified_queue = copy.deepcopy(queue)
            from .review_archive import verify_committed_review
            from .review_integrity import review_targets
            from .review_sources import ArchivedSources, source_scope
            from .scan_store import EvidenceProvider
            archived = ArchivedSources(root, EvidenceProvider(out/'scan.db')) if is_canonical(out) else None
            expected = {f['finding_id']: f for f in review_targets(report)}
            for row in verified_queue:
                if row.get('state') != 'DONE':
                    continue
                try:
                    fid = row['finding_id']
                    receipt = read_json(out/'review'/(fid+'.result.json'))
                    with source_scope(archived):
                        verify_committed_review(root, out/'review', row, expected[fid], state['fingerprint'], receipt)
                except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
                    receipt_errors.append(dict(finding_id=row['finding_id'], error=str(exc)))
                    set_review_state(row, 'TECH_FAILED')
                    row.update(error=str(exc))
                    row.pop('answer', None)
            if receipt_errors:
                integrity = review_integrity(report, verified_queue)
                records = review_records(dict(findings=selected_findings(report)), verified_queue)
                info.update(review_integrity=integrity, review_complete=False,
                            unresolved=sum(category(r) == 'unresolved' for r in records),
                            review_receipt_errors=receipt_errors)
            disabled = not cfg.get('review', {}).get('enabled', True)
            if receipt_errors:
                action = f"{len(receipt_errors)} 项复核收据未通过校验；运行 review-resume 重试对应结果。"
            elif integrity['all_done']:
                if info['unresolved']:
                    action = f"全部模型复核已有答复，但 {info['unresolved']} 项仍缺证据；查看逐项复核并补充上下文。"
                elif report['analysis_status'] == 'INCOMPLETE':
                    action = '逐项复核已完成；静态分析仍有覆盖缺口，请查看报告的覆盖证据与未知事实。'
                else:
                    action = '逐项复核已完成；查看报告并核对固件构建配置。'
            elif disabled:
                action = ('当前未启用模型：可在 ECRA Studio 按归档证据人工排查；运行原命令重新扫描。'
                          if is_canonical(out) else
                          '当前未启用模型：可按 HTML 人工排查；运行原命令重新扫描；运行 report 仅刷新结果。')
            else:
                action = '运行 review-resume 继续剩余项；review 重跑全部疑似/未知；review-failed 只重跑技术失败'
            info.update(resumable=True, review_enabled=not disabled,
                        next_action=action)
        except (OSError, ValueError, KeyError) as exc:
            info.update(resumable=False, review_complete=False, next_action=str(exc))
    return info


def pause_saved_review(out, facts, report, state):
    from .scan_persistence import append_runtime, is_canonical
    report['run_status'] = state
    if is_canonical(out):
        append_runtime(out, dict(run_status=state), [])
    else:
        generate(out, facts, report, read_queue(out))
    manifest_path = out/'manifest.json'
    if manifest_path.is_file():
        manifest = read_json(manifest_path)
        manifest['run_state'] = state
        write_json(manifest_path, manifest)
    write_json(out/'resume.json', dict(command='review-resume', state=state,
                                     exit_code=130 if state=='INTERRUPTED' else 3,
                                     finished=datetime.now(timezone.utc).isoformat()))


def invalidate_saved_reviews(out, report, fingerprint, reason):
    from .review_integrity import mark_review_stale, review_targets
    from .scan_persistence import is_canonical, append_runtime
    rows = {row['finding_id']: row for row in read_queue(out)}
    reviews = []
    for finding in review_targets(report):
        fid = finding['finding_id']
        row = rows.get(fid, dict(finding_id=fid, scan_fingerprint=fingerprint,
                                static_classification=finding.get('static_classification')))
        reviews.append(mark_review_stale(out/'review', row, reason))
    report.update(run_status='INCOMPLETE', stale_reason=str(reason))
    if is_canonical(out):
        append_runtime(out, dict(run_status=report['run_status'], stale_reason=str(reason)), reviews)
    else:
        write_json(out/'review/queue.json', reviews)
    return reviews


def saved_run(root, config_path=None, render_only=False, failed_only=False, *, resume=False, resume_scope=None,
              _out=None,_budget_owned=False):
    from contextlib import ExitStack
    from .scan_persistence import is_canonical
    from .storage_activity import DataActivity,review_data_root
    cfg,_=load_config(root,config_path)
    out=_out if _out is not None else output_path(root,cfg)
    from .workspace import context, formal_workspace, managed_path
    out = managed_path(out)
    native = is_canonical(out)
    if native:
        formal_workspace(root, cfg['analysis'])
    data=review_data_root(Path(out)/'reviews.db') if native else None
    with ExitStack() as activities:
        if data:
            activities.enter_context(DataActivity(data))
            if not _budget_owned:activities.enter_context(DataActivity(data,exclusive=True,purpose='scan-budget'))
        from .scan_persistence import project_scan_lock
        context(root, cfg['analysis']).initialize()
        with project_scan_lock(root, cfg['analysis']):
            return _saved_run(root, config_path, render_only, failed_only, resume=resume, resume_scope=resume_scope, _out=out)


def _archived_checkpoint(data, out, workspace):
    """Use the sealed static proof when its live storage paths are obsolete."""
    from .data_transfer import retired_roots
    roots = retired_roots(data)
    state_path = out/'scan_state.json'
    if not all(path.is_file() for path in (state_path, out/'manifest.json', out/'scan.db')):
        return None
    state = read_json(state_path)
    previous_engine = state.get('engine_digest') in _PRE_WORKSPACE_ENGINES
    if not roots and not previous_engine:
        return None
    from .scan_store import EvidenceProvider
    from .report_package import validate_objects, sha256
    from .scan_persistence import validate_review_binding
    provider = EvidenceProvider(out/'scan.db')
    try:
        origin = Path(provider.load('report', ['workspace', 'results_root']))
    except KeyError:
        return None
    if not ((origin == out and previous_engine) or any(origin == old/'scans'/out.name for old in roots)):
        return None
    manifest = read_json(out/'manifest.json')
    binding = provider.validate(deep=True)
    if (manifest.get('format') != 'ECRA_LOCAL_SCAN' or manifest.get('state') != 'STATIC_VALIDATED'
            or any(manifest.get(key) != binding[key] for key in ('scan_id', 'project_id', 'facts_hash', 'report_hash'))
            or binding['project_id'] != workspace.project_id or binding['scan_id'] != out.name
            or sha256(out/'scan.db') != manifest.get('scan_sha256')):
        raise ValueError('搬迁后的静态归档身份或内容校验失败')
    validate_objects(out, manifest)
    validate_review_binding(out, provider)
    index = read_json(out/'evidence'/manifest['audit_index'])
    state_hash = sha256(state_path)
    if index['files']['scan_state.json']['sha256'] != state_hash:
        raise ValueError('搬迁后的复核检查点与发布清单不一致')
    if state['fingerprint'] != provider.load('report', ['fingerprint']):
        raise ValueError('搬迁后的复核检查点与扫描指纹不一致')
    return state, state_hash, manifest['scan_sha256']


def _saved_run(root, config_path=None, render_only=False, failed_only=False, *, resume=False, resume_scope=None, _out=None):
    from .git_diff import selected_findings
    cfg, config_file = load_config(root, config_path)
    out = output_path(root, cfg)
    if _out is not None:
        from dataclasses import replace
        from .workspace import context, no_links
        out = no_links(_out)
        replace(context(root,cfg['analysis']),results_root=str(out)).bind(cfg['analysis'])
    if not out.is_dir():
        if (Path(root)/'.ecra').is_dir() and Path(root)/'.ecra' != out:
            raise ValueError(f'旧版数据目录存在: {Path(root)/".ecra"}；请先运行 run 验证归属、复制迁移并刷新结果，再执行 report/review')
        raise ValueError('还没有扫描结果；请先运行 run')
    from .workspace import context
    workspace = context(root, cfg['analysis']).initialize()
    source_reader=None;source_scope=None;source_token=None;source_entered=False
    from .scan_persistence import is_canonical
    runtime_only=is_canonical(out)
    relocated = _archived_checkpoint(Path(workspace.workspace_root), out, workspace) if runtime_only else None
    from .scan_diagnostics import ACTIVE
    review_diagnostics=ACTIVE.get()
    if getattr(review_diagnostics,'consumer',None)!='REVIEW':review_diagnostics=None
    def review_stage(name):
        if review_diagnostics:review_diagnostics.stage(name)
    def refresh(facts,report,reviews):
        if runtime_only:return generate(out,facts,report,reviews,_runtime_only=True)
        return generate(out,facts,report,reviews)
    try:
        try:
            if relocated:
                from .native_consumers import runtime_inputs
                facts, report = runtime_inputs(out)
                state = relocated[0]
                print(f'使用已校验的历史扫描归档继续复核: {out}', flush=True)
            elif runtime_only and not render_only and (out/'scan_state.json').is_file():
                from .studio.opencode_recovery import recover_review_tree
                state = read_json(out/'scan_state.json')
                if isinstance(state, dict):
                    recover_review_tree(workspace, state.get('git_diff_pin'))
            if not relocated:
                facts, report, state = checked_scan(root,out,cfg,config_file,with_facts=not runtime_only,
                    _report_projection=runtime_only)
                if runtime_only:
                    from .native_consumers import runtime_inputs
                    facts,report=runtime_inputs(out)
                from .git_diff import current_context
                root, cfg = current_context(root, cfg, state.get('git_diff_pin'))
            if state.get('scan_mode'):
                cfg['analysis']['git_diff']['enabled'] = state['scan_mode'] == 'diff'
            if not relocated:
                from .frozen_scan import saved_reader
                from .input_snapshot import SOURCE_READS
                source_scope=saved_reader(root,out,cfg,state)
                source_reader=source_scope.__enter__()
                source_entered=True
                if source_reader is not None:source_token=SOURCE_READS.set(source_reader)
        except ValueError as exc:
            if '源码/头文件/编译数据库已变化' not in str(exc):
                raise
            # Retain history while invalidating verdicts bound to changed source.
            if runtime_only:
                from .native_consumers import runtime_inputs
                facts,report=runtime_inputs(out)
            else:
                facts = read_saved_json(out/'facts.json', canonical_accesses=True)
                report = clean_report(read_saved_json(out/'reports/global_static_concurrency.json'))
            reviews = invalidate_saved_reviews(out, report, read_json(out/'scan_state.json')['fingerprint'], exc)
            refresh(facts,report,reviews)
            write_json(out/'review/queue.json', reviews)
            write_json(out/'resume.json', dict(command='run', state='INCOMPLETE', exit_code=2,
                review_integrity=report['review_integrity'], finished=datetime.now(timezone.utc).isoformat()))
            return 2
        queue_file = out/'review/queue.json'
        review_stage('核对历史复核收据与队列（剩余量未知）')
        mode = 'report' if render_only else 'review-failed' if failed_only else 'review-resume' if resume else 'review'
        if render_only:
            from .review_archive import reconcile_reviews
            from .review_integrity import review_targets
            from .review_sources import ArchivedSources, source_scope as archived_scope
            from .scan_store import EvidenceProvider
            archived = ArchivedSources(root, EvidenceProvider(out/'scan.db')) if runtime_only else None
            with archived_scope(archived):
                reviews = reconcile_reviews(root, out, review_targets(report), read_queue(out), state['fingerprint'])
        else:
            cfg['review']['enabled'] = True
            try:
                from contextlib import nullcontext
                with review_diagnostics.cooperative_extraction_stop() if review_diagnostics else nullcontext():
                    from .config import review_material_path
                    reviews = review_all(root, out, cfg, facts, report, state['fingerprint'],
                                         review_context_path=review_material_path(config_file, 'review_context.md'),
                                         case_library_path=review_material_path(config_file, 'concurrency_cases.md'),
                                         mode=mode, resume_scope=resume_scope)
            except KeyboardInterrupt:
                pause_saved_review(out, facts, report, 'INTERRUPTED')
                print('复核已中断；使用 review-resume 继续剩余项。', flush=True)
                return 130
            except Exception:
                pause_saved_review(out, facts, report, 'FAILED')
                raise
        inputs_current = True
        review_stage('复核后完整输入重验与结果保存（剩余量未知）')
        try:
            if relocated:
                if (file_digest(out/'scan_state.json'), file_digest(out/'scan.db')) != relocated[1:]:
                    raise ValueError('复核期间搬迁归档的静态证据已变化')
            else:
                checked_scan(root, out, cfg, config_file, with_facts=False, _report_projection=True)
        except KeyboardInterrupt:
            pause_saved_review(out, facts, report, 'INTERRUPTED')
            raise
        except (OSError, ValueError, KeyError):
            inputs_current = False
            reviews = invalidate_saved_reviews(out, report, state['fingerprint'], '恢复期间输入发生变化；请重新扫描。')
            report['analysis_status']='INCOMPLETE'
            report['limitations'].append('恢复期间输入发生变化；请重新扫描。')
        records = review_records(dict(findings=selected_findings(report)), reviews)
        from .review_integrity import review_integrity
        integrity = review_integrity(report, reviews, require_terminal=True)
        report['run_status'] = 'INCOMPLETE' if (report['analysis_status']=='INCOMPLETE' or
            not integrity['complete'] or any(category(r) in {'unresolved', 'likely'} for r in records)) else 'REVIEW_COMPLETE'
        mapping={r['finding_id']:r for r in records}
        for f in selected_findings(report):
            r=mapping[f['finding_id']]
            f['review_state']=r['state']
            f['review_status']=r.get('status')
            f['review_result']=r
            if r['state']=='DONE':
                f['status']=r['status']; f['review']=r['answer']
        refresh(facts,report,reviews)
        write_json(queue_file, reviews)
        if inputs_current and not relocated:
            try:
                verify_saved_publication(root, out, cfg, state, config_file)
            except KeyboardInterrupt:
                pause_saved_review(out, facts, report, 'INTERRUPTED')
                raise
            except (OSError, ValueError, KeyError) as exc:
                invalidate_saved_reviews(out, report, state['fingerprint'], exc)
                raise
        code=2 if report['run_status']=='INCOMPLETE' else (1 if selected_findings(report) else 0)
        write_json(out/'resume.json', dict(command=mode, state=report['run_status'],
                                         finished=datetime.now(timezone.utc).isoformat(), exit_code=code,
                                         review_integrity=integrity))
        from .scan_persistence import is_canonical, archive_audit
        if is_canonical(out):
            manifest_path = out/'manifest.json'
            if manifest_path.is_file():
                manifest = read_json(manifest_path)
                manifest.update(archive_audit(out), run_state=report['run_status'])
                write_json(manifest_path, manifest)
            print(f"{report['run_status']}：{out/'scan.db'}；请在 ECRA Studio 查看。", flush=True)
        else:
            print(f"{report['run_status']}：{out/'index.html'}\nOpenCode：{out/REVIEW_PAGE}", flush=True)
        return code
    finally:
        if source_token is not None:
            from .input_snapshot import SOURCE_READS
            SOURCE_READS.reset(source_token)
        if source_entered:
            import sys
            source_scope.__exit__(*sys.exc_info())
