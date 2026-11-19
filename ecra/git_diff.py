"""Pinned Git comparison and conservative, typed semantic impact closure.

Static facts are never filtered here. Summaries are persisted between the two
sequential analyses, so two complete fact graphs need not coexist in memory.
"""
from collections import Counter, defaultdict, deque
from contextlib import closing
from pathlib import Path
import copy
import os
import re
import subprocess

from .common import digest, read_json, write_json

SUMMARY_SCHEMA = 11

DEFAULTS = dict(enabled=False, base_ref='origin/master', current_ref='HEAD',
                include_uncommitted=False, cache_enabled=True, verify_against_full=False)


def validate_mode(options):
    if options.get('enabled') and options.get('include_uncommitted'):
        raise ValueError('Diff 只支持分支或 tag 的固定提交比较，不再支持 include_uncommitted: true；'
                         '请明确设置 include_uncommitted: false，或关闭 Diff 使用原全量未提交扫描')


def settings(value):
    if isinstance(value, dict) and set(value) & {'target_ref', 'compare_mode', 'uncertain_impact_policy'}:
        raise ValueError('analysis.git_diff 配置已简化：用 base_ref/current_ref 指定直接比较的两个版本；'
                         '删除 target_ref、compare_mode、uncertain_impact_policy。'
                         '旧 merge_base 语义请先建立指向该基准提交的分支或 tag，再填入 base_ref')
    if not isinstance(value, dict) or set(value) - DEFAULTS.keys():
        raise ValueError('analysis.git_diff 必须是映射且不能包含未知字段')
    result = dict(DEFAULTS, **value)
    for key in ('enabled', 'include_uncommitted', 'cache_enabled', 'verify_against_full'):
        if type(result[key]) is not bool:
            raise ValueError(f'analysis.git_diff.{key} 必须是 true/false')
    for key in ('base_ref', 'current_ref'):
        if (not isinstance(result[key], str) or not result[key].strip()
                or result[key] != result[key].strip() or result[key].startswith('-')
                or '\0' in result[key]):
            raise ValueError(f'analysis.git_diff.{key} 必须是非空 Git 引用')
    if result['include_uncommitted'] and result['current_ref'] != 'HEAD':
        raise ValueError('include_uncommitted: true 仅适用于 current_ref: HEAD（当前工作区）')
    return result


def git(root, *args, _stdout=subprocess.PIPE, _returncodes=(0,), _reject_stderr=False):
    from .portable import tool_path
    from .runtime_storage import child_environment
    exe = tool_path('git')
    try:
        # GIT_OPTIONAL_LOCKS alone does not disable porcelain diff's stat-only
        # index refresh. All comparison callers preserve the original index.
        proc = subprocess.run([exe, '-c', 'core.longpaths=true', '-c', 'diff.autoRefreshIndex=false',
                               '-C', str(root), *args], stdout=_stdout,
                              stderr=subprocess.PIPE, timeout=300,
                              env=child_environment(dict(os.environ, GIT_OPTIONAL_LOCKS='0')))
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f'Git 无法运行，差异扫描未完成：{exe}，{exc}') from exc
    if proc.returncode not in _returncodes or (_reject_stderr and proc.stderr):
        detail = proc.stderr.decode('utf-8', 'replace').strip()
        if args == ('rev-parse', '--show-toplevel'):
            raise ValueError(f'Git 无法识别固件工作树 {root}，请核对工程仓库。{exe} 退出码 {proc.returncode}：{detail}')
        raise ValueError(f'Git 比较失败，差异扫描未完成：{exe} 退出码 {proc.returncode}：{detail}')
    return proc.stdout


def write_comparison_patch(pinned, destination):
    """Archive tracked and untracked bytes without changing Git's real index.

    no-index returns 1 for a successful difference. Its stderr must be empty:
    an I/O failure can also return 1 and must never become a complete patch.
    All subprocess output streams to a private pending file, then publishes
    atomically. Unicode paths, empty files, symlinks and binary payloads use
    Git's own patch representation.
    """
    import tempfile
    from .common import replace_file
    repo = Path(pinned.get('frozen_git', {}).get('repository', pinned['repository_root']))
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    pending = None
    try:
        with tempfile.NamedTemporaryFile(mode='wb', buffering=0, prefix='.patch-',
                suffix='.pending', dir=destination.parent, delete=False) as output:
            pending = Path(output.name)
            git(repo, 'diff', '--no-relative', '--binary', '--no-color', '--no-ext-diff', '--no-textconv',
                '--src-prefix=a/', '--dst-prefix=b/', pinned['base_sha'],
                *([] if pinned.get('include_uncommitted') else [pinned['head_sha']]), '--', _stdout=output)
            for change in sorted(pinned['files'], key=lambda row: row['new_path']):
                if change['status'] != '?':
                    continue
                # Keep repository-relative paths even when project.root is a
                # subdirectory. -- prevents a leading dash becoming an option.
                start = output.tell()
                git(repo, '-c', 'core.safecrlf=false', 'diff', '--no-index', '--binary', '--no-color',
                    '--no-ext-diff', '--no-textconv', '--src-prefix=a/', '--dst-prefix=b/',
                    '--', '/dev/null', change['new_path'], _stdout=output,
                    _returncodes=(0, 1), _reject_stderr=True)
                if output.tell() <= start:
                    raise ValueError('未跟踪文件没有形成完整新增补丁，差异扫描未完成：' + change['new_path'])
        replace_file(pending, destination)
    finally:
        if pending is not None:
            pending.unlink(missing_ok=True)


def text(root, *args):
    return git(root, *args).decode('utf-8', 'strict').strip()


def resolve_revision(root, ref):
    """Resolve Git syntax first, then a unique leaf of a local branch name."""
    if not isinstance(ref, str) or not ref or len(ref) > 4096 or '\0' in ref or ref != ref.strip() or ref.startswith('-'):
        raise ValueError('Git 引用格式无效')
    def commit(name):
        return git(root, 'rev-parse', '--verify', '--quiet', '--end-of-options', name + '^{commit}',
                   _returncodes=(0, 1)).decode('ascii').strip()

    resolved = commit(ref)
    if resolved:
        return resolved
    if '/' not in ref and ref != 'HEAD':
        matches = [name for name in text(root, 'for-each-ref', '--format=%(refname)', 'refs/heads').splitlines()
                   if name.removeprefix('refs/heads/').endswith('/' + ref)]
        if len(matches) == 1:
            resolved = commit(matches[0])
            if resolved:
                return resolved
        if len(matches) > 1:
            names = ', '.join(name.removeprefix('refs/heads/') for name in matches[:10])
            raise ValueError(f'Git 短分支名 {ref} 有多个匹配，请填写完整分支名：{names}')
    from .portable import tool_path
    raise ValueError(f'Git 引用不能解析为提交：{ref}（{root}，{tool_path("git")}）。'
                     '请在当前固件仓库中选择已有的本地分支、标签或提交 SHA 后重试。')


def resolve_selection(root, ref):
    """Public Diff inputs are branch/tag names; HEAD aliases its branch."""
    # Reuse argument validation and the unique local leaf convenience.
    sha = resolve_revision(root, ref)
    name = ref
    if ref == 'HEAD':
        name = git(root, 'symbolic-ref', '--quiet', 'HEAD', _returncodes=(0, 1)).decode('utf-8').strip()
    elif '/' not in ref:
        exact = text(root, 'for-each-ref', '--format=%(refname)', 'refs/heads', 'refs/remotes', 'refs/tags').splitlines()
        if not any(p in exact for p in ('refs/heads/'+ref, 'refs/tags/'+ref)):
            leaves = [p for p in exact if p.startswith('refs/heads/') and p.endswith('/'+ref)]
            if len(leaves) == 1:
                name = leaves[0]
    full = (git(root, 'rev-parse', '--symbolic-full-name', '--verify', '--quiet', '--end-of-options', name,
                _returncodes=(0, 1), _reject_stderr=True).decode('utf-8').strip() if name else '')
    if not full.startswith(('refs/heads/', 'refs/remotes/', 'refs/tags/')):
        raise ValueError('Diff 只支持已有分支或 tag；HEAD 必须指向分支，不能使用游离 HEAD、提交表达式或裸 SHA：' + ref)
    return sha, full


def _content_changes(root, base, current=None):
    """Content-aware paths, including zero-line/binary/rename changes.

    Older Git can emit stat-only paths in raw --name-status/--name-only output
    even with --exit-code. Numstat computes actual content without refreshing
    the caller's index; zero counts are meaningful records, not empty changes.
    """
    raw = git(root, 'diff', '--no-relative', '--no-ext-diff', '--no-textconv', '--numstat', '-z', '--find-renames', base,
              *([current] if current else []), '--', _reject_stderr=True)
    if not raw:return set()
    if not raw.endswith(b'\0'):raise ValueError('Git 内容差异记录未完整结束，拒绝缩小比较范围')
    fields=raw.split(b'\0')[:-1];result=set();index=0
    while index<len(fields):
        columns=fields[index].split(b'\t',2);index+=1
        if len(columns)!=3 or any(value!=b'-' and not value.isdigit() for value in columns[:2]):
            raise ValueError('Git 内容差异记录格式无效，拒绝缩小比较范围')
        if columns[2]:old=new=columns[2]
        else:
            if index+1>=len(fields) or not fields[index] or not fields[index+1]:
                raise ValueError('Git 重命名内容记录不完整，拒绝缩小比较范围')
            old,new=fields[index:index+2];index+=2
        result.add((old.decode('utf-8','strict'),new.decode('utf-8','strict')))
    return result


