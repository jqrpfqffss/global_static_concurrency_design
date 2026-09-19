"""Project-independent OpenCode output contract, shared by both review passes.

Validation checks structure and references, never supplies missing reasoning.
"""
import json


SCHEMA_VERSION = 2
EXAMPLE = {
    'schema_version': SCHEMA_VERSION,
    'review_type': 'VARIABLE 或 EVIDENCE_GAP（与本项是否有 symbol_id 一致）',
    'explanation': {
        'summary': '180字内，先说有问题/无问题/证据不足，再用一句白话说明原因及结果',
        'cause': '本对象为什么会出问题，或为什么该疑点不成立；不要只说存在并发',
        'scheduling': '谁能够在什么条件下打断谁，或硬件怎样同时运行；安全项说明谁不能打断谁',
        'evidence_refs': [1],
        'participants': [
            {'id': 'A', 'label': '主循环/某个中断/任务/硬件的易读名称',
             'eligibility': 'ACTUAL 或 EXCLUDED 或 UNKNOWN（真实访问者/已排除/尚不确定）',
             'entry': '真实入口和到访问函数的调用路径', 'access': '它读写本对象的哪些数据', 'evidence_refs': [1]}
        ],
        'scenarios': [
            {'title': '一个具体场景，其他场景单独列出', 'kind': 'CONFLICT 或 BLOCKED 或 UNRESOLVED',
             'precondition': '发生此场景必须满足的当前源码条件；示例初值须明确是假设',
             'steps': [
                 {'actor_id': 'A', 'action': '这一方此刻做了什么，暂停/抢占/恢复发生在哪里',
                  'state_before': '操作前共享值及必要的局部旧副本；未知就明确写未知',
                  'state_after': '操作后共享值及必要的局部副本，未改变也要说明', 'evidence_refs': [1]}
             ],
             'expected': '按本源码语义正常应得到什么', 'actual': '此执行过程实际可能得到什么；不成立场景说明在哪一步被阻止'}
        ],
        'missing_evidence': []
    }
}
CONTRACT_PROMPT = '''
【跨项目统一的 OpenCode 复核输出协议 v2】
你是结论与用户解释的唯一生成者。工具只校验、排版你的字段，绝不会替你推断参与者、补写时序、猜状态或改结论。
在既有 finding_id/status/reason/evidence/interleaving/protection/impact/fix/verification 字段之外，必须返回下列字段结构（示意文字和枚举选项必须替换为本项目真实内容）：
''' + json.dumps(EXAMPLE, ensure_ascii=False, indent=2) + '''
规则：
1. schema_version 必须为整数 2。review_type：有 symbol_id 是 VARIABLE，否则是 EVIDENCE_GAP。任何工程均使用同一字段名和枚举，不依赖示例工程、变量名、固定目录或芯片。用中文解释；函数/变量名保留原名。
2. summary 不超过 180 字；participants 中 label 不超过 100 字，entry/access 各不超过 400 字；每步 action 不超过 400 字、state_before/state_after 各不超过 240 字。用短句写清谁做什么，英文缩写首次用中文说明。不要把代码全文或一串文件行号当作解释。
3. evidence_refs 是 evidence 列表的 1 起始序号，必须引用实际读过且 quote/claim 正确的源码。cause/scheduling 共用 explanation.evidence_refs；参与者和每步也各自引用依据。引用正确不代表推理自动正确，必须核对抢占和调用条件。
4. VARIABLE 的 CONFIRMED：至少两个真实参与执行者，首个场景必须 CONFLICT，至少两步且涉及至少两方；写出完整可成立过程与预期/实际差异。读改写应展示读旧值、另一方更新、旧副本写回；DMA 场景应展示硬件启动、CPU/硬件重叠访问及结果。不要为了凑步骤捏造被源码排除的路径。多个冲突用不同 scenarios，不能把多个起点混为一个顺序。
5. REVIEWED_SAFE/FALSE_POSITIVE：至少一个 BLOCKED 场景，说明冲突在哪个条件被阻止；没有运行期访问时 steps 可为空，不能编造访问。LIKELY/NEED_MORE_CONTEXT 只能用 UNRESOLVED/BLOCKED 场景，missing_evidence 必须列具体缺失条件；无法确定参与者/状态时保留空列表或明确未知，不猜。EVIDENCE_GAP 不强制构造变量冲突，不计作变量缺陷。
6. explanation 中不得与 status 或其他文字自相矛盾；安全回答不能包含 CONFLICT 场景。已有 interleaving 与结构化 scenarios 应描述相同事实，反证撤回的错误路径只能作为 BLOCKED 场景或在 reason 中说明，不能混入成立场景。
7. impact 分清可证明的存储结果和未证实的业务后果；fix 覆盖所有真实写点及忙状态；verification 是待执行的验证建议，没有实际执行就不能说已实测。缺依据请返回 NEED_MORE_CONTEXT，而不是为了填满格式编造事实。
8. 格式或证据校验失败将把具体错误退给你重新输出完整答案；程序不会替你生成字段。首轮和反证轮都必须使用这个版本。
9. 每个 participant 只代表一个执行上下文，不得将 USART1/USART2/DMA 等多个中断合成一个参与者。逐条核对回调实参、对象身份、条件分支和硬件模式；静态可达不等于实际访问。真实访问者标 ACTUAL，被参数过滤等条件排除的候选标 EXCLUDED，未知标 UNKNOWN。CONFLICT 步骤只允许 ACTUAL；被排除者只能在 BLOCKED/UNRESOLVED 场景中解释。没有证据支持的假想未来配置不要列为本次执行场景。
'''


