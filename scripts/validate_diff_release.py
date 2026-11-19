"""Measure cold/hot/corrupt-summary recovery on an existing real branch/tag build.

No source/ref edits, model calls or hardware actions. A fresh managed data root
must be supplied in config; every failure and raw log is retained.
"""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import subprocess
import sys
import time

TOOL=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(TOOL))


def preconfigure_builds(root,cfg,workspace,evidence):
    """Stabilize real CMake inputs without extracting or populating scan caches."""
    import copy
    from ecra.common import digest,read_json,write_json
    from ecra.compilation import configure_cmake,cmake_build_directory,cmake_input_records
    from ecra.git_diff import (pin,prepare_current,version_directory,relocate_config,
                               _relative_worktree_gitdir,check_isolated_tree)
    from ecra.independent_git import prepare_frozen
    from ecra.input_snapshot import content_key
    from ecra.workflow import file_digest
    if 'cmake' not in cfg['analysis']:
        raise ValueError('--preconfigure-builds requires a real CMake build')
    workspace.initialize();workspace.bind(cfg['analysis'])
    fixed=pin(root,cfg);result=dict(base_sha=fixed['base_sha'],head_sha=fixed['head_sha'],sides={})
    prepared=Path(workspace.project_workspace)/'build-preparation'
    with (evidence/'build-preparation.log').open('w',encoding='utf-8') as log:
        def progress(message):print(message,file=log,flush=True)
        for side in ('base','current'):
            out=prepared/side;out.mkdir(parents=True,exist_ok=True)
            if side=='base':
                directory=version_directory(workspace,fixed,side)
                private=prepare_frozen(directory,fixed['base_sha'],workspace,fixed['frozen_git'])
                _relative_worktree_gitdir(private['repository'],directory,fixed['base_sha'])
                source=directory/fixed['project_subdir']
                config=read_json(fixed['config_path']);config['analysis']['git_diff']['enabled']=False
                config=relocate_config(config,root,source)
            else:
                source,config=prepare_current(root,out,copy.deepcopy(cfg),fixed,progress)
            workspace.for_results(out).bind(config['analysis'])
            attempts=[];previous=None
            for index in range(4):
                started=time.monotonic()
                database,_=configure_cmake(source,config['analysis'],progress,True,project=config.get('project'))
                build=cmake_build_directory(source,config['analysis'])
                inputs=cmake_input_records(source,build)
                signature=dict(database=file_digest(database),
                               cmake_inputs=digest({k:content_key(v) for k,v in inputs.items()}))
                check_isolated_tree(source,fixed['base_sha' if side=='base' else 'head_sha'],build)
                attempts.append(dict(attempt=index+1,seconds=round(time.monotonic()-started,3),signature=signature))
                if signature==previous:break
                previous=signature
            else:raise AssertionError('CMake inputs did not stabilize after four preparations: '+side)
            result['sides'][side]=dict(source=str(source),build=str(build),database=str(database),attempts=attempts)
            write_json(evidence/'build-preparation.json',result)
            print(json.dumps(dict(prepared_side=side,attempts=len(attempts),signature=signature)),flush=True)
    cache_files=sum(p.is_file() for p in Path(workspace.cache_root).rglob('*'))
    summaries=sum(p.is_file() for p in (Path(workspace.git_diff_root)/'summary-cache').rglob('*'))
    if cache_files or summaries:raise AssertionError('Build preparation must not populate analysis caches')
    result.update(analysis_cache_files=cache_files,summary_cache_files=summaries,
                  note='CMake configure/build preparation is outside timed CLI runs; ECRA analysis caches remain empty.')
    write_json(evidence/'build-preparation.json',result)
    return result


