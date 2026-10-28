"""Independent, project-scoped human audit ledger. Never changes static facts."""
import json
import sqlite3
from collections import defaultdict
from contextlib import closing
from datetime import datetime, timezone

from .common import digest, read_json

LABELS = {'UNCONFIRMED': '待人工确认', 'CONFIRMED_RISK': '人工确认有风险',
          'CONFIRMED_SAFE': '人工确认无风险', 'NEEDS_RECHECK': '需重新确认'}
CONFIRMED = {'CONFIRMED_RISK', 'CONFIRMED_SAFE'}
CONTAINERS = {'STRUCT_CONTAINER', 'STRUCT_MEMBER_CONTAINER', 'ARRAY_CONTAINER', 'NON_STORAGE'}


class Conflict(ValueError):
    """The browser must reload before retrying a stale operation."""


def targets(facts, report):
    ids = {f.get('symbol_id') for f in report.get('findings', [])
           if not f.get('review_safe_sample') and not f.get('review_screened_sample')}
    return [v for v in facts.get('variables', [])
            if v.get('symbol_id') and v.get('resource_kind') not in CONTAINERS
            and v.get('static_classification') not in {'NON_STORAGE', 'SAFE_PROVEN', 'SHARED_NO_REVIEW'}
            and v.get('coverage_source') not in {'supplemental', 'inactive_branch'}
            and (v['symbol_id'] in ids or v.get('static_classification') in {'SUSPECT', 'UNKNOWN'})]


# Locations are display information, not storage identity. Executable order is
# retained in source fragments; unordered fact collections are canonicalized.
VOLATILE = {'line', 'column', 'offset', 'end_line', 'end_offset', 'definition_line', 'access_id',
            'finding_id', 'generated_at', 'timestamp', 'confirmed_at', 'updated_at',
            'scan_fingerprint', 'cache_key', 'attempts', 'duration_seconds',
            'review', 'review_state', 'review_status', 'review_result',
            'effective_decision', 'decision_label', 'status'}
UNORDERED = {'accesses', 'declarations', 'definitions', 'translation_units',
             'contexts', 'readers', 'writers', 'function_ids', 'symbol_ids',
             'screening_blockers', 'unknown_reason_codes', 'coverage_reasons',
             'concurrency_relations', 'conflict_pairs', 'protection_events'}


def canonical(value, root):
    if isinstance(value, dict):
        result = {k: canonical(v, root) for k, v in sorted(value.items()) if k not in VOLATILE}
        for key in UNORDERED & result.keys():
            if isinstance(result[key], list):
                result[key] = sorted(result[key], key=lambda r: json.dumps(r, sort_keys=True))
        return result
    if isinstance(value, list):
        return [canonical(v, root) for v in value]
    if isinstance(value, str):
        return value.replace(str(root), '$PROJECT').replace(root.as_posix(), '$PROJECT')
    return value


def unordered(rows, root):
    return sorted((canonical(r, root) for r in rows), key=lambda r: json.dumps(r, sort_keys=True))


def source_evidence(root, facts, related, manifest):
    """Keep declarations/directives and related function bodies.

    A fresh scan detects new accesses/call edges in previously unrelated bodies.
    Unknown/overlapping function extents fall back to the entire file hash.
    Headers and other build inputs are deliberately conservative.
    """
    functions = {}
    for f in facts.get('functions', []):
        functions.setdefault(f.get('file'), []).append(f)
    result = {}
    for name, sha in sorted(manifest.items()):
        if name not in functions:
            result[name] = sha
            continue
        try:
            source = (root / name).read_bytes()
            spans = sorted(functions[name], key=lambda f: f.get('offset', 0))
            end = 0
            chunks = []
            for f in spans:
                start, stop = f['offset'], f['end_offset']
                if not (end <= start < stop <= len(source)):
                    raise ValueError('ambiguous function extent')
                chunks.append(source[end:start])
                if f['function_id'] in related:
                    chunks.append(source[start:stop])
                else:
                    # Preserve the function identity; line movement is harmless.
                    chunks.append(('/* excluded body ' + f['function_id'] + ' */\n').encode())
                end = stop
            chunks.append(source[end:])
            import hashlib
            # A directive inside an otherwise unrelated body may change macros
            # used by later functions. Preserve logical preprocessor lines.
            logical_lines = source.replace(b'\\\r\n', b'').replace(b'\\\n', b'').splitlines()
            directives = b'\n'.join(line for line in logical_lines if line.lstrip().startswith(b'#'))
            result[name] = hashlib.sha256(b''.join(chunks) + b'\n' + directives).hexdigest()
        except (OSError, KeyError, TypeError, ValueError):
            result[name] = sha
    return result


