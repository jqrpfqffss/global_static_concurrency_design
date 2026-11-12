"""Read native baseline inputs for the unchanged Git summary algorithm.

This removes whole facts/report restoration, not the summary's global indexes
or its largest individual field. Only values the original algorithm never
reads are omitted. Every hashed field is an ordinary complete dict/list.
"""
from collections.abc import Mapping, Sequence
from contextlib import closing

from .scan_store import connect_readonly, _decode


class _Fields(Mapping):
    def __init__(self, reader, node):
        self.reader, self.node = reader, node

    def __getitem__(self, key):
        # Native object keys are strings. SQLite's TEXT affinity would match
        # integer 1 to key "1", unlike the original Python dictionary.
        if not isinstance(key, str):
            hash(key)  # Preserve TypeError for unhashable dictionary keys.
            raise KeyError(key)
        node = self.reader.child(self.node, key)
        if node is None:
            raise KeyError(key)
        return self.reader.value(node)

    def __iter__(self):
        for row in self.reader.conn.execute(
                'SELECT key FROM edges WHERE parent=? ORDER BY ordinal', (self.node,)):
            yield row[0]

    def __len__(self):
        return self.reader.conn.execute('SELECT length FROM nodes WHERE id=?', (self.node,)).fetchone()[0]


class _Atoms(Sequence):
    def __init__(self, reader, node):
        self.reader, self.node = reader, node

    def __len__(self):
        return self.reader.conn.execute('SELECT length FROM nodes WHERE id=?', (self.node,)).fetchone()[0]

    def __getitem__(self, index):
        if isinstance(index, slice):
            return [self[i] for i in range(*index.indices(len(self)))]
        if index < 0:
            index += len(self)
        row = self.reader.conn.execute(
            'SELECT child FROM edges WHERE parent=? AND ordinal=?', (self.node, index)).fetchone()
        if row is None:
            raise IndexError(index)
        return self.reader.value(row[0])


class _Rows:
    """Reiterable authority rows, with a memo scoped to the current row."""
    def __init__(self, reader, node, *, fields=None, lazy=False):
        self.reader, self.node, self.fields, self.lazy = reader, node, fields, lazy

    def __iter__(self):
        reader = self.reader
        if self.fields is not None:
            yield from self.selected()
            return
        for row in reader.conn.execute(
                'SELECT child FROM edges WHERE parent=? ORDER BY ordinal', (self.node,)):
            reader.memo.clear()
            if self.lazy:
                reader.require_kind(row[0], 'object')
                yield _Fields(reader, row[0])
            else:
                yield reader.value(row[0])

    def selected(self):
        # One ordered cursor avoids millions of per-function field lookups.
        # LEFT JOIN retains empty records so missing required fields still fail.
        sql = ('SELECT member.ordinal,member.child,record.kind,field.key,'
               'value.id,value.kind,value.value FROM edges member '
               'JOIN nodes record ON record.id=member.child '
               'LEFT JOIN edges field ON field.parent=member.child AND field.key IN ('
               + ','.join('?' for _ in self.fields) + ') '
               'LEFT JOIN nodes value ON value.id=field.child '
               'WHERE member.parent=? ORDER BY member.ordinal,field.ordinal')
        previous, item = None, None
        for ordinal, node, kind, key, child, child_kind, payload in self.reader.conn.execute(
                sql, (*self.fields, self.node)):
            if ordinal != previous:
                if previous is not None:
                    yield item
                self.reader.memo.clear()
                if kind != 'object':
                    raise ValueError('Diff关系包含非对象记录')
                previous, item = ordinal, {}
            if key is not None:
                item[key] = (self.reader.value(child) if child_kind in {'list', 'object'}
                             else _decode(child_kind, payload))
        if previous is not None:
            yield item


