"""Bounded read-only status and checkpoint hashing over the authority graph.

This is a consumer, not a solver or a replacement evidence format. It computes
the existing clean_report/ECRA_MERKLE_V1 contract without restoring its objects.
"""
import codecs
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile

from .scan_store import connect_readonly, _decode
from .scan_persistence import RUNTIME_KEYS, runtime
from .shared_json import _literal
from .workspace import no_links

REVIEW_FIELDS = frozenset({'review','review_state','review_status','review_result',
                           'effective_decision','decision_label','status'})
STATIC_STATUS = 'NEED_OPENCODE_REVIEW'
MISSING = object()


def _child(conn, node, key):
    row=conn.execute('SELECT child FROM edges WHERE parent=? AND key=?',(node,key)).fetchone()
    if row is None:raise KeyError(key)
    return row[0]


def _root(conn, name):
    row=conn.execute('SELECT node FROM roots WHERE name=?',(name,)).fetchone()
    if row is None:raise KeyError(name)
    return row[0]


def _small_value(conn,node):
    """Only called for selected status metadata, never complete report roots."""
    row=conn.execute('SELECT kind,value FROM nodes WHERE id=?',(node,)).fetchone()
    if row is None:raise ValueError('静态状态字段引用缺失')
    kind,value=row
    if kind not in {'list','object'}:return _decode(kind,value)
    result={} if kind=='object' else []
    for key,child in conn.execute('SELECT key,child FROM edges WHERE parent=? ORDER BY ordinal',(node,)):
        value=_small_value(conn,child)
        if kind=='object':result[key]=value
        else:result.append(value)
    return result


def _field(conn,node,key,default=None):
    try:return _small_value(conn,_child(conn,node,key))
    except KeyError:return default


def status_report(out):
    """Complete review identities/count inputs, with no access/call payloads."""
    out=no_links(out)
    with closing(connect_readonly(out/'scan.db')) as conn:
        conn.execute('BEGIN')
        root=_root(conn,'report')
        coverage=_child(conn,root,'coverage')
        result=dict(analysis_status=_field(conn,root,'analysis_status'),
                    coverage=dict(variables_total=_field(conn,coverage,'variables_total')))
        if result['analysis_status'] is None:raise ValueError('静态报告缺少分析状态')
        saved_status=_field(conn,root,'run_status',MISSING)
        if saved_status is not MISSING:result['run_status']=saved_status
        for relation in ['findings','review_safe_samples']:
            try:array=_child(conn,root,relation)
            except KeyError:
                if relation=='findings':raise ValueError('静态报告缺少完整候选列表')
                continue
            if conn.execute('SELECT kind FROM nodes WHERE id=?',(array,)).fetchone()[0]!='list':
                raise ValueError('静态报告候选列表格式无效')
            values=[]
            for (node,) in conn.execute('SELECT child FROM edges WHERE parent=? ORDER BY ordinal',(array,)):
                if conn.execute('SELECT kind FROM nodes WHERE id=?',(node,)).fetchone()[0]!='object':
                    raise ValueError('静态候选身份不是对象')
                fields={key:_small_value(conn,child) for key,child in conn.execute(
                    "SELECT key,child FROM edges WHERE parent=? AND key IN ('finding_id','symbol_id','static_classification') ORDER BY ordinal",(node,))}
                values.append(fields)
            result[relation]=values
        try:diff=_child(conn,root,'git_diff')
        except KeyError:pass
        else:
            kind,length=conn.execute('SELECT kind,length FROM nodes WHERE id=?',(diff,)).fetchone()
            if kind=='null' or (kind=='object' and length==0):result['git_diff']=None if kind=='null' else {}
            else:
                selected=_child(conn,diff,'selected_symbol_ids')
                result['git_diff']=dict(selected_symbol_ids=_small_value(conn,selected))
        try:risk=_child(conn,root,'risk_summary')
        except KeyError:pass
        else:
            value=_field(conn,risk,'total_variables',MISSING)
            result['risk_summary']={} if value is MISSING else dict(total_variables=value)
    overlay=runtime(out,with_reviews=False).get('report',{})
    if 'run_status' in overlay:result['run_status']=overlay['run_status']
    if 'risk_summary' in overlay:
        result['risk_summary']=({} if 'total_variables' not in overlay['risk_summary'] else
                                dict(total_variables=overlay['risk_summary']['total_variables']))
    return result


