"""Durable files and content-addressed evidence for individual AI receipts."""
from contextlib import closing, nullcontext
from functools import lru_cache
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import sqlite3
from tempfile import NamedTemporaryFile
import time
import uuid


def _sync_directory(path):
    if os.name != 'nt':
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def durable_replace(source, target):
    if os.name != 'nt':
        source.replace(target)
        _sync_directory(target.parent)
        return
    import ctypes
    from ctypes import wintypes
    move = ctypes.WinDLL('kernel32', use_last_error=True).MoveFileExW
    move.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
    move.restype = wintypes.BOOL
    for attempt in range(5):
        if move(str(source), str(target), 0x1 | 0x8):  # REPLACE_EXISTING | WRITE_THROUGH
            return
        error = ctypes.get_last_error()
        if error not in {5, 32, 33} or attempt == 4:
            raise ctypes.WinError(error)
        time.sleep(.05 * 2**attempt)


def write_receipt(path, row, *, compact=False):
    with NamedTemporaryFile(mode='w', encoding='utf-8', newline='', dir=path.parent, suffix='.pending', delete=False) as stream:
        temp = Path(stream.name)
        try:
            json.dump(row, stream, ensure_ascii=False, indent=None if compact else 2,
                      separators=(',', ':') if compact else None)
            stream.flush()
            os.fsync(stream.fileno())
            stream.close()
            durable_replace(temp, path)
        finally:
            stream.close()
            temp.unlink(missing_ok=True)


@lru_cache(maxsize=4)
def _writer_birth(pid):
    from .lock_owner import process_identity
    return process_identity(pid) or 0


def _same_prefix(partial, original):
    if partial.stat().st_size > original.stat().st_size:
        return False
    with partial.open('rb') as left, original.open('rb') as right:
        for chunk in iter(lambda: left.read(1024 * 1024), b''):
            if right.read(len(chunk)) != chunk:
                return False
    return True


def _new_stage(folder, hashed):
    pid = os.getpid()
    return folder/f'{hashed}.{pid}.{_writer_birth(pid)}.{uuid.uuid4().hex}.part'


def _abandoned_digest(path):
    from .lock_owner import abandoned
    match = re.fullmatch(r'([0-9a-f]{64})\.([0-9]+)\.([0-9]+)\.[0-9a-f]{32}\.part', path.name)
    if match and abandoned(dict(pid=int(match[2]), creation_filetime=int(match[3]) or None)):
        return match[1]


def recover_object_copies(out, expected=None, *, progress=print):
    """Retire interrupted copy buffers only against a verified immutable original."""
    from .report_package import sha256
    from .workspace import no_links
    stage = no_links(out/'.ecra-object-copies')
    if not stage.is_dir():
        return
    candidates = stage.glob(expected+'.*.part') if expected else stage.iterdir()
    for path in candidates:
        hashed = _abandoned_digest(path)
        if hashed is None:
            continue
        try:
            path = no_links(path)
            target = no_links(out/'evidence'/hashed)
            if not target.is_file():
                # A caller with an expected digest can finish the interrupted
                # copy without declaring any SQLite event committed.
                if expected == hashed and sha256(path) == expected:
                    durable_replace(path, target)
                continue
            if sha256(target) == hashed and _same_prefix(path, target):
                path.unlink()
        except (OSError, ValueError) as exc:
            progress(f'归档复制暂存保留待重试 {path.name}：{exc}')


def archive_object(out, source, expected=None):
    from .report_package import sha256
    raw = isinstance(source, bytes)
    hashed = expected or (hashlib.sha256(source).hexdigest() if raw else sha256(source))
    if not isinstance(hashed, str) or not re.fullmatch('[0-9a-f]{64}', hashed):
        raise ValueError('复核对象摘要无效')
    from .workspace import no_links
    objects = no_links(out/'evidence')
    if not objects.is_dir():
        objects.mkdir(exist_ok=True)
        _sync_directory(out)
    target = no_links(objects/hashed)
    if not target.is_file():
        stage = no_links(out/'.ecra-object-copies')
        stage.mkdir(exist_ok=True)
        recover_object_copies(out, hashed)
        if not target.is_file():
            temp = _new_stage(stage, hashed)
            try:
                with temp.open('xb') as stream:
                    if raw:
                        stream.write(source)
                    else:
                        with source.open('rb') as original:
                            shutil.copyfileobj(original, stream)
                    stream.flush()
                    os.fsync(stream.fileno())
                if sha256(temp) != hashed:
                    raise ValueError('写入的归档原件与预期摘要不一致：'+hashed)
                durable_replace(temp, target)
                recover_object_copies(out, hashed)
            finally:
                temp.unlink(missing_ok=True)
    if sha256(target) != hashed:
        raise ValueError('内容寻址审计对象损坏：'+str(target))
    return dict(sha256=hashed, size=target.stat().st_size)


def _intent_stage(out):
    from .workspace import no_links
    return no_links(out/'.ecra-receipt-writes')


