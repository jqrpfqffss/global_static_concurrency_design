"""Variable-local evidence and conflict-first bare-metal classification.

Diagnostics are not taints. Every blocking gap retains its source and the
specific storage/entry relation that can hide another conflicting access.
"""
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field, asdict

from .common import digest


SAFE_REASONS = {
    'SAFE_NO_RUNTIME_ACCESS': '静态已判安全：没有运行期访问',
    'SAFE_READ_ONLY': '静态已判安全：运行期仅读取',
    'SAFE_SINGLE_FOREGROUND': '静态已判安全：仅主循环串行访问',
    'SAFE_SINGLE_IRQ': '静态已判安全：仅同一物理中断串行访问',
    'SAFE_MULTI_CONTEXT_READ_ONLY': '静态已判安全：所有上下文均只读取',
    'SAFE_NON_INTERLEAVING': '静态已判安全：所有修改相关上下文均已证明不能交错',
    'SAFE_EFFECTIVE_PROTECTION': '静态已判安全：完整临界区保护',
    'SAFE_INIT_ONLY_WRITE': '静态已判安全：写入仅发生在异步源启用前的初始化阶段',
    'SAFE_DISJOINT_STORAGE': '静态已判安全：不同执行上下文访问不重叠的存储',
}
READS = {'READ', 'WHOLE_OBJECT_READ', 'DMA_READ'}
WRITES = {'WRITE', 'RMW', 'WHOLE_OBJECT_WRITE', 'DMA_WRITE'}
RUNTIME = READS | WRITES
ENTRY_GAPS = {'FUNCTION_ADDRESS', 'MISSING_SOURCE_CALLER', 'ASSEMBLY_FUNCTION_REFERENCE',
              'UNKNOWN_CALLBACK_ENTRY', 'UNRESOLVED_REGISTERED_ENTRY', 'TASK_ENTRY_WITHOUT_DEFINITION',
              'UNRESOLVED_VECTOR_ENTRY'}
SYMBOL_CODES = {
    'ADDRESS_ESCAPE': 'UNKNOWN_ADDRESS_ESCAPE',
    'STATIC_INITIALIZER_REFERENCE': 'UNKNOWN_RELEVANT_ALIAS',
    'DMA_SHARED_REVIEW': 'UNKNOWN_DMA_LIFETIME',
    'UNRESOLVED_DMA_BUFFER': 'UNKNOWN_DMA_LIFETIME',
    'ASSEMBLY_SYMBOL_REFERENCE': 'UNKNOWN_INLINE_ASM',
    'INLINE_ASSEMBLY': 'UNKNOWN_INLINE_ASM',
    'PARSE_FAILED': 'UNKNOWN_RELEVANT_MISSING_TU',
    'SOURCE_NOT_IN_DATABASE': 'UNKNOWN_RELEVANT_MISSING_TU',
    'DEFINITION_MISSING': 'UNKNOWN_RELEVANT_MISSING_TU',
    'TYPE_VARIANT': 'UNKNOWN_RELEVANT_ALIAS',
    'UNRESOLVED_POINTEE': 'UNKNOWN_RELEVANT_ALIAS',
    'INDIRECT_CALL': 'UNKNOWN_RELEVANT_INDIRECT_CALL',
}


@dataclass
class PhysicalExecutionContext:
    physical_id: str
    kind: str
    logical_context_ids: list = field(default_factory=list)
    entry_functions: list = field(default_factory=list)


@dataclass
class VariableEvidenceSlice:
    symbol_id: str
    canonical_path: str
    definition: dict
    linkage: str
    direct_access_ids: list = field(default_factory=list)
    alias_access_ids: list = field(default_factory=list)
    address_taken: list = field(default_factory=list)
    address_escapes: list = field(default_factory=list)
    function_ids: list = field(default_factory=list)
    physical_contexts: list = field(default_factory=list)
    call_edges: list = field(default_factory=list)
    unresolved_edges: list = field(default_factory=list)
    protection: list = field(default_factory=list)
    whole_object_effects: list = field(default_factory=list)
    critical_gaps: list = field(default_factory=list)


