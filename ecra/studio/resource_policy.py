"""Execution scheduling limits; never alter the scan's semantic configuration."""
import os


def policy(value=None):
    value=value or {}
    preset=value.get('preset','auto')
    if preset not in {'auto','low','high','manual'}:raise ValueError('资源预设必须是自动/低内存/高性能/手动')
    peak=value.get('peak_gib',16) if preset=='manual' else (8 if preset=='low' else 16)
    if type(peak) not in {int,float} or not 2<=peak<=64:raise ValueError('进程树峰值提交预算要求2–64 GiB')
    workers=value.get('workers',1 if preset=='low' else min(4,max(1,(os.cpu_count() or 2)//2)))
    if type(workers) is not int or not 1<=workers<=8:raise ValueError('最大TU并行数要求1–8')
    if preset=='low':workers=1
    return dict(preset=preset,peak_bytes=int(peak*1024**3),soft_bytes=int(peak*.75*1024**3),workers=workers)
