"""The variable review contract: essential structure and local source locations."""
import json
from pathlib import Path


STATUSES = {'CONFIRMED', 'LIKELY', 'REVIEWED_SAFE', 'FALSE_POSITIVE', 'NEED_MORE_CONTEXT'}
EXAMPLE = dict(
    finding_id='原样复制本项 finding_id', status='CONFIRMED',
    reason='结论及其源码依据', interleaving='主要交错过程，或不能形成危险交错的原因',
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
所有五种 status 都是正常语义结论。无法执行或输出故障不能冒充 NEED_MORE_CONTEXT。
'''


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
    if not isinstance(evidence, list):
        raise ValueError('evidence 必须是列表')
    if answer['status'] in {'CONFIRMED', 'REVIEWED_SAFE', 'FALSE_POSITIVE'} and not evidence:
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
    if answer['status'] in {'LIKELY', 'NEED_MORE_CONTEXT'}:
        missing = answer.get('missing_context')
        if (not isinstance(missing, list) or not missing
                or any(not isinstance(s, str) or not s.strip() for s in missing)):
            raise ValueError('missing_context 必须至少说明一个具体缺失条件')
    return answer
