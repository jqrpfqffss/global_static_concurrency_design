"""Declaration-only coverage outside the active build; never adds access evidence."""
import copy
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

from .common import digest, execute, read_json, relative, write_json

SOURCE_EXTENSIONS = {'.c', '.cc', '.cpp', '.cxx', '.h', '.hh', '.hpp', '.hxx', '.inc'}
CPP_EXTENSIONS = {'.cc', '.cpp', '.cxx', '.hh', '.hpp', '.hxx'}


def selected_files(root, scope, output):
    result = set()
    output = Path(output).resolve()
    for tree in scope.walk_roots():
        for base, dirs, names in os.walk(tree):
            dirs[:] = [d for d in dirs if d not in {'.git', '__pycache__', 'node_modules'}
                       and not (Path(base) / d).resolve().is_relative_to(output)]
            for name in names:
                path = Path(base) / name
                if path.suffix.lower() in SOURCE_EXTENSIONS and scope.contains(path) and scope.file_selected(relative(path, root)):
                    result.add(relative(path, root))
    return sorted(result)


def units_by_file(units, root):
    """Normalize each include once; shared headers otherwise cause F*T*H work."""
    result = defaultdict(list)
    for unit in units:
        for file in {unit['source_file'], *(relative(p, root) for p in unit.get('includes', []))}:
            result[file].append(unit)
    return result


def _run_extractor(root, unit, cfg, worker_dir, env, tool_root, timeout, coverage_source, source_overrides=None):
    request = dict(root=str(root), unit=unit, config=cfg, coverage_source=coverage_source,
                   declaration_only=True, source_overrides=source_overrides or {})
    key = digest([unit, coverage_source, source_overrides])[:24]
    req, resp = worker_dir / (key + '.request.json'), worker_dir / (key + '.response.json')
    write_json(req, request)
    resp.unlink(missing_ok=True)
    try:
        proc = execute([sys.executable, '-m', 'ecra.extract', str(req), str(resp)],
                       cwd=tool_root, env=env, timeout=timeout)
        if proc.returncode or not resp.is_file():
            raise ValueError(f'提取器退出 {proc.returncode}: {proc.stderr[-2000:]}')
        part = read_json(resp)
    except Exception as exc:
        part = dict(parse_status='FAILED', diagnostics=[dict(severity=4, message=str(exc))], variables=[], includes=[])
    return part


def _clean_lines(lines):
    # Preserve strings and physical newlines while removing comments. Only
    # directive structure is recognized here; Clang parses every declaration.
    text = '\n'.join(lines)
    pattern = r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|/\*[\s\S]*?\*/|//[^\n]*'
    def strip(match):
        value = match.group()
        return re.sub(r'[^\n]', ' ', value) if value.startswith(('/',)) else value
    return re.sub(pattern, strip, text).splitlines()


def _directives(lines):
    clean = _clean_lines(lines)
    i = 0
    while i < len(clean):
        start = i
        logical = clean[i]
        while logical.rstrip().endswith('\\') and i + 1 < len(clean):
            logical = logical.rstrip()[:-1] + clean[i + 1]
            i += 1
        match = re.match(r'^\s*#\s*(\w+)\b(.*)', logical)
        if match:
            yield start + 1, i + 1, match[1], match[2].strip()
        i += 1


class ConditionalGroup:
    def __init__(self, open_line, close_line=0, parent=None):
        self.open_line, self.close_line, self.parent = open_line, close_line, parent
        self.branches = []
        self.directive_ends = {}
        self.guard = False


def _track_conditionals(lines):
    groups, stack = [], []
    directives = list(_directives(lines))
    for start, end, cmd, expression in directives:
        if cmd in ('if', 'ifdef', 'ifndef'):
            parent = (stack[-1][0], stack[-1][1]) if stack else None
            group = ConditionalGroup(start, parent=parent)
            group.directive_ends[start] = end
            groups.append(group)
            stack.append((group, start, cmd))
        elif cmd in ('elif', 'else') and stack:
            group, previous, dtype = stack[-1]
            group.branches.append((previous, start - 1, dtype))
            group.directive_ends[start] = end
            stack[-1] = (group, start, cmd)
        elif cmd == 'endif' and stack:
            group, previous, dtype = stack.pop()
            group.branches.append((previous, start - 1, dtype))
            group.close_line = start
    if stack:
        raise ValueError('未闭合的条件编译指令')
    # Do not force include guards open on repeated inclusion.
    for group in groups:
        if group.parent is None and len(group.branches) == 1:
            following = [d for d in directives if d[0] >= group.open_line][:2]
            if len(following) == 2 and following[0][2] == 'ifndef' and following[1][2] == 'define':
                group.guard = following[0][3] == following[1][3].split()[0]
    return groups


def _find_inactive_branches(groups, active_lines=None):
    # Enumerate every arm; AST absence is not a reliable preprocessor predicate.
    return [(g, *branch) for g in groups if not g.guard for branch in g.branches]


