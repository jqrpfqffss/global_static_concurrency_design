"""Independent, append-only human decisions with explicit offline conflicts."""
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import uuid

DECISIONS = {'PENDING', 'CONFIRMED_RISK', 'CONFIRMED_SAFE', 'NEED_MORE_EVIDENCE', 'RECHECK_REQUIRED'}
HANDLING = {'TODO', 'FIXING', 'TO_VERIFY', 'CLOSED', 'ACCEPTED_RISK'}
FIELDS = ('event_id', 'scan_id', 'project_id', 'symbol_id', 'fingerprint', 'reviewer',
          'timestamp', 'decision', 'handling_status', 'comment', 'revision', 'device', 'parents')
HUMAN_SCHEMA = """
CREATE TABLE IF NOT EXISTS binding (
 singleton INTEGER PRIMARY KEY CHECK(singleton=1), scan_id TEXT NOT NULL,
 project_id TEXT NOT NULL, facts_hash TEXT NOT NULL, report_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events (
 event_id TEXT PRIMARY KEY, symbol_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
 revision INTEGER NOT NULL, payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS event_symbol ON events(symbol_id,fingerprint);
CREATE TABLE IF NOT EXISTS predecessors (
 event_id TEXT NOT NULL REFERENCES events(event_id),
 parent_id TEXT NOT NULL REFERENCES events(event_id),
 PRIMARY KEY(event_id,parent_id), CHECK(event_id<>parent_id));
CREATE INDEX IF NOT EXISTS predecessor_parent ON predecessors(parent_id);
CREATE TABLE IF NOT EXISTS positions (
 name TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events BEGIN
 SELECT RAISE(ABORT,'human events are immutable'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events BEGIN
 SELECT RAISE(ABORT,'human events are immutable'); END;
CREATE TRIGGER IF NOT EXISTS parents_no_update BEFORE UPDATE ON predecessors BEGIN
 SELECT RAISE(ABORT,'event predecessors are immutable'); END;
CREATE TRIGGER IF NOT EXISTS parents_no_delete BEFORE DELETE ON predecessors BEGIN
 SELECT RAISE(ABORT,'event predecessors are immutable'); END;
"""

