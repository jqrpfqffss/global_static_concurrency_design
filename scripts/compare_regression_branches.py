"""Account for ECRA branch differences by original and derived storage identity."""
import argparse
from collections import Counter, defaultdict
from contextlib import closing
import csv
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

TOOL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL))
from ecra.json_rows import RowReader


STATIC = {'SAFE_PROVEN', 'SHARED_NO_REVIEW', 'SUSPECT', 'UNKNOWN'}
DISPLAY = {'SAFE_PROVEN': '已排查：未发现并发风险', 'SHARED_NO_REVIEW': '共享访问，无需复核',
           'SUSPECT': '疑似并发风险', 'UNKNOWN': '无法判断', 'CONTAINER': '容器汇总',
           'NON_STORAGE': '非独立存储', 'OUT_OF_BUILD': '未进入构建',
           'LIKELY': '疑似并发风险', 'CONFIRMED': '已确认并发风险', 'SAFE': '已排查：未发现并发风险',
           'REVIEWED_SAFE': '已复核安全', 'INVENTORY': '变量清单'}
CONTAINERS = {'STRUCT_CONTAINER', 'STRUCT_MEMBER_CONTAINER', 'ARRAY_CONTAINER'}
LEGACY_DISPLAY_GROUPS = {'confirmed': 'CONFIRMED', 'likely': 'LIKELY', 'unresolved': 'UNKNOWN',
                         'safe': 'SAFE', 'screened_safe': 'SAFE', 'screened_shared': 'SHARED_NO_REVIEW',
                         'inventory': 'INVENTORY', 'supplemental': 'OUT_OF_BUILD'}


