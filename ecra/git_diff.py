"""Pinned Git comparison and conservative, typed semantic impact closure.

Static facts are never filtered here. Summaries are persisted between the two
sequential analyses, so two complete fact graphs need not coexist in memory.
"""
from collections import Counter, defaultdict, deque
from pathlib import Path
import copy
import os
import re
import subprocess

from .common import digest, read_json, write_json

SUMMARY_SCHEMA = 4

DEFAULTS = dict(enabled=False, target_ref='origin/master', compare_mode='merge_base',
                include_uncommitted=False, cache_enabled=True, verify_against_full=False,
                uncertain_impact_policy='expand_or_full_scan')


def settings(value):
    if not isinstance(value, dict) or set(value) - DEFAULTS.keys():
        raise ValueError('analysis.git_diff 必须是映射且不能包含未知字段')
    result = dict(DEFAULTS, **value)
    for key in ('enabled', 'include_uncommitted', 'cache_enabled', 'verify_against_full'):
        if type(result[key]) is not bool:
            raise ValueError(f'analysis.git_diff.{key} 必须是 true/false')
    if not isinstance(result['target_ref'], str) or not result['target_ref'].strip() or result['target_ref'].startswith('-'):
        raise ValueError('analysis.git_diff.target_ref 必须是非空 Git 引用')
    if result['compare_mode'] not in ('merge_base', 'direct'):
        raise ValueError('analysis.git_diff.compare_mode 必须是 merge_base/direct')
    if result['uncertain_impact_policy'] != 'expand_or_full_scan':
        raise ValueError('analysis.git_diff.uncertain_impact_policy 仅支持 expand_or_full_scan')
    return result


def git(root, *args, _stdout=subprocess.PIPE, _returncodes=(0,), _reject_stderr=False):
    from .portable import bundle_root
    bundle = bundle_root()
    exe = str(bundle/'tools/git/cmd/git.exe') if bundle else 'git'
    if bundle and not Path(exe).is_file():
        raise ValueError('Portable 差异模式缺少离线 Git：请将完整 MinGit 解压到 tools/git（包含 cmd/git.exe）')
    try:
        proc = subprocess.run([exe, '-C', str(root), *args], stdout=_stdout,
                              stderr=subprocess.PIPE, timeout=300)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f'Git 无法运行，差异扫描未完成：{exc}') from exc
    if proc.returncode not in _returncodes or (_reject_stderr and proc.stderr):
        raise ValueError('Git 比较失败，差异扫描未完成：' + proc.stderr.decode('utf-8', 'replace'))
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
    repo = Path(pinned['repository_root'])
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    pending = None
    try:
        with tempfile.NamedTemporaryFile(mode='wb', buffering=0, prefix='.patch-',
                suffix='.pending', dir=destination.parent, delete=False) as output:
            pending = Path(output.name)
            git(repo, 'diff', '--no-relative', '--binary', '--no-color', '--no-ext-diff', '--no-textconv',
                '--src-prefix=a/', '--dst-prefix=b/', pinned['base_sha'], '--', _stdout=output)
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


def changes(root, base):
    fields = git(root, 'diff', '--no-relative', '--name-status', '-z', '--find-renames', base, '--').split(b'\0')
    result = []
    i = 0
    while i < len(fields) and fields[i]:
        status = fields[i].decode('ascii')
        old = fields[i+1].decode('utf-8', 'strict')
        new = fields[i+2].decode('utf-8', 'strict') if status.startswith(('R', 'C')) else old
        result.append(dict(status=status, old_path=old, new_path=new))
        i += 3 if status.startswith(('R', 'C')) else 2
    return result


