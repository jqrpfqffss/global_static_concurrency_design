"""Legacy JSON -> the canonical ordered graph, with a disk-backed shared pool.

Only one scalar token and the parser stack live in Python. Containers, duplicate
key checks and shared-codec pool references are held in SQLite. This is an
encoding adapter; it never normalizes, sorts or interprets analysis evidence.
"""
from pathlib import Path
import sqlite3

from .json_rows import RowReader
from .scan_store import _hash_start, _hash_edge, _decode
from .shared_json import encoded_stream


class StreamedGraph:
    def __init__(self, writer):
        self.writer = writer
        self.conn = writer.conn
        self.marker = None
        self.pool_count = 0
        self.conn.execute('CREATE TEMP TABLE IF NOT EXISTS json_pool(ordinal INTEGER PRIMARY KEY,node INTEGER,hash TEXT)')
        self.conn.execute('CREATE TEMP TABLE IF NOT EXISTS json_keys(parent INTEGER,key TEXT,PRIMARY KEY(parent,key))')
        self.conn.execute('DELETE FROM json_pool')
        self.conn.execute('DELETE FROM json_keys')

    def container(self, reader):
        token = reader.peek()
        if token not in {'{', '['}:
            value = reader.value()
            if isinstance(value, (dict, list)):
                raise ValueError('JSON 标量分词损坏')
            return self.writer.put(value)
        kind, end = ('object', '}') if token == '{' else ('list', ']')
        reader.take(token)
        node = self.conn.execute('INSERT INTO nodes(kind,length) VALUES (?,0)', (kind,)).lastrowid
        count = 0
        reference = None
        while reader.peek() != end:
            key = None
            if kind == 'object':
                key = reader.value()
                if not isinstance(key, str):
                    raise ValueError('旧 JSON 对象键必须是字符串')
                try:
                    self.conn.execute('INSERT INTO json_keys VALUES (?,?)', (node, key))
                except sqlite3.IntegrityError as exc:
                    raise ValueError('旧 JSON 对象键重复；不能丢弃原证据') from exc
                reader.take(':')
            child, _ = self.container(reader)
            self.conn.execute('INSERT INTO edges VALUES (?,?,?,?)', (node, count, key, child))
            if self.marker is not None and key == self.marker:
                reference = child
            count += 1
            if reader.peek() == end:
                break
            reader.take(',')
            if reader.peek() == end:
                raise ValueError('旧 JSON 末尾多余逗号')
        reader.take(end)
        self.conn.execute('DELETE FROM json_keys WHERE parent=?', (node,))
        if reference is not None:
            kind_ref, payload = self.conn.execute('SELECT kind,value FROM nodes WHERE id=?', (reference,)).fetchone()
            index = _decode(kind_ref, payload) if kind_ref == 'int' else None
            if count != 1 or index is None or not 0 <= index < self.pool_count:
                raise ValueError('共享 JSON 引用损坏或前向引用；禁止复用证据')
            result = self.conn.execute('SELECT node,hash FROM json_pool WHERE ordinal=?', (index,)).fetchone()
            self.conn.execute('DELETE FROM edges WHERE parent=?', (node,))
            self.conn.execute('DELETE FROM nodes WHERE id=?', (node,))
            return tuple(result)
        hasher = _hash_start(kind, count)
        for key, hashed in self.conn.execute('SELECT e.key,n.hash FROM edges e JOIN nodes n ON n.id=e.child '
                'WHERE e.parent=? ORDER BY e.ordinal', (node,)):
            _hash_edge(hasher, key, hashed)
        hashed = hasher.hexdigest()
        old = self.conn.execute('SELECT id,kind,length FROM nodes WHERE hash=?', (hashed,)).fetchone()
        if old:
            if old[1:] != (kind, count) or not self.writer._same_edges(old[0], node):
                raise ValueError('证据 SHA-256 冲突；拒绝合并')
            self.conn.execute('DELETE FROM edges WHERE parent=?', (node,))
            self.conn.execute('DELETE FROM nodes WHERE id=?', (node,))
            node = old[0]
        else:
            self.conn.execute('UPDATE nodes SET hash=?,length=? WHERE id=?', (hashed, count, node))
        return node, hashed

    def read(self, stream):
        shared = encoded_stream(stream)
        reader = RowReader(stream)
        if shared:
            reader.take('{')
            for index, (key, expected) in enumerate([('_ecra_shared_json', 1), ('reference_key', None)]):
                if index:
                    reader.take(',')
                if reader.value() != key:
                    raise ValueError('共享 JSON 格式标记缺失')
                reader.take(':')
                value = reader.value()
                if key == '_ecra_shared_json':
                    if type(value) is not int or value != expected:
                        raise ValueError('不支持的共享 JSON 版本')
                elif not isinstance(value, str) or not value:
                    raise ValueError('共享 JSON 引用标记无效')
                else:
                    self.marker = value
            reader.take(',')
            if reader.value() != 'pool':
                raise ValueError('共享 JSON 证据池缺失')
            reader.take(':'); reader.take('[')
            while reader.peek() != ']':
                node, hashed = self.container(reader)
                if self.conn.execute('SELECT kind FROM nodes WHERE id=?', (node,)).fetchone()[0] not in {'list', 'object'}:
                    raise ValueError('共享 JSON 池节点类型无效')
                self.conn.execute('INSERT INTO json_pool VALUES (?,?,?)', (self.pool_count, node, hashed))
                self.pool_count += 1
                if reader.peek() == ']':
                    break
                reader.take(',')
                if reader.peek() == ']':
                    raise ValueError('共享 JSON 池末尾多余逗号')
            reader.take(']'); reader.take(',')
            if reader.value() != 'value':
                raise ValueError('共享 JSON 完整数据缺失')
            reader.take(':')
        result = self.container(reader)
        if shared:
            reader.take('}')
        if reader.peek():
            raise ValueError('旧 JSON 尾部存在额外数据')
        self.conn.execute('DELETE FROM json_pool')
        return result


def read_json(path, writer):
    with Path(path).open(encoding='utf-8-sig') as stream:
        return StreamedGraph(writer).read(stream)
