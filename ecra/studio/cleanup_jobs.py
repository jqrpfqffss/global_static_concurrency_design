"""Small persistent job registry; cleanup itself runs on the real data store."""
from contextlib import closing
from datetime import datetime,timezone
import json
from pathlib import Path
import sqlite3
import threading
import traceback
import uuid

from .. import garbage_collection as gc
from ..workspace import no_links
from ..report_package import IDENTITY
from ..storage_activity import DataActivity


class CleanupJobs:
    def __init__(self,data):
        self.data=Path(data);self.lock=threading.Lock()
        self.folder=no_links(self.data/'work/cleanup-jobs');self.folder.mkdir(parents=True,exist_ok=True)
        with self.connect() as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,started TEXT,operation TEXT,preview_id TEXT,state TEXT,error TEXT)')
        try:lease=DataActivity(self.data,exclusive=True,purpose='cleanup-job').__enter__()
        except ValueError:pass  # a different Studio still owns its live job
        else:
            try:
                with self.connect() as conn:
                    conn.execute("UPDATE jobs SET state='INTERRUPTED',error=? WHERE state='RUNNING'",
                        ('上次整理监督器已退出；查看计划后可恢复隔离文件或继续已确认的释放。',))
            finally:lease.__exit__(None,None,None)

    def connect(self):
        conn=sqlite3.connect(no_links(self.folder/'jobs.db'),timeout=10)
        conn.execute('PRAGMA trusted_schema=OFF');conn.row_factory=sqlite3.Row
        # Caller owns a short connection, never a service-wide SQLite handle.
        from contextlib import contextmanager
        @contextmanager
        def lifetime():
            try:
                with conn:yield conn
            finally:conn.close()
        return lifetime()

    def start(self,operation,preview_id=None):
        functions={'preview':gc.preview,'quarantine':gc.quarantine,'restore':gc.restore,'purge':gc.purge}
        if operation not in functions:raise ValueError('整理操作未知')
        if operation!='preview' and (not isinstance(preview_id,str) or not IDENTITY.fullmatch(preview_id)):
            raise ValueError('整理预览身份无效')
        if not self.lock.acquire(blocking=False):raise ValueError('已有空间整理操作，请等待结束')
        ident=uuid.uuid4().hex
        lease=None
        try:
            lease=DataActivity(self.data,exclusive=True,purpose='cleanup-job').__enter__()
            with self.connect() as conn:
                conn.execute('INSERT INTO jobs VALUES (?,?,?,?,?,NULL)',(ident,datetime.now(timezone.utc).isoformat(),operation,preview_id,'RUNNING'))
            def run():
                try:
                    result=functions[operation](self.data,*([preview_id] if operation!='preview' else []))
                    with self.connect() as conn:
                        conn.execute("UPDATE jobs SET preview_id=?,state='COMPLETE' WHERE id=?",(result['id'],ident))
                except Exception as exc:
                    (self.folder/(ident+'.trace.txt')).write_text(traceback.format_exc(),encoding='utf-8')
                    with self.connect() as conn:
                        conn.execute("UPDATE jobs SET state='FAILED',error=? WHERE id=?",(str(exc),ident))
                finally:
                    lease.__exit__(None,None,None);self.lock.release()
            threading.Thread(target=run,daemon=True).start()
        except BaseException:
            if lease is not None:lease.__exit__(None,None,None)
            self.lock.release();raise
        return dict(id=ident,state='RUNNING')

    def get(self,ident):
        if not IDENTITY.fullmatch(ident):raise ValueError('整理任务身份无效')
        with self.connect() as conn:
            row=conn.execute('SELECT * FROM jobs WHERE id=?',(ident,)).fetchone()
            if row is None:raise ValueError('整理任务不存在')
            return dict(row)

    def history(self,offset=0,limit=50):
        if offset<0 or not 1<=limit<=200:raise ValueError('整理历史分页无效')
        with self.connect() as conn:
            total=conn.execute('SELECT count(*) FROM jobs').fetchone()[0]
            rows=[dict(row) for row in conn.execute('SELECT * FROM jobs ORDER BY started DESC LIMIT ? OFFSET ?',(limit,offset))]
            return dict(items=rows,total=total,offset=offset,next_offset=offset+len(rows) if offset+len(rows)<total else None)
