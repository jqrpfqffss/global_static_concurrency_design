"""Shared pagination/counting rules for Studio's three independent dimensions."""
from contextlib import closing
from pathlib import Path

from ..scan_store import EvidenceProvider, connect_readonly

HUMAN_HEADS = """WITH current_heads AS (
 SELECT e.symbol_id,CASE WHEN count(*)>1 THEN 'CONFLICT'
 ELSE min(json_extract(e.payload,'$.decision')) END AS decision,
 CASE WHEN count(*)>1 THEN 'CONFLICT' ELSE min(json_extract(e.payload,'$.handling_status')) END AS handling_status
 FROM human.events e WHERE NOT EXISTS(SELECT 1 FROM human.predecessors p WHERE p.parent_id=e.event_id)
 GROUP BY e.symbol_id), heads AS (
 SELECT c.symbol_id,CASE WHEN c.decision='PENDING' AND EXISTS(
 SELECT 1 FROM human.prior_decisions p WHERE p.symbol_id=c.symbol_id)
 THEN 'RECHECK_REQUIRED' ELSE c.decision END AS decision,c.handling_status FROM current_heads c
 UNION ALL SELECT DISTINCT p.symbol_id,'RECHECK_REQUIRED','TODO' FROM human.prior_decisions p
 WHERE NOT EXISTS(SELECT 1 FROM current_heads c WHERE c.symbol_id=p.symbol_id))
"""


