"""Canonical scan publication and explicit legacy artifact navigation.

No solver/classification code lives here. Small input/recovery receipts remain
files; complete facts and static reports have exactly one authoritative graph.
"""
from contextlib import closing,contextmanager
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import traceback
import uuid

from .common import read_json, write_json
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


def snapshot_head(conn):
    row = conn.execute('SELECT sequence,hash,payload FROM ai_snapshots ORDER BY sequence DESC LIMIT 1').fetchone()
    if not row:
        return {}
    if hashlib.sha256(row[2].encode()).hexdigest() != row[1]:
        raise ValueError('AI 快照摘要损坏')
    value = json.loads(row[2])
    value['revision'] = row[0]
    return value


def runtime(out, *, with_reviews=True):
    path = Path(out)/'reviews.db'
    if not path.is_file():
        return {}
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True)) as conn:
        conn.execute('PRAGMA trusted_schema=OFF')
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ai_snapshots'").fetchone():
            return {}
        value = snapshot_head(conn)
        if not value:
            return {}
        if not with_reviews:
            value.pop('reviews',None)
            return value
        if value.get('ai_events_version') == 2:
            value['reviews']=[_read_event(*row) for row in conn.execute(
                'SELECT a.finding_id,a.state,a.hash,a.payload FROM ai_events a WHERE a.sequence<=? AND NOT EXISTS('
                'SELECT 1 FROM ai_events newer WHERE newer.finding_id=a.finding_id AND newer.sequence>a.sequence '
                'AND newer.sequence<=?) ORDER BY a.ordinal,a.finding_id', [value['watermark']]*2)]
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


def _read_event(finding_id, state, hashed, payload):
    try:
        row = json.loads(payload)
        if (hashlib.sha256(payload.encode()).hexdigest() != hashed
                or row.get('finding_id') != finding_id or row.get('state') != state):
            raise ValueError('AI 事件摘要或身份不一致')
        return row
    except (ValueError, AttributeError) as exc:
        return dict(finding_id=finding_id, state='TECH_FAILED', error=str(exc), error_type='InvalidReviewEvent')


