"""The variable review contract: essential structure and local source locations."""
import json
import re
from pathlib import Path


STATUSES = {'CONFIRMED', 'LIKELY', 'REVIEWED_SAFE', 'FALSE_POSITIVE', 'NEED_MORE_CONTEXT'}
EXAMPLE = dict(
    finding_id='原样复制本项 finding_id', status='CONFIRMED',
    summary='独立一句话结论，按本次摘要配置生成',
    reason='完整结论及其源码依据，不受摘要长度限制', interleaving='主要交错过程，或不能形成危险交错的原因',
    protection='保护机制、范围及有效性', impact='源码支持的影响，不编造业务后果',
    evidence=[dict(file='工程相对路径.c', line=1, claim='该位置支持什么事实')],
    fix='修复建议', verification='验证建议，不代表已实测', missing_context=[])
CONTRACT_PROMPT = '''
只输出一个 JSON 对象，结构如下（将示意内容替换为本项分析）：
''' + json.dumps(EXAMPLE, ensure_ascii=False, indent=2) + '''
status 只能为：
CONFIRMED：源码、存储身份和执行关系足以证明实际并发风险；给出源码 evidence。
LIKELY：有较强的现存风险证据，少量关键运行条件未定；missing_context 必须说明具体缺什么。
REVIEWED_SAFE：完整源码和执行关系证明不冲突或完整保护有效；必须有源码 evidence。
FALSE_POSITIVE：静态疑点因不可达、不同存储、互斥上下文或访问不存在而被证伪；必须有源码 evidence。
NEED_MORE_CONTEXT：已检查源码但证据不足以判风险或安全；missing_context 必须列具体缺失事实，禁止猜测。
evidence 是列表，每项 file 为真实工程内文件、line 为有效行号、claim 说明该位置支持什么。
reason 必须非空。其余说明字段可按已有证据简洁描述，无需逐访问/逐组合复述，不限制文字长度。
所有面向用户的自然语言字段必须使用专业、准确的简体中文，包括 summary、reason、interleaving、protection、impact、fix、verification、missing_context 和 evidence.claim。技术标识符、API、宏、IRQn、寄存器、字段名、状态枚举、数值和源码引用必须保持原样；不得输出整段英文分析。
所有五种 status 都是正常语义结论。无法执行或输出故障不能冒充 NEED_MORE_CONTEXT。
仅当 Packet 存在 READ_THEN_WRITEBACK，安全/误报结论还须返回：
"stale_writeback_assessment": {"applicable": true, "blocked": true,
 "reason": "具体解释整个READ→WRITEBACK窗口为何不能被其他writer插入",
 "evidence": [{"file": "工程相对路径.c", "line": 1}]}。
原子load/store、自然对齐、单条store、无撕裂、last-writer-wins、相同setter和单一源码store位置不能作为blocked证明。
风险/证据不足结论无需该字段。已有字段和五种status保持不变。
'''


class StaleWritebackSafetyError(ValueError):
    """A semantic safety claim needs one focused challenge, never FORMAT_FIX."""


class NVICFactConflictError(ValueError):
    """A generic missing-priority claim contradicts recovered source facts."""


def validate_nvic_missing_facts(answer, packet):
    rows = [r for r in (packet or {}).get('nvic_priorities', [])
            if r.get('source_configurations') and r.get('configured_preemption') is not None]
    if not rows:
        return
    for text in answer.get('missing_context', []):
        if not re.search(r'优先级|priority|priorities|分组|grouping', text, re.I):
            continue
        # Runtime validity is genuinely separate from the source assignment.
        if re.search(r'运行|生命周期|窗口|屏蔽|使能|触发|重配置|不可见|runtime|mask|enabl|trigger|window|reconfig|bootloader', text, re.I):
            continue
        mentioned = [r for r in rows if any(name in text for name in r.get('irqn', []) + r.get('vectors', []))]
        relevant = mentioned or rows if len(rows) == len((packet or {}).get('nvic_priorities', [])) else mentioned
        if relevant and re.search(r'缺|未知|未核|未确|无法|待核|missing|unknown|unverified|unresolved|actual.*priority', text, re.I):
            raise NVICFactConflictError('缺失事实与已恢复的 NVIC 源码配置冲突；须引用配置位置并区分数值与运行期有效性：' + text)


def stale_writeback_hints(packet):
    return [h for h in (packet or {}).get('concurrency_hints', [])
            if h.get('kind') == 'READ_THEN_WRITEBACK']