def load(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def indexed(rows):
    result = {row['symbol_id']: row for row in rows}
    if len(result) != len(rows):
        raise ValueError('Repeated IDs in an inventory stage')
    return result


def storage_identity(row):
    """Recover the original object and ordered projections, including array fields."""
    sid = row['symbol_id']
    parent = row.get('root_symbol_id') or row.get('array_root_symbol_id')
    if not parent or parent == sid:
        return sid, ''
    # The ID includes array indices even when the field metadata contains
    # only the field under that element.
    offsets = [parent.index(marker) for marker in ('::member::','::element::') if marker in parent]
    root = parent[:min(offsets)] if offsets else parent
    if sid.startswith(root+'::'):
        return root, sid[len(root):]
    if row.get('field_path'):
        return root, '::member::' + row['field_path']
    return root, '::element::' + str(row['array_index']) if row.get('array_index') is not None else ''


def locations(row, key):
    return tuple(sorted((d.get('file'), d.get('line'), d.get('column'), d.get('offset'))
                        for d in row.get(key, []) if d.get('file')))


def physical_units(root):
    if root.get('linkage') in {'INTERNAL', 'NO_LINKAGE', 'UNIQUE_EXTERNAL'}:
        return tuple(sorted(root.get('translation_units', [])))
    return ()


def identity(row, roots):
    root_id, path = storage_identity(row)
    root = roots.get(root_id, row)
    site = locations(root, 'definitions') or locations(root, 'declarations')
    if not site:
        return None
    # The same physical position in a header may have independent instances.
    # Exact ID remains primary for external definitions and inline COMDATs.
    link = root.get('linkage')
    return (site, link, root.get('kind'), root.get('qualified_name'), physical_units(root), path)


def aligned(left, right, left_roots, right_roots):
    same, unverified = {}, {}
    for sid in left.keys() & right.keys():
        a, b = left[sid], right[sid]
        old_id, old_path = storage_identity(a)
        new_id, new_path = storage_identity(b)
        old, new = left_roots.get(old_id, a), right_roots.get(new_id, b)
        old_sites = set(locations(old, 'definitions') or locations(old, 'declarations'))
        new_sites = set(locations(new, 'definitions') or locations(new, 'declarations'))
        if (old.get('linkage') == new.get('linkage') and physical_units(old) == physical_units(new)
                and old_path == new_path
                and (old_sites & new_sites or not old_sites and not new_sites)):
            same[sid] = sid
        else:
            unverified[sid] = [sid]
    left_key, right_key = defaultdict(list), defaultdict(list)
    for rows, keys, matched, roots in (
            (left, left_key, set(same), left_roots), (right, right_key, set(same.values()), right_roots)):
        for sid in rows.keys() - matched:
            key = identity(rows[sid], roots)
            if key is not None:
                keys[key].append(sid)
    changed = {}
    for key in left_key.keys() & right_key.keys():
        a, b = left_key[key], right_key[key]
        if len(a) == len(b) == 1:
            changed[a[0]] = b[0]
        else:
            unverified.update({sid: sorted(b) for sid in a})
    return same | changed, changed, {sid: candidates for sid, candidates in unverified.items() if sid not in changed}


def l2_rows(scan, units):
    pending = []
    worker_dir = scan/'workers'
    for unit in units:
        path = worker_dir/(unit['tu_id']+'.response.json')
        if not path.is_file():
            if unit['parse_status'] == 'FAILED' and unit.get('diagnostics'):
                continue
            raise FileNotFoundError(path)
        # ECRA workers put variables first; read to the end of that array.
        with path.open(encoding='utf-8-sig') as stream:
            reader = RowReader(stream)
            reader.take('{')
            first_key = reader.value()
            if first_key == 'parse_status' and unit['parse_status'] == 'FAILED':
                failure = load(path)
                if failure.get('parse_status') == 'FAILED' and failure.get('diagnostics') and 'variables' not in failure:
                    continue
            if first_key != 'variables':
                raise ValueError('Unexpected worker layout: ' + str(path))
            reader.take(':')
            reader.take('[')
            while reader.peek() != ']':
                row = reader.value()
                item = {key: row[key] for key in ('symbol_id','definitions','declarations','name','qualified_name',
                        'kind','linkage','type','definition_file','definition_line','owner_function_id') if key in row}
                pending.append(dict(item, tu_id=unit['tu_id'], translation_unit=unit['source_file'],
                                    parse_status=unit['parse_status']))
                if reader.peek() == ']':
                    break
                reader.take(',')
            reader.take(']')
    return pending


def normalize_state(row):
    if row.get('static_classification') is None and row.get('resource_kind') in CONTAINERS:
        return 'CONTAINER'
    return row.get('static_classification')


def snapshot_stats(scan, stage):
    return {key:sum(bool(row.get(key)) for row in scan[stage].values())
            for key in ('declarations','definitions')}


def write_csv(path, rows, fields):
    with path.open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: (json.dumps(row[key], ensure_ascii=False, sort_keys=True)
                              if isinstance(row.get(key), (dict,list,tuple)) else row.get(key))
                             for key in fields})


