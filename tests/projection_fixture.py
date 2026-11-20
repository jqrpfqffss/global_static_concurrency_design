"""Small published Studio archive. All answers and identities are test data."""
from pathlib import Path

from ecra.cli import safe_review_samples
from ecra.human_reviews import ReviewStore
from ecra.scan_persistence import append_runtime, commit_review_result, review_head, review_writer, snapshot_head
from ecra.scan_store import EvidenceProvider, publish_scan


def create_checkpoint(out, *, extra_pending=0, diff=False):
    out = Path(out)
    out.mkdir(parents=True)
    states = dict(A='SUSPECT', B='SUSPECT', C='UNKNOWN', D='UNKNOWN', E='SAFE_PROVEN', F='SHARED_NO_REVIEW')
    states.update({f'Z{i:03d}': 'UNKNOWN' for i in range(extra_pending)})
    facts = dict(variables=[dict(symbol_id=s, name=s, qualified_name=s, static_classification=state,
                                 definition_file='Src/test.c', definition_line=i+1)
                            for i, (s, state) in enumerate(states.items())])
    findings = [dict(symbol_id=s, finding_id=fid, static_classification=states[s])
                for s, fid in [('A','a1'), ('A','a2'), ('B','b1'), ('C','c1'), ('D','d1')]]
    sample, = safe_review_samples(facts, count=1)
    report = dict(findings=findings+[dict(finding_id='gap1')], review_safe_samples=[sample])
    if diff:
        report['git_diff'] = dict(selected_symbol_ids=['B','C'], conservative_symbol_ids=[], deleted_variables=[])
    publish_scan(out/'scan.db', facts, report, scan_id=out.name, project_id='fixture')
    ReviewStore(out/'reviews.db', EvidenceProvider(out/'scan.db').metadata())
    append_runtime(out, {}, [dict(finding_id=f['finding_id'], state='PENDING') for f in findings+[sample, dict(finding_id='gap1')]])
    return sample['finding_id']


def publish(out, fid, verdict=None):
    """Submit through the native conditional commit, preserving the frozen ordinal."""
    with review_writer(out) as conn:
        sequence, _, _ = review_head(conn, fid, snapshot_head(conn)['watermark'])
        ordinal = conn.execute('SELECT ordinal FROM ai_events WHERE sequence=?', (sequence,)).fetchone()[0]
        row = dict(finding_id=fid, state='DONE' if verdict else 'TECH_FAILED', review_base_sequence=sequence)
        if verdict:
            row.update(status=verdict, answer=dict(status=verdict, reason='测试夹具 '+fid+' '+verdict))
        commit_review_result(conn, ordinal, row)
    return ordinal, row


def finish_checkpoint(out, sample):
    for fid, status in [('a1','REVIEWED_SAFE'), ('a2','REVIEWED_SAFE'), ('b1',None),
                        ('c1','CONFIRMED'), ('d1','NEED_MORE_CONTEXT'), (sample,'REVIEWED_SAFE')]:
        publish(out, fid, status)
