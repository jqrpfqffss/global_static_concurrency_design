"""Profile-bound review documents; keep the engine's adjacent-file contract."""
import hashlib
from contextlib import closing
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile

from ..workspace import no_links

NAMES=('concurrency_cases.md','review_context.md')
MAX_EDIT=4*1024**2


def _binding(profile):return no_links(Path(profile).with_suffix('.review-materials.json'))


def bindings(profile):
    path=_binding(profile)
    if not path.exists():return {},'default'
    raw=path.read_bytes();value=json.loads(raw)
    if value.get('version')!=1 or not isinstance(value.get('documents'),dict):raise ValueError('复核资料配置损坏，请保留原文件并重新配置')
    return value['documents'],hashlib.sha256(raw).hexdigest()


def source(profile,name,spec):
    if name not in NAMES:raise ValueError('不支持的复核资料')
    if not isinstance(spec,dict):raise ValueError('复核资料来源格式无效')
    from ..config import CONFIG_HOME
    mode=spec.get('mode','automatic')
    if mode=='empty' and name=='review_context.md':return None
    if mode=='automatic':
        adjacent=no_links(Path(profile).parent/name)
        if adjacent.is_file():return adjacent
        default=no_links(Path(CONFIG_HOME)/name)
        if name=='review_context.md' and not default.is_file():return None
        return default
    if mode=='builtin':return no_links(Path(CONFIG_HOME)/name)
    if mode=='file':
        value=spec.get('path')
        if not isinstance(value,str) or not Path(value).is_absolute():raise ValueError('复核资料须填写本机绝对路径')
        return no_links(Path(value))
    if mode=='managed':
        digest=spec.get('sha256')
        if not isinstance(digest,str) or not re.fullmatch('[a-f0-9]{64}',digest):raise ValueError('工程资料副本身份无效')
        return no_links(Path(profile).parent/'review-materials'/(digest+'.md'))
    raise ValueError('复核资料来源选项无效')


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
        else:result['notice']='仅展示预览，原文件完整保留；超过4MiB或编码异常时请用本机文件方式维护'
        return result
    except (OSError,ValueError) as exc:return dict(available=False,path=str(path),error=str(exc),text='',editable=False)


def describe(profile):
    settings,revision=bindings(profile);documents={}
    for name in NAMES:
        spec=settings.get(name,{'mode':'automatic'})
        try:
            info=inspect_document(source(profile,name,spec),name)
            if name=='review_context.md' and spec.get('mode','automatic')=='automatic' and info.get('path') is None:
                info['notice']='未找到默认工程背景文件，当前无额外声明；可在这里编辑工程副本'
            if spec.get('mode')=='managed' and info.get('sha256')!=spec.get('sha256'):
                info.update(available=False,error='工程资料副本内容与保存哈希不符，请保留现场后重新导入')
        except ValueError as exc:info=dict(available=False,error=str(exc),text='',editable=False)
        documents[name]=dict(info,mode=spec.get('mode','automatic'),configured_path=spec.get('path',''))
    return dict(revision=revision,documents=documents)


def _atomic(path,raw):
    path=no_links(path);path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent,suffix='.pending',delete=False) as f:
        pending=Path(f.name);f.write(raw);f.flush();os.fsync(f.fileno())
    try:os.replace(pending,path)
    finally:pending.unlink(missing_ok=True)


def save(data,profile,payload):
    from ..storage_activity import DataActivity
    from ..human_reviews import ReviewConflict
    settings=no_links(Path(data)/'settings');settings.mkdir(parents=True,exist_ok=True)
    with DataActivity(data),closing(sqlite3.connect(no_links(settings/'profiles.db'),timeout=10)) as conn,conn:
        conn.execute('BEGIN IMMEDIATE')
        if 'profile_revision' in payload and hashlib.sha256(Path(profile).read_bytes()).hexdigest()!=payload['profile_revision']:
            raise ReviewConflict('工程配置已变化，请重新打开后再保存复核资料')
        _,revision=bindings(profile)
        if payload.get('revision')!=revision:raise ReviewConflict('复核资料已被其他窗口修改，请重新读取后再保存')
        documents=payload.get('documents')
        if not isinstance(documents,dict) or set(documents)!=set(NAMES):raise ValueError('请同时提交案例库和工程背景的来源设置')
        accepted={}
        for name,spec in documents.items():
            if not isinstance(spec,dict):raise ValueError('资料来源格式无效')
            mode=spec.get('mode');value={'mode':mode}
            if mode=='managed' and 'content' in spec:
                content=spec['content']
                if not isinstance(content,str) or len(content.encode('utf-8'))>MAX_EDIT:raise ValueError('在线编辑内容不能超过4MiB；大文件请选择本机文件')
                raw=content.encode('utf-8');digest=hashlib.sha256(raw).hexdigest()
                path=no_links(Path(profile).parent/'review-materials'/(digest+'.md'))
                if path.exists():
                    if path.read_bytes()!=raw:raise ValueError('工程资料副本哈希不一致，请保留现场')
                else:_atomic(path,raw)
                value['sha256']=digest
            elif mode=='managed':value['sha256']=spec.get('sha256')
            elif mode=='file':value['path']=spec.get('path')
            path=source(profile,name,value);info=inspect_document(path,name)
            if not info['available']:raise ValueError(name+'不可读取：'+info['error'])
            if mode=='managed' and info['sha256']!=value['sha256']:raise ValueError('工程资料副本内容与保存哈希不符')
            accepted[name]=value
        target=_binding(profile)
        if target.exists():
            raw=target.read_bytes();history=no_links(Path(profile).parent/'review-materials-history'/(hashlib.sha256(raw).hexdigest()+'.json'))
            if not history.exists():_atomic(history,raw)
        _atomic(target,(json.dumps(dict(version=1,documents=accepted),ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
    return dict(saved=True,**describe(profile))


def stage(profile,folder,*,retry=False):
    """Freeze exact bytes adjacent to task YAML, without changing review logic."""
    profile=Path(profile);folder=Path(folder);records={}
    previous=profile.parent/'review-materials.json'
    frozen=json.loads(previous.read_text('utf-8'))['documents'] if retry and previous.is_file() else None
    settings,_=bindings(profile) if frozen is None else ({},'')
    for name in NAMES:
        spec=settings.get(name,{'mode':'automatic'})
        origin=no_links(profile.parent/name) if frozen is not None else source(profile,name,spec)
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
            if spec.get('mode')=='managed' and digest.hexdigest()!=spec['sha256']:raise ValueError('工程资料副本内容与保存哈希不符')
            records[name]=dict(path=name,origin=str(origin),bytes=after.st_size,sha256=digest.hexdigest(),mode='retry_snapshot' if frozen else spec.get('mode','automatic'))
        except (OSError,ValueError) as exc:raise ValueError('无法冻结复核资料 '+name+'：'+str(exc)+'；请打开“案例库与工程背景”修复来源后重试。') from exc
    manifest=dict(version=1,status='FROZEN',documents=records)
    _atomic(folder/'review-materials.json',(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
    return manifest


def stage_for_task(profile,folder,mode,cfg,*,retry=False):
    review=cfg.get('review',{})
    if mode in {'review','review-failed'} or (mode=='scan' and (review.get('enabled',False) or review.get('prepare_packets',False))):
        return stage(profile,folder,retry=retry)
    return dict(status='NOT_REQUIRED')
