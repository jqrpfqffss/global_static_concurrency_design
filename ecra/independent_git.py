"""Owned Git management data for fixed revisions; never register in firmware."""
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from .common import replace_file
from .workspace import canonical, no_links


HOOK_POLICY = 'owned-empty-directory-and-checkout-events-v1'


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


def _layout_error(source, stage, reasons):
    from .scan_diagnostics import ACTIVE
    active = ACTIVE.get()
    log = f'；诊断日志 {active.folder/"exception.log"}' if active else ''
    return ValueError(f'{stage} {source}：' + '；'.join(reasons) + log)


def _progress(message):
    from .scan_diagnostics import ACTIVE
    active = ACTIVE.get()
    if active:
        active.progress(message)


def _empty_hooks(path):
    path = no_links(path)
    if not path.is_dir() or any(path.iterdir()):
        raise _layout_error(path, '复验私有 Hook 策略', ['工具的空 Hook 目录已改变'])
    return path


def _check_hooks(root, expected):
    expected = _empty_hooks(expected)
    actual = _text(root, 'rev-parse', '--path-format=absolute', '--git-path', 'hooks')
    if no_links(actual) != expected:
        raise _layout_error(root, '复验私有 Hook 策略', [f'core.hooksPath 应指向 {expected}'])


def _verify_objects(repository):
    _progress(f'校验私有 Git 对象完整性 {repository}')
    try:
        _git(repository, 'fsck', '--full', '--no-dangling')
    except ValueError as exc:
        raise _layout_error(repository, '校验私有 Git 对象', [str(exc)]) from exc


def _checkout_git(root, hooks, *args):
    # A conditional global include can first match inside the destination.
    # Protect the events fired by clone/ref updates/checkout before that
    # destination exists to inspect, including Git's configuration-based hooks.
    return _git(root, '-c', 'core.hooksPath='+str(_empty_hooks(hooks)), '-c', 'core.fsmonitor=false',
                '-c', 'hook.reference-transaction.enabled=false', '-c', 'hook.post-index-change.enabled=false',
                '-c', 'hook.post-checkout.enabled=false', *args)


def _unsupported_dependency(root, key):
    if key.startswith('hook.') and key.endswith('.event'):
        return '配置式 Hook 事件不受空 Hook 目录控制'
    if key == 'core.fsmonitor':
        try:
            _text(root, 'config', '--type=bool', '--get', key)
        except ValueError:
            return '外部文件监视器命令不受空 Hook 目录控制'
    if key.startswith('remote.'):
        if key.endswith('.partialclonefilter'):
            return '部分克隆过滤器需要独立的对象物化证明'
        if key.endswith('.promisor'):
            try:
                values = _text(root, 'config', '--type=bool', '--get-all', key).splitlines()
            except ValueError:
                return '外部对象库配置不是有效布尔值'
            if 'true' in values:
                return '远端承诺的对象尚未物化'
    return None


