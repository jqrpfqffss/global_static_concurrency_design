"""Lossless, ordered SQLite evidence graph and indexed business projections.

This module does not classify evidence. Publication accepts complete facts and
reports; no field, list order, duplicate or JSON scalar type is discarded.
"""
from collections import OrderedDict
from contextlib import closing
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import sqlite3
import struct
import uuid

SCHEMA_VERSION = 2
SUPPORTED_VERSIONS = {1, 2}
SCHEMA = """
CREATE TABLE nodes (
 id INTEGER PRIMARY KEY, hash TEXT UNIQUE, kind TEXT NOT NULL,
 value BLOB, length INTEGER NOT NULL CHECK(length>=0));
CREATE TABLE edges (
 parent INTEGER NOT NULL REFERENCES nodes(id), ordinal INTEGER NOT NULL,
 key TEXT, child INTEGER NOT NULL REFERENCES nodes(id),
 PRIMARY KEY(parent,ordinal));
CREATE INDEX edge_child ON edges(child);
CREATE TABLE roots (name TEXT PRIMARY KEY, node INTEGER NOT NULL REFERENCES nodes(id));
CREATE TABLE records (
 dataset TEXT NOT NULL, relation TEXT NOT NULL, ordinal INTEGER NOT NULL,
 node INTEGER NOT NULL REFERENCES nodes(id), symbol_id TEXT, function_id TEXT,
 source_id TEXT, target_id TEXT, PRIMARY KEY(dataset,relation,ordinal));
CREATE INDEX record_symbol ON records(dataset,relation,symbol_id,ordinal);
CREATE INDEX record_function ON records(dataset,relation,function_id,ordinal);
CREATE INDEX record_source ON records(dataset,relation,source_id,ordinal);
CREATE INDEX record_target ON records(dataset,relation,target_id,ordinal);
CREATE TABLE symbols (
 symbol_id TEXT PRIMARY KEY, ordinal INTEGER NOT NULL UNIQUE,
 node INTEGER NOT NULL REFERENCES nodes(id), name TEXT NOT NULL,
 static_classification TEXT NOT NULL, resource_kind TEXT NOT NULL,
 definition_file TEXT, definition_line INTEGER, analysis_coverage TEXT);
CREATE INDEX symbol_class ON symbols(static_classification,ordinal);
CREATE INDEX symbol_name ON symbols(name,ordinal);
CREATE TABLE projects (project_id TEXT PRIMARY KEY, node INTEGER REFERENCES nodes(id));
CREATE TABLE profiles (profile_id TEXT PRIMARY KEY, project_id TEXT REFERENCES projects(project_id));
CREATE TABLE scans (
 scan_id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(project_id),
 profile_id TEXT REFERENCES profiles(profile_id), state TEXT NOT NULL,
 facts_hash TEXT NOT NULL, report_hash TEXT NOT NULL);
CREATE VIEW functions AS SELECT * FROM records WHERE dataset='facts' AND relation='functions';
CREATE VIEW accesses AS SELECT * FROM records WHERE dataset='facts' AND relation='accesses';
CREATE VIEW call_edges AS SELECT * FROM records WHERE dataset='facts' AND relation='calls';
CREATE VIEW protection_events AS SELECT * FROM records WHERE dataset='facts' AND relation='protection_events';
CREATE VIEW findings AS SELECT * FROM records WHERE dataset='report' AND relation='findings';
CREATE VIEW irq_priorities AS SELECT * FROM records WHERE dataset='facts' AND relation='irq_priority_events';
CREATE VIEW coverage_gaps AS SELECT * FROM records WHERE dataset='facts' AND relation='unknowns';
CREATE VIEW translation_units AS SELECT * FROM records WHERE dataset='facts' AND relation='translation_units';
"""


def connect_readonly(path):
    """Never execute schema-owned code or attach databases from an import."""
    conn = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    conn.execute('PRAGMA query_only=ON')
    conn.execute('PRAGMA trusted_schema=OFF')
    conn.execute('PRAGMA foreign_keys=ON')
    if conn.execute('PRAGMA user_version').fetchone()[0] not in SUPPORTED_VERSIONS:
        conn.close()
        raise ValueError('不支持的 scan.db schema；请使用匹配版本的 ECRA Studio')
    conn.row_factory = sqlite3.Row
    return conn


