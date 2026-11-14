"""Durable files and content-addressed evidence for individual AI receipts."""
from contextlib import closing, nullcontext
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
from tempfile import NamedTemporaryFile
import time


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


def archive_object(out, source, expected=None):
    from .report_package import sha256
    hashed = expected or sha256(source)
    objects = out/'evidence'
    if not objects.is_dir():
        objects.mkdir(exist_ok=True)
        _sync_directory(out)
    target = objects/hashed
    if not target.is_file():
        # Keep temporary names outside the immutable object namespace used by exports.
        with NamedTemporaryFile(dir=out, suffix='.pending', delete=False) as stream:
            temp = Path(stream.name)
            try:
                with source.open('rb') as original:
                    shutil.copyfileobj(original, stream)
                stream.flush()
                os.fsync(stream.fileno())
                stream.close()
                if sha256(temp) != hashed:
                    raise ValueError('复核原件在归档期间变化：'+source.name)
                durable_replace(temp, target)
            finally:
                stream.close()
                temp.unlink(missing_ok=True)
    elif sha256(target) != hashed:
        raise ValueError('内容寻址审计对象损坏：'+str(target))
    return dict(sha256=hashed, size=target.stat().st_size)


def archive_receipt(out, path, row):
    from .scan_persistence import _encode
    write_receipt(path, row, compact=True)
    archive_object(out, path, _encode(row)[0])


def repair_orphan_receipt(out, cache, row):
    from .scan_persistence import _encode
    expected, _ = _encode(row)
    from .report_package import sha256
    if sha256(cache) != expected:
        raise ValueError('待恢复复核收据不是原始完整写入')
    archive_object(out, cache, expected)


def archive_review_files(out, row):
    folder = out/'review'
    attempts = row.get('attempts', [])[row.get('attempt_start', 0):]
    files = {}
    for record in [row, *attempts, row.get('execution') or {}]:
        for key in ('stdout', 'stderr', 'prompt', 'packet'):
            name, hashed = record.get(key+'_file'), record.get(key+'_sha256')
            if name and hashed and name not in files:
                path = folder/name
                if path.parent.resolve() != folder.resolve() or not path.is_file():
                    raise ValueError('复核归档缺少原件：'+name)
                # Flush the original logs as well as their immutable copies.
                with path.open('r+b') as stream:
                    os.fsync(stream.fileno())
                files[name] = archive_object(out, path, hashed)
    for key in ('language_correction', 'summary_correction'):
        correction = row.get(key)
        if correction:
            name, hashed = correction['source_stdout_file'], correction['source_stdout_sha256']
            if name not in files:
                path = folder/name
                if path.parent.resolve() != folder.resolve():
                    raise ValueError('复核修正引用越出归档目录')
                files[name] = archive_object(out, path, hashed)
    return files


def keep_damaged_receipt(out, path):
    if path.is_file():
        object_ref = archive_object(out, path)
        folder = out/'diagnostics'/'review-recovery'
        folder.mkdir(parents=True, exist_ok=True)
        write_receipt(folder/(path.name+'.'+object_ref['sha256']+'.json'), object_ref)


def verify_committed_review(root, folder, row, finding, fingerprint, receipt):
    stable = {key:value for key,value in receipt.items() if key != 'cached'}
    if stable != {key:value for key,value in row.items() if key != 'cached'}:
        raise ValueError('结果收据与已提交的 AI 事件不一致')
    from .review import validate_result_receipt
    validate_result_receipt(root, folder, row, finding['finding_id'], fingerprint, finding.get('static_classification'))
    if 'review_base_sequence' in row:
        from .scan_persistence import _encode
        from .report_package import sha256
        object_hash, _ = _encode(row)
        if sha256(folder.parent/'evidence'/object_hash) != object_hash:
            raise ValueError('已提交的单变量结果归档损坏')


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
                    validate_result_receipt(root, folder, receipt, fid, fingerprint, finding.get('static_classification'))
                    if native:
                        repair_orphan_receipt(out, cache, receipt)
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
            if row['state'] == 'DONE':
                try:
                    if not recovered:
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
            elif row['state'] == 'TECH_FAILED' and receipt != row:
                keep_damaged_receipt(out, cache)
                write_receipt(cache, row)
            row['static_classification'] = finding.get('static_classification')
            verified.append(row)
        return verified


def archived_file(out, name, finding_id):
    """Resolve an archived name within one finding's immutable event history."""
    database = (out/'reviews.db').resolve().as_uri()+'?mode=ro'
    with closing(sqlite3.connect(database, uri=True)) as conn:
        conn.execute('PRAGMA trusted_schema=OFF')
        from .scan_persistence import snapshot_head
        snapshot = snapshot_head(conn)
        if snapshot.get('ai_events_version') != 2:
            return None
        for hashed, raw in conn.execute('SELECT hash,payload FROM ai_events WHERE finding_id=? AND sequence<=? ORDER BY sequence DESC',
                                        (finding_id, snapshot['watermark'])):
            files = json.loads(raw).get('archived_files')
            if files is None:
                continue
            if hashlib.sha256(raw.encode()).hexdigest() != hashed:
                raise ValueError('复核归档事件摘要损坏')
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


def validate_event_archives(out, database, *, progress=None, package_files=None):
    from pathlib import PurePosixPath
    from .report_package import OBJECT, sha256
    checked = set()
    with closing(sqlite3.connect(Path(database).resolve().as_uri()+'?mode=ro', uri=True)) as conn:
        conn.execute('PRAGMA trusted_schema=OFF')
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='ai_events' AND type='table'").fetchone():
            return
        for finding_id, hashed, raw in conn.execute("SELECT finding_id,hash,payload FROM ai_events WHERE json_type(payload,'$.archived_files')='object'"):
            if hashlib.sha256(raw.encode()).hexdigest() != hashed:
                raise ValueError('AI 复核归档事件摘要损坏')
            files = json.loads(raw)['archived_files']
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