class EvidenceIndex:
    def __init__(self, facts, coverage, cfg, unreachable):
        self.facts, self.coverage, self.cfg = facts, coverage, cfg
        self.unreachable = unreachable
        self.by_symbol, self.entries, self.reverse = defaultdict(list), defaultdict(list), defaultdict(set)
        self.function_files = {f['function_id']: f.get('file') for f in facts['functions']}
        for call in facts['calls']:
            if call.get('callee_function_id'):
                self.reverse[call['callee_function_id']].add(call['caller_function_id'])
        self.failed_files = {u.get('file') for u in facts['unknowns'] if u['kind'] == 'PARSE_FAILED'}
        self.failed_files.update(u['source_file'] for u in facts.get('translation_units', [])
                                 if u.get('parse_status') == 'FAILED')
        for issue in facts['unknowns']:
            if issue.get('symbol_id'):
                self.by_symbol[issue['symbol_id']].append(issue)
            if issue.get('target_function_id') and issue['kind'] in ENTRY_GAPS:
                self.entries[issue['target_function_id']].append(issue)
        self.ancestor_cache = {}

    def ancestors(self, fid):
        if fid not in self.ancestor_cache:
            found, todo = {fid}, [fid]
            while todo:
                for caller in self.reverse[todo.pop()] - found:
                    found.add(caller)
                    todo.append(caller)
            self.ancestor_cache[fid] = found
        return self.ancestor_cache[fid]

    def build(self, variable, accesses, contexts, protection):
        sid = variable['symbol_id']
        runtime = [a for a in accesses if a['access_kind'] in RUNTIME]
        writers = any(a['access_kind'] in WRITES for a in runtime)
        ancestors = set().union(*(self.ancestors(a['function_id']) for a in runtime)) if runtime else set()
        result = VariableEvidenceSlice(sid, variable.get('canonical_path', variable['qualified_name']),
            dict(file=variable.get('definition_file'), line=variable.get('definition_line')),
            variable.get('linkage', ''),
            direct_access_ids=[a['access_id'] for a in runtime if not a.get('via_alias')],
            alias_access_ids=[a['access_id'] for a in runtime if a.get('via_alias')],
            address_taken=[a for a in accesses if a['access_kind'] == 'ADDRESS_TAKEN'],
            function_ids=sorted(ancestors),
            physical_contexts=sorted({contexts[c]['physical_id'] for a in runtime for c in a['contexts']}),
            call_edges=[c for c in self.facts['calls'] if c['caller_function_id'] in ancestors
                        and c.get('callee_function_id') in ancestors],
            protection=protection,
            whole_object_effects=[a['access_id'] for a in runtime if a.get('inherited_from_access_id')])

        def gap(issue, code, reason):
            row = dict(issue, reason_code=code, affected_symbol_id=sid, relevance=reason)
            row['blocker_id'] = 'B-' + digest({k:v for k,v in issue.items()
                if k not in {'symbol_id', 'canonical_path', 'root_symbol_id', 'inherited_object_uncertainty'}})[:20]
            result.critical_gaps.append(row)

        for issue in self.by_symbol[sid]:
            if issue.get('function_id') in self.unreachable:
                continue
            kind = issue['kind']
            gap(issue, SYMBOL_CODES.get(kind, 'UNKNOWN_RELEVANT_ALIAS'),
                '该事实直接绑定目标存储，可能引入尚未恢复的访问。')
            if kind == 'ADDRESS_ESCAPE':
                result.address_escapes.append(issue)
        # An unknown execution source is immaterial when every possible
        # access to this storage is a read. It cannot manufacture a writer.
        if writers:
            for fid in sorted(ancestors):
                for issue in self.entries[fid]:
                    gap(issue, 'UNKNOWN_EXECUTION_CONTEXT',
                        '此未知入口可沿已解析调用边到达目标变量的访问函数。')
                    result.unresolved_edges.append(issue)
            for access in runtime:
                if (not access.get('contexts') or any(contexts[c]['physical_kind'] == 'UNKNOWN_CONTEXT'
                                                     for c in access.get('contexts', []))):
                    gap(dict(kind='EXECUTION_CONTEXT_UNRESOLVED', function_id=access['function_id'],
                        file=access['file'], line=access['line'], access_id=access['access_id']),
                        'UNKNOWN_EXECUTION_CONTEXT', '实际访问尚未归属物理执行上下文，可能与修改者交错。')
        related_files = set(variable.get('translation_units', [])) | {variable.get('definition_file')}
        for file in sorted(self.failed_files - {None}):
            # Internal linkage cannot be named by another TU. Exported storage
            # is visible to a genuinely missing ACTIVE TU (not unbuilt files).
            if file in related_files or variable.get('linkage') == 'EXTERNAL':
                gap(dict(kind='PARSE_FAILED', file=file), 'UNKNOWN_RELEVANT_MISSING_TU',
                    '当前目标编译单元解析失败；目标存储在该单元中可见，访问覆盖不能证明完整。')
        if not variable.get('definition_file'):
            gap(dict(kind='DEFINITION_MISSING', file=next(iter(variable.get('declarations', [])), {}).get('file')),
                'UNKNOWN_RELEVANT_MISSING_TU', '目标存储的实际定义不在已解析构建闭包内。')
        if variable.get('parse_status') == 'FAILED' and not result.critical_gaps:
            gap(dict(kind='PARSE_FAILED', file=variable.get('definition_file')), 'UNKNOWN_RELEVANT_MISSING_TU',
                '定义所在编译单元的访问覆盖不完整。')
        if variable.get('linkage') == 'EXTERNAL':
            for obj in self.coverage.get('build_closure', {}).get('missing_objects', []):
                gap(dict(kind='MISSING_LINKED_OBJECT', file=str(obj)), 'UNKNOWN_RELEVANT_MISSING_TU',
                    '实际链接对象缺少对应编译单元；该对象可通过外部链接名称访问目标存储。')
        if self.cfg['project'].get('cm4_enabled') or self.cfg['project'].get('concurrency_model', 'single_core_preemptive') != 'single_core_preemptive':
            gap(dict(kind='UNMODELED_CONCURRENCY', file=variable.get('definition_file')),
                'UNKNOWN_EXECUTION_CONTEXT', '当前执行模型包含未恢复的其他核或调度域，目标的额外执行者待确认。')
        result.critical_gaps = list({digest(g):g for g in result.critical_gaps}.values())
        return result


