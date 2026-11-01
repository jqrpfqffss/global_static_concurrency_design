from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from ecra.human_reviews import ReviewStore
from ecra.report_package import sha256
from ecra.scan_store import EvidenceProvider
from ecra.studio.sample import ASSETS,EXPECTED_METADATA_SHA256,open_sample,sample_info


class BuiltinSampleTests(unittest.TestCase):
    def test_git_checkout_settings_cannot_change_locked_sample_metadata_bytes(self):
        git=shutil.which('git')
        if git is None:self.skipTest('Git is required for checkout byte preservation')
        tool=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix='ecra-asset-git-') as folder:
            root=Path(folder);relative='ecra/studio/sample_assets/sample.json';target=root/relative;target.parent.mkdir(parents=True)
            (root/'.gitattributes').write_bytes((tool/'.gitattributes').read_bytes())
            target.write_bytes((ASSETS/'sample.json').read_bytes())
            def run(*args):return subprocess.check_output([git,'-C',str(root),*args],stderr=subprocess.STDOUT)
            run('init','--quiet')
            import hashlib
            for autocrlf in ['true','false']:
                run('config','core.autocrlf',autocrlf);run('add','.gitattributes',relative)
                self.assertEqual(hashlib.sha256(run('show',':'+relative)).hexdigest(),EXPECTED_METADATA_SHA256)
                target.unlink();run('checkout','--',relative)
                self.assertEqual(sha256(target),EXPECTED_METADATA_SHA256)

    def test_real_archive_opens_repeatedly_without_overwriting_confirmation_or_program_asset(self):
        descriptor=sample_info();self.assertTrue(descriptor['available'],descriptor)
        original={p.name:(sha256(p),p.stat().st_mtime_ns) for p in ASSETS.iterdir() if p.is_file()}
        with tempfile.TemporaryDirectory(prefix='ecra-sample-') as folder:
            root=Path(folder)/'data';first=open_sample(root)
            provider=EvidenceProvider(root/'scans'/first['scan_id']/'scan.db');binding=provider.validate(deep=True)
            self.assertEqual(binding['profile_id'],'builtin-stm32-demo')
            item=provider.symbols(search='g_counter',limit=1)['items'][0];symbol=item['symbol_id'];fingerprint=provider.fingerprint(symbol)
            reviews=ReviewStore(root/'scans'/first['scan_id']/'reviews.db',binding)
            event=reviews.append(symbol,fingerprint,decision='CONFIRMED_RISK',handling_status='TODO',reviewer='教学确认',comment='保留实际未知与风险')
            static_hash=sha256(provider.path);second=open_sample(root)
            self.assertTrue(second['repeated']);self.assertEqual(second['scan_id'],first['scan_id'])
            reopened=ReviewStore(root/'scans'/first['scan_id']/'reviews.db',binding)
            self.assertEqual(reopened.current(symbol,fingerprint)['decision'],'CONFIRMED_RISK')
            self.assertEqual([row['event_id'] for row in reopened.history(symbol)],[event['event_id']])
            self.assertEqual(sha256(provider.path),static_hash)
        self.assertEqual(original,{p.name:(sha256(p),p.stat().st_mtime_ns) for p in ASSETS.iterdir() if p.is_file()})

    def test_missing_or_changed_assets_fail_before_any_import_data_is_created(self):
        with tempfile.TemporaryDirectory(prefix='ecra-sample-bad-') as folder:
            base=Path(folder);bad=base/'asset';shutil.copytree(ASSETS,bad);data=base/'data'
            package=bad/'stm32-demo.ecra-report'
            with package.open('r+b') as stream:stream.write(b'BAD!')
            self.assertFalse(sample_info(_assets=bad)['available'])
            with self.assertRaisesRegex(ValueError,'摘要'):open_sample(data,_assets=bad)
            self.assertFalse(data.exists())
            self.assertFalse(sample_info(_assets=base/'missing')['available'])
            self.assertFalse(data.exists())

    def test_changed_metadata_does_not_offer_an_unverified_example(self):
        with tempfile.TemporaryDirectory(prefix='ecra-sample-meta-') as folder:
            bad=Path(folder)/'asset';shutil.copytree(ASSETS,bad)
            (bad/'sample.json').write_text('{}','utf-8')
            value=sample_info(_assets=bad);self.assertFalse(value['available']);self.assertIn('清单摘要',value['reason'])


if __name__=='__main__':unittest.main()