def changes(root, base, current=None):
    fields = git(root, 'diff', '--no-relative', '--no-ext-diff', '--no-textconv', '--name-status', '-z', '--find-renames', base,
                 *([current] if current else []), '--', _reject_stderr=True).split(b'\0')
    content=_content_changes(root,base,current)
    result = []
    covered=set()
    i = 0
    while i < len(fields) and fields[i]:
        status = fields[i].decode('ascii')
        old = fields[i+1].decode('utf-8', 'strict')
        new = fields[i+2].decode('utf-8', 'strict') if status.startswith(('R', 'C')) else old
        pair=(old,new)
        if pair in content:
            result.append(dict(status=status, old_path=old, new_path=new));covered.add(pair)
        elif status.startswith(('R','C')) and (old,old) in content and (new,new) in content:
            # Preserve a genuine raw rename if content output represented the
            # same operation as delete/add. Never use a rename's old path to
            # retain a separate stat-only modification of that unchanged file.
            result.append(dict(status=status,old_path=old,new_path=new));covered.update(((old,old),(new,new)))
        i += 3 if status.startswith(('R', 'C')) else 2
    if content-covered:raise ValueError('Git 名称与内容差异记录不一致，拒绝丢弃真实源码变化')
    return result


def pin(root, cfg):
    options = dict(cfg['analysis']['git_diff'], enabled=True)
    validate_mode(options)
    repo = Path(text(root, 'rev-parse', '--show-toplevel')).resolve()
    from .workspace import context, canonical
    ws = context(root, cfg['analysis'])
    if canonical(repo) != canonical(ws.repository_root):
        raise ValueError('Git 实际仓库根目录与项目身份边界不一致；请检查 .git/core.worktree 配置后重新扫描')
    # Resolve both names only after their shared, build-visible Git view exists.
    from .independent_git import freeze
    frozen = freeze(repo, ws)
    fixed_repo = Path(frozen['repository'])
    head, head_ref = resolve_selection(fixed_repo, options['current_ref'])
    base, base_ref = resolve_selection(fixed_repo, options['base_ref'])
    files = changes(fixed_repo, base, head)
    for change in files:
        change['comment_only'] = False
        if change['status'].startswith('M') and Path(change['new_path']).suffix.lower() in ('.h', '.hh', '.hpp', '.hxx', '.inc'):
            before = git(fixed_repo, 'show', base + ':' + change['old_path'])
            after = git(fixed_repo, 'show', head + ':' + change['new_path'])
            old, new = comment_insensitive(before), comment_insensitive(after)
            change['comment_only'] = old is not None and old == new
    effective = copy.deepcopy(cfg)
    effective['analysis'].pop('_workspace', None)
    effective.setdefault('project', {})['root'] = str(Path(root).resolve())
    input_id = digest([frozen['id'], effective])
    from .workspace import no_links
    config = no_links(Path(ws.git_diff_root)/'inputs'/input_id[:24]/'semantics.json')
    # Configuration is part of the fixed input, not a pointer to a mutable
    # profile. Preserve a corrupt existing copy for diagnosis instead of repair.
    import json
    data = json.dumps(effective, ensure_ascii=False, sort_keys=True, indent=2).encode('utf-8')
    import hashlib
    config_sha = hashlib.sha256(data).hexdigest()
    if config.exists():
        if config.read_bytes() != data:
            raise ValueError('本轮固定配置已损坏；保留现场，禁止复用')
    else:
        config.parent.mkdir(parents=True, exist_ok=True)
        from .independent_git import _write
        _write(config, data)
    return dict(schema=3, repository_root=str(repo), project_subdir=Path(root).resolve().relative_to(repo).as_posix(),
        current_ref=options['current_ref'], base_ref=options['base_ref'], head_sha=head, base_sha=base,
        current_resolved_ref=head_ref, base_resolved_ref=base_ref, frozen_git=frozen, input_id=input_id,
        config_path=str(config), config_sha256=config_sha,
        include_uncommitted=False, workspace_digest=digest(None), files=files)


def comment_insensitive(data):
    """Conservative header comment gate; preserve directive whitespace.

    Raw strings and escaped newlines are intentionally not normalized: their
    lexical rules could make removal of blank lines semantically meaningful.
    """
    try:
        value = data.decode('utf-8', 'strict')
    except UnicodeError:
        return None
    if re.search(r'\\\r?\n|R"', value):
        return None
    pattern = r'"(?:\\[\s\S]|[^"\\])*"|\'(?:\\[\s\S]|[^\'\\])*\'|//[^\n]*|/\*[\s\S]*?\*/'
    value = re.sub(pattern, lambda m: (' ' + '\n'*m[0].count('\n')) if m[0].startswith(('/', '/*')) else m[0], value)
    return '\n'.join(line.strip() for line in value.splitlines() if line.strip())


def fixed_config_path(pinned):
    from .workflow import file_digest
    if pinned.get('schema') != 3:
        raise ValueError('旧 Diff 检查点未固定构建输入；请重新扫描')
    path = Path(pinned['config_path'])
    if file_digest(path) != pinned['config_sha256']:
        raise ValueError('本轮固定配置已改变/损坏；请重新扫描')
    return path


def assert_pin(root, cfg, expected):
    origin_root = Path(expected['repository_root']) / expected['project_subdir']
    if expected.get('schema') != 3:
        raise ValueError('旧 Diff 检查点未固定 Git 构建元数据与配置；请重新扫描以建立固定输入身份')
    from .workspace import context, canonical
    ws = context(origin_root, cfg['analysis'])
    if canonical(ws.repository_root) != canonical(expected['repository_root']):
        raise ValueError('固定 Git 输入不属于当前工程')
    from .independent_git import check_frozen, check_external, _owned
    repository = check_frozen(expected['frozen_git'], ws)
    for side, sha_key in (('base', 'base_sha'), ('current', 'head_sha')):
        if resolve_revision(repository, expected[side+'_resolved_ref']) != expected[sha_key]:
            raise ValueError('固定 Git 提交身份已改变/损坏；禁止使用')
        if expected.get(side+'_source_root'):
            source = Path(expected[side+'_source_root'])
            tree = source if expected['project_subdir'] == '.' else source.parents[len(Path(expected['project_subdir']).parts)-1]
            _owned(repository, tree, expected[sha_key])
            check_external(tree, expected['frozen_git'])
    from .workflow import file_digest
    for path_key, hash_key in (('config_path', 'config_sha256'), ('base_facts_path', 'base_facts_sha256'), ('diff_patch_path', 'diff_patch_sha256'),
                               ('base_summary_path', 'base_summary_sha256')):
        if expected.get(path_key) and file_digest(expected[path_key]) != expected[hash_key]:
            raise ValueError('固定输入或基准证据已变化/损坏：' + expected[path_key] + '；请重新扫描')
    if expected.get('base_source_root'):
        base_root = Path(expected['base_source_root'])
        check_isolated_tree(base_root, expected['base_sha'], expected.get('base_build_path'))
    if expected.get('current_source_root'):
        check_current_tree(expected)
    if expected.get('base_scan_path'):
        # Baseline-only headers, generator outputs and external SDK inputs
        # must remain valid through current extraction/publication as well.
        # Checking just the immutable facts would miss a changed build input.
        from .config import load_config
        from .workflow import checked_scan
        base_cfg, base_config = load_config(Path(expected['base_source_root']), expected['base_config_path'])
        ws.for_results(Path(expected['base_scan_path'])).bind(base_cfg['analysis'])
        checked_scan(Path(expected['base_source_root']), Path(expected['base_scan_path']), base_cfg,
                     base_config, with_facts=False, _report_projection=True)


def canonical_id(value, renames):
    if not isinstance(value, str):
        return value
    for actual in getattr(renames, 'build_roots', ()):
        if value == actual or value.startswith(actual + '/'):
            value = '<构建>' + value[len(actual):]
        for prefix in ('tu::', 'local::'):
            value = value.replace(prefix + actual + '/', prefix + '<构建>/')
    for old, new in renames.items():
        value = value.replace('tu::' + old + '::', 'tu::' + new + '::')
        # Clang file static USRs contain a basename as well as the TU identity.
        if value.startswith(('tu::', 'local::')):
            value = value.replace('c:' + Path(old).name + '@', 'c:' + Path(new).name + '@')
    if value.startswith('local:'):
        # Automatic-local pointer slots are not global/static storage IDs.
        # Clang embeds their declaration byte offset in the USR; inserting a
        # comment must not appear to replace a pointer target. Actual body
        # edits remain independently detected by the full function token hash.
        value = re.sub(r'@\d+(?=@F@)', '@<声明位置>', value)
    return renames.get(value, value)


# Positional/derived identifiers are audit references, not semantic identity.
POSITIONAL = frozenset(('line', 'column', 'offset', 'end_line', 'end_offset', 'definition_line',
    'source_text', 'access_id', 'call_id', 'event_id', 'node_id', 'conflict_id', 'source_access_id',
    'call_chains', 'all_call_chains', 'call_path_set', 'resolved_call_path_count', 'call_path_count',
    'evidence_id', 'blocker_id', 'inherited_from_access_id',
    'cfg_node_id', 'cfg_node', 'instance_id', 'id', 'generated_at', 'call_depth',
    'access_ids', 'instance_ids'))


