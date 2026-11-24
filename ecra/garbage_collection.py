"""Reference-based cleanup with an inspected proposal and recoverable quarantine.

Candidates are unreferenced content objects, disposable TU caches and exact
review working copies bound to verified, published events.
"""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import uuid

from .common import write_json
from .report_package import sha256, IDENTITY, validate_objects
from .scan_store import EvidenceProvider, connect_readonly
from .storage_activity import DataActivity
from .workspace import no_links, studio_data_root

HASH=re.compile(r'[a-f0-9]{64}\Z')
TOKENS=re.compile(rb'[a-f0-9]{64}',re.I)
SCHEMA="""
CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE candidates(ordinal INTEGER PRIMARY KEY,relative TEXT UNIQUE NOT NULL,
 category TEXT NOT NULL,size INTEGER NOT NULL,sha256 TEXT NOT NULL,state TEXT NOT NULL);
"""


def _meta(conn,key,value=None):
    if value is None:
        row=conn.execute('SELECT value FROM meta WHERE key=?',(key,)).fetchone()
        return json.loads(row[0]) if row else None
    conn.execute('INSERT OR REPLACE INTO meta VALUES (?,?)',(key,json.dumps(value,ensure_ascii=False)))


def _owned(root,relative):
    value=Path(relative)
    if value.is_absolute() or '..' in value.parts:
        raise ValueError('整理目标路径越界')
    path=no_links(root/value)
    if not path.is_relative_to(root) or path==root:
        raise ValueError('整理目标越出当前数据根')
    return path


def _tokens(conn,table,column,refs,proof):
    # Large strings are read in fixed byte segments, not an all-facts load.
    expression='CAST("'+column+'" AS BLOB)'
    for ident,size,small in conn.execute('SELECT rowid,length('+expression+'),CASE WHEN length('+expression+')<=65536 THEN '+expression+' ELSE NULL END FROM "'+table+'" WHERE '+expression+' IS NOT NULL ORDER BY rowid'):
        proof.update(str(ident).encode()+b'\0')
        previous=b''
        if small is not None:
            pieces=(small,)
        else:
            pieces=(conn.execute('SELECT substr('+expression+',?,1048576) FROM "'+table+'" WHERE rowid=?',(offset+1,ident)).fetchone()[0]
                    for offset in range(0,size,1048576))
        for part in pieces:
            proof.update(part)
            refs.update(match.decode('ascii').lower() for match in TOKENS.findall(previous+part))
            previous=part[-63:]
        proof.update(b'\0')


