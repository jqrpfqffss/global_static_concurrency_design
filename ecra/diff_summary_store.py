"""Private, derived row indexes for the unchanged complete Diff comparison.

Public summary JSON/schema/cache keys remain unchanged. Large maps and outer
lists are lazy; each selected record is a complete ordinary JSON value.
"""
from collections.abc import Mapping, Sequence
from itertools import chain, zip_longest
import json
import operator
from pathlib import Path
import sqlite3
import uuid

from .json_rows import RowReader

MAPS = {'variables', 'functions', 'graphs', 'macros', 'semantics'}
LISTS = {'edges', 'return_edges', 'dependencies', 'unknowns', 'build'}
DDL = '''CREATE TABLE containers(id INTEGER PRIMARY KEY,kind TEXT NOT NULL,length INTEGER NOT NULL);
CREATE TABLE entries(parent INTEGER NOT NULL,ordinal INTEGER NOT NULL,key TEXT,payload TEXT,child INTEGER,
PRIMARY KEY(parent,ordinal),UNIQUE(parent,key));'''


class _Map(Mapping):
    def __init__(self, store, node): self.store, self.node = store, node
    def __len__(self): return self.store.length(self.node)
    def __iter__(self):
        for row in self.store.conn.execute('SELECT key FROM entries WHERE parent=? ORDER BY ordinal', (self.node,)):
            yield row[0]
    def __getitem__(self, key):
        if not isinstance(key, str):
            hash(key)
            raise KeyError(key)
        row = self.store.conn.execute('SELECT payload,child FROM entries WHERE parent=? AND key=?', (self.node, key)).fetchone()
        if row is None: raise KeyError(key)
        return self.store.decode(row)
    def items(self):
        for key, payload, child in self.store.conn.execute(
                'SELECT key,payload,child FROM entries WHERE parent=? ORDER BY ordinal', (self.node,)):
            yield key, self.store.decode((payload, child))
    def __eq__(self, other):
        if not isinstance(other, Mapping): return NotImplemented
        if len(self) != len(other): return False
        sentinel = object()
        return all(value == other.get(key, sentinel) for key, value in self.items())


class _List(Sequence):
    def __init__(self, store, node): self.store, self.node = store, node
    def __len__(self): return self.store.length(self.node)
    def __iter__(self):
        for row in self.store.conn.execute('SELECT payload,child FROM entries WHERE parent=? ORDER BY ordinal', (self.node,)):
            yield self.store.decode(row)
    def __getitem__(self, index):
        if isinstance(index, slice): return [self[i] for i in range(*index.indices(len(self))) ]
        index = operator.index(index)
        if index < 0: index += len(self)
        row = self.store.conn.execute('SELECT payload,child FROM entries WHERE parent=? AND ordinal=?', (self.node, index)).fetchone()
        if row is None: raise IndexError(index)
        return self.store.decode(row)
    def __add__(self, other): return chain(self, other)
    def __eq__(self, other):
        if not isinstance(other, (list, _List)): return False
        if len(self) != len(other): return False
        sentinel = object()
        return all(a == b for a, b in zip_longest(self, other, fillvalue=sentinel))


