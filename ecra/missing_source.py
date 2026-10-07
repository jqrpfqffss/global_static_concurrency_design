"""Conservative identifier evidence for active translation units that failed parsing.

Successful preprocessing proves which identifier spellings survived the exact
build macros and included headers. A failed or unavailable preprocessor gives
no negative evidence: every exported name remains possibly referenced.
"""

import hashlib
import re
import subprocess


_OUTPUT_OPTIONS = {'-o', '-MF', '-MT', '-MQ', '-MJ', '-serialize-diagnostics'}
_SIDE_EFFECT_OPTIONS = {'-c', '-M', '-MM', '-MD', '-MMD', '-MP', '-save-temps'}


def _preprocess_command(arguments):
    if not arguments or any(not isinstance(arg, str) for arg in arguments):
        return None
    result = []
    skip_next = False
    for arg in arguments:
        if skip_next:
            skip_next = False
            continue
        if arg in _OUTPUT_OPTIONS:
            skip_next = True
            continue
        if arg in _SIDE_EFFECT_OPTIONS or arg.startswith('-save-temps='):
            continue
        if arg.startswith('-o') and arg != '-o':
            continue
        # Dependency output embedded in a driver option could write beside the
        # source. In that case do not run the probe or claim negative evidence.
        if arg.startswith(('-Wp,-MD', '-Wp,-MMD', '-MF', '-MJ')):
            return None
        result.append(arg)
    if skip_next or not result:
        return None
    return [result[0], '-E', '-o', '-', *result[1:]]


def preprocess_failed_units(facts):
    """Attach complete per-variant identifier sets, or an explicit failure."""
    rows = []
    for unit in facts.get('translation_units', ()):
        if unit.get('parse_status') != 'FAILED':
            continue
        row = dict(source_file=unit.get('source_file'), tu_id=unit.get('tu_id'),
                   status='UNAVAILABLE')
        command = _preprocess_command(unit.get('original_arguments'))
        if command and unit.get('directory'):
            try:
                probe = subprocess.run(command, cwd=unit['directory'],
                                       capture_output=True, timeout=60, check=False)
                if probe.returncode == 0 and len(probe.stdout) <= 64 * 1024 * 1024:
                    opaque_assembly = bool(re.search(rb'\b(?:asm|__asm|__asm__)\b', probe.stdout))
                    row.update(status='OPAQUE_ASM' if opaque_assembly else 'COMPLETE',
                               command_sha256=hashlib.sha256('\0'.join(command).encode(
                                   'utf-8', errors='surrogatepass')).hexdigest(),
                               output_sha256=hashlib.sha256(probe.stdout).hexdigest(),
                               identifiers=sorted({word.decode('ascii') for word in
                                   re.findall(rb'\b[A-Za-z_][A-Za-z_0-9]*\b', probe.stdout)}))
                    if opaque_assembly:
                        row['reason'] = 'inline assembly in unparsed source may access unnamed storage'
                else:
                    row['reason'] = 'preprocessor failed or output exceeded 64 MiB'
            except (OSError, subprocess.TimeoutExpired) as exc:
                row['reason'] = type(exc).__name__
        rows.append(row)
    facts['failed_tu_preprocessing'] = rows
    return rows


def may_reference(facts, file, name):
    """Return False only when every failed variant excludes an ASCII name."""
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', name):
        return True
    rows = [row for row in facts.get('failed_tu_preprocessing', ())
            if row.get('source_file') == file]
    return not rows or any(row.get('status') != 'COMPLETE'
                           or name in row.get('identifiers', ()) for row in rows)


def complete_identifiers(facts, file):
    rows = [row for row in facts.get('failed_tu_preprocessing', ())
            if row.get('source_file') == file]
    if not rows or any(row.get('status') != 'COMPLETE' for row in rows):
        return None
    return set().union(*(row['identifiers'] for row in rows))
