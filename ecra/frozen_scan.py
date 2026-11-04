"""Fixed logical Clang inputs and replay for explicit compilation databases.

The caller owns a complete pre-existing capture. Runtime view identities never
enter analysis configuration, cache keys or static report normalization.
"""
from pathlib import Path
from contextlib import contextmanager

from .working_compiler_view import ParentFiles, validate


def execution_workspace(root, analysis, compiler_view):
    """Reuse every formal path boundary; only the private dirty gate differs.

    A non-null view is subsequently fully verified before pin/base processing.
    Broker-owned GUI/CLI capture supplies this internal argument. CMake and
    unproved build modes remain blocked by the separate configuration policy.
    """
    from .workspace import formal_workspace
    if compiler_view is None:
        return formal_workspace(root, analysis)
    effective=dict(analysis,git_diff=dict(analysis.get('git_diff',{}),include_uncommitted=False))
    return formal_workspace(root, effective)


def check_mode(cfg, workspace, doctor_only):
    from .scan_persistence import is_canonical
    analysis = cfg['analysis']
    if workspace is None or not is_canonical(workspace.results_root):
        raise ValueError('冻结扫描验收必须使用显式独立原生工作区')
    diff=analysis['git_diff']
    if (doctor_only or (diff['enabled'] and (not diff.get('include_uncommitted') or diff.get('current_ref')!='HEAD')) or 'cmake' in analysis
            or analysis.get('auto_configure_cmake', False)
            or analysis.get('compile_database', 'auto') == 'auto'
            or not analysis.get('build_closure_only', True)):
        raise ValueError('冻结扫描内部验收仅支持显式编译数据库的完整/HEAD工作区比较；固定提交Diff/CMake/补充扫描尚未验收')
    out = Path(workspace.results_root)
    if (out/'scan.db').exists() or (out/'run.json').exists():
        raise ValueError('冻结扫描验收需要新的原生扫描目录；原有结果保留')


class ScanFiles(ParentFiles):
    """Verify original Git/index/files/namespace at every pipeline barrier."""
    def __init__(self, descriptor, root, cfg, *, review_config_path=None):
        self.review_config_path=review_config_path
        validate(descriptor, root, cfg, reverify_original=True,review_config_path=review_config_path)
        super().__init__(descriptor, root, cfg)

    def assert_valid(self):
        if self.connection is None:
            raise ValueError('冻结父进程文件视图已经关闭')
        validate(dict(file=self.identity['file'], sha256=self.identity['sha256']),
                 self.record['root'], self.config, reverify_original=True,review_config_path=self.review_config_path)


@contextmanager
def replay_files(capsule,root,cfg,*,config_path=None):
    identity=capsule.get('frozen_view')
    if identity is None:
        yield None
        return
    base={'file','sha256','original_final_reverification_required'}
    legacy=isinstance(identity,dict) and set(identity)==base|{'formal_dirty_enabled'} and identity['formal_dirty_enabled'] is False
    modern=(isinstance(identity,dict) and set(identity)==base|{'proof_scope'}
        and identity['proof_scope']=='COMPLETE_LOGICAL_CLANG_INPUTS_V1')
    if not (legacy or modern) or identity['original_final_reverification_required'] is not True:
        raise ValueError('冻结父进程输入证明字段不完整或版本未知；不能忽略视图身份读取实时源码')
    from .dirty_inputs import supported
    supported(cfg['analysis'])
    descriptor={key:identity[key] for key in ('file','sha256')}
    with ScanFiles(descriptor,root,cfg,review_config_path=config_path) as view:
        if view.identity!=identity:raise ValueError('冻结输入闭包与原视图证明不一致')
        yield view
        view.assert_valid()


def saved_reader(root,out,cfg,state):
    """Bind later Packet/source reads to the exact verified closure bytes."""
    from contextlib import nullcontext
    import hashlib
    import json
    expected=state.get('input_closure_sha256')
    if not expected:return nullcontext(None)
    raw=(Path(out)/'input_closure.json').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=expected:
        raise ValueError('扫描输入闭包在复验后变化，不能构造复核证据')
    return replay_files(json.loads(raw),root,cfg,config_path=Path(root)/state['config_file'])