def runtime_inputs(out):
    """Metadata for the original runtime summaries, never static publication.

    Accesses, conflict products, calls and global solver relations stay in the
    authority. The caller must verify the full report/input closure first.
    """
    variable_fields={'symbol_id','name','qualified_name','static_classification','resource_kind',
        'definition_file','definition_line','kind','coverage_source','parse_status','audit_status',
        'definitions','declarations'}
    finding_fields={'finding_id','symbol_id','static_classification','rules','definition'}
    with closing(connect_readonly(no_links(out)/'scan.db')) as conn:
        conn.execute('BEGIN')
        def records(root,key,fields,*,optional=False):
            try:array=_child(conn,root,key)
            except KeyError:
                if optional:return []
                raise
            if conn.execute('SELECT kind FROM nodes WHERE id=?',(array,)).fetchone()[0]!='list':
                raise ValueError('运行时摘要的权威关系不是有序列表：'+key)
            result=[]
            for (node,) in conn.execute('SELECT child FROM edges WHERE parent=? ORDER BY ordinal',(array,)):
                if conn.execute('SELECT kind FROM nodes WHERE id=?',(node,)).fetchone()[0]!='object':
                    raise ValueError('运行时摘要的身份记录不是对象：'+key)
                result.append({key:_small_value(conn,child) for key,child in conn.execute(
                    'SELECT key,child FROM edges WHERE parent=? ORDER BY ordinal',(node,)) if key in fields})
            return result
        facts_root=_root(conn,'facts');report_root=_root(conn,'report')
        facts=dict(variables=records(facts_root,'variables',variable_fields))
        coverage=_child(conn,report_root,'coverage')
        report=dict(analysis_status=_field(conn,report_root,'analysis_status'),limitations=[],
            coverage={key:_field(conn,coverage,key) for key in ('audit_scope','project_root')
                      if conn.execute('SELECT 1 FROM edges WHERE parent=? AND key=?',(coverage,key)).fetchone()},
            findings=records(report_root,'findings',finding_fields))
        try:classification=_child(conn,coverage,'static_classification')
        except KeyError:pass
        else:
            total=_field(conn,classification,'total',MISSING)
            report['coverage']['static_classification']={} if total is MISSING else dict(total=total)
        if conn.execute("SELECT 1 FROM edges WHERE parent=? AND key='review_safe_samples'",(report_root,)).fetchone():
            report['review_safe_samples']=records(report_root,'review_safe_samples',finding_fields)
        try:diff=_child(conn,report_root,'git_diff')
        except KeyError:pass
        else:
            kind,length=conn.execute('SELECT kind,length FROM nodes WHERE id=?',(diff,)).fetchone()
            if kind=='null' or (kind=='object' and length==0):report['git_diff']=None if kind=='null' else {}
            else:
                report['git_diff']=dict(selected_symbol_ids=_small_value(conn,_child(conn,diff,'selected_symbol_ids')))
                reasons=_field(conn,diff,'fallback_reasons',MISSING)
                if reasons is not MISSING:report['git_diff']['fallback_reasons']=reasons
    return facts,report