def _write_intent(out, path, row):
    from .scan_persistence import _encode
    hashed, raw = _encode(row)
    stage = _intent_stage(out)
    if not stage.is_dir():
        stage.mkdir(exist_ok=True)
        _sync_directory(out)
    temp = _new_stage(stage, hashed)
    with temp.open('xb') as stream:
        try:
            stream.write(raw.encode())
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            stream.close()
            temp.unlink(missing_ok=True)
            raise
    # A failed rename leaves a complete, identifiable intent for recovery.
    durable_replace(temp, path)


def _recover_intents(out, conn, watermark, progress):
    from .report_package import sha256
    from .scan_persistence import review_head, review_request
    from .workspace import no_links
    stage = _intent_stage(out)
    if not stage.is_dir():
        return
    for item in stage.iterdir():
        hashed = _abandoned_digest(item)
        if hashed is None:
            continue
        try:
            item = no_links(item)
            original = local_name(out/'evidence', hashed)
            if sha256(item) != hashed:
                if original.is_file() and sha256(original) == hashed and _same_prefix(item, original):
                    item.unlink()
                continue  # Otherwise this is an incomplete pre-commit result.
            row = json.loads(item.read_bytes())
            fid = row['finding_id']
            target = local_name(out/'review', fid+'.result.json')
            if target.is_file():
                if sha256(target) == hashed or (original.is_file() and sha256(original) == hashed):
                    item.unlink()
                continue
            head = review_head(conn, fid, watermark)
            if (head and head[2] in {'PENDING', 'TECH_FAILED'} and head[0] == row.get('review_base_sequence')
                    and review_request(conn, fid, head[0]) == row.get('review_request')):
                # Normal receipt reconciliation verifies all originals before commit.
                durable_replace(item, target)
            elif original.is_file() and sha256(original) == hashed:
                item.unlink()
        except (OSError, ValueError, TypeError, KeyError) as exc:
            progress(f'复核收据暂存保留待恢复 {item.name}：{exc}')


def archive_receipt(out, path, row):
    from .scan_persistence import _encode
    # The complete replay intent is durable before creating the first object.
    _write_intent(out, path, row)
    archive_review_files(out, row)
    archive_object(out, path, _encode(row)[0])


def repair_orphan_receipt(out, cache, row):
    from .scan_persistence import _encode
    expected, _ = _encode(row)
    from .report_package import sha256
    if sha256(cache) != expected:
        raise ValueError('待恢复复核收据不是原始完整写入')
    archive_review_files(out, row)
    archive_object(out, cache, expected)


def local_name(folder, name):
    from .workspace import no_links
    if (not isinstance(name, str) or not name or Path(name).name != name
            or any(char in name for char in '/\\:') or name in {'.', '..'}
            or name.endswith(('.', ' ')) or Path(name).is_reserved()):
        raise ValueError('复核原件名称无效')
    return no_links(folder/name)


def audit_originals(out, name):
    """Resolve a legacy logical name only through authenticated manifest roots."""
    from .report_package import sha256
    manifest_path = out/'manifest.json'
    if not manifest_path.is_file():
        return
    manifest = json.loads(manifest_path.read_bytes())
    indices = list(manifest.get('audit_indices', []))
    if manifest.get('audit_index'):
        indices.append(manifest['audit_index'])
    for hashed in dict.fromkeys(indices):
        if not re.fullmatch('[0-9a-f]{64}', hashed):
            raise ValueError('历史审计索引身份无效')
        index = local_name(out/'evidence', hashed)
        if sha256(index) != hashed:
            raise ValueError('历史审计索引摘要损坏')
        record = json.loads(index.read_bytes())['files'].get('review/'+name)
        if record:
            yield record


def review_original(folder, files, name, expected):
    """Read an issued receipt's immutable object, or an unarchived input."""
    from .report_package import sha256
    path = local_name(folder, name)
    if not isinstance(expected, str) or not re.fullmatch('[0-9a-f]{64}', expected):
        raise ValueError('复核原件摘要无效')
    if name not in files and not path.exists():
        files = {name: entry for entry in audit_originals(folder.parent, name) if entry['sha256'] == expected}
    if name in files:
        entry = files[name]
        if entry['sha256'] != expected:
            raise ValueError('复核原件与归档清单不一致：'+name)
        path = local_name(folder.parent/'evidence', expected)
        if path.stat().st_size != entry['size']:
            raise ValueError('复核归档原件长度不符：'+name)
    if not path.is_file() or sha256(path) != expected:
        raise ValueError('OpenCode 日志/证据包校验失败：'+name)
    return path


def committed_receipt(folder, row):
    from .common import read_json
    from .scan_persistence import _encode
    if 'archived_files' in row and 'review_base_sequence' in row:
        hashed, _ = _encode(row)
        path = local_name(folder.parent/'evidence', hashed)
        from .report_package import sha256
        if sha256(path) != hashed:
            raise ValueError('已提交的单变量结果归档损坏')
    else:
        name = row['finding_id']+'.result.json'
        path = local_name(folder, name)
        if not path.exists():
            for entry in audit_originals(folder.parent, name):
                original = review_original(folder, {name: entry}, name, entry['sha256'])
                saved = read_json(original)
                if saved == row:
                    return saved
    return read_json(path)