def catalog(root, out, cfg, facts, report):
    from .workflow import analysis_config, engine_digest
    project_id = digest(['ecra-project-v1', str(root.resolve()).casefold()])
    scope = digest(canonical(analysis_config(cfg), root))
    manifest = read_json(out / 'input_manifest.json')
    config_name = read_json(out / 'scan_state.json')['config_file']
    manifest.pop(config_name, None)
    funcs = {f['function_id']: f for f in facts.get('functions', [])}
    calls = facts.get('calls', [])
    adjacency = defaultdict(set)
    for c in calls:
        caller, callee = c.get('caller_function_id'), c.get('callee_function_id')
        if caller and callee:
            adjacency[caller].add(callee)
            adjacency[callee].add(caller)
    components = {}
    for fid in set(funcs) | set(adjacency):
        if fid in components:
            continue
        found, todo = set(), [fid]
        while todo:
            current = todo.pop()
            if current in found:
                continue
            found.add(current)
            todo.extend(adjacency[current] - found)
        frozen = frozenset(found)
        for current in found:
            components[current] = frozen
    by_symbol = defaultdict(list)
    for finding in report.get('findings', []):
        by_symbol[finding.get('symbol_id')].append(finding)
    reviews_by_id = {r.get('finding_id'): r for r in report.get('review_records', [])}
    rows = {}
    engine = engine_digest()
    graph_cache = {}
    global_evidence = dict(contexts=unordered(facts.get('contexts', []), root),
        unknowns=unordered(facts.get('unknowns', []), root),
        build=unordered([{k: u.get(k) for k in
            ('source_file', 'arguments', 'parse_status', 'missing_defines', 'audit_role')}
            for u in facts.get('translation_units', [])], root))
    for v in targets(facts, report):
        sid = v['symbol_id']
        related = {a.get('function_id') for a in v.get('accesses', [])}
        # Ancestors establish reachability; descendants can change protection,
        # aliases and the effects of wrappers even without a direct access.
        related = set().union(*(components.get(fid, {fid}) for fid in related)) if related else set()
        findings = by_symbol[sid]
        reviews = [{k: r.get(k) for k in ('finding_id', 'state', 'status', 'answer')}
                   for f in findings if f['finding_id'] in reviews_by_id
                   for r in [reviews_by_id[f['finding_id']]]]
        # Review verdict status is semantic, unlike the derived finding status.
        for r in reviews:
            r['verdict'] = r.pop('status')
        related_key = tuple(sorted(f for f in related if f))
        if related_key not in graph_cache:
            graph_cache[related_key] = dict(
                calls=unordered([c for c in calls if c.get('caller_function_id') in related or c.get('callee_function_id') in related], root),
                functions=unordered([funcs[f] for f in related if f in funcs], root),
                source=source_evidence(root, facts, related, manifest))
        evidence = dict(schema=1, engine=engine, scope=scope,
            variable=canonical(v, root), findings=unordered(findings, root),
            reviews=unordered(reviews, root),
            # Keep global uncertainty too: an unbound indirect access must never
            # accidentally validate a previous human safety decision.
            **global_evidence, **graph_cache[related_key])
        vid = digest(['storage-v1', sid])
        rows[vid] = dict(variable_id=vid, symbol_id=sid,
            variable_name=v.get('qualified_name', v.get('name', sid)),
            source_file=v.get('definition_file'), source_location=v.get('definition_line'),
            analysis_scope_id=scope, evidence_digest=digest(evidence),
            static_classification=v.get('static_classification'), reviews=reviews)
    return project_id, rows


def now():
    return datetime.now(timezone.utc).isoformat()


