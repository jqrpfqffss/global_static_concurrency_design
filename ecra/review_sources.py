"""Citation reads from the same immutable source text exposed to the model."""
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
from pathlib import Path

CURRENT=ContextVar('ecra_archived_review_sources',default=None)


class ArchivedSources:
    def __init__(self,root,provider):
        self.root=Path(root).resolve();self.provider=provider

    def read(self,path):
        path=Path(path).resolve()
        if not path.is_relative_to(self.root):raise ValueError('复核引用不属于当前工程')
        file=path.relative_to(self.root).as_posix()
        ref=self.provider.archived_source(file)
        if not ref['available']:raise ValueError('归档缺少对应源码，不能回退到实时文件：'+file)
        if not isinstance(ref.get('sha256'),str) or len(ref['sha256'])!=64:
            raise ValueError('归档源码缺少原始字节指纹：'+file)
        parts=[];offset=0;expected=None
        while True:
            page=self.provider.text(ref['text_node'],offset=offset,limit=16384)
            if expected is None:expected=page['hash']
            if page['hash']!=expected:raise ValueError('归档源码在读取期间变化，不能混用证据')
            parts.append(page['value']);offset=page['next_offset']
            if offset is None:break
        return ''.join(parts),ref['sha256']


@contextmanager
def source_scope(provider):
    token=CURRENT.set(provider)
    try:yield
    finally:CURRENT.reset(token)


def read_source(path):
    current=CURRENT.get()
    if current is not None:return current.read(path)
    from .input_snapshot import read_analysis_bytes
    raw=read_analysis_bytes(path)
    return raw.decode('utf-8','replace'),hashlib.sha256(raw).hexdigest()
