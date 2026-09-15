"""Readable, lossless formatting of current review prose; no inferred witnesses."""
import html
import re


def paragraphs(text):
    """Split at sentence/paragraph boundaries, never inside code parentheses."""
    text = str(text or '').strip()
    parts, start, stack = [], 0, []
    pairs = {'(': ')', '（': '）', '[': ']', '{': '}'}
    for i, char in enumerate(text):
        if char in pairs:
            stack.append(pairs[char])
        elif stack and char == stack[-1]:
            stack.pop()
        if not stack and char in '；。\n':
            part = text[start:i + 1].strip()
            if part:
                parts.append(part)
            start = i + 1
    if text[start:].strip():
        parts.append(text[start:].strip())
    return parts


def prose(text):
    return ''.join('<p>' + html.escape(part, quote=True) + '</p>' for part in paragraphs(text))


def process(text, numbered=True):
    """Expose the author's sequence without inventing actors, values or steps.

    Numbered witnesses retain their exact labels and any intervening caveats.
    Unnumbered prose is separated only into paragraphs, not invented time steps.
    In particular arrows may be call chains, not scheduling transitions.
    """
    text = str(text or '').strip()
    if not text:
        return '<p class="notice">本条有效回答没有描述具体过程，不能据此补造抢占步骤。</p>'
    # A priority "（优先级 7）" or expression "(H+1)" is not step 7/1.
    pattern = re.compile(r'[（(][1-9][0-9]?[)）]|(?<![\w.])[1-9][0-9]?[)）]|[①②③④⑤⑥⑦⑧⑨⑩]')
    markers, stack, position = [], [], 0
    pairs = {'(': ')', '（': '）', '[': ']', '{': '}'}
    while numbered and position < len(text):
        match = pattern.match(text, position) if not stack else None
        if match:
            markers.append(match)
            position = match.end()
            continue
        char = text[position]
        if char in pairs:
            stack.append(pairs[char])
        elif stack and char == stack[-1]:
            stack.pop()
        position += 1
    if len(markers) < 2:
        return '<div class="process-prose">' + prose(text) + '</div>'
    result = prose(text[:markers[0].start()]) + '<div class="process-steps">'
    for index, marker in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
        result += ('<div class="process-step"><span class="step-number">'
                   + html.escape(marker.group()) + '</span><div>'
                   + prose(text[marker.end():end]) + '</div></div>')
    return result + '</div>'


def explanation(answer, group, is_variable=True):
    if not answer:
        return '<p class="notice">尚无有效复核结论，也没有已验证的执行过程。请先完成复核，不能当作安全。</p>'
    if not is_variable:
        labels = [('reason', '这处证据说明了什么'), ('interleaving', '调用过程与适用条件'),
                  ('protection', '保护条件'), ('impact', '对判断的影响'), ('fix', '处理建议')]
        return ''.join('<section class="story-section"><h4>' + title + '</h4>' + prose(answer.get(key, '未提供')) + '</section>' for key, title in labels)
    safe = group == 'safe'
    title = '为什么这次不会形成冲突' if safe else ('并发怎样发生' if group == 'confirmed' else '候选过程与尚未确认的条件')
    protection = '安全依赖哪些条件' if safe else ('为什么现有保护没有挡住它' if group == 'confirmed' else '已知保护与待确认的条件')
    impact = '本条结论及影响边界' if safe else ('会造成什么结果' if group == 'confirmed' else '复核描述的影响与不确定性')
    return ('<section class="story-impact"><h4>' + impact + '</h4>' + prose(answer.get('impact', '未提供影响说明')) + '</section>'
            + '<div class="story-columns"><section class="story-process"><h4>' + title + '</h4>'
            + '<p class="story-caption">以下按有效复核原文展开；步骤中的假设、反例和限制一并保留。</p>'
            + process(answer.get('interleaving'), numbered=not safe) + '</section>'
            + '<aside class="story-remedy"><section><h4>' + protection + '</h4>' + prose(answer.get('protection', '未提供保护说明'))
            + '</section><section><h4>' + ('维护时要保留什么' if safe else '应该怎样修复') + '</h4>'
            + prose(answer.get('fix', '未提供修复建议')) + '</section></aside></div>'
            + '<details class="story-reason"><summary>完整判定理由</summary>' + prose(answer.get('reason', '未提供')) + '</details>'
            + '<details class="story-verification"><summary>修复后如何验证（建议步骤，不代表已经实测）</summary>' + prose(answer.get('verification', '未提供')) + '</details>')