def _capture(source, *, stage='兼容快照', isolated=False):
    common = (source / _text(source, 'rev-parse', '--git-common-dir')).resolve()
    admin = Path(_text(source, 'rev-parse', '--absolute-git-dir')).resolve()
    config = no_links(common/'config').read_bytes()
    # Relative include paths, per-worktree overrides, grafts, alternates and
    # shallow history need their own equivalence proof. Do not flatten them.
    keys = _git(source, 'config', '--local', '--no-includes', '-z', '--name-only', '--list').split(b'\0')
    blocked = []
    per_tree = admin/'config.worktree'
    worktree_config = False
    for raw in keys:
        key = raw.decode('utf-8')
        reason = _unsupported_dependency(source, key)
        if reason:
            blocked.append(f'{common/"config"} {key}：{reason}')
        elif key.startswith(('include.', 'includeif.')):
            # A hasconfig condition can contain an authenticated remote URL.
            name = 'includeIf.<条件>.path' if key.startswith('includeif.') else key
            blocked.append(f'{common/"config"} {name} 的配置上下文尚不能重定位')
        elif isolated and key == 'extensions.worktreeconfig':
            try:
                worktree_config = _text(source, 'config', '--local', '--type=bool', '--get', key) == 'true'
            except ValueError:
                blocked.append(f'{common/"config"} {key} 不是有效布尔值')
            if worktree_config:
                blocked.append(f'{common/"config"} {key}=true，启用的逐工作树配置尚不能重定位')
        elif key.startswith('extensions.') or key == 'core.worktree':
            blocked.append(f'{common/"config"} {key} 的管理布局尚不能重定位')
        elif not isolated and key == 'core.hookspath':
            blocked.append(f'{common/"config"} {key} 缺少私有钩子策略')
    if not isolated:
        directory = no_links(common/'hooks')
        if directory.is_dir():
            blocked.extend(f'未隔离的钩子目录文件 {p}' for p in directory.iterdir()
                           if p.is_file() and not p.name.endswith('.sample'))
    if (not isolated or worktree_config) and per_tree.exists():
        blocked.append(f'{per_tree}：工作树配置未固定')
    for path, reason in ((common/'shallow', '浅历史未补全'), (common/'info/grafts', '历史改写未固定'),
                         (common/'objects/info/alternates', '外部对象库未物化')):
        if path.exists():
            blocked.append(f'{path}：{reason}')
    # Git fsck permits missing objects referenced by a promisor pack.
    blocked.extend(f'{path}：部分克隆对象包未物化' for path in (common/'objects/pack').glob('*.promisor'))
    if blocked:
        raise _layout_error(source, stage, blocked)
    result = dict(config=config, head=no_links(admin/'HEAD').read_bytes(),
                  refs=_git(source, 'for-each-ref', '--format=%(refname) %(objectname) %(symref)'))
    if isolated and per_tree.exists():
        result['inactive_worktree_config'] = no_links(per_tree).read_bytes()
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


def _environment():
    overrides = ('GIT_DIR', 'GIT_COMMON_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE',
                 'GIT_OBJECT_DIRECTORY', 'GIT_ALTERNATE_OBJECT_DIRECTORIES',
                 'GIT_CONFIG', 'GIT_CONFIG_COUNT', 'GIT_CONFIG_PARAMETERS', 'GIT_NAMESPACE')
    active = [name for name in (*overrides, 'GIT_SHALLOW_FILE', 'GIT_GRAFT_FILE') if name in os.environ]
    if active:
        raise ValueError('Git 环境覆盖影响独立目录身份：' + ', '.join(active))


def _hashes(values):
    return {key: _hash(value) if value is not None else None for key, value in values.items()}


def _frozen_home(workspace, ident):
    # Git must open a worktree's admin path before it can read core.longpaths.
    # Avoid repeating long tree names in the shared repository's parent path.
    if not isinstance(ident, str) or not re.fullmatch('[0-9a-f]{64}', ident):
        raise ValueError('固定 Git 输入摘要无效')
    return no_links(Path(workspace.project_workspace)/'git-fixed'/ident[:20])


def _source_hooks(source):
    common = (source/_text(source, 'rev-parse', '--git-common-dir')).resolve()
    active = Path(_text(source, 'rev-parse', '--path-format=absolute', '--git-path', 'hooks'))
    directories = {}
    for directory in (common/'hooks', active):
        directories[str(directory)] = (sorted(p.name for p in directory.iterdir()
                                              if not p.name.endswith('.sample'))
                                       if directory.is_dir() else [])
    from .git_diff import git
    raw = git(source, 'config', '-z', '--show-origin', '--show-scope', '--get-regexp',
              r'^(core\.hookspath|init\.templatedir)$', _returncodes=(0, 1))
    fields = raw.split(b'\0')
    if fields.pop() or len(fields) % 3:
        raise _layout_error(source, '采集原仓库', ['无法解析 Hook 或模板配置来源'])
    declarations = []
    for index in range(0, len(fields), 3):
        scope, origin, entry = fields[index:index+3]
        key, _, value = entry.partition(b'\n')
        declarations.append(dict(scope=scope.decode(), origin=origin.decode(), key=key.decode(), value_sha256=_hash(value)))
    return dict(active=str(active), directories=directories, declarations=declarations,
                admin=_text(source, 'rev-parse', '--absolute-git-dir'), common=str(common),
                template_env=os.environ.get('GIT_TEMPLATE_DIR'))


