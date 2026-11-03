"""Read-only archive comparison; never changes native Git Diff or decisions.

Canonical identity is exact, including TU/instance qualifiers. A full facts or
report hash change conservatively invalidates evidence equality for every shared
object. This is a navigation aid, not the strict same-input G1 proof.
"""
from contextlib import closing
import json
from pathlib import Path

from ..scan_identity import query as identity
from ..scan_store import EvidenceProvider, connect_readonly
from ..workspace import no_links

KINDS = {'', 'ADDED', 'NOT_OBSERVED', 'EVIDENCE_CHANGED', 'EVIDENCE_IDENTICAL'}


def _provider(folder):
    folder = no_links(folder)
    if no_links(folder/'storage.json').exists() and not no_links(folder/'manifest.json').is_file():
        raise ValueError('未发布的扫描任务不能作为历史对比输入')
    provider = EvidenceProvider(no_links(folder/'scan.db'))
    binding = provider.metadata()
    if binding['scan_id'] != folder.name:
        raise ValueError('归档目录与扫描身份不一致，拒绝对比')
    manifest = no_links(folder/'manifest.json')
    if manifest.is_file():
        if manifest.stat().st_size > 1024*1024:
            raise ValueError('归档显示清单过大，拒绝对比')
        value = json.loads(manifest.read_text('utf-8'))
        if not isinstance(value, dict):
            raise ValueError('归档清单格式无效')
        if value.get('format') == 'ECRA_LOCAL_SCAN':
            if value.get('state') != 'STATIC_VALIDATED' or any(value.get(key) != binding[key] for key in
                    ('scan_id', 'project_id', 'facts_hash', 'report_hash')):
                raise ValueError('本机发布清单未校验或与静态库不一致，拒绝对比')
    try:
        degraded = provider.node(provider.resolve('provenance', ['legacy_degraded']), limit=1).get('value') is True
    except KeyError:
        degraded = False
    if degraded:
        raise ValueError('缺证据旧原件不能进行可信对象对比；请保留原件并补齐证据')
    return provider, binding


def compare_archives(before, after, *, search='', change='', offset=0, limit=50):
    EvidenceProvider._bounds(offset, limit)
    if limit > 100 or offset > 2**63-1:
        raise ValueError('对比分页要求 limit=1–100，offset为有效非负整数')
    if not isinstance(search, str) or len(search) > 256 or not isinstance(change, str) or change not in KINDS:
        raise ValueError('对比检索须为不超过256字的文本及已支持的变化类型')
    old, old_binding = _provider(Path(before))
    new, new_binding = _provider(Path(after))
    if old_binding['scan_id'] == new_binding['scan_id']:
        raise ValueError('请选择两个不同扫描批次，方向为基准→当前')
    if old_binding['project_id'] != new_binding['project_id']:
        raise ValueError('工程身份不同，不能按变量名关联；请选择同一工程的归档')
    same_roots = all(old_binding[key] == new_binding[key] for key in ('facts_hash', 'report_hash'))
    kind = "CASE WHEN a.symbol_id IS NULL THEN 'ADDED' WHEN b.symbol_id IS NULL THEN 'NOT_OBSERVED' "
    kind += "WHEN ? AND na.hash=nb.hash THEN 'EVIDENCE_IDENTICAL' ELSE 'EVIDENCE_CHANGED' END"
    columns = """coalesce(b.symbol_id,a.symbol_id) AS symbol_id,
        a.name AS before_name,b.name AS after_name,
        a.static_classification AS before_classification,b.static_classification AS after_classification,
        a.definition_file AS before_file,a.definition_line AS before_line,
        b.definition_file AS after_file,b.definition_line AS after_line,
        a.node AS before_node,b.node AS after_node,""" + kind + ' AS change'
    # Two indexed left joins implement a full outer join on all supported
    # Portable SQLite versions. Rows stay in SQLite, never a full Python list.
    common = ' LEFT JOIN nodes nb ON nb.id=b.node LEFT JOIN baseline.nodes na ON na.id=a.node'
    cte = ('WITH compared AS (SELECT ' + columns +
           ' FROM symbols b LEFT JOIN baseline.symbols a ON a.symbol_id=b.symbol_id' + common +
           ' UNION ALL SELECT ' + columns +
           ' FROM baseline.symbols a LEFT JOIN symbols b ON b.symbol_id=a.symbol_id' + common +
           ' WHERE b.symbol_id IS NULL) ')
    terms, params = [], [same_roots, same_roots]
    if search:
        terms.append("(instr(symbol_id,?)>0 OR instr(coalesce(before_name,''),?)>0 OR instr(coalesce(after_name,''),?)>0)")
        params.extend([search]*3)
    if change:
        terms.append('change=?'); params.append(change)
    where = ' WHERE ' + ' AND '.join(terms) if terms else ''
    with closing(connect_readonly(new.path)) as conn:
        conn.execute('PRAGMA temp_store=FILE')
        conn.execute('PRAGMA cache_size=-8192')
        conn.execute('ATTACH DATABASE ? AS baseline', (old.path.resolve().as_uri()+'?mode=ro',))
        conn.execute('PRAGMA baseline.cache_size=-8192')
        counts = {row['change']: row['total'] for row in conn.execute(cte+
            'SELECT change,count(*) AS total FROM compared GROUP BY change', [same_roots, same_roots])}
        total = conn.execute(cte+'SELECT count(*) FROM compared'+where, params).fetchone()[0]
        rows = [dict(row) for row in conn.execute(cte+'SELECT * FROM compared'+where+
            ' ORDER BY symbol_id COLLATE BINARY LIMIT ? OFFSET ?', [*params, limit, offset])]
    roots = {row['name']: row for row in old.roots()}
    current = {row['name']: row for row in new.roots()}
    root_comparison = [dict(name=name, before=roots.get(name), after=current.get(name),
                           identical=name in roots and name in current and roots[name]['hash']==current[name]['hash'])
                       for name in sorted(roots.keys() | current.keys())]
    return dict(before=dict(binding=old_binding, identity=identity(old)),
                after=dict(binding=new_binding, identity=identity(new)),
                profile_equal=old_binding['profile_id']==new_binding['profile_id'],
                roots=root_comparison, counts=counts, total=total, items=rows, offset=offset, limit=limit,
                next_offset=offset+len(rows) if offset+len(rows)<total else None,
                proof_scope='ARCHIVED_CANONICAL_OBJECTS_CONSERVATIVE_FULL_SCAN_FINGERPRINT',
                note='本轮未观察到不等于已修复。证据指纹相同不表示当前源码有效，不自动继承人工确认，也不替代重新扫描与完整证据核对。')
