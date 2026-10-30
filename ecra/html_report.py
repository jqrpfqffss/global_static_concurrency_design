"""Two offline, evidence-preserving views of the same scan and review queue."""
import html
import json
from collections import Counter, defaultdict
from datetime import datetime

from .common import digest
from .decisions import (CONCURRENT_SIGNALS, DECISIONS, RISK_PRIORITY, aggregate_decisions,
                        decision_label,
                        effective_decision as decision, review_category as category,
                        variable_decisions)
from .review_presentation import explanation as story_explanation, prose
from .review_summary import display_summary
from .review_language import display_answer, is_english_prose
from .html_evidence import CURRENT, EXTERNAL_SCRIPT, HtmlEvidence, large


REVIEW_PAGE = "opencode_review.html"
QUALITY_PAGE = "classification_quality.html"
HTML_CONFLICT_PAIR_SAMPLE_LIMIT = 12
# Internal enum values deliberately remain unchanged in facts/report JSON.  This
# is the single display boundary for the human-facing HTML: templates must use
# this function instead of rendering a raw enum value.
DISPLAY_TEXT = {
    'UNKNOWN_PREEMPTION': '抢占关系无法确认', 'CAN_PREEMPT': '可以抢占',
    'CANNOT_PREEMPT': '不可抢占', 'NO_PREEMPT': '不可抢占',
    'UNRESOLVED': '尚未确认', 'NOT_FOUND': '未发现', 'NONE': '未发现',
    'DETECTED': '已发现', 'EFFECTIVE': '保护有效', 'PARTIAL': '分析不完整 / 部分覆盖',
    'INEFFECTIVE': '保护无效', 'SAFE': '未发现并发风险',
    'SAFE_PROVEN': '静态已判安全', 'SHARED_NO_REVIEW': '共享访问，无需复核',
    'SCREENED_SAFE': '已排查：未发现并发风险', 'LIKELY': '疑似并发风险',
    'CONFIRMED': '已确认并发风险', 'UNKNOWN': '无法判断',
    'NEED_MORE_CONTEXT': 'OpenCode复核证据不足', 'NEED_OPENCODE_REVIEW': '待进一步复核',
    'PENDING': '待复核', 'REVIEWED_SAFE': '已复核：未发现并发风险',
    'FALSE_POSITIVE': '已确认误报', 'READ': '读取', 'WRITE': '写入',
    'RMW': '读改写', 'MAIN': '主循环', 'ISR': '中断', 'TASK': '任务',
    'CALLBACK': '回调', 'DMA': 'DMA 异步访问', 'DMA_ASYNC': 'DMA 异步访问',
    'COMPLETE': '分析完整', 'HIGH': '优先排查', 'MEDIUM': '常规排查',
    'LOW': '较低优先', 'CRITICAL': '最高优先', 'SUSPECT': '疑似并发风险',
    'CONTAINER': '结构体容器（成员分别判定）', 'INCOMPLETE': '分析不完整',
    'MODELED_SCOPE_COMPLETE': '已完成当前建模范围分析', 'PARSED': '解析成功',
    'FAILED': '解析失败', 'DONE': '已完成', 'STALE': '结果已失效',
    'TECH_FAILED': '复核执行失败', 'RUNNING': '执行中', 'SCANNED': '静态扫描完成',
    'EXECUTED': '调用已执行，等待校验',
    'REVIEW_COMPLETE': '复核完成', 'OUT_OF_BUILD': '当前构建之外的声明',
    'ADDRESS_TAKEN': '取地址（不等于读写）',
}
PROTECTION_DISPLAY_TEXT = {
    **DISPLAY_TEXT, 'PARTIAL': '仅部分保护', 'UNRESOLVED': '尚未确认',
}


def to_display_text(value, mapping=None):
    """Translate an internal enum at the HTML boundary without mutating facts.

    Unknown all-caps values intentionally do not leak into normal UI.  They
    remain available in the nested raw JSON used for engineering/debug audit.
    """
    if value is None:
        return '未提供'
    mapping = mapping or DISPLAY_TEXT
    if isinstance(value, str):
        if value in mapping:
            return mapping[value]
        if value.isupper() and any(char.isalpha() for char in value):
            return '未翻译的内部状态（请查看高级静态分析信息）'
    return str(value)


def complete_call_paths(access):
    """Return every resolved path in a stable, duplicate-free representation."""
    raw_paths = access.get('all_call_chains')
    if raw_paths is None:
        raw_paths = {cid: [path] for cid, path in access.get('call_chains', {}).items()}
    result = {}
    for context_id, paths in (raw_paths or {}).items():
        if not paths:
            result[context_id] = []
            continue
        # Legacy facts contain one path as a flat list; current facts contain
        # a list of paths.  Normalize both without losing either form.
        if isinstance(paths, (tuple, list)) and (not paths or isinstance(paths[0], str)):
            paths = [paths]
        unique = sorted({tuple(path) for path in paths if path})
        result[context_id] = [list(path) for path in unique]
    return result


def source_access_views(accesses):
    """Aggregate Access × Context facts into one real source access view.

    Facts remain deliberately unmodified.  A view represents one canonical
    variable access at one source expression and owns every reaching context
    and every complete call path under that source point.
    """
    grouped = {}
    for access in accesses:
        key = (access.get('symbol_id'), access.get('canonical_path'), access.get('file'),
               access.get('line'), access.get('source_text'), access.get('access_kind'))
        view = grouped.setdefault(key, dict(
            key=key, symbol_id=access.get('symbol_id'),
            canonical_variable=access.get('canonical_path') or access.get('symbol_id'),
            file=access.get('file'), line=access.get('line'),
            source_text=access.get('source_text', ''), access_kind=access.get('access_kind'),
            accesses=[], access_ids=[], context_ids=set(), function_ids=set(),
            call_paths=defaultdict(set),
        ))
        view['accesses'].append(access)
        if access.get('access_id') is not None:
            view['access_ids'].append(access['access_id'])
        if access.get('function_id'):
            view['function_ids'].add(access['function_id'])
        view['context_ids'].update(access.get('contexts', []))
        for context_id, paths in complete_call_paths(access).items():
            view['context_ids'].add(context_id)
            view['call_paths'][context_id].update(tuple(path) for path in paths)
    result = []
    for view in grouped.values():
        view['access_ids'].sort()
        view['function_ids'] = sorted(view['function_ids'])
        view['context_ids'] = sorted(view['context_ids'])
        view['call_paths'] = {context_id: [list(path) for path in sorted(paths)]
                              for context_id, paths in sorted(view['call_paths'].items())}
        result.append(view)
    order = {'RMW': 0, 'WRITE': 1, 'READ': 2, 'ADDRESS_TAKEN': 3}
    return sorted(result, key=lambda view: (order.get(view['access_kind'], 4),
                                             view.get('file') or '', view.get('line') or 0,
                                             view.get('source_text') or ''))


def verify_source_access_views(accesses, views, variable_name):
    """Generation-time guard: de-duplication may not discard fact or path."""
    def source_key(access):
        return (access.get('symbol_id'), access.get('canonical_path'), access.get('file'),
                access.get('line'), access.get('source_text'), access.get('access_kind'))
    expected_sources = {source_key(access) for access in accesses}
    actual_sources = {view['key'] for view in views}
    if expected_sources != actual_sources:
        raise ValueError('HTML 源码访问聚合校验失败：' + variable_name)
    expected_paths = {(source_key(access), context_id, tuple(path))
                      for access in accesses for context_id, paths in complete_call_paths(access).items()
                      for path in paths}
    actual_paths = {(view['key'], context_id, tuple(path))
                    for view in views for context_id, paths in view['call_paths'].items()
                    for path in paths}
    if expected_paths != actual_paths:
        raise ValueError('HTML 调用链聚合校验失败：' + variable_name)
VERDICTS = {
    "CONFIRMED": "确认存在并发风险",
    "LIKELY": "疑似存在，尚需验证",
    "REVIEWED_SAFE": "已复核：在所述条件下安全",
    "FALSE_POSITIVE": "已复核：该候选为误报",
    "NEED_MORE_CONTEXT": "已完成复核，源码证据仍不足",
}
LABELS = {
    'summary_attempt': '摘要修复序号', 'trigger_reason': '触发原因',
    'before_summary': '修复前摘要', 'after_summary': '修复后摘要',
    'before_chars': '修复前字符数', 'after_chars': '修复后字符数',
    'max_chars': '字符上限', 'validation_result': '校验结果',
    'technical_retry': '本次技术重试序号',
    "symbol_id": "唯一变量 ID", "name": "名称", "qualified_name": "限定名称", "kind": "变量类别",
    "scope": "作用域", "storage_class": "存储类别", "linkage": "链接属性", "type": "类型",
    "size_bytes": "大小（字节）", "alignment_bytes": "对齐（字节）", "initializer": "初始化表达式",
    "declarations": "所有声明", "definitions": "所有定义", "translation_units": "所属编译单元",
    "is_const": "const", "is_volatile": "volatile", "is_array": "数组", "is_pointer": "指针",
    "is_struct": "结构体", "is_bitfield_container": "包含位域", "audit_status": "静态盘点状态",
    "protection_status": "保护证据状态", "annotations": "资源配置", "core_instances": "各核实例",
    "analysis_coverage": "访问分析覆盖率", "coverage_reasons": "覆盖缺口原因",
    "static_classification": "静态分类", "classification_reason": "静态分类依据",
    "protection_details": "保护区间与访问点证据", "protection_note": "保护结论说明",
    "reason": "结论依据", "interleaving": "最短交错时序 / 不发生交错的条件",
    "protection": "保护范围及不足", "impact": "影响", "fix": "修复建议", "verification": "验证方法",
    'number': '尝试次数', 'stage': '执行阶段', 'started': '开始时间', 'finished': '结束时间',
    'model': '复核模型', 'command': '执行参数', 'input_method': '输入方式', 'state': '执行状态',
    'error_type': '错误类型', 'error_message': '错误说明', 'exit_code': '退出码', 'timeout': '是否超时',
    'stdout_file': '原始输出文件', 'stderr_file': '原始错误文件', 'prompt_file': '提示词文件',
    'packet_file': '证据包文件', 'stdout_sha256': '原始输出校验值', 'stderr_sha256': '原始错误校验值',
    'prompt_sha256': '提示词校验值', 'packet_sha256': '证据包校验值',
}

# The first sentence describes a static signal, not a confirmed execution bug.
RULES = {
    'GS-RMW-INTERLEAVE': ('读改写可能被打断', '核对读出旧值到写回之间，是否可能被另一写入者抢占。'),
    'GS-STALE-SNAPSHOT': ('旧快照可能覆盖新状态', '沿调用链核对快照读取、后续更新和最终写回是否在同一保护范围内。'),
    'DMA_SHARED_REVIEW': ('CPU 与 DMA 共享缓冲区', '核对 DMA 完成前 CPU 是否会复用或读取缓冲区，以及完成通知和所有权交接。'),
    'GS-MULTI-WRITER': ('多个执行入口会写入', '先核对各写入入口能否交错，再确认临界区覆盖了完整更新。'),
    'GS-TEAR-RISK': ('访问可能需要多条指令', '核对实际访问宽度和对齐，检查读取时是否可能混入另一次更新。'),
    'GS-STRUCT-INCONSISTENT': ('多个字段可能不一致', '检查读者能否读到一部分新字段和一部分旧字段。'),
    'GS-MULTI-FIELD-COHERENCE': ('跨字段发布 / 消费可能不一致', '核对同一结构体多个成员是否构成一个必须整体一致的状态快照。'),
    'GS-LOCAL-STATIC-REENTRANT': ('函数 static 可能被重入', '确认函数从哪些入口调用，以及执行尚未结束时能否再次进入。'),
    'GS-OWNER-VIOLATION': ('访问超出声明的所有者', '核对配置中的所有者和实际调用入口是否一致。'),
    'GS-UNKNOWN-CONTEXT': ('部分访问找不到执行入口', '从访问函数向上查找主循环、中断或回调入口；必要时补充 contexts。'),
    'GS-INDIRECT-ACCESS': ('间接访问目标仍有不确定性', '核对指针指向的对象、参数传递和回调注册。'),
    'GS-DEFINITION-MISSING': ('尚未找到变量定义', '确认定义所在源码是否加入当前 CMake 目标，或是否由链接脚本提供。'),
    'GS-NO-ACCESS-EVIDENCE': ('尚未找到读写证据', '检查条件编译、汇编、硬件访问或未建模的调用；没有访问证据不代表安全。'),
    'GS-COVERAGE-INCOMPLETE': ('覆盖缺口阻止安全判定', '查看 screening_blockers，先补齐缺失编译单元、上游回调或外部实现，再重新扫描。'),
    'GS-FILE-STATIC-SHARED': ('文件 static 被多个入口访问', 'static 只限制名称作用域，仍需核对实际并发入口和保护范围。'),
    'GS-MULTI-CONTEXT': ('多个执行入口共享变量', '核对这些入口是否可能交错，以及至少一方写入时的保护范围。'),
    'EXTERNAL_CALLEE': ('被调用函数缺少可分析的实现', '查明该函数是否读写目标变量或调用回调，补充源码或语义配置。'),
    'FUNCTION_ADDRESS': ('函数被取址，调用入口待核对', '查找回调注册位置和最终调用方，确认它在哪个中断或主循环中执行。'),
    'INDIRECT_CALL': ('间接调用目标尚未完全确定', '核对函数指针赋值和回调注册，补充缺失的调用目标。'),
    'INLINE_ASSEMBLY': ('内联汇编的效果需要核对', '查看汇编是否改变中断屏蔽状态、内存或目标变量。'),
    'POINTER_DEREFERENCE': ('指针解引用需要核对', '核对指针实际对象，以及第三方函数是否会访问你的变量。'),
    'POINTER_SUBSCRIPT': ('指针下标访问需要核对', '核对缓冲区归属、下标范围和读写方向。'),
    'UNRESOLVED_POINTEE': ('尚未确定指针目标', '追踪指针赋值和函数参数，确认实际访问了哪个对象。'),
    'PARSE_FAILED': ('源码解析失败', '先修复编译参数或缺失头文件，再重新扫描。'),
    'EMPTY_AUDIT_SCOPE': ('排查范围没有匹配变量', '检查包含和排除目录，以及当前 CMake 构建目标。'),
}
PRIORITIES = {'CRITICAL': '最高优先', 'HIGH': '优先排查', 'MEDIUM': '常规排查', 'LOW': '较低优先'}
KINDS = {'FILE_STATIC': '文件 static', 'LOCAL_STATIC': '函数内 static', 'GLOBAL': '全局变量',
         'HEADER_STATIC': '头文件 static', 'INACTIVE': '非活动分支变量',
         'READ': '读取', 'WRITE': '写入', 'RMW': '读改写',
         'ADDRESS_TAKEN': '取地址（不等于读写）', 'STRUCT_MEMBER': '结构体成员',
         'ARRAY_ELEMENT': '数组元素', 'STRUCT_MEMBER_CONTAINER': '结构体成员容器',
         'ARRAY_CONTAINER': '数组容器'}


def rule_summary(finding):
    rules = finding.get('rules', [])
    known = [code for code in RULES if code in rules]
    ordered = known + [code for code in rules if code not in RULES]
    return [(code, *RULES.get(code, ('其它静态分析线索', '查看高级静态分析信息并补充缺失证据。'))) for code in ordered]


def local_pending(record):
    return record.get('state') == 'PENDING' and '自动复核已关闭' in record.get('error', '')


def review_label(record):
    if record.get('state') == 'DONE':
        return VERDICTS.get(record.get('status'), '证据不足，不能判定安全')
    return {'TECH_FAILED': 'OpenCode复核失败，不能判定安全', 'FAILED': '复核执行失败，不能判定安全', 'STALE': '旧结论已失效，需重新复核',
            'AUDIT_PENDING': '首轮已返回，等待反证复核',
            'RUNNING': '正在复核，尚无有效结论'}.get(record.get('state'),
            '待人工核对（未启用模型）' if local_pending(record) else '待复核，不能判定安全')


def esc(value):
    if isinstance(value, (dict, list, tuple)):
        # Large vendor evidence remains embedded, but whitespace is expanded
        # only when the user opens its details instead of inflating both files.
        value = json.dumps(value, ensure_ascii=False, separators=(',', ':'))
    return html.escape(str(value if value is not None else "未知"), quote=True)


def anchor(prefix, value):
    return prefix + digest(value)[:20]


def loc(row):
    return f"{row.get('file') or '未知'}:{row.get('line') or '?'}"


def raw(value, title="完整原始证据字段"):
    evidence = CURRENT.get()
    if evidence is not None and large(value):
        return evidence.raw(value, title)
    return f"<details class=\"raw-evidence\"><summary>高级调试：{esc(title)}</summary><pre>{esc(value)}</pre></details>"


def fields(value):
    def display(key, item):
        if key in {'error_message', 'validation_error'} and is_english_prose(item):
            return '执行或校验未完成，错误原文保存在原始日志中。'
        if key == 'stage':
            return {'ANALYZE': '源码复核', 'FORMAT_FIX': '格式修正', 'LANGUAGE_FIX': '中文表达修正',
                    'SUMMARY_FIX': '一句话结论修正',
                    'NVIC_FACT_CHALLENGE': 'NVIC 事实核实', 'STALE_WRITEBACK_CHALLENGE': '旧值写回安全核实'}.get(item, item)
        if key == 'state':
            return to_display_text(item)
        if key == 'model' and item == 'OpenCode configured default':
            return 'OpenCode 默认配置模型'
        if key == 'input_method':
            return {'stdin': '标准输入', 'argument': '命令参数'}.get(item, item)
        return item
    return "<dl>" + "".join(f"<dt>{esc(LABELS.get(k, k))}</dt><dd><pre>{esc(display(k, v))}</pre></dd>" for k, v in value.items()) + "</dl>"


