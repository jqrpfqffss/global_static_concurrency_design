"""Background whole-root transfers with persistent restartable operation status."""
from datetime import datetime,timezone
import json
from pathlib import Path
import threading
import traceback
import uuid

from ..common import write_json
from ..data_transfer import registry,transfer
from ..report_package import IDENTITY
from ..storage_activity import DataActivity,DataBusy
from ..workspace import no_links,studio_data_root


class RootTransfers:
    def __init__(self,data):
        self.data=studio_data_root(data);self.folder=registry(self.data)
        self.folder.mkdir(parents=True,exist_ok=True)
        try:lease=DataActivity(self.folder,exclusive=True,purpose='root-transfer').__enter__()
        except DataBusy:return
        try:
            for path in self.folder.glob('job-*.json'):
                item=json.loads(no_links(path).read_text('utf-8'))
                if item.get('state') in {'RUNNING','COPYING','VALIDATING'}:
                    item.update(state='INTERRUPTED',error='上次复制进程已退出，原目录与已校验副本保留。可重新校验后恢复。')
                    write_json(path,item)
        finally:lease.__exit__(None,None,None)

    def path(self,ident):
        if not isinstance(ident,str) or not IDENTITY.fullmatch(ident):raise ValueError('整套复制任务身份无效')
        return no_links(self.folder/('job-'+ident+'.json'))

    def get(self,ident):
        path=self.path(ident)
        if not path.is_file():raise ValueError('整套复制任务不存在')
        return json.loads(path.read_text('utf-8'))

    def history(self):
        return sorted([json.loads(no_links(p).read_text('utf-8')) for p in self.folder.glob('job-*.json')],
            key=lambda item:item['started'],reverse=True)

    def start(self,source,target,*,expected=None,resume=None):
        source=studio_data_root(source)
        if not isinstance(target,str) or not Path(target).is_absolute():raise ValueError('请选择目标数据根的绝对路径')
        target=studio_data_root(target)
        # Do not let a missing preview become an expensive background failure.
        if resume is None and (not isinstance(expected,str) or len(expected)!=64):raise ValueError('请先检查整套复制计划')
        lease=DataActivity(self.folder,exclusive=True,purpose='root-transfer').__enter__()
        ident=uuid.uuid4().hex;path=self.path(ident)
        item=dict(id=ident,state='RUNNING',started=datetime.now(timezone.utc).isoformat(),
            source=str(source),target=str(target))
        try:
            write_json(path,item)
            def update(value):
                item.update({k:v for k,v in value.items() if k!='id'})
                write_json(path,item)
            def run():
                try:
                    result=transfer(source,str(target),expected=expected,resume=resume,progress=update)
                    update(dict(state='COMPLETE',result={k:v for k,v in result.items() if k!='files'},journal=result['journal']))
                except BaseException as exc:
                    (self.folder/('job-'+ident+'.trace.txt')).write_text(traceback.format_exc(),'utf-8')
                    update(dict(state='INTERRUPTED' if isinstance(exc,(KeyboardInterrupt,InterruptedError)) else 'FAILED',error=str(exc)))
                finally:lease.__exit__(None,None,None)
            threading.Thread(target=run,daemon=True).start()
        except BaseException:
            lease.__exit__(None,None,None);raise
        return dict(id=ident,state='RUNNING')

    def resume(self,ident):
        previous=self.get(ident)
        if previous['state'] not in {'INTERRUPTED','FAILED','PUBLISHING'} or not previous.get('journal'):
            raise ValueError('只有保留了校验记录的中断/失败任务可恢复；否则重新检查计划')
        return self.start(previous['source'],previous['target'],resume=previous['journal'])