def _encode(value):
    raw = json.dumps(value, ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(raw.encode()).hexdigest(), raw


def _insert_event(conn, ordinal, row, hashed, raw):
    return conn.execute('INSERT INTO ai_events(ordinal,finding_id,state,hash,payload) VALUES (?,?,?,?,?)',
                        (ordinal, row['finding_id'], row['state'], hashed, raw)).lastrowid


def _append_snapshot(conn, report, watermark):
    hashed, raw = _encode(dict(report=report,reviews=[],ai_events_version=2,watermark=watermark))
    previous = conn.execute('SELECT hash FROM ai_snapshots ORDER BY sequence DESC LIMIT 1').fetchone()
    if not previous or previous[0] != hashed:
        conn.execute('INSERT INTO ai_snapshots(hash,payload) VALUES (?,?)', (hashed, raw))


def _review_connection(out):
    conn = sqlite3.connect(Path(out)/'reviews.db', timeout=20)
    try:
        conn.execute('PRAGMA trusted_schema=OFF')
        conn.execute('PRAGMA synchronous=FULL')
    except BaseException:
        conn.close()
        raise
    return conn


def enable_review_wal(conn):
    import time
    deadline = time.monotonic() + 20
    while True:
        try:
            if conn.execute('PRAGMA journal_mode=WAL').fetchone()[0] != 'wal':
                raise ValueError('无法启用复核账本 WAL；原记录保留')
            return
        except sqlite3.OperationalError as exc:
            if str(exc).lower() != 'database is locked' or time.monotonic() >= deadline:
                raise
            time.sleep(.05)


def append_runtime(out, report, reviews):
    with closing(_review_connection(out)) as conn, conn:
        conn.executescript(AI_SCHEMA)
        enable_review_wal(conn)
        conn.execute('BEGIN IMMEDIATE')
        snapshot = snapshot_head(conn)
        maximum = conn.execute('SELECT coalesce(max(sequence),0) FROM ai_events').fetchone()[0]
        watermark = snapshot.get('watermark', maximum)
        unpublished = (maximum != watermark)
        ids = set()
        for ordinal,row in enumerate(reviews):
            ids.add(row['finding_id'])
            hashed, raw = _encode(row)
            previous=review_head(conn, row['finding_id'], watermark)
            if unpublished and conn.execute('SELECT 1 FROM ai_events WHERE finding_id=? AND sequence>? AND sequence<=?',
                                            (row['finding_id'], watermark, maximum)).fetchone():
                previous = None  # Explicitly supersede this uncommitted row.
            if previous is None or previous[1]!=hashed:
                _insert_event(conn, ordinal, row, hashed, raw)
        if unpublished and any(fid not in ids for (fid,) in conn.execute(
                'SELECT DISTINCT finding_id FROM ai_events WHERE sequence>? AND sequence<=?', (watermark, maximum))):
            raise ValueError('AI 账本发现水位外事件，拒绝发布')
        summary={key:report[key] for key in RUNTIME_KEYS if key in report and key!='review_records'}
        if 'risk_summary' in summary:
            # Per-symbol decisions are a query projection of immutable facts
            # plus individual AI events, not a second full inventory per tick.
            summary['risk_summary']={key:value for key,value in summary['risk_summary'].items() if key!='variables'}
        if 'final_conclusion' in summary:
            summary['final_conclusion']={key:value for key,value in summary['final_conclusion'].items()
                                         if key not in {'confirmed_findings','unresolved_findings'}}
        watermark=conn.execute('SELECT coalesce(max(sequence),0) FROM ai_events').fetchone()[0]
        _append_snapshot(conn, summary, watermark)


def review_head(conn, finding_id, watermark):
    return conn.execute('SELECT sequence,hash,state FROM ai_events WHERE finding_id=? AND sequence<=? '
                        'ORDER BY sequence DESC LIMIT 1', (finding_id, watermark)).fetchone()


def review_request(conn, finding_id, sequence):
    return conn.execute("SELECT json_extract(payload,'$.review_request') FROM ai_events WHERE finding_id=? AND sequence=?",
                        (finding_id, sequence)).fetchone()[0]


def validate_review_binding(out, provider):
    path = out/'reviews.db'
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as conn:
        conn.execute('PRAGMA trusted_schema=OFF')
        row = conn.execute('SELECT scan_id,project_id,facts_hash,report_hash FROM binding WHERE singleton=1').fetchone()
    binding = provider.metadata()
    expected = tuple(binding[key] for key in ('scan_id','project_id','facts_hash','report_hash'))
    if row != expected or (out.parent.name == 'scans' and binding['scan_id'] != out.name):
        raise ValueError('复核账本与当前扫描的工程、身份或静态证据摘要不一致')


@contextmanager
def review_writer(out):
    with closing(_review_connection(out)) as conn:
        if not conn.execute('SELECT 1 FROM ai_snapshots LIMIT 1').fetchone():
            raise ValueError('扫描尚未初始化 AI 复核账本')
        enable_review_wal(conn)
        yield conn


def commit_review_result(conn, ordinal, row):
    """Publish one verified receipt, conditional on the head it was issued for."""
    hashed, raw = _encode(row)
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        snapshot = snapshot_head(conn)
        if snapshot.get('ai_events_version') != 2:
            raise ValueError('扫描尚未初始化 AI 复核账本')
        watermark = snapshot['watermark']
        head = review_head(conn, row['finding_id'], watermark)
        if head is None:
            raise ValueError('变量不在已初始化的 AI 复核队列中：'+row['finding_id'])
        if conn.execute('SELECT coalesce(max(sequence),0) FROM ai_events').fetchone()[0] != watermark:
            raise ValueError('AI 账本发现水位外事件，拒绝发布')
        if head[1] == hashed:
            return
        if head[0] != row['review_base_sequence'] or head[2] not in {'PENDING', 'TECH_FAILED'}:
            raise ValueError('复核期间当前事件已变化，拒绝覆盖：'+row['finding_id'])
        if row.get('review_request') != review_request(conn, row['finding_id'], head[0]):
            raise ValueError('复核收据与本次分发身份不一致：'+row['finding_id'])
        sequence = _insert_event(conn, ordinal, row, hashed, raw)
        _append_snapshot(conn, snapshot['report'], sequence)


def queue_directory(path):
    path=Path(path)
    if path.name=='queue.json' and path.parent.name=='review' and (path.parent.parent/'scan.db').is_file():
        return path.parent.parent
    return None


def _ai_labels(alias='main'):
    # The authoritative symbol projection supplies readable names without
    # reconstructing facts/report or copying names into mutable AI receipts.
    return (f"SELECT CAST(n.value AS TEXT) AS finding_id,f.symbol_id,s.name,"
            f"s.definition_file,s.definition_line FROM {alias}.records f "
            f"CROSS JOIN {alias}.edges e ON e.parent=f.node AND e.key='finding_id' "
            f"CROSS JOIN {alias}.nodes n ON n.id=e.child LEFT JOIN {alias}.symbols s ON s.symbol_id=f.symbol_id "
            "WHERE f.dataset='report' AND f.relation IN ('findings','review_safe_samples') GROUP BY n.value")


def _ai_label_page(conn, finding_ids):
    from .scan_store import _hash_start, _scalar
    labels = {}
    relations = dict(conn.execute("SELECT e.child,e.key FROM evidence.roots root JOIN evidence.edges e ON e.parent=root.node "
                                  "WHERE root.name='report' AND e.key IN ('findings','review_safe_samples')"))
    if not relations:
        return labels
    keys = [value for item in relations.items() for value in item]
    parents = ','.join('?' for _ in relations)
    for first in range(0, len(finding_ids), 100):
        ids = finding_ids[first:first+100]
        placeholders = ','.join('?' for _ in ids)
        hashes = []
        for fid in ids:
            kind, raw = _scalar(fid)
            hashed = _hash_start(kind, len(raw))
            hashed.update(raw)
            hashes.append(hashed.hexdigest())
        # Resolve interned scalars by hash before traversing child edges.
        sql = ("SELECT CAST(n.value AS TEXT),f.symbol_id,s.name,s.definition_file,s.definition_line "
               "FROM evidence.nodes n CROSS JOIN evidence.edges e ON e.child=n.id AND e.key='finding_id' "
               "CROSS JOIN evidence.edges member ON member.child=e.parent "
               "CROSS JOIN evidence.records f ON f.dataset='report' AND f.relation=CASE member.parent "
               + ' '.join('WHEN ? THEN ?' for _ in relations) + ' END AND f.ordinal=member.ordinal '
               "LEFT JOIN evidence.symbols s ON s.symbol_id=f.symbol_id "
               f"WHERE n.hash IN ({placeholders}) AND member.parent IN ({parents})")
        for fid, symbol, name, file, line in conn.execute(sql, [*keys, *hashes, *relations]):
            labels[fid] = (symbol, name, file, line)
    return labels


@lru_cache(maxsize=4)
def _ai_search_labels(database, identity):
    # Labels come from sealed facts. Reuse the small label projection across
    # successive revisions while a search filter is active.
    with closing(sqlite3.connect(database.as_uri()+'?mode=ro', uri=True)) as conn:
        conn.execute('PRAGMA trusted_schema=OFF')
        return tuple(conn.execute(_ai_labels()))


def review_progress(states):
    done, failed = states.get('DONE', 0), states.get('TECH_FAILED', 0)
    total = sum(states.values())
    return dict(total=total, done=done, tech_failed=failed, pending=total-done-failed)


def _ai_progress(conn, meta):
    if meta.get('ai_events_version') == 2:
        return dict(conn.execute('SELECT a.state,count(*) FROM ai_events a WHERE a.sequence<=? AND NOT EXISTS('
            'SELECT 1 FROM ai_events n WHERE n.finding_id=a.finding_id AND n.sequence>a.sequence AND n.sequence<=?) '
            'GROUP BY a.state', [meta['watermark']]*2))
    if meta.get('ai_events_version') == 1:
        return dict(conn.execute("SELECT a.state,count(*) FROM json_each(?,'$.reviews') r JOIN ai_events a "
            "ON a.sequence=json_extract(r.value,'$.sequence') AND a.hash=json_extract(r.value,'$.hash') GROUP BY a.state",
            [json.dumps(meta)]))
    from collections import Counter
    return Counter(row.get('state', 'PENDING') for row in meta.get('reviews', []))


def ai_progress(out):
    with closing(sqlite3.connect((Path(out)/'reviews.db').resolve().as_uri()+'?mode=ro', uri=True)) as conn:
        conn.execute('PRAGMA trusted_schema=OFF')
        return review_progress(_ai_progress(conn, snapshot_head(conn)))


def ai_page(out, offset=0, limit=50, *, outcome='', search='', revision=None, finding_id='', include_progress=True):
    from .decisions import review_category
    import re
    EvidenceProvider._bounds(offset,limit)
    groups={key:0 for key in ('confirmed','likely','safe','unresolved')}
    if outcome and outcome not in groups:
        raise ValueError('OpenCode 结论筛选无效')
    if not isinstance(search,str) or len(search)>256:
        raise ValueError('复核搜索最多 256 字符')
    if finding_id and (not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', finding_id) or '..' in finding_id):
        raise ValueError('复核对象身份无效')
    search=search.strip()
    meta=runtime(out,with_reviews=False)
    current_revision=meta.get('revision', 0)
    if revision is not None and revision == current_revision:
        return dict(unchanged=True, revision=current_revision)
    if meta.get('ai_events_version')!=2:
        rows=runtime(out).get('reviews',[])
        states={}
        labels={}
        if rows and (Path(out)/'scan.db').is_file():
            from .scan_store import connect_readonly
            with closing(connect_readonly(Path(out)/'scan.db')) as conn:
                labels={row['finding_id']:dict(row) for row in conn.execute(_ai_labels())}
        for row in rows:
            states[row['state']]=states.get(row['state'],0)+1
            row.update(labels.get(row['finding_id'],{}))
            row['outcome']=review_category(row)
            groups[row['outcome']]+=1
        all_total=len(rows)
        rows=[row for row in rows if (not finding_id or row['finding_id']==finding_id) and (not outcome or row['outcome']==outcome) and
              (not search or any(search in str(row.get(k) or '') for k in ('finding_id','name','symbol_id','definition_file')))]
        return dict(items=rows[offset:offset+limit],total=len(rows),all_total=all_total,states=states,groups=groups,offset=offset,
                    revision=current_revision, progress=review_progress(states),
                    next_offset=offset+limit if offset+limit<len(rows) else None)
    with closing(sqlite3.connect((Path(out)/'reviews.db').resolve().as_uri()+'?mode=ro',uri=True)) as conn:
        conn.execute('PRAGMA trusted_schema=OFF')
        database = (Path(out)/'scan.db').resolve()
        conn.execute('ATTACH DATABASE ? AS evidence', (database.as_uri()+'?mode=ro',))
        if search:
            info = database.stat()
            labels = _ai_search_labels(database, (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns))
            conn.execute('CREATE TEMP TABLE ai_matches(finding_id TEXT PRIMARY KEY) WITHOUT ROWID')
            conn.executemany('INSERT INTO ai_matches VALUES (?)', (
                (fid,) for fid, sid, name, file, _ in labels if any(search in (value or '') for value in (fid, sid, name, file))))
        # Same raw-outcome rule as decisions.review_category and the original
        # review page. DONE alone never implies safety; stale/failed answers
        # remain unresolved even when their historical payload says "safe".
        verdict="CASE WHEN a.state='DONE' AND json_valid(a.payload) THEN json_extract(a.payload,'$.status') END"
        category=(f"CASE {verdict} WHEN 'CONFIRMED' THEN 'confirmed' WHEN 'LIKELY' THEN 'likely' "
                  "WHEN 'REVIEWED_SAFE' THEN 'safe' WHEN 'FALSE_POSITIVE' THEN 'safe' ELSE 'unresolved' END")
        cte=("WITH latest AS (SELECT a.sequence,a.finding_id,a.state,a.ordinal,"+category+" AS outcome FROM ai_events a WHERE a.sequence<=? "
             "AND NOT EXISTS(SELECT 1 FROM ai_events n WHERE n.finding_id=a.finding_id "
             "AND n.sequence>a.sequence AND n.sequence<=?)) ")
        args=[meta['watermark']]*2
        states={}
        if include_progress or not finding_id:
            for state,group,count in conn.execute(cte+'SELECT state,outcome,count(*) FROM latest GROUP BY state,outcome',args):
                states[state]=states.get(state,0)+count
                groups[group]+=count
        where=[];filters=[]
        if finding_id:where.append('a.finding_id=?');filters.append(finding_id)
        if outcome:where.append('a.outcome=?');filters.append(outcome)
        if search:
            where.append('(instr(a.finding_id,?)>0 OR a.finding_id IN (SELECT finding_id FROM ai_matches))')
            filters.append(search)
        source=' FROM latest a'
        if where:
            source += ' WHERE '+' AND '.join(where)
        total=(conn.execute(cte+'SELECT count(*)'+source,[*args,*filters]).fetchone()[0] if search or finding_id
               else groups[outcome] if outcome else sum(states.values()))
        rows=[]
        page_sql = cte + ', page AS (SELECT a.*'+source+' ORDER BY a.ordinal,a.finding_id LIMIT ? OFFSET ?) '
        page_sql += ('SELECT p.finding_id,p.state,e.hash,e.payload,p.outcome '
                     'FROM page p JOIN ai_events e ON e.sequence=p.sequence ORDER BY p.ordinal,p.finding_id')
        page_rows = conn.execute(page_sql, [*args,*filters,limit,offset]).fetchall()
        labels = _ai_label_page(conn, [item[0] for item in page_rows])
        for fid,state,hashed,payload,group in page_rows:
            row=_read_event(fid,state,hashed,payload)
            sid,name,file,line = labels.get(fid, (None, None, None, None))
            row.update(symbol_id=sid,name=name,definition_file=file,definition_line=line,outcome=group)
            rows.append(row)
        return dict(items=rows,total=total,all_total=sum(states.values()),states=states,groups=groups,offset=offset,
                    revision=current_revision, progress=review_progress(states),
                    next_offset=offset+len(rows) if offset+len(rows)<total else None)


def persist(out, facts, report, reviews, *, _existing_only=False):
    from .workflow import clean_report
    from .human_reviews import ReviewStore
    out = Path(out)
    database = out/'scan.db'
    if not database.exists():
        if _existing_only:raise ValueError('已有权威库不可用，不能用运行时元数据重建静态事实')
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
            from .input_snapshot import read_analysis_bytes
            raw = read_analysis_bytes(path)
            if hashlib.sha256(raw).hexdigest() != expected:
                raise ValueError('归档输入已改变: '+file)
            config_input = (report.get('git_diff') or {}).get('pin', {}).get('config_path') or settings.get('config_file')
            if config_input and path.resolve() == Path(config_input).resolve():
                from .scan_identity import capture
                provenance['display_identity'] = capture(raw, file, report.get('coverage', {}))
                import os
                provenance['execution_environment'] = dict(
                    parent_python_hash_seed=os.environ.get('PYTHONHASHSEED'),
                    extraction_python_hash_seed=os.environ.get('PYTHONHASHSEED') or '0',
                    source_date_epoch=os.environ.get('SOURCE_DATE_EPOCH'))
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
        # Only new private authority files pass the callback. Existing published
        # archives and all human/AI databases keep their original bytes.
        compact=None
        if out.parent.name=='scans' and settings.get('storage_policy') is not None:
            from .storage_compaction import ScanStorage
            storage=ScanStorage(out.parent.parent,out,out.parent.parent/'cache',settings['storage_policy'])
            compact=lambda path:storage.compress(path,'authority')
        publish_scan(database, facts, clean_report(report), scan_id=settings['scan_id'],
                     project_id=settings['project_id'], profile_id=settings.get('profile_id', 'default'),
                     provenance=provenance, validation_state='UNVERIFIED',compact=compact)
        ReviewStore(out/'reviews.db', EvidenceProvider(database).metadata())
    append_runtime(out, report, reviews)


def archive_audit(out):
    """Content-address every required receipt, preserving relative provenance."""
    from .review_archive import archive_object
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
            records[source.relative_to(out).as_posix()] = archive_object(out, source)
    for name in ('scan_state.json', 'input_manifest.json', 'input_closure.json', 'run.json',
                 'doctor.json', 'run.log', 'result_validity.json', MARKER):
        source = out/name
        if source.is_file():
            records[name] = archive_object(out, source)
    index = json.dumps(dict(version=1, files=records), ensure_ascii=False, sort_keys=True).encode()
    sha = hashlib.sha256(index).hexdigest()
    target=objects/sha
    if target.exists():
        if target.read_bytes()!=index:
            raise ValueError('审计索引对象损坏，拒绝覆盖')
    else:
        from .review_archive import durable_replace
        from tempfile import NamedTemporaryFile
        with NamedTemporaryFile(dir=out, suffix='.pending', delete=False) as stream:
            pending = Path(stream.name)
            try:
                stream.write(index)
                stream.flush()
                os.fsync(stream.fileno())
                stream.close()
                durable_replace(pending, target)
            finally:
                stream.close()
                pending.unlink(missing_ok=True)
    return dict(audit_index=sha, audit_files=len(records))


def run_canonical(root, config_path=None, no_review=False, doctor_only=False, review_safe_sample=0,
                  review_shared_sample=0, scan_mode=None, *, scan_id=None, profile_id='default',_budget_owned=False,_storage_policy=None,
                  _compiler_view=None, _git_pin=None):
    from .config import load_config
    from .frozen_scan import execution_workspace
    from .storage_activity import DataActivity
    if _git_pin is not None:
        from .git_diff import fixed_config_path
        if scan_mode == 'full':
            raise ValueError('固定 Diff 输入不能用于全量扫描')
        config_path = fixed_config_path(_git_pin)
    cfg,_=load_config(root,config_path)
    if scan_mode is not None:
        cfg['analysis']['git_diff']['enabled']=scan_mode=='diff'
    workspace=execution_workspace(root,cfg['analysis'],_compiler_view)
    from contextlib import ExitStack
    with ExitStack() as activities:
        activities.enter_context(DataActivity(workspace.workspace_root))
        if not _budget_owned:activities.enter_context(DataActivity(workspace.workspace_root,exclusive=True,purpose='scan-budget'))
        if cfg['analysis']['git_diff'].get('include_uncommitted') and _compiler_view is None:
            if doctor_only:raise ValueError('包含未提交输入时请使用Studio的真实环境检查；独立doctor尚不支持此固定输入工作流')
            from .dirty_inputs import capture_inputs
            _compiler_view=capture_inputs(root,config_path,
                Path(workspace.workspace_root)/'work/captured-inputs'/uuid.uuid4().hex,
                progress=lambda text:print(text,flush=True),scan_mode=scan_mode)
        return _run_canonical(root,config_path,no_review,doctor_only,review_safe_sample,review_shared_sample,
                              scan_mode,scan_id=scan_id,profile_id=profile_id,_expected_root=workspace.workspace_root,_storage_policy=_storage_policy,
                              _compiler_view=_compiler_view, _git_pin=_git_pin)


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
        except (ValueError,TypeError,AttributeError):
            stale=original.isdigit() and abandoned({'pid':int(original)})
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


def _publication_failed(out, exc):
    interrupted = isinstance(exc, KeyboardInterrupt)
    state, code = ('INTERRUPTED', 130) if interrupted else ('FAILED', 3)
    error = f'{type(exc).__name__}: {exc}'
    write_json(out/'result_validity.json', dict(analysis_valid=False, state=state, error=error))
    run = read_json(out/'run.json')
    run.update(state=state, exit_code=code, error=error, failed_stage='publication')
    write_json(out/'run.json', run)
    with (out/'diagnostics/exception.log').open('a', encoding='utf-8') as log:
        traceback.print_exception(type(exc), exc, exc.__traceback__, file=log)


def _publish_checkpoint(out, root, cfg, workspace, profile_id, *, compiler_view, run_state, verify_inputs=None):
    from datetime import datetime, timezone
    from .human_reviews import ReviewStore
    from .report_package import IDENTITY, sha256
    from .workspace import no_links
    from .review_archive import write_receipt

    profile_pointer = Path(workspace.project_workspace)/('latest-scan-'+profile_id+'.json')
    latest = Path(workspace.project_workspace)/'latest-scan.json'
    provider = EvidenceProvider(out/'scan.db')
    binding = provider.validate(deep=True)
    previous_pointer = profile_pointer if profile_pointer.is_file() else latest
    if previous_pointer.is_file():
        previous = read_json(previous_pointer)
        if not IDENTITY.fullmatch(previous.get('scan_id', '')) or previous.get('project_id') != workspace.project_id:
            raise ValueError('历史扫描指针身份不符，拒绝自动关联')
        previous_out = no_links(Path(workspace.workspace_root)/'scans'/previous['scan_id'])
        old_provider = EvidenceProvider(previous_out/'scan.db')
        old = old_provider.metadata()
        if old['profile_id'] == profile_id:
            ReviewStore(out/'reviews.db',binding).inherit_from(
                ReviewStore(previous_out/'reviews.db',old),old_provider,provider)
    audit = archive_audit(out)
    scan_sha256 = sha256(out/'scan.db')
    if verify_inputs is not None:
        verify_inputs()
    if compiler_view is not None:
        from .workflow import engine_digest
        from .working_compiler_view import validate
        validate(compiler_view, root, cfg, reverify_original=True)
        if engine_digest() != read_json(out/'scan_state.json')['engine_digest']:
            raise ValueError('归档审计期间分析实现已变化；冻结扫描不能发布')
    if verify_inputs is not None:
        from .scan_stop import check_stop
        check_stop()
        fingerprint = read_json(out/'scan_state.json')['fingerprint']
        write_receipt(out/'result_validity.json', dict(analysis_valid=True, state='STATIC_SCAN_SAVED',
                      snapshot_status='VERIFIED', fingerprint=fingerprint))
    manifest = dict(binding, format='ECRA_LOCAL_SCAN', version=1, **audit,
                    state='STATIC_VALIDATED', run_state=run_state,
        scan_sha256=scan_sha256, source_reverification=True,
                    completed_at=datetime.now(timezone.utc).isoformat())
    try:
        manifest['publication'] = provider.load('report', ['git_diff', 'publication'])
    except KeyError:
        pass
    write_receipt(out/'manifest.json', manifest)
    pointer = dict(project_id=workspace.project_id, scan_id=binding['scan_id'])
    write_receipt(latest, pointer)
    write_receipt(profile_pointer, pointer)


def _run_canonical(root, config_path=None, no_review=False, doctor_only=False, review_safe_sample=0,
                  review_shared_sample=0, scan_mode=None, *, scan_id=None, profile_id='default',_expected_root=None,_storage_policy=None,
                  _compiler_view=None, _git_pin=None):
    """Run the unchanged pipeline in a unique external, persistent scan area.

    No latest pointer is changed until all original post-publication input
    checks pass. Failed tasks and previous valid scans remain separately visible.
    """
    from dataclasses import replace
    from .cli import run
    from .config import load_config
    from .workspace import no_links
    from .frozen_scan import execution_workspace
    from .report_package import IDENTITY
    cfg, config_file = load_config(root, config_path)
    if scan_mode is not None:
        cfg['analysis']['git_diff']['enabled'] = scan_mode == 'diff'
    workspace = execution_workspace(root,cfg['analysis'],_compiler_view)
    if _expected_root is not None and workspace.workspace_root!=_expected_root:
        raise ValueError('启动期间配置的数据根已变化，请重新开始扫描')
    from .storage_policy import snapshot as storage_snapshot
    fixed_policy=storage_snapshot(workspace.workspace_root,_storage_policy)
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
        write_json(out/MARKER, dict(version=1, scan_id=ident, project_id=workspace.project_id,
                                   profile_id=profile_id, config_file=str(config_file),storage_policy=fixed_policy))
        previous_pointers = {}
        def publish_static(verify_inputs):
            for name in ('latest-scan.json', 'latest-scan-'+profile_id+'.json'):
                pointer = Path(workspace.project_workspace)/name
                if pointer.is_file():
                    previous_pointers[name] = read_json(pointer)
            _publish_checkpoint(out, root, cfg, workspace, profile_id,
                                compiler_view=_compiler_view, run_state='REVIEW_RUNNING', verify_inputs=verify_inputs)

        internal = {} if _compiler_view is None else dict(_compiler_view=_compiler_view)
        code = run(root, config_path, no_review, doctor_only, review_safe_sample, review_shared_sample,
                   scan_mode=scan_mode, _workspace=workspace, _cache_enabled=True,_lock_owned=True,
                   _publish_static=publish_static, _git_pin=_git_pin, **internal)
        validity = json.loads((out/'result_validity.json').read_text(encoding='utf-8'))
        if (out/'manifest.json').is_file():
            manifest = read_json(out/'manifest.json')
            if code == 3 and not validity['analysis_valid']:
                # This scan's final input check failed. Keep its evidence and
                # expose the prior valid scan as the current project result.
                for name in ('latest-scan.json', 'latest-scan-'+profile_id+'.json'):
                    pointer = Path(workspace.project_workspace)/name
                    if pointer.is_file() and read_json(pointer).get('scan_id') == ident:
                        if name in previous_pointers:
                            write_json(pointer, previous_pointers[name])
                        else:
                            pointer.unlink()
            elif code in {0, 1, 2}:
                # The checkpoint's index predates the final scan diagnostics.
                # Individual AI receipts already have their own immutable refs.
                manifest.update(archive_audit(out))
            manifest.update(run_state=read_json(out/'run.json')['state'],
                            source_reverification=validity['analysis_valid'])
            write_json(out/'manifest.json', manifest)
            return code
        if code not in {0, 1, 2} or not validity.get('analysis_valid'):
            return code
        try:
            _publish_checkpoint(out, root, cfg, workspace, profile_id,
                                compiler_view=_compiler_view, run_state=read_json(out/'run.json')['state'])
        except (Exception, KeyboardInterrupt) as exc:
            _publication_failed(out, exc)
            raise
        return code
