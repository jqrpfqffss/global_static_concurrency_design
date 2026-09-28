"""Canonical array elements and overlapping storage evidence."""
import copy
import re
from collections import defaultdict

from .common import digest


def expand_member_arrays(facts):
    """Expand indexed record fields without promoting a field access to the root."""
    by_symbol = defaultdict(list)
    for access in facts['accesses']:
        by_symbol[access['symbol_id']].append(access)
    for root in facts['variables']:
        if not root.get('is_struct'):
            continue
        definitions = root.get('member_definitions', [])
        for field in list(definitions):
            if not field.get('is_array'):
                continue
            prefix = field['field_path']
            pattern = re.compile('^' + re.escape(prefix) + r'(\[(?:\d+|\*)\])(.*)$')
            indices = set()
            for access in by_symbol[root['symbol_id']]:
                path = access.get('access_path', '').replace('/', '.').lstrip('.').replace('.[', '[')
                match = pattern.match(path)
                if match:
                    indices.add(match[1])
            if not indices:
                continue
            templates = [d for d in definitions if d['field_path'].startswith(prefix + '[*].')]
            definitions[:] = [d for d in definitions if d not in templates]
            field['is_struct'] = True  # container, never a standalone verdict
            for index in sorted(indices):
                element_size = field.get('array_element_size_bytes', field.get('size_bytes'))
                delta_bits = int(index[1:-1]) * element_size * 8 if index != '[*]' and element_size else None
                element_offset = (field['offset_bits'] + delta_bits
                                  if field.get('offset_bits') is not None and delta_bits is not None else None)
                element = dict(field, field_path=prefix + index, name=field['name'] + index,
                    is_array=False, is_struct=bool(field.get('array_element_is_struct')),
                    type=field.get('array_element_type', field['type']),
                    size_bytes=element_size, offset_bits=element_offset)
                definitions.append(element)
                for template in templates:
                    offset = (template['offset_bits'] + delta_bits
                              if template.get('offset_bits') is not None and delta_bits is not None else None)
                    definitions.append(dict(template, field_path=template['field_path'].replace(prefix+'[*]', prefix+index, 1),
                                            offset_bits=offset))
            generated = []
            for access in by_symbol[root['symbol_id']]:
                path = access.get('access_path', '').replace('/', '.').lstrip('.').replace('.[', '[')
                match = pattern.match(path)
                if not match:
                    continue
                index, suffix = match.groups()
                access['access_path'] = prefix + index + suffix
                for target in sorted(indices):
                    if target == index or (index != '[*]' and target != '[*]'):
                        continue
                    clone = copy.deepcopy(access)
                    clone.update(access_path=prefix + target + suffix,
                                 inherited_from_access_id=access['access_id'], access_scope='OVERLAPPING_ARRAY_ACCESS')
                    clone['access_id'] = 'A-' + digest([access['access_id'], clone['access_path']])[:20]
                    generated.append(clone)
            facts['accesses'].extend(generated)
            by_symbol[root['symbol_id']].extend(generated)


