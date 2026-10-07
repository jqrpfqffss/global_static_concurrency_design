"""Compact, source-backed diagnostics for the static review queue.

Counterfactual counts are upper bounds for investigation. They never change a
classification and do not assert that the hypothetical proof is obtainable.
"""

from collections import Counter


def destructive_codes(variable, active):
    """Emit only D-patterns directly supported by current access evidence."""
    if not active:
        return []
    codes = set()
    failures = set(variable.get('shared_no_review_rejections', ()))
    for pair in active:
        left, right = pair['participant_a'], pair['participant_b']
        if pair.get('representation') == 'CONTEXT_ACCESS_PRODUCT':
            both_write = bool(pair.get('participant_a_write_access_ids')
                              and pair.get('participant_b_write_access_ids'))
        else:
            both_write = left.get('access_kind') in {'WRITE', 'RMW', 'DMA_WRITE'} and \
                         right.get('access_kind') in {'WRITE', 'RMW', 'DMA_WRITE'}
        if both_write and left.get('context_id') != right.get('context_id'):
            codes.add('D-01')
        if pair.get('relation', {}).get('relation') == 'MAY_REENTER':
            codes.add('D-02')
        if any(part.get('access_kind', '').startswith('DMA_')
               or str(part.get('context_id', '')).startswith('DMA:') for part in (left, right)):
            codes.add('D-03')
        if any(part.get('access_scope') in {'WHOLE_OBJECT_ACCESS',
                                            'INHERITED_WHOLE_OBJECT_ACCESS',
                                            'WHOLE_MEMBER_OBJECT_ACCESS'}
               and part.get('access_kind') in {'WRITE', 'RMW', 'DMA_WRITE'}
               for part in (left, right)):
            codes.add('D-06')
    if variable.get('is_bitfield_container'):
        codes.add('D-04')
    if (variable.get('is_union') or variable.get('overlap_groups')) and any(
            part.get('access_scope') == 'OVERLAPPING_MEMBER_ACCESS'
            for pair in active for part in (pair['participant_a'], pair['participant_b'])):
        codes.add('D-05')
    if variable.get('multi_field_coherence'):
        codes.add('D-07')
    if 'SHARED_NONATOMIC_WIDTH_OR_ALIGNMENT' in failures:
        codes.add('D-08')
    if 'SHARED_COMPILER_VISIBILITY' in failures:
        codes.add('D-10')
    return sorted(codes)


def root_causes(variables, review_rates):
    rows = []
    causes = Counter()
    hotspots = Counter()
    counterfactual = Counter()
    for variable in sorted(variables, key=lambda item: item['symbol_id']):
        state = variable.get('static_classification')
        if state not in {'SUSPECT', 'UNKNOWN'}:
            continue
        gaps = variable.get('blocking_evidence', [])
        blockers = sorted({gap['blocker_id'] for gap in gaps if gap.get('blocker_id')})
        if state == 'SUSPECT':
            gate_failures = sorted(set(variable.get('shared_no_review_rejections', ())))
            active = [pair for pair in variable.get('conflict_pairs', ())
                      if pair.get('may_concurrent') and pair.get('has_write_conflict')
                      and pair.get('protection_status') != 'EFFECTIVE']
            patterns = destructive_codes(variable, active)
            codes = patterns or gate_failures
            witness = None
            if active:
                pair = min(active, key=lambda item: item.get('conflict_id', ''))
                left, right = pair['participant_a'], pair['participant_b']
                witness = dict(conflict_id=pair.get('conflict_id'), mhp=pair.get('mhp'),
                    relation=pair.get('relation', {}).get('relation'),
                    participant_a=dict(access_id=left.get('access_id'),
                                       context_id=left.get('context_id'),
                                       file=left.get('file'), line=left.get('line')),
                    participant_b=dict(access_id=right.get('access_id'),
                                       context_id=right.get('context_id'),
                                       file=right.get('file'), line=right.get('line')))
                hotspot = left.get('file') or right.get('file')
                if hotspot:
                    hotspots[hotspot] += 1
        else:
            codes = sorted({gap['reason_code'] for gap in gaps if gap.get('reason_code')})
            gate_failures = []
            patterns = []
            witness = None
            for gap in gaps:
                if gap.get('file'):
                    hotspots[gap['file']] += 1
                    break
            if len(codes) == 1 and gaps:
                counterfactual[codes[0]] += 1
        causes.update(codes)
        rows.append(dict(symbol_id=variable['symbol_id'],
                         canonical_path=variable.get('canonical_path', variable.get('qualified_name')),
                         classification=state, reason_codes=codes,
                         destructive_codes=patterns, gate_failure_codes=gate_failures,
                         coherence_witnesses=[dict(member_symbol_ids=row.get('member_symbol_ids', []),
                            writer_access_ids=row.get('writer_access_ids', []),
                            reader_access_ids=row.get('reader_access_ids', []))
                            for row in variable.get('multi_field_coherence', [])] if state == 'SUSPECT' else [],
                         witness=witness, blocker_ids=blockers))
    return dict(schema_version=1, review_rates=review_rates,
                review_queue=len(rows), reason_counts=dict(sorted(causes.items())),
                hotspots=[dict(file=file, variables=count) for file, count in
                          sorted(hotspots.items(), key=lambda item: (-item[1], item[0]))],
                counterfactual_upper_bounds=dict(sorted(counterfactual.items())),
                counterfactual_note=(
                    'UNKNOWN 的全部相关缺口属于同一种原因时计入可能翻转上界；'
                    '只有重新分析并取得证明后才能改变分类。'),
                variables=rows)


def root_causes_markdown(data):
    rates = data['review_rates']
    build, all_inventory = rates['rr_build'], rates['rr_all']
    lines = ['# 静态分类根因', '',
             f"RR_build：{build['numerator']}/{build['denominator']} = {build['percent']}%。",
             f"RR_all：{all_inventory['numerator']}/{all_inventory['denominator']} = {all_inventory['percent']}%；其中 {rates['variant_inventory']} 个补充声明未分析访问。",
             '', '## 原因码（一个变量可命中多项）', '', '| 原因码 | 变量数 |', '|---|---:|']
    lines += [f'| {code} | {count} |' for code, count in
              sorted(data['reason_counts'].items(), key=lambda item: (-item[1], item[0]))]
    lines += ['', '## 可能翻转上界', '', data['counterfactual_note'], '',
              '| 唯一缺口类型 | 变量数上界 |', '|---|---:|']
    lines += [f'| {code} | {count} |' for code, count in
              sorted(data['counterfactual_upper_bounds'].items(), key=lambda item: (-item[1], item[0]))]
    lines += ['', '## 源文件热点', '', '| 文件 | 变量数 |', '|---|---:|']
    lines += [f"| {row['file'].replace('|', chr(92) + '|')} | {row['variables']} |"
              for row in data['hotspots'][:50]]
    lines += ['', '逐变量的冲突访问 ID、执行上下文与缺口 ID 见 `root_cause_v2.json`。', '']
    return '\n'.join(lines)