def validate_stale_writeback_safety(answer, packet, root):
    """Only guard safe answers for this one composite operation.

    Source locations and a claimed blocking argument are required, not an
    automated proof of that argument. Reject the known atomic-only shortcut;
    the reviewer still owns the final concurrency judgment.
    """
    if (not isinstance(answer, dict) or answer.get('status') not in {'REVIEWED_SAFE', 'FALSE_POSITIVE'}
            or not stale_writeback_hints(packet)):
        return
    assessment = answer.get('stale_writeback_assessment')
    if not isinstance(assessment, dict) or assessment.get('applicable') is not True or assessment.get('blocked') is not True:
        raise StaleWritebackSafetyError('READ_THEN_WRITEBACK安全结论缺少applicable=true、blocked=true的窗口阻塞证明')
    reason = assessment.get('reason')
    if not isinstance(reason, str) or not reason.strip():
        raise StaleWritebackSafetyError('stale_writeback_assessment.reason必须说明窗口阻塞依据')
    atomic = re.search(r'原子|32\s*位|对齐|撕裂|last[-_ ]writer[-_ ]wins|最后.*写.*生效|'
                       r'(?:同一|相同|同一个).*(?:setter|设置函数|写入函数)|'
                       r'(?:单[一条个]|只有一[个处]|仅一[个处]).*(?:store|赋值|写点|写入位置)|'
                       r'atomic|align|tear|same\s+setter|(?:single|one)\s+(?:(?:source|code)\s+)?(?:store|assignment)',
                       reason, re.I)
    # This is intentionally a narrow shortcut check, not a prose proof engine.
    blocking = re.search(r'PRIMASK|BASEPRI|FAULTMASK|临界区|屏蔽|不可抢占|不能抢占|无法抢占|'
                         r'串行|不可重入|同一.*上下文|优先级|启用前|使能前|不同.*存储|'
                         r'critical\s+section|mask|cannot\s+preempt|non.?reentrant|serial|'
                         r'same\s+(?:physical\s+)?context|priorit|before.*enabl|different\s+storage', reason, re.I)
    if atomic and not blocking:
        raise StaleWritebackSafetyError('原子性/对齐/单store/相同setter/last-writer-wins不能证明stale-writeback窗口被阻塞')
    try:
        validate_source_evidence(assessment.get('evidence'), root, required=True)
    except ValueError as exc:
        raise StaleWritebackSafetyError('stale_writeback_assessment证据无效: ' + str(exc)) from exc


def validate_minimal_answer(answer, finding_id, root, *, require_quotes=False):
    """No prose length, story structure or per-pair reasoning gates.

    Optional quote checking is only for historical receipts; new responses
    need file/line/claim and retain source SHA checks in the execution archive.
    """
    if not isinstance(answer, dict):
        raise ValueError('OpenCode 最终答案必须是 JSON 对象')
    if answer.get('finding_id') != finding_id:
        raise ValueError(f'finding_id 不匹配：必须原样返回 {finding_id}')
    if not isinstance(answer.get('status'), str) or answer['status'] not in STATUSES:
        raise ValueError(f'OpenCode status 不合法；必须使用 {sorted(STATUSES)}')
    if not isinstance(answer.get('reason'), str) or not answer['reason'].strip():
        raise ValueError('reason 必须是非空字符串')
    evidence = answer.get('evidence')
    validate_source_evidence(evidence, root,
        required=answer['status'] in {'CONFIRMED', 'REVIEWED_SAFE', 'FALSE_POSITIVE'}, require_quotes=require_quotes)
    if answer['status'] in {'LIKELY', 'NEED_MORE_CONTEXT'}:
        missing = answer.get('missing_context')
        if (not isinstance(missing, list) or not missing
                or any(not isinstance(s, str) or not s.strip() for s in missing)):
            raise ValueError('missing_context 必须至少说明一个具体缺失条件')
    return answer


def validate_source_evidence(evidence, root, *, required=False, require_quotes=False):
    """Validate local citations for the ordinary and stale-writeback fields."""
    if not isinstance(evidence, list):
        raise ValueError('evidence 必须是列表')
    if required and not evidence:
        raise ValueError('确认风险/安全/误报结论至少需要一处有效源码 evidence')
    root = Path(root).resolve()
    sources = {}
    for item in evidence:
        if (not isinstance(item, dict) or not isinstance(item.get('file'), str)
                or not item['file'].strip() or type(item.get('line')) is not int or item['line'] < 1):
            raise ValueError('无效 evidence：需要 file 和 line >= 1')
        source = (root / item['file']).resolve()
        if not source.is_relative_to(root):
            raise ValueError('证据路径不属于当前工程')
        if not source.is_file():
            raise ValueError(f'证据文件不存在: {item["file"]}')
        if source not in sources:
            sources[source] = source.read_text(encoding='utf-8', errors='replace').splitlines()
        lines = sources[source]
        if item['line'] > len(lines):
            raise ValueError(f'证据行号越界: {item["file"]}:{item["line"]}')
        if require_quotes:
            quote = item.get('quote')
            if not isinstance(quote, str) or not quote.strip():
                raise ValueError('历史证据缺少 quote 原文')
            if quote.strip() not in lines[item['line'] - 1]:
                raise ValueError(f'证据引用原文与源码不符: {item["file"]}:{item["line"]}')
