"""Frozen unchanged034ecb5 access enrichment loop; do not edit the reference.

Original block SHA256: 7635719f65ca00c5e1962eacc0e8b938250d511cffafdf34ef7943ddaad46715
"""

def enrich_accesses(facts, paths, all_call_paths, unreachable, events, access_graph, compact_paths, by_var):
    for a in facts["accesses"]:
        allowed = a.get('allowed_contexts')
        access_paths = {cid: route for cid, route in paths.get(a['function_id'], {}).items()
                        if allowed is None or cid in allowed}
        a["contexts"] = sorted(access_paths)
        a['reachability'] = ('PROVEN_UNREACHABLE' if a['function_id'] in unreachable or a.get('context_proven_unreachable') else
                             'REACHABLE' if a['contexts'] else 'UNKNOWN_ENTRY')
        a["call_chains"] = access_paths
        a["all_call_chains"] = {cid: routes for cid, routes in all_call_paths.get(a["function_id"], {}).items()
                                if cid in access_paths}
        graph_slice = access_graph.for_function(a['function_id'])
        a['call_graph_slice'] = a['function_id']
        a['call_chain_representation'] = facts['context_call_graph']['representation']
        a['call_path_lists_complete'] = not compact_paths
        a['resolved_call_edge_count'] = len(graph_slice['call_edge_indices'])
        a['unresolved_call_edge_count'] = len(graph_slice['unresolved_issue_indices'])
        # Even a small path graph can have thousands of aliased access sites.
        # Share its full edge evidence once per accessor in both display modes;
        # the path lists above and every original call/issue remain available.
        a.pop('resolved_call_edges', None)
        a.pop('unresolved_call_edges', None)
        a['call_chain_cycles'] = graph_slice['recursive_edges']
        a["protection_evidence"] = [e for e in events[a["function_id"]] if e["event_kind"] in {"lock_enter", "lock_exit"}]
        by_var[a["symbol_id"]].append(a)
