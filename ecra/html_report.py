"""Two offline, evidence-preserving views of the same scan and review queue."""
import html
import json
from collections import Counter, defaultdict
from datetime import datetime

from .common import digest
from .review_presentation import explanation as story_explanation


REVIEW_PAGE = "opencode_review.html"
VERDICTS = {
    "CONFIRMED": "确认存在并发风险",
    "LIKELY": "疑似存在，尚需验证",
    "REVIEWED_SAFE": "已复核：在所述条件下安全",
    "FALSE_POSITIVE": "已复核：该候选为误报",
    "NEED_MORE_CONTEXT": "证据不足 / 尚未完成",
}
LABELS = {
    "symbol_id": "唯一变量 ID", "name": "名称", "qualified_name": "限定名称", "kind": "变量类别",
    "scope": "作用域", "storage_class": "存储类别", "linkage": "链接属性", "type": "类型",
    "size_bytes": "大小（字节）", "alignment_bytes": "对齐（字节）", "initializer": "初始化表达式",
    "declarations": "所有声明", "definitions": "所有定义", "translation_units": "所属编译单元",
    "is_const": "const", "is_volatile": "volatile", "is_array": "数组", "is_pointer": "指针",
    "is_struct": "结构体", "is_bitfield_container": "包含位域", "audit_status": "静态盘点状态",
    "protection_status": "保护证据状态", "annotations": "资源配置", "core_instances": "各核实例",
    "reason": "结论依据", "interleaving": "最短交错时序 / 不发生交错的条件",
    "protection": "保护范围及不足", "impact": "影响", "fix": "修复建议", "verification": "验证方法",
}

# The first sentence describes a static signal, not a confirmed execution bug.
RULES = {
    'GS-RMW-INTERLEAVE': ('读改写可能被打断', '核对读出旧值到写回之间，是否可能被另一写入者抢占。'),
    'GS-STALE-SNAPSHOT': ('旧快照可能覆盖新状态', '沿调用链核对快照读取、后续更新和最终写回是否在同一保护范围内。'),
    'DMA_SHARED_REVIEW': ('CPU 与 DMA 共享缓冲区', '核对 DMA 完成前 CPU 是否会复用或读取缓冲区，以及完成通知和所有权交接。'),
    'GS-MULTI-WRITER': ('多个执行入口会写入', '先核对各写入入口能否交错，再确认临界区覆盖了完整更新。'),
    'GS-TEAR-RISK': ('访问可能需要多条指令', '核对实际访问宽度和对齐，检查读取时是否可能混入另一次更新。'),
    'GS-STRUCT-INCONSISTENT': ('多个字段可能不一致', '检查读者能否读到一部分新字段和一部分旧字段。'),
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
         'ADDRESS_TAKEN': '取地址（不等于读写）'}


def rule_summary(finding):
    rules = finding.get('rules', [])
    known = [code for code in RULES if code in rules]
    ordered = known + [code for code in rules if code not in RULES]
    return [(code, *RULES.get(code, (code, '查看完整证据并补充缺失信息。'))) for code in ordered]


def local_pending(record):
    return record.get('state') == 'PENDING' and '自动复核已关闭' in record.get('error', '')