def normalize(value, renames=None):
    renames = {} if renames is None else renames
    if isinstance(value, dict):
        result = {k: normalize(v, renames) for k, v in value.items() if k not in POSITIONAL}
        for key in ('type', 'canonical_type', 'type_spelling'):
            if isinstance(result.get(key), str):
                # Clang's human-readable anonymous type spelling embeds a
                # source coordinate. Declaration tokens and complete field
                # layout still distinguish actual type/storage changes.
                result[key] = re.sub(r'(\((?:unnamed|anonymous)(?: (?:struct|union|enum))? at )[^\r\n]*?:\d+:\d+\)',
                                     r'\1<source>)', result[key])
        return result
    if isinstance(value, (list, tuple)):
        return [normalize(v, renames) for v in value]
    return canonical_id(value, renames)


def row_hashes(rows, renames):
    return sorted(digest(normalize(row, renames)) for row in rows)


def evidence_digest(value, renames):
    """Compare independent evidence records as a multiset, retaining duplicates.

    Only the explicitly selected outer collection is unordered. Ordered lists
    inside a record (arguments, arrays, execution steps) retain their order.
    Raw facts and static classifications are never modified.
    """
    return digest(row_hashes(value, renames) if isinstance(value, (list, tuple)) else normalize(value, renames))


def pointer_hashes(facts, renames):
    """Compare exact pointees independently of bitmap encoding/atom order."""
    from .target_set import point_targets
    pooled, result = {}, []
    for row in facts.get('pointer_targets', []):
        reference = row.get('target_set_id')
        if reference is not None and reference in pooled:
            targets = pooled[reference]
        else:
            targets = digest(sorted({canonical_id(value, renames) for value in point_targets(facts, row)}))
            if reference is not None:
                pooled[reference] = targets
        content = {key: value for key, value in row.items()
                   if key not in {'targets', 'target_set_id', 'target_count'}}
        content['targets_digest'] = targets
        result.append(digest(normalize(content, renames)))
    return sorted(result)


def build_arguments(unit, root):
    """Canonical project path identity, including Portable's ASCII junctions.

    The real compile command and cache keys remain untouched. Only arguments
    proven to resolve inside this snapshot's root are relocated for comparison;
    compiler driver spelling and macro/literal values retain their semantics.
    """
    root = Path(root).resolve() if root else None
    build_root = Path(unit['ecra_build_root']).resolve() if unit.get('ecra_build_root') else None
    result = []
    prefixes = ('-isystem', '-iquote', '-idirafter', '-include', '-imacros',
                '-isysroot', '--sysroot=', '-I', '-L', '@', '')
    for index, value in enumerate(unit.get('original_arguments', [])):
        value = str(value)
        normalized = None
        if root is not None and index:
            for prefix in prefixes:
                if not value.startswith(prefix):
                    continue
                path = Path(value[len(prefix):])
                if not path.is_absolute():
                    continue
                try:
                    actual = path.resolve()
                    if build_root is not None and actual.is_relative_to(build_root):
                        normalized = prefix + '<构建>/' + actual.relative_to(build_root).as_posix()
                    elif actual.is_relative_to(root):
                        normalized = prefix + '<工程>/' + actual.relative_to(root).as_posix()
                    else:
                        normalized = value  # external aliases are not project relocation proofs
                except (OSError, ValueError):
                    normalized = value
                break
        if normalized is None:
            normalized = (value.replace(str(root), '<工程>').replace(root.as_posix(), '<工程>')
                          if root is not None else value)
        result.append(normalized)
    return result


def variable_change_summary(variable, contexts, renames):
    """紧凑展示摘要，不参与筛选、风险证明或完整证据的替代。"""
    irq_states, fault_states, base_values = Counter(), Counter(), set()
    base_unknown = observations = 0
    for detail in variable.get('protection_details', []):
        for state in detail.get('states', []):
            observations += 1
            irq_states[state.get('irq_state', 'UNKNOWN')] += 1
            value = state.get('faultmask')
            fault_states[str(int(value)) if value in (0, 1) else 'UNKNOWN'] += 1
            value = state.get('basepri')
            if type(value) is int:
                base_values.add(value)
            else:
                base_unknown += 1
    return dict(
        declaration=normalize({key: variable.get(key) for key in
            ('type', 'size_bytes', 'alignment_bytes', 'offset_bits', 'field_path', 'array_size',
             'is_const', 'is_volatile')}, renames),
        accesses=dict(sorted(Counter(a['access_kind'] for a in variable.get('accesses', [])).items())),
        contexts=[dict(id=canonical_id(cid, renames), kind=contexts.get(cid, {}).get('kind'))
                  for cid in sorted(variable.get('contexts', []))],
        protection=dict(status=variable.get('protection_status'), observations=observations,
                        primask=dict(sorted(irq_states.items())), faultmask=dict(sorted(fault_states.items())),
                        basepri_values=sorted(base_values), basepri_unknown=base_unknown),
        coverage=dict(status=variable.get('analysis_coverage'),
                      blocking_records=len(variable.get('blocking_evidence', []))),
        conflicts=dict(records=len(variable.get('conflict_pairs', []))))


