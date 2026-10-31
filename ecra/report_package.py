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
from .scan_store import EvidenceProvider, connect_readonly, SCHEMA, SCHEMA_VERSION, SUPPORTED_VERSIONS
from .workspace import no_links
from .storage_activity import guarded_operation, scan_data_root

IDENTITY = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z')
OBJECT = re.compile(r'evidence/[a-f0-9]{64}\Z')


def sha256(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            value.update(block)
    return value.hexdigest()


def _safe_name(name):
    if name in {'scan.db', 'reviews.db', 'manifest.json'} or OBJECT.fullmatch(name):
        p = PurePosixPath(name)
        if not p.is_absolute() and '..' not in p.parts and '\\' not in name and ':' not in name:
            return name
    raise ValueError('结果包包含不允许的路径: ' + name[:200])


def snapshot(source, destination):
    with closing(sqlite3.connect(Path(source).resolve().as_uri()+'?mode=ro', uri=True)) as src, \
            closing(sqlite3.connect(destination)) as dst:
        src.execute('PRAGMA trusted_schema=OFF')
        src.backup(dst)
        if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('SQLite 一致快照完整性失败')


def _schema(conn):
    return sorted(tuple(row) for row in conn.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"))


def validate_schema(path, sql, version=0):
    with closing(sqlite3.connect(':memory:')) as expected, \
            closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True)) as actual:
        actual.execute('PRAGMA trusted_schema=OFF')
        expected.executescript(sql)
        if _schema(actual) != _schema(expected) or actual.execute('PRAGMA user_version').fetchone()[0] != version:
            raise ValueError('结果包数据库结构未知或已被修改；拒绝执行/导入')
        if actual.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or list(actual.execute('PRAGMA foreign_key_check')):
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
    """Historical confirmations stay bound to their old evidence, never SAFE here."""
    from .human_reviews import SCHEMA as REVIEW_SCHEMA
    with ExitStack() as stack:
        src=stack.enter_context(closing(sqlite3.connect(Path(source).resolve().as_uri()+'?mode=ro',uri=True)))
        src.execute('PRAGMA trusted_schema=OFF')
        if not src.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='prior_decisions'").fetchone():
            return
        dst=_connection
        if dst is None:
            dst=stack.enter_context(closing(sqlite3.connect(destination)));stack.enter_context(dst)
        binding=provider.metadata()
        for row in src.execute('SELECT symbol_id,fingerprint,source_scan,source_fingerprint,hash,payload FROM prior_decisions ORDER BY symbol_id,source_scan'):
            sid,current,source_scan,source_fingerprint,hashed,raw=row
            if hashlib.sha256(raw.encode()).hexdigest()!=hashed or provider.fingerprint(sid)!=current:
                raise ValueError('历史确认与当前证据引用不一致')
            value=json.loads(raw)
            if not isinstance(value,dict) or set(value)!={'binding','symbol_id','fingerprint','events'}:
                raise ValueError('历史确认载荷无效')
            old=value['binding']
            if (not isinstance(old,dict) or set(old)!={'scan_id','project_id','facts_hash','report_hash'}
                    or old['scan_id']!=source_scan or old['project_id']!=binding['project_id']
                    or source_scan==binding['scan_id'] or value['symbol_id']!=sid or value['fingerprint']!=source_fingerprint
                    or not isinstance(value['events'],list)):
                raise ValueError('历史确认扫描/对象身份不一致')
            check=ReviewStore.__new__(ReviewStore);check.binding=old
            with closing(sqlite3.connect(':memory:')) as proof:
                proof.executescript(REVIEW_SCHEMA)
                for event in sorted(value['events'],key=lambda e:(e['revision'],e['event_id'])):
                    check._validate(event)
                    if event['symbol_id']!=sid or event['fingerprint']!=source_fingerprint:
                        raise ValueError('历史确认引用其他对象/证据')
                    check._insert(proof,event)
            existing=dst.execute('SELECT symbol_id,fingerprint,source_scan,source_fingerprint,hash,payload FROM prior_decisions WHERE symbol_id=? AND source_scan=?',(sid,source_scan)).fetchone()
            if existing is not None and existing!=row:
                raise ValueError('同一历史确认来源包含不同内容')
            if existing is None:
                dst.execute('INSERT INTO prior_decisions VALUES (?,?,?,?,?,?)',row)