def _originals(row):
    attempts = row.get('attempts', [])[row.get('attempt_start', 0):]
    for record in [row, *attempts, row.get('execution') or {}]:
        for key in ('stdout', 'stderr', 'prompt', 'packet'):
            name, hashed = record.get(key+'_file'), record.get(key+'_sha256')
            if name and hashed:
                yield name, hashed
    yield from row.get('interrupted_files', {}).items()
    for key in ('language_correction', 'summary_correction'):
        if row.get(key):
            yield row[key]['source_stdout_file'], row[key]['source_stdout_sha256']


def interrupted_files(out, conn, issued, fingerprint, progress):
    """Claim only closed producer journals bound to a real dispatch in this scan."""
    from .lock_owner import abandoned
    from .report_package import sha256
    from .workspace import no_links
    folder = out/'review'
    retired = {}
    for path in folder.glob('*.execution.json'):
        try:
            path = no_links(path)
            raw = path.read_bytes()
            journal = json.loads(raw)
            owner = journal.get('work_owner') or {}
            fid = journal.get('finding_id')
            if (fid not in issued or journal.get('scan_fingerprint') != fingerprint
                    or type(owner.get('sequence')) is not int or owner['sequence'] >= issued[fid]
                    or not (owner.get('closed') is True or abandoned(owner))):
                continue
            event = conn.execute("SELECT hash,payload FROM ai_events WHERE finding_id=? AND sequence=? AND state='PENDING'",
                                 (fid, owner['sequence'])).fetchone()
            if not event or hashlib.sha256(event[1].encode()).hexdigest() != event[0]:
                continue
            request = json.loads(event[1]).get('review_request')
            if not request or request != owner.get('request'):
                continue
            stem = path.name.removesuffix('.execution.json')
            if (not re.fullmatch(re.escape(fid)+r'\.\d{8}T\d{12}-[0-9a-f]{8}', stem)
                    or owner.get('packet') != stem+'.input.json' or owner.get('prompt') != stem+'.prompt.txt'):
                continue
            allowed = re.compile(re.escape(stem)+r'(?:\.attempt[0-9]+\.[A-Z_]+)?\.(?:input\.json|failed-input\.json|prompt\.txt|jsonl|stderr\.txt|stdout\.txt)')
            files = {path.name: hashlib.sha256(raw).hexdigest()}
            records = [dict(packet_file=owner['packet'], prompt_file=owner['prompt']), journal,
                       *journal.get('attempts', [])[journal.get('attempt_start', 0):]]
            for record in records:
                for field in ('packet','prompt','stdout','stderr'):
                    name = record.get(field+'_file')
                    if not name or not allowed.fullmatch(name):
                        continue
                    source = local_name(folder, name)
                    if source.is_file():
                        hashed = sha256(source)
                        if record.get(field+'_sha256', hashed) != hashed:
                            raise ValueError('中断调用的文件摘要已改变：'+name)
                        files[name] = hashed
            retired.setdefault(fid, {}).update(files)
        except (ValueError, OSError, TypeError, AttributeError, KeyError) as exc:
            progress(f'中断调用保留现场 {path.name}：{exc}')
    return retired


def review_inventory(out, row):
    folder = out/'review'
    existing = row.get('archived_files', {})
    files = {}
    for name, hashed in _originals(row):
        if name in files:
            if files[name]['sha256'] != hashed:
                raise ValueError('同名复核原件摘要冲突：'+name)
            continue
        path = review_original(folder, existing, name, hashed)
        files[name] = dict(sha256=hashed, size=path.stat().st_size)
    return files


def archive_review_files(out, row):
    originals = dict(_originals(row))
    for name, entry in row['archived_files'].items():
        hashed = entry['sha256']
        if name in originals and originals[name] != hashed:
            raise ValueError('复核归档摘要不一致：'+name)
        target = local_name(out/'evidence', hashed)
        if not target.exists():
            folder = out/'review'
            if name not in originals:
                if re.fullmatch(r'[0-9a-f]{64}(?:\.index)?\.md', name):
                    folder = folder/'case-library'
                elif name not in ('project-evidence.json', row['finding_id']+'.input.json', row['finding_id']+'.prompt.txt'):
                    raise ValueError('未知的共享复核原件：'+name)
            path = local_name(folder, name)
            if archive_object(out, path, hashed) != entry:
                raise ValueError('复核归档长度不一致：'+name)
        else:
            review_original(out/'review', {name: entry}, name, hashed)


class DamagedArchive(ValueError):
    """A work copy is the last verified copy of a committed original."""


