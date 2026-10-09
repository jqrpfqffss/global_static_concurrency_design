"""Invented protocol payloads ONLY for tests, never model or project evidence."""
def structured_fields(status='CONFIRMED', review_type='VARIABLE'):
    unknown = status in {'NEED_MORE_CONTEXT', 'LIKELY'}
    safe = status in {'REVIEWED_SAFE', 'FALSE_POSITIVE'}
    participants = [dict(id=actor, label='Protocol fixture '+actor,
                         eligibility='UNKNOWN' if status == 'LIKELY' and actor == 'B' else 'ACTUAL',
                         entry='fixture entry', access='fixture access', evidence_refs=[1])
                    for actor in ['A', 'B']] if status != 'NEED_MORE_CONTEXT' else []
    if status == 'NEED_MORE_CONTEXT':
        scenarios = []
    elif status == 'LIKELY':
        scenarios = [dict(title='Protocol fixture unresolved', kind='UNRESOLVED',
                          precondition='Fixture condition', expected='Fixture expected',
                          actual='Fixture unknown', steps=[])]
    else:
        scenarios = [dict(title='Protocol fixture scenario', kind='BLOCKED' if safe else 'CONFLICT',
                          precondition='Fixture only', expected='Fixture expected', actual='Fixture actual',
                          steps=[] if safe else [dict(actor_id=actor, action='Fixture action',
                              state_before='Fixture before', state_after='Fixture after', evidence_refs=[1])
                              for actor in ['A', 'B']])]
    return dict(schema_version=2, review_type=review_type, explanation=dict(
        summary='Protocol fixture only', cause='Fixture cause', scheduling='Fixture scheduling',
        evidence_refs=[] if status == 'NEED_MORE_CONTEXT' else [1], participants=participants, scenarios=scenarios,
        missing_evidence=['Fixture missing scheduling'] if unknown else []))
