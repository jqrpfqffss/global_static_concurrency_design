"""Owned Git management data for fixed revisions; never register in firmware."""
import hashlib
import json
import os
from pathlib import Path
import re

from .common import replace_file
from .workspace import canonical, no_links


def _git(root, *args):
    from .git_diff import git
    return git(root, *args)


def _text(root, *args):
    return _git(root, *args).decode('utf-8', 'strict').strip()


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _write(path, data, *, replace=False):
    path = no_links(path)
    if not replace:
        with path.open('xb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        return
    pending = no_links(path.with_name(path.name + '.pending'))
    _write(pending, data)
    replace_file(pending, path)


def _state(path, value, *, replace=False):
    _write(path, json.dumps(value, ensure_ascii=True, indent=2).encode('ascii'), replace=replace)


def _capture(source):
    common = (source / _text(source, 'rev-parse', '--git-common-dir')).resolve()
    admin = Path(_text(source, 'rev-parse', '--absolute-git-dir')).resolve()
    config = no_links(common/'config').read_bytes()
    # Relative include paths, per-worktree overrides, grafts, alternates and
    # shallow history need their own equivalence proof. Do not flatten them.
    keys = _git(source, 'config', '--local', '--no-includes', '--name-only', '--list').lower().splitlines()
    hooks = no_links(common/'hooks')
    custom_hooks = hooks.is_dir() and any(p.is_file() and not p.name.endswith('.sample') for p in hooks.iterdir())
    if (any(key.startswith((b'include.', b'includeif.', b'extensions.')) or key in {b'core.worktree', b'core.hookspath'}
            for key in keys)
            or custom_hooks
            or any((root/name).exists() for root, name in
                   ((admin, 'config.worktree'), (common, 'shallow'), (common, 'info/grafts'),
                    (common, 'objects/info/alternates')))):
        raise ValueError('此 Git 管理布局尚未证明可独立复制（include/扩展/钩子/浅历史/外部对象）；请使用独立完整副本')
    result = dict(config=config, head=no_links(admin/'HEAD').read_bytes(),
                  refs=_git(source, 'for-each-ref', '--format=%(refname) %(objectname) %(symref)'))
    for name in ('attributes', 'exclude'):
        path = no_links(common/'info'/name)
        result[name] = path.read_bytes() if path.is_file() else None
    return result


def _owned(repository, tree, sha):
    if (repository/'objects/info/alternates').exists():
        raise ValueError('独立 Git 对象变成外部引用，禁止复用')
    common = (tree/_text(tree, 'rev-parse', '--git-common-dir')).resolve()
    if (common != repository or _text(tree, 'rev-parse', 'HEAD') != sha
            or Path(_text(tree, 'rev-parse', '--show-toplevel')).resolve() != tree):
        raise ValueError('独立 Git 工作树身份已改变或损坏，禁止复用')
    admin = Path(_text(tree, 'rev-parse', '--absolute-git-dir')).resolve()
    if not admin.is_relative_to(repository/'worktrees'):
        raise ValueError('独立 Git 登记已改变，禁止复用')
    return admin


def prepare(source, tree, sha, workspace, *, allow_legacy_project=False):
    """Return a verified private common-dir; retain interrupted/legacy data."""
    # Git environment overrides could redirect reads/writes to the firmware.
    overrides = ('GIT_DIR', 'GIT_COMMON_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE',
                 'GIT_OBJECT_DIRECTORY', 'GIT_ALTERNATE_OBJECT_DIRECTORIES',
                 'GIT_CONFIG', 'GIT_CONFIG_COUNT', 'GIT_CONFIG_PARAMETERS', 'GIT_NAMESPACE')
    if any(name in os.environ for name in overrides):
        raise ValueError('Git 环境覆盖影响独立目录身份；请先移除 GIT_DIR/INDEX/OBJECT/CONFIG 等覆盖')
    source, tree = Path(source).resolve(), no_links(tree)
    work = no_links(workspace.project_workspace)
    trees = no_links(workspace.worktree_root)
    # Only the explicit legacy/development renderer supports its old in-project
    # result directory. Formal canonical scans reject it before this function.
    legacy = (allow_legacy_project and work != source and work.is_relative_to(source)
              and work == Path(workspace.results_root).resolve())
    if (canonical(source) != canonical(workspace.repository_root)
            or tree.parent != trees or not trees.is_relative_to(work)
            or (work.is_relative_to(source) and not legacy) or source.is_relative_to(work)
            or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', sha)):
        raise ValueError('独立 Git 来源、工作区或目标路径身份不一致')
    _git(source, 'cat-file', '-e', sha + '^{commit}')
    before = _capture(source)
    home = no_links(work/'git-snapshots'/tree.name)
    repository = no_links(home/'repository.git')
    marker = no_links(home/'state.json')
    identity = dict(version=1, project_id=workspace.project_id, source=canonical(source),
                    tree=canonical(tree), sha=sha, repository=canonical(repository))
    saved = None
    if home.exists():
        if not marker.is_file() or marker.with_name('state.json.pending').exists():
            raise ValueError('独立 Git 创建中断或未知目录；保留现场，请选择新的独立数据根')
        saved = json.loads(marker.read_text(encoding='utf-8'))
        if any(saved.get(key) != value for key, value in identity.items()):
            raise ValueError('独立 Git 所有权已改变，禁止接管')
        if saved.get('status') != 'READY':
            raise ValueError('独立 Git 上次操作未完成；保留现场，请选择新的独立数据根')
        _owned(repository, tree, sha)
        actual = dict(config=no_links(repository/'config').read_bytes(),
                      head=no_links(repository/'HEAD').read_bytes(),
                      refs=_git(repository, 'for-each-ref', '--format=%(refname) %(objectname) %(symref)'))
        for name in ('attributes', 'exclude'):
            p = no_links(repository/'info'/name)
            actual[name] = p.read_bytes() if p.is_file() else None
        if {key: _hash(value) if value is not None else None for key, value in actual.items()} != saved['private']:
            raise ValueError('独立 Git 引用或配置已改变/损坏，禁止复用')
        if saved['source_state'] == {key: _hash(value) if value is not None else None for key, value in before.items()}:
            if _capture(source) != before:
                raise ValueError('原 Git 输入在核对时改变，请重新扫描')
            return dict(repository=str(repository), sha=sha)
    elif tree.exists():
        raise ValueError('目标含历史或未知工作树；原数据完整保留，请选择新的独立数据根重扫')
    else:
        home.mkdir(parents=True)
    _state(marker, dict(identity, status='REFRESHING' if saved else 'CREATING'), replace=bool(saved))
    if saved:
        # Explicit local path: never contact any configured remote. Ref deletes
        # are mirrored too; previous refs/config remain in immutable states.
        _git(repository, '-c', 'gc.auto=0', 'fetch', '--no-auto-maintenance',
             '--no-write-fetch-head', '--force', '--prune', str(source), '+refs/*:refs/*')
    else:
        _git(source, 'clone', '--mirror', '--no-hardlinks', '--', str(source), str(repository))
    if (repository/'objects/info/alternates').exists():
        raise ValueError('独立 Git 仍依赖外部对象；保留现场，禁止使用')
    # Preserve build-visible local configuration, origin URLs and attributes.
    # Only bare management mode differs; linked checkouts remain non-bare.
    _write(repository/'config', before['config'], replace=True)
    _git(repository, 'config', '--local', 'core.bare', 'true')
    _write(repository/'HEAD', before['head'], replace=True)
    (repository/'info').mkdir(exist_ok=True)
    for name in ('attributes', 'exclude'):
        path = no_links(repository/'info'/name)
        if before[name] is not None:
            _write(path, before[name], replace=path.exists())
        elif path.exists():
            # This is only a previously owned copy, never a source file.
            path.unlink()
    # A mirror clone/fetch can materialize a symbolic ref as a direct ref.
    # Preserve aliases such as refs/remotes/origin/HEAD explicitly.
    for line in before['refs'].decode('utf-8', 'strict').splitlines():
        fields = line.split()
        if len(fields) == 3:
            _git(repository, 'symbolic-ref', fields[0], fields[2])
    if _git(repository, 'for-each-ref', '--format=%(refname) %(objectname) %(symref)') != before['refs']:
        raise ValueError('独立 Git 引用未完整复制；保留现场，禁止使用')
    if _capture(source) != before:
        raise ValueError('复制期间原 Git 引用/配置改变；保留现场，请重新扫描')
    if not saved:
        tree.parent.mkdir(parents=True, exist_ok=True)
        _git(repository, 'worktree', 'add', '--detach', str(tree), sha)
    _owned(repository, tree, sha)
    from .git_diff import _relative_worktree_gitdir
    _relative_worktree_gitdir(repository, tree, sha)
    private = dict(config=(repository/'config').read_bytes(), head=(repository/'HEAD').read_bytes(), refs=before['refs'],
                   attributes=before['attributes'], exclude=before['exclude'])
    source_state = {key: _hash(value) if value is not None else None for key, value in before.items()}
    states = no_links(home/'states')
    states.mkdir(exist_ok=True)
    audit = states/(str(len(list(states.iterdir()))+1).zfill(8))
    audit.mkdir()
    for name, value in before.items():
        if value is not None:
            _write(audit/name, value)
    _state(audit/'identity.json', identity)
    if _capture(source) != before:
        raise ValueError('建立工作树期间原 Git 输入改变；保留现场，请重新扫描')
    _state(marker, dict(identity, status='READY', source_state=source_state,
           private={key: _hash(value) if value is not None else None for key, value in private.items()}), replace=True)
    return dict(repository=str(repository), sha=sha)
