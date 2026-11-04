import json
from pathlib import Path
import sys
sys.path.insert(0,'H:/global_static_concurrency_design')
from ecra.report_package import export_report, import_report, sha256
from ecra.workspace import formal_workspace
from ecra.common import write_json

w=Path('H:/ECRAStudio-data/rearchitecture-20261031/continuation-h3')
source=w/'multicore-native-gui-v1'
dest=w/'multicore-native-gui-v3'
dest.mkdir(exist_ok=False)
record=json.loads((source/'acceptance.json').read_text('utf-8'))
original_data=Path(record['data_root']);data=dest/'data'
for item in record['inputs']:
    scan=original_data/'scans'/item['scan_id']
    before={p.name:sha256(p) for p in [scan/'scan.db',scan/'reviews.db']}
    package=dest/(item['scan_id']+'.ecra-report')
    export_report(scan,package)
    restored=import_report(package,data)
    assert restored['scan_id']==item['scan_id']
    copy=data/'scans'/item['scan_id']
    assert sha256(copy/'scan.db')==before['scan.db']
    assert sha256(copy/'reviews.db')==before['reviews.db']
    assert before=={p.name:sha256(p) for p in [scan/'scan.db',scan/'reviews.db']}
ws=formal_workspace(record['project_root'],dict(output=dict(location='custom',custom_dir=str(data))))
pointer=Path(ws.project_workspace)/'latest-scan.json'
write_json(pointer,dict(project_id=ws.project_id,scan_id=record['inputs'][-1]['scan_id']))
record.update(data_root=str(data),scope='Independent strict complete standard export/import copy of v1 approved F030 native aliases and original human events; no new native scan and not dual-core G2.',
              native_scan_executed_for_this_copy=False,original_producer_receipt_sha256=sha256(source/'acceptance.json'))
write_json(dest/'acceptance.json',record)
print(json.dumps(dict(passed=True,data_root=str(data),inputs=len(record['inputs']))))