def validate_objects(directory, manifest, *, max_raw_bytes=128*1024**3):
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
            if target.stat().st_size != record.get('size') or sha256(target) != record['sha256']:
                raise ValueError('审计收据对象缺失或已损坏')
    consumed = 0
    # Query scalar reference fields only; source text is never loaded here.
    with closing(connect_readonly(directory/'scan.db')) as conn:
        root = conn.execute("SELECT e.child FROM roots r JOIN edges e ON e.parent=r.node WHERE r.name='provenance' AND e.key='archived_sources'").fetchone()
        if root is None:
            return
        from .scan_store import _decode
        for (node,) in conn.execute('SELECT child FROM edges WHERE parent=? ORDER BY ordinal', (root[0],)):
            fields = {key:_decode(kind,value) for key,kind,value in conn.execute(
                "SELECT e.key,n.kind,n.value FROM edges e JOIN nodes n ON n.id=e.child WHERE e.parent=? AND e.key IN ('raw_object','codec','sha256','size')", (node,))}
            if 'raw_object' not in fields:
                continue  # v1 source bytes are embedded directly in the graph
            if (not OBJECT.fullmatch('evidence/'+str(fields['raw_object'])) or fields.get('codec') != 'gzip'
                    or type(fields.get('size')) is not int or fields['size'] < 0):
                raise ValueError('归档源码对象描述无效')
            target = directory/'evidence'/fields['raw_object']
            if sha256(target) != fields['raw_object']:
                raise ValueError('归档源码压缩对象缺失/损坏')
            hashed, size = hashlib.sha256(), 0
            with gzip.open(target,'rb') as stream:
                for block in iter(lambda:stream.read(1024*1024),b''):
                    size += len(block); consumed += len(block)
                    if size > fields['size'] or consumed > max_raw_bytes:
                        raise ValueError('归档源码展开超过声明/预算')
                    hashed.update(block)
            if size != fields['size'] or hashed.hexdigest() != fields.get('sha256'):
                raise ValueError('归档源码原始字节摘要不一致')


@guarded_operation(lambda args:scan_data_root(args['scan_directory']))
def export_report(scan_directory, destination):
    source, destination = no_links(scan_directory), no_links(destination)
    provider = EvidenceProvider(source/'scan.db')
    binding = provider.validate(deep=True)
    if destination.exists():
        raise FileExistsError('导出目标已存在，请另存新文件')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='ecra export ', dir=destination.parent) as folder:
        stage = Path(folder)
        snapshot(source/'scan.db', stage/'scan.db')
        snapshot(source/'reviews.db', stage/'reviews.db')
        events = _review_events(stage/'reviews.db', binding)
        # Validate all original immutable events in a fresh trusted schema.
        check = ReviewStore(stage/'check.db', binding)
        check.merge(events, fingerprint_for=provider.fingerprint)
        copy_ai_receipts(stage/'reviews.db', stage/'check.db')
        copy_prior_decisions(stage/'reviews.db',stage/'check.db',provider)
        files = {'scan.db': stage/'scan.db', 'reviews.db': stage/'reviews.db'}
        evidence = source/'evidence'
        if evidence.exists():
            no_links(evidence)
            for item in evidence.iterdir():
                no_links(item)
                name = _safe_name('evidence/' + item.name)
                if not item.is_file() or sha256(item) != item.name:
                    raise ValueError('归档证据对象损坏')
                files[name] = item
        with closing(connect_readonly(source/'scan.db')) as conn:
            schema_version = conn.execute('PRAGMA user_version').fetchone()[0]
        manifest = dict(format='ECRA_REPORT', version=1, schema_version=schema_version,
            scan_id=binding['scan_id'], project_id=binding['project_id'], facts_hash=binding['facts_hash'],
            report_hash=binding['report_hash'], capabilities=['archived_evidence', 'human_decisions'],
            source_reverification=False, files={name: dict(size=path.stat().st_size, sha256=sha256(path)) for name, path in files.items()})
        local_manifest = source/'manifest.json'
        if local_manifest.is_file():
            local = json.loads(local_manifest.read_text(encoding='utf-8'))
            if local.get('audit_index'):
                manifest['audit_index'] = local['audit_index']
                if 'evidence/'+local['audit_index'] not in files:
                    raise ValueError('缺少完整审计对象索引')
            if local.get('audit_indices'):
                manifest['audit_indices']=local['audit_indices']
        validate_objects(source, manifest)
        archive = stage/'result.pending'
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zipped:
            zipped.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, sort_keys=True))
            for name, path in files.items():
                zipped.write(path, name)
        # Export is exclusive; existing user packages are never overwritten.
        # Atomic and exclusive on NTFS/ext4. A process crash must not expose a
        # partially copied package at the final user-visible filename.
        os.link(archive, destination)
    return manifest


