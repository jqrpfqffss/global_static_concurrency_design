"""Select complete original Packet inputs without restoring the facts root.

Internal reader only; the existing Packet builder remains the output contract.
All selection is against the ordered authority graph, including legacy v1.
"""
from contextlib import closing,contextmanager

from .scan_store import connect_readonly,_scalar,_decode,_hash_start


class _Length:
    def __init__(self,value):self.value=value
    def __len__(self):return self.value


class _Pairs:
    """Every pair, in original order; only fields read by the old builder."""
    def __init__(self,connection,node,length):self.conn=connection;self.node=node;self.length=length
    def __len__(self):return self.length
    def __iter__(self):
        for ordinal,node in self.conn.execute('SELECT ordinal,child FROM edges WHERE parent=? ORDER BY ordinal',(self.node,)):
            reader=PacketInputs(self.conn)
            if self.conn.execute('SELECT kind FROM nodes WHERE id=?',(node,)).fetchone()[0]!='object':
                raise ValueError('Packet冲突关系不是对象')
            value={}
            for key in ('participant_a','participant_b'):
                participant=reader.child(node,key)
                if participant is None:value[key]=None
                elif self.conn.execute('SELECT kind FROM nodes WHERE id=?',(participant,)).fetchone()[0]=='object':
                    value[key]=dict(context_id=reader.field(participant,'context_id'))
                else:
                    value[key]=reader.value(participant)
                    if value[key]:raise ValueError('Packet冲突参与者不是对象')
            for key in ('relation','mhp','may_concurrent','has_write_conflict','protection_status','status'):
                child=reader.child(node,key)
                if child is not None:value[key]=reader.value(child)
            yield value