def duplicate_files(out, row, *, aliases=False, relocated=None):
    """Only names issued for this finding and bytes backed by its committed event."""
    from .report_package import sha256
    from .scan_persistence import _encode
    folder = out/'review'
    fid = row['finding_id']
    files = row['archived_files']
    relocated = relocated or {}
    # Bind the basename to the producer's full per-run identity, including UUID.
    prefix = re.escape(fid) + r'\.\d{8}T\d{12}-[0-9a-f]{8}'
    issued = re.compile(prefix + r'(?:\.attempt[0-9]+\.[A-Z_]+)?\.(?:input\.json|failed-input\.json|prompt\.txt|jsonl|stderr\.txt|stdout\.txt)')
    names = {name: hashed for name, hashed in _originals(row)
             if issued.fullmatch(name) and files.get(name, {}).get('sha256') == hashed}
    for name, hashed in row.get('interrupted_files', {}).items():
        if re.fullmatch(prefix+r'\.execution\.json', name) and files.get(name, {}).get('sha256') == hashed:
            names[name] = hashed
    for suffix in ('.input.json', '.prompt.txt'):
        name = fid+suffix
        if name in files:
            names[name] = files[name]['sha256']  # A previous explicit manual export.
    if aliases:
        for key, suffix in [('packet', '.input.json'), ('prompt', '.prompt.txt')]:
            if row.get(key+'_file') in names:
                names.setdefault(fid+suffix, names[row[key+'_file']])
    receipt_hash, _ = _encode(row)
    names[fid+'.result.json'] = receipt_hash
    for name, hashed in names.items():
        path = local_name(folder, name)
        content = relocated.get(path, path)
        if not content.is_file():
            continue
        target = local_name(out/'evidence', hashed)
        if sha256(content) != hashed:
            continue
        if not target.is_file() or content.stat().st_size != target.stat().st_size or sha256(target) != hashed:
            raise DamagedArchive('已提交复核的审计对象损坏，工作原件保留：'+name)
        yield path, hashed
    yield from execution_journal(out, row, relocated)


def execution_journal(out, row, relocated=None):
    fid = row['finding_id']
    folder = out/'review'
    relocated = relocated or {}
    prefix = re.escape(fid) + r'\.\d{8}T\d{12}-[0-9a-f]{8}'
    packet = row.get('packet_file', '')
    match = re.fullmatch('('+prefix+r')\.(?:failed-)?input\.json', packet)
    if match:
        path = local_name(folder, match[1]+'.execution.json')
        content = relocated.get(path, path)
        if content.is_file():
            raw = content.read_bytes()
            journal = json.loads(raw)
            # An execution journal is a pre-validation snapshot of these calls.
            if not isinstance(journal, dict) or journal.get('finding_id') != fid:
                return
            owner = journal.get('work_owner')
            if owner is not None:
                if (owner.get('request') != row.get('review_request') or owner.get('sequence') != row.get('review_base_sequence')
                        or owner.get('packet') != match[1]+'.input.json' or owner.get('prompt') != match[1]+'.prompt.txt'
                        or set(owner) - {'pid','creation_filetime','sequence','request','packet','prompt','closed'}):
                    return
                if (set(journal) == {'finding_id','scan_fingerprint','work_owner'}
                        and journal['scan_fingerprint'] == row.get('scan_fingerprint')):
                    yield path, hashlib.sha256(raw).hexdigest()
                    return
            if journal.get('packet_file') != packet:
                return
            attempts = row.get('attempts', [])
            saved = journal.get('attempts')
            def matches_attempt(record, final):
                return (isinstance(record, dict) and record.get('stdout_file') == final.get('stdout_file')
                        and all(value == final.get(key) if key != 'state' else
                                value in {final.get('state'), 'RUNNING', 'EXECUTED'}
                                for key, value in record.items()))
            if (not isinstance(saved, list) or not saved or len(saved) > len(attempts)
                    or not all(matches_attempt(record, final) for record, final in zip(saved, attempts))
                    or not any(matches_attempt(journal.get('execution'), final)
                               for final in attempts[row.get('attempt_start', 0):])):
                return
            # The producer writes this snapshot before parsing the final answer.
            # An unknown key or unique diagnostic must survive historical GC.
            transient = {'state', 'review_state', 'status', 'review_status', 'execution', 'attempts', 'summary_validation'}
            if owner is not None:
                transient.add('work_owner')
            if any(key not in row or value != row[key] for key, value in journal.items() if key not in transient):
                return
            for key in ('state', 'review_state', 'status', 'review_status'):
                if journal.get(key) not in (None, 'PENDING', row.get(key)):
                    return
            summary = journal.get('summary_validation', {})
            final = row.get('summary_validation', {})
            if any(key not in final or value != final[key] for key, value in summary.items()
                   if key != 'state' or value != 'PENDING'):
                return
            yield path, hashlib.sha256(raw).hexdigest()


def release_committed(out, row, progress, *, retry_marker=None, aliases=False):
    if row.get('state') not in {'DONE', 'TECH_FAILED'}:
        return
    errors = []
    damaged = None
    try:
        copies = duplicate_files(out, row, aliases=aliases) if 'archived_files' in row else execution_journal(out, row)
        for path, _ in list(copies):
            try:
                path.unlink()
            except OSError as exc:
                errors.append(f'{path.name}：{exc}')
        if retry_marker and not errors:
            retry_marker.unlink(missing_ok=True)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        errors.append(str(exc))
        if isinstance(exc, DamagedArchive):
            damaged = exc
    if errors:
        from .scan_persistence import _encode
        if 'archived_files' in row and not retry_marker:
            try:
                from .workspace import no_links
                folder = no_links(out/'diagnostics'/'review-cleanup')
                folder.mkdir(parents=True, exist_ok=True)
                hashed, _ = _encode(row)
                write_receipt(local_name(folder, hashed+'.json'), dict(finding_id=row['finding_id'], errors=errors))
            except (OSError, ValueError) as exc:
                errors.append(str(exc))
        try:
            progress(f'{row["finding_id"]} 工作副本待补偿清理：'+', '.join(errors))
        except OSError:
            pass
    return damaged


