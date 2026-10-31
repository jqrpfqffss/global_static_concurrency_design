from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from ecra.workspace import WorkspaceResolver
from ecra import working_snapshot as snapshot


class WorkingSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='ECRA dirty 输入 ');self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name).resolve();self.repo=self.base/'firmware';self.repo.mkdir()
        self.git('init','-q');self.git('config','user.name','snapshot fixture');self.git('config','user.email','snapshot@example.invalid')
        self.git('config','core.autocrlf','false')
        for name,data in [('main.c',b'int value;\r\n'),('removed.c',b'int removed;\n'),('rename.c',b'int renamed;\n'),('.gitignore',b'generated/\n')]:
            (self.repo/name).write_bytes(data)
        self.git('add','.');self.git('commit','-qm','base')
        self.analysis=dict(output=dict(location='custom',custom_dir=str(self.base/'data')))
        self.ws=WorkspaceResolver.resolve(self.repo,self.analysis).initialize();self.ws.bind(self.analysis)

    def git(self,*args):
        result=subprocess.run(['git','-C',str(self.repo),*args],capture_output=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr);return result.stdout

    def hashes(self):
        return {p.relative_to(self.repo).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in self.repo.rglob('*') if p.is_file()}

    def test_staged_worktree_rename_delete_untracked_ignored_and_binary_bytes_are_independent(self):
        (self.repo/'main.c').write_bytes(b'int staged;\r\n');self.git('add','main.c')
        # The working file matches HEAD but staging still differs. Its build
        # Git identity must not silently become a clean checkout.
        (self.repo/'main.c').write_bytes(b'int value;\r\n')
        self.git('mv','rename.c','renamed.c');self.git('rm','removed.c')
        (self.repo/'new 中文.c').write_bytes('int 新变量;\r\n'.encode('utf-8'))
        (self.repo/'generated').mkdir();(self.repo/'generated/input.h').write_bytes(b'#define INPUT 123\n')
        (self.repo/'binary.dat').write_bytes(bytes(range(256))*100)
        before=self.hashes();index=self.git('ls-files','--stage','-z');staged=self.git('show',':main.c')
        result=snapshot.capture(self.repo,dict(analysis=self.analysis))
        source=Path(result['source_root'])
        self.assertEqual(self.hashes(),before,'the original .git and firmware bytes must remain unchanged')
        self.assertEqual(snapshot._git(source,'ls-files','--stage','-z'),index)
        self.assertEqual(snapshot._git(source,'show',':main.c'),staged)
        self.assertEqual((source/'main.c').read_bytes(),b'int value;\r\n')
        self.assertFalse((source/'removed.c').exists());self.assertTrue((source/'renamed.c').is_file())
        for name in ('new 中文.c','generated/input.h','binary.dat'):
            self.assertEqual((source/name).read_bytes(),(self.repo/name).read_bytes())
            self.assertEqual((source/name).stat().st_mtime_ns,(self.repo/name).stat().st_mtime_ns)
        (source/'main.c').write_bytes(b'only capture changed')
        self.assertEqual(self.hashes(),before,'copies must not hardlink mutable original input')
        self.assertFalse((source/'.git/objects/info/alternates').exists())
        self.assertFalse((self.repo/'.git/worktrees').exists())
        with closing(sqlite3.connect(result['manifest'])) as conn:
            self.assertEqual(json.loads(conn.execute("SELECT value FROM meta WHERE key='state'").fetchone()[0]),'COMPLETE')
            self.assertEqual(conn.execute('SELECT count(*) FROM files').fetchone()[0],result['files'])
        self.assertEqual(result['project_id'],self.ws.project_id)
        self.assertEqual(result['proof'],'BYTES_AND_INDEX_ONLY_NOT_BUILD_EQUIVALENCE')

    def test_tampered_capture_and_changed_original_are_never_treated_as_reverified(self):
        result=snapshot.capture(self.repo,dict(analysis=self.analysis));source=Path(result['source_root'])
        self.assertTrue(snapshot.validate(result,self.repo,dict(analysis=self.analysis))['valid'])
        (self.repo/'main.c').write_bytes(b'int changed_original;')
        with self.assertRaisesRegex(ValueError,'原工作输入已变化'):
            snapshot.validate(result,self.repo,dict(analysis=self.analysis))
        self.assertFalse(snapshot.validate(result,self.repo,dict(analysis=self.analysis),reverify_original=False)['original_reverified'])
        (source/'main.c').write_bytes(b'int corrupt_capture;')
        with self.assertRaisesRegex(ValueError,'隔离输入已改变'):
            snapshot.validate(result,self.repo,dict(analysis=self.analysis),reverify_original=False)

    def test_same_modified_status_with_changing_bytes_fails_capture(self):
        (self.repo/'main.c').write_bytes(b'int first_modification;')
        original=snapshot._working_digest;calls=[]
        def change(repo,folder,name):
            calls.append(name)
            if name=='working-after.z':(self.repo/'main.c').write_bytes(b'int second_modification;')
            return original(repo,folder,name)
        with patch('ecra.working_snapshot._working_digest',side_effect=change):
            with self.assertRaisesRegex(ValueError,'工作输入字节变化'):
                snapshot.capture(self.repo,dict(analysis=self.analysis))
        capture=next(Path(self.ws.worktree_root).glob('working-*/capture.db'))
        with closing(sqlite3.connect(capture)) as conn:
            self.assertEqual(json.loads(conn.execute("SELECT value FROM meta WHERE key='state'").fetchone()[0]),'FAILED')
        self.assertFalse((self.repo/'.git/worktrees').exists())

    def test_native_clang_full_tu_facts_with_file_macro_map_and_ignored_header(self):
        import copy,os
        from ecra.compilation import normalize
        from ecra.config import load_config
        from ecra.extract import Extractor
        from ecra.git_diff import relocate_paths
        from scripts.validate_studio_baseline import strict_difference
        original_cwd=Path.cwd();self.addCleanup(os.chdir,original_cwd)
        (self.repo/'generated').mkdir();(self.repo/'generated/input.h').write_text('#define INPUT 7\n',encoding='utf-8')
        (self.repo/'main.c').write_text('''#include "generated/input.h"
static int shared;
const char *source_name=__FILE__;
const char *base_name=__BASE_FILE__;
const char *const source_stamp=__TIMESTAMP__;
void ISR(void){shared+=INPUT;}
int main(void){shared++;return shared;}
''',encoding='utf-8')
        config=self.base/'semantics.json'
        config.write_text(json.dumps(dict(version=1,project=dict(root=str(self.repo)),analysis=self.analysis,
            contexts=[dict(id='main',kind='MAIN',functions=['main']),dict(id='irq',kind='ISR',functions=['ISR'])],
            review=dict(enabled=False))),encoding='utf-8')
        cfg,_=load_config(self.repo,config)
        result=snapshot.capture(self.repo,cfg);source=Path(result['source_root'])
        entry=dict(directory=str(self.repo),file='main.c',arguments=['arm-none-eabi-gcc','-mcpu=cortex-m7','-mthumb','-c','main.c','-o','main.o'])
        original=normalize(entry,self.repo,cfg['analysis']);original['tu_id']='TU-00001'
        relocated=copy.deepcopy(cfg)
        relocated['analysis']['extra_args']=[
            '-ffile-prefix-map='+str(source)+'='+str(self.repo),
            '-ffile-prefix-map='+source.as_posix()+'='+str(self.repo)]
        moved=normalize(dict(entry,directory=str(source)),source,relocated['analysis']);moved['tu_id']='TU-00001'
        first=Extractor(dict(root=str(self.repo),unit=original,config=cfg)).run()
        second=Extractor(dict(root=str(source),unit=moved,config=relocated)).run()
        self.assertEqual(first['parse_status'],'PARSED',first['diagnostics'])
        self.assertEqual(second['parse_status'],'PARSED',second['diagnostics'])
        # Explicit directory relocation only; no field/type/order exclusion.
        difference=strict_difference(first,relocate_paths(second,source,self.repo))
        self.assertIsNone(difference,difference)
        from ecra.analysis import merge,analyze
        left=merge([first]);right=merge([relocate_paths(second,source,self.repo)])
        coverage=dict(translation_units_total=1,translation_units_failed=0,translation_units_partial=0,translation_units_parsed=1)
        old_report=analyze(left,cfg,coverage);new_report=analyze(right,cfg,coverage)
        self.assertIsNone(strict_difference(left,right))
        self.assertIsNone(strict_difference(old_report,new_report))
        snapshot.validate(result,self.repo,cfg)

    def test_real_arm_gcc_preprocessor_file_base_and_timestamp_expansions_are_preserved(self):
        import shutil
        from ecra.portable import build_path,tool_path,tool_environment
        if not shutil.which('arm-none-eabi-gcc'):self.skipTest('requires native ARM GCC')
        (self.repo/'main.c').write_text('''const char *file_name=__FILE__;
const char *base_name=__BASE_FILE__;
const char *stamp=__TIMESTAMP__;
''',encoding='utf-8')
        result=snapshot.capture(self.repo,dict(analysis=self.analysis));source=Path(result['source_root'])
        old=Path(build_path(self.repo,prefer_junction=True));new=Path(build_path(source,prefer_junction=True))
        compiler=tool_path('arm-none-eabi-gcc')
        def preprocess(folder,mapping=()):
            invocation=[compiler,'-E','-P','-mcpu=cortex-m7','-mthumb',*mapping,str(folder/'main.c')]
            child=subprocess.run(invocation,capture_output=True,env=tool_environment(),timeout=30)
            self.assertEqual(child.returncode,0,child.stderr);return child.stdout
        original=preprocess(old)
        relocated=preprocess(new,['-ffile-prefix-map='+str(new)+'='+str(old),
            '-ffile-prefix-map='+new.as_posix()+'='+str(old)])
        self.assertEqual(relocated,original,'compiler macro bytes, not only Clang classifications, must match')
        self.assertNotEqual(preprocess(new),original,'the fixture must actually exercise the directory mapping')

    def test_original_dynamic_macro_rejection_remains_on_the_capture(self):
        import os
        from ecra.compilation import normalize
        from ecra.config import load_config
        from ecra.extract import Extractor
        original_cwd=Path.cwd();self.addCleanup(os.chdir,original_cwd)
        (self.repo/'main.c').write_text('const char *mutable_clock=__TIMESTAMP__;\n',encoding='utf-8')
        config=self.base/'semantics.json';config.write_text(json.dumps(dict(version=1,
            project=dict(root=str(self.repo)),analysis=self.analysis,review=dict(enabled=False))),encoding='utf-8')
        cfg,_=load_config(self.repo,config);captured=snapshot.capture(self.repo,cfg)
        for root in (self.repo,Path(captured['source_root'])):
            unit=normalize(dict(directory=str(root),file='main.c',arguments=['arm-none-eabi-gcc','-c','main.c']),root,cfg['analysis'])
            unit['tu_id']='TU-00001'
            with self.assertRaisesRegex(ValueError,'动态预定义宏用于运行逻辑或存储布局'):
                Extractor(dict(root=str(root),unit=unit,config=cfg)).run()

    def test_new_ignored_input_after_capture_invalidates_original_reverification(self):
        (self.repo/'generated').mkdir()
        result=snapshot.capture(self.repo,dict(analysis=self.analysis))
        (self.repo/'generated/new.h').write_bytes(b'#define CHANGED_HAS_INCLUDE 1\n')
        with self.assertRaisesRegex(ValueError,'原工作目录出现未记录的输入'):
            snapshot.validate(result,self.repo,dict(analysis=self.analysis))

    def test_native_redirect_only_vfs_keeps_logical_paths_macros_and_frozen_negative_probes(self):
        import os
        from clang import cindex as ci
        from ecra.compilation import normalize
        from ecra.config import load_config
        from ecra.extract import Extractor
        from scripts.validate_studio_baseline import strict_difference
        original_cwd=Path.cwd();self.addCleanup(os.chdir,original_cwd)
        sdk=self.base/'external-sdk';sdk.mkdir();(sdk/'external.h').write_text('#define EXTERNAL 11\n',encoding='utf-8')
        (self.repo/'generated').mkdir();(self.repo/'generated/input.h').write_text('#define INPUT 7\n',encoding='utf-8')
        (self.repo/'main.c').write_text('''#include "generated/input.h"
#include <external.h>
#if __has_include("generated/late.h")
#define PROBE 9
#else
#define PROBE 0
#endif
int shared=PROBE;
char source_layout[sizeof(__FILE__)];
const char *source_name=__FILE__;
const char *base_name=__BASE_FILE__;
const char *const source_stamp=__TIMESTAMP__;
void ISR(void){shared+=INPUT+EXTERNAL;}
int main(void){shared++;return shared;}
''',encoding='utf-8')
        config=self.base/'vfs-semantics.json';config.write_text(json.dumps(dict(version=1,
            project=dict(root=str(self.repo)),analysis=self.analysis,review=dict(enabled=False))),encoding='utf-8')
        cfg,_=load_config(self.repo,config)
        unit=normalize(dict(directory=str(self.repo),file='main.c',arguments=['arm-none-eabi-gcc',
            '-mcpu=cortex-m7','-mthumb','-I',str(sdk),'-c','main.c']),self.repo,cfg['analysis']);unit['tu_id']='TU-00001'
        request=dict(root=str(self.repo),unit=unit,config=cfg,verify_inputs=True)
        original=Extractor(request).run();self.assertEqual(original['parse_status'],'PARSED',original['diagnostics'])
        captured=snapshot.capture(self.repo,cfg);tree=Path(captured['repository_root'])
        roots=[]
        with closing(sqlite3.connect(captured['manifest'])) as conn:
            for (relative,) in conn.execute('SELECT relative FROM files ORDER BY relative'):
                roots.append(dict(type='file',name=(self.repo/relative).as_posix(),
                    **{'external-contents':(tree/relative).as_posix()}))
        roots.append(dict(type='directory-remap',name=sdk.as_posix(),**{'external-contents':sdk.as_posix()}))
        overlay=self.base/'readonly-vfs.json'
        document=dict(version=0,roots=roots,**{'case-sensitive':False,'use-external-names':False,
            'redirecting-with':'redirect-only'})
        overlay.write_text(json.dumps(document),encoding='utf-8')
        # These are deliberate changes to the owned test fixture after capture.
        # The compiler view must use only captured original-repo bytes, including
        # a negative __has_include probe which was absent at capture time.
        (self.repo/'main.c').write_text('int wrong_live_source;\n',encoding='utf-8')
        (self.repo/'generated/input.h').write_text('#define INPUT 999\n',encoding='utf-8')
        (self.repo/'generated/late.h').write_text('#define LATE 1\n',encoding='utf-8')
        parse=ci.Index.parse
        def with_overlay(index,filename,args=None,**kwargs):
            return parse(index,filename,args=[*(args or []),'-ivfsoverlay',str(overlay)],**kwargs)
        with patch.object(ci.Index,'parse',new=with_overlay):
            frozen=Extractor(request).run()
        self.assertEqual(frozen['parse_status'],'PARSED',frozen['diagnostics'])
        self.assertIsNone(strict_difference(original,frozen),strict_difference(original,frozen))
        live=Extractor(request).run()
        self.assertIsNotNone(strict_difference(original,live),'the fixture must actually distinguish current live source')
        document['redirecting-with']='fallthrough';overlay.write_text(json.dumps(document),encoding='utf-8')
        with patch.object(ci.Index,'parse',new=with_overlay):
            unsafe=Extractor(request).run()
        self.assertIsNotNone(strict_difference(original,unsafe),
            'fallthrough admits the newly created ignored header and cannot be used as frozen input')
        self.assertTrue(snapshot.validate(captured,self.repo,cfg,reverify_original=False)['valid'])
        with self.assertRaisesRegex(ValueError,'原工作目录出现未记录的输入'):
            snapshot.validate(captured,self.repo,cfg)