class PacketInputs:
    def __init__(self,connection):
        self.conn=connection;self.memo={};self.checked_arrays=set()
        self.roots={name:node for name,node in connection.execute('SELECT name,node FROM roots')}

    def child(self,node,key,default=None):
        row=self.conn.execute('SELECT child FROM edges WHERE parent=? AND key=?',(node,key)).fetchone()
        return row[0] if row else default

    def value(self,node):
        if node in self.memo:return self.memo[node]
        row=self.conn.execute('SELECT kind,value FROM nodes WHERE id=?',(node,)).fetchone()
        if row is None:raise ValueError('Packet证据节点缺失')
        kind,payload=row
        if kind not in {'list','object'}:result=_decode(kind,payload)
        else:
            result=[] if kind=='list' else {};self.memo[node]=result
            for key,child in self.conn.execute('SELECT key,child FROM edges WHERE parent=? ORDER BY ordinal',(node,)):
                item=self.value(child)
                if kind=='list':result.append(item)
                else:result[key]=item
        self.memo[node]=result;return result

    def field(self,node,key,default=None):
        child=self.child(node,key)
        return self.value(child) if child is not None else default

    def array(self,root,key,*,required=False):
        node=self.child(self.roots[root],key)
        if node is None:
            if required:raise KeyError(key)
            return None
        if self.conn.execute('SELECT kind FROM nodes WHERE id=?',(node,)).fetchone()[0]!='list':
            raise ValueError('Packet关系不是有序列表：'+key)
        record_keys={'variables','functions','calls','unknowns','protection_events','context_bindings',
            'mask_windows','address_escapes','pointer_targets','control_flow','findings','review_safe_samples','translation_units'}
        if key in record_keys and (node,key) not in self.checked_arrays:
            bad=self.conn.execute("SELECT 1 FROM edges member JOIN nodes item ON item.id=member.child "
                "WHERE member.parent=? AND item.kind!='object' LIMIT 1",(node,)).fetchone()
            if bad:raise ValueError('Packet关系包含非对象记录，不能静默过滤：'+key)
            required_field={'variables':'symbol_id','functions':'function_id','control_flow':'function_id'}.get(key)
            if required_field and self.conn.execute('SELECT 1 FROM edges member WHERE member.parent=? AND NOT EXISTS('
                    'SELECT 1 FROM edges field WHERE field.parent=member.child AND field.key=?) LIMIT 1',(node,required_field)).fetchone():
                raise ValueError('Packet关系缺少必要身份：'+key+'/'+required_field)
            self.checked_arrays.add((node,key))
        return node

    def packet_record(self,node,*,finding=False):
        # These root fields are excluded and never read by the original Packet
        # builder. Keep all original evidence in the authority, not in RAM.
        unused={'whole_object_accesses'}
        if finding:unused|={'review','review_state','review_status','review_result','effective_decision','decision_label','context_pairs'}
        result={}
        for key,child in self.conn.execute('SELECT key,child FROM edges WHERE parent=? ORDER BY ordinal',(node,)):
            if key in unused:continue
            kind,length=self.conn.execute('SELECT kind,length FROM nodes WHERE id=?',(child,)).fetchone()
            if key=='conflict_pairs' and kind=='list':result[key]=_Pairs(self.conn,child,length)
            elif key=='variable_evidence_slice' and kind=='object':
                item={}
                for name,field in self.conn.execute('SELECT key,child FROM edges WHERE parent=? ORDER BY ordinal',(child,)):
                    if name=='protection':continue
                    if name=='address_taken':
                        if self.conn.execute('SELECT kind FROM nodes WHERE id=?',(field,)).fetchone()[0]!='list':
                            item[name]=self.value(field)
                        else:
                            rows=[]
                            for ordinal,value in self.entries(field):
                                if self.conn.execute('SELECT kind FROM nodes WHERE id=?',(value,)).fetchone()[0]!='object':
                                    raise ValueError('Packet地址引用不是对象')
                                rows.append(dict(access_id=self.field(value,'access_id')))
                            item[name]=rows
                    else:item[name]=self.value(field)
                result[key]=item
            else:result[key]=self.value(child)
        return result

    def entries(self,array):
        if array is not None:
            yield from self.conn.execute('SELECT ordinal,child FROM edges WHERE parent=? ORDER BY ordinal',(array,))

    def matches(self,array,key,value):
        if array is None:return []
        if not isinstance(value,str):
            # .get(key) must also match missing keys when value is None.
            return [(ordinal,node) for ordinal,node in self.entries(array) if self.field(node,key)==value]
        kind,payload=_scalar(value);hashed=_hash_start(kind,len(payload));hashed.update(payload)
        # CROSS JOIN fixes the physical loop order. Otherwise SQLite may scan
        # every array member for each scalar despite its unique hash index.
        return list(self.conn.execute('SELECT member.ordinal,field.parent FROM nodes scalar '
            'CROSS JOIN edges field INDEXED BY edge_child CROSS JOIN edges member INDEXED BY edge_child '
            'WHERE scalar.hash=? AND field.child=scalar.id AND field.key=? '
            'AND member.child=field.parent AND member.parent=? ORDER BY member.ordinal',(hashed.hexdigest(),key,array)))

    def select(self,relation,conditions):
        array=self.array('facts',relation);rows={}
        for key,values in conditions:
            for value in values:
                for ordinal,node in self.matches(array,key,value):rows[ordinal]=node
        return [(ordinal,rows[ordinal]) for ordinal in sorted(rows)]

    def packet_inputs(self,finding_id):
        found=[]
        for relation in ('findings','review_safe_samples'):
            found.extend(node for ordinal,node in self.matches(self.array('report',relation),'finding_id',finding_id))
        if len(found)!=1:raise ValueError('Packet候选身份缺失或重复，不能自动选择')
        finding=self.packet_record(found[0],finding=True);sid=finding.get('symbol_id')
        variables=self.matches(self.array('facts','variables',required=True),'symbol_id',sid)
        variable=self.packet_record(variables[0][1]) if variables else {}
        accesses=finding.get('accesses',variable.get('accesses',[]))
        related={access['function_id'] for access in accesses if access.get('function_id')}
        related.update(finding.get('function_ids',[]))
        related.update(variable.get('variable_evidence_slice',{}).get('function_ids',[]))
        if finding.get('function_id'):related.add(finding['function_id'])
        for access in accesses:
            for key in ('call_chains','all_call_chains'):
                if key not in access:continue
                for value in access[key].values():
                    for path in value if key=='all_call_chains' else [value]:related.update(path)
        calls=self.array('facts','calls');pending=list(related)
        while pending:
            for ordinal,node in self.matches(calls,'callee_function_id',pending.pop()):
                caller=self.field(node,'caller_function_id')
                if caller and caller not in related:related.add(caller);pending.append(caller)
        facts=dict(variables=[variable] if variables else [])
        for relation,conditions in [
                ('functions',[('function_id',related)]),
                ('calls',[('caller_function_id',related),('callee_function_id',related)]),
                ('unknowns',[('symbol_id',[sid] if sid else []),('function_id',related),('target_function_id',related)]),
                ('protection_events',[('function_id',related)]),('context_bindings',[('function_id',related)]),
                ('mask_windows',[('symbol_id',[sid])]),
                ('address_escapes',[('symbol_id',[sid] if sid else []),('function_id',related)])]:
            facts[relation]=[self.value(node) for ordinal,node in self.select(relation,conditions)]
        from .review import recursive_edge_endpoints
        recursive=[]
        for ordinal,node in self.entries(self.array('facts','recursive_edges')):
            edge=self.value(node);caller,callee=recursive_edge_endpoints(edge)
            if caller in related or callee in related:recursive.append(edge)
        facts['recursive_edges']=recursive
        pointers=[]
        if sid:
            for ordinal,node in self.entries(self.array('facts','pointer_targets')):
                location=self.field(node,'location','')
                if location=='obj:'+sid or location.startswith('obj:'+sid+'/'):pointers.append(self.value(node))
        facts['pointer_targets']=pointers
        flow=[]
        for ordinal,node in self.select('control_flow',[('function_id',related)]):
            item={key:self.value(child) for key,child in self.conn.execute('SELECT key,child FROM edges WHERE parent=? ORDER BY ordinal',(node,)) if key!='nodes'}
            nodes=self.child(node,'nodes')
            if nodes is None:item['nodes']=_Length(0)
            else:
                kind,length=self.conn.execute('SELECT kind,length FROM nodes WHERE id=?',(nodes,)).fetchone()
                item['nodes']=_Length(length) if kind in {'list','object'} else self.value(nodes)
            flow.append(item)
        facts['control_flow']=flow
        for key,default in [('contexts',[]),('physical_contexts',[]),('irq_priority_events',[]),
                ('nvic_priorities',[]),('nvic_resolved_events',[]),('nvic_lifecycle_barriers',[]),
                ('nvic_recovery',{}),('preemption_relations',[])]:
            facts[key]=self.field(self.roots['facts'],key,default)
        return facts,finding


