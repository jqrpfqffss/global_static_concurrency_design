"""Compare complete SQLite evidence tables with bounded Python memory.

Row ordering is normalized in a temporary SQLite database; nested JSON keys
are canonicalized but no evidence values or list entries are discarded.
"""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile

REVIEW_TABLES = {'findings', 'review_safe_samples'}


def tables_at(path):
    with closing(sqlite3.connect(f'{path.resolve().as_uri()}?mode=ro',uri=True)) as source:
        return {row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")} - REVIEW_TABLES


def fingerprint(path, tables=None):
    result = {}
    with closing(sqlite3.connect(f'{path.resolve().as_uri()}?mode=ro',uri=True)) as source, \
            tempfile.TemporaryDirectory(prefix='ecra fact comparison ') as temp:
        with closing(sqlite3.connect(str(Path(temp)/'hashes.db'))) as index:
            index.execute('PRAGMA temp_store=FILE')
            index.execute('CREATE TABLE hashes (digest BLOB)')
            existing = {row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table in sorted(tables if tables is not None else tables_at(path)):
                if table not in existing:
                    result[table] = dict(missing=True)
                    continue
                columns = [row[1] for row in source.execute(f'PRAGMA table_info("{table}")')]
                def rows():
                    for row in source.execute(f'SELECT * FROM "{table}"'):
                        value = {}
                        for key, item in zip(columns,row):
                            if isinstance(item,str) and item.startswith(('[','{')):
                                try: item = json.loads(item)
                                except json.JSONDecodeError: pass
                            value[key] = item
                        encoded = json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()
                        yield (hashlib.sha256(encoded).digest(),)
                with index:
                    index.execute('DELETE FROM hashes')
                    index.executemany('INSERT INTO hashes VALUES (?)', rows())
                sha = hashlib.sha256(); count = 0
                for row in index.execute('SELECT digest FROM hashes ORDER BY digest'):
                    sha.update(row[0]);count += 1
                result[table] = dict(count=count,sha256=sha.hexdigest())
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('before',type=Path)
    parser.add_argument('after',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    tables = sorted(tables_at(args.before) | tables_at(args.after))
    first, second = fingerprint(args.before, tables), fingerprint(args.after, tables)
    result = dict(identical=first==second,tables={key:dict(before=first[key],after=second[key],
                  identical=first[key]==second[key]) for key in tables},
                  scope='all persisted fact tables, including bindings, solved targets, NVIC and build metadata; review receipts excluded')
    args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(dict(identical=result['identical'],output=str(args.output))))
    return 0 if result['identical'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