def table(headers, rows, ident=None, searchable=False):
    attrs = (f' id="{esc(ident)}"' if ident else "") + (' class="searchable"' if searchable else "")
    body = "".join(rows) or f'<tr><td colspan="{len(headers)}">无记录</td></tr>'
    pager = (f'<div class="pager" data-table="{esc(ident)}"><button type="button" data-step="-1">上一页</button><span aria-live="polite"></span><button type="button" data-step="1">下一页</button></div>' if searchable else '')
    empty = '<p class="empty" hidden>没有匹配记录。请更换关键词、切换栏目，或点击“清除筛选”。</p>' if searchable else ''
    return pager + empty + '<div class="table-scroll"><table' + attrs + '><thead><tr>' + "".join(f'<th scope="col">{esc(h)}</th>' for h in headers) + "</tr></thead><tbody>" + body + "</tbody></table></div>"


def row(cells, ident=None, group=None, level=None, file=None, scope=None, decision=None, files=None,
        source_access_view=False, search_text=None):
    attrs = (f' id="{esc(ident)}"' if ident else "") + (f' data-group="{esc(group)}"' if group else "")
    for key, value in [('level', level), ('file', file), ('scope', scope), ('decision', decision)]:
        if value is not None:
            attrs += f' data-{key}="{esc(value)}"'
    if files is not None:
        attrs += ' data-files="' + esc(json.dumps(files)) + '"'
    if source_access_view:
        attrs += ' data-source-access-view="1"'
    if search_text:
        # Search must not force the browser to walk inactive detail templates.
        # Keep a compact index on the visible row instead.
        evidence = CURRENT.get()
        if evidence is not None and len(search_text) > 16384:
            attrs += ' data-search-ref="' + evidence.search(search_text) + '"'
        else:
            attrs += ' data-search="' + esc(search_text) + '"'
    return "<tr" + attrs + ">" + "".join("<td>" + c + "</td>" for c in cells) + "</tr>"


def deferred_detail(summary, contents, classes="evidence"):
    """Keep a heavy evidence tree out of the live DOM until it is opened.

    Pagination only hides rows; it does not stop the browser from parsing and
    laying out every nested table, preformatted JSON blob and call path.  A
    template is inert, while keeping the report completely offline and its
    evidence source-preserving for tool-based audit.
    """
    evidence = CURRENT.get()
    if evidence is not None:
        external = evidence.detail(summary, contents, classes)
        if external is not None:
            return external
    return ('<details class="' + esc(classes) + '" data-deferred-detail="1"><summary>'
            + summary + '</summary><template data-detail-template="1">' + contents
            + '</template></details>')


def compact_debug_fields(value, omitted):
    """Return the non-duplicated part of a fact for the HTML debug pane.

    Source accesses, full call paths and conflict pairs are already rendered
    in the user-facing evidence tables.  Repeating those recursive structures
    as raw JSON was the main cause of multi-megabyte HTML reports.  The exact
    original facts remain available in the neighbouring facts.json file.
    """
    return {key: item for key, item in value.items() if key not in omitted}


def compact_evidence_summary(items, sample_limit=8):
    """Summarize repetitive low-level evidence without dropping it from JSON."""
    items = list(items or [])
    by_kind = Counter()
    samples = []
    for item in items:
        if isinstance(item, dict):
            by_kind[item.get('kind') or item.get('event_kind') or item.get('status') or '其它'] += 1
            if len(samples) < sample_limit:
                samples.append({key: item[key] for key in ('kind', 'event_kind', 'status', 'file', 'line',
                                                            'function_id', 'api') if item.get(key) is not None})
        else:
            by_kind[str(item)] += 1
            if len(samples) < sample_limit:
                samples.append(str(item))
    return dict(total=len(items), by_kind=dict(sorted(by_kind.items())), samples=samples)


def review_records(report, reviews):
    """Every current finding gets a row; absent/stale receipts cannot imply safe."""
    by_id = {r["finding_id"]: r for r in reviews}
    return [dict(by_id.get(f["finding_id"], {}), finding_id=f["finding_id"],
                 static_classification=f.get('static_classification'),
                 state=by_id.get(f["finding_id"], {}).get("state", "PENDING"),
                 status=(by_id.get(f["finding_id"], {}).get("status")
                         if by_id.get(f["finding_id"], {}).get("state") == "DONE" else None))
            for f in report["findings"]]


def localized_records(reviews):
    """Presentation copies only; JSON receipts and semantic statuses stay raw."""
    return [dict(r, answer=display_answer(r['answer'])) if r.get('answer') else dict(r) for r in reviews]


def nvic_summary(facts):
    rows = []
    def number(value):
        return str(value) if value is not None else '尚未确定'
    for item in facts.get('nvic_priorities', []):
        sources = item.get('source_configurations', [])
        configurations = []
        for event in sources:
            pre, sub = event.get('configured_preemption'), event.get('configured_subpriority')
            value = ('抢占优先级 ' + number(pre) + '，子优先级 ' + number(sub) if pre is not None
                     else '编码优先级 ' + number(event.get('logical_priority')))
            chain = ' → '.join(c.get('function') or c['function_id'] for c in event.get('call_chain', []))
            configurations.append('<p>' + esc(value + '；' + loc(event)) + '<br>' + esc(chain) + '</p>')
        group = item.get('grouping')
        group_text = str(group) if group is not None else '有效分组待核实；源码分组 ' + str(item.get('source_groupings', []))
        if group is not None:
            group_text += '；抢占位数 ' + str(item.get('preemption_bits')) + '，子优先级位数 ' + str(item.get('subpriority_bits'))
        effective = ('已确认初始化结果：抢占 ' + str(item.get('preemption_priority')) + '，子优先级 ' + str(item.get('subpriority'))
                     if item.get('effective_validity') == 'CONFIRMED' else item.get('reason', '有效优先级尚待证明'))
        enabled = {True: '初始化末端已使能', False: '初始化末端已禁用', None: '初始化末端启停状态尚待证明'}[item.get('enabled')]
        rows.append(row([esc(' / '.join(item['irqn']) + ' → ' + ' / '.join(item['vectors'])),
                         ''.join(configurations) or '未发现可达的优先级配置证据',
                         esc('有效位数 ' + number(item.get('priority_bits')) + '；分组 ' + group_text),
                         esc(effective + '；' + enabled + '。' + item.get('enable_scope', ''))]))
    if not rows:
        return ''
    return deferred_detail('中断优先级、分组及配置调用链',
        '<p>源码配置与运行期有效性分别记录。IRQ 使能不代表已触发；共享向量内部串行，子优先级不产生嵌套。屏蔽有效性按具体访问窗口判定。</p>'
        + table(['IRQn 与实际向量', '源码配置与证据', '优先级位数及分组', '有效性与启停范围'], rows), 'nvic-evidence')


def reviewed_variable_summary(findings, records, variable=None):
    """Describe the merged risk, keeping review uncertainty on a separate axis."""
    if not findings:
        return None
    rows = [records.get(f['finding_id'], {'state': 'PENDING'}) for f in findings]
    def done(status):
        return next((r for r in rows if r.get('state') == 'DONE' and r.get('status') == status), None)
    def explanation(row):
        answer = row.get('answer') or {}
        return display_summary(answer) or review_label(row)
    decisions = [decision(f, r, variable=variable) for f, r in zip(findings, rows)]
    merged = aggregate_decisions(decisions)
    if merged == 'confirmed':
        return DECISIONS[merged][0], explanation(done('CONFIRMED'))
    if merged == 'safe':
        return decision_label(merged, rows), explanation(rows[0])
    relevant = [(f, r) for f, r, d in zip(findings, rows, decisions) if d == merged]
    finding, record = next(((f, r) for f, r in relevant if r.get('state') == 'DONE'), relevant[0])
    why = explanation(record) if record.get('state') == 'DONE' else (
        finding.get('classification_reason') or (variable or {}).get('classification_reason') or DECISIONS[merged][1])
    notes = list(dict.fromkeys(review_label(r) for r in rows if category(r) == 'unresolved'))
    if notes:
        why += '；复核状态：' + '；'.join(notes)
    return DECISIONS[merged][0], why


def final_conclusion(report, reviews):
    records = review_records(report, reviews)
    mapping = {r['finding_id']: r for r in records}
    confirmed = [f['finding_id'] for f in report['findings']
                 if f.get('symbol_id') and category(mapping[f['finding_id']]) == 'confirmed']
    unresolved = [r['finding_id'] for r in records if category(r) in {'unresolved', 'likely'}]
    if not confirmed:
        unresolved += [f['finding_id'] for f in report['findings'] if not f.get('symbol_id')
                       and category(mapping[f['finding_id']]) == 'confirmed']
    if confirmed:
        verdict, label = 'HAS_ISSUES', '有问题：OpenCode 已确认存在并发缺陷'
    elif (unresolved or report.get('analysis_status') != 'MODELED_SCOPE_COMPLETE'
          or report.get('git_diff', {}).get('fallback_reasons')):
        verdict, label = 'INCONCLUSIVE', '尚不能确定：不能据此宣称没有问题'
    else:
        verdict, label = 'NO_ISSUES_IN_SCOPE', '本次已覆盖的构建与候选范围内未确认并发问题'
    return dict(verdict=verdict, label=label, confirmed_findings=confirmed,
                unresolved_findings=unresolved, total=len(records),
                reviewed=sum(r['state'] == 'DONE' for r in records),
                static_coverage_complete=report.get('analysis_status') == 'MODELED_SCOPE_COMPLETE',
                scope='仅适用于当前源码、构建配置和已覆盖路径；原文校验不等于硬件运行验证。')


def risk_summary(facts, report, records):
    """One variable-level interpretation shared by HTML and machine exports."""
    decisions = variable_decisions(facts, report, records)
    targets = [v for v in facts['variables'] if v.get('static_classification') not in {'CONTAINER', 'OUT_OF_BUILD'}
               and v.get('resource_kind') not in {'STRUCT_MEMBER_CONTAINER', 'STRUCT_CONTAINER', 'ARRAY_CONTAINER'}]
    counts = Counter(decisions[v['symbol_id']] for v in targets)
    by_symbol = defaultdict(list)
    for finding in report['findings']:
        by_symbol[finding.get('symbol_id')].append(records.get(finding['finding_id'], {}))
    return dict(total_variables=len(targets), counts={key: counts[key] for key in DECISIONS},
                inventory_rows=len(decisions),
                labels={key: value[0] for key, value in DECISIONS.items()},
                independent_gaps=sum(not f.get('symbol_id') for f in report['findings']),
                basis='静态线索与有效复核共同分类；疑似不等于已确认，未发现线索不等于安全。',
                variables=[dict(symbol_id=v['symbol_id'], name=v.get('qualified_name', v.get('name')),
                    static_classification=v.get('static_classification'),
                    definition_file=v.get('definition_file'), definition_line=v.get('definition_line'),
                    kind=v.get('kind'), coverage_source=v.get('coverage_source', 'compile_database'),
                    decision=decisions[v['symbol_id']],
                    label=decision_label(decisions[v['symbol_id']], by_symbol[v['symbol_id']]))
                    for v in targets])


def snapshot_scenario(finding, contexts):
    """A conditional source-backed witness, never a feasibility/safety proof.

    Require the same object path, an ordered read/write in one function, and a
    distinct modeled ISR writer. Do not invent reads for address-taking or use
    different structure members as the same location.
    """
    if 'GS-STALE-SNAPSHOT' not in finding.get('rules', []):
        return None
    snapshot_functions = {s.get('function_id') for s in finding.get('snapshots', [])}
    accesses = finding.get('accesses', [])
    for read in accesses:
        if read.get('access_kind') != 'READ' or read.get('function_id') not in snapshot_functions:
            continue
        mains = [cid for cid in read.get('contexts', []) if contexts.get(cid, {}).get('kind') == 'MAIN']
        if not mains:
            continue
        writes = [a for a in accesses if a.get('access_kind') == 'WRITE'
                  and a.get('function_id') == read['function_id'] and a.get('file') == read.get('file')
                  and a.get('access_path', '') == read.get('access_path', '')
                  and (a.get('line') or 0) > (read.get('line') or 0)
                  and mains[0] in a.get('contexts', [])]
        rivals = [(cid, a) for a in accesses if a.get('access_kind') in {'WRITE', 'RMW'}
                  and a.get('access_path', '') == read.get('access_path', '')
                  for cid in a.get('contexts', []) if contexts.get(cid, {}).get('kind') == 'ISR'
                  and cid in a.get('call_chains', {})]
        if writes and rivals:
            cid, rival = min(rivals, key=lambda pair: (len(pair[1]['call_chains'][pair[0]]), pair[0]))
            write = min(writes, key=lambda a: a['line'])
            steps = [(mains[0], read), (cid, rival), (mains[0], write)]
            if all(a.get('source_text') and a.get('file') and a.get('line') and c in a.get('call_chains', {}) for c, a in steps):
                return steps
    return None


def decision_tag(group):
    return f'<span class="decision {group}">{esc(DECISIONS[group][0])}</span>'