def _build_config(root):
    # Git preserves subsection case, order, duplicates and embedded newlines.
    fields = _git(root, 'config', '--local', '--no-includes', '--null', '--list').split(b'\0')
    management = {b'core.bare', b'core.longpaths', b'core.hookspath'}
    return [row for row in fields if row.partition(b'\n')[0] not in management]


def _external_config(source, *, isolated=False):
    """External Git configuration is a checked tool input, like an SDK.

    Repository-local config/refs are copied. Global/system includes remain
    external and must have the same effective meaning in both private trees.
    Never execute global hooks or allow a global worktree override at checkout.
    """
    fields = _git(source, 'config', '--show-origin', '--show-scope', '--null', '--list').split(b'\0')
    if fields[-1] or (len(fields)-1) % 3:
        raise ValueError('无法完整记录 Git 外部构建配置')
    files, records, blocked = {}, [], []
    for index in range(0, len(fields)-1, 3):
        scope, origin, value = fields[index:index+3]
        if scope not in (b'system', b'global'):
            continue
        key = value.split(b'\n', 1)[0]
        reason = _unsupported_dependency(source, key.decode('utf-8'))
        if not reason and (key == b'core.worktree' or key.startswith(b'extensions.')
                           or (key == b'core.hookspath' and not isolated)):
            reason = '尚不能重定位'
        if reason:
            blocked.append(f'{scope.decode()} {origin.decode()} {key.decode()}：{reason}')
        if not origin.startswith(b'file:'):
            raise ValueError('Git 外部构建配置来源不可校验')
        path = (Path(source)/origin[5:].decode('utf-8')).resolve()
        if str(path) not in files:
            files[str(path)] = _hash(path.read_bytes())
        records.append(_hash(b'\0'.join((scope, origin, value))))
    if blocked:
        raise _layout_error(source, '核对外部 Git 配置', blocked)
    return dict(files=files, records=records)


def check_external(source, frozen):
    isolated = frozen['version'] == 3
    if isolated:
        _check_hooks(source, Path(frozen['repository']).parents[1]/'empty-hooks')
    if _external_config(source, isolated=isolated) != frozen['external_config']:
        raise _layout_error(source, '复验快照', ['Git 外部构建配置已变化，或条件配置在隔离工作树中含义不同'])


def check_frozen(frozen, workspace, *, verify_objects=True):
    """Check the owned copy, never re-resolve a name in the original repo."""
    _environment()
    home = _frozen_home(workspace, frozen['id'])
    repository = no_links(home/'r.git')
    version = frozen.get('version')
    if version not in (2, 3):
        raise _layout_error(repository, '复验快照', ['不支持的固定 Git 证明版本'])
    if version == 3:
        from .common import digest
        expected = digest(dict(version=3, policy=HOOK_POLICY, source=canonical(workspace.repository_root),
                               inputs=frozen['source_state'], hooks=frozen['source_hooks'], external=frozen['external_config']))
        if expected != frozen['id'] or frozen.get('hook_policy') != HOOK_POLICY:
            raise _layout_error(repository, '复验快照', ['固定输入摘要或 Hook 策略不一致，请重新扫描'])
    identity = dict(version=version, project_id=workspace.project_id, source=canonical(workspace.repository_root),
                    id=frozen['id'], repository=str(repository))
    if (any(frozen.get(key) != value for key, value in identity.items())
            or no_links(home/'state.json.pending').exists()
            or json.loads(no_links(home/'state.json').read_text('utf-8')) != dict(frozen, status='READY')):
        raise ValueError('固定 Git 输入身份已改变或建立未完成；保留现场，请重新扫描')
    if _hashes(_capture(repository, stage='复验私有镜像', isolated=version == 3)) != frozen['private']:
        raise _layout_error(repository, '复验私有镜像', ['固定 Git 引用或配置已改变/损坏'])
    check_external(repository, frozen)
    if version == 3 and verify_objects:
        _verify_objects(repository)
    return repository


