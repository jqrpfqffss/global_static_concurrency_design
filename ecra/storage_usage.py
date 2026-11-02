"""Complete metadata walk with disk-backed hard-link accounting, no contents."""
from contextlib import closing
from datetime import datetime,timezone
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile

from .workspace import no_links,studio_data_root
from .storage_activity import DataActivity


GROUPS=('scans','projects','cache','work','exports','settings')


def category(path):
    if path.parts[0]=='projects' and 'cache' in path.parts:return 'cache'
    return path.parts[0]


def measure(data):
    root=studio_data_root(data);totals={name:0 for name in GROUPS};allocated={name:0 for name in GROUPS}
    counts={name:0 for name in GROUPS};missing={name:0 for name in GROUPS};errors=[];partial=False
    allocation=None
    if os.name=='nt':
        from .windows_storage import WindowsFiles
        allocation=WindowsFiles()
    with DataActivity(root):
        scratch=no_links(root/'work/storage-sampling');scratch.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='owned-',dir=scratch) as folder:
            own=Path(folder)
            with closing(sqlite3.connect(own/'identities.db')) as conn:
                conn.execute('PRAGMA cache_size=-1024');conn.execute('PRAGMA temp_store=FILE')
                conn.execute('CREATE TABLE files(volume TEXT,id TEXT,PRIMARY KEY(volume,id)) WITHOUT ROWID')
                for group in GROUPS:
                    start=no_links(root/group)
                    if not start.exists():continue
                    pending=[start]
                    while pending:
                        current=pending.pop()
                        try:
                            with os.scandir(current) as entries:
                                for entry in entries:
                                    path=Path(entry.path)
                                    if path==own:continue  # this request's temporary observer, not retained user data
                                    name=category(path.relative_to(root))
                                    try:
                                        stat=entry.stat(follow_symlinks=False)
                                        if entry.is_symlink() or getattr(stat,'st_file_attributes',0)&0x400:raise ValueError('链接/重解析路径未计入')
                                        if entry.is_dir(follow_symlinks=False):pending.append(path);continue
                                        if not entry.is_file(follow_symlinks=False):raise ValueError('非普通文件未计入')
                                        totals[name]+=stat.st_size;counts[name]+=1
                                        if allocation is not None:
                                            info=allocation.allocation(path)
                                            volume,ident=info['identity']
                                            cursor=conn.execute('INSERT OR IGNORE INTO files VALUES (?,?)',(str(volume),ident))
                                            if cursor.rowcount:allocated[name]+=info['allocated_bytes']
                                    except (OSError,ValueError) as exc:
                                        partial=True;missing[name]+=1
                                        # Bounded display diagnostics; all missing counts remain exact.
                                        if len(errors)<20:errors.append(dict(file=str(path.relative_to(root)),error=str(exc)))
                        except (OSError,ValueError) as exc:
                            partial=True;missing[group]+=1
                            if len(errors)<20:errors.append(dict(file=str(current.relative_to(root)),error=str(exc)))
    usage=shutil.disk_usage(root)
    return dict(bytes=totals,allocated_bytes={name:allocated[name] if allocation is not None and not missing[name] else None for name in GROUPS},
                allocated_observed_bytes=allocated if allocation is not None else None,files=counts,unmeasured_files=missing,
                sampled_at=datetime.now(timezone.utc).isoformat(),sampling_partial=partial,cleanup_available=True,
                physical_disk_free_bytes=usage.free,physical_disk_total_bytes=usage.total,errors=errors,
                allocation_status='PARTIAL' if partial else 'MEASURED' if allocation is not None else 'UNSUPPORTED_PLATFORM',
                reason='逻辑量按全部路径计数；实际文件分配量按文件身份去重，不含目录/MFT/ADS及本次临时采样账本。采样期间变化或不可读取标为不完整，未知分配量不当作0。整理仍先验证引用、预览并明确确认。')
