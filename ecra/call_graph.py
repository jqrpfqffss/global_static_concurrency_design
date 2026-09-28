"""Finite, lossless call graph storage and bounded path presentation.

The edge graph is the evidence. Enumerated paths are a convenient view for
small graphs; large graphs retain shortest witnesses plus every edge, root,
and context binding without constructing an exponential path family.
"""
from collections import defaultdict


def edge_context_graph(graph, calls, contexts):
    """Union callsite permissions; one unrestricted call keeps an edge open."""
    permissions = {}
    for call in calls:
        key = (call['caller_function_id'], call.get('callee_function_id'))
        if key in permissions and permissions[key] is None:
            continue
        if 'allowed_contexts' not in call:
            permissions[key] = None
        else:
            permissions.setdefault(key, set()).update(call['allowed_contexts'])
    result = {}
    for cid in contexts:
        result[cid] = {caller: {callee for callee in callees
            if permissions.get((caller, callee)) is None or cid in permissions[(caller, callee)]}
            for caller, callees in graph.items()}
    return result


def represent_paths(graphs, roots, paths, cfg):
    """Return explicit paths or a marked witness view with a complete graph.

    An explicit max_call_paths remains a fail-closed user limit. The automatic
    inline budget only changes representation and never drops graph evidence.
    """
    maximum = cfg.get('analysis', {}).get('max_call_paths', 0)
    budget = cfg.get('analysis', {}).get('inline_call_path_budget', 4096)
    if type(maximum) is not int or maximum < 0:
        raise ValueError('analysis.max_call_paths 必须为非负整数；0 表示不限制。')
    if type(budget) is not int or budget < 1:
        raise ValueError('analysis.inline_call_path_budget 必须为正整数。')
    # If a user explicitly requires a path-count limit, count up to that limit
    # (without storing beyond the inline budget) and retain historical failure.
    all_paths = defaultdict(lambda: defaultdict(list))
    produced_total, compact = 0, False
    counts = {}
    for cid, entries in roots.items():
        produced = 0
        graph = graphs[cid]
        for entry in sorted(entries):
            stack = [(entry, [entry], iter(sorted(graph.get(entry, ())))) ]
            if not compact:
                all_paths[entry][cid].append([entry])
            produced += 1
            produced_total += 1
            while stack:
                _, route, successors = stack[-1]
                child = next(successors, None)
                if child is None:
                    stack.pop()
                    continue
                if child in route:
                    continue
                if maximum and produced >= maximum:
                    raise ValueError('CALL_PATH_LIMIT：已解析调用链超过显式上限，扫描失败；提高 max_call_paths 或使用 0。')
                if produced_total >= budget:
                    compact = True
                    all_paths.clear()
                    if not maximum:
                        break
                child_route = route + [child]
                if not compact:
                    all_paths[child][cid].append(child_route)
                produced += 1
                produced_total += 1
                stack.append((child, child_route, iter(sorted(graph.get(child, ())))))
            if compact and not maximum:
                break
        counts[cid] = produced
        if compact and not maximum:
            break
    if compact:
        all_paths = {fid: {cid: [route] for cid, route in per_context.items()} for fid, per_context in paths.items()}
    else:
        all_paths = {fid: {cid: list({tuple(route): route for route in routes}.values())
                          for cid, routes in per_context.items()} for fid, per_context in all_paths.items()}
    metadata = dict(representation='COMPLETE_GRAPH_WITH_WITNESSES' if compact else 'ENUMERATED_PATHS',
        complete=True, path_lists_complete=not compact, inline_call_path_budget=budget,
        roots={cid: sorted(entries) for cid, entries in roots.items()},
        reachable_functions={cid: sorted(fid for fid in paths if cid in paths[fid]) for cid in roots},
        edges={cid: [[caller, callee] for caller in sorted(graphs[cid]) if cid in paths.get(caller, {})
                    for callee in sorted(graphs[cid][caller])] for cid in roots},
        callsite_evidence='facts.calls',
        note=('路径列表仅为最短见证；完整调用链由所有上下文入口和调用边表示，安全证明不使用见证路径替代完整图。'
              if compact else '路径列表完整；递归边另存，完整调用点保存在 facts.calls。'))
    return all_paths, metadata


class AccessGraphSlices:
    """Share complete upstream slices once per accessor, never per access."""
    def __init__(self, facts, paths):
        self.facts, self.paths, self.cache = facts, paths, {}
        self.incoming = {}
        for cid, edges in facts['context_call_graph']['edges'].items():
            reverse = defaultdict(set)
            for caller, callee in edges:
                reverse[callee].add(caller)
            self.incoming[cid] = reverse

    def for_function(self, fid):
        if fid in self.cache:
            return self.cache[fid]
        ancestors = {fid}
        edges = set()
        for cid in self.paths.get(fid, {}):
            reverse = self.incoming[cid]
            seen, todo = {fid}, [fid]
            while todo:
                callee = todo.pop()
                for caller in reverse.get(callee, ()):
                    edges.add((caller, callee))
                    if caller not in seen:
                        seen.add(caller)
                        todo.append(caller)
            ancestors.update(seen)
        calls = [i for i, call in enumerate(self.facts['calls'])
                 if (call.get('caller_function_id'),call.get('callee_function_id')) in edges]
        unresolved = [i for i, issue in enumerate(self.facts['unknowns']) if
            (issue.get('function_id') in ancestors or issue.get('target_function_id') in ancestors)
            and issue['kind'] in {'INDIRECT_CALL','EXTERNAL_CALLEE','MISSING_SOURCE_CALLER','UNRESOLVED_REGISTERED_ENTRY'}]
        result = dict(function_id=fid, function_ids=sorted(ancestors), call_edge_indices=calls,
            unresolved_issue_indices=unresolved,
            recursive_edges=[e for e in self.facts['recursive_edges'] if tuple(e) in edges],
            complete=True, representation='COMPLETE_UPSTREAM_GRAPH')
        self.cache[fid] = result
        return result
