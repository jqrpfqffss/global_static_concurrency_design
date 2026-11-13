"""Versioned ZIP64 result packages; validate in isolation before publication."""
from contextlib import closing, ExitStack
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import stat
import tempfile
import zipfile

from .human_reviews import ReviewStore
from .diff_review import DiffReviewEvidence
from .scan_store import EvidenceProvider, connect_readonly, schema_for_version, SUPPORTED_VERSIONS
from .workspace import no_links
from .storage_activity import DataActivity, guarded_operation, scan_data_root

IDENTITY = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z')
OBJECT = re.compile(r'evidence/[a-f0-9]{64}\Z')
MAX_PACKAGE_RATIO = 2000


def sha256(path, *, progress=None):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            value.update(block)
            if progress:
                progress({})
    return value.hexdigest()


def _safe_name(name):
    if name in {'scan.db', 'reviews.db', 'manifest.json'} or OBJECT.fullmatch(name):
        p = PurePosixPath(name)
        if not p.is_absolute() and '..' not in p.parts and '\\' not in name and ':' not in name:
            return name
    raise ValueError('结果包包含不允许的路径: ' + name[:200])


def snapshot(source, destination, *, check_integrity=True, progress=None):
    with closing(sqlite3.connect(Path(source).resolve().as_uri()+'?mode=ro', uri=True)) as src, \
            closing(sqlite3.connect(destination)) as dst:
        src.execute('PRAGMA trusted_schema=OFF')
        def copied(status, remaining, total):
            if progress:
                progress(dict(completed=total-remaining, total=total, unit='pages'))
        src.backup(dst, pages=4096, progress=copied)
        if check_integrity:
            from .operation_progress import sqlite_progress
            with sqlite_progress(dst, progress):
                if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('SQLite 一致快照完整性失败')


def _schema(conn):
    return sorted(tuple(row) for row in conn.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"))


def validate_schema(path, sql, version=0, *, check_integrity=True):
    with closing(sqlite3.connect(':memory:')) as expected, \
            closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True)) as actual:
        actual.execute('PRAGMA trusted_schema=OFF')
        expected.executescript(sql)
        if _schema(actual) != _schema(expected) or actual.execute('PRAGMA user_version').fetchone()[0] != version:
            raise ValueError('结果包数据库结构未知或已被修改；拒绝执行/导入')
        if check_integrity and (actual.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or list(actual.execute('PRAGMA foreign_key_check'))):
            raise ValueError('结果包数据库完整性/外键检查失败')


def _review_events(path, binding):
    from .human_reviews import SCHEMA as REVIEW_SCHEMA, HUMAN_SCHEMA, LEGACY_AI_SCHEMA, PRE_INHERIT_SCHEMA
    for known in (REVIEW_SCHEMA,PRE_INHERIT_SCHEMA,HUMAN_SCHEMA+LEGACY_AI_SCHEMA,HUMAN_SCHEMA):
        try:
            validate_schema(path,known)
            break
        except ValueError:
            if known==HUMAN_SCHEMA:
                raise
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True)) as conn:
        conn.execute('PRAGMA trusted_schema=OFF')
        saved = conn.execute('SELECT scan_id,project_id,facts_hash,report_hash FROM binding').fetchall()
        if saved != [tuple(binding[key] for key in ('scan_id', 'project_id', 'facts_hash', 'report_hash'))]:
            raise ValueError('人工记录与静态证据不匹配')
        events = [json.loads(row[0]) for row in conn.execute('SELECT payload FROM events ORDER BY revision,event_id')]
        # Payload and the relational DAG must agree; do not trust only JSON.
        expected = sorted((event['event_id'], parent) for event in events for parent in event['parents'])
        actual = list(conn.execute('SELECT event_id,parent_id FROM predecessors ORDER BY event_id,parent_id'))
        if expected != actual:
            raise ValueError('人工事件历史关系损坏')
    return events