def _references(data, *, duplicates=None, relocated=None):
    refs=set();proof=hashlib.sha256()
    # Stopped/failed scans still own their TU recovery cache. Rebuilding a
    # disposable cache is allowed only after no resumable task references it.
    # Be conservative at project granularity when an old checkpoint has no
    # individual cache-key manifest; never discard the 350 committed TUs.
    protected=set()
    tasks=no_links(data/'work/tasks')
    for marker in tasks.glob('*/task.json'):
        value=json.loads(no_links(marker).read_text(encoding='utf-8'))
        if value.get('mode','scan')=='scan' and value.get('state') in {'RUNNING','STOP_REQUESTED','FAILED','INTERRUPTED'}:
            protected.add(value.get('project_id',''))
    scans=no_links(data/'scans')
    for marker in scans.glob('*/storage.json'):
        if not no_links(marker.parent/'manifest.json').is_file():
            protected.add(json.loads(no_links(marker).read_text(encoding='utf-8')).get('project_id',''))
    projects=no_links(data/'projects')
    for marker in projects.glob('*/project.json'):
        value=json.loads(no_links(marker).read_text(encoding='utf-8'))
        result=no_links(value.get('output_root',marker.parent/'results'))
        if not result.is_relative_to(marker.parent):continue
        run=result/'run.json'
        if run.is_file() and json.loads(no_links(run).read_text(encoding='utf-8')).get('state') in {'RUNNING','FAILED','INTERRUPTED'}:
            protected.add(value.get('project_id',''))
    for project in sorted(protected):
        if not project:continue
        token='CHECKPOINT_PROJECT:'+project;refs.add(token);proof.update(token.encode()+b'\0')
    if scans.exists():
        for folder in sorted(scans.iterdir()):
            no_links(folder)
            database=no_links(folder/'scan.db')
            if not database.is_file():
                continue
            provider=EvidenceProvider(database)
            metadata=provider.validate()
            if metadata['scan_id']!=folder.name:
                raise ValueError('扫描目录与库身份不一致，停止整理')
            database_hash=sha256(database)
            manifest=no_links(folder/'manifest.json')
            value=json.loads(manifest.read_text(encoding='utf-8')) if manifest.is_file() else {}
            expected=value.get('scan_sha256') or value.get('files',{}).get('scan.db',{}).get('sha256')
            bound = (value.get('format') in {'ECRA_LOCAL_SCAN','ECRA_REPORT','ECRA_LEGACY_IMPORT'}
                     and value.get('scan_id') == metadata['scan_id'] and bool(expected)
                     and all(value[key] == metadata.get(key) for key in ('project_id','facts_hash','report_hash')
                             if key in value))
            intents = no_links(folder/'.ecra-receipt-writes')
            if intents.is_dir() and any(intents.iterdir()):
                bound = False  # A complete pre-rename result may still be replayed.
                proof.update(b'unresolved-receipt-write')
            if not bound:
                refs.add('HOLD_OBJECTS:'+folder.name)
            if expected:
                if database_hash!=expected:raise ValueError('扫描库摘要改变/损坏，停止整理')
            else:
                provider.validate(deep=True)
            validate_objects(folder,value)
            proof.update(folder.name.encode()+bytes.fromhex(database_hash))
            with closing(connect_readonly(database)) as conn:
                _tokens(conn,'nodes','value',refs,proof)
            indices=set()
            if manifest.is_file():
                raw=manifest.read_bytes();proof.update(raw)
                refs.update(value.decode().lower() for value in TOKENS.findall(raw))
                value=json.loads(raw)
                indices=set(value.get('audit_indices',[]))
                if value.get('audit_index'):
                    indices.add(value['audit_index'])
                for ident in indices:
                    if not HASH.fullmatch(ident):
                        raise ValueError('审计索引身份错误，停止整理')
                    path=no_links(folder/'evidence'/ident)
                    if sha256(path)!=ident:
                        raise ValueError('审计索引缺失/损坏，停止整理')
                    _index_references(folder, json.loads(path.read_bytes()), refs)
            reviews=no_links(folder/'reviews.db')
            if reviews.is_file():
                with closing(sqlite3.connect(reviews.resolve().as_uri()+'?mode=ro',uri=True)) as conn:
                    conn.execute('PRAGMA query_only=ON');conn.execute('PRAGMA trusted_schema=OFF');conn.execute('BEGIN')
                    from .scan_persistence import validate_review_binding
                    validate_review_binding(folder, provider)
                    if conn.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                        raise ValueError('复核库完整性校验失败，保留工作副本')
                    for table,column in [('events','payload'),('ai_events','payload'),('ai_snapshots','payload'),('prior_decisions','payload'),('positions','value')]:
                        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone():
                            _tokens(conn,table,column,refs,proof)
                    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ai_events'").fetchone():
                        for (hashed,) in conn.execute("SELECT hash FROM ai_events WHERE json_type(payload,'$.archived_files')='object'"):
                            refs.add(hashed)  # The event's digest is also the immutable .result.json object name.
                        if bound and duplicates is not None:
                            _review_duplicates(folder, conn, duplicates, relocated)
                        # An orphan result can precede the SQLite commit. Its immutable
                        # receipt and all of its original objects are recovery roots.
                        for receipt in (folder/'review').glob('*.result.json'):
                            raw = no_links(receipt).read_bytes()
                            refs.add(hashlib.sha256(raw).hexdigest())
                            refs.update(value.decode().lower() for value in TOKENS.findall(raw))
                            proof.update(raw)
            for path in (folder/'diagnostics'/'review-recovery').glob('*.json'):
                raw = no_links(path).read_bytes()
                proof.update(raw)
                refs.update(value.decode().lower() for value in TOKENS.findall(raw))
            # Older checkpoint writers replaced manifest.audit_index without
            # recording its predecessor. An authentic historical index is still
            # evidence and must never be dropped as an unreferenced blob.
            for obj in (folder/'evidence').glob('*'):
                if obj.name not in indices and HASH.fullmatch(obj.name):
                    index = _historical_index(no_links(obj))
                    if index is not None:
                        if sha256(obj) != obj.name:
                            raise ValueError('历史审计索引摘要损坏，保留现场')
                        refs.add(obj.name)
                        proof.update(obj.name.encode())
                        _index_references(folder, index, refs)
    return refs,proof.hexdigest()


