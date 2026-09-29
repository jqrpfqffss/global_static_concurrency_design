"""Cluster UNKNOWN evidence by source site and count distinct storage objects."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path


def cluster(rows):
    unknown = [row for row in rows if row.get('static_classification') == 'UNKNOWN']
    codes = Counter(code for row in unknown for code in set(row.get('unknown_reason_codes', [])))
    sites, names = defaultdict(set), {}
    for row in unknown:
        ident = row['symbol_id']
        names[ident] = row.get('qualified_name', ident)
        for gap in row.get('blocking_evidence', []):
            key = (gap.get('reason_code'), gap.get('kind'), gap.get('file'), gap.get('line'), gap.get('reason'))
            sites[key].add(ident)
    result = []
    for key, affected in sorted(sites.items(), key=lambda item: (-len(item[1]), str(item[0]))):
        code, kind, file, line, reason = key
        result.append(dict(reason_code=code, kind=kind, file=file, line=line, reason=reason,
            blocker_fanout=len(affected), unknown_percent=round(100*len(affected)/max(1,len(unknown)),2),
            symbol_ids=sorted(affected), examples=sorted(names[ident] for ident in affected)[:5]))
    return dict(unknown=len(unknown), reason_distribution=dict(codes), sites=result,
        counting='Distinct canonical variables per site; overlapping reasons must not be summed')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('folder', type=Path)
    args = parser.parse_args()
    data = cluster(json.loads((args.folder/'classification-index.json').read_text(encoding='utf-8')))
    (args.folder/'unknown-top-sites.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    print('UNKNOWN', data['unknown'], data['reason_distribution'])
    for row in data['sites'][:10]:
        print(row['kind'], str(row['file'])+':'+str(row['line']), row['blocker_fanout'])


if __name__ == '__main__':
    main()
