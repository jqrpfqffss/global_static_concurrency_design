import json
import sqlite3
from collections import Counter, defaultdict

from .common import write_json, replace_file


def cell(s):
    return str(s if s is not None else "—").replace("|", "\\|").replace("\n", " ")


def location(row):
    return f"{row.get('file') or '未知'}:{row.get('line') or '?'}"


# SUSPECT 展示规则 → 根因桶（Section 1 的用户 taxonomy）。
SUSPECT_CAUSE_BUCKETS = (
    ('GS-DMA-RACE', 'DMA'),
    ('GS-MULTI-FIELD-COHERENCE', 'MULTI_FIELD_COHERENCE'),
    ('GS-MULTI-WRITER', 'MULTI_WRITER'),
    ('GS-RMW-INTERLEAVE', 'RMW'),
    ('GS-STALE-SNAPSHOT', 'STALE_SNAPSHOT'),
    ('GS-LOCAL-STATIC-REENTRANT', 'FUNCTION_STATIC_REENTRANCY'),
    ('GS-STRUCT-INCONSISTENT', 'STRUCT_BITFIELD'),
    ('GS-TEAR-RISK', 'TEAR_RISK'),
    ('GS-OWNER-VIOLATION', 'OWNER_VIOLATION'),
    ('GS-MULTI-CONTEXT', 'MULTI_CONTEXT'),
)


def write_classification_diagnostics(out, facts, report):
    """classification_root_causes.md + classification_quality.html（Section 1/14）。"""
    from .common import digest
    cov = report['coverage']
    static = cov.get('static_classification', {})
    variables = facts['variables']
    compiled = [v for v in variables
                if v.get('resource_kind') not in {'STRUCT_CONTAINER', 'STRUCT_MEMBER_CONTAINER'}
                and v.get('coverage_source') == 'compile_database']
    total = len(compiled) or 1
    findings_by_sid = {f['symbol_id']: f for f in report['findings'] if f.get('symbol_id')}
    suspect_causes = Counter()
    for v in compiled:
        if v.get('static_classification') != 'SUSPECT':
            continue
        finding = findings_by_sid.get(v['symbol_id'], {})
        rules = set(finding.get('rules', []))
        matched = [label for code, label in SUSPECT_CAUSE_BUCKETS if code in rules]
        for label in (matched or ['其它']):
            suspect_causes[label] += 1
    unknown_causes = Counter()
    for v in compiled:
        if v.get('static_classification') != 'UNKNOWN':
            continue
        for reason in (v.get('unknown_reason') or ['UNKNOWN_GENERAL']):
            unknown_causes[reason] += 1
    queue = static.get('suspect', 0) + static.get('unknown', 0)
    md = ["# 分类根因统计（SUSPECT / UNKNOWN）", "",
          f"- TOTAL（编译变量）：{len(compiled)}",
          f"- SUSPECT：{static.get('suspect', 0)}（{round(100 * static.get('suspect', 0) / total, 1)}%）",
          f"- UNKNOWN：{static.get('unknown', 0)}（{round(100 * static.get('unknown', 0) / total, 1)}%）",
          f"- OpenCode 队列（SUSPECT+UNKNOWN）：{queue}（{round(100 * queue / total, 1)}%）", "",
          "| 原因 | 变量数 | 占总变量% | 占 SUSPECT/UNKNOWN% |", "|---|---|---|---|"]
    queue_total = max(1, queue)
    for label, count in suspect_causes.most_common():
        md.append(f"| SUSPECT:{label} | {count} | {round(100 * count / total, 1)} | {round(100 * count / queue_total, 1)} |")
    for label, count in unknown_causes.most_common():
        md.append(f"| UNKNOWN:{label} | {count} | {round(100 * count / total, 1)} | {round(100 * count / queue_total, 1)} |")
    md += ["", "SUSPECT 只统计破坏性冲突模式（双写 / RMW 交叉 / DMA 与 CPU 至少一方写 / 位域 / 多字段一致性）；"
           "单一写者 + 只读者的共享变量已归入 SHARED_NO_REVIEW，不进入本表。"]
    (out / "reports/classification_root_causes.md").write_text("\n".join(md), encoding="utf-8")

    quality = cov.get('classification_quality', {})
    if quality:
        rows = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>"
                       for k, v in sorted(quality.get('refinements', {}).items(), key=lambda kv: -kv[1]))
        html = ("<!doctype html><meta charset='utf-8'><title>分类质量报告</title>"
                "<style>body{font-family:system-ui;margin:2rem}table{border-collapse:collapse}"
                "td,th{border:1px solid #ccc;padding:.3rem .8rem}</style>"
                "<h1>分类质量报告</h1>"
                f"<p>TOTAL {quality.get('total')}；原始共享写候选 {quality.get('raw_shared_write_candidates')}；"
                f"精化后 OpenCode 队列 {quality.get('suspect') + quality.get('unknown')}"
                f"（Review Rate {quality.get('review_rate')}%）。</p>"
                "<h2>降噪贡献（按最终证明规则）</h2>"
                "<table><tr><th>精化规则</th><th>变量数</th></tr>" + rows + "</table>"
                "<p class='muted'>原始候选到最终分类的差值由破坏性冲突保留量（SUSPECT）与证据缺口（UNKNOWN）解释；"
                "降噪不得通过放宽冲突判定实现。</p>")
        (out / "classification_quality.html").write_text(html, encoding="utf-8")


