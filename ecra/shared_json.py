"""Lossless, streamed JSON storage for read-only evidence object graphs.

This codec changes storage only. References preserve lists, order, duplicates,
JSON scalar types and every record field. Consumers receive ordinary objects.
"""
import json
import hashlib
from functools import lru_cache
from pathlib import Path


HEADER = b'{"_ecra_shared_json":'
MAGIC = HEADER + b'1,'
DEFAULT_THRESHOLD = 64 * 1024 * 1024


def _signature_hash(signature):
    return hash(signature)


@lru_cache(maxsize=32768)
def _short_string(value):
    quoted = json.encoder.encode_basestring(value)
    return quoted, len(quoted.encode('utf-8'))


def _quoted(value):
    return _short_string(value)[0] if len(value) <= 256 else json.encoder.encode_basestring(value)


def _string_bytes(value):
    return (_short_string(value)[1] if len(value) <= 256 else
            len(json.encoder.encode_basestring(value).encode('utf-8')))


def _literal(value):
    if isinstance(value, str):
        return _quoted(value)
    if value is None:
        return 'null'
    if type(value) is bool:
        return 'true' if value else 'false'
    if type(value) is int:
        return str(value)
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def _write_chunks(stream, chunks):
    """Bound encoding/write overhead without collecting the document."""
    parts, size = [], 0
    for chunk in chunks:
        parts.append(chunk)
        size += len(chunk)
        if size >= 65536:
            stream.write(''.join(parts))
            parts.clear()
            size = 0
    if parts:
        stream.write(''.join(parts))


def logical_digest(value):
    """Hash complete JSON values once per shared node, with sorted dict keys."""
    memo, active = {}, set()

    def visit(item):
        if not isinstance(item, (dict, list, tuple)):
            return hashlib.sha256(b'S'+_literal(item).encode('utf-8')).digest()
        ident = id(item)
        if ident in active:
            raise ValueError('完整证据摘要不能包含循环结构')
        if ident in memo:
            return memo[ident]
        active.add(ident)
        sha = hashlib.sha256(b'D' if isinstance(item, dict) else b'L')
        if isinstance(item, dict):
            for key in sorted(item):
                sha.update(visit(key))
                sha.update(visit(item[key]))
        else:
            for child in item:
                sha.update(visit(child))
        sha.update(str(len(item)).encode('ascii'))
        active.remove(ident)
        memo[ident] = sha.digest()
        return memo[ident]
    try:
        return visit(value).hex()
    finally:
        # Recursive closures otherwise retain their large memo until cyclic GC.
        visit = None
        memo.clear()
        active.clear()


def encoded(path):
    with Path(path).open('rb') as stream:
        return stream.read(len(HEADER)) == HEADER


def encoded_stream(stream):
    position = stream.tell()
    prefix = stream.read(len(HEADER))
    stream.seek(position)
    return prefix == HEADER.decode('ascii')


