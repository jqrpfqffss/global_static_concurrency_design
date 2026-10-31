import json
import sqlite3
from contextlib import closing, ExitStack
from collections import Counter, defaultdict

from .common import write_json, replace_file


def cell(s):
    return str(s if s is not None else "—").replace("|", "\\|").replace("\n", " ")


def location(row):
    return f"{row.get('file') or '未知'}:{row.get('line') or '?'}"


def write_database(path, facts, report, shared_threshold=None):
    # Replace a complete temporary DB atomically; never leave partially refreshed facts.
    temp = path.with_suffix(".db.tmp")
    if temp.exists():
        temp.unlink()
    rows_by_table = {k: v for k, v in facts.items() if isinstance(v, list) and (not v or isinstance(v[0], dict))}
    rows_by_table["findings"] = report["findings"]
    rows_by_table['review_safe_samples'] = report.get('review_safe_samples', [])
    from .shared_json import Plan, DEFAULT_THRESHOLD
    plan = Plan(dict(facts=facts, findings=report['findings'],
                     review_safe_samples=report.get('review_safe_samples', [])))
    shared = plan.logical_bytes >= (DEFAULT_THRESHOLD if shared_threshold is None else shared_threshold)
    serialize = plan.dumps if shared else lambda value: json.dumps(value, ensure_ascii=False)
    with closing(sqlite3.connect(temp)) as conn, conn:
        if shared:
            conn.execute('CREATE TABLE ecra_shared_json_metadata (version INTEGER, reference_key TEXT)')
            conn.execute('INSERT INTO ecra_shared_json_metadata VALUES (?,?)', (1, plan.marker))
            conn.execute('CREATE TABLE ecra_shared_json_pool (node_id INTEGER PRIMARY KEY, data TEXT NOT NULL)')
            conn.executemany('INSERT INTO ecra_shared_json_pool VALUES (?,?)',
                             ((i, plan.dumps(node, force=True)) for i, node in enumerate(plan.nodes)))
        for table, rows in rows_by_table.items():
            columns = sorted({key for row in rows for key in row}) or ["empty"]
            # All identifiers originate from our own fact schema, never from source text.
            conn.execute(f'CREATE TABLE "{table}" (' + ",".join(f'"{c}"' for c in columns) + ")")
            # sqlite3 consumes the iterator incrementally. Never materialize
            # a second serialized copy of an entire table in Python memory.
            values = ([serialize(row.get(c)) if isinstance(row.get(c), (dict, list)) else row.get(c)
                       for c in columns] for row in rows)
            conn.executemany(f'INSERT INTO "{table}" VALUES (' + ",".join("?" for _ in columns) + ")", values)
            if table == 'findings' and 'finding_id' in columns:
                # Covering index avoids reading enormous evidence overflow
                # pages merely to recover previous IDs at the next startup.
                conn.execute('CREATE INDEX finding_identity ON findings(finding_id)')
        if facts.get('pointer_target_sets'):
            # Encoded target references must be usable from SQLite as well as
            # facts.json. Dict/string-list pools are not ordinary fact tables.
            conn.execute('CREATE TABLE pointer_target_atoms (target_index INTEGER PRIMARY KEY, target TEXT)')
            conn.executemany('INSERT INTO pointer_target_atoms VALUES (?,?)',
                             enumerate(facts['pointer_target_atoms']))
            conn.execute('CREATE TABLE pointer_target_sets '
                         '(target_set_id TEXT PRIMARY KEY, encoding TEXT, block_bits INTEGER, data TEXT)')
            conn.executemany('INSERT INTO pointer_target_sets VALUES (?,?,?,?)',
                ((ident, facts['pointer_target_encoding'], facts.get('pointer_target_block_bits'),
                  json.dumps(value, ensure_ascii=False, separators=(',', ':')))
                 for ident, value in facts['pointer_target_sets'].items()))
        if facts["accesses"]:
            conn.execute("CREATE INDEX access_symbol ON accesses(symbol_id)")
            conn.execute("CREATE INDEX access_function ON accesses(function_id)")
    replace_file(temp, path)


