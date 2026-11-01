"""Read-only coverage projections; no analysis, inference or full graph restore."""
from contextlib import closing

from ..scan_store import EvidenceProvider, connect_readonly, _decode


class CoverageService:
    def __init__(self, database):
        self.evidence=EvidenceProvider(database)

    @staticmethod
    def _field(conn, root, *keys):
        row=conn.execute('SELECT node FROM roots WHERE name=?',(root,)).fetchone()
        if row is None:return None
        node=row[0]
        for key in keys:
            row=conn.execute('SELECT child FROM edges WHERE parent=? AND key=?',(node,key)).fetchone()
            if row is None:return None
            node=row[0]
        row=conn.execute('SELECT id,hash,kind,length FROM nodes WHERE id=?',(node,)).fetchone()
        return dict(row) if row else None

    @staticmethod
    def _brief(conn,node,keys):
        result={};references={}
        for key,ident,kind,length,payload in conn.execute(
                "SELECT e.key,n.id,n.kind,n.length,CASE WHEN n.length<=4096 THEN n.value END "
                'FROM edges e JOIN nodes n ON n.id=e.child WHERE e.parent=?',(node,)):
            if key not in keys:continue
            references[key]=dict(id=ident,kind=kind,total=length)
            if kind not in {'object','list'} and length<=4096:
                result[key]=_decode(kind,payload)
        return dict(summary=result,fields=references)

    @staticmethod
    def _tu_relation():
        return (" FROM records r LEFT JOIN edges f ON f.parent=r.node AND f.key='source_file' "
            "LEFT JOIN nodes fn ON fn.id=f.child LEFT JOIN edges s ON s.parent=r.node AND s.key='parse_status' "
            "LEFT JOIN nodes sn ON sn.id=s.child WHERE r.dataset='facts' AND r.relation='translation_units'")

    @staticmethod
    def _associations():
        return ("WITH variable_tus AS (SELECT c.child AS file_node,count(DISTINCT v.symbol_id) AS symbols "
            "FROM symbols v JOIN edges t ON t.parent=v.node AND t.key='translation_units' "
            "JOIN nodes collection ON collection.id=t.child AND collection.kind='list' "
            "JOIN edges c ON c.parent=t.child JOIN nodes name ON name.id=c.child AND name.kind='str' "
            'GROUP BY c.child) ')

    @classmethod
    def _association_quality(cls,conn):
        unknown=conn.execute("SELECT count(*) FROM symbols v WHERE NOT EXISTS(SELECT 1 FROM edges t "
            "JOIN nodes n ON n.id=t.child WHERE t.parent=v.node AND t.key='translation_units' AND n.kind='list' "
            "AND n.length>0 AND NOT EXISTS(SELECT 1 FROM edges c JOIN nodes item ON item.id=c.child "
            "WHERE c.parent=n.id AND item.kind<>'str'))").fetchone()[0]
        duplicates=conn.execute("SELECT count(*) FROM (SELECT f.child FROM records r JOIN edges f ON f.parent=r.node "
            "AND f.key='source_file' WHERE r.dataset='facts' AND r.relation='translation_units' GROUP BY f.child HAVING count(*)>1)").fetchone()[0]
        missing_sources=conn.execute("SELECT count(*) FROM records r WHERE r.dataset='facts' AND r.relation='translation_units' "
            "AND NOT EXISTS(SELECT 1 FROM edges f JOIN nodes n ON n.id=f.child WHERE f.parent=r.node AND f.key='source_file' "
            "AND n.kind='str' AND n.length>0)").fetchone()[0]
        tus=cls._field(conn,'facts','translation_units');variables=cls._field(conn,'facts','variables')
        tu_count=conn.execute("SELECT count(*) FROM records WHERE dataset='facts' AND relation='translation_units'").fetchone()[0]
        var_count=conn.execute('SELECT count(*) FROM symbols').fetchone()[0]
        complete=bool(tus and tus['kind']=='list' and tus['length']==tu_count
            and variables and variables['kind']=='list' and variables['length']==var_count)
        return dict(objects_without_tu_origin=unknown,ambiguous_tu_source_names=duplicates,
            tus_without_source_name=missing_sources,association_collections_complete=complete,
            zero_filter_available=complete and not unknown and not duplicates and not missing_sources)

    def summary(self):
        with closing(connect_readonly(self.evidence.path)) as conn:
            unknowns=self._field(conn,'facts','unknowns');tus=self._field(conn,'facts','translation_units')
            blockers=self._field(conn,'report','coverage','blocker_fanout')
            status=self._field(conn,'report','analysis_status')
            status_value=None
            if status and status['kind']=='str' and status['length']<=256:
                status_value=_decode('str',conn.execute('SELECT value FROM nodes WHERE id=?',(status['id'],)).fetchone()[0])
            status_types=conn.execute('SELECT count(*) FROM (SELECT s.child'+self._tu_relation()+' GROUP BY s.child)').fetchone()[0]
            groups=[]
            for node,kind,length,payload,count in conn.execute("SELECT sn.id,sn.kind,sn.length,"
                    "CASE WHEN sn.kind='str' AND sn.length<=256 THEN sn.value END,count(*)"+self._tu_relation()+
                    " GROUP BY s.child ORDER BY CASE WHEN sn.kind='str' AND CAST(sn.value AS TEXT) "
                    "IN ('PARSED','PARTIAL','FAILED') THEN 0 ELSE 1 END,count(*) DESC,s.child LIMIT 50"):
                groups.append(dict(node=node,raw=_decode(kind,payload) if payload is not None else None,
                    value_kind=kind,total_bytes=length,count=count))
            build=[]
            for key in ['build_closure','excluded_sources','excluded_from_build','unlisted_sources',
                    'unlisted_headers','excluded_headers_from_build','assembly_sources','cmake_steps',
                    'cmake_cache','compilers','external_tools','consumed_inputs','file_coverage','unknown_reason_distribution']:
                reference=self._field(conn,'report','coverage',key)
                if reference:build.append(dict(key=key,**reference))
            unknown_rows=conn.execute("SELECT count(*) FROM records WHERE dataset='facts' AND relation='unknowns'").fetchone()[0]
            tu_rows=conn.execute("SELECT count(*) FROM records WHERE dataset='facts' AND relation='translation_units'").fetchone()[0]
            return dict(analysis_status=status_value,unknowns=unknowns,translation_units=tus,blockers=blockers,
                unknown_records=unknown_rows,tu_records=tu_rows,tu_statuses=groups,tu_status_types=status_types,build=build,
                unprojected_unknowns=(unknowns['length']-unknown_rows if unknowns and unknowns['kind']=='list' else None),
                unprojected_tus=(tus['length']-tu_rows if tus and tus['kind']=='list' else None),
                **self._association_quality(conn))

    def groups(self,offset=0,limit=50):
        self.evidence._bounds(offset,limit)
        source=(" FROM records r LEFT JOIN edges k ON k.parent=r.node AND k.key='kind' "
            "LEFT JOIN nodes n ON n.id=k.child LEFT JOIN symbols v ON v.symbol_id=r.symbol_id "
            "WHERE r.dataset='facts' AND r.relation='unknowns' ")
        with closing(connect_readonly(self.evidence.path)) as conn:
            total=conn.execute('SELECT count(*) FROM (SELECT k.child'+source+'GROUP BY k.child)').fetchone()[0]
            items=[]
            for node,kind,length,payload,count,symbols,unbound in conn.execute(
                    "SELECT k.child,n.kind,n.length,CASE WHEN n.kind='str' AND n.length<=256 THEN n.value END,"
                    'count(*),count(DISTINCT v.symbol_id),sum(v.symbol_id IS NULL)'+source+
                    'GROUP BY k.child ORDER BY count(*) DESC,k.child LIMIT ? OFFSET ?',(limit,offset)):
                items.append(dict(node=node,raw=_decode(kind,payload) if payload is not None else None,
                    value_kind=kind,total_bytes=length,records=count,direct_symbols=symbols,unbound_records=unbound))
        return dict(items=items,total=total,offset=offset,next_offset=offset+len(items) if offset+len(items)<total else None)

    def issues(self,kind_node=None,missing_kind=False,offset=0,limit=50):
        self.evidence._bounds(offset,limit)
        if kind_node is not None and missing_kind:raise ValueError('请选择一个缺口类型')
        source=(" FROM records r LEFT JOIN edges k ON k.parent=r.node AND k.key='kind' "
            "WHERE r.dataset='facts' AND r.relation='unknowns'")
        args=[]
        if missing_kind:source+=' AND k.child IS NULL'
        elif kind_node is not None:source+=' AND k.child=?';args.append(kind_node)
        with closing(connect_readonly(self.evidence.path)) as conn:
            total=conn.execute('SELECT count(*)'+source,args).fetchone()[0]
            items=[]
            for row in conn.execute('SELECT r.*'+source+' ORDER BY r.ordinal LIMIT ? OFFSET ?',[*args,limit,offset]):
                item=dict(row);item.update(self._brief(conn,row['node'],
                    {'kind','file','line','function_id','symbol_id','reason','diagnostic','detail','message'}));items.append(item)
        return dict(items=items,total=total,offset=offset,next_offset=offset+len(items) if offset+len(items)<total else None)

    def blockers(self,offset=0,limit=50):
        self.evidence._bounds(offset,limit)
        with closing(connect_readonly(self.evidence.path)) as conn:
            root=self._field(conn,'report','coverage','blocker_fanout')
            if not root or root['kind']!='list':return dict(items=[],total=0,available=False,offset=offset,next_offset=None)
            items=[]
            for ordinal,node in conn.execute('SELECT ordinal,child FROM edges WHERE parent=? ORDER BY ordinal LIMIT ? OFFSET ?',
                    (root['id'],limit,offset)):
                item=dict(ordinal=ordinal,node=node,**self._brief(conn,node,
                    {'blocker_id','kind','file','line','blocker_fanout','suspected_overpropagation','diagnostic','symbol_ids','relevance_proofs'}))
                symbols=item['fields'].get('symbol_ids')
                item['archived_symbol_ids_count']=symbols['total'] if symbols and symbols['kind']=='list' else None
                items.append(item)
        return dict(items=items,total=root['length'],available=True,offset=offset,
            next_offset=offset+len(items) if offset+len(items)<root['length'] else None)

    def translation_units(self,status_node=None,status_missing=False,search='',zero_only=False,offset=0,limit=50):
        self.evidence._bounds(offset,limit)
        if status_node is not None and status_missing:raise ValueError('请选择一个TU状态')
        with closing(connect_readonly(self.evidence.path)) as conn:
            quality=self._association_quality(conn)
            if zero_only and not quality['zero_filter_available']:
                raise ValueError('归档缺少部分TU来源或存在同名编译变体，不能证明零关联对象TU；请查看全部TU及原始编译参数')
            source=self._tu_relation();args=[]
            if status_missing:source+=' AND s.child IS NULL'
            elif status_node is not None:source+=' AND s.child=?';args.append(status_node)
            if search:source+=" AND fn.kind='str' AND instr(CAST(fn.value AS TEXT),?)>0";args.append(search)
            selection=('SELECT r.ordinal,r.node,f.child AS file_node,s.child AS status_node'+source)
            cte=self._associations()+' , selected AS ('+selection+') '
            joined=' FROM selected r LEFT JOIN variable_tus a ON a.file_node=r.file_node'
            where=' WHERE coalesce(a.symbols,0)=0' if zero_only else ''
            total=conn.execute(cte+'SELECT count(*)'+joined+where,args).fetchone()[0]
            items=[]
            for ordinal,node,count in conn.execute(cte+'SELECT r.ordinal,r.node,coalesce(a.symbols,0)'+joined+where+
                    ' ORDER BY r.ordinal LIMIT ? OFFSET ?',[*args,limit,offset]):
                item=dict(ordinal=ordinal,node=node,associated_objects=count,
                    association_complete=quality['zero_filter_available'])
                item.update(self._brief(conn,node,{'source_file','source','directory','tu_id','audit_role','parse_status',
                    'diagnostics','original_arguments','arguments','system_include_dirs','missing_defines','includes'}));items.append(item)
        return dict(items=items,total=total,offset=offset,**quality,
            next_offset=offset+len(items) if offset+len(items)<total else None)

    def related(self,node,offset=0,limit=50):
        self.evidence._bounds(offset,limit)
        with closing(connect_readonly(self.evidence.path)) as conn:
            root=self._field(conn,'report','coverage','blocker_fanout')
            known=conn.execute("SELECT 1 FROM records WHERE dataset='facts' AND relation='unknowns' AND node=?",(node,)).fetchone()
            if not known and root and root['kind']=='list':
                known=conn.execute('SELECT 1 FROM edges WHERE parent=? AND child=?',(root['id'],node)).fetchone()
            if not known:raise ValueError('当前节点不是该归档的缺口或覆盖阻断记录')
            array=conn.execute("SELECT n.id,n.length FROM edges e JOIN nodes n ON n.id=e.child "
                "WHERE e.parent=? AND e.key='symbol_ids' AND n.kind='list'",(node,)).fetchone()
            if array:
                total=array[1]
                records=conn.execute("SELECT e.ordinal,n.kind,n.length,CASE WHEN n.length<=4096 THEN n.value END FROM edges e JOIN nodes n ON n.id=e.child "
                    'WHERE e.parent=? ORDER BY e.ordinal LIMIT ? OFFSET ?',(array[0],limit,offset))
            else:
                row=conn.execute("SELECT n.kind,n.length,CASE WHEN n.length<=4096 THEN n.value END FROM edges e JOIN nodes n ON n.id=e.child "
                    "WHERE e.parent=? AND e.key='symbol_id'",(node,)).fetchone()
                total=1 if row else 0
                records=[(0,*row)] if row and offset==0 else []
            items=[]
            for ordinal,kind,length,payload in records:
                if kind!='str' or length>4096:
                    items.append(dict(ordinal=ordinal,symbol_id=None,available=False,
                        reason='该身份是复合或长值，请从完整原始证据读取'));continue
                ident=_decode(kind,payload)
                symbol=conn.execute('SELECT * FROM symbols WHERE symbol_id=?',(ident,)).fetchone()
                items.append(dict(ordinal=ordinal,symbol_id=ident,available=symbol is not None,
                    symbol=dict(symbol) if symbol else None,
                    reason='' if symbol else '该身份未出现在当前静态清单；不能解释为无影响'))
        return dict(items=items,total=total,offset=offset,next_offset=offset+len(items) if offset+len(items)<total else None)
