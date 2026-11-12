"""Read-only operational projection of static facts, AI and human history.

This does not rewrite a static classification or manufacture a human decision.
Every consumer uses the same committed AI watermark and variable aggregation.
"""

from ..scan_store import symbol_columns_sql

AI_CTE = """
ai_snapshot AS (SELECT sequence,payload FROM human.ai_snapshots ORDER BY sequence DESC LIMIT 1),
ai_current AS (
 SELECT a.finding_id,a.state,a.payload FROM human.ai_events a,ai_snapshot snap
 WHERE json_extract(snap.payload,'$.ai_events_version')=2
 AND a.sequence<=json_extract(snap.payload,'$.watermark') AND NOT EXISTS(
 SELECT 1 FROM human.ai_events n WHERE n.finding_id=a.finding_id AND n.sequence>a.sequence
 AND n.sequence<=json_extract(snap.payload,'$.watermark'))
 UNION ALL
 SELECT a.finding_id,a.state,a.payload FROM ai_snapshot snap,json_each(snap.payload,'$.reviews') ref
 JOIN human.ai_events a ON a.sequence=json_extract(ref.value,'$.sequence')
 AND a.finding_id=json_extract(ref.value,'$.finding_id') AND a.hash=json_extract(ref.value,'$.hash')
 WHERE json_extract(snap.payload,'$.ai_events_version')=1
 UNION ALL
 SELECT json_extract(ref.value,'$.finding_id'),json_extract(ref.value,'$.state'),ref.value
 FROM ai_snapshot snap,json_each(snap.payload,'$.reviews') ref
 WHERE json_extract(snap.payload,'$.ai_events_version') IS NULL),
ai_verdicts AS (SELECT *,CASE WHEN state='DONE' THEN json_extract(payload,'$.status') END AS verdict FROM ai_current)
"""


EMPTY_AI = "ai_verdicts AS (SELECT NULL AS finding_id,NULL AS state,NULL AS payload,NULL AS verdict WHERE 0)"