def write_database(path, facts, report):
    # Replace a complete temporary DB atomically; never leave partially refreshed facts.
    temp = path.with_suffix(".db.tmp")
    if temp.exists():
        temp.unlink()
    conn = sqlite3.connect(temp)
    rows_by_table = {k: v for k, v in facts.items() if isinstance(v, list) and (not v or isinstance(v[0], dict))}
    rows_by_table["findings"] = report["findings"]
    rows_by_table['review_safe_samples'] = report.get('review_safe_samples', [])
    with conn:
        for table, rows in rows_by_table.items():
            columns = sorted({key for row in rows for key in row}) or ["empty"]
            # All identifiers originate from our own fact schema, never from source text.
            conn.execute(f'CREATE TABLE "{table}" (' + ",".join(f'"{c}"' for c in columns) + ")")
            values = []
            for row in rows:
                values.append([json.dumps(row.get(c), ensure_ascii=False) if isinstance(row.get(c), (dict, list)) else row.get(c) for c in columns])
            conn.executemany(f'INSERT INTO "{table}" VALUES (' + ",".join("?" for _ in columns) + ")", values)
        if facts["accesses"]:
            conn.execute("CREATE INDEX access_symbol ON accesses(symbol_id)")
            conn.execute("CREATE INDEX access_function ON accesses(function_id)")
    conn.close()
    replace_file(temp, path)


