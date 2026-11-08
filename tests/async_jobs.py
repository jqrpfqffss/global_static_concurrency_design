"""Bounded observation and teardown for real asynchronous product fixtures.

There is no product promise that a migration finishes in 10/30 seconds or a
derived task in 40. The 600-second test ceiling follows the existing command
budget and includes slow Windows FULL-sync I/O. Business assertions still
require the actual terminal state; cleanup never turns interruption into success.
"""
import time


RUNNING = {'RUNNING', 'STOP_REQUESTED'}
OBSERVATION_SECONDS = 600
CLEANUP_SECONDS = 120


def _get(client, path):
    response = client.get(path)
    if response.status_code != 200:
        raise AssertionError('Async fixture status unavailable: '+response.text)
    return response.json()


def wait_migration(client, identity, *, timeout=OBSERVATION_SECONDS):
    deadline = time.monotonic()+timeout
    while True:
        row = _get(client, '/api/migrations/'+identity)
        if row['state'] != 'RUNNING':
            return row
        if time.monotonic() >= deadline:
            raise AssertionError('Migration did not reach a real terminal state within the test budget: '+repr(row))
        time.sleep(.1)


def settle_migration(case, client, identity, *, timeout=CLEANUP_SECONDS):
    # Migrations expose no cancel endpoint. Wait for their real state/lease;
    # never edit a job row or delete its active lock to complete a test.
    from ecra.storage_activity import DataActivity, DataBusy
    deadline = time.monotonic()+timeout
    try:
        wait_migration(client, identity, timeout=timeout)
        while True:
            try:
                with DataActivity(case.data, exclusive=True, purpose='legacy-import'):
                    return
            except DataBusy:
                if time.monotonic() >= deadline:
                    raise AssertionError('Migration terminal row did not release its owner lease; fixture retained: '+str(case.base))
                time.sleep(.05)
    except BaseException:
        case._retain_async_root = True
        raise


def wait_task(client, manager, identity, *, timeout=OBSERVATION_SECONDS, settle_timeout=CLEANUP_SECONDS):
    deadline = time.monotonic()+timeout
    while True:
        row = _get(client, '/api/tasks/'+identity)
        if row['state'] not in RUNNING:
            break
        if time.monotonic() >= deadline:
            raise AssertionError('Owned task did not reach a real terminal state within the test budget: '+repr(row))
        time.sleep(.1)
    deadline = time.monotonic()+settle_timeout
    while manager.active is not None:
        if time.monotonic() >= deadline:
            raise AssertionError('Owned task terminal row did not release supervisor ownership: '+repr(row))
        time.sleep(.05)
    return row


def stop_and_settle_tasks(case, client, manager, *, timeout=CLEANUP_SECONDS):
    # Register after the TestClient exit cleanup so this runs while its real
    # API is open. A business failure still fails after ordinary stop/settle.
    if manager.active is None:
        return
    try:
        identity = manager.active[0]
        row = _get(client, '/api/tasks/'+identity)
        if row['state'] in RUNNING:
            response = client.post('/api/tasks/'+identity+'/stop')
            if response.status_code != 200:
                raise AssertionError('Owned fixture could not request product stop: '+response.text)
        wait_task(client, manager, identity, timeout=timeout, settle_timeout=timeout)
    except BaseException:
        case._retain_async_root = True
        raise


def cleanup_temporary(case, temporary):
    if getattr(case, '_retain_async_root', False):
        # Only this disposable test directory is retained for diagnosis. No
        # product state is rewritten and no active file is recursively removed.
        temporary._finalizer.detach()
    else:
        # Also protect failures before an HTTP start response supplied an id.
        # Probe only existing locks; an unknown active fixture is retained.
        from ecra.storage_activity import DataActivity, DataBusy
        data = getattr(case, 'data', None)
        try:
            if data is not None:
                deadline = time.monotonic()+CLEANUP_SECONDS
                for purpose in ('legacy-import', 'scan-budget'):
                    if not (data/'settings'/(purpose+'-activity.lock')).is_file():
                        continue
                    while True:
                        try:
                            with DataActivity(data, exclusive=True, purpose=purpose):
                                break
                        except DataBusy:
                            if time.monotonic() >= deadline:
                                raise AssertionError('Async fixture still has a live owner; retained: '+str(case.base))
                            time.sleep(.05)
            temporary.cleanup()
        except BaseException:
            temporary._finalizer.detach()
            raise
