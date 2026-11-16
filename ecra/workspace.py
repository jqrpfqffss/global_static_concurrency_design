"""Project-owned runtime paths. Firmware, analysis trees and data are distinct.

No resolver operation removes firmware or historical data. Identity is verified
before adopting a directory; links in writable data paths are rejected.
"""
from dataclasses import dataclass, asdict, replace
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import os
import re
import shutil
import tempfile
import time

from .common import digest, read_json, write_json
from .config import TOOL_ROOT
from .path_io import is_link, lstat_if_present, resolved_path


def canonical(path):
    value = Path(path).resolve().as_posix()
    return value.casefold() if os.name == 'nt' else value


def no_links(path):
    path = Path(path).absolute()
    for item in reversed((path, *path.parents)):
        info = lstat_if_present(item)
        if info is not None and is_link(info):
            raise ValueError(f'ECRA 数据路径包含符号链接/Junction，拒绝写入: {item}')
    return resolved_path(path)


_MOVE_TOOL = '当前工具位于 C 盘。请将整个 ECRA 工具目录移动到 D/E 等非 C 盘的可写目录后重新运行。'


def _local_path(value, label):
    path = Path(value)
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError(f'{label} 必须使用明确的绝对路径: {value}')
    if os.name == 'nt' and (
            not re.fullmatch(r'[a-zA-Z]:', path.drive)
            or any(':' in part or part.endswith(('.', ' ')) or Path(part).is_reserved() for part in path.parts[1:])):
        raise ValueError(f'{label} 必须位于本机盘符，且不能使用设备名、数据流或异常路径: {value}')
    return path


def managed_root():
    tool = resolved_path(TOOL_ROOT)
    if os.name == 'nt' and tool.drive.casefold() == 'c:':
        raise ValueError(f'{_MOVE_TOOL} 实际工具目录: {tool}')
    _local_path(tool, 'ECRA 工具目录')
    if not tool.is_dir():
        raise ValueError(f'ECRA 工具目录不存在或不可访问: {tool}')
    return no_links(tool/'workspace')


def managed_path(value, *, label='ECRA 写入路径'):
    """Admit only absolute writes in the workspace of this code installation."""
    root = managed_root()
    raw = _local_path(value, label)
    path = no_links(raw)
    if not path.is_relative_to(root) or (os.name == 'nt' and path.drive.casefold() == 'c:'):
        raise ValueError(f'{label} 位于当前工具的数据区域之外: {path}；请使用 {root} 内的路径，'
                         '旧数据可从 Studio「数据与共享」只读迁移。')
    return path


def control_path(*parts):
    return managed_path(managed_root().joinpath('.ecra', *parts))


def read_owner(marker):
    try:
        return read_json(no_links(marker))
    except (OSError, ValueError) as exc:
        raise ValueError(f'项目归属元数据无法读取: {marker}；请保留并备份该工程工作区，'
                         '检查 project.json/初始化 pending；不要手工替换身份摘要。' + str(exc)) from exc


@contextmanager
def _owner_publication():
    """Defer cooperative SIGINT only until this small ownership claim is durable.

    Hard exits and I/O errors still leave the existing explicit-recovery claim.
    API worker threads do not install process-wide signal handlers.
    """
    import signal
    import threading
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    previous=signal.getsignal(signal.SIGINT);pending=[];failed=False
    def defer(signum,frame):pending[:]=[(signum,frame)]
    signal.signal(signal.SIGINT,defer)
    try:
        yield
    except BaseException:
        failed=True
        raise
    finally:
        signal.signal(signal.SIGINT,previous)
        if pending and not failed:
            if callable(previous):previous(*pending[-1])
            elif previous==signal.SIG_DFL:signal.raise_signal(signal.SIGINT)


def user_data_root():
    """The historical user mode uses the same portable workspace as Studio."""
    explicit = _active_data.get()
    if explicit is not None:
        return studio_data_root(explicit)
    value = os.environ.get('ECRA_DATA_ROOT')
    if value:
        return studio_data_root(value, label='ECRA_DATA_ROOT')
    from .studio_preferences import preferred_data_root
    return studio_data_root(preferred_data_root(default_user_data_root()))


def default_user_data_root():
    return managed_root()