def copy_ai_receipts(source, destination, *, _connection=None):
    """Copy validated data only, executing no SQL from an imported schema."""
    with ExitStack() as stack:
        src=stack.enter_context(closing(sqlite3.connect(Path(source).resolve().as_uri()+'?mode=ro',uri=True)))
        dst=_connection
        if dst is None:
            dst=stack.enter_context(closing(sqlite3.connect(destination)))
            stack.enter_context(dst)
        src.execute('PRAGMA trusted_schema=OFF')
        if not src.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ai_snapshots'").fetchone():
            return
        if src.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ai_events'").fetchone():
            for row in src.execute('SELECT sequence,ordinal,finding_id,state,hash,payload FROM ai_events ORDER BY sequence'):
                if hashlib.sha256(row[5].encode()).hexdigest()!=row[4]:
                    raise ValueError('AI 复核事件摘要损坏')
                payload=json.loads(row[5])
                if not isinstance(payload,dict) or payload.get('finding_id')!=row[2] or payload.get('state')!=row[3]:
                    raise ValueError('AI 复核事件投影不一致')
                old=dst.execute('SELECT sequence,ordinal,finding_id,state,hash,payload FROM ai_events WHERE sequence=?',(row[0],)).fetchone()
                if old and old!=row:
                    raise ValueError('AI 复核事件序列冲突')
                if not old:
                    dst.execute('INSERT INTO ai_events VALUES (?,?,?,?,?,?)',row)
        for sequence, hashed, payload in src.execute('SELECT sequence,hash,payload FROM ai_snapshots ORDER BY sequence'):
            if hashlib.sha256(payload.encode()).hexdigest() != hashed:
                raise ValueError('AI 复核收据摘要损坏')
            value = json.loads(payload)
            if (not isinstance(value, dict) or set(value) not in ({'report', 'reviews'},{'report','reviews','ai_events_version'},{'report','reviews','ai_events_version','watermark'})
                    or not isinstance(value['report'], dict) or not isinstance(value['reviews'], list)):
                raise ValueError('AI 复核收据格式未知')
            if 'ai_events_version' in value and value['ai_events_version'] not in {1,2}:
                raise ValueError('未知 AI 事件版本')
            if value.get('ai_events_version')==1:
                for ref in value['reviews']:
                    actual=dst.execute('SELECT finding_id,hash FROM ai_events WHERE sequence=?',(ref.get('sequence'),)).fetchone()
                    if actual != (ref.get('finding_id'),ref.get('hash')):
                        raise ValueError('AI 复核快照缺少引用事件')
            if value.get('ai_events_version')==2:
                watermark=value.get('watermark')
                if (type(watermark) is not int or watermark<0 or value['reviews']
                        or (watermark and not dst.execute('SELECT 1 FROM ai_events WHERE sequence=?',(watermark,)).fetchone())):
                    raise ValueError('AI 复核快照水位无效')
            existing = dst.execute('SELECT hash,payload FROM ai_snapshots WHERE sequence=?', (sequence,)).fetchone()
            if existing and existing != (hashed, payload):
                raise ValueError('AI 复核审计序列冲突，保留原记录')
            if not existing:
                dst.execute('INSERT INTO ai_snapshots VALUES (?,?,?)', (sequence, hashed, payload))


def copy_prior_decisions(source, destination, provider, *, _connection=None):
    """Copy original history and independently verify optional inheritance proof."""
    with ExitStack() as stack:
        src=stack.enter_context(closing(sqlite3.connect(Path(source).resolve().as_uri()+'?mode=ro',uri=True)))
        src.execute('PRAGMA trusted_schema=OFF')
        if not src.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='prior_decisions'").fetchone():
            return
        dst=_connection
        if dst is None:
            dst=stack.enter_context(closing(sqlite3.connect(destination)));stack.enter_context(dst)
        copy_prior_rows(list(src.execute('SELECT * FROM prior_decisions ORDER BY symbol_id,source_scan')), dst, provider)


def copy_prior_rows(rows, destination, provider):
    from .review_inheritance import validate_prior, validate_lineage
    if not isinstance(rows, list) or any(not isinstance(r, (list,tuple)) or len(r)!=6 for r in rows):
        raise ValueError('历史确认行格式无效')
    for raw in rows:
        row=tuple(raw)
        validate_prior(row,provider)
        existing=destination.execute('SELECT * FROM prior_decisions WHERE symbol_id=? AND source_scan=?',
            (row[0],row[2])).fetchone()
        if existing is not None and tuple(existing)!=row:
            raise ValueError('同一历史确认来源包含不同内容')
        if existing is None:
            destination.execute('INSERT INTO prior_decisions VALUES (?,?,?,?,?,?)',row)
    values=[json.loads(r[0]) for r in destination.execute('SELECT payload FROM prior_decisions')]
    validate_lineage(values, [])