def scan_input(root, name, variant, attempt):
    work = root/f'{name}-{variant}-run{attempt}'
    if not (work/'L6-L7-analyzed.json').is_file():
        raise FileNotFoundError('Analysis boundary not reached: ' + str(work))
    final = indexed(load(work/'L6-L7-analyzed.json'))
    linked = indexed(load(work/'L3-linked.json'))
    projected = indexed(load(work/'L5-projection-before-scope.json'))
    selected = indexed(load(work/'L4-selected.json'))
    units = load(work/'L1-parsed.json')
    terminal = work/'execution-terminal.json'
    receipt = load(terminal if terminal.is_file() else work/'execution.json')
    engine = load(work/'engine.json')
    config = load(work/'effective_config.json')
    analysis = config['analysis']
    source = Path(config['project']['root'])
    if variant == 'A':
        scan = source/analysis['output_dir']
    else:
        data = Path(analysis['output']['custom_dir'])/'scans'
        candidates = [p for p in data.iterdir() if p.is_dir() and (p/'storage.json').is_file()
                      and load(p/'storage.json').get('config_file') == engine['config']]
        if len(candidates) != 1:
            raise ValueError('The config does not identify a unique scan in ' + str(data))
        scan = candidates[0]
    authority_complete = False
    published_counts = {}
    authority_ids = set()
    if receipt['state'] == 'EXITED' and receipt.get('exit_code') in (0, 1, 2):
        proof = scan/'result_validity.json'
        if variant == 'A':
            authority_complete = (scan/'scan_state.json').is_file() and (scan/'facts.db').is_file()
            db = scan/'facts.db'
            sql = 'SELECT symbol_id,static_classification FROM variables'
        else:
            authority_complete = ((scan/'manifest.json').is_file() and proof.is_file()
                                  and load(proof)['analysis_valid'])
            db = scan/'scan.db'
            sql = 'SELECT symbol_id,static_classification FROM symbols'
        if authority_complete:
            with closing(sqlite3.connect(db.as_uri()+'?mode=ro', uri=True)) as conn:
                counts = Counter()
                for sid,state in conn.execute(sql):
                    if sid in authority_ids:
                        raise ValueError('Duplicate persisted ID: ' + sid)
                    authority_ids.add(sid)
                    counts[state or 'LEGACY_CONTAINER_WITHOUT_LABEL'] += 1
                    if sid not in final or normalize_state(dict(final[sid], static_classification=state)) != normalize_state(final[sid]):
                        raise ValueError('Published static decision diverged: ' + sid)
                assert authority_ids == final.keys(), 'Published inventory IDs diverged'
                published_counts = dict(counts)
    rows = l2_rows(scan, units)
    grouped_l2 = defaultdict(list)
    for row in rows:
        grouped_l2[row['symbol_id']].append(row)
    return dict(work=work, linked=linked, projected=projected, selected=selected, units=units, final=final,
                receipt=receipt, engine=engine, scan=scan, l2=grouped_l2, l2_count=len(rows), config=config,
                l2_definition_count=sum(bool(row.get('definitions')) for row in rows),
                authority_complete=authority_complete, published_counts=published_counts,
                authority_ids=authority_ids, findings={r['symbol_id']:r for r in load(work/'L7-findings.json') if r.get('symbol_id')})


def first_absent(row, other):
    sid = row['symbol_id']
    root, _ = storage_identity(row)
    for label, key, ident in (('L2', 'l2', root), ('L3', 'linked', root), ('L5', 'projected', sid),
                              ('L4', 'selected', sid), ('L7', 'final', sid)):
        if ident not in other[key]:
            return label
    return 'PERSISTENCE' if other['authority_complete'] and sid not in other['authority_ids'] else 'UNRESOLVED'


def presence_reason(row, first, target):
    sid = row['symbol_id']
    status = {unit['source_file']:unit['parse_status'] for unit in target['units']}
    owners = row.get('translation_units', [])
    if owners and all(tu not in status for tu in owners):
        return 'L1', 'COMPILATION_UNIT_NOT_ANALYZED'
    if first == 'L5':
        return first, 'DERIVATION_CHANGED_REVIEW_REQUIRED'
    if first == 'L4' and sid in target['projected']:
        return first, 'SCOPE_EXCLUSION_REVIEW_REQUIRED'
    if first == 'L3' and storage_identity(row)[0] in target['l2']:
        return first, 'LINK_MERGE_REVIEW_REQUIRED'
    if first == 'L7':
        return first, 'CLASSIFICATION_INPUT_REVIEW_REQUIRED'
    if any(status.get(tu) != 'PARSED' for tu in owners):
        return first, 'PARSE_COVERAGE_GAP'
    return first, 'UNEXPLAINED'


