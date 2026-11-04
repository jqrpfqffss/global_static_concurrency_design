"""Full canonical original/frozen scans on an independent authorized source copy.

This is an internal explicit-database acceptance controller. It does not open
the formal dirty/Diff/CMake/resume gates or replace original-path golden runs.
"""
import argparse
import contextlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work',type=Path,required=True)
    parser.add_argument('--engine',type=Path,required=True)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--config',type=Path,required=True)
    args=parser.parse_args()
    engine=args.engine.resolve(); sys.path.insert(0,str(engine))
    from ecra.report_package import sha256,export_report,import_report
    from ecra.common import read_json,write_json
    from ecra.config import load_config,read_yaml
    from ecra.workspace import formal_workspace,no_links
    from ecra.git_diff import relocate_paths
    from ecra import working_snapshot,working_compiler_view
    from ecra.compilation import prepare
    from ecra.portable import resolved_executable
    from ecra.scan_persistence import run_canonical
    from scripts.compare_native_graphs import compare
    source=no_links(args.source); config=no_links(args.config); work=no_links(args.work)
    if work==source or work.is_relative_to(source) or source.is_relative_to(work):
        raise ValueError('验收目录必须独立于原工程')
    work.mkdir(parents=True,exist_ok=False)
    state=dict(passed=False,scope=__doc__,all_gates_passed=False,engine=str(engine),
               source=str(source),config=str(config),controller_sha256=sha256(Path(__file__)))
    def save():write_json(work/'acceptance.json',state)
    def stamps(paths):return {str(p):(sha256(p),p.stat().st_size,p.stat().st_mtime_ns) for p in paths}
    def unchanged(before):return [p for p,value in before.items() if not Path(p).is_file() or
                                (sha256(Path(p)),Path(p).stat().st_size,Path(p).stat().st_mtime_ns)!=value]
    tick=time.monotonic();save()
    try:
        engine_before=stamps((engine/'ecra').rglob('*.py'))
        initial,_=load_config(source,config)
        if 'cmake' in initial['analysis'] or initial['analysis'].get('compile_database','auto')=='auto':
            raise ValueError('本阶段只验收真实显式编译数据库')
        original_db=(source/initial['analysis']['compile_database']).resolve()
        originals=stamps([config,original_db,*[p for p in source.rglob('*') if p.is_file()]])
        root=work/'firmware';shutil.copytree(source,root)
        def git(*values):
            subprocess.run(['git','-c','core.autocrlf=false','-C',str(root),*values],check=True,
                           stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=120,
                           env=dict(os.environ,GIT_OPTIONAL_LOCKS='0'))
        if (root/'.git').exists():raise ValueError('本控制器需要无.git的获准源快照；不接管既有仓库')
        git('init','-q');git('config','user.name','ECRA private acceptance')
        git('config','user.email','acceptance@example.invalid');git('config','core.autocrlf','false')
        git('add','.');git('commit','-qm','Independent authorized input copy')
        marker=root/'capture-audit.txt';marker.write_bytes(b'staged byte receipt\n');git('add',marker.name)
        marker.write_bytes(b'working byte receipt\n')
        private_db=work/'metadata/compile_commands.json';private_db.parent.mkdir()
        write_json(private_db,relocate_paths(read_json(original_db),source,root))
        raw=relocate_paths(read_yaml(config),source,root)
        raw['project']['root']=str(root);raw['analysis']['compile_database']=str(private_db)
        raw['analysis']['output']=dict(location='custom',custom_dir=str(work/'data'))
        private_config=work/'semantics.yaml';write_json(private_config,raw)
        cfg,_=load_config(root,private_config)
        ws=formal_workspace(root,cfg['analysis']).initialize();ws.bind(cfg['analysis'])
        private_before=stamps(p for p in root.rglob('*') if p.is_file())
        units,compilation=prepare(root,cfg)
        directories=[]
        def directory(value,cwd):
            path=no_links(Path(cwd)/value)
            if path==root or path.is_relative_to(root):return
            if not path.is_dir():raise ValueError('未固定外部缺失搜索目录，不能推断其负探针：'+str(path))
            if any(path==p or path.is_relative_to(p) for p in directories):return
            directories[:]=[p for p in directories if not p.is_relative_to(path)]
            directories.append(path)
        executables=[]
        from clang import cindex
        cindex.Index.create();executables.append(Path(cindex.conf.lib._name).resolve())
        for unit in units:
            directory(unit['directory'],root)
            for value in unit.get('system_include_dirs',[]):directory(value,unit['directory'])
            arguments=iter(unit['arguments'])
            for argument in arguments:
                if argument in {'-I','-isystem','-iquote','-idirafter','-isysroot','--sysroot','-resource-dir'}:
                    directory(next(arguments),unit['directory'])
                elif argument.startswith(('--sysroot=','-resource-dir=')):
                    directory(argument.split('=',1)[1],unit['directory'])
                elif argument.startswith('-I') and argument!='-I':directory(argument[2:],unit['directory'])
            original=unit['original_arguments']
            count=2 if Path(original[0]).stem.lower() in {'ccache','sccache'} else 1
            executables.extend(resolved_executable(value,unit['directory']) for value in original[:count])
        external_before=stamps(p for directory_root in directories for p in directory_root.rglob('*') if p.is_file())
        explicit=[private_config,private_db,*[p for p in executables if p.is_file()],
                  *[Path(p) for p in compilation.get('consumed_inputs',{})]]
        captured=working_snapshot.capture(root,cfg)
        descriptor=working_compiler_view.create(captured,root,cfg,external_directories=directories,external_files=explicit)
        state.update(descriptor=descriptor,units=len(units),external_files=len(external_before),
                     external_directories=list(map(str,directories)),status='RUNNING_FULL_SCANS');save()
        roots=[]
        for mode,fixed in [('original',None),('frozen',descriptor)]:
            with (work/(mode+'.log')).open('x',encoding='utf-8') as log,contextlib.redirect_stdout(log):
                started=time.monotonic()
                code=run_canonical(root,private_config,no_review=True,scan_id=mode,profile_id=mode,_compiler_view=fixed)
            out=work/'data/scans'/mode
            assert code in {0,1,2} and read_json(out/'result_validity.json')['analysis_valid'],mode
            state[mode]=dict(seconds=time.monotonic()-started,exit_code=code,
                            cache=read_json(out/'diagnostics/tu_cache.json'),
                            completion=read_json(out/'diagnostics/completion.json'))
            roots.append(out);save()
        state['comparison']=compare(roots[0]/'scan.db',roots[1]/'scan.db',envelope=work/'comparison-envelope.jsonl')
        assert state['comparison']['passed'],state['comparison']['differences']
        package=work/'frozen-complete.ecra-report';export_report(roots[1],package)
        imported=import_report(package,work/'independent-import')
        state['roundtrip']=compare(roots[1]/'scan.db',work/'independent-import/scans'/imported['scan_id']/'scan.db')
        assert state['roundtrip']['passed'],state['roundtrip']['differences']
        state['archive']=dict(bytes=package.stat().st_size,sha256=sha256(package))
        state['final_view_validation']=working_compiler_view.validate(descriptor,root,cfg)
        for name,before in [('approved_original',originals),('private_git',private_before),
                            ('external_build_sdk',external_before),('engine',engine_before)]:
            differences=unchanged(before);state[name+'_differences']=differences
            assert not differences,(name,differences)
        assert sha256(Path(__file__))==state['controller_sha256']
        state.update(passed=True,status='PASS_SCOPED',seconds=time.monotonic()-tick);save()
        print(json.dumps(dict(passed=True,units=len(units),seconds=state['seconds'])),flush=True)
    except BaseException:
        state.update(status='FAIL',error=traceback.format_exc(),seconds=time.monotonic()-tick);save();raise


if __name__=='__main__':main()
