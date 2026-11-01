"""Strict ordered/typed native comparison without loading complete fact graphs.

Inputs must be full canonical graphs. Legacy JSON can be streamed into one by
publish_json_scan; original JSON/results are never modified. Only the existing
clean_report contract and explicitly documented execution envelope are removed
from the comparison hash. Every other field, order and duplicate is retained.
"""
import argparse
from contextlib import ExitStack,closing
import itertools
import json
from pathlib import Path
import sys

TOOL=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(TOOL))
from ecra.scan_store import EvidenceProvider,connect_readonly,_hash_start,_hash_edge,_wire_value
from ecra.scan_persistence import RUNTIME_KEYS

REVIEW_FIELDS=frozenset(['review','review_state','review_status','review_result','effective_decision','decision_label'])
READ_TIMINGS=frozenset(['read_started_ns','read_completed_ns'])
STATUS='NEED_OPENCODE_REVIEW'
payload=STATUS.encode('utf-8');hasher=_hash_start('str',len(payload));hasher.update(payload);STATUS_HASH=hasher.hexdigest()


class NormalizedGraph:
    def __init__(self,connection,record=lambda _:None):
        self.conn=connection;self.record=record

    def root(self,name):
        row=self.conn.execute('SELECT node FROM roots WHERE name=?',(name,)).fetchone()
        if row is None:raise ValueError('Missing complete root: '+name)
        return row[0]

    def metadata(self,node):
        if node is None:return dict(kind='str',hash=STATUS_HASH,length=len(payload))
        row=self.conn.execute('SELECT kind,hash,length FROM nodes WHERE id=?',(node,)).fetchone()
        if row is None:raise ValueError('Missing evidence node')
        return dict(row)

    def peek(self,node):
        result=self.metadata(node)
        if node is None:result['value']=STATUS;return result
        if result['kind'] not in {'object','list'} and result['length']<=4096:
            value=self.conn.execute('SELECT value FROM nodes WHERE id=?',(node,)).fetchone()[0]
            result.update(_wire_value(result['kind'],value))
        return result

    def children(self,node,scope,path):
        kind=self.metadata(node)['kind']
        omit=(frozenset(RUNTIME_KEYS)|{'generated_at','fingerprint'} if scope=='report' else
            REVIEW_FIELDS if scope=='finding' else {'results_root'} if scope=='workspace' else
            READ_TIMINGS if scope=='input-row' else frozenset())
        status_found=False
        for ordinal,key,child in self.conn.execute('SELECT ordinal,key,child FROM edges WHERE parent=? ORDER BY ordinal',(node,)):
            part=key if kind=='object' else ordinal;location=[*path,part]
            if key in omit:
                self.record(dict(path=location,node=child,original=self.peek(child)));continue
            child_scope='opaque'
            if scope=='report':child_scope={'findings':'findings','workspace':'workspace','coverage':'coverage'}.get(key,'opaque')
            elif scope=='findings':child_scope='finding'
            elif scope=='coverage' and key=='consumed_inputs':child_scope='input-map'
            elif scope=='input-map':child_scope='input-row'
            if scope=='finding' and key=='status':
                status_found=True
                if self.metadata(child)['hash']!=STATUS_HASH:self.record(dict(path=location,node=child,original=self.peek(child)))
                child=None
            yield dict(key=part,node=child,scope=child_scope,path=location)
        if scope=='finding' and not status_found:
            yield dict(key='status',node=None,scope='opaque',path=[*path,'status'])

    def hash(self,node,scope='opaque',path=()):
        meta=self.metadata(node)
        if scope=='opaque':return meta['hash']
        required={'report':'object','findings':'list','finding':'object','workspace':'object','coverage':'object','input-map':'object'}
        if scope in required and meta['kind']!=required[scope]:raise ValueError('Malformed native report at '+repr(path))
        if meta['kind'] not in {'object','list'}:return meta['hash']
        if scope=='report' and not self.conn.execute("SELECT 1 FROM edges WHERE parent=? AND key='findings'",(node,)).fetchone():
            raise ValueError('Complete native report lacks findings')
        # Two streaming passes avoid a list of all input names or findings.
        # The first pass has no envelope side effect.
        kind=meta['kind'];count=0
        original_record=self.record;self.record=lambda _:None
        try:
            for _ in self.children(node,scope,path):count+=1
        finally:self.record=original_record
        hashed=_hash_start(kind,count)
        for child in self.children(node,scope,path):
            _hash_edge(hashed,child['key'] if kind=='object' else None,self.hash(child['node'],child['scope'],child['path']))
        return hashed.hexdigest()


