"""独立验收证据匹配，不依赖忽略目录、历史结果或生产判定逻辑。

保留原 STM32 验收器 identify/chain_matches 的匹配规则。
仅有告警、取址或配置声明的调用边，不能代替真实写访问与入口证据。
"""


def identify(expected, facts):
    candidates = [v for v in facts.get('variables', []) if v['name'] == expected['name']
                  and v['definition_file'] == expected['file'] and v['kind'] == expected['kind']]
    if expected.get('function'):
        candidates = [v for v in candidates if v['qualified_name'] == expected['function'] + '::' + expected['name']]
        candidates = sorted(candidates, key=lambda v: (v['definition_line'], v['symbol_id']))
        candidates = candidates[expected['ordinal']:expected['ordinal']+1]
    if expected.get('translation_unit'):
        candidates = [v for v in candidates if expected['translation_unit'] in v['translation_units']]
    return candidates[0] if len(candidates) == 1 else None


def chain_matches(expected, variable, facts):
    functions = {f['function_id']: f for f in facts['functions']}
    edges = {(c['caller_function_id'], c['callee_function_id']) for c in facts['calls']
             if c['call_kind'] != 'CONFIGURED'}
    roots = {b['function_id'] for b in facts.get('context_bindings', [])
             if b['context_id'] == expected['context'] and b['call_depth'] == 0}
    paths = [[f] for f in roots if functions[f]['name'] == expected['functions'][0]]
    for name in expected['functions'][1:]:
        paths = [p + [b] for p in paths for a, b in edges
                 if a == p[-1] and functions.get(b, {}).get('name') == name]
    for access in variable.get('accesses', []):
        if access['access_kind'] not in expected['modes'] or expected['context'] not in access.get('contexts', []):
            continue
        if any(p[-1] == access['function_id'] for p in paths):
            return dict(access_id=access['access_id'], kind=access['access_kind'], file=access['file'],
                        line=access['line'], context=expected['context'], chain=next(p for p in paths if p[-1] == access['function_id']))
    return None