class QueryService:
    def __init__(self, scan_path):
        self.path = Path(scan_path)
        self.evidence = EvidenceProvider(self.path/'scan.db')

    def symbols(self, *, search='', classification='', human_decision='', handling_status='',
                file='',function='',context='',coverage='',ai_state='',diff='',sort='priority',order='asc',offset=0, limit=50):
        self.evidence._bounds(offset, limit)
        sorts={
            'priority':["CASE s.static_classification WHEN 'SUSPECT' THEN 0 WHEN 'UNKNOWN' THEN 1 ELSE 2 END"],
            'name':['s.name COLLATE BINARY'],
            'definition':["coalesce(s.definition_file,'') COLLATE BINARY",'coalesce(s.definition_line,0)'],
            'review_priority':["CASE coalesce(h.decision,'PENDING') WHEN 'PENDING' THEN 0 WHEN 'RECHECK_REQUIRED' THEN 1 "
                "WHEN 'CONFLICT' THEN 2 WHEN 'NEED_MORE_EVIDENCE' THEN 3 WHEN 'CONFIRMED_RISK' THEN 4 "
                "WHEN 'CONFIRMED_SAFE' THEN 5 ELSE 6 END"]}
        if not isinstance(sort,str) or sort not in sorts or order not in {'asc','desc'}:
            raise ValueError('列表排序只接受风险/名称/定义位置/待办优先级和升序/降序')
        ordering=','.join(field+' '+order.upper() for field in sorts[sort])+',s.ordinal ASC'
        terms, args = [], []
        if search:
            terms.append("(instr(s.name,?)>0 OR instr(coalesce(s.definition_file,''),?)>0 OR instr(s.symbol_id,?)>0)")
            args.extend([search]*3)
        if classification:
            terms.append('s.static_classification=?'); args.append(classification)
        if human_decision:
            terms.append("coalesce(h.decision,'PENDING')=?"); args.append(human_decision)
        if handling_status:
            terms.append("coalesce(h.handling_status,'TODO')=?");args.append(handling_status)
        if file:
            terms.append("instr(coalesce(s.definition_file,''),?)>0");args.append(file)
        if coverage:
            terms.append('s.analysis_coverage=?');args.append(coverage)
        if function:
            terms.append("EXISTS(SELECT 1 FROM records a WHERE a.dataset='facts' AND a.relation='accesses' AND a.symbol_id=s.symbol_id AND instr(coalesce(a.function_id,''),?)>0)")
            args.append(function)
        if context:
            terms.append("EXISTS(SELECT 1 FROM records a JOIN edges c ON c.parent=a.node AND c.key='contexts' JOIN edges i ON i.parent=c.child JOIN nodes n ON n.id=i.child WHERE a.dataset='facts' AND a.relation='accesses' AND a.symbol_id=s.symbol_id AND n.kind='str' AND n.value=?)")
            args.append(context.encode('utf-8',errors='surrogatepass'))
        if ai_state:
            if ai_state=='NOT_QUEUED':
                terms.append("NOT EXISTS(SELECT 1 FROM records f WHERE f.dataset='report' AND f.relation='findings' AND f.symbol_id=s.symbol_id)")
            else:
                terms.append("EXISTS(SELECT 1 FROM records f JOIN edges e ON e.parent=f.node AND e.key='finding_id' JOIN nodes n ON n.id=e.child WHERE f.dataset='report' AND f.relation='findings' AND f.symbol_id=s.symbol_id AND coalesce((SELECT a.state FROM human.ai_events a WHERE a.finding_id=CAST(n.value AS TEXT) ORDER BY a.sequence DESC LIMIT 1),'PENDING')=?)")
                args.append(ai_state)
        if diff:
            if diff not in {'selected','conservative','direct'}:raise ValueError('Diff筛选只接受 selected/conservative/direct')
            try:
                selected=self.evidence.resolve('report',['git_diff','selected_symbol_ids'])
                conservative=self.evidence.resolve('report',['git_diff','conservative_symbol_ids'])
            except KeyError as exc:raise ValueError('此扫描没有Git差异选择证据，不能使用Diff筛选') from exc
            root=conservative if diff=='conservative' else selected
            terms.append("s.symbol_id IN (SELECT CAST(n.value AS TEXT) FROM edges e JOIN nodes n ON n.id=e.child WHERE e.parent=?)")
            args.append(root)
            if diff=='direct':
                terms.append("s.symbol_id NOT IN (SELECT CAST(n.value AS TEXT) FROM edges e JOIN nodes n ON n.id=e.child WHERE e.parent=?)")
                args.append(conservative)
        where = ' WHERE '+' AND '.join(terms) if terms else ''
        # Only a service-owned, schema-validated reviews path can be attached.
        # No arbitrary file path is accepted from an API request.
        with closing(connect_readonly(self.path/'scan.db')) as conn:
            conn.execute('ATTACH DATABASE ? AS human', ((self.path/'reviews.db').resolve().as_uri()+'?mode=ro',))
            cte = HUMAN_HEADS
            source = ' FROM symbols s LEFT JOIN heads h ON h.symbol_id=s.symbol_id'+where
            total = conn.execute(cte+'SELECT count(*)'+source, args).fetchone()[0]
            rows = [dict(row) for row in conn.execute(cte+'SELECT s.*'+source+' ORDER BY '+ordering+' LIMIT ? OFFSET ?',
                [*args,limit,offset])]
        return dict(total=total,items=rows,offset=offset,sort=sort,order=order,
            next_offset=offset+len(rows) if offset+len(rows)<total else None)

    def diff_summary(self):
        try:node=self.evidence.resolve('report',['git_diff'])
        except KeyError:return None
        fields={row['key']:row for row in self.evidence.node(node,limit=200)['items']}
        result=dict(node=node)
        for key in ('fallback_level','impact_coverage','selection_basis','note'):
            if key in fields and 'value' in fields[key]:result[key]=fields[key]['value']
        if 'pin' in fields:
            result['pin']={row['key']:row['value'] for row in self.evidence.node(fields['pin']['id'],limit=200)['items']
                if row['key'] in {'base_ref','current_ref','head_sha','base_sha','include_uncommitted'} and 'value' in row}
        for key in ('selected_symbol_ids','conservative_symbol_ids'):
            result[key+'_count']=fields[key]['total'] if key in fields else 0
        return result

    def human_counts(self):
        with closing(connect_readonly(self.path/'scan.db')) as conn:
            conn.execute('ATTACH DATABASE ? AS human',((self.path/'reviews.db').resolve().as_uri()+'?mode=ro',))
            return dict(conn.execute(HUMAN_HEADS+"SELECT coalesce(h.decision,'PENDING'),count(*) "
                "FROM symbols s LEFT JOIN heads h ON h.symbol_id=s.symbol_id GROUP BY coalesce(h.decision,'PENDING')"))

    def symbol_functions(self, symbol_id, *, offset=0, limit=50):
        self.evidence._bounds(offset,limit)
        with closing(connect_readonly(self.path/'scan.db')) as conn:
            where="dataset='facts' AND relation='accesses' AND symbol_id=? AND function_id IS NOT NULL"
            total=conn.execute('SELECT count(DISTINCT function_id) FROM records WHERE '+where,(symbol_id,)).fetchone()[0]
            functions=[row[0] for row in conn.execute('SELECT function_id FROM records WHERE '+where+
                ' GROUP BY function_id ORDER BY min(ordinal) LIMIT ? OFFSET ?',(symbol_id,limit,offset))]
        items=[dict(function_id=ident,definitions=self.evidence.records('functions',function_id=ident)['items']) for ident in functions]
        return dict(items=items,total=total,offset=offset,next_offset=offset+len(items) if offset+len(items)<total else None)

    def call_neighbors(self, function_id, *, direction='upstream', offset=0, limit=50):
        if direction not in {'upstream','downstream'}:
            raise ValueError('调用方向无效')
        page=self.evidence.records('calls',offset=offset,limit=limit,
            **({'target_id':function_id} if direction=='upstream' else {'source_id':function_id}))
        for item in page['items']:
            row=item['summary']
            ident=row.get('caller_function_id') if direction=='upstream' else row.get('callee_function_id')
            item['neighbor_id']=ident
            item['definitions']=self.evidence.records('functions',function_id=ident)['items'] if ident else []
        return dict(page,function_id=function_id,direction=direction)
