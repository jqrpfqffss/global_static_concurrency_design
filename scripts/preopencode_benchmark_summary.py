"""Summarize large facts files without loading duplicate call evidence in RAM."""
import argparse
from collections import Counter
import json
from pathlib import Path


def records(path, key='variables'):
    decoder = json.JSONDecoder()
    with Path(path).open(encoding='utf-8') as stream:
        buffer = ''
        token = '"' + key + '": ['
        while token not in buffer:
            chunk = stream.read(262144)
            if not chunk:
                raise ValueError('Missing array ' + key)
            buffer += chunk
        buffer = buffer.split(token, 1)[1]
        while True:
            buffer = buffer.lstrip(' \r\n\t,')
            if buffer.startswith(']'):
                return
            try:
                row, end = decoder.raw_decode(buffer)
            except json.JSONDecodeError:
                chunk = stream.read(262144)
                if not chunk:
                    raise
                buffer += chunk
                continue
            yield row
            buffer = buffer[end:]


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
            unknown.update(v.get('unknown_reason_codes') or v.get('screening_blockers', []))
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
