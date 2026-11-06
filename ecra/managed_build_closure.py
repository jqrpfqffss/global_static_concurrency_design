"""Bind an absent logical CMake build path to its actual owned build output."""
from pathlib import Path

from .input_snapshot import file_record
from .workspace import no_links


def resolve(root,analysis,build,steps,consumed):
    closure=dict(analysis.get('build_closure',{}));settings=analysis.get('cmake')
    if (not settings or settings.get('location','workspace')!='workspace'
            or not all(closure.get(k) for k in ('elf','map'))
            or not any(row.get('stage')=='build' and row.get('exit_code')==0 for row in steps)):
        return closure,None
    configured=Path(settings.get('build_dir','build/ecra'))
    if configured.is_absolute():return closure,None
    paths={key:Path(closure[key]) for key in ('elf','map')}
    if any(path.is_absolute() or not path.is_relative_to(configured) for path in paths.values()):
        return closure,None
    root=no_links(root);build=no_links(build)
    # Existing explicit inputs retain their old meaning. Never select between
    # a user's real file and a managed output merely by matching a filename.
    if any((root/path).exists() for path in paths.values()):return closure,None
    from .compilation import _owns_build_directory
    if not _owns_build_directory(build,root):raise ValueError('CMake闭包绑定缺少本轮构建归属，原输入保留')
    bound={key:no_links(build/path.relative_to(configured)) for key,path in paths.items()}
    if any(not path.is_relative_to(build) or not path.is_file() for path in bound.values()):
        raise ValueError('CMake声明的ELF/MAP未在本轮实际构建目录生成，禁止猜测或省略')
    proof={}
    for key,path in bound.items():
        row=file_record(path)
        if row.get('status')!='OK':raise ValueError('CMake实际ELF/MAP无法完整读取：'+str(path))
        consumed[str(path)]=row;closure[key]=str(path)
        proof[key]=dict(declared=str(paths[key]),actual=str(path),sha256=row['sha256'],size=row['size'])
    return closure,dict(format='ECRA_MANAGED_BUILD_CLOSURE_V1',build=str(build),owner=str(root),artifacts=proof)