def studio_data_root(value=None, *, label='ECRA 数据根'):
    root = managed_root()
    path = managed_path(value if value is not None else user_data_root(), label=label)
    slots = root/'data-roots'
    if path != root and (path == slots or not path.is_relative_to(slots) or
                         any(part.startswith('.') for part in path.relative_to(slots).parts)):
        raise ValueError(f'{label} 只能使用 {root} 或 {root / "data-roots" / "<名称>"}: {path}')
    for ancestor in (path, *[p for p in path.parents if p.is_relative_to(slots)]):
        if ((ancestor/'.git').exists() or (ancestor/'CMakeLists.txt').is_file()
                or (ancestor/'compile_commands.json').is_file()):
            raise ValueError(f'{label} 与源码/Git/构建工程重叠: {ancestor}')
        if ancestor.exists() and not ancestor.is_dir():
            raise ValueError(f'{label} 的路径被文件占用: {ancestor}')
        if ancestor != path and any((ancestor/name).exists() for name in (
                'scans', 'projects', 'work', 'settings/device.json', 'settings/storage-location.json')):
            raise ValueError(f'{label} 不能嵌套在另一数据根中: {ancestor} / {path}')
    return path


_active_data = ContextVar('ecra_active_data_root', default=None)


@contextmanager
def using_data_root(value):
    token = _active_data.set(studio_data_root(value))
    try:
        yield
    finally:
        _active_data.reset(token)


def formal_workspace(root, analysis):
    """Validate scan boundaries without initializing or writing firmware."""
    if analysis.get('cmake', {}).get('location') == 'project':
        raise ValueError('正式扫描禁止在固件中构建；请使用 analysis.cmake.location: workspace')
    if analysis.get('git_diff', {}).get('include_uncommitted'):
        from .dirty_inputs import supported
        supported(analysis)
    return WorkspaceResolver.resolve(root, analysis)


def output_settings(analysis):
    value = analysis.get('output')
    legacy = analysis.get('output_dir', '.ecra')
    if not isinstance(legacy, str) or not legacy.strip():
        raise ValueError('analysis.output_dir 必须是非空路径字符串')
    if value is None:
        value = {}
    if not isinstance(value, dict) or set(value) - {'location', 'custom_dir'}:
        raise ValueError('analysis.output 只支持 location/custom_dir')
    mode = value.get('location', 'user')
    if mode not in {'user', 'tool', 'project', 'custom'}:
        raise ValueError('analysis.output.location 必须是 tool 或 custom；旧 user 沿用工具数据根')
    if mode == 'project' or legacy != '.ecra':
        raise ValueError(f'禁止在固件工程中生成数据（analysis.output.location / output_dir: {legacy}）；'
                         '请移除旧 output_dir，设置 output.location: tool，并从 Studio 迁移旧结果。')
    if mode == 'custom':
        if not isinstance(value.get('custom_dir'), str) or not value['custom_dir'].strip():
            raise ValueError('analysis.output.custom_dir 必须是非空绝对路径')
        if not Path(value['custom_dir']).is_absolute():
            raise ValueError('analysis.output.custom_dir 必须是绝对路径')
    elif 'custom_dir' in value:
        raise ValueError('custom_dir 仅可用于 location: custom')
    return dict(value, location=mode)


