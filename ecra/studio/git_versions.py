"""Read-only, bounded browser pages of real local Git revisions."""
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import os

from ..git_diff import git
from ..workspace import no_links


def _records(stream, separator):
    buffer = b''
    while chunk := stream.read(65536):
        parts = (buffer + chunk).split(separator)
        yield from parts[:-1]
        buffer = parts[-1]
        if len(buffer) > 4*1024**2:
            raise ValueError('Git 单条记录过大，未显示不完整版本列表')
    if buffer:
        yield buffer


def inspect_versions(project_root, work, *, base_ref='', current_ref='HEAD', include_uncommitted=False, search='', offset=0, limit=50,build_mode=''):
    if build_mode not in {'','database','cmake'}:raise ValueError('构建方式必须为编译数据库或CMake')
    if type(include_uncommitted) is not bool:raise ValueError('纳入未提交输入必须是布尔值')
    if include_uncommitted and current_ref!='HEAD':raise ValueError('纳入未提交输入仅适用于当前 ref 为 HEAD；其他分支请使用固定提交比较')
    if not isinstance(project_root, str) or not Path(project_root).is_absolute():
        raise ValueError('固件目录必须是绝对路径')
    root = Path(project_root).resolve()
    if not root.is_dir():
        raise ValueError('固件目录不存在')
    if (type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100
            or not isinstance(search, str) or len(search) > 200 or '\0' in search):
        raise ValueError('版本筛选或分页参数无效')
    if not any((p/'.git').exists() for p in (root, *root.parents)):
        return dict(available=False, items=[], total=0, message='此目录不是 Git 工程，可继续全量扫描。')
    repository = git(root, 'rev-parse', '--show-toplevel').decode('utf-8', 'strict').strip()
    work = no_links(work)
    repo = Path(repository).resolve()
    if work == repo or work.is_relative_to(repo) or repo.is_relative_to(work):
        raise ValueError('版本查询数据目录与固件 Git 重叠；请先选择独立数据根')
    work.mkdir(parents=True, exist_ok=True)
    def text(*args, codes=(0,)):
        return git(root, *args, _returncodes=codes).decode('utf-8', 'strict').strip()
    def resolve(value):
        if not isinstance(value, str) or len(value) > 4096 or '\0' in value:
            raise ValueError('Git 引用格式无效')
        if not value:
            return None
        if value != value.strip() or value.startswith('-'):
            raise ValueError('Git 引用不能含首尾空白或以减号开头')
        result = text('rev-parse', '--verify', '--quiet', '--end-of-options', value+'^{commit}', codes=(0, 1))
        if not result:
            raise ValueError('Git 引用不能解析为提交：'+value+'；请检查本地分支、标签或完整 SHA，不自动联网获取。')
        return result
    items = []; total = 0
    with tempfile.TemporaryFile(dir=work) as output:
        git(root, 'for-each-ref', '--format=%(refname)%00%(objectname)%00%(objecttype)%00%(symref)',
            'refs/heads', 'refs/remotes', 'refs/tags', _stdout=output)
        if output.tell() > 64*1024**2:
            raise ValueError('本地版本列表超过64MiB读取预算；请先缩小工程引用范围，未显示截断列表')
        output.seek(0)
        for raw in _records(output, b'\n'):
            fields = raw.rstrip(b'\r').decode('utf-8', 'strict').split('\0')
            if len(fields) != 4:
                raise ValueError('Git 版本记录损坏，未显示不完整列表')
            ref, oid, kind, alias = fields
            if search.casefold() not in ref.casefold():
                continue
            if offset <= total < offset + limit:
                items.append(dict(ref=ref, object_id=oid, object_type=kind, symbolic_target=alias))
            total += 1
    dirty = dict(staged=0, unstaged=0, untracked=0, conflicted=0)
    with tempfile.TemporaryFile(dir=work) as output:
        git(root, '-c', 'core.fsmonitor=false', 'status', '--porcelain=v2', '--untracked-files=all', '-z', _stdout=output)
        if output.tell() > 64*1024**2:
            raise ValueError('工作区状态超过64MiB读取预算，不能确认未提交覆盖；原数据保留')
        output.seek(0); records = iter(_records(output, b'\0'))
        for record in records:
            if record.startswith((b'1 ', b'2 ')):
                xy = record.split(b' ', 2)[1]
                dirty['staged'] += xy[0:1] != b'.'
                dirty['unstaged'] += xy[1:2] != b'.'
                if record.startswith(b'2 '):
                    next(records)  # The rename's original name is a raw second record.
            elif record.startswith(b'? '):
                dirty['untracked'] += 1
            elif record.startswith(b'u '):
                dirty['conflicted'] += 1
            else:
                raise ValueError('无法完整解释 Git 工作区状态，未确认覆盖')
    return dict(available=True, repository=repository, head=resolve('HEAD'),
        branch=text('symbolic-ref', '-q', '--short', 'HEAD', codes=(0, 1)) or None,
        base_ref=base_ref, current_ref=current_ref, base_sha=resolve(base_ref), current_sha=resolve(current_ref),
        items=items, total=total, offset=offset, limit=limit, search=search,
        next_offset=offset+limit if offset+limit < total else None,
        dirty=dirty, include_uncommitted=include_uncommitted,build_mode=build_mode,
        formal_scan_allowed=not include_uncommitted or build_mode=='database' or (build_mode=='cmake' and os.name=='nt'),
        blocking_reason=('当前构建方式的未提交扫描被阻断：需要显式编译数据库，或Windows/Ninja外置CMake；请检查实际构建配置。'
            if include_uncommitted and build_mode!='database' and not (build_mode=='cmake' and os.name=='nt') else None),
        sampled_at=datetime.now(timezone.utc).isoformat(),
        notice=('已选择当前工作区实际字节，包括已暂存、未暂存、重命名、删除和参与输入的未跟踪文件；不是只扫描暂存区。显式数据库或Windows/Ninja外置CMake启动时仍须通过实际配置、生成输入与SDK固定检查。' if include_uncommitted else '固定提交比较不包含这些未提交修改。')+'这里只是当前预览，启动扫描时会重新固定输入。')
