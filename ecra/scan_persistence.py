"""Canonical scan publication and explicit legacy artifact navigation.

No solver/classification code lives here. Small input/recovery receipts remain
files; complete facts and static reports have exactly one authoritative graph.
"""
from contextlib import closing,contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import uuid

from .common import write_json
from .scan_store import EvidenceProvider, publish_scan

MARKER = 'storage.json'
REPORT = 'reports/global_static_concurrency.json'
RUNTIME_KEYS = ('run_status', 'stale_reason', 'review_summary', 'review_integrity',
                'review_records', 'matrix_review_summary', 'risk_summary', 'final_conclusion',
                'safe_sample_summary', 'screened_sample_summary')
from .human_reviews import AI_SCHEMA



def is_canonical(out):
    return (Path(out)/MARKER).is_file() or (Path(out)/'scan.db').is_file()


def artifact(path):
    """Map only the two historical, exact logical names, never arbitrary JSON."""
    path = Path(path)
    if path.name == 'facts.json':
        out, name = path.parent, 'facts'
    elif path.as_posix().endswith('/'+REPORT):
        out, name = path.parent.parent, 'report'
    else:
        return None
    database = out/'scan.db'
    return (database, name) if database.is_file() else None


def exists(path):
    return Path(path).is_file() or artifact(path) is not None


def runtime(out, *, with_reviews=True):
    path = Path(out)/'reviews.db'
    if not path.is_file():
        return {}
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True)) as conn:
        conn.execute('PRAGMA trusted_schema=OFF')
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ai_snapshots'").fetchone():
            return {}
        row = conn.execute('SELECT payload FROM ai_snapshots ORDER BY sequence DESC LIMIT 1').fetchone()
        if not row:
            return {}
        value = json.loads(row[0])
        if not with_reviews:
            value.pop('reviews',None)
            return value
        if value.get('ai_events_version') == 2:
            value['reviews']=[json.loads(row[0]) for row in conn.execute(
                'SELECT a.payload FROM ai_events a WHERE a.sequence<=? AND NOT EXISTS('
                'SELECT 1 FROM ai_events newer WHERE newer.finding_id=a.finding_id AND newer.sequence>a.sequence '
                'AND newer.sequence<=?) ORDER BY a.ordinal', [value['watermark']]*2)]
        elif value.get('ai_events_version') == 1:
            rows=[]
            for reference in value['reviews']:
                record=conn.execute('SELECT finding_id,hash,payload FROM ai_events WHERE sequence=?', (reference['sequence'],)).fetchone()
                if record is None or record[:2] != (reference['finding_id'],reference['hash']):
                    raise ValueError('AI 收据事件引用损坏')
                rows.append(json.loads(record[2]))
            value['reviews']=rows
        return value


def read(path):
    mapped = artifact(path)
    if mapped is None:
        raise FileNotFoundError(path)
    database, name = mapped
    result = EvidenceProvider(database).load(name)
    if name == 'report':
        result.update(runtime(database.parent).get('report', {}))
    return result