@dataclass(frozen=True)
class WorkspaceResolver:
    tool_root: str
    project_root: str
    repository_root: str
    project_id: str
    project_name: str
    workspace_root: str
    project_workspace: str
    results_root: str
    cache_root: str
    snapshots_root: str
    build_root: str
    git_diff_root: str
    worktree_root: str

    @classmethod
    def resolve(cls, root, analysis):
        root = Path(root).resolve()
        # Normal repositories, submodules and worktrees have a .git marker.
        # Full scans also work in Portable distributions without Git. Diff
        # pinning independently verifies this boundary using real Git.
        repo = next((p for p in (root, *root.parents) if (p/'.git').exists()), root)
        identity = dict(repository_root=canonical(repo), project_subdir=root.relative_to(repo).as_posix())
        if os.name == 'nt':
            identity['project_subdir'] = identity['project_subdir'].casefold()
        project_id = digest(identity)
        name = re.sub(r'[^\w.-]+', '_', repo.name + ('_' + root.name if root != repo else ''))[:64]
        if os.name == 'nt':
            name = name.casefold()
        settings = output_settings(analysis)
        workspace = (studio_data_root(settings['custom_dir'], label='analysis.output.custom_dir')
                     if settings['location'] == 'custom' else user_data_root())
        active = _active_data.get()
        if active is not None and workspace != active:
            raise ValueError(f'配置的数据根 {workspace} 与本次启动数据根 {active} 不同；'
                             '请修改 analysis.output 或从所选目录启动。')
        tool = resolved_path(TOOL_ROOT)
        if (workspace.is_relative_to(root) or root.is_relative_to(workspace)
                or (repo != tool and (workspace.is_relative_to(repo) or repo.is_relative_to(workspace)))):
            raise ValueError(f'ECRA 数据根与固件源码或 Git 仓库重叠: {workspace} / {root}')
        label = re.sub(r'[^A-Za-z0-9_.-]', '_', name).strip('._-')[:24] or 'project'
        work = workspace/'projects'/(label + '_' + project_id[:20])
        result = work/'results'
        no_links(work)
        location = digest(canonical(workspace))[:12]
        return cls(*map(str, (tool, root, repo, project_id, name, workspace, work, result,
            result/'cache', result/'snapshots', work/'builds', result/'git_diff'/location, work/'trees'/location)))

    def git_admin_home(self, tree):
        return no_links(Path(self.project_workspace)/'git-snapshots'/Path(self.worktree_root).name/Path(tree).name)

    def initialize(self):
        self.verify_paths()
        from .data_transfer import register_location
        register_location(self.workspace_root)
        work = no_links(self.project_workspace)
        marker = no_links(work/'project.json')
        claim = no_links(work/'project.json.pending')
        if claim.exists() and not marker.exists():
            raise ValueError(f'项目工作区初始化锁存在: {claim}；等待当前进程完成；若进程已退出，'
                             '先备份目录，再按迁移说明恢复完整 pending 或选择新的 custom_dir。')
        expected = dict(schema_version=1, project_id=self.project_id, project_name=self.project_name,
                        repository_root=canonical(self.repository_root), project_root=canonical(self.project_root))
        expected['project_subdir'] = Path(self.project_root).relative_to(Path(self.repository_root)).as_posix()
        if os.name == 'nt':
            expected['project_subdir'] = expected['project_subdir'].casefold()
        if marker.exists():
            saved = read_owner(marker)
            if not isinstance(saved, dict) or any(saved.get(k) != v for k, v in expected.items()):
                raise ValueError(f'ECRA 项目身份冲突，拒绝复用: {marker}')
        elif work.exists() and any(work.iterdir()):
            raise ValueError(f'ECRA 工作区已有未知数据，拒绝接管: {work}')
        try:
            work.mkdir(parents=True, exist_ok=True)
            # O_EXCL prevents two first runs from racing the ownership claim.
            if not marker.exists():
                claimed = published = False
                with _owner_publication():
                    try:
                        with claim.open('x', encoding='utf-8') as stream:
                            claimed = True
                            import json
                            json.dump(dict(expected, output_root=self.results_root,
                                created_at=datetime.now(timezone.utc).isoformat()), stream, ensure_ascii=False, indent=2)
                            stream.flush()
                            os.fsync(stream.fileno())
                        if marker.exists():
                            raise FileExistsError(str(marker))
                        claim.rename(marker)
                        published = True
                    except FileExistsError:
                        if not marker.exists():
                            raise ValueError(f'已有项目初始化锁: {claim}；等待初始化完成后重试')
                        saved = read_owner(marker)
                        if not isinstance(saved, dict) or any(saved.get(k) != v for k, v in expected.items()):
                            raise ValueError(f'ECRA 项目身份冲突: {marker}')
                        published = True
                    except KeyboardInterrupt:
                        if claimed and not published and not marker.exists():claim.unlink(missing_ok=True)
                        raise
                    finally:
                        if claimed and published:
                            claim.unlink(missing_ok=True)
            no_links(self.results_root).mkdir(parents=True, exist_ok=True)
            for base, dirs, files in os.walk(self.results_root):
                # Git manages the source trees; only data paths are writable
                # storage. Firmware symlinks there are handled as source inputs.
                dirs[:] = [d for d in dirs if Path(base)/d != Path(self.worktree_root)]
                for name in dirs + files:
                    no_links(Path(base)/name)
            with tempfile.TemporaryFile(dir=work):
                pass
        except OSError as exc:
            raise ValueError(f'ECRA workspace 无法写入: {work}；请检查工具目录权限和磁盘空间。{exc}') from exc
        return self

    def verify_paths(self):
        data = studio_data_root(self.workspace_root)
        work = managed_path(self.project_workspace)
        if work.parent != data/'projects' or not work.name.endswith('_'+self.project_id[:20]):
            raise ValueError(f'项目工作区越出所属数据根: {work}')
        for value in (self.results_root, self.cache_root, self.snapshots_root,
                      self.build_root, self.git_diff_root, self.worktree_root):
            path = managed_path(value)
            if path != data and path.is_relative_to(data):
                continue
            raise ValueError(f'运行目录越出所属数据根: {path}')

    def verify_identity(self):
        self.verify_paths()
        marker = no_links(Path(self.project_workspace)/'project.json')
        if marker.exists():
            saved = read_owner(marker)
            if (not isinstance(saved, dict) or saved.get('schema_version') != 1 or saved.get('project_id') != self.project_id or
                    saved.get('project_root') != canonical(self.project_root) or
                    saved.get('repository_root') != canonical(self.repository_root)):
                raise ValueError(f'ECRA 项目身份冲突: {marker}')
        return self

    def for_results(self, result):
        result = no_links(result)
        if not result.is_relative_to(Path(self.project_workspace)):
            raise ValueError('内部结果目录越出项目工作区')
        return replace(self, results_root=str(result), cache_root=str(result/'cache'), snapshots_root=str(result/'snapshots'))

    def bind(self, analysis):
        analysis['_workspace'] = asdict(self)