def _scalar(value):
    if value is None:
        return 'null', b''
    if type(value) is bool:
        return 'bool', b'1' if value else b'0'
    if type(value) is int:
        return 'int', str(value).encode('ascii')
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError('证据包含非有限浮点数')
        return 'float', value.hex().encode('ascii')
    if isinstance(value, str):
        return 'str', value.encode('utf-8', errors='surrogatepass')
    raise TypeError(f'证据类型不可无损编码: {type(value).__name__}')


def _decode(kind, value):
    if kind == 'null':
        return None
    if kind == 'bool':
        return value == b'1'
    if kind == 'int':
        return int(value)
    if kind == 'float':
        return float.fromhex(value.decode('ascii'))
    if kind == 'str':
        return value.decode('utf-8', errors='surrogatepass')
    raise ValueError('未知证据标量类型: ' + kind)


def _wire_value(kind, payload):
    value = _decode(kind, payload)
    result = dict(value=value)
    # JSON numbers are arbitrary precision in Python but binary64 in browsers.
    # Preserve a decimal spelling for display and a float's exact binary value;
    # never let a GUI round a large integer or erase the sign of zero.
    if kind == 'int':
        result['exact_value'] = str(value)
    elif kind == 'float':
        result.update(exact_value=repr(value), binary_value=value.hex())
    elif kind == 'str' and any(0xd800 <= ord(char) <= 0xdfff for char in value):
        result['display_json'] = json.dumps(value,ensure_ascii=True)
    return result


def _hash_start(kind, count):
    result = hashlib.sha256()
    result.update(b'ECRA_ORDERED_TYPED_V1\0' + kind.encode('ascii') + b'\0')
    result.update(struct.pack('>Q', count))
    return result


def _hash_edge(hasher, key, child_hash):
    raw = key.encode('utf-8', errors='surrogatepass') if key is not None else b''
    hasher.update(struct.pack('>Q', len(raw)))
    hasher.update(raw)
    hasher.update(bytes.fromhex(child_hash))


class GraphWriter:
    def __init__(self, connection, cache_size=8192):
        self.conn = connection
        # Bounded acceleration index, never an evidence limit.
        self.cache = OrderedDict()
        self.cache_size = cache_size

    def put(self, value):
        # The engine uses tuples for immutable JSON arrays too. Match the
        # original JSON encoder's tuple -> array contract without dropping data.
        container = isinstance(value, (dict, list, tuple))
        if container:
            previous = self.cache.get(id(value))
            if previous is not None and previous[0] is value:
                self.cache.move_to_end(id(value))
                return previous[1:]
            kind = 'object' if isinstance(value, dict) else 'list'
            count = len(value)
            hasher = _hash_start(kind, count)
            node = self.conn.execute('INSERT INTO nodes(kind,length) VALUES (?,?)', (kind, count)).lastrowid
            items = value.items() if kind == 'object' else ((None, item) for item in value)
            for ordinal, (key, item) in enumerate(items):
                if kind == 'object' and not isinstance(key, str):
                    raise TypeError('证据映射键必须是字符串')
                child, child_hash = self.put(item)
                self.conn.execute('INSERT INTO edges VALUES (?,?,?,?)', (node, ordinal, key, child))
                _hash_edge(hasher, key, child_hash)
            hashed = hasher.hexdigest()
            old = self.conn.execute('SELECT id,kind,length FROM nodes WHERE hash=?', (hashed,)).fetchone()
            if old:
                if old[1:] != (kind, count) or not self._same_edges(old[0], node):
                    raise ValueError('证据 SHA-256 冲突；拒绝合并')
                self.conn.execute('DELETE FROM edges WHERE parent=?', (node,))
                self.conn.execute('DELETE FROM nodes WHERE id=?', (node,))
                node = old[0]
            else:
                self.conn.execute('UPDATE nodes SET hash=? WHERE id=?', (hashed, node))
            self.cache[id(value)] = (value, node, hashed)
            while len(self.cache) > self.cache_size:
                self.cache.popitem(last=False)
            return node, hashed
        kind, payload = _scalar(value)
        hasher = _hash_start(kind, len(payload))
        hasher.update(payload)
        hashed = hasher.hexdigest()
        old = self.conn.execute('SELECT id,kind,value,length FROM nodes WHERE hash=?', (hashed,)).fetchone()
        if old:
            if old[1:] != (kind, payload, len(payload)):
                raise ValueError('证据 SHA-256 冲突；拒绝合并')
            return old[0], hashed
        node = self.conn.execute('INSERT INTO nodes(hash,kind,value,length) VALUES (?,?,?,?)',
                                 (hashed, kind, payload, len(payload))).lastrowid
        return node, hashed

    def _same_edges(self, first, second):
        sql = 'SELECT ordinal,key,child FROM edges WHERE parent=? ORDER BY ordinal'
        return all(a == b for a, b in itertools.zip_longest(self.conn.execute(sql, (first,)),
                                                         self.conn.execute(sql, (second,))))