def _create_variant(lines, group, branch_start, branch_end=None, dtype=None):
    variant = list(lines)
    while group is not None:
        if not group.guard:
            for index, (start, _, kind) in enumerate(group.branches):
                if kind == 'else':
                    continue
                replacement = ('#if ' if index == 0 else '#elif ') + ('1' if start == branch_start else '0')
                variant[start - 1] = replacement.ljust(len(lines[start - 1]))
                for continuation in range(start, group.directive_ends[start]):
                    variant[continuation] = ' ' * len(lines[continuation])
        if group.parent is None:
            break
        group, branch_start = group.parent
    return '\n'.join(variant) + '\n'


def _locations(v):
    return v.get('declarations', []) + v.get('definitions', [])


def _owned(v, file, start=None, end=None):
    return any(d.get('file') == file and (start is None or start < d.get('line', 0) <= end)
               for d in _locations(v))


def _synthetic_unit(root, file, template):
    args = list(template.get('arguments', []))
    suffix = Path(file).suffix.lower()
    template_cpp = Path(template.get('source', '')).suffix.lower() in CPP_EXTENSIONS or any('c++' in a for a in args)
    cpp = suffix in CPP_EXTENSIONS or (suffix in {'.h', '.inc'} and template_cpp)
    clean = []
    skip = False
    for arg in args:
        if skip:
            skip = False
            continue
        if arg == '-x':
            skip = True
        elif not arg.startswith('-x') and not arg.startswith('-std='):
            clean.append(arg)
    standard = next((a for a in args if a.startswith('-std=') and ('++' in a) == cpp),
                    '-std=c++17' if cpp else '-std=c11')
    return dict(source_file=file, source=str((root / file).resolve()),
                directory=template.get('directory', str(root)),
                arguments=clean + ['-x', 'c++' if cpp else 'c', standard],
                tu_id='SUP-' + digest(file)[:16], missing_defines=[], response_files=[], audit_role='target')


def find_inactive_branch_declarations(root, source_file, source_text, arguments, cfg,
                                      worker_dir, env, tool_root, timeout, progress, unit=None, dependencies=None):
    lines = source_text.splitlines()
    try:
        groups = _track_conditionals(lines)
    except ValueError as exc:
        return [], [dict(kind='INACTIVE_BRANCH_PARSE_FAILED', file=source_file, message=str(exc))]
    if not groups:
        return [], []
    unit = unit or _synthetic_unit(root, source_file, dict(arguments=arguments, directory=str(root)))
    variables, failures = [], []
    directive_lines = {line for start, end, _, _ in _directives(lines) for line in range(start, end + 1)}
    code_lines = {i for i, line in enumerate(_clean_lines(lines), 1) if line.strip() and i not in directive_lines}
    # A macro defined here can introduce declarations at a later invocation.
    code_lines.update(start for start, _, cmd, _ in _directives(lines) if cmd in {'define', 'undef'})
    arms = [(g, start, end, dtype) for g, start, end, dtype in _find_inactive_branches(groups)
            if any(start < line <= end and not any(child.open_line <= line <= child.close_line
                   for child in groups if child.parent and child.parent[0] is g)
                   for line in code_lines)]
    if arms:
        progress(f'条件声明盘点：{source_file}，{len(arms)} 个分支（{unit["source_file"]}）')
    for group, start, end, dtype in arms:
        variant = _create_variant(lines, group, start, end, dtype)
        part = _run_extractor(root, unit, cfg, worker_dir, env, tool_root, timeout,
                              'inactive_branch', {str((root / source_file).resolve()): variant})
        if dependencies is not None:
            dependencies.update(part.get('includes', []))
        # Keep partial AST AND failures, never unrelated headers at the same line.
        found = [v for v in part.get('variables', []) if _owned(v, source_file)]
        for v in found:
            v['branch_range'] = dict(file=source_file, start=start, end=end)
        variables.extend(found)
        if part.get('parse_status') != 'PARSED':
            failures.append(dict(kind='INACTIVE_BRANCH_PARSE_FAILED', file=source_file,
                                 range=f'{start}-{end}', translation_unit=unit['source_file'],
                                 diagnostics=part.get('diagnostics', []),
                                 message='分支变体解析不完整；已保留可恢复声明，仍可能漏项'))
    return variables, failures


