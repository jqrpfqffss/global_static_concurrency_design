"""Readable, lossless formatting of current review prose; no inferred witnesses."""
import html
import re
from .review_contract import validate_explanation


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


def structured_explanation(answer, citation_link=None):
    """Render OpenCode's fields verbatim; do not derive another review."""
    story = answer['explanation']
    escape = html.escape

    def references(values):
        if not values:
            return ''
        return '<span class="story-refs">源码依据 ' + ' '.join(
            '<a href="' + escape(citation_link(i), quote=True) + '">[' + str(i) + ']</a>' if citation_link else '[' + str(i) + ']'
            for i in values) + '</span>'

    result = '<p class="story-origin">解释来源：OpenCode 原始结构化回答 · 统一协议 v2</p>'
    result += '<section class="story-impact"><h4>一句话结论</h4>' + prose(story['summary']) + '</section>'
    actors = {a['id']: a for a in story['participants']}
    def actor_card(actor):
        return ('<div class="actor-card"><strong>' + escape(actor['label']) + '</strong><p>' + escape(actor['access']) + '</p>'
                + '<span class="tag">' + {'ACTUAL': '真实访问者', 'EXCLUDED': '已排除实际访问', 'UNKNOWN': '是否访问尚未确定'}[actor['eligibility']] + '</span>'
                + '<p class="actor-entry">执行路径：' + escape(actor['entry']) + '</p>' + references(actor['evidence_refs']) + '</div>')
    result += '<section class="story-participants"><h4>谁在访问：OpenCode 核对的执行入口</h4><div class="actor-cards">'
    result += ''.join(actor_card(a) for a in actors.values() if a['eligibility'] != 'EXCLUDED')
    if not any(a['eligibility'] != 'EXCLUDED' for a in actors.values()):
        result += '<p>OpenCode 未列出可证实的实际访问者；排除原因或缺失条件见下方。</p>'
    result += '</div>'
    excluded = [a for a in actors.values() if a['eligibility'] == 'EXCLUDED']
    if excluded:
        result += '<details><summary>OpenCode 已排除的入口（' + str(len(excluded)) + '）</summary><div class="actor-cards">' + ''.join(actor_card(a) for a in excluded) + '</div></details>'
    result += '</section><section class="story-scheduling"><h4>执行关系：为何能够交错，或为何不能交错</h4>' + prose(story['scheduling']) + references(story['evidence_refs']) + '</section>'
    result += '<div class="story-columns"><section class="story-process"><h4>具体执行过程</h4>'
    if not story['scenarios']:
        result += '<p>OpenCode 尚未给出可成立或可排除的完整过程。</p>'
    kinds = {'CONFLICT': '可成立的冲突', 'BLOCKED': '已排除的冲突路径', 'UNRESOLVED': '尚待核实的路径'}
    for scenario in story['scenarios']:
        result += '<section class="model-scenario"><h5>' + escape(scenario['title']) + '</h5><span class="tag">' + kinds[scenario['kind']] + '</span>'
        result += '<p><strong>前提：</strong>' + escape(scenario['precondition']) + '</p><ol class="model-steps">'
        for step in scenario['steps']:
            result += '<li><strong>' + escape(actors[step['actor_id']]['label']) + '</strong>' + prose(step['action'])
            result += '<dl class="step-states"><dt>操作前</dt><dd>' + escape(step['state_before']) + '</dd><dt>操作后</dt><dd>' + escape(step['state_after']) + '</dd></dl>' + references(step['evidence_refs']) + '</li>'
        result += '</ol><div class="scenario-result"><p><strong>正常应得到：</strong>' + escape(scenario['expected']) + '</p><p><strong>此过程的结果：</strong>' + escape(scenario['actual']) + '</p></div></section>'
    result += '</section><aside class="story-remedy"><section><h4>具体原因</h4>' + prose(story['cause']) + references(story['evidence_refs']) + '</section>'
    for key, title in [('protection', '保护范围与成立条件'), ('impact', '影响及证据边界'), ('fix', '处理建议')]:
        result += '<section><h4>' + title + '</h4>' + prose(answer[key]) + '</section>'
    result += '</aside></div>'
    if story['missing_evidence']:
        result += '<section class="notice"><h4>还缺哪些证据</h4><ul>' + ''.join('<li>' + escape(s) + '</li>' for s in story['missing_evidence']) + '</ul></section>'
    result += '<details class="story-reason"><summary>OpenCode 完整判定理由与文字时序</summary>' + prose(answer['reason']) + prose(answer['interleaving']) + '</details>'
    result += '<details class="story-verification"><summary>如何验证（OpenCode 建议，不代表已经实测）</summary>' + prose(answer['verification']) + '</details>'
    if answer.get('investigation'):
        result += '<details class="story-audit"><summary>逐项核对记录（' + str(len(answer['investigation'])) + ' 项）</summary><ul>'
        for item in answer['investigation']:
            result += '<li><code>' + escape(item['id']) + '</code>' + prose(item['assessment']) + references(item['evidence_refs']) + '</li>'
        result += '</ul></details>'
    return result


