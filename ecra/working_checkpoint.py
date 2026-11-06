"""Reuse one verified CMake working-input build after an explicit task retry."""
from pathlib import Path

from .common import read_json,write_json,digest
from .report_package import IDENTITY,sha256
from .workspace import no_links


def retry_inputs(data,folder,config,mode,progress=print):
    """Return (original config, view) or None when capture never completed.

    A complete but changed checkpoint is an error, never a live-build fallback.
    The original config path remains an input: the task records its provenance
    and its new immutable config must contain exactly the same bytes.
    """
    folder=no_links(folder);data=no_links(data);config=no_links(config)
    recipe=folder/'retry-source.json'
    if not recipe.is_file():return None
    from .config import configured_project_root,load_config
    current_root=configured_project_root(config);current,_=load_config(current_root,config)
    if 'cmake' not in current['analysis'] or not current['analysis']['git_diff'].get('include_uncommitted'):return None
    spec=read_json(no_links(recipe))
    if (folder.parent!=data/'work/tasks' or config!=folder/'semantics.yaml'
            or not isinstance(spec,dict) or set(spec)!={'source_task'}
            or not isinstance(spec['source_task'],str) or not IDENTITY.fullmatch(spec['source_task'])):
        raise ValueError('恢复输入来源不属于本数据根的受控任务')
    source=no_links(data/'work/tasks'/spec['source_task']);task=read_json(no_links(source/'task.json'))
    original=no_links(source/'semantics.yaml')
    if (task.get('id')!=spec['source_task'] or task.get('state') not in {'INTERRUPTED','FAILED'}
            or task.get('mode')!=mode or mode not in {'scan','precheck'}
            or sha256(original)!=task.get('profile_revision') or sha256(config)!=sha256(original)):
        raise ValueError('恢复任务状态、模式或原配置字节已变化；保留检查点，请重新发起扫描')
    from .workflow import analysis_config,engine_digest
    root=configured_project_root(original);cfg,_=load_config(root,original)
    if 'cmake' not in cfg['analysis'] or not cfg['analysis']['git_diff'].get('include_uncommitted'):return None
    plan=no_links(source/'fixed-inputs/capture-plan.json')
    if not plan.is_file():return None  # No complete view existed before the stop.
    saved=read_json(plan)
    if (saved.get('engine_digest')!=engine_digest()
            or saved.get('effective_analysis_digest')!=digest(analysis_config(cfg))):
        raise ValueError('分析实现或有效配置已变化，不能复用旧CMake构建；请从工程配置启动新扫描')
    from .frozen_scan import execution_workspace,ScanFiles
    from .working_compiler_view import _load
    ws=execution_workspace(root,cfg['analysis'],object()).initialize();ws.bind(cfg['analysis'])
    descriptor=saved.get('compiler_view');_,record=_load(descriptor,root,cfg)
    if (record.get('format')!='ECRA_FROZEN_COMPILER_VIEW_V3' or saved.get('project_id')!=ws.project_id
            or Path(task.get('project_root','')).resolve()!=root.resolve()):
        raise ValueError('CMake恢复来源的工程或能力版本不一致')
    progress('恢复：完整复验原CMake工作输入、生成目录、SDK及索引；不重新配置')
    with ScanFiles(descriptor,root,cfg) as view:view.assert_valid()
    write_json(folder/'reused-working-inputs.json',dict(format='ECRA_CMAKE_RETRY_INPUTS_V1',
        source_task=spec['source_task'],source_capture_plan_sha256=sha256(plan),
        config=str(original),config_sha256=sha256(original),compiler_view=descriptor,
        engine_digest=engine_digest(),proof='ORIGINAL_AND_COPIES_REVERIFIED_NO_CMAKE_RECONFIGURE'))
    return original,descriptor
