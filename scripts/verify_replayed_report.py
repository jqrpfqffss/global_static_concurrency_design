"""Verify complete controlled-render artifacts; never label them native acceptance."""
import argparse
from contextlib import closing
import gc
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ecra.common import read_json,write_json
from ecra.shared_json import logical_digest
from ecra.workflow import read_saved_json,clean_report,file_digest
from scripts.validate_large_report import audit_fact_database


def verify(evidence):
    evidence=Path(evidence)
    replay=read_json(evidence/'replay-result.json');proof=read_json(evidence/'render-proof.json')
    if (replay.get('full_scan_acceptance') is not False or replay.get('safety_report_valid') is not False
            or not replay.get('full_analysis_complete') or not replay.get('report_generation_complete')
            or not replay.get('solver_fixed_points_complete') or not proof.get('complete')):
        raise ValueError('受控报告尚未完整生成，禁止记录通过')
    result=verify_artifacts(evidence/'rendered',proof)
    write_json(evidence/'render-verification.json',result)
    return result


def verify_artifacts(folder,proof):
    """Audit stored values independently of extraction/analysis execution."""
    started=time.monotonic();folder=Path(folder)
    if not proof.get('complete'):
        raise ValueError('完整逻辑值证明缺失，禁止记录通过')
    if read_json(folder/'result_validity.json').get('analysis_valid') is not False:
        raise ValueError('受控报告不能冒充有效原生安全报告')
    print('核对完整事实逻辑值与来源摘要…',flush=True)
    facts=read_saved_json(folder/'facts.json',canonical_accesses=True)
    actual=logical_digest(facts)
    counts={key:len(value) for key,value in facts.items() if isinstance(value,list)}
    if actual!=proof['facts_logical_digest'] or counts!=proof['fact_counts']:
        raise ValueError('完整事实往返不一致，禁止发布或截断证据')
    del facts;gc.collect()
    print('核对完整静态报告逻辑值…',flush=True)
    report=read_saved_json(folder/'reports/global_static_concurrency.json')
    if logical_digest(clean_report(report))!=proof['static_report_logical_digest']:
        raise ValueError('完整静态报告往返不一致')
    del report;gc.collect()
    print('核对 JSON/SQLite 完整表、指针池和数据库完整性…',flush=True)
    with tempfile.TemporaryDirectory(prefix='ecra replay audit ') as temp, \
            closing(sqlite3.connect(f'{(folder/"facts.db").as_uri()}?mode=ro',uri=True)) as source, \
            closing(sqlite3.connect(str(Path(temp)/'audit.db'))) as index:
        audit=audit_fact_database(folder/'facts.json',source,index)
        integrity=source.execute('PRAGMA integrity_check').fetchone()[0]
    if audit['differences'] or audit['pools']['error_count'] or not audit['solver_fixed_points_complete'] or integrity!='ok':
        raise ValueError('完整 JSON/SQLite 或指针池校验失败')
    result=dict(complete=True,controlled_replay=True,native_acceptance=False,safety_report_valid=False,
        facts_logical_digest=actual,facts_sha256=file_digest(folder/'facts.json'),
        static_report_logical_digest=proof['static_report_logical_digest'],fact_counts=counts,
        classifications=proof['classifications'],variable_accountability=proof['variable_accountability'],
        database=audit,sqlite_integrity=integrity,seconds=time.monotonic()-started)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--evidence',type=Path,required=True)
    args=parser.parse_args();result=verify(args.evidence.resolve())
    print(json.dumps(dict(complete=result['complete'],native_acceptance=False,seconds=result['seconds'])))


if __name__=='__main__':main()