def append_runtime(out, report, reviews):
    with closing(sqlite3.connect(Path(out)/'reviews.db', timeout=20)) as conn, conn:
        conn.execute('PRAGMA synchronous=FULL')
        conn.executescript(AI_SCHEMA)
        for ordinal,row in enumerate(reviews):
            raw=json.dumps(row,ensure_ascii=False,separators=(',',':'))
            hashed=hashlib.sha256(raw.encode()).hexdigest()
            previous=conn.execute('SELECT sequence,hash FROM ai_events WHERE finding_id=? ORDER BY sequence DESC LIMIT 1', (row['finding_id'],)).fetchone()
            if previous is None or previous[1]!=hashed:
                sequence=conn.execute('INSERT INTO ai_events(ordinal,finding_id,state,hash,payload) VALUES (?,?,?,?,?)',
                    (ordinal,row['finding_id'],row['state'],hashed,raw)).lastrowid
            else:
                sequence=previous[0]
        summary={key:report[key] for key in RUNTIME_KEYS if key in report and key!='review_records'}
        if 'risk_summary' in summary:
            # Per-symbol decisions are a query projection of immutable facts
            # plus individual AI events, not a second full inventory per tick.
            summary['risk_summary']={key:value for key,value in summary['risk_summary'].items() if key!='variables'}
        if 'final_conclusion' in summary:
            summary['final_conclusion']={key:value for key,value in summary['final_conclusion'].items()
                                         if key not in {'confirmed_findings','unresolved_findings'}}
        watermark=conn.execute('SELECT coalesce(max(sequence),0) FROM ai_events').fetchone()[0]
        payload=json.dumps(dict(report=summary,reviews=[],ai_events_version=2,watermark=watermark),ensure_ascii=False,separators=(',',':'))
        hashed=hashlib.sha256(payload.encode()).hexdigest()
        previous = conn.execute('SELECT hash FROM ai_snapshots ORDER BY sequence DESC LIMIT 1').fetchone()
        if not previous or previous[0] != hashed:
            conn.execute('INSERT INTO ai_snapshots(hash,payload) VALUES (?,?)', (hashed, payload))


def queue_directory(path):
    path=Path(path)
    if path.name=='queue.json' and path.parent.name=='review' and (path.parent.parent/'scan.db').is_file():
        return path.parent.parent
    return None


def ai_page(out, offset=0, limit=50):
    EvidenceProvider._bounds(offset,limit)
    meta=runtime(out,with_reviews=False)
    if meta.get('ai_events_version')!=2:
        rows=runtime(out).get('reviews',[])
        states={}
        for row in rows:
            states[row['state']]=states.get(row['state'],0)+1
        return dict(items=rows[offset:offset+limit],total=len(rows),states=states,offset=offset,
                    next_offset=offset+limit if offset+limit<len(rows) else None)
    with closing(sqlite3.connect((Path(out)/'reviews.db').resolve().as_uri()+'?mode=ro',uri=True)) as conn:
        conn.execute('PRAGMA trusted_schema=OFF')
        source=(' FROM ai_events a WHERE a.sequence<=? AND NOT EXISTS(SELECT 1 FROM ai_events n '
                'WHERE n.finding_id=a.finding_id AND n.sequence>a.sequence AND n.sequence<=?)')
        args=[meta['watermark']]*2
        states=dict(conn.execute('SELECT a.state,count(*)'+source+' GROUP BY a.state',args))
        total=sum(states.values())
        rows=[json.loads(row[0]) for row in conn.execute('SELECT a.payload'+source+' ORDER BY a.ordinal LIMIT ? OFFSET ?', [*args,limit,offset])]
        return dict(items=rows,total=total,states=states,offset=offset,next_offset=offset+len(rows) if offset+len(rows)<total else None)