class AtomicLines:
    """Write exactly join(lines, '\\n') without retaining all report text."""
    def __init__(self, path, initial=()):
        self.path, self.initial = path, initial
        self.temp = path.with_suffix(path.suffix+'.tmp')
        self.stream, self.count = None, 0
        self.finished = False

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.temp.open('w', encoding='utf-8')
        try:
            self.extend(self.initial)
        except BaseException:
            self.__exit__(*__import__('sys').exc_info())
            raise
        self.initial = ()
        return self

    def append(self, line):
        if not isinstance(line, str):
            raise TypeError('报告行必须是字符串')
        if self.finished:
            raise ValueError('报告已完成原子发布')
        if self.count:
            self.stream.write('\n')
        self.stream.write(line)
        self.count += 1

    def extend(self, lines):
        for line in lines:
            self.append(line)

    def __iadd__(self, lines):
        self.extend(lines)
        return self

    def finish(self):
        if not self.finished:
            self.stream.close()
            replace_file(self.temp, self.path)
            self.finished = True

    def __exit__(self, kind, value, traceback):
        try:
            if kind is None:
                self.finish()
            elif self.stream:
                self.stream.close()
        finally:
            self.temp.unlink(missing_ok=True)


def generate(out, facts, report, reviews):
    from .scan_persistence import is_canonical, persist
    if is_canonical(out):
        prepare(facts, report, reviews)
        return persist(out, facts, report, reviews)
    with ExitStack() as files:
        return _generate(out, facts, report, reviews, files)


def prepare(facts, report, reviews):
    from .html_report import category, review_records, write_html, risk_summary, final_conclusion, localized_records
    from .decisions import decision_label, effective_decision
    from .scope import validate_selection
    from .analysis import compact_conflict_pair_storage
    from .review_integrity import review_integrity
    from .review_integrity import review_targets
    compact_conflict_pair_storage(facts.get('variables', []))
    compact_conflict_pair_storage(report.get('findings', []))
    validate_selection(facts, report)
    # The published result must account for every target with a terminal
    # review record. A queue containing all IDs is structurally valid but is
    # not a completed review when any record is still PENDING or RUNNING.
    report['review_integrity'] = review_integrity(report, reviews, require_terminal=True)
    report['review_records'] = review_records(dict(findings=review_targets(report)), reviews)
    from .git_diff import selected_findings, presentation_view
    records = review_records(dict(findings=selected_findings(report)), reviews)
    records_by_id = {r['finding_id']: r for r in records}
    variables_by_id = {v['symbol_id']: v for v in facts['variables']}
    sample_records = review_records(dict(findings=report.get('review_safe_samples', [])), reviews)
    report['safe_sample_summary'] = dict(total=len(sample_records),
        completed=sum(r['state']=='DONE' for r in sample_records),
        unresolved=sum(category(r)=='unresolved' for r in sample_records))
    sample_findings = {item['finding_id']: item for item in report.get('review_safe_samples', [])}
    report['screened_sample_summary'] = {
        state: dict(total=sum(sample_findings.get(record['finding_id'], {}).get('static_classification') == state
                              for record in sample_records),
                    completed=sum(record['state'] == 'DONE'
                                  and sample_findings.get(record['finding_id'], {}).get('static_classification') == state
                                  for record in sample_records))
        for state in ('SAFE_PROVEN', 'SHARED_NO_REVIEW')}
    for finding in selected_findings(report):
        record = records_by_id[finding['finding_id']]
        finding['review_state'] = record['state']
        finding['review_status'] = record.get('status')
        finding['review_result'] = record
        finding['effective_decision'] = effective_decision(finding, record,
            variable=variables_by_id.get(finding.get('symbol_id')))
        finding['decision_label'] = decision_label(finding['effective_decision'], [record])
        finding['status'] = record['status'] if record['state'] == 'DONE' else 'NEED_OPENCODE_REVIEW'
        if record['state'] == 'DONE' and record.get('answer'):
            finding['review'] = record['answer']
        else:
            finding.pop('review', None)
    # A matrix/subset review must not inherit an old "all reviewed" summary.
    counts = Counter(category(r) for r in records)
    report['review_summary'] = dict(total=len(records), unresolved=counts['unresolved'],
                                   confirmed=counts['confirmed'], likely=counts['likely'],
                                   reviewed_safe_or_false_positive=counts['safe'])
    report['review_summary'].update({k: report['review_integrity'][k] for k in
        ('targets', 'archived', 'done', 'failed', 'pending', 'stale', 'missing', 'duplicate')})
    report['review_summary']['complete'] = report['review_integrity']['complete']
    report['review_summary']['all_done'] = report['review_integrity']['all_done']
    report['review_summary']['basis'] = '仅统计 OpenCode 原始复核结果与进度；最终风险分类见 risk_summary。'
    by_symbol = defaultdict(list)
    for f in selected_findings(report):
        if f.get('symbol_id'):
            by_symbol[f['symbol_id']].append(records_by_id[f['finding_id']])
    terminal = sum(all(category(r) in {'confirmed', 'safe'} for r in group) for group in by_symbol.values())
    report['review_summary']['variable_coverage'] = dict(
        total=(sum(v.get('static_classification') not in {'CONTAINER', 'OUT_OF_BUILD'}
                   and v.get('resource_kind') not in {'STRUCT_MEMBER_CONTAINER', 'STRUCT_CONTAINER', 'ARRAY_CONTAINER'}
                   for v in facts['variables'] if v['symbol_id'] in report['git_diff']['selected_symbol_ids']) if report.get('git_diff') else
               report.get('coverage', {}).get('static_classification', {}).get('total', len(facts['variables']))),
        statically_screened=sum(v.get('static_classification') in {'SAFE_PROVEN', 'SHARED_NO_REVIEW'}
                                for v in facts['variables'] if not report.get('git_diff')
                                or v['symbol_id'] in report['git_diff']['selected_symbol_ids']),
        queued=len(by_symbol), terminal=terminal, remaining=len(by_symbol)-terminal)
    view_facts, view_report = presentation_view(facts, report)
    report['risk_summary'] = risk_summary(view_facts, view_report, records_by_id)
    if report.get('git_diff'):
        report['risk_summary']['scope'] = 'CURRENT_GIT_DIFF'
        report['review_summary']['basis'] = '当前差异范围的原始复核结果与进度；完整构建静态分类保留在 coverage 与 findings。'
    report['final_conclusion'] = final_conclusion(view_report, records)
    if (counts['unresolved'] or counts['likely'] or not report['review_integrity']['complete']
            or report.get('git_diff', {}).get('fallback_reasons')) and report.get('run_status') == 'REVIEW_COMPLETE':
        report['run_status'] = 'INCOMPLETE'
    from .diagnostics import root_causes, root_causes_markdown
    diagnostic = root_causes(facts['variables'], report['coverage']['review_rates'])
    quality = report['coverage']['classification_quality']
    quality['root_cause_reason_counts'] = diagnostic['reason_counts']
    quality['root_cause_hotspots'] = diagnostic['hotspots'][:50]
    quality['counterfactual_upper_bounds'] = diagnostic['counterfactual_upper_bounds']
    return records_by_id, diagnostic


