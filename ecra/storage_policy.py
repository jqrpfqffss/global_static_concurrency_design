"""Nonsemantic per-data-root policy; atomically saved and fixed per new scan."""
import hashlib
import json
import os
from pathlib import Path
import tempfile

from .workspace import no_links,studio_data_root


class PolicyConflict(ValueError):pass


def read(data):
    path=no_links(studio_data_root(data)/'settings/storage-policy.json')
    if not path.exists():return dict(mode='auto',revision='missing',valid=True,payload={},raw=None,error=None)
    if path.stat().st_size>1024**2:raise ValueError('空间设置超过1MiB，请保留原件并核对 '+str(path))
    raw=path.read_bytes();result=dict(mode=None,revision=hashlib.sha256(raw).hexdigest(),valid=False,payload=None,raw=raw,error=None)
    try:
        payload=json.loads(raw.decode('utf-8'))
        if (not isinstance(payload,dict) or payload.get('format')!='ECRA_STORAGE_POLICY' or type(payload.get('version')) is not int
                or payload['version']!=1 or not isinstance(payload.get('mode'),str) or payload['mode'] not in {'auto','off'}):raise ValueError('空间设置格式或策略不支持')
        result.update(mode=payload['mode'],valid=True,payload=payload)
    except (ValueError,UnicodeError,TypeError) as exc:result['error']=str(exc)+'；原文保留，明确备份修复后再扫描。'
    return result


def status(data):return {k:v for k,v in read(data).items() if k not in {'raw','payload'}}


def snapshot(data,value=None):
    root=studio_data_root(data)
    value=status(root) if value is None else value
    if (not isinstance(value,dict) or value.get('valid') is not True or not isinstance(value.get('mode'),str) or value['mode'] not in {'auto','off'}
            or not isinstance(value.get('revision'),str)):raise ValueError('空间策略无效，请到设置中备份并修复原设置')
    if value.get('data_root',str(root))!=str(root):raise ValueError('任务空间策略不属于当前独立数据根')
    return dict(mode=value['mode'],revision=value['revision'],valid=True,data_root=str(root))


def save(data,*,mode,revision,repair=False):
    if not isinstance(mode,str) or mode not in {'auto','off'}:raise ValueError('请选择自动节省空间或保持普通文件')
    root=studio_data_root(data);folder=no_links(root/'settings');folder.mkdir(parents=True,exist_ok=True)
    from .storage_activity import DataActivity
    try:lease=DataActivity(root,exclusive=True,purpose='storage-policy').__enter__()
    except ValueError as exc:raise PolicyConflict('其他窗口正在保存空间策略；请重新读取') from exc
    try:
        state=read(root)
        if revision!=state['revision']:raise PolicyConflict('空间策略已由其他窗口修改；请重新读取')
        if not state['valid'] and repair is not True:raise ValueError('请明确同意备份损坏空间设置后再保存')
        if state['raw'] is not None:
            backup=no_links(folder/'storage-policy-backups'/ (state['revision']+'.json'));backup.parent.mkdir(exist_ok=True)
            try:
                with backup.open('xb') as stream:stream.write(state['raw']);stream.flush();os.fsync(stream.fileno())
            except FileExistsError:
                if backup.read_bytes()!=state['raw']:raise ValueError('空间设置备份摘要冲突，原设置保留')
        payload=dict(state['payload'] or {});payload.update(format='ECRA_STORAGE_POLICY',version=1,mode=mode)
        raw=json.dumps(payload,ensure_ascii=True,indent=2).encode()+b'\n';pending=None
        from .common import replace_file
        try:
            with tempfile.NamedTemporaryFile(prefix='storage-policy-',suffix='.pending',dir=folder,delete=False) as stream:
                pending=no_links(stream.name);stream.write(raw);stream.flush();os.fsync(stream.fileno())
            replace_file(pending,no_links(folder/'storage-policy.json'))
        finally:
            if pending is not None:pending.unlink(missing_ok=True)
        return dict(saved=True,**status(root),activation='应用于下一次扫描；当前任务保留启动时的空间策略。')
    finally:lease.__exit__(None,None,None)