@guarded_operation(lambda args:args['data_root'])
def import_report(package, data_root, *, max_bytes=128*1024**3, max_entries=100000, max_ratio=2000):
    data = no_links(data_root)
    work = no_links(data/'work'); work.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='import-', dir=work) as folder:
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
            if (manifest.get('format') != 'ECRA_REPORT' or manifest.get('version') != 1
                    or manifest.get('schema_version') not in SUPPORTED_VERSIONS):
                raise ValueError('未知结果包/schema版本，请使用匹配版本软件')
            if not all(isinstance(manifest.get(k), str) and IDENTITY.fullmatch(manifest[k]) for k in ('scan_id', 'project_id')):
                raise ValueError('结果包工程/扫描身份无效')
            records = manifest.get('files')
            if (not isinstance(records, dict) or not {'scan.db', 'reviews.db'} <= set(records)
                    or set(records) != {m.filename for m in members} - {'manifest.json'}):
                raise ValueError('结果包内容与清单不一致')
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
                    while True:
                        block = src.read(1024*1024)
                        if not block:
                            break
                        copied += len(block)
                        if copied>member.file_size:
                            raise ValueError('结果包解压数据超过声明大小')
                        dst.write(block)
                if copied != record['size'] or sha256(target) != record.get('sha256'):
                    raise ValueError('结果包 SHA-256 校验失败')
                if OBJECT.fullmatch(member.filename) and record['sha256'] != Path(member.filename).name:
                    raise ValueError('证据对象内容身份错误')
        validate_schema(stage/'scan.db', SCHEMA, manifest['schema_version'])
        provider = EvidenceProvider(stage/'scan.db')
        binding = provider.validate(deep=True)
        validate_objects(stage, manifest, max_raw_bytes=max_bytes)
        if any(manifest.get(k) != binding[k] for k in ('scan_id', 'project_id', 'facts_hash', 'report_hash')):
            raise ValueError('结果包身份/证据摘要与数据库不一致')
        events = _review_events(stage/'reviews.db', binding)
        # Rebuild untrusted reviews into our schema before any write/query with
        # a writable connection. Imported SQL/triggers are never executed.
        clean = ReviewStore(stage/'clean-reviews.db', binding)
        clean.merge(events, fingerprint_for=provider.fingerprint)
        copy_ai_receipts(stage/'reviews.db', stage/'clean-reviews.db')
        copy_prior_decisions(stage/'reviews.db',stage/'clean-reviews.db',provider)
        (stage/'reviews.db').unlink()
        (stage/'clean-reviews.db').replace(stage/'reviews.db')
        destination = no_links(data/'scans'/binding['scan_id'])
        if destination.exists():
            existing = EvidenceProvider(destination/'scan.db').validate(deep=True)
            if any(existing[k] != binding[k] for k in ('scan_id', 'project_id', 'facts_hash', 'report_hash')):
                raise ValueError('扫描ID已存在但完整证据不同；原归档保持不变')
            # Publish immutable objects first. A later failure can leave an
            # unreachable object, never a missing reference or overwritten file.
            for source in (stage/'evidence').glob('*'):
                target=no_links(destination/'evidence'/source.name)
                target.parent.mkdir(exist_ok=True)
                if target.exists():
                    if sha256(target)!=source.name:
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
                with store.connection() as conn:
                    copy_ai_receipts(stage/'reviews.db',destination/'reviews.db',_connection=conn)
                    copy_prior_decisions(stage/'reviews.db',destination/'reviews.db',provider,_connection=conn)
                    imported=store.merge(events,fingerprint_for=provider.fingerprint,_connection=conn)
                    from .common import write_json
                    write_json(manifest_path,local)
            except BaseException:
                if old_bytes is not None:
                    from .common import replace_file
                    pending=manifest_path.with_suffix('.rollback-pending')
                    pending.write_bytes(old_bytes);replace_file(pending,manifest_path)
                raise
            return dict(scan_id=binding['scan_id'], imported_events=imported, repeated=True)
        (stage/'manifest.json').write_text(json.dumps(dict(manifest, import_origin=sha256(package)), ensure_ascii=False, indent=2), encoding='utf-8')
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Rename only a fully validated isolated directory; failures above
        # cannot alter any existing scan or human decision.
        stage.rename(destination)
        return dict(scan_id=binding['scan_id'], imported_events=len(events), repeated=False)


def export_delta(scan_directory, destination):
    source, destination = no_links(scan_directory), no_links(destination)
    provider = EvidenceProvider(source/'scan.db')
    binding = provider.validate()
    events = _review_events(source/'reviews.db', binding)
    payload = dict(format='ECRA_REVIEW_DELTA', version=1,
                   binding={key: binding[key] for key in ('scan_id', 'project_id', 'facts_hash', 'report_hash')}, events=events)
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
    imported = ReviewStore(Path(scan_directory)/'reviews.db', binding).merge(payload['events'], fingerprint_for=provider.fingerprint)
    return dict(imported_events=imported, scan_id=binding['scan_id'])
