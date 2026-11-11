"""Read the supervisor's TU admission limit without changing scan inputs."""
import json
import os
from pathlib import Path
import stat
import time
import traceback

from .scan_stop import check_stop

PRESSURE_FILE = 'ECRA_RESOURCE_PRESSURE_FILE'
PRESSURE_NAME = 'resource-pressure.json'
EVENT_LOG = 'resource_control.jsonl'
RETRY_DELAYS = (0.05, 0.10, 0.20, 0.40)
RETRY_DEADLINE = 0.8
STOP_POLL_SECONDS = 0.02


class ResourceControlError(RuntimeError):
    def __init__(self, record):
        super().__init__(record['message'])
        self.resource_control = record


def check_extraction_stop():
    check_stop('扫描已响应停止请求，已保存的数据和上一次有效扫描保留。')


def _is_directory(path):
    # The Windows CRT can report EACCES when asked to open a directory.
    try:
        return stat.S_ISDIR(path.stat().st_mode)
    except OSError:
        return False


def read_limit(path, budget, *, completed, total, on_event):
    started = time.monotonic()
    deadline = started + RETRY_DEADLINE
    attempts = 0
    error = None

    def event(status, operation, cause, message):
        record = dict(status=status, operation=operation, path=os.fspath(path),
                      attempts=attempts, retries=max(0, attempts - 1),
                      elapsed_seconds=time.monotonic() - started,
                      completed_units=completed, total_units=total, message=message,
                      exception_type=type(cause).__name__, errno=getattr(cause, 'errno', None),
                      winerror=getattr(cause, 'winerror', None),
                      exception_chain=''.join(traceback.format_exception(type(cause), cause, cause.__traceback__)))
        on_event(record)
        return record

    def invalid(exc, operation='validate'):
        return ResourceControlError(event('INVALID', operation, exc,
            f'资源调度信息无效，扫描已停止。{path}：{exc}。请查看任务日志。'))

    try:
        check_extraction_stop()
        if not path:
            exc = ValueError(f'{PRESSURE_FILE} 已设置，但路径为空')
            raise invalid(exc) from exc
        file = Path(path)
        while True:
            attempts += 1
            try:
                with file.open(encoding='utf-8-sig') as stream:
                    value = json.load(stream)
                if not isinstance(value, dict) or type(value.get('parallel_limit')) is not int:
                    raise ValueError('要求 JSON 对象包含整数 parallel_limit')
                if not 1 <= value['parallel_limit'] <= 8:
                    raise ValueError('parallel_limit 必须为 1–8')
            except ValueError as exc:
                raise invalid(exc) from exc
            except (IsADirectoryError, NotADirectoryError) as exc:
                raise invalid(exc, 'read') from exc
            except OSError as exc:
                if isinstance(exc, PermissionError) and _is_directory(file):
                    record = event('INVALID', 'read', exc, f'资源调度路径是目录，扫描已停止。{path}。请查看任务日志。')
                    raise ResourceControlError(record) from exc
                error = exc
                retryable = isinstance(exc, (PermissionError, FileNotFoundError))
                if retryable and attempts <= len(RETRY_DELAYS) and time.monotonic() < deadline:
                    if attempts == 1:
                        event('RETRYING', 'read', exc, f'资源调度信息暂时无法读取，正在重试。已处理 {completed}/{total}。')
                    wake_at = min(deadline, time.monotonic() + RETRY_DELAYS[attempts - 1])
                    while True:
                        check_extraction_stop()
                        remaining = wake_at - time.monotonic()
                        if remaining <= 0:
                            break
                        time.sleep(min(remaining, STOP_POLL_SECONDS))
                    if time.monotonic() < deadline:
                        continue
                message = '资源调度信息持续无法读取' if retryable else '资源调度信息无法读取'
                record = event('FAILED', 'read', exc,
                    f'{message}，扫描已停止。已保存的数据和诊断保留，请查看任务日志后重试。')
                raise ResourceControlError(record) from exc
            check_extraction_stop()
            if error is not None:
                event('RECOVERED', 'read', error, '资源调度信息读取已恢复，继续扫描。')
            return min(budget, value['parallel_limit'])
    except KeyboardInterrupt:
        if error is not None:
            event('CANCELLED', 'read', error, '扫描已响应停止请求，资源调度读取重试结束。')
        raise