LEGACY_AI_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_snapshots (
 sequence INTEGER PRIMARY KEY, hash TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS ai_no_update BEFORE UPDATE ON ai_snapshots BEGIN
 SELECT RAISE(ABORT,'AI receipts are immutable'); END;
CREATE TRIGGER IF NOT EXISTS ai_no_delete BEFORE DELETE ON ai_snapshots BEGIN
 SELECT RAISE(ABORT,'AI receipts are immutable'); END;
"""
AI_SCHEMA = LEGACY_AI_SCHEMA + """
CREATE TABLE IF NOT EXISTS ai_events (
 sequence INTEGER PRIMARY KEY, ordinal INTEGER NOT NULL, finding_id TEXT NOT NULL,
 state TEXT NOT NULL, hash TEXT NOT NULL, payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ai_finding ON ai_events(finding_id,sequence);
CREATE TRIGGER IF NOT EXISTS ai_events_no_update BEFORE UPDATE ON ai_events BEGIN
 SELECT RAISE(ABORT,'AI events are immutable'); END;
CREATE TRIGGER IF NOT EXISTS ai_events_no_delete BEFORE DELETE ON ai_events BEGIN
 SELECT RAISE(ABORT,'AI events are immutable'); END;
"""
PRE_INHERIT_SCHEMA = HUMAN_SCHEMA + AI_SCHEMA
SCHEMA = PRE_INHERIT_SCHEMA + """
CREATE TABLE IF NOT EXISTS prior_decisions (
 symbol_id TEXT NOT NULL, fingerprint TEXT NOT NULL, source_scan TEXT NOT NULL,
 source_fingerprint TEXT NOT NULL, hash TEXT NOT NULL, payload TEXT NOT NULL,
 PRIMARY KEY(symbol_id,source_scan));
CREATE INDEX IF NOT EXISTS prior_current ON prior_decisions(symbol_id,fingerprint);
CREATE TRIGGER IF NOT EXISTS prior_no_update BEFORE UPDATE ON prior_decisions BEGIN
 SELECT RAISE(ABORT,'historical decisions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS prior_no_delete BEFORE DELETE ON prior_decisions BEGIN
 SELECT RAISE(ABORT,'historical decisions are immutable'); END;
"""


class ReviewConflict(ValueError):
    pass


class ReviewStore:
    def __init__(self, path, binding, *, device=None):
        self.path = Path(path)
        self.binding = {key: binding[key] for key in ('scan_id', 'project_id', 'facts_hash', 'report_hash')}
        self.device = device or 'local-' + uuid.uuid4().hex
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            conn.executescript(SCHEMA)
            old = conn.execute('SELECT scan_id,project_id,facts_hash,report_hash FROM binding').fetchone()
            if old is None:
                conn.execute('INSERT INTO binding VALUES (1,?,?,?,?)', tuple(self.binding.values()))
            elif tuple(old) != tuple(self.binding.values()):
                raise ValueError('人工记录不属于此扫描/完整证据，拒绝覆盖')

    @contextmanager
    def connection(self):
        from .storage_activity import DataActivity, review_data_root
        data_root=review_data_root(self.path)
        activity=DataActivity(data_root) if data_root else nullcontext()
        with activity:
            conn = sqlite3.connect(self.path, timeout=10)
            try:
                conn.execute('PRAGMA foreign_keys=ON')
                conn.execute('PRAGMA trusted_schema=OFF')
                conn.execute('PRAGMA synchronous=FULL')
                conn.execute('BEGIN IMMEDIATE')
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
            finally:
                conn.close()


    @staticmethod
    def _heads(conn, symbol_id, fingerprint):
        return [json.loads(row[0]) for row in conn.execute(
            'SELECT e.payload FROM events e WHERE symbol_id=? AND fingerprint=? '
            'AND NOT EXISTS(SELECT 1 FROM predecessors p WHERE p.parent_id=e.event_id) ORDER BY e.event_id',
            (symbol_id, fingerprint))]

    def current(self, symbol_id, fingerprint):
        with self.connection() as conn:
            heads = self._heads(conn, symbol_id, fingerprint)
            prior=bool(conn.execute('SELECT 1 FROM prior_decisions WHERE symbol_id=? AND fingerprint=?',(symbol_id,fingerprint)).fetchone())
        decision=heads[0]['decision'] if len(heads)==1 else 'CONFLICT' if heads else 'PENDING'
        if prior and decision=='PENDING':
            decision='RECHECK_REQUIRED'
        return dict(heads=heads, conflict=len(heads)>1, decision=decision,
                    handling_status=heads[0]['handling_status'] if len(heads)==1 else 'TODO',has_prior=prior)

    def prior(self, symbol_id, fingerprint):
        with self.connection() as conn:
            return [json.loads(row[0]) for row in conn.execute(
                'SELECT payload FROM prior_decisions WHERE symbol_id=? AND fingerprint=? ORDER BY source_scan', (symbol_id,fingerprint))]

    def inherit_from(self, previous, old_provider, new_provider):
        """Associate canonical IDs only; never copy an old SAFE into this scan.

        Original events keep their original scan/fingerprint. New confirmation
        is a separate current-scan event, with historical evidence visible.
        """
        import hashlib
        if previous.binding['project_id']!=self.binding['project_id']:
            raise ValueError('不能关联其他工程的人工历史')
        old={}
        with previous.connection() as conn:
            for (symbol,) in conn.execute('SELECT DISTINCT symbol_id FROM events ORDER BY symbol_id'):
                fingerprint=old_provider.fingerprint(symbol)
                heads=previous._heads(conn,symbol,fingerprint)
                if heads and any(head['decision']!='PENDING' for head in heads):
                    history=[json.loads(row[0]) for row in conn.execute('SELECT payload FROM events WHERE symbol_id=? ORDER BY revision,event_id',(symbol,))]
                    old[(symbol,previous.binding['scan_id'])]=dict(binding=previous.binding,symbol_id=symbol,
                        fingerprint=fingerprint,events=history)
            for symbol,source,payload in conn.execute('SELECT symbol_id,source_scan,payload FROM prior_decisions'):
                old.setdefault((symbol,source),json.loads(payload))
        inserted=0
        with self.connection() as conn:
            for (symbol,source),value in old.items():
                try:
                    current=new_provider.fingerprint(symbol)
                except KeyError:
                    continue  # renamed/deleted storage is not matched by name
                payload=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))
                hashed=hashlib.sha256(payload.encode()).hexdigest()
                row=(symbol,current,source,value['fingerprint'],hashed,payload)
                existing=conn.execute('SELECT symbol_id,fingerprint,source_scan,source_fingerprint,hash,payload FROM prior_decisions WHERE symbol_id=? AND source_scan=?',(symbol,source)).fetchone()
                if existing is not None and existing!=row:
                    raise ValueError('相同历史来源包含不同内容，拒绝覆盖')
                if existing is None:
                    conn.execute('INSERT INTO prior_decisions VALUES (?,?,?,?,?,?)',row);inserted+=1
        return inserted

    def append(self, symbol_id, fingerprint, *, decision, handling_status='TODO', reviewer,
               comment='', expected_heads=(), resolve=False):
        with self.connection() as conn:
            heads = self._heads(conn, symbol_id, fingerprint)
            actual = sorted(e['event_id'] for e in heads)
            if sorted(expected_heads) != actual:
                raise ReviewConflict('此变量已有其他确认，请重新读取双方事件再保存')
            if len(heads)>1 and not resolve:
                raise ReviewConflict('离线确认发生冲突；必须显式查看并解决全部分支')
            if len(heads)>1 and not comment.strip():
                raise ValueError('解决冲突必须填写依据')
            event = dict(event_id=str(uuid.uuid4()), **{k: self.binding[k] for k in ('scan_id', 'project_id')},
                symbol_id=symbol_id, fingerprint=fingerprint, reviewer=reviewer.strip(),
                timestamp=datetime.now(timezone.utc).isoformat(), decision=decision,
                handling_status=handling_status, comment=comment, revision=max((e['revision'] for e in heads), default=0)+1,
                device=self.device, parents=actual)
            self._validate(event)
            self._insert(conn, event)
        return event

    def _validate(self, event):
        if not isinstance(event, dict) or set(event) != set(FIELDS):
            raise ValueError('人工事件字段不完整或版本未知')
        if any(not isinstance(event[k], str) for k in FIELDS if k not in {'revision', 'parents'}):
            raise ValueError('人工事件字段类型错误')
        if any(not event[k].strip() for k in ('event_id', 'symbol_id', 'fingerprint', 'reviewer', 'device')):
            raise ValueError('确认者/对象/证据/来源不能为空；确认者为用户声明，未经认证')
        if event['decision'] not in DECISIONS or event['handling_status'] not in HANDLING:
            raise ValueError('人工判定或处理状态无效')
        if event['decision'] == 'CONFIRMED_SAFE' and not event['comment'].strip():
            raise ValueError('确认无风险必须填写依据或证据引用')
        if event['scan_id'] != self.binding['scan_id'] or event['project_id'] != self.binding['project_id']:
            raise ValueError('事件不属于此扫描/项目')
        if type(event['revision']) is not int or event['revision'] < 1:
            raise ValueError('事件 revision 无效')
        if (not isinstance(event['parents'], list) or any(not isinstance(p, str) for p in event['parents'])
                or len(event['parents']) != len(set(event['parents'])) or event['event_id'] in event['parents']):
            raise ValueError('事件前驱无效')
        try:
            stamp = datetime.fromisoformat(event['timestamp'])
            if stamp.tzinfo is None or stamp.utcoffset().total_seconds() != 0:
                raise ValueError()
        except ValueError as exc:
            raise ValueError('事件时间必须是 UTC') from exc

    @staticmethod
    def _insert(conn, event):
        payload = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        old = conn.execute('SELECT payload FROM events WHERE event_id=?', (event['event_id'],)).fetchone()
        if old is not None:
            if old[0] != payload:
                raise ValueError('相同事件ID含不同内容，拒绝导入')
            return False
        parents = []
        for ident in event['parents']:
            row = conn.execute('SELECT payload FROM events WHERE event_id=?', (ident,)).fetchone()
            if row is None:
                raise ValueError('人工事件缺少前驱，不能丢弃历史后导入')
            parent = json.loads(row[0])
            if (parent['symbol_id'], parent['fingerprint']) != (event['symbol_id'], event['fingerprint']):
                raise ValueError('事件前驱属于不同对象或证据')
            parents.append(parent)
        if event['revision'] != max((p['revision'] for p in parents), default=0)+1:
            raise ValueError('事件修订顺序无效')
        conn.execute('INSERT INTO events VALUES (?,?,?,?,?)',
            (event['event_id'], event['symbol_id'], event['fingerprint'], event['revision'], payload))
        conn.executemany('INSERT INTO predecessors VALUES (?,?)', ((event['event_id'], ident) for ident in event['parents']))
        return True

    def merge(self, events, *, fingerprint_for, _connection=None):
        # Caller supplies the authority's fingerprint function. Validate every
        # imported event even when its ID is already present (idempotence must
        # not bless a tampered repeat).
        if not isinstance(events, list) or any(not isinstance(event, dict) for event in events):
            raise ValueError('人工事件必须是完整对象列表')
        imported = 0
        with (self.connection() if _connection is None else nullcontext(_connection)) as conn:
            for event in sorted(events, key=lambda e: (e.get('revision', -1), e.get('event_id', ''))):
                self._validate(event)
                if fingerprint_for(event['symbol_id']) != event['fingerprint']:
                    raise ValueError('确认增量证据指纹不同；需重新确认，原事件保留')
                imported += self._insert(conn, event)
        return imported

    def history(self, symbol_id=None):
        with self.connection() as conn:
            query = 'SELECT payload FROM events'
            args = ()
            if symbol_id is not None:
                query += ' WHERE symbol_id=?'
                args = (symbol_id,)
            return [json.loads(row[0]) for row in conn.execute(query+' ORDER BY revision,event_id', args)]

    def undo(self, symbol_id, fingerprint, *, reviewer, comment, expected_heads):
        if not comment.strip():
            raise ValueError('撤销需填写理由，原确认会保留在历史中')
        state = self.current(symbol_id, fingerprint)
        if state['conflict'] or len(state['heads']) != 1:
            raise ReviewConflict('没有可直接撤销的唯一确认；请先解决冲突')
        head = state['heads'][0]
        history = {event['event_id']: event for event in self.history(symbol_id)}
        previous = history[head['parents'][0]] if len(head['parents']) == 1 else None
        return self.append(symbol_id, fingerprint, decision=previous['decision'] if previous else 'PENDING',
            handling_status=previous['handling_status'] if previous else 'TODO', reviewer=reviewer,
            comment=f"撤销 {head['event_id']}：{comment}", expected_heads=expected_heads)

    def position(self, name, value=None):
        with self.connection() as conn:
            if value is not None:
                conn.execute('INSERT INTO positions VALUES (?,?) ON CONFLICT(name) DO UPDATE SET value=excluded.value',
                             (name, json.dumps(value, ensure_ascii=False)))
            row = conn.execute('SELECT value FROM positions WHERE name=?', (name,)).fetchone()
            return json.loads(row[0]) if row else None
