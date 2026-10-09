"""Check that a model risk verdict has a source-bound execution witness.

This gate rejects unsupported risk claims; it never promotes a candidate to
safe. An explicit source-backed override lets a reviewer correct incomplete
static facts without concealing a real conflict.
"""

RUNTIME_KINDS = {'READ', 'WRITE', 'RMW', 'DMA_READ', 'DMA_WRITE',
                 'WHOLE_OBJECT_READ', 'WHOLE_OBJECT_WRITE'}
WRITE_KINDS = {'WRITE', 'RMW', 'DMA_WRITE', 'WHOLE_OBJECT_WRITE'}


def feasible_pairs(packet, *, confirmed=False):
    finding = packet.get('finding') or {}
    if finding.get('protection_status') == 'EFFECTIVE':
        return []
    pairs = []
    for pair in finding.get('conflict_pairs', ()):
        if not pair.get('has_write_conflict') or not pair.get('may_concurrent'):
            continue
        relation = (pair.get('relation') or {}).get('relation')
        if relation == 'SERIAL' or pair.get('mhp') == 'NO':
            continue
        if pair.get('protection_status') == 'EFFECTIVE':
            continue
        if confirmed and (relation == 'UNKNOWN_PREEMPTION' or pair.get('mhp') == 'MAYBE'):
            continue
        left, right = pair.get('participant_a') or {}, pair.get('participant_b') or {}
        a, b = left.get('canonical_path'), right.get('canonical_path')
        if a and b and a != b and not finding.get('multi_field_coherence'):
            continue
        pairs.append(pair)
    return pairs


def risk_focus(packet):
    """Put identity and disqualifying facts before the static rule labels."""
    finding, variable = packet.get('finding') or {}, packet.get('variable') or {}
    accesses = finding.get('accesses') or []
    serial = [p.get('conflict_id') for p in finding.get('conflict_pairs', ())
              if (p.get('relation') or {}).get('relation') == 'SERIAL' or p.get('mhp') == 'NO']
    uncertain = [p.get('conflict_id') for p in finding.get('conflict_pairs', ())
                 if (p.get('relation') or {}).get('relation') == 'UNKNOWN_PREEMPTION']
    return dict(
        instruction='静态规则只是待推翻的假设。先逐项寻找反证，再评估可成立的最短交错。',
        object_identity=dict(symbol_id=finding.get('symbol_id'),
            canonical_path=variable.get('canonical_path') or variable.get('qualified_name'),
            resource_kind=variable.get('resource_kind'), is_pointer=bool(variable.get('is_pointer')),
            pointer_slot_separate_from_pointee=True,
            root_symbol_id=variable.get('root_symbol_id'), field_path=variable.get('field_path'),
            overlap_groups=variable.get('overlap_groups', [])),
        runtime_accesses=[dict(access_id=a.get('access_id'), kind=a.get('access_kind'),
            file=a.get('file'), line=a.get('line'), canonical_path=a.get('canonical_path'),
            contexts=a.get('contexts', []), reachability=a.get('reachability'),
            access_scope=a.get('access_scope')) for a in accesses if a.get('access_kind') in RUNTIME_KINDS],
        non_accesses=[dict(access_id=a.get('access_id'), kind=a.get('access_kind'),
            file=a.get('file'), line=a.get('line')) for a in accesses
            if a.get('access_kind') not in RUNTIME_KINDS],
        serial_or_excluded_pair_ids=serial, unknown_priority_pair_ids=uncertain,
        candidate_interleaving_pair_ids=[p.get('conflict_id') for p in feasible_pairs(packet, confirmed=True)],
        initialization_proof=variable.get('initialization_proof'),
        multi_field_coherence=variable.get('multi_field_coherence', []),
        protection_status=finding.get('protection_status'),
        note='列表里的候选交错仍需核对编译、回调实参、IRQ 使能、完整保护范围和业务结果。')


def _evidence_locations(answer):
    return {(e.get('file'), e.get('line')) for e in answer.get('evidence', ())}


def _pair_cited(pair, answer, finding):
    locations = _evidence_locations(answer)
    by_id = {a.get('access_id'): a for a in finding.get('accesses', ())}

    def cited(access_id):
        access = by_id.get(access_id)
        return (access is not None and access.get('access_kind') in RUNTIME_KINDS
                and access.get('reachability') != 'PROVEN_UNREACHABLE'
                and (access.get('file'), access.get('line')) in locations)

    if pair.get('representation') == 'CONTEXT_ACCESS_PRODUCT':
        # A large variable has one compact context product instead of every
        # access pair. The representative participant is not necessarily the
        # access cited by the reviewer; use the complete access-id selectors.
        left = [(i, 'WRITE') for i in pair.get('participant_a_write_access_ids', ())]
        left += [(i, 'READ') for i in pair.get('participant_a_read_access_ids', ())]
        right = [(i, 'WRITE') for i in pair.get('participant_b_write_access_ids', ())]
        right += [(i, 'READ') for i in pair.get('participant_b_read_access_ids', ())]
        return any(cited(a) and cited(b) and (ak == 'WRITE' or bk == 'WRITE')
                   and by_id[a].get('canonical_path') == by_id[b].get('canonical_path')
                   for a, ak in left for b, bk in right)
    left, right = pair.get('participant_a') or {}, pair.get('participant_b') or {}
    return (cited(left.get('access_id')) and cited(right.get('access_id'))
            and left.get('canonical_path') == right.get('canonical_path'))