def validate_objects(directory, manifest, *, max_raw_bytes=128*1024**3, progress=None, database=None):
    """Verify all referenced raw evidence and receipt objects, in bounded reads."""
    from pathlib import PurePosixPath
    import gzip
    directory = Path(directory)
    indices=manifest.get('audit_indices',[])
    if not isinstance(indices,list) or any(not isinstance(value,str) for value in indices):
        raise ValueError('审计索引列表无效')
    for index_hash in set([*indices,*([manifest['audit_index']] if manifest.get('audit_index') else [])]):
        if not isinstance(index_hash,str) or not OBJECT.fullmatch('evidence/'+index_hash):
            raise ValueError('审计索引身份无效')
        index = json.loads((directory/'evidence'/index_hash).read_text(encoding='utf-8'))
        if index.get('version') != 1 or not isinstance(index.get('files'),dict):
            raise ValueError('审计索引版本未知')
        for name, record in index['files'].items():
            path = PurePosixPath(name)
            if (path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name
                    or not isinstance(record,dict) or not OBJECT.fullmatch('evidence/'+str(record.get('sha256','')))):
                raise ValueError('审计对象引用或相对路径无效')
            target = directory/'evidence'/record['sha256']
            if target.stat().st_size != record.get('size') or sha256(target, progress=progress) != record['sha256']:
                raise ValueError('审计收据对象缺失或已损坏')
    consumed = 0
    # Query scalar reference fields only; source text is never loaded here.
    with closing(connect_readonly(database or directory/'scan.db')) as conn:
        from .scan_store import _decode
        legacy = conn.execute("SELECT e.child FROM roots r JOIN edges e ON e.parent=r.node WHERE r.name='provenance' AND e.key='legacy_inputs'").fetchone()
        if legacy:
            for (node,) in conn.execute('SELECT child FROM edges WHERE parent=? ORDER BY ordinal',(legacy[0],)):
                fields = {key:_decode(kind,value) for key,kind,value in conn.execute(
                    "SELECT e.key,n.kind,n.value FROM edges e JOIN nodes n ON n.id=e.child WHERE e.parent=? "
                    "AND e.key IN ('file','sha256','size','disposition') AND n.kind NOT IN ('object','list')",(node,))}
                name=fields.get('file'); hashed=fields.get('sha256'); size=fields.get('size')
                if (not isinstance(name,str) or PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts
                        or '\\' in name or ':' in name or not OBJECT.fullmatch('evidence/'+str(hashed))
                        or type(size) is not int or size<0):
                    raise ValueError('旧归档原文件引用损坏')
                if fields.get('disposition')=='CANONICAL_REENCODED':
                    if name not in {'facts.json','reports/global_static_concurrency.json'}:
                        raise ValueError('未知旧文件被错误标成可重建，拒绝丢弃证据')
                elif fields.get('disposition')=='OPAQUE_AUDIT_PRESERVED':
                    target=directory/'evidence'/hashed
                    if not target.is_file() or target.stat().st_size!=size or sha256(target, progress=progress)!=hashed:
                        raise ValueError('旧归档审计原字节缺失或损坏：'+name)
                else:
                    raise ValueError('旧归档原文件处置方式未知')
        root = conn.execute("SELECT e.child FROM roots r JOIN edges e ON e.parent=r.node WHERE r.name='provenance' AND e.key='archived_sources'").fetchone()
        if root is None:
            return
        for (node,) in conn.execute('SELECT child FROM edges WHERE parent=? ORDER BY ordinal', (root[0],)):
            fields = {key:_decode(kind,value) for key,kind,value in conn.execute(
                "SELECT e.key,n.kind,n.value FROM edges e JOIN nodes n ON n.id=e.child WHERE e.parent=? AND e.key IN ('raw_object','codec','sha256','size')", (node,))}
            if 'raw_object' not in fields:
                continue  # v1 source bytes are embedded directly in the graph
            if (not OBJECT.fullmatch('evidence/'+str(fields['raw_object'])) or fields.get('codec') != 'gzip'
                    or type(fields.get('size')) is not int or fields['size'] < 0):
                raise ValueError('归档源码对象描述无效')
            target = directory/'evidence'/fields['raw_object']
            if sha256(target, progress=progress) != fields['raw_object']:
                raise ValueError('归档源码压缩对象缺失/损坏')
            hashed, size = hashlib.sha256(), 0
            with gzip.open(target,'rb') as stream:
                for block in iter(lambda:stream.read(1024*1024),b''):
                    size += len(block); consumed += len(block)
                    if size > fields['size'] or consumed > max_raw_bytes:
                        raise ValueError('归档源码展开超过声明/预算')
                    hashed.update(block)
                    if progress:
                        progress({})
            if size != fields['size'] or hashed.hexdigest() != fields.get('sha256'):
                raise ValueError('归档源码原始字节摘要不一致')


