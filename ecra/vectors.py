"""Recover Cortex-M execution entries from actual vector-table storage.

Section names are Cortex-M linker conventions, never project/function-name
exceptions. Slot identity preserves separate IRQs sharing the same callback.
"""
import re


SECTIONS = {'.isr_vector', '.vectors', '.vector_table', '.interrupt_vector'}


def recover_vector_entries(facts):
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
            if slot is None or slot == 0:
                continue
            for target in point['targets']:
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