def freeze(source, workspace):
    """Capture one self-contained Git view shared by both comparison sides.

    The content-addressed view is never fetched/refreshed. Later scans with
    changed refs/config use a new view; existing scans keep their old tags,
    symbolic refs, attributes and object store. No writes reach source Git.
    """
    from .common import digest
    _environment()
    source = Path(source).resolve()
    work = no_links(workspace.project_workspace)
    if (canonical(source) != canonical(workspace.repository_root)
            or source.is_relative_to(work) or work.is_relative_to(source)):
        raise ValueError('固定 Git 来源与独立数据边界不一致')
    before = _capture(source, stage='采集原仓库', isolated=True)
    source_state = _hashes(before)
    observation = _source_hooks(source)
    external = _external_config(source, isolated=True)
    ident = digest(dict(version=3, policy=HOOK_POLICY, source=canonical(source),
                        inputs=source_state, hooks=observation, external=external))
    home = _frozen_home(workspace, ident)
    repository, marker = no_links(home/'r.git'), no_links(home/'state.json')
    if home.exists():
        if not marker.is_file():
            raise ValueError('固定 Git 创建中断或未知目录；保留现场，请选择新的独立数据根')
        saved = json.loads(marker.read_text('utf-8'))
        if saved.get('status') != 'READY' or saved.get('source_state') != source_state:
            raise ValueError('固定 Git 创建未完成或身份损坏；保留现场，请选择新的独立数据根')
        frozen = {key: value for key, value in saved.items() if key != 'status'}
        if frozen.get('id') != ident or frozen.get('version') != 3 or frozen.get('source_hooks') != observation:
            raise _layout_error(home, '复用快照', ['快照身份不一致'])
        _progress(f'复用固定 Git 镜像并校验对象 {repository}')
        check_frozen(frozen, workspace)
        if (_capture(source, stage='复用时复核原仓库', isolated=True) != before
                or _external_config(source, isolated=True) != external or _source_hooks(source) != observation):
            raise _layout_error(source, '复用快照', ['固定期间引用或配置改变，请重新扫描'])
        return frozen
    home.parent.mkdir(parents=True, exist_ok=True)
    hooks = no_links(home.parent/'empty-hooks')
    hooks.mkdir(exist_ok=True)
    _empty_hooks(hooks)
    # Publish the complete directory in one rename. A stopped clone is kept as
    # evidence but cannot occupy the reusable address or the next attempt.
    staging = Path(tempfile.mkdtemp(prefix=ident[:12]+'-', dir=home.parent))
    identity = dict(version=3, hook_policy=HOOK_POLICY, project_id=workspace.project_id, source=canonical(source),
                    id=ident, repository=str(repository))
    marker, repository = staging/'state.json', staging/'r.git'
    _state(marker, dict(identity, status='CREATING'))
    _progress(f'克隆固定 Git 镜像 {source} → {repository}；隔离模板和 Hook，私有 Hook 目录 {hooks}')
    _checkout_git(source, hooks, 'clone', '--mirror', '--no-hardlinks',
                  '--template='+str(hooks), '--', str(source), str(repository))
    _write(repository/'config', before['config'], replace=True)
    _git(repository, 'config', '--local', '--replace-all', 'core.hooksPath', hooks.as_posix())
    _git(repository, 'config', '--local', '--replace-all', 'core.bare', 'true')
    # Builds may call Git themselves, without the engine's -c longpaths flag.
    _git(repository, 'config', '--local', '--replace-all', 'core.longpaths', 'true')
    _check_hooks(repository, hooks)
    _write(repository/'HEAD', before['head'], replace=True)
    (repository/'info').mkdir(exist_ok=True)
    for name in ('attributes', 'exclude'):
        path = no_links(repository/'info'/name)
        if before[name] is not None:
            _write(path, before[name], replace=path.exists())
        elif path.exists():
            path.unlink()
    for line in before['refs'].decode('utf-8', 'strict').splitlines():
        fields = line.split()
        if len(fields) == 3:
            _checkout_git(repository, hooks, 'symbolic-ref', fields[0], fields[2])
    _progress(f'校验私有 Git 对象、引用和构建配置 {repository}')
    _verify_objects(repository)
    private = _capture(repository, stage='检查新建私有镜像', isolated=True)
    if (any(private[k] != before[k] for k in ('head', 'refs', 'attributes', 'exclude'))
            or _build_config(repository) != _build_config(source)
            or _capture(source, stage='复制后复核原仓库', isolated=True) != before
            or _source_hooks(source) != observation or _external_config(source, isolated=True) != external):
        raise _layout_error(source, '复制后复核', [f'引用或配置改变，或副本有效配置不一致 {repository}；请重试'])
    frozen = dict(identity, source_state=source_state, source_hooks=observation, private=_hashes(private),
                  external_config=external)
    staging.rename(home)
    # Conditional global includes can match the final directory differently.
    # Check them there before publishing the READY proof. A rejected copy is
    # retained under its staging name, leaving the address free for a retry.
    try:
        check_external(home/'r.git', frozen)
        if _hashes(_capture(home/'r.git', stage='发布固定镜像', isolated=True)) != frozen['private']:
            raise _layout_error(home, '发布固定镜像', ['私有引用或配置在发布前发生变化'])
        _state(home/'state.json', dict(frozen, status='READY'), replace=True)
    except BaseException:
        home.rename(staging)
        raise
    return frozen


