from contextlib import closing
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ecra.scan_store import EvidenceProvider,publish_scan,connect_readonly
from ecra.report_package import sha256
from ecra.workflow import clean_report
from scripts.compare_native_graphs import compare,NormalizedGraph


class NativeGraphComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='ECRA graph comparison ');self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)
        self.facts=dict(variables=[],future=[False,0,1,-0.0,0.0,2**80,'中文\ud800',dict(b=2,a=1),[1,1,2]])
        self.report=dict(generated_at='before',fingerprint='one',run_status='REVIEWING',
            findings=[dict(finding_id='f1',status='DONE',review=dict(verdict='old'),
                static_classification='UNKNOWN',proof=dict(all_edges=[1,1,2],future='preserve'))],
            workspace=dict(project_id='p',project_root='same',results_root='before'),
            coverage=dict(consumed_inputs={'a.c':dict(status='OK',sha256='fixed',size=10,read_started_ns=1,read_completed_ns=2)}))

    def publish(self,name,facts=None,report=None):
        path=self.folder/(name+'.db')
        publish_scan(path,self.facts if facts is None else facts,self.report if report is None else report,scan_id=name,project_id='p')
        return path

    def test_normalized_hash_matches_existing_clean_report_and_exact_documented_envelope(self):
        original=self.publish('original');report=clean_report(copy.deepcopy(self.report))
        report.pop('generated_at');report.pop('fingerprint');report['workspace'].pop('results_root')
        report['coverage']['consumed_inputs']['a.c'].pop('read_started_ns')
        report['coverage']['consumed_inputs']['a.c'].pop('read_completed_ns')
        reference=self.publish('reference',report=report)
        with closing(connect_readonly(original)) as conn:
            graph=NormalizedGraph(conn)
            self.assertEqual(graph.hash(graph.root('report'),'report',['report']),EvidenceProvider(reference).metadata()['report_hash'])

    def test_runtime_only_difference_is_allowed_without_full_restore_and_raw_values_remain_referenced(self):
        before=self.publish('before');changed=copy.deepcopy(self.report)
        changed.update(generated_at='after',fingerprint='two',run_status='OTHER')
        changed['findings'][0]['status']='TECH_FAILED';changed['findings'][0]['review']=dict(error='tool missing')
        changed['workspace']['results_root']='after'
        changed['coverage']['consumed_inputs']['a.c'].update(read_started_ns=3,read_completed_ns=4)
        after=self.publish('after',report=changed);hashes=[sha256(before),sha256(after)]
        envelope=self.folder/'envelope.jsonl'
        with patch.object(EvidenceProvider,'load',side_effect=AssertionError('full fact restore forbidden')):
            result=compare(before,after,envelope=envelope)
        self.assertTrue(result['passed']);self.assertEqual([sha256(before),sha256(after)],hashes)
        records=[json.loads(line) for line in envelope.read_text(encoding='utf-8').splitlines()]
        self.assertTrue(any(row['path']==['report','coverage','consumed_inputs','a.c','read_started_ns'] and row['original']['exact_value']=='3' for row in records))
        self.assertTrue(any(row['path']==['report','workspace','results_root'] and row['original']['value']=='before' for row in records))

    def test_every_static_field_list_order_duplicate_and_scalar_type_remains_significant(self):
        before=self.publish('before')
        cases=[]
        changed=copy.deepcopy(self.facts);changed['future'][0]=0;cases.append(('bool-type',changed,None))
        changed=copy.deepcopy(self.facts);changed['future'][3]=0.0;cases.append(('signed-zero',changed,None))
        changed=copy.deepcopy(self.facts);changed['future'][-1]=[1,2,1];cases.append(('array-order',changed,None))
        changed=copy.deepcopy(self.facts);changed['future'][-1]=[1,2];cases.append(('multiplicity',changed,None))
        changed=copy.deepcopy(self.facts);changed['future'][-2]=dict(a=1,b=2);cases.append(('field-order',changed,None))
        changed=copy.deepcopy(self.report);changed['findings'][0]['static_classification']='SAFE_PROVEN';cases.append(('classification',None,changed))
        changed=copy.deepcopy(self.report);changed['findings'][0]['proof']['future']='changed';cases.append(('unknown-field',None,changed))
        for name,facts,report in cases:
            with self.subTest(name=name):
                after=self.publish(name,facts=facts,report=report);result=compare(before,after)
                self.assertFalse(result['passed'])
                self.assertTrue(any(result['differences'].values()))

    def test_only_named_input_read_timings_are_removed_and_nested_similar_names_are_not_hidden(self):
        report=copy.deepcopy(self.report);report['coverage']['consumed_inputs']['a.c']['read_fake_ns']=1
        report['findings'][0]['proof']['generated_at']='static evidence field'
        before=self.publish('before',report=report)
        for name,mutate in [('future-time',lambda r:r['coverage']['consumed_inputs']['a.c'].update(read_fake_ns=2)),
                ('input-size',lambda r:r['coverage']['consumed_inputs']['a.c'].update(size=11)),
                ('nested-generated',lambda r:r['findings'][0]['proof'].update(generated_at='changed'))]:
            changed=copy.deepcopy(report);mutate(changed)
            self.assertFalse(compare(before,self.publish(name,report=changed))['passed'],name)

    def test_malformed_or_corrupted_complete_report_cannot_be_blessed(self):
        before=self.publish('before');after=self.publish('no-findings',report=dict(coverage={}))
        with self.assertRaisesRegex(ValueError,'lacks findings'):compare(before,after)
        import sqlite3
        with sqlite3.connect(after) as conn:conn.execute("UPDATE nodes SET value=? WHERE kind='str'",(b'corrupt',))
        # There may be no string nodes in this minimal report, but the complete
        # facts fixture contains them, so the raw typed hash check must fail.
        with self.assertRaises(ValueError):compare(before,after)


if __name__=='__main__':unittest.main()