def canonicalize_arrays(facts):
    if facts.get('array_resources_canonicalized'):
        return
    roots = {v['symbol_id']: v for v in facts['variables'] if v.get('is_array')}
    indexed = defaultdict(set)
    for access in facts['accesses']:
        if access['symbol_id'] in roots:
            match = re.match(r'^/?(\[(?:\d+|\*)\])', access.get('access_path', ''))
            if match:
                indexed[access['symbol_id']].add(match[1])
    targets, additions = {}, []
    for sid, indices in indexed.items():
        root = roots[sid]
        root['resource_kind'] = 'ARRAY_CONTAINER'
        root['canonical_path'] = root['qualified_name']
        for index in sorted(indices):
            child = copy.deepcopy(root)
            child_sid = sid + '::element::' + index
            child.update(symbol_id=child_sid, name=root['name'] + index,
                qualified_name=root['qualified_name'] + index, canonical_path=root['qualified_name'] + index,
                array_root_symbol_id=sid, array_index=index, resource_kind='ARRAY_ELEMENT',
                is_array=False, is_struct=bool(root.get('array_element_is_struct')),
                is_union=bool(root.get('array_element_is_union')), type=root.get('array_element_type', root['type']),
                member_definitions=copy.deepcopy(root.get('member_definitions', [])))
            if root.get('array_size') and root.get('size_bytes'):
                child['size_bytes'] = root['size_bytes'] // root['array_size']
            targets[(sid, index)] = child
            additions.append(child)
        root['element_symbol_ids'] = [targets[(sid, i)]['symbol_id'] for i in sorted(indices)]
    rows = []
    for access in facts['accesses']:
        sid = access['symbol_id']
        if sid not in indexed:
            rows.append(access)
            continue
        match = re.match(r'^/?(\[(?:\d+|\*)\])(.*)$', access.get('access_path', ''))
        index, suffix = (match[1], match[2].lstrip('./')) if match else (None, '')
        for target_index in sorted(indexed[sid]):
            # '*' overlaps every element of THIS array, never another root.
            if index is not None and index != '[*]' and target_index not in {index, '[*]'}:
                continue
            target = targets[(sid, target_index)]
            row = copy.deepcopy(access)
            row.update(symbol_id=target['symbol_id'], access_path=suffix,
                canonical_path=target['canonical_path'], array_root_symbol_id=sid,
                storage_index=index or '[*]', canonical_array_index=target_index)
            if index != target_index:
                row['inherited_from_access_id'] = access['access_id']
                row['inherited_from_canonical_path'] = roots[sid]['qualified_name'] + (index or '')
                row['access_scope'] = 'OVERLAPPING_ARRAY_ACCESS'
            row['access_id'] = 'A-' + digest([access['access_id'], target['symbol_id']])[:20]
            rows.append(row)
    issues = []
    for issue in facts['unknowns']:
        sid = issue.get('symbol_id')
        if sid not in indexed:
            continue
        match = re.match(r'^/?(\[(?:\d+|\*)\])', issue.get('access_path', ''))
        index = match[1] if match else '[*]'
        for target_index in indexed[sid]:
            if index == '[*]' or target_index in {index, '[*]'}:
                issues.append(dict(issue, symbol_id=targets[(sid, target_index)]['symbol_id'],
                                   array_root_symbol_id=sid,
                                   access_path=issue.get('access_path', '')[match.end():].lstrip('./') if match else ''))
    facts['variables'].extend(additions)
    facts['accesses'] = rows
    facts['unknowns'].extend(issues)
    facts['array_resources_canonicalized'] = True


def propagate_overlapping_members(facts):
    """Union/bitfield accesses must never acquire a disjoint-field proof."""
    variables = {v['symbol_id']: v for v in facts['variables']}
    members = defaultdict(list)
    for variable in variables.values():
        if variable.get('resource_kind') == 'STRUCT_MEMBER':
            members[variable['root_symbol_id']].append(variable)
    def overlaps(member, other, root):
        return (root.get('is_union') or (member.get('is_bitfield_container') and other.get('is_bitfield_container'))
                or bool(set(member.get('overlap_groups', [])) & set(other.get('overlap_groups', []))))

    generated = []
    for access in list(facts['accesses']):
        member = variables.get(access['symbol_id'], {})
        root = variables.get(member.get('root_symbol_id'), {})
        if not root or member.get('resource_kind') != 'STRUCT_MEMBER':
            continue
        for other in members[root['symbol_id']]:
            if other['symbol_id'] == member['symbol_id']:
                continue
            if not overlaps(member, other, root):
                continue
            clone = copy.deepcopy(access)
            clone.update(symbol_id=other['symbol_id'], canonical_path=other['canonical_path'],
                field_path=other['field_path'], access_scope='OVERLAPPING_MEMBER_ACCESS',
                inherited_from_access_id=access['access_id'],
                inherited_from_canonical_path=member['canonical_path'])
            clone['access_id'] = 'A-' + digest([access['access_id'], other['symbol_id']])[:20]
            generated.append(clone)
    facts['accesses'].extend(generated)
    gaps = []
    for issue in list(facts['unknowns']):
        member = variables.get(issue.get('symbol_id'), {})
        root = variables.get(member.get('root_symbol_id'), {})
        if not root or member.get('resource_kind') != 'STRUCT_MEMBER':
            continue
        for other in members[root['symbol_id']]:
            if other['symbol_id'] != member['symbol_id'] and overlaps(member, other, root):
                gaps.append(dict(issue, symbol_id=other['symbol_id'], canonical_path=other['canonical_path'],
                                 inherited_object_uncertainty=True))
    facts['unknowns'].extend(gaps)