def _historical_index(path):
    # Both encodings were produced by the v1 audit writer and legacy importer.
    with path.open('rb') as stream:
        prefix = stream.read(128).lstrip()
        if not re.match(rb'\{\s*"(files|version)"\s*:', prefix):
            return None
        stream.seek(0)
        try:
            index = json.load(stream)
        except (ValueError, UnicodeError):
            return None
    return index if isinstance(index,dict) and index.get('version')==1 and isinstance(index.get('files'),dict) else None


def _index_references(folder, index, refs):
    for name, entry in index['files'].items():
        hashed=entry['sha256']
        if not HASH.fullmatch(hashed):
            raise ValueError('历史审计对象引用无效')
        refs.add(hashed)
        if name.startswith('diagnostics/review-recovery/') or (name.startswith('review/') and name.endswith('.result.json')):
            nested = no_links(folder/'evidence'/hashed)
            if sha256(nested) != hashed:
                raise ValueError('历史收据引用损坏')
            with nested.open('rb') as stream:
                previous = b''
                for block in iter(lambda: stream.read(1048576), b''):
                    refs.update(token.decode().lower() for token in TOKENS.findall(previous+block))
                    previous = block[-63:]


def _review_duplicates(folder, conn, duplicates, relocated):
    from .review_archive import duplicate_files, validate_event_archives
    from .scan_persistence import snapshot_head
    snapshot = snapshot_head(conn)
    if snapshot.get('ai_events_version') != 2:
        return
    validate_event_archives(folder, folder/'reviews.db')
    for fid, raw in conn.execute(
            "SELECT a.finding_id,a.payload FROM ai_events a WHERE a.sequence<=? "
            "AND a.state IN ('DONE','TECH_FAILED') AND json_type(a.payload,'$.archived_files')='object' "
            "AND (SELECT state FROM ai_events WHERE finding_id=a.finding_id AND sequence<=? "
            "ORDER BY sequence DESC LIMIT 1) IN ('DONE','TECH_FAILED')",
            (snapshot['watermark'], snapshot['watermark'])):
        row = json.loads(raw)
        if row.get('finding_id') != fid or 'review_base_sequence' not in row:
            continue
        for path, hashed in duplicate_files(folder, row, aliases=True, relocated=relocated):
            duplicates[path] = hashed


def _checkpoint_cache(data,path,refs):
    relative=path.relative_to(data)
    if len(relative.parts)<2 or relative.parts[0]!='projects':return False
    marker=no_links(data/'projects'/relative.parts[1]/'project.json')
    value=json.loads(marker.read_text(encoding='utf-8'))
    return 'CHECKPOINT_PROJECT:'+str(value.get('project_id')) in refs