STYLE = """
*{box-sizing:border-box}body{margin:0;color:#203247;background:#f3f6fa;font:14px/1.6 'Segoe UI','Microsoft YaHei',sans-serif}
header{background:#142c45;color:white;padding:28px max(24px,4vw)}header h1{margin:0 0 6px;font-size:26px}header a{color:#bee2ff}main{padding:24px 4vw;max-width:1900px;margin:auto}
nav{display:flex;gap:18px;flex-wrap:wrap}a{color:#075b9c}h2{font-size:21px;margin-top:30px}h3{font-size:16px}.notice{border-left:4px solid #bb7914;background:#fff7df;padding:12px 16px;margin:16px 0}
.metrics{display:flex;gap:12px;flex-wrap:wrap;margin:18px 0}.metric{background:white;border:1px solid #d6e0eb;padding:14px 22px;min-width:140px;border-radius:6px}.metric strong{display:block;font-size:26px}
.pager{display:flex;align-items:center;gap:12px;margin:12px 0}.pager button:disabled{opacity:.4;cursor:default}.next-actions{padding:16px;background:white;border:1px solid #d6e0eb}.next-actions h2{margin:0 0 8px;font-size:18px}.next-actions ul{margin:0;padding-left:24px}
.toolbar{background:white;padding:14px;border:1px solid #d6e0eb;display:flex;gap:12px;flex-wrap:wrap;align-items:center;position:sticky;top:0;z-index:2}input,select,button{font:inherit;padding:8px;border:1px solid #aabccb;border-radius:4px}input{min-width:230px;flex:1}button,summary{cursor:pointer}summary{color:#075b9c}details{margin:6px 0}details[open]>summary{margin-bottom:8px}pre{white-space:pre-wrap;overflow-wrap:anywhere;margin:0;font:12px/1.65 Consolas,monospace}
.table-scroll{overflow-x:auto;margin:12px 0}table{border-collapse:collapse;background:white;width:100%;font-size:13px}th,td{padding:10px 12px;border:1px solid #d6e0eb;text-align:left;vertical-align:top;overflow-wrap:anywhere}th{background:#e9f0f7}td{min-width:100px;max-width:620px}td:first-child{min-width:150px}td table td{min-width:80px}dl{display:grid;grid-template-columns:minmax(90px,25%) minmax(0,1fr);gap:6px 12px}dt{font-weight:600}dd{margin:0;min-width:0}.muted{color:#596d80}.tag{display:inline-block;border-radius:3px;padding:2px 6px;background:#e8eff6;font-weight:600}.confirmed{background:#ffe0df;color:#8b2220}.likely{background:#fff0d0;color:#785218}.safe{background:#ddf2e5;color:#235b38}.unresolved{background:#e8ebf0;color:#46546b}.supplemental{background:#f0e8f6;color:#52356b}tr:target{outline:3px solid #277cb7;scroll-margin-top:90px}[hidden]{display:none!important}footer{padding:24px 0;color:#596d80}
#review-table{table-layout:fixed;min-width:1000px}#review-table>thead th:nth-child(1){width:15%}#review-table>thead th:nth-child(2){width:15%}#review-table>thead th:nth-child(3){width:34%}#review-table>thead th:nth-child(4){width:26%}#review-table>thead th:nth-child(5){width:10%}#inventory-table{min-width:900px}
@media(max-width:700px){main{padding:14px}header{padding:20px}header h1{font-size:21px}.toolbar{position:static}td,th{padding:8px}dl{grid-template-columns:1fr}}
header{padding:18px 4vw}header h1{font-size:24px}header p{margin:3px 0 8px}main{padding-top:18px;max-width:1600px}
.overview{background:white;border:1px solid #d6e0eb;border-radius:8px;padding:14px 18px;margin-bottom:16px}.overview p{margin:4px 0}.overview h2{margin:0 0 5px;font-size:19px}.overview details{margin-bottom:0}.overview .notice{margin:8px 0;padding:6px 12px}
.metrics{margin:12px 0;gap:10px}.metric{padding:8px 16px;flex:1;min-width:130px}.metric strong{font-size:23px}.tabs{gap:6px;margin:14px 0 0;border-bottom:2px solid #cfdae6}.tabs a{padding:10px 16px;text-decoration:none;border-radius:6px 6px 0 0;font-weight:600}.tabs a[aria-current="page"]{background:#075b9c;color:white}.panel h2{margin:18px 0 4px}.panel>p{margin:4px 0 10px}.toolbar{position:static;padding:10px;margin:12px 0;gap:8px}.toolbar input{min-width:150px}.toolbar select{max-width:260px}#visible{width:100%;font-size:12px;color:#596d80}.pager{margin:8px 0}.empty{padding:25px;background:white;border:1px dashed #aabccb}
table.searchable{table-layout:fixed;min-width:0!important}table.searchable>thead th:first-child{width:24%}table.searchable>thead th:last-child{width:26%}table.searchable>tbody>tr>td{min-width:0;max-width:none}#inventory-table>thead th:first-child{width:28%}#review-table>thead th:nth-child(1){width:23%}#review-table>thead th:nth-child(2){width:21%}#review-table>thead th:nth-child(3){width:31%}#review-table>thead th:nth-child(4){width:25%}
.item-name{font:600 16px/1.5 Consolas,monospace}.location{display:block;color:#596d80;font-size:12px;margin:5px 0}.signal{margin:4px 0}.signal-list{padding-left:18px;margin:6px 0}.priority-HIGH,.priority-CRITICAL{background:#fff0d0;color:#785218}.step{margin:8px 0 0}.tag{font-size:12px}.evidence{margin-top:9px}.evidence[open]{padding:10px;background:#f6f9fc;border:1px solid #d6e0eb}.evidence .table-scroll{max-width:100%}.evidence table{min-width:760px}.evidence>summary{font-weight:600}.context-count{font-weight:600}.audit-ids{display:block;color:#596d80;font:11px/1.4 Consolas,monospace;margin-top:5px}.legend{padding:8px 0;color:#46546b}button:focus-visible,a:focus-visible,summary:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid #3180d8;outline-offset:2px}.copy-note{font-size:12px;display:block;margin-top:4px}tr:target{scroll-margin-top:12px}pre{tab-size:4}footer details{max-width:100%}
@media(min-width:801px){table.searchable,table.searchable>thead,table.searchable>tbody{display:block}table.searchable>thead>tr,table.searchable>tbody>tr{display:grid;grid-template-columns:24% 50% 26%}#inventory-table>thead>tr,#inventory-table>tbody>tr{grid-template-columns:28% 45% 27%}#review-table>thead>tr,#review-table>tbody>tr{grid-template-columns:23% 21% 31% 25%}table.searchable>thead th{width:auto!important;min-width:0}table.searchable>tbody>tr>td{min-width:0;width:auto}table.searchable>tbody>tr>td:has(>.evidence[open]){grid-column:1/-1;order:1}#risk-table>tbody>tr:has(.evidence[open])>td:last-child,#gap-table>tbody>tr:has(.evidence[open])>td:last-child{grid-column:2/-1}.next-actions{padding:8px 12px}}
@media(max-width:800px){header{padding:16px}main{padding:12px}.overview{padding:12px}.metrics{gap:6px}.metric{min-width:110px;padding:8px}.tabs{gap:0}.tabs a{padding:8px 10px;font-size:13px}.toolbar{align-items:stretch}.toolbar input{width:75%}.toolbar select{max-width:100%}table.searchable,table.searchable>tbody,table.searchable>tbody>tr,table.searchable>tbody>tr>td{display:block;width:100%}table.searchable>thead{display:none}table.searchable>tbody>tr{margin-bottom:12px;border:1px solid #c5d3e0;border-radius:6px;overflow:hidden}table.searchable>tbody>tr>td{border:0;border-bottom:1px solid #e4ebf3;padding:10px 12px}table.searchable>tbody>tr>td::before{content:attr(data-label);display:block;font-size:12px;color:#596d80;font-weight:600;margin-bottom:5px}.table-scroll{margin:8px 0}.panel h2{font-size:19px}dl{grid-template-columns:1fr}}
.print-context{display:none}header button{padding:3px 9px;background:transparent;color:inherit;border-color:#7895ad}.scenario{padding:8px 10px;background:#fff8e8;border-left:3px solid #bc8629}.scenario li{margin:8px 0}.scenario p{font-size:13px}
@media print{.toolbar,.pager,.tabs,button{display:none!important}body{background:white}.table-scroll{overflow:visible}header{background:white;color:black}.print-context{display:block;border:1px solid #aaa;padding:8px}.panel{break-before:auto}.table-scroll>table{min-width:0!important}a{color:inherit}}
.risk-overview{background:white;border:1px solid #d6e0eb;border-radius:8px;overflow:hidden;margin-bottom:14px}.verdict-head{padding:14px 20px;border-left:6px solid currentColor}.verdict-head>span{font-size:13px;font-weight:600}.verdict-head h2{font-size:29px;line-height:1.25;margin:3px 0 7px}.verdict-head p{margin:0;color:#34465c}.verdict-cards{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;padding:12px 18px 0}.verdict-card{border-radius:6px;padding:9px 14px;text-decoration:none;border:1px solid transparent}.verdict-card:hover{border-color:currentColor}.verdict-card strong{display:block;font-size:25px;line-height:1.3}.verdict-card span{font-weight:600}.risk-overview>.scope-line,.risk-overview>.muted{margin:8px 18px;font-size:12px}.scope-check{padding:8px 18px;border-top:1px solid #d6e0eb;margin:8px 0 0}.decision{display:inline-block;border-radius:4px;padding:5px 9px;margin:0 0 8px;font-weight:700;font-size:15px;border-left:4px solid currentColor}.source-previews{display:flex;gap:8px;margin:8px 0}.source-preview{flex:1;min-width:0;padding:7px 9px;background:#f1f5fa;border-radius:4px;font-size:12px}.source-preview .location{margin:2px 0}.source-preview pre{font-size:12px}.source-preview strong{color:#234666}.review-brief{margin:5px 0}.source-previews:empty{display:none}
@media(max-width:800px){.verdict-head{padding:12px}.verdict-head h2{font-size:23px}.verdict-cards{grid-template-columns:repeat(2,1fr);gap:7px;padding:10px}.verdict-card{padding:8px 10px}.risk-overview>.scope-line,.risk-overview>.muted{margin:8px 12px}.scope-check{padding:8px 12px}.source-previews{flex-direction:column}.decision{font-size:16px}}
/* The review is a reading view, not a multi-column evidence spreadsheet. */
.story-origin,.format-summary{font-size:12px;color:#596d80;margin:8px 0}.actor-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,280px),1fr));gap:12px}.actor-card{background:#f0f5fb;padding:12px 16px;border-radius:6px;min-width:0}.actor-entry,.story-refs{font-size:12px;color:#526b86}.story-refs{display:block}.story-scheduling{margin:18px 0;background:#f6f9fc;padding:12px 16px;border-left:3px solid #799dbd}.model-scenario{margin:12px 0 24px;border:1px solid #dce5ef;border-radius:6px;padding:14px}.model-scenario h5{font-size:16px;margin:0 0 8px}.model-scenario>.tag{margin-bottom:8px}.model-steps{padding-left:25px}.model-steps>li{padding:4px 0 12px 8px;border-bottom:1px solid #e4ebf3;margin:8px 0}.model-steps>li::marker{font-weight:700;color:#27517e}.step-states{font-size:13px;grid-template-columns:55px minmax(0,1fr);background:#f5f8fb;padding:8px;gap:4px 10px}.scenario-result{background:#edf4fb;padding:10px;font-size:14px}.scenario-result p:last-child{margin:0}
.reading-page>header{padding:12px 4vw;display:flex;align-items:center;gap:10px 24px;flex-wrap:wrap}.reading-page>header h1{font-size:20px;margin:0}.reading-page>header p{order:2;flex-basis:100%;font-size:11px;margin:0}.reading-page>header nav{margin-left:auto;font-size:12px}.reading-page>main{padding-top:12px}.advanced-filters>div{display:flex;flex-wrap:wrap;align-items:center;gap:8px;padding:8px 0}.review-reading .panel>h2,.review-reading .panel>p{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%)}.review-reading .toolbar #visible{width:auto;margin-left:auto}.review-reading .toolbar button{padding:5px 8px}.review-reading .toolbar input{padding:5px 8px}.review-reading .toolbar{font-size:12px}.review-reading .story-jump{display:inline-flex;margin:4px 0;max-width:100%;font-size:12px}.review-reading .story-jump select{padding:4px 8px;max-width:100%}.review-reading .pager{display:inline-flex;float:right;margin:4px 0}.review-reading .table-scroll{clear:both}
.review-reading{max-width:1320px;margin:auto}.review-verdict{border-left:5px solid #b13c35;background:white;padding:14px 20px;border-radius:6px}.review-verdict h2{margin:0 0 6px;font-size:23px}.review-verdict p{margin:4px 0}.review-verdict .muted{font-size:12px}
.review-reading .toolbar{border:0;background:transparent;padding:4px 0;margin:10px 0}.review-reading .toolbar input{max-width:320px}.review-reading .panel>h2{font-size:18px}.review-reading .panel>p{color:#596d80;font-size:13px}.story-jump{display:flex;align-items:center;gap:12px;margin:12px 0}.story-jump select{max-width:80%;background:white}.review-reading .pager{font-size:12px}.review-reading .pager button{padding:3px 10px}
.review-reading table.searchable{background:transparent}.review-reading table.searchable>thead{display:none}.review-reading table.searchable>tbody>tr{display:block;margin:0 0 24px;border:0;overflow:visible}.review-reading table.searchable>tbody>tr>td{display:block;width:100%;padding:0;border:0}.review-reading table.searchable>tbody>tr>td::before{display:none}
.review-story{border:1px solid #cbd7e4;border-top:4px solid #a73b37;border-radius:9px;padding:22px 26px;background:white;color:#203247;font-size:15px;line-height:1.8;overflow-wrap:anywhere}.review-story.safe{border-top-color:#34835c}.review-story.likely{border-top-color:#b98823}.review-story.unresolved{border-top-color:#657589}.story-heading{display:flex;justify-content:space-between;align-items:flex-start;gap:20px;border-bottom:1px solid #e1e8ee;padding-bottom:10px}.story-heading h3{font:700 23px/1.4 Consolas,'Microsoft YaHei',monospace;margin:0}.story-heading .tag{flex-shrink:0;font-size:13px}.story-heading .location{font-size:13px;margin:4px 0 0}
.review-story h4{font-size:16px;margin:0 0 8px;color:#182f4b}.review-story p{margin:0 0 10px}.story-impact{background:#f8f0ed;padding:12px 16px;margin:16px 0;border-radius:5px}.safe .story-impact{background:#eff8f2}.story-impact p:last-child{margin-bottom:0}.story-columns{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(0,1fr);gap:28px;margin:22px 0}.story-process,.story-remedy{min-width:0}.story-caption{color:#596d80;font-size:12px}.story-remedy{border-left:1px solid #dce5ef;padding-left:22px;font-size:14px}.story-remedy section+section{margin-top:22px}.process-step{display:grid;grid-template-columns:35px minmax(0,1fr);gap:10px;margin:12px 0}.step-number{background:#e7effa;color:#27517e;border-radius:50%;align-self:start;text-align:center;font-weight:700;font-size:13px;padding:5px 0}.process-step>div{padding:3px 0 8px;border-bottom:1px solid #e4ebf3}.process-step:last-child>div{border-bottom:0}.process-prose p{padding:8px 12px;border-left:3px solid #7ba4cd;background:#f4f8fc;margin:10px 0}.story-section{margin:18px 0}.story-audit,.story-citations,.story-reason,.story-verification{font-size:13px;border-top:1px solid #e0e7ef;padding-top:8px;margin-top:10px}.story-citations li{margin:8px 0}.story-audit .evidence table{min-width:0}.story-audit .evidence td:first-child{width:23%;min-width:0}.story-audit .evidence td:nth-child(2){width:7%;min-width:0}.review-scope{margin-top:24px}
@media(max-width:900px){.story-columns{grid-template-columns:1fr;gap:18px}.story-remedy{border-left:0;border-top:1px solid #dce5ef;padding:18px 0 0}.review-story{padding:16px;font-size:15px}.story-heading{flex-wrap:wrap;gap:8px}.story-heading h3{font-size:21px}.review-verdict h2{font-size:20px}.story-jump{flex-wrap:wrap;gap:5px}.story-jump select{max-width:100%;width:100%}.review-reading .toolbar input{max-width:none}.review-reading .tabs a{font-size:13px}.story-audit .evidence table{font-size:12px}}
@media print{.story-jump{display:none}.review-story{border:1px solid #aaa;color:black}.story-heading{break-after:avoid}.story-columns{display:block}.story-remedy{border:0;padding:0}.process-step,.story-impact{break-inside:avoid}.review-story details[open]{break-inside:auto}}
"""


SCRIPT = """
document.addEventListener('toggle',e=>{if(e.target.tagName!=='DETAILS'||!e.target.open)return;
const detail=e.target;
if(detail.dataset.deferredDetail==='1'&&!detail.dataset.detailLoaded){const template=[...detail.children].find(child=>child.tagName==='TEMPLATE'&&child.dataset.detailTemplate==='1');if(template){detail.append(template.content);template.remove();}detail.dataset.detailLoaded='1';}
for(const p of detail.querySelectorAll('pre')){if(p.dataset.formatted)continue;p.dataset.formatted='1';const text=p.textContent.trim();if(text.startsWith('{')||text.startsWith('[')){try{p.textContent=JSON.stringify(JSON.parse(text),null,2);}catch{}}}},true);
const q=document.getElementById('q'), filter=document.getElementById('filter'), fileFilter=document.getElementById('file-filter');
const panels=[...document.querySelectorAll('.panel')], tabs=[...document.querySelectorAll('.tabs a')];
let active=document.getElementById('inventory')||panels[0];
const rows=[...document.querySelectorAll('table.searchable > tbody > tr[data-group]')];
const searchText=new Map(rows.map(r=>[r,(r.dataset.search||(r.querySelector('.story-current')||r).textContent).toLowerCase()]));
const pageSize=document.getElementById('page-size'), views=[...document.querySelectorAll('.pager')].map(p=>({pager:p,page:0,rows:rows.filter(r=>r.closest('table').id===p.dataset.table),matches:[]}));
for(const v of views){const t=document.getElementById(v.pager.dataset.table),labels=[...t.tHead.rows[0].cells].map(c=>c.textContent);for(const r of v.rows)[...r.cells].forEach((c,i)=>c.dataset.label=labels[i]);}
function matchesFilter(r){const [kind,value]=filter.value.split(':');return filter.value==='all'||(value?r.dataset[kind]===value:r.dataset.group===filter.value);}
let fullSearchReady=false,fullSearchPending=null;
function search(reset=true){if(q.value.trim()&&!fullSearchReady&&rows.some(r=>r.dataset.searchRef)){document.getElementById('visible').textContent='正在载入完整源码搜索索引…';if(!fullSearchPending)fullSearchPending=new Promise((resolve,reject)=>{const s=document.createElement('script');s.src='html_details/search-index.js';s.onload=()=>{const index=window.ECRA_SEARCH_INDEX||{};if(rows.some(r=>r.dataset.searchRef&&typeof index[r.dataset.searchRef]!=='string')){reject(new Error('incomplete index'));return;}for(const r of rows)if(r.dataset.searchRef)searchText.set(r,index[r.dataset.searchRef].toLowerCase());fullSearchReady=true;resolve();};s.onerror=reject;document.head.append(s);});fullSearchPending.then(()=>applySearch(reset)).catch(()=>{fullSearchPending=null;document.getElementById('visible').textContent='完整源码搜索索引未能载入，尚未应用本次搜索；请检查 html_details 文件。';});return;}applySearch(reset);}
function applySearch(reset=true){let n=0,shown=0;const size=Number(pageSize.value);for(const v of views){if(reset)v.page=0;v.matches=v.rows.filter(r=>searchText.get(r).includes(q.value.trim().toLowerCase())&&matchesFilter(r)&&(fileFilter.value==='all'||JSON.parse(r.dataset.files||JSON.stringify([r.dataset.file])).includes(fileFilter.value)));const count=Math.max(1,Math.ceil(v.matches.length/size));v.page=Math.max(0,Math.min(v.page,count-1));const visible=new Set(v.matches.slice(v.page*size,(v.page+1)*size));for(const r of v.rows)r.hidden=!visible.has(r);if(v.pager.closest('.panel')===active){n+=v.matches.length;shown+=visible.size;}v.pager.querySelector('span').textContent=v.matches.length+' 条 · 第 '+(v.page+1)+' / '+count+' 页';v.pager.nextElementSibling.hidden=!!v.matches.length;v.pager.querySelector('[data-step="-1"]').disabled=v.page===0;v.pager.querySelector('[data-step="1"]').disabled=v.page+1>=count;}document.getElementById('visible').textContent=(document.querySelector('.review-reading')?'搜索当前有效解释与引用（不含历史回答）：':'仅搜索当前栏目（含折叠证据）：')+n+' 条匹配，当前展示 '+shown+' 条';}
function activate(panel,clear=false){active=panel;for(const p of panels)p.hidden=p!==panel;for(const a of tabs){if(a.hash==='#'+panel.id)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');}if(clear)q.value='';filter.replaceChildren(...JSON.parse(panel.dataset.options||'[]').map(([k,v])=>new Option(v,k)));const files=[...new Set(rows.filter(r=>r.closest('.panel')===panel).flatMap(r=>JSON.parse(r.dataset.files||JSON.stringify([r.dataset.file]))).filter(Boolean))].sort();fileFilter.replaceChildren(new Option('全部文件','all'),...files.map(f=>new Option(f,f)));document.querySelector('.toolbar').hidden=!panel.querySelector('.searchable');search();}
for(const v of views)for(const b of v.pager.querySelectorAll('button'))b.addEventListener('click',()=>{v.page+=Number(b.dataset.step);search(false);});
q.addEventListener('input',()=>search());filter.addEventListener('change',()=>search());fileFilter.addEventListener('change',()=>search());pageSize.addEventListener('change',()=>search());
document.getElementById('reset').addEventListener('click',()=>{q.value='';filter.value='all';fileFilter.value='all';search()});
function reveal(){let id;try{id=decodeURIComponent(location.hash.slice(1));}catch{return;}const target=document.getElementById(id);if(!target)return;const panel=target.closest('.panel');if(!panel)return;activate(panel,target!==panel);const targetRow=target.closest('tr[data-group]')||target;for(const v of views){let i=v.matches.indexOf(targetRow);if(i>=0)v.page=Math.floor(i/Number(pageSize.value));}search(false);targetRow.hidden=false;for(let p=target.parentElement;p&&p!==panel;p=p.parentElement)if(p.tagName==='DETAILS')p.open=true;if(target!==panel&&!target.querySelector('.review-story'))(target.querySelector('.evidence')||target.querySelector('details'))?.setAttribute('open','');const scrollTarget=target===panel?(document.querySelector('.tabs')||target):target;requestAnimationFrame(()=>scrollTarget.scrollIntoView({block:'start'}));}
document.addEventListener('click',e=>{if(e.defaultPrevented)return;const a=e.target.closest('a');if(a&&a.getAttribute('href')===location.hash&&location.hash){e.preventDefault();reveal();}});
window.addEventListener('hashchange',reveal);if(active)activate(active);reveal();
for(const select of document.querySelectorAll('[data-story-jump]'))select.addEventListener('change',()=>{if(select.value){location.hash=select.value;reveal();}});
for(const a of document.querySelectorAll('[data-decision-filter]'))a.addEventListener('click',e=>{e.preventDefault();const p=document.querySelector(a.getAttribute('href'));activate(p,true);filter.value='decision:'+a.dataset.decisionFilter;search();history.replaceState(null,'',a.getAttribute('href'));(document.querySelector('.tabs')||p).scrollIntoView({block:'start'});});
let printRows=null;
window.addEventListener('beforeprint',()=>{if(printRows)return;printRows=rows.map(r=>[r,r.hidden]);const v=views.find(v=>v.pager.closest('.panel')===active);if(v){const all=new Set(v.matches);for(const r of v.rows)r.hidden=!all.has(r);}document.querySelector('.print-context').textContent='打印栏目：'+(active?.getAttribute('aria-label')||'报告')+'；关键词：'+(q.value||'无')+'；筛选：'+(filter.selectedOptions[0]?.textContent||'无')+'；文件：'+(fileFilter.selectedOptions[0]?.textContent||'全部')+(v?'；包含全部 '+v.matches.length+' 条匹配记录（跨分页）。':'。');});
window.addEventListener('afterprint',()=>{for(const [r,hidden] of printRows||[])r.hidden=hidden;printRows=null;});
document.getElementById('print-view').addEventListener('click',()=>window.print());
for(const b of document.querySelectorAll('[data-copy]'))b.addEventListener('click',async()=>{const note=b.nextElementSibling;try{await navigator.clipboard.writeText(b.dataset.copy);note.textContent='已复制，可粘贴到排查记录或问题单。';}catch{note.textContent='请选中下方文字复制：';let p=note.querySelector('textarea');if(!p){p=document.createElement('textarea');p.readOnly=true;p.value=b.dataset.copy;p.style.width='100%';p.rows=8;note.append(p);}p.focus();p.select();}});
"""