def persist(out, facts, report, reviews):
    from .workflow import clean_report
    from .human_reviews import ReviewStore
    out = Path(out)
    database = out/'scan.db'
    if not database.exists():
        settings = json.loads((out/MARKER).read_text(encoding='utf-8'))
        provenance = dict(storage_version=1, project_root=report.get('workspace', {}).get('project_root'),
                          input_files={})
        # The original byte hashes are retained, with receipts embedded in the
        # authority. Runtime files remain available for strict input replay.
        for name in ('input_manifest.json', 'input_closure.json'):
            path = out/name
            if path.is_file():
                raw = path.read_bytes()
                provenance['input_files'][name] = dict(sha256=hashlib.sha256(raw).hexdigest(),
                                                       value=json.loads(raw))
        archived = []
        root = Path(report['workspace']['analysis_root'])
        manifest = provenance['input_files'].get('input_manifest.json', {}).get('value', {})
        for file, expected in manifest.items():
            path = root/file
            # Tool binaries are bound by the full input hash/identity; they are
            # not source text and must never be decoded into a huge SQL string.
            if path.suffix.lower() in {'.exe', '.dll', '.so', '.dylib'}:
                continue
            # Hash before capture: archived source must be the bytes consumed
            # by this scan, including external headers. Failure aborts publish.
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != expected:
                raise ValueError('归档输入已改变: '+file)
            import gzip
            compressed = gzip.compress(raw, mtime=0)
            object_hash = hashlib.sha256(compressed).hexdigest()
            objects = out/'evidence'; objects.mkdir(exist_ok=True)
            target = objects/object_hash
            if not target.exists():
                target.write_bytes(compressed)
            entry = dict(file=file, sha256=expected, raw_object=object_hash, codec='gzip', size=len(raw))
            if b'\x00' not in raw:
                entry.update(encoding='utf-8-replace', text=raw.decode('utf-8', errors='replace'))
            archived.append(entry)
        provenance['archived_sources'] = archived
        publish_scan(database, facts, clean_report(report), scan_id=settings['scan_id'],
                     project_id=settings['project_id'], profile_id=settings.get('profile_id', 'default'),
                     provenance=provenance, validation_state='UNVERIFIED')
        ReviewStore(out/'reviews.db', EvidenceProvider(database).metadata())
    append_runtime(out, report, reviews)


def archive_audit(out):
    """Content-address every required receipt, preserving relative provenance."""
    out = Path(out)
    objects = out/'evidence'; objects.mkdir(exist_ok=True)
    records = {}
    for folder in ('review', 'diagnostics', 'git_diff'):
        base = out/folder
        if not base.exists():
            continue
        for source in sorted(base.rglob('*')):
            if not source.is_file():
                continue
            hashed = hashlib.sha256()
            with source.open('rb') as stream:
                for block in iter(lambda: stream.read(1024*1024), b''):
                    hashed.update(block)
            sha = hashed.hexdigest()
            target = objects/sha
            if not target.exists():
                # A stable convenience name or diagnostic can be rewritten by
                # a later review. Never hard-link writable files into the CAS.
                pending=objects/(sha+'.'+uuid.uuid4().hex+'.pending')
                try:
                    shutil.copyfile(source,pending)
                    from .report_package import sha256
                    if sha256(pending)!=sha:
                        raise ValueError('收据在归档期间变化，请等待当前任务结束后重试')
                    try:
                        os.link(pending,target)
                    except FileExistsError:
                        pass
                finally:
                    pending.unlink(missing_ok=True)
            from .report_package import sha256
            if sha256(target) != sha:
                raise ValueError('内容寻址审计对象冲突/损坏: '+str(target))
            records[source.relative_to(out).as_posix()] = dict(sha256=sha, size=source.stat().st_size)
    for name in ('scan_state.json', 'input_manifest.json', 'input_closure.json', 'run.json',
                 'doctor.json', 'run.log', 'result_validity.json', MARKER):
        source = out/name
        if source.is_file():
            raw = source.read_bytes(); sha = hashlib.sha256(raw).hexdigest()
            target = objects/sha
            if not target.exists():
                target.write_bytes(raw)
            records[name] = dict(sha256=sha, size=len(raw))
    index = json.dumps(dict(version=1, files=records), ensure_ascii=False, sort_keys=True).encode()
    sha = hashlib.sha256(index).hexdigest()
    target=objects/sha
    if target.exists():
        if target.read_bytes()!=index:
            raise ValueError('审计索引对象损坏，拒绝覆盖')
    else:
        with target.open('xb') as stream:
            stream.write(index)
    return dict(audit_index=sha, audit_files=len(records))