def observed_display(scan):
    if not scan['authority_complete']:
        return {}, {}
    if (scan['scan']/'scan.db').is_file():
        from ecra.studio.query import QueryService
        from ecra.scan_store import connect_readonly
        service = QueryService(scan['scan'])
        with closing(connect_readonly(scan['scan']/'scan.db')) as conn:
            service._attach_human(conn)
            source, values = service._result_rows(conn, [], [], '')
            decisions = {sid: dict(decision=state, label=DISPLAY.get('REVIEWED_SAFE' if state=='SAFE' and origin=='OPENCODE'
                                   else state, state), result_source=origin,
                                   human_decision=human, confirmation_state=confirm)
                         for sid,state,origin,human,confirm in conn.execute(
                             'SELECT symbol_id,current_result,result_source,human_record_decision,confirmation_state FROM ('+source+')',
                             values)}
        if decisions.keys() != scan['authority_ids']:
            raise ValueError('Studio projection inventory diverged from the authority')
        return dict(projection='Studio', counts=dict(Counter(r['decision'] for r in decisions.values()))), decisions
    from ecra.json_rows import rows
    report = scan['scan']/'reports/global_static_concurrency.json'
    risk = next(value for name, value, array in rows(report) if name == 'risk_summary' and not array)
    decisions = {row['symbol_id']: dict(decision=row['decision'], label=row['label']) for row in risk['variables']}
    if not decisions.keys() <= scan['authority_ids']:
        raise ValueError('Legacy report contains a symbol absent from the authority')
    return dict(projection='A legacy HTML', counts=risk['counts']), decisions


def display_group(decision):
    value = decision.get('decision')
    return LEGACY_DISPLAY_GROUPS.get(value, value)


def category(a, b):
    raw = a.get('static_classification'), b.get('static_classification')
    if raw[0] != raw[1] and normalize_state(a)==normalize_state(b)=='CONTAINER':
        return 'EXPLICIT_NESTED_CONTAINER_SUMMARY'
    if normalize_state(a)==normalize_state(b):
        return 'SAME_STATIC'
    if normalize_state(a) in STATIC and normalize_state(b)=='NON_STORAGE':
        return 'LINKER_STORAGE_PROOF_REVIEW_REQUIRED'
    if normalize_state(a) in {'SUSPECT','UNKNOWN'} and normalize_state(b) in {'SAFE_PROVEN','SHARED_NO_REVIEW'}:
        return 'REQUIRES_POSITIVE_SAFETY_PROOF'
    return 'EVIDENCE_REVIEW_REQUIRED'


def access_hashes(scan):
    """Compare locations, modes, contexts and shortest witnesses without copying large reports."""
    if not scan['authority_complete']:
        raise ValueError('Access comparison requires a published authority')
    path = scan['scan']
    result, functions = defaultdict(Counter), defaultdict(set)
    boolean_fields = {'hardware', 'via_alias'}
    json_fields = {'contexts', 'call_chains', 'mask_states', 'protection_evidence', 'context_exclusions'}
    wanted = ('symbol_id','file','line','column','offset','function_id','access_kind','access_path',
              'access_scope','contexts','reachability','call_chains','hardware','mask_states',
              'protection_evidence','context_exclusions','via_alias','via_api','inherited_from_access_id',
              'resolved_call_edge_count','unresolved_call_edge_count')

    def index(row, decoder=json.loads):
        sid = row.pop('symbol_id')
        row = {key: value for key, value in row.items() if value is not None and
               (key not in boolean_fields or value)}
        for key in boolean_fields & row.keys():
            row[key] = bool(row[key])
        for key in json_fields & row.keys():
            if isinstance(row[key], str):
                row[key] = decoder(row[key])
        result[sid][digest(row)] += 1
        if row.get('function_id'):
            functions[sid].add(row['function_id'])

    if (path/'scan.db').is_file():
        from ecra.native_consumers import _small_value
        from ecra.scan_store import connect_readonly
        with closing(connect_readonly(path/'scan.db')) as conn:
            for sid,node in conn.execute("SELECT symbol_id,node FROM records WHERE dataset='facts' AND relation='accesses' ORDER BY ordinal"):
                row = {key:_small_value(conn,child) for key,child in conn.execute(
                    "SELECT key,child FROM edges WHERE parent=?", (node,)) if key in wanted and key != 'symbol_id'}
                index(dict(row, symbol_id=sid))
    else:
        with closing(sqlite3.connect((path/'facts.db').as_uri()+'?mode=ro',uri=True)) as conn:
            available = {row[1] for row in conn.execute('PRAGMA table_info(accesses)')}
            columns = [key for key in wanted if key in available]
            if 'symbol_id' in columns:
                from ecra.shared_json import DatabasePool
                pool = DatabasePool(conn)
                for value in conn.execute('SELECT '+','.join(columns)+' FROM accesses'):
                    index(dict(zip(columns, value)), pool.loads)
    return result, functions


