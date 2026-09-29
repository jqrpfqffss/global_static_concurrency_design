"""Recover Cortex-M execution entries from actual vector-table storage.

Section names are Cortex-M linker conventions, never project/function-name
exceptions. Slot identity preserves separate IRQs sharing the same callback.
"""
import re


SECTIONS = {'.isr_vector', '.vectors', '.vector_table', '.interrupt_vector'}


def recover_assembly_functions(source, file, functions):
    """Recover literal no-argument calls in explicitly delimited ARM functions.

    A verified vector slot supplies the execution context of an assembly
    wrapper. Its instructions do not supply a mask/initialization proof.
    Preprocessor/macro bodies, opaque operands and unbounded labels stay gaps.
    """
    clean = re.sub(r'/\*.*?\*/', lambda m: '\n' * m[0].count('\n'), source, flags=re.S)
    if re.search(r'^\s*(?:#|\.macro\b|\.include\b)', clean, re.M):
        return [], []
    lines = [re.split(r'//|\s@', line, maxsplit=1)[0].strip() for line in clean.splitlines()]
    typed = {match[1] for line in lines
             if (match := re.fullmatch(r'\.type\s+([A-Za-z_]\w*)\s*,\s*%function', line))}
    existing = {f['name']: f for f in functions}
    definitions, ranges = [], []
    for name in sorted(typed - existing.keys()):
        starts = [i for i, line in enumerate(lines) if line == name + ':']
        ends = [i for i, line in enumerate(lines) if re.fullmatch(r'\.size\s+' + re.escape(name) + r'\s*,.+', line)]
        if len(starts) != 1 or len(ends) != 1 or starts[0] >= ends[0]:
            continue
        first, last = starts[0], ends[0]
        if any(line.startswith('.section') for line in lines[first+1:last]):
            continue
        fid = 'assembly:' + file + ':' + name
        definitions.append(dict(function_id=fid, name=name, qualified_name=name+'()', linkage='EXTERNAL',
            parameter_count=0, return_type_kind='VOID', file=file, line=first+1, end_line=last+1,
            assembly_definition=True, entry_attributes=[]))
        ranges.append((fid, first, last))
    calls = []
    for fid, first, last in ranges:
        for index in range(first+1, last):
            match = re.fullmatch(r'(?:b|bl)(?:\.w)?\s+([A-Za-z_]\w*)', lines[index])
            callee = existing.get(match[1]) if match else None
            if (not callee or callee.get('parameter_count') != 0
                    or callee.get('return_type_kind') != 'VOID' and callee['name'] != 'main'):
                continue
            calls.append(dict(caller_function_id=fid, callee_function_id=callee['function_id'],
                callee_name=callee['name'], call_kind='ASSEMBLY_LITERAL_CALL', file=file, line=index+1,
                source_text=source.splitlines()[index], resolution='DELIMITED_ARM_FUNCTION_CALL'))
    return definitions, calls


def recover_assembly_vectors(source, file, functions_by_name):
    """Recover slots only when assembler directives preserve known layout.

    A textual .word count is unsound in the presence of .rept, conditional
    assembly, padding, or included bytes: an IRQ may be mistaken for reset.
    Unsupported layout retains function-local entry gaps instead of guessing.
    """
    source = re.sub(r'/\*.*?\*/', lambda match: '\n' * match[0].count('\n'), source, flags=re.S)
    sections, current = {}, None
    preprocessed = bool(re.search(r'^\s*#\s*(?:if|ifdef|ifndef|elif|else|include)\b', source, re.M))
    for line, raw in enumerate(source.splitlines(), 1):
        text = re.sub(r'@.*|//.*', '', raw).strip()
        section = re.match(r'\.(?:section|pushsection)\s+"?([.\w]+)', text)
        if section:
            current = section[1] if section[1] in SECTIONS else None
        elif re.match(r'\.(?:text|data|bss|popsection|previous)\b', text):
            current = None
        if current is None:
            continue
        state = sections.setdefault(current, dict(slot=0, valid=not preprocessed, entries=[], references=[]))
        for name in set(re.findall(r'\b[A-Za-z_]\w*\b', text)):
            for fid in functions_by_name.get(name, []):
                state['references'].append(dict(target_function_id=fid, file=file, line=line, source_text=raw))
        if section or not text or re.fullmatch(r'[A-Za-z_.$][\w.$]*:', text):
            continue
        words = re.fullmatch(r'\.(?:word|long|4byte)\s+(.+)', text)
        if words:
            for word in words[1].split(','):
                word = word.strip()
                symbol = re.fullmatch(r'([A-Za-z_]\w*)(?:\s*\+\s*1)?', word)
                if not symbol and not re.fullmatch(r'(?:0[xX][0-9A-Fa-f]+|\d+)', word):
                    state['valid'] = False
                for fid in functions_by_name.get(symbol[1] if symbol else '', []):
                    slot = state['slot']
                    if slot:
                        state['entries'].append(dict(function_id=fid, slot=slot,
                            kind='MAIN' if slot == 1 else 'ISR', vector='slot:' + str(slot),
                            unmaskable=slot in {2, 3}, file=file, line=line,
                            discovery='Cortex-M assembly vector section and verified ABI slot'))
                state['slot'] += 1
            continue
        reserve = re.fullmatch(r'\.(?:space|skip|zero)\s+(\d+)(?:\s*,\s*0)?', text)
        if reserve and int(reserve[1]) % 4 == 0:
            state['slot'] += int(reserve[1]) // 4
            continue
        if re.match(r'\.(?:global|globl|type|size|weak|thumb_set|set|equ)\b', text):
            continue
        if re.fullmatch(r'\.(?:align|p2align)\s+[012]|\.balign\s+[124]', text):
            continue
        # Initial alignment changes section placement, not vector-relative
        # slot offsets. Later alignment must be explicitly understood above.
        if state['slot'] == 0 and re.fullmatch(r'\.(?:align|p2align|balign)\s+\d+', text):
            continue
        state['valid'] = False
    entries, gaps = [], []
    for section, state in sections.items():
        if state['valid']:
            entries.extend(state['entries'])
        else:
            gaps.extend(dict(reference, kind='UNRESOLVED_VECTOR_ENTRY', section=section,
                reason='Assembler layout or preprocessing prevents proving the physical vector slot')
                for reference in state['references'])
    return entries, gaps