def classify(evidence, accesses, contexts, pairs, protection, protection_note, init_proof=None):
    runtime = [a for a in accesses if a['access_kind'] in RUNTIME]
    conflicts = [p for p in pairs if p['may_concurrent'] and p['has_write_conflict']
                 and all(contexts[p[side]['context_id']]['physical_kind'] != 'UNKNOWN_CONTEXT'
                         for side in ('participant_a', 'participant_b'))]
    if protection == 'EFFECTIVE':
        for pair in conflicts:
            pair['protection_status'] = 'EFFECTIVE'
        conflicts = []
    if init_proof:
        conflicts = []
    reasons = {g['kind'] for g in evidence.critical_gaps}
    if protection == 'UNRESOLVED':
        reasons.add('PROTECTION_UNRESOLVED')
    if any(p['relation']['relation'] == 'UNKNOWN_PREEMPTION' for p in conflicts):
        reasons.add('IRQ_PREEMPTION_UNRESOLVED')
    state, code = None, None
    if conflicts:
        state = 'SUSPECT'
        explanation = '存在已知跨物理上下文修改冲突；尚未证明不能交错或受到完整有效保护。'
        if protection == 'UNRESOLVED':
            explanation += '保护有效性待确认。'
    elif evidence.critical_gaps:
        state = 'UNKNOWN'
        explanation = '变量相关证据缺口可能隐藏额外冲突：' + '、'.join(sorted({g['reason_code'] for g in evidence.critical_gaps}))
    else:
        state = 'SAFE'
        ids = {c for a in runtime for c in a['contexts']}
        physical = {contexts[c]['physical_id'] for c in ids}
        if not runtime:
            code = 'SAFE_NO_RUNTIME_ACCESS'
        elif all(a['access_kind'] in READS for a in runtime):
            code = 'SAFE_MULTI_CONTEXT_READ_ONLY' if len(physical) > 1 else 'SAFE_READ_ONLY'
        elif init_proof:
            code = 'SAFE_INIT_ONLY_WRITE'
        elif physical == {'FOREGROUND'}:
            code = 'SAFE_SINGLE_FOREGROUND'
        elif len(physical) == 1 and next(iter(physical)).startswith('IRQ:'):
            code = 'SAFE_SINGLE_IRQ'
        elif protection == 'EFFECTIVE':
            code = 'SAFE_EFFECTIVE_PROTECTION'
        else:
            code = 'SAFE_NON_INTERLEAVING'
        explanation = SAFE_REASONS[code]
    return dict(static_classification=state, classification_reason=explanation,
        safe_reason_code=code, unknown_reason_codes=sorted({g['reason_code'] for g in evidence.critical_gaps}) if state == 'UNKNOWN' else [],
        coverage='PARTIAL' if reasons else 'COMPLETE', analysis_coverage='PARTIAL' if reasons else 'COMPLETE',
        coverage_reasons=sorted(reasons), screening_blockers=sorted({g['kind'] for g in evidence.critical_gaps}),
        variable_evidence_slice=asdict(evidence), blocking_evidence=evidence.critical_gaps,
        initialization_proof=init_proof)


def fanout_diagnostics(variables, threshold=50):
    rows = {}
    for variable in variables:
        if variable.get('static_classification') != 'UNKNOWN':
            continue
        for gap in variable.get('blocking_evidence', []):
            row = rows.setdefault(gap['blocker_id'], dict(blocker_id=gap['blocker_id'], kind=gap['kind'],
                file=gap.get('file'), line=gap.get('line'), symbol_ids=set(), relevance_proofs=[]))
            row['symbol_ids'].add(variable['symbol_id'])
            row['relevance_proofs'].append(dict(symbol_id=variable['symbol_id'], reason=gap['relevance']))
    for row in rows.values():
        row['symbol_ids'] = sorted(row['symbol_ids'])
        row['blocker_fanout'] = len(row['symbol_ids'])
        row['suspected_overpropagation'] = row['blocker_fanout'] > threshold
        row['diagnostic'] = '疑似 UNKNOWN 过度传播；逐项核对相关性证明' if row['suspected_overpropagation'] else ''
    return sorted(rows.values(), key=lambda row: (-row['blocker_fanout'], row['blocker_id']))
