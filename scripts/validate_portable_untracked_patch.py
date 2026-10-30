"""仅验收指定 Portable 的 Git 新增文件补丁；不提取 AST、不运行模型。"""
from pathlib import Path
import json, os, shutil, sys, tempfile

if not __debug__:
    raise RuntimeError('验收脚本需要启用断言，禁止使用 Python -O')
if len(sys.argv) != 3:
    raise SystemExit('用法：包内 python.exe -B scripts/validate_portable_untracked_patch.py <Portable目录> <新的收据路径>')
bundle, receipt = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
if Path(sys.executable).resolve() != (bundle/'runtime/python.exe').resolve():
    raise RuntimeError('本项必须使用指定 Portable 的 runtime/python.exe 执行')
assert not receipt.exists()
sys.path.insert(0, str(bundle))
from ecra.git_diff import git, pin, settings, write_comparison_patch
from ecra.portable import bundle_root
from ecra.workflow import file_digest
assert bundle_root() == bundle
record = dict(complete=False, bundle=str(bundle), review_executed=False,
              native_scan=False, safety_report_valid=False,
              git_executable=str(bundle/'tools/git/cmd/git.exe'),
              implementation_sha256=file_digest(bundle/'ecra/git_diff.py'),
              runtime_executable=sys.executable, runtime_version=sys.version)
receipt.parent.mkdir(parents=True, exist_ok=True)
receipt.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
with tempfile.TemporaryDirectory(prefix='Portable 新增补丁 中文 空格-', dir=receipt.parent) as name:
    root = Path(name)
    git(root, 'init')
    git(root, 'config', 'user.email', 'ecra@example.invalid')
    git(root, 'config', 'user.name', 'ECRA Portable validation')
    git(root, 'config', 'core.autocrlf', 'false')
    (root/'.gitignore').write_bytes(b'.ecra/\n')
    (root/'a.c').write_bytes(b'int global_value;\n')
    git(root, 'add', '.')
    git(root, 'commit', '-m', 'base')
    additions = {'新 文件.h': b'#define PORTABLE_ADDED 271828\n', 'empty.h': b'',
                 'data.bin': b'\x00\xffPORTABLE\x00', '-[special].h': b'#define SPECIAL 3\n'}
    for path, value in additions.items():
        (root/path).write_bytes(value)
    os.symlink('新 文件.h', root/'link.h')
    cfg = {'analysis': {'git_diff': settings(dict(base_ref='HEAD', include_uncommitted=True))}}
    pinned = pin(root, cfg)
    index = (root/'.git/index').read_bytes()
    destination = root/'.ecra/untracked.patch'
    write_comparison_patch(pinned, destination)
    assert b'271828' in destination.read_bytes()
    assert b'GIT binary patch' in destination.read_bytes()
    assert index == (root/'.git/index').read_bytes()
    assert pinned == pin(root, cfg)
    clone = root/'.ecra/clone'
    git(root, 'clone', '--no-hardlinks', str(root), str(clone))
    git(clone, 'config', 'core.symlinks', 'true')
    git(clone, '-c', 'core.autocrlf=false', 'apply', '--binary', str(destination))
    for path, value in additions.items():
        assert (clone/path).read_bytes() == value
    assert (clone/'link.h').is_symlink() and os.readlink(clone/'link.h') == '新 文件.h'
    preserved = receipt.with_suffix('.patch')
    shutil.copyfile(destination, preserved)
    record.update(complete=True, git_version=git(root, '--version').decode('utf-8').strip(),
                  untracked_files=len(additions)+1, unicode_space_path=True, leading_dash_path=True,
                  empty_file=True, binary_payload=True, symlink=True, index_unchanged=True,
                  independent_apply_equal=True, patch=str(preserved), patch_sha256=file_digest(preserved))
receipt.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(record, ensure_ascii=False))
