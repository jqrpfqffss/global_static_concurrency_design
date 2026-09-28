"""Summarize large facts files without loading duplicate call evidence in RAM."""
import argparse
from collections import Counter
import json
from pathlib import Path
import re


def records(path, key='variables'):
    """Read each object once, even when one record spans hundreds of MB.

    Repeated raw_decode on incomplete records repeatedly reparsed the same
    growing prefix. This lexical boundary scan is linear in bytes and invokes
    json.loads exactly once per complete object. It ignores brackets in strings
    and carries quoted-string/escape state across chunk boundaries.
    """
    key_pattern = re.compile(rb'"' + re.escape(key.encode()) + rb'"\s*:\s*\[')
    tokens = re.compile(rb'"|\\.|[{}\[\]]|\\$', re.S)
    with Path(path).open('rb') as stream:
        chunk = b''
        while True:
            data = stream.read(1024 * 1024)
            if not data:
                raise ValueError('Missing array ' + key)
            chunk += data
            match = key_pattern.search(chunk)
            if match:
                chunk = chunk[match.end():]
                break
            chunk = chunk[-256:]
        depth, quoted, escaped_next = 0, False, False
        pieces = []
        while chunk:
            begin = 0 if depth else None
            scan_from = 1 if escaped_next else 0
            escaped_next = False
            for match in tokens.finditer(chunk, scan_from):
                token = match.group()
                if token.startswith(b'\\'):
                    if quoted and len(token) == 1:
                        escaped_next = True
                    continue
                if token == b'"':
                    quoted = not quoted
                    continue
                if quoted:
                    continue
                if token in (b'{', b'['):
                    if not depth:
                        begin = match.start()
                    depth += 1
                elif token in (b'}', b']'):
                    if not depth:
                        return
                    depth -= 1
                    if not depth:
                        pieces.append(chunk[begin:match.end()])
                        yield json.loads(b''.join(pieces))
                        pieces.clear()
                        begin = None
            if begin is not None:
                pieces.append(chunk[begin:])
            chunk = stream.read(1024 * 1024)
        if depth or quoted:
            raise ValueError('Truncated JSON array ' + key)


def summarize(folder):
    classes, kinds, safe, unknown = Counter(), Counter(), Counter(), Counter()
    roots = {}
    for v in records(folder/'facts.json'):
        state = v.get('static_classification')
        if state not in {'SAFE', 'SUSPECT', 'UNKNOWN'}:
            continue
        classes[state] += 1
        kinds[v['kind']] += 1
        if state == 'SAFE':
            safe[v.get('safe_reason_code') or v.get('screening_reason')] += 1
        elif state == 'UNKNOWN':
            blockers = v.get('unknown_reason_codes') or v.get('screening_blockers', [])
            unknown.update(b if isinstance(b,str) else b.get('code',b.get('kind','UNSPECIFIED')) for b in blockers)
        root = v.get('array_root_symbol_id') or v.get('root_symbol_id') or v['symbol_id']
        root = root.split('::element::', 1)[0]
        roots[root] = max(roots.get(root, 'SAFE'), state, key={'SAFE':0,'UNKNOWN':1,'SUSPECT':2}.get)
    total = sum(classes.values())
    summary = dict(total=total, classifications=dict(classes), by_kind=dict(kinds),
        percentages={k: round(100*classes[k]/max(1,total),2) for k in ('SAFE','SUSPECT','UNKNOWN')},
        safe_reasons=dict(safe), unknown_reasons=dict(unknown), review_queue=classes['SUSPECT']+classes['UNKNOWN'],
        root_storage_total=len(roots), root_classifications=dict(Counter(roots.values())))
    existing = folder/'summary.json'
    if existing.exists():
        summary = dict(json.loads(existing.read_text(encoding='utf-8')), **summary)
    existing.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('folder', type=Path)
    args = parser.parse_args()
    print(json.dumps(summarize(args.folder),ensure_ascii=False,indent=2))