def first_difference(left,right,a,b,scope='opaque',path=()):
    while left.hash(a,scope,path)!=right.hash(b,scope,path):
        ma,mb=left.metadata(a),right.metadata(b)
        if ma['kind']!=mb['kind'] or ma['kind'] not in {'object','list'}:
            return dict(path=list(path),before=left.peek(a),after=right.peek(b))
        ac,bc=left.children(a,scope,path),right.children(b,scope,path)
        for one,two in itertools.zip_longest(ac,bc):
            if one is None or two is None or one['key']!=two['key']:
                return dict(path=list(path),before_edge=None if one is None else one['key'],after_edge=None if two is None else two['key'])
            if left.hash(one['node'],one['scope'],one['path'])!=right.hash(two['node'],two['scope'],two['path']):
                a,b,scope,path=one['node'],two['node'],one['scope'],one['path'];break
        else:return dict(path=list(path),reason='Container count or hash differs')
    return None


def compare(before,after,*,envelope=None):
    before,after=Path(before),Path(after)
    for path in [before,after]:EvidenceProvider(path).validate(deep=True)
    with ExitStack() as stack:
        a=stack.enter_context(closing(connect_readonly(before)));b=stack.enter_context(closing(connect_readonly(after)))
        a.execute('BEGIN');b.execute('BEGIN')
        stream=stack.enter_context(Path(envelope).open('x',encoding='utf-8')) if envelope else None
        def recorder(side):
            return lambda row:stream.write(json.dumps(dict(side=side,**row),ensure_ascii=True)+'\n') if stream else None
        left,right=NormalizedGraph(a,recorder('before')),NormalizedGraph(b,recorder('after'))
        hashes={};differences={}
        for root,scope in [('facts','opaque'),('report','report')]:
            one,two=left.root(root),right.root(root)
            h1,h2=left.hash(one,scope,[root]),right.hash(two,scope,[root]);hashes[root]=dict(before=h1,after=h2)
            # Envelope entries already emitted above; mismatch traversal is read-only.
            left.record=right.record=lambda _:None
            differences[root]=first_difference(left,right,one,two,scope,[root]) if h1!=h2 else None
            left.record,right.record=recorder('before'),recorder('after')
        return dict(passed=not any(differences.values()),hashes=hashes,differences=differences,
            scope=__doc__,before=str(before),after=str(after),deep_integrity_checked=True,
            complete_fact_graph_restore=False,large_native_G1='Requires matching independently native inputs and receipts; this tool alone is not G1')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before',type=Path,required=True);parser.add_argument('--after',type=Path,required=True)
    parser.add_argument('--receipt',type=Path,required=True);parser.add_argument('--envelope',type=Path,required=True)
    args=parser.parse_args()
    if args.receipt.exists() or args.envelope.exists():raise FileExistsError('Preserve previous comparison receipts')
    args.receipt.parent.mkdir(parents=True,exist_ok=True);args.envelope.parent.mkdir(parents=True,exist_ok=True)
    try:result=compare(args.before,args.after,envelope=args.envelope)
    except Exception as exc:
        result=dict(passed=False,error=str(exc),error_type=type(exc).__name__,scope=__doc__,before=str(args.before),after=str(args.after))
    with args.receipt.open('x',encoding='utf-8') as stream:json.dump(result,stream,ensure_ascii=True,indent=2)
    print(json.dumps(dict(passed=result['passed'],differences=result.get('differences'),error=result.get('error')),ensure_ascii=True))
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