def page(title, content, report, options, script="", reading=False):
    generated = report.get('generated_at', '未知')
    try:
        generated = datetime.fromisoformat(generated.replace('Z', '+00:00')).astimezone().strftime('%Y-%m-%d %H:%M:%S %z')
    except (ValueError, TypeError):
        pass
    root = report.get('coverage', {}).get('project_root', '')
    project = root.replace('\\', '/').rstrip('/').rsplit('/', 1)[-1] or '当前工程'
    meta = f"{project} · 扫描时间：{generated}（重新生成页面不会刷新扫描时间）"
    controls = '<div class="toolbar"><label for="q">搜索</label><input id="q" type="search" placeholder="变量、函数、文件或证据"><label for="filter">筛选</label><select id="filter">' + "".join(f'<option value="{esc(k)}">{esc(v)}</option>' for k, v in options) + '</select><label for="file-filter">文件</label><select id="file-filter"><option value="all">全部文件</option></select><label for="page-size">每页</label><select id="page-size"><option value="25">25 条</option><option value="100">100 条</option><option value="1000000000">全部</option></select><button id="reset" type="button">清除筛选</button><span id="visible" aria-live="polite"></span></div>'
    if reading:
        controls = controls.replace('<label for="filter">', '<details class="advanced-filters"><summary>筛选与分页设置</summary><div><label for="filter">').replace('<button id="reset"', '</div></details><button id="reset"')
        controls = controls.replace('变量、函数、文件或证据', '变量、函数或当前复核解释')
    content = content.replace('<!--controls-->', controls)
    if report.get('presentation_notice'):
        content = '<p class="notice">' + esc(report['presentation_notice']) + '</p>' + content
    if CURRENT.get() is not None:
        script = EXTERNAL_SCRIPT + script
    return '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="icon" href="data:,"><title>' + esc(title) + '</title><style>' + STYLE + '</style></head><body' + (' class="reading-page"' if reading else '') + '><header><h1>' + esc(title) + '</h1><p>' + esc(meta) + '</p><nav><a href="index.html">静态排查</a><a href="' + REVIEW_PAGE + '">逐项复核结果</a><a href="' + QUALITY_PAGE + '">分类质量</a><button type="button" id="print-view">打印 / 保存当前筛选结果</button></nav></header><main><p class="print-context"></p><noscript>启用 JavaScript 可使用搜索、栏目切换、分页和按需展开详情；完整机器事实见同目录 facts.json 与 reports/。</noscript>' + content + '<footer>' + raw({'源码指纹': report.get('fingerprint'), '工具版本': report.get('tool_version'), '工程版本': report.get('git_commit'), '静态状态': report.get('analysis_status'), '本轮状态': report.get('run_status')}, '报告版本与原始状态') + '</footer></main><script>' + SCRIPT + script + '</script></body></html>'


def metrics(values):
    return '<div class="metrics">' + "".join(f'<div class="metric"><strong>{esc(n)}</strong>{esc(label)}</div>' for label, n in values) + '</div>'


def diff_evidence_table(impact):
    """只概述已变化维度；完整新旧事实和未修改路径仍在后台。"""
    labels = dict(declaration='声明与布局', accesses='访问类型（分析记录数）', graph='完整调用子图',
                  contexts='执行上下文', protection='保护状态与屏蔽观测',
                  coverage='覆盖状态', conflicts='冲突证据条目（含聚合项）', classification='静态分类')

    def formatted(dimension, value, side):
        if side == 'base' and not impact.get('base'):
            return '该版本未匹配到对应存储对象'
        if value is None:
            return '未提供该项摘要，请查看完整证据'
        if dimension == 'classification':
            return to_display_text(value, {**DISPLAY_TEXT, 'CONTAINER': '容器汇总（成员或元素分别判定）'})
        if dimension == 'declaration':
            return ('类型：' + str(value.get('type') or '未提供') + '；大小：' +
                    str(value.get('size_bytes') if value.get('size_bytes') is not None else '未知') +
                    ' 字节；对齐：' + str(value.get('alignment_bytes') if value.get('alignment_bytes') is not None else '未知') + ' 字节')
        if dimension == 'accesses':
            names = {**DISPLAY_TEXT, 'WHOLE_OBJECT_READ': '整个对象读取', 'WHOLE_OBJECT_WRITE': '整个对象写入'}
            kinds = ['READ', 'WRITE', 'RMW'] + sorted(set(value) - {'READ', 'WRITE', 'RMW'})
            return '；'.join(to_display_text(k, names) + '：' + str(value.get(k, 0)) for k in kinds)
        if dimension == 'contexts':
            return '；'.join(to_display_text(c.get('kind')) + '：' + c['id'] for c in value) or '未记录已解析执行入口'
        if dimension == 'protection':
            irq, fault = value.get('primask', {}), value.get('faultmask', {})
            return ('状态：' + to_display_text(value.get('status'), PROTECTION_DISPLAY_TEXT) +
                    '；PRIMASK 已屏蔽/未屏蔽/未知：' + '/'.join(str(irq.get(k, 0)) for k in ('DISABLED', 'ENABLED', 'UNKNOWN')) +
                    '；BASEPRI 记录值：' + ('、'.join(map(str, value.get('basepri_values', []))) or '无') +
                    '，未知：' + str(value.get('basepri_unknown', 0)) +
                    '；FAULTMASK 已屏蔽/未屏蔽/未知：' + '/'.join(str(fault.get(k, 0)) for k in ('1', '0', 'UNKNOWN')))
        if dimension == 'graph':
            return '函数节点：' + str(value['functions']) + '；调用边：' + str(value['edges']) + '；执行入口：' + str(value['roots'])
        if dimension == 'coverage':
            return to_display_text(value.get('status')) + '；相关阻断证据条目：' + str(value.get('blocking_records', 0))
        if dimension == 'conflicts':
            return str(value.get('records', 0))
        return '请查看完整证据'

    changes = impact.get('evidence_changes', {})
    if not changes:
        return ''
    rows = [row([esc(labels.get(key, '其他证据变化')),
                 esc(formatted(key, change.get('base'), 'base')),
                 esc(formatted(key, change.get('head'), 'head'))]) for key, change in changes.items()]
    return ('<h4>新旧变化摘要</h4>' + table(['变化证据', '基准版本', '当前版本'], rows) +
            '<p>条目数相同不代表证据内容相同；请结合代码差异和完整证据核对访问表达式、完整保护窗口及具体冲突关系。</p>')


def next_actions(report, records):
    records = list(records)
    cov=report['coverage']; actions=[]
    if cov.get('translation_units_failed'):
        actions.append(f"先修复 {cov['translation_units_failed']} 个编译单元的解析错误：核对缺失头文件、芯片宏与真实编译参数，然后重新运行 run。")
    missing=len(cov.get('unlisted_sources',[]))+len(cov.get('unlisted_headers',[]))
    if missing:
        actions.append(f"确认 {missing} 个未纳入的源文件/头文件是否属于当前固件；在覆盖证据中逐项核对，不能直接当作没有变量。")
    if cov.get('unknown_accesses'):
        actions.append(f"还有 {cov['unknown_accesses']} 处访问没有已知任务/中断入口；核对 contexts、回调注册及调用边。")
    counts=Counter(category(r) for r in records)
    if counts['confirmed'] or counts['likely']:
        actions.append(f"查看 {counts['confirmed']} 项确认风险及 {counts['likely']} 项疑似风险的交错、修复与验证建议。")
    if counts['unresolved']:
        disabled = sum(local_pending(r) for r in records)
        if disabled:
            actions.append(f"{disabled} 项未启用模型复核：可直接按静态证据人工排查；需要模型辅助时设置 review.enabled: true 后重新执行原命令。")
        if counts['unresolved'] > disabled:
            actions.append(f"另有 {counts['unresolved'] - disabled} 项待复核或证据不足：查看逐项复核中的原因；补充配置或修复错误后继续，源码变化后重新运行扫描。")
    if not actions:
        actions.append('当前建模范围的流程已完成。核对报告适用的构建配置和安全条件，再安排工程验证。')
    return '<details class="next-actions"><summary>后续操作与待补信息</summary><ul>'+''.join('<li>'+esc(a)+'</li>' for a in actions)+'</ul></details>'


def scope_summary(cov):
    scope = cov.get('audit_scope')
    if not scope:
        return '<p>排查范围：本次构建实际解析到的变量；详细覆盖证据见下方。</p>'
    files = scope.get('exclude_files', [])
    check = f'；输出校验：{scope["excluded_variable_leaks"]} 个范围外变量进入结果' if 'excluded_variable_leaks' in scope else ''
    return ('<p><strong>本次排查范围：</strong>' + esc('、'.join(scope['include_dirs']) or '全部目录')
            + ' · <strong>排除：</strong>' + esc('、'.join(scope['exclude_dirs']) or '无')
            + (f' + {len(files)} 个指定文件' if files else '')
            + f' · 范围外 {scope["variables_omitted"]} 个变量不排查' + esc(check) + '。</p>'
            + (raw(files, '查看混放在业务目录中的排除文件') if files else '')
            + '<details><summary>为什么仍可能看到 HAL / 第三方路径？</summary><p>排除按变量定义归属生效；依赖代码对目标变量的读写、回调链和相关证据缺口仍保留。它们不是第三方自有变量候选。排除优先于包含；不代表范围外代码安全。</p></details>')


def panel(ident, title, description, body, options):
    return f'<section id="{ident}" class="panel" data-options="{esc(options)}" aria-label="{esc(title)}"><h2>{esc(title)}</h2><p>{esc(description)}</p>{body}</section>'


def overview(report, records, values):
    cov = report['coverage']
    records = list(records)
    counts = Counter(category(r) for r in records)
    if records and all(local_pending(r) for r in records):
        state = '本地静态排查已生成；模型复核未启用'
    elif counts['unresolved']:
        state = '排查报告已生成；仍有待复核或证据不足的项目'
    else:
        state = '排查报告已生成；请按适用条件核对结论'
    parsed, total = cov.get('translation_units_parsed', '?'), cov.get('translation_units_total', '?')
    coverage_note = f'源码解析 {parsed}/{total} 个编译单元 · 未知入口访问 {cov.get("unknown_accesses", 0)} 处。'
    if cov.get('translation_units_failed'):
        coverage_note += ' 有解析失败，请先查看覆盖范围并修复。'
    return ('<section class="overview"><h2>' + esc(state) + '</h2><p>' + esc(coverage_note)
            + ' <strong>解析成功不等于并发安全；静态候选尚需证实。</strong></p>'
            + metrics(values) + scope_summary(cov) + next_actions(report, records) + '</section>')


def risk_overview(facts, report, records, assessments):
    summary = risk_summary(facts, report, records)
    counts = summary['counts']
    if counts['confirmed']:
        state, color = '已确认存在并发风险', 'confirmed'
        explanation = '有效复核已确认风险。先处理红色项目，再核对其余疑似风险。'
    elif counts['likely']:
        state, color = '发现疑似并发风险', 'likely'
        explanation = '已有共享读写、读改写或 DMA 等风险线索；是否会造成实际缺陷，仍需核对交错和保护条件。'
    elif counts['unresolved'] or not facts['variables']:
        state, color = '证据不足，无法判断是否安全', 'unresolved'
        explanation = '先补齐缺失的入口、定义或访问证据；不能把未知项当作没有风险。'
    else:
        state, color = '当前未发现未解决的并发风险线索', 'unresolved'
        explanation = '这不是全工程无风险证明。已复核结论只适用于所列条件，未发现线索的变量尚未证明安全。'
    cards = ''.join(f'<a class="verdict-card {key}" href="#{"inventory" if key in {"screened_safe", "screened_shared"} else "risks"}" data-decision-filter="{key}"><strong>{counts[key]}</strong><span>{esc(DECISIONS[key][0])}</span></a>'
                    for key in ['confirmed', 'likely', 'unresolved', 'safe', 'screened_safe', 'screened_shared'])
    cov = report['coverage']
    gap_count = sum(not f.get('symbol_id') for f in report['findings'])
    inventory_by_kind = (dict(Counter(v['kind'] for v in facts['variables'])) if report.get('git_diff')
                         else cov.get('inventory_by_kind', {}))
    mode = '模型复核未启用；当前分类依据静态证据。' if records and all(local_pending(r) for r in records.values()) else '分类结合静态证据与有效复核；失败或过期回答不算当前结论。'
    kind_line = ' · '.join(f'{KINDS.get(k, k)} {n}' for k, n in sorted(inventory_by_kind.items())) or '无变量'
    return ('<section class="risk-overview"><div class="verdict-head ' + color + '"><span>并发风险结论</span><h2 id="risk-verdict">'
            + esc(state) + '</h2><p>' + esc(explanation) + '</p></div><div class="verdict-cards">' + cards + '</div>'
            + '<p class="scope-line">以上按变量去重统计。共 ' + str(summary['total_variables']) + ' 个分析对象（清单含 ' + str(len(facts['variables'])) + ' 行，' + esc(kind_line) + '）；另有 '
            + f'<a href="#inventory" data-decision-filter="screened_safe">{counts["screened_safe"]} 个已排查：未发现并发风险</a>、'
            + f'<a href="#inventory" data-decision-filter="screened_shared">{counts["screened_shared"]} 个共享访问、无需复核</a>、'
            + f'<a href="#inventory" data-decision-filter="inventory">{counts["inventory"]} 个未发现静态线索</a>（不等于安全）'
            + (f'、<a href="#inventory" data-decision-filter="supplemental">{counts["supplemental"]} 个补充解析</a>' if counts.get('supplemental') else '')
            + f'。<a href="#gaps">{gap_count} 项覆盖 / 依赖缺口</a>单独保留，不计入风险变量。</p>'
            + '<p class="muted">' + esc(mode) + ' 源码解析完整 ' + str(cov.get('translation_units_parsed', '?'))
            + '；部分 ' + str(cov.get('translation_units_partial', 0))
            + '；失败 ' + str(cov.get('translation_units_failed', 0))
            + '；总计 ' + str(cov.get('translation_units_total', '?')) + '。'
            + ('<strong>请先修复解析失败；当前结果可能遗漏风险。</strong>' if cov.get('translation_units_failed') else '') + '</p>'
            + '<details class="scope-check"><summary>过滤结果与排查范围：已排除 ' + str(cov.get('audit_scope', {}).get('variables_omitted', 0))
            + ' 个变量；查看具体配置</summary>' + scope_summary(cov) + next_actions(report, records.values()) + '</details></section>')