def retry_cleanup(out, conn, watermark, progress):
    """Retry exactly the failed event, even after a later round superseded it."""
    from .workspace import no_links
    folder = no_links(out/'diagnostics'/'review-cleanup')
    if not folder.is_dir():
        return
    for marker in folder.iterdir():
        if not re.fullmatch(r'[0-9a-f]{64}\.json', marker.name):
            continue
        try:
            marker = no_links(marker)
            fid = json.loads(marker.read_bytes())['finding_id']
            event = conn.execute('SELECT payload FROM ai_events WHERE finding_id=? AND hash=? AND sequence<=?',
                                 (fid, marker.stem, watermark)).fetchone()
            if event and hashlib.sha256(event[0].encode()).hexdigest() == marker.stem:
                row = json.loads(event[0])
                committed_receipt(out/'review', row)
                release_committed(out, row, progress, retry_marker=marker)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            progress(f'保留待补偿记录 {marker.name}：{exc}')


def navigation_record(out, name):
    import sys
    return dict(format='ECRA_EVIDENCE_NAVIGATION', version=1, root=name,
                database=str(out/'scan.db'), command=[sys.executable, '-m', 'ecra.evidence_reader',
                    '--database', str(out/'scan.db'), '--root', name],
                instructions='按 JSON path 或 node 读取；返回 total/hash/next_offset。必须继续分页直到 next_offset=null；字符串使用 --text。所有证据完整保留。')


def release_navigation(out, root):
    from .fact_parts import discard_worker_files
    path = local_name(out/'review', root+'-navigation.json')
    if path.is_file():
        # Only the complete generator output is reproducible. Preserve edits,
        # extensions and navigation issued by an unrecognized Portable.
        text = json.dumps(navigation_record(out, root), ensure_ascii=False, indent=2)
        originals = (text.encode('utf-8'), text.replace('\n', '\r\n').encode('utf-8'))
        with path.open('rb') as stream:
            saved = stream.read(max(map(len, originals)) + 1)
        if saved in originals:
            discard_worker_files(path)


def release_saved_shared(out, rows, progress):
    """A crash can leave shared inputs after every event has committed."""
    from .report_package import sha256
    from .fact_parts import discard_worker_files
    folder = out/'review'
    refs = {}
    for row in rows:
        if row.get('state') == 'PENDING':
            return
        for name, entry in row.get('archived_files', {}).items():
            if name == 'project-evidence.json' or re.fullmatch(r'[0-9a-f]{64}(?:\.index)?\.md', name):
                refs.setdefault(name, set()).add(entry['sha256'])
    for name, hashes in refs.items():
        try:
            path = local_name(folder if name == 'project-evidence.json' else folder/'case-library', name)
            if path.is_file():
                hashed = sha256(path)
                if hashed in hashes and sha256(local_name(out/'evidence', hashed)) == hashed:
                    discard_worker_files(path)
        except (OSError, ValueError) as exc:
            progress(f'共享材料保留待清理 {name}：{exc}')
    if refs:
        for root in ('report', 'facts'):
            try:
                release_navigation(out, root)
            except (OSError, ValueError, AttributeError) as exc:
                progress(f'导航文件保留待清理：{exc}')


def keep_damaged_receipt(out, path):
    if path.is_file():
        object_ref = archive_object(out, path)
        folder = out/'diagnostics'/'review-recovery'
        folder.mkdir(parents=True, exist_ok=True)
        write_receipt(folder/(path.name+'.'+object_ref['sha256']+'.json'), object_ref)
        manifest_path = out/'manifest.json'
        if manifest_path.is_file():
            manifest = json.loads(manifest_path.read_bytes())
            # Keep the damaged bytes identifiable in full result packages too.
            key = 'diagnostics/review-recovery/'+path.name+'.'+object_ref['sha256']
            index = dict(version=1, files={key: object_ref})
            with NamedTemporaryFile(dir=out, suffix='.pending', delete=False) as stream:
                temp = Path(stream.name)
                try:
                    stream.write(json.dumps(index, sort_keys=True).encode())
                    stream.close()
                    hashed = archive_object(out, temp)['sha256']
                finally:
                    stream.close()
                    temp.unlink(missing_ok=True)
            manifest['audit_indices'] = sorted({*manifest.get('audit_indices', []), hashed})
            write_receipt(manifest_path, manifest)


def verify_committed_review(root, folder, row, finding, fingerprint, receipt):
    stable = {key:value for key,value in receipt.items() if key != 'cached'}
    if stable != {key:value for key,value in row.items() if key != 'cached'}:
        raise ValueError('结果收据与已提交的 AI 事件不一致')
    from .review import validate_result_receipt
    validate_result_receipt(root, folder, row, finding['finding_id'], fingerprint, finding.get('static_classification'))