def recover_vector_entries(facts):
    from .target_set import point_targets
    variables = {v['symbol_id']: v for v in facts['variables'] if v.get('linker_section') in SECTIONS}
    entries = list(facts.get('assembly_vector_entries', []))
    for point in facts.get('pointer_targets', []):
        for sid, variable in variables.items():
            root = 'obj:' + sid
            if not point['location'].startswith(root + '/'):
                continue
            path = point['location'][len(root)+1:]
            slot = None
            match = re.fullmatch(r'\[(\d+)\]', path)
            if match:
                slot = int(match[1])
            else:
                match = re.fullmatch(r'(.+?)(?:/\[(\d+)\])?', path)
                field = next((f for f in variable.get('member_definitions', [])
                              if f['field_path'] == match[1].replace('/', '.')), None) if match else None
                if field and field.get('offset_bits') is not None and field['offset_bits'] % 32 == 0:
                    slot = field['offset_bits'] // 32 + int(match[2] or 0)
            if slot is None:
                for target in point_targets(facts, point):
                    if target.startswith('fn:'):
                        facts['unknowns'].append(dict(kind='UNRESOLVED_VECTOR_ENTRY',
                            target_function_id=target[3:], file=variable.get('definition_file'),
                            line=variable.get('definition_line'), storage_symbol_id=sid,
                            reason='Vector-table index or layout is not statically known'))
                continue
            if slot == 0:
                continue
            for target in point_targets(facts, point):
                if target.startswith('fn:'):
                    entries.append(dict(function_id=target[3:], slot=slot,
                        kind='MAIN' if slot == 1 else 'ISR', vector='slot:' + str(slot),
                        unmaskable=slot in {2, 3}, storage_symbol_id=sid,
                        file=variable.get('definition_file'), line=variable.get('definition_line'),
                        discovery='Cortex-M vector table section and ABI slot'))
    facts['vector_entries'] = entries
    # Taking an address for a recovered hardware slot is a resolved entry,
    # not an unknown caller. Other opaque uses of the same function remain.
    recovered = {(e['function_id'], e['file'], e['line']) for e in entries}
    recovered_functions = {e['function_id'] for e in entries}
    facts['unknowns'] = [u for u in facts['unknowns'] if not (
        u['kind'] == 'FUNCTION_ADDRESS' and (
            u.get('target_function_id') in recovered_functions and not u.get('actual_escape') or
            (u.get('target_function_id'), u.get('file'), u.get('line')) in recovered and
            u.get('reason') == 'Callback stored in externally visible storage'))]
    return entries


def resolve_assembly_references(facts):
    """Discharge exact vector slots and symbol declarations before refinement.

    An IRQ function can still be called or exported by other assembly code.
    Recognizing its vector therefore cannot clear every reference to its name.
    """
    vector_sites = {(entry['function_id'], entry['file'], entry['line'])
                    for entry in facts.get('assembly_vector_entries', [])}
    functions = {f['function_id']: f for f in facts['functions']}
    calls = {(call['callee_function_id'], call['file'], call['line'])
             for call in facts['calls'] if call.get('call_kind') == 'ASSEMBLY_LITERAL_CALL'}
    resolved, remaining = [], []
    for issue in facts['unknowns']:
        if issue['kind'] != 'ASSEMBLY_FUNCTION_REFERENCE':
            remaining.append(issue)
            continue
        target = issue.get('target_function_id')
        name = functions.get(target, {}).get('name', '')
        text = issue.get('source_text', '').strip()
        declaration = re.fullmatch(r'\.(?:weak|global|globl|extern|type|size)\s+'
                                  + re.escape(name) + r'(?:\s*,[^\n]*)?\s*', text) if name else None
        alias_definition = re.fullmatch(r'\.(?:thumb_set|set)\s+' + re.escape(name)
                                       + r'\s*,\s*[A-Za-z_]\w*\s*', text) if name else None
        vector = (target, issue.get('file'), issue.get('line')) in vector_sites
        call = (target, issue.get('file'), issue.get('line')) in calls
        definition = functions.get(target, {})
        label = definition.get('assembly_definition') and text == name + ':'
        section = re.fullmatch(r'\.section\s+[^\s,]+(?:\s*,.*)?', text)
        if vector or declaration or alias_definition or call or label or section:
            resolved.append(dict(issue, resolution=('VERIFIED_VECTOR_SLOT' if vector else
                'DELIMITED_ARM_FUNCTION_CALL' if call else 'SYMBOL_DECLARATION')))
        else:
            remaining.append(issue)
    facts.setdefault('resolved_assembly_references', []).extend(resolved)
    facts['unknowns'] = remaining