def _published_scan_hash(manifest, binding, version):
    """Reuse a local publication/import checksum, never a ZIP's trust claim.

    Export transports an already published immutable database. Matching every
    byte to its publication checksum avoids rerunning graph construction.
    Receiving imports still perform all independent deep validation. Missing
    receipts (including legacy archives) use the full snapshot/check path.
    """
    if not isinstance(manifest, dict) or type(manifest.get('version')) is not int or manifest['version'] != 1:
        return None
    if manifest.get('format') == 'ECRA_LOCAL_SCAN' and manifest.get('state') == 'STATIC_VALIDATED':
        expected = manifest.get('scan_sha256')
        keys = ('scan_id', 'project_id', 'profile_id', 'facts_hash', 'report_hash')
    elif (manifest.get('format') == 'ECRA_REPORT' and manifest.get('schema_version') == version
          and isinstance(manifest.get('import_origin'), str)
          and re.fullmatch('[a-f0-9]{64}', manifest['import_origin'])):
        files = manifest.get('files')
        record = files.get('scan.db') if isinstance(files, dict) else None
        expected = record.get('sha256') if isinstance(record, dict) else None
        keys = ('scan_id', 'project_id', 'facts_hash', 'report_hash')
    else:
        return None
    if not isinstance(expected, str) or not re.fullmatch('[a-f0-9]{64}', expected):
        return None
    if any(manifest.get(key) != binding[key] for key in keys):
        raise ValueError('扫描身份与已封存记录不一致，拒绝导出')
    return expected