class Ledger:
    def __init__(self, out, project_id):
        self.path = out / 'manual_review/manual_review.sqlite3'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.project_id = project_id
        with closing(self.connect()) as db, db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS current_review (
                    project_id TEXT NOT NULL, variable_id TEXT NOT NULL,
                    payload TEXT NOT NULL, revision INTEGER NOT NULL,
                    PRIMARY KEY(project_id, variable_id));
                CREATE TABLE IF NOT EXISTS history (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT NOT NULL, variable_id TEXT NOT NULL,
                    revision INTEGER NOT NULL, payload TEXT NOT NULL,
                    UNIQUE(project_id, variable_id, revision));
            ''')

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA synchronous=FULL')
        return db

    def _get(self, db, vid):
        row = db.execute('SELECT payload FROM current_review WHERE project_id=? AND variable_id=?',
                         (self.project_id, vid)).fetchone()
        return json.loads(row[0]) if row else dict(decision='UNCONFIRMED', revision=0)

    def _write(self, db, item, old, decision, reason, reviewer, event, **extra):
        stamp = now()
        row = dict(item, decision=decision, reason=reason, reviewer=reviewer,
                   confirmed_at=stamp if decision in CONFIRMED else old.get('confirmed_at'),
                   updated_at=stamp, revision=old['revision'] + 1)
        row.update(extra)
        history = dict(event=event, old_decision=old['decision'], new_decision=decision,
            old_evidence_digest=old.get('evidence_digest'), new_evidence_digest=item['evidence_digest'],
            reason=reason, reviewer=reviewer, timestamp=stamp, revision=row['revision'],
            previous=old, current=row)
        db.execute('INSERT INTO history(project_id,variable_id,revision,payload) VALUES(?,?,?,?)',
                   (self.project_id, item['variable_id'], row['revision'], json.dumps(history, ensure_ascii=False)))
        db.execute('INSERT OR REPLACE INTO current_review VALUES(?,?,?,?)',
                   (self.project_id, item['variable_id'], json.dumps(row, ensure_ascii=False), row['revision']))
        return row

    def sync(self, items, valid=True, error=''):
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            result = []
            for vid, item in items.items():
                old = self._get(db, vid)
                if old['decision'] in CONFIRMED and (not valid or old.get('evidence_digest') != item['evidence_digest']):
                    old = self._write(db, item, old, 'NEEDS_RECHECK',
                        error or '相关源码、配置或分析证据已变化', '系统', 'INVALIDATE',
                        previous_decision=old['decision'])
                result.append(dict(item, **{k: old.get(k) for k in
                    ('decision', 'revision', 'reason', 'reviewer', 'confirmed_at', 'updated_at', 'previous_decision')},
                    valid=valid))
            return result

    def paused(self, items):
        """Read without reconciling against a catalog a scanner is replacing."""
        with closing(self.connect()) as db, db:
            db.execute('BEGIN')
            result = []
            for vid, item in items.items():
                current = self._get(db, vid)
                result.append(dict(item, **{k: current.get(k) for k in
                    ('revision', 'reason', 'reviewer', 'confirmed_at', 'updated_at')},
                    decision='NEEDS_RECHECK' if current['decision'] in CONFIRMED else current['decision'], valid=False))
            return result

    def submit(self, items, request):
        vid = request.get('variable_id')
        if vid not in items:
            raise ValueError('变量不属于当前人工核对范围')
        item = items[vid]
        if (request.get('evidence_digest') != item['evidence_digest'] or
                request.get('analysis_scope_id') != item['analysis_scope_id']):
            raise Conflict('证据或范围已变化，请重新加载报告')
        decision = request.get('decision')
        if decision not in CONFIRMED | {'UNCONFIRMED'}:
            raise ValueError('不允许的人工确认状态')
        reason, reviewer = request.get('reason', ''), request.get('reviewer', '')
        if not isinstance(reason, str) or not isinstance(reviewer, str) or len(reason) > 10000 or len(reviewer) > 200:
            raise ValueError('确认依据或确认人格式错误/超长')
        if decision == 'CONFIRMED_SAFE' and not reason.strip():
            raise ValueError('确认无风险必须填写人工确认依据')
        if type(request.get('revision')) is not int:
            raise ValueError('缺少有效修订号')
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            old = self._get(db, vid)
            if request['revision'] != old['revision']:
                raise Conflict('其他页面已修改此变量，请重新加载最新状态')
            if old['decision'] != 'UNCONFIRMED' and not reason.strip():
                raise ValueError('修改或撤销确认必须填写原因')
            return self._write(db, item, old, decision, reason.strip(), reviewer.strip(), 'SUBMIT')

    def history(self, vid=None):
        with closing(self.connect()) as db:
            sql = 'SELECT payload FROM history WHERE project_id=?'
            args = [self.project_id]
            if vid is not None:
                sql += ' AND variable_id=?'
                args.append(vid)
            return [json.loads(r[0]) for r in db.execute(sql + ' ORDER BY event_id', args)]

    def revisions(self):
        with closing(self.connect()) as db:
            return dict(db.execute('SELECT variable_id,revision FROM current_review WHERE project_id=?', (self.project_id,)))

    def export(self):
        with closing(self.connect()) as db, db:
            db.execute('BEGIN')
            rows = [json.loads(r[0]) for r in db.execute(
                'SELECT payload FROM current_review WHERE project_id=? ORDER BY variable_id', (self.project_id,))]
            events = [json.loads(r[0]) for r in db.execute(
                'SELECT payload FROM history WHERE project_id=? ORDER BY event_id', (self.project_id,))]
        return dict(schema=1, project_id=self.project_id, records=rows, history=events)

    def import_data(self, items, document, revisions):
        if not isinstance(document, dict) or document.get('schema') != 1 or document.get('project_id') != self.project_id:
            raise ValueError('导入文件格式或工程身份不匹配')
        records, history = document.get('records'), document.get('history')
        if not isinstance(records, list) or not isinstance(history, list) or not isinstance(revisions, dict):
            raise ValueError('导入记录格式错误')
        seen = set()
        # Validate the entire file before starting any writes.
        for r in records:
            if (not isinstance(r, dict) or not isinstance(r.get('variable_id'), str)
                    or r['variable_id'] in seen or r.get('decision') not in LABELS
                    or type(r.get('revision')) is not int or r['revision'] < 1
                    or any(not isinstance(r.get(k), str) for k in ('symbol_id', 'evidence_digest', 'analysis_scope_id', 'reason', 'reviewer'))
                    or len(r['reason']) > 10000 or len(r['reviewer']) > 200
                    or r['decision'] == 'CONFIRMED_SAFE' and not r['reason'].strip()):
                raise ValueError('导入记录字段无效或重复')
            if r['variable_id'] != digest(['storage-v1', r['symbol_id']]):
                raise ValueError('导入变量身份不匹配')
            seen.add(r['variable_id'])
        if any(not isinstance(h, dict) or not isinstance(h.get('current'), dict)
               or h['current'].get('variable_id') not in seen for h in history):
            raise ValueError('导入历史格式错误')
        for h in history:
            if (h.get('new_decision') not in LABELS or h.get('old_decision') not in LABELS
                    or type(h.get('revision')) is not int or h['revision'] < 1
                    or h['current'].get('revision') != h['revision']
                    or h['current'].get('decision') != h['new_decision']
                    or any(not isinstance(h.get(k), str) for k in ('reason', 'reviewer', 'timestamp'))):
                raise ValueError('导入历史字段无效')
            try:
                datetime.fromisoformat(h['timestamp'])
            except ValueError as exc:
                raise ValueError('导入历史时间无效') from exc
        for r in records:
            events = [h for h in history if h['current']['variable_id'] == r['variable_id']]
            if (not events or events[-1]['revision'] != r['revision']
                    or events[-1]['current'].get('decision') != r['decision']
                    or events[-1]['current'].get('evidence_digest') != r['evidence_digest']):
                raise ValueError('导入当前状态与操作历史不一致')
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            for r in records:
                vid = r['variable_id']
                old = self._get(db, vid)
                if revisions.get(vid, 0) != old['revision']:
                    raise Conflict('导入发生版本冲突，请重新加载后重试')
                item = items.get(vid, r)
                valid = vid in items and r['evidence_digest'] == item['evidence_digest'] and r['analysis_scope_id'] == item['analysis_scope_id']
                decision = r['decision'] if valid or r['decision'] == 'UNCONFIRMED' else 'NEEDS_RECHECK'
                # The imported history is retained as provenance inside an
                # append-only event; local history/revisions are never replaced.
                self._write(db, item, old, decision, r['reason'], r['reviewer'], 'IMPORT',
                    confirmed_at=r.get('confirmed_at'), imported_record=r,
                    imported_history=[h for h in history if h['current']['variable_id'] == vid])

    def backup(self, destination):
        """SQLite backup API includes committed WAL pages, even while serving."""
        with closing(self.connect()) as source, closing(sqlite3.connect(destination)) as dest:
            source.backup(dest)


def progress(rows):
    counts = {key: sum(r['decision'] == key for r in rows) for key in LABELS}
    total = len(rows)
    return dict(total=total, counts=counts,
                percent=round(100 * sum(counts[k] for k in CONFIRMED) / total, 2) if total else 0)
