"""Own, archive, and retire OpenCode sessions without putting cleanup in AI receipts."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, closing, contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from threading import Lock
import uuid

from .common import digest
from .opencode_storage import database_path
from .review_process import ReviewStop
from .report_package import sha256
from .review_opencode_sessions import Runtime, Unavailable, Unverifiable, file_identity, session_from_jsonl, store_identity
from .storage_activity import DataActivity, DataBusy
from .workspace import canonical, no_links


STAGES = frozenset({'ANALYZE', 'FORMAT_FIX', 'LANGUAGE_FIX', 'SUMMARY_FIX',
                   'NVIC_FACT_CHALLENGE', 'STALE_WRITEBACK_CHALLENGE'})
RUN_ID = re.compile(r'[0-9a-f]{32}')
JOURNAL = 'ownership.sqlite3'


def compatible_review_implementation(hashed):
    # Preserve keys across storage/cleanup changes. Edits to model inputs or
    # validation fall through to their own digest.
    if hashed in {'23749946dbf1b2530e47464b658035eadc2d8d6b266aa31849837ee7d9c90a1b',
                  'b481381bb8933a5e0a6e4224ffc5d6c0df783d95174b077f38e69c4c04926abb'}:
        return '8636daf895c4b0024a23b22f8f0cca5bc417bc04f710ebf6cd7f17120eae775d'
    if hashed == '141ec36a8849a3abbf9c79e11e9d9bcf240a36935532b33420d605cb157d3542':
        return '699efac22ac5578db71150692ddd12643edbbca57a301c7fbc3ff7f8a74321b5'
    return hashed


SCHEMA = '''
CREATE TABLE run (binding TEXT NOT NULL, database_identity TEXT NOT NULL, compacted INTEGER NOT NULL);
CREATE TABLE calls (
    invocation_id TEXT PRIMARY KEY, review_request TEXT NOT NULL, finding_id TEXT NOT NULL,
    number INTEGER NOT NULL, stage TEXT NOT NULL, cwd TEXT NOT NULL, project_id TEXT,
    stdout_file TEXT NOT NULL, stdout_sha256 TEXT, session_id TEXT,
    process_state TEXT NOT NULL, review_state TEXT NOT NULL, cleanup_state TEXT NOT NULL, reason TEXT NOT NULL,
    UNIQUE(review_request, finding_id, number)
);
CREATE TABLE claims (session_id TEXT NOT NULL, invocation_id TEXT NOT NULL,
                     PRIMARY KEY(session_id, invocation_id));
CREATE INDEX review_calls ON calls(review_request, finding_id);
'''


@dataclass
class Invocation:
    run: 'Run'
    id: str
    ended: bool = False

    @property
    def title(self):
        return 'ECRA ' + self.id

    def stopped(self):
        self.ended = True


class Run:
    def __init__(self, path, runtime, binding, environment):
        self.path = no_links(path)
        self.journal = self.path/JOURNAL
        self.runtime = runtime
        self.binding = dict(binding, run_id=self.path.name, exe=canonical(runtime.exe), exe_sha256=runtime.hash)
        self.environment = environment
        self.identity = None
        self.resources = ExitStack()
        self.server_resources = ExitStack()
        self.api = None
        self.protocol_problem = None
        self.transport_problem = None
        self.journal_lock = Lock()

    @contextmanager
    def connect(self):
        with self.journal_lock, closing(sqlite3.connect(no_links(self.journal), timeout=10)) as conn, conn:
            conn.row_factory = sqlite3.Row
            conn.execute('PRAGMA trusted_schema=OFF')
            conn.execute('PRAGMA synchronous=FULL')
            yield conn

    def start(self, storage):
        self.path.mkdir(mode=0o700)
        self.resources.enter_context(DataActivity(self.path, exclusive=True))
        self.database, self.shared = storage.database, storage.shared
        if storage.identity is None:
            storage.prepare(self.runtime)
        self.identity = storage.identity
        self.check_store()
        self.binding.update(database=str(self.database), shared=self.shared)
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            conn.execute('INSERT INTO run VALUES (?, ?, 1)',
                         (json.dumps(self.binding), json.dumps(self.identity)))

    def reopen(self, legacy_environment):
        self.resources.enter_context(DataActivity(self.path, exclusive=True))
        # Recovery only opens a previously initialized ECRA run and store.
        file_identity(self.journal)
        with self.connect() as conn:
            rows = conn.execute('SELECT binding, database_identity FROM run').fetchall()
        if len(rows) != 1:
            raise Unverifiable('复核会话清理账本缺少唯一的任务记录')
        recorded = json.loads(rows[0]['binding'])
        if recorded.get('schema') == 1:
            database, shared = self.path/'sessions.db', False
            expected = dict(self.binding, schema=1, environment=legacy_environment)
        else:
            database, shared = recorded.pop('database', None), recorded.pop('shared', None)
            if not isinstance(database, str) or type(shared) is not bool:
                raise Unverifiable('复核会话清理账本缺少数据库路径或归属')
            expected = self.binding
        if recorded != expected:
            raise Unverifiable('复核任务、工程或 OpenCode 程序身份不匹配')
        self.database, self.shared = database_path(database, shared=shared), shared
        self.identity = json.loads(rows[0]['database_identity'])
        self.check_store()

    def check_store(self):
        self.runtime.check_exe()
        if store_identity(self.database) != self.identity:
            raise Unverifiable(f'OpenCode 会话数据库已更换: {self.database}')

    def maintenance(self):
        return self.runtime.maintenance(self.database, workdir=self.path, shared=self.shared,
                                        environment=self.environment)

    def register(self, request, record, cwd):
        self.check_store()
        invocation = Invocation(self, uuid.uuid4().hex)
        directory = Path(cwd).resolve()
        # Model and maintenance processes disable discovery of external Git dirs.
        project_id = 'global'
        with self.connect() as conn:
            conn.execute('INSERT INTO calls VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?, ?)',
                         (invocation.id, request, record['finding_id'], record['number'], record['stage'],
                          canonical(directory), project_id, record['stdout_file'],
                          'RUNNING', 'PENDING', 'WAITING_FOR_ARCHIVE', ''))
        return invocation

    def finish(self, invocation, stdout, hashed):
        sid, claims, problem = session_from_jsonl(stdout)
        if not invocation.ended:
            problem = '无法确认原 OpenCode 进程已结束'
        with self.connect() as conn:
            conn.executemany('INSERT INTO claims VALUES (?, ?)', [(sid, invocation.id) for sid in claims])
            conn.execute('UPDATE calls SET stdout_sha256=?, session_id=?, process_state=?, cleanup_state=?, reason=? '
                         'WHERE invocation_id=?',
                         (hashed, sid, 'EXITED' if invocation.ended else 'UNPROVEN',
                          'SKIPPED_UNVERIFIABLE' if problem else 'WAITING_FOR_ARCHIVE', problem, invocation.id))

    def state(self, call, state, reason=''):
        with self.connect() as conn:
            conn.execute('UPDATE calls SET cleanup_state=?, reason=? WHERE invocation_id=?',
                         (state, reason, call['invocation_id']))
            if state == 'DELETED' and not self.shared:
                conn.execute('UPDATE run SET compacted=0')

    def assert_claim(self, call):
        with self.connect() as conn:
            owners = conn.execute('SELECT invocation_id FROM claims WHERE session_id=?',
                                  (call['session_id'],)).fetchall()
        if [row[0] for row in owners] != [call['invocation_id']]:
            raise Unverifiable('会话被多个调用引用或缺少独立归属')

    def delete(self, call):
        def assert_scope():
            self.check_store()
            self.assert_claim(call)

        assert_scope()
        if self.transport_problem:
            raise Unavailable(self.transport_problem)
        if self.protocol_problem:
            raise Unverifiable(self.protocol_problem)
        try:
            if self.api is None:
                try:
                    agent = self.server_resources.enter_context(self.maintenance())
                    self.api = self.server_resources.enter_context(agent.server())
                except Unverifiable as exc:
                    self.protocol_problem = str(exc)
                    raise
            self.api.delete_owned(call['session_id'], title='ECRA ' + call['invocation_id'],
                                  cwd=call['cwd'], project_id=call['project_id'], assert_scope=assert_scope)
        except Unavailable as exc:
            # Don't incur one timeout per queued variable during an outage.
            self.transport_problem = str(exc)
            raise

    def compact(self):
        with self.connect() as conn:
            needed = conn.execute('SELECT compacted FROM run').fetchone()[0] == 0
            uncertain = conn.execute("SELECT 1 FROM calls WHERE process_state != 'EXITED' LIMIT 1").fetchone()
        if not needed or uncertain:
            return
        self.check_store()
        with self.maintenance() as maintenance:
            maintenance.verify()
            maintenance.compact()
        self.check_store()
        with self.connect() as conn:
            conn.execute('UPDATE run SET compacted=1')

    def stop_api(self):
        self.server_resources.close()

    def close(self):
        try:
            self.stop_api()
        finally:
            self.resources.close()


class SessionCleanup:
    """Bind a run to a store; only the post-commit queue may schedule deletion."""
    def __init__(self, root, out, fingerprint, progress, *, timeout=60):
        self.root, self.out, self.fingerprint = root, out, fingerprint
        self.native = (out/'scan.db').is_file()
        self.progress = progress
        self.environment = os.environ.copy()
        self.timeout = timeout
        self.stop = ReviewStop()
        self.base = out/'opencode-session-cleanup'
        self.lock = Lock()
        self.run = None
        self.disabled = False
        self.pool = None
        self.recovery = None
        self.counts = Counter()

    def note(self, message, **counts):
        with self.lock:
            self.counts.update(counts)
        try:
            self.progress(message)
        except Exception:
            pass  # A cleanup diagnostic must never change a review result.

    @contextmanager
    def events(self):
        uri = no_links(self.out/'reviews.db').as_uri() + '?mode=ro'
        with closing(sqlite3.connect(uri, uri=True, timeout=2)) as conn:
            conn.execute('PRAGMA trusted_schema=OFF')
            yield conn

    def environment_binding(self, *, legacy=False):
        keys = ('HOME', 'USERPROFILE', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_STATE_HOME', 'XDG_CACHE_HOME',
                'OPENCODE_CONFIG', 'OPENCODE_CONFIG_DIR', 'OPENCODE_TEST_HOME')
        if legacy:
            keys += ('OPENCODE_DB',)
        return digest({key: self.environment.get(key) for key in keys})

    def binding(self):
        ids = {}
        if self.native:
            with self.events() as conn:
                row = conn.execute('SELECT scan_id, project_id, facts_hash, report_hash FROM binding').fetchone()
                if row is None:
                    raise Unverifiable('扫描缺少工程归属')
                ids = dict(zip(('scan_id', 'project_id', 'facts_hash', 'report_hash'), row))
        return dict(schema=2, output=canonical(self.out), project_root=canonical(self.root),
                    fingerprint=self.fingerprint, environment=self.environment_binding(), **ids)

    def begin(self, command, request, record, cwd, storage, runtime):
        if record['stage'] not in STAGES:
            return None
        problem = None
        with self.lock:
            if self.disabled:
                return None
            try:
                if self.run is None:
                    base = no_links(self.base)
                    base.mkdir(mode=0o700, exist_ok=True)
                    run = Run(base/uuid.uuid4().hex, runtime or Runtime(command, timeout=self.timeout, stop=self.stop), self.binding(), self.environment)
                    try:
                        run.start(storage)
                    except BaseException:
                        run.close()
                        raise
                    self.run = run
                    self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='opencode-cleanup')
                return self.run.register(request, record, cwd)
            except Exception as exc:
                self.disabled = True
                problem = str(exc)
        self.note('OpenCode 会话清理已停用，保留未确认归属的会话：' + problem, skipped=1)
        return None

    def finish(self, invocation, path, hashed):
        try:
            invocation.run.finish(invocation, path.read_text('utf-8', errors='replace'), hashed)
        except Exception as exc:
            self.note(f'OpenCode 会话归属记录写入失败，已保留会话: {exc}', skipped=1)

    def archived(self, row):
        if row['state'] != 'DONE' or row.get('cached') or row.get('scan_fingerprint') != self.fingerprint:
            raise Unverifiable('本次复核没有已验证的 DONE 收据')
        folder = self.out/'review'
        if self.native:
            from .scan_persistence import _read_event, review_head, snapshot_head
            with self.events() as conn:
                conn.execute('BEGIN')
                snapshot = snapshot_head(conn)
                head = review_head(conn, row['finding_id'], snapshot['watermark'])
                if not head or head[2] != 'DONE':
                    raise Unverifiable('SQLite 尚未提交本次复核')
                payload, = conn.execute('SELECT payload FROM ai_events WHERE sequence=?', (head[0],)).fetchone()
                if _read_event(row['finding_id'], head[2], head[1], payload) != row:
                    raise Unverifiable('SQLite 已提交收据与本次复核不一致')
            if sha256(self.out/'evidence'/head[1]) != head[1]:
                raise Unverifiable('内容寻址结果收据损坏')
        elif json.loads((folder/(row['finding_id']+'.result.json')).read_text('utf-8')) != row:
            raise Unverifiable('独立结果收据未持久化')

    def check_attempt(self, row, call):
        if call['stage'] not in STAGES or call['process_state'] != 'EXITED':
            raise Unverifiable('无法确认复核阶段或进程退出')
        attempts = row['attempts'][row.get('attempt_start', 0):]
        found = [a for a in attempts if a.get('number') == call['number'] and a.get('stage') == call['stage']
                 and a.get('stdout_file') == call['stdout_file'] and a.get('stdout_sha256') == call['stdout_sha256']]
        if len(found) != 1:
            raise Unverifiable('会话调用没有匹配的本轮归档记录')
        for stream in ('stdout', 'stderr'):
            name, hashed = found[0][stream+'_file'], found[0][stream+'_sha256']
            if Path(name).name != name or not re.fullmatch('[0-9a-f]{64}', hashed):
                raise Unverifiable('会话原始日志的路径或摘要不合法')
            if self.native:
                if row.get('archived_files', {}).get(name, {}).get('sha256') != hashed:
                    raise Unverifiable('会话原始日志未归档')
                path = self.out/'evidence'/hashed
            else:
                path = self.out/'review'/name
                with path.open('r+b') as source:
                    os.fsync(source.fileno())
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != hashed:
                raise Unverifiable('会话原始日志归档摘要不一致')
            if stream == 'stdout' and session_from_jsonl(raw.decode('utf-8', errors='replace'))[0] != call['session_id']:
                raise Unverifiable('已归档的会话事件和归属记录不一致')

    def retire(self, run, row):
        counts = Counter()
        try:
            request, fid = row['review_request'], row['finding_id']
            with run.connect() as conn:
                calls = conn.execute('SELECT * FROM calls WHERE review_request=? AND finding_id=? '
                                     'ORDER BY number', (request, fid)).fetchall()
                if row['state'] == 'TECH_FAILED':
                    conn.execute("UPDATE calls SET review_state='TECH_FAILED', cleanup_state='RETAINED' "
                                 'WHERE review_request=? AND finding_id=?', (request, fid))
                    return
            if not calls:
                return
            self.archived(row)
            with run.connect() as conn:
                conn.execute("UPDATE calls SET review_state='DONE', "
                             "cleanup_state=CASE WHEN cleanup_state='WAITING_FOR_ARCHIVE' THEN 'READY_TO_DELETE' "
                             "ELSE cleanup_state END WHERE review_request=? AND finding_id=?", (request, fid))
            for call in calls:
                state = call['cleanup_state']
                if state == 'SKIPPED_UNVERIFIABLE':
                    counts['skipped'] += 1
                if state not in {'WAITING_FOR_ARCHIVE', 'READY_TO_DELETE', 'DELETE_FAILED'}:
                    continue
                try:
                    self.check_attempt(row, call)
                    run.delete(call)
                except (Unverifiable, FileNotFoundError, KeyError, TypeError) as exc:
                    run.state(call, 'SKIPPED_UNVERIFIABLE', str(exc))
                    counts['skipped'] += 1
                except Exception as exc:
                    run.state(call, 'DELETE_FAILED', str(exc))
                    counts['failed'] += 1
                except KeyboardInterrupt as exc:
                    # Pause stops optional maintenance too. Keep its session
                    # and a recoverable reason without changing the DONE row.
                    run.state(call, 'DELETE_FAILED', str(exc))
                    counts['failed'] += 1
                else:
                    run.state(call, 'DELETED')
                    counts['deleted'] += 1
            if counts:
                self.note(f'{fid}：OpenCode 会话清理成功 {counts["deleted"]}，'
                          f'失败保留 {counts["failed"]}，无法确认归属已跳过 {counts["skipped"]}', **counts)
        except Exception:
            self.note(f'{row["finding_id"]}：无法验证会话清理记录或已提交归档，保留会话', skipped=1)

    def after_archive(self, row):
        if self.pool and row.get('review_request') and row['state'] in {'DONE', 'TECH_FAILED'} and not row.get('cached'):
            try:
                self.pool.submit(self.retire, self.run, row)
            except Exception:
                self.note('OpenCode 会话清理未能调度，继续复核时可补偿', failed=1)

    def recover(self, rows, command):
        try:
            if self.base.is_dir() and any(row['state'] == 'DONE' for row in rows.values()):
                self.recovery = ThreadPoolExecutor(max_workers=1, thread_name_prefix='opencode-cleanup-recovery')
                self.recovery.submit(self._recover, rows, command)
        except Exception:
            self.note('OpenCode 会话补偿清理未能调度，已保留会话', skipped=1)

    def _recover(self, rows, command):
        try:
            from .review import resolve_command
            runtime = Runtime(resolve_command(command), timeout=self.timeout, stop=self.stop)
            binding = self.binding()
            legacy_environment = self.environment_binding(legacy=True)
            for path in no_links(self.base).iterdir():
                if not RUN_ID.fullmatch(path.name) or not (path/JOURNAL).is_file():
                    continue
                run = None
                try:
                    run = Run(path, runtime, binding, self.environment)
                    run.reopen(legacy_environment)
                    with run.connect() as conn:
                        pending = conn.execute('SELECT DISTINCT review_request, finding_id FROM calls WHERE '
                                               "cleanup_state IN ('WAITING_FOR_ARCHIVE','READY_TO_DELETE','DELETE_FAILED')").fetchall()
                    for request, fid in pending:
                        row = rows.get(fid)
                        if row and row['state'] == 'DONE' and row.get('review_request') == request:
                            self.retire(run, row)
                    self._finish_run(run)
                    run = None
                except DataBusy:
                    pass  # Another process owns this exact run, never adopt it.
                except Exception as exc:
                    self.note(f'OpenCode 历史清理记录 {path.name} 无法重新验证，已保留会话：{exc}', skipped=1)
                finally:
                    if run:
                        run.close()
        except Exception:
            self.note('OpenCode 会话补偿清理不可用，已保留会话', skipped=1)

    def _finish_run(self, run):
        try:
            # The first resource is the lease. The service runs in a separate
            # stack so it can be stopped before reclaiming the store's pages.
            run.stop_api()
            if not run.shared:
                run.compact()
        except (Exception, KeyboardInterrupt) as exc:
            self.note(f'OpenCode 会话库暂未压缩，可在继续复核时重试：{exc}')
        finally:
            try:
                run.close()
            except Exception:
                self.note('OpenCode 会话清理资源关闭失败')

    def close(self):
        if self.run:
            if self.pool is None:
                self._finish_run(self.run)
            else:
                try:
                    # Close on the same worker after the last DELETE. A
                    # Ctrl+C while the caller joins must not release its lease.
                    self.pool.submit(self._finish_run, self.run)
                except Exception:
                    self.note('OpenCode 会话清理收尾未能调度，可在继续复核时重试')
        for pool in (self.pool, self.recovery):
            if pool:
                try:
                    pool.shutdown(wait=True)
                except Exception:
                    self.note('OpenCode 会话清理队列未正常关闭')
        if self.counts:
            self.note(f'OpenCode 会话清理：成功 {self.counts["deleted"]}，失败 {self.counts["failed"]}，'
                      f'跳过 {self.counts["skipped"]}')
