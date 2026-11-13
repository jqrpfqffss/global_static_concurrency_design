"""Complete validation of an isolated imported database, using bounded workers.

The receiver never trusts a publisher's receipt to skip any check. Workers only
read a private, already byte-verified staging file. The parent's read transaction
pins rollback-journal databases for the whole operation; WAL uses the sequential
validator because independent connections cannot share its exact read view.
"""
from contextlib import closing
import multiprocessing
import os
from pathlib import Path
import threading
import time

from .operation_progress import OperationCancelled, sqlite_progress
from .scan_store import (EvidenceProvider, connect_readonly, _validate_nodes,
                         _validate_integrity, _validate_foreign_keys, _validate_identity)


def _worker(path, task, cancelled, channel):
    lock = threading.Lock()
    last = 0.0
    completed = 0
    def progress(change):
        nonlocal last, completed
        owner = multiprocessing.parent_process()
        if cancelled.is_set() or (owner is not None and not owner.is_alive()):
            raise OperationCancelled('导入已取消')
        with lock:
            completed = change.get('completed', completed)
            now = time.monotonic()
            if 'completed' in change and now-last >= .25:
                channel.send(('progress', change['completed']))
                last = now
    try:
        result = None
        with closing(connect_readonly(path)) as conn, sqlite_progress(conn, progress):
            conn.execute('PRAGMA cache_size=-'+('524288' if task['kind']=='database' else '131072'))
            conn.execute('BEGIN')
            if task['kind'] == 'database':
                _validate_integrity(conn)
                result = _validate_identity(conn)
            elif task['kind'] == 'references':
                _validate_foreign_keys(conn)
            elif task['kind'] == 'graph':
                _validate_nodes(conn, node_range=task['range'], progress=progress)
                result = completed
            else:
                from .scan_store import _validate_projections
                _validate_projections(conn, progress=progress)
        channel.send(('done', result))
    except BaseException as exc:
        channel.send(('error', type(exc).__name__+': '+str(exc)))
    finally:
        channel.close()


def validate_imported_database(path, *, progress=None, parallel_threshold=256*1024**2):
    """Validate every byte-level structure, graph hash and projection before publish.

    Up to six processes: full SQLite integrity and FK checks, a full projection
    comparison, and four disjoint graph ranges scheduled as capacity is freed.
    This avoids the Python GIL without loading the whole graph in memory.
    """
    notify = progress or (lambda _: None)
    path = Path(path)
    with closing(connect_readonly(path)) as pinned, sqlite_progress(pinned, progress):
        pinned.execute('BEGIN')
        pinned.execute('SELECT id FROM nodes LIMIT 1').fetchone()
        if path.stat().st_size < parallel_threshold or pinned.execute('PRAGMA journal_mode').fetchone()[0] == 'wal':
            return EvidenceProvider(path).validate(deep=True, progress=progress)
        low, high, count = pinned.execute('SELECT min(id),max(id),count(*) FROM nodes').fetchone()
        if not count:
            return EvidenceProvider(path).validate(deep=True, progress=progress)
        width = max(1, (high-low+4)//4)
        tasks = [dict(kind='database'), dict(kind='references')]
        tasks.extend(dict(kind='graph', range=(start, min(high, start+width-1)))
                     for start in range(low, high+1, width))
        tasks.append(dict(kind='projections'))
        context = multiprocessing.get_context('spawn')
        cancelled = context.Event()
        running = []; all_workers = []; done = 0; graph_done = 0; binding = None; completed_tasks = []
        capacity = min(6, os.cpu_count() or 1)
        total = len(tasks); pending = list(tasks)
        notify(dict(stage='VERIFY_ALL', message='并行校验数据库、全部证据哈希与查询索引',
                    completed=0, total=total, unit='checks'))
        try:
            while pending or running:
                notify({})
                while pending and len(running)<capacity:
                    task = pending.pop(0)
                    receive, send = context.Pipe(duplex=False)
                    process = context.Process(target=_worker, args=(str(path), task, cancelled, send))
                    process.start(); send.close()
                    entry = dict(process=process, channel=receive, task=task, nodes=0, started=time.monotonic())
                    running.append(entry); all_workers.append(entry)
                changed = False
                for entry in list(running):
                    channel = entry['channel']; terminal = False; pipe_closed = False
                    while True:
                        try:
                            if not channel.poll(): break
                            state, payload = channel.recv()
                        except (EOFError, BrokenPipeError): pipe_closed = True; break
                        if state == 'error':
                            raise ValueError('结果包完整性校验失败：'+payload)
                        if state == 'progress':
                            entry['nodes'] = payload
                            changed = True
                        elif state == 'done':
                            if entry['task']['kind']=='database': binding = payload
                            if entry['task']['kind']=='graph': graph_done += payload
                            done += 1; terminal = True; changed = True
                            completed_tasks.append(dict(entry['task'], seconds=round(time.monotonic()-entry['started'],3)))
                            notify(dict(validated_task=completed_tasks[-1], validated_tasks=list(completed_tasks)))
                            break
                    if terminal:
                        entry['process'].join(timeout=1)
                        channel.close(); running.remove(entry)
                    elif not entry['process'].is_alive():
                        # A child may send its terminal message between the
                        # empty poll above and exit. Drain that message on the
                        # next iteration before classifying an unexpected exit.
                        try:
                            if not pipe_closed and channel.poll(): continue
                        except (EOFError, BrokenPipeError): pass
                        raise ValueError('结果包完整性校验进程意外退出，未发布数据')
                if changed:
                    # Only completed independent checks contribute to this bar;
                    # graph node counts additionally make long checks observable.
                    checked = graph_done+sum(e['nodes'] for e in running if e['task']['kind']=='graph')
                    remaining={t['kind'] for t in pending} | {e['task']['kind'] for e in running}
                    names=[title for kind,title in [('database','数据库结构'),('references','外键引用'),('graph','证据哈希'),('projections','查询索引')] if kind in remaining]
                    detail='；正在核对：'+'、'.join(names) if names else '；全部检查已通过'
                    notify(dict(stage='VERIFY_ALL', message=f'完整性校验已通过 {done}/{total} 项'+detail,
                                completed=done, total=total, unit='checks', graph_completed=min(checked,count), graph_total=count))
                if running: cancelled.wait(.1)
            if binding is None:
                raise ValueError('结果包数据库完整性校验未完成')
            if graph_done != count:
                raise ValueError('结果包证据节点校验未完全覆盖，未发布数据')
            return binding
        finally:
            cancelled.set()
            deadline = time.monotonic()+5
            for entry in all_workers:
                process = entry['process']
                process.join(timeout=max(0, deadline-time.monotonic()))
                if process.is_alive(): process.terminate(); process.join()
                entry['channel'].close()
                process.close()