def classification_quality_html(facts, report):
    """Render an auditable account of what left and remained in the queue."""
    quality = report.get('coverage', {}).get('classification_quality', {})
    rates = quality.get('review_rates', {})
    build = rates.get('rr_build', {})
    all_inventory = rates.get('rr_all', {})
    headline = metrics([
        ('构建变量总数', quality.get('total', 0)),
        ('SAFE_PROVEN', quality.get('safe_proven', 0)),
        ('SHARED_NO_REVIEW', quality.get('shared_no_review', 0)),
        ('SUSPECT', quality.get('suspect', 0)),
        ('UNKNOWN', quality.get('unknown', 0)),
        ('复核队列', quality.get('review_queue', 0)),
        ('复核比例（RR_build）', str(build.get('percent', quality.get('review_queue_percent', 0))) + '%'),
        ('补充盘点声明', rates.get('variant_inventory', 0)),
        ('RR_all', str(all_inventory.get('percent', 0)) + '%'),
    ])
    elimination_rows = []
    visible_ids = set(report['git_diff']['selected_symbol_ids']) if report.get('git_diff') else None
    for item in quality.get('eliminations', []):
        variable_rows = [row([
            '<a href="index.html#' + anchor('var-', variable['symbol_id']) + '">' + esc(variable['name']) + '</a>',
            esc(variable['classification']), esc(variable['symbol_id'])])
            for variable in item.get('variables', []) if visible_ids is None or variable['symbol_id'] in visible_ids]
        details = deferred_detail('查看 ' + str(len(variable_rows)) + ' 个当前范围变量',
                                  table(['变量', '分类', 'symbol_id'], variable_rows))
        elimination_rows.append(row([esc(item.get('code')), esc(item.get('description')),
                                     str(item.get('variable_count', 0)), details],
                                    search_text=' '.join(str(variable.get('name', ''))
                                                         for variable in item.get('variables', []))))
    distribution = lambda values: table(['原因', '变量数'], [
        row([esc(code), str(count)]) for code, count in
        sorted(values.items(), key=lambda pair: (-pair[1], pair[0]))])
    fanout_rows = [row([
        esc(item.get('kind')), esc(loc(item)), str(item.get('blocker_fanout', 0)),
        esc(item.get('diagnostic') or '变量局部传播'),
        raw(item.get('relevance_proofs', []), '逐变量相关性证明')])
        for item in quality.get('blocker_fanout', [])]
    content = '<section class="overview"><h2>Pre-OpenCode 四分类质量</h2>' + headline
    if visible_ids is not None:
        content += '<p class="notice">分类质量统计使用完整构建范围；下方变量导航只列当前差异范围，避免链接到未展示变量。当前差异范围变量数：' + str(len(visible_ids)) + '。</p>'
    content += '<p>RR_build = 构建变量复核队列 / 构建变量总数；RR_all = (复核队列 + 未分析的补充盘点声明) / (构建变量 + 补充盘点声明)。补充声明保留在清单中，须扫描对应构建变体才能完成访问分析。</p>'
    content += '<p>' + esc(quality.get('note', '')) + '</p></section>'
    content += '<nav class="tabs"><a href="#eliminations">排除贡献</a><a href="#remaining">剩余原因</a><a href="#fanout">UNKNOWN fanout</a><a href="#hotspots">源码热点</a></nav><!--controls-->'
    content += panel('eliminations', '哪些机制排除了哪些变量',
                     '每一行都能展开到 canonical variable；同一变量可由多个证据机制共同证明。',
                     table(['机制', '证明含义', '变量数', '变量清单'], elimination_rows,
                           'quality-eliminations', True), [('all', '全部机制')])
    remaining = '<h3>SUSPECT 主要原因</h3>' + distribution(quality.get('suspect_reason_distribution', {}))
    remaining += '<h3>UNKNOWN 变量相关原因</h3>' + distribution(quality.get('unknown_reason_distribution', {}))
    remaining += '<h3>结构化分类原因</h3>' + distribution(quality.get('root_cause_reason_counts', {}))
    remaining += '<h3>单一缺口的可能翻转上界</h3>' + distribution(quality.get('counterfactual_upper_bounds', {}))
    remaining += '<p>上界只用于决定下一步分析顺序；取得新的静态证明前，变量分类不会变化。</p>'
    content += panel('remaining', '仍需复核的原因',
                     'SUSPECT 表示已存在冲突候选；UNKNOWN 表示变量证据切片内仍可能隐藏冲突。',
                     remaining, [('all', '全部原因')])
    content += panel('fanout', 'UNKNOWN blocker fanout',
                     'fanout 只统计真正进入各变量 evidence slice 的 blocker，并保留相关性证明。',
                     table(['blocker', '位置', '变量数', '诊断', '相关性证据'], fanout_rows,
                           'quality-fanout', True), [('all', '全部 blocker')])
    content += panel('hotspots', '根因源码热点',
                     '按每个复核变量的一处冲突或阻塞见证位置统计；完整见证见 root_cause_v2.json。',
                     table(['文件', '变量数'], [row([esc(item['file']), str(item['variables'])])
                         for item in quality.get('root_cause_hotspots', [])],
                         'quality-hotspots', True), [('all', '全部热点')])
    content += raw(quality, '完整 classification_quality 机器证据')
    return page('Pre-OpenCode 分类质量', content, report, [('all', '全部记录')])


def write_html(out, facts, report, reviews):
    if len(facts.get('variables', [])) >= 1000 or len(facts.get('accesses', [])) >= 50000:
        # Individually small templates still create millions of inert DOM
        # nodes in a large project. Load every deferred detail independently.
        with HtmlEvidence(out, report.get('fingerprint'), STYLE, threshold=0):
            return _write_html(out, facts, report, reviews)
    return _write_html(out, facts, report, reviews)