def generate(out, facts, report, reviews):
    from .html_report import category, review_records, write_html, risk_summary, final_conclusion
    from .scope import validate_selection
    from .analysis import compact_conflict_pair_storage
    compact_conflict_pair_storage(facts.get('variables', []))
    compact_conflict_pair_storage(report.get('findings', []))
    validate_selection(facts, report)
    records = review_records(report, reviews)
    records_by_id = {r['finding_id']: r for r in records}
    sample_records = review_records(dict(findings=report.get('review_safe_samples', [])), reviews)
    report['safe_sample_summary'] = dict(total=len(sample_records),
        completed=sum(r['state']=='DONE' for r in sample_records),
        unresolved=sum(category(r)=='unresolved' for r in sample_records))
    for finding in report['findings']:
        record = records_by_id[finding['finding_id']]
        finding['review_state'] = record['state']
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
    by_symbol = defaultdict(list)
    for f in report['findings']:
        if f.get('symbol_id'):
            by_symbol[f['symbol_id']].append(records_by_id[f['finding_id']])
    terminal = sum(all(category(r) in {'confirmed', 'safe'} for r in group) for group in by_symbol.values())
    report['review_summary']['variable_coverage'] = dict(
        total=len(facts['variables']),
        statically_screened=sum(v.get('audit_status') == 'SCREENED_NO_CONCURRENCY_RISK' for v in facts['variables']),
        queued=len(by_symbol), terminal=terminal, remaining=len(by_symbol)-terminal)
    report['risk_summary'] = risk_summary(facts, report, records_by_id)
    report['final_conclusion'] = final_conclusion(report, records)
    if (counts['unresolved'] or counts['likely']) and report.get('run_status') == 'REVIEW_COMPLETE':
        report['run_status'] = 'INCOMPLETE'
    for folder in ("inventory", "reports"):
        (out / folder).mkdir(parents=True, exist_ok=True)
    write_json(out / "facts.json", facts)
    write_json(out / "inventory/global_static_inventory.json", facts["variables"])
    write_json(out / "reports/global_static_concurrency.json", report)
    write_database(out / "facts.db", facts, report)
    funcs = {f["function_id"]: f for f in facts["functions"]}

    def chain(path):
        return " → ".join(funcs[fid]["name"] + " (" + location(funcs[fid]) + ")" if fid in funcs else fid for fid in path)

    inventory = ["# 全局变量与 static 变量完整清单", "", "清单覆盖全局变量、文件 static、函数 static（含头文件实例和 C++ 静态成员）及补充声明；普通局部变量、参数和结构体字段不作为共享对象盘点。完整性受报告覆盖门槛约束。", ""]
    inventory += ["| 变量 | 类别 | 定义 | 读上下文 | 写上下文 | 静态分类 / 覆盖率 |", "|---|---|---|---|---|---|"]
    for v in facts["variables"]:
        inventory.append("| " + " | ".join(map(cell, [v["qualified_name"], v["kind"], f"{v.get('definition_file')}:{v.get('definition_line')}",
                         ", ".join(v.get("readers", [])), ", ".join(v.get("writers", [])),
                         f"{v.get('static_classification', 'UNKNOWN')} / {v.get('analysis_coverage', 'PARTIAL')}"])) + " |")
    for v in facts["variables"]:
        inventory += ["", f"## {v['qualified_name']}", "", f"- ID: `{v['symbol_id']}`", f"- 类型: `{v.get('type')}`；大小: {v.get('size_bytes')}；对齐: {v.get('alignment_bytes')}",
                      f"- const: {v.get('is_const')}；volatile: {v.get('is_volatile')}；翻译单元: {', '.join(v.get('translation_units', []))}", ""]
        inventory += [f"- 静态分类：{v.get('static_classification', 'UNKNOWN')}；依据：{v.get('classification_reason', '尚未证明')}",
                      f"- 分析覆盖率：{v.get('analysis_coverage', 'PARTIAL')}；缺口：{', '.join(v.get('coverage_reasons', [])) or '无'}",
                      f"- 保护：{v.get('protection_status', 'NOT_FOUND')}；说明：{v.get('protection_note', '无')}",
                      f"- 安全筛除依据：{v.get('screening_reason') or '尚未证明'}；阻塞项：{', '.join(v.get('screening_blockers', [])) or '无'}",
                      f"- 不可达函数中的访问：{v.get('unreachable_access_count', 0)} 处（保留原始证据）"]
        for a in v.get("accesses", []):
            inventory.append(f"- {a['access_kind']} {location(a)} `{a['source_text']}`")
            complete = a.get('all_call_chains') or {cid: [path] for cid, path in a.get("call_chains", {}).items()}
            for cid, routes in complete.items():
                for path in routes:
                    inventory.append(f"  - {cid}: {chain(path)}")
            if a.get('reachability') == 'PROVEN_UNREACHABLE':
                inventory.append('  - PROVEN_UNREACHABLE：当前构建入口不可达')
            elif not a.get("contexts"):
                inventory.append("  - UNKNOWN-CONTEXT")
    (out / "inventory/global_static_inventory.md").write_text("\n".join(inventory), encoding="utf-8")
    cov = report["coverage"]
    md = ["# 全局变量与 static 变量并发排查报告", "", f"- 分析状态：**{report['analysis_status']}**", f"- 本轮状态：**{report.get('run_status', 'SCANNED')}**",
          f"- 变量：{len(facts['variables'])}；候选及盲区复核项：{len(report['findings'])}",
          f"- 编译单元：{cov['translation_units_parsed']}/{cov['translation_units_total']} 成功（{cov['parse_coverage_percent']}%）；失败 {cov['translation_units_failed']}",
          f"- 函数上下文覆盖：{cov['context_coverage_percent']}%；未知访问：{cov['unknown_accesses']}",
          f"- 工程版本：{report.get('git_commit', 'unknown')}；源码指纹：{report.get('fingerprint', 'unknown')}", "",
          "本报告是风险候选和覆盖证据，不是全工程无风险证明。OpenCode 结论仍需工程/硬件验证。", "",
          "[变量完整清单](../inventory/global_static_inventory.md) · [未知项](unknown_contexts.md) · [OpenCode 复核](opencode_global_static_review.md)", ""]
    static = cov.get('static_classification', {})
    if static:
        if 'proven' in static:
            md[2:2] = [f"- 静态归账：TOTAL {static.get('total', 0)} = SAFE_PROVEN {static.get('proven', 0)} + "
                       f"SHARED_NO_REVIEW {static.get('no_review', 0)} + SUSPECT {static.get('suspect', 0)} + "
                       f"UNKNOWN {static.get('unknown', 0)}；OpenCode 队列 "
                       f"{static.get('suspect', 0) + static.get('unknown', 0)}（"
                       f"{round(100 * (static.get('suspect', 0) + static.get('unknown', 0)) / max(1, static.get('total', 1)), 1)}%）", ""]
        safe_dist = cov.get('safe_reason_distribution', {})
        unknown_dist = cov.get('unknown_reason_distribution', {})
        if safe_dist:
            md[2:2] = ["- SAFE 证明规则分布：" + "；".join(f"{code}={count}" for code, count in
                       sorted(safe_dist.items(), key=lambda item: -item[1])), ""]
        if unknown_dist:
            md[2:2] = ["- UNKNOWN 根因分布：" + "；".join(f"{code}={count}" for code, count in
                       sorted(unknown_dist.items(), key=lambda item: -item[1])), ""]
    summary = report['risk_summary']
    md[2:2] = ['## 与 HTML 一致的变量风险结论', '',
        '| 已确认风险 | 疑似并发风险 | 无法判断 | 已复核安全 / 误报 | 已排查不存在并发风险 | 未发现静态线索 | 补充声明 |',
        '|---|---|---|---|---|---|---|', '| ' + ' | '.join(str(summary['counts'][key]) for key in summary['labels']) + ' |', '',
        f"以上按 {summary['total_variables']} 个变量去重；另有 {summary['independent_gaps']} 项覆盖 / 依赖缺口。",
        'risk_summary 是风险分类；review_summary 是模型复核进度，二者不能相互替代。“已排查不存在并发风险”仅适用于无盲区且没有读写冲突的当前建模范围。', '']
    for limit in report["limitations"]:
        md.append("- " + limit)
    md += ["", "## 编译覆盖与排除", ""]
    for key in ("unlisted_sources", "unlisted_headers", "excluded_sources"):
        md.append(f"- {key}: " + (", ".join(cov.get(key, [])) or "无"))
    for u in facts["translation_units"]:
        if u["parse_status"] != "PARSED":
            md += [f"- 失败：{u['source_file']}"] + ["  - " + cell(d["message"]) for d in u["diagnostics"]]
    review_map = {r["finding_id"]: r for r in reviews}
    for f in report["findings"]:
        r = review_map.get(f["finding_id"], {})
        md += ["", f"## {f['finding_id']} — {f['variable_name']}", "", f"- 风险：{f['risk_level']}；置信度：{f['confidence']}",
               f"- 规则：{', '.join(f['rules'])}", f"- 定义：{location(f['definition'])}；ID: `{f.get('symbol_id')}`",
               f"- 保护：{f['protection_status']}；复核：{r.get('state', 'PENDING')} / {r.get('status', 'NEED_MORE_CONTEXT')}",
               f"- 依据：{f.get('concurrency_reason', '分析盲区需要补充源码/配置证据')}", ""]
        for a in f["accesses"]:
            md.append(f"- **{a['access_kind']}** {location(a)} `{a['source_text']}`")
            complete = a.get('all_call_chains') or {cid: [path] for cid, path in a["call_chains"].items()}
            for cid, routes in complete.items():
                for path in routes:
                    md.append(f"  - {cid}: {chain(path)}")
            if not a["contexts"]:
                md.append("  - UNKNOWN-CONTEXT")
        md += ["", "复核动作：核对所有调用入口、真实抢占与临界区；构造最短交错时序，检查旧值覆盖、事件丢失、重入和 DMA 生命周期。修复建议与验证方法见复核报告。"]
    (out / "reports/global_static_concurrency.md").write_text("\n".join(md), encoding="utf-8")
    unknown = ["# 未知上下文与分析盲区", ""]
    for a in facts["accesses"]:
        if not a["contexts"]:
            unknown.append(f"- UNKNOWN-CONTEXT {a['symbol_id']} {location(a)}")
    for u in facts["unknowns"]:
        unknown.append(f"- {u['kind']} {location(u)}: {cell(u)}")
    (out / "reports/unknown_contexts.md").write_text("\n".join(unknown), encoding="utf-8")
    conclusion = report['final_conclusion']
    review_md = ["# OpenCode 逐项复核结果", "", '**最终结论：' + conclusion['label'] + '**', '',
                 conclusion['scope'], '', f"已返回回答 {conclusion['reviewed']}/{conclusion['total']}；仍未决 {len(conclusion['unresolved_findings'])} 项。", '',
                 "状态统计：" + str(dict(Counter(r["state"] for r in reviews))), ""]
    patches = ["# 最小修复建议（未修改固件）", ""]
    for r in records:
        review_md += [f"## {r['finding_id']}", "", f"- {r['state']} / {r['status']}"]
        if r.get("error"):
            review_md.append("- " + r["error"])
        if r.get('state') == 'DONE':
            from .review_presentation import review_markdown
            review_md += review_markdown(r.get('answer', {}))
        elif r.get('answer'):
            review_md.append('- 旧回答已失效，不作为本轮结论；原始收据保留在 review/queue.json。')
        review_md.append("")
        if r['state'] == 'DONE' and r["status"] in {"CONFIRMED", "LIKELY"}:
            patches += [f"## {r['finding_id']}", "", r["answer"]["fix"], "", r["answer"]["verification"], ""]
    (out / "reports/opencode_global_static_review.md").write_text("\n".join(review_md), encoding="utf-8")
    (out / "reports/opencode_patch_plan.md").write_text("\n".join(patches), encoding="utf-8")
    write_classification_diagnostics(out, facts, report)
    write_html(out, facts, report, reviews)