def reconcile_reviews(root, out, targets, rows, fingerprint, *, progress=print):
    """Compare current events with their receipts and replay validated orphan receipts."""
    from .common import read_json
    from .review import validate_result_receipt
    from .review_integrity import mark_review_stale, normalize_review_record
    from .scan_persistence import commit_review_result, review_head, review_request, review_writer, snapshot_head

    folder = out/'review'
    folder.mkdir(exist_ok=True)
    ledger = {row['finding_id']: row for row in rows}
    native = (out/'scan.db').is_file() and (out/'reviews.db').is_file()
    with review_writer(out) if native else nullcontext() as conn:
        snapshot = snapshot_head(conn) if native else {}
        watermark = snapshot.get('watermark') if snapshot.get('ai_events_version') == 2 else None
        if watermark is not None:
            _recover_intents(out, conn, watermark, progress)
            retry_cleanup(out, conn, watermark, progress)
        verified = []
        for ordinal, finding in enumerate(targets):
            fid = finding['finding_id']
            old = ledger.get(fid, dict(finding_id=fid, state='PENDING'))
            row = normalize_review_record(old)
            cache = folder/(fid+'.result.json')
            head = review_head(conn, fid, watermark) if watermark is not None else None
            try:
                receipt = read_json(cache)
            except (OSError, ValueError, TypeError) as exc:
                receipt = {}
                problem = f'结果收据无法读取：{exc}'
            else:
                if not isinstance(receipt, dict):
                    receipt = {}
                problem = '结果收据与已提交的 AI 事件不一致'
            if receipt and receipt.get('finding_id') != fid:
                problem = '独立收据的变量身份不匹配'
            if receipt and receipt.get('static_classification') != finding.get('static_classification'):
                problem = '独立收据的静态分类不匹配'
            recovered = False
            orphan = False
            if receipt.get('state') in {'DONE', 'TECH_FAILED'}:
                if head is not None and head[2] in {'PENDING', 'TECH_FAILED'} and head[0] == receipt.get('review_base_sequence'):
                    orphan = receipt.get('review_request') == review_request(conn, fid, head[0])
                elif not native:
                    orphan = row['state'] == 'PENDING'
            if orphan:
                try:
                    if native:
                        repair_orphan_receipt(out, cache, receipt)
                    validate_result_receipt(root, folder, receipt, fid, fingerprint, finding.get('static_classification'))
                except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
                    problem = '待恢复的复核收据校验失败：'+str(exc)
                    progress(f'{fid}：{problem}')
                    keep_damaged_receipt(out, cache)
                else:
                    if native:
                        commit_review_result(conn, ordinal, receipt)
                    progress(f'已恢复待提交的复核收据：{fid}')
                    row = receipt
                    recovered = True
            if native and head and head[2] in {'DONE', 'TECH_FAILED'} and 'archived_files' in row:
                try:
                    receipt = committed_receipt(folder, row)
                except (OSError, ValueError) as exc:
                    receipt = {}
                    problem = str(exc)
            if row['state'] == 'DONE':
                try:
                    if not recovered:
                        if not receipt and native:
                            receipt = committed_receipt(folder, row)
                        if not receipt:
                            raise ValueError(problem)
                        verify_committed_review(root, folder, row, finding, fingerprint, receipt)
                except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
                    progress(f'{fid}：复核收据失效，已列入重试：{exc}')
                    keep_damaged_receipt(out, cache)
                    mark_review_stale(folder, row, exc)
            elif row.get('error_type') == 'InvalidReviewEvent' or old.get('state') == 'DONE':
                progress(f'{fid}：{row.get("error", problem)}')
                keep_damaged_receipt(out, cache)
                mark_review_stale(folder, row, row.get('error', problem))
            elif row['state'] == 'TECH_FAILED' and native and 'archived_files' in row:
                try:
                    validate_result_receipt(root, folder, row, fid, fingerprint, finding.get('static_classification'))
                except (OSError, KeyError, ValueError, TypeError) as exc:
                    receipt = {}
                    progress(f'{fid}：已保留技术失败的工作文件：{exc}')
            elif row['state'] == 'TECH_FAILED' and receipt != row:
                keep_damaged_receipt(out, cache)
                write_receipt(cache, row)
            if receipt == row:
                release_committed(out, row, progress)
            row['static_classification'] = finding.get('static_classification')
            verified.append(row)
        if native:
            recover_object_copies(out, progress=progress)
        return verified