def merge_supplemental_variables(facts, supplemental_vars):
    """Compiled storage ownership wins; all other declaration sites remain auditable."""
    by_sid = {v['symbol_id']: v for v in facts['variables']}
    def keys(v):
        instance = tuple(v.get('translation_units', [])) if v['kind'] in {'FILE_STATIC', 'LOCAL_STATIC'} else ()
        return [(d.get('file'), d.get('line'), d.get('column'), v['name'], v['kind'], instance)
                for d in _locations(v)]
    seen = {k for v in facts['variables'] for k in keys(v)}
    for original in supplemental_vars:
        v = copy.deepcopy(original)
        if keys(v) and all(k in seen for k in keys(v)):
            continue
        sid = v['symbol_id']
        if sid in by_sid:
            old = by_sid[sid]
            # Different static/local declaration sites can share Clang's ordinal
            # across mutually exclusive variants. They must not be merged.
            if v['kind'] in {'GLOBAL'}:
                for d in v.get('declarations', []):
                    marked = dict(d, provenance=v.get('coverage_source', 'supplemental'))
                    if not any(all(existing.get(k) == d.get(k) for k in ('file','line','column')) for existing in old['declarations']):
                        old['declarations'].append(marked)
                receipt = {k: v.get(k) for k in ('type','definitions','declarations','coverage_source','parse_status','branch_range')}
                if receipt not in old.setdefault('supplemental_declarations', []):
                    old['supplemental_declarations'].append(receipt)
                seen.update(keys(v))
                continue
            sid = 'decl::' + digest(keys(v))[:24]
            v['symbol_id'] = sid
        if sid not in by_sid:
            facts['variables'].append(v)
            by_sid[sid] = v
        seen.update(keys(v))
    facts['variables'].sort(key=lambda v: v['symbol_id'])


def supplement(root, out, facts, units, cfg, scope, worker_dir, env, tool_root, progress):
    """Visit all selected files in their real TU context, or explicit fallback context."""
    files = selected_files(root, scope, out)
    timeout = float(cfg['analysis'].get('parse_timeout_seconds', 180))
    template = next((u for u in units if scope.contains(u['source_file'])), units[0])
    supplemental_units, failures, variables, includes = [], [], [], set()
    indexed_units = units_by_file(units, root)
    for file in files:
        contexts = indexed_units.get(file, [])
        if not contexts:
            progress('补充声明盘点：' + file)
            fallback = _synthetic_unit(root, file, template)
            part = _run_extractor(root, fallback, cfg, worker_dir, env, tool_root, timeout, 'supplemental')
            fallback.update(parse_status=part['parse_status'], diagnostics=part.get('diagnostics', []),
                            includes=part.get('includes', []), coverage_source='supplemental')
            includes.update(fallback['includes'])
            supplemental_units.append(fallback)
            variables.extend(v for v in part.get('variables', []) if _owned(v, file))
            if part['parse_status'] != 'PARSED':
                failures.append(dict(kind='SUPPLEMENTAL_PARSE_FAILED', file=file, diagnostics=fallback['diagnostics']))
            contexts = [fallback]
        try:
            source = (root / file).read_text(encoding='utf-8', errors='strict')
        except (OSError, UnicodeError) as exc:
            failures.append(dict(kind='INVENTORY_SOURCE_UNREADABLE', file=file, message=str(exc)))
            continue
        for unit in contexts:
            extra, gaps = find_inactive_branch_declarations(root, file, source, unit['arguments'], cfg,
                worker_dir, env, tool_root, timeout, progress, unit=unit, dependencies=includes)
            variables.extend(extra)
            failures.extend(gaps)
    merge_supplemental_variables(facts, variables)
    facts['unknowns'].extend(failures)
    return supplemental_units, includes


def build_file_coverage(facts, units, supplemental_tus, scope, root, output_dir=None):
    rows = []
    indexed_units = units_by_file(units, root)
    fallbacks, variables, issues = defaultdict(list), defaultdict(list), defaultdict(list)
    for u in supplemental_tus:
        fallbacks[u['source_file']].append(u)
    for v in facts['variables']:
        if scope.variable(v):
            for file in {d.get('file') for d in _locations(v)}:
                variables[file].append(v)
    for u in facts.get('unknowns', []):
        if u.get('kind') in {'INACTIVE_BRANCH_PARSE_FAILED','SUPPLEMENTAL_PARSE_FAILED','INVENTORY_SOURCE_UNREADABLE'}:
            issues[u.get('file')].append(u)
    for file in selected_files(root, scope, output_dir or root / '.ecra'):
        contexts = indexed_units.get(file, [])
        fallback = fallbacks[file]
        related = contexts or fallback
        states = {u.get('parse_status', 'FAILED') for u in related}
        gaps = issues[file]
        status = ('NOT_COMPILED' if not related else 'PARSED' if states == {'PARSED'} else
                  'FAILED' if states == {'FAILED'} else 'PARTIAL')
        if gaps:
            status = 'PARTIAL'
        owned = variables[file]
        rows.append(dict(file=file, variable_count=len(owned), parse_status=status,
                         symbol_ids=sorted(v['symbol_id'] for v in owned),
                         coverage_source='compile_database' if contexts else 'supplemental',
                         translation_units=[u['source_file'] for u in related],
                         diagnostics=[d for u in related for d in u.get('diagnostics', [])], gaps=gaps))
    return rows