class Plan:
    def __init__(self, value):
        self.nodes, self.references = [], {}
        identities, signatures, counts, canonical, sizes = {}, {}, [], [], []
        active, keys = set(), set()

        def token_size(token):
            return sizes[token[1]] if token[0] == 'node' else token[-1]

        def scalar(item):
            if item is None:
                return ('null', 4)
            if type(item) is bool:
                return ('bool', item, 4 if item else 5)
            if type(item) is int:
                return ('int', item, len(str(item)))
            if type(item) is float:
                return ('float', item.hex(), len(json.dumps(item)))
            if isinstance(item, str):
                return ('str', item, _string_bytes(item))
            raise TypeError('共享 JSON 不支持此证据值类型: '+type(item).__name__)

        def same_value(left, right):
            if left is right:
                return True
            left_node = isinstance(left, (dict, list, tuple))
            right_node = isinstance(right, (dict, list, tuple))
            if left_node or right_node:
                return left_node and right_node and identities[id(left)] == identities[id(right)]
            return scalar(left) == scalar(right)

        def same_container(left, right):
            # Children have already been canonicalized, so comparison is linear
            # in direct children even for a heavily shared evidence DAG.
            if isinstance(left, dict) != isinstance(right, dict) or len(left) != len(right):
                return False
            if isinstance(left, dict):
                return all(lk == rk and same_value(lv, rv)
                           for (lk, lv), (rk, rv) in zip(left.items(), right.items()))
            return all(same_value(lv, rv) for lv, rv in zip(left, right))

        def visit(item):
            if not isinstance(item, (dict, list, tuple)):
                return scalar(item)
            ident = id(item)
            if ident in active:
                raise ValueError('共享 JSON 不能保存循环证据')
            if ident in identities:
                node = identities[ident]
                counts[node] += 1
                return ('node', node)
            active.add(ident)
            if isinstance(item, dict):
                keys.update(item)
                if any(not isinstance(key, str) for key in item):
                    raise ValueError('共享 JSON 对象字段名必须是字符串')
                signature = ('dict', tuple((key, visit(child)) for key, child in item.items()))
                size = 2 + max(0, len(item)-1) + sum(
                    _string_bytes(key)+1+token_size(child)
                    for key, child in signature[1])
            else:
                signature = ('list', tuple(visit(child) for child in item))
                size = 2 + max(0, len(item)-1) + sum(token_size(child) for child in signature[1])
            active.remove(ident)
            # Retaining every typed child tuple duplicates the complete graph
            # in memory. Keep only its hash and canonical node index instead.
            # Every hit is checked against ALL original direct children and
            # their typed canonical identities; collisions cannot merge facts.
            signature_hash = _signature_hash(signature)
            del signature
            bucket = signatures.get(signature_hash)
            candidates = () if bucket is None else bucket if isinstance(bucket, list) else (bucket,)
            node = next((index for index in candidates if same_container(item, canonical[index])), None)
            if node is None:
                node = len(canonical)
                if bucket is None:
                    signatures[signature_hash] = node
                elif isinstance(bucket, list):
                    bucket.append(node)
                else:
                    signatures[signature_hash] = [bucket, node]
                canonical.append(item)
                counts.append(0)
                sizes.append(size)
            identities[ident] = node
            counts[node] += 1
            return ('node', node)

        try:
            self.logical_bytes = token_size(visit(value))
            self.marker = '$ecra_ref'
            while self.marker in keys:
                self.marker += '_'
            # Child-first order permits one-pass resolution with no forward refs.
            selected = {}
            for index, node in enumerate(canonical):
                if counts[index] > 1:
                    selected[index] = len(self.nodes)
                    self.nodes.append(node)
            # Reuse the identity table instead of allocating a second complete
            # table while all temporary signatures are still alive.
            unselected = []
            for ident, index in identities.items():
                if index in selected:
                    identities[ident] = selected[index]
                else:
                    unselected.append(ident)
            for ident in unselected:
                del identities[ident]
            if not identities:
                identities.clear()
            elif len(unselected) > 3 * len(identities):
                # Compact sparse tables only after signatures are released;
                # this copy contains less than a quarter of the original IDs.
                signatures.clear()
                identities = dict(identities)
            self.references = identities
            identities = {}
        finally:
            visit = None
            identities.clear()
            signatures.clear()
            counts.clear()
            canonical.clear()
            sizes.clear()
            active.clear()
            keys.clear()

    def chunks(self, value, force=False):
        ref = self.references.get(id(value)) if isinstance(value, (dict, list, tuple)) else None
        if ref is not None and not force:
            yield '{' + _quoted(self.marker) + ':' + str(ref) + '}'
        elif isinstance(value, dict):
            yield '{'
            for index, (key, item) in enumerate(value.items()):
                if index:
                    yield ','
                if not isinstance(key, str):
                    # Fact schemas require string keys, as the saved reader does.
                    raise ValueError('共享 JSON 对象字段名必须是字符串')
                yield _quoted(key)
                yield ':'
                yield from self.chunks(item)
            yield '}'
        elif isinstance(value, (list, tuple)):
            yield '['
            for index, item in enumerate(value):
                if index:
                    yield ','
                yield from self.chunks(item)
            yield ']'
        else:
            yield _literal(value)

    def dumps(self, value, force=False):
        return ''.join(self.chunks(value, force))


def write(path, value, threshold=DEFAULT_THRESHOLD):
    from .common import replace_file
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    plan = Plan(value)
    if plan.logical_bytes < threshold:
        from .common import write_json
        write_json(path, value, indent=None)
        return
    temp = path.with_suffix(path.suffix+'.tmp')
    with temp.open('w', encoding='utf-8') as stream:
        stream.write(MAGIC.decode('ascii'))
        stream.write('"reference_key":'+json.dumps(plan.marker)+',"pool":[')
        for index, node in enumerate(plan.nodes):
            if index:
                stream.write(',')
            _write_chunks(stream, plan.chunks(node, force=True))
        stream.write('],"value":')
        _write_chunks(stream, plan.chunks(value))
        stream.write('}')
    replace_file(temp, path)