def summarize(facts, report, renames=None):
    from .diff_risk import object_evidence, risk_evidence, scope_evidence
    class BuildRenames(dict):
        pass
    renames = BuildRenames(renames or {})
    renames.build_roots = sorted({Path(u['ecra_build_root']).resolve().as_posix()
        for u in facts.get('translation_units', []) if u.get('ecra_build_root')})
    # CFG references hash [translation_unit, function_id]. Relocating a
    # generated TU changes that derived reference, not its mask/protection
    # evidence. Rebuild only references whose proven build path was mapped.
    for function in facts['functions']:
        source, fid = function.get('translation_unit'), function['function_id']
        canonical = [canonical_id(source, renames), canonical_id(fid, renames)]
        if source and canonical != [source, fid]:
            renames['CFG-' + digest([source, fid])[:20]] = 'CFG-' + digest(canonical)[:20]
    cid = lambda value: canonical_id(value, renames)
    functions = {cid(f['function_id']): dict(digest=digest([f.get('semantic_digest'), f.get('consumed_macros_digest')]),
                  _dependency_program=f.get('diff_dependencies'),
                  non_call_digest=digest([f.get('non_call_digest', f.get('semantic_digest')), f.get('consumed_macros_digest')]),
                  standalone_calls=[[offset, cid(target)] for offset, target in f.get('standalone_calls', [])],
                  return_type_kind=f.get('return_type_kind'), name=f['name'],
                  file=cid(f.get('file')), line=f.get('line')) for f in facts['functions']}
    edges = sorted({(cid(c['caller_function_id']), cid(c.get('callee_function_id') or 'unresolved:' + c.get('callee_name', '')))
                    for c in facts['calls']})
    return_edges = sorted({(cid(c['caller_function_id']), cid(c['callee_function_id']))
                           for c in facts['calls'] if c.get('callee_function_id') and c.get('result_used', True)})
    incoming = defaultdict(set)
    for a, b in edges:
        incoming[b].add(a)
    slices, graphs = {}, {}
    context_graph = facts.get('context_call_graph', {})
    context_rows = {row['id']: row for row in facts.get('contexts', [])}
    nvic_by_context = defaultdict(list)
    for priority in facts.get('nvic_priorities', []):
        state = {key: priority.get(key) for key in (
            'irq_number', 'priority_bits', 'grouping', 'logical_priority', 'preemption_priority',
            'subpriority', 'configured_preemption', 'configured_subpriority', 'enabled',
            'effective_validity', 'preemption_validity')}
        for context in priority.get('context_ids', []):
            nvic_by_context[context].append(state)

    def graph_for(accessors):
        key = tuple(sorted(accessors))
        if key not in slices:
            related, pending = set(key), list(key)
            while pending:
                for parent in incoming[pending.pop()]:
                    if parent not in related:
                        related.add(parent)
                        pending.append(parent)
            graph = dict(functions=sorted(related), edges=[list(e) for e in edges if e[1] in related],
                roots=sorted({cid(f) for entries in context_graph.get('roots', {}).values() for f in entries if cid(f) in related}),
                       context_edges={context: paths for context, graph in context_graph.get('edges', {}).items()
                                      if (paths := sorted([cid(a), cid(b)] for a, b in graph if cid(b) in related))})
            graph_id = digest(graph)
            graphs.setdefault(graph_id, graph)
            slices[key] = graph_id
        return slices[key]

    variables = {}
    by_symbol = defaultdict(list)
    for finding in report['findings']:
        by_symbol[finding.get('symbol_id')].append(finding)
    for v in facts['variables']:
        sid = v['symbol_id']
        accesses = v.get('accesses', [])
        accessors = {cid(a['function_id']) for a in accesses if a.get('function_id')}
        graph = graph_for(accessors)
        dimensions = dict(
            declaration=digest(normalize({k: v.get(k) for k in ('semantic_digest', 'consumed_macros_digest', 'type', 'kind', 'storage_class',
                'owner_function_id', 'field_path', 'array_size', 'size_bytes', 'initializer', 'member_definitions')}, renames)),
            # Per-function protection_event hints are attached to every
            # access for navigation. Actual per-access protection is compared
            # below; moving a lock around a must not create a change in b.
            accesses=row_hashes(({key: value for key, value in access.items() if key != 'protection_evidence'}
                                 for access in accesses), renames),
            contexts=row_hashes(
                [c for c in facts.get('context_bindings', []) if cid(c.get('function_id')) in accessors]
                + [dict(context_id=context, nvic_state=state) for context in v.get('contexts', [])
                   for state in nvic_by_context[context]]
                + v.get('concurrency_relations', []), renames),
            protection=evidence_digest(v.get('protection_details', []), renames),
            coverage=digest(dict(analysis_coverage=v.get('analysis_coverage'),
                blocking_evidence=evidence_digest(v.get('blocking_evidence'), renames),
                screening_blockers=evidence_digest(v.get('screening_blockers'), renames),
                safe_evidence=evidence_digest(v.get('safe_evidence'), renames),
                shared_evidence=evidence_digest({key: value for key, value in (v.get('shared_evidence') or {}).items()
                    if not key.endswith('_access_ids')}, renames))),
            conflicts=row_hashes(v.get('conflict_pairs', []), renames),
            classification=v.get('static_classification'), graph=graph)
        # A global conservative fallback need not pull in a private scalar
        # whose complete direct accesses and isolated graph are unchanged.
        # Address-taking, aliases, aggregate overlap and incomplete evidence
        # deliberately disqualify the proof. Ordinary dependency propagation
        # still wins over this exemption whenever it selected the variable.
        private_isolation = (
            v.get('kind') in {'FILE_STATIC', 'LOCAL_STATIC'} and v.get('storage_class') == 'STATIC'
            and v.get('static_classification') == 'SAFE_PROVEN'
            and v.get('analysis_coverage') == 'COMPLETE' and not v.get('blocking_evidence')
            and not any(v.get(k) for k in ('is_pointer', 'is_struct', 'is_array', 'field_path', 'overlap_groups'))
            and bool(accesses) and len(v.get('contexts', [])) == 1
            and all(a.get('access_kind') in {'READ', 'WRITE', 'RMW'}
                    and a.get('parse_confidence') == 'exact'
                    and not any(a.get(k) for k in ('via_alias', 'via_api', 'inherited_from_access_id'))
                    for a in accesses))
        variables[cid(sid)] = dict(symbol_id=sid, name=v.get('qualified_name', v.get('name')),
            _dependency_accesses=accesses,
            object_evidence=object_evidence(v, cid), risk_evidence=risk_evidence(v, context_rows, cid),
            private_storage_isolation=private_isolation,
            file=cid(v.get('definition_file')), original_file=v.get('definition_file'), line=v.get('definition_line'), dimensions=dimensions,
            accessors=sorted(accessors), graph_id=graph,
            reads=sorted({cid(a['function_id']) for a in accesses if a.get('access_kind') in ('READ', 'RMW')}),
            writes=sorted({cid(a['function_id']) for a in accesses if a.get('access_kind') in ('WRITE', 'RMW')}),
            root=cid(v.get('root_symbol_id') or v.get('array_root_symbol_id') or sid),
            array_index=v.get('array_index'),
            field_path=v.get('field_path'), is_union=v.get('is_union'),
            offset_bits=v.get('offset_bits'), size_bytes=v.get('size_bytes'), overlap_groups=v.get('overlap_groups', []),
            container=v.get('static_classification') == 'CONTAINER',
            findings=row_hashes([dict(static_classification=f.get('static_classification'),
                **{key: evidence_digest(f.get(key), renames) for key in ('rules', 'conflict_pairs', 'uncertainties')})
                for f in by_symbol[sid]], {}),
            evidence_summary=variable_change_summary(v, context_rows, renames))
        variables[cid(sid)]['evidence_summary'].update(
            classification=v.get('static_classification'),
            graph=dict(functions=len(graphs[graph]['functions']), edges=len(graphs[graph]['edges']),
                       roots=len(graphs[graph]['roots'])))
    from .diff_dependencies import bind_dependencies
    dependency_storage = {}
    for variable in facts.get('diff_dependency_storage', []):
        sid = cid(variable['symbol_id'])
        dependency_storage[sid] = dict(symbol_id=sid, root=cid(variable.get('root_symbol_id')
            or variable.get('array_root_symbol_id') or variable['symbol_id']),
            declaration=digest(normalize({key: value for key, value in variable.items() if key != 'accesses'}, renames)),
            container=bool(variable.get('is_struct') or variable.get('is_array')
                           or variable.get('resource_kind') in {'STRUCT_CONTAINER', 'STRUCT_MEMBER_CONTAINER', 'ARRAY_CONTAINER'}),
            _dependency_accesses=variable.get('accesses', []),
            **{key: variable.get(key) for key in ('array_index', 'field_path', 'offset_bits', 'size_bytes', 'overlap_groups')})
    bind_dependencies(functions, dict(dependency_storage, **variables), cid, lambda value: normalize(value, renames))
    global_semantics = {k: row_hashes(facts.get(k, []), renames) for k in
        ('contexts', 'irq_priority_events', 'nvic_resolved_events', 'protection_events', 'registrations',
         'hardware_contexts', 'preemption_relations', 'address_escapes')}
    global_semantics['pointer_targets'] = pointer_hashes(facts, renames)
    return dict(schema=SUMMARY_SCHEMA, variables=variables, graphs=graphs, functions=functions, edges=edges,
        dependency_storage=dependency_storage,
        comparison_scope=scope_evidence(facts, report, cid),
        return_edges=return_edges,
        macros={cid(u['source_file']): u.get('semantic_macros_digest') for u in facts.get('translation_units', [])},
        dependencies=sorted({canonical_id(str(Path(p).resolve().relative_to(Path(report['coverage']['project_root']).resolve())).replace('\\', '/'), renames)
            if report.get('coverage', {}).get('project_root') and Path(p).resolve().is_relative_to(Path(report['coverage']['project_root']).resolve())
            else cid(str(p)) for u in facts.get('translation_units', []) for p in u.get('includes', [])}),
        semantics=global_semantics, unknowns=row_hashes(facts.get('unknowns', []), renames),
        impact_unknowns=[normalize({key: gap.get(key) for key in ('kind', 'function_id', 'symbol_id', 'file')}, renames)
                        for gap in facts.get('unknowns', [])],
        build=sorted(digest([cid(u.get('source_file')), build_arguments(u, report.get('coverage', {}).get('project_root'))])
                     for u in facts.get('translation_units', [])),
        analysis_status=report['analysis_status'])


REASONS = dict(DIRECT_CHANGED='声明、初始化或存储定义变化', CALL_GRAPH_CHANGED='完整调用图变化',
    ACCESS_CHANGED='读写或间接访问变化', EXECUTION_CONTEXT_CHANGED='执行上下文变化',
    PROTECTION_CHANGED='保护机制变化', COVERAGE_CHANGED='覆盖证据变化',
    CONFLICT_CHANGED='并发冲突证据变化', STATIC_CHANGED='静态结论变化',
    SEMANTIC_IMPACT='上下游数据或控制语义影响', CANNOT_EXCLUDE_IMPACT='无法排除影响，保守扩大',
    BUILD_SEMANTICS_CHANGED='头文件、宏或构建语义变化', MATCH_UNCERTAIN='跨版本存储身份无法可靠匹配',
    OBJECT_CHANGED='对象存在性或构建归属变化', VERSION_EVIDENCE='双版本对象证据变化',
    DATA_DEPENDENCY='实际数据依赖', RETURN_DEPENDENCY='返回值被实际消费',
    COVERAGE_DEPENDENCY='提取缺口可能隐藏变化，沿实际依赖保留待核实',
    PARAMETER_DEPENDENCY='实际参数值依赖', CONTROL_DEPENDENCY='控制条件影响执行',
    CALL_DEPENDENCY='实际调用执行影响', FUNCTION_ONLY_DEPENDENCY='仅函数级或不完整依赖，待核实',
    PHYSICAL_OVERLAP='已证明物理存储重叠', POSSIBLE_OVERLAP='可能存储重叠，待核实',
    INDEPENDENCE_PROVEN='具有独立性证明，可排除', CONTAINER_AGGREGATION='仅汇总成员，不重复计作风险')


def variable_graph(summary, variable):
    if not variable:
        return dict(edges=[], roots=[])
    if 'graph_id' in variable:
        return summary['graphs'][variable['graph_id']]
    return variable['graph']  # Legacy in-memory callers; persisted caches use SUMMARY_SCHEMA.


def risk_comparison(old, new):
    """变量风险只能在同一分析粒度、两版均有结论时比较。"""
    if old is None or new is None:
        return 'UNMATCHED', '缺少同一存储对象的双版本证据；新增或删除记录不等于风险新增或修复。'
    old_class = old['dimensions']['classification']
    new_class = new['dimensions']['classification']
    old_container = old.get('container', old_class == 'CONTAINER')
    new_container = new.get('container', new_class == 'CONTAINER')
    if old_container != new_container:
        return ('STORAGE_SHAPE_CHANGED',
                '存储对象在标量与容器间转换，根对象与成员的风险需要分别核对，不能据容器分类判断风险新增或消除。')
    comparable = {'SUSPECT', 'SAFE_PROVEN', 'SHARED_NO_REVIEW', 'UNKNOWN'}
    if old_container or old_class not in comparable or new_class not in comparable:
        return ('AGGREGATE_OR_UNASSESSED',
                '容器、非存储对象或尚未分析的记录不是可直接比较的变量风险结论，需核对实际存储对象及其成员。')
    return 'COMPARABLE', None


