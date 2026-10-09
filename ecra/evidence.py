"""Variable-local evidence and conflict-first bare-metal classification.

Diagnostics are not taints. Every blocking gap retains its source and the
specific storage/entry relation that can hide another conflicting access.
"""
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field, fields

from .common import digest
from .linker_symbols import linker_definitions


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
SHARED_REASONS = {
    'SHARED_SINGLE_WRITER_READERS': '共享访问，无需复核：单一物理上下文写入，其余上下文仅执行独立标量读取',
}
READS = {'READ', 'WHOLE_OBJECT_READ', 'DMA_READ'}
WRITES = {'WRITE', 'RMW', 'WHOLE_OBJECT_WRITE', 'DMA_WRITE'}
RUNTIME = READS | WRITES
CLASSIFIED_STATES = {'SAFE_PROVEN', 'SHARED_NO_REVIEW', 'SUSPECT', 'UNKNOWN'}
SCREENED_STATES = {'SAFE_PROVEN', 'SHARED_NO_REVIEW'}
REVIEW_STATES = {'SUSPECT', 'UNKNOWN'}
ENTRY_GAPS = {'FUNCTION_ADDRESS', 'MISSING_SOURCE_CALLER', 'ASSEMBLY_FUNCTION_REFERENCE',
              'UNKNOWN_CALLBACK_ENTRY', 'UNRESOLVED_REGISTERED_ENTRY', 'TASK_ENTRY_WITHOUT_DEFINITION',
              'UNRESOLVED_VECTOR_ENTRY', 'UNRESOLVED_NONLOCAL_JUMP'}
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
    'PARTIAL_PARSE_REGION': 'UNKNOWN_RELEVANT_PARTIAL_TU',
    'NONLOCAL_JUMP_CONTEXT': 'UNKNOWN_EXECUTION_CONTEXT',
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
    call_edge_indices: list = field(default_factory=list)
    call_edges_reference: str = 'facts.json:calls'
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
        self.variables_by_id = {v['symbol_id']: v for v in facts['variables']}
        self.contexts_by_id = {row['id']: row for row in facts.get('contexts', ())}
        self.owner_contexts = defaultdict(set)
        for binding in facts.get('context_bindings', ()):
            self.owner_contexts[binding['function_id']].add(binding['context_id'])
        self.linker_definitions = linker_definitions(
            coverage.get('build_closure', {}), coverage.get('project_root'))
        self.call_edges_by_caller = defaultdict(list)
        for index, call in enumerate(facts['calls']):
            self.call_edges_by_caller[call['caller_function_id']].append(
                (index, call.get('callee_function_id')))
            if call.get('callee_function_id'):
                self.reverse[call['callee_function_id']].add(call['caller_function_id'])
        self.failed_files = {u.get('file') for u in facts['unknowns'] if u['kind'] == 'PARSE_FAILED'}
        self.failed_files.update(u['source_file'] for u in facts.get('translation_units', [])
                                 if u.get('parse_status') == 'FAILED')
        escaped_entry_sites = defaultdict(list)
        for issue in facts['unknowns']:
            if issue.get('symbol_id'):
                self.by_symbol[issue['symbol_id']].append(issue)
            if issue.get('target_function_id') and issue['kind'] in ENTRY_GAPS:
                # An opaque callback slot can create an executor only if the
                # assignment site itself can execute. A linked but unreachable
                # HAL DMA helper must not become an entry for unrelated runs.
                if issue.get('function_id') in self.unreachable:
                    continue
                if issue['kind'] == 'FUNCTION_ADDRESS':
                    # Address formation inside a dispatch table is ordinary
                    # data flow. Only an actual opaque consumer can introduce
                    # an additional, unknown execution source.
                    if issue.get('actual_escape'):
                        escaped_entry_sites[issue['target_function_id']].append(issue)
                else:
                    self.entries[issue['target_function_id']].append(issue)
        for target, sites in escaped_entry_sites.items():
            # Any one opaque consumer leaves this function's entry context
            # unresolved. Keep every original site in facts['unknowns']; the
            # variable-local slice needs one blocker for that target function.
            ordered = sorted(sites, key=lambda row: (
                row.get('file') or '', row.get('line') or 0,
                row.get('offset') or 0, row.get('function_id') or ''))
            first = ordered[0]
            self.entries[target].append(dict(
                kind='FUNCTION_ADDRESS', target_function_id=target,
                function_id=first.get('function_id'), file=first.get('file'),
                line=first.get('line'), offset=first.get('offset'),
                actual_escape=True, entry_site_count=len(ordered),
                entry_site_function_ids=sorted({row.get('function_id') for row in ordered
                                                if row.get('function_id')}),
                entry_site_has_unowned=any(not row.get('function_id') for row in ordered),
                entry_sites_reference='facts.json:unknowns (FUNCTION_ADDRESS, actual_escape, target_function_id)',
                entry_site_sample=[dict(file=row.get('file'), line=row.get('line'),
                                        function_id=row.get('function_id'), offset=row.get('offset'))
                                   for row in ordered[:8]]))
        self.ancestor_cache = {}
        self.issue_identity_cache = {}
        self.gap_row_cache = {}

    def ancestors(self, fid):
        if fid not in self.ancestor_cache:
            found, todo = {fid}, [fid]
            while todo:
                for caller in self.reverse[todo.pop()] - found:
                    found.add(caller)
                    todo.append(caller)
            self.ancestor_cache[fid] = found
        return self.ancestor_cache[fid]

    def entry_after_init_writes(self, issue, writers, proof):
        """An IRQ-only callback registration cannot race with proven init writes.

        Every publisher must execute in an IRQ whose concrete vector slot is
        covered by the initialization proof's NVIC enable barrier. The callback
        must not be able to reach any of this variable's writers. In all other
        cases the unknown entry remains a critical gap.
        """
        if (issue.get('kind') != 'FUNCTION_ADDRESS' or not proof or not writers
                or issue.get('entry_site_has_unowned')):
            return False
        if {row['access_id'] for row in writers} != set(proof.get('write_access_ids', ())):
            return False
        target = issue.get('target_function_id')
        if not target or any(target in self.ancestors(row['function_id']) for row in writers):
            return False
        slots = {int(value) + 16
                 for barrier in proof.get('irq_barriers', ())
                 for event in barrier.get('enables', ())
                 for value in event.get('argument_values', ())
                 if isinstance(value, int)}
        owners = issue.get('entry_site_function_ids') or [issue.get('function_id')]
        if (not slots or not owners or any(not self.owner_contexts.get(owner)
                                          or self.entries.get(owner) for owner in owners)):
            return False
        return all(self.contexts_by_id.get(cid, {}).get('physical_kind') == 'IRQ'
                   and self.contexts_by_id[cid].get('slot') in slots
                   for owner in owners for cid in self.owner_contexts[owner])

    def build(self, variable, accesses, contexts, protection, init_proof=None):
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
            call_edge_indices=sorted(index for fid in ancestors
                                     for index, callee in self.call_edges_by_caller[fid]
                                     if callee in ancestors),
            protection=protection,
            whole_object_effects=[a['access_id'] for a in runtime if a.get('inherited_from_access_id')])
        unique_gaps = {}

        def gap(issue, code, reason):
            issue_key = id(issue)
            if issue_key not in self.issue_identity_cache:
                identity = {field: issue[field] for field in (
                    'kind', 'file', 'line', 'column', 'offset', 'function_id',
                    'caller_function_id', 'callee_function_id', 'target_function_id',
                    'access_id', 'call_id', 'reason_code') if field in issue}
                # Retain the issue to prevent Python from reusing its id for a
                # later temporary gap record in this analysis run.
                self.issue_identity_cache[issue_key] = (
                    issue, digest(issue), 'B-' + digest(identity)[:20])
            _, issue_digest, blocker_id = self.issue_identity_cache[issue_key]
            key = (issue_digest, code, reason)
            if key in unique_gaps:
                return
            row = self.gap_row_cache.get(key)
            if row is None:
                row = dict(issue, reason_code=code, relevance=reason)
                # Identify a blocker by its source site and edge, rather than
                # re-hashing target lists for every member reached by it.
                row['blocker_id'] = blocker_id
                self.gap_row_cache[key] = row
            unique_gaps[key] = row
            result.critical_gaps.append(row)

        for issue in self.by_symbol[sid]:
            if issue.get('function_id') in self.unreachable:
                continue
            kind = issue['kind']
            if kind == 'NONLOCAL_JUMP_CONTEXT' and not writers:
                continue
            if kind == 'DMA_SHARED_REVIEW' and not writers:
                # Proven DMA reads and CPU reads cannot conflict merely
                # because their lifetimes overlap. Unresolved direction,
                # buffers, escapes and actual DMA writes remain blockers.
                continue
            gap(issue, SYMBOL_CODES.get(kind, 'UNKNOWN_RELEVANT_ALIAS'),
                '该事实直接绑定目标存储，可能引入尚未恢复的访问。')
            if kind == 'ADDRESS_ESCAPE':
                result.address_escapes.append(issue)
        # An unknown execution source is immaterial when every possible
        # access to this storage is a read. It cannot manufacture a writer.
        if writers:
            writer_rows = [a for a in runtime if a['access_kind'] in WRITES]
            for fid in sorted(ancestors):
                for issue in self.entries[fid]:
                    if self.entry_after_init_writes(issue, writer_rows, init_proof):
                        continue
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
        from .missing_source import may_reference
        for file in sorted(self.failed_files - {None}):
            # Internal linkage cannot be named by another TU. Exported storage
            # is visible to a genuinely missing ACTIVE TU (not unbuilt files).
            if file in related_files or (variable.get('linkage') == 'EXTERNAL'
                                         and may_reference(self.facts, file, variable.get('name'))):
                gap(dict(kind='PARSE_FAILED', file=file), 'UNKNOWN_RELEVANT_MISSING_TU',
                    '当前目标编译单元解析失败；目标存储在该单元中可见，访问覆盖不能证明完整。')
        if not variable.get('definition_file'):
            root = self.variables_by_id.get(
                variable.get('root_symbol_id') or variable.get('array_root_symbol_id'), variable)
            linker_name = root.get('name')
            linker_proof = (self.linker_definitions.get(linker_name)
                            if root.get('linkage') == 'EXTERNAL' else None)
            declaration_files = [d.get('file') for d in root.get('declarations', [])]
            unused_header_declaration = (not accesses and declaration_files
                and all(str(file).lower().endswith(('.h', '.hh', '.hpp', '.hxx'))
                        for file in declaration_files if file)
                and all(declaration_files))
            if linker_proof:
                result.definition.update(linker_proof)
            elif unused_header_declaration:
                result.definition['origin'] = 'UNUSED_HEADER_DECLARATION'
            else:
                gap(dict(kind='DEFINITION_MISSING', file=next(iter(root.get('declarations', [])), {}).get('file')),
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
        result.critical_gaps = [unique_gaps[key] for key in sorted(unique_gaps)]
        return result


def access_role(kind):
    if kind in READS:
        return 'READ'
    if kind in WRITES:
        return 'WRITE'
    return None


def shared_no_review_proof(variable, evidence, accesses, contexts, pairs, cfg, snapshots=(),
                           coherence_evidence=()):
    """Prove the deliberately narrow single-writer/readers review exemption.

    This is not a safety proof.  It only establishes that every known
    interleaving is one naturally aligned scalar store observed by readers,
    with none of the destructive protocols listed by the classification
    contract.  Rejections are retained so a known conflict cannot silently
    fall through to SAFE_PROVEN.
    """
    runtime = [a for a in accesses if access_role(a.get('access_kind'))]
    reasons = set()
    physical = {}
    for access in runtime:
        ids = access.get('contexts', [])
        if not ids:
            reasons.add('SHARED_UNKNOWN_CONTEXT')
        for cid in ids:
            context = contexts.get(cid, {})
            pid = context.get('physical_id')
            if not pid:
                reasons.add('SHARED_UNKNOWN_CONTEXT')
                continue
            physical.setdefault(pid, []).append(access)
            if context.get('reentrant'):
                reasons.add('SHARED_REENTRANT_CONTEXT')
            if context.get('physical_kind') in {'DMA', 'EXTERNAL_ASYNC', 'UNKNOWN_CONTEXT'}:
                reasons.add('SHARED_ASYNC_OR_UNKNOWN_CONTEXT')
    writers = {pid for pid, rows in physical.items()
               if any(access_role(row.get('access_kind')) == 'WRITE' for row in rows)}
    readers = {pid for pid, rows in physical.items()
               if any(access_role(row.get('access_kind')) == 'READ' for row in rows)}
    if len(physical) < 2:
        reasons.add('SHARED_NOT_MULTI_CONTEXT')
    if len(writers) != 1:
        reasons.add('SHARED_NOT_SINGLE_WRITER')
    writer = next(iter(writers)) if len(writers) == 1 else None
    if not readers - writers:
        reasons.add('SHARED_NO_OTHER_READER')
    if any(access_role(row.get('access_kind')) == 'READ'
           for pid in writers for row in physical[pid]):
        # Until an ordered def-use proof exists, a writer-side read may be a
        # snapshot/check followed by a later writeback.
        reasons.add('SHARED_WRITER_ALSO_READS')
    if any(row.get('access_kind') == 'RMW' for row in runtime):
        reasons.add('SHARED_RMW')
    if any(row.get('access_kind', '').startswith('DMA_') for row in runtime):
        reasons.add('SHARED_DMA')
    if any(row.get('access_kind') in {'WHOLE_OBJECT_READ', 'WHOLE_OBJECT_WRITE'}
           or row.get('access_scope') in {'WHOLE_OBJECT_ACCESS', 'WHOLE_MEMBER_OBJECT_ACCESS',
                                          'INHERITED_WHOLE_OBJECT_ACCESS', 'OVERLAPPING_MEMBER_ACCESS',
                                          'OVERLAPPING_ARRAY_ACCESS'} for row in runtime):
        reasons.add('SHARED_OVERLAPPING_STORAGE')
    if any(row.get('via_alias') for row in runtime):
        # Variable width is not proof of the width used through a cast/alias.
        reasons.add('SHARED_ALIAS_ACCESS_WIDTH')
    if any(row.get('conditional_ancestor') for row in runtime):
        reasons.add('SHARED_CONDITIONAL_PROTOCOL')
    if snapshots:
        reasons.add('SHARED_STALE_SNAPSHOT')
    if coherence_evidence:
        reasons.add('SHARED_MULTI_FIELD_COHERENCE')
    if variable.get('is_bitfield_container'):
        reasons.add('SHARED_BITFIELD')
    if variable.get('is_union') or variable.get('overlap_groups'):
        reasons.add('SHARED_UNION_OR_OVERLAP')
    if '[*]' in variable.get('canonical_path', ''):
        reasons.add('SHARED_DYNAMIC_ARRAY_OVERLAP')
    if variable.get('is_pointer'):
        reasons.add('SHARED_POINTER_STATE')
    size = variable.get('size_bytes')
    alignment = variable.get('alignment_bytes')
    allowed = set(cfg.get('analysis', {}).get('atomic_access_width_bytes', (1, 2, 4)))
    native = max(1, cfg.get('project', {}).get('native_word_bits', 32) // 8)
    allowed = {width for width in allowed if isinstance(width, int) and 0 < width <= native}
    offset = variable.get('offset_bits')
    if (size not in allowed or not isinstance(alignment, int) or alignment < size
            or offset is not None and (offset < 0 or offset % (size * 8 if size else 1))):
        reasons.add('SHARED_NONATOMIC_WIDTH_OR_ALIGNMENT')
    if not variable.get('is_volatile') and not variable.get('is_atomic'):
        # Volatile is never sufficient for safety, but without volatile/atomic
        # semantics an ISR/foreground observer may be optimized into a stale
        # value even when the hardware load/store itself is indivisible.  Type
        # names are not evidence: only Clang's canonical ATOMIC kind qualifies.
        reasons.add('SHARED_COMPILER_VISIBILITY')
    if evidence.critical_gaps or evidence.address_escapes:
        reasons.add('SHARED_RELEVANT_UNKNOWN')
    if not pairs:
        reasons.add('SHARED_NO_CROSS_CONTEXT_PAIR')
    if reasons:
        return None, sorted(reasons)
    writer_rows = physical[writer]
    reader_rows = [row for pid, rows in physical.items() if pid != writer for row in rows]
    proof = dict(
        proof='SHARED_SINGLE_WRITER_READERS',
        writer_physical_context=writer,
        reader_physical_contexts=sorted(readers - {writer}),
        writer_access_ids=sorted({row['access_id'] for row in writer_rows}),
        reader_access_ids=sorted({row['access_id'] for row in reader_rows}),
        atomic_width_bytes=size,
        alignment_bytes=alignment,
        declared_alignment_bytes=variable.get('declared_alignment_bytes', alignment),
        root_alignment_bytes=variable.get('root_alignment_bytes', alignment),
        compiler_visibility='ATOMIC' if variable.get('is_atomic') else 'VOLATILE',
        excluded_hazards=['RMW', 'MULTI_WRITER', 'STALE_SNAPSHOT', 'CHECK_THEN_ACT', 'DMA',
                          'BITFIELD', 'UNION_OR_OVERLAP', 'WHOLE_OBJECT_MEMBER_CONFLICT',
                          'ADDRESS_ESCAPE', 'MULTI_FIELD_COHERENCE', 'UNKNOWN_WRITER'])
    return proof, []


def classify(evidence, accesses, contexts, pairs, protection, protection_note, init_proof=None,
             variable=None, cfg=None, snapshots=(), coherence_evidence=()):
    runtime = [a for a in accesses if a['access_kind'] in RUNTIME]
    conflicts = [p for p in pairs if p['may_concurrent'] and p['has_write_conflict']
                 and all(contexts[p[side]['context_id']]['physical_kind'] != 'UNKNOWN_CONTEXT'
                         for side in ('participant_a', 'participant_b'))]
    if protection == 'EFFECTIVE':
        for pair in conflicts:
            pair['protection_status'] = 'EFFECTIVE'
        conflicts = []
    if init_proof:
        init_accesses = set(init_proof.get('write_access_ids', ()))
        remaining = []
        for pair in conflicts:
            if pair.get('representation') == 'CONTEXT_ACCESS_PRODUCT':
                # A witness can be an initialization writer while another
                # member of the same compressed product writes at runtime.
                # Remove the group only when *every* represented writer was
                # proved to precede asynchronous enablement.
                writers = (set(pair['participant_a_write_access_ids'])
                           | set(pair['participant_b_write_access_ids']))
                initialization_excludes_pair = bool(writers) and writers <= init_accesses
            else:
                initialization_excludes_pair = (
                    pair['participant_a'].get('access_id') in init_accesses
                    or pair['participant_b'].get('access_id') in init_accesses)
            if initialization_excludes_pair:
                pair.update(mhp='NO', may_concurrent=False,
                            status='忽略（初始化与运行阶段不重叠）',
                            mhp_reason='INIT 写入发生在相关异步源首次使能之前。')
            else:
                remaining.append(pair)
        conflicts = remaining
    reasons = {g['kind'] for g in evidence.critical_gaps}
    if protection == 'UNRESOLVED':
        reasons.add('PROTECTION_UNRESOLVED')
    if any(p['relation']['relation'] == 'UNKNOWN_PREEMPTION' for p in conflicts):
        reasons.add('IRQ_PREEMPTION_UNRESOLVED')
    state, code, shared_code, shared_evidence = None, None, None, None
    shared_rejections = []
    known_destructive = False
    if conflicts:
        shared_evidence, shared_rejections = shared_no_review_proof(
            variable or {}, evidence, runtime, contexts, conflicts, cfg or {}, snapshots, coherence_evidence)
        known_destructive = any(reason != 'SHARED_RELEVANT_UNKNOWN' for reason in shared_rejections)
    if conflicts and known_destructive:
        state = 'SUSPECT'
        explanation = '存在已知跨物理上下文修改冲突；尚未证明不能交错或受到完整有效保护。'
        if protection == 'UNRESOLVED':
            explanation += '保护有效性待确认。'
    elif conflicts and shared_evidence:
        state = 'SHARED_NO_REVIEW'
        shared_code = 'SHARED_SINGLE_WRITER_READERS'
        explanation = SHARED_REASONS[shared_code]
    elif evidence.critical_gaps:
        state = 'UNKNOWN'
        explanation = '变量相关证据缺口可能隐藏额外冲突：' + '、'.join(sorted({g['reason_code'] for g in evidence.critical_gaps}))
    elif conflicts:
        state = 'SUSPECT'
        explanation = '存在跨物理上下文读写候选，但尚未满足单写者只读观察的全部严格门禁。'
    else:
        state = 'SAFE_PROVEN'
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
        safe_reason_code=code, shared_reason_code=shared_code, shared_evidence=shared_evidence,
        shared_no_review_rejections=shared_rejections,
        unknown_reason_codes=sorted({g['reason_code'] for g in evidence.critical_gaps}),
        coverage='PARTIAL' if reasons else 'COMPLETE', analysis_coverage='PARTIAL' if reasons else 'COMPLETE',
        coverage_reasons=sorted(reasons), screening_blockers=sorted({g['kind'] for g in evidence.critical_gaps}),
        # Evidence rows are immutable after classification. Preserve their
        # shared identity instead of recursively cloning complete call edges,
        # alias target lists and protection traces for every member.
        variable_evidence_slice={item.name: getattr(evidence, item.name) for item in fields(evidence)},
        blocking_evidence=evidence.critical_gaps,
        initialization_proof=init_proof)


def fanout_diagnostics(variables, threshold=50):
    rows = {}
    for variable in variables:
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
