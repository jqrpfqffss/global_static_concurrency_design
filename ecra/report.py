import json
import sqlite3
from collections import Counter, defaultdict

from .common import write_json, replace_file


def cell(s):
    return str(s if s is not None else "—").replace("|", "\\|").replace("\n", " ")


def location(row):
    return f"{row.get('file') or '未知'}:{row.get('line') or '?'}"


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
        total=report.get('coverage', {}).get('static_classification', {}).get('total', len(facts['variables'])),
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
                      f"- 安全筛除依据：{v.get('safe_reason_code') or v.get('screening_reason') or '尚未证明'}；阻塞项：{', '.join(v.get('screening_blockers', [])) or '无'}",
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
        md[2:2] = [f"- 静态归账：TOTAL {static.get('total', 0)} = SAFE {static.get('safe', 0)} + SUSPECT {static.get('suspect', 0)} + UNKNOWN {static.get('unknown', 0)}", ""]
    causes = ["# 变量相关 UNKNOWN 根因", "",
              f"UNKNOWN 比例：{cov.get('unknown_percent', 0)}%；诊断阈值 10% 仅触发分析，不改变判定标准。", "",
              "| 原因 | 变量数 |", "|---|---:|"]
    causes += [f"| {cell(code)} | {count} |" for code, count in
               sorted(cov.get('unknown_reason_distribution', {}).items(), key=lambda pair: (-pair[1], pair[0]))]
    causes += ["", "## 阻塞项传播", "", "| blocker | 位置 | fanout | 诊断 |", "|---|---|---:|---|"]
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
    write_html(out, facts, report, reviews)