def call_slice_hashes(scan, functions):
    """Digest all resolved incoming direct and indirect edges for accessors."""
    fields = ('caller_function_id','callee_function_id','call_kind','file','line','column','offset')
    slices = {}
    incoming = defaultdict(list)
    if (scan['scan']/'scan.db').is_file():
        from ecra.native_consumers import _small_value
        from ecra.scan_store import connect_readonly
        with closing(connect_readonly(scan['scan']/'scan.db')) as conn:
            for node, in conn.execute("SELECT node FROM records WHERE dataset='facts' AND relation='calls' ORDER BY ordinal"):
                row = {key:_small_value(conn,child) for key,child in conn.execute(
                    'SELECT key,child FROM edges WHERE parent=?', (node,)) if key in fields}
                if row.get('callee_function_id'):
                    incoming[row['callee_function_id']].append((row.get('caller_function_id'), digest(row)))
    else:
        with closing(sqlite3.connect((scan['scan']/'facts.db').as_uri()+'?mode=ro', uri=True)) as conn:
            available = {row[1] for row in conn.execute('PRAGMA table_info(calls)')}
            columns = [field for field in fields if field in available]
            if 'callee_function_id' in columns:
                for values in conn.execute('SELECT '+','.join(columns)+' FROM calls WHERE callee_function_id IS NOT NULL'):
                    row = {key:value for key,value in zip(columns,values) if value is not None}
                    incoming[row['callee_function_id']].append((row.get('caller_function_id'), digest(row)))
    for function in sorted({fid for accessors in functions.values() for fid in accessors}):
        pending, seen, edges = [function], {function}, Counter()
        while pending:
            for caller, evidence_hash in incoming.get(pending.pop(), ()):
                edges[evidence_hash] += 1
                if caller and caller not in seen:
                    seen.add(caller)
                    pending.append(caller)
        slices[function] = digest(edges)
    return {sid:digest({fid:slices[fid] for fid in fids}) for sid,fids in functions.items()}