def context(root, analysis):
    value = analysis.get('_workspace')
    result = WorkspaceResolver(**value) if value else WorkspaceResolver.resolve(root, analysis)
    return result.verify_identity()


def results_path(root, analysis):
    return Path(context(root, analysis).results_root)


def lock_path(root, analysis):
    ws = context(root, analysis)
    out = Path(ws.results_root)
    return (out if out.is_relative_to(Path(ws.git_diff_root)/'artifacts') else Path(ws.project_workspace))/'scan.lock'


def build_path(root, analysis):
    ws = context(root, analysis)
    settings = analysis['cmake']
    if settings.get('location', 'workspace') == 'project':
        raise ValueError('禁止在固件中构建；请使用 analysis.cmake.location: workspace')
    label = Path(settings.get('build_dir', 'build/ecra'))
    if label.anchor or '..' in label.parts:
        raise ValueError(f'analysis.cmake.build_dir 只能使用工程内的相对标签；实际构建边界为 {ws.build_root}: {label}')
    # Actual source tree + settings bind separate commits and workspace builds.
    key = digest(dict(source=canonical(root), cmake=settings, workspace=canonical(ws.workspace_root)))[:24]
    return no_links(Path(ws.build_root)/key)


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def validate_analysis_inputs(root, analysis, paths, *, config_file, compilation):
    """Fail closed if an isolated version consumes the original Git workspace.

    Explicit tool/configuration inputs and owned build products have separate
    identities. Other inputs inside the original repository must come from the
    selected worktree, including headers reached through links/absolute flags.
    """
    ws = context(root, analysis)
    root = Path(root).resolve()
    from .data_transfer import reject_retired_inputs
    reject_retired_inputs(ws.workspace_root,list(paths))
    if root == Path(ws.project_root):
        return
    if not root.is_relative_to(Path(ws.worktree_root)):
        raise ValueError(f'analysis_root 不属于当前工程的隔离工作树: {root}')
    actual_repo = next((p for p in (root, *root.parents) if (p/'.git').exists()), root)
    from .git_diff import text
    gitdir = Path(text(actual_repo, 'rev-parse', '--absolute-git-dir')).resolve()
    allowed_dirs = [actual_repo, gitdir]
    if compilation.get('cmake_steps'):
        allowed_dirs.append(Path(compilation['compile_database']).resolve().parent)
    allowed_files = {Path(config_file).resolve(), Path(compilation['compile_database']).resolve()}
    original = Path(ws.repository_root)
    leaked = []
    for value in paths:
        path = (root/value).resolve()
        if (path.is_relative_to(original) and path not in allowed_files
                and not any(path.is_relative_to(folder) for folder in allowed_dirs)):
            leaked.append(str(path))
    if leaked:
        raise ValueError('固定提交扫描检测到原固件工作区输入，禁止混用版本: ' + '; '.join(sorted(leaked)[:8]) +
            '；请检查 analysis.extra_args/include_dirs、版本内 compile_commands.json 和 CMake 输入，'
            '将仓库内源码/头文件引用改为相对路径，或使用所选版本的隔离 CMake 数据库。'
            '工具链应放在固件仓库外；不能通过忽略这些输入绕过检查。')