def read_root(reader):
    """Read root arrays row by row, never allocate their complete JSON text."""
    if reader.peek() == '[':
        reader.take('[')
        value = []
        while reader.peek() != ']':
            value.append(reader.value())
            if reader.peek() == ']':
                break
            reader.take(',')
        reader.take(']')
        return value
    if reader.peek() == '{':
        reader.take('{')
        value = {}
        while reader.peek() != '}':
            key = reader.value()
            if not isinstance(key, str) or key in value:
                raise ValueError('共享 JSON 字段损坏或重复')
            reader.take(':')
            value[key] = read_root(reader) if reader.peek() == '[' else reader.value()
            if reader.peek() == '}':
                break
            reader.take(',')
        reader.take('}')
        return reader.decoder.object_hook(value) if reader.decoder.object_hook else value
    return reader.value()


def prepare_reader(reader, object_hook=None, shared_ids=None, normalize=None):
    """Consume a codec header; position the reader before its logical value."""
    reader.take('{')
    if reader.value() != '_ecra_shared_json':
        raise ValueError('共享 JSON 格式标记缺失')
    reader.take(':')
    if type(version := reader.value()) is not int or version != 1:
        raise ValueError('不支持的共享 JSON 版本')
    reader.take(',')
    if reader.value() != 'reference_key':
        raise ValueError('共享 JSON 引用标记缺失')
    reader.take(':')
    marker = reader.value()
    if not isinstance(marker, str) or not marker:
        raise ValueError('共享 JSON 引用标记无效')
    pool = []

    def resolve(value):
        if marker in value:
            index = value[marker]
            if (len(value) != 1 or type(index) is not int or not 0 <= index < len(pool)):
                raise ValueError('共享 JSON 引用损坏或前向引用，禁止复用证据')
            return pool[index]
        return object_hook(value) if object_hook else value

    reader.decoder = json.JSONDecoder(object_hook=resolve)
    reader.take(',')
    if reader.value() != 'pool':
        raise ValueError('共享 JSON 证据池缺失')
    reader.take(':')
    reader.take('[')
    while reader.peek() != ']':
        node = read_root(reader)
        if not isinstance(node, (dict, list)):
            raise ValueError('共享 JSON 池节点类型无效')
        if normalize:
            node = normalize(node)
        pool.append(node)
        if shared_ids is not None:
            shared_ids.add(id(node))
        if reader.peek() == ']':
            break
        reader.take(',')
    reader.take(']')
    reader.take(',')
    if reader.value() != 'value':
        raise ValueError('共享 JSON 完整数据缺失')
    reader.take(':')
    return pool


def finish_reader(reader):
    reader.take('}')
    if reader.peek():
        raise ValueError('共享 JSON 尾部存在额外数据')


def read(path, object_hook=None, shared_ids=None, normalize=None):
    with Path(path).open(encoding='utf-8-sig') as stream:
        return read_stream(stream, object_hook, shared_ids, normalize)


def read_stream(stream, object_hook=None, shared_ids=None, normalize=None):
    from .json_rows import RowReader
    reader = RowReader(stream)
    prepare_reader(reader, object_hook, shared_ids, normalize)
    value = read_root(reader)
    finish_reader(reader)
    return value


class DatabasePool:
    """Restore JSON cells from a self-contained SQLite evidence pool."""
    TABLES = {'ecra_shared_json_metadata', 'ecra_shared_json_pool'}

    def __init__(self, connection):
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.nodes, self.marker = [], None
        if not tables & self.TABLES:
            return
        if not self.TABLES <= tables:
            raise ValueError('SQLite 共享证据池不完整')
        metadata = list(connection.execute('SELECT version,reference_key FROM ecra_shared_json_metadata'))
        if len(metadata) != 1 or metadata[0][0] != 1 or not isinstance(metadata[0][1], str) or not metadata[0][1]:
            raise ValueError('SQLite 共享证据元数据无效')
        self.marker = metadata[0][1]
        for ident, data in connection.execute('SELECT node_id,data FROM ecra_shared_json_pool ORDER BY node_id'):
            if type(ident) is not int or ident != len(self.nodes):
                raise ValueError('SQLite 共享证据池节点缺失')
            value = self.loads(data)
            if not isinstance(value, (dict, list)):
                raise ValueError('SQLite 共享证据池类型无效')
            self.nodes.append(value)

    def resolve(self, value):
        if self.marker is not None and self.marker in value:
            index = value[self.marker]
            if len(value) != 1 or type(index) is not int or not 0 <= index < len(self.nodes):
                raise ValueError('SQLite 共享证据引用损坏')
            return self.nodes[index]
        return value

    def loads(self, text):
        return json.loads(text, object_hook=self.resolve)