def compare(base, head, pinned):
    from .diff_risk import COMPARISON_SCHEMA, ObjectComparison, risk_transition, change_counts
    bv, hv = base['variables'], head['variables']
    objects = ObjectComparison(base, head, pinned)
    reasons = defaultdict(set)
    modified = {f for f in base['functions'].keys() | head['functions'].keys()
                if base['functions'].get(f, {}).get('digest') != head['functions'].get(f, {}).get('digest')
                or base['functions'].get(f, {}).get('dependencies', {}).get('semantic_digest')
                   != head['functions'].get(f, {}).get('dependencies', {}).get('semantic_digest')
                or f not in base['functions'] or f not in head['functions']}
    mapping = dict(declaration='DIRECT_CHANGED', accesses='ACCESS_CHANGED', graph='CALL_GRAPH_CHANGED',
        contexts='EXECUTION_CONTEXT_CHANGED', protection='PROTECTION_CHANGED', coverage='COVERAGE_CHANGED',
        conflicts='CONFLICT_CHANGED', classification='STATIC_CHANGED')
    for sid in bv.keys() | hv.keys():
        old, new = bv.get(sid), hv.get(sid)
        if old is None or new is None:
            event = objects.describe(old, new)['event']
            reasons[sid].add('OBJECT_CHANGED')
            reasons[sid].add('MATCH_UNCERTAIN' if event in {'MATCH_UNCERTAIN', 'EXISTENCE_UNCERTAIN'} else 'DIRECT_CHANGED')
            continue
        if risk_comparison(old, new)[0] == 'STORAGE_SHAPE_CHANGED':
            reasons[sid].add('MATCH_UNCERTAIN')
        for key, reason in mapping.items():
            if old['dimensions'][key] != new['dimensions'][key]:
                reasons[sid].add(reason)
        if old['findings'] != new['findings']:
            reasons[sid].add('CONFLICT_CHANGED')
    fallback = []
    if base['semantics'] != head['semantics']:
        fallback.append('执行入口、保护、NVIC、DMA 或别名全局语义变化')
    # Record global review triggers separately from each object's positive or
    # negative dependence proof. They do not automatically change risk labels.
    if (modified or reasons) and (base['unknowns'] or head['unknowns']):
        fallback.append('存在未解析依赖，无法证明局部影响边界')
    dependencies = set(base.get('dependencies', [])) | set(head.get('dependencies', []))
    prefix = pinned.get('project_subdir', '.')
    from .compilation import source_language
    build_changed = base.get('build') != head.get('build') or base.get('macros') != head.get('macros') or any(
        Path(f['new_path']).suffix.lower() in ('.h', '.hh', '.hpp', '.hxx', '.inc', '.cmake', '.ld', '.lds', '.s', '.a', '.o', '.obj', '.mk', '.sct', '.icf')
        or Path(f['new_path']).name in ('CMakeLists.txt', 'CMakePresets.json', 'CMakeUserPresets.json', 'compile_commands.json', 'Makefile')
        or (source_language(f['new_path']) not in {'c', 'c++'}
            and Path(os.path.relpath(f['new_path'], prefix)).as_posix() in dependencies) for f in pinned['files'] if not f.get('comment_only'))
    if build_changed:
        fallback.append('头文件或构建输入变化，重新评估完整构建范围')
    from .diff_impact import classify_impacts, LABELS
    # Macro/header consumers and declaration layouts are already compared
    # from expanded AST facts. Actual command/link/build changes still need
    # an independent build-boundary proof before excluding an object.
    build_uncertain = base.get('build') != head.get('build') or any(
        Path(f['new_path']).suffix.lower() in ('.cmake', '.ld', '.lds', '.s', '.a', '.o', '.obj', '.mk', '.sct', '.icf')
        or Path(f['new_path']).name in ('CMakeLists.txt', 'CMakePresets.json', 'CMakeUserPresets.json', 'compile_commands.json', 'Makefile')
        for f in pinned['files'] if not f.get('comment_only'))
    accounting = classify_impacts(base, head, reasons, modified,
                                  build_changed=build_uncertain)
    if build_changed:
        for sid, category in accounting['categories'].items():
            if category != 'EXCLUDED':
                reasons[sid].add('BUILD_SEMANTICS_CHANGED')
    fallback_exemptions = accounting['fallback_exemptions']
    conservative = {hv[sid]['symbol_id'] for sid, category in accounting['categories'].items()
                    if category == 'UNCERTAIN' and sid in hv}
    incomplete_impact = bool(accounting['counts']['UNCERTAIN'] or accounting['regional_gaps'])
    from functools import lru_cache
    impacts, deleted, baseline_only = {}, [], []
    @lru_cache(maxsize=32)
    def indexed_edges(is_base, graph_id):
        # Only an acceleration cache is bounded; every graph is still compared.
        return frozenset(tuple(e) for e in (base if is_base else head)['graphs'][graph_id]['edges'])
    def edges_of(summary, variable):
        if not variable:
            return frozenset()
        if 'graph_id' in variable:
            return indexed_edges(summary is base, variable['graph_id'])
        return frozenset(tuple(e) for e in variable_graph(summary, variable)['edges'])
    for sid, why in sorted(reasons.items()):
        old, new = bv.get(sid), hv.get(sid)
        old_edges, new_edges = edges_of(base, old), edges_of(head, new)
        old_class = old['dimensions']['classification'] if old else None
        new_class = new['dimensions']['classification'] if new else None
        object_change = objects.describe(old, new)
        transition = risk_transition(old, new, object_change,
                                     base.get('comparison_scope', {}), head.get('comparison_scope', {}))
        category = accounting['categories'][sid]
        impact = dict(selected=category != 'EXCLUDED', impact_class=category, impact_label=LABELS[category],
            impact_evidence=accounting['evidence'].get(sid, []),
            exclusion_proof=accounting['exclusion_proofs'].get(sid),
            impact_coverage_evidence=accounting['coverage'][sid], reasons=sorted(why), reason_labels=[REASONS[r] for r in sorted(why)],
            added_edges=[list(e) for e in sorted(new_edges-old_edges)], removed_edges=[list(e) for e in sorted(old_edges-new_edges)],
            unchanged_edges_count=len(old_edges & new_edges), impact_coverage='CONSERVATIVE' if (
                category == 'UNCERTAIN' or any(assessment['related_gaps'] or assessment['unaccounted_gaps']
                    for assessment in accounting['coverage'][sid].values())) else 'COMPLETE',
            object_change=object_change, risk_transition=transition,
            risk_change=transition['label'], risk_comparison_status=transition['comparison_status'], risk_comparison_note=transition['note'],
            base=old, head_classification=new_class,
            base_source_root=pinned.get('base_source_root'), head_sha=pinned['head_sha'], base_sha=pinned['base_sha'])
        impact['evidence_changes'] = {dimension: dict(
            base=old.get('evidence_summary', {}).get(dimension) if old else None,
            head=new.get('evidence_summary', {}).get(dimension) if new else None)
            for dimension, reason in mapping.items() if reason in why}
        impact.update(added_paths=representative_paths(new, new_edges-old_edges, variable_graph(head, new)),
                      removed_paths=representative_paths(old, old_edges-new_edges, variable_graph(base, old)),
                      base_facts_path=pinned.get('base_facts_path'), base_facts_sha256=pinned.get('base_facts_sha256'),
                      base_summary_path=pinned.get('base_summary_path'), base_summary_sha256=pinned.get('base_summary_sha256'),
                      diff_patch_path=pinned.get('diff_patch_path'))
        if new:
            impacts[new['symbol_id']] = impact
        else:
            record = dict(symbol_id=old['symbol_id'], name=old['name'], impact_class=category,
                          impact_label=LABELS[category], impact=impact)
            baseline_only.append(record)
            if object_change['event'] == 'DELETED':
                deleted.append(record)
    from itertools import chain
    object_accounting = [dict(object_id=sid, symbol_id=(hv.get(sid) or bv[sid])['symbol_id'],
        name=(hv.get(sid) or bv[sid])['name'], evidence_side='current' if sid in hv else 'baseline',
        impact_class=category, impact_label=LABELS[category],
        container=bool((hv.get(sid) or bv[sid]).get('container')), reasons=sorted(reasons[sid]))
        for sid, category in sorted(accounting['categories'].items())]
    comparison_objects = []
    baseline_indexes = {item['symbol_id']: i for i, item in enumerate(baseline_only)}
    for row in object_accounting:
        side, symbol = row['evidence_side'], row['symbol_id']
        if row['impact_class'] == 'EXCLUDED':
            continue
        if side == 'current':
            impact = impacts[symbol]
            path = ['impacts', symbol]
        else:
            index = baseline_indexes[symbol]
            impact = baseline_only[index]['impact']
            path = ['baseline_only_variables', index, 'impact']
        transition = impact['risk_transition']
        comparison_objects.append(dict(row, object_event=impact['object_change']['event'],
            base_classification=transition['base_classification'], head_classification=transition['head_classification'],
            risk_case=transition['matrix_case'], risk_code=transition['code'], risk_label=transition['label'],
            impact_path=path))
    return dict(pin=pinned, selected_symbol_ids=sorted(sid for sid, row in impacts.items() if row['selected']),
        definite_symbol_ids=sorted(sid for sid, row in impacts.items() if row['impact_class'] == 'DEFINITE'),
        excluded_symbol_ids=sorted(sid for sid, row in impacts.items() if row['impact_class'] == 'EXCLUDED'),
        impacts=impacts, deleted_variables=deleted,
        impact_schema=accounting['schema'], impact_counts=accounting['counts'],
        identified_object_count=accounting['identified_object_count'], container_count=accounting['container_count'],
        identified_objects_accounted=True, real_object_inventory_complete=not accounting['regional_gaps'],
        regional_gaps=accounting['regional_gaps'],
        object_accounting=object_accounting,
        comparison_objects=comparison_objects,
        comparison_analysis_status=dict(base=base.get('analysis_status'), head=head.get('analysis_status')),
        comparison_schema=COMPARISON_SCHEMA, baseline_only_variables=baseline_only,
        change_counts=change_counts(chain((row for row in impacts.values() if row['selected']),
                                         (row['impact'] for row in baseline_only if row['impact']['selected']))),
        modified_function_ids=sorted(modified), fallback_level='L1' if fallback else 'L0', fallback_reasons=fallback,
        fallback_exemptions=fallback_exemptions,
        conservative_symbol_ids=sorted(conservative),
        selection_basis='THREE_WAY_DEPENDENCY_ACCOUNTING',
        impact_coverage='CONSERVATIVE' if incomplete_impact else 'COMPLETE',
        note='差异清单包含明确影响和待核实对象；可排除对象及其证明保留在后台。三类数量仅覆盖已识别存储对象，容器不重复计数，区域性缺口单独记录。影响分类不改变静态风险和原人工规则。')