def prepare_frozen(tree, sha, workspace, frozen):
    """Attach a version tree to a fixed repository without refreshing refs."""
    # The pin checks the complete object store before use and publication.
    # Here checkout consumes those objects; recheck ownership and metadata on
    # both sides of that operation without repeating a full fsck twice.
    repository = check_frozen(frozen, workspace, verify_objects=False)
    if frozen['version'] != 3:
        raise _layout_error(repository, '准备工作树', ['旧快照仅供按原证明读取，请重新扫描以建立私有 Hook 策略'])
    tree = no_links(tree)
    if tree.parent != no_links(workspace.worktree_root) or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', sha):
        raise ValueError('固定 Git 工作树目标身份不一致')
    home = workspace.git_admin_home(tree)
    marker = no_links(home/'state.json')
    identity = dict(version=2, project_id=workspace.project_id, tree=canonical(tree), sha=sha,
                    repository=canonical(repository), frozen_id=frozen['id'])
    creating = not home.exists()
    if not creating:
        if (not marker.is_file() or marker.with_name('state.json.pending').exists()
                or json.loads(marker.read_text('utf-8')) != dict(identity, status='READY')):
            raise _layout_error(tree, '准备固定工作树', [f'建立未完成或所有权改变，保留登记 {marker}；可选择新的工具数据根重试'])
    else:
        if tree.exists():
            raise ValueError('固定工作树目标包含未知数据；保留现场，禁止接管')
        home.mkdir(parents=True)
        _state(marker, dict(identity, status='CREATING'))
        tree.parent.mkdir(parents=True, exist_ok=True)
        hooks = _empty_hooks(repository.parents[1]/'empty-hooks')
        _progress(f'建立独立工作树 {tree}，固定提交 {sha}')
        _checkout_git(repository, hooks, 'worktree', 'add', '--detach', str(tree), sha)
    _owned(repository, tree, sha)
    from .git_diff import _relative_worktree_gitdir
    _relative_worktree_gitdir(repository, tree, sha)
    check_frozen(frozen, workspace, verify_objects=False)
    check_external(tree, frozen)
    if creating:
        _state(marker, dict(identity, status='READY'), replace=True)
    return dict(repository=str(repository), sha=sha)


def prepare(source, tree, sha, workspace, *, allow_legacy_project=False):
    """Return a verified private common-dir; retain interrupted/legacy data."""
    # Git environment overrides could redirect reads/writes to the firmware.
    _environment()
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
    home = workspace.git_admin_home(tree)
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