def _role(data,path,category):
    relative=path.relative_to(data);parts=relative.parts
    if category=='UNREFERENCED_OBJECT':
        valid=len(parts)==4 and parts[0]=='scans' and IDENTITY.fullmatch(parts[1]) and parts[2]=='evidence' and HASH.fullmatch(parts[3])
    elif category=='REVIEW_DUPLICATE':
        valid=len(parts)==4 and parts[0]=='scans' and IDENTITY.fullmatch(parts[1]) and parts[2]=='review'
    elif category=='TU_CACHE':
        valid=False
        if (len(parts)>=5 and parts[0]=='projects' and parts[-2]=='tu-v1'
                and path.suffix in {'.facts','.json'} and HASH.fullmatch(path.stem)):
            owner=no_links(data/'projects'/parts[1])
            marker=owner/'project.json'
            if marker.is_file():
                saved=json.loads(marker.read_text(encoding='utf-8'))
                result=no_links(saved.get('output_root',owner/'results'))
                valid=result.is_relative_to(owner) and any(path.is_relative_to(cache) for cache in _cache_roots(result))
    else:
        valid=False
    if not valid:
        raise ValueError('目标不是可回收的受控对象/缓存: '+str(relative))
    return relative.as_posix()


def _cache_roots(result):
    """Follow the existing resolver's owned result/cache layout, including bases."""
    yield no_links(result/'cache')
    for path in result.glob('git_diff/artifacts/*/cache'):
        yield no_links(path)


def preview(data_root):
    data=studio_data_root(data_root)
    ident=uuid.uuid4().hex
    folder=no_links(data/'work/gc'/ident);folder.mkdir(parents=True)
    database=folder/'preview.db'
    with DataActivity(data),closing(sqlite3.connect(database)) as conn,conn:
        conn.execute('PRAGMA synchronous=FULL');conn.executescript(SCHEMA)
        duplicates={}
        refs,token=_references(data,duplicates=duplicates)
        _meta(conn,'id',ident);_meta(conn,'root',str(data));_meta(conn,'references',token);_meta(conn,'state','PREVIEW')
        def candidate(path,category):
            path=no_links(path)
            if not path.is_file() or path.stat().st_nlink>1 or path.stem.lower() in refs:
                return
            if category=='TU_CACHE' and _checkpoint_cache(data,path,refs):return
            relative=_role(data,path,category)
            hashed=sha256(path)
            if hashed in refs:
                return
            if category=='UNREFERENCED_OBJECT' and hashed!=path.name:
                raise ValueError('未引用对象已损坏；先修复后整理: '+relative)
            conn.execute('INSERT INTO candidates(relative,category,size,sha256,state) VALUES (?,?,?,?,?)',
                         (relative,category,path.stat().st_size,hashed,'SOURCE'))
        for path,hashed in duplicates.items():
            if path.stat().st_nlink==1:
                conn.execute('INSERT INTO candidates(relative,category,size,sha256,state) VALUES (?,?,?,?,?)',
                    (_role(data,path,'REVIEW_DUPLICATE'),'REVIEW_DUPLICATE',path.stat().st_size,hashed,'SOURCE'))
        scans=no_links(data/'scans')
        if scans.exists():
            for evidence in scans.glob('*/evidence'):
                no_links(evidence)
                # A partial failed publication is retained for diagnosis.
                if not all(no_links(evidence.parent/name).is_file() for name in ('manifest.json','scan.db','reviews.db')):
                    continue
                if 'HOLD_OBJECTS:'+evidence.parent.name in refs:
                    continue
                for path in evidence.iterdir():
                    if HASH.fullmatch(path.name):candidate(path,'UNREFERENCED_OBJECT')
        projects=no_links(data/'projects')
        if projects.exists():
            for owner in projects.glob('*/project.json'):
                no_links(owner)
                value=json.loads(owner.read_text(encoding='utf-8'))
                if value.get('schema_version')!=1 or not HASH.fullmatch(str(value.get('project_id',''))):
                    continue
                result=no_links(value.get('output_root',owner.parent/'results'))
                if not result.is_relative_to(owner.parent):continue
                for base in _cache_roots(result):
                    for cache in base.glob('**/tu-v1'):
                        no_links(cache)
                        for path in cache.iterdir():
                            if path.suffix in {'.facts','.json'} and HASH.fullmatch(path.stem):candidate(path,'TU_CACHE')
    return status(data,ident)


