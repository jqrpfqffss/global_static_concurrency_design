"""Share immutable access context views without changing any logical fact.

The maps/events supplied here are final for this analysis pass. Consumers only
read these nested containers; per-access mutable fields stay on distinct dicts.
Bounded LRUs accelerate allocation, never limit evidence or cache eligibility.
"""
from collections import OrderedDict


def enrich_accesses(facts, paths, all_call_paths, unreachable, events, access_graph,
                    compact_paths, by_var, *, cache_size=4096):
    views, protection = OrderedDict(), OrderedDict()

    def remember(cache, key, value):
        cache[key] = value
        cache.move_to_end(key)
        while len(cache) > cache_size:
            cache.popitem(last=False)

    for a in facts["accesses"]:
        allowed = a.get('allowed_contexts')
        fid = a['function_id']
        # Unknown containers can compute changing membership results. Preserve
        # their original per-access predicate calls instead of memoizing them.
        reusable = type(fid) is str and (allowed is None or
            (type(allowed) in {list, tuple, set, frozenset} and all(type(cid) is str for cid in allowed)))
        key = (fid, None if allowed is None else frozenset(allowed)) if reusable else None
        shared = views.get(key) if reusable else None
        if shared is None:
            access_paths = {cid: route for cid, route in paths.get(fid, {}).items()
                            if allowed is None or cid in allowed}
            shared = (sorted(access_paths), access_paths,
                {cid: routes for cid, routes in all_call_paths.get(fid, {}).items() if cid in access_paths})
            if reusable:
                remember(views, key, shared)
        elif reusable:
            views.move_to_end(key)
        a["contexts"] = shared[0]
        a['reachability'] = ('PROVEN_UNREACHABLE' if fid in unreachable or a.get('context_proven_unreachable') else
                             'REACHABLE' if a['contexts'] else 'UNKNOWN_ENTRY')
        a["call_chains"] = shared[1]
        a["all_call_chains"] = shared[2]
        graph_slice = access_graph.for_function(fid)
        a['call_graph_slice'] = fid
        a['call_chain_representation'] = facts['context_call_graph']['representation']
        a['call_path_lists_complete'] = not compact_paths
        a['resolved_call_edge_count'] = len(graph_slice['call_edge_indices'])
        a['unresolved_call_edge_count'] = len(graph_slice['unresolved_issue_indices'])
        a.pop('resolved_call_edges', None)
        a.pop('unresolved_call_edges', None)
        a['call_chain_cycles'] = graph_slice['recursive_edges']
        if type(fid) is str and fid in protection:
            protection.move_to_end(fid)
            a["protection_evidence"] = protection[fid]
        else:
            a["protection_evidence"] = [e for e in events[fid] if e["event_kind"] in {"lock_enter", "lock_exit"}]
            if type(fid) is str:
                remember(protection, fid, a["protection_evidence"])
        by_var[a["symbol_id"]].append(a)