def clean_report_digest(database, *, work):
    """Existing logical_digest(clean_report(report)), using a disk-backed memo.

    Every field, scalar type, list order and duplicate is hashed. Only the
    historical clean_report transformation is applied, including its forced
    finding status. Strings are quoted incrementally, never loaded whole.
    """
    database=no_links(database);work=no_links(work);work.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='report-digest-',dir=work) as folder:
        with closing(connect_readonly(database)) as conn,closing(sqlite3.connect(Path(folder)/'memo.db')) as memo:
            conn.execute('BEGIN')
            memo.execute('PRAGMA cache_size=-8192');memo.execute('PRAGMA journal_mode=OFF')
            memo.execute('PRAGMA synchronous=OFF')
            memo.execute('CREATE TABLE hashes(node INTEGER,scope TEXT,hash BLOB NOT NULL,PRIMARY KEY(node,scope)) WITHOUT ROWID')
            active=set()
            def children(node,kind,scope):
                order='key COLLATE BINARY' if kind=='object' else 'ordinal'
                status_inserted=False
                for key,child in conn.execute('SELECT key,child FROM edges WHERE parent=? ORDER BY '+order,(node,)):
                    if scope=='report' and key in RUNTIME_KEYS:continue
                    if scope=='finding':
                        if not status_inserted and key>='status':
                            yield 'status',None,'status';status_inserted=True
                        if key in REVIEW_FIELDS:continue
                    child_scope=('findings' if scope=='report' and key=='findings' else
                                 'finding' if scope=='findings' else 'opaque')
                    yield key,child,child_scope
                if scope=='finding' and not status_inserted:yield 'status',None,'status'
            def visit(node,scope):
                if scope=='status':return hashlib.sha256(b'S'+_literal(STATIC_STATUS).encode('utf-8')).digest()
                cached=memo.execute('SELECT hash FROM hashes WHERE node=? AND scope=?',(node,scope)).fetchone()
                if cached is not None:return cached[0]
                identity=node,scope
                if identity in active:raise ValueError('静态报告包含循环引用')
                row=conn.execute('SELECT kind,length,length(value) FROM nodes WHERE id=?',(node,)).fetchone()
                if row is None:raise ValueError('静态报告引用缺失')
                kind,length,payload_length=row
                if kind not in {'object','list'} and payload_length!=length:
                    raise ValueError('静态报告标量字节长度无效')
                if ((scope in {'report','finding'} and kind!='object')
                        or (scope=='findings' and kind!='list')):raise ValueError('静态报告结构无效')
                active.add(identity)
                try:
                    if kind in {'object','list'}:
                        hashed=hashlib.sha256(b'D' if kind=='object' else b'L');count=0;previous=None
                        for key,child,child_scope in children(node,kind,scope):
                            if kind=='object':
                                if previous==key:raise ValueError('静态报告映射键重复')
                                previous=key
                                hashed.update(hashlib.sha256(b'S'+_literal(key).encode('utf-8')).digest())
                            hashed.update(visit(child,child_scope));count+=1
                        hashed.update(str(count).encode('ascii'))
                    elif kind=='str':
                        hashed=hashlib.sha256(b'S"');decoder=codecs.getincrementaldecoder('utf-8')(errors='surrogatepass')
                        for offset in range(0,length,1024**2):
                            payload=conn.execute('SELECT substr(value,?,1048576) FROM nodes WHERE id=?',(offset+1,node)).fetchone()[0]
                            text=decoder.decode(payload,final=offset+len(payload)==length)
                            hashed.update(json.encoder.encode_basestring(text)[1:-1].encode('utf-8'))
                        hashed.update(b'"')
                    else:
                        payload=conn.execute('SELECT value FROM nodes WHERE id=?',(node,)).fetchone()[0]
                        hashed=hashlib.sha256(b'S'+_literal(_decode(kind,payload)).encode('utf-8'))
                    result=hashed.digest();memo.execute('INSERT INTO hashes VALUES (?,?,?)',(node,scope,result));return result
                finally:active.remove(identity)
            root=_root(conn,'report')
            _child(conn,root,'findings')
            try:return visit(root,'report').hex()
            finally:
                visit=None
                active.clear()