def archived_file(out, name, finding_id):
    """Resolve an archived name within one finding's immutable event history."""
    database = (out/'reviews.db').resolve().as_uri()+'?mode=ro'
    with closing(sqlite3.connect(database, uri=True)) as conn:
        conn.execute('PRAGMA trusted_schema=OFF')
        from .scan_persistence import snapshot_head
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ai_snapshots'").fetchone():
            return None
        snapshot = snapshot_head(conn)
        if snapshot.get('ai_events_version') != 2:
            return None
        for sequence, hashed, raw in conn.execute('SELECT sequence,hash,payload FROM ai_events WHERE finding_id=? AND sequence<=? ORDER BY sequence DESC',
                                        (finding_id, snapshot['watermark'])):
            row = json.loads(raw)
            files = row.get('archived_files')
            if files is None:
                if name in row.get('manual_exports', {}):
                    if hashlib.sha256(raw.encode()).hexdigest() != hashed:
                        raise ValueError('手动复核事件摘要损坏')
                    return manual_original(out, row, name)
                continue
            if hashlib.sha256(raw.encode()).hexdigest() != hashed:
                raise ValueError('复核归档事件摘要损坏')
            if (name == finding_id+'.result.json' and not (out/'evidence'/hashed).exists()
                    and _pending_projection(conn, sequence, row)):
                continue
            entry = dict(sha256=hashed) if name == finding_id+'.result.json' else files.get(name)
            if entry:
                from .report_package import OBJECT, sha256
                from .workspace import no_links
                hashed = entry.get('sha256')
                if not isinstance(hashed, str) or not OBJECT.fullmatch('evidence/'+hashed):
                    raise ValueError('复核收据对象身份无效')
                path = no_links(out/'evidence'/hashed)
                if sha256(path) != hashed:
                    raise ValueError('复核收据对象内容损坏')
                return path
    return None


def manual_original(out, row, name):
    """Resolve only an editable export bound to this exact published finding."""
    from .report_package import sha256
    fid = row['finding_id']
    field = {fid+'.input.json': 'packet', fid+'.prompt.txt': 'prompt'}.get(name)
    entry = row.get('manual_exports', {}).get(name)
    if not field or not entry or row.get(field+'_file') != name or row.get(field+'_sha256') != entry['sha256']:
        return None
    expected = entry['sha256']
    for path in (local_name(out/'evidence', expected), local_name(out/'review', name)):
        if path.is_file() and path.stat().st_size == entry['size'] and sha256(path) == expected:
            return path
    return None


def publish_manual_export(out, row, staged, name):
    """Replace an earlier manual output only after sealing its distinct bytes."""
    from .report_package import sha256
    target = local_name(out/'review', name)
    original = manual_original(out, row, name)
    if target.is_file():
        actual = sha256(target)
        if actual == sha256(staged):
            staged.unlink()
            return target
        if actual != row.get('manual_exports', {}).get(name, {}).get('sha256'):
            # Keep distinct user edits outside the automatic receipt namespace.
            edited = local_name(out/'review', name+'.edited-'+actual)
            if not edited.exists():
                durable_replace(target, edited)
            elif sha256(edited) != actual:
                raise ValueError('手动备包的编辑副本已变化，保留当前文件：'+name)
    if original is not None:
        archive_object(out, original, row['manual_exports'][name]['sha256'])
    durable_replace(staged, target)
    return target


def manual_context_path(out, name):
    folder = out/'review'
    if name in {'facts-navigation.json', 'report-navigation.json', 'project-evidence.json'}:
        return local_name(folder, name)
    if re.fullmatch(r'case-library/[0-9a-f]{64}(?:\.index)?\.md', name):
        return local_name(folder/'case-library', name.partition('/')[2])
    raise ValueError('未知的手动复核共享材料')


def seal_manual_context(out, rows):
    """A new batch may replace shared navigators still used by manual packets."""
    from .report_package import sha256
    checked = set()
    for row in rows:
        if row.get('state') != 'PENDING':
            continue
        for name, entry in row.get('manual_context', {}).items():
            key = (name, entry['sha256'])
            if key in checked:
                continue
            checked.add(key)
            path = manual_context_path(out, name)
            obj = local_name(out/'evidence', entry['sha256'])
            if obj.is_file() and obj.stat().st_size == entry['size'] and sha256(obj) == entry['sha256']:
                continue
            if archive_object(out, path, entry['sha256']) != entry:
                raise ValueError('手动复核共享材料已变化')


