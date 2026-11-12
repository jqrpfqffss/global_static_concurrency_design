"""Shared pagination/counting rules for Studio's three independent dimensions."""
from contextlib import closing
from pathlib import Path

from ..scan_store import EvidenceProvider, connect_readonly
from ..diff_review import DELETED_IDS, DELETED_REVIEW_PREFIX, DiffReviewEvidence

DIFF_CHANGE_LISTS = {
    'files': (['pin', 'files'], {'status', 'old_path', 'new_path', 'comment_only'}),
    'deleted': (['deleted_variables'], {'symbol_id', 'name'}),
}

HUMAN_HEADS = """WITH current_heads AS (
 SELECT e.symbol_id,CASE WHEN count(*)>1 THEN 'CONFLICT'
 ELSE min(json_extract(e.payload,'$.decision')) END AS decision,
 CASE WHEN count(*)>1 THEN 'CONFLICT' ELSE min(json_extract(e.payload,'$.handling_status')) END AS handling_status
 FROM human.events e WHERE NOT EXISTS(SELECT 1 FROM human.predecessors p WHERE p.parent_id=e.event_id)
 GROUP BY e.symbol_id), heads AS (
 SELECT c.symbol_id,CASE WHEN c.decision='PENDING' AND EXISTS(
 SELECT 1 FROM human.prior_decisions p WHERE p.symbol_id=c.symbol_id)
 THEN 'RECHECK_REQUIRED' ELSE c.decision END AS decision,c.handling_status FROM current_heads c
 UNION ALL SELECT DISTINCT p.symbol_id,ecra_inherited_decision(p.symbol_id),ecra_inherited_handling(p.symbol_id) FROM human.prior_decisions p
 WHERE NOT EXISTS(SELECT 1 FROM current_heads c WHERE c.symbol_id=p.symbol_id))
"""

BASELINE_HEADS = f"""WITH nodes AS NOT MATERIALIZED (SELECT * FROM baseline.nodes),
 edges AS NOT MATERIALIZED (SELECT * FROM baseline.edges), records AS NOT MATERIALIZED (SELECT * FROM baseline.records),
 symbols AS (SELECT * FROM baseline.symbols WHERE symbol_id IN ({DELETED_IDS})),
 heads AS (
 SELECT substr(e.symbol_id,{len(DELETED_REVIEW_PREFIX)+1}) AS symbol_id,
 CASE WHEN count(*)>1 THEN 'CONFLICT' ELSE min(json_extract(e.payload,'$.decision')) END AS decision,
 CASE WHEN count(*)>1 THEN 'CONFLICT' ELSE min(json_extract(e.payload,'$.handling_status')) END AS handling_status
 FROM human.events e WHERE e.symbol_id GLOB '{DELETED_REVIEW_PREFIX}*'
 AND NOT EXISTS(SELECT 1 FROM human.predecessors p WHERE p.parent_id=e.event_id) GROUP BY e.symbol_id)
"""