@contextmanager
def packet_inputs(database,finding_id):
    with closing(connect_readonly(database)) as conn:
        conn.execute('BEGIN')
        yield PacketInputs(conn).packet_inputs(finding_id)


def build_packet(database,root,finding_id,**paths):
    """Finish the ordinary Packet while the lazy, read-only cursor is owned."""
    from .review import build_variable_review_packet
    with packet_inputs(database,finding_id) as (facts,finding):
        return build_variable_review_packet(root,facts,finding,**paths)


def shared_context(database):
    """Exact original shared prompt fields, without function bodies/CFGs."""
    with closing(connect_readonly(database)) as conn:
        conn.execute('BEGIN');reader=PacketInputs(conn);units=[]
        for ordinal,node in reader.entries(reader.array('facts','translation_units')):
            item={}
            for key in ('source_file','arguments','parse_status','diagnostics'):
                child=reader.child(node,key)
                if child is not None:item[key]=reader.value(child)
            units.append(item)
        files=set()
        for ordinal,node in reader.entries(reader.array('facts','functions')):
            file=reader.field(node,'file')
            if file:files.add(file)
        return dict(contexts=reader.field(reader.roots['facts'],'contexts',[]),
            coverage=reader.field(reader.roots['report'],'coverage',{}),
            limitations=reader.field(reader.roots['report'],'limitations',[]),
            compile_commands=units,source_files=sorted(files))
