"""Summarize an ECRA facts.json without importing analysis or changing facts."""
import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path


def metrics(facts):
    variables = [row for row in facts.get('variables', ())
                 if row.get('static_classification') in
                 {'SAFE_PROVEN', 'SHARED_NO_REVIEW', 'SUSPECT', 'UNKNOWN'}]
    states = Counter(row.get('static_classification') for row in variables)
    tus = Counter(row.get('parse_status') for row in facts.get('translation_units', ()))
    blockers = Counter(gap.get('reason_code') for row in variables
                       for gap in row.get('blocking_evidence', ()))
    unknowns = Counter(row.get('kind') for row in facts.get('unknowns', ()))
    pairs = [pair for row in variables for pair in row.get('conflict_pairs', ())]
    self_pairs = [pair for pair in pairs
                  if pair.get('participant_a', {}).get('access_id') ==
                     pair.get('participant_b', {}).get('access_id')]
    fanout = defaultdict(set)
    samples = defaultdict(list)
    for row in variables:
        samples[row['static_classification']].append(dict(
            symbol_id=row['symbol_id'], name=row.get('qualified_name', row.get('name')),
            reason=row.get('safe_reason_code') or row.get('shared_reason_code'),
            contexts=row.get('contexts', ()),
            blockers=[dict(id=gap.get('blocker_id'), code=gap.get('reason_code'),
                           file=gap.get('file'), line=gap.get('line'),
                           relation=gap.get('relevance'))
                      for gap in row.get('blocking_evidence', ())],
            conflict_witnesses=[dict(left=pair.get('participant_a', {}).get('access_id'),
                                     right=pair.get('participant_b', {}).get('access_id'),
                                     relation=pair.get('relation', {}).get('relation'))
                                for pair in row.get('conflict_pairs', ())
                                if pair.get('may_concurrent') and pair.get('has_write_conflict')][:8]))
        for gap in row.get('blocking_evidence', ()):
            fanout[gap.get('blocker_id')].add(row['symbol_id'])
    return dict(translation_units=len(facts.get('translation_units', ())),
                inventory_variables=len(facts.get('variables', ())),
                parse_status=dict(tus), variables=len(variables),
                classifications=dict(states), blockers=dict(blockers),
                raw_unknowns=dict(unknowns),
                initialization_proofs=sum(bool(row.get('initialization_proof')) for row in variables),
                conflict_pairs=len(pairs), self_conflicts=len(self_pairs),
                blocker_fanout=sorted((dict(blocker_id=key, affected_variable_count=len(value))
                                       for key, value in fanout.items()),
                                      key=lambda row: -row['affected_variable_count']),
                samples={key: sorted(value, key=lambda row: row['symbol_id'])
                         for key, value in samples.items()})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('facts', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    report = metrics(json.loads(args.facts.read_text(encoding='utf-8')))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: value for key, value in report.items()
                      if key not in {'samples', 'raw_unknowns', 'blocker_fanout'}}, ensure_ascii=False))