def validate_explanation(answer, expected_type=None, required=False):
    """Allow explicit legacy reads; require v2 for every new model response."""
    version = answer.get('schema_version')
    if version is None and not required:
        if 'explanation' in answer or 'review_type' in answer:
            raise ValueError('结构化解释缺少 schema_version，不能当作旧版接受')
        return False
    if type(version) is not int or version != SCHEMA_VERSION:
        raise ValueError('OpenCode 必须返回 schema_version=2 的统一复核格式')
    review_type = answer.get('review_type')
    if review_type not in {'VARIABLE', 'EVIDENCE_GAP'} or (expected_type and review_type != expected_type):
        raise ValueError('review_type 必须与本项 symbol_id 对应：VARIABLE 或 EVIDENCE_GAP')
    details = answer.get('explanation')
    if not isinstance(details, dict):
        raise ValueError('缺少 explanation 对象；必须由 OpenCode 提供完整解释')
    status = answer['status']

    def fail(path, message):
        raise ValueError('explanation.' + path + '：' + message)

    def string(obj, key, path='', limit=None):
        value = obj.get(key)
        if not isinstance(value, str) or not value.strip():
            fail(path + key, '必须是非空字符串，未知请明确说明')
        if limit and len(value) > limit:
            fail(path + key, f'不得超过 {limit} 字符，请用短句重写')
        return value

    def array(obj, key, path=''):
        value = obj.get(key)
        if not isinstance(value, list):
            fail(path + key, '必须是列表')
        return value

    def refs(obj, path='', allow_empty=False):
        values = array(obj, 'evidence_refs', path)
        if not values and not allow_empty:
            fail(path + 'evidence_refs', '必须给出源码证据序号')
        if any(type(i) is not int or i < 1 or i > len(answer['evidence']) for i in values):
            fail(path + 'evidence_refs', '必须引用 evidence 中存在的 1 起始序号')

    for key in ('summary', 'cause', 'scheduling'):
        string(details, key, limit=180 if key == 'summary' else None)
    for i, item in enumerate(answer['evidence']):
        string(item, 'claim', f'evidence[{i}].')
    refs(details, allow_empty=status == 'NEED_MORE_CONTEXT')
    participants = array(details, 'participants')
    ids, eligibility = set(), {}
    for i, actor in enumerate(participants):
        path = f'participants[{i}].'
        if not isinstance(actor, dict):
            fail(path, '必须是对象')
        ident = string(actor, 'id', path, 80)
        if ident in ids:
            fail(path + 'id', '参与者 ID 不能重复')
        ids.add(ident)
        if actor.get('eligibility') not in {'ACTUAL', 'EXCLUDED', 'UNKNOWN'}:
            fail(path + 'eligibility', '必须说明该入口是 ACTUAL/EXCLUDED/UNKNOWN')
        eligibility[ident] = actor['eligibility']
        for key in ('label', 'entry', 'access'):
            string(actor, key, path, 100 if key == 'label' else 400)
        refs(actor, path)
    scenarios = array(details, 'scenarios')
    for i, scenario in enumerate(scenarios):
        path = f'scenarios[{i}].'
        if not isinstance(scenario, dict):
            fail(path, '必须是对象')
        for key in ('title', 'precondition', 'expected', 'actual'):
            string(scenario, key, path)
        kind = scenario.get('kind')
        if kind not in {'CONFLICT', 'BLOCKED', 'UNRESOLVED'}:
            fail(path + 'kind', '必须是 CONFLICT/BLOCKED/UNRESOLVED')
        if status != 'CONFIRMED' and kind == 'CONFLICT':
            fail(path + 'kind', '非确认结论不能展示已成立的冲突场景')
        if status in {'REVIEWED_SAFE', 'FALSE_POSITIVE'} and kind != 'BLOCKED':
            fail(path + 'kind', '安全/误报结论必须解释为何路径被阻止')
        steps = array(scenario, 'steps', path)
        used = set()
        for j, step in enumerate(steps):
            step_path = path + f'steps[{j}].'
            if not isinstance(step, dict):
                fail(step_path, '必须是对象')
            actor_id = string(step, 'actor_id', step_path, 80)
            if actor_id not in ids:
                fail(step_path + 'actor_id', '不存在于 participants 中')
            if kind == 'CONFLICT' and eligibility[actor_id] != 'ACTUAL':
                fail(step_path + 'actor_id', '成立的冲突不能使用已排除或尚未确定的访问者')
            used.add(actor_id)
            for key in ('action', 'state_before', 'state_after'):
                string(step, key, step_path, 400 if key == 'action' else 240)
            refs(step, step_path)
        if kind == 'CONFLICT' and (len(steps) < 2 or len(used) < 2):
            fail(path, '成立的冲突必须有至少两步、两个参与执行者')
    if review_type == 'VARIABLE' and status == 'CONFIRMED':
        if not scenarios or scenarios[0]['kind'] != 'CONFLICT':
            fail('scenarios', '确认变量缺陷必须首先给出一个完整 CONFLICT 场景')
    if status in {'REVIEWED_SAFE', 'FALSE_POSITIVE'} and not scenarios:
        fail('scenarios', '安全/误报必须给出至少一个 BLOCKED 场景及不成立原因')
    missing = array(details, 'missing_evidence')
    if any(not isinstance(s, str) or not s.strip() for s in missing):
        fail('missing_evidence', '每项必须说明一个具体缺失条件')
    if status in {'LIKELY', 'NEED_MORE_CONTEXT'} and not missing:
        fail('missing_evidence', '尚未确认的结论必须说明具体还缺什么证据')
    return True
