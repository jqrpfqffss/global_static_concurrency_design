"""Read-only, bounded directory pages for the local engineering wizard.

No source content is opened. A page is an observation, never an input snapshot.
Only a user-requested level is enumerated; reparse entries are never followed.
"""
import heapq
import os
from pathlib import Path
import stat

from ..workspace import no_links


def _directory(value):
    if not isinstance(value,str) or not value or '\0' in value or len(value)>32767:
        raise ValueError('请选择有效的绝对目录路径')
    path=Path(value)
    if not path.is_absolute():raise ValueError('目录路径必须是绝对路径')
    try:path=no_links(path)
    except ValueError as exc:raise ValueError('目录选择不跟随符号链接或Junction，请选择真实目录：'+value) from exc
    if not path.is_dir():raise ValueError('目录不存在或不是文件夹：'+str(path))
    return path


def _roots():
    if os.name=='nt':
        import ctypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.GetLogicalDrives.argtypes=[];kernel.GetLogicalDrives.restype=ctypes.c_ulong
        mask=kernel.GetLogicalDrives()
        if not mask:raise ctypes.WinError(ctypes.get_last_error())
        return [dict(name=chr(65+i)+':',path=chr(65+i)+':\\',selectable=False,reason='进入后选择实际工程目录') for i in range(26) if mask&(1<<i)]
    return [dict(name='/',path='/',selectable=False,reason='进入后选择实际工程目录')]


def browse(path=None,*,root=None,after=None,search='',limit=50):
    if type(limit) is not int or not 1<=limit<=100:raise ValueError('目录分页大小必须为1至100')
    if not isinstance(search,str) or len(search)>256 or '\0' in search:raise ValueError('当前层目录筛选文本无效')
    if after is not None and (not isinstance(after,str) or not after or len(after)>32767 or '\0' in after):raise ValueError('目录分页游标无效')
    bound=_directory(root) if root is not None else None
    if path is None or path=='':
        if bound:path=str(bound)
        else:return dict(mode='roots',path=None,root=None,parent=None,items=_roots(),total=None,next_after=None,changed=False,notice='本机驱动器；仅进入用户选择的目录，不读取源码内容。')
    folder=_directory(path)
    if bound and not folder.is_relative_to(bound):raise ValueError('范围目录不能超出当前固件工程根目录')
    before=folder.stat();counts=dict(total=0,files=0,links=0,vanished=0);needle=search.casefold()
    cursor=(after.casefold(),after) if after is not None else None
    def entries():
        with os.scandir(folder) as scan:
            for entry in scan:
                try:info=entry.stat(follow_symlinks=False)
                except FileNotFoundError:counts['vanished']+=1;continue
                linked=stat.S_ISLNK(info.st_mode) or bool(getattr(info,'st_file_attributes',0)&stat.FILE_ATTRIBUTE_REPARSE_POINT)
                if linked:counts['links']+=1
                elif not stat.S_ISDIR(info.st_mode):counts['files']+=1;continue
                if needle not in entry.name.casefold():continue
                counts['total']+=1;key=(entry.name.casefold(),entry.name)
                if cursor is not None and key<=cursor:continue
                target=folder/entry.name
                yield key,dict(name=entry.name,path=str(target),relative=str(target.relative_to(bound)) if bound else None,
                               selectable=not linked,reason='链接/重解析项不跟随；请选择真实目录' if linked else '')
    # nsmallest consumes the whole level for a truthful total using O(limit)
    # retained entries, even when a directory contains millions of siblings.
    found=heapq.nsmallest(limit+1,entries(),key=lambda row:row[0]);items=[row[1] for row in found[:limit]]
    checked=_directory(str(folder));end=checked.stat()
    changed=(before.st_dev,before.st_ino,before.st_mtime_ns)!=(end.st_dev,end.st_ino,end.st_mtime_ns) or bool(counts['vanished'])
    parent=None if folder.parent==folder or folder==bound else str(folder.parent)
    return dict(mode='directory',path=str(folder),root=str(bound) if bound else None,parent=parent,
                relative=str(folder.relative_to(bound)) if bound else None,items=items,total=counts['total'],
                next_after=items[-1]['name'] if len(found)>limit else None,changed=changed,
                directory_mtime_ns=end.st_mtime_ns,counts=counts,
                notice='目录在读取期间发生变化，请刷新后选择。' if changed else '仅列当前层目录；名称筛选不递归。目录观察不代替扫描输入校验。')