def _validate_override(answer, packet, *, require_invariant=False):
    override = answer.get('risk_override')
    if not isinstance(override, dict) or not isinstance(override.get('reason'), str) or not override['reason'].strip():
        prefix = '单纯多个原子/对齐 store 不能确认风险；' if require_invariant else ''
        raise ValueError(prefix + '风险结论缺少可引用的静态事实反证/补证 risk_override.reason')
    refs = override.get('evidence_refs')
    evidence = answer.get('evidence') or []
    if (not isinstance(refs, list) or len(set(refs)) < 2 or
            any(type(i) is not int or not 1 <= i <= len(evidence) for i in refs)):
        raise ValueError('risk_override 必须引用至少两处有效源码证据')
    for key in ('schedule_evidence_ref', 'protection_evidence_ref', 'outcome_evidence_ref'):
        if type(override.get(key)) is not int or override[key] not in refs:
            raise ValueError(f'risk_override.{key} 必须引用源码证据')
    accesses = override.get('accesses')
    if not isinstance(accesses, list) or len(accesses) != 2:
        raise ValueError('risk_override 必须给出两个真实访问点')
    paths = []
    for item in accesses:
        if not isinstance(item, dict) or item.get('kind') not in RUNTIME_KINDS:
            raise ValueError('risk_override 访问必须是 READ/WRITE/RMW/DMA，不能是 ADDRESS_TAKEN')
        ref = item.get('evidence_ref')
        if type(ref) is not int or ref not in refs:
            raise ValueError('risk_override 访问缺少源码引用')
        cited = evidence[ref - 1]
        if (item.get('file'), item.get('line')) != (cited.get('file'), cited.get('line')):
            raise ValueError('risk_override 访问位置与源码引用不一致')
        if not isinstance(item.get('context_id'), str) or not item['context_id']:
            raise ValueError('risk_override 必须明确两个执行上下文')
        path = item.get('canonical_path')
        if not isinstance(path, str) or not path:
            raise ValueError('risk_override 必须明确访问的 canonical storage')
        paths.append(path)
    if all(item['kind'] not in WRITE_KINDS for item in accesses):
        raise ValueError('risk_override 两个访问均不写入')
    if accesses[0]['context_id'] == accesses[1]['context_id'] and not override.get('reentrant'):
        raise ValueError('risk_override 不能将同一串行上下文写成两个参与者')
    variable = packet.get('variable') or {}
    identity = variable.get('canonical_path') or variable.get('qualified_name')
    cross_field_refs = override.get('invariant_evidence_refs')
    if identity and any(path != identity for path in paths) and (variable.get('is_pointer') or not cross_field_refs):
        raise ValueError('risk_override 访问的是其他存储对象；指针本体与 pointee 必须分开')
    if paths[0] != paths[1] and not cross_field_refs:
        raise ValueError('不同结构成员必须引用源码证明跨字段一致性约束')
    if cross_field_refs and (not isinstance(cross_field_refs, list) or
                             any(type(i) is not int or i not in refs for i in cross_field_refs)):
        raise ValueError('risk_override 的跨字段一致性依据引用无效')
    if require_invariant:
        invariant_refs = override.get('invariant_evidence_refs')
        if (not isinstance(invariant_refs, list) or not invariant_refs or
                any(type(i) is not int or i not in refs for i in invariant_refs)):
            raise ValueError('单纯多个原子/对齐 store 不能确认风险；必须引用协议约束')
    return override


def validate_risk_result(answer, packet):
    """Reject unsupported CONFIRMED/LIKELY, preserving failure for retry."""
    finding = packet.get('finding') or {}
    if not finding.get('symbol_id') or answer.get('status') not in {'CONFIRMED', 'LIKELY'}:
        return
    status = answer['status']
    accesses = [a for a in finding.get('accesses', ()) if a.get('access_kind') in RUNTIME_KINDS
                and a.get('reachability') != 'PROVEN_UNREACHABLE'
                and a.get('symbol_id', finding['symbol_id']) == finding['symbol_id']]
    if status == 'LIKELY':
        if not any(a.get('access_kind') in WRITE_KINDS for a in accesses) and not answer.get('risk_override'):
            raise ValueError('LIKELY 缺少本对象真实写入证据；未知不能作为风险兜底')
        likely_pairs = feasible_pairs(packet)
        if not likely_pairs and not answer.get('risk_override'):
            raise ValueError('LIKELY 没有可核实的候选交错；串行/保护/初始化证据不能当作风险')
        if likely_pairs and not any(_pair_cited(p, answer, finding) for p in likely_pairs) \
                and not answer.get('risk_override'):
            raise ValueError('LIKELY 未引用本对象两个候选访问点；须补充证据或给 NEED_MORE_CONTEXT')
        if answer.get('risk_override'):
            _validate_override(answer, packet)
        return
    scenario = answer['explanation']['scenarios'][0]
    if scenario['expected'].strip() == scenario['actual'].strip():
        raise ValueError('CONFIRMED 的预期与实际结果相同，未证明错误结果')
    pairs = feasible_pairs(packet, confirmed=True)
    cited_pairs = [p for p in pairs if _pair_cited(p, answer, finding)]
    if not cited_pairs:
        _validate_override(answer, packet)
    # Multiple plain aligned stores have a final order, but no demonstrated
    # loss on their own. RMW, readers, DMA and source-backed coherence remain.
    variable = packet.get('variable') or {}
    only_stores = bool(accesses) and all(a.get('access_kind') == 'WRITE' for a in accesses)
    width, alignment = variable.get('size_bytes'), variable.get('alignment_bytes')
    native = (packet.get('project_native_word_bits') or 32) // 8
    simple_stores = (only_stores and isinstance(width, int) and 0 < width <= native
                     and isinstance(alignment, int) and alignment >= width
                     and not finding.get('multi_field_coherence'))
    if simple_stores:
        _validate_override(answer, packet, require_invariant=True)