def _project(connection, dataset, root):
    version = connection.execute('PRAGMA user_version').fetchone()[0]
    fields = connection.execute('SELECT key,child FROM edges WHERE parent=? ORDER BY ordinal', (root,))
    for relation, array in fields:
        if connection.execute('SELECT kind FROM nodes WHERE id=?', (array,)).fetchone()[0] != 'list':
            continue
        for ordinal, node in connection.execute('SELECT ordinal,child FROM edges WHERE parent=? ORDER BY ordinal', (array,)):
            if connection.execute('SELECT kind FROM nodes WHERE id=?', (node,)).fetchone()[0] != 'object':
                continue
            values = {}
            for key, kind, value in connection.execute(
                    'SELECT e.key,n.kind,n.value FROM edges e JOIN nodes n ON n.id=e.child WHERE e.parent=?', (node,)):
                if kind not in {'object', 'list'}:
                    values[key] = _decode(kind, value)
            connection.execute('INSERT INTO records VALUES (?,?,?,?,?,?,?,?)',
                (dataset, relation, ordinal, node, values.get('symbol_id'), values.get('function_id'),
                 (values.get('caller_function_id') if version >= 2 else None) or values.get('caller') or values.get('caller_id'),
                 (values.get('callee_function_id') if version >= 2 else None) or values.get('callee') or values.get('callee_id')))
            if dataset == 'facts' and relation == 'variables':
                connection.execute('INSERT INTO symbols VALUES (?,?,?,?,?,?,?,?,?)',
                    (values['symbol_id'], ordinal, node, values.get('qualified_name') or values.get('name') or values['symbol_id'],
                     values.get('static_classification', 'UNKNOWN'), values.get('resource_kind', ''),
                     values.get('definition_file'), values.get('definition_line'), values.get('analysis_coverage')))


def publish_scan(path, facts, report, *, scan_id, project_id, profile_id='default', provenance=None,
                 validation_state='UNVERIFIED'):
    """Publish once, never overwrite a valid archive, including on failure."""
    return _publish(path, lambda writer: {name: writer.put(value) for name, value in
        [('facts', facts), ('report', report), ('provenance', provenance or {})]},
        scan_id=scan_id, project_id=project_id, profile_id=profile_id, validation_state=validation_state)


def publish_json_scan(path, facts_path, report_path, *, scan_id, project_id, profile_id='default',
                      provenance=None, provenance_path=None, validation_state='LEGACY_READ_ONLY', progress=lambda _: None):
    """Import complete legacy JSON without restoring the evidence in Python.

    The same ordered typed graph, projections and publication rules are used
    by native scans. This grants no current-source or original-engine proof.
    """
    from .streamed_evidence import read_json
    def build(writer):
        roots = {}
        for name, source in [('facts', facts_path), ('report', report_path)]:
            progress('正在转换完整旧' + ('事实' if name == 'facts' else '报告') + '；剩余量未知')
            roots[name] = read_json(source, writer)
            kind = writer.conn.execute('SELECT kind FROM nodes WHERE id=?', (roots[name][0],)).fetchone()[0]
            if kind != 'object':
                raise ValueError('旧事实/报告根必须是完整对象')
        if provenance is not None and provenance_path is not None:
            raise ValueError('迁移来源不能同时来自对象与JSON文件')
        roots['provenance'] = read_json(provenance_path, writer) if provenance_path is not None else writer.put(provenance or {})
        return roots
    return _publish(path, build, scan_id=scan_id, project_id=project_id,
        profile_id=profile_id, validation_state=validation_state)


