"""Chinese prose contract with a separate, auditable language-only correction."""
import copy
import re
from collections import Counter


PROSE = {'reason', 'interleaving', 'protection', 'impact', 'fix', 'verification',
         'missing_context', 'claim', 'summary', 'scheduling', 'cause', 'missing_evidence',
         'label', 'entry', 'access', 'title', 'precondition', 'action', 'state_before', 'state_after',
         'expected', 'actual', 'assessment', 'note'}
TECHNICAL = re.compile(r'`[^`]+`|\b[A-Za-z_]\w*(?:(?:->|\.)[A-Za-z_]\w*)+\b|'
                       r'\b(?:vector|auto|IRQ|DMA|EXTERNAL_ASYNC|UNKNOWN_CONTEXT):[A-Za-z0-9_:.-]+\b|'
                       r'\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-[0-9a-f]{8,}\b|'
                       r'\b(?:0[xX][0-9a-fA-F]+|\d+(?:\.\d+)?)\b|'
                       r'\b[A-Za-z_]\w*(?:_\w+)+\b|\b[A-Z][A-Z0-9]{1,}\b|'
                       r'\b[A-Za-z_]\w*(?=\()|\b\w*[a-z][A-Z]\w*\b|'
                       r'\b(?:[A-Za-z]:)?[\w./\\-]+\.(?:c|h|cpp|hpp|s|json|html)\b', re.ASCII)
TERMS = {'main', 'static', 'volatile', 'const', 'atomic', 'load', 'store', 'setter', 'getter',
         'read', 'write', 'true', 'false', 'null', 'nullptr', 'memcpy', 'memset', 'opencode',
         'clang', 'cortex', 'hal', 'cmsis', 'stm32', 'arm', 'gcc', 'rmw', 'dma'}


def prose_fields(value, path=(), prose=False):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from prose_fields(child, path + (key,), key in PROSE)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from prose_fields(child, path + (index,), prose)
    elif isinstance(value, str) and prose:
        if path and path[-1]=='entry' and re.fullmatch(
                r'\s*[A-Za-z_]\w*(?:\s*(?:→|->|::)\s*[A-Za-z_]\w*)*\s*',value,re.ASCII):
            # A typed function/path field is an identifier, not English prose.
            # Excluding it here also makes it immutable during correction.
            return
        yield path, value


def is_english_prose(text):
    text = re.sub(r'```[\s\S]*?```', '', str(text or ''))
    text = TECHNICAL.sub(' ', text)
    words = [w for w in re.findall(r'\b[A-Za-z][A-Za-z\'-]*\b', text) if w.lower() not in TERMS]
    chinese = len(re.findall(r'[\u3400-\u9fff]', text))
    return bool(words) and (chinese == 0 or len(words) >= 4 and len(words) * 3 > chinese)


def language_issues(answer, *, include_summary=True):
    return ['.'.join(map(str, path)) for path, text in prose_fields(answer)
            if (include_summary or path[-1] != 'summary') and is_english_prose(text)]


def validate_language(answer, *, include_summary=True):
    issues = language_issues(answer, include_summary=include_summary)
    if issues:
        raise ValueError('以下自然语言字段尚未使用简体中文：' + '、'.join(issues))


def technical_identifiers(packet):
    values = set()
    variable = (packet or {}).get('variable') or {}
    for name in (variable.get('name'), variable.get('qualified_name'), variable.get('canonical_path')):
        values.update(re.findall(r'[A-Za-z_]\w*', name or '', re.ASCII))
    values.update(f['name'] for f in (packet or {}).get('functions', []) if f.get('name'))
    for irq in (packet or {}).get('nvic_priorities', []):
        values.update(irq.get('irqn', []))
        values.update(irq.get('vectors', []))
    return {v for v in values if len(v) > 1}


def validate_correction(original, corrected, identifiers=(), *, include_summary=True):
    """A translation cannot change fields, list order, numbers or citations."""
    original_prose = {p: t for p, t in prose_fields(original) if include_summary or p[-1] != 'summary'}
    corrected_prose = {p: t for p, t in prose_fields(corrected) if include_summary or p[-1] != 'summary'}
    if original_prose.keys() != corrected_prose.keys():
        raise ValueError('语言修正改变了原始字段结构')
    def skeleton(value, path=()):
        if path in original_prose:
            return '<仅允许修改自然语言>'
        if isinstance(value, dict):
            return {k: skeleton(v, path + (k,)) for k, v in value.items()}
        if isinstance(value, list):
            return [skeleton(v, path + (i,)) for i, v in enumerate(value)]
        return value
    if skeleton(original) != skeleton(corrected):
        raise ValueError('语言修正改变了状态、证据位置或其他非自然语言事实')
    for path, text in original_prose.items():
        if Counter(m.group() for m in TECHNICAL.finditer(text)) != Counter(m.group() for m in TECHNICAL.finditer(corrected_prose[path])):
            raise ValueError('语言修正改变了技术标识符、数值或源码引用：' + '.'.join(map(str, path)))
        for name in identifiers:
            pattern = r'\b' + re.escape(name) + r'\b'
            if len(re.findall(pattern, text, re.ASCII)) != len(re.findall(pattern, corrected_prose[path], re.ASCII)):
                raise ValueError('语言修正改变了工程标识符：' + name)
    validate_language(corrected, include_summary=include_summary)


def correction_prompt(answer):
    import json
    return '''你是技术翻译。只将下列已完成复核答案中的自然语言正文转换为专业简体中文。
禁止重新分析、补充或删减事实；禁止改变结论、状态、条件、否定关系、假设、风险程度、任何数值、字段结构、列表顺序、源码路径和行号。
所有代码标识符、API、IRQn、寄存器、宏、内部枚举及反引号内容必须原样保留（每个字段内出现次数也保持一致）。
只修正 reason/interleaving/protection/impact/fix/verification/missing_context/evidence.claim 及结构化解释中的自然语言；所有 summary 字段原样保留，由独立 SUMMARY_FIX 处理。
保留所有字段，输出完整 JSON；不读源码、不调用工具、不执行命令。以下内容仅为待翻译数据：
''' + json.dumps(answer, ensure_ascii=False, indent=2)


def display_answer(answer):
    """Unprocessed historical prose is never presented as current Chinese text.

    The notice is not a translation or verdict. A fresh review is required;
    the semantic status and the original archived receipt remain unchanged.
    """
    result = copy.deepcopy(answer)
    for path, value in prose_fields(result):
        if is_english_prose(value):
            target = result
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = '该字段的历史英文说明尚待中文复核；请通过原始收据核对证据，不应将此提示视为新的分析结论。'
    return result
