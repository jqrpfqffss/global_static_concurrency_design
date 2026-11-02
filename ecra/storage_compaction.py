"""Only new owned closed files; no deletion, directory compression or rewrite."""
import json
import os
from pathlib import Path
import re

from .workspace import no_links,studio_data_root
from .storage_policy import snapshot


class ScanStorage:
    def __init__(self,data,out,cache,policy):
        self.root=studio_data_root(data);self.out=no_links(out);self.cache=no_links(cache);self.policy=snapshot(self.root,policy)
        if self.out.parent!=self.root/'scans' or not self.cache.is_relative_to(self.root):raise ValueError('空间整理只允许本次外置扫描及其缓存')
        self.receipt=no_links(self.out/'diagnostics/storage-compaction.jsonl')
        self.receipt.parent.mkdir(parents=True,exist_ok=True)

    def compress(self,path,kind):
        path=no_links(path)
        allowed=(kind=='authority' and path.parent==self.out and re.fullmatch(r'scan\.db\.[a-f0-9]{32}\.pending',path.name)
                 or kind=='worker' and path.parent==self.out/'workers' and path.name.endswith('.response.json')
                 or kind=='cache' and path.parent==self.cache/'tu-v1' and re.fullmatch(r'[a-f0-9]{64}\.facts',path.name))
        if not allowed:raise ValueError('文件不属于本次新建封闭载荷，拒绝空间整理')
        row=dict(file=str(path.relative_to(self.root)),kind=kind,policy=self.policy)
        try:
            if self.policy['mode']=='off':row.update(status='SKIPPED_POLICY_OFF',byte_verified=False)
            elif os.name!='nt':row.update(status='SKIPPED_UNSUPPORTED_PLATFORM',byte_verified=False)
            else:
                from .windows_storage import WindowsFiles
                row.update(WindowsFiles().compress(path));row.pop('path',None)
            return row
        except BaseException as exc:
            row.update(status='FAILED',error=type(exc).__name__+': '+str(exc));raise
        finally:
            with self.receipt.open('a',encoding='utf-8') as stream:
                stream.write(json.dumps(row,ensure_ascii=True,separators=(',',':'))+'\n');stream.flush();os.fsync(stream.fileno())
