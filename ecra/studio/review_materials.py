"""Studio edits only the two config originals; tasks consume frozen copies."""
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from ..workspace import no_links
from .review_document_forms import library_forms,update_library,context_text,context_markdown
NAMES=('concurrency_cases.md','review_context.md')
MAX_EDIT=4*1024**2


def target(name):
    if name not in NAMES:raise ValueError('只允许编辑 config 中的案例库和工程背景')
    from ..config import CONFIG_HOME
    return no_links(Path(CONFIG_HOME)/name)


def config_source(name):
    path=target(name)
    return None if name=='review_context.md' and not path.exists() else path


def material_lock():
    from ..storage_activity import DataActivity
    from ..config import CONFIG_HOME
    key=str(no_links(Path(CONFIG_HOME))).casefold() if os.name=='nt' else str(no_links(Path(CONFIG_HOME)))
    root=Path(tempfile.gettempdir())/'ECRAStudio-config-locks'/hashlib.sha256(key.encode()).hexdigest()
    # A stable path across different Studio data roots protects the same two
    # originals. No lock/database/cache is placed in config or the firmware.
    return DataActivity(root,exclusive=True,purpose='api')


def inspect_document(path,name):
    if path is None:return dict(available=True,path=None,bytes=0,sha256=None,text='',editable=True,effective_chars=0,notice='明确不提供额外工程背景')
    try:
        path=no_links(Path(path));before=path.stat()
        if not path.is_file():raise ValueError('资料不是普通文件')
        digest=hashlib.sha256();retained=bytearray()
        with path.open('rb') as stream:
            for block in iter(lambda:stream.read(1024**2),b''):
                digest.update(block)
                if len(retained)<MAX_EDIT+1:retained.extend(block[:MAX_EDIT+1-len(retained)])
        after=path.stat()
        if (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns):raise ValueError('资料在读取时变化，请保存文件后重试')
        editable=before.st_size<=MAX_EDIT;warnings=[]
        try:text=retained.decode('utf-8-sig',errors='strict' if editable else 'ignore')
        except UnicodeDecodeError:
            if name=='review_context.md':raise ValueError('工程背景不是有效UTF-8，请在外部编辑器修复编码')
            text=retained.decode('utf-8-sig',errors='replace');editable=False;warnings.append('存在非UTF-8内容；原字节保留，请在外部编辑器修复编码')
        result=dict(available=True,path=str(path),bytes=before.st_size,sha256=digest.hexdigest(),editable=editable,
                    text=text if editable else text[:16000],preview_only=not editable,warnings=warnings)
        if editable and name=='concurrency_cases.md':
            from ..case_library import case_index
            index=case_index(text,warnings.append);result.update(cases=len(index.splitlines()) if index else 0,index_complete=True)
        elif editable:
            result['effective_chars']=len(re.sub(r'<!--.*?-->','',text,flags=re.S).strip())
            if not result['effective_chars']:result['notice']='只有空白或模板注释，当前没有会送入复核的工程背景'
        else:result['notice']='仅展示预览，原文件完整保留；超过4MiB或编码异常时请直接维护 config 中的原文件'
        return result
    except (OSError,ValueError) as exc:return dict(available=False,path=str(path),error=str(exc),text='',editable=False)



def _atomic(path,raw):
    path=no_links(path);path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent,suffix='.pending',delete=False) as f:
        pending=Path(f.name);f.write(raw);f.flush();os.fsync(f.fileno())
    try:os.replace(pending,path)
    finally:pending.unlink(missing_ok=True)



def _describe():
    documents={}
    for name in NAMES:
        path=target(name)
        if not path.exists():
            info=dict(available=True,path=str(path),bytes=0,sha256=None,text='',editable=True,
                notice='文件尚未创建，填写后保存即可；工程背景也可以为空')
        else:info=inspect_document(path,name)
        info['revision']=info.get('sha256') or 'missing'
        info['mode']='config'
        if info.get('editable') and info.get('available'):
            if name=='concurrency_cases.md':
                forms,_=library_forms(info['text'])
                info['entries']=[dict(id=c['id'],form=c['form'],editable=c['editable']) for c in forms]
                info['cases']=len(forms)
            else:info['content']=context_text(info['text'])
        documents[name]=info
    return dict(documents=documents,shared=True,source='config')


def describe():
    with material_lock():return _describe()