def representative_paths(variable, changed_edges, evidence_graph=None):
    """One finite shortest graph witness per changed edge, never all paths."""
    if not variable or not changed_edges:
        return []
    evidence_graph = evidence_graph if evidence_graph is not None else variable['graph']
    graph, reverse = defaultdict(set), defaultdict(set)
    for a, b in evidence_graph['edges']:
        graph[a].add(b)
        reverse[b].add(a)
    before, after = {}, {}
    queue = deque(evidence_graph.get('roots', []))
    # Store one predecessor/successor per vertex. Keeping a copied path at
    # every BFS vertex costs quadratic memory on long firmware call chains;
    # only the requested display witnesses need complete path lists.
    before.update((f, None) for f in queue)
    while queue:
        f = queue.popleft()
        for child in sorted(graph[f]):
            if child not in before:
                before[child] = f
                queue.append(child)
    queue = deque(variable['accessors'])
    after.update((f, None) for f in queue)
    while queue:
        f = queue.popleft()
        for parent in sorted(reverse[f]):
            if parent not in after:
                after[parent] = f
                queue.append(parent)
    def prefix(vertex):
        path = [vertex]
        while before.get(vertex) is not None:
            vertex = before[vertex]
            path.append(vertex)
        path.reverse()
        return path

    def suffix(vertex):
        path = [vertex]
        while after.get(vertex) is not None:
            vertex = after[vertex]
            path.append(vertex)
        return path

    return [prefix(a) + suffix(b) for a, b in sorted(changed_edges)]


def selected_findings(report):
    selection = report.get('git_diff')
    if not selection:
        return list(report.get('findings', []))
    ids = set(selection['selected_symbol_ids'])
    # Independent global gaps must not disappear from review/coverage.
    return [f for f in report.get('findings', []) if not f.get('symbol_id') or f['symbol_id'] in ids]


def presentation_view(facts, report):
    if not report.get('git_diff'):
        return facts, report
    ids = set(report['git_diff']['selected_symbol_ids'])
    view, result = dict(facts), dict(report)
    view['variables'] = [v for v in facts['variables'] if v['symbol_id'] in ids]
    result['findings'] = selected_findings(report)
    result['presentation_notice'] = '当前差异范围：展示明确影响与待核实变量；可排除对象及证明保留在后台。区域性缺口不计入变量数量，后台保留完整分析。'
    return view, result


def _relative_worktree_gitdir(repository, directory, expected_sha):
    """Keep private linked snapshots compatible with legacy CMake Git readers."""
    from .common import replace_file
    repository, directory = Path(repository).resolve(), Path(directory).resolve()
    reference = directory / '.git'
    if reference.is_symlink() or not reference.is_file():
        raise ValueError('隔离基准缺少普通工作树 Git 引用文件，禁止改写')

    def resolved_git_path(root, option):
        path = Path(text(root, 'rev-parse', option))
        return (root / path).resolve()

    common = resolved_git_path(repository, '--git-common-dir')
    gitdir = resolved_git_path(directory, '--absolute-git-dir')
    if (resolved_git_path(directory, '--git-common-dir') != common
            or not gitdir.is_relative_to(common / 'worktrees')
            or Path(text(directory, 'rev-parse', '--show-toplevel')).resolve() != directory
            or text(directory, 'rev-parse', 'HEAD') != expected_sha):
        raise ValueError('隔离基准不属于当前仓库的指定工作树，禁止改写 Git 引用')
    registered = Path((gitdir / 'gitdir').read_text(encoding='utf-8').strip())
    if (gitdir / registered).resolve() != reference.resolve():
        raise ValueError('隔离基准工作树登记路径不一致，禁止改写 Git 引用')
    original = reference.read_bytes()
    if not original.decode('utf-8').startswith('gitdir: '):
        raise ValueError('隔离基准 Git 引用格式无效')
    try:
        relative = Path(os.path.relpath(gitdir, directory)).as_posix()
    except ValueError:
        # Different Windows volumes cannot be expressed as a relative path.
        # Preserve the valid absolute reference; ordinary build validation must
        # still succeed before facts can be reused or a result published.
        return 'ABSOLUTE_CROSS_VOLUME'
    replacement = ('gitdir: ' + relative + '\n').encode('utf-8')
    if original == replacement:
        return 'RELATIVE'
    temp = reference.with_name('.git.ecra-relative.tmp')
    replaced = False
    try:
        temp.write_bytes(replacement)
        replace_file(temp, reference)
        replaced = True
        if (resolved_git_path(directory, '--absolute-git-dir') != gitdir
                or resolved_git_path(directory, '--git-common-dir') != common
                or text(directory, 'rev-parse', 'HEAD') != expected_sha):
            raise ValueError('隔离基准 Git 引用转换后身份不一致')
    except BaseException:
        if replaced:
            temp.write_bytes(original)
            replace_file(temp, reference)
        raise
    finally:
        temp.unlink(missing_ok=True)
    return 'RELATIVE'


def relocate_paths(value, old_root, new_root):
    """Relocate project-local paths once, retaining external sibling paths."""
    replacements = {str(old_root): str(new_root), old_root.as_posix(): new_root.as_posix()}
    pattern = '(?:' + '|'.join(re.escape(path) for path in replacements) + r')(?=$|[/\\\s"\x27])'
    def relocate(value):
        if isinstance(value, dict):
            return {key: relocate(item) for key, item in value.items()}
        if isinstance(value, list):
            return [relocate(item) for item in value]
        return re.sub(pattern, lambda match: replacements[match[0]], value) if isinstance(value, str) else value
    return relocate(value)


def relocate_config(cfg, old_root, new_root):
    """Use the same analysis settings with version-local absolute paths."""
    result = relocate_paths(cfg, old_root, new_root)
    if '_workspace' in cfg['analysis']:
        result['analysis']['_workspace'] = copy.deepcopy(cfg['analysis']['_workspace'])
    result['project']['root'] = str(new_root)
    return result


def current_context(root, cfg, pinned):
    """Restore a saved analysis context without creating or repairing inputs."""
    if not pinned or not pinned.get('current_source_root'):
        return root, cfg
    source = Path(pinned['current_source_root'])
    origin = Path(pinned['repository_root']) / pinned['project_subdir']
    if root.resolve() not in (origin.resolve(), source.resolve()):
        raise ValueError('分支比较检查点不属于当前工程；请重新扫描')
    if cfg.get('project', {}).get('root') == str(source) and pinned.get('schema') != 3:
        return source, cfg
    from .workspace import context
    workspace = context(origin, cfg['analysis'])
    if pinned.get('schema') == 3:
        from .workflow import file_digest
        if file_digest(pinned['config_path']) != pinned['config_sha256']:
            raise ValueError('本轮固定配置已改变/损坏；请重新扫描')
        # Review settings may still change independently of static evidence.
        fixed = read_json(pinned['config_path'])
        fixed['review'] = copy.deepcopy(cfg.get('review', {}))
        cfg = fixed
    current_cfg = relocate_config(cfg, origin, source)
    workspace.bind(current_cfg['analysis'])
    if pinned.get('current_database_path'):
        current_cfg['analysis']['compile_database'] = pinned['current_database_path']
    return source, current_cfg


def version_directory(workspace, pinned, side):
    sha = pinned['head_sha' if side == 'current' else 'base_sha']
    identity = digest([sha, pinned['input_id']])[:20] if pinned.get('schema') == 3 else sha[:16]
    from .workspace import no_links
    return no_links(Path(workspace.worktree_root)/(side + '-' + identity))


def check_isolated_tree(source, sha, build=None):
    source = Path(source)
    if text(source, 'rev-parse', 'HEAD') != sha:
        raise ValueError('隔离工作树提交身份已变化；请重新扫描')
    if _content_changes(source,'HEAD'):
        raise ValueError(f'隔离源码已变化，拒绝使用污染的事实: {source}')
    repo = Path(text(source, 'rev-parse', '--show-toplevel'))
    from .compilation import _owns_build_directory
    owned = Path(build).resolve() if build and _owns_build_directory(Path(build), source) else None
    # --ignored also catches source-directory generators hidden by .gitignore.
    # Only a specifically owned, explicitly selected build may be admitted.
    paths = git(source, 'ls-files', '--full-name', '--others', '--exclude-standard', '-z').split(b'\0')
    paths += git(source, 'ls-files', '--full-name', '--others', '--ignored', '--exclude-standard', '-z').split(b'\0')
    for path in paths:
        if not path:
            continue
        file = (repo/path.decode('utf-8')).resolve()
        if owned is None or not file.is_relative_to(owned):
            raise ValueError(f'隔离源码目录出现构建写入或未知文件: {file}；'
                             '请将生成文件放入 CMAKE_BINARY_DIR；源码内构建可显式设置 analysis.cmake.location: project，'
                             '但不得改写已提交文件或构建目录外源码。')


