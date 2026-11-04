"""Verify unchanged evidence and preserve cross-scan human-event causality.

An ordered root witness binds the old input fingerprint to the report root
already bound by the original human event. Names and timestamps prove nothing.
"""
from contextlib import closing
import hashlib
import json
import re
import sqlite3

from .scan_store import _hash_start, _hash_edge, connect_readonly

SHA = re.compile(r'^[0-9a-f]{64}$')


def input_witness(provider):
    with closing(connect_readonly(provider.path)) as conn:
        fields = [dict(key=r[0], hash=r[1]) for r in conn.execute(
            "SELECT e.key,n.hash FROM roots r JOIN edges e ON e.parent=r.node "
            "JOIN nodes n ON n.id=e.child WHERE r.name='report' ORDER BY e.ordinal")]
        row = conn.execute("SELECT n.kind,n.value FROM roots r JOIN edges e ON e.parent=r.node "
            "JOIN nodes n ON n.id=e.child WHERE r.name='report' AND e.key='fingerprint'").fetchone()
    if row is None or row[0] != 'str':
        return None
    value = bytes(row[1]).decode('utf-8')
    if not SHA.fullmatch(value):
        return None
    return dict(version=1, kind='FULL_INPUT_AND_FACTS_V1', input_fingerprint=value, report_fields=fields)


def verify_witness(value, provider):
    """Return False for changed inputs; reject malformed/forged proofs."""
    proof = value.get('inheritance')
    if proof is None:
        return False
    if (not isinstance(proof, dict) or set(proof) != {'version','kind','input_fingerprint','report_fields'}
            or type(proof['version']) is not int or proof['version'] != 1
            or proof['kind'] != 'FULL_INPUT_AND_FACTS_V1'
            or not isinstance(proof['input_fingerprint'], str) or not SHA.fullmatch(proof['input_fingerprint'])
            or not isinstance(proof['report_fields'], list) or not 1 <= len(proof['report_fields']) <= 10000):
        raise ValueError('确认继承证明格式无效')
    root = _hash_start('object', len(proof['report_fields']))
    seen = set()
    fp_hash = _hash_start('str', len(proof['input_fingerprint'].encode()))
    fp_hash.update(proof['input_fingerprint'].encode())
    for field in proof['report_fields']:
        if (not isinstance(field, dict) or set(field) != {'key','hash'}
                or not isinstance(field['key'], str) or field['key'] in seen
                or not isinstance(field['hash'], str) or not SHA.fullmatch(field['hash'])):
            raise ValueError('确认继承报告根见证无效')
        seen.add(field['key'])
        if field['key'] == 'fingerprint' and field['hash'] != fp_hash.hexdigest():
            raise ValueError('确认继承输入指纹未绑定到原报告')
        _hash_edge(root, field['key'], field['hash'])
    if 'fingerprint' not in seen or root.hexdigest() != value['binding']['report_hash']:
        raise ValueError('确认继承报告根不一致')
    current = input_witness(provider)
    binding = provider.metadata()
    if (current is None or current['input_fingerprint'] != proof['input_fingerprint']
            or binding['facts_hash'] != value['binding']['facts_hash']):
        return False
    with closing(connect_readonly(provider.path)) as conn:
        row = conn.execute('SELECT n.hash FROM symbols s JOIN nodes n ON n.id=s.node WHERE s.symbol_id=?',
            (value['symbol_id'],)).fetchone()
    if row is None:
        return False
    fingerprint = hashlib.sha256('\0'.join([value['symbol_id'], row[0],
        value['binding']['facts_hash'], value['binding']['report_hash']]).encode()).hexdigest()
    if fingerprint != value['fingerprint']:
        raise ValueError('确认继承原事件与完整证据不一致')
    return True


