"""Invented protocol payloads ONLY for tests, never model or project evidence."""
def structured_fields(status='CONFIRMED', review_type='VARIABLE'):
    unknown = status in {'NEED_MORE_CONTEXT', 'LIKELY'}
    safe = status in {'REVIEWED_SAFE', 'FALSE_POSITIVE'}
    participants = [dict(id=actor, label='协议测试参与者 '+actor,
                         eligibility='UNKNOWN' if status == 'LIKELY' and actor == 'B' else 'ACTUAL',
                         entry='测试入口', access='测试访问', evidence_refs=[1])
                    for actor in ['A', 'B']] if status != 'NEED_MORE_CONTEXT' else []
    if status == 'NEED_MORE_CONTEXT':
        scenarios = []
    elif status == 'LIKELY':
        scenarios = [dict(title='协议测试未决场景', kind='UNRESOLVED',
                          precondition='测试条件', expected='测试预期',
                          actual='测试未知状态', steps=[])]
    else:
        scenarios = [dict(title='协议测试场景', kind='BLOCKED' if safe else 'CONFLICT',
                          precondition='仅用于测试', expected='测试预期', actual='测试结果',
                          steps=[] if safe else [dict(actor_id=actor, action='测试操作',
                              state_before='测试前状态', state_after='测试后状态', evidence_refs=[1])
                              for actor in ['A', 'B']])]
    return dict(schema_version=2, review_type=review_type,
        missing_context=['测试中缺少调度条件'] if unknown else [], explanation=dict(
        summary='仅用于协议测试', cause='测试原因', scheduling='测试调度条件',
        evidence_refs=[] if status == 'NEED_MORE_CONTEXT' else [1], participants=participants, scenarios=scenarios,
        missing_evidence=['测试中缺少调度条件'] if unknown else []))