def pin(root, cfg):
    options = cfg['analysis']['git_diff']
    repo = Path(text(root, 'rev-parse', '--show-toplevel')).resolve()
    head = text(root, 'rev-parse', '--verify', 'HEAD^{commit}')
    target = text(root, 'rev-parse', '--verify', options['target_ref'] + '^{commit}')
    ancestor = text(root, 'merge-base', target, head) if options['compare_mode'] == 'merge_base' else None
    base = ancestor or target
    dirty = git(repo, 'status', '--porcelain=v1', '-z', '--untracked-files=all')
    # Build/report outputs must be ignored by the firmware repository. Refuse
    # dirty tracked/untracked inputs rather than accidentally analysing bytes
    # other than the pinned HEAD when workspace inclusion is disabled.
    if dirty and not options['include_uncommitted']:
        raise ValueError('固件工作区存在未提交文件；请提交、忽略构建/报告输出，或启用 include_uncommitted')
    files = changes(repo, base)
    untracked = git(repo, 'ls-files', '--others', '--exclude-standard', '-z').split(b'\0')
    if options['include_uncommitted']:
        files.extend(dict(status='?', old_path=None, new_path=p.decode('utf-8')) for p in untracked if p)
    for change in files:
        change['comment_only'] = False
        if change['status'].startswith('M') and Path(change['new_path']).suffix.lower() in ('.h', '.hh', '.hpp', '.hxx', '.inc'):
            before = git(repo, 'show', base + ':' + change['old_path'])
            path = repo/change['new_path']
            if path.is_file():
                old, new = comment_insensitive(before), comment_insensitive(path.read_bytes())
                change['comment_only'] = old is not None and old == new
    # Full input contents (not mtimes) bind the workspace. Ignored generated
    # compiler inputs are additionally bound by InputSnapshot.
    paths = git(repo, 'ls-files', '-z', '--cached', '--others', '--exclude-standard').split(b'\0')
    from .workflow import file_digest
    workspace = {p.decode('utf-8'): file_digest(repo/p.decode('utf-8')) if (repo/p.decode('utf-8')).is_file() else None
                 for p in paths if p}
    return dict(schema=1, repository_root=str(repo), project_subdir=Path(root).resolve().relative_to(repo).as_posix(),
        current_ref=text(root, 'rev-parse', '--abbrev-ref', 'HEAD'), target_ref=options['target_ref'],
        target_sha=target, head_sha=head, merge_base_sha=ancestor, base_sha=base,
        compare_mode=options['compare_mode'], include_uncommitted=options['include_uncommitted'],
        workspace_digest=digest(workspace), files=files)


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


def assert_pin(root, cfg, expected):
    current = pin(root, cfg)
    if any(current[k] != expected.get(k) for k in current):
        raise ValueError('Git 引用或工作区快照已变化；差异结果失效，请重新扫描')
    from .workflow import file_digest
    for path_key, hash_key in (('base_facts_path', 'base_facts_sha256'), ('diff_patch_path', 'diff_patch_sha256'),
                               ('base_summary_path', 'base_summary_sha256')):
        if expected.get(path_key) and file_digest(expected[path_key]) != expected[hash_key]:
            raise ValueError('基准事实或本轮代码差异已变化/损坏；请重新扫描')
    if expected.get('base_source_root'):
        base_root = Path(expected['base_source_root'])
        changed = git(base_root, 'diff', 'HEAD', '--name-only', '-z').split(b'\0')
        allowed = expected.get('base_database_path')
        if any(p and p.decode('utf-8') != allowed for p in changed):
            raise ValueError('隔离基准源码已变化；本轮差异证据失效')