@guarded_operation(lambda args:scan_data_root(args['scan_directory']))
def export_report(scan_directory, destination, *, compression='compact', progress=None):
    if not isinstance(compression,str) or compression not in {'compact','deflate'}:
        raise ValueError('完整包压缩只支持 compact（省空间）或 deflate（快速）')
    source, destination = no_links(scan_directory), no_links(destination)
    notify = progress or (lambda _: None)
    if destination.exists():
        raise FileExistsError('导出目标已存在，请另存新文件')
    destination.parent.mkdir(parents=True, exist_ok=True)
    local_manifest = source/'manifest.json'
    local = json.loads(local_manifest.read_text(encoding='utf-8')) if local_manifest.is_file() else {}
    with tempfile.TemporaryDirectory(prefix='ecra export ', dir=destination.parent) as folder, ExitStack() as static_lock:
        stage = Path(folder)
        notify(dict(stage='PREPARING', message='核对扫描归档与导出范围', completed=None, total=None, unit=None))
        locked = static_lock.enter_context(closing(connect_readonly(source/'scan.db')))
        locked.execute('BEGIN')
        # The schema read acquires a shared SQLite read lock. Validate the
        # closed schema before querying any user-controlled table or view.
        locked.execute('SELECT count(*) FROM sqlite_master').fetchone()
        schema_version = locked.execute('PRAGMA user_version').fetchone()[0]
        validate_schema(source/'scan.db', schema_for_version(schema_version), schema_version, check_integrity=False)
        # In rollback journal
        # modes it prevents a writer/checkpoint changing the main file while
        # we stream it. WAL needs backup(): copying its main file loses rows.
        rows = locked.execute('SELECT * FROM scans').fetchall()
        if len(rows) != 1:
            raise ValueError('静态库扫描身份缺失/不唯一')
        binding = dict(rows[0])
        expected_static = _published_scan_hash(local, binding, schema_version)
        if expected_static and locked.execute('PRAGMA journal_mode').fetchone()[0] in {'delete', 'truncate', 'persist'}:
            static = source/'scan.db'
            provider = EvidenceProvider(static)
        else:
            static_lock.close()
            expected_static = None
            static = stage/'scan.db'
            notify(dict(stage='SNAPSHOT', message='建立静态数据库一致快照', completed=0, total=None, unit='pages'))
            snapshot(source/'scan.db', static, check_integrity=False, progress=progress)
            notify(dict(stage='VERIFY_DATABASE', message='完整校验未封存的静态快照', completed=None, total=None, unit=None))
            with closing(connect_readonly(static)) as conn:
                schema_version = conn.execute('PRAGMA user_version').fetchone()[0]
            validate_schema(static, schema_for_version(schema_version), schema_version, check_integrity=False)
            provider = EvidenceProvider(static)
            binding = provider.validate(deep=True, progress=progress)
        notify(dict(stage='REVIEWS', message='保存并核对人工确认与审计记录', completed=None, total=None, unit=None))
        snapshot(source/'reviews.db', stage/'reviews.db', progress=progress)
        events = _review_events(stage/'reviews.db', binding)
        # Validate all original immutable events in a fresh trusted schema.
        check = ReviewStore(stage/'check.db', binding)
        copy_prior_decisions(stage/'reviews.db',stage/'check.db',provider)
        check.merge(events, fingerprint_for=DiffReviewEvidence(source, provider, progress=progress).fingerprint)
        copy_ai_receipts(stage/'reviews.db', stage/'check.db')
        files = {'scan.db': static, 'reviews.db': stage/'reviews.db'}
        evidence = source/'evidence'
        notify(dict(stage='EVIDENCE', message='校验归档源码与全部证据对象', completed=None, total=None, unit=None))
        if evidence.exists():
            no_links(evidence)
            for item in evidence.iterdir():
                no_links(item)
                name = _safe_name('evidence/' + item.name)
                if not item.is_file():
                    raise ValueError('归档证据对象损坏')
                files[name] = item
        baseline = DiffReviewEvidence(source, provider, progress=progress).baseline()
        if baseline is not None and baseline.path.name == 'scan.db':
            files['evidence/'+baseline.path.parent.name] = baseline.path
        manifest = dict(format='ECRA_REPORT', version=1, schema_version=schema_version,
            scan_id=binding['scan_id'], project_id=binding['project_id'], facts_hash=binding['facts_hash'],
            report_hash=binding['report_hash'], capabilities=['archived_evidence', 'human_decisions'],
            source_reverification=False, files={})
        if local:
            if local.get('audit_index'):
                manifest['audit_index'] = local['audit_index']
                if 'evidence/'+local['audit_index'] not in files:
                    raise ValueError('缺少完整审计对象索引')
            if local.get('audit_indices'):
                manifest['audit_indices']=local['audit_indices']
        validate_objects(source, manifest, progress=progress, database=static)
        archive = stage/'result.pending'
        def encode(compact):
            total=sum(path.stat().st_size for path in files.values()); completed=0
            notify(dict(stage='COMPRESS', message='打包并核对完整扫描数据' + ('（省空间模式）' if compact else '（快速模式）'), completed=0, total=total, unit='bytes'))
            records = {}
            with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=1,allowZip64=True) as zipped:
                for name,path in files.items():
                    method=zipfile.ZIP_BZIP2 if compact and name=='scan.db' else zipfile.ZIP_DEFLATED
                    info=zipfile.ZipInfo.from_file(path,name)
                    expected_size = info.file_size
                    info.compress_type=method
                    info._compresslevel=9 if method==zipfile.ZIP_BZIP2 else 1
                    digest = hashlib.sha256(); size = 0
                    with path.open('rb') as src, zipped.open(info,'w',force_zip64=True) as dst:
                        for block in iter(lambda:src.read(1024**2),b''):
                            dst.write(block); digest.update(block); size+=len(block); completed+=len(block)
                            notify(dict(completed=completed, total=total, unit='bytes'))
                    hashed = digest.hexdigest()
                    if name == 'scan.db' and expected_static and hashed != expected_static:
                        raise ValueError('扫描数据库与封存时的完整摘要不一致，拒绝发布结果包；原数据保留')
                    if OBJECT.fullmatch(name) and hashed != path.name:
                        raise ValueError('归档证据对象损坏，拒绝发布结果包')
                    if size != expected_size:
                        raise ValueError('导出期间文件大小发生变化，拒绝发布结果包')
                    records[name] = dict(size=size, sha256=hashed)
                # Bind precisely the bytes written into the ZIP, with no
                # separate full-file hashing pass or source reread race.
                manifest['files'] = records
                zipped.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,sort_keys=True))
        encode(compression=='compact')
        if compression=='compact':
            with zipfile.ZipFile(archive) as zipped:
                database=zipped.getinfo('scan.db')
                fallback=database.file_size>max(1,database.compress_size)*MAX_PACKAGE_RATIO
            if fallback:
                # Re-encode the same frozen files, preserving the established
                # importer budget. This is a fresh private pending, never an
                # existing user archive, and publication still happens last.
                encode(False)
        # Export is exclusive; existing user packages are never overwritten.
        # Atomic and exclusive on NTFS/ext4. A process crash must not expose a
        # partially copied package at the final user-visible filename.
        notify(dict(stage='PUBLISH', message='发布完整结果包', completed=None, total=None, unit=None))
        os.link(archive, destination)
    return manifest