def projection(human_heads, *, include_ai=True):
    # Match decisions.effective_decision: NEED_MORE_CONTEXT is a completed AI
    # answer, but cannot refute a static conflict. Keep it available in the AI
    # view while attributing the effective fallback to the static evidence.
    return human_heads.rstrip()+', '+(AI_CTE if include_ai else EMPTY_AI)+""",
symbol_attributes AS (
 SELECT """+symbol_columns_sql('s',provenance=True)+""",max(CASE e.key WHEN 'coverage_source' THEN CAST(n.value AS TEXT) END) AS coverage_source,
 max(CASE e.key WHEN 'parse_status' THEN CAST(n.value AS TEXT) END) AS parse_status,
 max(CASE e.key WHEN 'audit_status' THEN CAST(n.value AS TEXT) END) AS audit_status
 FROM symbols s LEFT JOIN edges e ON e.parent=s.node AND e.key IN ('coverage_source','parse_status','audit_status')
 LEFT JOIN nodes n ON n.id=e.child GROUP BY s.symbol_id),
finding_labels AS (
 SELECT f.symbol_id,CAST(id.value AS TEXT) AS finding_id,
 coalesce((SELECT CAST(n.value AS TEXT) FROM edges e JOIN nodes n ON n.id=e.child
 WHERE e.parent=f.node AND e.key='static_classification'),s.static_classification) AS static_classification
 FROM records f JOIN edges fid ON fid.parent=f.node AND fid.key='finding_id' JOIN nodes id ON id.id=fid.child
 JOIN symbols s ON s.symbol_id=f.symbol_id
 WHERE f.dataset='report' AND f.relation IN ('findings','review_safe_samples')
 GROUP BY f.symbol_id,id.value),
finding_results AS (
 SELECT f.*,a.state AS ai_state,a.verdict,
 CASE a.verdict WHEN 'CONFIRMED' THEN 0 WHEN 'LIKELY' THEN 1
 WHEN 'REVIEWED_SAFE' THEN 3 WHEN 'FALSE_POSITIVE' THEN 3 ELSE
 CASE f.static_classification WHEN 'SUSPECT' THEN 1 WHEN 'SAFE_PROVEN' THEN 3
 WHEN 'SHARED_NO_REVIEW' THEN 4 ELSE 2 END END AS result_rank
 FROM finding_labels f LEFT JOIN ai_verdicts a ON a.finding_id=f.finding_id),
symbol_review AS (
 SELECT symbol_id,min(result_rank) AS result_rank,count(*) AS finding_count,
 sum(CASE WHEN result_rank=4 THEN 1 ELSE 0 END) AS shared_count,
 sum(CASE WHEN verdict IN ('CONFIRMED','REVIEWED_SAFE','FALSE_POSITIVE') THEN 0 ELSE 1 END) AS supplemental_unresolved,
 sum(CASE WHEN verdict IN ('CONFIRMED','LIKELY','NEED_MORE_CONTEXT','REVIEWED_SAFE','FALSE_POSITIVE') THEN 1 ELSE 0 END) AS ai_answer_count,
 sum(CASE WHEN verdict IN ('CONFIRMED','LIKELY','REVIEWED_SAFE','FALSE_POSITIVE') THEN 1 ELSE 0 END) AS ai_decision_count,
 sum(CASE WHEN verdict IN ('REVIEWED_SAFE','FALSE_POSITIVE') THEN 1 ELSE 0 END) AS ai_safe_count
 FROM finding_results GROUP BY symbol_id),
result_base AS (
 SELECT s.*,coalesce(r.finding_count,0) AS finding_count,coalesce(r.ai_answer_count,0) AS ai_answer_count,
 CASE WHEN s.static_classification IN ('CONTAINER','OUT_OF_BUILD','NON_STORAGE') THEN s.static_classification
 WHEN s.coverage_source IN ('supplemental','inactive_branch') AND (r.finding_count IS NULL OR r.supplemental_unresolved>0) THEN 'UNKNOWN'
 WHEN r.result_rank=0 THEN 'CONFIRMED' WHEN r.result_rank=1 THEN 'LIKELY' WHEN r.result_rank=2 THEN 'UNKNOWN'
 WHEN r.result_rank>=3 AND r.shared_count>0 THEN 'SHARED_NO_REVIEW' WHEN r.result_rank=3 THEN 'SAFE'
 WHEN s.static_classification='SUSPECT' THEN 'LIKELY'
 WHEN s.static_classification='UNKNOWN' OR s.parse_status='FAILED' THEN 'UNKNOWN'
 WHEN s.static_classification='SAFE_PROVEN' OR s.audit_status='STATIC_SAFE_PROVEN' THEN 'SAFE'
 WHEN s.static_classification='SHARED_NO_REVIEW' THEN 'SHARED_NO_REVIEW' ELSE 'INVENTORY' END AS current_result,
 CASE WHEN r.ai_decision_count=0 OR r.ai_decision_count IS NULL THEN 'STATIC'
 WHEN r.ai_decision_count<r.finding_count THEN 'MIXED' ELSE 'OPENCODE' END AS result_source,
 CASE WHEN r.ai_safe_count=r.finding_count AND r.finding_count>0 THEN 1 ELSE 0 END AS ai_safe,
 coalesce(h.decision,'PENDING') AS human_record_decision,coalesce(h.handling_status,'TODO') AS handling_status
 FROM symbol_attributes s LEFT JOIN symbol_review r ON r.symbol_id=s.symbol_id LEFT JOIN heads h ON h.symbol_id=s.symbol_id),
current_results AS (
 SELECT *,CASE WHEN current_result IN ('CONFIRMED','LIKELY','UNKNOWN') THEN human_record_decision ELSE 'NOT_REQUIRED' END AS confirmation_state,
 CASE WHEN current_result IN ('CONFIRMED','LIKELY','UNKNOWN') THEN 1 ELSE 0 END AS requires_human_review,
 CASE WHEN current_result IN ('CONFIRMED','LIKELY','UNKNOWN') AND human_record_decision
 IN ('PENDING','NEED_MORE_EVIDENCE','RECHECK_REQUIRED','CONFLICT') THEN 1 ELSE 0 END AS needs_human_confirmation
 FROM result_base)
"""


def revision(conn):
    row=conn.execute("SELECT coalesce((SELECT max(sequence) FROM human.ai_snapshots),0),"
                     "(SELECT count(*) FROM human.events),(SELECT count(*) FROM human.prior_decisions)").fetchone()
    return ':'.join(map(str,row))


def summary(conn, source, args, *, include_static=False):
    # Aggregate the small, bounded set of enum combinations in one pass. Never
    # reconstruct a scan or run the expensive read-only projection per counter.
    counts,human,raw,safe_sources,static={},{},{},{},{}
    pending=derived_count=0
    rows=conn.execute('''SELECT current_result,confirmation_state,human_record_decision,result_source,
        needs_human_confirmation,count(*),sum(static_classification_derived),static_classification
        FROM ('''+source+''') GROUP BY current_result,confirmation_state,human_record_decision,result_source,
        needs_human_confirmation,static_classification''', args)
    for result,confirmation,record,origin,needs,count,derived,classification in rows:
        for mapping,key in ((counts,result),(human,confirmation),(raw,record)):
            mapping[key]=mapping.get(key,0)+count
        pending+=needs*count
        derived_count+=derived
        if result=='SAFE':safe_sources[origin]=safe_sources.get(origin,0)+count
        static[classification]=static.get(classification,0)+count
    result=dict(result_counts=counts,human_counts=human,raw_human_counts=raw,pending_count=pending,
                safe_sources=safe_sources,result_revision=revision(conn),derived_static_classification_count=derived_count)
    if include_static:
        result.update(static_counts=static,total=sum(static.values()))
    return result
