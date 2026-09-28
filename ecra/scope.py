"""Select audit ownership without cutting dependency call/alias propagation."""
from collections import Counter, defaultdict
from fnmatch import fnmatch
import os
from pathlib import Path


class AuditScope:
    def __init__(self, root, analysis):
        self.root = Path(root).resolve()
        self.include_dirs = analysis.get('include_dirs', [])
        self.exclude_dirs = analysis.get('exclude_dirs', [])
        self.exclude_files = analysis.get('exclude_files', [])
        self.legacy_exclude = analysis.get('exclude', [])
        # build_closure: 以编译数据库实际参与的 TU 为排查闭包（Section 13）。
        # 未参与当前 target 构建的源码只作为调用链依赖，不进入盘点，也不构
        # 成任何变量的覆盖缺口。
        self.build_closure = analysis.get('audit_mode') == 'build_closure'
        self.closure_sources = set()
        self.includes = [self.path(p) for p in self.include_dirs]
        self.excludes = [self.path(p) for p in self.exclude_dirs]
        self.files = [self.path(p) for p in self.exclude_files]
        self.active = bool(self.includes or self.excludes or self.files or self.legacy_exclude)
        for folder in self.includes:
            if not folder.is_dir():
                raise ValueError(f'排查目录不存在或不是目录: {folder}；请检查 analysis.include_dirs')
        for folder in self.excludes:
            if folder.is_file():
                raise ValueError(f'exclude_dirs 中填写了文件: {folder}；请改放到 analysis.exclude_files')
        for file in self.files:
            if file.is_dir():
                raise ValueError(f'exclude_files 中填写了目录: {file}；请改放到 analysis.exclude_dirs')

    def path(self, path):
        return (self.root / str(path).replace('\\', '/')).resolve()

    def set_closure_sources(self, sources):
        self.closure_sources = {str(s).replace('\\', '/') for s in sources}

    def file_selected(self, relative_path):
        """File-level audit selection for discovery/supplemental walks."""
        if not self.build_closure:
            return True
        return str(relative_path).replace('\\', '/') in self.closure_sources

    def contains(self, path):
        if not path:
            return False
        p = self.path(path)
        return (not self.includes or any(p.is_relative_to(d) for d in self.includes)) and not self.exclusion(path)

    def exclusion(self, path):
        if not path:
            return None
        p = self.path(path)
        for raw, folder in zip(self.exclude_dirs, self.excludes):
            if p.is_relative_to(folder):
                return 'exclude_dirs: ' + raw
        for raw, file in zip(self.exclude_files, self.files):
            if p == file:
                return 'exclude_files: ' + raw
        # Legacy exclusions must also apply to headers reached via includes,
        # not just to compilation-database entries and unlisted-file checks.
        for raw in self.legacy_exclude:
            pattern = raw.replace('\\', '/')
            if not any(c in pattern for c in '*?['):
                if p.is_relative_to(self.path(pattern)):
                    return 'exclude: ' + raw
            else:
                relative = p.relative_to(self.root).as_posix() if p.is_relative_to(self.root) else p.as_posix()
                if fnmatch(os.path.normcase(relative), os.path.normcase(pattern)) or fnmatch(
                        os.path.normcase(p.as_posix()), os.path.normcase(self.path(pattern).as_posix())):
                    return 'exclude: ' + raw
        return None

    def variable(self, variable):
        # The definition owns an extern symbol; a declaration in a user header
        # must not bring a vendor-owned definition back into the audit.
        return self.variable_reason(variable) is None

    def variable_reason(self, variable):
        definitions = {d['file'] for d in variable.get('definitions', []) if d.get('file')}
        if variable.get('definition_file'):
            definitions.add(variable['definition_file'])
        paths = definitions or {d['file'] for d in variable.get('declarations', []) if d.get('file')}
        # An included extern declaration cannot override an excluded definition.
        # When definition ownership is unresolved, excluded declarations also win.
        for path in sorted(paths):
            reason = self.exclusion(path)
            if reason:
                return reason
        if not paths or not all(self.contains(path) for path in paths):
            return '不在 include_dirs 内或归属未确定'
        return None

    def walk_roots(self):
        roots = [self.root]
        for folder in sorted(self.includes, key=lambda p: len(p.parts)):
            if not any(folder.is_relative_to(r) for r in roots):
                roots.append(folder)
        return roots