def check_current_tree(pinned):
    check_isolated_tree(pinned['current_source_root'], pinned['head_sha'], pinned.get('current_build_path'))


def prepare_current(root, out, cfg, pinned, progress):
    """Materialize an arbitrary comparison ref without switching the user's HEAD."""
    if pinned['include_uncommitted']:
        return root, cfg
    from .workspace import context, no_links
    workspace = context(root, cfg['analysis'])
    # Keep Windows Git's administrative paths bounded. The complete SHA is
    # always checked before reuse; a shortened-name collision is rejected.
    directory = version_directory(workspace, pinned, 'current')
    from .independent_git import prepare_frozen
    private = prepare_frozen(directory, pinned['head_sha'], workspace, pinned['frozen_git'])
    pinned['current_gitdir_reference'] = _relative_worktree_gitdir(private['repository'], directory, pinned['head_sha'])
    source = directory/pinned['project_subdir']
    pinned['current_source_root'] = str(source)
    # Preparation starts from the version's configured database. A preflight
    # pin already carries the derived database path for saved-result replay;
    # treating that artifact as a version-local source would relocate twice.
    source, current_cfg = current_context(root, cfg, dict(pinned, current_database_path=None))
    if 'cmake' in current_cfg['analysis']:
        from .compilation import cmake_build_directory
        pinned['current_build_path'] = str(cmake_build_directory(source, current_cfg['analysis']))
    allowed = None
    if 'cmake' not in current_cfg['analysis']:
        db = current_cfg['analysis'].get('compile_database', 'auto')
        if db == 'auto':
            raise ValueError('任意分支比较的非 CMake 工程必须显式配置版本内的 compile_database')
        relative_db = (source/db).relative_to(directory).as_posix()
        database = Path(workspace.git_diff_root)/'artifacts'/directory.name/'compile_commands.json'
        allowed = str(database)
    pinned['current_database_path'] = allowed
    check_current_tree(pinned)
    if allowed:
        import json
        entries = json.loads(git(private['repository'], 'show', pinned['head_sha'] + ':' + relative_db))
        entries = relocate_paths(entries, root, source)
        write_json(database, entries)
        current_cfg['analysis']['compile_database'] = str(database)
    progress('当前版本独立工作树：' + pinned['current_ref'] + '（' + pinned['head_sha'] + '）')
    return source, current_cfg


def prepare_base(root, out, cfg, pinned, progress, cache_stats=None, *, _frozen_current=False):
    """Persistent detached worktree: no checkout/reset/clean in user workspace."""
    from .cli import run
    from .workflow import read_saved_json, file_digest, checked_scan, engine_digest, clean_report, saved_report_digest
    repo = Path(pinned['frozen_git']['repository'])
    from .workspace import context, no_links
    workspace = context(root, cfg['analysis'])
    if file_digest(pinned['config_path']) != pinned['config_sha256']:
        raise ValueError('本轮固定配置已改变/损坏；请重新扫描')
    cfg = read_json(pinned['config_path'])
    workspace.bind(cfg['analysis'])
    directory = version_directory(workspace, pinned, 'base')
    from .independent_git import prepare_frozen
    from .scan_persistence import is_canonical
    private = prepare_frozen(directory, pinned['base_sha'], workspace, pinned['frozen_git'])
    if text(directory, 'rev-parse', 'HEAD') != pinned['base_sha']:
        raise ValueError('基准工作树身份不一致；禁止复用')
    pinned['base_gitdir_reference'] = _relative_worktree_gitdir(private['repository'], directory, pinned['base_sha'])
    base_root = directory/pinned['project_subdir']
    baseline = copy.deepcopy(cfg)
    baseline['analysis']['git_diff']['enabled'] = False
    if _frozen_current:
        # The baseline is an independent fixed commit. Current working bytes
        # and their private view must never propagate into its full scan.
        baseline['analysis']['git_diff']['include_uncommitted'] = False
    baseline['review']['enabled'] = False
    baseline['review']['prepare_packets'] = False
    baseline['analysis']['open_report'] = False
    # Absolute in-project config paths are remapped. External toolchains remain
    # explicit inputs and are checked by the ordinary snapshot mechanism.
    baseline = relocate_config(baseline, root, base_root)
    artifacts = no_links(Path(workspace.git_diff_root)/'artifacts')
    base_name = directory.name
    baseline_index = no_links(artifacts/(base_name+'.latest.json'))
    native_baseline = is_canonical(out)
    candidate = no_links(artifacts/base_name)
    if native_baseline and baseline_index.exists():
        reference = read_json(baseline_index)
        if (not isinstance(reference, dict) or set(reference) != {'version','base_sha','directory'}
                or type(reference.get('version')) is not int or reference['version'] != 1
                or reference.get('base_sha') != pinned['base_sha']
                or not isinstance(reference.get('directory'), str)
                or not re.fullmatch(re.escape(base_name)+r'(?:-[a-f0-9]{32})?', reference['directory'])):
            raise ValueError('基准权威库索引损坏/越界；保留历史并拒绝接管未知目录')
        candidate = no_links(artifacts/reference['directory'])
    def baseline_workspace(result):
        selected = workspace.for_results(result)
        if native_baseline:
            from dataclasses import replace
            # Attempts have independent immutable authorities, but committed
            # TU objects remain reusable through their original full keys.
            selected = replace(selected, cache_root=str(no_links(
                Path(workspace.cache_root)/'git-baselines'/pinned['base_sha'])))
        return selected
    base_workspace = baseline_workspace(candidate)
    base_workspace.bind(baseline['analysis'])
    if 'cmake' in baseline['analysis']:
        from .compilation import cmake_build_directory
        pinned['base_build_path'] = str(cmake_build_directory(base_root, baseline['analysis']))
    allowed_database = None
    if _content_changes(directory,'HEAD'):
        raise ValueError('隔离基准源码已被修改；拒绝使用污染的基准事实')
    if 'cmake' not in baseline['analysis']:
        db = baseline['analysis'].get('compile_database', 'auto')
        if db == 'auto':
            raise ValueError('差异基准非 CMake 工程必须显式配置版本内的 compile_database')
        original_database = base_root/db
        if not original_database.is_file():
            raise ValueError('基准版本缺少编译数据库；请使用隔离 CMake 构建或提交可重定位的真实数据库')
        # Never copy the HEAD database/build products into the baseline.
        relative_db = original_database.relative_to(directory).as_posix()
        database = Path(workspace.git_diff_root)/'artifacts'/(base_name+'-db')/'compile_commands.json'
        import json
        entries = relocate_paths(json.loads(git(repo, 'show', pinned['base_sha'] + ':' + relative_db)), root, base_root)
        write_json(database, entries)
        baseline['analysis']['compile_database'] = str(database)
    config = artifacts/(base_name+'-config')/'semantics.json'
    saved_baseline = copy.deepcopy(baseline)
    saved_baseline['analysis'].pop('_workspace', None)
    write_json(config, saved_baseline)
    progress('建立基准版本完整事实：' + pinned['base_sha'])
    base_out = Path(base_workspace.results_root)
    base_report = None
    base_state = None
    if cfg['analysis']['git_diff']['cache_enabled']:
        from .config import load_config
        if 'cmake' in baseline['analysis'] and (base_out/'scan_state.json').is_file():
            # Configure/build may consume arbitrary environment variables or
            # generator inputs. Refresh real outputs before verifying the
            # saved compiler closure; a build failure must never become a hit.
            from .compilation import prepare
            from .build_target_checkpoint import baseline_selection
            progress('刷新基准 CMake 构建输入后验证完整事实缓存。')
            with baseline_selection(_frozen_current):
                prepare(base_root, baseline, progress)
        try:
            validated, _ = load_config(base_root, config)
            base_workspace.bind(validated['analysis'])
            _, base_report, base_state = checked_scan(base_root, base_out, validated, config,
                                                      with_facts=False, _report_projection=True)
            if native_baseline and not is_canonical(base_out):
                base_report = None
            else:
                progress('基准完整事实缓存通过源码、预处理闭包和引擎校验。')
        except (ValueError, OSError, KeyError, TypeError) as exc:
            progress('基准完整事实需重新生成，旧权威库保留：' + str(exc))
    if base_report is None:
        from .scan_persistence import is_canonical, MARKER
        if native_baseline:
            # Canonical persistence is immutable: rerunning into an existing
            # database would update only runtime receipts, leaving old static
            # facts paired with a new checkpoint. Never mutate/move that DB.
            if base_out.exists() and any(base_out.iterdir()):
                import uuid
                base_out = no_links(artifacts/(base_name+'-'+uuid.uuid4().hex))
                base_workspace = baseline_workspace(base_out)
                base_workspace.bind(baseline['analysis'])
            base_out.mkdir(parents=True, exist_ok=True)
            # Baselines use the same authority and solver as the current side.
            # Their identity is distinct; no current-version facts are copied.
            write_json(base_out/MARKER, dict(version=1, scan_id='base-'+pinned['base_sha'],
                project_id=workspace.project_id, profile_id='git-baseline'))
        from .build_target_checkpoint import baseline_selection
        with baseline_selection(_frozen_current):
            code = run(base_root, str(config), no_review=True, _cache_enabled=cfg['analysis']['git_diff']['cache_enabled'],
                       _workspace=base_workspace)
        if code == 3 or not read_json(base_out/'result_validity.json').get('analysis_valid'):
            raise ValueError('基准版本分析失败，差异扫描未完成；详见 ' + str(base_out))
        if is_canonical(base_out):
            from .config import load_config
            validated, _ = load_config(base_root, config)
            base_workspace.bind(validated['analysis'])
            _, base_report, base_state = checked_scan(base_root, base_out, validated, config,
                                                      with_facts=False, _report_projection=True)
        else:
            base_report = read_saved_json(base_out/'reports/global_static_concurrency.json')
    check_isolated_tree(base_root, pinned['base_sha'], pinned.get('base_build_path'))
    prefix = pinned['project_subdir'].rstrip('/')
    def local(path):
        return Path(os.path.relpath(path, prefix)).as_posix() if prefix and prefix != '.' and path else path
    renames = {local(f['old_path']): local(f['new_path']) for f in pinned['files'] if f['status'].startswith('R')}
    sha = file_digest(base_out/'facts.json')
    # A projection is not a substitute report. checked_scan verified the full
    # ordered Merkle root before returning this original report digest.
    report_digest = (base_state['report_digest'] if is_canonical(base_out) else
                     saved_report_digest(clean_report(base_report), encoding='ECRA_MERKLE_V1'))
    key = digest(dict(schema=SUMMARY_SCHEMA, engine=engine_digest(), facts=sha,
                      report=report_digest, renames=renames))
    summary_file = no_links(Path(workspace.git_diff_root)/'summary-cache'/(key + '.summary.json'))
    manifest_file = summary_file.with_suffix('.manifest.json')
    reused, corrupt = False, False
    if cfg['analysis']['git_diff']['cache_enabled']:
        try:
            from .diff_verification import summary_cache_matches
            manifest = read_json(manifest_file)
            if (not isinstance(manifest, dict) or manifest.get('key') != key or manifest.get('schema') != SUMMARY_SCHEMA
                    or not summary_cache_matches(manifest, base_report['coverage'])
                    or manifest.get('sha256') != file_digest(summary_file)):
                raise ValueError('基准摘要缓存内容不一致')
            reused = True
            progress('基准规范化证据摘要通过内容校验，复用摘要及其覆盖状态。')
        except FileNotFoundError:
            pass
        except (ValueError, KeyError, TypeError, OSError):
            corrupt = True
    if not reused:
        if is_canonical(base_out):
            from .native_diff_summary import summarize_native
            summary = summarize_native(base_out/'scan.db', renames)
        else:
            base_facts = read_saved_json(base_out/'facts.json', canonical_accesses=True)
            summary = summarize(base_facts, base_report, renames)
            del base_facts
        from .diff_verification import completeness
        summary_completeness = completeness(summary['comparison_scope'])
        write_json(summary_file, summary, indent=None)
        manifest = dict(schema=SUMMARY_SCHEMA, key=key, complete_tus=summary_completeness['complete_tus'],
                        completeness=summary_completeness, sha256=file_digest(summary_file))
        write_json(manifest_file, manifest)
        del summary
    summary_sha256 = manifest['sha256']
    archived = no_links(out/'git_diff/summary-cache'/summary_file.name)
    if archived != summary_file:
        # Pins belong to immutable scan archives, never to a mutable cache.
        # Independent streaming copies keep later cache corruption/rebuilds
        # from changing already published evidence.
        import shutil
        from .common import replace_file
        archived.parent.mkdir(parents=True, exist_ok=True)
        temporary = archived.with_suffix(archived.suffix+'.pending')
        shutil.copyfile(summary_file, temporary)
        if file_digest(temporary) != summary_sha256:
            raise ValueError('基准摘要归档复制校验失败；禁止发布')
        replace_file(temporary, archived)
        write_json(archived.with_suffix('.manifest.json'), manifest)
        summary_file = archived
    if file_digest(summary_file) != summary_sha256:
        raise ValueError('基准摘要验证后已变化；禁止发布')
    pinned['base_summary_path'] = str(summary_file)
    pinned['base_summary_sha256'] = summary_sha256
    if cache_stats is not None:
        cache_stats.update(hit=reused, corrupt=corrupt)
    pinned['base_source_root'] = str(base_root)
    pinned['base_database_path'] = allowed_database
    evidence = out/'git_diff/evidence'/sha
    evidence.mkdir(parents=True, exist_ok=True)
    database = base_out/'scan.db' if (base_out/'scan.db').is_file() else base_out/'facts.json'
    immutable = evidence/database.name
    if not immutable.exists():
        import shutil
        try:
            os.link(database, immutable)
        except OSError:
            temp = immutable.with_suffix('.pending')
            shutil.copyfile(database, temp)
            from .common import replace_file
            replace_file(temp, immutable)
    if file_digest(immutable) != sha:
        raise ValueError('不可变基准证据归档损坏；禁止发布')
    pinned['base_facts_path'] = str(immutable)
    pinned['base_facts_sha256'] = sha
    pinned['base_scan_path'] = str(base_out)
    pinned['base_config_path'] = str(config)
    patch = out/'git_diff'/(digest({k: v for k, v in pinned.items() if not k.startswith('base_facts')}) + '.patch')
    patch_inputs = pinned if not _frozen_current else dict(pinned,repository_root=_frozen_current['repository_root'])
    write_comparison_patch(patch_inputs, patch)
    pinned['diff_patch_path'] = str(patch)
    pinned['diff_patch_sha256'] = file_digest(patch)
    if native_baseline:
        # A mutable locator, not a proof. Every reuse rechecks the original
        # input/config/engine/report gates; failed attempts never replace it.
        no_links(baseline_index.with_suffix(baseline_index.suffix+'.tmp'))
        write_json(baseline_index, dict(version=1,base_sha=pinned['base_sha'],directory=base_out.name))
    return summary_file


