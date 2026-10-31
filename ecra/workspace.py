"""Project-owned runtime paths. Firmware, analysis trees and data are distinct.

No resolver operation removes firmware or historical data. Identity is verified
before adopting a directory; links in writable data paths are rejected.
"""
from dataclasses import dataclass, asdict, replace
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import os
import re
import shutil
import stat
import tempfile
import time

from .common import digest, read_json, write_json
from .config import TOOL_ROOT


def canonical(path):
    value = Path(path).resolve().as_posix()
    return value.casefold() if os.name == 'nt' else value


def no_links(path):
    path = Path(path).absolute()
    for item in (path, *path.parents):
        if item.is_symlink() or (item.exists() and
                getattr(item.lstat(), 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise ValueError(f'ECRA 数据路径包含符号链接/Junction，拒绝写入: {item}')
    return path.resolve()


def read_owner(marker):
    try:
        return read_json(no_links(marker))
    except (OSError, ValueError) as exc:
        raise ValueError(f'项目归属元数据无法读取: {marker}；请保留并备份该工程工作区，'
                         '检查 project.json/初始化 pending；不要手工替换身份摘要。' + str(exc)) from exc


def output_settings(analysis):
    value = analysis.get('output')
    legacy = analysis.get('output_dir', '.ecra')
    if not isinstance(legacy, str) or not legacy.strip():
        raise ValueError('analysis.output_dir 必须是非空路径字符串')
    if value is None:
        return dict(location='tool' if legacy == '.ecra' else 'project')
    if not isinstance(value, dict) or set(value) - {'location', 'custom_dir'}:
        raise ValueError('analysis.output 只支持 location/custom_dir')
    mode = value.get('location', 'tool')
    if mode not in {'tool', 'project', 'custom'}:
        raise ValueError('analysis.output.location 必须是 tool/project/custom')
    if mode == 'custom':
        if not isinstance(value.get('custom_dir'), str) or not value['custom_dir'].strip():
            raise ValueError('analysis.output.custom_dir 必须是非空绝对路径')
        if not Path(value['custom_dir']).is_absolute():
            raise ValueError('analysis.output.custom_dir 必须是绝对路径')
    elif 'custom_dir' in value:
        raise ValueError('custom_dir 仅可用于 location: custom')
    if mode != 'project' and legacy != '.ecra':
        raise ValueError('analysis.output 与旧 output_dir 冲突；删除旧字段或显式选择 location: project')
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
        if settings['location'] == 'project':
            requested = root/analysis.get('output_dir', '.ecra')
            result = no_links(requested)
            if result == root or not result.is_relative_to(root):
                raise ValueError('location: project 的 output_dir 必须是固件工程内独立子目录；外置路径请使用 custom')
            work = result
            workspace = result.parent
        else:
            workspace = no_links(TOOL_ROOT/'workspace' if settings['location'] == 'tool' else settings['custom_dir'])
            if workspace == repo or workspace.is_relative_to(repo):
                raise ValueError(f'ECRA workspace 与固件 Git 仓库重叠: {workspace}；请配置 analysis.output.location: custom 和仓库外 custom_dir')
            # Preserve the full Unicode display name in project.json while
            # keeping data paths compact for Windows Git/embedded toolchains.
            label = re.sub(r'[^A-Za-z0-9_.-]', '_', name).strip('._-')[:24] or 'project'
            work = workspace/'projects'/(label + '_' + project_id[:20])
            result = work/'results'
        no_links(work)
        return cls(*map(str, (TOOL_ROOT, root, repo, project_id, name, workspace, work, result,
            result/'cache', result/'snapshots', work/'builds', result/'git_diff', work/'trees')))

    def initialize(self):
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
            if work != Path(self.results_root):
                raise ValueError(f'ECRA 工作区已有未知数据，拒绝接管: {work}')
            # Explicit project mode is not permission to adopt a source folder
            # or another project's unmarked historical results.
            names = {p.name for p in work.iterdir()}
            if names != {'semantics.yaml'}:
                try:
                    legacy_files(self.project_root, work)
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    raise ValueError(f'工程内输出目录缺少可验证所有权，拒绝接管: {work}；'
                                     '请选择新的独立目录或使用默认 tool 模式。' + str(exc)) from exc
        try:
            work.mkdir(parents=True, exist_ok=True)
            # O_EXCL prevents two first runs from racing the ownership claim.
            if not marker.exists():
                claimed = published = False
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
            raise ValueError(f'ECRA workspace 无法写入: {work}；请设置 analysis.output.location: custom 和可写 custom_dir。{exc}') from exc
        return self

    def verify_identity(self):
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
        return no_links(Path(root)/settings.get('build_dir', 'build/ecra'))
    # Actual source tree + settings bind separate commits and workspace builds.
    key = digest(dict(source=canonical(root), cmake=settings))[:24]
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
    if not legacy.is_dir() or legacy == out or (out/'migration.json').exists():
        return
    # An existing new scan is never overwritten by old results.
    if (out/'run.json').exists():
        return
    try:
        files = legacy_files(ws.project_root, legacy)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        progress(f'旧目录未自动接管: {legacy}；{exc}。保留原目录；核对身份后可手动归档到 snapshots。')
        return
    if (legacy/'scan.lock').exists():
        raise ValueError(f'旧数据存在扫描锁: {legacy}/scan.lock；确认旧进程退出并处理锁后重试')
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
        if set(files) != set(legacy_files(ws.project_root, legacy)) or (legacy/'scan.lock').exists():
            raise ValueError('迁移期间旧数据目录发生变化')
        for source in files:
            record = records[source.relative_to(legacy).as_posix()]
            if source.stat().st_size != record['size'] or file_hash(source) != record['sha256']:
                raise ValueError(f'迁移期间旧数据发生变化: {source}')
        write_json(pending/'migration.json', dict(schema=1, source=str(legacy), project_id=ws.project_id,
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