class _Inputs:
    def __init__(self, connection):
        self.conn, self.memo = connection, {}
        self.roots = dict(connection.execute('SELECT name,node FROM roots'))

    def child(self, node, key):
        row = self.conn.execute('SELECT child FROM edges WHERE parent=? AND key=?', (node, key)).fetchone()
        return row[0] if row else None

    def require_kind(self, node, expected):
        row = self.conn.execute('SELECT kind FROM nodes WHERE id=?', (node,)).fetchone()
        if row is None or row[0] != expected:
            raise ValueError('Diff证据类型错误，需要 ' + expected)

    def value(self, node):
        if node in self.memo:
            return self.memo[node]
        row = self.conn.execute('SELECT kind,value FROM nodes WHERE id=?', (node,)).fetchone()
        if row is None:
            raise ValueError('Diff证据节点缺失')
        kind, payload = row
        if kind not in {'list', 'object'}:
            result = _decode(kind, payload)
        else:
            result = [] if kind == 'list' else {}
            self.memo[node] = result
            for key, child in self.conn.execute(
                    'SELECT key,child FROM edges WHERE parent=? ORDER BY ordinal', (node,)):
                if kind == 'list':
                    result.append(self.value(child))
                else:
                    result[key] = self.value(child)
        self.memo[node] = result
        return result

    def rows(self, root, key, *, required=False, **options):
        node = self.child(self.roots[root], key)
        if node is None:
            if required:
                raise KeyError(key)
            return []
        self.require_kind(node, 'list')
        return _Rows(self, node, **options)

    def inputs(self):
        for root in ('facts', 'report'):
            self.require_kind(self.roots[root], 'object')
        facts = dict(
            functions=self.rows('facts', 'functions', required=True, fields=(
                'function_id', 'translation_unit', 'semantic_digest', 'consumed_macros_digest',
                'non_call_digest', 'standalone_calls',
                'return_type_kind', 'name', 'file', 'line')),
            calls=self.rows('facts', 'calls', required=True, fields=(
                'caller_function_id', 'callee_function_id', 'callee_name', 'result_used')),
            variables=self.rows('facts', 'variables', required=True, lazy=True))
        # These shared relations are traversed repeatedly by summarize.
        # Keep the complete relations, rather than re-decoding them per variable.
        for key in ('translation_units', 'context_bindings', 'contexts', 'context_call_graph', 'nvic_priorities'):
            node = self.child(self.roots['facts'], key)
            if node is not None:
                self.memo.clear()
                facts[key] = self.value(node)
        for key in ('irq_priority_events', 'nvic_resolved_events', 'protection_events', 'registrations',
                    'hardware_contexts', 'preemption_relations', 'address_escapes', 'pointer_targets', 'unknowns'):
            facts[key] = self.rows('facts', key)
        for key, kind, wrapper in (('pointer_target_atoms', 'list', _Atoms),
                                   ('pointer_target_sets', 'object', _Fields)):
            node = self.child(self.roots['facts'], key)
            if node is not None:
                self.require_kind(node, kind)
                facts[key] = wrapper(self, node)
        node = self.child(self.roots['facts'], 'pointer_target_block_bits')
        if node is not None:
            facts['pointer_target_block_bits'] = self.value(node)
        report = dict(findings=self.rows('report', 'findings', required=True, lazy=True))
        for key in ('coverage', 'analysis_status'):
            node = self.child(self.roots['report'], key)
            if node is not None:
                self.memo.clear()
                if key == 'coverage':
                    self.require_kind(node, 'object')
                    report[key] = _Fields(self, node)
                else:
                    report[key] = self.value(node)
        self.memo.clear()
        return facts, report


def summarize_native(path, renames=None):
    """Call only after checked_scan has validated the complete native authority."""
    from .git_diff import summarize
    with closing(connect_readonly(path)) as connection:
        reader = _Inputs(connection)
        facts, report = reader.inputs()
        units = facts.get('translation_units', [])
        if not units or any(u.get('parse_status') != 'PARSED' for u in units):
            raise ValueError('基准版本存在解析失败/部分解析，不能将缺失事实当作无变化')
        return summarize(facts, report, renames)