@guarded_operation(lambda args:args['data_root'])
def import_report(package, data_root, *, max_bytes=128*1024**3, max_entries=100000, max_ratio=MAX_PACKAGE_RATIO, progress=None):
    notify = progress or (lambda _: None)
    notify(dict(stage='PREPARING', message='检查结果包清单与可用空间', completed=None, total=None, unit=None))
    data = no_links(data_root)
    work = no_links(data/'work'); work.mkdir(parents=True, exist_ok=True)
    # Also serialize CLI/legacy synchronous imports with background imports;
    # their manifest union must not race even though review transactions lock.
    with DataActivity(data, exclusive=True, purpose='report-import'), \
            tempfile.TemporaryDirectory(prefix='import-', dir=work) as folder, ExitStack() as resources:
        stage = Path(folder)
        with zipfile.ZipFile(package) as zipped:
            members = zipped.infolist()
            if len(members)>max_entries or len({m.filename.casefold() for m in members}) != len(members):
                raise ValueError('结果包条目过多或存在重复/大小写冲突路径')
            total = 0
            for member in members:
                _safe_name(member.filename)
                mode = member.external_attr >> 16
                if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in {0, stat.S_IFREG}) or member.flag_bits & 1:
                    raise ValueError('结果包不允许链接、目录、设备或加密条目')
                total += member.file_size
                if total>max_bytes or member.file_size>max(1,member.compress_size)*max_ratio:
                    raise ValueError('结果包解压大小/压缩比超出预算；请核对来源与可用空间')
            if shutil.disk_usage(work).free < total*2:
                raise ValueError('导入及数据库校验所需磁盘空间不足')
            try:
                info = zipped.getinfo('manifest.json')
                if info.file_size>4*1024*1024:
                    raise ValueError('结果包清单过大')
                manifest = json.loads(zipped.read(info))
            except (KeyError, json.JSONDecodeError) as exc:
                raise ValueError('结果包缺少有效清单') from exc
            if (manifest.get('format') != 'ECRA_REPORT' or type(manifest.get('version')) is not int
                    or manifest.get('version') != 1 or type(manifest.get('schema_version')) is not int
                    or manifest.get('schema_version') not in SUPPORTED_VERSIONS):
                raise ValueError('未知结果包/schema版本，请使用匹配版本软件')
            if not all(isinstance(manifest.get(k), str) and IDENTITY.fullmatch(manifest[k]) for k in ('scan_id', 'project_id')):
                raise ValueError('结果包工程/扫描身份无效')
            records = manifest.get('files')
            if (not isinstance(records, dict) or not {'scan.db', 'reviews.db'} <= set(records)
                    or set(records) != {m.filename for m in members} - {'manifest.json'}):
                raise ValueError('结果包内容与清单不一致')
            extracted = 0
            payload_size = sum(m.file_size for m in members if m.filename != 'manifest.json')
            notify(dict(stage='EXTRACT', message='解包并逐字节校验 SHA-256', completed=0, total=payload_size, unit='bytes'))
            for member in members:
                if member.filename == 'manifest.json':
                    continue
                record = records[member.filename]
                if not isinstance(record, dict) or record.get('size') != member.file_size:
                    raise ValueError('结果包文件大小不一致')
                target = no_links(stage/member.filename)
                target.parent.mkdir(parents=True, exist_ok=True)
                with zipped.open(member) as src, target.open('xb') as dst:
                    copied = 0
                    digest = hashlib.sha256()
                    while True:
                        block = src.read(1024*1024)
                        if not block:
                            break
                        copied += len(block)
                        if copied>member.file_size:
                            raise ValueError('结果包解压数据超过声明大小')
                        dst.write(block)
                        digest.update(block)
                        extracted += len(block)
                        notify(dict(completed=extracted, total=payload_size, unit='bytes'))
                if copied != record['size'] or digest.hexdigest() != record.get('sha256'):
                    raise ValueError('结果包 SHA-256 校验失败')
                if OBJECT.fullmatch(member.filename) and record['sha256'] != Path(member.filename).name:
                    raise ValueError('证据对象内容身份错误')
        # The provider below performs integrity/foreign-key checks on this
        # same isolated snapshot with its bounded large-database cache.
        validate_schema(stage/'scan.db', schema_for_version(manifest['schema_version']), manifest['schema_version'], check_integrity=False)
        provider = EvidenceProvider(stage/'scan.db')
        from .import_validation import validate_imported_database
        binding = validate_imported_database(stage/'scan.db', progress=progress)
        notify(dict(stage='EVIDENCE', message='核对全部归档证据与源文件', completed=None, total=None, unit=None))
        validate_objects(stage, manifest, max_raw_bytes=max_bytes, progress=progress)
        if any(manifest.get(k) != binding[k] for k in ('scan_id', 'project_id', 'facts_hash', 'report_hash')):
            raise ValueError('结果包身份/证据摘要与数据库不一致')
        notify(dict(stage='REVIEWS', message='核对并保留完整人工历史与分析记录', completed=None, total=None, unit=None))
        events = _review_events(stage/'reviews.db', binding)
        # Rebuild untrusted reviews into our schema before any write/query with
        # a writable connection. Imported SQL/triggers are never executed.
        clean = ReviewStore(stage/'clean-reviews.db', binding)
        copy_prior_decisions(stage/'reviews.db',stage/'clean-reviews.db',provider)
        clean.merge(events, fingerprint_for=DiffReviewEvidence(stage, provider, progress=progress).fingerprint)
        copy_ai_receipts(stage/'reviews.db', stage/'clean-reviews.db')
        (stage/'reviews.db').unlink()
        (stage/'clean-reviews.db').replace(stage/'reviews.db')
        destination = no_links(data/'scans'/binding['scan_id'])
        if destination.exists():
            notify(dict(stage='VERIFY_EXISTING', message='核对已有归档后合并完整历史', completed=None, total=None, unit=None))
            # The incoming private file has just passed every deep check. If
            # the existing database is byte-identical under a pinned rollback
            # transaction, repeating those same checks has no extra information.
            # Different bytes or WAL still require independent deep validation.
            pinned = resources.enter_context(closing(connect_readonly(destination/'scan.db')))
            pinned.execute('BEGIN')
            pinned.execute('SELECT name FROM sqlite_master').fetchall()
            if (pinned.execute('PRAGMA journal_mode').fetchone()[0] in {'delete','truncate','persist'}
                    and sha256(destination/'scan.db', progress=progress) == records['scan.db']['sha256']):
                existing = EvidenceProvider(destination/'scan.db').metadata()
            else:
                existing = EvidenceProvider(destination/'scan.db').validate(deep=True, progress=progress)
            if any(existing[k] != binding[k] for k in ('scan_id', 'project_id', 'facts_hash', 'report_hash')):
                raise ValueError('扫描ID已存在但完整证据不同；原归档保持不变')
            # Publish immutable objects first. A later failure can leave an
            # unreachable object, never a missing reference or overwritten file.
            for source in (stage/'evidence').glob('*'):
                target=no_links(destination/'evidence'/source.name)
                target.parent.mkdir(exist_ok=True)
                if target.exists():
                    if sha256(target, progress=progress)!=source.name:
                        raise ValueError('已有内容寻址对象损坏，拒绝合并')
                else:
                    os.link(source,target)
            store=ReviewStore(destination/'reviews.db',existing)
            manifest_path=destination/'manifest.json'
            old_bytes=manifest_path.read_bytes() if manifest_path.is_file() else None
            local=json.loads(old_bytes) if old_bytes else dict(format='ECRA_REPORT',**existing)
            indices=set(local.get('audit_indices',[])+manifest.get('audit_indices',[]))
            indices.update(value for value in (local.get('audit_index'),manifest.get('audit_index')) if value)
            local['audit_indices']=sorted(indices)
            try:
                notify(dict(stage='PUBLISH', message='合并已验证的证据与人工历史', completed=None, total=None, unit=None))
                with store.connection() as conn:
                    copy_ai_receipts(stage/'reviews.db',destination/'reviews.db',_connection=conn)
                    copy_prior_decisions(stage/'reviews.db',destination/'reviews.db',provider,_connection=conn)
                    imported=store.merge(events,fingerprint_for=DiffReviewEvidence(destination).fingerprint,_connection=conn)
                    from .common import write_json
                    write_json(manifest_path,local)
            except BaseException:
                if old_bytes is not None:
                    from .common import replace_file
                    pending=manifest_path.with_suffix('.rollback-pending')
                    pending.write_bytes(old_bytes);replace_file(pending,manifest_path)
                raise
            return dict(scan_id=binding['scan_id'], imported_events=imported, repeated=True, integrity_verified=True)
        notify(dict(stage='PACKAGE_HASH', message='记录完整结果包校验摘要', completed=None, total=None, unit=None))
        origin = sha256(package, progress=progress)
        (stage/'manifest.json').write_text(json.dumps(dict(manifest, import_origin=origin), ensure_ascii=False, indent=2), encoding='utf-8')
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Rename only a fully validated isolated directory; failures above
        # cannot alter any existing scan or human decision.
        notify(dict(stage='PUBLISH', message='发布完整性已验证的归档', completed=None, total=None, unit=None))
        stage.rename(destination)
        return dict(scan_id=binding['scan_id'], imported_events=len(events), repeated=False, integrity_verified=True)