def main():
    import psutil
    from ecra.common import read_json,write_json,digest
    from ecra.config import load_config
    from ecra.workflow import engine_digest,output_path,file_digest
    from ecra.native_diff_summary import summarize_native
    from ecra.scan_store import EvidenceProvider
    from ecra.studio.query import QueryService
    from ecra.workspace import WorkspaceResolver,no_links
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--preconfigure-builds',action='store_true',
                        help='Stabilize both real CMake builds before measuring cold ECRA analysis caches')
    args=parser.parse_args();args.config=args.config.resolve();root=args.project.resolve();cfg,_=load_config(root,args.config)
    if cfg['review']['enabled'] or cfg['review']['prepare_packets']:
        raise ValueError('关闭模型调用与复核包生成后再测量')
    if not cfg['analysis']['git_diff']['verify_against_full']:
        raise ValueError('必须开启独立无缓存对照')
    evidence=no_links(args.evidence.resolve());evidence.mkdir(parents=True,exist_ok=False)
    workspace=WorkspaceResolver.resolve(root,cfg['analysis'])
    if (Path(workspace.project_workspace)/'latest-scan.json').exists():
        raise ValueError('冷扫描要求全新的独立数据根')
    def git(*argv):
        return subprocess.check_output(['git','-C',str(root),*argv],stderr=subprocess.STDOUT).decode('utf-8',errors='replace')
    before=dict(status=git('status','--porcelain'),refs=git('show-ref'))
    result=dict(engine_digest=engine_digest(),project=str(root),config=str(args.config),
                config_sha256=file_digest(args.config),runs=[],complete=False,hardware_executed=False,review_executed=False,
                measurement_script_sha256=file_digest(Path(__file__)),
                query_consumer_sha256=file_digest(TOOL/'ecra/studio/query.py'),
                measurement_conditions='Fresh ECRA caches; OS filesystem cache not cleared; same host may run acceptance tests.')
    write_json(evidence/'results.json',result)
    if args.preconfigure_builds:
        result['build_preparation']=preconfigure_builds(root,cfg,workspace,evidence)
        result['measurement_conditions']+=' CMake builds preconfigured to stable command/input hashes outside timed runs.'
        if before!=dict(status=git('status','--porcelain'),refs=git('show-ref')):
            raise AssertionError('Build preparation modified original workspace or refs')
        if engine_digest()!=result['engine_digest']:raise AssertionError('Analysis engine changed during preparation')
        write_json(evidence/'results.json',result)
    def portable(value):
        if isinstance(value,dict):
            return {k:portable(v) for k,v in value.items() if k not in {'base_summary_path','base_facts_path','diff_patch_path'}}
        if isinstance(value,list):return [portable(v) for v in value]
        return value
    previous=None
    for name in ['cold','hot','summary-cache-recovery']:
        if name=='summary-cache-recovery':
            cache=Path(workspace.git_diff_root)/'summary-cache'/Path(pin['base_summary_path']).name
            if not cache.is_file():raise ValueError('待验证的派生摘要缓存不存在')
            cache.write_bytes(b'intentional derived-cache corruption for recovery acceptance')
        started=time.monotonic();peak=0;sampling_errors=0
        with (evidence/(name+'.log')).open('wb') as log:
            command=[sys.executable,'-B',str(TOOL/'run_ecra.py'),'--project',str(root),
                     '--config',str(args.config),'--scan-mode','diff','--no-review']
            process=subprocess.Popen(command,cwd=TOOL,stdout=log,stderr=subprocess.STDOUT,
                                     env=dict(os.environ,ECRA_DATA_ROOT=workspace.workspace_root,PYTHONUTF8='1'))
            while process.poll() is None:
                try:
                    parent=psutil.Process(process.pid)
                    peak=max(peak,sum(p.memory_info().rss for p in [parent,*parent.children(recursive=True)] if p.is_running()))
                except psutil.NoSuchProcess:pass
                except psutil.Error:sampling_errors+=1
                time.sleep(.25)
        row=dict(name=name,seconds=round(time.monotonic()-started,3),exit_code=process.returncode,
                 peak_tree_rss_bytes=peak,memory_sampling_errors=sampling_errors)
        result['runs'].append(row);write_json(evidence/'results.json',result)
        if process.returncode not in (0,1,2):raise RuntimeError('实际扫描失败：'+str(evidence/(name+'.log')))
        out=output_path(root,cfg);provider=EvidenceProvider(out/'scan.db')
        delta=provider.load('report',['git_diff']);pin=delta['pin'];summary=summarize_native(out/'scan.db')
        comparable={k:portable(delta[k]) for k in ('impacts','baseline_only_variables','impact_counts',
            'object_accounting','comparison_objects','change_counts','regional_gaps','full_verification','publication')}
        signature=dict(summary=digest(summary),comparison=digest(comparable))
        if previous is not None and signature!=previous:raise AssertionError('冷热或恢复后完整事实/比较不一致')
        previous=signature
        if delta['full_verification']['state']!='PASSED':raise AssertionError('真实完整构建未通过独立全量对照')
        if sum(delta['impact_counts'].values())!=delta['identified_object_count']:raise AssertionError('对象归账缺失')
        if QueryService(out).diff_changes('objects')['total']!=len(delta['comparison_objects']):raise AssertionError('UI分母不一致')
        if name=='hot' and not delta['baseline_summary_cache']['hit']:raise AssertionError('未命中热摘要缓存')
        if name=='summary-cache-recovery' and not delta['baseline_summary_cache']['corrupt']:raise AssertionError('未检测到摘要损坏')
        row.update(output=str(out),scan_sha256=file_digest(out/'scan.db'),signature=signature,
            base_sha=pin['base_sha'],head_sha=pin['head_sha'],translation_units=len(summary['comparison_scope']['units']),
            parse_statuses=dict(Counter(u['parse_status'] for u in summary['comparison_scope']['units'])),
            variables=len(summary['variables']),functions=len(summary['functions']),impact_counts=delta['impact_counts'],
            verification=delta['full_verification'],publication=delta['publication'],
            tu_cache=delta['tu_cache'],summary_cache=delta['baseline_summary_cache'],database_bytes=(out/'scan.db').stat().st_size)
        if engine_digest()!=result['engine_digest']:raise AssertionError('分析实现已变化')
        if file_digest(Path(__file__))!=result['measurement_script_sha256']:raise AssertionError('测量脚本已变化')
        if file_digest(TOOL/'ecra/studio/query.py')!=result['query_consumer_sha256']:raise AssertionError('查询实现已变化')
        if before!=dict(status=git('status','--porcelain'),refs=git('show-ref')):raise AssertionError('原工作区或引用被修改')
        write_json(evidence/'results.json',result)
        print(json.dumps(row,ensure_ascii=True),flush=True)
        del summary,delta,comparable,provider
    result['complete']=True;write_json(evidence/'results.json',result)


if __name__=='__main__':main()
