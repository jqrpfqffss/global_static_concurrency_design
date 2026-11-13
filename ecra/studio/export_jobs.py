"""Durable, single-flight exports; HTTP requests never wait for compression."""
from contextlib import contextmanager, ExitStack
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import threading
import time
import traceback
import uuid
import zipfile

from ..operation_progress import OperationCancelled
from ..report_package import export_report, export_delta, IDENTITY
from ..storage_activity import DataActivity, DataBusy
from ..workspace import no_links


ACTIVE = {'RUNNING', 'CANCELLING'}


class ExportJobs:
    def __init__(self, data):
        self.data = Path(data)
        self.folder = no_links(self.data/'work/export-jobs')
        self.folder.mkdir(parents=True, exist_ok=True)
        self.threads = set()
        self.lock = threading.Lock()
        self.stopping = threading.Event()
        with self.connect() as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, started TEXT, state TEXT, payload TEXT)')
        try:
            with DataActivity(self.data, exclusive=True, purpose='export-job'):
                with self.connect() as conn:
                    for ident, raw in conn.execute("SELECT id,payload FROM jobs WHERE state IN ('RUNNING','CANCELLING')").fetchall():
                        item = json.loads(raw)
                        item.update(state='INTERRUPTED', error='上次导出服务已退出，请重新导出；原扫描与人工记录保留。')
                        self.save(conn, item)
        except DataBusy:
            pass

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(no_links(self.folder/'jobs.db'), timeout=10)
        try:
            conn.execute('PRAGMA trusted_schema=OFF')
            with conn:
                yield conn
        finally:
            conn.close()

    @staticmethod
    def save(conn, item):
        conn.execute('INSERT OR REPLACE INTO jobs VALUES (?,?,?,?)',
                     (item['id'], item['started'], item['state'], json.dumps(item, ensure_ascii=True)))

    def get(self, ident):
        if not isinstance(ident, str) or not IDENTITY.fullmatch(ident):
            raise ValueError('导出任务身份无效')
        with self.connect() as conn:
            row = conn.execute('SELECT payload FROM jobs WHERE id=?', (ident,)).fetchone()
        if row is None:
            raise ValueError('导出任务不存在')
        return json.loads(row[0])

    def history(self):
        with self.connect() as conn:
            return dict(items=[json.loads(row[0]) for row in conn.execute('SELECT payload FROM jobs ORDER BY started DESC LIMIT 20')])

    def start(self, scan, *, kind='full', compression='deflate'):
        if not isinstance(kind, str) or kind not in {'full', 'delta'}:
            raise ValueError('请选择标准完整包或人工确认增量')
        if kind == 'full' and (not isinstance(compression, str) or compression not in {'compact', 'deflate'}):
            raise ValueError('完整包压缩只支持 compact（省空间）或 deflate（快速）')
        scan = no_links(scan)
        if not (scan/'scan.db').is_file() or not (scan/'reviews.db').is_file():
            raise ValueError('扫描归档不完整，无法导出')
        compression = compression if kind == 'full' else None
        with self.lock:
            if self.stopping.is_set():
                raise ValueError('服务正在退出，请重新启动后导出')
            leases = ExitStack()
            try:
                leases.enter_context(DataActivity(self.data))
                try:
                    leases.enter_context(DataActivity(self.data, exclusive=True, purpose='export-job'))
                except DataBusy:
                    for item in self.history()['items']:
                        if item['state'] in ACTIVE and item['scan_id'] == scan.name and item['kind'] == kind and item['compression'] == compression:
                            leases.close()
                            return item
                    raise ValueError('已有导出任务正在运行，请在导出进度中等待完成或取消后重试')
                ident = uuid.uuid4().hex
                item = dict(id=ident, scan_id=scan.name, kind=kind, compression=compression,
                            started=datetime.now(timezone.utc).isoformat(), state='RUNNING',
                            stage='PREPARING', message='准备导出完整归档' if kind == 'full' else '准备导出人工确认增量',
                            completed=None, total=None, unit=None, elapsed_seconds=0)
                with self.connect() as conn:
                    self.save(conn, item)
                thread = threading.Thread(target=self.run, args=(scan, item, leases), daemon=True)
                self.threads.add(thread)
                thread.start()
            except BaseException:
                leases.close()
                raise
        return dict(item)

    def run(self, scan, item, leases):
        started = time.monotonic()
        last_write = 0
        progress_lock = threading.Lock()

        def update(changes):
            with progress_lock:
                write_progress(changes)

        def write_progress(changes):
            nonlocal last_write
            old_stage = item['stage']
            item.update(changes)
            now = time.monotonic()
            if self.stopping.is_set():
                raise OperationCancelled('服务退出，导出已停止；原扫描与人工记录保留。')
            if now-last_write < .5 and item['stage'] == old_stage:
                return
            with self.connect() as conn:
                conn.execute('BEGIN IMMEDIATE')
                current = conn.execute('SELECT state FROM jobs WHERE id=?', (item['id'],)).fetchone()
                if current and current[0] == 'CANCELLING':
                    raise OperationCancelled('已取消导出；原扫描与人工记录保留。')
                item['elapsed_seconds'] = round(now-started, 1)
                self.save(conn, item)
            last_write = now

        try:
            exports = no_links(self.data/'exports'); exports.mkdir(exist_ok=True)
            name = item['id'] + ('.ecra-report' if item['kind'] == 'full' else '.ecra-review-delta')
            target = exports/name
            if item['kind'] == 'full':
                export_report(scan, target, compression=item['compression'], progress=update)
            else:
                export_delta(scan, target, progress=update)
            result = dict(download='/api/download/'+name, filename=name, bytes=target.stat().st_size)
            if item['kind'] == 'full':
                with zipfile.ZipFile(target) as archive:
                    actual = 'compact' if archive.getinfo('scan.db').compress_type == zipfile.ZIP_BZIP2 else 'deflate'
                result.update(compression=actual, compression_fallback=actual != item['compression'])
            item.update(state='COMPLETE', stage='COMPLETE', message='导出完成，可下载完整结果包', result=result)
        except OperationCancelled as exc:
            item.update(state='CANCELLED', error=str(exc))
        except Exception as exc:
            item.update(state='FAILED', error='导出失败：'+str(exc)+'。请检查数据目录和系统临时目录的可用空间及归档状态；原扫描与人工记录保留。')
            try:
                (self.folder/(item['id']+'.trace.txt')).write_text(traceback.format_exc(), encoding='utf-8')
            except OSError:
                pass
        finally:
            item['elapsed_seconds'] = round(time.monotonic()-started, 1)
            try:
                with self.connect() as conn:
                    self.save(conn, item)
            finally:
                leases.close()
                with self.lock:
                    self.threads.discard(threading.current_thread())

    def cancel(self, ident):
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT payload FROM jobs WHERE id=?', (ident,)).fetchone()
            if row is None:
                raise ValueError('导出任务不存在')
            item = json.loads(row[0])
            if item['state'] in ACTIVE:
                item.update(state='CANCELLING', message='正在安全取消导出')
                self.save(conn, item)
        return item

    def close(self):
        with self.lock:
            self.stopping.set()
            threads = list(self.threads)
        for thread in threads:
            thread.join(timeout=10)