def legacy_files(root, legacy):
    """Require an identity-bound checkpoint and safe tree, never just a name.

    Unknown files are copied as history but cannot be excluded from Git inputs.
    In particular source/build files remain real inputs even inside .ecra.
    """
    legacy = no_links(legacy)
    state = read_json(legacy/'scan_state.json')
    run = read_json(legacy/'run.json')
    if (canonical(state['project_root']) != canonical(root) or canonical(run['project_root']) != canonical(root)
            or state.get('schema') != 1 or not isinstance(state.get('fingerprint'), str)):
        raise ValueError('旧 ECRA 数据项目身份不匹配')
    if not (legacy/'facts.db').is_file() or not (legacy/'reports/global_static_concurrency.json').is_file():
        raise ValueError('旧 ECRA 数据缺少事实/报告')
    files = []
    for base, dirs, names in os.walk(legacy):
        for name in dirs + names:
            no_links(Path(base)/name)
        files.extend(Path(base)/name for name in names)
    return files


def migrate_legacy(ws, progress=print):
    legacy = Path(ws.project_root)/'.ecra'
    out = Path(ws.results_root)
    source_kind = 'FIRMWARE_LEGACY'
    source_lock = legacy/'scan.lock'
    if not legacy.is_dir():
        # Adopt only this resolver's exact previous tool identity, never a
        # directory guessed from a project display name. Raw bytes are copied
        # for revalidation; this does not bless old engine/input proofs.
        with using_data_root(managed_root()):
            previous = WorkspaceResolver.resolve(ws.project_root, {})
        old_work = Path(previous.project_workspace)
        legacy = Path(previous.results_root)
        if legacy == out or not (old_work/'project.json').is_file():
            return
        previous.verify_identity()
        source_kind = 'TOOL_WORKSPACE'
        source_lock = old_work/'scan.lock'
    if not legacy.is_dir() or legacy == out or (out/'migration.json').exists():
        return
    # An existing new scan is never overwritten by old results.
    if (out/'run.json').exists():
        return
    try:
        def source_files():
            if source_kind == 'FIRMWARE_LEGACY':
                return legacy_files(ws.project_root, legacy)
            previous.verify_identity()
            run = read_json(legacy/'run.json')
            if canonical(run.get('project_root', '')) != canonical(ws.project_root):
                raise ValueError('旧工具 workspace 的扫描工程身份不匹配')
            if not (legacy/'facts.db').is_file() or not (legacy/'reports/global_static_concurrency.json').is_file():
                raise ValueError('旧工具 workspace 缺少完整事实/报告；保留原数据，不能冒充有效历史')
            files = []
            for base, dirs, names in os.walk(no_links(legacy)):
                for name in dirs + names:
                    no_links(Path(base)/name)
                files.extend(Path(base)/name for name in names)
            return files
        files = source_files()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        progress(f'旧目录未自动接管: {legacy}；{exc}。保留原目录；核对身份后可手动归档到 snapshots。')
        return
    if source_lock.exists():
        raise ValueError(f'旧数据存在扫描锁: {source_lock}；确认旧进程退出并处理锁后重试')
    if any(out.iterdir()):
        raise ValueError(f'迁移目标已有数据，拒绝覆盖: {out}；请将旧目录手动归档至 snapshots 后重新扫描')
    pending = Path(ws.project_workspace)/'.migration-pending'
    no_links(pending)
    pending.mkdir(exist_ok=True)
    records = {}
    started = time.monotonic()
    try:
        needed = sum(p.stat().st_size for p in files if not (pending/p.relative_to(legacy)).exists())
        if shutil.disk_usage(pending).free < needed:
            raise OSError(f'迁移剩余空间不足，需要至少 {needed} 字节')
        for source in files:
            rel = source.relative_to(legacy)
            target = no_links(pending/rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            before = (source.stat().st_size, file_hash(source))
            if not target.is_file() or (target.stat().st_size, file_hash(target)) != before:
                shutil.copyfile(source, target)
            if (target.stat().st_size, file_hash(target)) != before or file_hash(source) != before[1]:
                raise ValueError(f'迁移校验失败/旧数据正在变化: {source}')
            records[rel.as_posix()] = dict(size=before[0], sha256=before[1])
        if set(files) != set(source_files()) or source_lock.exists():
            raise ValueError('迁移期间旧数据目录发生变化')
        for source in files:
            record = records[source.relative_to(legacy).as_posix()]
            if source.stat().st_size != record['size'] or file_hash(source) != record['sha256']:
                raise ValueError(f'迁移期间旧数据发生变化: {source}')
        write_json(pending/'migration.json', dict(schema=1, source=str(legacy), source_kind=source_kind, project_id=ws.project_id,
            files=records, complete=True, copied_bytes=sum(r['size'] for r in records.values()),
            seconds=time.monotonic()-started, review_state='PRESERVED_REVALIDATION_REQUIRED'))
        # Publish one whole directory; interrupted copies never masquerade as a
        # complete migration. rmdir removes only the previously empty directory.
        out.rmdir()
        pending.replace(out)
        progress(f'旧 ECRA 数据已复制并逐文件校验，原数据保留: {legacy} -> {out}；旧结论需通过输入/引擎校验后使用。')
    except (OSError, ValueError) as exc:
        raise ValueError(f'历史迁移未完成，原数据未删除: {legacy}；释放空间/解决冲突后重试；待恢复目录 {pending}。{exc}') from exc


def generated_untracked(root, cfg):
    """Only manifest-verified migrated bytes may be excluded; never tracked files."""
    ws = context(root, cfg['analysis'])
    manifest = Path(ws.results_root)/'migration.json'
    if not manifest.is_file():
        return set()
    saved = read_json(manifest)
    if saved.get('project_id') != ws.project_id or not saved.get('complete'):
        return set()
    legacy = Path(saved['source'])
    if legacy != Path(ws.project_root)/'.ecra':
        return set()
    repo = Path(ws.repository_root)
    safe = set()
    consumed = set()
    for manifest_file in (legacy/'input_manifest.json', Path(ws.results_root)/'input_manifest.json'):
        if manifest_file.is_file():
            manifest_inputs = read_json(manifest_file)
            if isinstance(manifest_inputs, dict):
                consumed.update(canonical(Path(ws.project_root)/p) for p in manifest_inputs)
    # Source, headers, CMake, toolchains, response files and unknown inputs are
    # deliberately absent. Actual compiler dependencies are always snapshotted.
    allowed_roots = {'reports', 'review', 'diagnostics', 'inventory', 'html_details', 'cache', 'snapshots'}
    allowed_files = {'facts.json', 'facts.db', 'index.html', 'opencode_review.html', 'run.json', 'run.log',
        'scan_state.json', 'input_manifest.json', 'input_closure.json', 'result_validity.json', 'doctor.json'}
    for rel, record in saved.get('files', {}).items():
        p = Path(rel)
        if p.is_absolute() or '..' in p.parts or (p.parts[0] not in allowed_roots and rel not in allowed_files):
            continue
        if p.suffix.lower() not in {'.json', '.db', '.html', '.log', '.js', '.txt', '.md', '.facts'}:
            continue
        source = no_links(legacy/p)
        if canonical(source) in consumed:
            continue
        if source.is_file() and source.stat().st_size == record['size'] and file_hash(source) == record['sha256']:
            safe.add(source.relative_to(repo).as_posix())
    return safe