@guarded_operation(lambda args:scan_data_root(args['scan_directory']))
def export_delta(scan_directory, destination, *, progress=None):
    source, destination = no_links(scan_directory), no_links(destination)
    provider = EvidenceProvider(source/'scan.db')
    binding = provider.validate(progress=progress)
    events = _review_events(source/'reviews.db', binding)
    payload = dict(format='ECRA_REVIEW_DELTA', version=1,
                   binding={key: binding[key] for key in ('scan_id', 'project_id', 'facts_hash', 'report_hash')}, events=events)
    with closing(sqlite3.connect((source/'reviews.db').resolve().as_uri()+'?mode=ro',uri=True)) as conn:
        prior=[list(r) for r in conn.execute('SELECT * FROM prior_decisions ORDER BY symbol_id,source_scan')]
        if prior:
            payload['prior_decisions']=prior
    # Validate the same lineage that the receiving computer will require.
    with tempfile.TemporaryDirectory(prefix='ecra delta check ',dir=destination.parent if destination.parent.exists() else None) as folder:
        check=ReviewStore(Path(folder)/'reviews.db',binding)
        with check.connection() as conn:
            copy_prior_rows(payload.get('prior_decisions',[]),conn,provider)
            check.merge(events,fingerprint_for=DiffReviewEvidence(source, provider, progress=progress).fingerprint,_connection=conn)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='ecra delta ', dir=destination.parent) as folder:
        temp = Path(folder)/'delta.pending'
        temp.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding='utf-8')
        os.link(temp, destination)
    return dict(events=len(events), scan_id=binding['scan_id'])


def import_delta(package, scan_directory, *, max_bytes=256*1024**2):
    if Path(package).stat().st_size>max_bytes:
        raise ValueError('人工增量包超出大小预算')
    payload = json.loads(Path(package).read_text(encoding='utf-8'))
    if payload.get('format') != 'ECRA_REVIEW_DELTA' or payload.get('version') != 1:
        raise ValueError('未知人工增量包版本')
    provider = EvidenceProvider(Path(scan_directory)/'scan.db')
    binding = provider.validate()
    if payload.get('binding') != {key: binding[key] for key in ('scan_id', 'project_id', 'facts_hash', 'report_hash')}:
        raise ValueError('增量包不属于此扫描/证据版本，需重新确认')
    if not isinstance(payload.get('events'), list):
        raise ValueError('增量包缺少完整人工事件')
    store=ReviewStore(Path(scan_directory)/'reviews.db', binding)
    with store.connection() as conn:
        copy_prior_rows(payload.get('prior_decisions',[]),conn,provider)
        imported=store.merge(payload['events'],fingerprint_for=DiffReviewEvidence(scan_directory, provider).fingerprint,_connection=conn)
    return dict(imported_events=imported, scan_id=binding['scan_id'])