def _write_html(out, facts, report, reviews):
    reviews = localized_records(reviews)
    from .scope import validate_selection
    validate_selection(facts, report)
    from .git_diff import presentation_view
    facts, report = presentation_view(facts, report)
    funcs = {f['function_id']: f for f in facts['functions']}
    variables = {v['symbol_id']: v for v in facts['variables']}
    contexts = {c['id']: c for c in facts['contexts']}
    records = {r['finding_id']: r for r in review_records(report, reviews)}
    assessments = variable_decisions(facts, report, records)
    candidates = defaultdict(list)
    for finding in report['findings']:
        if finding.get('symbol_id'):
            candidates[finding['symbol_id']].append(finding)
    members_by_root = defaultdict(list)
    for variable in facts['variables']:
        if variable.get('root_symbol_id'):
            members_by_root[variable['root_symbol_id']].append(variable)

    def function(fid):
        f = funcs.get(fid)
        return f"{f['name']} ({loc(f)})" if f else fid

    def function_name(fid):
        return funcs.get(fid, {}).get('name', fid)

    def context(cid):
        c = contexts.get(cid, {})
        target = c.get('registration', {}).get('function_id') or c.get('function_id')
        kind = c.get('kind', 'UNKNOWN')
        if kind == 'DMA':
            return {'tx': 'DMA 发送（硬件读取）', 'rx': 'DMA 接收（硬件写入）'}.get(c.get('direction'), 'DMA 硬件') + f' · {cid}'
        name = ', '.join(c.get('functions', [])) or funcs.get(target, {}).get('name')
        if not name:
            name = cid.split(':')[1] if cid.startswith('auto:') else cid
        return {'MAIN': '主循环', 'ISR': '中断', 'TASK': '任务', 'UNKNOWN': '未知入口'}.get(kind, to_display_text(kind)) + ' ' + name

    def context_list(ids):
        return '<br>'.join(esc(context(cid)) for cid in ids) or '无已知上下文'

    def context_brief(ids, label):
        ids = list(ids)
        return '<p class="signal"><span class="context-count">' + esc(label) + f'：{len(ids)} 个已知入口</span></p>' + (
            '<details><summary>查看入口名称</summary>' + context_list(ids) + '</details>' if ids else '')

    def source_view_anchor(anchor_prefix, view_or_access):
        key = view_or_access.get('key') if isinstance(view_or_access, dict) else None
        if key is None:
            key = (view_or_access.get('symbol_id'), view_or_access.get('canonical_path'),
                   view_or_access.get('file'), view_or_access.get('line'),
                   view_or_access.get('source_text'), view_or_access.get('access_kind'))
        return anchor('source-access-' + anchor_prefix + '-', key)

    def path_tree(path):
        return '\n'.join(([function_name(path[0])] if path else [])
                         + ['└─ ' + function_name(fid) for fid in path[1:]])

    def accesses(items, anchor_prefix='', validate_member=None):
        """Render the one-row-per-real-source-point user-facing access table."""
        views = source_access_views(items)
        if validate_member is not None:
            verify_source_access_views(items, views, validate_member['qualified_name'])
        rows = []
        for view in views:
            path_count = sum(len(paths) for paths in view['call_paths'].values())
            witness_only = any(not a.get('call_path_lists_complete', True) for a in view['accesses'])
            path_label = '见证路径' if witness_only else '全部调用链'
            chains = ''
            if view['context_ids']:
                chains += '<strong>' + str(len(view['context_ids'])) + ' 个入口</strong>'
                if witness_only:
                    chains += '<p>此处列出最短见证；完整调用证据由全部入口和调用边表示。'
                    chains += '<a href="facts.json">查看完整图证据（context_call_graph / call_graph_slices / calls）</a>；'
                    chains += '见证数量不是全部路径数量，安全证明仍使用完整图。</p>'
                chains += '<details><summary>展开' + path_label + '（' + str(path_count) + ' 条）</summary>'
                for context_id in view['context_ids']:
                    routes = view['call_paths'].get(context_id, [])
                    chains += '<details><summary>' + esc(context(context_id)) + '：' + str(len(routes)) + ' 条' + ('见证路径' if witness_only else '调用链') + '</summary><pre>'
                    chains += '\n\n'.join('<span data-resolved-call-path="1">' + esc(path_tree(path)) + '</span>'
                                         for path in routes)
                    chains += '</pre></details>'
                chains += '</details>'
            else:
                reachable = any(a.get('reachability') == 'PROVEN_UNREACHABLE' for a in view['accesses'])
                chains = '<strong>' + ('当前构建入口不可达（保留访问证据）' if reachable
                                       else '尚未确定执行上下文或调用链') + '</strong>'
            functions = '<br>'.join(esc(function_name(fid)) for fid in view['function_ids']) or '未知函数'
            mode_label = to_display_text(view['access_kind'])
            if any(a.get('access_scope') == 'INHERITED_WHOLE_OBJECT_ACCESS' for a in view['accesses']):
                mode_label += '（整对象继承影响）'
            elif any(a.get('access_scope') in {'WHOLE_OBJECT_ACCESS', 'WHOLE_MEMBER_OBJECT_ACCESS'} for a in view['accesses']):
                mode_label += '（整对象访问）'
            audit_ids = '<span class="audit-ids">访问事实 ID：' + esc('、'.join(view['access_ids']) or '未提供') + '</span>'
            rows.append(row([esc(mode_label), esc(str(view.get('file') or '未知') + ':' + str(view.get('line') or '?'))
                             + '<pre>' + esc(view.get('source_text', '')) + '</pre>' + audit_ids, functions, chains],
                            source_view_anchor(anchor_prefix, view), source_access_view=True))
        rendered = table(['访问方式', '源码位置与表达式', '访问函数', '执行上下文 / 调用链'], rows)
        if validate_member is not None:
            actual_sources = rendered.count('data-source-access-view="1"')
            actual_paths = rendered.count('data-resolved-call-path="1"')
            expected_paths = len({(view['key'], cid, tuple(path)) for view in views
                                  for cid, paths in view['call_paths'].items() for path in paths})
            if actual_sources != len(views) or actual_paths != expected_paths:
                raise ValueError('HTML 源码访问 / 调用链渲染计数校验失败：' + validate_member['qualified_name'])
        return rendered

    def rendered_path_count(items):
        return sum(len(paths) for access in items for paths in complete_call_paths(access).values())

    def verify_member_rendering(variable):
        """The table below is the only HTML projection of member facts.

        Guard it at report generation time: a future UI optimization may fold
        rows visually, but it must never omit a fact or a resolved call path.
        """
        if variable.get('resource_kind') != 'STRUCT_MEMBER':
            return
        items = variable.get('accesses', [])
        if variable.get('access_count') != len(items):
            raise ValueError('HTML 成员访问计数校验失败：' + variable['qualified_name'])
        if variable.get('resolved_call_path_count') != rendered_path_count(items):
            raise ValueError('HTML 成员调用链计数校验失败：' + variable['qualified_name'])

    def path_instance(instance, anchor_prefix):
        """Link to the one canonical collection of full paths for this access."""
        target = source_view_anchor(anchor_prefix, instance)
        label = (context(instance.get('context_id')) + ' · '
                 + to_display_text(instance.get('access_kind')) + ' · '
                 + str(instance.get('file') or '未知') + ':' + str(instance.get('line') or '?'))
        witness_only = instance.get('call_path_count_kind') == 'WITNESS_COUNT'
        text = str(instance.get('canonical_path') or '') + ('（见证路径 ' if witness_only else '（完整路径 ') + str(instance.get('call_path_count', 0)) + ' 条）'
        if instance.get('access_scope') == 'INHERITED_WHOLE_OBJECT_ACCESS':
            text += '；继承：' + str(instance.get('inherited_from_canonical_path') or '整对象访问')
        return '<a href="#' + target + '">' + esc(label) + '<br>' + esc(text) + '<br>展开该访问的' + ('图证据与见证路径' if witness_only else '全部调用链') + '</a>'

    def conflict_pair_table(pairs, protection, anchor_prefix):
        if not pairs:
            return '<p>未生成可比较的上下文访问实例。</p>'
        shown_pairs = pairs[:HTML_CONFLICT_PAIR_SAMPLE_LIMIT]
        rows = []
        for pair in shown_pairs:
            relation = pair.get('relation', {})
            preemption = to_display_text(relation.get('relation', 'UNKNOWN'))
            if relation.get('higher') and relation.get('lower'):
                preemption += '：' + context(relation['higher']) + ' 可以抢占 ' + context(relation['lower'])
            rows.append(row([esc(pair.get('conflict_id')), path_instance(pair['participant_a'], anchor_prefix),
                             path_instance(pair['participant_b'], anchor_prefix),
                             esc(preemption) + '<br><span class="muted">' + esc(relation.get('reason', '')) + '</span>',
                             esc('未发现有效保护' if protection in {'NOT_FOUND', 'NONE'} else to_display_text(protection, PROTECTION_DISPLAY_TEXT)),
                             '<strong>' + esc(to_display_text(pair.get('status'))) + '</strong><br><span class="muted">完整路径组合：'
                             + esc(pair.get('path_combination_count', 1)) + '</span>']))
        notice = ''
        if len(shown_pairs) < len(pairs):
            notice = ('<p class="notice">为保持变量详情可快速打开，此处只展示 ' + str(len(shown_pairs))
                      + ' / ' + str(len(pairs)) + ' 组代表性组合。所有源码访问和完整调用链仍在本变量详情中；'
                      + '完整组合清单保存在同目录的 <a href="facts.json">facts.json</a> 与 '
                      + '<a href="reports/global_static_concurrency.json">global_static_concurrency.json</a>。</p>')
        return notice + table(['ID', '参与者 A：完整调用链', '参与者 B：完整调用链', '并发 / 抢占关系', '保护', '状态'], rows)

    def context_sort_key(context_id):
        kind = contexts.get(context_id, {}).get('kind')
        return ({'MAIN': 0, 'ISR': 1, 'TASK': 2, 'CALLBACK': 3, 'DMA': 4}.get(kind, 5),
                context(context_id))

    def context_summary(views):
        counts = defaultdict(Counter)
        for view in views:
            for context_id in view['context_ids']:
                counts[context_id][view['access_kind']] += 1
        rows = [row([esc(context(context_id)), str(counts[context_id]['READ']),
                     str(counts[context_id]['WRITE']), str(counts[context_id]['RMW'])])
                for context_id in sorted(counts, key=context_sort_key)]
        return table(['执行上下文', '读取', '写入', '读改写'], rows)

    def user_text(value):
        """Translate enum tokens embedded in an analyst-authored explanation."""
        text = str(value or '')
        for internal, display in sorted(DISPLAY_TEXT.items(), key=lambda item: -len(item[0])):
            text = text.replace(internal, display)
        return text

    def variable_explanation(variable, views, finding_list):
        if variable.get('static_classification') == 'SUSPECT' and not finding_list:
            return ('疑似并发风险', variable.get('classification_reason') or DECISIONS['likely'][1], '')
        if variable.get('static_classification') == 'SAFE_PROVEN':
            return ('静态已判安全', variable.get('classification_reason', ''), '')
        if variable.get('static_classification') == 'SHARED_NO_REVIEW':
            proof = variable.get('shared_evidence', {})
            detail = ('唯一写入者：' + str(proof.get('writer_physical_context', '?'))
                      + '；只读观察者：' + '、'.join(proof.get('reader_physical_contexts', [])))
            return ('共享访问，无需复核', variable.get('classification_reason', ''), detail)
        if variable.get('static_classification') == 'OUT_OF_BUILD':
            return ('未参与当前固件构建', variable.get('classification_reason', ''), '')
        if variable.get('static_classification') == 'UNKNOWN':
            gaps = variable.get('blocking_evidence', [])
            detail = '；'.join(str(g.get('file') or '?') + ':' + str(g.get('line') or '?')
                + ' ' + g.get('relevance', '') for g in gaps[:5])
            return ('无法判断', variable.get('classification_reason', ''), detail)
        rules = {rule for finding in finding_list for rule in finding.get('rules', [])}
        by_kind = defaultdict(set)
        for view in views:
            by_kind[view['access_kind']].update(view['context_ids'])
        main_writers = [cid for cid in by_kind['WRITE'] | by_kind['RMW']
                        if contexts.get(cid, {}).get('kind') == 'MAIN']
        async_writers = [cid for cid in by_kind['WRITE'] | by_kind['RMW']
                         if contexts.get(cid, {}).get('kind') in {'ISR', 'DMA', 'CALLBACK'}]
        rmw_views = [view for view in views if view['access_kind'] == 'RMW']
        if 'GS-STALE-SNAPSHOT' in rules and main_writers and async_writers:
            return ('疑似并发风险',
                    context(main_writers[0]) + '中存在“读取旧值 → 后续写回”的操作；'
                    + context(async_writers[0]) + '也会写入该变量。',
                    '重点确认：' + context(async_writers[0]) + '是否可能在主循环“读取”和“写回”之间执行。')
        multi_entry_rmw = next((view for view in rmw_views if len(view['context_ids']) > 1), None)
        if multi_entry_rmw:
            function_names = [function_name(fid) for fid in multi_entry_rmw['function_ids']]
            subject = '、'.join(function_names) or '该函数'
            return ('疑似并发风险', subject + '可由 ' + str(len(multi_entry_rmw['context_ids']))
                    + ' 个不同执行入口到达，且函数内会修改该变量。',
                    '重点确认：这些入口是否允许相互抢占，从而造成 ' + subject + ' 重入。')
        if async_writers and (main_writers or by_kind['READ']):
            reader_contexts = sorted(by_kind['READ'], key=context_sort_key)
            reader = context(reader_contexts[0]) if reader_contexts else '其它执行上下文'
            return ('疑似并发风险', reader + '会读取该变量；' + context(async_writers[0]) + '会写入该变量。',
                    '重点确认：写入者是否可能与读取或其它写入交错执行，以及保护是否覆盖完整访问。')
        if variable.get('static_classification') == 'SAFE_PROVEN' or assessments.get(variable['symbol_id']) == 'screened_safe':
            all_contexts = {cid for view in views for cid in view['context_ids']}
            if all_contexts and all(contexts.get(cid, {}).get('kind') == 'MAIN' for cid in all_contexts):
                reason = '当前解析到的访问均来自主循环同一串行执行上下文，未发现其它中断或异步执行入口修改该变量。'
            else:
                reason = '当前已解析的访问没有形成跨执行上下文的读写冲突。'
            return ('未发现并发风险', reason, '')
        if variable.get('static_classification') == 'UNKNOWN' or assessments.get(variable['symbol_id']) == 'unresolved':
            return ('无法判断', '部分访问的执行入口、抢占关系或保护证据尚未确认，不能据此判定安全。',
                    '重点确认：补齐缺失的入口、优先级或保护范围信息后重新判断。')
        return ('未发现并发风险', '当前解析范围内未发现需要进一步排查的跨执行上下文读写。', '')

    def protection_section(variable):
        status = to_display_text(variable.get('protection_status', 'NOT_FOUND'), PROTECTION_DISPLAY_TEXT)
        note = user_text(variable.get('protection_note') or '当前没有更多保护范围说明。')
        return ('<details><summary>查看保护分析</summary><p>保护状态：<strong>' + esc(status)
                + '</strong></p><p>' + esc(note) + '</p></details>')

    def scenario_section(finding):
        scenario = snapshot_scenario(finding, contexts) if finding else None
        if not scenario:
            return ''
        labels = ['读取共享变量', '可能被其它执行上下文插入更新', '恢复执行并写回旧值']
        body = ''
        for label, (context_id, access) in zip(labels, scenario):
            body += '<li><strong>' + esc(context(context_id)) + '：' + esc(label) + '</strong><br>'
            body += '<span class="location">' + esc(loc(access)) + '</span><pre>' + esc(access.get('source_text', '')) + '</pre></li>'
        return ('<details class="scenario"><summary>查看可能的并发时序</summary><p>这是需要在实际优先级、可达性和保护范围中确认的时序，不是已证明的运行轨迹。</p>'
                + '<ol>' + body + '</ol><p>结果：其它执行上下文刚写入的新值可能被旧值覆盖。</p></details>')

    def advanced_static_info(variable, finding_list, views, anchor_prefix):
        pairs = [pair for finding in finding_list for pair in finding.get('conflict_pairs', [])]
        relations = [relation for finding in finding_list for relation in finding.get('concurrency_relations', [])]
        body = deferred_detail('查看全部底层并发组合（' + str(len(pairs)) + ' 组）',
                               conflict_pair_table(pairs, variable.get('protection_status', 'NOT_FOUND'), anchor_prefix))
        body += '<details><summary>查看抢占关系、保护明细与静态规则</summary>'
        body += '<p>重复的保护 / 覆盖缺口明细仅保存在机器事实中，避免每个变量在 HTML 中重复数百次。'
        body += '完整内容见 <a href="facts.json">facts.json</a>（变量 ID：<code>' + esc(variable['symbol_id']) + '</code>）。</p>'
        body += raw(dict(抢占关系=relations,
                         保护明细概览=compact_evidence_summary(variable.get('protection_details', [])),
                         静态规则=[finding.get('rules', []) for finding in finding_list],
                         证据缺口概览=compact_evidence_summary(variable.get('blocking_evidence', []))),
                    '静态分析证据概览') + '</details>'
        body += '<details><summary>查看调试字段与完整机器事实的位置</summary>'
        body += '<p>源码访问、调用证据和并发组合已在本变量详情中展示。大图展示见证路径，全部入口和调用边保存在图证据中。完整机器事实保存在同目录 '
        body += '<a href="facts.json">facts.json</a>，可按变量 ID 查找：<code>' + esc(variable['symbol_id']) + '</code>。'
        body += '完整变量证据切片与多字段一致性来源保存在该事实文件中。</p>'
        body += raw(dict(source_access_views=[dict(key=view['key'], access_ids=view['access_ids'],
                                               contexts=view['context_ids'],
                                               access_metadata=[dict(
                                                   access_id=access.get('access_id'),
                                                   protection_evidence=access.get('protection_evidence', []),
                                                   resolved_call_edge_count=access.get('resolved_call_edge_count',len(access.get('resolved_call_edges', []))),
                                                   unresolved_call_edge_count=access.get('unresolved_call_edge_count',len(access.get('unresolved_call_edges', []))),
                                                   mask_state_count=len(access.get('mask_states', [])),
                                                   call_chain_cycle_count=len(access.get('call_chain_cycles', [])),
                                               ) for access in view['accesses']])
                                           for view in views],
                    完整证据定位=dict(file='facts.json',symbol_id=variable['symbol_id'],
                        fields=['variable_evidence_slice','multi_field_coherence']),
                    variable=compact_debug_fields(variable, {
                        'accesses', 'whole_object_accesses', 'conflict_pairs',
                        'concurrency_relations', 'protection_details', 'blocking_evidence',
                        'variable_evidence_slice', 'multi_field_coherence',
                    })), '调试 JSON（不重复嵌入访问事实）') + '</details>'
        return deferred_detail('高级静态分析信息', body, 'advanced')

    inventory_rows = []
    for v in facts['variables']:
        sid = v['symbol_id']
        links = '<br>'.join(f'<a href="#{anchor("risk-", f["finding_id"])}">查看候选原因 · {esc(PRIORITIES.get(f["risk_level"], f["risk_level"]))}</a>' for f in candidates[sid])
        sites = v.get('declarations', [])
        primary = dict(file=v.get('definition_file'), line=v.get('definition_line')) if v.get('definition_file') else next(iter(sites), {})
        files = sorted({d['file'] for d in sites if d.get('file')} | ({primary['file']} if primary.get('file') else set()))
        is_supplemental = v.get('coverage_source') in ('supplemental', 'inactive_branch')
        is_container = v.get('resource_kind') in {'STRUCT_CONTAINER', 'ARRAY_CONTAINER', 'STRUCT_MEMBER_CONTAINER'}
        detail_body = '<p>类型：' + esc(v.get('type')) + ' · 大小：' + esc(v.get('size_bytes')) + ' 字节 · volatile：' + ('是' if v.get('is_volatile') else '否') + ' · const：' + ('是' if v.get('is_const') else '否') + '</p>'
        impact = v.get('impact') if report.get('git_diff') else None
        if impact:
            detail_body += '<h3>本次影响依据</h3><p>' + esc('；'.join(impact['reason_labels'])) + '</p>'
            detail_body += '<p>风险变化：' + esc(impact['risk_change']) + '；影响覆盖：' + esc({'COMPLETE': '完整', 'CONSERVATIVE': '保守扩大'}.get(impact['impact_coverage'], '未完成')) + '</p>'
            if impact.get('risk_comparison_note'):
                detail_body += '<p>' + esc(impact['risk_comparison_note']) + '</p>'
            detail_body += diff_evidence_table(impact)
            if impact.get('diff_patch_path'):
                from pathlib import Path
                patch_path = Path(impact['diff_patch_path']).resolve()
                patch_link = patch_path.relative_to(out.resolve()).as_posix() if patch_path.is_relative_to(out.resolve()) else patch_path.as_uri()
                detail_body += '<p><a href="' + esc(patch_link) + '">查看本轮代码差异</a></p>'
            for key, label, source_root in [('removed_paths', '基准版本删除路径的最短代表证据', impact.get('base_source_root')), ('added_paths', '当前版本新增路径的最短代表证据', None)]:
                detail_body += '<h4>' + label + '</h4><pre>' + esc('\n'.join(' → '.join(function_name(fid) for fid in edge) for edge in impact[key]) or '没有调用边变化') + '</pre>'
            detail_body += '<p>未变化调用边：' + str(impact['unchanged_edges_count']) + ' 条，默认收起。其他未修改路径参与并发分析；完整访问和上下文保留在下方证据及 OpenCode Packet。</p>'
            if impact.get('base'):
                from pathlib import Path
                base = impact['base']
                if impact.get('base_source_root') and base.get('file'):
                    detail_body += '<p><a href="' + esc((Path(impact['base_source_root'])/(base.get('original_file') or base['file'])).as_uri()) + '">基准源码</a>：' + esc(base.get('original_file') or base['file']) + ':' + esc(base.get('line')) + '</p>'
            detail_body += '<details><summary>展开完整当前证据（含未修改路径）</summary>'
        if is_supplemental:
            detail_body += '<p class="notice">补充声明盘点：来自未编译文件或条件分支变体，不代表当前构建中已分析其并发访问。</p>'
        if is_container:
            members = sorted(members_by_root.get(sid, []), key=lambda member: member.get('field_path', ''))
            counts = v.get('member_status_counts', {})
            detail_body += '<h3>成员级结论</h3><p>成员：' + str(v.get('member_count', len(members))) + '；未发现并发风险：' + str(counts.get('safe', 0)) + '；疑似并发风险：' + str(counts.get('suspect', 0)) + '；无法判断：' + str(counts.get('unknown', 0)) + '。</p>'
            member_rows = []
            for member in members:
                member_rows.append(row(['<a href="#' + anchor('var-', member['symbol_id']) + '">' + esc(member['qualified_name']) + '</a>',
                                        esc(to_display_text(member.get('static_classification', 'UNKNOWN'))),
                                        str(member.get('access_count', 0)), str(member.get('resolved_call_path_count', 0)),
                                        str(len(member.get('conflict_pairs', [])))]))
            detail_body += table(['具体成员', '结论', '访问事实', '完整调用链', '底层并发组合'], member_rows)
            whole = v.get('whole_object_accesses', [])
            detail_body += '<h3>整对象访问及对成员的继承影响（' + str(len(source_access_views(whole))) + ' 处源码访问）</h3>'
            detail_body += accesses(whole, 'whole-' + sid)
            detail_body += advanced_static_info(v, candidates[sid], source_access_views(whole), 'whole-' + sid)
        else:
            verify_member_rendering(v)
            views = source_access_views(v.get('accesses', []))
            conclusion, reason, focus = variable_explanation(v, views, candidates[sid])
            reviewed_summary = reviewed_variable_summary(candidates[sid], records, v)
            if reviewed_summary:
                conclusion, reason = reviewed_summary
            detail_body += '<h3>一句话结论</h3><p><strong>' + esc(conclusion) + '</strong></p><p>' + esc(reason) + '</p>'
            if v.get('safe_reason_code'):
                detail_body += '<p>静态证明：<code>' + esc(v['safe_reason_code']) + '</code></p>' + raw(v.get('safe_evidence'), '查看安全证明依据')
            detail_body += '<p>变量证据覆盖：' + esc(v.get('analysis_coverage', 'PARTIAL')) + '</p>'
            if focus:
                detail_body += '<p class="notice"><strong>排查重点</strong><br>' + esc(focus) + '</p>'
            detail_body += '<h3>执行上下文摘要</h3>' + context_summary(views)
            detail_body += '<h3>全部源码访问与调用链（' + str(len(views)) + ' 处源码访问）</h3>'
            detail_body += accesses(v.get('accesses', []), 'inventory-' + sid, validate_member=v)
            detail_body += ('<details class="graph" data-symbol="' + esc(sid)
                            + '"><summary>展开完整调用图边证据（含其他未修改路径）</summary>'
                            '<pre>完整调用图按需载入，包含全部相关调用边。</pre></details>')
            detail_body += scenario_section(candidates[sid][0] if candidates[sid] else None)
            detail_body += protection_section(v)
            detail_body += advanced_static_info(v, candidates[sid], views, 'inventory-' + sid)
        if impact:
            detail_body += '</details>'
        detail = deferred_detail('查看结构体成员汇总' if is_container else '查看变量详情、源码访问与调用链', detail_body)
        group = 'supplemental' if is_supplemental else ('candidate' if candidates[sid] else 'inventory')
        list_views = source_access_views(v.get('accesses', []))
        if is_container:
            why = '结构体成员按具体字段分别分析；请进入成员项查看各字段的源码访问和调用链。'
            conclusion = '查看成员级结论'
        else:
            conclusion, why, _ = variable_explanation(v, list_views, candidates[sid])
            reviewed_summary = reviewed_variable_summary(candidates[sid], records, v)
            if reviewed_summary:
                conclusion, why = reviewed_summary
        if v.get('parse_status') == 'FAILED' and assessments[sid] == 'unresolved':
            conclusion, why = '无法判断', '解析不完整：只保留已恢复声明，可能仍有漏项，不能判定安全。'
        inventory_rows.append(row(['<a class="item-name" href="#' + anchor('var-', sid) + '">' + esc(v['qualified_name'])
            + '</a><span class="location">' + esc(f"{primary.get('file') or '缺少位置'}:{primary.get('line') or '?'}") + '</span>'
            + esc(KINDS.get(v['kind'], v['kind'])) + ' · ' + esc(v.get('type')),
            '<p>' + esc(why) + '</p>' + ('<p>影响：' + esc('；'.join(impact['reason_labels'])) + '</p>' if impact else ''),
            decision_tag(assessments[sid]) + '<p>' + esc(conclusion) + '</p>' + detail],
            anchor('var-', sid), group, file=primary.get('file'), decision=assessments[sid], files=files,
            search_text=' '.join(dict.fromkeys([v.get('qualified_name', ''), v.get('name', ''), v.get('type', ''), *files,
                                  *(function_name(a.get('function_id')) for a in v.get('accesses', [])),
                                  *(str(a.get('source_text', '')) for a in v.get('accesses', []))]))))

    risks, gaps = [], []
    for f in sorted(report['findings'], key=lambda f: (RISK_PRIORITY.index(decision(f, records[f['finding_id']],
                    variable=variables.get(f.get('symbol_id')))),
                    {'CRITICAL': 0, 'HIGH': 1, 'MEDIUM': 2, 'LOW': 3}.get(f['risk_level'], 4),
                    -len(set(f.get('rules', [])) & CONCURRENT_SIGNALS), f['variable_name'], f['finding_id'])):
        sid = f.get('symbol_id')
        ident = anchor('risk-', f['finding_id'])
        r = records[f['finding_id']]
        summary = rule_summary(f)
        detail_body = '<p><strong>静态线索需要结合实际交错与保护条件确认。</strong></p><ol>'
        detail_body += ''.join('<li>' + esc(title) + '：' + esc(action) + '</li>' for _, title, action in summary)
        pair_prefix = 'inventory-' + sid if sid else 'risk-' + f['finding_id']
        detail_body += '</ol>'
        if sid:
            detail_body += '<p>源码访问、执行上下文和全部调用链只在变量详情中展示一次：'
            detail_body += '<a href="#' + anchor('var-', sid) + '">打开 ' + esc(f['variable_name']) + ' 的变量详情</a>。</p>'
        else:
            detail_body += '<details><summary>相关源码访问与调用链</summary>' + accesses(f.get('accesses', []), pair_prefix) + '</details>'
        detail_body += '<details class="advanced"><summary>高级静态分析信息</summary>'
        if sid:
            detail_body += '<p>该变量的全部底层并发组合、访问事实和调用链只在变量详情中保留一次：'
            detail_body += '<a href="#' + anchor('var-', sid) + '">打开变量详情</a>。</p>'
        else:
            detail_body += deferred_detail('查看全部底层并发组合（' + str(len(f.get('conflict_pairs', []))) + ' 组）',
                                            conflict_pair_table(f.get('conflict_pairs', []),
                                                                f.get('protection_status', 'NOT_FOUND'), pair_prefix))
        detail_body += '<p>完整、不重复的机器事实在同目录 <a href="reports/global_static_concurrency.json">global_static_concurrency.json</a>；候选 ID：<code>' + esc(f['finding_id']) + '</code>。</p>'
        detail_body += raw(compact_debug_fields(f, {
            'accesses', 'conflict_pairs', 'concurrency_relations', 'context_pairs', 'review', 'review_result',
        }), '候选调试 JSON（不重复嵌入访问事实）') + '</details>'
        note = '\n'.join([f"变量 / 项目：{f['variable_name']}", f"定义：{loc(f['definition'])}",
                          f"候选 ID：{f['finding_id']}", '静态线索：' + '；'.join(t for _, t, _ in summary),
                          '复核状态：' + review_label(r), '源码指纹：' + str(report.get('fingerprint', '未知')),
                          '人工核对结论：', '实际交错 / 保护条件：', '修复与验证：'])
        detail_body += '<button type="button" data-copy="' + esc(note) + '">复制排查记录模板</button><span class="copy-note" role="status"></span>'
        detail = deferred_detail('查看排查建议', detail_body)
        scenario = snapshot_scenario(f, contexts)
        scenario_html = ''
        if scenario:
            phases = ['先读取共享值', '中断插入一次更新', '原路径恢复，随后写入共享值']
            scenario_html = '<details class="scenario"><summary>看一个可能出问题的执行顺序（3 步）</summary><p><strong>待验证示例，不是已证明的运行轨迹。</strong>仅当访问指向同一存储位置、所列分支可达、该中断能在读写之间抢占，且保护没有覆盖完整过程时，此顺序才可能发生。</p><ol>'
            for title, (cid, a) in zip(phases, scenario):
                scenario_html += '<li><strong>' + esc(title) + ' · ' + esc(context(cid)) + '</strong><span class="location">' + esc(loc(a)) + '</span><pre>' + esc(a['source_text']) + '</pre></li>'
            scenario_html += '</ol><p>需要验证的后果：第 2 步的新状态是否被第 3 步写入覆盖，而第 1 步的旧快照又看不到这次更新。</p></details>'
        name = f'<a class="item-name" href="#{anchor("var-", sid)}">{esc(f["variable_name"])}</a>' if sid else '<strong>' + esc(summary[0][1] if summary else f['variable_name']) + '</strong>'
        dependency = f.get('scope_role') == 'dependency_evidence'
        if dependency:
            name += '<br><span class="tag">依赖证据 · 与目标变量有关</span>'
        v = variables.get(sid)
        actors = ''
        if v:
            readers, writers = v.get('readers', []), v.get('writers', [])
            distances = {}
            for a in f.get('accesses', []):
                for cid, path in a.get('call_chains', {}).items():
                    distances[cid] = min(distances.get(cid, len(path)), len(path))
            entry_ids = sorted(set(readers) | set(writers), key=lambda cid: (
                contexts.get(cid, {}).get('kind') != 'MAIN', distances.get(cid, 999), cid))
            actors = '<p class="entry-summary">分析到的入口：<br>' + ('<br>'.join(esc(context(cid)) for cid in entry_ids[:2]) or '尚未确定')
            actors += (f'<br>另有 {len(entry_ids)-2} 个入口' if len(entry_ids) > 2 else '') + '</p>'
            actors += deferred_detail(f'全部入口：读 {len(readers)} / 写 {len(writers)}',
                                      '<strong>读取</strong><br>' + context_list(readers)
                                      + '<br><strong>写入</strong><br>' + context_list(writers))
        titles = '<ul class="signal-list">' + ''.join('<li>' + esc(t) + '</li>' for _, t, _ in summary[:2]) + '</ul>'
        if len(summary) > 2:
            titles += '<span class="muted">另有 ' + str(len(summary)-2) + ' 条线索，展开可看全部</span>'
        # Show actual source evidence immediately, from distinct functions when
        # possible. Preserve all other accesses and dependency paths in details.
        previews, seen_functions = [], set()
        source_accesses = sorted(f.get('accesses', []), key=lambda a: (
            not any(contexts.get(c, {}).get('kind') == 'MAIN' for c in a.get('contexts', [])),
            {'RMW': 0, 'WRITE': 1, 'READ': 2}.get(a.get('access_kind'), 3),
            min((len(path) for path in a.get('call_chains', {}).values()), default=999)))
        for a in source_accesses:
            if a['function_id'] in seen_functions or a.get('access_kind') == 'ADDRESS_TAKEN':
                continue
            seen_functions.add(a['function_id'])
            previews.append('<div class="source-preview"><strong>' + esc(KINDS.get(a['access_kind'], a['access_kind']))
                + ' · ' + esc(funcs.get(a['function_id'], {}).get('name', '未知函数')) + '</strong><span class="location">'
                + esc(loc(a)) + '</span><pre>' + esc(a.get('source_text', '')) + '</pre></div>')
            if len(previews) == 2:
                break
        assessment = decision(f, r, variable=variables.get(sid))
        if r.get('state') == 'DONE' and r.get('answer', {}).get('reason'):
            titles = '<p class="review-brief">' + esc(display_summary(r['answer'])) + '</p>' + titles
            if display_summary(r['answer']) != r['answer']['reason']:
                titles += '<details><summary>完整技术判断理由</summary>' + prose(r['answer']['reason']) + '</details>'
        state = f'<span class="tag {category(r)}">{esc(review_label(r))}</span>'
        cells = [(('<span>变量结论：</span>' + decision_tag(assessments.get(sid, assessment))
                  + '<br>') if sid else '')
                 + name + '<span class="location">' + esc(loc(f['definition'])) + '</span>'
                 + '<span class="tag priority-' + esc(f['risk_level']) + '">' + esc(PRIORITIES.get(f['risk_level'], f['risk_level'])) + '</span>' + actors,
                 titles + '<div class="source-previews">' + ''.join(previews) + '</div>' + scenario_html + detail,
                 '<p class="step">' + esc(summary[0][2] if summary else '查看证据，补充未知信息。') + '</p>'
                 + f'<a href="{REVIEW_PAGE}#{anchor("review-", f["finding_id"])}">{state}</a>']
        (risks if sid else gaps).append(row(cells, ident, 'candidate' if sid else 'gap',
            f['risk_level'], f['definition'].get('file'), 'dependency' if dependency else 'target', assessment))

    cov = report['coverage']
    coverage = scope_summary(cov)
    inventory_by_kind = (dict(Counter(v['kind'] for v in facts['variables'])) if report.get('git_diff')
                         else cov.get('inventory_by_kind', {}))
    if inventory_by_kind:
        coverage += '<h3>变量盘点分类</h3>' + table(['变量类别', '数量'], [row([esc(KINDS.get(k, k)), str(n)]) for k, n in sorted(inventory_by_kind.items())])
    coverage += metrics([('源码解析完整 / 总数', f'{cov.get("translation_units_parsed", "?")} / {cov.get("translation_units_total", "?")}'),
                         ('部分解析', cov.get('translation_units_partial', 0)),
                         ('解析失败', cov.get('translation_units_failed', 0)),
                         ('入口已知的目标函数 / 总数', f'{cov.get("functions_with_context", "?")} / {cov.get("functions_total", "?")}'),
                         ('未知入口访问', cov.get('unknown_accesses', 0)),
                         ('补充解析变量', cov.get('supplemental_variables', 0))])
    static = cov.get('static_classification', {})
    if static:
        coverage += '<h3>变量静态分类归账</h3>' + metrics([('变量总数', static.get('total', 0)),
            ('静态已判安全', static.get('safe_proven', 0)),
            ('共享访问，无需复核', static.get('shared_no_review', 0)),
            ('疑似并发风险', static.get('suspect', 0)),
            ('无法判断', static.get('unknown', 0))])
        coverage += '<h3>UNKNOWN 传播诊断</h3>' + raw(cov.get('blocker_fanout', []), 'blocker_fanout 与逐变量相关性证明')
        coverage += raw(cov.get('safe_reason_distribution', {}), 'SAFE 证明分布')
        coverage += raw(cov.get('unknown_reason_distribution', {}), 'UNKNOWN 关键缺口分布')
    problems = [row(['未进入编译数据库的源码', esc(p)]) for p in cov.get('unlisted_sources', [])]
    problems += [row(['未纳入的头文件', esc(p)]) for p in cov.get('unlisted_headers', [])]
    problems += [row(['解析失败', esc(u.get('source_file')) + raw(u.get('diagnostics', []), '查看失败原因')])
                 for u in facts.get('translation_units', []) if u.get('parse_status') not in {None, 'PARSED'}]
    coverage += '<h3>先处理这些覆盖问题</h3>' + (table(['问题', '文件 / 原因'], problems) if problems else '<p>没有发现解析失败或未纳入的目标源码 / 头文件。仍需核对未知入口与下面的分析限制。</p>')
    file_cov = cov.get('file_coverage', [])
    if file_cov:
        coverage += '<h3>每个排查文件的变量数与解析状态</h3>' + table(['文件', '变量数', '解析状态', '来源'], [
            row([esc(fc['file']), str(fc['variable_count']), esc(to_display_text(fc['parse_status'])),
                 esc({'compile_database': '当前构建', 'supplemental': '补充解析',
                      'inactive_branch': '非活动分支'}.get(fc.get('coverage_source'), '其它来源'))
                 + raw(dict(diagnostics=fc.get('diagnostics', []), gaps=fc.get('gaps', [])), '覆盖诊断')])
            for fc in file_cov])
    steps = cov.get('cmake_steps', [])
    if steps:
        coverage += '<h3>本次 CMake 配置与编译</h3>' + table(['步骤', '结果', '参数与日志'], [row([
            {'configure': '配置工程', 'build': '编译固件'}.get(s['stage'], s['stage']),
            '成功' if s['exit_code'] == 0 else '失败', raw(s, '构建参数及日志位置')]) for s in steps])
    coverage += raw(cov, '编译覆盖、遗漏源文件 / 头文件、排除文件与数量')
    coverage += raw(facts.get('translation_units', []), '全部编译单元、真实参数与解析诊断')
    coverage += raw(facts.get('unknowns', []), '全部原始分析盲区（不因合并复核项而删除）')
    coverage += raw(report.get('limitations', []), '分析限制') + raw(report.get('baseline', {}), '与上轮的变化')
    if report.get('git_diff', {}).get('fallback_reasons'):
        diff = report['git_diff']
        coverage += '<h3>差异关联尚未排除的潜在影响</h3><p>另有 ' + str(len(diff.get('conservative_symbol_ids', []))) + ' 个变量未发现版本变化或明确依赖，但因覆盖缺口暂不能排除潜在影响。它们未计入默认清单；未列出不构成额外的安全证明。</p>'
        coverage += raw(dict(reasons=diff['fallback_reasons'], symbol_ids=diff.get('conservative_symbol_ids', [])), '查看关联不确定性的范围与依据')
    coverage += '<h2>任务、中断与硬件上下文</h2>' + table(['上下文', '入口、优先级、注册与发现依据'],
        [row([esc(context(c['id'])), raw(c)]) for c in facts['contexts']])
    counts = Counter(category(r) for r in records.values())
    content = risk_overview(facts, report, records, assessments) + nvic_summary(facts)
    if report.get('git_diff'):
        diff = report['git_diff']
        pinned = diff['pin']
        classes = Counter(v.get('static_classification') for v in facts['variables'])
        summary = '<section class="overview"><h2>扫描模式：分支差异</h2><p>当前版本：' + esc(pinned['current_ref']) + '（' + esc(pinned['head_sha'][:12]) + '）；比较基准：' + esc(pinned['base_ref']) + '（' + esc(pinned['base_sha'][:12]) + '）；比较方式：两个版本直接比较</p>'
        storage_count = risk_summary(facts, report, records)['total_variables']
        summary += metrics([('变更文件', len(pinned['files'])), ('变更函数', len(diff['modified_function_ids'])), ('受影响分析对象', storage_count), ('疑似并发风险', classes['SUSPECT']), ('无法判断', classes['UNKNOWN']), ('静态已判安全', classes['SAFE_PROVEN']), ('共享访问，无需复核', classes['SHARED_NO_REVIEW'])])
        summary += '<p>当前差异清单共 ' + str(len(diff['selected_symbol_ids'])) + ' 行（含结构体/数组容器汇总）；上述静态分类按实际分析对象统计，容器不重复计入风险分母。</p>'
        summary += '<p>影响分析状态：' + ('仍有未排除的潜在影响（' + esc('；'.join(diff['fallback_reasons'])) + '）' if diff['fallback_reasons'] else '完整') + '。未列出变量不代表安全。覆盖栏目使用完整构建范围。</p>'
        summary += '<p>默认清单仅展示有版本变化或明确依赖关系的变量；未排除的潜在影响另有 ' + str(len(diff.get('conservative_symbol_ids', []))) + ' 个，详见覆盖说明。后台始终保留完整并发分析。</p>'
        if not diff['selected_symbol_ids']:
            summary += '<p>本次比较未识别到需要核对的差异变量。</p>'
        if diff['deleted_variables']:
            summary += '<details><summary>已删除存储对象（不计入当前风险统计）</summary>' + raw(diff['deleted_variables'], '删除证据') + '</details>'
        content = summary + '</section>' + content
    content += '<nav class="tabs" aria-label="排查栏目">' + ''.join(f'<a href="#{key}">{label} {number}</a>' for key, label, number in [
        ('risks', '变量风险结论', len(risks)), ('inventory', '差异涉及变量' if report.get('git_diff') else '全部目标变量', len(inventory_rows)), ('gaps', '覆盖 / 依赖证据', len(gaps)), ('coverage', '过滤与覆盖校验', '')]) + '</nav><!--controls-->'
    decision_options = [('decision:' + key, value[0]) for key, value in DECISIONS.items()]
    priority_options = [('all', '全部结论')] + decision_options[:-1] + [('level:' + k, v) for k, v in PRIORITIES.items()]
    content += panel('risks', '变量风险结论与关键证据',
        '先看左侧结论，再看读写语句和下一步。确认风险在前，疑似风险其次；证据不足单独标识。',
        table(['风险结论 / 目标变量', '关键依据：哪里读写、为什么可疑', '下一步处理'], risks, 'risk-table', True), priority_options)
    content += panel('inventory', '本次差异涉及的全局 / static 变量' if report.get('git_diff') else '全部全局 / static 变量清单', '先看变量为什么值得排查和结论；点击变量即可查看执行上下文、真实源码访问与完整调用链。相同源码访问点不会因多个入口重复成行。',
        table(['变量', '为什么值得看', '结论'], inventory_rows, 'inventory-table', True),
        [('all', '全部差异变量' if report.get('git_diff') else '全部变量'), ('candidate', '有静态候选'), ('inventory', '未筛出候选'), ('supplemental', '补充解析')] + decision_options)
    content += panel('gaps', '待补证据：影响判断的覆盖缺口',
        '这些记录不是已确认的变量风险。标有“依赖证据”的第三方路径与目标变量有关，补证据后才能缩小不确定性。',
        table(['缺口与位置', '缺少什么证据', '如何补充 / 复核状态'], gaps, 'gap-table', True),
        [('all', '全部缺口'), ('scope:target', '目标范围 / 全局缺口'), ('scope:dependency', '相关依赖证据')])
    content += panel('coverage', '覆盖范围与分析限制',
        '这里只覆盖本次构建实际解析到的代码；条件编译关闭的代码需使用对应构建变体另行扫描。', coverage, [])
    content += '<details class="legend"><summary>新手术语：读、写、读改写、上下文和证据缺口</summary><p>上下文是代码从哪个主循环、中断或硬件入口执行。读取是取值；写入是更新值；读改写是先读再计算再写回；取地址本身不代表读写。证据缺口表示工具还无法确定某段行为。volatile、static 或出现锁 API 都不能单独证明并发安全。</p></details>'

    # Preserve every relevant edge without enumerating infinitely many recursive
    # paths. The reverse traversal is lazy and includes alternate call sites.
    graph_ids = {fid for call in facts['calls'] for fid in
                 (call.get('caller_function_id'), call.get('callee_function_id')) if fid}
    graph_ids.update(a['function_id'] for v in facts['variables'] for a in v.get('accesses', []))
    graph = dict(functions={fid: function(fid) for fid in sorted(graph_ids)},
                 calls=[{k: c.get(k) for k in ('caller_function_id', 'callee_function_id', 'callee_name', 'call_kind', 'file', 'line')} for c in facts['calls']],
                 accesses={v['symbol_id']: sorted({a['function_id'] for a in v.get('accesses', [])}) for v in facts['variables']})
    graph_script = """
const graph=JSON.parse(document.getElementById('call-graph').textContent), incoming=new Map();
for(const edge of graph.calls){const k=edge.callee_function_id;if(!incoming.has(k))incoming.set(k,[]);incoming.get(k).push(edge);}
document.addEventListener('toggle',event=>{const d=event.target;if(!d.matches('details.graph')||!d.open||d.dataset.loaded)return;d.dataset.loaded='1';let seen=new Set(), edges=[], todo=[...(graph.accesses[d.dataset.symbol]||[])];while(todo.length){let f=todo.pop();if(seen.has(f))continue;seen.add(f);for(const e of incoming.get(f)||[]){edges.push(e);todo.push(e.caller_function_id);}}d.querySelector('pre').textContent=edges.map(e=>(graph.functions[e.caller_function_id]||e.caller_function_id)+' → '+(graph.functions[e.callee_function_id]||e.callee_name)+' ['+e.call_kind+'] @ '+e.file+':'+e.line).join('\\n')||'没有已解析调用边；入口直接访问或上下文未知。';},true);
"""
    evidence = CURRENT.get()
    if evidence is not None:
        graph_script = """
let graphPromise=null;
function completeGraph(){if(window.ECRA_CALL_GRAPH)return Promise.resolve(window.ECRA_CALL_GRAPH);if(!graphPromise)graphPromise=new Promise((resolve,reject)=>{const s=document.createElement('script');s.src=(document.documentElement.dataset.ecraRoot||'')+'html_details/graph-data.js';s.onload=()=>window.ECRA_CALL_GRAPH?resolve(window.ECRA_CALL_GRAPH):reject(new Error('missing graph'));s.onerror=reject;document.head.append(s);}).catch(error=>{graphPromise=null;throw error;});return graphPromise;}
document.addEventListener('toggle',async event=>{const d=event.target;if(!d.matches('details.graph')||!d.open||d.dataset.loaded)return;d.dataset.loaded='loading';const pre=d.querySelector('pre');pre.textContent='正在载入完整调用关系…';try{const graph=await completeGraph(),incoming=new Map();for(const edge of graph.calls){const k=edge.callee_function_id;if(!incoming.has(k))incoming.set(k,[]);incoming.get(k).push(edge);}const seen=new Set(),edges=[],todo=[...(graph.accesses[d.dataset.symbol]||[])];while(todo.length){const f=todo.pop();if(seen.has(f))continue;seen.add(f);for(const e of incoming.get(f)||[]){edges.push(e);todo.push(e.caller_function_id);}}pre.textContent=edges.map(e=>(graph.functions[e.caller_function_id]||e.caller_function_id)+' → '+(graph.functions[e.callee_function_id]||e.callee_name)+' ['+e.call_kind+'] @ '+e.file+':'+e.line).join('\\n')||'没有已解析调用边；入口直接访问或上下文未知。';d.dataset.loaded='1';}catch{delete d.dataset.loaded;pre.textContent='完整调用图未能载入，不能将其解释为没有调用关系；请检查 html_details 文件。';}},true);
"""
        evidence.graph(graph, graph_script)
    else:
        data = json.dumps(graph, ensure_ascii=False).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
        content += '<script type="application/json" id="call-graph">' + data + '</script>'
    inventory_page = page('并发变量排查报告', content, report, priority_options, graph_script)

    counts = Counter(category(r) for r in records.values())
    review_rows = defaultdict(list)
    review_jumps = defaultdict(list)
    ordered_findings = sorted(report['findings'], key=lambda f: RISK_PRIORITY.index(
        decision(f, records[f['finding_id']], variable=variables.get(f.get('symbol_id')))) if f.get('symbol_id') else 4)
    for f in ordered_findings:
        r = records[f['finding_id']]
        # Failed/stale receipts may contain an old answer. Preserve it only in
        # the raw record, never as the current explanation or source evidence.
        answer = r.get('answer', {}) if r['state'] == 'DONE' else {}
        group = assessments.get(f['symbol_id'], decision(f, r)) if f.get('symbol_id') else category(r)
        status = review_label(r)
        if not f.get('symbol_id') and r['state'] == 'DONE':
            status = {'CONFIRMED': '此证据疑点成立', 'LIKELY': '此证据疑点仍需验证',
                      'REVIEWED_SAFE': '此证据项已解释（有适用条件）',
                      'FALSE_POSITIVE': '此证据疑点为误报'}.get(r.get('status'), status)
        captured = {(e['file'], e['line']): e for e in r.get('source_evidence', [])}
        evidence_rows = []
        for evidence_index, e in enumerate(answer.get('evidence', []), 1):
            window = captured.get((e.get('file'), e.get('line')), {})
            excerpt = '\n'.join(f"{line['line']}: {line['text']}" for line in window.get('lines', []))
            evidence_rows.append(row([esc(e.get('file')), esc(e.get('line')),
                '<p>' + esc(e.get('claim', '按下方源码核对结论依据')) + '</p>' +
                '<pre>' + esc(excerpt or '此旧记录未保存源码片段；请按文件与行号核对原始源码。') + '</pre>' + raw(window or e)],
                anchor('citation-', f['finding_id'] + ':' + str(evidence_index)) ))
        source_evidence = table(['文件', '行号', '引用处源码及邻近语句'], evidence_rows)
        explanation = story_explanation(answer, category(r), bool(f.get('symbol_id')),
                                        lambda i: '#' + anchor('citation-', f['finding_id'] + ':' + str(i)))
        if r.get('language_correction') and answer:
            explanation = ('<p class="notice">本条中文表达经过独立修正，原始结论、数值、工程标识符和源码位置已通过一致性校验；原始回答及修正日志分别保留。</p>' + explanation)
        if r['state'] in {'TECH_FAILED', 'STALE', 'FAILED'} and r.get('answer'):
            explanation += '<p>旧回答已失效，仅在原始记录中保留，不作为本轮结论或证据。</p>'
        message = r.get('error', '')
        if is_english_prose(message):
            message = '复核执行或校验未完成，请查看下方原始日志中的错误详情。'
        error = '<details><summary>复核未完成的原因</summary><p>' + esc(message) + '</p></details>' if message and not local_pending(r) else ''
        execution = r.get('execution', {})
        for key, label in (('prompt_file', 'Prompt'), ('packet_file', '证据包'),
                           ('stderr_file', 'stderr')):
            name = execution.get(key) or r.get(key)
            if name:
                error += '<p><a href="review/' + esc(name) + '">' + label + '</a></p>'
        if execution.get('stdout_file'):
            error += '<p><a href="review/' + esc(execution['stdout_file']) + '">原始 OpenCode 执行日志</a></p>'
            error += '<details><summary>执行时间、日志 SHA-256 与校验范围</summary>' + fields(execution) + '</details>'
        for attempt in r.get('attempts', [])[r.get('attempt_start', 0):]:
            error += '<details class="repair-attempt"><summary>调用 ' + str(attempt.get('number', '')) + ' · ' + esc(attempt.get('stage', '')) + '</summary>'
            error += fields(attempt)
            for stream, title in [('prompt', '完整提示词'), ('stdout', '原始响应'), ('stderr', '标准错误')]:
                if attempt.get(stream + '_file'):
                    error += '<p><a href="review/' + esc(attempt[stream + '_file']) + '">' + title + '</a></p>'
            error += '</details>'
        if r.get('previous_reviews'):
            error += '<p>保留 ' + str(len(r['previous_reviews'])) + ' 次先前回答，当前状态：' + esc(r['status']) + '。</p>'
            for attempt, previous in enumerate(r['previous_reviews'], 1):
                error += '<details><summary>第 ' + str(attempt) + ' 轮历史回答（不作为当前结论）</summary><p>历史原文保留在原始归档中；未经中文复核不混入当前说明。</p>'
                if previous.get('execution',{}).get('stdout_file'):
                    error += '<a href="review/' + esc(previous['execution']['stdout_file']) + '">该轮 OpenCode 日志</a>'
                error += '</details>'
        source_link = f'index.html#{anchor("var-", f["symbol_id"])}' if f.get('symbol_id') else f'index.html#{anchor("risk-", f["finding_id"])}'
        name = f['variable_name'] if f.get('symbol_id') else (rule_summary(f)[0][1] if f.get('rules') else f['variable_name'])
        bucket = 'gaps' if not f.get('symbol_id') else ('safe' if group == 'safe' else 'risks')
        ident = anchor('review-', f['finding_id'])
        variable = variables.get(f.get('symbol_id'), {})
        instances = variable.get('translation_units', []) if str(f.get('symbol_id', '')).startswith('tu::') else []
        instance = ' · 实例属于 ' + '、'.join(instances) if instances else ''
        review_jumps[bucket].append((ident, name + ' · ' + loc(f['definition']) + instance))
        # Quotes and claims stay linked to the exact receipt. They are not new
        # model answers, execution observations, or guessed context pairs.
        citations = '<details class="story-citations"><summary>核对这条解释的源码依据（' + str(len(evidence_rows)) + ' 处）</summary><ol>'
        for evidence_index, e in enumerate(answer.get('evidence', []), 1):
            citations += '<li><a href="#' + anchor('citation-', f['finding_id'] + ':' + str(evidence_index)) + '">' + esc(loc(e)) + '</a> — ' + esc(e.get('claim', '查看引用源码')) + '</li>'
        citations += '</ol></details>'
        current = ('<div class="story-current"><div class="story-heading"><div><h3>' + esc(name) + '</h3>'
                   + '<span class="location">' + esc(loc(f['definition']) + instance) + '</span></div>'
                   + ('<span>变量最终分类：</span>' + decision_tag(group) + ' ' if f.get('symbol_id') else '')
                   + f'<span class="tag {category(r)}">OpenCode：{esc(status)}</span></div>' + explanation + citations + '</div>')
        audit = ('<details class="story-audit"><summary>原始证据、执行日志与历史复核</summary>' + error
                 + f'<p><a href="{source_link}">静态读写与变量身份</a> · <a href="index.html#{anchor("risk-", f["finding_id"])}">候选依据与处理步骤</a></p>'
                 + '<details class="evidence"><summary>有效复核引用的源码（' + str(len(evidence_rows)) + ' 处）</summary>' + source_evidence + '</details>'
                 + deferred_detail('静态读写与上下文调用链', accesses(f.get('accesses', []), 'review-' + f['finding_id']))
                 + '<p><a href="review/queue.json">原始复核记录与历史回答归档</a>（保留原文，不混入当前中文结论）</p></details>')
        review_rows[bucket].append(row(['<article class="review-story ' + group + '">' + current + audit + '</article>'],
            ident, group, file=f['definition'].get('file')))
    review_options = [('all', '全部结论'), ('confirmed', '确认存在风险'), ('likely', '疑似，仍需验证'), ('safe', '条件安全 / 误报'), ('unresolved', '无法判断')]
    conclusion = final_conclusion(report, list(records.values()))
    counts_by_variable = risk_summary(facts, report, records)['counts']
    content = '<div class="review-reading"><section class="review-verdict"><h2>最终结论：' + esc(conclusion['label']) + '</h2>'
    remaining_variables = sum(counts_by_variable[k] for k in ('likely','unresolved','supplemental','inventory'))
    content += '<p><strong>' + str(counts_by_variable['confirmed']) + ' 个变量确认有风险</strong> · ' + str(counts_by_variable['safe']) + ' 个变量复核安全 / 误报 · ' + str(remaining_variables) + ' 个变量仍需判断。</p>'
    content += '<p class="muted">' + esc(conclusion['scope']) + ' 收到有效回答 ' + str(conclusion['reviewed']) + '/' + str(conclusion['total']) + ' 项（含独立证据缺口；证据不足的回答仍需继续排查）。</p></section>'
    from .review_integrity import review_integrity
    integrity = report.get('review_integrity') or review_integrity(report, reviews)
    content += '<p class="review-coverage"><strong>' + ('复核目标全部完成' if integrity['all_done'] else '复核结果不完整') + '</strong> · OpenCode目标总数 ' + str(integrity['targets']) + ' · 成功完成数 ' + str(integrity['done']) + ' · 复核失败数 ' + str(integrity['failed']) + ' · 待复核数 ' + str(integrity['pending']) + ' · 结果失效数 ' + str(integrity['stale']) + ' · 遗漏数 ' + str(integrity['missing']) + ' · 重复数 ' + str(integrity['duplicate']) + '</p>'
    if integrity['errors']:
        content += '<details><summary>复核结果不完整：查看不变量错误</summary>' + raw(integrity['errors']) + '</details>'
    content += '<p class="format-summary">最终分类合并静态证据与有效 OpenCode 复核；证据不足、待复核、技术失败或失效不会降低静态疑似风险。OpenCode 原始结论和解释单独展示。review 重新复核全部静态疑似/未知变量；review-failed 只重新复核技术失败项。</p>'
    content += '<nav class="tabs" aria-label="复核栏目">' + ''.join('<a href="#reviews' + ('-' + key if key != 'risks' else '') + '">' + label + ' ' + str(len(review_rows[key])) + '</a>'
        for key, label in [('risks', '风险变量'), ('safe', '安全 / 误报'), ('gaps', '独立证据缺口')]) + '</nav><!--controls-->'
    for key, title, description in [
        ('risks', '风险变量：先看它是怎样发生的', '每张卡直接展示执行过程、保护条件和结果；疑似或未完成项会明确标注。'),
        ('safe', '安全 / 误报：为什么不构成冲突', '列出阻止交错的条件；仅适用于本条复核的构建与路径。'),
        ('gaps', '独立证据缺口：与变量缺陷分开查看', '这些是调用、硬件或覆盖信息的复核项；确认一个证据缺口，不等于确认一个变量缺陷。')]:
        jump = '<label class="story-jump">快速定位 <select data-story-jump><option value="">选择变量 / 复核项及定义位置</option>'
        jump += ''.join('<option value="' + ident + '">' + esc(label) + '</option>' for ident, label in review_jumps[key]) + '</select></label>'
        content += panel('reviews' + ('-' + key if key != 'risks' else ''), title, description,
            jump + table(['复核说明'], review_rows[key], 'review-' + key + '-table', True), review_options)
    samples = report.get('review_safe_samples', [])
    if samples:
        sample_records = {r['finding_id']:r for r in review_records(dict(findings=samples), reviews)}
        sample_rows = []
        for sample in samples:
            receipt = sample_records[sample['finding_id']]
            proof_label = ('静态安全证明与全部访问'
                           if sample.get('static_classification') == 'SAFE_PROVEN'
                           else '共享免复核门禁与全部访问')
            sample_rows.append(row([esc(sample['variable_name']), esc(review_label(receipt)),
                '<a href="index.html#' + anchor('var-',sample['symbol_id']) + '">' + proof_label + '</a>'
                + raw(receipt, '抽样复核记录') + deferred_detail('全部静态访问', accesses(sample.get('accesses', []), 'sample-' + sample['finding_id']))],
                anchor('review-',sample['finding_id'])))
        content += '<section id="safe-samples"><h2>筛除项独立抽样审计</h2><p>SAFE_PROVEN 与 SHARED_NO_REVIEW 分别抽样；不计入风险队列，也不改变静态分类。</p>' + table(['变量','复核状态','证据'],sample_rows) + '</section>'
    content += '<details class="review-scope"><summary>覆盖范围、复核进度与术语说明</summary>'
    content += '<p>主循环：CPU 正常轮询执行的代码。中断 / ISR：事件触发后，CPU 暂停当前代码并执行处理函数，返回后继续原来的位置。DMA：独立于 CPU 搬运数据的硬件。读改写 / RMW：读出旧值、计算、写回；中间若被另一写入者打断，可能覆盖对方的新值。</p>'
    content += nvic_summary(facts)
    content += overview(report, records.values(), [('确认项（含缺口）', counts['confirmed']), ('疑似项', counts['likely']), ('安全 / 误报项', counts['safe']), ('待复核 / 证据不足项', counts['unresolved'])])
    content += raw(cov, '本轮静态覆盖范围') + raw(report['limitations'], '结论适用范围与限制') + '</details></div>'
    review_page = page('并发复核：原因、过程与结论', content, report, review_options, reading=True)
    quality_page = classification_quality_html(facts, report)
    for name, contents in [('index.html', inventory_page), (REVIEW_PAGE, review_page),
                           (QUALITY_PAGE, quality_page)]:
        if evidence is not None:
            evidence.register(name, contents)
        temporary = out / (name + '.tmp')
        temporary.write_text(contents, encoding='utf-8')
        from .common import replace_file
        replace_file(temporary, out / name)
    if evidence is not None:
        evidence.finish()


def write_failure(out, state='FAILED', *, write_report=True):
    title = {'RUNNING': '本次扫描正在运行', 'INTERRUPTED': '本次扫描已中断'}.get(state, '本次扫描失败')
    contents = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>' + title + '</title><h1>' + title + '，不能使用旧结论</h1><p>请查看 run.json / run.log 和 diagnostics/exception.log。已有事实及复核缓存可能来自旧版本，不能作为本次结论。</p></html>'
    for name in ('index.html', REVIEW_PAGE, QUALITY_PAGE):
        (out / name).write_text(contents, encoding='utf-8')
    # The previous complete report is already archived by run(). A consumer
    # opening JSON directly must also see invalidity, not last run's SAFE rows.
    from .common import write_json
    if write_report:
        write_json(out / 'reports/global_static_concurrency.json', dict(
            analysis_status='INVALID', analysis_valid=False, run_status=state, findings=[],
            coverage={}, limitations=[title + '；旧结论不可作为本次扫描结果。'],
            diagnostic_files=['run.json', 'diagnostics/exception.log', 'diagnostics/source_changes.json']))