def validate_selection(facts, report):
    """Fail closed at export if any excluded object re-enters a derived view."""
    cov = report.get('coverage', {})
    policy = cov.get('audit_scope')
    if not policy or not cov.get('project_root'):
        return
    scope = AuditScope(cov['project_root'], policy)
    variables = {v['symbol_id']: v for v in facts['variables']}
    leaks = [sid for sid, v in variables.items() if not scope.variable(v)]
    leaks += [f['finding_id'] for f in report['findings'] if f.get('symbol_id') and (
        f['symbol_id'] not in variables or (f.get('definition', {}).get('file') and not scope.contains(f['definition']['file'])))]
    if leaks:
        raise ValueError('过滤完整性校验失败：范围外变量进入输出，已阻止生成报告；请重新扫描。' + ', '.join(leaks))


def select_facts(facts, scope, coverage):
    """Run AFTER pointer solving and context discovery, BEFORE risk generation.

    Keep every access to selected objects, including writes made by libraries.
    Keep dependency uncertainties on their incoming call paths and all parse
    failures; an excluded dependency failing to parse is not a safety proof.
    """
    if not scope.active:
        return
    all_variables = facts['variables']
    selected = [v for v in all_variables if scope.variable(v)]
    excluded_counts = Counter((v.get('definition_file') or next((d.get('file') for d in v.get('declarations', []) if d.get('file')), '归属未知'),
                               scope.variable_reason(v)) for v in all_variables if not scope.variable(v))
    ids = {v['symbol_id'] for v in selected}
    accesses = [a for a in facts['accesses'] if a['symbol_id'] in ids]
    relevant = {a['function_id'] for a in accesses}
    incoming = defaultdict(set)
    for call in facts['calls']:
        incoming[call['callee_function_id']].add(call['caller_function_id'])
    pending = list(relevant)
    while pending:
        for caller in incoming[pending.pop()]:
            if caller not in relevant:
                relevant.add(caller)
                pending.append(caller)
    kept, omitted = [], []
    for issue in facts['unknowns']:
        if issue.get('symbol_id'):
            keep = issue['symbol_id'] in ids
        elif issue.get('files'):
            issue = dict(issue, files=[f for f in issue['files'] if scope.contains(f)])
            keep = bool(issue['files'])
        elif issue.get('kind') == 'PARSE_FAILED':
            keep = True
        elif not issue.get('file'):
            # Global solver limits, input changes and invalid declarations
            # cannot be dismissed using a directory filter.
            keep = True
        else:
            keep = scope.contains(issue['file']) or (issue.get('function_id') in relevant
                    or issue.get('target_function_id') in relevant)
        (kept if keep else omitted).append(issue)
    facts['variables'] = selected
    facts['accesses'] = accesses
    facts['snapshots'] = [s for s in facts['snapshots'] if s['symbol_id'] in ids]
    facts['unknowns'] = kept
    coverage['audit_scope'] = dict(include_dirs=scope.include_dirs, exclude_dirs=scope.exclude_dirs,
        exclude_files=scope.exclude_files, exclude=scope.legacy_exclude,
        variables_discovered=len(all_variables), variables_selected=len(selected),
        variables_omitted=len(all_variables)-len(selected),
        excluded_files=[dict(file=file, reason=reason, variables=count) for (file, reason), count in sorted(excluded_counts.items())],
        excluded_variable_leaks=sum(not scope.variable(v) for v in facts['variables']),
        omitted_unknowns_by_kind=dict(sorted(Counter(u['kind'] for u in omitted).items())),
        dependency_policy='依赖保留调用链及对目标变量的访问；不排查依赖自身变量。')
    if not selected:
        facts['unknowns'].append(dict(kind='EMPTY_AUDIT_SCOPE',
            hint='当前编译配置未发现排查目录中的变量；核对 include_dirs/exclude_dirs、源码及条件编译。'))