def review_markdown(answer):
    """Export the same model-authored structure for readers of Markdown."""
    if not validate_explanation(answer):
        return ['来源：旧版 OpenCode 文字回答，尚未按 v2 协议重审。', ''] + [f'- {key}: {value}' for key, value in answer.items()]
    story = answer['explanation']
    actors = {a['id']: a for a in story['participants']}
    result = ['来源：OpenCode 原始结构化回答 · 统一协议 v2', '', '### 一句话结论', '', story['summary'], '', '### 执行入口', '']
    def refs(values):
        return '源码依据：' + '、'.join('[' + str(i) + ']' for i in values)
    for actor in actors.values():
        result += ['- **' + actor['label'] + '**（' + actor['eligibility'] + '）：' + actor['access'],
                   '  - 路径：' + actor['entry'], '  - ' + refs(actor['evidence_refs'])]
    result += ['', '### 执行关系与具体原因', '', story['scheduling'], '', story['cause'], '', refs(story['evidence_refs']), '']
    for scenario in story['scenarios']:
        result += ['### ' + scenario['title'], '', '场景类型：' + scenario['kind'], '', '前提：' + scenario['precondition'], '']
        for i, step in enumerate(scenario['steps'], 1):
            result += [f"{i}. **{actors[step['actor_id']]['label']}**：{step['action']}",
                       '   - 操作前：' + step['state_before'], '   - 操作后：' + step['state_after'],
                       '   - ' + refs(step['evidence_refs'])]
        result += ['', '**正常应得到：**' + scenario['expected'], '', '**此过程的结果：**' + scenario['actual'], '']
    if story['missing_evidence']:
        result += ['### 尚缺证据', ''] + ['- ' + value for value in story['missing_evidence']] + ['']
    for key, label in [('protection', '保护范围'), ('impact', '影响及证据边界'), ('fix', '处理建议'),
                       ('verification', '验证建议（不表示已实测）'), ('reason', '完整判定理由'), ('interleaving', 'OpenCode 文字时序')]:
        result += ['### ' + label, '', answer[key], '']
    result += ['### 源码依据', '']
    for i, evidence in enumerate(answer['evidence'], 1):
        result += [f"{i}. {evidence['file']}:{evidence['line']} — {evidence['claim']}", '',
                   '```c', evidence.get('quote', ''), '```', '']
    if answer.get('investigation'):
        result += ['### 逐项核对记录', '']
        for item in answer['investigation']:
            result += ['- `' + item['id'] + '`：' + item['assessment'] + '（' + refs(item['evidence_refs']) + '）']
    return result


def explanation(answer, group, is_variable=True, citation_link=None):
    if not answer:
        return '<p class="notice">尚无有效复核结论，也没有已验证的执行过程。请先完成复核，不能当作安全。</p>'
    try:
        structured = validate_explanation(answer, expected_type='VARIABLE' if is_variable else 'EVIDENCE_GAP')
    except (ValueError, KeyError, TypeError) as exc:
        return '<p class="notice">OpenCode 结构化解释未通过校验，不能展示为统一格式：' + html.escape(str(exc)) + '</p>'
    if structured:
        return structured_explanation(answer, citation_link)
    legacy = '<p class="story-origin">来源：旧版 OpenCode 文字回答；尚未按 v2 统一协议重审。以下仅对原文排版，不是工具补写的复核。</p>'
    if not is_variable:
        labels = [('reason', '这处证据说明了什么'), ('interleaving', '调用过程与适用条件'),
                  ('protection', '保护条件'), ('impact', '对判断的影响'), ('fix', '处理建议')]
        return legacy + ''.join('<section class="story-section"><h4>' + title + '</h4>' + prose(answer.get(key, '未提供')) + '</section>' for key, title in labels)
    safe = group == 'safe'
    title = '为什么这次不会形成冲突' if safe else ('并发怎样发生' if group == 'confirmed' else '候选过程与尚未确认的条件')
    protection = '安全依赖哪些条件' if safe else ('为什么现有保护没有挡住它' if group == 'confirmed' else '已知保护与待确认的条件')
    impact = '本条结论及影响边界' if safe else ('会造成什么结果' if group == 'confirmed' else '复核描述的影响与不确定性')
    return (legacy + '<section class="story-impact"><h4>' + impact + '</h4>' + prose(answer.get('impact', '未提供影响说明')) + '</section>'
            + '<div class="story-columns"><section class="story-process"><h4>' + title + '</h4>'
            + '<p class="story-caption">以下按有效复核原文展开；步骤中的假设、反例和限制一并保留。</p>'
            + process(answer.get('interleaving'), numbered=not safe) + '</section>'
            + '<aside class="story-remedy"><section><h4>' + protection + '</h4>' + prose(answer.get('protection', '未提供保护说明'))
            + '</section><section><h4>' + ('维护时要保留什么' if safe else '应该怎样修复') + '</h4>'
            + prose(answer.get('fix', '未提供修复建议')) + '</section></aside></div>'
            + '<details class="story-reason"><summary>完整判定理由</summary>' + prose(answer.get('reason', '未提供')) + '</details>'
            + '<details class="story-verification"><summary>修复后如何验证（建议步骤，不代表已经实测）</summary>' + prose(answer.get('verification', '未提供')) + '</details>')