def package_manual_exports(out, database, stage, files, manifest):
    """Supply v1 Portable with manual inputs and exact SQLite-only queue receipts."""
    from .report_package import sha256
    from .scan_persistence import snapshot_head
    entries = {}
    with closing(sqlite3.connect(Path(database).resolve().as_uri()+'?mode=ro', uri=True)) as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ai_events'").fetchone():
            return
        head = snapshot_head(conn)
        if head.get('ai_events_version') != 2:
            return
        watermark = head['watermark']
        # Early Portable validates a physical object for every archived_files
        # event, including a requeued projection stored exclusively in SQLite.
        # Export those exact signed bytes without altering the source scan.
        for sequence, hashed, raw in conn.execute(
                "SELECT sequence,hash,payload FROM ai_events WHERE sequence<=? AND state='PENDING' "
                "AND json_type(payload,'$.archived_files')='object'", (watermark,)):
            key = 'evidence/'+hashed
            if key in files:
                continue
            payload = raw.encode()
            if hashlib.sha256(payload).hexdigest() != hashed or not _pending_projection(conn, sequence, json.loads(raw)):
                raise ValueError('待复核历史事件缺少可验证的原始收据')
            member = stage/hashed
            member.write_bytes(payload)
            files[key] = member
        sql = ("SELECT a.finding_id,a.hash,a.payload FROM ai_events a WHERE a.sequence<=? AND a.state='PENDING' "
               "AND json_type(a.payload,'$.manual_exports')='object' AND NOT EXISTS "
               "(SELECT 1 FROM ai_events b WHERE b.finding_id=a.finding_id AND b.sequence>a.sequence AND b.sequence<=?)")
        for fid, hashed, raw in conn.execute(sql, (watermark, watermark)):
            row = json.loads(raw)
            outputs = row['manual_exports']
            if (hashlib.sha256(raw.encode()).hexdigest() != hashed or row['finding_id'] != fid
                    or set(outputs) != {fid+'.input.json', fid+'.prompt.txt'}):
                raise ValueError('手动导出证据包的变量或文件清单无效')
            for name, record in row.get('manual_context', {}).items():
                local = manual_context_path(out, name)
                expected = record['sha256']
                if not re.fullmatch('[0-9a-f]{64}', expected):
                    raise ValueError('手动复核共享材料摘要无效')
                key = 'evidence/'+expected
                source = files.get(key) or local
                if key not in files and (source.stat().st_size != record['size'] or sha256(source) != expected):
                    raise ValueError('手动复核共享文件已变化：'+name)
                files[key] = source
                entries['review/'+name] = record
            for field in ('packet', 'prompt'):
                name = row[field+'_file']
                record = outputs[name]
                expected = record['sha256']
                if expected != row[field+'_sha256'] or not re.fullmatch('[0-9a-f]{64}', expected):
                    raise ValueError('手动导出文件摘要无效')
                key = 'evidence/'+expected
                source = files.get(key) or local_name(out/'review', name)
                if source.stat().st_size != record['size'] or sha256(source) != expected:
                    raise ValueError('手动导出文件已变化，无法发布原始版本：'+name)
                entries['review/'+name] = record
                files[key] = source
    if entries:
        raw = json.dumps(dict(version=1, files=entries), ensure_ascii=False, sort_keys=True).encode()
        hashed = hashlib.sha256(raw).hexdigest()
        index = stage/hashed
        index.write_bytes(raw)
        files['evidence/'+hashed] = index
        manifest['audit_indices'] = sorted({*manifest.get('audit_indices', []), hashed})


def _pending_projection(conn, sequence, row):
    """Older Portable queue updates copied terminal fields into a PENDING event.

    Only the original terminal event issued a file receipt. Prove the exact
    payload relationship before accepting a queue-only event without one.
    """
    if row.get('state') != 'PENDING' or not row.get('review_request'):
        return False
    mutable = {'state', 'status', 'review_state', 'review_status', 'review_retry_mode'}
    stable = {key:value for key,value in row.items() if key not in mutable}
    for hashed, raw in conn.execute(
            "SELECT hash,payload FROM ai_events WHERE finding_id=? AND sequence<? "
            "AND state IN ('DONE','TECH_FAILED') ORDER BY sequence DESC", (row['finding_id'], sequence)):
        if hashlib.sha256(raw.encode()).hexdigest() != hashed:
            raise ValueError('历史复核事件摘要损坏')
        if stable == {key:value for key,value in json.loads(raw).items() if key not in mutable}:
            return True
    return False


def validate_event_archives(out, database, *, progress=None, package_files=None):
    from pathlib import PurePosixPath
    from .report_package import OBJECT, sha256
    checked = set()
    with closing(sqlite3.connect(Path(database).resolve().as_uri()+'?mode=ro', uri=True)) as conn:
        conn.execute('PRAGMA trusted_schema=OFF')
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='ai_events' AND type='table'").fetchone():
            return
        for sequence, finding_id, hashed, raw in conn.execute("SELECT sequence,finding_id,hash,payload FROM ai_events WHERE json_type(payload,'$.archived_files')='object'"):
            if hashlib.sha256(raw.encode()).hexdigest() != hashed:
                raise ValueError('AI 复核归档事件摘要损坏')
            row = json.loads(raw)
            files = row['archived_files']
            if (out/'evidence'/hashed).exists() or not _pending_projection(conn, sequence, row):
                files[f'{finding_id}.result.json'] = dict(sha256=hashed, size=len(raw.encode()))
            for name, entry in files.items():
                path = PurePosixPath(name)
                object_hash, size = entry.get('sha256'), entry.get('size')
                if (len(path.parts) != 1 or path.is_absolute() or '\\' in name or ':' in name or '..' in path.parts
                        or not isinstance(object_hash, str) or not OBJECT.fullmatch('evidence/'+object_hash)
                        or type(size) is not int or size < 0):
                    raise ValueError('逐项复核审计引用无效')
                if package_files is not None and 'evidence/'+object_hash not in package_files:
                    raise ValueError('结果包缺少逐项复核审计原件：'+name)
                target = out/'evidence'/object_hash
                if target.stat().st_size != size or (object_hash not in checked and sha256(target, progress=progress) != object_hash):
                    raise ValueError('逐项复核审计原件损坏：'+name)
                checked.add(object_hash)