def _open(data_root,ident):
    data=studio_data_root(data_root)
    if not isinstance(ident,str) or not IDENTITY.fullmatch(ident):
        raise ValueError('整理预览身份无效')
    folder=no_links(data/'work/gc'/ident)
    database=no_links(folder/'preview.db')
    if not database.is_file():raise ValueError('整理预览不存在')
    conn=sqlite3.connect(database);conn.execute('PRAGMA trusted_schema=OFF');conn.execute('PRAGMA synchronous=FULL')
    if _meta(conn,'root')!=str(data) or _meta(conn,'id')!=ident:
        conn.close();raise ValueError('整理预览不属于当前数据根')
    return data,folder,conn


def status(data_root,ident,*,offset=0,limit=50):
    if offset<0 or not 1<=limit<=200:raise ValueError('整理分页无效')
    data,folder,conn=_open(data_root,ident)
    with closing(conn):
        total,size=conn.execute('SELECT count(*),coalesce(sum(size),0) FROM candidates').fetchone()
        items=[dict(zip(('ordinal','relative','category','size','sha256','state'),row)) for row in conn.execute(
            'SELECT ordinal,relative,category,size,sha256,state FROM candidates ORDER BY ordinal LIMIT ? OFFSET ?',(limit,offset))]
        groups=[dict(zip(('category','state','files','logical_bytes'),row)) for row in conn.execute(
            'SELECT category,state,count(*),coalesce(sum(size),0) FROM candidates GROUP BY category,state')]
        return dict(id=ident,state=_meta(conn,'state'),files=total,logical_bytes=size,groups=groups,items=items,offset=offset,
                    next_offset=offset+len(items) if offset+len(items)<total else None,
                    reason='已提交复核的可验证工作副本、未引用对象和无恢复任务引用的可重建TU缓存；未放弃的失败/中断检查点保留。逻辑字节不是保证释放的物理空间。')


def quarantine(data_root,ident):
    data,folder,conn=_open(data_root,ident)
    with closing(conn),DataActivity(data,exclusive=True):
        if _meta(conn,'state')!='PREVIEW':raise ValueError('该预览已执行；请查看恢复/释放状态')
        duplicates={}
        refs,token=_references(data,duplicates=duplicates)
        if token!=_meta(conn,'references'):raise ValueError('预览后结果或人工记录已变化，请重新预览')
        for relative,category,size,hashed in conn.execute('SELECT relative,category,size,sha256 FROM candidates'):
            source=_owned(data,relative);_role(data,source,category)
            if category=='TU_CACHE' and _checkpoint_cache(data,source,refs):raise ValueError('出现恢复检查点引用，保留TU缓存')
            if category=='REVIEW_DUPLICATE':
                protected=duplicates.get(source)!=hashed
            else:
                protected=source.stem.lower() in refs or hashed in refs
            if protected or source.stat().st_nlink>1 or source.stat().st_size!=size or sha256(source)!=hashed:
                raise ValueError('预览目标已变化或出现引用，未执行整理')
        trash=no_links(folder/'trash');trash.mkdir(exist_ok=True)
        _meta(conn,'state','MOVING');conn.commit()
        try:
            for ordinal,relative in conn.execute('SELECT ordinal,relative FROM candidates ORDER BY ordinal'):
                source=_owned(data,relative);target=_owned(data,(trash/str(ordinal)).relative_to(data))
                source.rename(target)
                conn.execute("UPDATE candidates SET state='QUARANTINE' WHERE ordinal=?",(ordinal,));conn.commit()
            _meta(conn,'state','QUARANTINED');conn.commit()
        except BaseException:
            _restore(data,folder,conn)
            raise
    return status(data,ident)