def _publish(path, build_roots, *, scan_id, project_id, profile_id, validation_state):
    if validation_state not in {'UNVERIFIED', 'LEGACY_READ_ONLY', 'STATIC_VALIDATED'}:
        raise ValueError('未知静态快照有效性状态')
    path = Path(path)
    if path.exists():
        raise FileExistsError(f'扫描快照已存在，拒绝覆盖: {path}')
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.pending')
    try:
        with closing(sqlite3.connect(temp)) as conn:
            conn.execute('PRAGMA foreign_keys=ON')
            conn.execute('PRAGMA synchronous=FULL')
            conn.execute('PRAGMA cache_size=-8192')
            conn.execute('PRAGMA temp_store=FILE')
            conn.executescript(SCHEMA)
            conn.execute(f'PRAGMA user_version={SCHEMA_VERSION}')
            with conn:
                writer = GraphWriter(conn)
                roots = build_roots(writer)
                for name, (node, hashed) in roots.items():
                    conn.execute('INSERT INTO roots VALUES (?,?)', (name, node))
                _project(conn, 'facts', roots['facts'][0])
                _project(conn, 'report', roots['report'][0])
                conn.execute('INSERT INTO projects VALUES (?,?)', (project_id, roots['provenance'][0]))
                conn.execute('INSERT INTO profiles VALUES (?,?)', (profile_id, project_id))
                conn.execute('INSERT INTO scans VALUES (?,?,?,?,?,?)',
                    (scan_id, project_id, profile_id, validation_state, roots['facts'][1], roots['report'][1]))
            if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or list(conn.execute('PRAGMA foreign_key_check')):
                raise ValueError('scan.db 完整性/引用校验失败')
        # NTFS/ext4 hard-link publication is atomic and exclusive. A crash
        # cannot expose an empty claim file or overwrite an older archive.
        os.link(temp, path)
    finally:
        temp.unlink(missing_ok=True)
    return roots