def finding_proofs(scan, symbol_ids):
    """Read the criteria and witnesses for changed objects from the authority."""
    if not scan['authority_complete']:
        return {}
    common = {'symbol_id', 'static_classification', 'coverage_reasons', 'unknown_reason_codes',
              'protection_status', 'protection_details', 'protection_note', 'screening_blockers',
              'concurrency_relations', 'conflict_pairs', 'blocking_evidence', 'variable_evidence_slice'}
    criteria = common | {'classification_reason', 'analysis_coverage', 'readers', 'writers', 'contexts',
                         'safe_evidence', 'safe_reason_codes', 'shared_evidence', 'shared_no_review_rejections',
                         'initialization_proof', 'resolved_call_path_count', 'unreachable_access_count',
                         'linker_anchor_evidence', 'weak_symbol_evidence', 'unlinked_declaration_evidence'}
    findings = common | {'finding_id', 'rules', 'declared_protection', 'uncertainties', 'snapshots',
                         'configured_preemption', 'configured_concurrency'}
    results = defaultdict(lambda: {'variable': {}, 'findings': []})
    if (scan['scan']/'scan.db').is_file():
        from ecra.native_consumers import _small_value
        from ecra.scan_store import connect_readonly
        with closing(connect_readonly(scan['scan']/'scan.db')) as conn:
            def proof(node, wanted):
                return {key:_small_value(conn,child) for key,child in conn.execute(
                    'SELECT key,child FROM edges WHERE parent=? ORDER BY ordinal', (node,)) if key in wanted}
            for sid in sorted(symbol_ids):
                node, = conn.execute('SELECT node FROM symbols WHERE symbol_id=?', (sid,)).fetchone()
                results[sid]['variable'] = proof(node, criteria)
            for sid,node in conn.execute("SELECT symbol_id,node FROM records WHERE dataset='report' AND relation='findings' AND symbol_id IS NOT NULL ORDER BY ordinal"):
                if sid in symbol_ids:
                    results[sid]['findings'].append(proof(node, findings))
    else:
        database = scan['scan']/'facts.db'
        with closing(sqlite3.connect(database.as_uri()+'?mode=ro', uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            from ecra.shared_json import DatabasePool
            pool = DatabasePool(conn)
            for table, wanted in (('variables', criteria), ('findings', findings)):
                available = {row[1] for row in conn.execute(f'PRAGMA table_info({table})')}
                if 'symbol_id' not in available:
                    continue
                fields = ','.join(sorted(wanted & available))
                for row in conn.execute(f'SELECT {fields} FROM {table}'):
                    sid = row['symbol_id']
                    if sid not in symbol_ids:
                        continue
                    proof = dict(row)
                    for key, value in proof.items():
                        if isinstance(value, str) and value.startswith(('{', '[')):
                            try:
                                proof[key] = pool.loads(value)
                            except json.JSONDecodeError:
                                pass  # Scalar or ordinary text stored in a legacy column.
                    if table == 'variables':
                        results[sid]['variable'] = proof
                    else:
                        results[sid]['findings'].append(proof)
    return results


def audit(source, target, output, followup=None, evidence=False):
    output.mkdir(parents=True, exist_ok=True)
    left, right = source['final'],target['final']
    common, changes, ambiguous = aligned(left, right, source['linked'], target['linked'])
    to_fixed = aligned(left, followup['final'], source['linked'], followup['linked'])[0] if followup else {}
    right_to_fixed = aligned(right, followup['final'], target['linked'], followup['linked'])[0] if followup else {}
    commonfields = ('symbol_id','name','type','qualified_name','kind','linkage','definition_file','definition_line',
                    'translation_units','definitions','declarations','resource_kind','a_id','b_id','c_id','c_representation',
                    'first_differing_stage','reason','target_tu_status','identity_candidates','resolution')
    reverse_ambiguity = defaultdict(list)
    for sid, candidates in ambiguous.items():
        for candidate in candidates:
            reverse_ambiguity[candidate].append(sid)

    def deltas(available, absent, matched, pair):
        results = []
        statuses = {u['source_file']:u['parse_status'] for u in absent['units']}
        fixed_ids = to_fixed if pair == 'a' else right_to_fixed
        questionable = ambiguous if pair == 'a' else reverse_ambiguity
        for sid,row in sorted(available['final'].items()):
            if sid in matched:
                continue
            first, reason = presence_reason(row, first_absent(row, absent), absent)
            candidates = questionable.get(sid, [])
            record = dict(row, first_differing_stage=first,
                          reason='IDENTITY_REQUIRES_REVIEW' if candidates else reason,
                          target_tu_status={tu:statuses.get(tu,'NOT_ANALYZED') for tu in row.get('translation_units',[])},
                          identity_candidates=candidates, resolution='UNVERIFIED',
                          c_id=fixed_ids.get(sid))
            record[pair+'_id'] = sid
            if sid in fixed_ids:
                record['c_representation']=normalize_state(followup['final'][fixed_ids[sid]])
            results.append(record)
        return results

    missing = deltas(source,target,common,'a')
    new = deltas(target,source,set(common.values()),'b')
    write_csv(output/'missing_variables.csv',missing,commonfields)
    write_csv(output/'new_variables.csv',new,commonfields)
    write_csv(output/'identity_changes.csv',
              [dict(left[sid],a_id=sid,b_id=end,c_id=to_fixed.get(sid),reason='UNIQUE_MATCH_BY_DEFINITION_SITE_AND_SCOPE')
               for sid,end in sorted(changes.items())],commonfields)
    completed = [('left',source),('right',target)] + ([('fixed',followup)] if followup is not None else [])
    projections = {label: observed_display(scan) for label,scan in completed}
    decisions_a = projections['left'][1]
    decisions_b = projections['right'][1]
    decisions_c = projections.get('fixed', ({}, {}))[1]
    classifications = []
    for a,b in sorted(common.items()):
        u,v = left[a],right[b]
        a_decision,b_decision = decisions_a.get(a, {}),decisions_b.get(b, {})
        changed_display = (source['authority_complete'] and target['authority_complete']
                           and (normalize_state(u) in STATIC or normalize_state(v) in STATIC)
                           and display_group(a_decision) != display_group(b_decision))
        if not changed_display and u.get('static_classification')==v.get('static_classification') and u.get('resource_kind')==v.get('resource_kind'):
            continue
        reason = category(u,v)
        if changed_display and reason=='SAME_STATIC':
            reason = 'PRESENTATION_REVIEW_REQUIRED'
        fixed = to_fixed.get(a)
        code = normalize_state(followup['final'][fixed]) if fixed else None
        classifications.append(dict(u,a_id=a,b_id=b,c_id=fixed,
            raw_a=u.get('static_classification'),raw_b=v.get('static_classification'),
            static_a=normalize_state(u),static_b=normalize_state(v),static_c=code,
            final_a=a_decision.get('label'),final_b=b_decision.get('label'),final_c=decisions_c.get(fixed, {}).get('label'),
            effective_a=a_decision.get('decision'),effective_b=b_decision.get('decision'),
            effective_c=decisions_c.get(fixed, {}).get('decision'),
            safe_reason_a=u.get('safe_reason_code'),safe_reason_b=v.get('safe_reason_code'),
            unknown_a=u.get('unknown_reason_codes'),unknown_b=v.get('unknown_reason_codes'),
            rules_a=source['findings'].get(a,{}).get('rules'),rules_b=target['findings'].get(b,{}).get('rules'),
            reviewed_reason=reason,validation='VERIFIED_PRESENTATION_ONLY' if reason=='EXPLICIT_NESTED_CONTAINER_SUMMARY' else 'UNVERIFIED'))
    write_csv(output/'classification_changes.csv',classifications,
              ('a_id','b_id','c_id','name','type','definition_file','definition_line','raw_a','raw_b','static_a','static_b','static_c',
               'effective_a','effective_b','effective_c','final_a','final_b','final_c','safe_reason_a','safe_reason_b','unknown_a','unknown_b','rules_a','rules_b',
               'reviewed_reason','validation'))
    evidence_rows = []
    evidence_verified = evidence and all(s['authority_complete'] for s in (source,target))
    if evidence_verified:
        (a_evidence,a_funcs), (b_evidence,b_funcs) = access_hashes(source),access_hashes(target)
        # A/B may store graph lists differently. Walk complete resolved edge
        # facts using the same rule and compare their multiplicities.
        a_calls, b_calls = call_slice_hashes(source,a_funcs),call_slice_hashes(target,b_funcs)
        for a,b in sorted(common.items()):
            x,y = a_evidence.get(a,Counter()), b_evidence.get(b,Counter())
            if x!=y or a_calls.get(a)!=b_calls.get(b):
                evidence_rows.append(dict(left[a],a_id=a,b_id=b,access_count_a=x.total(),access_count_b=y.total(),
                    removed=dict(x-y),added=dict(y-x),incoming_call_edges_a=a_calls.get(a),incoming_call_edges_b=b_calls.get(b),
                    validation='RUNTIME_ACCESS_OR_CALL_GRAPH_CHANGED'))
    write_csv(output/'evidence_changes.csv',evidence_rows,
              ('a_id','b_id','name','definition_file','definition_line','access_count_a','access_count_b','removed','added',
               'incoming_call_edges_a','incoming_call_edges_b','validation'))
    # Keep the full published proof record for changed objects, even if access
    # sites agree. A display label or equal counts cannot prove safe behavior.
    changed_proofs = [row for row in classifications if row['validation']=='UNVERIFIED']
    if changed_proofs and evidence_verified:
        old_proof = finding_proofs(source, {row['a_id'] for row in changed_proofs})
        new_proof = finding_proofs(target, {row['b_id'] for row in changed_proofs})
        save(output/'classification_changed_proofs.json', [{
            'left_id': row['a_id'], 'right_id':row['b_id'],
            'left_static_proof':left[row['a_id']], 'right_static_proof':right[row['b_id']],
            'left_published_evidence':old_proof.get(row['a_id']),
            'right_published_evidence':new_proof.get(row['b_id']),
        } for row in changed_proofs])
    for label,scan in completed:
        folder = output/label
        folder.mkdir(exist_ok=True)
        stages = {key:sorted(scan[key]) for key in ('linked','projected','selected','final')}
        stages['l2'] = scan['l2']
        stages['classified'] = sorted(sid for sid,row in scan['final'].items() if normalize_state(row) in STATIC)
        save(folder/'stage-identities.json',stages)
        save(folder/'L1-TU-diagnostics.json',scan['units'])
        display, displayed_decisions = projections[label]
        save(folder/'L7-effective-decisions.json', {
             sid: dict(displayed_decisions.get(sid, {}),static=normalize_state(row)) for sid,row in scan['final'].items()})
        parsed=Counter(u['parse_status'] for u in scan['units'])
        stat=Counter(normalize_state(v) for v in scan['final'].values())
        save(folder/'metrics.json',dict(L1=len(scan['units']),parse_status=parsed,L2=scan['l2_count'],
             L2_unique_ids=len(scan['l2']), L2_variables_with_definition=scan['l2_definition_count'],
             L3=len(scan['linked']), L3_storage_sites=snapshot_stats(scan,'linked'), L4=len(scan['selected']),
             L5=len(scan['projected']),L6=len(stages['classified']),L7=dict(stat),
             authority_complete=scan['authority_complete'],published_counts=scan['published_counts'],
             displayed=display,
             execution=scan['receipt'],engine=scan['engine']))
    for stage in ('l2','linked','projected','selected','final'):
        a, b = source[stage], target[stage]
        save(output/('difference-'+stage+'.json'), dict(
            left_count=len(a), right_count=len(b), left_only=sorted(a.keys()-b.keys()),
            right_only=sorted(b.keys()-a.keys()), common=len(a.keys() & b.keys())))
    summary = dict(common=len(common),missing=len(missing),new=len(new),identity_changes=len(changes),
                   classification_changes=len(classifications),
                   raw_static_changes=dict(Counter(r['reviewed_reason'] for r in classifications)),
                   access_and_shortest_witness_comparison_completed=evidence_verified,
                   incoming_call_edge_comparison_completed=evidence_verified,
                   evidence_changes=len(evidence_rows) if evidence_verified else None)
    save(output/'comparison.json',summary)
    print(json.dumps(summary,ensure_ascii=False),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--evidence',type=Path,required=True)
    p.add_argument('--project',required=True)
    p.add_argument('--left',default='A:1')
    p.add_argument('--right',default='B:1')
    p.add_argument('--fixed')
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--compare-accesses',action='store_true')
    args=p.parse_args()
    def get(name):
        variant,attempt=name.split(':',1)
        return scan_input(args.evidence,args.project,variant,attempt)
    audit(get(args.left),get(args.right),args.output,get(args.fixed) if args.fixed else None,args.compare_accesses)


if __name__ == '__main__':
    main()
