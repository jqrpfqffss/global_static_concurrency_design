"""Frozen3cf2ff9 full validator; helpers retain unchanged encoding/projection contract."""
from contextlib import closing
from pathlib import Path
import itertools,sqlite3
from ecra.scan_store import connect_readonly,_hash_start,_hash_edge,_scalar,_decode,_project,SCHEMA
ORIGINAL_LF_SHA256='2ae0baba1580a5d7392fc6a1ef47c86edc48632fc756328c5ffb42ea4633be13'

def validate_original(self, *, deep=False):
    with closing(connect_readonly(self.path)) as conn:
        # Keep graph hashes and rebuilt query projections on one read view.
        conn.execute('BEGIN')
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
            for node in conn.execute('SELECT id,hash,kind,length,typeof(value) AS payload_type,'
                                     'length(value) AS payload_bytes FROM nodes ORDER BY id'):
                if node['kind'] not in {'object','list','null','bool','int','float','str'}:
                    raise ValueError('未知证据编码类型')
                if type(node['length']) is not int or node['length'] < 0:
                    raise ValueError('证据长度类型损坏')
                if node['kind'] in {'object', 'list'}:
                    if node['payload_type'] != 'null':
                        raise ValueError('容器证据包含未编码的标量数据')
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
                    if node['payload_type'] != 'blob' or node['payload_bytes'] != node['length']:
                        raise ValueError('证据标量字节长度/编码类型损坏，拒绝不完整哈希范围')
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
            # Rebuild only projections in a file-backed disposable index,
            # comparing every row against this same immutable read view.
            import tempfile
            with tempfile.TemporaryDirectory(prefix='ecra projection validation ') as folder:
                with closing(sqlite3.connect(Path(folder)/'projection.db')) as expected:
                    expected.executescript(SCHEMA)
                    expected.execute('PRAGMA foreign_keys=OFF')
                    expected.execute('PRAGMA cache_size=-8192')
                    expected.execute('PRAGMA temp_store=FILE')
                    for name in ('facts', 'report'):
                        root = conn.execute('SELECT node FROM roots WHERE name=?', (name,)).fetchone()[0]
                        _project(expected, name, root, source=conn)
                    for table, order in [('symbols', 'ordinal'), ('records', 'dataset,relation,ordinal')]:
                        actual = (tuple(row) for row in conn.execute('SELECT * FROM ' + table + ' ORDER BY ' + order))
                        rebuilt = expected.execute('SELECT * FROM ' + table + ' ORDER BY ' + order)
                        if any(a != b for a, b in itertools.zip_longest(actual, rebuilt)):
                            raise ValueError('静态库查询投影与权威证据不一致: ' + table)
        return dict(scan)