def path_may_cover(source, target):
    """Unknown index/whole-object effects cover only descendants of that path."""
    expression = re.escape(source).replace(r'\[\*\]', r'\[(?:\d+|\*)\]')
    return bool(re.match('^' + expression + r'(?:$|\.|\[)', target))


def add_disjoint_storage_proofs(facts):
    """Add auditable spatial proofs to variables already independently SAFE.

    Canonicalization separates storage before conflict analysis. Preserve why
    other contexts accessing the same containing object were excluded, without
    using this supplementary proof to erase any conflict or evidence gap.
    """
    variables = {variable['symbol_id']: variable for variable in facts['variables']}
    runtime_kinds = {'READ', 'WRITE', 'RMW', 'WHOLE_OBJECT_READ', 'WHOLE_OBJECT_WRITE', 'DMA_READ', 'DMA_WRITE'}
    writes = {'WRITE', 'RMW', 'WHOLE_OBJECT_WRITE', 'DMA_WRITE'}

    def extent(variable):
        if variable.get('is_bitfield_container') or '[*]' in variable.get('canonical_path', ''):
            return None
        size = variable.get('size_bytes')
        if not isinstance(size, int) or size <= 0:
            return None
        sid = variable['symbol_id']
        if variable.get('resource_kind') == 'STRUCT_MEMBER':
            parent = variables.get(variable.get('root_symbol_id'))
            base = extent(parent) if parent else None
            offset = variable.get('offset_bits')
            if base is None or offset is None or offset < 0:
                return None
            return base[0], base[1] + offset, base[1] + offset + size * 8
        if variable.get('array_root_symbol_id'):
            parent = variables.get(variable['array_root_symbol_id'])
            index = re.fullmatch(r'\[(\d+)\]', variable.get('array_index', ''))
            if not parent or not index or not parent.get('array_size') or not parent.get('size_bytes'):
                return None
            ordinal = int(index[1])
            if ordinal >= parent['array_size']:
                return None
            width = parent['size_bytes'] * 8 // parent['array_size']
            return parent['symbol_id'], ordinal * width, (ordinal + 1) * width
        return sid, 0, size * 8

    families = defaultdict(list)
    for variable in variables.values():
        if variable.get('static_classification') not in {'SAFE', 'SUSPECT', 'UNKNOWN'}:
            continue
        accesses = [access for access in variable.get('accesses', [])
                    if access['access_kind'] in runtime_kinds and access.get('reachability') != 'PROVEN_UNREACHABLE']
        span = extent(variable)
        if not accesses or not span:
            continue
        physical = set(variable.get('variable_evidence_slice', {}).get('physical_contexts', []))
        families[span[0]].append((variable, accesses, span, physical))
    for family in families.values():
        for variable, accesses, span, physical in family:
            if variable['static_classification'] != 'SAFE' or not physical:
                continue
            witnesses = []
            for other, other_accesses, other_span, other_physical in family:
                if other['symbol_id'] == variable['symbol_id'] or not other_physical - physical:
                    continue
                if not any(access['access_kind'] in writes for access in accesses + other_accesses):
                    continue
                if span[2] <= other_span[1] or other_span[2] <= span[1]:
                    witnesses.append(dict(symbol_id=other['symbol_id'], canonical_path=other.get('canonical_path'),
                        range_bits=[other_span[1], other_span[2]], physical_contexts=sorted(other_physical),
                        access_ids=[access['access_id'] for access in other_accesses]))
            variable['safe_reason_codes'] = [variable['safe_reason_code']]
            if witnesses:
                variable['safe_reason_codes'].append('SAFE_DISJOINT_STORAGE')
                variable['safe_evidence']['disjoint_storage'] = dict(proof='SAFE_DISJOINT_STORAGE',
                    root_symbol_id=span[0], range_bits=[span[1], span[2]], nonoverlapping_resources=witnesses,
                    basis='Clang object layout and constant array indices; half-open bit ranges')