def run_canonical(root, config_path=None, no_review=False, doctor_only=False, review_safe_sample=0,
                  review_shared_sample=0, scan_mode=None, *, scan_id=None, profile_id='default',_budget_owned=False):
    from .config import load_config
    from .workspace import formal_workspace
    from .storage_activity import DataActivity
    cfg,_=load_config(root,config_path)
    if scan_mode is not None:
        cfg['analysis']['git_diff']['enabled']=scan_mode=='diff'
    workspace=formal_workspace(root,cfg['analysis'])
    from contextlib import ExitStack
    with ExitStack() as activities:
        activities.enter_context(DataActivity(workspace.workspace_root))
        if not _budget_owned:activities.enter_context(DataActivity(workspace.workspace_root,exclusive=True,purpose='scan-budget'))
        return _run_canonical(root,config_path,no_review,doctor_only,review_safe_sample,review_shared_sample,
                              scan_mode,scan_id=scan_id,profile_id=profile_id,_expected_root=workspace.workspace_root)


@contextmanager
def project_scan_lock(root,analysis):
    from .workspace import lock_path,no_links
    from datetime import datetime,timezone
    path=no_links(lock_path(root,analysis))
    from .lock_owner import abandoned,process_identity
    try:
        fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    except FileExistsError as exc:
        original=path.read_bytes()
        try:stale=abandoned(json.loads(original))
        except (ValueError,TypeError,AttributeError):stale=False
        if not stale:raise ValueError('已有扫描锁 '+str(path)+'；等待当前任务结束；无法证明过期时保留锁') from exc
        # The caller owns the data-root scan budget; other canonical runs
        # cannot race this recovery. Live legacy owners are never removed.
        backup=no_links(path.with_name('scan.lock.recovered-'+uuid.uuid4().hex+'.json'))
        with backup.open('xb') as stream:
            stream.write(original);stream.flush();os.fsync(stream.fileno())
        if path.read_bytes()!=original:raise ValueError('恢复期间锁已变化，保留现场')
        path.unlink()
        fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    try:
        os.write(fd,json.dumps(dict(pid=os.getpid(),creation_filetime=process_identity(os.getpid()),
            started=datetime.now(timezone.utc).isoformat())).encode());os.close(fd)
        fd=None
        yield
    finally:
        if fd is not None:os.close(fd)
        no_links(path).unlink(missing_ok=True)


def previous_scan(workspace,profile_id):
    from .workspace import no_links
    from .report_package import IDENTITY,sha256
    specific=Path(workspace.project_workspace)/('latest-scan-'+profile_id+'.json')
    pointer=specific if specific.is_file() else Path(workspace.project_workspace)/'latest-scan.json'
    if not pointer.is_file():return None
    value=json.loads(pointer.read_text(encoding='utf-8'))
    if not IDENTITY.fullmatch(value.get('scan_id','')) or value.get('project_id')!=workspace.project_id:
        raise ValueError('历史扫描指针身份不符')
    out=no_links(Path(workspace.workspace_root)/'scans'/value['scan_id'])
    provider=EvidenceProvider(out/'scan.db');binding=provider.validate()
    if binding['project_id']!=workspace.project_id:raise ValueError('历史扫描属于其他工程')
    if binding['profile_id']!=profile_id:return None
    manifest=json.loads((out/'manifest.json').read_text(encoding='utf-8'))
    expected=manifest.get('scan_sha256') or manifest.get('files',{}).get('scan.db',{}).get('sha256')
    if not expected or sha256(out/'scan.db')!=expected:raise ValueError('上一扫描快照摘要损坏，不能计算历史变化')
    return out,provider,binding


def previous_finding_ids(out,workspace):
    settings=json.loads((Path(out)/MARKER).read_text(encoding='utf-8'))
    old=previous_scan(workspace,settings['profile_id'])
    if old is None:return set()
    from .scan_store import connect_readonly
    with closing(connect_readonly(old[0]/'scan.db')) as conn:
        return {row[0].decode('utf-8') for row in conn.execute("SELECT n.value FROM records r JOIN edges e ON e.parent=r.node AND e.key='finding_id' JOIN nodes n ON n.id=e.child WHERE r.dataset='report' AND r.relation='findings' ORDER BY r.ordinal")}