def canonical_id(value, renames):
    if not isinstance(value, str):
        return value
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
    renames = renames or {}
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
                    if actual.is_relative_to(root):
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
    renames = renames or {}
    cid = lambda value: canonical_id(value, renames)
    functions = {cid(f['function_id']): dict(digest=f.get('semantic_digest'), name=f['name'],
                  file=cid(f.get('file')), line=f.get('line')) for f in facts['functions']}
    edges = sorted({(cid(c['caller_function_id']), cid(c.get('callee_function_id') or 'unresolved:' + c.get('callee_name', '')))
                    for c in facts['calls']})
    incoming = defaultdict(set)
    for a, b in edges:
        incoming[b].add(a)
    slices, graphs = {}, {}
    context_graph = facts.get('context_call_graph', {})
    context_rows = {row['id']: row for row in facts.get('contexts', [])}

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
                context_edges={context: sorted([cid(a), cid(b)] for a, b in graph if cid(b) in related)
                               for context, graph in context_graph.get('edges', {}).items()})
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
            declaration=digest(normalize({k: v.get(k) for k in ('semantic_digest', 'type', 'kind', 'storage_class',
                'owner_function_id', 'field_path', 'array_size', 'size_bytes', 'initializer', 'member_definitions')}, renames)),
            accesses=row_hashes(accesses, renames),
            contexts=row_hashes([c for c in facts.get('context_bindings', []) if cid(c.get('function_id')) in accessors], renames),
            protection=evidence_digest(v.get('protection_details', []), renames),
            coverage=digest(dict(analysis_coverage=v.get('analysis_coverage'),
                blocking_evidence=evidence_digest(v.get('blocking_evidence'), renames),
                screening_blockers=evidence_digest(v.get('screening_blockers'), renames),
                safe_evidence=evidence_digest(v.get('safe_evidence'), renames))),
            conflicts=row_hashes(v.get('conflict_pairs', []), renames),
            classification=v.get('static_classification'), graph=graph)
        variables[cid(sid)] = dict(symbol_id=sid, name=v.get('qualified_name', v.get('name')),
            file=cid(v.get('definition_file')), original_file=v.get('definition_file'), line=v.get('definition_line'), dimensions=dimensions,
            accessors=sorted(accessors), graph_id=graph,
            reads=sorted({cid(a['function_id']) for a in accesses if a.get('access_kind') in ('READ', 'RMW')}),
            writes=sorted({cid(a['function_id']) for a in accesses if a.get('access_kind') in ('WRITE', 'RMW')}),
            root=cid(v.get('root_symbol_id') or sid),
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
    global_semantics = {k: row_hashes(facts.get(k, []), renames) for k in
        ('contexts', 'irq_priority_events', 'nvic_resolved_events', 'protection_events', 'registrations',
         'hardware_contexts', 'preemption_relations', 'address_escapes')}
    global_semantics['pointer_targets'] = pointer_hashes(facts, renames)
    return dict(schema=SUMMARY_SCHEMA, variables=variables, graphs=graphs, functions=functions, edges=edges,
        macros={cid(u['source_file']): u.get('semantic_macros_digest') for u in facts.get('translation_units', [])},
        dependencies=sorted({canonical_id(str(Path(p).resolve().relative_to(Path(report['coverage']['project_root']).resolve())).replace('\\', '/'), renames)
            if report.get('coverage', {}).get('project_root') and Path(p).resolve().is_relative_to(Path(report['coverage']['project_root']).resolve())
            else str(p) for u in facts.get('translation_units', []) for p in u.get('includes', [])}),
        semantics=global_semantics, unknowns=row_hashes(facts.get('unknowns', []), renames),
        build=sorted(digest([u.get('source_file'), build_arguments(u, report.get('coverage', {}).get('project_root'))])
                     for u in facts.get('translation_units', [])),
        analysis_status=report['analysis_status'])


REASONS = dict(DIRECT_CHANGED='声明、初始化或存储定义变化', CALL_GRAPH_CHANGED='完整调用图变化',
    ACCESS_CHANGED='读写或间接访问变化', EXECUTION_CONTEXT_CHANGED='执行上下文变化',
    PROTECTION_CHANGED='保护机制变化', COVERAGE_CHANGED='覆盖证据变化',
    CONFLICT_CHANGED='并发冲突证据变化', STATIC_CHANGED='静态结论变化',
    SEMANTIC_IMPACT='上下游数据或控制语义影响', CANNOT_EXCLUDE_IMPACT='无法排除影响，保守扩大',
    BUILD_SEMANTICS_CHANGED='头文件、宏或构建语义变化', MATCH_UNCERTAIN='跨版本存储身份无法可靠匹配')


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
    if 'UNKNOWN' in (old_class, new_class):
        return 'UNKNOWN_CLASSIFICATION', '至少一个版本的静态结论为无法判断，不能据此确定风险新增或消除。'
    comparable = {'SUSPECT', 'SAFE_PROVEN', 'SHARED_NO_REVIEW'}
    if old_container or old_class not in comparable or new_class not in comparable:
        return ('AGGREGATE_OR_UNASSESSED',
                '容器、非存储对象或尚未分析的记录不是可直接比较的变量风险结论，需核对实际存储对象及其成员。')
    return 'COMPARABLE', None


def compare(base, head, pinned):
    bv, hv = base['variables'], head['variables']
    reasons = defaultdict(set)
    modified = {f for f in base['functions'].keys() | head['functions'].keys()
                if base['functions'].get(f, {}).get('digest') != head['functions'].get(f, {}).get('digest')
                or f not in base['functions'] or f not in head['functions']}
    mapping = dict(declaration='DIRECT_CHANGED', accesses='ACCESS_CHANGED', graph='CALL_GRAPH_CHANGED',
        contexts='EXECUTION_CONTEXT_CHANGED', protection='PROTECTION_CHANGED', coverage='COVERAGE_CHANGED',
        conflicts='CONFLICT_CHANGED', classification='STATIC_CHANGED')
    for sid in bv.keys() | hv.keys():
        old, new = bv.get(sid), hv.get(sid)
        if old is None or new is None:
            reasons[sid].update(('DIRECT_CHANGED', 'MATCH_UNCERTAIN'))
            continue
        if risk_comparison(old, new)[0] == 'STORAGE_SHAPE_CHANGED':
            reasons[sid].add('MATCH_UNCERTAIN')
        for key, reason in mapping.items():
            if old['dimensions'][key] != new['dimensions'][key]:
                reasons[sid].add(reason)
        if old['findings'] != new['findings']:
            reasons[sid].add('CONFLICT_CHANGED')
    # Typed worklist: changed callee -> all callers (return/control effects),
    # affected caller -> all callees (arguments/side effects), writer -> readers
    # (shared data), overlapping root -> sibling storages. No path enumeration.
    outgoing, incoming, function_vars, readers, root_vars = (defaultdict(set) for _ in range(5))
    for a, b in base['edges'] + head['edges']:
        outgoing[a].add(b)
        incoming[b].add(a)
    for summary in (base, head):
        for sid, v in summary['variables'].items():
            for f in v['accessors']:
                function_vars[f].add(sid)
            readers[sid].update(v['reads'])
            root_vars[v['root']].add(sid)
    pending = deque(('function', f) for f in modified)
    pending.extend(('variable', sid) for sid in list(reasons))
    seen = set()
    while pending:
        kind, key = pending.popleft()
        if (kind, key) in seen:
            continue
        seen.add((kind, key))
        if kind == 'function':
            pending.extend(('function', f) for f in outgoing[key] | incoming[key])
            for sid in function_vars[key]:
                reasons[sid].add('SEMANTIC_IMPACT')
                pending.append(('variable', sid))
                if any(key in summary['variables'].get(sid, {}).get('writes', []) for summary in (base, head)):
                    pending.extend(('function', f) for f in readers[sid])
        else:
            # A selected read alone is not a write. Only affected writers and
            # changed storage can propagate values into cross-function readers.
            old, new = bv.get(key, {}), hv.get(key, {})
            writers = set(old.get('writes', [])) | set(new.get('writes', []))
            if 'DIRECT_CHANGED' in reasons[key] or any(('function', f) in seen for f in writers):
                pending.extend(('function', f) for f in readers[key])
            for v in (old, new):
                for sibling in root_vars[v.get('root')]:
                    if sibling != key:
                        other = hv.get(sibling) or bv.get(sibling)
                        if other.get('container'):
                            # A UI aggregation node must not bridge otherwise
                            # disjoint physical fields back to every sibling.
                            continue
                        # Concrete non-overlapping fields keep field precision.
                        a, b = v.get('offset_bits'), other.get('offset_bits')
                        sa, sb = v.get('size_bytes'), other.get('size_bytes')
                        if (all(type(n) is int and n >= 0 for n in (a, b, sa, sb))
                                and not (set(v.get('overlap_groups', [])) & set(other.get('overlap_groups', [])))
                                and (a + 8*sa <= b or b + 8*sb <= a)):
                            continue
                        reasons[sibling].add('CANNOT_EXCLUDE_IMPACT')
                        pending.append(('variable', sibling))
    fallback = []
    if base['semantics'] != head['semantics']:
        fallback.append('执行入口、保护、NVIC、DMA 或别名全局语义变化')
    # The current analyser has conservative gaps, not complete interprocedural
    # dependency proofs. With changed semantics an unresolved boundary expands
    # to the whole build; full analysis still retains UNKNOWN classifications.
    if (modified or reasons) and (base['unknowns'] or head['unknowns']):
        fallback.append('存在未解析依赖，无法证明局部影响边界')
    dependencies = set(base.get('dependencies', [])) | set(head.get('dependencies', []))
    prefix = pinned.get('project_subdir', '.')
    build_changed = base.get('build') != head.get('build') or base.get('macros') != head.get('macros') or any(
        Path(f['new_path']).suffix.lower() in ('.h', '.hh', '.hpp', '.hxx', '.inc', '.cmake', '.ld', '.lds', '.s', '.a', '.o', '.obj', '.mk', '.sct', '.icf')
        or Path(f['new_path']).name in ('CMakeLists.txt', 'CMakePresets.json', 'CMakeUserPresets.json', 'compile_commands.json', 'Makefile')
        or (Path(f['new_path']).suffix.lower() not in ('.c', '.cc', '.cpp', '.cxx')
            and Path(os.path.relpath(f['new_path'], prefix)).as_posix() in dependencies) for f in pinned['files'] if not f.get('comment_only'))
    if build_changed:
        fallback.append('头文件或构建输入变化，重新评估完整构建范围')
    if fallback:
        for sid in bv.keys() | hv.keys():
            reasons[sid].add('BUILD_SEMANTICS_CHANGED' if build_changed else 'CANNOT_EXCLUDE_IMPACT')
    from functools import lru_cache
    impacts, deleted = {}, []
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
        comparison_status, comparison_note = risk_comparison(old, new)
        risk = ('无法判断变化结果' if comparison_status != 'COMPARABLE'
            else '新增疑似风险' if old_class != 'SUSPECT' and new_class == 'SUSPECT'
            else '风险可能已消除' if old_class == 'SUSPECT' and new_class != 'SUSPECT'
            else '风险证据发生变化' if old['dimensions'] != new['dimensions']
            else '已有风险受到修改影响' if new_class == 'SUSPECT' else '当前静态结论未变化')
        impact = dict(selected=True, reasons=sorted(why), reason_labels=[REASONS[r] for r in sorted(why)],
            added_edges=[list(e) for e in sorted(new_edges-old_edges)], removed_edges=[list(e) for e in sorted(old_edges-new_edges)],
            unchanged_edges_count=len(old_edges & new_edges), impact_coverage='CONSERVATIVE' if fallback else 'COMPLETE',
            risk_change=risk, risk_comparison_status=comparison_status, risk_comparison_note=comparison_note,
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
            deleted.append(dict(symbol_id=old['symbol_id'], name=old['name'], impact=impact))
    return dict(pin=pinned, selected_symbol_ids=sorted(impacts), impacts=impacts, deleted_variables=deleted,
        modified_function_ids=sorted(modified), fallback_level='L1' if fallback else 'L0', fallback_reasons=fallback,
        impact_coverage='CONSERVATIVE' if fallback else 'COMPLETE',
        note='仅回答本次修改的影响；范围之外不代表安全。完整并发分析保留未修改路径。')


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
    result['presentation_notice'] = '当前差异范围：仅展示受影响变量；覆盖与依赖证据保留完整构建范围，未列出不代表安全。'
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


def prepare_base(root, out, cfg, pinned, progress, cache_stats=None):
    """Persistent detached worktree: no checkout/reset/clean in user workspace."""
    from .cli import run
    from .workflow import read_saved_json, file_digest, checked_scan, engine_digest, clean_report, saved_report_digest
    repo = Path(pinned['repository_root'])
    directory = out/'git_diff'/('base-' + pinned['base_sha'])
    if not directory.exists():
        directory.parent.mkdir(parents=True, exist_ok=True)
        git(repo, 'worktree', 'add', '--detach', str(directory), pinned['base_sha'])
    if text(directory, 'rev-parse', 'HEAD') != pinned['base_sha']:
        raise ValueError('基准工作树身份不一致；禁止复用')
    pinned['base_gitdir_reference'] = _relative_worktree_gitdir(repo, directory, pinned['base_sha'])
    base_root = directory/pinned['project_subdir']
    baseline = copy.deepcopy(cfg)
    baseline['analysis']['git_diff']['enabled'] = False
    baseline['review']['enabled'] = False
    baseline['review']['prepare_packets'] = False
    baseline['analysis']['open_report'] = False
    baseline['analysis']['output_dir'] = '.ecra-diff-base'
    # Absolute in-project config paths are remapped. External toolchains remain
    # explicit inputs and are checked by the ordinary snapshot mechanism.
    def relocate(value):
        if isinstance(value, dict):
            return {k: relocate(v) for k, v in value.items()}
        if isinstance(value, list):
            return [relocate(v) for v in value]
        return value.replace(str(root), str(base_root)).replace(root.as_posix(), base_root.as_posix()) if isinstance(value, str) else value
    baseline = relocate(baseline)
    baseline['project']['root'] = str(base_root)
    allowed_database = None
    if 'cmake' not in baseline['analysis']:
        allowed_database = (base_root/baseline['analysis'].get('compile_database', 'auto')).relative_to(directory).as_posix()
    modified_paths = git(directory, 'diff', 'HEAD', '--name-only', '-z').split(b'\0')
    if any(p and p.decode('utf-8') != allowed_database for p in modified_paths):
        raise ValueError('隔离基准源码已被修改；拒绝使用污染的基准事实')
    if 'cmake' not in baseline['analysis']:
        db = baseline['analysis'].get('compile_database', 'auto')
        if db == 'auto':
            raise ValueError('差异基准非 CMake 工程必须显式配置版本内的 compile_database')
        database = base_root/db
        if not database.is_file():
            raise ValueError('基准版本缺少编译数据库；请使用隔离 CMake 构建或提交可重定位的真实数据库')
        # Never copy the HEAD database/build products into the baseline.
        relative_db = database.relative_to(directory).as_posix()
        import json
        entries = relocate(json.loads(git(repo, 'show', pinned['base_sha'] + ':' + relative_db)))
        write_json(database, entries)
    config = out/'git_diff/base-semantics.yaml'
    write_json(config, baseline)
    progress('建立基准版本完整事实：' + pinned['base_sha'])
    base_out = base_root/'.ecra-diff-base'
    base_report = None
    if cfg['analysis']['git_diff']['cache_enabled']:
        from .config import load_config
        try:
            validated, _ = load_config(base_root, config)
            _, base_report, _ = checked_scan(base_root, base_out, validated, config, with_facts=False)
            progress('基准完整事实缓存通过源码、预处理闭包和引擎校验。')
        except (ValueError, OSError, KeyError, TypeError):
            pass
    if base_report is None:
        code = run(base_root, str(config), no_review=True, _cache_enabled=cfg['analysis']['git_diff']['cache_enabled'])
        if code == 3 or not read_json(base_out/'result_validity.json').get('analysis_valid'):
            raise ValueError('基准版本分析失败，差异扫描未完成；详见 ' + str(base_out))
        base_report = read_saved_json(base_out/'reports/global_static_concurrency.json')
    prefix = pinned['project_subdir'].rstrip('/')
    def local(path):
        return Path(os.path.relpath(path, prefix)).as_posix() if prefix and prefix != '.' and path else path
    renames = {local(f['old_path']): local(f['new_path']) for f in pinned['files'] if f['status'].startswith('R')}
    sha = file_digest(base_out/'facts.json')
    key = digest(dict(schema=SUMMARY_SCHEMA, engine=engine_digest(), facts=sha,
                      report=saved_report_digest(clean_report(base_report), encoding='ECRA_MERKLE_V1'), renames=renames))
    summary_file = out/'git_diff/summary-cache'/(key + '.summary.json')
    manifest_file = summary_file.with_suffix('.manifest.json')
    reused, corrupt = False, False
    if cfg['analysis']['git_diff']['cache_enabled']:
        try:
            manifest = read_json(manifest_file)
            if (not isinstance(manifest, dict) or manifest.get('key') != key or manifest.get('schema') != SUMMARY_SCHEMA
                    or manifest.get('complete_tus') is not True
                    or manifest.get('sha256') != file_digest(summary_file)):
                raise ValueError('基准摘要缓存内容不一致')
            reused = True
            progress('基准规范化证据摘要通过内容校验，复用已验证的完整摘要。')
        except FileNotFoundError:
            pass
        except (ValueError, KeyError, TypeError, OSError):
            corrupt = True
    if not reused:
        base_facts = read_saved_json(base_out/'facts.json', canonical_accesses=True)
        units = base_facts.get('translation_units', [])
        if not units or any(u.get('parse_status') != 'PARSED' for u in units):
            raise ValueError('基准版本存在解析失败/部分解析，不能将缺失事实当作无变化')
        summary = summarize(base_facts, base_report, renames)
        write_json(summary_file, summary, indent=None)
        write_json(manifest_file, dict(schema=SUMMARY_SCHEMA, key=key, complete_tus=True, sha256=file_digest(summary_file)))
        del base_facts, summary
    pinned['base_summary_path'] = str(summary_file)
    pinned['base_summary_sha256'] = file_digest(summary_file)
    if cache_stats is not None:
        cache_stats.update(hit=reused, corrupt=corrupt)
    pinned['base_source_root'] = str(base_root)
    pinned['base_database_path'] = allowed_database
    evidence = out/'git_diff/evidence'/sha
    evidence.mkdir(parents=True, exist_ok=True)
    immutable = evidence/'facts.json'
    if not immutable.exists():
        import shutil
        try:
            os.link(base_out/'facts.json', immutable)
        except OSError:
            temp = immutable.with_suffix('.pending')
            shutil.copyfile(base_out/'facts.json', temp)
            from .common import replace_file
            replace_file(temp, immutable)
    if file_digest(immutable) != sha:
        raise ValueError('不可变基准证据归档损坏；禁止发布')
    pinned['base_facts_path'] = str(immutable)
    pinned['base_facts_sha256'] = sha
    patch = out/'git_diff'/(digest({k: v for k, v in pinned.items() if not k.startswith('base_facts')}) + '.patch')
    write_comparison_patch(pinned, patch)
    pinned['diff_patch_path'] = str(patch)
    pinned['diff_patch_sha256'] = file_digest(patch)
    return summary_file


def verify_full(root, out, cfg, units, coverage, facts, report, worker_dir, env, tool_root, source_reader):
    """Independent uncached extraction and full analysis, compared per dimension."""
    from .cli import extraction_responses, add_build_unknowns
    from .fact_parts import FactParts
    from .analysis import merge, analyze
    from .input_snapshot import SOURCE_READS
    snapshot = SOURCE_READS.get()
    parts = FactParts()
    verification_units = []
    check_dir = worker_dir/'full-verification'
    check_dir.mkdir(exist_ok=True)
    for unit, response, metadata in extraction_responses(root, units, cfg, check_dir, env, tool_root, out):
        meta = read_json(metadata)
        if meta.get('parse_status') != 'PARSED':
            raise ValueError('全量对照提取不完整，禁止报告验证通过')
        snapshot.observe(unit, meta['input_snapshot'], signature=meta.get('preprocessor_signature'))
        parts.append_metadata(response, meta)
        verification_units.append(dict(unit, semantic_macros_digest=meta.get('semantic_macros_digest'),
                                       includes=meta.get('includes', []), parse_status=meta['parse_status']))
    snapshot.assert_valid()
    full_facts = merge(parts)
    full_facts['translation_units'] = verification_units
    full_cfg = copy.deepcopy(cfg)
    full_cfg['analysis']['git_diff']['enabled'] = False
    if not cfg['analysis'].get('build_closure_only', True):
        raise ValueError('当前独立全量对照要求 build_closure_only: true；补充分支盘点尚不支持独立对照')
    add_build_unknowns(full_facts, full_cfg, units, coverage)
    full_report = analyze(full_facts, full_cfg, copy.deepcopy(coverage), root=root, source_reader=source_reader)
    expected, actual = summarize(facts, report), summarize(full_facts, full_report)
    if expected != actual:
        write_json(out/'diagnostics/git-diff-verification-failed.json', dict(expected=expected, actual=actual), indent=None)
        raise ValueError('增量与独立全量的语义事实不一致，已阻止发布')
    return dict(state='PASSED', variables=len(actual['variables']), reextracted_units=len(units),
                classification_mismatches=0, semantic_mismatches=0)