class EvidenceProvider:
    """One read-only query protocol for UI and review evidence navigation."""
    def __init__(self, path):
        self.path = Path(path)

    def metadata(self):
        """Small immutable identity query, not an integrity_check per UI page."""
        with closing(connect_readonly(self.path)) as conn:
            rows = list(conn.execute('SELECT * FROM scans'))
            if len(rows) != 1:
                raise ValueError('静态库扫描身份缺失/不唯一')
            return dict(rows[0])

    def validate(self, *, deep=False):
        with closing(connect_readonly(self.path)) as conn:
            if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or list(conn.execute('PRAGMA foreign_key_check')):
                raise ValueError('静态库损坏或证据引用缺失')
            scan = conn.execute('SELECT * FROM scans').fetchone()
            if scan is None or conn.execute('SELECT count(*) FROM scans').fetchone()[0] != 1:
                raise ValueError('静态库扫描身份缺失/不唯一')
            for name in ('facts', 'report'):
                root = conn.execute('SELECT n.hash FROM roots r JOIN nodes n ON r.node=n.id WHERE r.name=?', (name,)).fetchone()
                if root is None or root[0] != scan[name + '_hash']:
                    raise ValueError('静态库权威根与扫描摘要不一致')
            if deep:
                for node in conn.execute('SELECT id,hash,kind,length FROM nodes ORDER BY id'):
                    if node['kind'] not in {'object','list','null','bool','int','float','str'}:
                        raise ValueError('未知证据编码类型')
                    if node['kind'] in {'object', 'list'}:
                        hasher = _hash_start(node['kind'], node['length'])
                        count = 0
                        for edge in conn.execute('SELECT e.ordinal,e.key,n.hash FROM edges e JOIN nodes n ON n.id=e.child WHERE e.parent=? ORDER BY e.ordinal', (node['id'],)):
                            if edge['ordinal'] != count:
                                raise ValueError('证据数组顺序/完整性损坏')
                            if (node['kind'] == 'list') != (edge['key'] is None):
                                raise ValueError('证据容器键类型损坏')
                            _hash_edge(hasher, edge['key'], edge['hash'])
                            count += 1
                        if count != node['length']:
                            raise ValueError('证据段缺失')
                        if node['kind'] == 'object' and conn.execute('SELECT 1 FROM edges WHERE parent=? GROUP BY key HAVING count(*)>1 LIMIT 1', (node['id'],)).fetchone():
                            raise ValueError('证据映射键重复')
                    else:
                        hasher = _hash_start(node['kind'], node['length'])
                        if conn.execute('SELECT 1 FROM edges WHERE parent=? LIMIT 1', (node['id'],)).fetchone():
                            raise ValueError('标量证据包含非法容器边')
                        if node['kind'] == 'str':
                            import codecs
                            decoder = codecs.getincrementaldecoder('utf-8')(errors='surrogatepass')
                        for offset in range(0,node['length'],1024*1024):
                            part = conn.execute('SELECT substr(value,?,?) FROM nodes WHERE id=?',
                                                (offset+1,1024*1024,node['id'])).fetchone()[0]
                            hasher.update(part)
                            if node['kind']=='str':
                                decoder.decode(part,final=offset+len(part)==node['length'])
                        if node['kind'] != 'str':
                            payload = conn.execute('SELECT value FROM nodes WHERE id=?',(node['id'],)).fetchone()[0]
                            if _scalar(_decode(node['kind'],payload)) != (node['kind'],payload):
                                raise ValueError('非规范化的证据标量编码')
                    if hasher.hexdigest() != node['hash']:
                        raise ValueError('证据哈希校验失败')
                # Rebuild projections in a separate disposable in-memory
                # index, comparing every row. Source evidence is never edited.
                # Use a file-backed temporary DB for large scans instead of
                # retaining all symbol/record rows in Python.
                import tempfile
                with tempfile.TemporaryDirectory(prefix='ecra projection validation ') as folder:
                    with closing(sqlite3.connect(Path(folder)/'projection.db')) as expected:
                        expected.executescript(SCHEMA)
                        expected.execute('PRAGMA foreign_keys=OFF')
                        # sqlite backup provides a consistent, bounded-memory
                        # copy; validate the exact projection against its tree.
                        conn.backup(expected)
                        expected.execute('DELETE FROM symbols')
                        expected.execute('DELETE FROM records')
                        for name in ('facts', 'report'):
                            root = expected.execute('SELECT node FROM roots WHERE name=?', (name,)).fetchone()[0]
                            _project(expected, name, root)
                        for table, order in [('symbols', 'ordinal'), ('records', 'dataset,relation,ordinal')]:
                            actual = (tuple(row) for row in conn.execute('SELECT * FROM ' + table + ' ORDER BY ' + order))
                            rebuilt = expected.execute('SELECT * FROM ' + table + ' ORDER BY ' + order)
                            if any(a != b for a, b in itertools.zip_longest(actual, rebuilt)):
                                raise ValueError('静态库查询投影与权威证据不一致: ' + table)
            return dict(scan)

    def load(self, name, path=()):
        """Compatibility reconstruction, intentionally explicit and unbounded.

        Global solvers still need a measured external-memory migration. UI must
        use pages; calling this method is not a low-memory claim.
        """
        with closing(connect_readonly(self.path)) as conn:
            row = conn.execute('SELECT node FROM roots WHERE name=?', (name,)).fetchone()
            if not row:
                raise KeyError(name)
            node = row[0]
            for key in path:
                column = 'ordinal' if type(key) is int else 'key'
                row = conn.execute('SELECT child FROM edges WHERE parent=? AND '+column+'=?', (node, key)).fetchone()
                if row is None:
                    raise KeyError(key)
                node = row[0]
            memo = {}
            def get(node):
                if node in memo:
                    return memo[node]
                kind, value = conn.execute('SELECT kind,value FROM nodes WHERE id=?', (node,)).fetchone()
                if kind not in {'object', 'list'}:
                    result = _decode(kind, value)
                    memo[node] = result
                    return result
                entries = conn.execute('SELECT key,child FROM edges WHERE parent=? ORDER BY ordinal', (node,))
                result = {} if kind == 'object' else []
                memo[node] = result
                for key, child in entries:
                    if kind == 'object':
                        result[key] = get(child)
                    else:
                        result.append(get(child))
                return result
            return get(node)

    def resolve(self, name, path=()):
        """Resolve an exact object key/list ordinal without loading its value."""
        with closing(connect_readonly(self.path)) as conn:
            row = conn.execute('SELECT node FROM roots WHERE name=?', (name,)).fetchone()
            if row is None:
                raise KeyError(name)
            node = row[0]
            for key in path:
                column = 'ordinal' if type(key) is int else 'key'
                row = conn.execute('SELECT child FROM edges WHERE parent=? AND '+column+'=?', (node, key)).fetchone()
                if row is None:
                    raise KeyError(key)
                node = row[0]
            return node

    @staticmethod
    def _bounds(offset, limit):
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError('分页要求 offset>=0，limit=1–200')

    def symbols(self, *, search='', classification='', offset=0, limit=50):
        self._bounds(offset, limit)
        terms, args = [], []
        if search:
            terms.append("(instr(name,?)>0 OR instr(coalesce(definition_file,''),?)>0 OR instr(symbol_id,?)>0)")
            args.extend([search] * 3)
        if classification:
            terms.append('static_classification=?')
            args.append(classification)
        where = ' WHERE ' + ' AND '.join(terms) if terms else ''
        with closing(connect_readonly(self.path)) as conn:
            total = conn.execute('SELECT count(*) FROM symbols' + where, args).fetchone()[0]
            rows = [dict(row) for row in conn.execute('SELECT * FROM symbols' + where + ' ORDER BY ordinal LIMIT ? OFFSET ?', [*args, limit, offset])]
        return dict(total=total, offset=offset, items=rows, next_offset=offset + len(rows) if offset + len(rows) < total else None)

    def counts(self):
        with closing(connect_readonly(self.path)) as conn:
            return {row[0]: row[1] for row in conn.execute('SELECT static_classification,count(*) FROM symbols GROUP BY static_classification')}

    def records(self, relation, *, dataset='facts', symbol_id=None, function_id=None, source_id=None, target_id=None, offset=0, limit=50):
        self._bounds(offset, limit)
        where, args = 'dataset=? AND relation=?', [dataset, relation]
        for key, value in [('symbol_id', symbol_id), ('function_id', function_id), ('source_id', source_id), ('target_id', target_id)]:
            if value is not None:
                where += ' AND ' + key + '=?'
                args.append(value)
        with closing(connect_readonly(self.path)) as conn:
            version=conn.execute('PRAGMA user_version').fetchone()[0]
            if version==1 and dataset=='facts' and relation=='calls':
                # V1 archives retain the engine IDs in authoritative edges,
                # although their original projection missed these two fields.
                where,args='dataset=? AND relation=?',[dataset,relation]
                for column,value in [('symbol_id',symbol_id),('function_id',function_id),('source_id',source_id),('target_id',target_id)]:
                    if value is None:
                        continue
                    if column in {'source_id','target_id'}:
                        key='caller_function_id' if column=='source_id' else 'callee_function_id'
                        where+=' AND ('+column+'=? OR node IN (SELECT e.parent FROM edges e JOIN nodes n ON n.id=e.child '
                        where+="WHERE e.key='"+key+"' AND n.kind='str' AND n.value=?))"
                        args.extend([value,value.encode('utf-8',errors='surrogatepass')])
                    else:
                        where+=' AND '+column+'=?';args.append(value)
            total = conn.execute('SELECT count(*) FROM records WHERE ' + where, args).fetchone()[0]
            rows = [dict(row) for row in conn.execute('SELECT * FROM records WHERE ' + where + ' ORDER BY ordinal LIMIT ? OFFSET ?', [*args, limit, offset])]
            for row in rows:
                row['summary'] = {field['key']: _decode(field['kind'],field['value']) for field in conn.execute(
                    "SELECT e.key,n.kind,n.value FROM edges e JOIN nodes n ON n.id=e.child WHERE e.parent=? AND n.kind NOT IN ('object','list') AND n.length<=4096",(row['node'],))}
        return dict(total=total, offset=offset, items=rows, next_offset=offset + len(rows) if offset + len(rows) < total else None)

    def archived_source(self, file):
        """Read only archived text references, never arbitrary live files."""
        with closing(connect_readonly(self.path)) as conn:
            root=conn.execute("SELECT e.child FROM roots r JOIN edges e ON e.parent=r.node WHERE r.name='provenance' AND e.key='archived_sources'").fetchone()
            if root is None:
                return dict(available=False,file=file,reason='此归档未包含对应源码文本；原源码不可用。')
            matches=[]
            for row in conn.execute("SELECT e.child FROM edges e JOIN edges f ON f.parent=e.child AND f.key='file' JOIN nodes n ON n.id=f.child WHERE e.parent=? AND n.kind='str' AND n.value=?",(root[0],file.encode('utf-8',errors='surrogatepass'))):
                fields={field[0]:field[1] for field in conn.execute('SELECT key,child FROM edges WHERE parent=?',(row[0],))}
                if 'text' in fields:
                    matches.append(fields)
            if len(matches)!=1:
                return dict(available=False,file=file,reason='归档源码缺失或来源有歧义，不能自动选择。')
            digest_node=matches[0].get('sha256')
            raw_digest=self.node(digest_node).get('value') if digest_node else None
            return dict(available=True,file=file,text_node=matches[0]['text'],sha256=raw_digest,
                        reason='归档文本仅用于查看；精确原始字节与输入哈希仍保留在来源记录中。')

    def node(self, node_id, *, offset=0, limit=50):
        self._bounds(offset, limit)
        with closing(connect_readonly(self.path)) as conn:
            row = conn.execute("SELECT id,hash,kind,length,CASE WHEN kind='str' AND length>16384 THEN NULL ELSE value END AS value FROM nodes WHERE id=?", (node_id,)).fetchone()
            if row is None:
                raise KeyError(node_id)
            result = dict(id=row['id'], hash=row['hash'], kind=row['kind'], total=row['length'])
            if row['kind'] in {'object', 'list'}:
                items = []
                for child in conn.execute("SELECT e.ordinal,e.key,n.id,n.hash,n.kind,n.length,CASE WHEN n.kind='str' AND n.length>16384 THEN NULL ELSE n.value END AS value FROM edges e JOIN nodes n ON n.id=e.child WHERE e.parent=? ORDER BY e.ordinal LIMIT ? OFFSET ?", (node_id, limit, offset)):
                    item = dict(ordinal=child['ordinal'], key=child['key'], id=child['id'], hash=child['hash'], kind=child['kind'], total=child['length'])
                    if child['kind'] not in {'object', 'list'}:
                        # Large strings have their own explicit segment reader.
                        if child['kind'] == 'str' and child['length'] > 16384:
                            item['value'] = None
                        else:
                            item.update(_wire_value(child['kind'], child['value']))
                    items.append(item)
                result.update(items=items, offset=offset, next_offset=offset + len(items) if offset + len(items) < row['length'] else None)
            elif row['kind'] == 'str' and row['length'] > 16384:
                result.update(value=None, segmented=True)
            else:
                result.update(_wire_value(row['kind'], row['value']))
            return result

    def text(self, node_id, *, offset=0, limit=8192):
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 16384:
            raise ValueError('文本分段参数无效')
        with closing(connect_readonly(self.path)) as conn:
            row = conn.execute("SELECT kind,length,hash,substr(value,?,?) AS part FROM nodes WHERE id=?", (offset+1,limit,node_id)).fetchone()
            if row is None or row['kind'] != 'str':
                raise KeyError(node_id)
            part = row['part']
            if offset>row['length']:
                raise ValueError('文本分段超出范围')
            # Cursor offsets are UTF-8 byte positions. End at a complete code
            # point; never decode the whole large string into Python memory.
            for trim in range(4):
                try:
                    value = part[:len(part)-trim] if trim else part
                    decoded = value.decode('utf-8',errors='surrogatepass')
                    break
                except UnicodeDecodeError as exc:
                    if exc.start < len(part)-3 or trim==3:
                        raise ValueError('文本游标未处于完整UTF-8字符边界') from exc
            next_offset=offset+len(value)
            if not value and next_offset<row['length']:
                raise ValueError('文本分段预算太小，无法容纳一个完整字符')
            previous=max(0,offset-limit)
            if previous:
                prefix=conn.execute('SELECT substr(value,?,4) FROM nodes WHERE id=?',(previous+1,node_id)).fetchone()[0]
                for byte in prefix:
                    if byte&0xc0 != 0x80:break
                    previous+=1
            return dict(**_wire_value('str',value), total=row['length'], offset=offset, previous_offset=previous if offset else None,
                        hash=row['hash'], offset_unit='UTF8_BYTES',
                        next_offset=next_offset if next_offset<row['length'] else None)

    def roots(self):
        with closing(connect_readonly(self.path)) as conn:
            return [dict(row) for row in conn.execute('SELECT r.name,n.id,n.hash,n.kind,n.length FROM roots r JOIN nodes n ON n.id=r.node ORDER BY r.name')]

    def fingerprint(self, symbol_id):
        with closing(connect_readonly(self.path)) as conn:
            row = conn.execute('SELECT n.hash FROM symbols s JOIN nodes n ON n.id=s.node WHERE s.symbol_id=?', (symbol_id,)).fetchone()
            if not row:
                raise KeyError(symbol_id)
            scan = conn.execute('SELECT facts_hash,report_hash FROM scans').fetchone()
            # Conservative full-scan binding: an unrelated change may require
            # rechecking, but no changed context can inherit a safe decision.
            return hashlib.sha256(('\0'.join([symbol_id, row[0], *scan])).encode()).hexdigest()
