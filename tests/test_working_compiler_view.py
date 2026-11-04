"""Real extractor processes over pinned working and external include bytes."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from ecra import working_compiler_view as view
from ecra import working_snapshot
from ecra.compilation import normalize
from ecra.config import load_config
from scripts.validate_studio_baseline import strict_difference
from tests import test_working_snapshot as fixture


class WorkingCompilerViewTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixture.WorkingSnapshotTests(methodName='runTest')
        self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.base=self.fixture.base;self.repo=self.fixture.repo
        self.sdk=self.base/'SDK %_ 中文';self.sdk.mkdir()
        (self.sdk/'empty search').mkdir()
        (self.sdk/'external.h').write_text('#define EXTERNAL 11\n','utf-8')
        (self.sdk/'probe-only.h').write_text('/* exists but is not included */\n','utf-8')
        (self.repo/'main.c').write_text('int staged_only;\n','utf-8');self.fixture.git('add','main.c')
        self.fixture.git('mv','rename.c','renamed.h');self.fixture.git('rm','removed.c')
        (self.repo/'new untracked.h').write_text('#define UNTRACKED 3\n','utf-8')
        (self.repo/'generated').mkdir();(self.repo/'generated/input.h').write_text('#define INPUT 7\n','utf-8')
        (self.repo/'main.c').write_text('''#include "generated/input.h"
#include "renamed.h"
#include "new untracked.h"
#include <external.h>
#if __has_include("generated/late.h") || __has_include(<late-sdk.h>)
#define LATE 99
#else
#define LATE 0
#endif
#if __has_include(<probe-only.h>)
#define POSITIVE 5
#else
#define POSITIVE 0
#endif
static int shared=LATE+POSITIVE;
char layout_depends_on_logical_name[sizeof(__FILE__)];
const char *source_name=__FILE__;
const char *base_name=__BASE_FILE__;
const char *const timestamp=__TIMESTAMP__;
void ISR(void){shared+=INPUT+EXTERNAL+UNTRACKED;}
int main(void){shared++;return shared;}
''','utf-8')
        config=self.base/'semantics.json'
        config.write_text(json.dumps(dict(version=1,project=dict(root=str(self.repo)),analysis=self.fixture.analysis,
            contexts=[dict(id='main',kind='MAIN',functions=['main']),dict(id='irq',kind='ISR',functions=['ISR'])],
            review=dict(enabled=False))),'utf-8')
        self.cfg,_=load_config(self.repo,config)
        self.unit=normalize(dict(directory=str(self.repo),file='main.c',arguments=['arm-none-eabi-gcc',
            '-mcpu=cortex-m7','-mthumb','-I',str(self.sdk),'-c','main.c']),self.repo,self.cfg['analysis'])
        self.unit['tu_id']='TU-00001';self.count=0

    def worker(self,descriptor=None,**kwargs):
        self.count+=1;request=self.base/('request-'+str(self.count)+'.json');output=self.base/('response-'+str(self.count)+'.json')
        record=dict(root=str(self.repo),config=self.cfg,unit=self.unit,verify_inputs=True)
        if descriptor is not None:record['compiler_view']=descriptor
        record.update(kwargs);request.write_text(json.dumps(record),'utf-8')
        result=subprocess.run([sys.executable,'-B','-X','utf8','-m','ecra.extract',str(request),str(output)],
            cwd=Path(__file__).resolve().parents[1],capture_output=True,timeout=90)
        self.assertEqual(result.returncode,0,result.stderr.decode('utf-8',errors='replace'))
        return json.loads(output.read_text('utf-8'))

    def capture(self):
        captured=working_snapshot.capture(self.repo,self.cfg)
        return captured,view.create(captured,self.repo,self.cfg,external_directories=[self.sdk])

    def test_actual_worker_full_facts_macros_paths_and_positive_negative_probes_match_after_live_inputs_change(self):
        original=self.worker();self.assertEqual(original['parse_status'],'PARSED',original['diagnostics'])
        before=self.fixture.hashes();captured,descriptor=self.capture()
        self.assertEqual(self.fixture.hashes(),before,'capture/view must not write original Git or firmware')
        frozen=self.worker(descriptor)
        self.assertIsNone(strict_difference(original,frozen))
        # Mutations are confined to the owned fixture; a frozen worker must
        # still consume the exact old bytes and negative include namespace.
        (self.repo/'main.c').write_text('int wrong_live_source;\n','utf-8')
        (self.repo/'generated/late.h').write_text('#define LATE 1\n','utf-8')
        (self.sdk/'external.h').write_text('#define EXTERNAL 999\n','utf-8')
        (self.sdk/'late-sdk.h').write_text('/* newly available */\n','utf-8')
        (self.sdk/'probe-only.h').unlink()
        frozen_again=self.worker(descriptor)
        self.assertEqual(frozen_again['parse_status'],'PARSED',frozen_again['diagnostics'])
        self.assertIsNone(strict_difference(original,frozen_again))
        live=self.worker();self.assertIsNotNone(strict_difference(original,live),'fixture must distinguish live source')
        self.assertTrue(view.validate(descriptor,self.repo,self.cfg,reverify_original=False)['valid'])
        with self.assertRaises(ValueError):view.validate(descriptor,self.repo,self.cfg)
        from ecra.analysis import merge,analyze
        left=merge([original]);right=merge([frozen_again])
        self.assertIsNone(strict_difference(left,right))
        coverage=dict(translation_units_total=1,translation_units_failed=0,translation_units_partial=0,translation_units_parsed=1)
        self.assertIsNone(strict_difference(analyze(left,self.cfg,coverage),analyze(right,self.cfg,coverage)))

    def test_actual_worker_rejects_changed_overlay_descriptor_and_consumed_copy_without_publishing_facts(self):
        captured,descriptor=self.capture();folder=Path(descriptor['file']).parent
        source=Path(captured['source_root'])/'main.c';source.write_text('int corrupted_copy;\n','utf-8')
        failed=self.worker(descriptor)
        self.assertEqual(failed['parse_status'],'FAILED');self.assertNotIn('variables',failed)
        self.assertIn('实际输入',failed['worker_exception']['message'])
        with self.assertRaises(ValueError):view.validate(descriptor,self.repo,self.cfg)
        with (folder/'overlay.json').open('ab') as stream:stream.write(b' ')
        failed=self.worker(descriptor)
        self.assertEqual(failed['parse_status'],'FAILED');self.assertIn('overlay已变化',failed['worker_exception']['message'])
        with (folder/'view.json').open('ab') as stream:stream.write(b' ')
        failed=self.worker(descriptor)
        self.assertEqual(failed['parse_status'],'FAILED');self.assertIn('描述已变化',failed['worker_exception']['message'])

    def test_external_additions_missing_files_and_uncaptured_copy_files_invalidate_full_closure(self):
        captured,descriptor=self.capture();folder=Path(descriptor['file']).parent
        late=self.sdk/'new-negative-probe.h';late.write_text('#define NEW 1\n','utf-8')
        with self.assertRaisesRegex(ValueError,'未记录输入'):view.validate(descriptor,self.repo,self.cfg)
        self.assertTrue(view.validate(descriptor,self.repo,self.cfg,reverify_original=False)['valid'])
        late.unlink()
        copied=folder/'external/0';(copied/'unexpected.h').write_text('/* not captured */','utf-8')
        with self.assertRaisesRegex(ValueError,'未记录输入'):view.validate(descriptor,self.repo,self.cfg,reverify_original=False)
        (copied/'unexpected.h').unlink();(copied/'external.h').unlink()
        with self.assertRaisesRegex(ValueError,'副本已变化'):view.validate(descriptor,self.repo,self.cfg,reverify_original=False)

    def test_bad_request_cannot_mix_unsaved_source_disable_verification_or_use_unowned_logical_paths(self):
        captured,descriptor=self.capture()
        for extra in [dict(verify_inputs=False),dict(source_overrides={self.unit['source']:'int injected;'})]:
            failed=self.worker(descriptor,**extra)
            self.assertEqual(failed['parse_status'],'FAILED');self.assertIn('必须核对实际Clang输入',failed['worker_exception']['message'])
        unit=copy.deepcopy(self.unit);unit['source']=str(self.sdk/'external.h')
        failed=self.worker(descriptor,unit=unit)
        self.assertEqual(failed['parse_status'],'FAILED');self.assertIn('原工程内',failed['worker_exception']['message'])
        outside=dict(descriptor,file=str(self.base/'view.json'))
        with self.assertRaisesRegex(ValueError,'Resolver'):view.arguments(outside,self.repo,self.cfg,self.unit)
        with self.assertRaisesRegex(ValueError,'绝对目录'):view.create(captured,self.repo,self.cfg,external_directories=['relative-sdk'])
        with self.assertRaisesRegex(ValueError,'重叠'):view.create(captured,self.repo,self.cfg,external_directories=[self.sdk,self.sdk/'empty search'])
        with self.assertRaisesRegex(ValueError,'数据根'):view.create(captured,self.repo,self.cfg,external_directories=[Path(self.fixture.ws.workspace_root)])

    def test_external_build_working_directory_must_be_captured_and_preserves_actual_worker_output(self):
        build=self.base/'external build';build.mkdir();(build/'include').mkdir()
        (build/'include/build.h').write_text('#define BUILD_HEADER 4\n','utf-8')
        with (self.repo/'main.c').open('a',encoding='utf-8') as stream:stream.write('\n#include "include/build.h"\nint generated_value=BUILD_HEADER;\n')
        self.unit['directory']=str(build)
        self.unit['arguments'].extend(['-I',str(build)])
        original=self.worker();self.assertEqual(original['parse_status'],'PARSED',original['diagnostics'])
        captured=working_snapshot.capture(self.repo,self.cfg)
        incomplete=view.create(captured,self.repo,self.cfg,external_directories=[self.sdk])
        failed=self.worker(incomplete);self.assertEqual(failed['parse_status'],'FAILED')
        self.assertIn('明确捕获的工作目录',failed['worker_exception']['message'])
        descriptor=view.create(captured,self.repo,self.cfg,external_directories=[self.sdk,build])
        frozen=self.worker(descriptor);self.assertIsNone(strict_difference(original,frozen))

    def test_low_disk_or_external_copy_race_never_returns_an_accepted_view_and_auto_dirty_stays_blocked(self):
        captured=working_snapshot.capture(self.repo,self.cfg);before=self.fixture.hashes()
        with patch('ecra.working_compiler_view.shutil.disk_usage',return_value=shutil_usage(0)):
            with self.assertRaisesRegex(ValueError,'空闲不足'):view.create(captured,self.repo,self.cfg,external_directories=[self.sdk])
        self.assertEqual(before,self.fixture.hashes())
        source_hash=working_snapshot._hash
        def changed(path):
            if Path(path)==self.sdk/'external.h':return '0'*64
            return source_hash(path)
        with patch('ecra.working_snapshot._hash',side_effect=changed):
            with self.assertRaisesRegex(ValueError,'复制期间外部编译输入已变化'):view.create(captured,self.repo,self.cfg,external_directories=[self.sdk])
        from ecra.workspace import formal_workspace
        analysis=dict(self.fixture.analysis,git_diff=dict(include_uncommitted=True))
        with self.assertRaisesRegex(ValueError,'显式编译数据库'):formal_workspace(self.repo,analysis)
        self.assertEqual(before,self.fixture.hashes())

    def test_failed_final_closure_validation_keeps_pending_view_unusable_by_actual_worker(self):
        captured=working_snapshot.capture(self.repo,self.cfg)
        publish=view.write_json
        def introduce_new_search_input(path,record):
            publish(path,record)
            if Path(path).name=='view.json' and record.get('state')=='PENDING':
                (self.sdk/'late-input.h').write_text('/* changed before publication */','utf-8')
        with patch('ecra.working_compiler_view.write_json',side_effect=introduce_new_search_input):
            with self.assertRaisesRegex(ValueError,'未记录输入'):
                view.create(captured,self.repo,self.cfg,external_directories=[self.sdk])
        path=next(Path(captured['folder']).glob('compiler-view-*/view.json'))
        self.assertEqual(json.loads(path.read_text('utf-8'))['state'],'PENDING')
        descriptor=dict(file=str(path),sha256=working_snapshot._hash(path))
        failed=self.worker(descriptor)
        self.assertEqual(failed['parse_status'],'FAILED');self.assertNotIn('variables',failed)
        self.assertIn('能力声明无效',failed['worker_exception']['message'])


def shutil_usage(free):
    from collections import namedtuple
    return namedtuple('Usage','total used free')(1024**3,1024**3-free,free)
