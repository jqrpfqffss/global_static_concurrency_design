"""结构化根因诊断（OPT-02，规划 §21.2）。

基于分类器输出的破坏性模式码（D-xx）、NR 门槛失败码与 UNKNOWN 缺口码
统计根因，替代对 reason 文本的字符串匹配；多原因与"最小充分原因"分开
统计；按 root 与域对聚类热点。反事实统计给出"若某类近似被精化，最多
多少变量可离开队列"的上界估计，只用于排序与调度，从不直接改变结论。

DMA 桶修正：D-03 只在上下文 kind 为 DMA（真实硬件 DMA 域）时由检测器
给出；名称含 DMA 的 ISR 上下文不会再被误归入 DMA 冲突桶（规划 §3.1）。
"""
from collections import Counter, defaultdict

from .classify import DESTRUCTIVE_LABELS, context_domains

# 反事实统计的破坏性码：这些模式的存在依赖"存在可交错的写者域对"，
# 若精化后写者域对消失（例如回退继承写被修正），模式随之消失。
WRITE_PAIR_PATTERNS = {'D-01', 'D-02', 'D-04', 'D-07'}


def root_cause_stats(facts, report):
    """机器可读根因统计：reports/root_cause_v2.json 的内容。"""
    cov = report.get('coverage', {})
    build = cov.get('static_classification_build', {})
    variables = [v for v in facts['variables']
                 if v.get('resource_kind') not in {'STRUCT_CONTAINER', 'STRUCT_MEMBER_CONTAINER'}
                 and v.get('coverage_source') == 'compile_database']
    domain_of = context_domains({c['id']: c for c in facts.get('contexts', [])})
    suspect_multi = Counter()
    suspect_minimal = Counter()
    unknown_causes = Counter()
    gate_failures = Counter()
    pair_hotspots = Counter()
    root_hotspots = Counter()
    code_hotspots = defaultdict(set)
    inherited_write_flip = []
    for v in variables:
        status = v.get('static_classification')
        if status == 'SUSPECT':
            codes = v.get('destructive_codes') or []
            for code in codes:
                suspect_multi[code] += 1
                code_hotspots[code].add(v['symbol_id'])
            if codes:
                # 最小充分原因：固定优先序下的首码（诊断口径，仅供排序）。
                suspect_minimal[min(codes)] += 1
            root = v.get('root_symbol_id')
            if root:
                root_hotspots[root] += 1
            for w in v.get('witnesses') or []:
                pair = tuple(sorted(w.get('domains') or ()))
                if len(pair) >= 1:
                    pair_hotspots[(w.get('pattern'),) + pair] += 1
            flip, detail = _inherited_write_flip(v, domain_of)
            if flip:
                inherited_write_flip.append(detail)
        elif status == 'UNKNOWN':
            for reason in v.get('unknown_reason') or ['UNKNOWN_GENERAL']:
                unknown_causes[reason] += 1
                code_hotspots[reason].add(v['symbol_id'])
            for g in v.get('gate_results') or ():
                if g.get('result') == 'FAIL' and g.get('code'):
                    gate_failures[g['code']] += 1
    return dict(
        totals=dict(report_totals=cov.get('static_classification', {}),
                    build=build),
        suspect=dict(multi_cause=dict(suspect_multi),
                     minimal_cause=dict(suspect_minimal),
                     labels={code: DESTRUCTIVE_LABELS.get(code, code)
                             for code in set(suspect_multi) | set(suspect_minimal)}),
        unknown=dict(cause_distribution=dict(unknown_causes)),
        nr_gate_failures=dict(gate_failures),
        hotspots=dict(
            roots=[dict(root=root, queued=count) for root, count in root_hotspots.most_common(20)],
            domain_pairs=[dict(pattern=entry[0], domains=list(entry[1:]), count=count)
                          for entry, count in pair_hotspots.most_common(20)]),
        counterfactual=dict(
            fallback_inherited_writes=dict(
                description='去掉整对象回退产生的 INHERITED_WHOLE_OBJECT_ACCESS 写后，'
                            '不再存在任何可交错写者域对的 SUSPECT 变量数（RC-3 精化收益上界）。',
                variables=len(inherited_write_flip),
                symbol_ids=sorted(row['symbol_id'] for row in inherited_write_flip))))


def _inherited_write_flip(variable, domain_of):
    """RC-3 反事实（上界）：剔除回退继承写后写者域对是否消失。

    与规划 §3.3 的手工统计同口径：只考虑依赖写者域对的破坏性码；剔除
    INHERITED_WHOLE_OBJECT_ACCESS 写行后若写者域 ≤1 或全部剩余写者域
    两两不可交错，则该变量是精化候选。
    """
    codes = set(variable.get('destructive_codes') or [])
    if not codes or not codes <= WRITE_PAIR_PATTERNS:
        return False, None
    writer_domains = set()
    for a in variable.get('accesses') or []:
        if a.get('access_kind') not in {'WRITE', 'RMW'}:
            continue
        if a.get('access_scope') == 'INHERITED_WHOLE_OBJECT_ACCESS':
            continue
        for cid in a.get('contexts') or ():
            writer_domains.add(domain_of.get(cid, cid))
    if len(writer_domains) < 2:
        return True, dict(symbol_id=variable['symbol_id'], name=variable.get('qualified_name'),
                          remaining_writer_domains=sorted(writer_domains))
    return False, None


def write_root_cause_v2(out, facts, report):
    import json
    target = out / "reports" / "root_cause_v2.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(root_cause_stats(facts, report), ensure_ascii=False, indent=1),
                      encoding="utf-8")