class SummaryStore:
    def __init__(self, path):
        self.path = Path(path)
        if self.path.exists(): raise FileExistsError(self.path)
        self.conn = sqlite3.connect(self.path)
        self.conn.executescript(DDL)
        self.conn.execute('PRAGMA cache_size=-2048')
        self.conn.execute('PRAGMA temp_store=FILE')
        self.root = self.container('object')
    def close(self): self.conn.close()
    def __enter__(self): return self
    def __exit__(self, *exc): self.close()
    def container(self, kind):
        return self.conn.execute('INSERT INTO containers(kind,length) VALUES (?,0)', (kind,)).lastrowid
    def append(self, parent, key=None, value=None, child=None):
        ordinal = self.length(parent)
        payload = json.dumps(value, ensure_ascii=True, separators=(',', ':')) if child is None else None
        self.conn.execute('INSERT INTO entries VALUES (?,?,?,?,?)', (parent, ordinal, key, payload, child))
        self.conn.execute('UPDATE containers SET length=length+1 WHERE id=?', (parent,))
    def length(self, node):
        return self.conn.execute('SELECT length FROM containers WHERE id=?', (node,)).fetchone()[0]
    def decode(self, row):
        payload, child = row
        if child is None: return json.loads(payload)
        kind = self.conn.execute('SELECT kind FROM containers WHERE id=?', (child,)).fetchone()[0]
        return (_Map if kind == 'object' else _List)(self, child)
    def ready(self):
        self.conn.commit()
        self.conn.execute('PRAGMA query_only=ON')
        return _Map(self, self.root)
    def from_value(self, value):
        for key, data in value.items():
            if not isinstance(key, str): raise ValueError('摘要对象键必须为字符串')
            if key in MAPS and isinstance(data, dict):
                node = self.container('object'); self.append(self.root, key, child=node)
                for name, item in data.items():
                    if not isinstance(name, str): raise ValueError('摘要对象键必须为字符串')
                    if key == 'semantics' and isinstance(item, list):
                        array = self.container('list'); self.append(node, name, child=array)
                        for member in item: self.append(array, value=member)
                    else: self.append(node, name, item)
            elif key in LISTS and isinstance(data, (list, tuple)):
                node = self.container('list'); self.append(self.root, key, child=node)
                for item in data: self.append(node, value=item)
            else: self.append(self.root, key, data)
        return self.ready()
    def from_json(self, path):
        with Path(path).open('r', encoding='utf-8') as stream:
            reader = RowReader(stream)
            def pairs():
                reader.take('{')
                if reader.peek() != '}':
                    while True:
                        key = reader.value()
                        if not isinstance(key, str): raise ValueError('摘要对象键必须为字符串')
                        reader.take(':'); yield key
                        if reader.peek() == '}': break
                        reader.take(',')
                reader.take('}')
            def members(node):
                reader.take('[')
                if reader.peek() != ']':
                    while True:
                        self.append(node, value=reader.value())
                        if reader.peek() == ']': break
                        reader.take(',')
                reader.take(']')
            for key in pairs():
                if key in MAPS and reader.peek() == '{':
                    node = self.container('object'); self.append(self.root, key, child=node)
                    for name in pairs():
                        if key == 'semantics' and reader.peek() == '[':
                            array = self.container('list'); self.append(node, name, child=array); members(array)
                        else: self.append(node, name, reader.value())
                elif key in LISTS and reader.peek() == '[':
                    node = self.container('list'); self.append(self.root, key, child=node); members(node)
                else: self.append(self.root, key, reader.value())
            if reader.peek(): raise ValueError('摘要包含尾随数据')
        return self.ready()

    def write(self, stream, node=None):
        node = self.root if node is None else node
        kind = self.conn.execute('SELECT kind FROM containers WHERE id=?', (node,)).fetchone()[0]
        stream.write('{' if kind == 'object' else '[')
        separator = ''
        for key, payload, child in self.conn.execute('SELECT key,payload,child FROM entries WHERE parent=? ORDER BY ordinal', (node,)):
            stream.write(separator); separator = ','
            if kind == 'object': stream.write(json.dumps(key, ensure_ascii=True)+':')
            if child is None: stream.write(payload)
            else: self.write(stream, child)
        stream.write('}' if kind == 'object' else ']')


def compare_spooled(base_path, head_factory, pinned, directory):
    """Release current summary before reading baseline; return only plain data."""
    from .common import write_json
    from .git_diff import compare
    from .workflow import file_digest
    from .workspace import no_links
    directory = no_links(directory)
    work = no_links(directory/('summary-compare-'+uuid.uuid4().hex)); work.mkdir(parents=True)
    paths = [work/'base.sqlite', work/'head.sqlite']
    try:
        with SummaryStore(paths[1]) as head_store, SummaryStore(paths[0]) as base_store:
            head_summary = head_factory()
            head = head_store.from_value(head_summary)
            del head_summary
            base = base_store.from_json(base_path)
            if pinned.get('base_summary_sha256') and file_digest(base_path) != pinned['base_summary_sha256']:
                raise ValueError('基准摘要在读取时变化，禁止比较/发布')
            result = compare(base, head, pinned)
        # No result refers to these derived indexes: record values are decoded
        # to ordinary dict/list, and original JSON/facts remain authoritative.
        for path in paths: no_links(path).unlink()
        work.rmdir()
        return result
    except BaseException as exc:
        write_json(work/'failure.json', dict(error=type(exc).__name__+': '+str(exc),
            scope='Private derived indexes retained; no original summary or authority changed'))
        raise


def verify_spooled(reference_path, head_factory, directory, diagnostic_path, units):
    """Original complete summary equality, with sequential resident inputs."""
    from .common import write_json
    from .workspace import no_links
    work = no_links(Path(directory)/('summary-verification-'+uuid.uuid4().hex)); work.mkdir(parents=True)
    paths = [work/'reference.sqlite', work/'head.sqlite']
    try:
        with SummaryStore(paths[1]) as head_store, SummaryStore(paths[0]) as reference_store:
            summary = head_factory(); head = head_store.from_value(summary); del summary
            reference = reference_store.from_json(reference_path)
            if reference != head:
                diagnostic_path = no_links(diagnostic_path); diagnostic_path.parent.mkdir(parents=True, exist_ok=True)
                with diagnostic_path.open('w', encoding='utf-8') as stream:
                    stream.write('{"expected":'); reference_store.write(stream)
                    stream.write(',"actual":'); head_store.write(stream); stream.write('}')
                raise ValueError('增量与独立全量的语义事实不一致，已阻止发布')
            count = len(reference['variables'])
        for path in paths: no_links(path).unlink()
        work.rmdir()
        return dict(state='PASSED', variables=count, reextracted_units=units,
                    classification_mismatches=0, semantic_mismatches=0)
    except BaseException as exc:
        write_json(work/'failure.json', dict(error=type(exc).__name__+': '+str(exc)))
        raise