def review_label(record):
    if record.get('state') == 'DONE':
        return VERDICTS.get(record.get('status'), '证据不足，不能判定安全')
    return {'FAILED': '复核失败，不能判定安全', 'STALE': '旧结论已失效，需重新复核',
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
    return f"<details><summary>{esc(title)}</summary><pre>{esc(value)}</pre></details>"


def fields(value):
    return "<dl>" + "".join(f"<dt>{esc(LABELS.get(k, k))}</dt><dd><pre>{esc(v)}</pre></dd>" for k, v in value.items()) + "</dl>"


def table(headers, rows, ident=None, searchable=False):
    attrs = (f' id="{esc(ident)}"' if ident else "") + (' class="searchable"' if searchable else "")
    body = "".join(rows) or f'<tr><td colspan="{len(headers)}">无记录</td></tr>'
    pager = (f'<div class="pager" data-table="{esc(ident)}"><button type="button" data-step="-1">上一页</button><span aria-live="polite"></span><button type="button" data-step="1">下一页</button></div>' if searchable else '')
    empty = '<p class="empty" hidden>没有匹配记录。请更换关键词、切换栏目，或点击“清除筛选”。</p>' if searchable else ''
    return pager + empty + '<div class="table-scroll"><table' + attrs + '><thead><tr>' + "".join(f'<th scope="col">{esc(h)}</th>' for h in headers) + "</tr></thead><tbody>" + body + "</tbody></table></div>"


def row(cells, ident=None, group=None, level=None, file=None, scope=None, decision=None, files=None):
    attrs = (f' id="{esc(ident)}"' if ident else "") + (f' data-group="{esc(group)}"' if group else "")
    for key, value in [('level', level), ('file', file), ('scope', scope), ('decision', decision)]:
        if value is not None:
            attrs += f' data-{key}="{esc(value)}"'
    if files is not None:
        attrs += ' data-files="' + esc(json.dumps(files)) + '"'
    return "<tr" + attrs + ">" + "".join("<td>" + c + "</td>" for c in cells) + "</tr>"


def review_records(report, reviews):
    """Every current finding gets a row; absent/stale receipts cannot imply safe."""
    by_id = {r["finding_id"]: r for r in reviews}
    return [dict(by_id.get(f["finding_id"], {}), finding_id=f["finding_id"],
                 state=by_id.get(f["finding_id"], {}).get("state", "PENDING"),
                 status=by_id.get(f["finding_id"], {}).get("status", "NEED_MORE_CONTEXT"))
            for f in report["findings"]]


def category(review):
    if review.get("state") != "DONE":
        return "unresolved"
    return {"CONFIRMED": "confirmed", "LIKELY": "likely", "REVIEWED_SAFE": "safe", "FALSE_POSITIVE": "safe"}.get(review.get("status"), "unresolved")


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
    elif unresolved or report.get('analysis_status') != 'MODELED_SCOPE_COMPLETE':
        verdict, label = 'INCONCLUSIVE', '尚不能确定：不能据此宣称没有问题'
    else:
        verdict, label = 'NO_ISSUES_IN_SCOPE', '本次已覆盖的构建与候选范围内未确认并发问题'
    return dict(verdict=verdict, label=label, confirmed_findings=confirmed,
                unresolved_findings=unresolved, total=len(records),
                reviewed=sum(r['state'] == 'DONE' for r in records),
                static_coverage_complete=report.get('analysis_status') == 'MODELED_SCOPE_COMPLETE',
                scope='仅适用于当前源码、构建配置和已覆盖路径；原文校验不等于硬件运行验证。')


CONCURRENT_SIGNALS = {'GS-MULTI-CONTEXT', 'GS-MULTI-WRITER', 'GS-RMW-INTERLEAVE',
    'GS-STALE-SNAPSHOT', 'DMA_SHARED_REVIEW', 'GS-LOCAL-STATIC-REENTRANT', 'GS-OWNER-VIOLATION'}
DECISIONS = {
    'confirmed': ('已确认风险', '存在风险；查看复核依据并修复。'),
    'likely': ('疑似并发风险', '有并发风险线索，尚未证实为实际缺陷。'),
    'unresolved': ('无法判断', '缺少入口、访问或定义证据，不能判定安全。'),
    'safe': ('已复核安全 / 误报', '仅在该项复核列出的条件下成立。'),
    'screened_safe': ('已排查：不存在并发风险', '当前编译配置下没有可形成读写冲突的已知访问；不覆盖解析盲区、汇编或未建模硬件入口。'),
    'inventory': ('未发现风险线索', '当前建模路径未发现候选，尚未证明安全。'),
    'supplemental': ('补充声明（未分析访问）', '来自未编译文件或条件分支变体；仅盘点声明，并发访问尚未分析。'),
}


def decision(finding, record):
    reviewed = category(record)
    if reviewed != 'unresolved':
        return reviewed
    return 'likely' if set(finding.get('rules', [])) & CONCURRENT_SIGNALS else 'unresolved'


def variable_decisions(facts, report, records):
    groups = defaultdict(list)
    for f in report['findings']:
        if f.get('symbol_id'):
            groups[f['symbol_id']].append(decision(f, records.get(f['finding_id'], {})))
    priority = ['confirmed', 'likely', 'unresolved', 'safe']
    result = {}
    for v in facts['variables']:
        sid = v['symbol_id']
        if v.get('coverage_source') in ('supplemental', 'inactive_branch'):
            result[sid] = 'supplemental'
        elif v.get('parse_status') == 'FAILED':
            result[sid] = 'unresolved'
        elif groups[sid]:
            result[sid] = min(groups[sid], key=priority.index)
        elif v.get('audit_status') == 'SCREENED_NO_CONCURRENCY_RISK':
            result[sid] = 'screened_safe'
        else:
            result[sid] = 'inventory'
    return result


def risk_summary(facts, report, records):
    """One variable-level interpretation shared by HTML and machine exports."""
    decisions = variable_decisions(facts, report, records)
    counts = Counter(decisions.values())
    return dict(total_variables=len(decisions), counts={key: counts[key] for key in DECISIONS},
                labels={key: value[0] for key, value in DECISIONS.items()},
                independent_gaps=sum(not f.get('symbol_id') for f in report['findings']),
                basis='静态线索与有效复核共同分类；疑似不等于已确认，未发现线索不等于安全。',
                variables=[dict(symbol_id=v['symbol_id'], name=v.get('qualified_name', v.get('name')),
                    definition_file=v.get('definition_file'), definition_line=v.get('definition_line'),
                    kind=v.get('kind'), coverage_source=v.get('coverage_source', 'compile_database'),
                    decision=decisions[v['symbol_id']], label=DECISIONS[decisions[v['symbol_id']]][0])
                    for v in facts['variables']])


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
#review-table{table-layout:fixed;min-width:1000px}#review-table>thead th:nth-child(1){width:15%}#review-table>thead th:nth-child(2){width:15%}#review-table>thead th:nth-child(3){width:34%}#review-table>thead th:nth-child(4){width:26%}#review-table>thead th:nth-child(5){width:10%}#inventory-table{min-width:1100px}
@media(max-width:700px){main{padding:14px}header{padding:20px}header h1{font-size:21px}.toolbar{position:static}td,th{padding:8px}dl{grid-template-columns:1fr}}
header{padding:18px 4vw}header h1{font-size:24px}header p{margin:3px 0 8px}main{padding-top:18px;max-width:1600px}
.overview{background:white;border:1px solid #d6e0eb;border-radius:8px;padding:14px 18px;margin-bottom:16px}.overview p{margin:4px 0}.overview h2{margin:0 0 5px;font-size:19px}.overview details{margin-bottom:0}.overview .notice{margin:8px 0;padding:6px 12px}
.metrics{margin:12px 0;gap:10px}.metric{padding:8px 16px;flex:1;min-width:130px}.metric strong{font-size:23px}.tabs{gap:6px;margin:14px 0 0;border-bottom:2px solid #cfdae6}.tabs a{padding:10px 16px;text-decoration:none;border-radius:6px 6px 0 0;font-weight:600}.tabs a[aria-current="page"]{background:#075b9c;color:white}.panel h2{margin:18px 0 4px}.panel>p{margin:4px 0 10px}.toolbar{position:static;padding:10px;margin:12px 0;gap:8px}.toolbar input{min-width:150px}.toolbar select{max-width:260px}#visible{width:100%;font-size:12px;color:#596d80}.pager{margin:8px 0}.empty{padding:25px;background:white;border:1px dashed #aabccb}
table.searchable{table-layout:fixed;min-width:0!important}table.searchable>thead th:first-child{width:24%}table.searchable>thead th:last-child{width:26%}table.searchable>tbody>tr>td{min-width:0;max-width:none}#inventory-table>thead th:first-child{width:24%}#review-table>thead th:nth-child(1){width:23%}#review-table>thead th:nth-child(2){width:21%}#review-table>thead th:nth-child(3){width:31%}#review-table>thead th:nth-child(4){width:25%}
.item-name{font:600 16px/1.5 Consolas,monospace}.location{display:block;color:#596d80;font-size:12px;margin:5px 0}.signal{margin:4px 0}.signal-list{padding-left:18px;margin:6px 0}.priority-HIGH,.priority-CRITICAL{background:#fff0d0;color:#785218}.step{margin:8px 0 0}.tag{font-size:12px}.evidence{margin-top:9px}.evidence[open]{padding:10px;background:#f6f9fc;border:1px solid #d6e0eb}.evidence .table-scroll{max-width:100%}.evidence table{min-width:760px}.evidence>summary{font-weight:600}.context-count{font-weight:600}.legend{padding:8px 0;color:#46546b}button:focus-visible,a:focus-visible,summary:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid #3180d8;outline-offset:2px}.copy-note{font-size:12px;display:block;margin-top:4px}tr:target{scroll-margin-top:12px}pre{tab-size:4}footer details{max-width:100%}
@media(min-width:801px){table.searchable,table.searchable>thead,table.searchable>tbody{display:block}table.searchable>thead>tr,table.searchable>tbody>tr{display:grid;grid-template-columns:24% 50% 26%}#inventory-table>thead>tr,#inventory-table>tbody>tr{grid-template-columns:24% 25% 25% 26%}#review-table>thead>tr,#review-table>tbody>tr{grid-template-columns:23% 21% 31% 25%}table.searchable>thead th{width:auto!important;min-width:0}table.searchable>tbody>tr>td{min-width:0;width:auto}table.searchable>tbody>tr>td:has(>.evidence[open]){grid-column:1/-1;order:1}#risk-table>tbody>tr:has(.evidence[open])>td:last-child,#gap-table>tbody>tr:has(.evidence[open])>td:last-child{grid-column:2/-1}.next-actions{padding:8px 12px}}
@media(max-width:800px){header{padding:16px}main{padding:12px}.overview{padding:12px}.metrics{gap:6px}.metric{min-width:110px;padding:8px}.tabs{gap:0}.tabs a{padding:8px 10px;font-size:13px}.toolbar{align-items:stretch}.toolbar input{width:75%}.toolbar select{max-width:100%}table.searchable,table.searchable>tbody,table.searchable>tbody>tr,table.searchable>tbody>tr>td{display:block;width:100%}table.searchable>thead{display:none}table.searchable>tbody>tr{margin-bottom:12px;border:1px solid #c5d3e0;border-radius:6px;overflow:hidden}table.searchable>tbody>tr>td{border:0;border-bottom:1px solid #e4ebf3;padding:10px 12px}table.searchable>tbody>tr>td::before{content:attr(data-label);display:block;font-size:12px;color:#596d80;font-weight:600;margin-bottom:5px}.table-scroll{margin:8px 0}.panel h2{font-size:19px}dl{grid-template-columns:1fr}}
.print-context{display:none}header button{padding:3px 9px;background:transparent;color:inherit;border-color:#7895ad}.scenario{padding:8px 10px;background:#fff8e8;border-left:3px solid #bc8629}.scenario li{margin:8px 0}.scenario p{font-size:13px}
@media print{.toolbar,.pager,.tabs,button{display:none!important}body{background:white}.table-scroll{overflow:visible}header{background:white;color:black}.print-context{display:block;border:1px solid #aaa;padding:8px}.panel{break-before:auto}.table-scroll>table{min-width:0!important}a{color:inherit}}
.risk-overview{background:white;border:1px solid #d6e0eb;border-radius:8px;overflow:hidden;margin-bottom:14px}.verdict-head{padding:14px 20px;border-left:6px solid currentColor}.verdict-head>span{font-size:13px;font-weight:600}.verdict-head h2{font-size:29px;line-height:1.25;margin:3px 0 7px}.verdict-head p{margin:0;color:#34465c}.verdict-cards{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;padding:12px 18px 0}.verdict-card{border-radius:6px;padding:9px 14px;text-decoration:none;border:1px solid transparent}.verdict-card:hover{border-color:currentColor}.verdict-card strong{display:block;font-size:25px;line-height:1.3}.verdict-card span{font-weight:600}.risk-overview>.scope-line,.risk-overview>.muted{margin:8px 18px;font-size:12px}.scope-check{padding:8px 18px;border-top:1px solid #d6e0eb;margin:8px 0 0}.decision{display:inline-block;border-radius:4px;padding:5px 9px;margin:0 0 8px;font-weight:700;font-size:15px;border-left:4px solid currentColor}.source-previews{display:flex;gap:8px;margin:8px 0}.source-preview{flex:1;min-width:0;padding:7px 9px;background:#f1f5fa;border-radius:4px;font-size:12px}.source-preview .location{margin:2px 0}.source-preview pre{font-size:12px}.source-preview strong{color:#234666}.review-brief{margin:5px 0}.source-previews:empty{display:none}
@media(max-width:800px){.verdict-head{padding:12px}.verdict-head h2{font-size:23px}.verdict-cards{grid-template-columns:repeat(2,1fr);gap:7px;padding:10px}.verdict-card{padding:8px 10px}.risk-overview>.scope-line,.risk-overview>.muted{margin:8px 12px}.scope-check{padding:8px 12px}.source-previews{flex-direction:column}.decision{font-size:16px}}
/* The review is a reading view, not a multi-column evidence spreadsheet. */
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
document.addEventListener('toggle',e=>{if(e.target.tagName!=='DETAILS'||!e.target.open)return;for(const p of e.target.querySelectorAll('pre')){if(p.dataset.formatted)continue;p.dataset.formatted='1';const text=p.textContent.trim();if(text.startsWith('{')||text.startsWith('[')){try{p.textContent=JSON.stringify(JSON.parse(text),null,2);}catch{}}}},true);
const q=document.getElementById('q'), filter=document.getElementById('filter'), fileFilter=document.getElementById('file-filter');
const panels=[...document.querySelectorAll('.panel')], tabs=[...document.querySelectorAll('.tabs a')];
let active=document.getElementById('inventory')||panels[0];
const rows=[...document.querySelectorAll('table.searchable > tbody > tr[data-group]')];
const searchText=new Map(rows.map(r=>[r,(r.querySelector('.story-current')||r).textContent.toLowerCase()]));
const pageSize=document.getElementById('page-size'), views=[...document.querySelectorAll('.pager')].map(p=>({pager:p,page:0,rows:rows.filter(r=>r.closest('table').id===p.dataset.table),matches:[]}));
for(const v of views){const t=document.getElementById(v.pager.dataset.table),labels=[...t.tHead.rows[0].cells].map(c=>c.textContent);for(const r of v.rows)[...r.cells].forEach((c,i)=>c.dataset.label=labels[i]);}
function matchesFilter(r){const [kind,value]=filter.value.split(':');return filter.value==='all'||(value?r.dataset[kind]===value:r.dataset.group===filter.value);}
function search(reset=true){let n=0,shown=0;const size=Number(pageSize.value);for(const v of views){if(reset)v.page=0;v.matches=v.rows.filter(r=>searchText.get(r).includes(q.value.trim().toLowerCase())&&matchesFilter(r)&&(fileFilter.value==='all'||JSON.parse(r.dataset.files||JSON.stringify([r.dataset.file])).includes(fileFilter.value)));const count=Math.max(1,Math.ceil(v.matches.length/size));v.page=Math.max(0,Math.min(v.page,count-1));const visible=new Set(v.matches.slice(v.page*size,(v.page+1)*size));for(const r of v.rows)r.hidden=!visible.has(r);if(v.pager.closest('.panel')===active){n+=v.matches.length;shown+=visible.size;}v.pager.querySelector('span').textContent=v.matches.length+' 条 · 第 '+(v.page+1)+' / '+count+' 页';v.pager.nextElementSibling.hidden=!!v.matches.length;v.pager.querySelector('[data-step="-1"]').disabled=v.page===0;v.pager.querySelector('[data-step="1"]').disabled=v.page+1>=count;}document.getElementById('visible').textContent=(document.querySelector('.review-reading')?'搜索当前有效解释与引用（不含历史回答）：':'仅搜索当前栏目（含折叠证据）：')+n+' 条匹配，当前展示 '+shown+' 条';}
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
    return '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="icon" href="data:,"><title>' + esc(title) + '</title><style>' + STYLE + '</style></head><body' + (' class="reading-page"' if reading else '') + '><header><h1>' + esc(title) + '</h1><p>' + esc(meta) + '</p><nav><a href="index.html">静态排查</a><a href="' + REVIEW_PAGE + '">逐项复核结果</a><button type="button" id="print-view">打印 / 保存当前筛选结果</button></nav></header><main><p class="print-context"></p><noscript>启用 JavaScript 可使用搜索、栏目切换和分页；下面仍保留全部文字证据。</noscript>' + content + '<footer>' + raw({'源码指纹': report.get('fingerprint'), '工具版本': report.get('tool_version'), '工程版本': report.get('git_commit'), '静态状态': report.get('analysis_status'), '本轮状态': report.get('run_status')}, '报告版本与原始状态') + '</footer></main><script>' + SCRIPT + script + '</script></body></html>'


def metrics(values):
    return '<div class="metrics">' + "".join(f'<div class="metric"><strong>{esc(n)}</strong>{esc(label)}</div>' for label, n in values) + '</div>'


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
    counts = Counter(assessments.values())
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
    cards = ''.join(f'<a class="verdict-card {key}" href="#{"inventory" if key == "screened_safe" else "risks"}" data-decision-filter="{key}"><strong>{counts[key]}</strong><span>{esc(DECISIONS[key][0])}</span></a>'
                    for key in ['confirmed', 'likely', 'unresolved', 'safe', 'screened_safe'])
    cov = report['coverage']
    gap_count = sum(not f.get('symbol_id') for f in report['findings'])
    inventory_by_kind = cov.get('inventory_by_kind', {})
    mode = '模型复核未启用；当前分类依据静态证据。' if records and all(local_pending(r) for r in records.values()) else '分类结合静态证据与有效复核；失败或过期回答不算当前结论。'
    kind_line = ' · '.join(f'{KINDS.get(k, k)} {n}' for k, n in sorted(inventory_by_kind.items())) or '无变量'
    return ('<section class="risk-overview"><div class="verdict-head ' + color + '"><span>并发风险结论</span><h2 id="risk-verdict">'
            + esc(state) + '</h2><p>' + esc(explanation) + '</p></div><div class="verdict-cards">' + cards + '</div>'
            + '<p class="scope-line">以上按变量去重统计。共 ' + str(len(facts['variables'])) + ' 个变量（' + esc(kind_line) + '）；另有 '
            + f'<a href="#inventory" data-decision-filter="screened_safe">{counts["screened_safe"]} 个已排查不存在并发风险</a>、'
            + f'<a href="#inventory" data-decision-filter="inventory">{counts["inventory"]} 个未发现静态线索</a>（不等于安全）'
            + (f'、<a href="#inventory" data-decision-filter="supplemental">{counts["supplemental"]} 个补充解析</a>' if counts.get('supplemental') else '')
            + f'。<a href="#gaps">{gap_count} 项覆盖 / 依赖缺口</a>单独保留，不计入风险变量。</p>'
            + '<p class="muted">' + esc(mode) + ' 源码解析 ' + esc(f'{cov.get("translation_units_parsed", "?")}/{cov.get("translation_units_total", "?")}')
            + '；解析失败 ' + str(cov.get('translation_units_failed', 0)) + '。'
            + ('<strong>请先修复解析失败；当前结果可能遗漏风险。</strong>' if cov.get('translation_units_failed') else '') + '</p>'
            + '<details class="scope-check"><summary>过滤结果与排查范围：已排除 ' + str(cov.get('audit_scope', {}).get('variables_omitted', 0))
            + ' 个变量；查看具体配置</summary>' + scope_summary(cov) + next_actions(report, records.values()) + '</details></section>')


def write_html(out, facts, report, reviews):
    from .scope import validate_selection
    validate_selection(facts, report)
    funcs = {f['function_id']: f for f in facts['functions']}
    variables = {v['symbol_id']: v for v in facts['variables']}
    contexts = {c['id']: c for c in facts['contexts']}
    records = {r['finding_id']: r for r in review_records(report, reviews)}
    assessments = variable_decisions(facts, report, records)
    candidates = defaultdict(list)
    for finding in report['findings']:
        if finding.get('symbol_id'):
            candidates[finding['symbol_id']].append(finding)

    def function(fid):
        f = funcs.get(fid)
        return f"{f['name']} ({loc(f)})" if f else fid

    def context(cid):
        c = contexts.get(cid, {})
        target = c.get('registration', {}).get('function_id') or c.get('function_id')
        kind = c.get('kind', 'UNKNOWN')
        if kind == 'DMA':
            return {'tx': 'DMA 发送（硬件读取）', 'rx': 'DMA 接收（硬件写入）'}.get(c.get('direction'), 'DMA 硬件') + f' · {cid}'
        name = ', '.join(c.get('functions', [])) or funcs.get(target, {}).get('name')
        if not name:
            name = cid.split(':')[1] if cid.startswith('auto:') else cid
        return {'MAIN': '主循环', 'ISR': '中断', 'TASK': '任务', 'UNKNOWN': '未知入口'}.get(kind, kind) + ' ' + name

    def context_list(ids):
        return '<br>'.join(esc(context(cid)) for cid in ids) or '无已知上下文'

    def context_brief(ids, label):
        ids = list(ids)
        return '<p class="signal"><span class="context-count">' + esc(label) + f'：{len(ids)} 个已知入口</span></p>' + (
            '<details><summary>查看入口名称</summary>' + context_list(ids) + '</details>' if ids else '')

    def accesses(items):
        rows = []
        for a in items:
            chains = ''.join('<details><summary>' + esc(context(cid)) + ' → 调用链</summary><pre>'
                             + esc(' → '.join(function(fid) for fid in path)) + '</pre></details>'
                             for cid, path in a.get('call_chains', {}).items())
            rows.append(row([esc(KINDS.get(a['access_kind'], a['access_kind'])), esc(loc(a)) + '<pre>' + esc(a.get('source_text', '')) + '</pre>',
                             esc(function(a['function_id'])), chains or '<strong>UNKNOWN-CONTEXT：尚不能确定任务或中断</strong>',
                             raw({k: v for k, v in a.items() if k not in {'source_text', 'call_chains'}}, '字段 / 别名 / 宏 / 保护事件等')]))
        return table(['访问方式', '源码位置与表达式', '访问函数', '上下文 → 最短证据调用链', '访问属性'], rows)

    inventory_rows = []
    for v in facts['variables']:
        sid = v['symbol_id']
        links = '<br>'.join(f'<a href="#{anchor("risk-", f["finding_id"])}">查看候选原因 · {esc(PRIORITIES.get(f["risk_level"], f["risk_level"]))}</a>' for f in candidates[sid])
        sites = v.get('declarations', [])
        primary = dict(file=v.get('definition_file'), line=v.get('definition_line')) if v.get('definition_file') else next(iter(sites), {})
        files = sorted({d['file'] for d in sites if d.get('file')} | ({primary['file']} if primary.get('file') else set()))
        is_supplemental = v.get('coverage_source') in ('supplemental', 'inactive_branch')
        detail = '<details class="evidence"><summary>变量属性、全部访问与调用链</summary>'
        detail += '<p>类型：' + esc(v.get('type')) + ' · 大小：' + esc(v.get('size_bytes')) + ' 字节 · volatile：' + ('是' if v.get('is_volatile') else '否') + ' · const：' + ('是' if v.get('is_const') else '否') + '</p>'
        if is_supplemental:
            detail += '<p class="notice">补充声明盘点：来自未编译文件或条件分支变体，不代表当前构建中已分析其并发访问。</p>'
        detail += '<h3>全部读写访问（' + str(len(v.get('accesses', []))) + ' 处）</h3>'
        detail += accesses(v.get('accesses', []))
        detail += '<details class="graph" data-symbol="' + esc(sid) + '"><summary>展开所有相关调用边（含多路径、递归及边的来源）</summary><pre></pre></details>'
        detail += '<details><summary>完整变量属性、唯一 ID 与编译单元</summary>' + fields({k: value for k, value in v.items() if k not in {'accesses', 'readers', 'writers', 'contexts'}}) + '</details></details>'
        group = 'supplemental' if is_supplemental else ('candidate' if candidates[sid] else 'inventory')
        status_text = DECISIONS[assessments[sid]][1]
        if assessments[sid] == 'screened_safe':
            status_text = {'ONLY_READS': '当前构建只有读取，没有运行期写入。',
                           'SINGLE_ACCESS_SITE': '唯一访问点仅属于一个不可重入执行上下文。',
                           'SINGLE_EXECUTION_CONTEXT': '全部读写属于同一个不可重入执行上下文。'}.get(v.get('screening_reason'), status_text)
        if v.get('screening_blockers'):
            status_text += ' 安全判定受阻：' + '、'.join(v['screening_blockers']) + '。'
        if v.get('parse_status') == 'FAILED':
            status_text = '解析不完整：只保留已恢复声明，可能仍有漏项，不能判定安全。'
        inventory_rows.append(row(['<span class="item-name">' + esc(v['qualified_name']) + '</span><span class="location">'
            + esc(f"{primary.get('file') or '缺少位置'}:{primary.get('line') or '?'}") + '</span>'
            + esc(KINDS.get(v['kind'], v['kind'])) + ' · ' + esc(v.get('type')),
            context_brief(v.get('readers', []), '读') + context_brief(v.get('writers', []), '写'),
            decision_tag(assessments[sid]) + '<p>' + esc(status_text) + '</p>' + (links if not is_supplemental else ''),
            detail],
            anchor('var-', sid), group, file=primary.get('file'), decision=assessments[sid], files=files))

    risks, gaps = [], []
    ordering = {'confirmed': 0, 'likely': 1, 'unresolved': 2, 'safe': 3}
    for f in sorted(report['findings'], key=lambda f: (ordering[decision(f, records[f['finding_id']])],
                    {'CRITICAL': 0, 'HIGH': 1, 'MEDIUM': 2, 'LOW': 3}.get(f['risk_level'], 4),
                    -len(set(f.get('rules', [])) & CONCURRENT_SIGNALS), f['variable_name'], f['finding_id'])):
        sid = f.get('symbol_id')
        ident = anchor('risk-', f['finding_id'])
        r = records[f['finding_id']]
        pairs = '<br>'.join(esc(' ↔ '.join(context(c) for c in pair)) for pair in f.get('context_pairs', []))
        summary = rule_summary(f)
        detail = '<details class="evidence"><summary>展开排查证据与处理步骤</summary><p><strong>静态规则线索；需核对实际交错与保护条件。</strong></p><ol>'
        detail += ''.join('<li>' + esc(title) + '：' + esc(action) + ' <code>' + esc(code) + '</code></li>' for code, title, action in summary)
        detail += '</ol><details><summary>读写明细与调用链（' + str(len(f.get('accesses', []))) + ' 处访问）</summary>' + accesses(f.get('accesses', [])) + '</details>'
        detail += '<details><summary>风险依据、并发关系与保护证据</summary><p>' + (pairs or '尚无已知并发入口对；见未知路径或重入证据。') + '</p>' + fields({
            '规则': f['rules'], '原因': f.get('concurrency_reason', '覆盖盲区，需要补充证据'),
            '保护状态': f.get('protection_status'), '保护说明': f.get('protection_note'),
            '已声明保护': f.get('declared_protection', []), '快照读回写': f.get('snapshots', []),
            '已配置抢占': f.get('configured_preemption', []), '已配置并发': f.get('configured_concurrency', []),
            '未知项': f.get('uncertainties', [])}) + '</details>' + raw(f)
        note = '\n'.join([f"变量 / 项目：{f['variable_name']}", f"定义：{loc(f['definition'])}",
                          f"候选 ID：{f['finding_id']}", '静态线索：' + '；'.join(t for _, t, _ in summary),
                          '复核状态：' + review_label(r), '源码指纹：' + str(report.get('fingerprint', '未知')),
                          '人工核对结论：', '实际交错 / 保护条件：', '修复与验证：'])
        detail += '<button type="button" data-copy="' + esc(note) + '">复制排查记录模板</button><span class="copy-note" role="status"></span></details>'
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
            actors += f'<details><summary>全部入口：读 {len(readers)} / 写 {len(writers)}</summary><strong>读取</strong><br>' + context_list(readers) + '<br><strong>写入</strong><br>' + context_list(writers) + '</details>'
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
        assessment = decision(f, r)
        if r.get('state') == 'DONE' and r.get('answer', {}).get('reason'):
            titles = '<p class="review-brief">' + esc(r['answer']['reason'][:240]) + '</p>' + titles
        state = f'<span class="tag {category(r)}">{esc(review_label(r))}</span>'
        cells = [(decision_tag(assessment) + '<br>' if sid else '') + name + '<span class="location">' + esc(loc(f['definition'])) + '</span>'
                 + '<span class="tag priority-' + esc(f['risk_level']) + '">' + esc(PRIORITIES.get(f['risk_level'], f['risk_level'])) + '</span>' + actors,
                 titles + '<div class="source-previews">' + ''.join(previews) + '</div>' + scenario_html + detail,
                 '<p class="step">' + esc(summary[0][2] if summary else '查看证据，补充未知信息。') + '</p>'
                 + f'<a href="{REVIEW_PAGE}#{anchor("review-", f["finding_id"])}">{state}</a>']
        (risks if sid else gaps).append(row(cells, ident, 'candidate' if sid else 'gap',
            f['risk_level'], f['definition'].get('file'), 'dependency' if dependency else 'target', assessment))

    cov = report['coverage']
    coverage = scope_summary(cov)
    inventory_by_kind = cov.get('inventory_by_kind', {})
    if inventory_by_kind:
        coverage += '<h3>变量盘点分类</h3>' + table(['变量类别', '数量'], [row([esc(KINDS.get(k, k)), str(n)]) for k, n in sorted(inventory_by_kind.items())])
    coverage += metrics([('源码解析成功 / 总数', f'{cov.get("translation_units_parsed", "?")} / {cov.get("translation_units_total", "?")}'),
                         ('解析失败', cov.get('translation_units_failed', 0)),
                         ('入口已知的目标函数 / 总数', f'{cov.get("functions_with_context", "?")} / {cov.get("functions_total", "?")}'),
                         ('未知入口访问', cov.get('unknown_accesses', 0)),
                         ('补充解析变量', cov.get('supplemental_variables', 0))])
    problems = [row(['未进入编译数据库的源码', esc(p)]) for p in cov.get('unlisted_sources', [])]
    problems += [row(['未纳入的头文件', esc(p)]) for p in cov.get('unlisted_headers', [])]
    problems += [row(['解析失败', esc(u.get('source_file')) + raw(u.get('diagnostics', []), '查看失败原因')])
                 for u in facts.get('translation_units', []) if u.get('parse_status') not in {None, 'PARSED'}]
    coverage += '<h3>先处理这些覆盖问题</h3>' + (table(['问题', '文件 / 原因'], problems) if problems else '<p>没有发现解析失败或未纳入的目标源码 / 头文件。仍需核对未知入口与下面的分析限制。</p>')
    file_cov = cov.get('file_coverage', [])
    if file_cov:
        coverage += '<h3>每个排查文件的变量数与解析状态</h3>' + table(['文件', '变量数', '解析状态', '来源'], [
            row([esc(fc['file']), str(fc['variable_count']), esc(fc['parse_status']), esc(fc.get('coverage_source', '')) + raw(dict(diagnostics=fc.get('diagnostics', []), gaps=fc.get('gaps', [])), '覆盖诊断')])
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
    coverage += '<h2>任务、中断与硬件上下文</h2>' + table(['上下文', '入口、优先级、注册与发现依据'],
        [row([esc(context(c['id'])), raw(c)]) for c in facts['contexts']])
    counts = Counter(category(r) for r in records.values())
    content = risk_overview(facts, report, records, assessments)
    content += '<nav class="tabs" aria-label="排查栏目">' + ''.join(f'<a href="#{key}">{label} {number}</a>' for key, label, number in [
        ('risks', '变量风险结论', len(risks)), ('inventory', '全部目标变量', len(inventory_rows)), ('gaps', '覆盖 / 依赖证据', len(gaps)), ('coverage', '过滤与覆盖校验', '')]) + '</nav><!--controls-->'
    decision_options = [('decision:' + key, value[0]) for key, value in DECISIONS.items()]
    priority_options = [('all', '全部结论')] + decision_options[:-1] + [('level:' + k, v) for k, v in PRIORITIES.items()]
    content += panel('risks', '变量风险结论与关键证据',
        '先看左侧结论，再看读写语句和下一步。确认风险在前，疑似风险其次；证据不足单独标识。',
        table(['风险结论 / 目标变量', '关键依据：哪里读写、为什么可疑', '下一步处理'], risks, 'risk-table', True), priority_options)
    content += panel('inventory', '全部全局 / static 变量清单', '同名变量请按定义位置、编译单元和详情内唯一 ID 区分。清单覆盖全局变量、文件 static、函数 static（含头文件实例和 C++ 静态成员）及补充声明；未筛出候选不等于已经证明安全。',
        table(['变量 / 定义 / 类型', '谁在读写', '静态筛选状态', '完整证据'], inventory_rows, 'inventory-table', True),
        [('all', '全部变量'), ('candidate', '有静态候选'), ('inventory', '未筛出候选'), ('supplemental', '补充解析')] + decision_options)
    content += panel('gaps', '待补证据：影响判断的覆盖缺口',
        '这些记录不是已确认的变量风险。标有“依赖证据”的第三方路径与目标变量有关，补证据后才能缩小不确定性。',
        table(['缺口与位置', '缺少什么证据', '如何补充 / 复核状态'], gaps, 'gap-table', True),
        [('all', '全部缺口'), ('scope:target', '目标范围 / 全局缺口'), ('scope:dependency', '相关依赖证据')])
    content += panel('coverage', '覆盖范围与分析限制',
        '这里只覆盖本次构建实际解析到的代码；条件编译关闭的代码需使用对应构建变体另行扫描。', coverage, [])
    content += '<details class="legend"><summary>新手术语：读、写、读改写、上下文和证据缺口</summary><p>上下文是代码从哪个主循环、中断或硬件入口执行。读（READ）读取值；写（WRITE）更新值；读改写（RMW）先读再计算再写回；取地址（ADDRESS_TAKEN）本身不代表读写。证据缺口表示工具还无法确定某段行为。volatile、static 或出现锁 API 都不能单独证明并发安全。</p></details>'

    # Preserve every relevant edge without enumerating infinitely many recursive
    # paths. The reverse traversal is lazy and includes alternate call sites.
    graph = dict(functions={fid: function(fid) for fid in funcs},
                 calls=[{k: c.get(k) for k in ('caller_function_id', 'callee_function_id', 'callee_name', 'call_kind', 'file', 'line')} for c in facts['calls']],
                 accesses={v['symbol_id']: sorted({a['function_id'] for a in v.get('accesses', [])}) for v in facts['variables']})
    data = json.dumps(graph, ensure_ascii=False).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    graph_script = """
const graph=JSON.parse(document.getElementById('call-graph').textContent), incoming=new Map();
for(const edge of graph.calls){const k=edge.callee_function_id;if(!incoming.has(k))incoming.set(k,[]);incoming.get(k).push(edge);}
for(const d of document.querySelectorAll('details.graph'))d.addEventListener('toggle',()=>{if(!d.open||d.dataset.loaded)return;d.dataset.loaded='1';let seen=new Set(), edges=[], todo=[...(graph.accesses[d.dataset.symbol]||[])];while(todo.length){let f=todo.pop();if(seen.has(f))continue;seen.add(f);for(const e of incoming.get(f)||[]){edges.push(e);todo.push(e.caller_function_id);}}d.querySelector('pre').textContent=edges.map(e=>(graph.functions[e.caller_function_id]||e.caller_function_id)+' → '+(graph.functions[e.callee_function_id]||e.callee_name)+' ['+e.call_kind+'] @ '+e.file+':'+e.line).join('\\n')||'没有已解析调用边；入口直接访问或上下文未知。';});
"""
    content += '<script type="application/json" id="call-graph">' + data + '</script>'
    inventory_page = page('并发变量排查报告', content, report, priority_options, graph_script)

    counts = Counter(category(r) for r in records.values())
    review_rows = defaultdict(list)
    review_jumps = defaultdict(list)
    review_priority = {'confirmed': 0, 'likely': 1, 'unresolved': 2, 'safe': 3}
    ordered_findings = sorted(report['findings'], key=lambda f: review_priority[category(records[f['finding_id']])] if f.get('symbol_id') else 4)
    for f in ordered_findings:
        r = records[f['finding_id']]
        # Failed/stale receipts may contain an old answer. Preserve it only in
        # the raw record, never as the current explanation or source evidence.
        answer = r.get('answer', {}) if r['state'] == 'DONE' else {}
        group = category(r)
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
        explanation = story_explanation(answer, group, bool(f.get('symbol_id')))
        if r['state'] in {'STALE', 'FAILED'} and r.get('answer'):
            explanation += '<p>旧回答已失效，仅在原始记录中保留，不作为本轮结论或证据。</p>'
        error = '<details><summary>复核未完成的原因</summary><p>' + esc(r['error']) + '</p></details>' if r.get('error') and not local_pending(r) else ''
        execution = r.get('execution', {})
        if execution.get('stdout_file'):
            error += '<p><a href="review/' + esc(execution['stdout_file']) + '">原始 OpenCode 执行日志</a></p>'
            error += '<details><summary>执行时间、日志 SHA-256 与校验范围</summary>' + fields(execution) + '</details>'
        if r.get('previous_reviews'):
            error += '<p>已做反证复核；保留 ' + str(len(r['previous_reviews'])) + ' 次先前回答，当前状态：' + esc(r['status']) + '。</p>'
            for attempt, previous in enumerate(r['previous_reviews'], 1):
                error += '<details><summary>第 ' + str(attempt) + ' 轮历史回答（不作为当前结论）</summary>' + raw(previous)
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
                   + f'<span class="tag {group}">{esc(status)}</span></div>' + explanation + citations + '</div>')
        audit = ('<details class="story-audit"><summary>原始证据、执行日志与历史复核</summary>' + error
                 + f'<p><a href="{source_link}">静态读写与变量身份</a> · <a href="index.html#{anchor("risk-", f["finding_id"])}">候选依据与处理步骤</a></p>'
                 + '<details class="evidence"><summary>有效复核引用的源码（' + str(len(evidence_rows)) + ' 处）</summary>' + source_evidence + '</details>'
                 + '<details><summary>静态读写与上下文调用链</summary>' + accesses(f.get('accesses', [])) + '</details>'
                 + raw(r, '原始复核记录（含失效回答 / 错误信息）') + '</details>')
        review_rows[bucket].append(row(['<article class="review-story ' + group + '">' + current + audit + '</article>'],
            ident, group, file=f['definition'].get('file')))
    review_options = [('all', '全部结论'), ('confirmed', '确认存在风险'), ('likely', '疑似，仍需验证'), ('safe', '条件安全 / 误报'), ('unresolved', '未完成 / 证据不足')]
    conclusion = final_conclusion(report, list(records.values()))
    counts_by_variable = Counter(assessments.values())
    content = '<div class="review-reading"><section class="review-verdict"><h2>最终结论：' + esc(conclusion['label']) + '</h2>'
    content += '<p><strong>' + str(counts_by_variable['confirmed']) + ' 个变量确认有风险</strong> · ' + str(counts_by_variable['safe']) + ' 个变量复核安全 / 误报 · ' + str(counts_by_variable['likely'] + counts_by_variable['unresolved']) + ' 个变量仍需判断。</p>'
    content += '<p class="muted">' + esc(conclusion['scope']) + ' 复核完成 ' + str(conclusion['reviewed']) + '/' + str(conclusion['total']) + ' 项（含独立证据缺口）。</p></section>'
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
    content += '<details class="review-scope"><summary>覆盖范围、复核进度与术语说明</summary>'
    content += '<p>主循环：CPU 正常轮询执行的代码。中断 / ISR：事件触发后，CPU 暂停当前代码并执行处理函数，返回后继续原来的位置。DMA：独立于 CPU 搬运数据的硬件。读改写 / RMW：读出旧值、计算、写回；中间若被另一写入者打断，可能覆盖对方的新值。</p>'
    content += overview(report, records.values(), [('确认项（含缺口）', counts['confirmed']), ('疑似项', counts['likely']), ('安全 / 误报项', counts['safe']), ('尚未完成项', counts['unresolved'])])
    content += raw(cov, '本轮静态覆盖范围') + raw(report['limitations'], '结论适用范围与限制') + '</details></div>'
    review_page = page('并发复核：原因、过程与结论', content, report, review_options, reading=True)
    for name, contents in [('index.html', inventory_page), (REVIEW_PAGE, review_page)]:
        temporary = out / (name + '.tmp')
        temporary.write_text(contents, encoding='utf-8')
        temporary.replace(out / name)


def write_failure(out):
    contents = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>本次扫描失败</title><h1>本次扫描失败，不能使用旧结论</h1><p>请查看 run.json / run.log。已有事实及复核缓存可能来自旧版本，不能作为本次结论。</p></html>'
    for name in ('index.html', REVIEW_PAGE):
        (out / name).write_text(contents, encoding='utf-8')