def _generate(out, facts, report, reviews, files):
    from .html_report import write_html, localized_records
    from .git_diff import selected_findings
    from .review_integrity import review_targets
    from .diagnostics import root_causes_markdown
    records_by_id, diagnostic = prepare(facts, report, reviews)
    for folder in ("inventory", "reports"):
        (out / folder).mkdir(parents=True, exist_ok=True)
    from .shared_json import write as write_shared_json
    write_shared_json(out / 'reports/root_cause_v2.json', diagnostic)
    (out / 'reports/classification_root_causes.md').write_text(
        root_causes_markdown(diagnostic), encoding='utf-8')
    del diagnostic
    write_shared_json(out / "facts.json", facts)
    write_shared_json(out / "inventory/global_static_inventory.json", facts["variables"])
    write_shared_json(out / "reports/global_static_concurrency.json", report)
    write_database(out / "facts.db", facts, report)
    funcs = {f["function_id"]: f for f in facts["functions"]}
    from .html_report import to_display_text, KINDS, RULES
    from .review_language import is_english_prose
    def zh(value):
        if value in KINDS:
            return KINDS[value]
        return to_display_text(value)

    def number(value):
        return str(value) if value is not None else '尚未确定'

    def chain(path):
        return " → ".join(funcs[fid]["name"] + " (" + location(funcs[fid]) + ")" if fid in funcs else fid for fid in path)

    inventory = files.enter_context(AtomicLines(out / 'inventory/global_static_inventory.md',
        ["# 全局变量与 static 变量完整清单", "", "清单覆盖全局变量、文件 static、函数 static（含头文件实例和 C++ 静态成员）及补充声明；普通局部变量、参数和结构体字段不作为共享对象盘点。完整性受报告覆盖门槛约束。", ""]))
    if not facts.get('context_call_graph', {}).get('path_lists_complete', True):
        inventory += ["调用路径以下仅列最短见证，条数不是全部路径数；完整调用证据包含全部入口、调用边与上下文，见 [facts.json](../facts.json) 的 context_call_graph、call_graph_slices 和 calls。保护与分类证明使用完整图。", ""]
    variable_risks = {v['symbol_id']: v for v in report['risk_summary']['variables']}
    inventory += ["| 变量 | 类别 | 定义 | 读上下文 | 写上下文 | 静态分类 / 覆盖率 | 最终分类 |", "|---|---|---|---|---|---|---|"]
    for v in facts["variables"]:
        inventory.append("| " + " | ".join(map(cell, [v["qualified_name"], zh(v["kind"]), f"{v.get('definition_file')}:{v.get('definition_line')}",
                         ", ".join('`' + c + '`' for c in v.get("readers", [])), ", ".join('`' + c + '`' for c in v.get("writers", [])),
                         f"{zh(v.get('static_classification', 'UNKNOWN'))} / {zh(v.get('analysis_coverage', 'PARTIAL'))}",
                         variable_risks.get(v['symbol_id'], {}).get('label', '不计入风险统计')])) + " |")
    for v in facts["variables"]:
        inventory += ["", f"## {v['qualified_name']}", "", f"- ID: `{v['symbol_id']}`", f"- 类型: `{v.get('type')}`；大小: {v.get('size_bytes')}；对齐: {v.get('alignment_bytes')}",
                      f"- const: {v.get('is_const')}；volatile: {v.get('is_volatile')}；翻译单元: {', '.join(v.get('translation_units', []))}", ""]
        inventory += [f"- 静态分类：{zh(v.get('static_classification', 'UNKNOWN'))}；依据：{v.get('classification_reason', '尚未证明')}",
                      f"- 最终分类：{variable_risks.get(v['symbol_id'], {}).get('label', '不计入风险统计')}",
                      f"- 分析覆盖率：{zh(v.get('analysis_coverage', 'PARTIAL'))}；缺口：{', '.join(v.get('coverage_reasons', [])) or '无'}",
                      f"- 保护：{zh(v.get('protection_status', 'NOT_FOUND'))}；说明：{v.get('protection_note', '无')}",
                      f"- 安全筛除依据：{v.get('safe_reason_code') or v.get('screening_reason') or '尚未证明'}；阻塞项：{', '.join(v.get('screening_blockers', [])) or '无'}",
                      f"- 不可达函数中的访问：{v.get('unreachable_access_count', 0)} 处（保留原始证据）"]
        for a in v.get("accesses", []):
            inventory.append(f"- {zh(a['access_kind'])} {location(a)} `{a['source_text']}`")
            complete = a.get('all_call_chains') or {cid: [path] for cid, path in a.get("call_chains", {}).items()}
            for cid, routes in complete.items():
                for path in routes:
                    inventory.append(f"  - `{cid}: {chain(path)}`")
            if a.get('reachability') == 'PROVEN_UNREACHABLE':
                inventory.append('  - PROVEN_UNREACHABLE：当前构建入口不可达')
            elif not a.get("contexts"):
                inventory.append("  - 执行上下文尚未确定")
    inventory.finish()
    cov = report["coverage"]
    md = ["# 全局变量与 static 变量并发排查报告", "", f"- 分析状态：**{zh(report['analysis_status'])}**", f"- 本轮状态：**{zh(report.get('run_status', 'SCANNED'))}**",
          f"- 变量：{len(facts['variables'])}；候选及盲区复核项：{len(report['findings'])}",
          f"- 编译单元：完整 {cov['translation_units_parsed']}；部分 {cov.get('translation_units_partial', 0)}；失败 {cov['translation_units_failed']}；可分析覆盖 {cov['parse_coverage_percent']}%（总计 {cov['translation_units_total']}）",
          f"- 函数上下文覆盖：{cov['context_coverage_percent']}%；未知访问：{cov['unknown_accesses']}",
          f"- 工程版本：{report.get('git_commit') if report.get('git_commit') not in {None, 'unknown'} else '未记录'}；源码指纹：{report.get('fingerprint') or '未记录'}", "",
          "本报告是风险候选和覆盖证据，不是全工程无风险证明。OpenCode 结论仍需工程/硬件验证。", "",
          "[变量完整清单](../inventory/global_static_inventory.md) · [未知项](unknown_contexts.md) · [OpenCode 复核](opencode_global_static_review.md)", ""]
    static = cov.get('static_classification', {})
    if report.get('git_diff'):
        md[2:2] = ['- 扫描模式：分支差异。以上覆盖、变量总数、静态归账和 RR 指标采用完整构建范围；下方风险条目、最终风险分类与复核队列采用当前差异范围。',
                   '- 当前差异清单行数（含容器）：' + str(len(report['git_diff']['selected_symbol_ids'])) + '；本轮复核项：' + str(len(review_targets(report))) + '。范围之外不代表安全。',
                   '- 未排除的潜在影响：' + str(len(report['git_diff'].get('conservative_symbol_ids', []))) + ' 个变量；只保留在覆盖证据，不自动列为本次差异。', '']
    if static:
        md[2:2] = [f"- 静态归账：总数 {static.get('total', 0)} = 静态安全 {static.get('safe_proven', 0)} + 共享无需复核 {static.get('shared_no_review', 0)} + 疑似风险 {static.get('suspect', 0)} + 无法判断 {static.get('unknown', 0)}", ""]
    rates = cov.get('review_rates', {})
    if rates:
        build, all_inventory = rates['rr_build'], rates['rr_all']
        md[2:2] = [
            f"- 当前构建复核比例（`RR_build`）：{build['numerator']}/{build['denominator']} = {build['percent']}%",
            f"- 全部盘点复核比例（`RR_all`）：{all_inventory['numerator']}/{all_inventory['denominator']} = {all_inventory['percent']}%（含 {rates['variant_inventory']} 个未分析的补充盘点声明）", ""]
    causes = ["# 无法判断的变量根因", "",
              f"无法判断的变量比例：{cov.get('unknown_percent', 0)}%；诊断阈值 10% 仅触发分析，不改变判定标准。", "",
              "| 原因 | 变量数 |", "|---|---:|"]
    causes += [f"| {cell(code)} | {count} |" for code, count in
               sorted(cov.get('unknown_reason_distribution', {}).items(), key=lambda pair: (-pair[1], pair[0]))]
    causes += ["", "## 阻塞项传播", "", "| 阻塞项 | 位置 | 影响变量数 | 诊断 |", "|---|---|---:|---|"]
    causes += [f"| {cell(item['kind'])} | {cell(location(item))} | {item['blocker_fanout']} | {cell(item['diagnostic'])} |"
               for item in cov.get('blocker_fanout', [])]
    causes += ["", "完整变量、源码位置和相关性解释保存在 facts.json 的 variable_evidence_slice / blocking_evidence。"]
    (out / 'reports/unknown_root_causes.md').write_text('\n'.join(causes), encoding='utf-8')
    summary = report['risk_summary']
    md[2:2] = ['## 与 HTML 一致的变量风险结论', '',
        '| 已确认风险 | 疑似并发风险 | 无法判断 | 已复核安全 / 误报 | 已排查不存在并发风险 | 未发现静态线索 | 补充声明 |',
        '|---|---|---|---|---|---|---|', '| ' + ' | '.join(str(summary['counts'][key]) for key in summary['labels']) + ' |', '',
        f"以上按 {summary['total_variables']} 个变量去重；另有 {summary['independent_gaps']} 项覆盖 / 依赖缺口。",
        'risk_summary 是风险分类；review_summary 是模型复核进度，二者不能相互替代。“已排查不存在并发风险”仅适用于无盲区且没有读写冲突的当前建模范围。', '']
    md = files.enter_context(AtomicLines(out / 'reports/global_static_concurrency.md', md))
    for limit in report["limitations"]:
        md.append("- " + limit)
    if facts.get('nvic_priorities'):
        md += ['', '## 中断优先级与源码证据', '', '源码配置、初始化结果和运行期有效性分别记录。子优先级不产生中断嵌套，共享向量内部串行；具体屏蔽条件按访问窗口核对。', '']
        for irq in facts['nvic_priorities']:
            md += ['- ' + ' / '.join(irq['irqn']) + ' → ' + ' / '.join(irq['vectors']),
                   '  - 有效位数：' + number(irq.get('priority_bits')) + '；初始化分组：' + number(irq.get('grouping')) + '；源码分组：' + str(irq.get('source_groupings', [])),
                   '  - ' + irq.get('reason', '有效性尚待核实')]
            for event in irq.get('source_configurations', []):
                md.append('  - 源码配置：抢占 ' + number(event.get('configured_preemption')) + '，子优先级 ' + number(event.get('configured_subpriority'))
                          + '；' + location(event) + '；调用链：' + ' → '.join(p.get('function') or p['function_id'] for p in event.get('call_chain', [])))
    md += ["", "## 编译覆盖与排除", ""]
    for key in ("unlisted_sources", "unlisted_headers", "excluded_sources"):
        label={'unlisted_sources':'未列入编译的源文件','unlisted_headers':'未列入编译的头文件','excluded_sources':'已排除的源文件'}[key]
        md.append(f"- {label}：" + (", ".join(cov.get(key, [])) or "无"))
    for u in facts["translation_units"]:
        if u["parse_status"] != "PARSED":
            md += [f"- {zh(u['parse_status'])}：{u['source_file']}"] + ["  - " + cell(
                '解析器返回错误；原文保留在 facts.json 中该编译单元的原始诊断。' if is_english_prose(d['message']) else d['message']) for d in u['diagnostics']]
    review_map = records_by_id
    for f in selected_findings(report):
        r = review_map.get(f["finding_id"], {})
        confidence={'HIGH':'高','MEDIUM':'中','LOW':'低'}.get(f['confidence'],zh(f['confidence']))
        md += ["", f"## {f['finding_id']} — {f['variable_name']}", "", f"- 排查优先级：{zh(f['risk_level'])}；置信度：{confidence}",
               f"- 静态分类：{zh(f.get('static_classification', 'UNKNOWN'))}；本项分类：{f['decision_label']}（`{f['effective_decision']}`）",
               *([f"- 变量最终分类：{variable_risks[f['symbol_id']]['label']}（`{variable_risks[f['symbol_id']]['decision']}`）"]
                 if f.get('symbol_id') in variable_risks else []),
               f"- 规则：{', '.join(f['rules'])}", f"- 定义：{location(f['definition'])}；ID: `{f.get('symbol_id')}`",
               f"- 保护：{zh(f['protection_status'])}；复核：{zh(r.get('state', 'PENDING'))} / {zh(r.get('status'))}",
               f"- 依据：{f.get('concurrency_reason', '分析盲区需要补充源码/配置证据')}", ""]
        for a in f["accesses"]:
            md.append(f"- **{zh(a['access_kind'])}** {location(a)} `{a['source_text']}`")
            complete = a.get('all_call_chains') or {cid: [path] for cid, path in a["call_chains"].items()}
            for cid, routes in complete.items():
                for path in routes:
                    md.append(f"  - `{cid}: {chain(path)}`")
            if not a["contexts"]:
                md.append("  - 执行上下文尚未确定")
        md += ["", "复核动作：核对所有调用入口、真实抢占与临界区；构造最短交错时序，检查旧值覆盖、事件丢失、重入和 DMA 生命周期。修复建议与验证方法见复核报告。"]
    md.finish()
    unknown = files.enter_context(AtomicLines(out / 'reports/unknown_contexts.md', ["# 未知上下文与分析盲区", ""]))
    for a in facts["accesses"]:
        if not a["contexts"]:
            unknown.append(f"- 执行上下文尚未确定 {a['symbol_id']} {location(a)}")
    for u in facts["unknowns"]:
        detail = u.get('reason') or u.get('hint') or RULES.get(u['kind'], ('该分析缺口尚待核实', ''))[0]
        if is_english_prose(detail):
            detail = '该分析缺口尚待核实；请按位置核对 facts.json 中保留的原始诊断。'
        unknown.append(f"- {u['kind']} {location(u)}: {cell(detail)}")
    unknown.finish()
    conclusion = report['final_conclusion']
    review_md = ["# OpenCode 逐项复核结果", "", '**最终结论：' + conclusion['label'] + '**', '',
                 conclusion['scope'], '', f"已返回回答 {conclusion['reviewed']}/{conclusion['total']}；仍未决 {len(conclusion['unresolved_findings'])} 项。", '',
                 "状态统计：" + '；'.join(zh(k) + ' ' + str(v) for k, v in Counter(r["state"] for r in reviews).items()), "",
                 "覆盖完整性：" + ("通过" if report['review_integrity']['complete'] else "复核结果不完整"), "",
                 "目标 {targets}；归档 {archived}；完成 {done}；失败 {failed}；待复核 {pending}；失效 {stale}；遗漏 {missing}；重复 {duplicate}".format(**report['review_integrity']), ""]
    review_md += ['- ' + error for error in report['review_integrity']['errors']]
    patches = ["# 最小修复建议（未修改固件）", ""]
    findings_by_id = {f['finding_id']: f for f in report['findings']}
    for r in localized_records(report['review_records']):
        review_md += [f"## {r['finding_id']}", "", f"- {zh(r['state'])} / {zh(r['status'])}"]
        finding = findings_by_id.get(r['finding_id'])
        if finding:
            review_md += [f"- 静态分类：{zh(finding.get('static_classification', 'UNKNOWN'))}；本项分类：{finding['decision_label']}（`{finding['effective_decision']}`）"]
            if finding.get('symbol_id') in variable_risks:
                variable = variable_risks[finding['symbol_id']]
                review_md += [f"- 变量最终分类：{variable['label']}（`{variable['decision']}`）"]
        if r.get("error"):
            review_md.append("- " + ('复核执行或校验未完成，请查看原始执行日志。' if is_english_prose(r['error']) else r['error']))
            review_md += [f"- 失败阶段：{r.get('failure_stage', 'unknown')}；错误类型：{r.get('error_type', 'unknown')}",
                          '- 历次尝试：[查看原始归档](../review/queue.json)']
            for key, label in (('prompt_file', '提示词'), ('packet_file', '证据包'),
                               ('stdout_file', '原始输出'), ('stderr_file', '原始错误')):
                name = r.get('execution', {}).get(key) or r.get(key)
                if name:
                    review_md.append(f'- {label}：[{name}](../review/{name})')
        if r.get('state') == 'DONE':
            from .review_presentation import review_markdown
            if r.get('language_correction'):
                review_md += ['本条已完成独立中文修正；原始结论、数值、工程标识符和源码位置保持一致。原始回答与修正记录分别保存在复核归档中。', '']
            review_md += review_markdown(r.get('answer', {}))
        elif r.get('answer'):
            review_md.append('- 旧回答已失效，不作为本轮结论；原始收据保留在 review/queue.json。')
        for attempt in r.get('attempts', [])[r.get('attempt_start', 0):]:
            if attempt.get('stage') != 'SUMMARY_FIX' and attempt.get('repair_for') != 'SUMMARY_FIX':
                continue
            review_md += ['', '### 摘要修复调用 ' + str(attempt.get('number', '')), '']
            review_md += ['```json', json.dumps(attempt, ensure_ascii=False, indent=2), '```', '']
            for stream, title in [('prompt', '完整提示词'), ('stdout', '原始响应'), ('stderr', '标准错误')]:
                name = attempt.get(stream + '_file')
                if name:
                    review_md.append(f'- {title}：[{name}](../review/{name})')
        review_md.append("")
        if r['state'] == 'DONE' and r["status"] in {"CONFIRMED", "LIKELY"}:
            patches += [f"## {r['finding_id']}", "", str(r['answer'].get('fix') or '未提供修复建议'), "",
                        str(r['answer'].get('verification') or '未提供验证建议'), ""]
    (out / "reports/opencode_global_static_review.md").write_text("\n".join(review_md), encoding="utf-8")
    (out / "reports/opencode_patch_plan.md").write_text("\n".join(patches), encoding="utf-8")
    write_html(out, facts, report, reviews)
