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
                element = dict(field, field_path=prefix + index, name=field['name'] + index,
                    is_array=False, is_struct=bool(field.get('array_element_is_struct')),
                    type=field.get('array_element_type', field['type']),
                    size_bytes=field.get('array_element_size_bytes', field.get('size_bytes')))
                definitions.append(element)
                for template in templates:
                    definitions.append(dict(template, field_path=template['field_path'].replace(prefix+'[*]', prefix+index, 1)))
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