def _restore(data,folder,conn):
    conflicts=[]
    for ordinal,relative,category,hashed in conn.execute('SELECT ordinal,relative,category,sha256 FROM candidates ORDER BY ordinal DESC'):
        source=_owned(data,relative);_role(data,source,category)
        target=_owned(data,(folder/'trash'/str(ordinal)).relative_to(data))
        if not target.is_file():continue
        if sha256(target)!=hashed:raise ValueError('回收暂存内容损坏，保留现场')
        if source.exists():
            if sha256(source)!=hashed:conflicts.append(relative);continue
        else:
            source.parent.mkdir(parents=True,exist_ok=True);target.rename(source)
        conn.execute("UPDATE candidates SET state='RESTORED' WHERE ordinal=?",(ordinal,));conn.commit()
    _meta(conn,'state','RESTORE_CONFLICT' if conflicts else 'RESTORED');_meta(conn,'conflicts',conflicts);conn.commit()


def restore(data_root,ident):
    data,folder,conn=_open(data_root,ident)
    with closing(conn),DataActivity(data,exclusive=True):
        if _meta(conn,'state') not in {'MOVING','QUARANTINED','RESTORE_CONFLICT'}:raise ValueError('当前状态不可恢复')
        _restore(data,folder,conn)
    return status(data,ident)


def purge(data_root,ident):
    data,folder,conn=_open(data_root,ident)
    with closing(conn),DataActivity(data,exclusive=True):
        if _meta(conn,'state') not in {'QUARANTINED','PURGING'}:raise ValueError('请先预览并隔离可回收数据')
        relocated={_owned(data,relative):no_links(folder/'trash'/str(ordinal))
                   for ordinal,relative in conn.execute("SELECT ordinal,relative FROM candidates WHERE category='REVIEW_DUPLICATE'")}
        duplicates={}
        for (ordinal,) in conn.execute("SELECT ordinal FROM candidates WHERE category='UNREFERENCED_OBJECT' AND state='QUARANTINE'"):
            target=no_links(folder/'trash'/str(ordinal))
            if target.is_file() and _historical_index(target) is not None:
                raise ValueError('旧隔离批次包含历史审计索引，请先恢复整个批次后重新预览')
        refs,_=_references(data,duplicates=duplicates,relocated=relocated)
        _meta(conn,'state','PURGING');conn.commit()
        for ordinal,relative,category,hashed,state in conn.execute('SELECT ordinal,relative,category,sha256,state FROM candidates ORDER BY ordinal'):
            if state in {'PURGED','RESTORED','PROTECTED'}:continue
            source=_owned(data,relative);_role(data,source,category)
            target=_owned(data,(folder/'trash'/str(ordinal)).relative_to(data))
            if target.is_file():
                if sha256(target)!=hashed:raise ValueError('隔离文件损坏；停止释放')
                missing_authority = category=='UNREFERENCED_OBJECT' and not all(
                    no_links(source.parent.parent/name).is_file() for name in ('scan.db','reviews.db','manifest.json'))
                uncertified = category=='UNREFERENCED_OBJECT' and 'HOLD_OBJECTS:'+source.parent.parent.name in refs
                protected = missing_authority or uncertified or (duplicates.get(source)!=hashed if category=='REVIEW_DUPLICATE'
                             else hashed in refs or source.stem.lower() in refs or
                             (category=='TU_CACHE' and _checkpoint_cache(data,source,refs)))
                if protected:
                    if not source.exists():source.parent.mkdir(parents=True,exist_ok=True);target.rename(source)
                    elif sha256(source)!=hashed:raise ValueError('出现新引用且原路径被占用，保留暂存')
                    conn.execute("UPDATE candidates SET state='PROTECTED' WHERE ordinal=?",(ordinal,));conn.commit();continue
                target.unlink()  # verified absolute path remains under this GC job
            conn.execute("UPDATE candidates SET state='PURGED' WHERE ordinal=?",(ordinal,));conn.commit()
        _meta(conn,'state','PURGED');conn.commit()
    return status(data,ident)
