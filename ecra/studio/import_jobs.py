"""Durable import progress, with private uploads and one importer per data root."""
from contextlib import contextmanager, ExitStack
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import sqlite3
import threading
import time
import traceback
import uuid
import zipfile

from ..operation_progress import OperationCancelled
from ..report_package import import_report
from ..storage_activity import DataActivity, DataBusy
from ..workspace import no_links


ACTIVE = {'UPLOADING', 'RUNNING', 'CANCELLING'}
MAX_UPLOAD_BYTES = 128 * 1024**3


def _identity(value):
    if not isinstance(value, str) or re.fullmatch('[a-f0-9]{32}', value) is None:
        raise ValueError('导入任务身份无效')
    return value


class _Upload:
    def __init__(self, item, path, leases):
        self.item, self.path, self.leases = item, path, leases
        self.started = time.monotonic()
        self.last_write = 0
        self.handed_off = False


class ImportJobs:
    def __init__(self, data, *, preflight=None):
        self.data = Path(data)
        self.folder = no_links(self.data/'work/import-jobs')
        self.folder.mkdir(parents=True, exist_ok=True)
        self.uploads = no_links(self.folder/'uploads')
        self.uploads.mkdir(exist_ok=True)
        self.preflight = preflight
        self.threads = set()
        self.lock = threading.Lock()
        self.stopping = threading.Event()
        with self.connect() as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, started TEXT, state TEXT, payload TEXT)')
        try:
            with DataActivity(self.data), DataActivity(self.data, exclusive=True, purpose='import-job'):
                with self.connect() as conn:
                    for raw, in conn.execute("SELECT payload FROM jobs WHERE state IN ('UPLOADING','RUNNING','CANCELLING')").fetchall():
                        item = json.loads(raw)
                        item.update(state='INTERRUPTED', error='上次导入服务已退出，请重新导入；已有扫描与人工记录保留。')
                        self.save(conn, item)
                        self._remove_upload(item['id'])
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
        with self.connect() as conn:
            row = conn.execute('SELECT payload FROM jobs WHERE id=?', (_identity(ident),)).fetchone()
        if row is None:
            raise ValueError('导入任务不存在')
        return json.loads(row[0])

    def history(self):
        with self.connect() as conn:
            return dict(items=[json.loads(row[0]) for row in conn.execute('SELECT payload FROM jobs ORDER BY started DESC LIMIT 20')])

    def _remove_upload(self, ident):
        # This directory is owned solely by the identified upload. Resolve and
        # reject links before a recursive removal; never remove a caller path.
        folder = no_links(self.uploads/_identity(ident))
        if folder.parent != self.uploads.resolve():
            raise ValueError('导入临时目录不属于当前工作目录')
        if folder.exists():
            shutil.rmtree(folder)

    def begin_upload(self, filename, total=None, *, ident=None):
        if not isinstance(filename, str) or len(filename.encode('utf-8', errors='surrogatepass')) > 4096:
            raise ValueError('导入文件名过长或无效')
        filename = filename.replace('\\', '/').rsplit('/', 1)[-1] or '导入结果包.ecra-report'
        if total is not None and (type(total) is not int or total < 0 or total > MAX_UPLOAD_BYTES):
            raise ValueError('上传包超过128GiB预算或长度无效')
        ident = uuid.uuid4().hex if ident is None else _identity(ident)
        with self.lock:
            if self.stopping.is_set():
                raise ValueError('服务正在退出，请重新启动后导入')
            leases = ExitStack()
            created = False
            try:
                leases.enter_context(DataActivity(self.data))
                try:
                    leases.enter_context(DataActivity(self.data, exclusive=True, purpose='import-job'))
                except DataBusy as exc:
                    raise ValueError('已有导入任务正在运行，请到数据与共享等待完成或取消后重试') from exc
                if total is not None and shutil.disk_usage(self.uploads).free < total + 512*1024**2:
                    raise ValueError('上传结果包所需磁盘空间不足，请释放数据目录空间后重试')
                item = dict(id=ident, filename=filename, scan_id=None, kind='full',
                            started=datetime.now(timezone.utc).isoformat(), state='UPLOADING',
                            stage='UPLOAD', message='正在上传完整结果包', completed=0,
                            total=total, unit='bytes', elapsed_seconds=0)
                with self.connect() as conn:
                    if conn.execute('SELECT 1 FROM jobs WHERE id=?', (ident,)).fetchone():
                        raise ValueError('导入任务身份已存在，请重新选择结果包')
                    folder = no_links(self.uploads/ident)
                    folder.mkdir()
                    created = True
                    self.save(conn, item)
                return _Upload(item, folder/'input.ecra-report', leases)
            except BaseException:
                try:
                    if created:
                        self._remove_upload(ident)
                finally:
                    leases.close()
                raise

    def upload_progress(self, upload, completed, *, force=False):
        if completed > MAX_UPLOAD_BYTES:
            raise ValueError('上传包超过128GiB预算')
        now = time.monotonic()
        if self.stopping.is_set():
            raise OperationCancelled('服务退出，导入上传已停止；已有扫描与人工记录保留。')
        if not force and now-upload.last_write < .5:
            return
        if shutil.disk_usage(self.uploads).free < 512*1024**2:
            raise ValueError('数据目录剩余空间不足，请释放空间后重新导入')
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            state = conn.execute('SELECT state FROM jobs WHERE id=?', (upload.item['id'],)).fetchone()
            if state and state[0] == 'CANCELLING':
                raise OperationCancelled('已取消导入上传；已有扫描与人工记录保留。')
            upload.item.update(completed=completed, elapsed_seconds=round(now-upload.started, 1))
            self.save(conn, upload.item)
        upload.last_write = now

    def finish_upload(self, upload, completed):
        self.upload_progress(upload, completed, force=True)
        if upload.item['total'] is not None and upload.item['total'] != completed:
            raise ValueError('上传长度与结果包声明不一致，请重新导入完整文件')
        with self.lock:
            if self.stopping.is_set():
                raise OperationCancelled('服务退出，导入已停止；已有扫描与人工记录保留。')
            with self.connect() as conn:
                conn.execute('BEGIN IMMEDIATE')
                state = conn.execute('SELECT state FROM jobs WHERE id=?', (upload.item['id'],)).fetchone()
                if state and state[0] == 'CANCELLING':
                    raise OperationCancelled('已取消导入；已有扫描与人工记录保留。')
                upload.item.update(state='RUNNING', stage='PREPARING', message='上传完成，准备校验完整归档',
                                   completed=None, total=None, unit=None, upload_bytes=completed)
                self.save(conn, upload.item)
            thread = threading.Thread(target=self.run, args=(upload,), daemon=True)
            self.threads.add(thread)
            try:
                thread.start()
                upload.handed_off = True
            except BaseException:
                self.threads.discard(thread)
                raise
        return dict(upload.item)

    def abort_upload(self, upload, exc):
        if upload.handed_off:
            return
        try:
            upload.item.update(state='CANCELLED' if isinstance(exc, OperationCancelled) else 'FAILED',
                               error='导入上传未完成：'+str(exc)+'；本次未发布结果，已有扫描与人工记录保留。',
                               elapsed_seconds=round(time.monotonic()-upload.started, 1))
            with self.connect() as conn:
                self.save(conn, upload.item)
        finally:
            try:
                self._remove_upload(upload.item['id'])
            finally:
                upload.leases.close()

    def run(self, upload):
        item = upload.item
        last_write = 0
        progress_lock = threading.Lock()

        def update(changes):
            nonlocal last_write
            with progress_lock:
                old_stage = item['stage']
                item.update(changes)
                now = time.monotonic()
                if self.stopping.is_set():
                    raise OperationCancelled('服务退出，导入已停止；已有扫描与人工记录保留。')
                if now-last_write < .5 and item['stage'] == old_stage:
                    return
                with self.connect() as conn:
                    conn.execute('BEGIN IMMEDIATE')
                    current = conn.execute('SELECT state FROM jobs WHERE id=?', (item['id'],)).fetchone()
                    if current and current[0] == 'CANCELLING':
                        raise OperationCancelled('已取消导入；已有扫描与人工记录保留。')
                    item['elapsed_seconds'] = round(now-upload.started, 1)
                    self.save(conn, item)
                last_write = now

        try:
            update({})
            if self.preflight:
                self.preflight(upload.path)
            result = import_report(upload.path, self.data, progress=update)
            item.update(state='COMPLETE', stage='COMPLETE', message='导入完成，完整性已验证，可继续人工确认' if result.get('integrity_verified') else '导入完成，可继续人工确认',
                        scan_id=result['scan_id'], result=result)
        except OperationCancelled as exc:
            item.update(state='CANCELLED', error=str(exc))
        except Exception as exc:
            if isinstance(exc, (zipfile.BadZipFile, EOFError)):
                item.update(code='INVALID_REPORT_ARCHIVE', error='结果包导入阶段失败：文件不是完整有效的 ZIP 结果包，或包内容已损坏。'
                            '本次未发布结果，已有扫描与人工记录保留；请重新获取完整的 .ecra-report 备份。技术信息：'+str(exc))
            else:
                item.update(error='导入失败：'+str(exc)+'。请检查归档内容和磁盘空间；已有扫描与人工记录保留。')
            item['state'] = 'FAILED'
            try:
                (self.folder/(item['id']+'.trace.txt')).write_text(traceback.format_exc(), encoding='utf-8')
            except OSError:
                pass
        finally:
            item['elapsed_seconds'] = round(time.monotonic()-upload.started, 1)
            try:
                with self.connect() as conn:
                    self.save(conn, item)
            finally:
                try:
                    self._remove_upload(item['id'])
                finally:
                    upload.leases.close()
                    with self.lock:
                        self.threads.discard(threading.current_thread())

    def cancel(self, ident):
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT payload FROM jobs WHERE id=?', (_identity(ident),)).fetchone()
            if row is None:
                raise ValueError('导入任务不存在')
            item = json.loads(row[0])
            if item['state'] in ACTIVE:
                item.update(state='CANCELLING', message='正在安全取消导入')
                self.save(conn, item)
        return item

    def close(self):
        with self.lock:
            self.stopping.set()
            threads = list(self.threads)
        for thread in threads:
            thread.join(timeout=10)