def full_reference_summary(root, out, cfg, units, coverage, worker_dir, env, tool_root, source_reader, *, compiler_view=None):
    """Original independent extraction/analysis; no current fact graph required."""
    from .cli import extraction_responses, add_build_unknowns
    from .fact_parts import FactParts
    from .analysis import merge, analyze
    from .input_snapshot import SOURCE_READS
    snapshot = SOURCE_READS.get()
    parts = FactParts()
    verification_units = []
    check_dir = worker_dir/'full-verification'
    check_dir.mkdir(exist_ok=True)
    fixed = {} if compiler_view is None else dict(compiler_view=compiler_view)
    responses = extraction_responses(root, units, cfg, check_dir, env, tool_root, out, **fixed)
    with closing(responses):
        for unit, response, metadata in responses:
            meta = read_json(metadata)
            if meta.get('worker_exception'):
                raise RuntimeError('独立对照提取内部故障：'+str(meta['worker_exception']))
            if meta.get('parse_status') not in {'PARSED', 'PARTIAL', 'FAILED'}:
                raise ValueError('独立对照提取状态无效')
            if isinstance(meta.get('input_snapshot'), dict):
                snapshot.observe(unit, meta['input_snapshot'], signature=meta.get('preprocessor_signature'))
            elif meta['parse_status'] != 'FAILED':
                raise ValueError('独立对照缺少输入证据')
            from .diff_verification import extraction_digest
            parts.append_metadata(response, meta)
            verification_units.append(dict(unit, semantic_macros_digest=meta.get('semantic_macros_digest'),
                                           extraction_digest=extraction_digest(response),
                                           includes=meta.get('includes', []), parse_status=meta['parse_status']))
    snapshot.assert_valid()
    full_facts = merge(parts)
    parts.clear()
    full_facts['translation_units'] = verification_units
    coverage = copy.deepcopy(coverage)
    coverage.update(translation_units_parsed=sum(u['parse_status']=='PARSED' for u in verification_units),
        translation_units_partial=sum(u['parse_status']=='PARTIAL' for u in verification_units),
        translation_units_failed=sum(u['parse_status']=='FAILED' for u in verification_units),
        parse_coverage_percent=round(100*sum(u['parse_status'] in {'PARSED','PARTIAL'} for u in verification_units)/len(verification_units),2))
    full_cfg = copy.deepcopy(cfg)
    full_cfg['analysis']['git_diff']['enabled'] = False
    if not cfg['analysis'].get('build_closure_only', True):
        raise ValueError('当前独立全量对照要求 build_closure_only: true；补充分支盘点尚不支持独立对照')
    add_build_unknowns(full_facts, full_cfg, units, coverage)
    full_report = analyze(full_facts, full_cfg, copy.deepcopy(coverage), root=root, source_reader=source_reader)
    return summarize(full_facts, full_report)


def verify_full(root, out, cfg, units, coverage, facts, report, worker_dir, env, tool_root, source_reader, *, compiler_view=None):
    """Legacy post-analysis entry; native runs execute the reference earlier."""
    actual = full_reference_summary(root, out, cfg, units, coverage, worker_dir, env, tool_root,
                                    source_reader, compiler_view=compiler_view)
    expected = summarize(facts, report)
    from .diff_verification import verify_summaries
    try:
        return verify_summaries(expected, actual, len(units))
    except ValueError:
        write_json(out/'diagnostics/git-diff-verification-failed.json', dict(expected=expected, actual=actual), indent=None)
        raise