def save(data,payload):
    from ..storage_activity import DataActivity
    from ..human_reviews import ReviewConflict
    if not isinstance(payload,dict):raise ValueError('资料填写格式无效')
    action=payload.get('action')
    allowed={'name','revision','action','text'} if action=='context' else {'name','revision','action','case_id','form'}
    if set(payload)-allowed:raise ValueError('资料来源固定为工具 config，不接受外部路径或导入')
    name=payload.get('name');path=target(name)
    if (action=='context' and name!='review_context.md') or (action=='case' and name!='concurrency_cases.md') or action not in {'context','case'}:raise ValueError('资料操作无效')
    with DataActivity(data),material_lock():
        exists=path.exists();old=path.read_bytes() if exists else b''
        revision=hashlib.sha256(old).hexdigest() if exists else 'missing'
        if payload.get('revision')!=revision:raise ReviewConflict('这份资料已被其他窗口或编辑器修改；草稿仍保留，请重新读取后核对')
        if len(old)>MAX_EDIT:raise ValueError('原文件超过4MiB，不能在线改写；请维护 config 原文件')
        try:text=old.decode('utf-8')
        except UnicodeDecodeError:raise ValueError('原文件不是UTF-8；为保留原内容，本次未保存') from None
        selected=None
        if action=='context':updated=context_markdown(payload.get('text'))
        else:
            updated,selected=update_library(text,payload.get('case_id'),payload.get('form'))
            entries,_=library_forms(updated)
            if not any(e['id']==selected for e in entries):raise ValueError('原文件的代码块未闭合，不能安全追加；本次未改写原文')
        raw=updated.encode('utf-8')
        if len(raw)>MAX_EDIT:raise ValueError('资料总大小不能超过4MiB，本次未改写原文件')
        backup=None;saved_copy=None
        if raw!=old or not exists:
            key=hashlib.sha256(str(path.parent).casefold().encode()).hexdigest()
            history=no_links(Path(data)/'settings/review-materials-history'/key)
            if exists:
                backup=no_links(history/(name+'.'+revision+'.md'))
                if backup.exists():
                    if backup.read_bytes()!=old:raise ValueError('原文备份哈希不一致，请保留现场')
                else:_atomic(backup,old)
            # Keep the new version too, so the last saved knowledge is also
            # included in an independent data-root backup/migration.
            saved_copy=no_links(history/(name+'.'+hashlib.sha256(raw).hexdigest()+'.md'))
            if saved_copy.exists():
                if saved_copy.read_bytes()!=raw:raise ValueError('资料版本备份哈希不一致，请保留现场')
            else:_atomic(saved_copy,raw)
            if path.exists()!=exists or (exists and path.read_bytes()!=old):raise ReviewConflict('保存前原文件发生变化；草稿保留，请重新读取后核对')
            try:_atomic(path,raw)
            except PermissionError:raise ValueError('config 原文件不可写；请将完整工具放到可写目录后重试。草稿仍保留') from None
        return dict(saved=True,selected_case_id=selected,backup=str(backup) if backup else None,
                    saved_copy=str(saved_copy) if saved_copy else None,**_describe())


def stage(profile,folder,*,retry=False):
    if retry:return _stage(profile,folder,retry=True)
    with material_lock():return _stage(profile,folder)


def _stage(profile,folder,*,retry=False):
    """Freeze exact bytes adjacent to task YAML, without changing review logic."""
    profile=Path(profile);folder=Path(folder);records={}
    previous=profile.parent/'review-materials.json'
    if retry and not previous.is_file():raise ValueError('原任务缺少复核资料快照；请保留现场并发起新任务，不能用当前 config 冒充原资料')
    frozen=json.loads(previous.read_text('utf-8'))['documents'] if retry and previous.is_file() else None
    for name in NAMES:
        origin=no_links(profile.parent/name) if frozen is not None else config_source(name)
        target=no_links(folder/name)
        if origin is None:raw=b'';_atomic(target,raw);records[name]=dict(path=name,origin=None,bytes=0,sha256=hashlib.sha256(raw).hexdigest(),mode='empty');continue
        origin=no_links(origin)
        try:
            before=origin.stat();digest=hashlib.sha256()
            if not origin.is_file():raise ValueError('来源不是普通文件')
            with origin.open('rb') as src,target.open('xb') as dst:
                for block in iter(lambda:src.read(1024**2),b''):dst.write(block);digest.update(block)
                dst.flush();os.fsync(dst.fileno())
            after=origin.stat()
            if (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns):raise ValueError('来源在冻结时变化，请保存后重试')
            if frozen is not None and digest.hexdigest()!=frozen[name]['sha256']:raise ValueError('原任务资料快照已变化，不能按原资料恢复')
            records[name]=dict(path=name,origin=str(origin),bytes=after.st_size,sha256=digest.hexdigest(),mode='retry_snapshot' if frozen else 'config')
        except (OSError,ValueError) as exc:raise ValueError('无法冻结复核资料 '+name+'：'+str(exc)+'；请打开“案例库与工程背景”修复来源后重试。') from exc
    manifest=dict(version=1,status='FROZEN',documents=records)
    _atomic(folder/'review-materials.json',(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
    return manifest


def stage_for_task(profile,folder,mode,cfg,*,retry=False):
    review=cfg.get('review',{})
    if mode in {'review','review-failed'} or (mode=='scan' and (review.get('enabled',False) or review.get('prepare_packets',False))):
        return stage(profile,folder,retry=retry)
    return dict(status='NOT_REQUIRED')
