"""逐字段核对已保存 JSON 与 SQLite；不执行分析或模型，不发布安全结论。"""
import argparse
from contextlib import closing
import gc
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ecra.shared_json import DatabasePool
from ecra.workflow import read_saved_json


class TypedDigest:
    """Identity memo holds strong references; array order and scalar types matter."""
    def __init__(self):
        self.memo={};self.active=set()

    def digest(self,value):
        if not isinstance(value,(dict,list)):
            return hashlib.sha256(b'S'+json.dumps(value,ensure_ascii=False,separators=(',',':')).encode('utf-8')).digest()
        ident=id(value)
        if ident in self.active:raise ValueError('完整证据包含循环结构')
        previous=self.memo.get(ident)
        if previous is not None:
            if previous[0] is not value:raise ValueError('证据摘要身份冲突')
            return previous[1]
        self.active.add(ident)
        sha=hashlib.sha256(b'D' if isinstance(value,dict) else b'L')
        if isinstance(value,dict):
            for key in sorted(value):sha.update(self.digest(key));sha.update(self.digest(value[key]))
        else:
            for child in value:sha.update(self.digest(child))
        sha.update(str(len(value)).encode('ascii'));result=sha.digest()
        self.active.remove(ident);self.memo[ident]=(value,result)
        return result


def identifier(value):
    return '"'+value.replace('"','""')+'"'


def audit_tables(connection,pool,tables,actual_digest):
    expected_digest=TypedDigest();counts={};cells=nested=0
    for table,rows in tables.items():
        print('逐字段核对：'+table,flush=True)
        columns=sorted({key for row in rows for key in row}) or ['empty']
        actual_columns=[r[1] for r in connection.execute('PRAGMA table_info('+identifier(table)+')')]
        if columns!=actual_columns:raise ValueError('数据库字段不一致：'+table)
        cursor=connection.execute('SELECT * FROM '+identifier(table)+' ORDER BY rowid')
        count=0
        for expected in rows:
            actual=cursor.fetchone()
            if actual is None:raise ValueError('数据库缺少记录：'+table)
            count+=1
            for key,stored in zip(columns,actual):
                value=expected.get(key);cells+=1
                if isinstance(value,(dict,list)):
                    nested+=1
                    if not isinstance(stored,str):raise ValueError('嵌套证据不是 JSON：'+table+'.'+key)
                    restored=pool.loads(stored)
                    if expected_digest.digest(value)!=actual_digest.digest(restored):
                        raise ValueError(f'数据库完整证据不一致：{table} 第 {count} 条 {key}')
                else:
                    # The existing SQLite schema binds top-level booleans as
                    # INTEGER; nested JSON booleans retain their actual type.
                    value=int(value) if isinstance(value,bool) else value
                    if type(value) is not type(stored) or value!=stored:
                        raise ValueError(f'数据库标量不一致：{table} 第 {count} 条 {key}')
        if cursor.fetchone() is not None:raise ValueError('数据库包含额外记录：'+table)
        counts[table]=count
    expected_digest.memo.clear()
    return counts,cells,nested


def verify(folder):
    start=time.monotonic();folder=Path(folder)
    tables_verified={};cells=nested=0
    with closing(sqlite3.connect((folder/'facts.db').resolve().as_uri()+'?mode=ro',uri=True)) as connection:
        print('读取完整 SQLite 共享证据池…',flush=True)
        pool=DatabasePool(connection);actual_digest=TypedDigest()
        for path,is_report in [(folder/'facts.json',False),(folder/'reports/global_static_concurrency.json',True)]:
            print('读取对应完整 JSON：'+path.name,flush=True)
            value=read_saved_json(path,canonical_accesses=not is_report)
            if is_report:
                tables=dict(findings=value['findings'],review_safe_samples=value.get('review_safe_samples',[]))
            else:
                tables={key:rows for key,rows in value.items() if isinstance(rows,list) and (not rows or isinstance(rows[0],dict))}
            counts,n,nj=audit_tables(connection,pool,tables,actual_digest)
            tables_verified.update(counts);cells+=n;nested+=nj
            del tables,value;gc.collect()
        actual_tables={r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        unexpected=actual_tables-set(tables_verified)-DatabasePool.TABLES-{'pointer_target_atoms','pointer_target_sets'}
        if unexpected:raise ValueError('数据库包含未归账表：'+','.join(sorted(unexpected)))
    return dict(complete=True,kind='DATABASE_ALL_VALUES_VERIFICATION',native_acceptance=False,
        safety_report_valid=False,analysis_reexecuted=False,review_executed=False,
        rows=tables_verified,cells=cells,nested_json_cells=nested,seconds=time.monotonic()-start)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--folder',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.resolve().is_relative_to(args.folder.resolve()):
        parser.error('校验收据必须保存在待校验产物目录之外')
    result=dict(complete=False,kind='DATABASE_ALL_VALUES_VERIFICATION',native_acceptance=False,safety_report_valid=False)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    try:result=verify(args.folder)
    except BaseException as error:
        result['error']=dict(type=type(error).__name__,message=str(error))
        args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        raise
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':main()