def _run_canonical(root, config_path=None, no_review=False, doctor_only=False, review_safe_sample=0,
                  review_shared_sample=0, scan_mode=None, *, scan_id=None, profile_id='default',_expected_root=None):
    """Run the unchanged pipeline in a unique external, persistent scan area.

    No latest pointer is changed until all original post-publication input
    checks pass. Failed tasks and previous valid scans remain separately visible.
    """
    from dataclasses import replace
    from datetime import datetime, timezone
    from .cli import run
    from .config import load_config
    from .workspace import formal_workspace, no_links
    from .report_package import IDENTITY, sha256
    cfg, config_file = load_config(root, config_path)
    if scan_mode is not None:
        cfg['analysis']['git_diff']['enabled'] = scan_mode == 'diff'
    workspace = formal_workspace(root,cfg['analysis'])
    if _expected_root is not None and workspace.workspace_root!=_expected_root:
        raise ValueError('启动期间配置的数据根已变化，请重新开始扫描')
    workspace.initialize()
    workspace.bind(cfg['analysis'])
    with project_scan_lock(root,cfg['analysis']):
        ident = scan_id or uuid.uuid4().hex
        if not IDENTITY.fullmatch(ident) or not IDENTITY.fullmatch(profile_id):
            raise ValueError('扫描身份无效')
        out = no_links(Path(workspace.workspace_root)/'scans'/ident)
        out.mkdir(parents=True, exist_ok=False)
        workspace = replace(workspace, results_root=str(out), cache_root=str(Path(workspace.cache_root)/'formal'),
                            snapshots_root=str(out/'snapshots'))
        write_json(out/MARKER, dict(version=1, scan_id=ident, project_id=workspace.project_id, profile_id=profile_id))
        code = run(root, config_path, no_review, doctor_only, review_safe_sample, review_shared_sample,
                   scan_mode=scan_mode, _workspace=workspace, _cache_enabled=True,_lock_owned=True)
        validity = json.loads((out/'result_validity.json').read_text(encoding='utf-8'))
        if code not in {0, 1, 2} or not validity.get('analysis_valid'):
            return code
        provider = EvidenceProvider(out/'scan.db')
        binding = provider.validate(deep=True)
        from .human_reviews import ReviewStore
        profile_pointer=Path(workspace.project_workspace)/('latest-scan-'+profile_id+'.json')
        previous_pointer=profile_pointer if profile_pointer.is_file() else Path(workspace.project_workspace)/'latest-scan.json'
        if previous_pointer.is_file():
            previous=json.loads(previous_pointer.read_text(encoding='utf-8'))
            if not IDENTITY.fullmatch(previous.get('scan_id','')) or previous.get('project_id')!=workspace.project_id:
                raise ValueError('历史扫描指针身份不符，拒绝自动关联')
            previous_out=no_links(Path(workspace.workspace_root)/'scans'/previous['scan_id'])
            old_provider=EvidenceProvider(previous_out/'scan.db')
            old=old_provider.metadata()
            if old['profile_id']==profile_id:
                ReviewStore(out/'reviews.db',binding).inherit_from(
                    ReviewStore(previous_out/'reviews.db',old),old_provider,provider)
        audit = archive_audit(out)
        manifest = dict(binding, format='ECRA_LOCAL_SCAN', version=1, **audit,
                        state='STATIC_VALIDATED', run_state=json.loads((out/'run.json').read_text(encoding='utf-8'))['state'],
                        scan_sha256=sha256(out/'scan.db'), source_reverification=True,
                        completed_at=datetime.now(timezone.utc).isoformat())
        write_json(out/'manifest.json', manifest)
        write_json(Path(workspace.project_workspace)/'latest-scan.json',
                   dict(project_id=workspace.project_id, scan_id=ident))
        write_json(profile_pointer,dict(project_id=workspace.project_id,scan_id=ident))
        return code
