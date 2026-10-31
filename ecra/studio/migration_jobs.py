"""Persistent legacy-conversion jobs with a process-owned recovery lease."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
import traceback
import uuid

from ..legacy_import import inspect, convert
from ..storage_activity import DataActivity
from ..workspace import no_links
from ..report_package import IDENTITY


def revision(plan):
    return hashlib.sha256(json.dumps(plan, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class MigrationJobs:
    def __init__(self, data):
        self.data = Path(data)
        self.folder = no_links(self.data/'work/migration-jobs'); self.folder.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,started TEXT,state TEXT,payload TEXT)')
        try: lease = DataActivity(self.data, exclusive=True, purpose='legacy-import').__enter__()
        except ValueError: pass
        else:
            try:
                with self.connect() as conn:
                    for ident, raw in conn.execute("SELECT id,payload FROM jobs WHERE state='RUNNING'"):
                        item = json.loads(raw)
                        item.update(state='INTERRUPTED', error='上次迁移进程已退出；私有暂存与原数据保留。核对来源后重新迁移，不会覆盖旧归档。')
                        conn.execute('UPDATE jobs SET state=?,payload=? WHERE id=?',
                            ('INTERRUPTED', json.dumps(item, ensure_ascii=False), ident))
            finally: lease.__exit__(None,None,None)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(no_links(self.folder/'jobs.db'), timeout=10)
        try:
            conn.execute('PRAGMA trusted_schema=OFF'); conn.execute('PRAGMA synchronous=FULL')
            with conn: yield conn
        finally: conn.close()

    def preview(self, source, project_root):
        plan = inspect(source, project_root, self.data)
        return dict(plan, revision=revision(plan))

    def start(self, source, project_root, expected):
        plan = inspect(source, project_root, self.data)
        if expected != revision(plan):
            raise ValueError('旧来源、归属或文件清单已变化；请重新检查迁移计划')
        lease = DataActivity(self.data, exclusive=True, purpose='legacy-import').__enter__()
        ident = uuid.uuid4().hex
        item = dict(id=ident, started=datetime.now(timezone.utc).isoformat(), state='RUNNING',
            stage='PREPARING', message='等待只读捕获', source=source, project_root=project_root)
        def update(changes):
            item.update(changes)
            with self.connect() as conn:
                conn.execute('INSERT OR REPLACE INTO jobs VALUES (?,?,?,?)',
                    (ident, item['started'], item['state'], json.dumps(item, ensure_ascii=False)))
        try:
            update({})
            def run():
                try:
                    result = convert(source, project_root, self.data, progress=update, _lease=lease)
                    update(dict(state='COMPLETE', result=result, scan_id=result['scan_id']))
                except Exception as exc:
                    (self.folder/(ident+'.trace.txt')).write_text(traceback.format_exc(), encoding='utf-8')
                    update(dict(state='FAILED', error=str(exc)))
                finally: lease.__exit__(None,None,None)
            threading.Thread(target=run, daemon=True).start()
        except BaseException:
            lease.__exit__(None,None,None); raise
        return dict(id=ident, state='RUNNING')

    def get(self, ident):
        if not isinstance(ident, str) or not IDENTITY.fullmatch(ident):
            raise ValueError('迁移任务身份无效')
        with self.connect() as conn:
            row = conn.execute('SELECT payload FROM jobs WHERE id=?', (ident,)).fetchone()
            if row is None: raise ValueError('迁移任务不存在')
            return json.loads(row[0])

    def history(self, offset=0, limit=50):
        if offset < 0 or not 1 <= limit <= 200: raise ValueError('迁移历史分页无效')
        with self.connect() as conn:
            total = conn.execute('SELECT count(*) FROM jobs').fetchone()[0]
            items = [json.loads(row[0]) for row in conn.execute('SELECT payload FROM jobs ORDER BY started DESC LIMIT ? OFFSET ?', (limit,offset))]
            return dict(items=items, total=total, offset=offset,
                next_offset=offset+len(items) if offset+len(items)<total else None)