def validate_prior(row, provider):
    from .human_reviews import ReviewStore, SCHEMA
    sid, current, source, fingerprint, hashed, raw = row
    if hashlib.sha256(raw.encode()).hexdigest() != hashed or provider.fingerprint(sid) != current:
        raise ValueError('历史确认与当前证据引用不一致')
    value = json.loads(raw)
    if not isinstance(value, dict) or set(value) not in (
            {'binding','symbol_id','fingerprint','events'}, {'binding','symbol_id','fingerprint','events','inheritance'}):
        raise ValueError('历史确认载荷无效')
    old, binding = value['binding'], provider.metadata()
    if (not isinstance(old, dict) or set(old) != {'scan_id','project_id','facts_hash','report_hash'}
            or old['scan_id'] != source or old['project_id'] != binding['project_id']
            or source == binding['scan_id'] or value['symbol_id'] != sid or value['fingerprint'] != fingerprint
            or not isinstance(value['events'], list)):
        raise ValueError('历史确认扫描/对象身份不一致')
    check = ReviewStore.__new__(ReviewStore)
    check.binding = old
    with closing(sqlite3.connect(':memory:')) as conn:
        conn.executescript(SCHEMA)
        for event in value['events']:
            check._validate(event)
        for event in sorted(value['events'], key=lambda e: (e['revision'], e['event_id'])):
            if event['symbol_id'] != sid or event['fingerprint'] != fingerprint:
                raise ValueError('历史确认引用其他对象/证据')
            check._insert(conn, event)
    return value, verify_witness(value, provider)


def references(values):
    """All visible historical heads, including those requiring rechecking."""
    result = []
    for value in values:
        parents = {p for e in value['events'] for p in e['parents']}
        result.extend(dict(scan_id=value['binding']['scan_id'], event_id=e['event_id'], fingerprint=e['fingerprint'])
            for e in value['events'] if e['event_id'] not in parents)
    return sorted(result, key=lambda ref: (ref['scan_id'], ref['event_id']))


def validate_lineage(values, events):
    known = {(e['symbol_id'],v['binding']['scan_id'], e['event_id'], e['fingerprint'])
        for v in values for e in v['events']}
    all_events=[*events, *(e for v in values for e in v['events'])]
    graph={}
    for event in all_events:
        key=(event['scan_id'],event['event_id'])
        graph[key]=[(event['scan_id'],p) for p in event['parents']]
        for ref in event.get('evidence_parents', []):
            if (event['symbol_id'],ref['scan_id'], ref['event_id'], ref['fingerprint']) not in known:
                raise ValueError('人工确认缺少跨扫描前驱；必须携带完整来源历史')
            graph[key].append((ref['scan_id'],ref['event_id']))
    # Iterative traversal also handles very long review histories.
    visiting,done=set(),set()
    for start in graph:
        stack=[(start,False)]
        while stack:
            node,leave=stack.pop()
            if leave:
                visiting.remove(node);done.add(node)
            elif node not in done:
                if node in visiting:
                    raise ValueError('跨扫描人工事件前驱形成循环')
                visiting.add(node);stack.append((node,True))
                stack.extend((parent,False) for parent in graph.get(node,[]))


def inherited_state(rows, provider):
    values, candidates = [], []
    for row in rows:
        value, verified = validate_prior(row, provider)
        values.append(value)
        parents = {p for e in value['events'] for p in e['parents']}
        candidates.extend((e,verified) for e in value['events'] if e['event_id'] not in parents)
    validate_lineage(values, [])
    superseded = {(r['scan_id'], r['event_id'], r['fingerprint'])
        for v in values for e in v['events'] for r in e.get('evidence_parents', [])}
    candidates = [(e,valid) for e,valid in candidates if (e['scan_id'], e['event_id'], e['fingerprint']) not in superseded]
    unverified = any(not valid for e,valid in candidates)
    candidates = [e for e,valid in candidates if valid]
    decisions = {(e['decision'], e['handling_status']) for e in candidates}
    conflict = len(candidates) > 1
    decision, handling = next(iter(decisions)) if len(decisions) == 1 and not conflict else ('CONFLICT' if conflict else 'RECHECK_REQUIRED', 'TODO')
    if decision == 'PENDING' or unverified:
        decision = 'RECHECK_REQUIRED'
    return dict(decision=decision, handling_status=handling, conflict=conflict,
        inherited=bool(candidates) and decision != 'RECHECK_REQUIRED', inherited_sources=candidates)
