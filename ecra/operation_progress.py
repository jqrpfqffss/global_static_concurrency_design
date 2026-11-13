"""Optional cooperative progress for long, bounded archive operations."""
from contextlib import contextmanager
import sqlite3
import threading


class OperationCancelled(Exception):
    pass


@contextmanager
def sqlite_progress(connection, progress):
    if progress is None:
        yield connection
        return

    # PRAGMA integrity_check can spend minutes inside a single VM opcode;
    # SQLite's instruction-count progress handler does not cover that wait.
    # interrupt() is explicitly safe from another thread, including on the
    # standard connection with check_same_thread=True.
    stop = threading.Event()
    failures = []
    def heartbeat():
        while not stop.wait(.5):
            try:
                progress({})
            except BaseException as exc:
                failures.append(exc)
                connection.interrupt()
                return
    thread = threading.Thread(target=heartbeat, daemon=True)
    # If cancellation lands between two short statements, interrupt() has no
    # pending operation to stop. Keep it latched for subsequent graph reads.
    connection.set_progress_handler(lambda: int(bool(failures)), 10000)
    thread.start()
    try:
        yield connection
    except sqlite3.OperationalError:
        if failures:
            raise failures[0]
        progress({})
        raise
    finally:
        stop.set()
        thread.join()
        connection.set_progress_handler(None, 0)
    if failures:
        raise failures[0]
