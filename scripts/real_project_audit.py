"""Inspect every classified variable and preserve bounded proof witnesses."""
import argparse
import json
from collections import defaultdict, deque
from pathlib import Path


READS = {'READ', 'WHOLE_OBJECT_READ', 'DMA_READ'}
WRITES = {'WRITE', 'RMW', 'WHOLE_OBJECT_WRITE', 'DMA_WRITE'}


def shortest_path(graph, start, targets):
    queue = deque([(start, [start])])
    seen = set()
    while queue:
        node, path = queue.popleft()
        if node in targets:
            return path
        if node in seen:
            continue
        seen.add(node)
        queue.extend((child, path + [child]) for child in graph.get(node, ()) if child not in seen)
    return []


def audit(facts):
    contexts = {row['id']: row for row in facts['contexts']}
    functions = {row['function_id']: row for row in facts['functions']}
    graph = defaultdict(set)
    for call in facts['calls']:
        if call.get('callee_function_id'):
            graph[call['caller_function_id']].add(call['callee_function_id'])
    rows, issues = [], []
    for variable in facts['variables']:
        state = variable.get('static_classification')
        if state not in {'SAFE_PROVEN', 'SHARED_NO_REVIEW', 'SUSPECT', 'UNKNOWN'}:
            continue
        sid = variable['symbol_id']
        runtime = [access for access in variable.get('accesses', ())
                   if access.get('access_kind') in READS | WRITES]
        writers = [access for access in runtime if access['access_kind'] in WRITES]
        physical = {contexts[cid]['physical_id'] for access in runtime
                    for cid in access.get('contexts', ()) if cid in contexts}
        gaps = variable.get('blocking_evidence', ())
        conflicts = [pair for pair in variable.get('conflict_pairs', ())
                     if pair.get('may_concurrent') and pair.get('has_write_conflict')]
        row = dict(symbol_id=sid, name=variable.get('qualified_name'), classification=state,
                   reason=variable.get('safe_reason_code') or variable.get('shared_reason_code'),
                   physical_contexts=sorted(physical), runtime_accesses=len(runtime),
                   runtime_writes=len(writers), blocker_count=len(gaps),
                   conflict_count=len(conflicts), initialization_proof=bool(variable.get('initialization_proof')))
        if state == 'SAFE_PROVEN':
            if gaps or any(not access.get('contexts') for access in runtime):
                issues.append((sid, 'SAFE_HAS_CRITICAL_GAP_OR_UNBOUND_ACCESS'))
            reason = row['reason']
            if reason == 'SAFE_SINGLE_FOREGROUND' and physical != {'FOREGROUND'}:
                issues.append((sid, 'FOREGROUND_REASON_WITH_OTHER_EXECUTOR'))
            if reason in {'SAFE_READ_ONLY', 'SAFE_MULTI_CONTEXT_READ_ONLY'} and writers:
                issues.append((sid, 'READ_ONLY_REASON_WITH_RUNTIME_WRITER'))
            if reason == 'SAFE_NO_RUNTIME_ACCESS' and runtime:
                issues.append((sid, 'NO_RUNTIME_REASON_WITH_RUNTIME_ACCESS'))
            if reason == 'SAFE_SINGLE_IRQ' and (len(physical) != 1 or not next(iter(physical)).startswith('IRQ:')):
                issues.append((sid, 'SINGLE_IRQ_REASON_WITH_OTHER_EXECUTOR'))
            if reason == 'SAFE_INIT_ONLY_WRITE':
                proof = variable.get('initialization_proof') or {}
                if {access['access_id'] for access in writers} != set(proof.get('write_access_ids', ())):
                    issues.append((sid, 'INIT_PROOF_DOES_NOT_COVER_ALL_WRITES'))
                if not proof.get('irq_barriers'):
                    issues.append((sid, 'INIT_PROOF_HAS_NO_ASYNC_BARRIER'))
            if conflicts:
                issues.append((sid, 'SAFE_HAS_POSSIBLE_WRITE_CONFLICT'))
        elif state == 'SUSPECT':
            if not conflicts:
                issues.append((sid, 'SUSPECT_WITHOUT_CONFLICT_WITNESS'))
            row['conflict_witness'] = [dict(
                left=pair['participant_a']['access_id'], right=pair['participant_b']['access_id'],
                left_context=pair['participant_a']['context_id'],
                right_context=pair['participant_b']['context_id'],
                relation=pair['relation']['relation'],
                file=pair['participant_a'].get('file'), line=pair['participant_a'].get('line'))
                for pair in conflicts[:3]]
        elif state == 'UNKNOWN':
            if not gaps:
                issues.append((sid, 'UNKNOWN_WITHOUT_BLOCKER'))
        if gaps:
            targets = {access['function_id'] for access in runtime}
            row['blockers'] = []
            for gap in gaps:
                if not gap.get('blocker_id') or not gap.get('file') or not gap.get('relevance'):
                    issues.append((sid, 'BLOCKER_MISSING_SOURCE_OR_RELATION'))
                target = gap.get('target_function_id')
                path = shortest_path(graph, target, targets) if target else []
                if target and not path:
                    issues.append((sid, 'ENTRY_BLOCKER_WITHOUT_CALL_PATH'))
                row['blockers'].append(dict(id=gap.get('blocker_id'), code=gap.get('reason_code'),
                                           file=gap.get('file'), line=gap.get('line'),
                                           target=functions.get(target, {}).get('name', target),
                                           call_path=[functions.get(fid, {}).get('name', fid) for fid in path],
                                           relation=gap.get('relevance')))
        rows.append(row)
    self_conflicts = [dict(symbol_id=variable['symbol_id'],
                           left=pair['participant_a']['context_id'],
                           right=pair['participant_b']['context_id'],
                           relation=pair['relation']['relation'])
                      for variable in facts['variables']
                      for pair in variable.get('conflict_pairs', ())
                      if pair['participant_a']['access_id'] == pair['participant_b']['access_id']
                      and pair.get('may_concurrent')]
    for pair in self_conflicts:
        if (pair['left'] == pair['right'] or
                contexts[pair['left']]['physical_id'] == contexts[pair['right']]['physical_id']):
            issues.append((pair['symbol_id'], 'UNPROVEN_SELF_CONFLICT'))
    return dict(variables=rows, self_conflicts=self_conflicts,
                issues=[dict(symbol_id=sid, issue=reason) for sid, reason in issues])


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('facts', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    result = audit(json.loads(args.facts.read_text(encoding='utf-8')))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(variables=len(result['variables']),
                          self_conflicts=len(result['self_conflicts']),
                          issues=result['issues']), ensure_ascii=False))