class QueryService:
    def __init__(self, scan_path, *, baseline=False):
        self.path = Path(scan_path)
        self.diff_review = DiffReviewEvidence(self.path)
        self.is_baseline = baseline
        self.evidence = self.diff_review.require_baseline() if baseline else self.diff_review.current

    def _attach_human(self, conn):
        from ..review_inheritance import inherited_state
        conn.execute('ATTACH DATABASE ? AS human',((self.path/'reviews.db').resolve().as_uri()+'?mode=ro',))
        conn.execute('BEGIN')
        states={}
        def state(sid):
            if sid not in states:
                rows=conn.execute('SELECT * FROM human.prior_decisions WHERE symbol_id=?',(sid,)).fetchall()
                states[sid]=inherited_state(rows,self.evidence)
            return states[sid]
        conn.create_function('ecra_inherited_decision',1,lambda sid:state(sid)['decision'])
        conn.create_function('ecra_inherited_handling',1,lambda sid:state(sid)['handling_status'])

    def symbols(self, *, search='', classification='', human_decision='', handling_status='',
                file='',function='',context='',coverage='',ai_state='',current_result='',review_scope='all',diff='',symbol_id='',sort='priority',order='asc',offset=0, limit=50):
        self.evidence._bounds(offset, limit)
        sorts={
            'priority':["CASE s.current_result WHEN 'CONFIRMED' THEN 0 WHEN 'LIKELY' THEN 1 WHEN 'UNKNOWN' THEN 2 ELSE 3 END"],
            'name':['s.name COLLATE BINARY'],
            'definition':["coalesce(s.definition_file,'') COLLATE BINARY",'coalesce(s.definition_line,0)'],
            'review_priority':["CASE WHEN s.requires_human_review=0 THEN 6 ELSE CASE s.human_record_decision WHEN 'PENDING' THEN 0 WHEN 'RECHECK_REQUIRED' THEN 1 "
                "WHEN 'CONFLICT' THEN 2 WHEN 'NEED_MORE_EVIDENCE' THEN 3 WHEN 'CONFIRMED_RISK' THEN 4 "
                "WHEN 'CONFIRMED_SAFE' THEN 5 ELSE 6 END END"]}
        if not isinstance(sort,str) or sort not in sorts or order not in {'asc','desc'}:
            raise ValueError('列表排序只接受风险/名称/定义位置/待办优先级和升序/降序')
        ordering=','.join(field+' '+order.upper() for field in sorts[sort])+',s.ordinal ASC'
        terms, args = [], []
        if symbol_id:
            terms.append('s.symbol_id=?');args.append(symbol_id)
        if search:
            terms.append("(instr(s.name,?)>0 OR instr(coalesce(s.definition_file,''),?)>0 OR instr(s.symbol_id,?)>0)")
            args.extend([search]*3)
        if classification:
            terms.append('s.static_classification=?'); args.append(classification)
        if human_decision:
            terms.append(('s.confirmation_state' if human_decision=='PENDING' else 's.human_record_decision')+'=?');args.append(human_decision)
        if handling_status:
            terms.append("s.handling_status=?");args.append(handling_status)
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
        if current_result:
            allowed={'CONFIRMED','LIKELY','UNKNOWN','SAFE','SHARED_NO_REVIEW','CONTAINER','OUT_OF_BUILD','NON_STORAGE','INVENTORY','RISK'}
            if current_result not in allowed:raise ValueError('当前结论筛选无效')
            if current_result=='RISK':terms.append("s.current_result IN ('CONFIRMED','LIKELY')")
            else:terms.append('s.current_result=?');args.append(current_result)
        if review_scope not in {'all','pending','required'}:raise ValueError('人工待办范围无效')
        if review_scope=='pending':terms.append('s.needs_human_confirmation=1')
        elif review_scope=='required':terms.append('s.requires_human_review=1')
        if ai_state:
            if ai_state=='NOT_QUEUED':terms.append('NOT EXISTS(SELECT 1 FROM finding_results f WHERE f.symbol_id=s.symbol_id)')
            elif ai_state in {'CONFIRMED','LIKELY','REVIEWED_SAFE','FALSE_POSITIVE','NEED_MORE_CONTEXT'}:
                terms.append('EXISTS(SELECT 1 FROM finding_results f WHERE f.symbol_id=s.symbol_id AND f.verdict=?)');args.append(ai_state)
            elif ai_state in {'PENDING','DONE','TECH_FAILED','STALE','RUNNING'}:
                terms.append("EXISTS(SELECT 1 FROM finding_results f WHERE f.symbol_id=s.symbol_id AND coalesce(f.ai_state,'PENDING')=?)");args.append(ai_state)
            else:raise ValueError('OpenCode状态筛选无效')
        with closing(connect_readonly(self.path/'scan.db')) as conn:
            self._attach_human(conn)
            source, values = self._result_rows(conn, terms, args, diff)
            total = conn.execute('SELECT count(*) FROM ('+source+')', values).fetchone()[0]
            rows = [dict(row) for row in conn.execute('SELECT s.* FROM ('+source+') s ORDER BY '+ordering+',s.evidence_side LIMIT ? OFFSET ?',
                [*values,limit,offset])]
        return dict(total=total,items=rows,offset=offset,sort=sort,order=order,
            next_offset=offset+len(rows) if offset+len(rows)<total else None)

    def _result_rows(self, conn, terms, args, diff):
        from .current_results import projection
        if diff not in {'', 'selected', 'direct', 'conservative', 'changes', 'deleted'}:
            raise ValueError('Git 差异筛选范围无效')
        def rows(cte, side, filters):
            where = ' WHERE '+' AND '.join(filters) if filters else ''
            return f"SELECT * FROM ({cte} SELECT s.*, '{side}' AS evidence_side FROM current_results s{where})"

        sources, values = [], []
        if diff != 'deleted':
            filters, current_args = list(terms), list(args)
            if diff:
                try:
                    key = 'conservative_symbol_ids' if diff=='conservative' else 'selected_symbol_ids'
                    root = self.evidence.resolve('report',['git_diff',key])
                    filters.append("s.symbol_id IN (SELECT CAST(n.value AS TEXT) FROM edges e JOIN nodes n ON n.id=e.child WHERE e.parent=?)")
                    current_args.append(root)
                    if diff=='direct':
                        conservative = self.evidence.resolve('report',['git_diff','conservative_symbol_ids'])
                        filters.append("s.symbol_id NOT IN (SELECT CAST(n.value AS TEXT) FROM edges e JOIN nodes n ON n.id=e.child WHERE e.parent=?)")
                        current_args.append(conservative)
                except KeyError as exc:
                    raise ValueError('此扫描没有 Git 差异选择证据') from exc
            sources.append(rows(projection(HUMAN_HEADS), 'current', filters))
            values.extend(current_args)
        if diff in {'changes', 'deleted'}:
            baseline = self.diff_review.require_baseline() if diff=='deleted' else self.diff_review.baseline()
            if baseline is not None:
                conn.execute('ATTACH DATABASE ? AS baseline', (baseline.path.as_uri()+'?mode=ro',))
                sources.append(rows(projection(BASELINE_HEADS, include_ai=False), 'baseline', terms))
                values.extend([self.diff_review.deleted_node(), *args])
        return ' UNION ALL '.join(sources), values


    def diff_summary(self):
        try:node=self.evidence.resolve('report',['git_diff'])
        except KeyError:return None
        fields={row['key']:row for row in self.evidence.node(node,limit=200)['items']}
        result=dict(node=node)
        for key in ('fallback_level','impact_coverage','selection_basis','note'):
            if key in fields and 'value' in fields[key]:result[key]=fields[key]['value']
        if 'pin' in fields:
            pin = {row['key']: row for row in self.evidence.node(fields['pin']['id'], limit=200)['items']}
            result['pin'] = {key: pin[key]['value'] for key in ('base_ref', 'current_ref', 'head_sha', 'base_sha', 'include_uncommitted')
                             if key in pin and 'value' in pin[key]}
            if pin.get('files', {}).get('kind') == 'list':
                result['file_count'] = pin['files']['total']
        if fields.get('deleted_variables', {}).get('kind') == 'list':
            result['deleted_variable_count'] = fields['deleted_variables']['total']
            if result['deleted_variable_count']:
                result['deleted_evidence_available'] = self.diff_review.baseline() is not None
        if fields.get('fallback_reasons', {}).get('kind') == 'list':
            result['fallback_reasons'] = [row['value'] for row in self.evidence.node(fields['fallback_reasons']['id'], limit=20)['items']
                                          if row.get('value')]
        for key in ('selected_symbol_ids','conservative_symbol_ids'):
            result[key+'_count']=fields[key]['total'] if key in fields else 0
        return result

    def diff_changes(self, kind, *, offset=0, limit=25):
        if kind not in DIFF_CHANGE_LISTS:
            raise ValueError('Git 差异明细仅支持变更文件和已删除变量')
        path, keys = DIFF_CHANGE_LISTS[kind]
        node = self.evidence.resolve('report', ['git_diff', *path])
        page = self.evidence.node(node, offset=offset, limit=limit)
        items = []
        for item in page['items']:
            fields = self.evidence.node(item['id'], limit=20)['items']
            values = {row['key']: row.get('display_json', row.get('value')) for row in fields if row['key'] in keys}
            items.append(dict(values, node=item['id'], ordinal=item['ordinal']))
        return dict(items=items, total=page['total'], offset=offset, next_offset=page['next_offset'])

    def current_summary(self, *, diff=''):
        from .current_results import summary
        with closing(connect_readonly(self.path/'scan.db')) as conn:
            self._attach_human(conn)
            source, args = self._result_rows(conn, [], [], diff)
            return summary(conn, source, args, include_static=bool(diff))

    def human_counts(self):return self.current_summary()['human_counts']

    def result_revision(self):
        from .current_results import revision
        with closing(connect_readonly(self.path/'scan.db')) as conn:
            self._attach_human(conn)
            return dict(result_revision=revision(conn))

    def symbol_ai(self,symbol_id,*,offset=0,limit=20):
        import json
        from .current_results import AI_CTE, EMPTY_AI
        self.evidence._bounds(offset,limit)
        with closing(connect_readonly(self.evidence.path)) as conn:
            self._attach_human(conn)
            cte='WITH '+(EMPTY_AI if self.is_baseline else AI_CTE)+", labels AS (SELECT CAST(n.value AS TEXT) AS finding_id,f.ordinal FROM records f JOIN edges e ON e.parent=f.node AND e.key='finding_id' JOIN nodes n ON n.id=e.child WHERE f.dataset='report' AND f.relation IN ('findings','review_safe_samples') AND f.symbol_id=? GROUP BY n.value) "
            source=' FROM labels l LEFT JOIN ai_verdicts a ON a.finding_id=l.finding_id'
            total=conn.execute(cte+'SELECT count(*)'+source,[symbol_id]).fetchone()[0]
            rows=[]
            for fid,payload in conn.execute(cte+'SELECT l.finding_id,a.payload'+source+' ORDER BY l.ordinal LIMIT ? OFFSET ?',[symbol_id,limit,offset]):
                rows.append(json.loads(payload) if payload else dict(finding_id=fid,state='PENDING',status=None))
            return dict(items=rows,total=total,offset=offset,next_offset=offset+len(rows) if offset+len(rows)<total else None)

    def symbol_functions(self, symbol_id, *, offset=0, limit=50):
        self.evidence._bounds(offset,limit)
        with closing(connect_readonly(self.evidence.path)) as conn:
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
            # The validated projection already applies the historical alias
            # precedence. V1 lacked these columns' values, so retain its
            # authoritative engine-field fallback without changing the data.
            ident=item.get('source_id' if direction=='upstream' else 'target_id') or row.get(
                'caller_function_id' if direction=='upstream' else 'callee_function_id')
            item['neighbor_id']=ident
            item['definitions']=self.evidence.records('functions',function_id=ident)['items'] if ident else []
        return dict(page,function_id=function_id,direction=direction)
