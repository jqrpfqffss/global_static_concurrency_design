"""Recoverable display of task metadata, without repairing its source bytes."""
from ..report_package import IDENTITY


def display_record(path, read, *, ident, states, action, validate=None):
    """A broken history entry must not hide independent, valid work.

    The UNREADABLE row is a diagnostic, never a recovered execution result or
    permission to retry from unverified configuration. The original is retained.
    """
    try:
        value = read(path)
        if (not isinstance(value, dict) or value.get('id') != ident
                or not IDENTITY.fullmatch(ident)
                or not isinstance(value.get('started'), str) or not value['started']
                or not isinstance(value.get('state'), str)
                or value.get('state') not in states):
            raise ValueError('任务身份、开始时间或状态字段无效')
        if validate is not None and not validate(value):
            raise ValueError('任务关键字段缺失或无效')
        return value
    except (OSError, ValueError, TypeError) as exc:
        return dict(id=ident, state='UNREADABLE', started='', metadata_error=True,
                    error='任务记录无法读取，不能确定其执行结果：'+str(path)+'。'+str(exc)+
                          '。原文件与独立扫描、人工记录均保留；'+action)
